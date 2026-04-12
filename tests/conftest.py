import sys
import types
import logging

# Stub indigo module for plugin imports before runtime
indigo_stub = types.SimpleNamespace()
class Devices(dict):
    def __iter__(self):
        return iter(self.values())

    def __missing__(self, key):
        # auto‐create a stub Device for unknown IDs
        dev = indigo_stub.Device(key)
        self[key] = dev
        return dev

indigo_stub.devices = Devices()
class Variables(dict):
    def __iter__(self):
        return iter(self.values())

    def __missing__(self, key):
        # auto‐create a stub Variable for unknown IDs
        var = indigo_stub.Variable(key)
        self[key] = var
        return var

indigo_stub.variables = Variables()
indigo_stub.kProtocol = types.SimpleNamespace(Plugin="Plugin")
def _create_device(*a, **k):
    dev_id = max(indigo_stub.devices.keys(), default=0) + 1
    dev = indigo_stub.Device(
        dev_id,
        name=k.get("name", ""),
        onState=True,
        brightness=0,
        sensorValue=0,
    )
    indigo_stub.devices[dev_id] = dev
    return dev

def _turn_on(dev_id, **_):
    dev = indigo_stub.devices[dev_id]
    dev.onState = True
    dev.onOffState = True
    dev.states["onState"] = True
    dev.states["onOffState"] = True
    if hasattr(dev, "brightness"):
        dev.brightness = 100
        dev.states["brightness"] = 100

def _turn_off(dev_id, **_):
    dev = indigo_stub.devices[dev_id]
    dev.onState = False
    dev.onOffState = False
    dev.states["onState"] = False
    dev.states["onOffState"] = False
    if hasattr(dev, "brightness"):
        dev.brightness = 0
        dev.states["brightness"] = 0

indigo_stub.device = types.SimpleNamespace(
    create=_create_device,
    turnOn=_turn_on,
    turnOff=_turn_off,
)
indigo_stub.variable = types.SimpleNamespace(
    create=lambda *a, **k: indigo_stub.variables.setdefault(
        max(indigo_stub.variables.keys(), default=0) + 1,
        types.SimpleNamespace(
            id=max(indigo_stub.variables.keys(), default=0) + 1,
            name=(a[0] if a else ""),
            value=(a[1] if len(a) > 1 else None),
        ),
    )
)

# stub Device and Variable classes to satisfy type annotations and helper imports
import datetime

class Device:
    def __init__(self, id, name="", onState=False, brightness=0, sensorValue=None):
        self.id = id
        self.name = name or f"Dev-{id}"
        self.onState = onState
        self.onOffState = onState
        self.brightness = brightness
        self.sensorValue = sensorValue if sensorValue is not None else brightness
        self.states = {
            "onState": self.onState,
            "onOffState": self.onOffState,
            "brightness": self.brightness,
        }
        self.pluginId = ""
        self.deviceTypeId = ""
        self.pluginProps = {}
        self.lastChanged = datetime.datetime.now()

    def __iter__(self):
        return iter(self.states.items())

    def replaceOnServer(self): pass
    def updateStatesOnServer(self, state_list): pass


class DimmerDevice(Device):
    pass


class RelayDevice(Device):
    pass


class _DummyHandler(logging.Handler):
    def __init__(self, baseFilename="/tmp/Logs/plugin.log"):
        super().__init__()
        self.baseFilename = baseFilename

    def emit(self, record):
        pass


class PluginBase:
    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs, **kwargs):
        self.pluginId = plugin_id
        self.pluginDisplayName = plugin_display_name
        self.pluginVersion = plugin_version
        self.pluginPrefs = plugin_prefs
        self.logger = logging.getLogger("Plugin")
        self.indigo_log_handler = _DummyHandler()
        self.plugin_file_handler = _DummyHandler()

    @staticmethod
    def deviceUpdated(self, orig_dev, new_dev):
        return None

    @staticmethod
    def variableUpdated(self, orig_var, new_var):
        return None

class Variable:
    def __init__(self, id, name="", value=None):
        self.id = id
        self.name = name
        self.value = value

indigo_stub.Device = Device
indigo_stub.DimmerDevice = DimmerDevice
indigo_stub.RelayDevice = RelayDevice
indigo_stub.Variable = Variable
indigo_stub.PluginBase = PluginBase

# Add Dict class for IWS response format (just a regular dict in tests)
class IndigoDict(dict):
    """Stub for indigo.Dict() - behaves exactly like dict in tests."""
    pass

indigo_stub.Dict = IndigoDict

sys.modules["indigo"] = indigo_stub

import pytest
import os
from collections import UserDict
# Make plugin code importable by pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "Auto Lights.indigoPlugin", "Contents", "Server Plugin")))

@pytest.fixture(autouse=True)
def fake_indigo():
    """
    Reset the stub indigo module before each test.
    """
    indigo_stub.devices.clear()
    indigo_stub.variables.clear()
    yield indigo_stub
