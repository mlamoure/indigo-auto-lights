import logging
from typing import List

from .auto_lights_config import AutoLightsConfig
from .zone import Zone

try:
    import indigo
except ImportError:
    pass


class AutoLightsAgent:
    def __init__(self, config: AutoLightsConfig) -> None:
        self._config = config
        self.logger = logging.getLogger("Plugin")

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

        self.logger.debug(
            f"[AutoLightsAgent.process_zone] Zone '{zone.name}': processing: enabled={zone.enabled}, current_lights_status={zone.current_lights_status}"
        )

        if not zone.enabled:
            self.logger.debug(
                f"[AutoLightsAgent.process_zone] Zone '{zone.name}': auto lights is disabled for this zone."
            )
            return False

        ################################################################
        # Lock logic
        ################################################################
        if zone.lock_enabled and zone.locked:

            if not zone.has_presence_detected() and zone.unlock_when_no_presence:
                zone.reset_lock("no longer presence in zone")
            else:
                self.logger.debug(
                    f"[AutoLightsAgent.process_zone] Zone '{zone.name}': zone is locked until {zone.lock_expiration}"
                )
                return False

        ################################################################
        # Period logic
        ################################################################
        if zone.lighting_periods is None:
            return False

        ################################################################
        # Zone execution logic (Where we decide what changes, if any, need to be made)
        ################################################################

        action_reason = ""

        # Check global behavior variables
        for behavior_var in self._config.global_behavior_variables:
            var_id = behavior_var.get("var_id")
            var_value = behavior_var.get("var_value")

            if var_id and var_value:
                try:
                    current_value = str(indigo.variables[var_id].value)
                    if current_value.lower() == var_value.lower():
                        zone.target_brightness = 0
                        action_reason = f"global behavior variable {indigo.variables[var_id].name} matches value '{var_value}'"
                        break
                except (KeyError, ValueError):
                    self.logger.debug(f"Invalid global behavior variable ID: {var_id}")

        # Next, look to the target_brightness
        if not action_reason and zone.current_lighting_period is not None:
            if (
                zone.current_lighting_period.mode == "On and Off"
                and zone.has_presence_detected()
                and zone.is_dark()
            ):
                zone.calculate_target_brightness()
                action_reason = (
                    "Presence is detected for a On and Off Zone, the zone is dark"
                )

            elif not zone.has_presence_detected():
                zone.target_brightness = 0
                action_reason = "presence is not detected"

        ################################################################
        # Save and write log
        ################################################################
        if zone.has_brightness_changes():
            self.logger.info(
                "[AutoLightsAgent.process_zone] Zone '"
                + zone.name
                + "': processing change to "
                + zone.last_changed_by
                + " (action reason: "
                + action_reason
                + ") : "
            )

            zone.save_brightness_changes()

        else:
            self.logger.debug(
                f"[AutoLightsAgent.process_zone] Zone '{zone.name}': no changes to make, checked in"
            )

            zone.check_in()

        ###### END ZONE LOOP #######

        ################################################################
        # Debug
        ################################################################

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
                self.logger.debug(
                    f"[AutoLightsAgent.process_device_change] has_device: zone {zone.name}; change from {orig_dev.name}; zone property: {device_prop}"
                )
                if not zone.locked and zone.has_lock_occured():
                    zone.locked = True
                    self.logger.info(
                        f"[AutoLightsAgent.process_device_change] New lock created for zone '{zone.name}'; device change from '{orig_dev.name}'; lock duration: {zone.lock_duration} seconds; extend_lock_when_active: {zone.extend_lock_when_active}"
                    )
                    processed.append(zone)
            elif device_prop in ["presence_dev_ids", "luminance_dev_ids"]:
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

        For each zone in the agent:
          - Call zone.has_variable(new_var.id)
            - If True, then return self.process_zone(zone)
          - return False

        Returns:
            List[Zone]: List of Zone's processed
        """

        processed = []
        for zone in self._config.zones:
            if zone.has_variable(orig_var.id):
                self.logger.debug(
                    f"has_variable: var_id {indigo.variables[orig_var.id].name}"
                )
                if self.process_zone(zone):
                    processed.append(zone)

        return processed
