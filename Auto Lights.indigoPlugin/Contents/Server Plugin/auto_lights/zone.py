import ast
import datetime
from typing import List, Union, Any, Optional, TYPE_CHECKING
import logging

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
    Represents an AutoLights zone, encompassing configuration, devices,
    lighting periods, and states for controlling lighting behavior.
    """

    # (2) Class variables or constants would go here if we had any.

    # (3) Constructor
    def __init__(self, name: str, config: 'AutoLightsConfig'):
        """
        Initialize a Zone instance.
        
        Args:
            name (str): The name of the zone.
            config (AutoLightsConfig): The global auto lights configuration.
        """
        self.logger = logging.getLogger("com.vtmikel.autolights.Zone")
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

        self._presence_dev_id = None
        self._minimum_luminance = 10000
        self._minimum_luminance_var_id = None

        self._current_lights_status = []
        self._target_brightness = None
        self._target_brightness_all_off = None

        # Behavior flags and settings
        self._adjust_brightness = False
        self._adjust_brightness_when_active = True
        self._perform_confirm = True
        self._lock_duration = None
        self._extend_lock_when_active = True
        self._turn_off_while_sleeping = False
        self._unlock_when_no_presence = True

        self._lock_expiration = None
        self._config = config

        self._last_changed_by = "none"
        self._previous_execution_lights_target = None
        self._locked = None
        self._special_rules_adjustment = ""
        self._lock_enabled = False
        self._lock_extension_duration = None
        self._global_behavior_variables = []

    def from_config_dict(self, cfg: dict) -> None:
        if "enabled_var_id" in cfg:
            self.enabled_var_id = cfg["enabled_var_id"]
        if "device_settings" in cfg:
            ds = cfg["device_settings"]
            if "on_lights_dev_ids" in ds:
                self.on_lights_dev_ids = ds["on_lights_dev_ids"]
            if "off_lights_dev_ids" in ds:
                self.off_lights_dev_ids = ds["off_lights_dev_ids"]
            if "lumaninance_dev_ids" in ds:
                self.luminance_dev_ids = ds["lumaninance_dev_ids"]
            if "presence_dev_id" in ds:
                self.presence_dev_id = ds["presence_dev_id"]
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
            if "turn_off_while_sleeping" in bs:
                self.turn_off_while_sleeping = bs["turn_off_while_sleeping"]
            if "unlock_when_no_presence" in bs:
                self.unlock_when_no_presence = bs["unlock_when_no_presence"]
        if "global_behavior_variables" in cfg:
            self.global_behavior_variables = cfg["global_behavior_variables"]

    # (4) Properties
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
    def last_changed_by(self) -> str:
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
        self.target_brightness = self.current_lights_status

    @property
    def off_lights_dev_ids(self) -> List[int]:
        """List of device IDs that should be turned off."""
        return self._off_lights_dev_ids

    @off_lights_dev_ids.setter
    def off_lights_dev_ids(self, value: List[int]) -> None:
        self._off_lights_dev_ids = value
        self.target_brightness = self.current_lights_status

    @property
    def presence_dev_id(self) -> int:
        """Identifier for device reporting presence."""
        return self._presence_dev_id

    @presence_dev_id.setter
    def presence_dev_id(self, value: int) -> None:
        self._presence_dev_id = value

    @property
    def luminance_dev_ids(self) -> List[int]:
        return self._luminance_dev_ids

    @luminance_dev_ids.setter
    def luminance_dev_ids(self, value: List[int]) -> None:
        self._luminance_dev_ids = value

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
            self._current_lights_status.append(get_device_status(indigo.devices[dev_id]))

        # Gather off_lights
        for dev_id in self.off_lights_dev_ids:
            if dev_id in self.exclude_from_lock_dev_ids:
                continue
            self._current_lights_status.append(get_device_status(indigo.devices[dev_id]))
        return self._current_lights_status

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
        """Set target brightness for on/off lights."""
        if isinstance(value, list):
            for i, val in enumerate(value):
                if isinstance(val, int) and val > 100:
                    value[i] = 100
            self._target_brightness = value
        else:
            self._target_brightness = []
            # Handle on-lights
            for dev_id in self.on_lights_dev_ids:
                if indigo.devices[dev_id].pluginId == "com.pennypacker.indigoplugin.senseme":
                    self._target_brightness.append(int((value / 100) * 16))
                elif isinstance(value, bool) or isinstance(indigo.devices[dev_id], indigo.DimmerDevice):
                    self._target_brightness.append(min(value, 100) if isinstance(value, int) else value)
                elif value > 0:
                    self._target_brightness.append(True)
                else:
                    self._target_brightness.append(False)
            # Handle off-lights
            off_device_target = 0 if (isinstance(value, bool) and not value) or value == 0 else -1
            for dev_id in self.off_lights_dev_ids:
                if off_device_target == -1:
                    if isinstance(indigo.devices[dev_id], indigo.DimmerDevice):
                        self._target_brightness.append(indigo.devices[dev_id].brightness)
                    elif isinstance(indigo.devices[dev_id], indigo.RelayDevice):
                        self._target_brightness.append(indigo.devices[dev_id].onState)
                    elif "brightness" in indigo.devices[dev_id].states:
                        self._target_brightness.append(indigo.devices[dev_id].states["brightness"])
                else:
                    if isinstance(indigo.devices[dev_id], indigo.DimmerDevice) or "brightness" in indigo.devices[dev_id].states:
                        self._target_brightness.append(0)
                    else:
                        self._target_brightness.append(False)

    @property
    def current_lighting_period(self) -> Optional[LightingPeriod]:
        if self._current_lighting_period is None:
            if not self.lighting_periods:
                self.logger.info("no periods for zone " + self._name)
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
        if self.presence_dev_id is not None and indigo.devices[self.presence_dev_id].lastChanged > device_last_changed:
            device_last_changed = indigo.devices[self.presence_dev_id].lastChanged
        for dev_id in self.luminance_dev_ids:
            if indigo.devices[dev_id].lastChanged > device_last_changed:
                device_last_changed = indigo.devices[dev_id].lastChanged
        return device_last_changed

    @property
    def previous_target_var_name(self) -> str:
        return self._name.replace(" ", "_") + "__autoLights_previousTarget"

    @property
    def previous_execution_lights_target(self) -> Union[str, List[Union[bool, int]]]:
        if self._previous_execution_lights_target is not None:
            return self._previous_execution_lights_target
        if "auto_lights_script" not in indigo.variables.folders:
            indigo.folders.create("auto_lights_script")
        var_folder = indigo.variables.folders["auto_lights_script"]
        try:
            prev_var = indigo.variables[self.previous_target_var_name]
        except KeyError:
            prev_var = indigo.variable.create(self.previous_target_var_name, "false", folder=var_folder)
        self._previous_execution_lights_target = prev_var.value
        try:
            self._previous_execution_lights_target = ast.literal_eval(prev_var.value)
        except Exception as e:
            indigo.server.log(f"Error converting previous_execution_lights_target: {e}")
            self._previous_execution_lights_target = []
        return self._previous_execution_lights_target

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
            indigo.server.log("check_out_var: created variable " + var_name)
        return debug_var

    @property
    def checked_out(self) -> bool:
        return self.check_out_var.getValue(bool)

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
        if self.current_lighting_period and self.current_lighting_period.has_lock_duration_override:
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
        var_name = self._name.replace(" ", "_") + "_autoLights__locked"
        try:
            locked_var = indigo.variables[var_name]
        except KeyError:
            if "auto_lights_script" not in indigo.variables.folders:
                pass
            var_folder = indigo.variables.folders["auto_lights_script"]
            locked_var = indigo.variable.create(var_name, "false", folder=var_folder)
        return locked_var

    @property
    def locked(self) -> bool:
        """Determines if the zone is currently locked."""
        if not self.lock_enabled:
            return False
        return self._locked

    @locked.setter
    def locked(self, value: bool) -> None:
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
            self._lock_expiration = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
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

    @property
    def global_behavior_variables(self) -> list:
        """
        A list of tuples each containing a variable ID (int) and a variable value (str)
        available for global behavior adjustments.
        """
        return self._global_behavior_variables

    @global_behavior_variables.setter
    def global_behavior_variables(self, value: list) -> None:
        """
        Set the list of global behavior variables.
        Each item should be an object with 'var_id' (int) and 'var_value' (str).
        """
        self._global_behavior_variables = value

    @property
    def special_rules_adjustment(self) -> str:
        return self._special_rules_adjustment

    @special_rules_adjustment.setter
    def special_rules_adjustment(self, value: str) -> None:
        self._special_rules_adjustment = value

    # (5) Public methods
    def has_presence_detected(self) -> bool:
        """
        Check if presence is detected in this zone or, if defined, in the current period.
        """
        if self.current_lighting_period and self.current_lighting_period.uses_presence_override:
            return self.current_lighting_period.has_presence_detected()
        if self.presence_dev_id is not None:
            if "onOffState" in indigo.devices[self.presence_dev_id].states:
                if indigo.devices[self.presence_dev_id].states["onOffState"]:
                    return True
            elif indigo.devices[self.presence_dev_id].onState:
                return True
        return False

    def is_dark(self) -> bool:
        """
        Decide if the zone is considered dark based on sensor readings or the current lighting period.
        """
        if self.current_lighting_period and self.current_lighting_period.uses_luminance_override:
            return self.luminance >= self.current_lighting_period.minimum_luminance
        if not self.luminance_dev_ids:
            return True
        for dev_id in self.luminance_dev_ids:
            if indigo.devices[dev_id].sensorValue < self.minimum_luminance:
                return True
        return False

    def current_state_any_light_is_on(self) -> bool:
        """
        Check if any device in current_lights_status is on (True or brightness > 0).
        """
        for status in self.current_lights_status:
            if status is True or (isinstance(status, (int, float)) and status > 0):
                return True
        return False

    def check_in(self):
        """Check in the zone by setting the checkout variable to False."""
        indigo.variable.updateValue(self.check_out_var, str(False))

    def force_check_in(self):
        """Force check in the zone, logging a message if it was previously checked out."""
        if self.checked_out:
            self.logger.info("       ... zone " + self._name + ": forced check in")
        indigo.variable.updateValue(self.check_out_var, str(False))

    def check_out(self):
        """
        Check out the zone by setting the checkout variable to True if it is not already checked out.
        """
        if not self.checked_out:
            indigo.variable.updateValue(self.check_out_var, str(True))

    def reset_lock(self, reason: str):
        """Reset the lock for the zone."""
        self._lock_expiration = datetime.datetime.now() - datetime.timedelta(minutes=1)
        indigo.variable.updateValue(self.lock_var, str(self.lock_expiration_str))
        self._locked = False
        self._previous_execution_lights_target = self.current_lights_status
        indigo.variable.updateValue(self.previous_target_var_name, str(self._current_lights_status))
        self.logger.info(f"auto_lights script for Zone '{self._name}', zone lock reset because {reason}")

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
                indigo.server.log(f"Warning: Missing target brightness for device with ID {dev_id}")
                continue
            self._send_to_indigo(dev_id, dev_target)

        # Save final state to an Indigo variable for lock detection
        indigo.variable.updateValue(self.previous_target_var_name, str(self.target_save_state))

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

    @property
    def special_rules_adjustment(self) -> str:
        return self._special_rules_adjustment

    @special_rules_adjustment.setter
    def special_rules_adjustment(self, value: str) -> None:
        self._special_rules_adjustment = value

    def run_special_rules(self) -> None:
        """Placeholder for zone-specific rules."""
        pass

    def calculate_target_brightness(self) -> None:
        """
        If adjust_brightness is True, set the on lights to (luminance - minimum_luminance) if >0, else 0.
        Set off lights to 0.
        """
        if self._adjust_brightness:
            diff = self.luminance - self.minimum_luminance
            diff = diff if diff > 0 else 0
            new_tb = [diff] * len(self._on_lights_dev_ids) + [0] * len(self._off_lights_dev_ids)
            self.target_brightness = new_tb

    def has_device(self, dev_id: int) -> str:
        """
        Check if the given device ID exists in this zone's device lists.
        """
        if dev_id in self.exclude_from_lock_dev_ids:
            return "exclude_from_lock_dev_ids"
        if dev_id in self._on_lights_dev_ids:
            return "on_lights_dev_ids"
        if dev_id in self._off_lights_dev_ids:
            return "off_lights_dev_ids"
        if self._presence_dev_id == dev_id:
            return "presence_dev_id"
        if dev_id in self._luminance_dev_ids:
            return "luminance_dev_ids"
        return ""

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
        if self._minimum_luminance_var_id is not None and var_id == self._minimum_luminance_var_id:
            return True
        elif var_id == self._enabled_var_id:
            return True

        return False

    # (6) Private methods
    def _send_to_indigo(self, device_id: int, desired_brightness: int | bool) -> None:
        """
        Send a command to update an Indigo device and ensure it is confirmed if self.perform_confirm is True.
        """
        utils.send_to_indigo(device_id, desired_brightness, self._perform_confirm, self._config.debug)

