import json
from pathlib import Path

import pytest

import indigo
from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.auto_lights_agent import AutoLightsAgent
from tests.helpers import load_yaml, make_device

@pytest.fixture
def agent_and_zone(tmp_path):
    data = load_yaml(Path(__file__).parent / "configs" / "scenario1_presence_dark_adjust_false.yaml")
    config_json = {
        "plugin_config": data.get("plugin_config", {}),
        "lighting_periods": data.get("lighting_periods", []),
        "zones": data.get("zones", []),
    }
    conf_path = tmp_path / "conf.json"
    conf_path.write_text(json.dumps(config_json))
    cfg = AutoLightsConfig(str(conf_path))
    agent = AutoLightsAgent(cfg)
    zone = cfg.zones[0]
    # create the on-light device stub
    dev_id = zone.on_lights_dev_ids[0]
    make_device(dev_id, brightness=0)
    return agent, zone, dev_id

def test_process_device_change_creates_new_lock(agent_and_zone):
    agent, zone, dev_id = agent_and_zone
    # Initially unlocked
    assert not zone.locked
    # Simulate external brightness change
    orig_dev = indigo.devices[dev_id]
    diff = {"brightness": 50}
    processed = agent.process_device_change(orig_dev, diff)
    # Lock should be created
    assert zone.locked
    assert zone.name in agent._timers
