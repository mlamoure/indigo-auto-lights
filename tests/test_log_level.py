"""
Regression tests for the "Event Logging Level" preference.

GitHub issue #7: at startup the plugin pinned its file handler to DEBUG regardless of
the configured level, so plugin.log ignored the preference until the config dialog was
saved. Both Indigo-provided handlers and the logger itself must follow the preference
at startup and again when the preferences dialog is saved.
"""

import logging
from types import SimpleNamespace

import pytest

from plugin import Plugin

PLUGIN_LOGGER = logging.getLogger("Plugin")


@pytest.fixture(autouse=True)
def _restore_plugin_logger_level():
    """The "Plugin" logger is process-wide; don't leak a level into other tests."""
    original = PLUGIN_LOGGER.level
    yield
    PLUGIN_LOGGER.setLevel(original)


def _make_plugin(prefs):
    return Plugin("com.vtmikel.autolights", "Auto Lights", "2026.9.0", prefs)


def _levels(plugin):
    return (
        plugin.logger.level,
        plugin.indigo_log_handler.level,
        plugin.plugin_file_handler.level,
    )


def test_startup_applies_configured_level_to_both_handlers():
    plugin = _make_plugin({"log_level": "20"})

    assert plugin.log_level == logging.INFO
    assert _levels(plugin) == (logging.INFO, logging.INFO, logging.INFO)


def test_startup_defaults_to_info_when_pref_missing():
    plugin = _make_plugin({})

    assert plugin.log_level == logging.INFO
    assert _levels(plugin) == (logging.INFO, logging.INFO, logging.INFO)


def test_closed_prefs_ui_updates_both_handlers():
    plugin = _make_plugin({"log_level": "20"})
    plugin._agent = SimpleNamespace(config=SimpleNamespace())

    plugin.closedPrefsConfigUi(
        {"log_level": "10", "log_non_events": False}, user_cancelled=False
    )

    assert plugin.log_level == logging.DEBUG
    assert _levels(plugin) == (logging.DEBUG, logging.DEBUG, logging.DEBUG)


def test_cancelled_prefs_ui_leaves_levels_alone():
    plugin = _make_plugin({"log_level": "20"})
    plugin._agent = SimpleNamespace(config=SimpleNamespace())

    plugin.closedPrefsConfigUi(
        {"log_level": "10", "log_non_events": True}, user_cancelled=True
    )

    assert plugin.log_level == logging.INFO
    assert _levels(plugin) == (logging.INFO, logging.INFO, logging.INFO)
