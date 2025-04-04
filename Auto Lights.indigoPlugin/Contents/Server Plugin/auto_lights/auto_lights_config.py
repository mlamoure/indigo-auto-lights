import datetime
import json

try:
    import indigo
except ImportError:
    pass


class AutoLightsConfig:
    """
    Configuration handler for the auto_lights script, managing time-of-day logic, presence, and brightness values.
    """

    def __init__(self) -> None:
        """
        Initialize the AutoLightsConfig with default numeric values for
        early hours, night hours, and the target brightness.

        The properties can be adjusted as needed to fine-tune lighting behavior.
        """
        self._enabled = False

        self._guest_mode = False
        self._someone_home = False
        self._gone_to_bed = False
        self._enabled_var_id = -1
        self._someone_home_var_id = -1
        self._gone_to_bed_var_id = -1
        self._guest_mode_var_id = -1
        self._rapid_execution_lock = False
        self._default_lock_duration = 0
        self._default_lock_extension_duration = 0

        self._zones = []
        self._lighting_periods = []

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = value

    @property
    def enabled_var_id(self):
        return self._enabled_var_id

    @enabled_var_id.setter
    def enabled_var_id(self, value):
        self._enabled_var_id = value
        self._enabled = indigo.variables[self._enabled_var_id].getValue(bool)
        # indigo.server.log("AutoLightsConfig: enabled set to: " + str(self._enabled))

    @property
    def guest_mode(self):
        return self._guest_mode

    @property
    def guest_mode_var_id(self):
        return self._guest_mode_var_id

    @guest_mode_var_id.setter
    def guest_mode_var_id(self, value):
        self._guest_mode_var_id = value
        self._guest_mode = indigo.variables[self._guest_mode_var_id].getValue(bool)

    @property
    def someone_home(self):
        return self._someone_home

    @someone_home.setter
    def someone_home(self, value):
        self._someone_home = value

    @property
    def someone_home_var_id(self):
        return self._someone_home_var_id

    @someone_home_var_id.setter
    def someone_home_var_id(self, value):
        self._someone_home_var_id = value
        self._someone_home = indigo.variables[self._someone_home_var_id].getValue(bool)

    @property
    def gone_to_bed(self):
        return self._gone_to_bed

    @gone_to_bed.setter
    def gone_to_bed(self, value):
        self._gone_to_bed = value

    @property
    def gone_to_bed_var_id(self):
        return self._gone_to_bed_var_id

    @gone_to_bed_var_id.setter
    def gone_to_bed_var_id(self, value):
        self._gone_to_bed_var_id = value
        self._gone_to_bed = indigo.variables[self._gone_to_bed_var_id].getValue(bool)

    @property
    def default_lock_duration(self) -> int:
        return self._default_lock_duration

    @default_lock_duration.setter
    def default_lock_duration(self, value: int) -> None:
        self._default_lock_duration = value

    @property
    def default_lock_extension_duration(self) -> int:
        return self._default_lock_extension_duration

    @default_lock_extension_duration.setter
    def default_lock_extension_duration(self, value: int) -> None:
        self._default_lock_extension_duration = value


    def load_config(self, config_file: str) -> None:
        import datetime
        from .zone import Zone
        from .lighting_period import LightingPeriod

        with open(config_file, "r") as f:
            data = json.load(f)

        plugin_config = data.get("plugin_config", {})

        # Initialize config from plugin_config
        for key, value in plugin_config.items():
            if hasattr(self, key):
                setattr(self, key, value)

        # Process zones into Zone objects
        self._zones = []
        zones_data = data.get("zones", [])
        for zone_d in zones_data:
            z = Zone(zone_d.get("name"), self)
            if "enabled_var_id" in zone_d:
                z.enabled_var_id = zone_d["enabled_var_id"]
            if "device_settings" in zone_d:
                ds = zone_d["device_settings"]
                if "on_lights_dev_ids" in ds:
                    z.on_lights_dev_ids = ds["on_lights_dev_ids"]
                if "off_lights_dev_ids" in ds:
                    z.off_lights_dev_ids = ds["off_lights_dev_ids"]
                if "lumaninance_dev_ids" in ds:
                    z.luminance_dev_ids = ds["lumaninance_dev_ids"]
                if "presence_dev_ids" in ds:
                    z.presence_dev_ids = ds["presence_dev_ids"]
            if "minimum_luminance_settings" in zone_d:
                mls = zone_d["minimum_luminance_settings"]
                if "minimum_luminance" in mls:
                    z.minimum_luminance = mls["minimum_luminance"]
                if "minimum_luminance_var_id" in mls:
                    z.minimum_luminance_var_id = mls["minimum_luminance_var_id"]
            if "behavior_settings" in zone_d:
                bs = zone_d["behavior_settings"]
                if "adjust_brightness" in bs:
                    z.adjust_brightness = bs["adjust_brightness"]
                if "lock_duration" in bs:
                    z.lock_duration = bs["lock_duration"]
                if "extend_lock_when_active" in bs:
                    z.extend_lock_when_active = bs["extend_lock_when_active"]
                if "perform_confirm" in bs:
                    z.perform_confirm = bs["perform_confirm"]
                if "turn_off_while_sleeping" in bs:
                    z.turn_off_while_sleeping = bs["turn_off_while_sleeping"]
                if "unlock_when_no_presence" in bs:
                    z.unlock_when_no_presence = bs["unlock_when_no_presence"]
            self._zones.append(z)

        # Process lighting periods into LightingPeriod objects
        self._lighting_periods = []
        lp_data = data.get("lighting_periods", [])
        for lp in lp_data:
            name = lp.get("name")
            mode = lp.get("mode")
            from_time = datetime.time(lp.get("from_time_hour"), lp.get("from_time_minute"))
            to_time = datetime.time(lp.get("to_time_hour"), lp.get("to_time_minute"))
            lperiod = LightingPeriod(name, mode, from_time, to_time)
            if "lock_duration" in lp:
                lperiod._lock_duration = lp["lock_duration"]
            self._lighting_periods.append(lperiod)

