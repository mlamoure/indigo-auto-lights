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


def test_no_unlock_when_stale_cache_hides_presence(config):
    """Verify _unlock_after_grace reads fresh device state, not stale cache.

    Scenario: cache says presence=False, but device is actually on.
    The zone should NOT be unlocked because fresh read detects presence."""
    import indigo
    from tests.helpers import make_device

    cfg = config("scenario1_presence_dark_adjust_false.yaml")
    agent = AutoLightsAgent(cfg)
    zone = cfg.zones[0]
    zone.unlock_when_no_presence = True
    zone.locked = True
    zone._lock_start_time -= datetime.timedelta(seconds=LOCK_HOLD_GRACE_SECONDS + 1)

    # Set presence device to ON
    dev_id = zone.presence_dev_ids[0]
    make_device(dev_id, onState=True)

    # Seed stale cache entry that says no presence
    zone._runtime_cache["presence"] = False

    agent._unlock_after_grace(zone)
    # Zone should stay locked because fresh device read shows presence
    assert zone.locked
