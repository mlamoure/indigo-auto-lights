"""
Dispatcher for the `mcp_tool_invoke` hidden action.

The MCP Server plugin calls
executeAction("mcp_tool_invoke", props={"tool": <name>, "arguments": <JSON string>})
and receives a JSON string back. Arguments cross the boundary as a JSON
string because indigo.Dict cannot carry None values or $-prefixed keys.

Reply envelope (always a JSON string, never an exception):
  {"status": "ok", "result": <any JSON>}
  {"status": "error", "error": {"type": "validation|not_found|conflict|internal",
                                "message": str, "details": <optional JSON>}}
"""

import inspect
import json
import logging
from typing import Any, Dict

from .config_tools import ConfigToolService, ToolError

logger = logging.getLogger("Plugin")


class ToolDispatcher:
    def __init__(self, service: ConfigToolService):
        self._service = service
        self._tools = {
            "get_config": service.get_config,
            "list_zones": service.list_zones,
            "get_zone": service.get_zone,
            "create_zone": service.create_zone,
            "update_zone": service.update_zone,
            "delete_zone": service.delete_zone,
            "list_lighting_periods": service.list_lighting_periods,
            "get_lighting_period": service.get_lighting_period,
            "create_lighting_period": service.create_lighting_period,
            "update_lighting_period": service.update_lighting_period,
            "delete_lighting_period": service.delete_lighting_period,
            "update_plugin_config": service.update_plugin_config,
            "list_backups": service.list_backups,
            "create_backup": service.create_backup,
            "restore_backup": service.restore_backup,
        }

    def tool_names(self):
        return sorted(self._tools)

    def dispatch(self, tool_name: str, arguments_json: str) -> str:
        try:
            handler = self._tools.get(tool_name)
            if handler is None:
                return self._error(
                    "not_found",
                    f"Unknown tool {tool_name!r}; available: {', '.join(self.tool_names())}",
                )

            try:
                arguments = json.loads(arguments_json or "{}")
            except json.JSONDecodeError as e:
                return self._error("validation", f"arguments is not valid JSON: {e}")
            if not isinstance(arguments, dict):
                return self._error("validation", "arguments must be a JSON object")

            try:
                inspect.signature(handler).bind(**arguments)
            except TypeError as e:
                return self._error("validation", f"bad arguments for {tool_name}: {e}")

            logger.info(f"🔧 MCP tool invoked: {tool_name}")
            result = handler(**arguments)
            return json.dumps({"status": "ok", "result": result})
        except ToolError as e:
            return self._error(e.error_type, e.message, e.details)
        except Exception as e:
            logger.exception(f"MCP tool {tool_name!r} failed")
            return self._error("internal", f"{type(e).__name__}: {e}")

    @staticmethod
    def _error(error_type: str, message: str, details: Any = None) -> str:
        error: Dict[str, Any] = {"type": error_type, "message": message}
        if details is not None:
            error["details"] = details
        logger.warning(f"MCP tool error ({error_type}): {message}")
        return json.dumps({"status": "error", "error": error})
