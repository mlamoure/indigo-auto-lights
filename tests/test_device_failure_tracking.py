"""Tests for per-device failure tracking to prevent infinite command loops.

When a device fails to confirm commands (e.g. HA Agent device that is
unreachable or whose brightness state never updates), the plugin should
suppress further commands after MAX_CONSECUTIVE_FAILURES and log a warning.
"""

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

import indigo
from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.auto_lights_agent import AutoLightsAgent
from auto_lights.zone import MAX_CONSECUTIVE_FAILURES
from auto_lights import utils
from plugin import Plugin
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


# --- send_to_indigo return value tests ---


@patch("auto_lights.utils._send_command")
def test_send_to_indigo_returns_true_on_confirmed(mock_cmd):
    """send_to_indigo returns True when the device reaches target state."""
    dev = make_device(501, brightness=0)

    def fake_cmd(dev_id, target, target_bool):
        # Simulate device confirming immediately
        d = indigo.devices[dev_id]
        d.brightness = target
        d.states["brightness"] = target

    mock_cmd.side_effect = fake_cmd
    result = utils.send_to_indigo(501, 100)
    assert result is True


@patch("auto_lights.utils._send_command")
def test_send_to_indigo_returns_false_on_unconfirmed(mock_cmd):
    """send_to_indigo returns False when device never reaches target."""
    dev = make_device(502, brightness=0)
    # _send_command does nothing — device stays at brightness 0
    mock_cmd.side_effect = lambda *a: None

    result = utils.send_to_indigo(502, 100)
    assert result is False


def test_send_to_indigo_returns_true_when_already_at_target():
    """send_to_indigo returns True (skip) when device is already at target."""
    make_device(503, brightness=100)
    result = utils.send_to_indigo(503, 100)
    assert result is True


# --- Failure tracking in Zone ---


@patch("auto_lights.utils.send_to_indigo")
def test_failure_count_increments(mock_send, agent_and_zone):
    """_device_fail_count increments when send_to_indigo returns False.

    The re-evaluation loop runs until MAX_CONSECUTIVE_FAILURES is reached
    and the device gets suppressed, so the final count equals the threshold.
    """
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # send_to_indigo returns False (device never confirms)
    mock_send.return_value = False

    agent.process_zone(zone)

    # Wait for full re-evaluation chain to settle.
    # checked_out briefly flips False→True between iterations, so we
    # wait for the device to actually be suppressed as the stable signal.
    deadline = time.monotonic() + 10.0
    while not zone._is_device_suppressed(dev_id) and time.monotonic() < deadline:
        time.sleep(0.05)

    assert zone._device_fail_count.get(dev_id, 0) == MAX_CONSECUTIVE_FAILURES


@patch("auto_lights.utils.send_to_indigo")
def test_failure_count_resets_on_success(mock_send, agent_and_zone):
    """_device_fail_count resets to 0 when send_to_indigo returns True."""
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # Pre-seed a failure count
    zone._device_fail_count[dev_id] = 2

    # send_to_indigo returns True and device state is updated
    def fake_send(d_id, brightness):
        dev = indigo.devices[d_id]
        dev.brightness = brightness if isinstance(brightness, int) else (100 if brightness else 0)
        dev.states["brightness"] = dev.brightness
        return True

    mock_send.side_effect = fake_send

    agent.process_zone(zone)

    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    assert zone._device_fail_count.get(dev_id, 0) == 0


@patch("auto_lights.utils.send_to_indigo")
def test_suppression_after_max_failures(mock_send, agent_and_zone):
    """has_brightness_changes() skips devices that reached MAX_CONSECUTIVE_FAILURES."""
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # Pre-seed failure count at the threshold
    zone._device_fail_count[dev_id] = MAX_CONSECUTIVE_FAILURES

    # Set target brightness to differ from actual
    zone.target_brightness = [{"dev_id": dev_id, "brightness": 100}]

    # Device is at 0, target is 100 — but it should be suppressed
    assert zone.has_brightness_changes() is False


@patch("auto_lights.utils.send_to_indigo")
def test_suppressed_device_not_written(mock_send, agent_and_zone):
    """save_brightness_changes() does not send commands to suppressed devices."""
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # Pre-seed failure count at the threshold
    zone._device_fail_count[dev_id] = MAX_CONSECUTIVE_FAILURES

    # Set target brightness
    zone.target_brightness = [{"dev_id": dev_id, "brightness": 100}]

    # Manually check out and call save
    zone.check_out()
    zone.save_brightness_changes()

    # Wait briefly
    time.sleep(0.5)

    # send_to_indigo should NOT have been called
    mock_send.assert_not_called()
    # Zone should have checked back in (nothing to write)
    assert not zone.checked_out


