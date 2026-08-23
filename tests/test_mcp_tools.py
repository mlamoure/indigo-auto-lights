"""
Tests for the MCP tool dispatcher and ConfigToolService.

Drives ToolDispatcher.dispatch() exactly as plugin.handle_mcp_tool_invoke
does: tool name + JSON-string arguments in, JSON-string envelope out.
"""

import json
import os

import pytest

from config_web_editor.config_editor import WebConfigEditor
from mcp_api.config_tools import ConfigToolService
from mcp_api.tool_dispatcher import ToolDispatcher

SCHEMA_FILE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "Auto Lights.indigoPlugin",
    "Contents",
    "Server Plugin",
    "config_web_editor",
    "config",
    "config_schema.json",
)

SEED_CONFIG = {
    "plugin_config": {
        "default_lock_duration": 5,
        "default_lock_extension_duration": 2,
        "global_behavior_variables": [],
    },
    "zones": [
        {
            "name": "Kitchen",
            "lighting_period_ids": [1],
            "device_settings": {
                "on_lights_dev_ids": [101],
                "off_lights_dev_ids": [],
                "luminance_dev_ids": [],
                "presence_dev_ids": [301],
            },
            "behavior_settings": {"lock_duration": -1},
            "device_period_map": {"101": {"1": True}},
        }
    ],
    "lighting_periods": [
        {
            "id": 1,
            "name": "All Day",
            "mode": "On and Off",
            "from_time_hour": 0,
            "from_time_minute": 0,
            "to_time_hour": 23,
            "to_time_minute": 45,
            "lock_duration": -1,
            "limit_brightness": -1,
        }
    ],
}


@pytest.fixture
def env(tmp_path):
    editor = WebConfigEditor(
        config_file=tmp_path / "auto_lights_conf.json",
        schema_file=SCHEMA_FILE,
        backup_dir=tmp_path / "backups",
        auto_backup_dir=tmp_path / "auto_backups",
        flask_app=None,
    )
    editor.config_file.write_text(json.dumps(SEED_CONFIG))
    reloads = []
    editor.reload_config_callback = lambda: reloads.append(True)
    dispatcher = ToolDispatcher(ConfigToolService(editor))
    return dispatcher, editor, reloads


def call(dispatcher, tool, **arguments):
    reply = json.loads(dispatcher.dispatch(tool, json.dumps(arguments)))
    assert reply["status"] in ("ok", "error")
    return reply


def saved_config(editor):
    return json.loads(editor.config_file.read_text())


# ----------------------------------------------------------------------
# reads


def test_get_config(env):
    dispatcher, _, reloads = env
    reply = call(dispatcher, "get_config")
    assert reply["status"] == "ok"
    assert reply["result"]["config"]["zones"][0]["name"] == "Kitchen"
    assert reply["result"]["zone_indexes"] == [{"zone_index": 0, "name": "Kitchen"}]
    assert reloads == []


def test_list_and_get_zone(env):
    dispatcher, _, _ = env
    assert call(dispatcher, "list_zones")["result"]["zones"][0]["name"] == "Kitchen"
    reply = call(dispatcher, "get_zone", zone_index=0, expected_name="Kitchen")
    assert reply["result"]["zone"]["name"] == "Kitchen"
    assert call(dispatcher, "get_zone", zone_index=5)["error"]["type"] == "not_found"
    conflict = call(dispatcher, "get_zone", zone_index=0, expected_name="Garage")
    assert conflict["error"]["type"] == "conflict"


def test_lighting_period_reads(env):
    dispatcher, _, _ = env
    periods = call(dispatcher, "list_lighting_periods")["result"]["lighting_periods"]
    assert periods[0]["id"] == 1
    assert (
        call(dispatcher, "get_lighting_period", period_id=1)["result"][
            "lighting_period"
        ]["name"]
        == "All Day"
    )
    assert (
        call(dispatcher, "get_lighting_period", period_id=99)["error"]["type"]
        == "not_found"
    )


# ----------------------------------------------------------------------
# zone writes


def test_zone_crud_cycle(env):
    dispatcher, editor, reloads = env

    created = call(
        dispatcher,
        "create_zone",
        zone={
            "name": "Garage",
            "lighting_period_ids": [1],
            "device_settings": {"on_lights_dev_ids": [201], "presence_dev_ids": [302]},
        },
    )
    assert created["status"] == "ok"
    assert created["result"]["zone_index"] == 1
    # behavior_settings is always emitted for API-authored zones
    assert "behavior_settings" in saved_config(editor)["zones"][1]
    assert len(reloads) == 1

    updated = call(
        dispatcher,
        "update_zone",
        zone_index=1,
        expected_name="Garage",
        zone={"behavior_settings": {"lock_duration": 30}},
    )
    assert updated["status"] == "ok"
    assert saved_config(editor)["zones"][1]["behavior_settings"]["lock_duration"] == 30
    # section merge preserves untouched keys
    assert saved_config(editor)["zones"][1]["device_settings"]["on_lights_dev_ids"] == [
        201
    ]
    assert len(reloads) == 2

    deleted = call(dispatcher, "delete_zone", zone_index=1, expected_name="Garage")
    assert deleted["status"] == "ok"
    assert len(saved_config(editor)["zones"]) == 1
    assert len(reloads) == 3


