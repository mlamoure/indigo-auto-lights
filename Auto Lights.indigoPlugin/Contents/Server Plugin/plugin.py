import sys

import indigo
import datetime
import copy
import os
from json_adaptor import JSONAdaptor
import subprocess
import signal

class Plugin(indigo.PluginBase):
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)


	def startup(self):
		pass

	# called after runConcurrentThread() exits
	def shutdown(self):
		pass

	def runConcurrentThread(self):
		try:
			while True:
				pass

		except self.StopThread:
			pass

	def deviceUpdated(self, origDev, newDev):
		# call base implementation
		indigo.PluginBase.deviceUpdated(self, origDev, newDev)


	def start_configuration_web_server(self):
		self.logger.info ("starting the Grafana server...")
		runGrafanaCommand = os.getcwd().replace(" ", "\ ") + "/servers/grafana/grafana-server -homepath " + os.getcwd().replace(" ", "\ ") + "/servers/grafana/" + " -config " + self.GrafanaConfigFileLoc.replace(" ", "\ ")


	def stop_configuration_web_server(self):
		self.GrafanaServerPID = None

		p = subprocess.Popen(['ps', '-A'], stdout=subprocess.PIPE)
		out, err = p.communicate()
		
		for line in out.splitlines():
			if b'grafana' in line:
				pid = int(line.split(None, 1)[0])
				os.kill(pid, signal.SIGKILL)		


	def closedPrefsConfigUi(self, valuesDict, userCancelled):
		if not userCancelled:
			pass
