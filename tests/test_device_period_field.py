import pytest
from wtforms import Form
from config_web_editor.iws_form_helpers import DevicePeriodMapField

# Dummy devices and periods:
DEVICES = [{"id": 101, "name": "Lamp A"}, {"id": 102, "name": "Lamp B"}]
PERIODS = [{"id": 1, "name": "All Day"}, {"id": 2, "name": "Night"}]

class DummyForm(Form):
    device_period_map = DevicePeriodMapField(label="Map", devices=DEVICES, lighting_periods=PERIODS)

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
    form = DummyForm()
    f = form._fields['device_period_map']
    f.process(formdata=None, data=initial)
    assert f.data == initial

def test_process_overwrites_with_posted_data():
    # Simulate POST: formdata has both entries
    posted_mapping = {
        "101": {"1": True,  "2": False},
        "102": {"1": False, "2": True},
    }
    formdata = make_formdata(posted_mapping)
    form = DummyForm()
    f = form._fields['device_period_map']
    f.process(formdata=formdata, data={"101": {"1": False}})
    # It must match exactly what we sent in
    assert f.data == {
      "101": {"1": True,  "2": False},
      "102": {"1": False, "2": True},
    }


def test_process_accepts_explicit_brightness():
    # A cell may post a brightness level instead of include/exclude
    formdata = {
        "device_period_map-101-1": "10",
        "device_period_map-101-2": "exclude",
        "device_period_map-102-1": "100",
        "device_period_map-102-2": "include",
    }
    form = DummyForm()
    f = form._fields['device_period_map']
    f.process(formdata=formdata, data={})
    assert f.data == {
        "101": {"1": 10, "2": False},
        "102": {"1": 100, "2": True},
    }
    # Levels must be ints, not strings, so the zone can compare them numerically
    assert isinstance(f.data["101"]["1"], int)


@pytest.mark.parametrize("bad_value", ["0", "101", "-5", "", "banana", "50.5"])
def test_process_rejects_invalid_brightness(bad_value):
    # Anything outside 1-100 falls back to plain inclusion rather than being
    # written into the config
    formdata = {"device_period_map-101-1": bad_value}
    form = DummyForm()
    f = form._fields['device_period_map']
    f.process(formdata=formdata, data={})
    assert f.data == {"101": {"1": True}}


def test_widget_marks_saved_brightness_as_selected():
    form = DummyForm()
    f = form._fields['device_period_map']
    f.process(formdata=None, data={"101": {"1": 25}, "102": {"1": False}})
    html = str(f.widget(f))
    assert '<option value="25" selected>25%</option>' in html
    assert '<option value="exclude" selected>Exclude from Period</option>' in html


def test_widget_renders_off_ladder_value():
    # A hand-edited config may hold a level the preset dropdown does not offer;
    # it still has to render as the selected option or saving would lose it
    form = DummyForm()
    f = form._fields['device_period_map']
    f.process(formdata=None, data={"101": {"1": 37}})
    html = str(f.widget(f))
    assert '<option value="37" selected>37%</option>' in html