def test_update_zone_conflict_on_stale_name(env):
    dispatcher, editor, reloads = env
    reply = call(
        dispatcher,
        "update_zone",
        zone_index=0,
        expected_name="Garage",
        zone={"name": "X"},
    )
    assert reply["error"]["type"] == "conflict"
    assert saved_config(editor)["zones"][0]["name"] == "Kitchen"
    assert reloads == []


def test_delete_zone_requires_expected_name(env):
    dispatcher, _, reloads = env
    reply = call(dispatcher, "delete_zone", zone_index=0)
    assert reply["error"]["type"] == "validation"
    assert reloads == []


def test_create_zone_validation_failure_leaves_config_untouched(env):
    dispatcher, editor, reloads = env
    reply = call(
        dispatcher,
        "create_zone",
        zone={"name": "Bad", "lighting_period_ids": ["one"]},
    )
    assert reply["error"]["type"] == "validation"
    paths = [e["path"] for e in reply["error"]["details"]["errors"]]
    assert any("lighting_period_ids[0]" in p for p in paths)
    assert len(saved_config(editor)["zones"]) == 1
    assert reloads == []


# ----------------------------------------------------------------------
# lighting period writes


def test_lighting_period_crud_cycle(env):
    dispatcher, editor, reloads = env

    created = call(
        dispatcher,
        "create_lighting_period",
        period={"name": "Evening", "mode": "Off Only", "from_time_hour": 18},
    )
    assert created["status"] == "ok"
    period = created["result"]["lighting_period"]
    assert period["id"] == 2
    # schema defaults applied to omitted fields
    assert period["to_time_minute"] == 45

    updated = call(
        dispatcher,
        "update_lighting_period",
        period_id=2,
        period={"limit_brightness": 40, "id": 99},
    )
    assert updated["status"] == "ok"
    assert updated["result"]["lighting_period"]["id"] == 2  # id immutable
    assert updated["result"]["lighting_period"]["limit_brightness"] == 40

    deleted = call(dispatcher, "delete_lighting_period", period_id=2)
    assert deleted["status"] == "ok"
    assert len(saved_config(editor)["lighting_periods"]) == 1
    assert len(reloads) == 3


def test_delete_lighting_period_in_use_requires_force(env):
    dispatcher, editor, _ = env
    refused = call(dispatcher, "delete_lighting_period", period_id=1)
    assert refused["error"]["type"] == "conflict"
    assert refused["error"]["details"]["referencing_zones"][0]["name"] == "Kitchen"

    forced = call(dispatcher, "delete_lighting_period", period_id=1, force=True)
    assert forced["status"] == "ok"
    config = saved_config(editor)
    assert config["zones"][0]["lighting_period_ids"] == []
    assert config["zones"][0]["device_period_map"]["101"] == {}


def test_invalid_period_enum_rejected(env):
    dispatcher, _, _ = env
    reply = call(
        dispatcher,
        "create_lighting_period",
        period={"name": "Odd", "from_time_minute": 7},
    )
    assert reply["error"]["type"] == "validation"


# ----------------------------------------------------------------------
# plugin config, backups, envelope edges


def test_update_plugin_config(env):
    dispatcher, editor, _ = env
    reply = call(
        dispatcher, "update_plugin_config", plugin_config={"default_lock_duration": 9}
    )
    assert reply["status"] == "ok"
    config = saved_config(editor)["plugin_config"]
    assert config["default_lock_duration"] == 9
    assert config["default_lock_extension_duration"] == 2  # merge preserves


def test_backup_cycle(env):
    dispatcher, editor, reloads = env
    backup = call(dispatcher, "create_backup")
    assert backup["result"]["backup_file"].startswith("manual_backup_")

    call(
        dispatcher, "update_plugin_config", plugin_config={"default_lock_duration": 99}
    )
    listed = call(dispatcher, "list_backups")["result"]
    assert backup["result"]["backup_file"] in listed["manual"]
    assert len(listed["auto"]) == 1

    restored = call(
        dispatcher,
        "restore_backup",
        backup_type="manual",
        backup_file=backup["result"]["backup_file"],
    )
    assert restored["status"] == "ok"
    assert saved_config(editor)["plugin_config"]["default_lock_duration"] == 5
    # restore triggers an explicit reload even though save_config isn't used
    assert len(reloads) == 2

    missing = call(
        dispatcher, "restore_backup", backup_type="manual", backup_file="nope.json"
    )
    assert missing["error"]["type"] == "not_found"


def test_unknown_tool_and_bad_arguments(env):
    dispatcher, _, _ = env
    assert call(dispatcher, "does_not_exist")["error"]["type"] == "not_found"
    assert call(dispatcher, "get_zone", bogus_arg=1)["error"]["type"] == "validation"

    raw = json.loads(dispatcher.dispatch("get_zone", "not json"))
    assert raw["error"]["type"] == "validation"
    raw = json.loads(dispatcher.dispatch("get_zone", "[1, 2]"))
    assert raw["error"]["type"] == "validation"


def test_corrupt_config_is_internal_error_not_empty_overwrite(env):
    dispatcher, editor, reloads = env
    editor.config_file.write_text("{broken")
    reply = call(dispatcher, "update_plugin_config", plugin_config={})
    assert reply["error"]["type"] == "internal"
    # the corrupt file was not replaced by an empty config
    assert editor.config_file.read_text() == "{broken"
    assert reloads == []
