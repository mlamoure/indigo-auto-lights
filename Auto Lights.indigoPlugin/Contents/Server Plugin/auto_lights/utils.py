import logging
import time

try:
    import indigo
except ImportError:
    pass

logger = logging.getLogger("Plugin")


def _check_confirm(device, target_level, target_bool) -> bool:
    """Return True if the device's state matches the target values."""
    logger.debug(
        f"_check_confirm called for '{device.name}' with target_level={target_level}, target_bool={target_bool}"
    )
    if isinstance(device, indigo.DimmerDevice):
        result = device.brightness == target_level
    elif isinstance(device, indigo.RelayDevice):
        want = target_bool if target_bool is not None else (target_level == 100)
        result = device.onState == want
    else:
        senseme = "com.pennypacker.indigoplugin.senseme"
        if device.pluginId == senseme:
            result = int(device.states.get("brightness", 0)) == target_level
        else:
            result = True
    logger.debug(f"_check_confirm result for '{device.name}': {result}")
    return result


def _send_command(device_id, target_level, target_bool) -> None:
    """Send the appropriate Indigo command for the desired state."""
    device = indigo.devices[device_id]
    senseme = "com.pennypacker.indigoplugin.senseme"
    is_fan = device.pluginId == senseme
    logger.debug(
        f"_send_command called for '{device.name}' (id={device_id}) with target_level={target_level}, target_bool={target_bool}"
    )
    if is_fan or isinstance(device, indigo.DimmerDevice):
        if is_fan:
            sense_plugin = indigo.server.getPlugin(senseme)
            sense_plugin.executeAction(
                "fanLightBrightness",
                deviceId=device_id,
                props={"lightLevel": str(target_level)},
            )
            logger.debug(
                f"_send_command: senseme fanLightBrightness for '{device.name}' -> {target_level}"
            )
        else:
            indigo.dimmer.setBrightness(device_id, value=target_level, delay=0)
            logger.debug(
                f"_send_command: dimmer.setBrightness for '{device.name}' -> {target_level}"
            )
    elif isinstance(device, indigo.RelayDevice):
        want_on = target_bool if target_bool is not None else (target_level == 100)
        if want_on:
            indigo.device.turnOn(device_id, delay=0)
            logger.debug(f"_send_command: turned ON '{device.name}'")
        else:
            indigo.device.turnOff(device_id, delay=0)
            logger.debug(f"_send_command: turned OFF '{device.name}'")


def send_to_indigo(
    device_id: int,
    desired_brightness: int | bool,
) -> None:
    """
    Send a command to update an Indigo device with retries, status requests, and timed logs.
    """
    indent = "      "
    start = time.monotonic()
    # Capture old state for logging purposes
    device = indigo.devices[device_id]
    old_level = None
    old_state = None
    if isinstance(device, indigo.DimmerDevice):
        old_level = device.brightness
    elif isinstance(device, indigo.RelayDevice):
        old_state = device.onState
    # Determine numeric target and bool for relays
    target_bool = None
    if isinstance(desired_brightness, bool):
        target_bool = desired_brightness
        target = 100 if desired_brightness else 0
    else:
        target = desired_brightness

    # Time‐based intervals
    last_send = last_log = start
    max_wait = 21.0
    send_interval = 7.0
    log_interval = 3.0

    # Initial send
    _send_command(device_id, target, target_bool)

    confirmed = False
    while not confirmed and (time.monotonic() - start) < max_wait:
        now = time.monotonic()
        device = indigo.devices[device_id]
        confirmed = _check_confirm(device, target, target_bool)
        if confirmed:
            break

        # resend commands at defined interval
        if now - last_send >= send_interval:
            _send_command(device_id, target, target_bool)
            last_send = now

        # always log how much time remains
        if now - last_log >= log_interval:
            remaining = int(max_wait - (now - start))
            last_log = now

        # brief sleep to avoid burning CPU
        time.sleep(0.05)

    total = round(time.monotonic() - start, 2)
    if confirmed:
        # Log detailed change based on device type
        if isinstance(device, indigo.DimmerDevice) and old_level is not None:
            if target > old_level:
                emoji = "🔆"
            elif target < old_level:
                emoji = "🔻"
        elif isinstance(device, indigo.RelayDevice) and old_state is not None:
            if not target_bool:
                emoji = "🔌"
            else:
                emoji = "💡"
            action = "turned on" if target_bool else "turned off"
        else:
            # Fallback logging
    else:
