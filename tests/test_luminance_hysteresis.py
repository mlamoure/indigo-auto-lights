"""Unit tests for Zone.is_dark() hysteresis and sensor-failure handling.

Two behaviours are covered here.

**Hysteresis.** A bare `avg < minimum_luminance` comparison oscillates when the
reading sits near the threshold. That is not merely sensor noise: a luminance
sensor mounted in the room it gates measures the very lights it controls, so
switching them on raises the reading and can push it back over the threshold.
The band must therefore be applied on the *getting brighter* side, and must be
wider than the lights' own contribution, or the loop still rings.

**Sensor failure.** "No luminance devices configured" and "configured devices
that cannot be read" are different conditions that previously collapsed to the
same silent `True`. The first is deliberate configuration; the second is a
failure and must be visible.
"""

import logging

import pytest


@pytest.fixture
def zone():
    """A bare Zone carrying only the attributes is_dark() touches."""
    from auto_lights.zone import Zone

    z = Zone.__new__(Zone)
    z._name = "TestZone"
    z.logger = logging.getLogger("Plugin")
    z._runtime_cache = {}
    z._luminance_dev_ids = []
    z._minimum_luminance = 2500
    z._minimum_luminance_var_id = None
    z._luminance_hysteresis = 0
    z._is_dark_state = None
    return z


def _sensors(zone, *values):
    """Attach luminance devices reporting `values`, and clear the eval cache."""
    import indigo

    ids = []
    for i, v in enumerate(values):
        dev_id = 90000 + i
        indigo.devices[dev_id] = type("Dev", (), {"sensorValue": v, "id": dev_id})()
        ids.append(dev_id)
    zone._luminance_dev_ids = ids
    zone._runtime_cache.pop("is_dark", None)
    return ids


# --------------------------------------------------------------------------
# Hysteresis
# --------------------------------------------------------------------------


def test_falling_below_threshold_becomes_dark(zone):
    zone._luminance_hysteresis = 500
    zone._is_dark_state = False
    _sensors(zone, 2400)
    assert zone.is_dark() is True


def test_rising_within_band_stays_dark(zone):
    """The behaviour that did not previously exist.

    2600 is above the 2500 threshold, so the old code called it light. With a
    500 band it must stay dark until 3000.
    """
    zone._luminance_hysteresis = 500
    zone._is_dark_state = True
    _sensors(zone, 2600)
    assert zone.is_dark() is True


def test_rising_past_band_becomes_light(zone):
    zone._luminance_hysteresis = 500
    zone._is_dark_state = True
    _sensors(zone, 3000)
    assert zone.is_dark() is False


def test_band_is_not_applied_when_currently_light(zone):
    """The band must be one-sided: it must not delay turning lights ON.

    2400 is below the threshold; a symmetric band would keep it 'light' down to
    2000 and leave the room dark while occupied.
    """
    zone._luminance_hysteresis = 500
    zone._is_dark_state = False
    _sensors(zone, 2400)
    assert zone.is_dark() is True


def test_real_world_oscillation_produces_one_transition(zone):
    """Replay of 2026-08-20 midday readings that crossed 2500 four times."""
    zone._luminance_hysteresis = 500
    zone._is_dark_state = False
    readings = [2293.5, 2587.6, 2218.33, 2022.97, 2228.18, 1254.76]

    results = []
    for r in readings:
        _sensors(zone, r)
        results.append(zone.is_dark())

    # Once dark, it stays dark: nothing here reaches 3000.
    assert results == [True, True, True, True, True, True]
    assert sum(1 for a, b in zip(results, results[1:]) if a != b) == 0


def test_zero_hysteresis_is_exactly_legacy_behaviour(zone):
    """Regression guard: the default must not change any existing install."""
    zone._luminance_hysteresis = 0
    for prior in (None, True, False):
        for value, expected in ((2499, True), (2500, False), (2501, False)):
            zone._is_dark_state = prior
            _sensors(zone, value)
            assert zone.is_dark() is expected, (prior, value)


def test_first_evaluation_uses_plain_threshold(zone):
    """With no prior state there is nothing to be sticky about."""
    zone._luminance_hysteresis = 500
    zone._is_dark_state = None
    _sensors(zone, 2600)
    assert zone.is_dark() is False


def test_state_persists_across_evaluations(zone):
    """The decision must outlive the per-evaluation runtime cache."""
    zone._luminance_hysteresis = 500
    zone._is_dark_state = None

    _sensors(zone, 2400)
    assert zone.is_dark() is True

    # Same lifecycle as a luminance device change: cache popped, state kept.
    _sensors(zone, 2700)
    assert zone.is_dark() is True
    assert zone._is_dark_state is True


def test_runtime_cache_short_circuits_within_one_evaluation(zone):
    zone._runtime_cache["is_dark"] = True
    zone._luminance_dev_ids = []
    assert zone.is_dark() is True


def test_averages_multiple_sensors(zone):
    zone._luminance_hysteresis = 0
    zone._is_dark_state = None
    _sensors(zone, 2000, 4000)  # avg 3000
    assert zone.is_dark() is False


# --------------------------------------------------------------------------
# Sensor failure
# --------------------------------------------------------------------------


def test_no_luminance_devices_configured_still_reports_dark(zone):
    """Deliberate configuration, not a failure — must not change."""
    zone._luminance_dev_ids = []
    zone._runtime_cache.pop("is_dark", None)
    assert zone.is_dark() is True


def test_no_luminance_devices_configured_does_not_warn(zone, caplog):
    zone._luminance_dev_ids = []
    zone._runtime_cache.pop("is_dark", None)
    with caplog.at_level(logging.WARNING, logger="Plugin"):
        zone.is_dark()
    assert caplog.records == []


