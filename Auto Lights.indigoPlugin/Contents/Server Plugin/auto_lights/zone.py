import datetime
import inspect
import logging
from typing import List, Union, Optional, TYPE_CHECKING

import math

if TYPE_CHECKING:
    from .auto_lights_config import AutoLightsConfig
from . import utils
from .lighting_period import LightingPeriod

try:
    import indigo
except ImportError:
    pass


class Zone:
    """
    Represents an AutoLights zone.

    This class manages configuration, device lists, lighting periods,
    and state information used to control the lighting behavior for a zone.
    
    It includes methods and properties to:
      - Load and apply configuration from a dictionary.
      - Compute and update target brightness levels.
      - Determine lock status based on expiration times.
      - Process sensor data and presence detection.
      - Interface with Indigo devices via utility functions.
    
    Attributes:
        _name (str): Name of the zone.
        _enabled (bool): Indicates if the zone is active.
        _lock_duration (int): Duration in minutes for zone locking.
        _lock_expiration (datetime): Expiration time for the current lock.
        ... (other attributes)
    """

    # (2) Class variables or constants would go here if we had any.

    # (3) Constructor
    def __init__(self, name: str, config: "AutoLightsConfig"):
        """
        Initialize a Zone instance.

        Args:
            name (str): The name of the zone.
            config (AutoLightsConfig): The global auto lights configuration.
        """
        self.logger = logging.getLogger("Plugin")
        self._name = name
        self._enabled = False
        self._enabled_var_id = None

        self._lighting_periods = []
        self._current_lighting_period = None

        # Device lists for lights
        self._on_lights_dev_ids = []
        self._off_lights_dev_ids = []
        self._exclude_from_lock_dev_ids = []

        self._luminance_dev_ids = []
        self._luminance = 0

        self._presence_dev_ids = []
        self._minimum_luminance = 10000
        self._minimum_luminance_var_id = None

        self._current_lights_status = []
        self._target_brightness = None
        self._target_brightness_all_off = None

        # Behavior flags and settings
        self._adjust_brightness = True
        self._perform_confirm = True
        self._lock_duration = None
        self._extend_lock_when_active = True
        self._unlock_when_no_presence = True

        self._lock_expiration = None
        self._config = config

        self._last_changed_by = "none"
        self._locked = False
        self._target_brightness_lock_comparison = None
        self._lock_enabled = True
        self._lock_extension_duration = None

        self._checked_out = False

    def _debug_log(self, message: str) -> None:
        """
        Logs a debug message with caller function and line information.

        Args:
            message (str): The debug message to log.
        """
        stack = inspect.stack()
        current_fn = stack[1].function if len(stack) > 1 else ""
        caller_fn = stack[2].function if len(stack) > 2 else ""
        caller_line = stack[2].lineno if len(stack) > 2 else 0
        self.logger.debug(
            f"[caller: {caller_fn} : {caller_line}][func: {current_fn}] Zone '{self._name}': {message}"
        )

    def from_config_dict(self, cfg: dict) -> None:
        """
        Updates the zone configuration based on a provided dictionary.

        Args:
            cfg (dict): Configuration dictionary with keys such as 'enabled_var_id',
                        'device_settings', 'minimum_luminance_settings', and 'behavior_settings'.
        """
        if "enabled_var_id" in cfg:
            self.enabled_var_id = cfg["enabled_var_id"]
        if "device_settings" in cfg:
            ds = cfg["device_settings"]
            if "on_lights_dev_ids" in ds:
                self.on_lights_dev_ids = ds["on_lights_dev_ids"]
            if "off_lights_dev_ids" in ds:
                self.off_lights_dev_ids = ds["off_lights_dev_ids"]
            if "luminance_dev_ids" in ds:
                self.luminance_dev_ids = ds["luminance_dev_ids"]
            if "presence_dev_ids" in ds:
                self.presence_dev_ids = ds["presence_dev_ids"]
            elif "presence_dev_id" in ds:
                self.presence_dev_ids = [ds["presence_dev_id"]]
        if "minimum_luminance_settings" in cfg:
            mls = cfg["minimum_luminance_settings"]
            if "minimum_luminance" in mls:
                self.minimum_luminance = mls["minimum_luminance"]
            if "minimum_luminance_var_id" in mls:
                self.minimum_luminance_var_id = mls["minimum_luminance_var_id"]
        if "behavior_settings" in cfg:
            bs = cfg["behavior_settings"]
            if "adjust_brightness" in bs:
                self.adjust_brightness = bs["adjust_brightness"]
            if "lock_duration" in bs:
                self.lock_duration = bs["lock_duration"]
            if "extend_lock_when_active" in bs:
                self.extend_lock_when_active = bs["extend_lock_when_active"]
            if "perform_confirm" in bs:
                self.perform_confirm = bs["perform_confirm"]
            if "unlock_when_no_presence" in bs:
                self.unlock_when_no_presence = bs["unlock_when_no_presence"]

    # (4) Properties
    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def enabled(self) -> bool:
        """Indicates whether the zone is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def enabled_var_id(self) -> int:
        """
        The Indigo variable ID that controls whether this zone is enabled.
        """
        return self._enabled_var_id

    @enabled_var_id.setter
    def enabled_var_id(self, value: int) -> None:
        self._enabled_var_id = value
        self._enabled = indigo.variables[self._enabled_var_id].getValue(bool)

    @property
    def perform_confirm(self) -> bool:
        """Returns True if zone actions require confirmation, otherwise False."""
        return self._perform_confirm

    @perform_confirm.setter
    def perform_confirm(self, value: bool) -> None:
        self._perform_confirm = value

    @property
    def unlock_when_no_presence(self) -> bool:
        """Indicates whether the zone should automatically unlock when no presence is detected."""
        return self._unlock_when_no_presence

    @unlock_when_no_presence.setter
    def unlock_when_no_presence(self, value: bool) -> None:
        self._unlock_when_no_presence = value

    @property
    def adjust_brightness(self) -> bool:
        """Returns True if brightness adjustment is enabled for the zone."""
        return self._adjust_brightness

    @adjust_brightness.setter
    def adjust_brightness(self, value: bool) -> None:
        self._adjust_brightness = value

    @property
    def last_changed_by(self) -> str:
        """Returns the identifier of the last entity that changed the zone's state."""
        return self._last_changed_by

    @property
    def exclude_from_lock_dev_ids(self) -> List[int]:
        """List of device IDs to exclude from lock operations."""
        return self._exclude_from_lock_dev_ids

    @exclude_from_lock_dev_ids.setter
    def exclude_from_lock_dev_ids(self, value: List[int]) -> None:
        self._exclude_from_lock_dev_ids = value

    @property
    def on_lights_dev_ids(self) -> List[int]:
        """List of device IDs that should be turned on."""
        return self._on_lights_dev_ids

    @on_lights_dev_ids.setter
    def on_lights_dev_ids(self, value: List[int]) -> None:
        self._on_lights_dev_ids = value

    @property
    def off_lights_dev_ids(self) -> List[int]:
        """List of device IDs that should be turned off."""
        return self._off_lights_dev_ids

    @off_lights_dev_ids.setter
    def off_lights_dev_ids(self, value: List[int]) -> None:
        # Remove any device ids that are also present in on_lights_dev_ids
        cleaned = [dev for dev in value if dev not in self.on_lights_dev_ids]
        self._off_lights_dev_ids = cleaned

    @property
    def presence_dev_ids(self) -> List[int]:
        """Identifiers for devices reporting presence."""
        return self._presence_dev_ids

    @presence_dev_ids.setter
    def presence_dev_ids(self, value: List[int]) -> None:
        self._presence_dev_ids = value

    @property
    def luminance_dev_ids(self) -> List[int]:
        return self._luminance_dev_ids

    @luminance_dev_ids.setter
    def luminance_dev_ids(self, value: List[int]) -> None:
        self._luminance_dev_ids = value

    @property
    def minimum_luminance(self) -> int:
        if self._minimum_luminance is None:
            return 20000
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
        if value is not None:
            self._minimum_luminance = indigo.variables[value].getValue(float)

    @property
    def luminance(self) -> int:
        self._luminance = 0
        if len(self.luminance_dev_ids) == 0:
            return 0
        for devId in self.luminance_dev_ids:
            self._luminance += indigo.devices[devId].sensorValue
        self._luminance = int(self._luminance / len(self.luminance_dev_ids))
        self._debug_log(f"computed luminance: {self._luminance}")
        return self._luminance

    @property
    def current_lights_status(self) -> List[Union[int, bool]]:
        """Retrieve the current status of on and off lights for the zone."""
        self._current_lights_status = []

        def get_device_status(device):
            if isinstance(device, indigo.DimmerDevice):
                return int(device.brightness)
            elif "brightness" in device.states:
                return int(device.states["brightness"])
            return bool(device.onState)

        # Gather on_lights
        for dev_id in self.on_lights_dev_ids:
            if dev_id in self.exclude_from_lock_dev_ids:
                continue
            self._current_lights_status.append(
                get_device_status(indigo.devices[dev_id])
            )

        # Gather off_lights
        for dev_id in self.off_lights_dev_ids:
            if dev_id in self.exclude_from_lock_dev_ids:
                continue
            self._current_lights_status.append(
                get_device_status(indigo.devices[dev_id])
            )
        return self._current_lights_status

    @property
    def target_brightness(self) -> List[Union[bool, int]]:
        """Get the target brightness for zone devices."""
        if self._target_brightness is None:
            total_devices = len(self.on_lights_dev_ids) + len(self.off_lights_dev_ids)
            self._target_brightness = [False] * total_devices
        self._debug_log(f"replied target brightness = {self._target_brightness}")
        return self._target_brightness

    @staticmethod
    def _normalize_dev_target_brightness(dev, brightness_value) -> Union[int, bool]:
        """
        Determine the correct brightness setting for the given device
        based on the input brightness_value.
        """
        # For dimmer devices:
        if isinstance(dev, indigo.DimmerDevice):
            # If numeric, cap it at 100; otherwise, allow bool/other to pass through
            if isinstance(brightness_value, int):
                return min(brightness_value, 100)
            return brightness_value

        # For relay devices or anything else that isn't a dimmer:
        # Convert numeric > 0 to True, 0 to False
        if isinstance(brightness_value, int):
            return brightness_value > 0
        # If it's already bool, just return it
        return bool(brightness_value)

    @target_brightness.setter
    def target_brightness(self, value: Union[list, int, bool]) -> None:
        # Reset internal state lists.
        self._target_brightness = []
        self._target_brightness_lock_comparison = []

        def normalize(dev_id, val):
            return self._normalize_dev_target_brightness(indigo.devices[dev_id], val)

        def off_light_state(dev_id):
            dev = indigo.devices[dev_id]
            if isinstance(dev, indigo.DimmerDevice):
                return dev.brightness
            elif isinstance(dev, indigo.RelayDevice):
                return dev.onState
            elif "brightness" in dev.states:
                return int(dev.states["brightness"])
            return False

        if isinstance(value, list):
            if len(value) != len(self.on_lights_dev_ids):
                raise ValueError(
                    "Length of brightness list must match the total number of devices."
                )
            for idx, val in enumerate(value):
                dev_id = self.on_lights_dev_ids[idx]
                bright = normalize(dev_id, val)
                self._target_brightness.append(bright)
                if dev_id not in self.exclude_from_lock_dev_ids:
                    self._target_brightness_lock_comparison.append(bright)
        else:
            force_off = (isinstance(value, bool) and not value) or value == 0
            lights_dev_ids = (
                self.on_lights_dev_ids + self.off_lights_dev_ids
                if force_off
                else self.on_lights_dev_ids
            )
            for dev_id in lights_dev_ids:
                bright = normalize(dev_id, value)
                self._target_brightness.append(bright)
                if dev_id not in self.exclude_from_lock_dev_ids:
                    self._target_brightness_lock_comparison.append(bright)
            if not force_off:
                for dev_id in self.off_lights_dev_ids:
                    self._target_brightness.append(off_light_state(dev_id))
        for dev_id in self.off_lights_dev_ids:
            if dev_id not in self.exclude_from_lock_dev_ids:
                self._target_brightness_lock_comparison.append(off_light_state(dev_id))
        self._debug_log(
            f"Set target_brightness to {self._target_brightness} with lock comparison {self._target_brightness_lock_comparison}"
        )

    @property
    def current_lighting_period(self) -> Optional[LightingPeriod]:
        if not self.lighting_periods:
            self._debug_log(f"no active lighting periods.")
            return None

        for period in self.lighting_periods:
            if period.is_active_period():
                self._current_lighting_period = period
                break

        return self._current_lighting_period

    @property
    def lighting_periods(self) -> List[LightingPeriod]:
        return self._lighting_periods

    @lighting_periods.setter
    def lighting_periods(self, value: List[LightingPeriod]) -> None:
        self._lighting_periods = value

    @property
    def last_changed(self) -> datetime.datetime:
        device_last_changed = datetime.datetime(1900, 1, 1)
        if (
            self.presence_dev_id is not None
            and indigo.devices[self.presence_dev_id].lastChanged > device_last_changed
        ):
            device_last_changed = indigo.devices[self.presence_dev_id].lastChanged
        for dev_id in self.luminance_dev_ids:
            if indigo.devices[dev_id].lastChanged > device_last_changed:
                device_last_changed = indigo.devices[dev_id].lastChanged
        return device_last_changed

    @property
    def check_out_var(self) -> indigo.Variable:
        var_name = self._name.replace(" ", "_") + "_autoLights__checkedOut"
        try:
            debug_var = indigo.variables[var_name]
        except KeyError:
            if "auto_lights_script" not in indigo.variables.folders:
                pass
            var_folder = indigo.variables.folders["auto_lights_script"]
            debug_var = indigo.variable.create(var_name, "false", folder=var_folder)
            self._debug_log(
                f"[Zone.check_out_var] check_out_var: created variable {var_name}"
            )
        return debug_var

    @property
    def checked_out(self) -> bool:
        return self.check_out_var.getValue(bool)

    @property
    def lock_enabled(self) -> bool:
        """Indicates if the lock functionality is enabled for the zone."""
        return self._lock_enabled

    @lock_enabled.setter
    def lock_enabled(self, value: bool) -> None:
        self._lock_enabled = value

    @property
    def extend_lock_when_active(self) -> bool:
        """Returns True if the zone lock should be extended when activity is detected."""
        return self._extend_lock_when_active

    @extend_lock_when_active.setter
    def extend_lock_when_active(self, value: bool) -> None:
        self._extend_lock_when_active = value

    @property
    def lock_duration(self) -> int:
        """
        Retrieves the lock duration in minutes for the zone.
        If a lighting period override is active and specifies a lock duration, that value is returned.
        Otherwise, the default configuration value is used.
        """
        if (
            self.current_lighting_period
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
        """
        Retrieves the lock extension duration in minutes.
        If not explicitly set, defaults to the value specified in the configuration.
        """
        if self._lock_extension_duration is None:
            self._lock_extension_duration = self._config.default_lock_extension_duration
        return self._lock_extension_duration

    @lock_extension_duration.setter
    def lock_extension_duration(self, value: int) -> None:
        self._lock_extension_duration = value

    @property
    def locked(self) -> bool:
        """Determines if the zone is currently locked."""
        if not self.lock_enabled:
            return False
        if self._lock_expiration is None:
            return False
        return datetime.datetime.now() < self._lock_expiration

    @locked.setter
    def locked(self, value: bool) -> None:
        """
        Sets the locked state for the zone. If setting to True and the zone was previously unlocked,
        updates the lock expiration time to the current time plus the lock duration in minutes.

        Args:
            value (bool): The desired locked state.
        """
        if value and not self._locked:
            self.lock_expiration = datetime.datetime.now() + datetime.timedelta(minutes=self.lock_duration)

        self._locked = value

    @property
    def lock_expiration_str(self) -> str:
        if self._lock_expiration is None:
            return ""
        return self._lock_expiration.strftime("%Y-%m-%d %H:%M:%S")

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
    def target_brightness_all_off(self) -> bool:
        """
        Check if all devices' target brightness indicate an off state.
        For dimmer devices, 0 means off; for relay devices, False means off.
        """
        for tb in self.target_brightness:
            if (isinstance(tb, int) and tb != 0) or (isinstance(tb, bool) and tb):
                return False
        return True

    # (5) Public methods
    def has_presence_detected(self) -> bool:
        """
        Check if presence is detected in this zone across all presence devices.
        """
        for dev_id in self.presence_dev_ids:
            presence_device = indigo.devices[dev_id]
            state_on = presence_device.states.get("onState", False)
            state_onoff = presence_device.states.get("onOffState", False)
            self._debug_log(
                f"Zone '{self._name}': presence device '{presence_device.name}' onOffState: {state_onoff}, onState: {state_on}"
            )
            detected = state_onoff or state_on
            if detected:
                return True
        return False

    def is_dark(self) -> bool:
        """
        Determine if the zone is considered dark based on sensor readings by averaging
        luminance devices' sensor values.

        Returns:
            bool: True if the calculated average luminance is below the minimum threshold,
                  or if no valid sensor values are available; otherwise False.
        """
        if not self.luminance_dev_ids:
            self._debug_log(
                f"Zone '{self._name}': is_dark: No luminance devices, returning True"
            )
            return True

        # Fetch sensor values safely; if a device doesn't have a sensorValue, you can decide on a default behavior.
        sensor_values = [
            indigo.devices[dev_id].sensorValue
            for dev_id in self.luminance_dev_ids
            if hasattr(indigo.devices[dev_id], "sensorValue")
        ]

        if not sensor_values:
            self._debug_log(
                f"Zone '{self._name}': is_dark: No valid sensor values available, returning True"
            )
            return True

        avg = sum(sensor_values) / len(sensor_values)
        self._debug_log(
            f"Zone '{self._name}': Calculated average luminance: {avg} (minimum required: {self.minimum_luminance})."
        )
        return avg < self.minimum_luminance

    def current_state_any_light_is_on(self) -> bool:
        """
        Check if any device in current_lights_status is on (True or brightness > 0).
        """
        for status in self.current_lights_status:
            if status is True or (isinstance(status, (int, float)) and status > 0):
                return True
        return False

    def check_in(self):
        self._checked_out = False

    def check_out(self):
        self._checked_out = True

    def reset_lock(self, reason: str):
        """Reset the lock for the zone."""
        self._lock_expiration = datetime.datetime.now() - datetime.timedelta(minutes=1)
        self._locked = False
        self.logger.info(f"Zone '{self._name}': zone lock reset because {reason}")

    def has_brightness_changes(self) -> bool:
        """
        Check if the current brightness or state of any on/off device differs from its target brightness.
        """
        if not self.enabled or not self.target_brightness:
            return False

        def brightness_differs(dev, target):
            if isinstance(dev, indigo.DimmerDevice):
                return dev.brightness != target
            elif isinstance(dev, indigo.RelayDevice):
                return dev.onState != (False if target == 0 else True)
            elif "brightness" in dev.states:
                return int(dev.states["brightness"]) != target
            return False

        # Check on_lights
        for idx, dev_id in enumerate(self.on_lights_dev_ids):
            dev = indigo.devices[dev_id]
            if brightness_differs(dev, self.target_brightness[idx]):
                return True

        # Check off_lights if all are supposed to be off
        if self.target_brightness_all_off and self.off_lights_dev_ids:
            for dev_id in self.off_lights_dev_ids:
                dev = indigo.devices[dev_id]
                if brightness_differs(dev, 0):
                    return True
        return False

    def save_brightness_changes(self) -> None:
        """
        Apply and confirm the target brightness changes for this zone's devices.
        """
        if self.target_brightness_all_off:
            for dev_id in self.off_lights_dev_ids:
                self._send_to_indigo(dev_id, 0)

        for idx, dev_id in enumerate(self.on_lights_dev_ids):
            try:
                dev_target = self.target_brightness[idx]
            except IndexError:
                indigo.server.log(
                    f"Warning: Missing target brightness for device with ID {dev_id}"
                )
                continue
            self._send_to_indigo(dev_id, dev_target)

    def write_debug_output(self, config) -> str:
        """
        Dynamically construct debug output by iterating over the zone's attributes.
        For list attributes, if the key is lighting_periods, print them in detail.
        """
        lines = [f"Zone '{self._name}' debug output:"]
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

    def calculate_target_brightness(self) -> str:
        """Calculate and set the target brightness for the zone.

        Returns:
            action_reason (str): Explanation of the action taken.
        """
        action_reason = ""

        self._debug_log(f"calculate_target_brightness called")

        if self.current_lighting_period is None:
            self._debug_log(f"no lighting periods available")
            return "No lighting periods available"

        # Check if the zone is in "On and Off" mode, has presence detected, and is dark.
        if (
            self.current_lighting_period.mode == "On and Off"
            and self.has_presence_detected()
            and self.is_dark()
        ):
            action_reason = (
                "Presence is detected for a On and Off Zone, the zone is dark"
            )

            # Case 1: No dimmer adjustment is enabled.
            if not self.adjust_brightness:
                new_tb = [100] * len(self._on_lights_dev_ids)
                self.target_brightness = new_tb
                self._debug_log(
                    f"Calculated target brightness (no dimmer adjustment): {self.target_brightness}"
                )
                return action_reason

            # Case 2: Dimmer adjustment is enabled.
            else:
                # Compute percentage delta relative to sensor luminance and minimum luminance.
                pct_delta = math.ceil(
                    (1 - (self.luminance / self.minimum_luminance)) * 100
                )
                self._debug_log(
                    f"Calculating target brightness: luminance={self.luminance}, minimum_luminance={self.minimum_luminance}, pct_delta={pct_delta}"
                )
                new_tb = [pct_delta] * len(self._on_lights_dev_ids)
                self.target_brightness = new_tb
                self._debug_log(f"Calculated target brightness: {self.target_brightness}")
        # If no presence detected, record action reason.
        elif not self.has_presence_detected():
            action_reason = "presence is not detected"
            self.target_brightness = 0

        return action_reason

    def has_device(self, dev_id: int) -> str:
        """
        Check if the given device ID exists in this zone's device lists.
        """
        if dev_id in self.exclude_from_lock_dev_ids:
            result = "exclude_from_lock_dev_ids"
        elif dev_id in self._on_lights_dev_ids:
            result = "on_lights_dev_ids"
        elif dev_id in self._off_lights_dev_ids:
            result = "off_lights_dev_ids"
        elif dev_id in self._presence_dev_ids:
            result = "presence_dev_ids"
        elif dev_id in self._luminance_dev_ids:
            result = "luminance_dev_ids"
        else:
            result = ""

        return result

    def has_variable(self, var_id: int) -> bool:
        """
        Check if the provided variable id is associated with this zone.

        This method determines if the given variable id matches the zone's minimum luminance variable id
        or the enabled variable id.

        Args:
            var_id (int): The variable id to check.

        Returns:
            bool: True if the variable is used by this zone, False otherwise.
        """
        if (
            self._minimum_luminance_var_id is not None
            and var_id == self._minimum_luminance_var_id
        ):
            result = True
        elif var_id == self._enabled_var_id:
            result = True
        else:
            result = False

        return result

    # (6) Private methods
    def _send_to_indigo(self, device_id: int, desired_brightness: int | bool) -> None:
        """
        Send a command to update an Indigo device and ensure it is confirmed if self.perform_confirm is True.
        """
        utils.send_to_indigo(device_id, desired_brightness, self._perform_confirm)

    def has_lock_occurred(self) -> bool:
        if self._checked_out:
            return False

        self._debug_log(
            f"lock check: current_lights_status = {self.current_lights_status}, target lock comparison = {self._target_brightness_lock_comparison}"
        )
        result = self.current_lights_status != self._target_brightness_lock_comparison
        self._debug_log(f"has_lock_occurred result: {result}")

        self.locked = result

        return result
