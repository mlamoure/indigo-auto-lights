import json
import pytest
from config_web_editor.web_config_app import init_flask_app

@pytest.fixture
def client(tmp_path):
    # 1) create a minimal config.json on disk
    cfg = {
      "plugin_config": {},
      "lighting_periods": [
        {"id": 1, "name": "All Day", "mode": "On and Off",
         "from_time_hour":0, "from_time_minute":0,
         "to_time_hour":23, "to_time_minute":59}
      ],
      "zones": [
        {
          "name": "MyZone",
          "lighting_period_ids": [1],
          "device_settings": {
            "on_lights_dev_ids": [1001, 1002],
            "off_lights_dev_ids": [],
            "luminance_dev_ids": [],
            "presence_dev_ids": []
          },
          "minimum_luminance_settings": {"minimum_luminance":None,
            "minimum_luminance_use_variable":False,
            "minimum_luminance_var_id":None,
            "adjust_brightness":True},
          "behavior_settings": {
            "lock_duration":None,"extend_lock_when_active":False,
            "lock_extension_duration":None,
            "off_lights_behavior":"",
            "unlock_when_no_presence":False
          },
          "advanced_settings":{"exclude_from_lock_dev_ids":[]},
          # initial mapping: both devices included
          "device_period_map": {
            "1001":{"1":True},
            "1002":{"1":True}
          },
          "global_behavior_variables_map":{}
        }
      ]
    }
    config_file = tmp_path/"conf.json"
    config_file.write_text(json.dumps(cfg))
    # 2) spin up Flask pointing at that config
    app = init_flask_app(str(config_file), debug=False)
    app.testing = True
    # Pre-populate caches to avoid Indigo connection errors
    app.config["config_editor"]._indigo_devices_cache["data"] = [
        {"id": 1001, "name": "Dev-1001", "class": "indigo.DimmerDevice", "deviceTypeId": "D1"},
        {"id": 1002, "name": "Dev-1002", "class": "indigo.RelayDevice", "deviceTypeId": "R2"},
        {"id": 2000, "name": "OtherDev",  "class": "indigo.DimmerDevice", "deviceTypeId": "D3"}
    ]
    app.config["config_editor"]._indigo_variables_cache["data"] = []
    return app.test_client()

def test_zone_form_initial_render(client):
    resp = client.get("/zone/0")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # initial mapping should show both devices included
    assert '<select name="device_period_map-1001-1"><option value="include" selected>' in html
    assert '<select name="device_period_map-1002-1"><option value="include" selected>' in html

def test_zone_form_can_exclude_one_device(client, tmp_path):
    # 1) fetch the form
    resp = client.get("/zone/0")
    assert resp.status_code == 200

    # 2) build a POST dict.  We need *all* fields:
    data = {
      "name": "MyZone",
      "lighting_period_ids": "1",
      "device_settings-on_lights_dev_ids": ["1001","1002"],
      "device_settings-off_lights_dev_ids": [],
      "device_settings-luminance_dev_ids": [],
      "device_settings-presence_dev_ids": [],
      "minimum_luminance_settings-minimum_luminance": "",
      "minimum_luminance_settings-minimum_luminance_use_variable": "false",
      "minimum_luminance_settings-minimum_luminance_var_id": "",
      "minimum_luminance_settings-adjust_brightness": "y",
      "behavior_settings-lock_duration": "",
      "behavior_settings-extend_lock_when_active": "",
      "behavior_settings-lock_extension_duration": "",
      "behavior_settings-off_lights_behavior": "",
      "behavior_settings-unlock_when_no_presence": "",
      "advanced_settings-exclude_from_lock_dev_ids": [],
      "device_period_map-1001-1": "include",
      "device_period_map-1002-1": "exclude",
    }

    # 3) submit
    post = client.post("/zone/0", data=data, follow_redirects=True)
    assert post.status_code == 200

    # 4) re-load JSON on disk and verify
    saved = json.loads((tmp_path/"conf.json").read_text())
    mapping = saved["zones"][0]["device_period_map"]
    assert mapping["1001"]["1"] is True
    assert mapping["1002"]["1"] is False
