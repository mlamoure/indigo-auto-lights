"""Tests for SuppressionManager — backoff-retry recovery for suppressed devices.

See Gitea issue #13. A device suppressed after MAX_CONSECUTIVE_FAILURES
unconfirmed commands must recover on its own (retry on a backoff, clear when a
retry confirms) rather than deadlocking until a plugin restart.
"""

import logging
import time
from types import SimpleNamespace
from unittest.mock import patch

import indigo
from auto_lights.suppression_manager import SuppressionManager
from auto_lights.zone import MAX_CONSECUTIVE_FAILURES
from tests.helpers import make_device


def _make_manager(backoff_steps=(0, 0, 0, 0)):
    """Build a manager with a fake agent that records process_zone calls."""
    reevaled = []
    agent = SimpleNamespace(process_zone=lambda z: reevaled.append(z))
    mgr = SuppressionManager(agent, scan_interval=0.05, backoff_steps=backoff_steps)
    return mgr, reevaled


def _fake_zone(name="Zone", targets=None):
    return SimpleNamespace(name=name, target_brightness=list(targets or []))


def _confirming_send(dev_id, desired):
    """Stand-in for utils.send_command that makes the device reach target."""
    d = indigo.devices[dev_id]
    level = desired if isinstance(desired, int) else (100 if desired else 0)
    d.brightness = level
    d.states["brightness"] = level
    d.onState = bool(level)
    d.onOffState = d.onState


# --- Suppression tracking ---


def test_suppresses_after_max_failures(caplog):
    """fail_count reaching the threshold suppresses the device and logs once."""
    mgr, _ = _make_manager()
    zone = _fake_zone(targets=[{"dev_id": 101, "brightness": 100}])
    make_device(101, brightness=0)

    with caplog.at_level(logging.WARNING, logger="Plugin"):
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            mgr.record_failure(101, zone)

    assert mgr.is_suppressed(101)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "suppressing" in warnings[0].message


def test_below_threshold_not_suppressed():
    """A failure streak below the threshold does not suppress."""
    mgr, _ = _make_manager()
    zone = _fake_zone(targets=[{"dev_id": 101, "brightness": 100}])
    make_device(101, brightness=0)
    for _ in range(MAX_CONSECUTIVE_FAILURES - 1):
        mgr.record_failure(101, zone)
    assert not mgr.is_suppressed(101)


def test_record_success_clears_streak():
    """A confirmed command resets the failure streak."""
    mgr, _ = _make_manager()
    zone = _fake_zone(targets=[{"dev_id": 101, "brightness": 100}])
    make_device(101, brightness=0)
    mgr.record_failure(101, zone)
    mgr.record_failure(101, zone)
    mgr.record_success(101)
    mgr.record_failure(101, zone)
    assert not mgr.is_suppressed(101)  # streak restarted from 0


# --- Backoff retry recovery ---


@patch("auto_lights.suppression_manager.utils.send_command")
def test_retry_confirms_clears_suppression(mock_send):
    """A confirmed retry clears suppression and re-evaluates the zone."""
    mock_send.side_effect = _confirming_send
    mgr, reevaled = _make_manager()
    zone = _fake_zone(targets=[{"dev_id": 101, "brightness": 100}])
    make_device(101, brightness=0)
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        mgr.record_failure(101, zone)
    assert mgr.is_suppressed(101)

    mgr.run_once()  # probe: issue retry (send brings the device to target)
    mock_send.assert_called_once_with(101, 100)
    mgr.run_once()  # resolve: device at target -> confirmed

    assert not mgr.is_suppressed(101)
    assert zone in reevaled


@patch("auto_lights.suppression_manager.utils.send_command")
def test_retry_failure_advances_backoff(mock_send):
    """A retry that does not confirm advances the backoff index."""
    mock_send.side_effect = lambda *a: None  # retry never reaches target
    mgr, _ = _make_manager(backoff_steps=(10, 20, 30, 40))
    zone = _fake_zone(targets=[{"dev_id": 101, "brightness": 100}])
    make_device(101, brightness=0)
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        mgr.record_failure(101, zone)
    entry = mgr._entries[101]
    assert entry.backoff_index == 0

    entry.next_retry_at = time.monotonic()  # make it due now
    mgr.run_once()  # probe: issue retry
    assert entry.awaiting_confirm
    mgr.run_once()  # resolve: not at target -> fail -> backoff advances
    assert entry.backoff_index == 1
    assert not entry.awaiting_confirm


@patch("auto_lights.suppression_manager.utils.send_command")
def test_protocol_group_first_confirm_releases_siblings(mock_send):
    """One device of a protocol confirming fast-releases its siblings."""
    mock_send.side_effect = _confirming_send
    mgr, _ = _make_manager()
    zone = _fake_zone(
        targets=[
            {"dev_id": 101, "brightness": 100},
            {"dev_id": 102, "brightness": 100},
        ]
    )
    make_device(101, brightness=0)
    make_device(102, brightness=0)  # same (empty) pluginId -> same group
    for dev in (101, 102):
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            mgr.record_failure(dev, zone)

    mgr.run_once()  # probe: round-robin retries ONE of the group
    assert mock_send.call_count == 1
    mgr.run_once()  # resolve confirmed -> fast-release the sibling

    retried = {c.args[0] for c in mock_send.call_args_list}
    assert retried == {101, 102}
    assert not mgr.is_suppressed(101)


@patch("auto_lights.suppression_manager.utils.send_command")
def test_note_device_event_resolves_pending_retry(mock_send):
    """A deviceUpdated event confirms a pending retry ahead of the scan cycle."""
    mock_send.side_effect = _confirming_send
    mgr, reevaled = _make_manager()
    zone = _fake_zone(targets=[{"dev_id": 101, "brightness": 100}])
    make_device(101, brightness=0)
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        mgr.record_failure(101, zone)

    mgr.run_once()  # retry issued; send already moved the device to target
    mgr.note_device_event(101)  # deviceUpdated arrives before the next cycle

    assert not mgr.is_suppressed(101)
    assert zone in reevaled


def test_note_device_event_ignores_unsuppressed_device():
    """note_device_event is a cheap no-op for a device with no suppression."""
    mgr, reevaled = _make_manager()
    make_device(101, brightness=0)
    mgr.note_device_event(101)  # must not raise
    assert reevaled == []


# --- Thread lifecycle ---


def test_start_and_shutdown_clean():
    """The background thread starts and stops without error."""
    mgr, _ = _make_manager()
    mgr.start()
    assert mgr._thread is not None
    time.sleep(0.15)  # allow a few scan cycles
    mgr.shutdown()
    assert mgr._thread is None