def test_unreadable_sensor_holds_previous_state(zone):
    """A failed read must not be mistaken for a genuine darkness reading."""
    import indigo

    zone._is_dark_state = False
    indigo.devices[90500] = type("Dev", (), {"id": 90500})()  # no sensorValue
    zone._luminance_dev_ids = [90500]
    zone._runtime_cache.pop("is_dark", None)

    assert zone.is_dark() is False  # held, not flipped to True


def test_unreadable_sensor_warns(zone, caplog):
    """Not crashing is right; staying silent is not."""
    import indigo

    zone._is_dark_state = False
    indigo.devices[90501] = type("Dev", (), {"id": 90501})()
    zone._luminance_dev_ids = [90501]
    zone._runtime_cache.pop("is_dark", None)

    with caplog.at_level(logging.WARNING, logger="Plugin"):
        zone.is_dark()
    assert any("luminance" in r.message.lower() for r in caplog.records)


def test_unreadable_sensor_with_no_prior_state_defaults_dark_and_warns(zone, caplog):
    """Safe fallback for a lighting plugin is light, but say so."""
    import indigo

    zone._is_dark_state = None
    indigo.devices[90502] = type("Dev", (), {"id": 90502})()
    zone._luminance_dev_ids = [90502]
    zone._runtime_cache.pop("is_dark", None)

    with caplog.at_level(logging.WARNING, logger="Plugin"):
        result = zone.is_dark()
    assert result is True
    assert any("luminance" in r.message.lower() for r in caplog.records)


def test_non_numeric_sensor_value_is_not_summed(zone):
    """sensorValue present but None previously reached sum() and raised."""
    import indigo

    zone._is_dark_state = False
    indigo.devices[90503] = type("Dev", (), {"id": 90503, "sensorValue": None})()
    zone._luminance_dev_ids = [90503]
    zone._runtime_cache.pop("is_dark", None)

    assert zone.is_dark() is False  # held previous state, no TypeError


def test_zero_lux_is_a_valid_reading_not_a_failure(zone):
    """0 is falsy — it must not be filtered out as missing."""
    zone._luminance_hysteresis = 0
    zone._is_dark_state = None
    _sensors(zone, 0)
    assert zone.is_dark() is True


def test_one_failed_sensor_does_not_discard_a_working_one(zone):
    """A partial failure must still use the readings it did get."""
    import indigo

    zone._luminance_hysteresis = 0
    zone._is_dark_state = None
    indigo.devices[90504] = type("Dev", (), {"id": 90504, "sensorValue": 4000})()
    indigo.devices[90505] = type("Dev", (), {"id": 90505})()  # no sensorValue
    zone._luminance_dev_ids = [90504, 90505]
    zone._runtime_cache.pop("is_dark", None)

    assert zone.is_dark() is False  # 4000 alone, not treated as total failure


# --------------------------------------------------------------------------
# Web editor surface
# --------------------------------------------------------------------------


def test_hysteresis_field_is_generated_from_the_real_schema():
    """The setting is useless if the editor never renders it.

    Guards against the field being added to zone.py but silently absent from
    the web form, which looks identical to "the feature does not work".
    """
    import json
    import os

    from wtforms import IntegerField

    from config_web_editor.iws_form_helpers import generate_form_class_from_schema

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(
        here,
        "Auto Lights.indigoPlugin",
        "Contents",
        "Server Plugin",
        "config_web_editor",
        "config",
        "config_schema.json",
    )
    schema = json.load(open(schema_path))

    zone_schema = schema["properties"]["zones"]["items"]
    mls = zone_schema["properties"]["minimum_luminance_settings"]
    assert "luminance_hysteresis" in mls["properties"]
    assert mls["properties"]["luminance_hysteresis"].get("default") == 0

    form_cls = generate_form_class_from_schema(mls)
    form = form_cls()
    assert "luminance_hysteresis" in form._fields
    assert isinstance(form._fields["luminance_hysteresis"], IntegerField)


def test_hysteresis_is_read_from_zone_config():
    """Third link in the chain: schema -> form -> config -> Zone.

    Each of these can be present while the next is missing, and the symptom is
    identical every time: the setting appears in the editor and does nothing.
    """
    from auto_lights.zone import Zone

    z = Zone.__new__(Zone)
    z._name = "TestZone"
    z.logger = logging.getLogger("Plugin")
    z._luminance_hysteresis = 0

    z.from_config_dict({"minimum_luminance_settings": {"luminance_hysteresis": 400}})
    assert z.luminance_hysteresis == 400


def test_absent_hysteresis_key_leaves_default_untouched():
    """Existing configs predate this key and must keep working."""
    from auto_lights.zone import Zone

    z = Zone.__new__(Zone)
    z._name = "TestZone"
    z.logger = logging.getLogger("Plugin")
    z._luminance_hysteresis = 0

    z.from_config_dict({"minimum_luminance_settings": {"minimum_luminance": 2500}})
    assert z.luminance_hysteresis == 0


@pytest.mark.parametrize("bad", ["not a number", None, -250])
def test_bad_hysteresis_falls_back_to_zero_and_warns(bad, caplog):
    """Never let a malformed value silently become a huge sticky band."""
    from auto_lights.zone import Zone

    z = Zone.__new__(Zone)
    z._name = "TestZone"
    z.logger = logging.getLogger("Plugin")
    z._luminance_hysteresis = 0

    with caplog.at_level(logging.WARNING, logger="Plugin"):
        z.luminance_hysteresis = bad
    assert z.luminance_hysteresis == 0
    assert any("hysteresis" in r.message.lower() for r in caplog.records)