@patch("auto_lights.utils.send_to_indigo")
def test_loop_terminates_after_max_failures(mock_send, agent_and_zone):
    """The process_zone -> save -> reeval loop stops after MAX_CONSECUTIVE_FAILURES."""
    agent, zone = agent_and_zone
    process_count = 0
    original_process = agent.process_zone

    def counting_process(z):
        nonlocal process_count
        process_count += 1
        return original_process(z)

    agent.process_zone = counting_process

    # Device never confirms
    mock_send.return_value = False

    # Start the zone processing
    counting_process(zone)

    # Wait for all iterations to settle
    deadline = time.monotonic() + 10.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    # Should have been called a limited number of times, not infinitely.
    # Initial call + up to MAX_CONSECUTIVE_FAILURES re-evaluations,
    # then the device is suppressed and no more changes are detected.
    assert process_count <= MAX_CONSECUTIVE_FAILURES + 2
    assert not zone.checked_out


# --- Auto-recovery via process_device_change ---


@patch("auto_lights.utils.send_to_indigo")
def test_device_change_clears_failure_count_when_at_target(mock_send, agent_and_zone):
    """When a suppressed device's state matches the zone's target, the fail
    count is cleared. Bare deviceUpdated callbacks that don't reach target
    must NOT clear the count — see test_device_change_unrelated_does_not_clear.
    """
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # Zone wants this device at brightness 100
    zone.target_brightness = [{"dev_id": dev_id, "brightness": 100}]

    # Pre-seed failure count at the threshold
    zone._device_fail_count[dev_id] = MAX_CONSECUTIVE_FAILURES

    # Simulate the device actually reaching brightness 100
    orig_dev = indigo.devices[dev_id]
    orig_dev.brightness = 100
    orig_dev.states["brightness"] = 100
    diff = {"brightness": 100}

    mock_send.return_value = True
    agent.process_device_change(orig_dev, diff)

    # Fail count should be cleared
    assert zone._device_fail_count.get(dev_id, 0) == 0


def test_plugin_device_updated_clears_failure_count_when_new_state_reaches_target(
    agent_and_zone,
):
    """Plugin.deviceUpdated must evaluate recovery against the post-update
    device snapshot from Indigo, not the pre-update one.
    """
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    zone.target_brightness = [{"dev_id": dev_id, "brightness": 100}]
    zone._device_fail_count[dev_id] = MAX_CONSECUTIVE_FAILURES

    orig_dev = indigo.DimmerDevice(
        dev_id,
        name=f"Dev-{dev_id}",
        onState=False,
        brightness=0,
    )
    new_dev = indigo.DimmerDevice(
        dev_id,
        name=f"Dev-{dev_id}",
        onState=True,
        brightness=100,
    )
    indigo.devices[dev_id] = new_dev

    fake_plugin = SimpleNamespace(_agent=agent)
    Plugin.deviceUpdated(fake_plugin, orig_dev, new_dev)

    assert zone._device_fail_count.get(dev_id, 0) == 0


@patch("auto_lights.utils.send_to_indigo")
def test_device_change_unrelated_does_not_clear(mock_send, agent_and_zone):
    """A deviceUpdated callback that does not reach the zone's target must
    NOT clear the failure count. This is the regression guard for the
    Z-Wave flood: a flaky node fires state updates (lastChanged, partial
    reports) that look like activity but never reach the desired state,
    and the old recovery logic cleared the counter on every such update,
    causing infinite re-evaluation loops.
    """
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # Zone wants this device at brightness 100
    zone.target_brightness = [{"dev_id": dev_id, "brightness": 100}]

    # Pre-seed at the suppression threshold
    zone._device_fail_count[dev_id] = MAX_CONSECUTIVE_FAILURES

    # Device is still at 0 — the deviceUpdated diff is irrelevant noise
    orig_dev = indigo.devices[dev_id]
    orig_dev.brightness = 0
    orig_dev.states["brightness"] = 0

    agent.process_device_change(orig_dev, {"brightness": 0})

    # Counter must remain at the threshold; device stays suppressed
    assert zone._device_fail_count.get(dev_id, 0) == MAX_CONSECUTIVE_FAILURES
    assert zone._is_device_suppressed(dev_id)


# --- _check_confirm fallback tests ---


