import sys
import types
import pytest

@pytest.fixture(autouse=True)
def fake_indigo():
    """
    Inject a dummy `indigo` module so imports in our plugin code never fail
    and all code paths can run headless.
    """
    fake = types.SimpleNamespace()
    # containers
    fake.devices = {}
    fake.variables = {}

    # Protocol enum
    fake.kProtocol = types.SimpleNamespace(Plugin="Plugin")

    # Minimal Device/Variable classes
    class DummyDevice:
        def __init__(self, id, name="", onState=False, brightness=0, sensorValue=None):
            self.id = id
            self.name = name or f"Dev-{id}"
            self.onState = onState
            self.onOffState = onState
            self.brightness = brightness
            self.sensorValue = brightness if sensorValue is None else sensorValue
            self.states = {"onState": self.onState, "brightness": self.brightness}
            self.pluginId = ""
            self.deviceTypeId = ""
            self.pluginProps = {}
        def replaceOnServer(self): pass
        def updateStatesOnServer(self, state_list): pass

    class DummyVariable:
        def __init__(self, id, name, value):
            self.id = id
            self.name = name
            self.value = value
        def getValue(self, t):
            return t(self.value)

    # assign classes
    fake.Device = fake.DimmerDevice = fake.RelayDevice = DummyDevice

    # device namespace
    def _create(protocol, name, address, deviceTypeId, props):
        new_id = max(fake.devices.keys(), default=0) + 1
        d = DummyDevice(new_id, name=name, onState=True)
        fake.devices[new_id] = d
        return d

    fake.device = types.SimpleNamespace(
        create=_create,
        turnOn=lambda dev_id, **kw: setattr(fake.devices[dev_id], "onState", True),
        turnOff=lambda dev_id, **kw: setattr(fake.devices[dev_id], "onState", False),
    )

    # variable namespace
    def _var_create(name, init_val):
        new_id = max(fake.variables.keys(), default=0) + 1
        v = DummyVariable(new_id, name, init_val)
        fake.variables[new_id] = v
        return v

    fake.variable = types.SimpleNamespace(create=_var_create)

    # no-op subscriptions
    fake.devices.subscribeToChanges = lambda *a, **k: None
    fake.variables.subscribeToChanges = lambda *a, **k: None

    # inject
    sys.modules["indigo"] = fake
    yield fake
    del sys.modules["indigo"]
