import json
import logging
import os
import random
import shutil
import socket
import threading
from datetime import datetime

# NOTE: Werkzeug server import disabled - migrated to IWS. Kept for rollback capability.
# from werkzeug.serving import make_server

from auto_lights.auto_lights_agent import AutoLightsAgent
from auto_lights.auto_lights_config import AutoLightsConfig
# NOTE: Flask imports disabled - migrated to IWS. Kept for rollback capability.
# from config_web_editor.web_config_app import init_flask_app, app as flask_app

try:
    import indigo
except ImportError:
    pass


class Plugin(indigo.PluginBase):

    def __init__(
        self: indigo.PluginBase,
        plugin_id: str,
        plugin_display_name: str,
        plugin_version: str,
        plugin_prefs: indigo.Dict,
        **kwargs: dict,
    ) -> None:
        """
        The init method that is called when a plugin is first instantiated.

        :param plugin_id: the ID string of the plugin from Info.plist
        :param plugin_display_name: the name string of the plugin from Info.plist
        :param plugin_version: the version string from Info.plist
        :param plugin_prefs: an indigo.Dict containing the prefs for the plugin
        :param kwargs: passthrough for any other keyword args
        """
        super().__init__(
            plugin_id, plugin_display_name, plugin_version, plugin_prefs, **kwargs
        )

        self._agent = None
        self._iws_web_handler = None  # IWS web handler for config interface (lazy init)
        self._log_non_events = bool(plugin_prefs.get("log_non_events", False))

        # Configure logging levels based on plugin preferences.
        self.log_level = int(plugin_prefs.get("log_level", logging.INFO))
        self.logger.debug(f"{self.log_level=}")
        self.indigo_log_handler.setLevel(self.log_level)
        self.plugin_file_handler.setLevel(logging.DEBUG)

        # Determine configuration file path based on plugin log file location.
        self._config_file_str = self.plugin_file_handler.baseFilename.replace(
            "Logs", "Preferences"
        ).replace("/plugin.log", "/config/auto_lights_conf.json")

    # Removed test_connections() - no longer needed with direct indigo object access

    def startup(self: indigo.PluginBase) -> None:
        """
        Any logic needed at startup, but after __init__ is called.

        :return:
        """
        self.logger.debug("startup called")

        # Subscribe to changes for devices and variables.
        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()

        # NOTE: Flask server disabled - migrated to IWS. Kept for rollback capability.
        # Start the configuration web server if not disabled.
        # if not self._disable_web_server:
        #     self.start_configuration_web_server()

        # NOTE: IWS web handler uses lazy initialization (created on first request)
        # This avoids __file__ not defined error at startup

        # Initialize configuration and AutoLightsAgent.
        self._init_config_and_agent()

        # Log IWS Web Configuration URL for user convenience
        indigo_host = "localhost"
        indigo_port = 8176  # Default Indigo web server port
        iws_url = f"http://{indigo_host}:{indigo_port}/message/{self.pluginId}/web_ui/"
        self.logger.info(f"🌐 Web Configuration Interface: {iws_url}")

        self.logger.debug("Plugin startup complete")

    def shutdown(self: indigo.PluginBase) -> None:
        """
        Any cleanup logic needed before the plugin is completely shut down.

        :return:
        """
        self.logger.debug("shutdown called")
        if hasattr(self, "_agent") and self._agent is not None:
            self._agent.shutdown()
        # NOTE: Flask web server cleanup removed - migrated to IWS

    def deviceUpdated(
        self: indigo.PluginBase, orig_dev: indigo.Device, new_dev: indigo.Device
    ) -> None:
        # call base implementation
        indigo.PluginBase.deviceUpdated(self, orig_dev, new_dev)
        # ignore our own plugin devices (zones & global config)
        if new_dev.pluginId == "com.vtmikel.autolights":
            return

        # Convert the payload objects from indigo.Dict() objects to Python dict() objects.
        orig_dict = {}
        for k, v in orig_dev:
            orig_dict[k] = v

        new_dict = {}
        for k, v in new_dev:
            new_dict[k] = v

        # Create a dictionary that contains only those properties and attributes that have changed.
        diff = {
            k: new_dict[k]
            for k in orig_dict
            if k in new_dict and orig_dict[k] != new_dict[k]
        }

        # process the change if the agent exists
        if self._agent is not None:
            processed = self._agent.process_device_change(orig_dev, diff)
            for z in processed:
                z.sync_indigo_device()

    def variableUpdated(
        self, orig_var: indigo.Variable, new_var: indigo.Variable
    ) -> None:
        # call base implementation
        indigo.PluginBase.variableUpdated(self, new_var, new_var)

        # process the change if the agent exists
        if self._agent is not None:
            self._agent.process_variable_change(orig_var, new_var)

    # NOTE: Flask web server methods removed - migrated to IWS
    # See git history (feature/migrate-to-iws branch) for rollback capability

    def closedPrefsConfigUi(self: indigo.PluginBase, values_dict, user_cancelled):
        """
        Called when the preferences configuration UI is closed.
        Updates logging configuration.
        """
        if not user_cancelled:
            # Update log_non_events setting
            self._log_non_events = bool(values_dict.get("log_non_events", False))
            self._agent.config.log_non_events = self._log_non_events

            # Update logging configuration
            self.log_level = int(values_dict.get("log_level", logging.INFO))
            self.logger.debug(f"{self.log_level=}")
            self.indigo_log_handler.setLevel(self.log_level)
            self.plugin_file_handler.setLevel(self.log_level)

    def get_zone_list(
        self: indigo.PluginBase, filter="", values_dict=None, type_id="", target_id=0
    ):
        menu_items = []

        for zone in self._agent.get_zones():
            menu_items.append((zone.name, zone.name))

        return menu_items

    def _init_config_and_agent(self: indigo.PluginBase):
        # Only log on reload, not initial startup
        reloading = hasattr(self, "_config_mtime")
        if reloading:
            self.logger.warning(
                "🔄 Configuration reloaded from web editor; all locks and zone state has been reset"
            )
        confg_file_empty_str = "config_web_editor/config/auto_lights_conf_empty.json"
        config_dir = os.path.dirname(self._config_file_str)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
        if not os.path.exists(self._config_file_str):
            shutil.copyfile(confg_file_empty_str, self._config_file_str)
        conf_path = os.path.abspath(self._config_file_str)
        self._config_path = conf_path
        self._config_mtime = os.path.getmtime(conf_path)
        config = AutoLightsConfig(conf_path)
        config.log_non_events = self._log_non_events
        self._agent = AutoLightsAgent(config)
        
        # Log info if plugin is globally disabled on startup
        if not config.enabled:
            config_dev_name = config.indigo_dev.name if config.indigo_dev else "Unknown"
            config_dev_state = config.indigo_dev.onState if config.indigo_dev else False
            self.logger.info(
                f"Auto Lights plugin is currently DISABLED "
                f"(config device '{config_dev_name}' onState={config_dev_state}). "
                f"Enable the device to activate automatic lighting control."
            )

        self._agent.process_all_zones()

    def _init_iws_web_handler(self: indigo.PluginBase):
        """
        Initialize the IWS web handler for the configuration interface.
        This replaces the separate Flask web server with IWS integration.

        Uses lazy initialization - called on first web request to avoid __file__ issues.
        """
        try:
            from config_web_editor.config_editor import WebConfigEditor
            from config_web_editor.iws_web_handler import IWSWebHandler

            # Set up WebConfigEditor
            # In Indigo plugins, os.getcwd() returns the Server Plugin directory
            current_dir = os.getcwd()
            schema_file = os.path.join(current_dir, "config_web_editor/config/config_schema.json")
            backup_dir = os.path.join(os.path.dirname(self._config_file_str), "backups")
            auto_backup_dir = os.path.join(os.path.dirname(self._config_file_str), "auto_backups")

            config_editor = WebConfigEditor(
                self._config_file_str,
                schema_file,
                backup_dir,
                auto_backup_dir,
                flask_app=None  # No Flask app for IWS mode
            )

            # Set up reload callback for when config is saved
            config_editor.reload_config_callback = self._init_config_and_agent

            # Initialize IWS web handler
            self._iws_web_handler = IWSWebHandler(
                config_editor=config_editor,
                plugin_id=self.pluginId
            )

            # Start cache refresher thread
            config_editor.start_cache_refresher()

            # Log IWS URL
            indigo_host = "localhost"  # Default to localhost
            indigo_port = 8176  # Default Indigo web server port
            iws_url = f"http://{indigo_host}:{indigo_port}/message/{self.pluginId}/web_ui/"
            self.logger.info(f"IWS Web Configuration Interface available at: {iws_url}")

        except Exception as e:
            self.logger.error(f"Failed to initialize IWS web handler: {e}")
            self.logger.exception(e)
            self._iws_web_handler = None

    def reset_zone_lock(
        self: indigo.PluginBase, action, dev, caller_waiting_for_result
    ):
        self._agent.reset_locks(action.props.get("zone_list"))

    def reset_all_locks(
        self: indigo.PluginBase, action, dev, caller_waiting_for_result
    ):
        self._agent.reset_locks()

    def print_locked_zones(
        self: indigo.PluginBase, action=None, dev=None, caller_waiting_for_result=None
    ):
        """
        Menu item callback to log all locked zones.
        """
        self._agent.print_locked_zones()

    def change_zones_enabled(self, action, dev=None, caller_waiting_for_result=None):
        """
        Handle enabling/disabling zones based on action.props.get("type").
        Types: 'enable_all', 'disable_all', 'enable', 'disable'
        """
        if self._agent is None:
            return
            
        action_type = action.pluginTypeId
        if action_type == "enable_all_zones":
            self._agent.enable_all_zones()
        elif action_type == "disable_all_zones":
            self._agent.disable_all_zones()
        elif action_type == "enable_zone":
            zone_name = action.props.get("zone_list")
            self._agent.enable_zone(zone_name)
        elif action_type == "disable_zone":
            zone_name = action.props.get("zone_list")
            self._agent.disable_zone(zone_name)

    def create_variable(self, action, dev=None, caller_waiting_for_result=None):
        """
        :param action: action.props contains all the information passed from the web server
        :param dev: unused
        :param caller_waiting_for_result: always True
        :return: a dict that contains the status, the Content-Type header, and the contents of the specified file.
        """
        self.logger.debug("Handling variable creation request")
        props_dict = dict(action.props)
        reply = indigo.Dict()
        context = {
            "date_string": str(datetime.now()),  # Used in the config.html template
            "prefs": self.pluginPrefs,
        }
        if props_dict.get("incoming_request_method") == "POST":
            post_params = json.loads(props_dict.get("request_body", "{}"))
            var_name = post_params.get("var_name", "").strip()
            # Validate input
            if not var_name:
                context = {"error": "var_name must be provided"}
                status = 400
            else:
                try:
                    newVar = indigo.variable.create(var_name, "true")
                    context = {"var_id": newVar.id}
                    status = 200
                except Exception as e:
                    # Log failure and return error message
                    self.logger.error(f"Failed to create variable '{var_name}': {e}")
                    context = {"error": str(e)}
                    status = 500
            reply["status"] = status
            reply["headers"] = indigo.Dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps(context)
        return reply

    def actionControlDevice(self, action, dev):
        """Handle global config and zone device toggles and dispatch processing."""

        if self._agent is None:
            return

        action_type = action.deviceAction

        # Ignore status requests
        if action_type == indigo.kDeviceAction.RequestStatus:
            return

        dev_type = dev.deviceTypeId
        # Only handle our plugin devices
        if dev_type not in ("auto_lights_config", "auto_lights_zone"):
            return

        # Determine desired on/off state
        if action_type == indigo.kDeviceAction.Toggle:
            desired_state = not dev.onOffState
        elif action_type in (indigo.kDeviceAction.TurnOn, indigo.kDeviceAction.TurnOff):
            desired_state = action_type == indigo.kDeviceAction.TurnOn
        else:
            self.logger.warning(
                f"Unrecognized device action {action_type} for {dev.name}"
            )
            return

        # Apply state change
        dev.updateStateOnServer("onOffState", desired_state)

        # Dispatch processing
        if dev_type == "auto_lights_config":
            self._agent.process_all_zones()
        else:
            zone_index = int(dev.pluginProps.get("zone_index", -1))
            zone = next(
                (z for z in self._agent.config.zones if z.zone_index == zone_index),
                None,
            )
            if zone:
                self._agent.process_zone(zone)
            else:
                self.logger.error(
                    f"actionControlDevice: Zone with index {zone_index} not found."
                )

    def _build_schema_state_definitions(self, dev, field_schemas):
        """
        Turn a dict of JSON‐schema entries into a list of
        getDeviceStateDictForXType(...) definitions.
        """
        out = []
        for key, schema in field_schemas.items():
            if not schema.get("x-sync_to_indigo"):
                continue
            title = schema.get("title", key)
            ftype = schema.get("type", "string")
            if ftype == "boolean":
                sd = self.getDeviceStateDictForBoolTrueFalseType(key, title, title)
            elif ftype in ("integer", "number"):
                sd = self.getDeviceStateDictForNumberType(key, title, title)
            else:
                sd = self.getDeviceStateDictForStringType(key, title, title)
            out.append(sd)
        return out

    def _build_zone_runtime_state_definitions(self, dev):
        """
        Turn a zone's runtime‐state entries into state‐definitions.
        """
        if self._agent is None:
            return []
            
        zone = next(
            (z for z in self._agent.config.zones if z.indigo_dev.id == dev.id), None
        )
        if not zone:
            return []

        out = []
        for entry in zone.zone_indigo_device_runtime_states:
            key = entry["key"]
            label = entry.get("label", key)
            rtype = entry.get("type", "string")
            if rtype in ("boolean", "bool"):
                sd = self.getDeviceStateDictForBoolTrueFalseType(key, label, label)
            elif rtype in ("integer", "number", "numeric"):
                sd = self.getDeviceStateDictForNumberType(key, label, label)
            else:
                sd = self.getDeviceStateDictForStringType(key, label, label)
            out.append(sd)
        return out

    def getDeviceStateList(self, dev):
        # Start with base state definitions
        states = super().getDeviceStateList(dev)

        # PLUGIN DEVICES ONLY – guard against calls before our agent/config are constructed
        if (
            dev.pluginId != "com.vtmikel.autolights"
            or getattr(self, "_agent", None) is None
        ):
            return states

        # ---- GLOBAL CONFIG DEVICE ----
        if dev.deviceTypeId == "auto_lights_config":
            if self._agent is not None:
                states.extend(
                    self._build_schema_state_definitions(
                        dev, self._agent.config.config_field_schemas
                    )
                )

        # ---- ZONE DEVICE ----
        elif dev.deviceTypeId == "auto_lights_zone":
            if self._agent is not None:
                # schema-driven fields
                states.extend(
                    self._build_schema_state_definitions(
                        dev, self._agent.config.zone_field_schemas
                    )
                )
                # plus runtime fields
                states.extend(self._build_zone_runtime_state_definitions(dev))

        return states

    ########################################
    # IWS Action Handlers
    ########################################

    def handle_web_ui(self, action, dev=None, callerWaitingForResult=True):
        """
        Handle web UI requests through Indigo IWS.

        Args:
            action: Indigo action containing request details in action.props
            dev: Optional device reference (unused)
            callerWaitingForResult: Whether caller is waiting for result

        Returns:
            Dict with status, headers, and content for IWS response
        """
        # Lazy initialization - create handler on first request
        if not self._iws_web_handler:
            self.logger.debug("Lazy initializing IWS web handler on first request")
            self._init_iws_web_handler()

        # If initialization failed, return error
        if not self._iws_web_handler:
            self.logger.error("IWS web handler failed to initialize")
            reply = indigo.Dict()
            reply["status"] = 503
            reply["headers"] = indigo.Dict({"Content-Type": "text/html; charset=utf-8"})
            reply["content"] = "<html><body><h1>503 Service Unavailable</h1><p>IWS web handler failed to initialize</p></body></html>"
            return reply

        # Extract request details from action.props
        method = (action.props.get("incoming_request_method") or "GET").upper()
        headers = dict(action.props.get("headers", {}))

        # IWS provides pre-parsed POST data in body_params (like url_query_args for GET)
        body_params = dict(action.props.get("body_params", {}))

        # For JSON POST requests, we need the raw request_body
        request_body = action.props.get("request_body", "")

        # IWS provides pre-parsed query parameters in url_query_args
        url_query_args = dict(action.props.get("url_query_args", {}))

        self.logger.debug(f"IWS Web UI: {method} request")
        self.logger.debug(f"URL query args from action.props: {url_query_args}")
        if method == "POST":
            self.logger.debug(f"POST body params from action.props: {body_params}")

        # Delegate to IWS web handler
        return self._iws_web_handler.handle_request(method, headers, body_params, url_query_args, request_body)

    # Static files are now automatically served from Resources/static/ by IWS
    # No custom handler needed - see Actions.xml and SDK example

    def deviceStartComm(self, dev):
        self.logger.debug(f"deviceStartComm called for device {dev.id} ('{dev.name}')")
        dev.stateListOrDisplayStateIdChanged()
        if self._agent is not None:
            self._agent.refresh_indigo_device(dev.id)
        self.logger.debug(f"deviceStartComm complete for device {dev.id} ('{dev.name}')")