def test_check_confirm_unknown_device_with_brightness():
    """Unknown device type with brightness attribute should check it."""
    dev = make_device(601, brightness=50)
    # Make it not a DimmerDevice or RelayDevice
    dev.__class__ = type("CustomDevice", (), {})
    dev.brightness = 50
    dev.states = {"brightness": 50}
    dev.pluginId = "some.other.plugin"
    dev.name = "Custom-601"

    assert utils._check_confirm(dev, 50, None) is True
    assert utils._check_confirm(dev, 100, None) is False


def test_check_confirm_unknown_device_no_brightness():
    """Unknown device type with no brightness info defaults to False."""

    class BareDevice:
        """A device with no brightness attribute or states."""
        def __init__(self):
            self.name = "Mystery-701"
            self.pluginId = "some.other.plugin"
            self.states = {}

    dev = BareDevice()
    # Not an instance of indigo.DimmerDevice or indigo.RelayDevice
    assert not isinstance(dev, indigo.DimmerDevice)
    assert not isinstance(dev, indigo.RelayDevice)
    assert not hasattr(dev, "brightness")

    assert utils._check_confirm(dev, 100, None) is False


def test_has_brightness_changes_normalizes_relay_bool_targets(agent_and_zone):
    """Relay targets stored as bool should compare through
    is_device_at_target(), not raw integer/bool inequality.
    """
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    make_device(dev_id, device_cls="relay", onState=True, brightness=100)
    zone.target_brightness = [{"dev_id": dev_id, "brightness": True}]

    assert zone.current_lights_status(include_lock_excluded=True)[0]["brightness"] == 100
    assert zone.target_brightness[0]["brightness"] is True
    assert zone.has_brightness_changes() is False


# --- Multi-device and edge case tests ---


@pytest.fixture
def multi_device_agent(tmp_path):
    """Set up an agent with a zone that has two on_lights and one off_lights device."""
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

    for dev_id_key in ["on_lights_dev_ids", "off_lights_dev_ids",
                       "luminance_dev_ids", "presence_dev_ids"]:
        for dev_id in getattr(zone, dev_id_key, []):
            if dev_id not in indigo.devices:
                make_device(dev_id)

    # Presence active, dark, all lights off
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
def test_only_failing_device_suppressed(mock_send, multi_device_agent):
    """In a multi-device zone, only the failing device gets suppressed."""
    agent, zone = multi_device_agent
    dev_ok = 101
    dev_bad = 102

    def selective_send(dev_id, brightness):
        if dev_id == dev_ok:
            dev = indigo.devices[dev_id]
            dev.brightness = brightness if isinstance(brightness, int) else (100 if brightness else 0)
            dev.states["brightness"] = dev.brightness
            return True
        return False  # dev_bad never confirms

    mock_send.side_effect = selective_send

    agent.process_zone(zone)

    deadline = time.monotonic() + 10.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    # dev_bad should be suppressed, dev_ok should not
    assert zone._is_device_suppressed(dev_bad)
    assert not zone._is_device_suppressed(dev_ok)
    assert zone._device_fail_count.get(dev_ok, 0) == 0


@patch("auto_lights.utils.send_to_indigo")
def test_off_lights_suppression(mock_send, multi_device_agent):
    """off_lights devices are also suppressed after repeated failures."""
    agent, zone = multi_device_agent
    off_dev = zone.off_lights_dev_ids[0]

    # Pre-seed the suppression
    zone._device_fail_count[off_dev] = MAX_CONSECUTIVE_FAILURES

    # Put every light in the wrong state, then target everything off.
    for dev_id in zone.on_lights_dev_ids:
        indigo.devices[dev_id].brightness = 100
        indigo.devices[dev_id].onState = True
        indigo.devices[dev_id].states["brightness"] = 100
        indigo.devices[dev_id].states["onState"] = True
        indigo.devices[dev_id].states["onOffState"] = True
    indigo.devices[off_dev].brightness = 100
    indigo.devices[off_dev].onState = True
    indigo.devices[off_dev].states["brightness"] = 100
    indigo.devices[off_dev].states["onState"] = True
    indigo.devices[off_dev].states["onOffState"] = True

    zone.target_brightness = [
        {"dev_id": d, "brightness": 0}
        for d in zone.on_lights_dev_ids + zone.off_lights_dev_ids
    ]

    def fake_send(dev_id, brightness):
        d = indigo.devices[dev_id]
        d.brightness = 100 if isinstance(brightness, bool) and brightness else int(brightness)
        d.onState = bool(d.brightness)
        d.states["brightness"] = d.brightness
        d.states["onState"] = d.onState
        d.states["onOffState"] = d.onState
        return True

    mock_send.side_effect = fake_send

    zone.check_out()
    zone.save_brightness_changes()

    time.sleep(0.5)

    # send_to_indigo should NOT have been called for the suppressed off_lights device
    for call_args in mock_send.call_args_list:
        assert call_args[0][0] != off_dev, \
            f"send_to_indigo was called for suppressed off_lights device {off_dev}"


