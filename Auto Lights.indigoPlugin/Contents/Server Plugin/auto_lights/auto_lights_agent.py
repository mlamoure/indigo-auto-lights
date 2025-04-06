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
        self.logger = logging.getLogger("com.vtmikel.autolights.AutoLightsAgent")

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
            "auto_lights script DEBUG for Zone '" + zone.name + "':   processing."
        )

        if not zone.enabled:
            self.logger.debug(
                "auto_lights script DEBUG for Zone '"
                + zone.name
                + "': auto lights is disabled for this zone."
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
                    "auto_lights script for Zone '"
                    + zone.name
                    + "': zone is locked until "
                    + str(zone.lock_expiration)
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
            self.logger.debug(
                "auto_lights script for Zone '"
                + zone.name
                + "': no changes to make, checked in"
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
        for zone in self._config._zones:
            device_prop = zone.has_device(orig_dev.id)
            if device_prop in ["on_lights_dev_ids", "off_lights_dev_ids"]:
                if zone.current_lights_status != zone.target_brightness:
                    zone.locked = True
                    processed.append(zone)
            elif device_prop in ["presence_dev_id", "luminance_dev_ids"]:
                if self.process_zone(zone):
                    processed.append(zone)

        return processed

    def process_all_zones(self) -> None:
        """
        Loop through each zone in the agent's configuration and process each zone.
        """
        for zone in self._config._zones:
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
        for zone in self._config._zones:
            if zone.has_variable(orig_var.id):
                if self.process_zone(zone):
                    processed.append(zone)

        return processed
