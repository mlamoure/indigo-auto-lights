import threading
from typing import List
import logging

from .auto_lights_config import AutoLightsConfig
from .zone import Zone

try:
    import indigo
except ImportError:
    pass


class AutoLightsAgent:
    def __init__(self, config: AutoLightsConfig) -> None:
        self._config = config
        self._zones = []
        self.logger = logging.getLogger("com.vtmikel.autolights.AutoLightsAgent")

    def process_zone(self, zone: Zone) -> bool:
        """
        Main automation function that processes a series of lighting zones.

        Args:
            zone (Zone): A Zone object to process

        Returns:
            bool: Whether the zone was processed.
        """
        debug_str = ""
        debug = False

        if not self._config.enabled:
            return False

        if debug:
            self.logger.info(
                "auto_lights script DEBUG for Zone '" + zone.name + "':   processing."
            )

        if not zone.enabled:
            if debug:
                self.logger.info(
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
                if debug:
                    indigo.server.log(
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

            # Even though there are no active periods, we want to pass if there is no one home or the house is asleep so that the lights will be turned off.
            if not self._config.someone_home or self._config.gone_to_bed:
                if debug:
                    indigo.server.log(
                        "auto_lights script DEBUG for Zone '"
                        + zone.name
                        + "': outside of applicable time periods for this zone, but continuing because there is no one home / gone to bed."
                    )
                # pass
            else:
                if debug:
                    self.logger.info(
                        "auto_lights script DEBUG for Zone '"
                        + zone.name
                        + "': outside of applicable time periods for this zone."
                    )
                zone.check_in()
                return False

        ################################################################
        # Zone execution logic (Where we decide what changes, if any, need to be made)
        ################################################################

        action_reason = ""
        if not self._config.someone_home:
            zone.target_brightness = 0
            action_reason = "no one is home"
        elif zone.turn_off_while_sleeping and self._config.gone_to_bed:
            zone.target_brightness = 0
            action_reason = "house is asleep"
        elif zone.current_lighting_period is not None:
            if (
                zone.current_lighting_period.mode == "OnOffZone"
                and zone.has_presence_detected()
                and zone.is_dark()
            ):

                zone.calculate_target_brightness()
                action_reason = "the requisite conditions have been met: presence is detected for a OnOffZone, the zone is dark, and we are using Timed Brightness Mode"
            elif (
                zone.current_lighting_period.mode == "OnOffZone"
                and zone.has_presence_detected()
                and zone.is_dark()
            ):
                zone.target_brightness = 100
                action_reason = "the requisite conditions have been met: presence is detected for a OnOffZone, the zone is dark, and we are NOT using Timed Brightness Mode"
            elif not zone.has_presence_detected():
                zone.target_brightness = 0
                action_reason = "presence is not detected for a OnOffZone or OffZone"

        ################################################################
        # Save and write log
        ################################################################
        if zone.has_brightness_changes():
            self.logger.info(
                "auto_lights script for Zone '"
                + zone.name
                + "': processing change to "
                + zone.last_changed_by
                + " (action reason: "
                + action_reason
                + ") : "
            )

            zone.save_brightness_changes()

        else:
            if self._config.debug:
                self.logger.info(
                    "auto_lights script for Zone '"
                    + zone.name
                    + "': no changes to make, checked in"
                )

                if hasattr(zone, "special_rules_adjustment"):
                    indigo.server.log("       " + zone.special_rules_adjustment)

            zone.check_in()

        ###### END ZONE LOOP #######


        ################################################################
        # Debug
        ################################################################

        if self.debug:
            self.logger.info(debug_str)

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
        for zone in self._zones:
            device_prop = zone.has_device(orig_dev.id)
            if device_prop in ["on_lights_dev_ids", "off_lights_dev_ids"]:
                if zone.current_lights_status != zone.target_brightness:
                    zone.locked = True
                    processed.append(zone)
            elif device_prop in ["presence_dev_ids", "luminance_dev_ids"]:
                if self.process_zone(zone):
                    processed.append(zone)

        return processed

    def process_variable_change(self, orig_var: indigo.Variable, new_var: indigo.Variable) -> List[Zone]:
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
        for zone in self._zones:
            if zone.has_variable(orig_var.id):
                if self.process_zone(zone):
                    processed.append(zone)

        return processed
