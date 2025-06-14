import pytest
from config_web_editor.web_config_app import DevicePeriodMapField

# Dummy devices and periods:
DEVICES = [{"id": 101, "name": "Lamp A"}, {"id": 102, "name": "Lamp B"}]
PERIODS = [{"id": 1, "name": "All Day"}, {"id": 2, "name": "Night"}]

def make_formdata(mapping):
    """
    Turn {dev_id: {period_id: include_bool}} 
    into a dict suitable for passing to Field.process().
    """
    data = {}
    for dev_id, periods in mapping.items():
        for per_id, inc in periods.items():
            key = f"device_period_map-{dev_id}-{per_id}"
            data[key] = "include" if inc else "exclude"
    return data

def test_process_initial_data_only_on_get():
    # Simulate GET: formdata=None, data=initial
    initial = {"101": {"1": False}}
    f = DevicePeriodMapField(devices=DEVICES, lighting_periods=PERIODS)
    f.process(formdata=None, data=initial)
    assert f.data == initial

def test_process_overwrites_with_posted_data():
    # Simulate POST: formdata has both entries
    posted_mapping = {
        "101": {"1": True,  "2": False},
        "102": {"1": False, "2": True},
    }
    formdata = make_formdata(posted_mapping)
    f = DevicePeriodMapField(devices=DEVICES, lighting_periods=PERIODS)
    f.process(formdata=formdata, data={"101": {"1": False}})
    # It must match exactly what we sent in
    assert f.data == {
      "101": {"1": True,  "2": False},
      "102": {"1": False, "2": True},
    }
