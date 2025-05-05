import json
from typing import List, Tuple
from .auto_lights_base import BrightnessPlan

from .auto_lights_base import AutoLightsBase
from .lighting_period import LightingPeriod
from .zone import Zone

try:
    import indigo
except ImportError:
    pass


class AutoLightsConfig(AutoLightsBase):
    """
    Configuration handler for the auto_lights script, managing time-of-day logic, presence, and brightness values.
    """

    def __init__(self, config: str) -> None:
        """
        Initialize the AutoLightsConfig with default numeric values for
        early hours, night hours, and the target brightness.

        The properties can be adjusted as needed to fine-tune lighting behavior.
        """
        super().__init__()
        self.log_non_events = False
        self._enabled = False

        self._enabled_var_id = -1
        self._default_lock_duration = 0
        self._default_lock_extension_duration = 0
        self._global_behavior_variables = []

        self._zones = []
        self._lighting_periods = []

        self._config_file = config

        # Load JSON schema to identify which zone fields to sync
        from pathlib import Path
        import json
        schema_path = Path(__file__).parent.parent / "config_web_editor" / "config" / "config_schema.json"
        with open(schema_path) as f:
            schema = json.load(f)
        zone_props = schema["properties"]["zones"]["items"]["properties"]
        self.zone_field_schemas = {}
        self.sync_zone_attrs = set()
        def _collect(p):
            for k, v in p.items():
                self.zone_field_schemas[k] = v
                if v.get("x-sync_to_indigo"):
                    self.sync_zone_attrs.add(k)
                if v.get("type") == "object" and "properties" in v:
                    _collect(v["properties"])
        _collect(zone_props)

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
        self._debug_log("from_config_dict called")
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
        # Build a map of period id to instance for ordering
        period_map = {p.id: p for p in self._lighting_periods}

        # Process zones into Zone objects
        self._zones = []
        zones_data = data.get("zones", [])
        for zone_d in zones_data:
            z = Zone(zone_d.get("name"), self)
            z.from_config_dict(zone_d)
            # Retrieve ordered lighting_period_ids or fallback to global order
            raw_ids = zone_d.get("lighting_period_ids", None)
            if raw_ids is None:
                ordered_ids = [p.id for p in self._lighting_periods]
            else:
                ordered_ids = raw_ids
            # Assign ordered LightingPeriod instances
            z.lighting_periods = [period_map[i] for i in ordered_ids if i in period_map]
            self._zones.append(z)
        # assign zone_index to each zone
        for idx, z in enumerate(self._zones):
            z.zone_index = idx

        # now that every zone has a valid zone_index, push its initial states to Indigo
        for z in self._zones:
            z._sync_indigo_device()

        for zone in self._zones:
            zone.calculate_target_brightness()

        self._debug_log("from_config_dict finished")

    @property
    def zones(self) -> List[Zone]:
        return self._zones

    def has_variable(self, var_id: int) -> bool:
        for behavior in self.global_behavior_variables:
            if behavior.get("var_id") == var_id:
                return True
        return False

    def has_global_lights_off(self) -> BrightnessPlan:
        """
        Check global behavior variables to determine if global lights should be turned off.
        Returns a BrightnessPlan with any triggers contributing to global off.
        """
        plan_contribs: List[Tuple[str,str]] = []
        for behavior in self._global_behavior_variables:
            var_id = behavior.get("var_id")
            var_value = behavior.get("var_value")
            comp_type = behavior.get("comparison_type")
            try:
                current_value = indigo.variables[var_id].value
                var_name = indigo.variables[var_id].name
            except Exception:
                continue
            lc_current = str(current_value).lower()
            lc_var_value = str(var_value).lower()
            if comp_type == "is equal to (str, lower())" and lc_current == lc_var_value:
                plan_contribs.append(("🌐", f"Variable {var_name} equals expected value '{var_value}'"))
            elif comp_type == "is not equal to (str, lower())" and lc_current != lc_var_value:
                plan_contribs.append(("🌐", f"Variable {var_name} does not equal '{var_value}'"))
            elif comp_type == "is TRUE (bool)" and lc_current in ["true", "1"]:
                plan_contribs.append(("🌐", f"Variable {var_name} evaluated as True"))
            elif comp_type == "is FALSE (bool)" and lc_current in ["false", "0"]:
                plan_contribs.append(("🌐", f"Variable {var_name} evaluated as False"))
            elif comp_type is None and lc_current == lc_var_value:
                plan_contribs.append(("🌐", f"Variable {var_name} equals (default) '{var_value}'"))
        return BrightnessPlan(
            contributions=plan_contribs,
            exclusions=[],
            new_targets=[],
            device_changes=[],
        )
