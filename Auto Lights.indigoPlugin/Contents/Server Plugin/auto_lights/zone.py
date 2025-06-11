import datetime
import json
import logging
import math
import threading
from typing import List, Union, Optional, TYPE_CHECKING, Tuple, Any

from .auto_lights_base import AutoLightsBase
from .brightness_plan import BrightnessPlan
from .lighting_period_mode import LightingPeriodMode

if TYPE_CHECKING:
    from .auto_lights_config import AutoLightsConfig
from . import utils
from .lighting_period import LightingPeriod

try:
    import indigo
except ImportError:
    pass


# Grace period before allowing auto-unlock when no presence (in seconds)
LOCK_HOLD_GRACE_SECONDS = 30

class Zone(AutoLightsBase):
    """
    Zone abstraction for Auto Lights.

    Manages a named group of Indigo devices that respond to lighting periods and presence/luminance sensors.
    Key responsibilities:
      - Maintain lists of on/off, luminance, and presence device IDs.
      - Load and apply configuration settings from a dictionary.
      - Calculate target brightness using LightingPeriod rules.
      - Enforce and extend a lock state to avoid rapid toggles.
      - Sync both configuration and runtime state definitions and values to an Indigo zone device.

    Attributes:
        name (str): Human-readable name of the zone.
        on_lights_dev_ids (List[int]): IDs of devices to turn on.
        off_lights_dev_ids (List[int]): IDs of devices to turn off.
        luminance_dev_ids (List[int]): IDs of luminance sensor devices.
        presence_dev_ids (List[int]): IDs of presence sensor devices.
        lighting_periods (List[LightingPeriod]): Configured lighting periods for scheduling.
        target_brightness (List[dict]): Desired brightness values for each device.
        locked (bool): Current lock status; True if zone changes are paused.
        zone_index (int): Index of the zone used for the Indigo device address.
    """

    # (2) Class variables or constants would go here if we had any.

    # ----------------------------------------------------------------
    # Which dynamic runtime‐states we will push into the zone device
    zone_indigo_device_runtime_states = [
        {
            "key": "current_period_name",
            "type": "string",
            "label": "Current Period",
            "getter": lambda z: (
                z.current_lighting_period.name if z.current_lighting_period else ""
            ),
        },
        {
            "key": "current_period_mode",
            "type": "string",
            "label": "Mode",
            "getter": lambda z: (
                z.current_lighting_period.mode.value if z.current_lighting_period else ""
            ),
        },
        {
            "key": "current_period_from",
            "type": "string",
            "label": "Start Time",
            "getter": lambda z: (
                z.current_lighting_period.from_time.strftime("%H:%M")
                if z.current_lighting_period
                else ""
            ),
        },
        {
            "key": "current_period_to",
            "type": "string",
            "label": "End Time",
            "getter": lambda z: (
                z.current_lighting_period.to_time.strftime("%H:%M")
                if z.current_lighting_period
                else ""
            ),
        },
        {
            "key": "presence_detected",
            "type": "boolean",
            "label": "Presence Detected",
            "getter": lambda z: z.has_presence_detected(),
        },
        {
            "key": "luminance",
            "type": "number",
            "label": "Luminance",
            "getter": lambda z: z.luminance,
        },
        {
            "key": "is_dark",
            "type": "boolean",
            "label": "Is Dark",
            "getter": lambda z: z.is_dark(),
        },
        {
            "key": "zone_locked",
            "type": "boolean",
            "label": "Locked",
            "getter": lambda z: z.locked,
        },
        {
            "key": "device_states_string",
            "type": "string",
            "label": "Device States",
            "getter": lambda z: z.get_device_states_string(),
        },
    ]
    # ----------------------------------------------------------------

    # (3) Constructor
    def __init__(self, name: str, config: "AutoLightsConfig"):
        """
        Initialize a Zone instance.

        Args:
            name (str): The name of the zone.
            config (AutoLightsConfig): The global auto lights configuration.
        """
        super().__init__()
        self.logger = logging.getLogger("Plugin")
        self._name = name
        self._zone_index = None

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
        self._lock_duration = None
        self._extend_lock_when_active = True
        self._unlock_when_no_presence = True
        self._off_lights_behavior = "do not adjust unless no presence"

        self._lock_expiration = None
        self._lock_timer = None
        self._config = config
        # compute which schema-driven fields we sync back to the Indigo zone device
        self.zone_indigo_device_config_states = {
            key
            for key, schema in self._config.zone_field_schemas.items()
            if schema.get("x-sync_to_indigo")
        }

        # Timer for scheduling next lighting-period transition
        self._transition_timer: Optional[threading.Timer] = None

        self._lock_enabled = True
        self._lock_extension_duration = None

        self._checked_out = False

        # counter for in-flight write commands
        self._pending_writes = 0
        self._write_lock = threading.Lock()
        self._indigo_dev_id: Optional[int] = None
        # global behavior variables map
        self._global_behavior_variables_map: dict[str, bool] = {}

        # per-process run cache (cleared by AutoLightsAgent.process_zone)
        self._runtime_cache: dict[str, Any] = {}

    def __setattr__(self, name, value):
        """
        Override __setattr__ to trigger synchronization to Indigo when
        certain configuration attributes change after zone_index has been set.
        """
        # always let Python store the attribute
        super().__setattr__(name, value)

        # --- BROAD GUARD: don't even think about syncing until after zone_index is set ---
        if getattr(self, "_zone_index", None) is None:
            return

        # now, if this is one of the fields we want to mirror back into Indigo, do it
        if hasattr(self, "_config"):
            key = name[1:] if name.startswith("_") else name
            if key in self.zone_indigo_device_config_states:
                self.sync_indigo_device()

    def from_config_dict(self, cfg: dict) -> None:
        """
        Updates the zone configuration based on a provided dictionary.

        Args:
            cfg (dict): Configuration dictionary with keys
                        'device_settings', 'minimum_luminance_settings', and 'behavior_settings'.
        """
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
            if "unlock_when_no_presence" in bs:
                self.unlock_when_no_presence = bs["unlock_when_no_presence"]
            if "off_lights_behavior" in bs:
                self.off_lights_behavior = bs["off_lights_behavior"]
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
            # load global behavior variables map
            if "global_behavior_variables_map" in cfg:
                self._global_behavior_variables_map = cfg[
                    "global_behavior_variables_map"
                ]
            else:
                self._global_behavior_variables_map = {
                    str(v["var_id"]): True
                    for v in self._config.global_behavior_variables
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
        """Indicates whether the zone is enabled via its Indigo Relay device."""
        try:
            result = bool(self.indigo_dev.onState)
            self._debug_log(f"enabled={result}")
            return result
        except Exception as e:
            self.logger.error(f"Zone '{self._name}': failed to read onState: {e}")
            return False

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """
        Sets the zone's enabled state by toggling the Indigo device on or off.
        """
        dev = self.indigo_dev
        if dev is None:
            return
        try:
            if value:
                indigo.device.turnOn(self.indigo_dev.id)
            else:
                indigo.device.turnOff(self.indigo_dev.id)
        except Exception as e:
            self.logger.error(f"Zone '{self._name}': failed to set enabled state: {e}")

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
    def off_lights_behavior(self) -> str:
        """When to turn off your Off-Lights in On-and-Off periods."""
        return self._off_lights_behavior

    @off_lights_behavior.setter
    def off_lights_behavior(self, value: str) -> None:
        self._off_lights_behavior = value

    @property
    def _last_changed_by(self) -> str:
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
                return float(indigo.variables[self._minimum_luminance_var_id].value)
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
                self._minimum_luminance = float(indigo.variables[value].value)
            except Exception as e:
                self.logger.error(f"minimum_luminance_var_id {value} not found: {e}")
                self._minimum_luminance = None

    @property
    def luminance(self) -> int:
        if "luminance" in self._runtime_cache:
            return self._runtime_cache["luminance"]

        self._luminance = 0
        if len(self.luminance_dev_ids) == 0:
            return 0
        for devId in self.luminance_dev_ids:
            self._luminance += indigo.devices[devId].sensorValue
        self._luminance = int(self._luminance / len(self.luminance_dev_ids))
        self._debug_log(f"computed luminance: {self._luminance}")
        self._runtime_cache["luminance"] = self._luminance
        return self._luminance

    def current_lights_status(self, include_lock_excluded: bool = False) -> List[dict]:
        """
        Retrieve the current status of on and off lights for the zone.
        By default this skips any device in exclude_from_lock_dev_ids;
        set include_lock_excluded=True to see *all* devices.
        """
        status = []

        def get_device_status(device):
            if isinstance(device, indigo.DimmerDevice):
                return int(device.brightness)
            elif hasattr(device, "brightness"):
                return int(device.brightness)
            elif "brightness" in device.states:
                return int(device.states["brightness"])
            elif "brightnessLevel" in device.states:
                return int(device.states["brightness"])

            try:
                return bool(device.onState)
            except Exception as e:
                logging.error(
                    f"Zone '{self._name}': failed to read current state for device "
                    f"{getattr(device, 'id', 'unknown')} ('{getattr(device, 'name', 'unknown')}'): {e}"
                )
                return False

        # Gather on_lights
        for dev_id in self.on_lights_dev_ids:
            if not include_lock_excluded and dev_id in self.exclude_from_lock_dev_ids:
                continue
            status.append(
                {
                    "dev_id": dev_id,
                    "brightness": get_device_status(indigo.devices[dev_id]),
                }
            )

        # Gather off_lights
        for dev_id in self.off_lights_dev_ids:
            if not include_lock_excluded and dev_id in self.exclude_from_lock_dev_ids:
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
    def _last_changed(self) -> datetime.datetime:
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
            # record lock start time for no-presence grace period
            self._lock_start_time = datetime.datetime.now()
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
                self._lock_timer = threading.Timer(delay, self._process_expired_lock)
                self._lock_timer.daemon = True
                self._lock_timer.start()

            # schedule no-presence grace timer at lock-time
            if self.unlock_when_no_presence and not self.has_presence_detected():
                agent = self._config.agent
                old = agent._no_presence_timers.pop(self.name, None)
                if old:
                    old.cancel()
                t = threading.Timer(
                    LOCK_HOLD_GRACE_SECONDS,
                    lambda z=self: agent._unlock_after_grace(z),
                )
                t.daemon = True
                agent._no_presence_timers[self.name] = t
                t.start()

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
        # Immediately refresh zone device UI after lock state change
        try:
            self.sync_indigo_device()
        except Exception as e:
            self.logger.exception(f"Failed to sync onOffState after lock change for zone '{self._name}': {e}")

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
        if "presence" in self._runtime_cache:
            return self._runtime_cache["presence"]

        for dev_id in self.presence_dev_ids:
            presence_device = indigo.devices[dev_id]
            state_on = presence_device.states.get("onState", False)
            state_onoff = presence_device.states.get("onOffState", False)
            self._debug_log(
                f"Presence device '{presence_device.name}' onOffState: {state_onoff}, onState: {state_on}"
            )
            detected = state_onoff or state_on
            if detected:
                self._runtime_cache["presence"] = True
                return True

        self._runtime_cache["presence"] = False
        return False

    def is_dark(self) -> bool:
        """
        Determine if the zone is considered dark based on sensor readings by averaging
        luminance devices' sensor values.

        Returns:
            bool: True if the calculated average luminance is below the minimum threshold,
                  or if no valid sensor values are available; otherwise False.
        """
        if "is_dark" in self._runtime_cache:
            return self._runtime_cache["is_dark"]

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
        result = avg < self.minimum_luminance
        self._runtime_cache["is_dark"] = result
        return result

    def _current_state_any_light_is_on(self) -> bool:
        """
        Check if any device in current_lights_status is on.

        A device is considered "on" if its status is True or its brightness is > 0.

        Returns:
            bool: True if any light is on, False otherwise.
        """
        for status in self.current_lights_status():
            if status is True or (isinstance(status, (int, float)) and status > 0):
                return True
        return False

    def check_in(self):
        """
        Mark the zone as checked in (not being processed).
        """
        self._checked_out = False
        self._debug_log(f"Zone '{self.name}' checked in")

    def check_out(self):
        """
        Mark the zone as checked out (currently being processed).
        """
        self._checked_out = True
        self._debug_log(f"Zone '{self.name}' checked out")

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
            item["dev_id"]: item["brightness"]
            for item in self.current_lights_status(include_lock_excluded=True)
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
                self._debug_log(
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
                utils.send_to_indigo(dev_id, desired_brightness)
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

    def _write_debug_output(self, config) -> str:
        """
        Dynamically construct debug output by iterating over the zone's attributes.
        For list attributes, if the key is '_lighting_periods' or 'lighting_periods', print them in detail.
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

    def calculate_target_brightness(self) -> BrightnessPlan:
        """
        Calculate and return a BrightnessPlan explaining lighting actions based on:
          1. Global behavior variables overriding all zones.
          2. Active lighting period rules (presence, darkness, period mode).
          3. Brightness limits and exclusion mappings.

        Returns:
            BrightnessPlan: Detailed plan with contributions, exclusions, new targets, and device changes.
        """
        self._debug_log("Calculating target brightness plan")
        # GLOBAL PLUGIN DISABLED: plugin globally disabled, turn all lights off
        if not self._config.enabled:
            all_devs = self.on_lights_dev_ids + self.off_lights_dev_ids
            new_targets = [{"dev_id": d, "brightness": 0} for d in all_devs]
            device_changes = []
            for d in all_devs:
                dev = indigo.devices[d]
                device_changes.append(["🔌", f"turned off '{dev.name}'"])
            return BrightnessPlan(
                contributions=[],
                exclusions=[],
                new_targets=new_targets,
                device_changes=device_changes,
            )
        # -- Global override: check for global lights-off conditions
        global_plan = self._config.has_global_lights_off(self)
        if global_plan.contributions:
            return global_plan

        # -- No active lighting period: nothing to do
        if self.current_lighting_period is None:
            return BrightnessPlan(
                contributions=[], exclusions=[], new_targets=[], device_changes=[]
            )

        # -- Initialize plan details
        plan_contribs: List[Tuple[str, str]] = []
        plan_exclusions: List[Tuple[str, str]] = []

        period = self.current_lighting_period
        presence = self.has_presence_detected()
        darkness = self.is_dark()
        limit_b = getattr(period, "limit_brightness", None)

        plan_contribs.append(("👫", f"presence detected = {presence}"))
        if self.luminance_dev_ids:
            plan_contribs.append(
                (
                    "🌝",
                    f"is dark = {darkness} (luminance={self.luminance}, minimum brightness={int(self.minimum_luminance)})",
                )
            )

        # we know `period` is non-None here, so just log its name/limits
        plan_contribs.append(
            (
                "⏰",
                f"period '{period.name}' mode='{period.mode}' from {period.from_time.strftime('%H:%M')} to {period.to_time.strftime('%H:%M')}",
            )
        )
        if limit_b is not None:
            plan_contribs.append(("⚖️", f"limit_brightness override = {limit_b}"))

        new_targets: List[dict] = []

        # -- Handle 'On and Off' mode when presence is detected and it's dark
        if period.mode is LightingPeriodMode.ON_AND_OFF and presence and darkness:
            plan_contribs.append(("💡", "presence & dark → turning on lights"))
            for dev_id in self.on_lights_dev_ids:
                excluded = self.has_dev_lighting_mapping_exclusion(dev_id, period)
                if excluded:
                    plan_exclusions.append(["❌", f"{indigo.devices[dev_id].name} is excluded from current period"])
                    continue
                if not self.adjust_brightness:
                    brightness = 100
                else:
                    raw = math.ceil(
                        (1 - (self.luminance / self.minimum_luminance)) * 100
                    )
                    brightness = min(raw, limit_b) if limit_b is not None else raw
                new_targets.append({"dev_id": dev_id, "brightness": brightness})

            # force-off any on-lights that are excluded from this period,
            # then your normal off_lights list when in force-off mode
            if (
                self.off_lights_behavior == "force off unless zone is locked"
                and not self.locked
            ):
                plan_contribs.append(("🔌", "off-lights behavior → force off"))
                # Turn off excluded on_lights
                for dev_id in self.on_lights_dev_ids:
                    if self.has_dev_lighting_mapping_exclusion(dev_id, period):
                        new_targets.append({"dev_id": dev_id, "brightness": 0})
                # Then turn off configured off_lights
                for off_id in self.off_lights_dev_ids:
                    new_targets.append({"dev_id": off_id, "brightness": 0})
        else:
            if not presence:
                plan_contribs.append(("👥", "no presence → turning all off"))
            elif not darkness:
                plan_contribs.append(("☀️", "zone is bright enough → turning all off"))

            # include *all* lights (even those excluded from locks) in our off-targets
            new_targets = [
                {"dev_id": d["dev_id"], "brightness": 0}
                for d in self.current_lights_status(include_lock_excluded=True)
            ]

        current = {
            d["dev_id"]: d["brightness"]
            for d in self.current_lights_status(include_lock_excluded=True)
        }

        # -- Compare current vs new targets to build device_changes
        device_changes: List[Tuple[str, str]] = []
        for t in new_targets:
            did, new_b = t["dev_id"], t["brightness"]
            old_b = current.get(did)
            if old_b is not None and old_b != new_b:
                device = indigo.devices[did]

                # Determine change style: off always on/off, on for relays, brightness-up for dimmers
                if new_b == 0:
                    emoji = "🔌"
                    device_changes.append(["🔌", f"turned off '{device.name}'"])
                elif not isinstance(device, indigo.DimmerDevice):
                    emoji = "💡"
                    device_changes.append(["💡", f"turned on '{device.name}'"])
                else:
                    emoji = "🔆" if isinstance(new_b, int) and new_b > old_b else "⬇️"
                    # use device name when any exclusions exist, otherwise zone name
                    label = device.name if plan_exclusions else self.name
                    device_changes.append([emoji, f"{label}: {old_b} → {new_b}"])

        return BrightnessPlan(
            contributions=plan_contribs,
            exclusions=plan_exclusions,
            new_targets=new_targets,
            device_changes=device_changes,
        )

    @property
    def device_period_map(self) -> dict:
        """Mapping of device IDs to lighting period inclusion/exclusion."""
        return self._device_period_map

    @property
    def global_behavior_variables_map(self) -> dict:
        """Mapping of global behavior variable IDs to whether they apply to this zone."""
        return self._global_behavior_variables_map

    @global_behavior_variables_map.setter
    def global_behavior_variables_map(self, value: dict) -> None:
        self._global_behavior_variables_map = value
        # sync to indigo after zone_index set
        if getattr(self, "_zone_index", None) is not None:
            self.sync_indigo_device()

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
        cache_key = f"excl_{dev_id}_{lighting_period.id}"
        if cache_key in self._runtime_cache:
            return self._runtime_cache[cache_key]

        device_map = self.device_period_map.get(str(dev_id), {})
        result = device_map.get(str(lighting_period.id), True) is False
        self._runtime_cache[cache_key] = result
        self._debug_log(
            f"has_dev_lighting_mapping_exclusion: dev_id={dev_id}, period={lighting_period.name}, device_map={device_map}, result={result}"
        )
        self._debug_log(f"has_device: dev_id={dev_id}, result={result}")
        return result

    @property
    def zone_index(self) -> int:
        return self._zone_index

    @zone_index.setter
    def zone_index(self, value: int) -> None:
        self._zone_index = value

    @property
    def indigo_dev(self) -> indigo.Device:
        """
        Retrieve or create the Indigo device for this zone.
        Caches device via self._indigo_dev_id.
        """
        # Return cached device if ID known
        if self._indigo_dev_id is not None:
            return indigo.devices[self._indigo_dev_id]

        # Try to find an existing plugin device with our zone_index
        for d in indigo.devices:
            if (
                d.pluginId == "com.vtmikel.autolights"
                and d.deviceTypeId == "auto_lights_zone"
                and d.pluginProps.get("zone_index") == self.zone_index
            ):
                self._indigo_dev_id = d.id
                return d

        # Didn't find it, so attempt to create one
        try:
            name = f"Auto Lights Zone - {self.name}"
            dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                name=name,
                address=self.zone_index,
                deviceTypeId="auto_lights_zone",
                props={"zone_index": self.zone_index},
            )
            self._indigo_dev_id = dev.id
            indigo.device.turnOn(dev.id, delay=0)
            self.logger.info(
                f"🆕 Created new Indigo device for Zone '{self.name}' (id: {dev.id})"
            )
            return dev
        except Exception as e:
            self.logger.error(
                f"error creating new indigo device for Zone '{self.name}': {e}"
            )
            return None

    def _build_schema_states(self, dev):
        """Collect states based on schema-driven sync attributes."""
        states = []
        for attr in self.zone_indigo_device_config_states:
            if attr in dev.states:
                val = getattr(self, attr)
                states.append(
                    {
                        "key": attr,
                        "value": json.dumps(val) if isinstance(val, list) else val,
                    }
                )
        return states

    def _get_runtime_state_value(self, key):
        """
        Retrieve the runtime state value for the given key using the getter in config.zone_indigo_device_runtime_states.
        """
        for entry in self.zone_indigo_device_runtime_states:
            if entry.get("key") == key:
                return entry["getter"](self)
        return None

    def _build_runtime_states(self, dev):
        """Collect dynamic runtime states for Indigo device."""
        states = []
        for entry in self.zone_indigo_device_runtime_states:
            key = entry["key"]
            if key in dev.states:
                val = self._get_runtime_state_value(key)
                if val is not None:
                    states.append({"key": key, "value": val})
        return states

    def sync_indigo_device(self) -> None:
        """
        Sync Indigo device states based on schema-driven and dynamic runtime values.

        Combines configured sync attributes and runtime state mappings
        into a single update to the Indigo server.
        """
        dev = self.indigo_dev
        if dev is None:
            self.logger.error(
                f"Zone '{self._name}': no Indigo device found, skipping sync"
            )
            return

        # Update device name to match zone name
        expected_name = f"Auto Lights Zone - {self.name}"
        if dev.name != expected_name:
            try:
                dev.name = expected_name
                dev.replaceOnServer()
            except Exception as e:
                self.logger.error(
                    f"Failed to rename Indigo device for Zone '{self._name}': {e}"
                )
        # Build list from schema-driven attributes
        state_list = self._build_schema_states(dev)

        # Append dynamic runtime states
        state_list.extend(self._build_runtime_states(dev))

        try:
            dev.updateStatesOnServer(state_list)
        except Exception as e:
            self.logger.error(f"Failed to sync states for zone '{self._name}': {e}")
        # Update onOffState with UI value
        try:
            on_state = dev.onState
            if self.locked:
                ui = "Locked"
            elif on_state:
                ui = "Enabled"
            else:
                ui = "Disabled"
            dev.updateStateOnServer("onOffState", on_state, uiValue=ui)
        except Exception as e:
            self.logger.error(f"Failed to update onOffState for zone '{self._name}': {e}")

    def _has_device(self, dev_id: int) -> str:
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

    def _process_expired_lock(self) -> None:
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
                f"🔁Lock extended for zone '{self._name}' until {self.lock_expiration_str}"
            )
        else:
            self.locked = False
            self.logger.info(
                f"🔓️Lock expired for zone '{self._name}' and zone is now unlocked"
            )

    def has_variable(self, var_id: int) -> bool:
        """
        Check if the provided variable id is associated with this zone.

        This method determines if the given variable id matches the zone's minimum luminance variable id.
        """
        if (
            self._minimum_luminance_var_id is not None
            and var_id == self._minimum_luminance_var_id
        ):
            return True
        return False

    def get_device_states_string(self) -> str:
        """
        Returns a semicolon-separated string showing each 'On' and 'Off' light in this zone,
        with its current brightness/state, its target brightness/state, and an
        optional note when it is excluded from the active lighting period.
        """
        lines: list[str] = []

        # make a single call to current_lights_status so we don’t re-query Indigo every time
        all_status = self.current_lights_status(include_lock_excluded=True)
        status_map = {item["dev_id"]: item["brightness"] for item in all_status}
        target_map = {
            item["dev_id"]: item["brightness"]
            for item in (self.target_brightness or [])
        }

        for dev_id in self.on_lights_dev_ids + self.off_lights_dev_ids:
            try:
                dev = indigo.devices[dev_id]
            except Exception:
                # device may have been removed
                continue

            curr = status_map.get(dev_id, None)
            tgt = target_map.get(dev_id, None)

            light_type = "On Light" if dev_id in self.on_lights_dev_ids else "Off Light"
            excluded = ""
            period = self.current_lighting_period
            if period and self.has_dev_lighting_mapping_exclusion(dev_id, period):
                excluded = " (excluded from Lighting Period)"

            lines.append(
                f"{light_type} '{dev.name}': current={curr}, " f"target={tgt}{excluded}"
            )

        return ";".join(lines)

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
