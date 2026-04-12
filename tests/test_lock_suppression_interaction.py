"""Tests for the intersection of zone locks and per-device failure suppression.

These cover scenarios that were not exercised by either the locking tests
(test_lock_extension.py, test_lock_on_device_change.py) or the suppression
tests (test_device_failure_tracking.py) in isolation. The interesting cases
all live where the two systems meet.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import indigo
from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.auto_lights_agent import AutoLightsAgent
from auto_lights.zone import MAX_CONSECUTIVE_FAILURES
from tests.helpers import load_yaml, make_device


@pytest.fixture
def multi_device_agent(tmp_path):
    """Multi-device zone: two on_lights (101, 102), one off_lights (103),
    one luminance (201, dark), one presence (301, on)."""
    data = load_yaml(
        Path(__file__).parent / "configs" / "scenario_multi_device.yaml"
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

    for dev_id_key in [
        "on_lights_dev_ids",
        "off_lights_dev_ids",
        "luminance_dev_ids",
        "presence_dev_ids",
    ]:
        for dev_id in getattr(zone, dev_id_key, []):
            if dev_id not in indigo.devices:
                make_device(dev_id)

    for dev_id in zone.presence_dev_ids:
        make_device(dev_id, onState=True)
    for dev_id in zone.luminance_dev_ids:
        make_device(dev_id, sensorValue=0)
    for dev_id in zone.on_lights_dev_ids:
        make_device(dev_id, brightness=0, onState=False)
    for dev_id in zone.off_lights_dev_ids:
        make_device(dev_id, brightness=0, onState=False)

    return agent, zone


@patch("auto_lights.utils.send_to_indigo")
def test_lock_expiry_writes_healthy_devices_skips_suppressed(
    mock_send, multi_device_agent
):
    """When a lock expires while one device is suppressed, the OTHER devices
    in the zone must resume normal automation. The broken device stays
    skipped; the healthy device gets written.

    This is the happy-path interaction: a self-induced lock from a flaky
    device gives the zone a breather, suppression engages in the meantime,
    and the rest of the zone keeps working when the lock lifts.
    """
    agent, zone = multi_device_agent
    dev_healthy = 101
    dev_broken = 102

    # Pre-suppress the broken device at the threshold
    zone._device_fail_count[dev_broken] = MAX_CONSECUTIVE_FAILURES

    # Lock the zone, then immediately expire it
    import datetime
    zone.lock_expiration = datetime.datetime.now() - datetime.timedelta(seconds=1)
    assert not zone.locked  # past expiration → not locked

    sent_to: list[int] = []

    def selective_send(dev_id, brightness):
        sent_to.append(dev_id)
        # Healthy device confirms; broken device never confirms
        if dev_id == dev_healthy:
            d = indigo.devices[dev_id]
            d.brightness = brightness if isinstance(brightness, int) else (
                100 if brightness else 0
            )
            d.states["brightness"] = d.brightness
            return True
        return False

    mock_send.side_effect = selective_send

    # Trigger the expired-lock handler — this is what the timer fires
    agent.process_expired_lock(zone)

    # Wait for writer threads
    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    # Healthy device must have been written; broken device must not
    assert dev_healthy in sent_to, "healthy device was never written after lock expiry"
    assert dev_broken not in sent_to, (
        f"suppressed device {dev_broken} was written despite being over the "
        f"failure threshold"
    )
    # Suppression state must persist across the lock cycle
    assert zone._is_device_suppressed(dev_broken)
    # And the healthy device's counter must remain clean
    assert zone._device_fail_count.get(dev_healthy, 0) == 0


@patch("auto_lights.utils.send_to_indigo")
def test_locked_zone_does_not_create_new_lock_for_suppressed_flap(
    mock_send, multi_device_agent
):
    """A suppressed device that keeps emitting state diffs while the zone
    is already locked must NOT cause new locks to stack up, must NOT clear
    its own failure count, and must NOT call process_zone.

    This is the worst-case flapping-Z-Wave-repeater scenario: a broken node
    fires deviceUpdated repeatedly while the zone is in its self-induced
    lock cooldown. The plugin should sit still through it.
    """
    import datetime
    agent, zone = multi_device_agent
    dev_broken = 102

    # Suppress the broken device at the threshold
    zone._device_fail_count[dev_broken] = MAX_CONSECUTIVE_FAILURES

    # Establish a clear target so is_device_at_target has something to compare
    # against. Target says brightness=100 but device is at 0 — never reaching it.
    zone.target_brightness = [{"dev_id": dev_broken, "brightness": 100}]
    indigo.devices[dev_broken].brightness = 0
    indigo.devices[dev_broken].states["brightness"] = 0

    # Lock the zone for 5 minutes
    zone.lock_expiration = datetime.datetime.now() + datetime.timedelta(minutes=5)
    assert zone.locked
    initial_expiration = zone.lock_expiration

    # Track how many times process_zone gets called
    process_zone_calls = 0
    original_process = agent.process_zone

    def counting_process(z):
        nonlocal process_zone_calls
        process_zone_calls += 1
        return original_process(z)

    agent.process_zone = counting_process

    # Fire 20 deviceUpdated events for the broken device, simulating flap
    orig_dev = indigo.devices[dev_broken]
    for _ in range(20):
        agent.process_device_change(orig_dev, {"brightness": 0})

    # Failure count must remain at the threshold (not cleared)
    assert zone._device_fail_count.get(dev_broken, 0) == MAX_CONSECUTIVE_FAILURES
    # Lock expiration must not have been pushed forward
    assert zone.lock_expiration == initial_expiration
    # Zone must still be locked
    assert zone.locked
    # process_zone must NOT have been called for any of the flap events
    # (process_device_change for on_lights/off_lights devices does not call
    # process_zone — it only checks for lock creation, which is gated on
    # `not zone.locked`)
    assert process_zone_calls == 0


@patch("auto_lights.utils.send_to_indigo")
def test_recovered_device_clears_suppression_while_locked_and_writes_after_expiry(
    mock_send, multi_device_agent
):
    """A suppressed device that recovers during a lock should clear its
    failure count immediately, and once the lock expires it should be treated
    like a normal device again rather than staying skipped forever.
    """
    import datetime
    agent, zone = multi_device_agent
    dev_recovered = 102

    zone.target_brightness = [
        {"dev_id": 101, "brightness": 100},
        {"dev_id": 102, "brightness": 100},
    ]
    zone._device_fail_count[dev_recovered] = MAX_CONSECUTIVE_FAILURES
    zone.lock_expiration = datetime.datetime.now() + datetime.timedelta(minutes=5)
    assert zone.locked

    # Device recovers to the desired state while the zone is locked.
    indigo.devices[dev_recovered].brightness = 100
    indigo.devices[dev_recovered].onState = True
    indigo.devices[dev_recovered].states["brightness"] = 100
    indigo.devices[dev_recovered].states["onState"] = True
    indigo.devices[dev_recovered].states["onOffState"] = True
    agent.process_device_change(indigo.devices[dev_recovered], {"brightness": 100})
    assert zone._device_fail_count.get(dev_recovered, 0) == 0

    # Drift again before lock expiry so there is real work to do after unlock.
    indigo.devices[dev_recovered].brightness = 0
    indigo.devices[dev_recovered].onState = False
    indigo.devices[dev_recovered].states["brightness"] = 0
    indigo.devices[dev_recovered].states["onState"] = False
    indigo.devices[dev_recovered].states["onOffState"] = False

    sent_to: list[int] = []

    def fake_send(dev_id, brightness):
        sent_to.append(dev_id)
        d = indigo.devices[dev_id]
        d.brightness = brightness if isinstance(brightness, int) else (
            100 if brightness else 0
        )
        d.onState = bool(d.brightness)
        d.states["brightness"] = d.brightness
        d.states["onState"] = d.onState
        d.states["onOffState"] = d.onState
        return True

    mock_send.side_effect = fake_send

    zone.lock_expiration = datetime.datetime.now() - datetime.timedelta(seconds=1)
    assert not zone.locked
    agent.process_expired_lock(zone)

    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    assert dev_recovered in sent_to
