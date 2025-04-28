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
    Send a command to update an Indigo device and optionally confirm the change.

    Sends a brightness change command for dimmers or on/off for switches, then
    optionally verifies that the device state matches the desired value within
    a timeout, retrying or requesting status updates as needed.

    Args:
        device_id (int): ID of the Indigo device to control.
        desired_brightness (int | bool): Target brightness (0-100) for dimmers, or True/False for relays.
        perform_confirm (bool): If True, retry and confirm state changes until timeout; if False, send once.
    """
    # Indentation for nested log messages
    indent = "      "
    start_time = time.monotonic()
    is_confirmed = False
    iteration_counter = 0
    command_attempts = 0

    pause_between_actions = 0.15
    max_wait_seconds = 15  # shrink confirmation window from 35 s to 15 s
    check_interval = 1.0
    remaining_wait = max_wait_seconds
    status_request_count = 0  # only allow up to two statusRequest calls

    senseme_plugin_id = "com.pennypacker.indigoplugin.senseme"
    device = indigo.devices[device_id]
    is_fan_light = device.pluginId == senseme_plugin_id
    sense_plugin = indigo.server.getPlugin(senseme_plugin_id)

    action_description = ""
    # Normalize desired brightness once
    if isinstance(desired_brightness, bool):
        target_bool = desired_brightness
        target_level = 100 if desired_brightness else 0
    else:
        target_bool = None
        target_level = desired_brightness

    # Retry loop: send commands and check status until confirmed or timeout
    while not is_confirmed and (time.monotonic() - start_time) <= max_wait_seconds:
        # Check device state against desired brightness.
        if isinstance(device, indigo.DimmerDevice):
            is_confirmed = device.brightness == target_level
        elif isinstance(device, indigo.RelayDevice):
            want_state = (
                target_bool if target_bool is not None else (target_level == 100)
            )
            is_confirmed = device.onState == want_state
        elif device.pluginId == senseme_plugin_id:
            current_brightness = int(device.states.get("brightness", 0))
            is_confirmed = current_brightness == target_level

        # Skip confirmation if already attempted and not required.
        if not is_confirmed and command_attempts > 0 and not perform_confirm:
            is_confirmed = True

        if not is_confirmed:
            if iteration_counter % 8 == 0:
                if command_attempts > 0:
                    logger.info(
                        f"{indent}{indent}... not yet confirmed changes to '{device.name}'. Retrying."
                    )

                if is_fan_light or isinstance(device, indigo.DimmerDevice):
                    current_brightness = (
                        int(device.states.get("brightness", 0))
                        if is_fan_light
                        else device.brightness
                    )
                    # Determine action description
                    if target_level == 0 and current_brightness > 0:
                        action_description = "turning off"
                    elif target_level == 100 and current_brightness == 0:
                        action_description = "turning on"
                    elif target_level > current_brightness:
                        action_description = "increasing"
                    else:
                        action_description = "decreasing"

                    # Log action with emoji
                    if action_description in ("turning on", "turning off"):
                        emoji = "💡" if action_description == "turning on" else "⏻"
                        logger.info(
                            f"{indent}{emoji} {action_description} '{device.name}'"
                        )
                    else:
                        emoji = "🔼" if action_description == "increasing" else "🔽"
                        logger.info(
                            f"{indent}{emoji} {action_description} brightness for '{device.name}' "
                            f"from {current_brightness}% to {target_level}%"
                        )

                    # Send command
                    if is_fan_light:
                        sense_plugin.executeAction(
                            "fanLightBrightness",
                            deviceId=device_id,
                            props={"lightLevel": str(target_level)},
                        )
                    else:
                        indigo.dimmer.setBrightness(
                            device_id, value=target_level, delay=0
                        )

                elif isinstance(device, indigo.RelayDevice):
                    want_state = target_level == 100

                    if device.onState and not want_state:
                        action_description = "turning off"
                        indigo.device.turnOff(device_id, delay=0)
                    elif not device.onState and want_state:
                        action_description = "turning on"
                        indigo.device.turnOn(device_id, delay=0)

                    if action_description:
                        emoji = "💡" if action_description == "turning on" else "⏻"
                        logger.info(
                            f"{indent}{emoji} {action_description} '{device.name}'"
                        )

                time.sleep(pause_between_actions)
                device = indigo.devices[device_id]
                command_attempts += 1

            elif iteration_counter % 4 == 0 and status_request_count < 2:
                logger.info(
                    f"{indent}{indent}.... not yet confirmed changes to '{device.name}'. Waiting and querying status. "
                    f"Max additional wait time: {remaining_wait} more seconds."
                )
                check_interval = 2.0
                time.sleep(check_interval)
                device = indigo.devices[device_id]
                time.sleep(1)
                indigo.device.statusRequest(device_id, suppressLogging=True)
                status_request_count += 1
            else:
                if iteration_counter > 1:
                    logger.info(f"{indent}{indent}... not yet confirmed changes to '{device.name}'. Waiting up to {remaining_wait} more seconds.")
                time.sleep(check_interval)
                device = indigo.devices[device_id]

        iteration_counter += 1
        elapsed_time = time.monotonic() - start_time
        remaining_wait = int(round(max_wait_seconds - elapsed_time, 1))

    total_time = round(time.monotonic() - start_time, 2)

    if action_description and not is_confirmed:
        logger.info(
            f"{indent}{indent}... COULD NOT CONFIRM change to '{device.name}' (time: {total_time} seconds, "
            "f{indent}{indent}     attempts: {command_attempts})"
        )
    else:
        logger.debug(
            f"{indent}{indent}... confirmed change to '{device.name}' (time: {total_time} seconds, "
            f"{indent}{indent}    attempts: {command_attempts})"
        )
