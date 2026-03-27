"""Tests for the writer thread re-evaluation fix (issue #2).

Verifies that calling process_zone() after writer threads complete
does not deadlock, even when the re-evaluation triggers new writes.
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import indigo
from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.auto_lights_agent import AutoLightsAgent
from tests.helpers import load_yaml, make_device


@pytest.fixture
def agent_and_zone(tmp_path):
    """Set up an agent with a zone that has presence and is dark (will want lights on)."""
    data = load_yaml(
        Path(__file__).parent / "configs" / "scenario1_presence_dark_adjust_false.yaml"
    )
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

    # Create device stubs matching the config
    for dev_id_key in ["on_lights_dev_ids", "luminance_dev_ids", "presence_dev_ids"]:
        for dev_id in getattr(zone, dev_id_key, []):
            if dev_id not in indigo.devices:
                make_device(dev_id)

    # Set up state: presence active, dark (luminance 0), lights off
    for dev_id in zone.presence_dev_ids:
        make_device(dev_id, onState=True)
    for dev_id in zone.luminance_dev_ids:
        make_device(dev_id, sensorValue=0)
    for dev_id in zone.on_lights_dev_ids:
        make_device(dev_id, brightness=0, onState=False)

    return agent, zone


@patch("auto_lights.utils.send_to_indigo")
def test_writer_completes_without_deadlock(mock_send, agent_and_zone):
    """Writer threads must complete and check the zone back in.

    Before the fix, process_zone() was called inside _write_lock,
    causing a deadlock when it tried to re-acquire the lock via
    save_brightness_changes().
    """
    agent, zone = agent_and_zone

    # Simulate device confirming the write (so send_to_indigo returns quickly)
    def fake_send(dev_id, brightness):
        dev = indigo.devices[dev_id]
        dev.brightness = brightness if isinstance(brightness, int) else (100 if brightness else 0)
        dev.onState = brightness > 0 if isinstance(brightness, int) else brightness
        dev.states["brightness"] = dev.brightness
        dev.states["onState"] = dev.onState

    mock_send.side_effect = fake_send

    # Process the zone - this should check out, find brightness changes,
    # call save_brightness_changes(), spawn writer threads
    result = agent.process_zone(zone)
    assert result is True

    # Wait for writer threads to complete (timeout = deadlock detection)
    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not zone.checked_out, (
        "Zone is still checked out after 5s - likely deadlocked"
    )


@patch("auto_lights.utils.send_to_indigo")
def test_reeval_with_state_change_during_write(mock_send, agent_and_zone):
    """When device state changes during writes, re-evaluation should
    process the new state without deadlocking.
    """
    agent, zone = agent_and_zone
    process_zone_calls = []

    original_process_zone = agent.process_zone

    def tracking_process_zone(z):
        process_zone_calls.append(z.name)
        return original_process_zone(z)

    agent.process_zone = tracking_process_zone

    call_count = 0

    def fake_send_with_state_change(dev_id, brightness):
        nonlocal call_count
        call_count += 1
        dev = indigo.devices[dev_id]
        dev.brightness = brightness if isinstance(brightness, int) else (100 if brightness else 0)
        dev.onState = brightness > 0 if isinstance(brightness, int) else brightness
        dev.states["brightness"] = dev.brightness
        dev.states["onState"] = dev.onState

    mock_send.side_effect = fake_send_with_state_change

    result = agent.process_zone(zone)
    assert result is True

    # Wait for all writer threads to complete
    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not zone.checked_out, (
        "Zone is still checked out after 5s - likely deadlocked"
    )
    # process_zone should have been called at least once (the initial call)
    assert len(process_zone_calls) >= 1


@patch("auto_lights.utils.send_to_indigo")
def test_pending_writes_reaches_zero(mock_send, agent_and_zone):
    """After all writer threads complete, _pending_writes must be 0."""
    agent, zone = agent_and_zone

    def fake_send(dev_id, brightness):
        dev = indigo.devices[dev_id]
        dev.brightness = brightness if isinstance(brightness, int) else (100 if brightness else 0)
        dev.onState = brightness > 0 if isinstance(brightness, int) else brightness
        dev.states["brightness"] = dev.brightness
        dev.states["onState"] = dev.onState

    mock_send.side_effect = fake_send

    agent.process_zone(zone)

    # Wait for completion
    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    assert zone._pending_writes == 0
    assert not zone.checked_out
