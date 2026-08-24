"""
Drift guard: Contents/Resources/mcp-manifest.json duplicates parts of
config_schema.json by design (the manifest carries cleaned inputSchemas for
AI clients). These tests fail when the two files, or the manifest and the
dispatcher's tool table, drift apart.
"""

import json
import os

import pytest

from mcp_api.config_tools import ConfigToolService
from mcp_api.tool_dispatcher import ToolDispatcher

PLUGIN_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "Auto Lights.indigoPlugin", "Contents"
)


@pytest.fixture(scope="module")
def manifest():
    with open(os.path.join(PLUGIN_ROOT, "Resources", "mcp-manifest.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def config_schema():
    with open(
        os.path.join(
            PLUGIN_ROOT,
            "Server Plugin",
            "config_web_editor",
            "config",
            "config_schema.json",
        )
    ) as f:
        return json.load(f)


def tool(manifest, name):
    return next(t for t in manifest["tools"] if t["name"] == name)


def test_manifest_basics(manifest):
    assert manifest["manifest_version"] == 1
    assert manifest["provider"]["plugin_id"] == "com.vtmikel.autolights"
    assert manifest["tool_prefix"] == "autolights"
    assert manifest["invoke_action_id"] == "mcp_tool_invoke"
    for t in manifest["tools"]:
        assert t["inputSchema"]["type"] == "object"
        assert isinstance(t["write"], bool)
        assert t["description"]


def test_manifest_tools_match_dispatcher(manifest):
    dispatcher = ToolDispatcher(ConfigToolService(None))
    assert sorted(t["name"] for t in manifest["tools"]) == dispatcher.tool_names()


def test_zone_schema_properties_subset(manifest, config_schema):
    manifest_zone = tool(manifest, "create_zone")["inputSchema"]["properties"]["zone"]
    schema_zone = config_schema["properties"]["zones"]["items"]

    assert set(manifest_zone["properties"]) <= set(schema_zone["properties"])
    for section in (
        "device_settings",
        "minimum_luminance_settings",
        "behavior_settings",
        "advanced_settings",
    ):
        assert set(manifest_zone["properties"][section]["properties"]) <= set(
            schema_zone["properties"][section]["properties"]
        )

    manifest_enum = manifest_zone["properties"]["behavior_settings"]["properties"][
        "off_lights_behavior"
    ]["enum"]
    schema_enum = schema_zone["properties"]["behavior_settings"]["properties"][
        "off_lights_behavior"
    ]["enum"]
    assert manifest_enum == schema_enum


def test_lighting_period_schema_sync(manifest, config_schema):
    manifest_period = tool(manifest, "create_lighting_period")["inputSchema"][
        "properties"
    ]["period"]
    schema_period = config_schema["properties"]["lighting_periods"]["items"]

    # id is auto-assigned, so the manifest must NOT offer it
    assert set(manifest_period["properties"]) <= (
        set(schema_period["properties"]) - {"id"}
    )
    for field in ("mode", "from_time_minute", "to_time_minute"):
        assert (
            manifest_period["properties"][field]["enum"]
            == schema_period["properties"][field]["enum"]
        )


def test_plugin_config_schema_sync(manifest, config_schema):
    manifest_pc = tool(manifest, "update_plugin_config")["inputSchema"]["properties"][
        "plugin_config"
    ]
    schema_pc = config_schema["properties"]["plugin_config"]

    assert set(manifest_pc["properties"]) <= set(schema_pc["properties"])
    manifest_enum = manifest_pc["properties"]["global_behavior_variables"]["items"][
        "properties"
    ]["comparison_type"]["enum"]
    schema_enum = schema_pc["properties"]["global_behavior_variables"]["items"][
        "properties"
    ]["comparison_type"]["enum"]
    assert manifest_enum == schema_enum
