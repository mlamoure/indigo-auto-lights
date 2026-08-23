"""
Config-authoring tool implementations for the MCP provider API.

Every write follows the same safe cycle: load_config_strict (a corrupt file
raises instead of masquerading as empty) -> mutate -> validate the FULL
document against config_schema.json -> save_config (which auto-backups and
hot-reloads the automation engine). One tool call therefore equals one
config reload, which resets all zone locks — callers batch a whole change
into a single call.
"""

import logging
from typing import Any, Dict, List, Optional

from .validator import validate_config

logger = logging.getLogger("Plugin")


class ToolError(Exception):
    """In-band tool failure carried to the reply envelope, never raised
    across the executeAction boundary."""

    def __init__(self, error_type: str, message: str, details: Any = None):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.details = details


class ConfigToolService:
    """Implements the tools advertised in Contents/Resources/mcp-manifest.json."""

    def __init__(self, config_editor):
        self._editor = config_editor

    # ------------------------------------------------------------------
    # helpers

    def _load(self) -> Dict[str, Any]:
        try:
            return self._editor.load_config_strict()
        except Exception as e:
            raise ToolError(
                "internal",
                f"Could not read the Auto Lights config file: {e}",
            ) from e

    def _validate_and_save(self, config: Dict[str, Any]) -> None:
        errors = validate_config(config, self._editor.config_schema)
        if errors:
            raise ToolError(
                "validation",
                "The change does not conform to the Auto Lights config schema",
                {"errors": errors},
            )
        self._editor.save_config(config)

    def _get_zone(self, config: Dict[str, Any], zone_index: int) -> Dict[str, Any]:
        zones = config.get("zones", [])
        if not isinstance(zone_index, int) or isinstance(zone_index, bool):
            raise ToolError("validation", "zone_index must be an integer")
        if zone_index < 0 or zone_index >= len(zones):
            raise ToolError(
                "not_found",
                f"zone_index {zone_index} is out of range (0..{len(zones) - 1})",
            )
        return zones[zone_index]

    @staticmethod
    def _check_expected_name(
        entity: Dict[str, Any], expected_name: Optional[str], kind: str
    ):
        if expected_name is not None and entity.get("name") != expected_name:
            raise ToolError(
                "conflict",
                f"{kind} name is {entity.get('name')!r}, not {expected_name!r} — "
                f"the config may have changed since it was read; re-read and retry",
            )

    @staticmethod
    def _zone_summary(index: int, zone: Dict[str, Any]) -> Dict[str, Any]:
        return {"zone_index": index, "name": zone.get("name", "")}

    # ------------------------------------------------------------------
    # read tools

    def get_config(self) -> Dict[str, Any]:
        config = self._load()
        return {
            "config": config,
            "zone_indexes": [
                self._zone_summary(i, z) for i, z in enumerate(config.get("zones", []))
            ],
        }

    def list_zones(self) -> Dict[str, Any]:
        config = self._load()
        return {
            "zones": [
                self._zone_summary(i, z) for i, z in enumerate(config.get("zones", []))
            ]
        }

    def get_zone(
        self, zone_index: int, expected_name: Optional[str] = None
    ) -> Dict[str, Any]:
        config = self._load()
        zone = self._get_zone(config, zone_index)
        self._check_expected_name(zone, expected_name, "Zone")
        return {"zone_index": zone_index, "zone": zone}

    def list_lighting_periods(self) -> Dict[str, Any]:
        config = self._load()
        return {"lighting_periods": config.get("lighting_periods", [])}

    def get_lighting_period(self, period_id: int) -> Dict[str, Any]:
        config = self._load()
        for period in config.get("lighting_periods", []):
            if period.get("id") == period_id:
                return {"lighting_period": period}
        raise ToolError("not_found", f"No lighting period with id {period_id}")

    def list_backups(self) -> Dict[str, Any]:
        import os

        return {
            "manual": sorted(self._editor.list_manual_backups(), reverse=True),
            "auto": [os.path.basename(p) for p in self._editor.list_auto_backups()],
        }

    # ------------------------------------------------------------------
    # zone write tools

    def create_zone(self, zone: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(zone, dict):
            raise ToolError("validation", "zone must be an object")
        # Always carry a behavior_settings section so downstream consumers
        # of older config snapshots never hit the historical parsing bug
        zone.setdefault("behavior_settings", {})
        config = self._load()
        config.setdefault("zones", []).append(zone)
        self._validate_and_save(config)
        index = len(config["zones"]) - 1
        return {"zone_index": index, "zone": zone}

    def update_zone(
        self,
        zone_index: int,
        zone: Dict[str, Any],
        expected_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(zone, dict):
            raise ToolError("validation", "zone must be an object")
        config = self._load()
        existing = self._get_zone(config, zone_index)
        self._check_expected_name(existing, expected_name, "Zone")
        # Per-section merge: a supplied section object updates its fields and
        # preserves the rest; scalars and arrays are replaced whole
        for key, value in zone.items():
            if isinstance(value, dict) and isinstance(existing.get(key), dict):
                existing[key].update(value)
            else:
                existing[key] = value
        existing.setdefault("behavior_settings", {})
        self._validate_and_save(config)
        return {"zone_index": zone_index, "zone": existing}

    def delete_zone(self, zone_index: int, expected_name: str) -> Dict[str, Any]:
        config = self._load()
        zone = self._get_zone(config, zone_index)
        # expected_name is mandatory for deletes: zones are addressed by
        # array index, so a stale index silently deletes the wrong zone
        self._check_expected_name(zone, expected_name, "Zone")
        config["zones"].pop(zone_index)
        self._validate_and_save(config)
        return {"deleted": True, "name": zone.get("name", "")}

    # ------------------------------------------------------------------
    # lighting period write tools

    def create_lighting_period(self, period: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(period, dict):
            raise ToolError("validation", "period must be an object")
        config = self._load()
        periods = config.setdefault("lighting_periods", [])
        existing_ids = [p.get("id", 0) for p in periods if isinstance(p.get("id"), int)]
        period["id"] = max(existing_ids, default=0) + 1
        self._apply_period_defaults(period)
        periods.append(period)
        self._validate_and_save(config)
        return {"lighting_period": period}

    def update_lighting_period(
        self, period_id: int, period: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(period, dict):
            raise ToolError("validation", "period must be an object")
        config = self._load()
        for existing in config.get("lighting_periods", []):
            if existing.get("id") == period_id:
                period.pop("id", None)  # ids are stable and immutable
                existing.update(period)
                self._validate_and_save(config)
                return {"lighting_period": existing}
        raise ToolError("not_found", f"No lighting period with id {period_id}")

    def delete_lighting_period(
        self, period_id: int, force: bool = False
    ) -> Dict[str, Any]:
        config = self._load()
        periods = config.get("lighting_periods", [])
        period = next((p for p in periods if p.get("id") == period_id), None)
        if period is None:
            raise ToolError("not_found", f"No lighting period with id {period_id}")

        referencing = [
            self._zone_summary(i, z)
            for i, z in enumerate(config.get("zones", []))
            if period_id in (z.get("lighting_period_ids") or [])
        ]
        if referencing and not force:
            raise ToolError(
                "conflict",
                f"Lighting period {period_id} is referenced by "
                f"{len(referencing)} zone(s); pass force=true to delete it and "
                f"scrub the references",
                {"referencing_zones": referencing},
            )

        periods.remove(period)
        for zone in config.get("zones", []):
            ids = zone.get("lighting_period_ids")
            if isinstance(ids, list) and period_id in ids:
                zone["lighting_period_ids"] = [i for i in ids if i != period_id]
            period_map = zone.get("device_period_map")
            if isinstance(period_map, dict):
                for dev_map in period_map.values():
                    if isinstance(dev_map, dict):
                        dev_map.pop(str(period_id), None)
        self._validate_and_save(config)
        return {
            "deleted": True,
            "name": period.get("name", ""),
            "scrubbed_zones": referencing,
        }

    @staticmethod
    def _apply_period_defaults(period: Dict[str, Any]) -> None:
        defaults = {
            "name": "New Lighting Period",
            "mode": "On and Off",
            "from_time_hour": 0,
            "from_time_minute": 0,
            "to_time_hour": 23,
            "to_time_minute": 45,
            "lock_duration": -1,
            "limit_brightness": -1,
        }
        for key, value in defaults.items():
            if period.get(key) is None:
                period[key] = value

    # ------------------------------------------------------------------
    # plugin config + backups

    def update_plugin_config(self, plugin_config: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(plugin_config, dict):
            raise ToolError("validation", "plugin_config must be an object")
        config = self._load()
        config.setdefault("plugin_config", {}).update(plugin_config)
        self._validate_and_save(config)
        return {"plugin_config": config["plugin_config"]}

    def create_backup(self) -> Dict[str, Any]:
        self._editor.create_manual_backup()
        backups = sorted(self._editor.list_manual_backups(), reverse=True)
        return {"backup_file": backups[0] if backups else None}

    def restore_backup(self, backup_type: str, backup_file: str) -> Dict[str, Any]:
        if backup_type not in ("manual", "auto"):
            raise ToolError("validation", "backup_type must be 'manual' or 'auto'")
        if not self._editor.restore_backup(backup_type, backup_file):
            raise ToolError(
                "not_found", f"No {backup_type} backup named {backup_file!r}"
            )
        # restore_backup only copies the file; reload explicitly so the
        # automation engine picks the restored config up immediately
        callback = self._editor.reload_config_callback
        if callable(callback):
            callback()
        return {"restored": True, "backup_file": backup_file}