@patch("auto_lights.utils.send_to_indigo")
def test_default_off_lights_behavior_does_not_write_off_lights_while_active(
    mock_send, multi_device_agent
):
    """Default off-lights behavior should leave off_lights alone while the
    zone is active and dark.
    """
    agent, zone = multi_device_agent
    off_dev = zone.off_lights_dev_ids[0]

    indigo.devices[off_dev].brightness = 100
    indigo.devices[off_dev].onState = True
    indigo.devices[off_dev].states["brightness"] = 100
    indigo.devices[off_dev].states["onState"] = True
    indigo.devices[off_dev].states["onOffState"] = True

    sent_to = []

    def fake_send(dev_id, brightness):
        sent_to.append((dev_id, brightness))
        d = indigo.devices[dev_id]
        d.brightness = 100 if isinstance(brightness, bool) and brightness else int(brightness)
        d.onState = bool(d.brightness)
        d.states["brightness"] = d.brightness
        d.states["onState"] = d.onState
        d.states["onOffState"] = d.onState
        return True

    mock_send.side_effect = fake_send

    agent.process_zone(zone)

    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    written_ids = [dev_id for dev_id, _ in sent_to]
    assert zone.on_lights_dev_ids[0] in written_ids
    assert zone.on_lights_dev_ids[1] in written_ids
    assert off_dev not in written_ids


