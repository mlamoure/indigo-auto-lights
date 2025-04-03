import threading

from config_web_editor.app import run_flask_app
from auto_lights.auto_lights_config import AutoLightsConfig

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
			**kwargs: dict
	) -> None:
		"""
		The init method that is called when a plugin is first instantiated.

		:param plugin_id: the ID string of the plugin from Info.plist
		:param plugin_display_name: the name string of the plugin from Info.plist
		:param plugin_version: the version string from Info.plist
		:param plugin_prefs: an indigo.Dict containing the prefs for the plugin
		:param kwargs: passthrough for any other keyword args
		"""
		super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs, **kwargs)

		indigo.devices.subscribeToChanges()
		indigo.variables.subscribeToChanges()

		self.debug: bool = True
		self._agent = None

	def startup(self: indigo.PluginBase) -> None:
		"""
        Any logic needed at startup, but after __init__ is called.

        :return:
        """
		self.logger.debug("startup called")
		self.start_configuration_web_server()

		config = AutoLightsConfig("config_web_editor/config/auto_lights_conf.json")


	def shutdown(self: indigo.PluginBase) -> None:
		"""
        Any cleanup logic needed before the plugin is completely shut down.

        :return:
        """
		self.logger.debug("shutdown called")

	def deviceUpdated(self: indigo.PluginBase, orig_dev: indigo.Device, new_dev: indigo.Device) -> None:
		# call base implementation
		indigo.PluginBase.deviceUpdated(self, orig_dev, new_dev)

		# Convert the payload objects from indigo.Dict() objects to Python dict() objects.
		orig_dict = {}
		for (k, v) in orig_dev:
			orig_dict[k] = v

		new_dict = {}
		for (k, v) in new_dev:
			new_dict[k] = v

		# Create a dictionary that contains only those properties and attributes that have changed.
		diff = {k: new_dict[k] for k in orig_dict if k in new_dict and orig_dict[k] != new_dict[k]}

		# process the change
		self._agent.process_device_change(orig_dev, diff)

	def variableUpdated(self, orig_var: indigo.Variable, new_var: indigo.Variable) -> None:
		# call base implementation
		indigo.PluginBase.variableUpdated(self, new_var, new_var)

	def start_configuration_web_server(self: indigo.PluginBase):
		address = "0.0.0.0"
		port = 9000
		self.logger.info(f"Starting the configuration web server... listening on address {address} and port {port}")
		thread = threading.Thread(target=run_flask_app, args=(address, port), daemon=True)
		thread.start()


	def closedPrefsConfigUi(self: indigo.PluginBase, values_dict, user_cancelled):
		if not user_cancelled:
			pass
