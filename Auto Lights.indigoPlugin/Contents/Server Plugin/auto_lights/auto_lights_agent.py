import datetime
import threading
from typing import List

from .auto_lights_base import AutoLightsBase
from .auto_lights_config import AutoLightsConfig
from .zone import Zone, LOCK_HOLD_GRACE_SECONDS

try:
    import indigo
except ImportError:
    pass


class AutoLightsAgent(AutoLightsBase):
    def __init__(self, config: AutoLightsConfig) -> None:
        super().__init__()
        self.config = config
        self._timers = {}
        # Timers for presence-based unlock grace periods
        self._no_presence_timers = {}

        # Initialize per-zone transition timers
        for z in self.config.zones:
            # give each zone a backreference to the agent
            z._config.agent = self
            z.schedule_next_transition()

    def process_zone(self, zone: Zone) -> bool:
        """
        Main automation function that processes a single lighting zone.
        """
        # sync the indigo device for any runtime changes
        zone.sync_indigo_device()

        # GUARD: skip if already running
        if zone.checked_out:
            self._debug_log(
                f"Skipping process_zone for '{zone.name}' – still checked out"
            )
            return False

        # GUARD: plugin globally disabled
        if not self.config.enabled:
            self._debug_log("Skipping process_zone: plugin globally DISABLED")
            return False

        # GUARD: zone disabled
        self._debug_log(f"process_zone: zone.enabled={zone.enabled}")
        if not zone.enabled:
            self._debug_log(f"Skipping process_zone for '{zone.name}' – zone disabled")
            return False

        # Initialize baseline if needed
        if zone._target_brightness is None:
            # include all lights in the initial baseline, too
            baseline = [
                {"dev_id": s["dev_id"], "brightness": s["brightness"]}
                for s in zone.current_lights_status(include_lock_excluded=True)
            ]
            zone.target_brightness = baseline

        # Context for logging and block writes
        last_dev = zone.last_changed_device
        triggered_by = last_dev.name if last_dev else "Auto Lights"
        zone.check_out()

        # LOCK: skip if already locked
        if zone.lock_enabled and zone.locked:
            self._debug_log(
                f"Zone '{zone.name}' is locked until {zone.lock_expiration}"
            )
            zone.check_in()
            return False

        # reset per-zone runtime cache for this run
        zone._runtime_cache.clear()

        # Determine plan
        plan_global = self.config.has_global_lights_off(zone)
        if plan_global.contributions:
            plan = plan_global
            zone.target_brightness = 0
        else:
            # Skip if no periods configured
            if not zone.lighting_periods:
                if self.config.log_non_events and zone.has_presence_detected():
                    self.logger.info(
                        f"🔇 Presence detected in Zone '{zone.name}' but no lighting periods configured – no action taken"
                    )
                zone.check_in()
                return False
            # Skip if no active period
            if zone.current_lighting_period is None:
                if self.config.log_non_events and zone.has_presence_detected():
                    self.logger.info(
                        f"🔇 Presence detected in Zone '{zone.name}' but no active lighting period right now – no action taken"
                    )
                zone.check_in()
                return False
            # Normal plan computation
            plan = zone.calculate_target_brightness()
            zone.target_brightness = plan.new_targets

        # EXECUTE: apply or skip changes
        if zone.has_brightness_changes():
            self.logger.info(f"💡 Zone '{zone.name}': applying lighting changes")
            self.logger.info(f"\t🔄 Triggered by: {triggered_by}")
            self.logger.info(f"\t📝 Change logic:")
            for emoji, msg in plan.contributions:
                self.logger.info(f"\t\t{emoji} {msg}")
            if plan.exclusions:
                self.logger.info(f"\t❌ Exclusions:")
                for emoji, msg in plan.exclusions:
                    self.logger.info(f"\t\t{emoji} {msg}")
            self.logger.info(f"\t⚙️ Changes made:")
            for emoji, msg in plan.device_changes:
                self.logger.info(f"\t\t{emoji} {msg}")
            zone.save_brightness_changes()
        else:
            self._debug_log(f"Zone '{zone.name}': no changes to make")
            zone.check_in()

        # sync the indigo device for any runtime changes
        zone.sync_indigo_device()

        return True

    def process_device_change(self, orig_dev: indigo.Device, diff: dict) -> List[Zone]:
        """
        Process a device change event.

        For each zone in the agent:
          - Call zone.has_device(orig_dev.id)
          - If the returned property is 'on_lights_dev_ids' or 'off_lights_dev_ids':
              - If the zone's current_lights_status does not equal its target_brightness,
                set zone.locked to True.
          - If the property is 'presence_dev_ids' or 'luminance_dev_ids':
              - Process the change by calling self.process_zone(zone)

        Returns:
            List[Zone]: List of Zone's processed
        """
        processed = []
        for zone in self.config.zones:
            device_prop = zone._has_device(orig_dev.id)
            if device_prop in ["on_lights_dev_ids", "off_lights_dev_ids"]:
                if not zone.enabled:
                    if (
                        any(k in diff for k in ["brightness", "onState", "onOffState"])
                        and self.config.log_non_events
                    ):
                        self.logger.info(
                            f"🚫 Ignored device change from '{orig_dev.name}' for disabled zone '{zone.name}'."
                        )
                    continue

                self._debug_log(
                    f"Change from {orig_dev.name}; zone property: {device_prop}"
                )

                # Skip lock logic when no active lighting period
                if zone.current_lighting_period is None:
                    self._debug_log(
                        f"Skipping lock logic for '{zone.name}': no active lighting period"
                    )
                    continue

                if zone.lock_enabled and not zone.locked and zone.has_lock_occurred():
                    change_info = ""
                    if "brightness" in diff:
                        old = getattr(orig_dev, "brightness", None)
                        new = diff["brightness"]
                        change_info = f" (was: {old}; now: {new})"
                    elif "onState" in diff:
                        old = orig_dev.states.get("onState", False)
                        new = diff["onState"]
                        change_info = f" (was: {old}; now: {new})"
                    elif "onOffState" in diff:
                        old = orig_dev.states.get("onOffState", False)
                        new = diff["onOffState"]
                        change_info = f" (was: {old}; now: {new})"
                    self.logger.info(
                        f"🔒 New lock created for zone '{zone.name}'; device change from '{orig_dev.name}'{change_info}."
                    )
                    self.logger.info("  🔒 Lock Details:")
                    self.logger.info(
                        f"    ⏲️ lock_duration: {zone.lock_duration} minutes"
                    )
                    self.logger.info(
                        f"    ⏰ lock_expiration: {zone.lock_expiration_str}"
                    )
                    self.logger.info(
                        f"    🔁 extend_lock_when_active: {zone.extend_lock_when_active}"
                    )
                    if zone.extend_lock_when_active:
                        self.logger.info(
                            f"    ⏳ lock_extension_duration: {zone.lock_extension_duration} minutes"
                        )
                        self.logger.info(
                            f"    🗝️ unlock_when_no_presence: {zone.unlock_when_no_presence}"
                        )
                    processed.append(zone)
                    # Schedule processing of expired lock after expiration + 2 seconds
                    delay = (
                        zone.lock_expiration
                        + datetime.timedelta(seconds=2)
                        - datetime.datetime.now()
                    ).total_seconds()
                    if delay > 0:
                        # Cancel any existing timer for this zone
                        if zone.name in self._timers:
                            self._timers[zone.name].cancel()
                        timer = threading.Timer(
                            delay, self.process_expired_lock, args=[zone]
                        )
                        timer.daemon = True
                        self._timers[zone.name] = timer
                        timer.start()
            elif device_prop in ["presence_dev_ids", "luminance_dev_ids"]:

                # presence-handling for auto-unlock: cancel grace timer on presence
                if device_prop == "presence_dev_ids" and zone.unlock_when_no_presence:
                    if zone.has_presence_detected():
                        t = self._no_presence_timers.pop(zone.name, None)
                        if t:
                            t.cancel()

                if self.process_zone(zone):
                    processed.append(zone)

        return processed

    def _unlock_after_grace(self, zone: Zone) -> None:
        """Called by timer to attempt unlock after presence-grace expires."""
        # remove our timer reference
        self._no_presence_timers.pop(zone.name, None)
        # Only unlock if the lock's grace period has expired.
        if hasattr(zone, "_lock_start_time"):
            elapsed = (datetime.datetime.now() - zone._lock_start_time).total_seconds()
            if elapsed < LOCK_HOLD_GRACE_SECONDS:
                return
        if (
            zone.locked
            and zone.unlock_when_no_presence
            and not zone.has_presence_detected()
        ):
            self.reset_locks(
                zone.name,
                f"no presence held ≥ {LOCK_HOLD_GRACE_SECONDS}s (grace)"
            )

    def process_all_zones(self) -> None:
        """
        Process all zones in the agent's configuration.

        Iterates through each zone in the configuration and calls process_zone() on each one.
        This is typically used when a global configuration change affects all zones.
        """
        for zone in self.config.zones:
            self.process_zone(zone)

    def process_variable_change(
        self, orig_var: indigo.Variable, new_var: indigo.Variable
    ) -> List[Zone]:
        """
        Process a variable change event.

        If the global configuration has the variable (via has_variable),
        then process all zones. Otherwise, for each zone,
        check if the zone has the variable and process it.

        Returns:
            List[Zone]: List of Zone's processed.
        """
        processed = []
        if self.config.has_variable(orig_var.id):
            self.logger.debug(
                f"Global config has variable: {indigo.variables[orig_var.id].name}; running process_all_zones"
            )
            self.process_all_zones()
            return self.config.zones

        for zone in self.config.zones:
            if zone.has_variable(orig_var.id):
                self.logger.debug(
                    f"has_variable: var_id {indigo.variables[orig_var.id].name}"
                )
                if self.process_zone(zone):
                    processed.append(zone)
        return processed

    def get_zones(self) -> List[Zone]:
        return self.config.zones

    def reset_locks(self, zone_name: str = None, reason: str = "manual reset") -> None:
        """
        Reset locks for zones. If zone_name is provided, only reset that zone's lock; otherwise, reset locks for all zones.
        """
        self._debug_log(
            f"[AutoLightsAgent.reset_locks] Called with zone_name={zone_name}"
        )
        if zone_name:
            for zone in self.config.zones:
                if zone.name == zone_name:
                    if zone.locked:
                        zone.reset_lock(reason)
                        self.process_zone(zone)
                        if zone.name in self._timers:
                            self._timers[zone.name].cancel()
                            del self._timers[zone.name]
        else:
            for zone in self.config.zones:
                if zone.locked:
                    zone.reset_lock(reason)
                    self.process_zone(zone)
                    if zone.name in self._timers:
                        self._timers[zone.name].cancel()
                        del self._timers[zone.name]

    def process_expired_lock(self, unlocked_zone: Zone) -> None:
        """
        Called when a zone's lock expiration triggers. If the zone is no longer locked, process the zone.  Without this, no changes will be made once the lock expires.
        Otherwise, schedule process_expired_lock again at the new lock_expiration.
        """
        self._debug_log(
            f"[AutoLightsAgent.process_expired_lock] Called for zone '{unlocked_zone.name}', locked={unlocked_zone.locked}"
        )
        if not unlocked_zone.locked:
            # Cancel and remove any existing timer for this zone
            if unlocked_zone.name in self._timers:
                self._timers[unlocked_zone.name].cancel()
                del self._timers[unlocked_zone.name]
            self.process_zone(unlocked_zone)
        else:
            # zone still locked; schedule next check at new expiration
            now = datetime.datetime.now()
            delay = (unlocked_zone.lock_expiration - now).total_seconds()
            if delay > 0:
                # Cancel any existing timer for this zone
                if unlocked_zone.name in self._timers:
                    self._timers[unlocked_zone.name].cancel()
                timer = threading.Timer(
                    delay, self.process_expired_lock, args=[unlocked_zone]
                )
                self._timers[unlocked_zone.name] = timer
                timer.start()

    def print_locked_zones(self) -> None:
        """
        Log information about all currently locked zones.

        Iterates through each zone and logs detailed information if the zone is locked,
        including lock expiration time and lock behavior settings. If no zones are locked,
        logs a message indicating this.
        """
        locked_zones = [zone for zone in self.config.zones if zone.locked]
        if not locked_zones:
            self.logger.info("No locked zones.")
        else:
            self.logger.info("🔒 Locked Zones:")
            for zone in locked_zones:
                self.logger.info(
                    f"🔒 Zone '{zone.name}' is locked until {zone.lock_expiration_str}"
                )
                self.logger.info(
                    f"    extend_lock_when_active: {zone.extend_lock_when_active}"
                )
                self.logger.info(
                    f"    lock_extension_duration: {zone.lock_extension_duration}"
                )
                self.logger.info(
                    f"    unlock_when_no_presence: {zone.unlock_when_no_presence}"
                )

    def enable_all_zones(self) -> None:
        """
        Enable plugin by toggling the global config device on.
        """
        self.config.enabled = True

    def disable_all_zones(self) -> None:
        """
        Disable plugin by toggling the global config device off.
        """
        self.config.enabled = False

    def enable_zone(self, zone_name: str) -> None:
        """
        Enable a specific zone by name.
        """
        for zone in self.config.zones:
            if zone.name == zone_name:
                zone.enabled = True
                break

    def disable_zone(self, zone_name: str) -> None:
        """
        Disable a specific zone by name.
        """
        for zone in self.config.zones:
            if zone.name == zone_name:
                zone.enabled = False
                break

    def debug_zone_states(self) -> None:
        """
        Debug helper: for each enabled, unlocked, idle zone,
        compare current_lights_status to target_brightness on all
        on_lights_dev_ids + off_lights_dev_ids.  Log DEBUG on match,
        WARNING on mismatch.
        """
        for zone in self.config.zones:
            # skip if zone off, locked, already processing, or no active lighting period
            if (
                not zone.enabled
                or zone.locked
                or zone.checked_out
                or zone.current_lighting_period is None
            ):
                continue

            # build quick lookup dicts
            current_map = {
                entry["dev_id"]: entry["brightness"]
                for entry in zone.current_lights_status(include_lock_excluded=True)
            }
            # zone.target_brightness might be None or empty
            target_map = {
                entry["dev_id"]: entry["brightness"]
                for entry in (zone.target_brightness or [])
            }

            for dev_id in zone.on_lights_dev_ids + zone.off_lights_dev_ids:
                actual = current_map.get(dev_id)
                desired = target_map.get(dev_id)
                # skip if target is None
                if desired is None:
                    continue
                if actual != desired:
                    # something is out-of-sync
                    self.logger.warning(
                        f"[debug_zone_states] Zone '{zone.name}' device '{indigo.devices[dev_id].name}': "
                        f"actual={actual!r}, target={desired!r}"
                    )
                else:
                    # everything matches
                    self._debug_log(
                        f"device '{indigo.devices[dev_id].name}' OK: {actual!r}"
                    )

    def shutdown(self) -> None:
        """
        Cancel all outstanding timers (lock-expiration timers in self._timers,
        plus each zone's transition-timer and lock-timer).
        """
        # Cancel agent-level timers
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()

        # Cancel each zone's timers
        for zone in self.config.zones:
            if getattr(zone, "_transition_timer", None):
                zone._transition_timer.cancel()
                zone._transition_timer = None
            if getattr(zone, "_lock_timer", None):
                zone._lock_timer.cancel()
                zone._lock_timer = None

    def refresh_all_indigo_devices(self) -> None:
        """
        Refresh all Indigo device states for all zones by syncing each zone's device states.
        """
        self.logger.debug(
            "refresh_all_indigo_devices: starting refresh of all Indigo devices"
        )
        for zone in self.config.zones:
            zone.sync_indigo_device()

        # clean up stale zone devices
        active_indices = {zone.zone_index for zone in self.config.zones}
        for dev in indigo.devices:
            if (
                dev.pluginId == "com.vtmikel.autolights"
                and dev.deviceTypeId == "auto_lights_zone"
            ):
                idx = int(dev.pluginProps.get("zone_index", -1))
                if idx not in active_indices:
                    try:
                        indigo.device.delete(dev.id)
                        self.logger.info(
                            f"Deleted stale zone device: {dev.name} (index: {idx})"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Failed to delete stale zone device {dev.name}: {e}"
                        )

    def refresh_indigo_device(self, dev_id: int) -> None:
        for zone in self.config.zones:
            if zone.indigo_dev.id == dev_id:
                zone.sync_indigo_device()
