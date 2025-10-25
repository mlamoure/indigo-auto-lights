"""
Utility Functions - Auto Lights Plugin

This module provides utility functions for device control and state verification:

- Device control with retry logic for unreliable devices
- State confirmation to ensure devices reach target states
- Brightness and on/off control for various device types (dimmers, relays, SenseME fans)
- Logging for device control operations

The functions in this module handle low-level device interaction and provide
a consistent interface for controlling different types of Indigo devices.
"""

import logging
import time

try:
    import indigo
except ImportError:
    pass

logger = logging.getLogger("Plugin")


def _check_confirm(device, target_level, target_bool) -> bool:
    """Return True if the device's state matches the target values."""
    logger.log(
        5,
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
    logger.log(5, f"_check_confirm result for '{device.name}': {result}")
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
    Send a command to update an Indigo device with retries.
    """
    start = time.monotonic()
    device = indigo.devices[device_id]

    # Determine numeric target and bool for relays
    if isinstance(desired_brightness, bool):
        target_bool = desired_brightness
        target = 100 if desired_brightness else 0
    else:
        target_bool = None
        target = desired_brightness

    # Retry settings
    max_wait = 21.0
    send_interval = 7.0
    last_send = start

    # Initial send
    _send_command(device_id, target, target_bool)

    # Retry until confirmed or timeout
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= max_wait:
            break

        now = time.monotonic()
        if now - last_send >= send_interval:
            _send_command(device_id, target, target_bool)
            last_send = now

        if _check_confirm(indigo.devices[device_id], target, target_bool):
            break

        time.sleep(0.05)

    total_time = round(time.monotonic() - start, 2)
    logger.debug(f"send_to_indigo: '{device.name}' completed in {total_time}s")
