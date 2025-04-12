import logging
import time

try:
    import indigo
except ImportError:
    pass

logger = logging.getLogger("Plugin")


def send_to_indigo(
    device_id: int, desired_brightness: int | bool, perform_confirm: bool
) -> None:
    """
    Send a command to update an Indigo device (brightness or switch state)
    and ensure it's confirmed within a limit.

    This function retries the command until the device state matches the desired
    value or the maximum wait limit is reached. If 'perform_confirm' is False,
    confirmation is skipped after the first attempt.

    Args:
        device_id (int): The Indigo device ID to be changed.
        desired_brightness (int | bool): The target brightness (0-100) for dimmer
            devices or True/False for switches.
    """
    start_timestamp = time.time()
    is_confirmed = False
    iteration_counter = 0
    command_attempts = 0

    pause_between_actions = 0.15
    max_wait_seconds = 35
    check_interval = 1.0
    remaining_wait = max_wait_seconds

    senseme_plugin_id = "com.pennypacker.indigoplugin.senseme"
    device = indigo.devices[device_id]
    is_fan_light = device.pluginId == senseme_plugin_id
    sense_plugin = indigo.server.getPlugin(senseme_plugin_id)

    action_description = ""

    while not is_confirmed and (time.time() - start_timestamp) <= max_wait_seconds:
        # Check device state against desired brightness.
        if isinstance(device, indigo.DimmerDevice):
            is_confirmed = device.brightness == desired_brightness
        elif isinstance(device, indigo.RelayDevice):
            if not isinstance(desired_brightness, bool):
                desired_brightness = desired_brightness == 100
            is_confirmed = device.onState == desired_brightness
        elif device.pluginId == senseme_plugin_id:
            current_brightness = int(device.states.get("brightness", 0))
            target = (
                int(desired_brightness)
                if isinstance(desired_brightness, bool)
                else desired_brightness
            )
            is_confirmed = current_brightness == target

        # Skip confirmation if already attempted and not required.
        if not is_confirmed and command_attempts > 0 and not perform_confirm:
            is_confirmed = True

        if not is_confirmed:
            if iteration_counter % 8 == 0:
                if command_attempts > 0:
                    logger.info(
                        f"... not yet confirmed changes to '{device.name}'. Retrying."
                    )

                if is_fan_light or isinstance(device, indigo.DimmerDevice):
                    current_brightness = (
                        int(device.states.get("brightness", 0))
                        if is_fan_light
                        else device.brightness
                    )
                    if isinstance(desired_brightness, bool):
                        desired_brightness = 100 if desired_brightness else 0

                    if desired_brightness == 0 and current_brightness == 100:
                        action_description = "turning off"
                    elif desired_brightness == 100 and current_brightness == 0:
                        action_description = "turning on"
                    elif desired_brightness > current_brightness:
                        action_description = "increasing"
                    else:
                        action_description = "decreasing"

                    if action_description in ("turning on", "turning off"):
                        logger.info(f"{action_description} '{device.name}'")
                    else:
                        logger.info(
                            f"    {action_description} brightness for '{device.name}' "
                            f"from {current_brightness}% to {desired_brightness}%"
                        )

                    if is_fan_light:
                        sense_plugin.executeAction(
                            "fanLightBrightness",
                            deviceId=device_id,
                            props={"lightLevel": str(desired_brightness)},
                        )
                    else:
                        indigo.dimmer.setBrightness(
                            device_id, value=desired_brightness, delay=0
                        )

                elif isinstance(device, indigo.RelayDevice):
                    if not isinstance(desired_brightness, bool):
                        desired_brightness = desired_brightness == 100

                    if device.onState and not desired_brightness:
                        action_description = "turning off"
                        indigo.device.turnOff(device_id, delay=0)
                    elif not device.onState and desired_brightness:
                        action_description = "turning on"
                        indigo.device.turnOn(device_id, delay=0)

                    if action_description:
                        logger.info(f"    {action_description} '{device.name}'")

                time.sleep(pause_between_actions)
                device = indigo.devices[device_id]
                command_attempts += 1

            elif iteration_counter % 4 == 0:
                logger.info(
                    f"    .... not yet confirmed changes to '{device.name}'. Waiting and querying status. "
                    f"         Max additional wait time: {remaining_wait} more seconds."
                )
                check_interval = 2.0
                time.sleep(check_interval)
                device = indigo.devices[device_id]
                time.sleep(1)
                indigo.device.statusRequest(device_id, suppressLogging=True)
            else:
                if iteration_counter > 1:
                    logger.info(
                        f"   ... not yet confirmed changes to '{device.name}'. Waiting up to "
                        f"       {remaining_wait} more seconds."
                    )
                time.sleep(check_interval)
                device = indigo.devices[device_id]

        iteration_counter += 1
        elapsed_time = time.time() - start_timestamp
        remaining_wait = int(round(max_wait_seconds - elapsed_time, 1))

    total_time = round(time.time() - start_timestamp, 2)

    if action_description and not is_confirmed:
        logger.info(
            f"    ... COULD NOT CONFIRM change to '{device.name}' (time: {total_time} seconds, "
            f"        attempts: {command_attempts})"
        )
    else:
        logger.debug(
            f"        ... confirmed change to '{device.name}' (time: {total_time} seconds, "
            f"            attempts: {command_attempts})"
        )
