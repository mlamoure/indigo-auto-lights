import indigo

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

	def startup(self: indigo.PluginBase) -> None:
		"""
        Any logic needed at startup, but after __init__ is called.

        :return:
        """
		self.logger.debug("startup called")

	def shutdown(self: indigo.PluginBase) -> None:
		"""
        Any cleanup logic needed before the plugin is completely shut down.

        :return:
        """
		self.logger.debug("shutdown called")

	def deviceUpdated(self: indigo.PluginBase, orig_dev: indigo.Device, new_dev: indigo.Device) -> None:
		indigo.server.log(f"Changed: {orig_dev.name}")
		# call base implementation
		indigo.PluginBase.deviceUpdated(self, orig_dev, new_dev)



	def start_configuration_web_server(self: indigo.PluginBase):
		self.logger.info ("starting the web server...")


	def closedPrefsConfigUi(self: indigo.PluginBase, values_dict, user_cancelled):
		if not user_cancelled:
			pass
