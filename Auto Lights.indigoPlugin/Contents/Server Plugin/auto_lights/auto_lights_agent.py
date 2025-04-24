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

    def process_zone(self, zone: Zone) -> bool:
        """
        Main automation function that processes a series of lighting zones.

        Args:
            zone (Zone): A Zone object to process

        Returns:
            bool: Whether the zone was processed.
        """
        if not self._config.enabled:
            return False

        self._debug_log(
            f"Processing: enabled={zone.enabled}, current_lights_status={zone.current_lights_status}"
        )

        if not zone.enabled:
            self._debug_log(f"Zone is disabled")
            return False

        zone.check_out()
        ################################################################
        # Lock logic
        ################################################################
        if zone.lock_enabled and zone.locked:
            self._debug_log(f"Zone is locked until {zone.lock_expiration}")
            zone.check_in()
            return False

        ################################################################
        # Period logic
        ################################################################
        if zone.lighting_periods is None:
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

        # Next, look to the target_brightness
        if not global_lights_off and zone.current_lighting_period is not None:
            action_reason = zone.calculate_target_brightness()
            self.logger.debug(
                f"AutoLightsAgent: Zone '{zone.name}' brightness update: {action_reason}. Target brightness: {zone.target_brightness}"
            )

        ################################################################
        # Save and write log
        ################################################################
        if zone.has_brightness_changes():
            self.logger.info(
                "Zone '"
                + zone.name
                + "': processing change to "
                + zone.last_changed_by
                + " (action reason: "
                + action_reason
                + ") : "
            )

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
                    continue

                self._debug_log(
                    f"Change from {orig_dev.name}; zone property: {device_prop}"
                )

                if zone.lock_enabled and not zone.locked and zone.has_lock_occurred():
                    self.logger.info(
                        f"New lock created for zone '{zone.name}'; device change from '{orig_dev.name}'."
                    )
                    self.logger.info("  Lock Details:")
                    self.logger.info(f"    lock_duration: {zone.lock_duration} minutes")
                    self.logger.info(f"    lock_expiration: {zone.lock_expiration_str}")
                    self.logger.info(
                        f"    extend_lock_when_active: {zone.extend_lock_when_active}"
                    )
                    if zone.extend_lock_when_active:
                        self.logger.info(
                            f"    lock_extension_duration: {zone.lock_extension_duration} minutes"
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
                        self._timers[zone.name] = timer
                        timer.start()
            elif device_prop in ["presence_dev_ids", "luminance_dev_ids"]:
                if device_prop == "presence_dev_ids" and zone.unlock_when_no_presence and not zone.has_presence_detected():
                    self.reset_locks(zone.name, "no presence detected and `unlock_when_no_presence` is set for this Zone")
                if self.process_zone(zone):
                    processed.append(zone)

        return processed

    def process_all_zones(self) -> None:
        """
        Loop through each zone in the agent's configuration and process each zone.
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
                    zone.reset_lock(reason)
                    self.process_zone(zone)
                    if zone.name in self._timers:
                        self._timers[zone.name].cancel()
                        del self._timers[zone.name]
        else:
            for zone in self._config.zones:
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
        Iterate through each zone and log if the zone is locked.
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
