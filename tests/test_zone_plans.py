import json
import datetime
import pytest
from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.auto_lights_agent import AutoLightsAgent
from tests.helpers import make_device, load_yaml

# Freeze "now" to a constant to make lighting periods deterministic
class FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2020, 1, 1, 12, 0, 0)

@pytest.fixture(autouse=True)
def freeze_datetime(monkeypatch):
    import auto_lights.lighting_period as lp_mod
    import auto_lights.zone as zone_mod
    monkeypatch.setattr(lp_mod.datetime, "datetime", FixedDateTime)
    monkeypatch.setattr(zone_mod.datetime, "datetime", FixedDateTime)

@pytest.fixture
def load_scenario(tmp_path):
    def _load(scenario_file):
        data = load_yaml(scenario_file)
        config_json = {
            "plugin_config": data.get("plugin_config", {}),
            "zones": data.get("zones", []),
            "lighting_periods": data.get("lighting_periods", []),
        }
        conf_path = tmp_path / "conf.json"
        conf_path.write_text(json.dumps(config_json))
        cfg = AutoLightsConfig(str(conf_path))
        agent = AutoLightsAgent(cfg)
        cfg.agent = agent
        for dev_id, st in data.get("device_states", {}).items():
            make_device(int(dev_id), **st)
        return data, cfg
    return _load

SCENARIOS = [
    "scenario1_presence_dark_adjust_false.yaml",
    "scenario2_presence_dark_adjust_true.yaml",
    "scenario3_presence_bright.yaml",
    "scenario4_no_presence.yaml",
    "scenario5_off_only_mode.yaml",
    "scenario7_force_off_behavior.yaml",
    "scenario8_device_exclusion.yaml",
    "scenario9_limit_brightness.yaml",
    "scenario10_global_off.yaml",
    "scenario11_variable_threshold.yaml",
]

@pytest.mark.parametrize("fname", SCENARIOS)
def test_zone_plan(load_scenario, fname):
    data, cfg = load_scenario(f"tests/configs/{fname}")
    zone = cfg.zones[0]
    plan = zone.calculate_target_brightness()
    exp = data["expected"]
    assert plan.new_targets == exp["new_targets"]
    assert plan.exclusions == exp["exclusions"]
    assert plan.device_changes == exp["device_changes"]

def test_locked_zone(load_scenario):
    # Scenario: locked zone should be skipped by agent
    data, cfg = load_scenario("tests/configs/scenario6_locked_zone.yaml")
    zone = cfg.zones[0]
    # lock the zone
    zone.locked = True
    result = cfg.agent.process_zone(zone)
    assert result is False
