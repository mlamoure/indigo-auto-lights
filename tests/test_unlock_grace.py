# tests for presence-based unlock grace timer

import datetime
import json
from pathlib import Path

import pytest

from auto_lights.auto_lights_agent import AutoLightsAgent
from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.zone import LOCK_HOLD_GRACE_SECONDS
from tests.helpers import load_yaml, make_device

@pytest.fixture
def config(tmp_path):
    def _load(scenario_file):
        data = load_yaml(Path(__file__).parent / "configs" / scenario_file)
        config_json = {
            "plugin_config": data.get("plugin_config", {}),
            "zones": data.get("zones", []),
            "lighting_periods": data.get("lighting_periods", []),
        }
        conf_path = tmp_path / "conf.json"
        conf_path.write_text(json.dumps(config_json))
        cfg = AutoLightsConfig(str(conf_path))
        # create dummy presence devices for all zones
        import indigo
        for zone in cfg.zones:
            for dev_id in zone.presence_dev_ids:
                make_device(dev_id, onState=False)
        return cfg
    return _load

def test_unlock_after_grace_expired(config):
    cfg = config("scenario1_presence_dark_adjust_false.yaml")
    agent = AutoLightsAgent(cfg)
    zone = cfg.zones[0]
    zone.unlock_when_no_presence = True
    zone.locked = True
    # simulate time elapsed beyond grace
    zone._lock_start_time -= datetime.timedelta(seconds=LOCK_HOLD_GRACE_SECONDS + 1)
    agent._unlock_after_grace(zone)
    assert not zone.locked

def test_no_unlock_before_grace(config):
    cfg = config("scenario1_presence_dark_adjust_false.yaml")
    agent = AutoLightsAgent(cfg)
    zone = cfg.zones[0]
    zone.unlock_when_no_presence = True
    zone.locked = True
    # simulate time within grace
    zone._lock_start_time -= datetime.timedelta(seconds=LOCK_HOLD_GRACE_SECONDS - 1)
    agent._unlock_after_grace(zone)
    assert zone.locked
