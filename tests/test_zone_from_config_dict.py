"""
Regression tests for Zone.from_config_dict section independence.

advanced_settings, device_period_map, and global_behavior_variables_map are
top-level zone keys; they must load even when a zone dict omits the
behavior_settings section (previously their parsing was nested inside the
behavior_settings branch and they were silently dropped).
"""

import json

import pytest

from auto_lights.auto_lights_config import AutoLightsConfig

LIGHTING_PERIODS = [
    {
        "id": 1,
        "name": "All Day",
        "mode": "On and Off",
        "from_time_hour": 0,
        "from_time_minute": 0,
        "to_time_hour": 23,
        "to_time_minute": 45,
        "lock_duration": -1,
        "limit_brightness": -1,
    }
]


def make_zone(**overrides):
    zone = {
        "name": "Test Zone",
        "lighting_period_ids": [1],
        "device_settings": {
            "on_lights_dev_ids": [101],
            "off_lights_dev_ids": [],
            "luminance_dev_ids": [],
            "presence_dev_ids": [301],
        },
        "advanced_settings": {"exclude_from_lock_dev_ids": [102]},
        "device_period_map": {"101": {"1": False}},
        "global_behavior_variables_map": {"555": False},
    }
    zone.update(overrides)
    return zone


def load_config(tmp_path, zone):
    conf_path = tmp_path / "conf.json"
    conf_path.write_text(
        json.dumps(
            {
                "plugin_config": {},
                "zones": [zone],
                "lighting_periods": LIGHTING_PERIODS,
            }
        )
    )
    return AutoLightsConfig(str(conf_path))


def test_zone_without_behavior_settings_keeps_top_level_sections(tmp_path):
    cfg = load_config(tmp_path, make_zone())
    zone = cfg.zones[0]

    assert zone.exclude_from_lock_dev_ids == [102]
    assert zone.device_period_map == {"101": {"1": False}}
    assert zone.global_behavior_variables_map == {"555": False}


def test_zone_with_behavior_settings_still_loads_all_sections(tmp_path):
    zone_dict = make_zone(
        behavior_settings={
            "lock_duration": 9,
            "extend_lock_when_active": False,
        }
    )
    cfg = load_config(tmp_path, zone_dict)
    zone = cfg.zones[0]

    assert zone.lock_duration == 9
    assert zone.extend_lock_when_active is False
    assert zone.exclude_from_lock_dev_ids == [102]
    assert zone.device_period_map == {"101": {"1": False}}
    assert zone.global_behavior_variables_map == {"555": False}
