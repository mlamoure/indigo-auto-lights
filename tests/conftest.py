import sys
import types

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
indigo_stub.device = types.SimpleNamespace(
    create=lambda *a, **k: indigo_stub.devices.setdefault(
        max(indigo_stub.devices.keys(), default=0) + 1,
        indigo_stub.Device(
            max(indigo_stub.devices.keys(), default=0) + 1,
            name=k.get("name", ""),
            onState=True,
            brightness=0,
            sensorValue=0,
        ),
    ),
    turnOn=lambda dev_id, **_: setattr(indigo_stub.devices[dev_id], "onState", True),
    turnOff=lambda dev_id, **_: setattr(indigo_stub.devices[dev_id], "onState", False),
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

    def replaceOnServer(self): pass
    def updateStatesOnServer(self, state_list): pass

class Variable:
    def __init__(self, id, name="", value=None):
        self.id = id
        self.name = name
        self.value = value

indigo_stub.Device = Device
indigo_stub.DimmerDevice = Device
indigo_stub.RelayDevice = Device
indigo_stub.Variable = Variable

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
