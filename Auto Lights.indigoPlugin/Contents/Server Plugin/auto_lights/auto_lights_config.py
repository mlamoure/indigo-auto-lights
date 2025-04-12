import json
import logging
from typing import List

from .lighting_period import LightingPeriod
from .zone import Zone

try:
    import indigo
except ImportError:
    pass


class AutoLightsConfig:
    """
    Configuration handler for the auto_lights script, managing time-of-day logic, presence, and brightness values.
    """

    def __init__(self, config: str) -> None:
        """
        Initialize the AutoLightsConfig with default numeric values for
        early hours, night hours, and the target brightness.

        The properties can be adjusted as needed to fine-tune lighting behavior.
        """
        self.logger = logging.getLogger("Plugin")
        self._enabled = False

        self._guest_mode = False
        self._enabled_var_id = -1
        self._guest_mode_var_id = -1
        self._default_lock_duration = 0
        self._default_lock_extension_duration = 0
        self._global_behavior_variables = []

        self._zones = []
        self._lighting_periods = []

        self._config_file = config

        self.load_config()

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

    @property
    def global_behavior_variables(self) -> List[dict]:
        """
        A list of dictionaries each containing a variable ID (var_id) and a variable value (var_value)
        available for global behavior adjustments.

        Each dictionary has the format:
        {
            "var_id": int,  # Indigo variable ID
            "var_value": str  # Value to check against
        }
        """
        return self._global_behavior_variables

    @global_behavior_variables.setter
    def global_behavior_variables(self, value: List[dict]) -> None:
        """
        Set the list of global behavior variables.
        Each item should be a dictionary with 'var_id' (int) and 'var_value' (str).
        """
        self._global_behavior_variables = value

    def load_config(self) -> None:
        with open(self._config_file, "r") as f:
            data = json.load(f)
        self.from_config_dict(data)

    def from_config_dict(self, data: dict) -> None:
        self.logger.debug("from_config_dict called")
        # Process plugin_config
        plugin_config = data.get("plugin_config", {})
        for key, value in plugin_config.items():
            if hasattr(self, key):
                setattr(self, key, value)

        # Process lighting periods into LightingPeriod objects
        self._lighting_periods = []
        lp_data = data.get("lighting_periods", [])
        for lp in lp_data:
            lp_instance = LightingPeriod.from_config_dict(lp)
            self._lighting_periods.append(lp_instance)

        # Process zones into Zone objects
        self._zones = []
        zones_data = data.get("zones", [])
        for zone_d in zones_data:
            z = Zone(zone_d.get("name"), self)
            z.from_config_dict(zone_d)
            # set lighting_periods based on reference ids
            ref_ids = zone_d.get("lighting_period_ids", [])
            zone_lps = []
            for ref in ref_ids:
                for lp in self._lighting_periods:
                    if lp.id == ref:
                        zone_lps.append(lp)
                        break
            z.lighting_periods = zone_lps
            self._zones.append(z)

        for zone in self._zones:
            zone.calculate_target_brightness()

        self.logger.debug("from_config_dict finished")

    @property
    def zones(self) -> List[Zone]:
        return self._zones
