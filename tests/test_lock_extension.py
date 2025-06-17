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
    # Set expiration to the past
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
    past = datetime.datetime.now() - datetime.timedelta(seconds=1)
    zone.lock_expiration = past
    zone._runtime_cache.clear()
    # Simulate presence gone
    make_device(zone.presence_dev_ids[0], onState=False)
    zone._runtime_cache.pop("presence", None)
    zone._process_expired_lock()
    assert not zone.locked
