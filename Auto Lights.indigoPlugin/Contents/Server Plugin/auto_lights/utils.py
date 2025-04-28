import logging
import time

try:
    import indigo
except ImportError:
    pass

logger = logging.getLogger("Plugin")

def _check_confirm(device, target_level, target_bool) -> bool:
    """Return True if the device's state matches the target values."""
    if isinstance(device, indigo.DimmerDevice):
        return device.brightness == target_level
    if isinstance(device, indigo.RelayDevice):
        want = target_bool if target_bool is not None else (target_level == 100)
        return device.onState == want
    senseme = "com.pennypacker.indigoplugin.senseme"
    if device.pluginId == senseme:
        return int(device.states.get("brightness", 0)) == target_level
    return True

def _send_command(device_id, target_level, target_bool) -> None:
    """Send the appropriate Indigo command for the desired state."""
    device = indigo.devices[device_id]
    senseme = "com.pennypacker.indigoplugin.senseme"
    is_fan = device.pluginId == senseme
    if is_fan or isinstance(device, indigo.DimmerDevice):
        if is_fan:
            sense_plugin = indigo.server.getPlugin(senseme)
            sense_plugin.executeAction(
                "fanLightBrightness",
                deviceId=device_id,
                props={"lightLevel": str(target_level)},
            )
        else:
            indigo.dimmer.setBrightness(device_id, value=target_level, delay=0)
    elif isinstance(device, indigo.RelayDevice):
        want_on = target_bool if target_bool is not None else (target_level == 100)
        if want_on:
            indigo.device.turnOn(device_id, delay=0)
        else:
            indigo.device.turnOff(device_id, delay=0)


def send_to_indigo(
    device_id: int,
    desired_brightness: int | bool,
    perform_confirm: bool,
) -> None:
    """
    Send a command to update an Indigo device with retries, status requests, and timed logs.
    """
    indent = "      "
    start = time.monotonic()
    # Determine numeric target and bool for relays
    target_bool = None
    if isinstance(desired_brightness, bool):
        target_bool = desired_brightness
        target = 100 if desired_brightness else 0
    else:
        target = desired_brightness

    # Time‐based intervals
    last_send = last_status = last_log = start
    max_wait = 15.0
    send_interval = 0.15
    status_interval = 2.0
    log_interval = 5.0

    # Initial send
    _send_command(device_id, target, target_bool)

    confirmed = False
    while not confirmed and (time.monotonic() - start) < max_wait:
        now = time.monotonic()
        device = indigo.devices[device_id]
        confirmed = _check_confirm(device, target, target_bool)
        if confirmed or not perform_confirm:
            break

        if now - last_send >= send_interval:
            _send_command(device_id, target, target_bool)
            last_send = now

        if now - last_status >= status_interval:
            try:
                indigo.device.statusRequest(device_id, suppressLogging=True)
            except Exception:
                pass
            last_status = now

        if now - last_log >= log_interval:
            remaining = int(max_wait - (now - start))
            logger.info(f"{indent}⏳ Not yet confirmed change to '{device.name}'. {remaining} seconds remaining.")
            last_log = now

        time.sleep(0.05)

    total = round(time.monotonic() - start, 2)
    if confirmed:
        logger.debug(f"{indent}✅ Confirmed change to '{device.name}' in {total}s")
    else:
        logger.info(f"{indent}❌ Could not confirm change to '{device.name}' after {total}s")
