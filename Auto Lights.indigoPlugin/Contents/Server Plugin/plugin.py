import logging
import os
import shutil
import socket
import threading

import requests
import json
from datetime import datetime

from auto_lights.auto_lights_agent import AutoLightsAgent
from auto_lights.auto_lights_config import AutoLightsConfig
from config_web_editor.web_config_app import run_flask_app

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
        self._web_server_thread = None

        os.environ["INDIGO_API_URL"] = plugin_prefs.get(
            "indigo_api_url", "https://myreflector.indigodomo.net"
        )
        os.environ["INDIGO_API_KEY"] = plugin_prefs.get(
            "api_key", "xxxxx-xxxxx-xxxxx-xxxxx"
        )
        self._web_config_bind_ip = plugin_prefs.get("web_config_bind_ip", "127.0.0.1")
        self._web_config_bind_port = plugin_prefs.get("web_config_bind_port", "9000")
        self._disable_web_server = plugin_prefs.get("disable_web_server", False)

        self.logLevel = int(plugin_prefs.get("log_level", logging.INFO))
        self.logger.debug(f"{self.logLevel=}")
        self.indigo_log_handler.setLevel(self.logLevel)
        self.plugin_file_handler.setLevel(self.logLevel)

        # self._config_file_str = "config_web_editor/config/auto_lights_conf.json"
        self._config_file_str = self.plugin_file_handler.baseFilename.replace(
            "Logs", "Preferences"
        ).replace("/plugin.log", "/config/auto_lights_conf.json")

    def startup(self: indigo.PluginBase) -> None:
        """
        Any logic needed at startup, but after __init__ is called.

        :return:
        """
        self.logger.debug("startup called")

        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()

        if not self._disable_web_server:
            self.start_configuration_web_server()
        self._init_config_and_agent()

    def shutdown(self: indigo.PluginBase) -> None:
        """
        Any cleanup logic needed before the plugin is completely shut down.

        :return:
        """
        self.logger.debug("shutdown called")

    def runConcurrentThread(self: indigo.PluginBase):
        try:
            while True:
                if os.path.exists(self._config_file_str):
                    current_mtime = os.path.getmtime(self._config_file_str)
                    if current_mtime != self._config_mtime:
                        self.logger.debug(
                            "Config file modified, reloading configuration."
                        )
                        self._init_config_and_agent()
                self.sleep(5)
        except self.StopThread:
            pass  # Optionally catch the StopThread exception and do any needed cleanup.

    def deviceUpdated(
        self: indigo.PluginBase, orig_dev: indigo.Device, new_dev: indigo.Device
    ) -> None:
        # call base implementation
        indigo.PluginBase.deviceUpdated(self, orig_dev, new_dev)

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

        # process the change
        self._agent.process_device_change(orig_dev, diff)

    def variableUpdated(
        self, orig_var: indigo.Variable, new_var: indigo.Variable
    ) -> None:
        # call base implementation
        indigo.PluginBase.variableUpdated(self, new_var, new_var)

        # process the change
        self._agent.process_variable_change(orig_var, new_var)

    def start_configuration_web_server(self: indigo.PluginBase):
        if self._web_server_thread is not None:
            self.stop_configuration_web_server()

        if (
            os.environ.get("INDIGO_API_URL") != "https://myreflector.indigodomo.net"
            and os.environ.get("API_KEY") != "xxxxx-xxxxx-xxxxx-xxxxx"
        ):
            urls = []
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
            self._web_server_thread = threading.Thread(
                target=run_flask_app,
                args=(
                    self._web_config_bind_ip,
                    self._web_config_bind_port,
                    True,
                    self._config_file_str,
                ),
                daemon=True,
            )
            self._web_server_thread.start()
        else:
            self.logger.info(
                "Skipping start of configuration web server due to default config values."
            )

    def stop_configuration_web_server(self: indigo.PluginBase):
        """
        Stops the configuration web server by calling its shutdown endpoint.
        """
        if self._web_server_thread is not None:
            try:
                shutdown_url = f"http://{self._web_config_bind_ip}:{self._web_config_bind_port}/shutdown"
                requests.get(shutdown_url)
                self.logger.info("Configuration web server shutdown initiated.")
            except Exception as e:
                self.logger.error(f"Error stopping configuration web server: {e}")
            self._web_server_thread = None
        else:
            self.logger.info("Configuration web server is not running.")

    def closedPrefsConfigUi(self: indigo.PluginBase, values_dict, user_cancelled):
        if not user_cancelled:
            os.environ["INDIGO_API_URL"] = values_dict.get(
                "indigo_api_url", "https://myreflector.indigodomo.net"
            )
            os.environ["API_KEY"] = values_dict.get(
                "api_key", "xxxxx-xxxxx-xxxxx-xxxxx"
            )
            self._web_config_bind_ip = values_dict.get(
                "web_config_bind_ip", "127.0.0.1"
            )
            self._web_config_bind_port = values_dict.get("web_config_bind_port", "9000")

            self._disable_web_server = values_dict.get("disable_web_server")

            if self._disable_web_server:
                self.stop_configuration_web_server()
            else:
                self.start_configuration_web_server()

            self.logLevel = int(values_dict.get("log_level", logging.INFO))
            self.logger.debug(f"{self.logLevel=}")
            self.indigo_log_handler.setLevel(self.logLevel)
            self.plugin_file_handler.setLevel(self.logLevel)

    def get_zone_list(
        self: indigo.PluginBase, filter="", values_dict=None, type_id="", target_id=0
    ):
        menu_items = []

        for zone in self._agent.get_zones():
            menu_items.append((zone.name, zone.name))

        return menu_items

    def _init_config_and_agent(self: indigo.PluginBase):
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
        if props_dict.get("incoming_request_method", "GET") == "POST":
            post_params = dict(props_dict["body_params"])
            var_name = post_params.get("var_name", None)
            if not var_name:
                context = {"error": "var_name must be provided"}
            else:
                newVar = indigo.variable.create(var_name, "default value")
                context = {"var_id": newVar.id}
            reply["status"] = 200
            reply["headers"] = indigo.Dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps(context)
            return reply
        try:
            template = self.templates.get_template("config.html")
            reply["status"] = 200
            reply["headers"] = indigo.Dict({"Content-Type": "text/html"})
            reply["content"] = template.render(context)
        except Exception as exc:
            # some error happened
            self.logger.error(f"some error occurred: {exc}")
            reply["status"] = 500
        return reply
