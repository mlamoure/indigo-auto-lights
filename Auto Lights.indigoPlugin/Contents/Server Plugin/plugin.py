import json
import logging
import os
import random
import shutil
import socket
import threading
from datetime import datetime

from werkzeug.serving import make_server

from auto_lights.auto_lights_agent import AutoLightsAgent
from auto_lights.auto_lights_config import AutoLightsConfig
from config_web_editor.tools.indigo_api_tools import get_indigo_api_url, indigo_api_call
from config_web_editor.web_config_app import init_flask_app, app as flask_app

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

        self.connection_indigo_api = None
        self._agent = None
        self._web_server_thread = None
        self._web_server = None

        # Set environment variables for Indigo API configuration.
        os.environ["INDIGO_API_URL"] = plugin_prefs.get(
            "indigo_api_url", "https://myreflector.indigodomo.net"
        )
        os.environ["INDIGO_API_KEY"] = plugin_prefs.get(
            "api_key", "xxxxx-xxxxx-xxxxx-xxxxx"
        )

        # Retrieve web server binding settings from plugin preferences.
        self._web_config_bind_ip = plugin_prefs.get("web_config_bind_ip", "127.0.0.1")
        self._web_config_bind_port = plugin_prefs.get("web_config_bind_port", "9000")
        self._disable_web_server = plugin_prefs.get("disable_web_server", False)
        self._log_non_events = bool(plugin_prefs.get("log_non_events", False))
        self._disable_ssl_validation = bool(
            plugin_prefs.get("disable_ssl_validation", False)
        )
        os.environ["INDIGO_API_DISABLE_SSL_VALIDATION"] = str(
            self._disable_ssl_validation
        )

        # Configure logging levels based on plugin preferences.
        self.log_level = int(plugin_prefs.get("log_level", logging.INFO))
        self.logger.debug(f"{self.log_level=}")
        self.indigo_log_handler.setLevel(self.log_level)
        self.plugin_file_handler.setLevel(logging.DEBUG)

        # Determine configuration file path based on plugin log file location.
        self._config_file_str = self.plugin_file_handler.baseFilename.replace(
            "Logs", "Preferences"
        ).replace("/plugin.log", "/config/auto_lights_conf.json")

    def test_connections(self) -> None:
        """
        Test connectivity to the Indigo API by fetching a random device.
        """

        # no need to test if the web server is disabled
        if self._disable_web_server:
            return

        try:
            random_device = random.choice(list(indigo.devices))
            device_id = random_device.id
            device_detail = indigo_api_call(
                f"{get_indigo_api_url()}/indigo.devices/{device_id}", "GET", None
            )
            if "error" not in device_detail:
                self.connection_indigo_api = True
            else:
                self.connection_indigo_api = False
        except Exception as e:
            self.logger.error("Indigo API connectivity test failed: %s", e)
            self.connection_indigo_api = False

    def startup(self: indigo.PluginBase) -> None:
        """
        Any logic needed at startup, but after __init__ is called.

        :return:
        """
        self.logger.debug("startup called")

        self.test_connections()

        # Subscribe to changes for devices and variables.
        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()

        # Start the configuration web server if not disabled.
        if not self._disable_web_server:
            self.start_configuration_web_server()
        # Initialize configuration and AutoLightsAgent.
        self._init_config_and_agent()
        self._agent.refresh_all_indigo_devices()
        self.logger.debug("Plugin startup complete")

    def shutdown(self: indigo.PluginBase) -> None:
        """
        Any cleanup logic needed before the plugin is completely shut down.

        :return:
        """
        self.logger.debug("shutdown called")
        if hasattr(self, "_agent") and self._agent is not None:
            self._agent.shutdown()
        self.stop_configuration_web_server()

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

    def start_configuration_web_server(self: indigo.PluginBase):
        if self._web_server_thread is not None:
            self.stop_configuration_web_server()
        if not getattr(self, "connection_indigo_api", False):
            self.logger.warning(
                "Cannot start web server because Indigo API connection failed."
            )
            return

        # Check if Indigo API configuration is not default
        if (
            os.environ.get("INDIGO_API_URL") != "https://myreflector.indigodomo.net"
            and os.environ.get("INDIGO_API_KEY") != "xxxxx-xxxxx-xxxxx-xxxxx"
        ):
            urls = []
            # Determine the appropriate URLs based on the bind IP.
            if self._web_config_bind_ip == "0.0.0.0":
                hostname = socket.gethostname()
                local_ip = socket.gethostbyname(hostname)
                urls.append(f"http://{hostname}:{self._web_config_bind_port}")
                urls.append(f"http://{local_ip}:{self._web_config_bind_port}")
            elif self._web_config_bind_ip == "127.0.0.1":
                urls.append(f"http://127.0.0.1:{self._web_config_bind_port}")
                urls.append(f"http://localhost:{self._web_config_bind_port}")
                self.logger.info(
                    "NOTE: This address will only work on the Indigo server directly.  See the plugin config to change this."
                )
            else:
                urls.append(
                    f"http://{self._web_config_bind_ip}:{self._web_config_bind_port}"
                )
            self.logger.info(
                f"Starting the configuration web server... Visit {' or '.join(urls)}"
            )
            # Start the configuration web server using a WSGI server in a daemon thread.
            # Initialize the Flask app (registers config_editor & caches).
            init_flask_app(
                self._config_file_str,
                self._web_config_bind_ip,
                self._web_config_bind_port,
            )
            # Notify plugin to reload config immediately after save from web UI
            flask_app.config["reload_config_cb"] = self._init_config_and_agent
            # Create a real WSGI server
            self._web_server = make_server(
                self._web_config_bind_ip,
                int(self._web_config_bind_port),
                flask_app,
                threaded=True,
            )
            self._web_server_thread = threading.Thread(
                target=self._web_server.serve_forever,
                name="AutoLightsWebUI",
                daemon=True,
            )
            self._web_server_thread.start()
        else:
            self.logger.info(
                "Skipping start of configuration web server due to default config values."
            )

    def stop_configuration_web_server(self: indigo.PluginBase):
        """
        Stops the configuration web server by calling server.shutdown()
        instead of an HTTP round-trip.
        """
        if self._web_server is None:
            self.logger.info("Configuration web server is not running.")
            return

        try:
            self.logger.info("Shutting down configuration web server...")
            self._web_server.shutdown()
            self._web_server_thread.join(timeout=3.0)
            if self._web_server_thread.is_alive():
                self.logger.warning("Web server thread did not exit cleanly.")

        except Exception as e:
            self.logger.error(f"Error stopping configuration web server: {e}")

        finally:
            self._web_server = None
            self._web_server_thread = None

    def closedPrefsConfigUi(self: indigo.PluginBase, values_dict, user_cancelled):
        """
        Called when the preferences configuration UI is closed.
        Updates environment variables, configuration, and logging levels.
        """
        if not user_cancelled:
            # Update environment variables based on user preferences.
            os.environ["INDIGO_API_URL"] = values_dict.get(
                "indigo_api_url", "https://myreflector.indigodomo.net"
            )
            os.environ["INDIGO_API_KEY"] = values_dict.get(
                "api_key", "xxxxx-xxxxx-xxxxx-xxxxx"
            )
            self._web_config_bind_ip = values_dict.get(
                "web_config_bind_ip", "127.0.0.1"
            )
            self._web_config_bind_port = values_dict.get("web_config_bind_port", "9000")

            self._disable_web_server = values_dict.get("disable_web_server")
            self._log_non_events = bool(values_dict.get("log_non_events", False))
            self._agent.config.log_non_events = self._log_non_events
            self._disable_ssl_validation = bool(
                values_dict.get("disable_ssl_validation", False)
            )
            os.environ["INDIGO_API_DISABLE_SSL_VALIDATION"] = str(
                self._disable_ssl_validation
            )

            # Update logging configuration.
            self.log_level = int(values_dict.get("log_level", logging.INFO))
            self.logger.debug(f"{self.log_level=}")
            self.indigo_log_handler.setLevel(self.log_level)
            self.plugin_file_handler.setLevel(self.log_level)

            self.test_connections()

            # Restart or stop the configuration web server based on new settings.
            if self._disable_web_server:
                self.stop_configuration_web_server()
            else:
                self.start_configuration_web_server()

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
        self._agent.process_all_zones()

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

    def deviceStartComm(self, dev):
        self.logger.debug(f"deviceStartComm called for device {dev.id} ('{dev.name}')")
        dev.stateListOrDisplayStateIdChanged()
        if self._agent is not None:
            self._agent.refresh_indigo_device(dev.id)
        self.logger.debug(f"deviceStartComm complete for device {dev.id} ('{dev.name}')")
