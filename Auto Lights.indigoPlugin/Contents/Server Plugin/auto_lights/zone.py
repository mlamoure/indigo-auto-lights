import datetime
import logging
import math
import threading
from typing import List, Union, Optional, TYPE_CHECKING

from .auto_lights_base import AutoLightsBase

if TYPE_CHECKING:
    from .auto_lights_config import AutoLightsConfig
from . import utils
from .lighting_period import LightingPeriod

try:
    import indigo
except ImportError:
    pass


class Zone(AutoLightsBase):
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

        self._target_brightness = None

        # Behavior flags and settings
        self._adjust_brightness = True
        self._perform_confirm = True
        self._lock_duration = None
        self._extend_lock_when_active = True
        self._unlock_when_no_presence = True

        self._lock_expiration = None
        self._lock_timer = None
        self._config = config

        # Timer for scheduling next lighting-period transition
        self._transition_timer: Optional[threading.Timer] = None

        self._lock_enabled = True
        self._lock_extension_duration = None

        self._checked_out = False

        # counter for in-flight write commands
        self._pending_writes = 0
        self._write_lock = threading.Lock()

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
            if "minimum_luminance_use_variable" in mls:
                use_var = mls["minimum_luminance_use_variable"]
                if not use_var:
                    self._minimum_luminance_var_id = None
            if "minimum_luminance_var_id" in mls:
                self.minimum_luminance_var_id = mls["minimum_luminance_var_id"]
            if "adjust_brightness" in mls:
                self.adjust_brightness = mls["adjust_brightness"]
        if "behavior_settings" in cfg:
            bs = cfg["behavior_settings"]
            if "lock_duration" in bs:
                self.lock_duration = bs["lock_duration"]
            if "extend_lock_when_active" in bs:
                self.extend_lock_when_active = bs["extend_lock_when_active"]
            if "lock_extension_duration" in bs:
                self.lock_extension_duration = bs["lock_extension_duration"]
            if "perform_confirm" in bs:
                self.perform_confirm = bs["perform_confirm"]
            if "unlock_when_no_presence" in bs:
                self.unlock_when_no_presence = bs["unlock_when_no_presence"]
            # load the advanced_settings.exclude_from_lock_dev_ids from the config
            if "advanced_settings" in cfg:
                adv = cfg["advanced_settings"]
                if "exclude_from_lock_dev_ids" in adv:
                    self.exclude_from_lock_dev_ids = adv["exclude_from_lock_dev_ids"]
            if "device_period_map" in cfg:
                self._device_period_map = cfg["device_period_map"]
            else:
                self._device_period_map = {}
                for dev_id in self._on_lights_dev_ids:
                    self._device_period_map[str(dev_id)] = {
                        str(period.id): True for period in self.lighting_periods
                    }

    # (4) Properties
    @property
    def name(self) -> str:
        """Name of the zone."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def enabled(self) -> bool:
        """Indicates whether the zone is enabled."""
        if self._enabled_var_id is None:
            return False
        try:
            return indigo.variables[self._enabled_var_id].getValue(bool)
        except Exception as e:
            self.logger.error(
                f"Zone '{self._name}': enabled_var_id {self._enabled_var_id} not found when accessing enabled property: {e}"
            )
            return False

    @property
    def enabled_var_id(self) -> int:
        """
        The Indigo variable ID that controls whether this zone is enabled.
        """
        return self._enabled_var_id

    @enabled_var_id.setter
    def enabled_var_id(self, value: int) -> None:
        self._enabled_var_id = value
        try:
            self._enabled = indigo.variables[self._enabled_var_id].getValue(bool)
        except Exception as e:
            self.logger.error(
                f"Zone '{self._name}': enabled_var_id {value} not found: {e}"
            )
            self._enabled = False

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
        """Returns the name of the device with the most recent lastChanged value, or 'Auto Lights' if we’re currently processing."""
        if self.checked_out:
            return "Auto Lights"
        return self.last_changed_device.name

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
        """List of device IDs used for luminance measurements."""
        return self._luminance_dev_ids

    @luminance_dev_ids.setter
    def luminance_dev_ids(self, value: List[int]) -> None:
        self._luminance_dev_ids = value

    @property
    def minimum_luminance(self) -> float:
        """
        Minimum luminance threshold for darkness check.
        If a variable ID is set, always read the current value from Indigo.
        """
        if self._minimum_luminance_var_id is not None:
            try:
                return indigo.variables[self._minimum_luminance_var_id].getValue(float)
            except Exception as e:
                self.logger.error(
                    f"Zone '{self._name}': failed to read minimum_luminance_var_id {self._minimum_luminance_var_id}: {e}"
                )
        if self._minimum_luminance is None:
            return 20000
        return self._minimum_luminance

    @minimum_luminance.setter
    def minimum_luminance(self, value: int) -> None:
        self._minimum_luminance = value

    @property
    def minimum_luminance_var_id(self) -> int:
        """Indigo variable ID for minimum luminance threshold."""
        return self._minimum_luminance_var_id

    @minimum_luminance_var_id.setter
    def minimum_luminance_var_id(self, value: int) -> None:
        self._minimum_luminance_var_id = value
        if value is not None:
            try:
                self._minimum_luminance = indigo.variables[value].getValue(float)
            except Exception as e:
                self.logger.error(f"minimum_luminance_var_id {value} not found: {e}")
                self._minimum_luminance = None

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
    def current_lights_status(self) -> List[dict]:
        """Retrieve the current status of on and off lights for the zone."""
        status = []

        def get_device_status(device):
            if isinstance(device, indigo.DimmerDevice):
                return int(device.brightness)
            elif hasattr(device, "brightness"):
                return int(device.brightness)
            elif "brightness" in device.states:
                return int(device.states["brightness"])
            return bool(device.onState)

        # Gather on_lights
        for dev_id in self.on_lights_dev_ids:
            if dev_id in self.exclude_from_lock_dev_ids:
                continue
            status.append(
                {
                    "dev_id": dev_id,
                    "brightness": get_device_status(indigo.devices[dev_id]),
                }
            )

        # Gather off_lights
        for dev_id in self.off_lights_dev_ids:
            if dev_id in self.exclude_from_lock_dev_ids:
                continue
            status.append(
                {
                    "dev_id": dev_id,
                    "brightness": get_device_status(indigo.devices[dev_id]),
                }
            )
        return status

    @property
    def target_brightness(self) -> List[dict]:
        """Get the target brightness for zone devices."""
        return self._target_brightness

    @staticmethod
    def _normalize_dev_target_brightness(
        dev_id, brightness_value=None
    ) -> Union[int, bool]:
        """
        Determine the correct brightness setting for the given device
        based on the input brightness_value.
        """
        dev = indigo.devices[dev_id]

        if brightness_value is None:
            if isinstance(dev, indigo.DimmerDevice):
                brightness_value = dev.brightness
            else:
                brightness_value = dev.onState

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
        """
        Set the target brightness for the zone's devices.

        Accepts:
          - A list of dictionaries, each containing:
              - 'dev_id': The ID of the device.
              - 'target_brightness': The desired brightness for that device.
          - An integer or boolean value:
              - For False or 0, sets all devices (both on and off) to off.
              - For other values, applies to on_lights devices first; then,
                if not forcing off, off_lights are appended with their current state.
        """
        # Reset internal state.
        self._target_brightness = []
        if isinstance(value, list):
            for item in value:
                self._target_brightness.append(
                    {
                        "dev_id": item["dev_id"],
                        "brightness": self._normalize_dev_target_brightness(
                            item["dev_id"], item["brightness"]
                        ),
                    }
                )
        else:
            force_off = (isinstance(value, bool) and not value) or value == 0
            lights = (
                self.on_lights_dev_ids + self.off_lights_dev_ids
                if force_off
                else self.on_lights_dev_ids
            )
            for dev_id in lights:
                self._target_brightness.append(
                    {
                        "dev_id": dev_id,
                        "brightness": self._normalize_dev_target_brightness(
                            dev_id, value
                        ),
                    }
                )
            if not force_off:
                for dev_id in self.off_lights_dev_ids:
                    self._target_brightness.append(
                        {
                            "dev_id": dev_id,
                            "brightness": self._normalize_dev_target_brightness(dev_id),
                        }
                    )
        self._debug_log(
            f"Set target_brightness to {self._target_brightness} with lock comparison {self._target_brightness_lock_comparison}"
        )

    @property
    def _target_brightness_lock_comparison(self) -> List[dict]:
        """Target brightness entries excluding devices excluded from lock detection."""
        return [
            item
            for item in self.target_brightness
            if item["dev_id"] not in self.exclude_from_lock_dev_ids
        ]

    @property
    def current_lighting_period(self) -> Optional[LightingPeriod]:
        """Current active lighting period, or None if no period is active."""
        active = None
        for period in self.lighting_periods:
            if period.is_active_period():
                active = period
                break

        # clear or update the cache
        self._current_lighting_period = active

        if not active:
            self._debug_log(
                f"Zone '{self._name}': no active lighting period right now."
            )
        return active

    @property
    def lighting_periods(self) -> List[LightingPeriod]:
        """List of LightingPeriod instances configured for the zone."""
        return self._lighting_periods

    @lighting_periods.setter
    def lighting_periods(self, value: List[LightingPeriod]) -> None:
        self._lighting_periods = value

    @property
    def last_changed_device(self) -> indigo.Device:
        """Returns the indigo.Device with the most recent lastChanged value."""
        latest_device = None
        latest_time = datetime.datetime(1900, 1, 1)
        for dev_id in self.presence_dev_ids:
            dev = indigo.devices[dev_id]
            if dev.lastChanged > latest_time:
                latest_time = dev.lastChanged
                latest_device = dev
        for dev_id in self.luminance_dev_ids:
            dev = indigo.devices[dev_id]
            if dev.lastChanged > latest_time:
                latest_time = dev.lastChanged
                latest_device = dev
        return latest_device

    @property
    def last_changed(self) -> datetime.datetime:
        """Returns the last changed timestamp from the last_changed_device property."""
        return self.last_changed_device.lastChanged

    @property
    def checked_out(self) -> bool:
        """True if this zone is currently in the middle of a process_zone run."""
        return self._checked_out

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
        if self._lock_duration is None or self._lock_duration == -1:
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
        if self._lock_extension_duration is None or self._lock_extension_duration == -1:
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
        Sets the locked state for the zone. If setting to True, updates the lock expiration time
        and schedules a background event to process the lock expiration. If setting to False, cancels any
        pending lock timers and unlocks the zone.

        Args:
            value (bool): The desired locked state.
        """
        if value:
            new_expiration = datetime.datetime.now() + datetime.timedelta(
                minutes=self.lock_duration
            )
            self.lock_expiration = new_expiration

            # Schedule a background event to process the expiration of the lock.
            now = datetime.datetime.now()
            delay = (self._lock_expiration - now).total_seconds()
            if delay > 0:
                if self._lock_timer:
                    self._lock_timer.cancel()
                self._lock_timer = threading.Timer(delay, self.process_expired_lock)
                self._lock_timer.daemon = True
                self._lock_timer.start()

            self.logger.info(
                f"Zone '{self._name}' locked until {self.lock_expiration_str}"
            )
        else:
            if self._lock_timer is not None:
                self._lock_timer.cancel()
                self._lock_timer = None
            self._lock_expiration = datetime.datetime.now() - datetime.timedelta(
                minutes=1
            )
            self._debug_log(f"Zone '{self._name}' unlocked")

    @property
    def lock_expiration_str(self) -> str:
        """Formatted lock expiration timestamp, empty if no expiration."""
        if self._lock_expiration is None:
            return ""
        return self._lock_expiration.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def lock_expiration(self) -> datetime.datetime:
        """Datetime when the zone lock expires."""
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

        Returns:
            bool: True if all devices are set to off, False otherwise.
        """
        for tb in self.target_brightness:
            if (isinstance(tb, int) and tb != 0) or (isinstance(tb, bool) and tb):
                return False
        return True

    # (5) Public methods
    def has_presence_detected(self) -> bool:
        """
        Check if presence is detected in this zone across all presence devices.

        Examines the onState and onOffState of all presence devices in the zone.
        If any device indicates presence, returns True.

        Returns:
            bool: True if presence is detected, False otherwise.
        """
        for dev_id in self.presence_dev_ids:
            presence_device = indigo.devices[dev_id]
            state_on = presence_device.states.get("onState", False)
            state_onoff = presence_device.states.get("onOffState", False)
            self._debug_log(
                f"Presence device '{presence_device.name}' onOffState: {state_onoff}, onState: {state_on}"
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
        Check if any device in current_lights_status is on.

        A device is considered "on" if its status is True or its brightness is > 0.

        Returns:
            bool: True if any light is on, False otherwise.
        """
        for status in self.current_lights_status:
            if status is True or (isinstance(status, (int, float)) and status > 0):
                return True
        return False

    def check_in(self):
        """
        Mark the zone as checked in (not being processed).
        """
        self._checked_out = False

    def check_out(self):
        """
        Mark the zone as checked out (currently being processed).
        """
        self._checked_out = True

    def reset_lock(self, reason: str):
        """
        Reset the lock for the zone.

        Args:
            reason (str): The reason for resetting the lock, which will be logged.
        """
        self.locked = False
        self.logger.info(f"🔓 Zone '{self._name}' lock reset: {reason}")

    def has_brightness_changes(self, exclude_lock_devices=False) -> bool:
        """
        Check if the current brightness or state of any device differs from its target brightness.

        Args:
            exclude_lock_devices (bool): If True, devices in exclude_from_lock_dev_ids will be ignored.

        Returns:
            bool: True if any device's current state differs from its target, False otherwise.
        """
        if not self.enabled or not self.target_brightness:
            self._debug_log(
                "has_brightness_changes: returning False because zone disabled or no target brightness"
            )
            return False

        # Build a lookup of current hardware states
        current = {
            item["dev_id"]: item["brightness"] for item in self.current_lights_status
        }
        # Compare each target to its actual brightness/state
        for tgt in self.target_brightness:
            dev_id = tgt["dev_id"]
            if exclude_lock_devices and dev_id in self.exclude_from_lock_dev_ids:
                continue

            desired = tgt["brightness"]
            if dev_id not in current:
                # skip devices that aren’t reported in the current status
                self._debug_log(
                    f"has_brightness_changes: skipping missing device {dev_id}"
                )
                continue

            actual = current[dev_id]
            self._debug_log(
                f"has_brightness_changes: device {dev_id}: desired={desired}, actual={actual}"
            )
            if actual != desired:
                return True

        self._debug_log("has_brightness_changes: no brightness changes detected")
        return False

    def save_brightness_changes(self) -> None:
        """
        Apply and confirm the target brightness changes for this zone's devices.

        We batch up all writes, set pending_writes once, then
        spawn one thread per write. The final thread to complete
        will call check_in(), so we don’t prematurely check in.
        """
        # 1) Gather all writes
        writes: List[tuple[int, Union[int, bool]]] = []

        # If all devices are off, write off-lights first
        if self.target_brightness_all_off:
            for dev_id in self.off_lights_dev_ids:
                self._debug_log(
                    f"Setting device {dev_id} off as per target_brightness_all_off"
                )
                writes.append((dev_id, 0))

        # Then map on-lights
        target_map = {
            item["dev_id"]: item["brightness"] for item in self.target_brightness
        }
        for dev_id in self.on_lights_dev_ids:
            brightness = target_map.get(dev_id)
            if brightness is not None:
                self._debug_log(f"Setting device {dev_id} brightness to {brightness}")
                writes.append((dev_id, brightness))
            else:
                self.logger.warning(
                    f"No target brightness found for device {dev_id}. Skipping update."
                )

        # If there’s nothing to do, check in immediately
        if not writes:
            self._debug_log("save_brightness_changes: nothing to write, checking in")
            self.check_in()
            return

        # 2) Set the pending-write count up front
        with self._write_lock:
            self._pending_writes = len(writes)

        # 3) Spawn one thread per write
        for dev_id, desired in writes:

            def _writer(dev_id=dev_id, desired_brightness=desired):
                self._debug_log(
                    f"starting write for device {dev_id}, value {desired_brightness}"
                )
                utils.send_to_indigo(dev_id, desired_brightness, self.perform_confirm)
                # when done, decrement; if zero, check in
                with self._write_lock:
                    self._pending_writes -= 1
                    self._debug_log(
                        f"completed write for device {dev_id}, pending_writes={self._pending_writes}"
                    )
                    if self._pending_writes == 0:
                        self.check_in()

            t = threading.Thread(target=_writer, daemon=True)
            t.start()

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
        mode = (
            self.current_lighting_period.mode if self.current_lighting_period else None
        )
        presence_detected = self.has_presence_detected()
        dark_condition = self.is_dark()
        self._debug_log(f"Current lighting period mode: {mode}")
        self._debug_log(f"Presence detected: {presence_detected}")
        self._debug_log(f"Is dark: {dark_condition}")

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

            new_target_brightness = []
            for dev_id in self.on_lights_dev_ids:
                self._debug_log(f"Processing device {dev_id}")
                # Skip devices excluded from this lighting period
                is_excluded = self.has_dev_lighting_mapping_exclusion(
                    dev_id, self.current_lighting_period
                )
                self._debug_log(
                    f"Device {dev_id} excluded: {is_excluded} because of has_dev_lighting_mapping_exclusion"
                )
                if not is_excluded:
                    if not self.adjust_brightness:
                        brightness = 100
                    else:
                        # Calculate brightness based on luminance
                        delta = math.ceil(
                            (1 - (self.luminance / self.minimum_luminance)) * 100
                        )
                        # Apply limit_brightness override if set
                        if (
                            self.current_lighting_period.limit_brightness is not None
                            and self.current_lighting_period.limit_brightness >= 0
                        ):
                            delta = min(
                                delta, self.current_lighting_period.limit_brightness
                            )
                        brightness = delta
                    new_target_brightness.append(
                        {"dev_id": dev_id, "brightness": brightness}
                    )
            self.target_brightness = new_target_brightness
            self._debug_log(f"Target brightness list set: {new_target_brightness}")

        # If no presence detected, record action reason.
        elif self.current_lighting_period.mode == "On and Off" and not self.is_dark():
            self._debug_log("Zone is bright, setting all lights off")
            action_reason = "zone is bright, turning lights off"
            self.target_brightness = 0
        elif not self.has_presence_detected():
            self._debug_log("No presence detected, setting all lights off")
            action_reason = "presence is not detected"
            self.target_brightness = 0
            self._debug_log("Target brightness set to off (0)")

        self._debug_log(f"calculate_target_brightness result: {action_reason}")
        return action_reason

    @property
    def device_period_map(self) -> dict:
        """Mapping of device IDs to lighting period inclusion/exclusion."""
        return self._device_period_map

    @device_period_map.setter
    def device_period_map(self, value: dict) -> None:
        self._device_period_map = value

    def has_dev_lighting_mapping_exclusion(
        self, dev_id: int, lighting_period: LightingPeriod
    ) -> bool:
        """
        Determines if a device is excluded from a specific lighting period.

        This method checks the device-to-period mapping to see if a device
        should be excluded from a particular lighting period's control.

        Args:
            dev_id (int): The Indigo device ID to check
            lighting_period (LightingPeriod): The lighting period to check against

        Returns:
            bool: True if the device is excluded from the lighting period,
                  False if the device should be controlled by the lighting period
        """
        device_map = self.device_period_map.get(str(dev_id), {})
        result = device_map.get(str(lighting_period.id), True) is False
        self._debug_log(
            f"has_dev_lighting_mapping_exclusion: dev_id={dev_id}, period={lighting_period.name}, device_map={device_map}, result={result}"
        )
        self._debug_log(f"has_device: dev_id={dev_id}, result={result}")
        return result

    def has_device(self, dev_id: int) -> str:
        """
        Check if the given device ID exists in this zone's device lists.

        Args:
            dev_id (int): The Indigo device ID to check.

        Returns:
            str: The name of the list containing the device ID, or an empty string if not found.
                 Possible values: "exclude_from_lock_dev_ids", "on_lights_dev_ids",
                 "off_lights_dev_ids", "presence_dev_ids", "luminance_dev_ids", or "".
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

        if result:
            self._debug_log(f"has_device: dev_id={dev_id}, result={result}")
        return result

    def schedule_next_transition(self):
        """
        Cancel any existing transition timer and schedule exactly one new timer:
         - if currently in a LightingPeriod: fire at its to_time
         - otherwise: fire at the next-from_time among all periods
        """
        if not self.lighting_periods:
            self._debug_log(
                f"Zone '{self._name}' has no lighting periods; skipping scheduling"
            )
            return
        # 1) cancel old
        if self._transition_timer:
            self._transition_timer.cancel()

        now = datetime.datetime.now()
        next_dt = None
        next_period = None
        next_boundary = None  # "from_time" or "to_time"

        # helper to consider a boundary time and pick the soonest future one
        def consider(dt: datetime.datetime, period, boundary_name):
            nonlocal next_dt, next_period, next_boundary
            if dt <= now:
                dt = dt + datetime.timedelta(days=1)
            if next_dt is None or dt < next_dt:
                next_dt = dt
                next_period = period
                next_boundary = boundary_name

        # if we are in a period now, schedule its end first
        current = self.current_lighting_period
        if current:
            dt = datetime.datetime.combine(now.date(), current.to_time)
            consider(dt, current, "to_time")

        # always also consider starts of *all* periods
        for period in self.lighting_periods:
            dt = datetime.datetime.combine(now.date(), period.from_time)
            consider(dt, period, "from_time")

        # by now next_dt is the very next boundary for this zone
        assert next_dt and next_period and next_boundary

        delay = (next_dt - now).total_seconds()
        self._transition_timer = threading.Timer(
            delay,
            self._on_transition,
            args=(next_period, next_boundary),
        )
        self._transition_timer.daemon = True
        self._transition_timer.start()
        self._debug_log(
            f"Scheduled next transition for zone '{self._name}' at {next_dt} for period '{next_period.name}' boundary '{next_boundary}'"
        )

    def _on_transition(self, period: LightingPeriod, boundary_name: str):
        """
        Called when we hit a scheduled boundary.
        1) Re-run our zone logic to pick up the new period
        2) Schedule the *next* boundary
        """
        # 1) process zone so that current_lighting_period has flipped
        #    you need a pointer back to the agent; assume your config holds it:
        self._debug_log(
            f"Transition triggered for zone '{self._name}': period '{period.name}', boundary '{boundary_name}'"
        )
        self._config.agent.process_zone(self)

        # 2) schedule the next transition
        self.schedule_next_transition()

    def process_expired_lock(self) -> None:
        """
        Processes the expiration of the zone lock. If the zone is still locked,
        and extend_lock_when_active is True and presence is detected,
        extends the lock expiration by lock_extension_duration minutes.
        Otherwise, unlocks the zone.
        """
        if self.extend_lock_when_active and self.has_presence_detected():
            new_expiration = datetime.datetime.now() + datetime.timedelta(
                minutes=self.lock_extension_duration
            )
            self.lock_expiration = new_expiration
            self.logger.info(
                f"Lock extended for zone '{self._name}' until {self.lock_expiration_str}"
            )
        else:
            self.locked = False
            self.logger.info(
                f"🔓️Lock expired for zone '{self._name}' and zone is now unlocked"
            )

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

    def has_lock_occurred(self) -> bool:
        """Determine if an external change should create a new zone lock."""
        # if we’re in the middle of our own process_zone run, don’t treat our device writes as
        # an external change that should create a new lock.
        if self.checked_out:
            return False

        result = self.has_brightness_changes(exclude_lock_devices=True)
        self._debug_log(f"has_lock_occurred result: {result}")
        if self.locked != result:
            self.locked = result
        return result
