import json
from .zone import Zone
from .lighting_period import LightingPeriod

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
        with open(config_file, "r") as f:
            data = json.load(f)
        self.from_config_dict(data)

    def from_config_dict(self, data: dict) -> None:
        # Process plugin_config
        plugin_config = data.get("plugin_config", {})
        for key, value in plugin_config.items():
            if hasattr(self, key):
                setattr(self, key, value)

        # Process zones into Zone objects
        self._zones = []
        zones_data = data.get("zones", [])
        for zone_d in zones_data:
            z = Zone(zone_d.get("name"), self)
            z.from_config_dict(zone_d)
            self._zones.append(z)

        # Process lighting periods into LightingPeriod objects
        self._lighting_periods = []
        lp_data = data.get("lighting_periods", [])
        for lp in lp_data:
            lp_instance = LightingPeriod.from_config_dict(lp)
            self._lighting_periods.append(lp_instance)

