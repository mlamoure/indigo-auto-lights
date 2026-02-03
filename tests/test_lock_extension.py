import datetime
import json
from pathlib import Path

import pytest

from auto_lights.auto_lights_config import AutoLightsConfig
from tests.helpers import load_yaml, make_device

@pytest.fixture
def cfg(tmp_path):
    def _load(scenario_file):
        data = load_yaml(Path(__file__).parent / "configs" / scenario_file)
        config_json = {
            "plugin_config": data.get("plugin_config", {}),
            "lighting_periods": data.get("lighting_periods", []),
            "zones": data.get("zones", []),
        }
        conf_path = tmp_path / "conf.json"
        conf_path.write_text(json.dumps(config_json))
        cfg = AutoLightsConfig(str(conf_path))
        import indigo
        # create dummy presence devices reporting presence
        for zone in cfg.zones:
            for dev_id in zone.presence_dev_ids:
                make_device(dev_id, onState=True)
        return cfg
    return _load


def test_process_expired_lock_extends_when_presence_active(cfg):
    cfg_obj = cfg("scenario1_presence_dark_adjust_false.yaml")
    zone = cfg_obj.zones[0]
    zone.extend_lock_when_active = True
    zone.lock_extension_duration = 5
    # Set expiration to the past so the extension logic triggers
    past = datetime.datetime.now() - datetime.timedelta(seconds=1)
    zone.lock_expiration = past
    zone._runtime_cache.clear()
    # Ensure presence still detected
    make_device(zone.presence_dev_ids[0], onState=True)
    zone._process_expired_lock()
    assert zone.lock_expiration > datetime.datetime.now()
    assert zone.locked

def test_process_expired_lock_unblocks_when_presence_drops(cfg):
    cfg_obj = cfg("scenario1_presence_dark_adjust_false.yaml")
    zone = cfg_obj.zones[0]
    zone.extend_lock_when_active = True
    zone.lock_extension_duration = 5
    # Put zone in locked state with future expiration, then expire it
    zone.lock_expiration = datetime.datetime.now() + datetime.timedelta(minutes=5)
    past = datetime.datetime.now() - datetime.timedelta(seconds=1)
    zone.lock_expiration = past
    zone._runtime_cache.clear()
    # Simulate presence gone
    make_device(zone.presence_dev_ids[0], onState=False)
    zone._process_expired_lock()
    assert not zone.locked

def test_process_expired_lock_clears_presence_cache(cfg):
    """Verify stale presence cache is cleared before the presence check."""
    cfg_obj = cfg("scenario1_presence_dark_adjust_false.yaml")
    zone = cfg_obj.zones[0]
    zone.extend_lock_when_active = True
    zone.lock_extension_duration = 5
    # Seed a stale cache entry
    zone._runtime_cache["presence"] = True
    # Turn presence OFF at the device level
    make_device(zone.presence_dev_ids[0], onState=False)
    zone._process_expired_lock()
    # With cache cleared, fresh device read should see no presence → unlock
    assert not zone.locked

def test_double_extension_with_presence(cfg):
    """Calling _process_expired_lock twice with presence active extends both times."""
    cfg_obj = cfg("scenario1_presence_dark_adjust_false.yaml")
    zone = cfg_obj.zones[0]
    zone.extend_lock_when_active = True
    zone.lock_extension_duration = 5
    zone._runtime_cache.clear()
    make_device(zone.presence_dev_ids[0], onState=True)

    # First extension
    zone._process_expired_lock()
    first_expiration = zone.lock_expiration
    assert zone.locked

    # Clear cache to simulate time passing, then extend again
    zone._runtime_cache.clear()
    zone._process_expired_lock()
    assert zone.lock_expiration >= first_expiration
    assert zone.locked

def test_no_extension_when_zone_disabled(cfg):
    """Disabled zone must not extend lock even with active presence."""
    cfg_obj = cfg("scenario1_presence_dark_adjust_false.yaml")
    zone = cfg_obj.zones[0]
    zone.enabled = False
    zone.extend_lock_when_active = True
    zone.lock_extension_duration = 5
    zone._runtime_cache.clear()
    make_device(zone.presence_dev_ids[0], onState=True)
    zone._process_expired_lock()
    assert not zone.locked

def test_no_extension_when_presence_drops(cfg):
    """Stale cache says presence=True but device is off → lock must expire."""
    cfg_obj = cfg("scenario1_presence_dark_adjust_false.yaml")
    zone = cfg_obj.zones[0]
    zone.extend_lock_when_active = True
    zone.lock_extension_duration = 5
    zone.lock_expiration = datetime.datetime.now() + datetime.timedelta(minutes=5)
    # Seed stale cache as True
    zone._runtime_cache["presence"] = True
    # But device is actually off
    make_device(zone.presence_dev_ids[0], onState=False)
    zone._process_expired_lock()
    # Cache should have been cleared, fresh read sees no presence → unlocked
    assert not zone.locked
