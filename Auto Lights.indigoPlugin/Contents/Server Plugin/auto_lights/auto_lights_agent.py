import random
import threading
import time
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

    def process_zone(self, orig_zones: List[Zone]) -> int:
        """
        Main automation function that processes a series of lighting zones.

        Args:
            orig_zones (list): A list of Zone objects to evaluate for automation.

        Returns:
            int: The number of zones that actually ran automation logic.
        """
        debug_str = ""

        if not self._config.enabled:
            if self._config.debug:
                indigo.server.log(
                    "auto_lights script DEBUG: auto lights is disabled globally."
                )
            return 0

        if self._config.debug:
            debug_str = "\n\n auto_lights script DEBUG output: \n\n"
            debug_str = debug_str + " CONFIG: \n"
            debug_str = (
                debug_str
                + "       config.getTimedBrightness(): "
                + str(self._config.get_timed_brightness())
                + "\n"
            )
            debug_str = (
                debug_str
                + "       config.isDayTimeHours(): "
                + str(self._config.is_day_time_hours())
                + "\n"
            )
            debug_str = (
                debug_str + "       config.guestMode: " + str(self._config.guest_mode) + "\n"
            )

        threads = []
        for zone in zones:
            zone._config = self._config

            if self._config.debug:
                indigo.server.log(
                    "auto_lights script DEBUG for Zone '" + zone.name + "':   processing."
                )

            if not zone.enabled:
                if self._config.debug:
                    indigo.server.log(
                        "auto_lights script DEBUG for Zone '"
                        + zone.name
                        + "': auto lights is disabled for this zone."
                    )
                continue

            ################################################################
            # Checkout
            ################################################################
            if zone.checked_out:
                checkout_message = (
                    "auto_lights script for Zone '"
                    + zone.name
                    + "': was already checked out by another execution of this script.  Waiting for it to complete before proceeding..."
                )

                checkout_wait_start_time = time.time()
                sleep_time = (
                    random.randint(4, 51) / 40.0
                )  # random in case multiple processes are waiting for the same zone to check in.  This will order them.
                max_wait_time = 35.0  # maximum wait time in seconds.  Setting this earlier could result in inaccurate lock alerts.
                i = 0
                time_so_far = 0.0
                remaining = max_wait_time

                while zone.checked_out and time_so_far < max_wait_time:
                    if i > 0 and i % 3 == 0:
                        checkout_str = (
                            "\n"
                            + "      ... waiting for Zone '"
                            + zone.name
                            + "' to be checked in... will wait for up to "
                            + str(round(remaining, 0))
                            + " additional seconds before forcing a check-in.  Polling/Sleep time: "
                            + str(sleep_time)
                            + " seconds."
                        )

                    time.sleep(sleep_time)
                    time_so_far = round(time.time() - checkout_wait_start_time, 2)
                    remaining = max_wait_time - time_so_far
                    i = i + 1

                ### end checkout loop

                checkout_wait_end_time = time.time()
                checkout_wait_total_time = round(
                    checkout_wait_end_time - checkout_wait_start_time, 2
                )

                if zone.checked_out:
                    indigo.server.log(checkout_message)
                    indigo.server.log(
                        "      ... timed out waiting for Zone '"
                        + zone.name
                        + "' after "
                        + str(checkout_wait_total_time)
                        + " seconds.  Forcing check in...",
                        isError=True,
                    )
                    zone.force_check_in()
                elif checkout_wait_total_time > 1:
                    indigo.server.log(checkout_message)
                    indigo.server.log(
                        "      ... Zone '"
                        + zone.name
                        + "' is now checked in.  Total wait time of "
                        + str(checkout_wait_total_time)
                        + " seconds."
                    )

            # check out the zone
            zone.check_out()

            ################################################################
            # Lock logic
            ################################################################
            if zone.lock_enabled and zone.locked:

                if not zone.has_presence_detected() and zone.unlock_when_no_presence:
                    zone.reset_lock("no longer presence in zone")
                else:
                    if self._config.debug:
                        indigo.server.log(
                            "auto_lights script for Zone '"
                            + zone.name
                            + "': zone is locked until "
                            + str(zone.lock_expiration)
                        )
                    zone.check_in()
                    continue

            ################################################################
            # Period logic
            ################################################################
            if zone.lighting_periods is None:

                # Even though there are no active periods, we want to pass if there is no one home or the house is asleep so that the lights will be turned off.
                if not self._config.someone_home or self._config.gone_to_bed:
                    if self._config.debug:
                        indigo.server.log(
                            "auto_lights script DEBUG for Zone '"
                            + zone.name
                            + "': outside of applicable time periods for this zone, but continuing because there is no one home / gone to bed."
                        )
                    # pass
                else:
                    if self._config.debug:
                        indigo.server.log(
                            "auto_lights script DEBUG for Zone '"
                            + zone.name
                            + "': outside of applicable time periods for this zone."
                        )
                    zone.check_in()
                    continue

            ################################################################
            # Zone execution logic (Where we decide what changes, if any, need to be made)
            ################################################################
            zones_ran = zones_ran + 1

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
                    if self._config.is_day_time_hours():
                        # during the day, we adjust the target brightness based on the brightness of the room

                        # don't adjust some lights when they are already on (luminance brightness changes are disabled) for some zones
                        if (
                            zone.current_state_any_light_is_on
                            and not zone.adjust_brightness_when_active
                        ):
                            action_reason = "did not adjust brightness because lights are already on and adjustBrightnessWhenActive is off"
                        else:
                            action_reason = "the requisite conditions have been met: presence is detected for a OnOffZone, the zone is dark, and we are using Timed Brightness Mode with adjustments for the current brightness level"

                            # Check to see if Timed Brightness Adjustments are off, which only applies when lights are already on, and we don't wish to adjust the brightness further.
                            if (
                                not zone.target_brightness_all_off
                                and hasattr(zone, "use_timed_brightness_adjustments")
                                and not zone.use_timed_brightness_adjustments
                            ):
                                zone.target_brightness = zone.current_lights_status
                            else:
                                zone.target_brightness = abs(
                                    int(
                                        (1 - (zone.luminance / zone.minimum_luminance))
                                        * 100
                                    )
                                )
                    else:
                        zone.target_brightness = self._config.get_timed_brightness()
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

                if self._config.threading_enabled:
                    thread = threading.Thread(target=zone.save_brightness_changes, args=())
                    threads.append(thread)
                    thread.start()
                else:
                    zone.save_brightness_changes()

                if hasattr(zone, "special_rules_adjustment"):
                    indigo.server.log("       " + zone.special_rules_adjustment)
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

        # Wait for the threads to complete, re-join them together
        for thread in threads:
            thread.join()

        ################################################################
        # CheckIn
        ################################################################
        for zone in zones:
            if zone.checked_out:
                if self._config.debug:
                    indigo.server.log(
                        "auto_lights script for Zone '"
                        + zone.name
                        + "': completed and checked in"
                    )
                zone.check_in()

        ################################################################
        # Debug
        ################################################################

        if self._config.debug:
            for zone in zones:
                debug_str = (
                    debug_str
                    + zone.write_debug_output(self._config)
                    + "\n----------------------------------------\n"
                )

        if self._config.debug:
            indigo.server.log(debug_str)

        return zones_ran
