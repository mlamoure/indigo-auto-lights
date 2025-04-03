import threading

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

    def process_zone(self, zone: Zone, orig_dev: indigo.Device, new_dev: indigo.Device) -> bool:
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
            indigo.server.log(
                "auto_lights script DEBUG for Zone '" + zone.name + "':   processing."
            )

        if not zone.enabled:
            if debug:
                indigo.server.log(
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
                    indigo.server.log(
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
                and zone.use_timed_brightness
            ):

                zone.calculate_target_brightness()
                action_reason = "the requisite conditions have been met: presence is detected for a OnOffZone, the zone is dark, and we are using Timed Brightness Mode"
            elif (
                zone.current_lighting_period.mode == "OnOffZone"
                and zone.has_presence_detected()
                and zone.is_dark()
                and not zone.use_timed_brightness
            ):
                zone.target_brightness = 100
                action_reason = "the requisite conditions have been met: presence is detected for a OnOffZone, the zone is dark, and we are NOT using Timed Brightness Mode"
            elif not zone.has_presence_detected():
                zone.target_brightness = 0
                action_reason = "presence is not detected for a OnOffZone or OffZone"
            elif not zone.is_dark() and zone.enforce_off != "presenceOnly":
                zone.target_brightness = 0
                action_reason = "the minimum room luminance has been met"

        ################################################################
        # Special rules
        ################################################################

        if (
            zone.current_lighting_period is not None
            and self._config.someone_home
            and not self._config.gone_to_bed
        ):
            zone.run_special_rules()

        ################################################################
        # Save and write log
        ################################################################
        if zone.has_brightness_changes():
            indigo.server.log(
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
                indigo.server.log(
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

        if self._config.debug:
            indigo.server.log(debug_str)

        return True

    def process_device_change(orig_dev: indigo.Device, diff: dict) -> bool:

        # First, iterate through each self._zone

            # For each zone, call has_device(orig_dev.id)
                # if this returns "on_lights_dev_ids" or "off_lights_dev_ids" then
                    # if the zone.current_lights_status == target_brightness
                        # Note: this likely means that the plugin made the change.
                        # return
                    # else
                        # This likely means it was changed outside of hte plugin, and so needs to be a lock
                        # set zone.lock = True

                # if reutrns presence_id or luminance_id
                    # process the change


