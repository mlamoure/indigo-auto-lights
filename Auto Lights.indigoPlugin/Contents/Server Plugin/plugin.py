import os
import shutil
import threading

import requests

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

        self.debug: bool = True
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

    def startup(self: indigo.PluginBase) -> None:
        """
        Any logic needed at startup, but after __init__ is called.

        :return:
        """
        self.logger.debug("startup called")

        indigo.devices.subscribeToChanges()
        indigo.variables.subscribeToChanges()

        confg_file_str = "config_web_editor/config/auto_lights_conf.json"
        confg_file_empty_str = "config_web_editor/config/auto_lights_empty_conf.json"
        if not os.path.exists(confg_file_str):
            shutil.copyfile(confg_file_empty_str, confg_file_str)

        if not self._disable_web_server:
            self.start_configuration_web_server()

        conf_path = os.path.abspath(confg_file_str)

        config = AutoLightsConfig(conf_path)
        self._agent = AutoLightsAgent(config)

        self._agent.process_all_zones()

    def shutdown(self: indigo.PluginBase) -> None:
        """
        Any cleanup logic needed before the plugin is completely shut down.

        :return:
        """
        self.logger.debug("shutdown called")

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
            self.stop_web_server_thread()

        if (
            os.environ.get("INDIGO_API_URL") != "https://myreflector.indigodomo.net"
            and os.environ.get("API_KEY") != "xxxxx-xxxxx-xxxxx-xxxxx"
        ):
            self.logger.info(
                f"Starting the configuration web server... Visit http://{self._web_config_bind_ip}:{self._web_config_bind_port}"
            )
            self._web_server_thread = threading.Thread(
                target=run_flask_app,
                args=(self._web_config_bind_ip, self._web_config_bind_port),
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