@pytest.fixture
def force_off_agent(tmp_path):
    """Zone with force-off behavior during an active dark period."""
    data = load_yaml(
        Path(__file__).parent / "configs" / "scenario7_force_off_behavior.yaml"
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

    make_device(101, brightness=0, onState=False)
    make_device(102, brightness=100, onState=True)
    make_device(201, sensorValue=0)
    make_device(301, onState=True)

    return agent, zone


@patch("auto_lights.utils.send_to_indigo")
def test_force_off_behavior_writes_off_lights_while_active(mock_send, force_off_agent):
    """Force-off mode should actively send off commands to off_lights during
    a presence+dark run.
    """
    agent, zone = force_off_agent
    off_dev = zone.off_lights_dev_ids[0]

    sent_to = []

    def fake_send(dev_id, brightness):
        sent_to.append((dev_id, brightness))
        d = indigo.devices[dev_id]
        d.brightness = 100 if isinstance(brightness, bool) and brightness else int(brightness)
        d.onState = bool(d.brightness)
        d.states["brightness"] = d.brightness
        d.states["onState"] = d.onState
        d.states["onOffState"] = d.onState
        return True

    mock_send.side_effect = fake_send

    agent.process_zone(zone)

    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    assert (zone.on_lights_dev_ids[0], 100) in sent_to
    assert (off_dev, 0) in sent_to


@patch("auto_lights.utils.send_to_indigo")
def test_warning_log_content(mock_send, agent_and_zone, caplog):
    """The warning message includes the device name and failure count."""
    import logging
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    mock_send.return_value = False

    with caplog.at_level(logging.WARNING, logger="Plugin"):
        agent.process_zone(zone)

        # Wait for device to be fully suppressed (not just checked_out=False)
        deadline = time.monotonic() + 10.0
        while not zone._is_device_suppressed(dev_id) and time.monotonic() < deadline:
            time.sleep(0.05)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, f"Expected 1 warning, got {len(warnings)}: {[w.message for w in warnings]}"
    msg = warnings[0].message
    assert "Dev-101" in msg or str(dev_id) in msg
    assert str(MAX_CONSECUTIVE_FAILURES) in msg
    assert "suppressing" in msg


@patch("auto_lights.utils.send_to_indigo")
def test_recovery_then_refailure(mock_send, agent_and_zone):
    """After recovery, a re-failing device restarts its counter from 0."""
    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # Simulate prior suppression
    zone._device_fail_count[dev_id] = MAX_CONSECUTIVE_FAILURES
    zone.target_brightness = [{"dev_id": dev_id, "brightness": 100}]

    # Device recovers via state change — it actually reaches target this time
    orig_dev = indigo.devices[dev_id]
    orig_dev.brightness = 100
    orig_dev.states["brightness"] = 100
    agent.process_device_change(orig_dev, {"brightness": 100})
    assert zone._device_fail_count.get(dev_id, 0) == 0

    # Drop the device back to 0 so the next plan computation has work to do
    orig_dev.brightness = 0
    orig_dev.onState = False
    orig_dev.states["brightness"] = 0
    orig_dev.states["onState"] = False

    # Device fails again
    mock_send.return_value = False
    agent.process_zone(zone)

    # Wait for full re-evaluation chain to settle
    deadline = time.monotonic() + 10.0
    while not zone._is_device_suppressed(dev_id) and time.monotonic() < deadline:
        time.sleep(0.05)

    # Counter should restart from 0, reaching MAX again
    assert zone._device_fail_count.get(dev_id, 0) == MAX_CONSECUTIVE_FAILURES


@patch("auto_lights.utils.send_to_indigo")
def test_exception_in_writer_does_not_deadlock(mock_send, agent_and_zone):
    """If send_to_indigo throws, _pending_writes still decrements and zone checks in."""
    agent, zone = agent_and_zone

    mock_send.side_effect = RuntimeError("Indigo API exploded")

    agent.process_zone(zone)

    deadline = time.monotonic() + 5.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not zone.checked_out, "Zone is still checked out — _writer exception caused deadlock"
    assert zone._pending_writes == 0


# --- Re-evaluation rate limit (belt-and-suspenders for runaway loops) ---


def test_can_reeval_allows_burst_then_blocks():
    """_can_reeval permits up to MAX_REEVAL_BURST writer re-evals, then refuses."""
    from auto_lights.zone import Zone, MAX_REEVAL_BURST

    z = Zone.__new__(Zone)
    z._name = "rate-limited"
    z._reeval_timestamps = __import__("collections").deque()
    z._reeval_lock = threading.Lock()
    z._reeval_limit_warned = False
    import logging
    z.logger = logging.getLogger("Plugin")

    for _ in range(MAX_REEVAL_BURST):
        assert z._can_reeval() is True
    # Next attempt is over the burst — must be denied
    assert z._can_reeval() is False
    # And again, still denied while the window has not drained
    assert z._can_reeval() is False


def test_can_reeval_window_drains():
    """After REEVAL_WINDOW_SECONDS, old timestamps age out and re-eval resumes."""
    from auto_lights.zone import Zone, MAX_REEVAL_BURST, REEVAL_WINDOW_SECONDS

    z = Zone.__new__(Zone)
    z._name = "rate-limited"
    z._reeval_timestamps = __import__("collections").deque()
    z._reeval_lock = threading.Lock()
    z._reeval_limit_warned = False
    import logging
    z.logger = logging.getLogger("Plugin")

    # Pre-fill with stale timestamps that should age out immediately
    stale = time.monotonic() - REEVAL_WINDOW_SECONDS - 1.0
    for _ in range(MAX_REEVAL_BURST):
        z._reeval_timestamps.append(stale)

    # Despite the deque being "full", everything is stale → allowed
    assert z._can_reeval() is True
    assert len(z._reeval_timestamps) == 1


@patch("auto_lights.utils.send_to_indigo")
def test_rate_limit_caps_runaway_writer_reeval(mock_send, agent_and_zone):
    """Even if failure suppression were broken, the rate limit caps the
    writer-thread re-eval loop. Simulates a pathological scenario where
    suppression is artificially defeated and verifies the loop terminates.
    """
    from auto_lights.zone import MAX_REEVAL_BURST

    agent, zone = agent_and_zone
    dev_id = zone.on_lights_dev_ids[0]

    # Simulate broken suppression: every time the count creeps up, reset it
    # via process_device_change of an already-at-target device. This is the
    # exact failure mode the auto_lights_agent.py recovery gate fixes — we
    # use it here as the "broken suppression" simulation.
    process_count = 0
    original_process = agent.process_zone

    def counting_process(z):
        nonlocal process_count
        process_count += 1
        # Defeat suppression so the only stop is the rate limit
        z._device_fail_count.clear()
        return original_process(z)

    agent.process_zone = counting_process

    mock_send.return_value = False
    counting_process(zone)

    deadline = time.monotonic() + 10.0
    while zone.checked_out and time.monotonic() < deadline:
        time.sleep(0.05)

    # Without the rate limit, this would loop forever. With it, the writer
    # thread re-eval is gated and the chain terminates within the burst.
    assert process_count <= MAX_REEVAL_BURST + 2, (
        f"Re-eval loop ran {process_count} times — rate limit did not engage"
    )
    assert not zone.checked_out
