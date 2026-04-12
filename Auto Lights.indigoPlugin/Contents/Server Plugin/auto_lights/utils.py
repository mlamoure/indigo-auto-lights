"""
Utility Functions - Auto Lights Plugin

This module provides utility functions for device control and state verification:

- Device control with brief settle-and-confirm for state verification
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
        elif hasattr(device, "brightness"):
            result = int(device.brightness) == target_level
        elif "brightness" in getattr(device, "states", {}):
            result = int(device.states["brightness"]) == target_level
        else:
            # Cannot confirm state — assume NOT at target so command is sent
            result = False
    logger.log(5, f"_check_confirm result for '{device.name}': {result}")
    return result


def is_device_at_target(device, desired_brightness) -> bool:
    """Return True if the given device is currently at the desired target.

    Accepts the same shape as the entries stored in zone.target_brightness
    (an int 0..100 or a bool). Wraps _check_confirm so callers don't have
    to translate between the int/bool target representations themselves.
    """
    if isinstance(desired_brightness, bool):
        target_level = 100 if desired_brightness else 0
        target_bool = desired_brightness
    else:
        target_level = int(desired_brightness)
        target_bool = None
    try:
        return _check_confirm(device, target_level, target_bool)
    except Exception:
        return False


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
) -> bool:
    """
    Send a command to update an Indigo device and wait briefly for confirmation.

    Sends the command once and polls for up to 2 seconds. Indigo handles
    protocol-level retries; the post-write re-evaluation in
    save_brightness_changes() handles any state changes that arrive later.

    Returns True if the device confirmed reaching the target state,
    False if the settle timeout expired without confirmation.
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

    # Pre-check: skip if device is already at target
    if _check_confirm(device, target, target_bool):
        logger.debug(
            f"send_to_indigo: '{device.name}' already at target {target}, skipping"
        )
        return True

    # Single send — no application-level retries
    _send_command(device_id, target, target_bool)

    # Brief settle — wait up to 2s for confirmation
    confirmed = False
    max_settle = 2.0
    while (time.monotonic() - start) < max_settle:
        time.sleep(0.05)
        if _check_confirm(indigo.devices[device_id], target, target_bool):
            confirmed = True
            break

    total_time = round(time.monotonic() - start, 2)
    if confirmed:
        logger.debug(f"send_to_indigo: '{device.name}' confirmed in {total_time}s")
    else:
        logger.debug(
            f"send_to_indigo: '{device.name}' did NOT confirm after {total_time}s"
        )
    return confirmed
