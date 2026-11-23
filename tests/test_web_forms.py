"""Web editor forms through WTForms: a browser-style save of the zone, lighting
period and plugin pages coerces device, variable and choice values (nested
form fields included), the saved values render as selected, and the select
fields validate their choices."""

import json
import os
import shutil

import pytest
from werkzeug.datastructures import MultiDict

from config_web_editor.config_editor import WebConfigEditor
from config_web_editor.iws_form_helpers import generate_form_class_from_schema
from config_web_editor.iws_web_handler import IWSWebHandler

BASE = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    "Auto Lights.indigoPlugin",
    "Contents",
    "Server Plugin",
)
CONFIG_DIR = os.path.join(BASE, "config_web_editor", "config")

DEVICES = [
    {"id": 10, "name": "Ceiling", "class": "indigo.DimmerDevice"},
    {"id": 11, "name": "Lamp", "class": "indigo.DimmerDevice"},
    {"id": 20, "name": "Outlet", "class": "indigo.RelayDevice"},
    {"id": 30, "name": "Motion", "class": "indigo.SensorDevice"},
    {"id": 31, "name": "Lux", "class": "indigo.SensorDevice"},
]
VARIABLES = [{"id": 500, "name": "min_lux"}, {"id": 501, "name": "house_mode"}]


@pytest.fixture
def web(tmp_path):
    conf = tmp_path / "auto_lights_conf.json"
    shutil.copy(os.path.join(CONFIG_DIR, "auto_lights_conf_empty.json"), conf)
    editor = WebConfigEditor(
        str(conf),
        os.path.join(CONFIG_DIR, "config_schema.json"),
        str(tmp_path / "backups"),
        str(tmp_path / "auto_backups"),
    )
    editor._indigo_devices_cache["data"] = list(DEVICES)
    editor._indigo_variables_cache["data"] = list(VARIABLES)
    handler = IWSWebHandler(editor, "com.vtmikel.autolights")

    def request(method, page, body=None):
        reply = handler.handle_request(method, {}, body or {}, {"page": page})
        assert reply["status"] == 200, (method, page, reply["status"])
        return reply["content"]

    def saved():
        return json.loads(conf.read_text())

    return request, saved, editor


def test_zone_save_coerces_nested_fields_and_renders_them_selected(web):
    request, saved, _ = web
    period_id = saved()["lighting_periods"][0]["id"]
    request("GET", "zone/new")
    # IWS hands a multi-value field over as a list, a single value as a string
    request(
        "POST",
        "zone/new",
        {
            "name": "Den",
            "lighting_period_ids": str(period_id),
            "device_settings-on_lights_dev_ids": ["10", "20"],
            "device_settings-off_lights_dev_ids": "11",
            "device_settings-presence_dev_ids": "30",
            "device_settings-luminance_dev_ids": "31",
            "minimum_luminance_settings-minimum_luminance_use_variable": "y",
            "minimum_luminance_settings-minimum_luminance_var_id": "500",
            "minimum_luminance_settings-adjust_brightness": "y",
            "behavior_settings-off_lights_behavior": "force off unless zone is locked",
            "behavior_settings-lock_duration": "15",
        },
    )
    zone = saved()["zones"][0]
    assert zone["name"] == "Den"
    assert zone["lighting_period_ids"] == [period_id]
    assert zone["device_settings"]["on_lights_dev_ids"] == [10, 20]
    assert zone["device_settings"]["off_lights_dev_ids"] == [11]
    assert zone["device_settings"]["presence_dev_ids"] == [30]
    assert zone["minimum_luminance_settings"]["minimum_luminance_var_id"] == 500
    assert zone["minimum_luminance_settings"]["minimum_luminance_use_variable"] is True
    assert (
        zone["behavior_settings"]["off_lights_behavior"]
        == "force off unless zone is locked"
    )
    assert zone["behavior_settings"]["lock_duration"] == 15

    html = request("GET", "zone/0")
    assert '<option value="20" selected>Outlet</option>' in html
    assert '<option value="31" selected>Lux</option>' in html
    assert '<option selected value="500">min_lux</option>' in html
    assert (
        '<option selected value="force off unless zone is locked">'
        "force off unless zone is locked</option>"
    ) in html


def test_lighting_period_save_coerces_choices_and_renders_them_selected(web):
    request, saved, _ = web
    request("GET", "lighting_period/new")
    request(
        "POST",
        "lighting_period/new",
        {
            "name": "Evening",
            "mode": "On and Off",
            "from_time_hour": "18",
            "from_time_minute": "30",
            "to_time_hour": "22",
            "to_time_minute": "0",
            "lock_duration": "20",
        },
    )
    period = saved()["lighting_periods"][-1]
    assert period["name"] == "Evening"
    assert (period["from_time_hour"], period["from_time_minute"]) == (18, 30)
    assert (period["to_time_hour"], period["to_time_minute"]) == (22, 0)
    assert period["lock_duration"] == 20

    html = request("GET", f"lighting_period/{period['id']}")
    assert '<option value="18" selected="selected"' in html
    assert '<option value="22" selected="selected"' in html


def test_plugin_config_save_renders_the_saved_values(web):
    request, saved, _ = web
    request("GET", "plugin_config")
    request(
        "POST",
        "plugin_config",
        {"default_lock_duration": "30", "default_lock_extension_duration": "5"},
    )
    cfg = saved()["plugin_config"]
    assert cfg["default_lock_duration"] == 30
    assert cfg["default_lock_extension_duration"] == 5
    html = request("GET", "plugin_config")
    assert 'name="default_lock_duration" type="number" value="30"' in html


def _zone_form(editor, formdata):
    schema = editor.config_schema["properties"]["zones"]["items"]
    form = generate_form_class_from_schema(schema)(formdata=MultiDict(formdata))
    form.device_settings.on_lights_dev_ids.choices = [
        (d["id"], d["name"]) for d in DEVICES[:3]
    ]
    form.minimum_luminance_settings.minimum_luminance_var_id.choices = [
        (-1, "None Selected")
    ] + [(v["id"], v["name"]) for v in VARIABLES]
    return form


def test_zone_select_fields_validate_their_choices(web):
    _, _, editor = web
    form = _zone_form(
        editor,
        [
            ("device_settings-on_lights_dev_ids", "10"),
            ("device_settings-on_lights_dev_ids", "20"),
            ("minimum_luminance_settings-minimum_luminance_var_id", "501"),
            (
                "behavior_settings-off_lights_behavior",
                "do not adjust unless no presence",
            ),
        ],
    )
    on_lights = form.device_settings.on_lights_dev_ids
    var_id = form.minimum_luminance_settings.minimum_luminance_var_id
    behavior = form.behavior_settings.off_lights_behavior
    assert on_lights.data == [10, 20]
    assert var_id.data == 501
    for field in (on_lights, var_id, behavior):
        assert field.validate(form), (field.name, field.errors)

    bad = _zone_form(
        editor,
        [
            ("device_settings-on_lights_dev_ids", "999"),
            ("minimum_luminance_settings-minimum_luminance_var_id", "999"),
            ("behavior_settings-off_lights_behavior", "sometimes"),
        ],
    )
    on_lights = bad.device_settings.on_lights_dev_ids
    for field in (
        on_lights,
        bad.minimum_luminance_settings.minimum_luminance_var_id,
        bad.behavior_settings.off_lights_behavior,
    ):
        assert not field.validate(bad), field.name
    assert "999" in on_lights.errors[0]

    not_a_number = _zone_form(editor, [("device_settings-on_lights_dev_ids", "abc")])
    assert not not_a_number.device_settings.on_lights_dev_ids.validate(not_a_number)
