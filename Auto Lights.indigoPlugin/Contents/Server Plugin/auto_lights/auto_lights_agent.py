import datetime
import threading
from typing import List

from .auto_lights_base import AutoLightsBase
from .auto_lights_config import AutoLightsConfig
from .zone import Zone

try:
    import indigo
except ImportError:
    pass


class AutoLightsAgent(AutoLightsBase):
    def __init__(self, config: AutoLightsConfig) -> None:
        super().__init__()
        self._config = config
        self._timers = {}

        # Initialize per-zone transition timers
        for z in self._config.zones:
            # give each zone a backreference to the agent
            z._config.agent = self
            z.schedule_next_transition()

    def process_zone(self, zone: Zone) -> bool:
        """
        Main automation function that processes a single lighting zone.

        This method handles the core automation logic for a zone, including:
        - Checking if the zone is enabled
        - Handling zone locks
        - Evaluating global behavior variables
        - Calculating target brightness based on lighting periods
        - Applying changes to devices when needed

        Args:
            zone (Zone): A Zone object to process

        Returns:
            bool: True if the zone was processed, False if skipped due to being disabled or locked.
        """
        # -------------------------------------------------------------------
        # If we’re already in the middle of running this zone, skip duplicates
        # -------------------------------------------------------------------
        if zone.checked_out:
            self._debug_log(
                f"Skipping process_zone for '{zone.name}' – still checked out"
            )
            return False
        # Seed baseline target_brightness if it hasn't been set yet
        if zone._target_brightness is None:
            baseline = [
                {"dev_id": s["dev_id"], "brightness": s["brightness"]}
                for s in zone.current_lights_status()
            ]
            zone.target_brightness = baseline

        if not self._config.enabled:
            return False

        self._debug_log(
            f"Processing: enabled={zone.enabled}, current_lights_status={zone.current_lights_status()}"
        )

        if not zone.enabled:
            self._debug_log(f"Zone is disabled")
            return False

        last_dev = zone.last_changed_device
        triggered_by = last_dev.name if last_dev else "Auto Lights"
        zone.check_out()
        ################################################################
        # Lock logic
        ################################################################
        if zone.lock_enabled and zone.locked:
            self._debug_log(f"Zone is locked until {zone.lock_expiration}")
            zone.check_in()
            return False

        ################################################################
        # Zone execution logic (Where we decide what changes, if any, need to be made)
        ################################################################

        action_reason = ""

        # Check global behavior variables using has_global_lights_off
        global_lights_off, reason = self._config.has_global_lights_off()
        if global_lights_off:
            zone.target_brightness = 0
            action_reason = reason

        if not global_lights_off and not zone.lighting_periods:
            self._debug_log(f"Skipping: no lighting periods configured")
            zone.check_in()
            return False

        if not global_lights_off and zone.current_lighting_period is None:
            self._debug_log(f"Skipping: no current lighting period configured")
            zone.check_in()
            return False

        # Next, look to the target_brightness
        if not global_lights_off and zone.current_lighting_period is not None:
            action_reason = zone.calculate_target_brightness()
            self.logger.debug(
                f"brightness update: {action_reason}. Target brightness: {zone.target_brightness}"
            )

        ################################################################
        # Save and write log
        ################################################################
        if zone.has_brightness_changes():
            self.logger.info(f"💡 Zone '{zone.name}': applying lighting changes")
            indent = "      "
            self.logger.info(f"{indent}🔄 Triggered by: {triggered_by}")
            reason_text = action_reason or "no explicit reason provided"
            self.logger.info(f"{indent}📝 Reason: {reason_text}")
            zone.save_brightness_changes()
        else:
            self._debug_log(f"no changes to make, checked in")
            zone.check_in()

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
        for zone in self._config.zones:
            device_prop = zone.has_device(orig_dev.id)
            if device_prop in ["on_lights_dev_ids", "off_lights_dev_ids"]:
                if not zone.enabled:
                    if any(k in diff for k in ["brightness", "onState", "onOffState"]):
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

                # if presence has changed and the zone is locked, investigate if it should be unlocked
                if (
                    device_prop == "presence_dev_ids"
                    and zone.locked
                    and zone.unlock_when_no_presence
                    and not zone.has_presence_detected()
                ):
                    self.reset_locks(
                        zone.name,
                        "no presence detected and `unlock_when_no_presence` is set for this Zone",
                    )

                if self.process_zone(zone):
                    processed.append(zone)

        return processed

    def process_all_zones(self) -> None:
        """
        Process all zones in the agent's configuration.

        Iterates through each zone in the configuration and calls process_zone() on each one.
        This is typically used when a global configuration change affects all zones.
        """
        for zone in self._config.zones:
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
        if self._config.has_variable(orig_var.id):
            self.logger.debug(
                f"Global config has variable: {indigo.variables[orig_var.id].name}; running process_all_zones"
            )
            self.process_all_zones()
            return self._config.zones

        for zone in self._config.zones:
            if zone.has_variable(orig_var.id):
                self.logger.debug(
                    f"has_variable: var_id {indigo.variables[orig_var.id].name}"
                )
                if self.process_zone(zone):
                    processed.append(zone)
        return processed

    def get_zones(self) -> List[Zone]:
        return self._config.zones

    def reset_locks(self, zone_name: str = None, reason: str = "manual reset") -> None:
        """
        Reset locks for zones. If zone_name is provided, only reset that zone's lock; otherwise, reset locks for all zones.
        """
        self._debug_log(
            f"[AutoLightsAgent.reset_locks] Called with zone_name={zone_name}"
        )
        if zone_name:
            for zone in self._config.zones:
                if zone.name == zone_name:
                    if zone.locked:
                        zone.reset_lock(reason)
                        zone.check_out()
                        zone._target_brightness = None
                        self.process_zone(zone)
                        zone.check_in()
                        if zone.name in self._timers:
                            self._timers[zone.name].cancel()
                            del self._timers[zone.name]
        else:
            for zone in self._config.zones:
                if zone.locked:
                    zone.reset_lock(reason)
                    zone.check_out()
                    zone._target_brightness = None
                    self.process_zone(zone)
                    zone.check_in()
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
        locked_zones = [zone for zone in self._config.zones if zone.locked]
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
        Enable all zones by setting their enabled variable to true.
        """
        for zone in self._config.zones:
            if zone.enabled_var_id:
                indigo.variable.updateValue(zone.enabled_var_id, "true")

    def disable_all_zones(self) -> None:
        """
        Disable all zones by setting their enabled variable to false.
        """
        for zone in self._config.zones:
            if zone.enabled_var_id:
                indigo.variable.updateValue(zone.enabled_var_id, "false")

    def enable_zone(self, zone_name: str) -> None:
        """
        Enable a specific zone by name.
        """
        for zone in self._config.zones:
            if zone.name == zone_name and zone.enabled_var_id:
                indigo.variable.updateValue(zone.enabled_var_id, "true")
                break

    def disable_zone(self, zone_name: str) -> None:
        """
        Disable a specific zone by name.
        """
        for zone in self._config.zones:
            if zone.name == zone_name and zone.enabled_var_id:
                indigo.variable.updateValue(zone.enabled_var_id, "false")
                break

    def print_zone_status(self) -> None:
        """
        Log detailed status information for all zones.

        For each zone, logs information including:
        - Enabled status
        - Current lighting period details
        - Presence detection status
        - Luminance values and thresholds
        - Current and target brightness for each light
        - Lock status and expiration time if locked

        This is useful for debugging and monitoring the system state.
        """
        for zone in self._config.zones:
            self.logger.info(f"Zone '{zone.name}':")
            self.logger.info(f"    enabled: {zone.enabled}")
            current_period = zone.current_lighting_period
            if current_period:
                self.logger.info(f"    current period: {current_period.name}")
                self.logger.info(f"        type: {current_period.mode}")
                self.logger.info(
                    f"        start: {current_period.from_time.strftime('%H:%M')}"
                )
                self.logger.info(
                    f"        end: {current_period.to_time.strftime('%H:%M')}"
                )
            else:
                self.logger.info(f"    current period: None")
            self.logger.info(f"    presence: {zone.has_presence_detected()}")
            self.logger.info(
                f"    luminance: {zone.luminance} "
                f"(minimum: {zone.minimum_luminance}, dark: {zone.is_dark()})"
            )
            # Print each zone light’s current and target brightness
            for dev_id in zone.on_lights_dev_ids + zone.off_lights_dev_ids:
                dev = indigo.devices[dev_id]
                curr = next(
                    (
                        item["brightness"]
                        for item in zone.current_lights_status(
                            include_lock_excluded=True
                        )
                        if item["dev_id"] == dev_id
                    ),
                    None,
                )
                tgt = next(
                    (
                        item["brightness"]
                        for item in zone.target_brightness
                        if item["dev_id"] == dev_id
                    ),
                    None,
                )
                light_type = (
                    "On Light" if dev_id in zone.on_lights_dev_ids else "Off Light"
                )
                excluded = ""
                if (
                    zone.current_lighting_period
                    and zone.has_dev_lighting_mapping_exclusion(
                        dev_id, zone.current_lighting_period
                    )
                ):
                    excluded = " (excluded from Lighting Period)"
                self.logger.info(
                    f"    {light_type} '{dev.name}': current={curr}, target={tgt}{excluded}"
                )
            self.logger.info(f"    locked: {zone.locked}")
            if zone.locked:
                self.logger.info(f"        expiration: {zone.lock_expiration_str}")

    def debug_zone_states(self) -> None:
        """
        Debug helper: for each enabled, unlocked, idle zone,
        compare current_lights_status to target_brightness on all
        on_lights_dev_ids + off_lights_dev_ids.  Log DEBUG on match,
        WARNING on mismatch.
        """
        for zone in self._config.zones:
            # skip if zone off, locked or already processing
            if not zone.enabled or zone.locked or zone.checked_out:
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
        for zone in self._config.zones:
            if getattr(zone, "_transition_timer", None):
                zone._transition_timer.cancel()
                zone._transition_timer = None
            if getattr(zone, "_lock_timer", None):
                zone._lock_timer.cancel()
                zone._lock_timer = None
