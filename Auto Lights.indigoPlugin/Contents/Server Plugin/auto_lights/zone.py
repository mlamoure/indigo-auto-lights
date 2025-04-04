import ast
import datetime
from typing import List, Union, Any, Optional

from . import utils
from .auto_lights_config import AutoLightsConfig
from .lighting_period import LightingPeriod

try:
    import indigo
except ImportError:
    pass


class Zone:
    """
    Represents an AutoLights zone, encompassing configuration, devices,
    lighting periods, and states for controlling lighting behavior.
    """

    def __init__(self, name: str, config: AutoLightsConfig):
        """
        Initialize a Zone instance.

        Args:
            name (str): The name of the zone.
            config (AutoLightsConfig): The global auto lights configuration.
        """
        # Zone identification
        self._name = name
        self._enabled = False
        self._enabled_var_id = None

        # Lighting periods configuration and saved target state for change detection
        self._lighting_periods = []
        self._current_lighting_period = None

        # Device lists for lights: devices to be turned on and off
        self._on_lights_dev_ids = []
        self._off_lights_dev_ids = []
        self._exclude_from_lock_dev_ids = []

        # Luminance
        self._luminance_dev_ids = []
        self._luminance = 0

        # List of device IDs reporting presence
        self._presence_dev_ids = []

        # Lumanance Behavior
        self._minimum_luminance = 10000
        self._minimum_luminance_var_id = None

        self._current_lights_status = []
        self._target_brightness = None
        self._target_brightness_all_off = None

        # Behavior
        self._adjust_brightness = False
        self._adjust_brightness_when_active = True
        self._perform_confirm = True
        self._lock_duration = None
        self._extend_lock_when_active = True
        self._turn_off_while_sleeping = False
        self._unlock_when_no_presence = True


        # need to clean up
        self._lock_expiration = None
        self._config = config

        # Metadata for tracking changes from external systems
        self._last_changed_by = "none"

        # Variables for managing current lighting status
        self._previous_execution_lights_target = None

        self._locked = None

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def perform_confirm(self) -> bool:
        return self._perform_confirm

    @perform_confirm.setter
    def perform_confirm(self, value: bool) -> None:
        self._perform_confirm = value

    @property
    def adjust_brightness_when_active(self) -> bool:
        return self._adjust_brightness_when_active

    @adjust_brightness_when_active.setter
    def adjust_brightness_when_active(self, value: bool) -> None:
        self._adjust_brightness_when_active = value

    @property
    def turn_off_while_sleeping(self) -> bool:
        return self._turn_off_while_sleeping

    @turn_off_while_sleeping.setter
    def turn_off_while_sleeping(self, value: bool) -> None:
        self._turn_off_while_sleeping = value

    @property
    def unlock_when_no_presence(self) -> bool:
        return self._unlock_when_no_presence

    @unlock_when_no_presence.setter
    def unlock_when_no_presence(self, value: bool) -> None:
        self._unlock_when_no_presence = value

    @property
    def adjust_brightness(self) -> bool:
        return self._adjust_brightness

    @adjust_brightness.setter
    def adjust_brightness(self, value: bool) -> None:
        self._adjust_brightness = value

    @property
    def enabled_var_id(self) -> int:
        """
        The Indigo variable ID that controls whether this zone is enabled.

        Returns:
            int: The Indigo variable ID.
        """
        return self._enabled_var_id

    @enabled_var_id.setter
    def enabled_var_id(self, value: int) -> None:
        """
        Set the Indigo variable ID that controls the zone's enabled state.

        Args:
            value (int): The Indigo variable ID.
        """
        self._enabled_var_id = value
        self._enabled = indigo.variables[self._enabled_var_id].getValue(bool)
        # indigo.server.log(f"Zone {self._name}: enabled set to: {str(self._enabled)}")

    @property
    def last_changed(self) -> datetime.datetime:
        device_last_changed = datetime.datetime(1900, 0o1, 0o1)

        for dev_id in self.presence_dev_ids:
            if indigo.devices[dev_id].lastChanged > device_last_changed:
                device_last_changed = indigo.devices[dev_id].lastChanged

        for dev_id in self.luminance_dev_ids:
            if indigo.devices[dev_id].lastChanged > device_last_changed:
                device_last_changed = indigo.devices[dev_id].lastChanged

        return device_last_changed

    @property
    def current_lighting_period(self) -> Optional[LightingPeriod]:
        if self._current_lighting_period is None:
            if self.lighting_periods is None:
                indigo.server.log("no periods for zone " + self._name)
                return None

            # Note that this will return the first active period.  Periods are intended to be ordered, processed squenetially, and with only one active.
            for period in self.lighting_periods:
                if period.is_active_period():
                    self._current_lighting_period = period
                    break

        return self._current_lighting_period

    def has_presence_detected(self) -> bool:
        """
        Check if presence is detected in this zone or, if defined, in the current period.

        Returns:
            bool: True if presence is detected, otherwise False.
        """
        if (
            not self.current_lighting_period is None
            and self.current_lighting_period.uses_presence_override
        ):
            return self.current_lighting_period.has_presence_detected()

        for dev_id in self.presence_dev_ids:
            if "onOffState" in indigo.devices[dev_id].states:
                if indigo.devices[dev_id].states["onOffState"]:
                    return True
            elif indigo.devices[dev_id].onState:
                return True

        return False

    @property
    def exclude_from_lock_dev_ids(self) -> List[int]:
        """
        List of device IDs to exclude from lock operations.
        """
        return self._exclude_from_lock_dev_ids

    @exclude_from_lock_dev_ids.setter
    def exclude_from_lock_dev_ids(self, value: List[int]):
        self._exclude_from_lock_dev_ids = value

    @property
    def on_lights_dev_ids(self) -> List[int]:
        """
        List of on lights device IDs.
        """
        return self._on_lights_dev_ids

    @on_lights_dev_ids.setter
    def on_lights_dev_ids(self, value: List[int]) -> None:
        self._on_lights_dev_ids = value
        self.target_brightness = self.current_lights_status

    @property
    def presence_dev_ids(self) -> List[int]:
        return self._presence_dev_ids

    @presence_dev_ids.setter
    def presence_dev_ids(self, value: List[int]) -> None:
        self._presence_dev_ids = value

    @property
    def target_brightness(self) -> List[Union[bool, int]]:
        """Get the target brightness for zone devices."""
        if self._target_brightness is None:
            total_devices = len(self.on_lights_dev_ids) + len(self.off_lights_dev_ids)
            self._target_brightness = [False] * total_devices
        return self._target_brightness

    @target_brightness.setter
    def target_brightness(
        self, value: Union[List[Union[bool, int]], int, bool]
    ) -> None:
        """Set the target brightness for zone devices, ensuring proper conversion and limits."""

        if type(value) is list:
            # Go through the list and ensure that no value is > 100.
            for idx, listValue in enumerate(value):
                if listValue > 100:
                    value[idx] = 100

            # TODO: Compare the list size to be sure it matches the number of onDevices.
            self._target_brightness = value
        else:
            self._target_brightness = []
            for idx, dev in enumerate(self.on_lights_dev_ids):
                # For SenseME Fans, limit the target brightness to between 0 and 16.
                if (
                    indigo.devices[dev].pluginId
                    == "com.pennypacker.indigoplugin.senseme"
                ):
                    self._target_brightness.append(int((value / 100) * 16))
                elif (
                    isinstance(value, bool)
                    or type(indigo.devices[dev]) is indigo.DimmerDevice
                ):
                    if value > 100:
                        self._target_brightness.append(100)
                    else:
                        self._target_brightness.append(value)
                elif value > 0:
                    self._target_brightness.append(True)
                elif value == 0:
                    self._target_brightness.append(False)
                else:
                    indigo.server.log(
                        "Target brightness could not be converted to the appropriate value for the indigo device type."
                    )

            # Determine offDevices target:
            # off_device_target = 0 to turn devices off; -1 to leave them unchanged.
            if isinstance(value, bool) and not value:
                off_device_target = 0
            elif isinstance(value, bool) and value:
                off_device_target = -1
            elif value == 0:
                off_device_target = 0
            else:
                off_device_target = -1

            for idx, dev in enumerate(self.off_lights_dev_ids):
                # Leave the device state unchanged if off_device_target is -1.
                if off_device_target == -1:
                    if type(indigo.devices[dev]) is indigo.DimmerDevice:
                        self._target_brightness.append(indigo.devices[dev].brightness)
                    elif type(indigo.devices[dev]) is indigo.RelayDevice:
                        self._target_brightness.append(indigo.devices[dev].onState)
                    elif "brightness" in indigo.devices[dev].states:
                        self._target_brightness.append(
                            indigo.devices[dev].states["brightness"]
                        )
                elif off_device_target == 0:
                    if (
                        type(indigo.devices[dev]) is indigo.DimmerDevice
                        or "brightness" in indigo.devices[dev].states
                    ):
                        self._target_brightness.append(0)
                    elif type(indigo.devices[dev]) is indigo.RelayDevice:
                        self._target_brightness.append(False)

    @property
    def minimum_luminance(self) -> int:
        return self._minimum_luminance

    @minimum_luminance.setter
    def minimum_luminance(self, value: int) -> None:
        self._minimum_luminance = value

    @property
    def minimum_luminance_var_id(self) -> int:
        return self._minimum_luminance_var_id

    @minimum_luminance_var_id.setter
    def minimum_luminance_var_id(self, value: int) -> None:
        self._minimum_luminance_var_id = value
        self._minimum_luminance = indigo.variables[
            self._minimum_luminance_var_id
        ].getValue(float)

    @property
    def luminance_dev_ids(self) -> List[int]:
        return self._luminance_dev_ids

    @luminance_dev_ids.setter
    def luminance_dev_ids(self, value: List[int]) -> None:
        self._luminance_dev_ids = value

    @property
    def luminance(self) -> int:
        self._luminance = 0

        for devId in self.luminance_dev_ids:
            self._luminance = self._luminance + indigo.devices[devId].sensorValue

        self._luminance = int(self._luminance / len(self.luminance_dev_ids))

        return self._luminance

    @property
    def last_changed_by(self) -> str:
        return self._last_changed_by

    @property
    def off_lights_dev_ids(self) -> List[int]:
        return self._off_lights_dev_ids

    @off_lights_dev_ids.setter
    def off_lights_dev_ids(self, value: List[int]) -> None:
        self._off_lights_dev_ids = value
        self.target_brightness = self.current_lights_status

    @property
    def current_lights_status(self) -> List[Union[int, bool]]:
        """Retrieve the current status of on and off lights for the zone.

        Returns:
            list: A list containing the brightness (as an int) for dimmer devices or a boolean state for relay devices.

        Devices listed in 'exclude_from_lock_dev_ids' are skipped.
        """
        self._current_lights_status = []

        def get_device_status(device):
            if isinstance(device, indigo.DimmerDevice):
                return int(device.brightness)
            elif "brightness" in device.states:
                return int(device.states["brightness"])
            else:
                return bool(device.onState)

        # Process on_lights_dev_id devices
        for dev_id in self.on_lights_dev_ids:
            if dev_id in self.exclude_from_lock_dev_ids:
                continue
            self._current_lights_status.append(
                get_device_status(indigo.devices[dev_id])
            )

        # Process off_lights_dev_id devices
        for dev_id in self.off_lights_dev_ids:
            if dev_id in self.exclude_from_lock_dev_ids:
                continue
            self._current_lights_status.append(
                get_device_status(indigo.devices[dev_id])
            )

        return self._current_lights_status

    @property
    def current_state_any_light_is_on(self) -> bool:
        """
        Check if any device in current_lights_status is on.
        A device is considered on if its corresponding value is True or if it's a numeric value greater than 0.

        Returns:
            bool: True if any device is on, otherwise False.
        """
        for status in self.current_lights_status:
            if status is True or (isinstance(status, (int, float)) and status > 0):
                return True
        return False

    @property
    def previous_target_var_name(self) -> str:
        return self.name.replace(" ", "_") + "__autoLights_previousTarget"

    @property
    def previous_execution_lights_target(self) -> Union[str, List[Union[bool, int]]]:
        """
        Retrieves and processes the previous execution target for lights from an Indigo variable.
        Ensures the variable exists and converts its value to a proper list of booleans or numeric targets.
        """
        if self._previous_execution_lights_target is not None:
            return self._previous_execution_lights_target

        # Ensure the folder exists
        if "auto_lights_script" not in indigo.variables.folders:
            indigo.folders.create("auto_lights_script")
        var_folder = indigo.variables.folders["auto_lights_script"]

        previous_execution_lights_target_var = None

        # Retrieve the variable; create it if it doesn't exist
        try:
            previous_execution_lights_target_var = indigo.variables[
                self.previous_target_var_name
            ]
        except KeyError:
            previous_execution_lights_target_var = indigo.variable.create(
                self.previous_target_var_name, "false", folder=var_folder
            )

        self._previous_execution_lights_target = (
            previous_execution_lights_target_var.value
        )

        # self.previous_execution_lights_target_value will always be a string in the form of a list.
        # Example: "[100, True, 0, 0]"
        try:
            self._previous_execution_lights_target = ast.literal_eval(
                previous_execution_lights_target_var.value
            )
        except Exception as e:
            indigo.server.log(f"Error converting previous_execution_lights_target: {e}")
            self._previous_execution_lights_target = []
        return self._previous_execution_lights_target

    @property
    def check_out_var(self) -> indigo.Variable:
        var_name = self.name.replace(" ", "_") + "_autoLights__checkedOut"

        try:
            debug_var = indigo.variables[var_name]
        except KeyError:
            if "auto_lights_script" not in indigo.variables.folders:
                pass  # should create folder
            var_folder = indigo.variables.folders["auto_lights_script"]
            debug_var = indigo.variable.create(
                var_name, str("false"), folder=var_folder
            )
            indigo.server.log("check_out_var: created variable " + var_name)

        return debug_var

    @property
    def checked_out(self) -> bool:
        return self.check_out_var.getValue(bool)

    def check_in(self):
        """
        Check in the zone by setting the checkout variable to False.
        """
        indigo.variable.updateValue(self.check_out_var, str(False))

    def force_check_in(self):
        """
        Force check in the zone, logging a message if it was previously checked out.
        """
        if self.checked_out:
            indigo.server.log("       ... zone " + self.name + ": forced check in")

        indigo.variable.updateValue(self.check_out_var, str(False))

    def check_out(self):
        """
        Check out the zone by setting the checkout variable to True if it is not already checked out.
        """
        if not self.checked_out:
            indigo.variable.updateValue(self.check_out_var, str(True))

    @property
    def lock_enabled(self) -> bool:
        return self._lock_enabled

    @lock_enabled.setter
    def lock_enabled(self, value: bool) -> None:
        self._lock_enabled = value

    @property
    def extend_lock_when_active(self) -> bool:
        return self._extend_lock_when_active

    @extend_lock_when_active.setter
    def extend_lock_when_active(self, value: bool) -> None:
        self._extend_lock_when_active = value

    @property
    def lock_duration(self) -> int:
        # check if the current period has a lock duration.  If so, use that.
        if (
            not self.current_lighting_period is None
            and self.current_lighting_period.has_lock_duration_override
        ):
            return self.current_lighting_period.lock_duration

        if self._lock_duration is None:
            self._lock_duration = self._config.default_lock_duration

        return self._lock_duration

    @lock_duration.setter
    def lock_duration(self, value: int) -> None:
        self._lock_duration = value

    @property
    def lock_extension_duration(self) -> int:
        if self._lock_extension_duration is None:
            self._lock_extension_duration = self._config.default_lock_extension_duration

        return self._lock_extension_duration

    @lock_extension_duration.setter
    def lock_extension_duration(self, value: int) -> None:
        self._lock_extension_duration = value

    @property
    def lock_var(self) -> Any:
        var_name = self.name.replace(" ", "_") + "_autoLights__locked"

        try:
            locked_var = indigo.variables[var_name]
        except KeyError:
            if "auto_lights_script" not in indigo.variables.folders:
                pass  # should create
            var_folder = indigo.variables.folders["auto_lights_script"]
            locked_var = indigo.variable.create(
                var_name, str("false"), folder=var_folder
            )

        return locked_var

    @property
    def locked(self) -> bool:
        """
        Determine if the zone is currently locked.

        A zone is locked if a lock is explicitly enabled and has not yet expired,
        or if recent changes to device brightness or state necessitate a new lock.

        Returns:
            bool: True if the zone is currently locked.
        """
        if not self.lock_enabled:
            return False

        return self._locked

    @locked.setter
    def locked(self, value: bool) -> None:
        self._locked = value

    def reset_lock(self, reason):
        """
        Reset the lock for the zone.

        Args:
            reason (str): Explanation for resetting the lock.
        """
        self._lock_expiration = datetime.datetime.now() - datetime.timedelta(minutes=1)
        indigo.variable.updateValue(self.lock_var, str(self.lock_expiration_str))
        self._locked = False

        self._previous_execution_lights_target = self.current_lights_status
        indigo.variable.updateValue(
            self.previous_target_var_name, str(self._current_lights_status)
        )

        indigo.server.log(
            "auto_lights script for Zone '"
            + self.name
            + "', zone lock has been reset because "
            + reason
        )

    @property
    def lock_expiration_str(self) -> str:
        if self.lock_expiration is None:
            return ""

        return self.lock_expiration.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def lock_expiration(self) -> datetime.datetime:
        return self._lock_expiration

    @lock_expiration.setter
    def lock_expiration(self, value: Union[str, datetime.datetime]) -> None:
        if isinstance(value, str):
            self._lock_expiration = datetime.datetime.strptime(
                value, "%Y-%m-%d %H:%M:%S"
            )
        else:
            self._lock_expiration = value

    @property
    def lighting_periods(self) -> List[LightingPeriod]:
        return self._lighting_periods

    @lighting_periods.setter
    def lighting_periods(self, value: List[LightingPeriod]) -> None:
        self._lighting_periods = value

    def is_dark(self) -> bool:
        """
        Determine if the zone is considered dark based on sensor readings or the current lighting period.

        Returns:
            bool: True if the zone is dark, False otherwise.
        """
        if (
            self.current_lighting_period is not None
            and self.current_lighting_period.uses_luminance_override
        ):
            return self.luminance >= self.current_lighting_period.minimum_luminance

        if len(self.luminance_dev_ids) == 0:
            return True

        for dev_id in self.luminance_dev_ids:
            if indigo.devices[dev_id].sensorValue < self.minimum_luminance:
                return True

        return False

    @property
    def target_brightness_all_off(self) -> bool:
        """
        Check if all devices' target brightness indicate an off state.
        For dimmer devices, an off state is indicated by 0.
        For relay devices, an off state is indicated by False.

        Returns:
            bool: True if every target value signifies off; otherwise, False.
        """
        for target in self.target_brightness:
            if isinstance(target, int) and target != 0:
                return False
            if isinstance(target, bool) and target:
                return False
        return True

    def has_brightness_changes(self):
        """
        Determines if any device's current brightness or state differs from its target brightness.
        Returns True if a difference is detected; otherwise, returns False.
        """
        if not self.enabled:
            return False

        if not self.target_brightness:
            return False

        def brightness_differs(dev, target):
            if isinstance(dev, indigo.DimmerDevice):
                return dev.brightness != target
            elif isinstance(dev, indigo.RelayDevice):
                # For relay devices, interpret target 0 as off (False), non-zero as on (True).
                desired_state = False if target == 0 else True
                return dev.onState != desired_state
            elif "brightness" in dev.states:
                return int(dev.states["brightness"]) != target
            return False

        # Check brightness differences for on lights.
        for idx, dev_id in enumerate(self.on_lights_dev_ids):
            dev = indigo.devices[dev_id]
            target = self.target_brightness[idx]
            if brightness_differs(dev, target):
                return True

        # If all devices are supposed to be off and off_lights_dev_id is defined, verify they are off.
        if self.target_brightness_all_off and self.off_lights_dev_ids is not None:
            for dev_id in self.off_lights_dev_ids:
                dev = indigo.devices[dev_id]
                if brightness_differs(dev, 0):
                    return True

        return False

    def _send_to_indigo(self, device_id: int, desired_brightness: int | bool) -> None:
        """
        Send a command to update an Indigo device (brightness or switch state) and ensure it's confirmed within a limit.

        This function retries the command until the device state matches the desired value or the maximum
        wait limit is reached. If 'perform_confirm' is False, confirmation is skipped after the first attempt.

        Args:
            device_id (int): The Indigo device ID to be changed.
            desired_brightness (int | bool): The target brightness (0-100) for dimmer devices or True/False for switches.
        """

        utils.send_to_indigo(
            device_id, desired_brightness, self.perform_confirm, self._config.debug
        )

    def save_brightness_changes(self) -> None:
        """
        Apply and confirm the target brightness changes for this zone's devices, optionally locking the zone.
        """
        # If all devices should be turned off and off_lights_dev_id is defined, turn off each off device

        # Update the state variable for the previous target brightness

        if self.target_brightness_all_off:
            for dev_id in self.off_lights_dev_ids:
                self._send_to_indigo(dev_id, 0)

        threads = []
        for idx, dev_id in enumerate(self.on_lights_dev_ids):
            # Safely get the target brightness for the device
            try:
                dev_target = self.target_brightness[idx]
            except IndexError:
                indigo.server.log(
                    f"Warning: Missing target brightness for device with ID {dev_id}"
                )
                continue

            self._send_to_indigo(dev_id, dev_target)

        # Wait for all threads to finish
        for thread in threads:
            thread.join()

        # Save the save_state to Indigo variable for lock detection
        indigo.variable.updateValue(
            self.previous_target_var_name, str(self.target_save_state)
        )

    def write_debug_output(self, config) -> str:
        """
        Dynamically construct debug output by iterating over the zone's attributes.
        For list attributes, if the key corresponds to lighting periods, print their properties dynamically with indentation.

        Args:
            config: AutoLightsConfig instance (unused in dynamic output).

        Returns:
            str: Formatted debug output.
        """
        lines = [f"Zone '{self.name}' debug output:"]
        for key, value in self.__dict__.items():
            if isinstance(value, list):
                if key in ("_lighting_periods", "lighting_periods"):
                    lines.append(f"{key}:")
                    for period in value:
                        lines.append(f"  {period.__class__.__name__}:")
                        for p_key, p_value in period.__dict__.items():
                            lines.append(f"    {p_key}: {repr(p_value)}")
                else:
                    lines.append(f"{key}:")
                    for item in value:
                        lines.append(f"    {repr(item)}")
            else:
                lines.append(f"{key}: {repr(value)}")

        return "\n".join(lines)

    @property
    def special_rules_adjustment(self) -> str:
        return self._special_rules_adjustment

    @special_rules_adjustment.setter
    def special_rules_adjustment(self, value: str) -> None:
        self._special_rules_adjustment = value

    # to be overridden
    def run_special_rules(self) -> None:
        """
        Placeholder for child classes to implement zone-specific rules.
        """
        pass

    def calculate_target_brightness(self) -> None:
        """
        Calculate and set the target_brightness based on adjust_brightness.
        If adjust_brightness is True, then set the target_brightness for on lights to 
        the non-negative difference between luminance and minimum_luminance, and off lights to 0.
        """
        if self.adjust_brightness:
            diff = self.luminance - self.minimum_luminance
            diff = diff if diff > 0 else 0
            new_tb = [diff] * len(self.on_lights_dev_ids) + [0] * len(self.off_lights_dev_ids)
            self.target_brightness = new_tb

    def has_device(self, dev_id: int) -> str:
        """
        Check if the provided device ID exists in any of the device ID lists.

        Args:
            dev_id (int): The device ID to look for.

        Returns:
            str: The property name where the device ID is found 
                 (one of: on_lights_dev_ids, off_lights_dev_ids, presence_dev_id, luminance_dev_id).
                 If not found, returns an empty string.
        """
        if dev_id in self.on_lights_dev_ids:
            return "on_lights_dev_ids"
        if dev_id in self.off_lights_dev_ids:
            return "off_lights_dev_ids"
        if dev_id in self.presence_dev_ids:
            return "presence_dev_ids"
        if dev_id in self.luminance_dev_ids:
            return "luminance_dev_ids"
        return ""

