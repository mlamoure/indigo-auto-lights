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
    # Enable unlock-when-no-presence and lock the zone
    zone.unlock_when_no_presence = True
    zone.locked = True
    # Insert a dummy grace timer
    import threading
    agent._no_presence_timers[zone.name] = threading.Timer(0, lambda: None)
    # Create the presence device stub
    dev_id = zone.presence_dev_ids[0]
    make_device(dev_id, onState=False)
    return agent, zone, dev_id

def test_presence_return_cancels_unlock_timer(agent_and_zone):
    agent, zone, dev_id = agent_and_zone
    # Simulate presence return
    make_device(dev_id, onState=True)
    orig_dev = indigo.devices[dev_id]
    diff = {"onState": True}
    agent.process_device_change(orig_dev, diff)
    assert zone.name not in agent._no_presence_timers


def test_stale_cache_cleared_on_presence_device_change(agent_and_zone):
    """Verify that a stale presence=False cache entry is invalidated when
    a presence device changes, so the grace timer cancellation reads
    fresh device state."""
    agent, zone, dev_id = agent_and_zone
    # Seed a stale cache entry (presence=False even though device will be on)
    zone._runtime_cache["presence"] = False
    # Simulate presence return
    make_device(dev_id, onState=True)
    orig_dev = indigo.devices[dev_id]
    diff = {"onState": True}
    agent.process_device_change(orig_dev, diff)
    # Grace timer should have been cancelled because fresh read sees presence
    assert zone.name not in agent._no_presence_timers
