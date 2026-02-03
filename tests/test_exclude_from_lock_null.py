"""
Tests for defensive handling of exclude_from_lock_dev_ids when set to None.

This test ensures the fix for array fields set to null (rather than empty list)
does not cause crashes when using the 'in' operator on the property.
"""

import json
from pathlib import Path

import pytest

from auto_lights.auto_lights_config import AutoLightsConfig
from tests.helpers import load_yaml, make_device


@pytest.fixture
def cfg(tmp_path):
    """Create a minimal config for testing zone property behavior."""
    def _load():
        data = load_yaml(Path(__file__).parent / "configs" / "scenario1_presence_dark_adjust_false.yaml")
        config_json = {
            "plugin_config": data.get("plugin_config", {}),
            "lighting_periods": data.get("lighting_periods", []),
            "zones": data.get("zones", []),
        }
        conf_path = tmp_path / "conf.json"
        conf_path.write_text(json.dumps(config_json))
        cfg = AutoLightsConfig(str(conf_path))
        # Create dummy devices
        for zone in cfg.zones:
            for dev_id in zone.presence_dev_ids:
                make_device(dev_id, onState=True)
            for dev_id in zone.on_lights_dev_ids:
                make_device(dev_id, brightness=0)
        return cfg
    return _load


def test_exclude_from_lock_dev_ids_none_getter(cfg):
    """Test that getter returns empty list when internal value is None."""
    cfg_obj = cfg()
    zone = cfg_obj.zones[0]

    # Directly set internal attribute to None (simulating corrupted config)
    zone._exclude_from_lock_dev_ids = None

    # Getter should return empty list, not None
    result = zone.exclude_from_lock_dev_ids
    assert result == []
    assert isinstance(result, list)

    # Should not raise TypeError when using 'in' operator
    assert 123 not in zone.exclude_from_lock_dev_ids


def test_exclude_from_lock_dev_ids_none_setter(cfg):
    """Test that setter normalizes None to empty list."""
    cfg_obj = cfg()
    zone = cfg_obj.zones[0]

    # Set property to None
    zone.exclude_from_lock_dev_ids = None

    # Internal value should be empty list, not None
    assert zone._exclude_from_lock_dev_ids == []
    assert zone.exclude_from_lock_dev_ids == []


def test_exclude_from_lock_dev_ids_normal_operation(cfg):
    """Test that normal list values work correctly."""
    cfg_obj = cfg()
    zone = cfg_obj.zones[0]

    # Set to a normal list
    zone.exclude_from_lock_dev_ids = [1, 2, 3]

    assert zone.exclude_from_lock_dev_ids == [1, 2, 3]
    assert 1 in zone.exclude_from_lock_dev_ids
    assert 99 not in zone.exclude_from_lock_dev_ids


def test_exclude_from_lock_dev_ids_in_has_device(cfg):
    """Test that _has_device doesn't crash when exclude_from_lock_dev_ids is None."""
    cfg_obj = cfg()
    zone = cfg_obj.zones[0]

    # Directly set internal attribute to None (simulating corrupted config)
    zone._exclude_from_lock_dev_ids = None

    # _has_device uses 'in' operator on exclude_from_lock_dev_ids
    # This should not raise TypeError
    result = zone._has_device(123)
    assert result == ""  # Not found in any list


def test_exclude_from_lock_dev_ids_in_current_lights_status(cfg):
    """Test that current_lights_status doesn't crash when exclude_from_lock_dev_ids is None."""
    cfg_obj = cfg()
    zone = cfg_obj.zones[0]

    # Directly set internal attribute to None (simulating corrupted config)
    zone._exclude_from_lock_dev_ids = None

    # current_lights_status uses 'in' operator on exclude_from_lock_dev_ids
    # This should not raise TypeError
    result = zone.current_lights_status()
    assert isinstance(result, list)
