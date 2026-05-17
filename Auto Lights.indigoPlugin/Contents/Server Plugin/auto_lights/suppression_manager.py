"""Background recovery for devices suppressed after repeated command failures.

See Gitea issue #13. A device is "suppressed" after ``MAX_CONSECUTIVE_FAILURES``
unconfirmed commands; the hot path then skips it in ``has_brightness_changes()``
and ``save_brightness_changes()``. Without active recovery a suppressed device
deadlocks until a plugin restart — it emits no events, or is stuck opposite its
target so the old at-target recovery gate never clears it.

``SuppressionManager`` owns failure tracking and runs a background thread that
retries suppressed devices on a backoff. The retry *is* the probe: command
confirmation is the only reliable, protocol-agnostic health signal (Indigo's
``lastSuccessfulComm`` / ``errorState`` are not — see #13). A confirmed retry
clears suppression and re-evaluates the zone, so no device ever needs a plugin
restart to recover.

Failures cluster by integration (a hub/network outage knocks out every device on
a protocol at once), so suppressed devices are grouped by ``pluginId``: probing
is throttled round-robin to one device per protocol, and the first device of a
protocol to confirm fast-releases its siblings.

All scanning, retrying and recovery happen on the manager's own thread; the core
sensor->command hot path only does O(1) bookkeeping (record_failure/success).
"""

import threading
import time
from typing import List, Optional, Tuple

from . import utils
from .auto_lights_base import AutoLightsBase
from .zone import MAX_CONSECUTIVE_FAILURES

try:
    import indigo
except ImportError:
    pass


# Backoff schedule (seconds) applied after each failed retry: 5, 15, 30, 60 min.
BACKOFF_STEPS: Tuple[int, ...] = (300, 900, 1800, 3600)

# How often the background thread runs one scan cycle.
SCAN_INTERVAL_SECONDS = 60.0


class _Entry:
    """Per-device suppression state."""

    __slots__ = (
        "dev_id",
        "zone",
        "plugin_id",
        "fail_count",
        "backoff_index",
        "next_retry_at",
        "awaiting_confirm",
    )

    def __init__(self, dev_id: int, zone) -> None:
        self.dev_id = dev_id
        self.zone = zone
        self.plugin_id = ""
        self.fail_count = 0
        self.backoff_index = 0
        self.next_retry_at = 0.0
        self.awaiting_confirm = False


