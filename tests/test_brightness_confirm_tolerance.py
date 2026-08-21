"""Tests for the ±1 brightness confirmation tolerance (issue #2).

Device plugins that carry level in a native non-percentage range scale a
commanded percentage out and back and truncate in both directions, so a
device commanded to 30% honestly reports 29%. Confirming on exact
equality suppressed healthy hardware for the life of the lighting period.
"""

import json
from pathlib import Path

import pytest

import indigo
from auto_lights import utils
from auto_lights.auto_lights_agent import AutoLightsAgent
from auto_lights.auto_lights_config import AutoLightsConfig
from tests.helpers import load_yaml, make_device


def zigbee_round_trip(percent: int) -> int:
    """Percentage as it comes back from zigbee2mqtt after a set.

    Mirrors the two truncations in the zigbee2mqtt Indigo plugin:
    plugin_actions.py:280 (send) and zigbeeHandler.py:1302 (receive).
    """
    level_255 = int((percent * 255) / 100)
    return int((level_255 / 255) * 100)


# --- the reported failure ---


@pytest.mark.parametrize(
    "target,reported",
    [(10, 9), (30, 29), (50, 49), (70, 69), (90, 89)],
)
def test_lossy_round_trip_confirms(target, reported):
    """The percentages that were suppressing live dimmers now confirm."""
    dev = make_device(801, brightness=reported)
    assert utils._check_confirm(dev, target, None) is True


def test_every_percentage_survives_the_zigbee_round_trip():
    """Property: no target may be unconfirmable after a zigbee round trip."""
    for target in range(0, 101):
        dev = make_device(802, brightness=zigbee_round_trip(target))
        assert (
            utils._check_confirm(dev, target, None) is True
        ), f"target {target} reported back as {zigbee_round_trip(target)}"


# --- what the tolerance must NOT hide ---


def test_off_target_stays_exact():
    """A light still faintly on must not satisfy a target of off."""
    dev = make_device(803, brightness=1)
    assert utils._check_confirm(dev, 0, None) is False


def test_full_target_stays_exact():
    dev = make_device(804, brightness=99)
    assert utils._check_confirm(dev, 100, None) is False


def test_stuck_device_still_fails():
    """A device that received the command but did nothing still fails."""
    dev = make_device(805, brightness=0)
    assert utils._check_confirm(dev, 30, None) is False


def test_two_points_off_still_fails():
    """The band is 1 — anything wider would start hiding real failures."""
    dev = make_device(806, brightness=28)
    assert utils._check_confirm(dev, 30, None) is False


def test_relay_is_unaffected():
    """Relays confirm on onState, with no notion of tolerance."""
    dev = make_device(807, device_cls="relay", onState=False, brightness=0)
    assert utils._check_confirm(dev, 100, True) is False
    assert utils._check_confirm(dev, 0, False) is True


# --- the recovery path must agree with the send path ---


@pytest.mark.parametrize("target", [0, 1, 10, 30, 50, 99, 100])
def test_is_device_at_target_agrees_with_check_confirm(target):
    """Auto-recovery gates on is_device_at_target(); if it disagreed with
    _check_confirm() a device could confirm on send yet never clear its
    failure count."""
    for reported in {0, target - 1, target, target + 1, 100}:
        if not 0 <= reported <= 100:
            continue
        dev = make_device(808, brightness=reported)
        assert utils.is_device_at_target(dev, target) == utils._check_confirm(
            dev, target, None
        ), f"target={target} reported={reported}"


# --- zone-level consequences ---


@pytest.fixture
def agent_and_zone(tmp_path):
    data = load_yaml(
        Path(__file__).parent / "configs" / "scenario1_presence_dark_adjust_false.yaml"
    )
    conf_path = tmp_path / "conf.json"
    conf_path.write_text(
        json.dumps(
            {
                "plugin_config": data.get("plugin_config", {}),
                "lighting_periods": data.get("lighting_periods", []),
                "zones": data.get("zones", []),
            }
        )
    )
    cfg = AutoLightsConfig(str(conf_path))
    agent = AutoLightsAgent(cfg)
    zone = cfg.zones[0]
    for dev_id_key in ["on_lights_dev_ids", "luminance_dev_ids", "presence_dev_ids"]:
        for dev_id in getattr(zone, dev_id_key, []):
            if dev_id not in indigo.devices:
                make_device(dev_id)
    return agent, zone


def test_no_phantom_change_from_a_lossy_dimmer(agent_and_zone):
    """A dimmer reporting 29 for a target of 30 is not an external change,
    so it can neither lock the zone nor be rewritten every evaluation."""
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]
    make_device(dev_id, brightness=29, onState=True)
    zone.target_brightness = [{"dev_id": dev_id, "brightness": 30}]

    assert zone.has_brightness_changes() is False


def test_zone_still_sees_a_genuinely_stuck_dimmer(agent_and_zone):
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]
    make_device(dev_id, brightness=0, onState=False)
    zone.target_brightness = [{"dev_id": dev_id, "brightness": 30}]

    assert zone.has_brightness_changes() is True
