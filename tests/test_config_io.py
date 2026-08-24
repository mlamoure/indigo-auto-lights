"""
Tests for WebConfigEditor config I/O hardening:
atomic saves, strict vs lenient loading of corrupt config files.
"""

import json
import os

import pytest

from config_web_editor.config_editor import WebConfigEditor

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

DEFAULT_CONFIG = {"plugin_config": {}, "zones": [], "lighting_periods": []}


@pytest.fixture
def editor(tmp_path):
    return WebConfigEditor(
        config_file=tmp_path / "auto_lights_conf.json",
        schema_file=SCHEMA_FILE,
        backup_dir=tmp_path / "backups",
        auto_backup_dir=tmp_path / "auto_backups",
        flask_app=None,
    )


def test_save_config_is_atomic_and_fires_reload(editor, tmp_path):
    reloads = []
    editor.reload_config_callback = lambda: reloads.append(True)

    config = dict(DEFAULT_CONFIG, plugin_config={"default_lock_duration": 7})
    editor.save_config(config)

    saved = json.loads(editor.config_file.read_text())
    assert saved["plugin_config"]["default_lock_duration"] == 7
    assert reloads == [True]
    # No temp file left behind by the temp-write + rename dance
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_config_creates_auto_backup(editor):
    editor.config_file.write_text(json.dumps(DEFAULT_CONFIG))
    editor.save_config(dict(DEFAULT_CONFIG, zones=[]))
    backups = list(editor.auto_backup_dir.glob("auto_backup_*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == DEFAULT_CONFIG


def test_load_config_strict_missing_file_returns_default(editor):
    assert editor.load_config_strict() == DEFAULT_CONFIG


def test_load_config_strict_raises_on_corrupt_json(editor):
    editor.config_file.write_text("{not valid json!")
    with pytest.raises(json.JSONDecodeError) as excinfo:
        editor.load_config_strict()
    assert str(editor.config_file) in str(excinfo.value)


def test_load_config_lenient_returns_default_on_corrupt_json(editor):
    editor.config_file.write_text("{not valid json!")
    assert editor.load_config() == DEFAULT_CONFIG


def test_load_config_strict_normalizes_legacy_modes(editor):
    config = dict(
        DEFAULT_CONFIG,
        lighting_periods=[
            {"id": 1, "name": "Legacy", "mode": "OnOffZone"},
            {"id": 2, "name": "Bogus", "mode": "does-not-exist"},
        ],
    )
    editor.config_file.write_text(json.dumps(config))
    loaded = editor.load_config_strict()
    assert loaded["lighting_periods"][0]["mode"] == "On and Off"
    assert loaded["lighting_periods"][1]["mode"] == "Off Only"