class SuppressionManager(AutoLightsBase):
    """Tracks command-failure suppression and recovers suppressed devices.

    Thread-safety: a single lock guards the entry dict. Retry commands and zone
    re-evaluations are always dispatched *outside* the lock (a zone re-eval
    re-enters ``is_suppressed``, which takes the same lock).
    """

    def __init__(
        self,
        agent,
        *,
        scan_interval: float = SCAN_INTERVAL_SECONDS,
        backoff_steps: Tuple[int, ...] = BACKOFF_STEPS,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._scan_interval = scan_interval
        self._backoff_steps = backoff_steps
        self._lock = threading.Lock()
        self._entries: dict[int, _Entry] = {}
        # Round-robin cursor per pluginId for the probing phase.
        self._protocol_cursor: dict[str, int] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # Hot-path API — called from zone writer threads. O(1), no I/O.
    # ------------------------------------------------------------------
    def record_failure(self, dev_id: int, zone) -> None:
        """Record an unconfirmed command for ``dev_id`` in ``zone``."""
        with self._lock:
            entry = self._entries.get(dev_id)
            if entry is None:
                entry = _Entry(dev_id, zone)
                self._entries[dev_id] = entry
            entry.zone = zone
            if entry.fail_count >= MAX_CONSECUTIVE_FAILURES:
                return  # already suppressed — manager owns it now
            entry.fail_count += 1
            if entry.fail_count >= MAX_CONSECUTIVE_FAILURES:
                # Crossed the threshold — suppress and schedule first retry.
                entry.plugin_id = self._plugin_id(dev_id)
                entry.backoff_index = 0
                entry.next_retry_at = time.monotonic() + self._backoff_steps[0]
                self.logger.warning(
                    f"⚠️ Device '{self._dev_name(dev_id)}' failed to confirm "
                    f"{entry.fail_count} consecutive commands — suppressing "
                    f"until it responds"
                )

    def record_success(self, dev_id: int) -> None:
        """Record a confirmed command for ``dev_id`` — clears any failure streak."""
        with self._lock:
            self._entries.pop(dev_id, None)

    def is_suppressed(self, dev_id: int) -> bool:
        """Return True if ``dev_id`` is currently suppressed."""
        with self._lock:
            entry = self._entries.get(dev_id)
            return entry is not None and entry.fail_count >= MAX_CONSECUTIVE_FAILURES

    def note_device_event(self, dev_id: int) -> None:
        """Fast-path recovery: a device emitted a state event.

        If the device is suppressed and now sits at its zone target, clear
        suppression immediately (resolves a manager retry, or a device fixed
        manually) and fast-release its protocol siblings.
        """
        reeval_zones: List = []
        retries: List[Tuple[int, object]] = []
        with self._lock:
            entry = self._entries.get(dev_id)
            if entry is None or entry.fail_count < MAX_CONSECUTIVE_FAILURES:
                return
            if not self._device_at_target(entry):
                return
            self._resolve_confirmed(entry, reeval_zones, retries)
        self._dispatch(retries, reeval_zones)

    def reset(self) -> None:
        """Clear all suppression state (manual reset / config reload)."""
        with self._lock:
            self._entries.clear()
            self._protocol_cursor.clear()

    # ------------------------------------------------------------------
    # Background scan
    # ------------------------------------------------------------------
    def run_once(self) -> None:
        """Run one scan cycle. Public so tests can drive it synchronously."""
        now = time.monotonic()
        reeval_zones: List = []
        retries: List[Tuple[int, object]] = []
        with self._lock:
            # 1) Resolve retries awaiting confirmation from a prior cycle.
            confirmed_protocols = set()
            for entry in list(self._entries.values()):
                if not self._is_suppressed(entry) or not entry.awaiting_confirm:
                    continue
                if self._device_at_target(entry):
                    confirmed_protocols.add(entry.plugin_id)
                    self._resolve_confirmed(entry, reeval_zones, retries=None)
                else:
                    entry.awaiting_confirm = False
                    entry.backoff_index = min(
                        entry.backoff_index + 1, len(self._backoff_steps) - 1
                    )
                    entry.next_retry_at = now + self._backoff_steps[entry.backoff_index]

            # 2) Fast-release: a protocol that just confirmed is proven healthy.
            for plugin_id in confirmed_protocols:
                self._fast_release(plugin_id, retries)

            # 3) Probe: one due device per protocol, round-robin.
            due = [
                e
                for e in self._entries.values()
                if self._is_suppressed(e)
                and not e.awaiting_confirm
                and now >= e.next_retry_at
            ]
            by_protocol: dict[str, List[_Entry]] = {}
            for e in due:
                by_protocol.setdefault(e.plugin_id, []).append(e)
            for plugin_id, group in by_protocol.items():
                group.sort(key=lambda e: e.dev_id)
                cursor = self._protocol_cursor.get(plugin_id, 0) % len(group)
                self._protocol_cursor[plugin_id] = cursor + 1
                self._queue_retry(group[cursor], now, retries)

        self._dispatch(retries, reeval_zones)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the background scan thread (idempotent)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="SuppressionManager", daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        """Stop the background scan thread."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        # _stop.wait() returns True when stopped, False on timeout.
        while not self._stop.wait(self._scan_interval):
            try:
                self.run_once()
            except Exception:
                self.logger.exception("SuppressionManager scan cycle failed")

    # ------------------------------------------------------------------
    # Internals — all callers hold self._lock unless noted.
    # ------------------------------------------------------------------
    @staticmethod
    def _is_suppressed(entry: _Entry) -> bool:
        return entry.fail_count >= MAX_CONSECUTIVE_FAILURES

    def _resolve_confirmed(
        self,
        entry: _Entry,
        reeval_zones: List,
        retries: Optional[List[Tuple[int, object]]],
    ) -> None:
        """Clear a confirmed device and queue its zone re-eval + sibling release."""
        self._entries.pop(entry.dev_id, None)
        self.logger.info(
            f"✅ Device '{self._dev_name(entry.dev_id)}' reached target state "
            f"— resuming automation for zone '{entry.zone.name}'"
        )
        reeval_zones.append(entry.zone)
        if retries is not None:
            self._fast_release(entry.plugin_id, retries)

    def _fast_release(self, plugin_id: str, retries: List[Tuple[int, object]]) -> None:
        """Queue an immediate retry for every still-suppressed device on a
        protocol just proven healthy (bypasses the round-robin throttle)."""
        for entry in self._entries.values():
            if (
                entry.plugin_id == plugin_id
                and self._is_suppressed(entry)
                and not entry.awaiting_confirm
            ):
                self._queue_retry(entry, time.monotonic(), retries)

    def _queue_retry(
        self, entry: _Entry, now: float, retries: List[Tuple[int, object]]
    ) -> None:
        """Mark an entry awaiting-confirm and queue its retry command."""
        desired = self._target_for(entry)
        if desired is None:
            # No current target to retry toward — back off and try later.
            entry.backoff_index = min(
                entry.backoff_index + 1, len(self._backoff_steps) - 1
            )
            entry.next_retry_at = now + self._backoff_steps[entry.backoff_index]
            return
        entry.awaiting_confirm = True
        retries.append((entry.dev_id, desired))

    def _dispatch(self, retries: List[Tuple[int, object]], reeval_zones: List) -> None:
        """Send queued retry commands and run queued zone re-evals. No lock held."""
        for dev_id, desired in retries:
            try:
                self.logger.info(
                    f"🔁 Retrying suppressed device '{self._dev_name(dev_id)}'"
                )
                utils.send_command(dev_id, desired)
            except Exception:
                self.logger.exception(f"Retry send failed for device {dev_id}")
        for zone in reeval_zones:
            try:
                if self._agent is not None:
                    self._agent.process_zone(zone)
            except Exception:
                self.logger.exception(
                    f"Re-eval failed for zone '{getattr(zone, 'name', '?')}'"
                )

    def _target_for(self, entry: _Entry):
        """Return the device's current target brightness for its zone, or None."""
        try:
            for tgt in entry.zone.target_brightness or []:
                if tgt["dev_id"] == entry.dev_id:
                    return tgt["brightness"]
        except Exception:
            return None
        return None

    def _device_at_target(self, entry: _Entry) -> bool:
        desired = self._target_for(entry)
        if desired is None:
            return False
        try:
            return utils.is_device_at_target(indigo.devices[entry.dev_id], desired)
        except Exception:
            return False

    @staticmethod
    def _plugin_id(dev_id: int) -> str:
        try:
            return indigo.devices[dev_id].pluginId or ""
        except Exception:
            return ""

    @staticmethod
    def _dev_name(dev_id: int) -> str:
        try:
            return indigo.devices[dev_id].name
        except Exception:
            return str(dev_id)
