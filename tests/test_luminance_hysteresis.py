"""Unit tests for Zone.is_dark() hysteresis and luminance-sensor failure handling.

**Hysteresis.** A bare `avg < minimum_luminance` comparison oscillates when the
reading sits near the threshold. That is not merely sensor noise: a luminance
sensor mounted in the room it gates measures the very lights it controls, so
switching them on raises the reading and can push it back over the threshold.
The band is therefore applied on the *getting brighter* side only, and must be
wider than the lights' own contribution or the loop still rings.

**Sensor failure.** "No luminance devices configured" and "configured devices
that cannot be read" are different conditions that previously collapsed to the
same silent `True`. The first is deliberate configuration; the second is a
failure, must be visible, and must not be held indefinitely.

Several tests here exist specifically to kill mutations that survived an earlier
version of this file: latching dark forever, seeding the hysteresis state from a
failure, dropping the bool exclusion, and silently thinning the sensor set.
"""

import logging
import math

import pytest


@pytest.fixture
def zone():
    """A bare Zone carrying only the attributes these paths touch.

    Deliberately `Zone.__new__` rather than a constructed Zone: a newly
    introduced dependency then fails loudly here instead of being silently
    satisfied by an `__init__` default.
    """
    from auto_lights.zone import Zone

    z = Zone.__new__(Zone)
    z._name = "TestZone"
    z.logger = logging.getLogger("Plugin")
    z._runtime_cache = {}
    z._luminance = 0
    z._luminance_dev_ids = []
    z._minimum_luminance = 2500
    z._minimum_luminance_var_id = None
    z._luminance_hysteresis = 0
    z._is_dark_state = None
    z._luminance_unreadable_warned = False
    z._luminance_partial_warned = False
    z._last_luminance_read = None
    return z


def _sensors(zone, *values):
    """Attach luminance devices reporting `values`, and clear the eval cache.

    Clears both cached luminance keys, matching what process_zone does, so a
    test reading `zone.luminance` after `is_dark()` sees the same generation.
    """
    import indigo

    ids = []
    for i, v in enumerate(values):
        dev_id = 90000 + i
        indigo.devices[dev_id] = type(
            "Dev", (), {"sensorValue": v, "id": dev_id, "name": f"Lux {i}"}
        )()
        ids.append(dev_id)
    zone._luminance_dev_ids = ids
    zone._runtime_cache.pop("is_dark", None)
    zone._runtime_cache.pop("luminance", None)
    return ids


def _broken_sensor(zone, dev_id=90500, **attrs):
    """Attach a single device that cannot produce a usable sensorValue."""
    import indigo

    attrs.setdefault("id", dev_id)
    attrs.setdefault("name", f"Broken {dev_id}")
    indigo.devices[dev_id] = type("Dev", (), attrs)()
    zone._luminance_dev_ids = [dev_id]
    zone._runtime_cache.pop("is_dark", None)
    zone._runtime_cache.pop("luminance", None)
    return dev_id


# --------------------------------------------------------------------------
# Hysteresis
# --------------------------------------------------------------------------


def test_falling_below_threshold_becomes_dark(zone):
    zone._luminance_hysteresis = 500
    zone._is_dark_state = False
    _sensors(zone, 2400)
    assert zone.is_dark() is True
    assert zone._is_dark_state is True


def test_rising_within_band_stays_dark(zone):
    """2600 is above the 2500 threshold; the 500 band holds it dark to 3000."""
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
    """One-sided: a symmetric band would leave an occupied room dark to 2000."""
    zone._luminance_hysteresis = 500
    zone._is_dark_state = False
    _sensors(zone, 2400)
    assert zone.is_dark() is True


def test_staying_light_within_the_band_stays_light(zone):
    """The light -> light transition: the band must not pull it dark early."""
    zone._luminance_hysteresis = 500
    zone._is_dark_state = False
    _sensors(zone, 2600)
    assert zone.is_dark() is False
    assert zone._is_dark_state is False


def test_leaving_dark_clears_the_band_for_the_next_evaluation(zone):
    """Kills the "latch dark forever" mutation.

    Asserting only the return value of the exit lets an implementation that
    never writes False back to _is_dark_state pass, and such a zone never turns
    its lights off again.
    """
    zone._luminance_hysteresis = 500
    zone._is_dark_state = True

    _sensors(zone, 3000)
    assert zone.is_dark() is False
    assert zone._is_dark_state is False

    # Now on the bare threshold again: 2600 must read light, not dark.
    _sensors(zone, 2600)
    assert zone.is_dark() is False


def test_hysteresis_changes_the_outcome_versus_no_hysteresis(zone):
    """The real-data replay, run as an experiment rather than a snapshot.

    These are readings taken 2026-08-20 around midday from a kitchen whose
    luminance sensor is in the room it gates. They cross 2500 twice. Asserting
    only that the banded run is all-True would also pass for `return True`, so
    the contrast with hysteresis=0 is the whole point.
    """
    readings = [2293.5, 2587.6, 2218.33, 2022.97, 2228.18, 1254.76]

    def replay(hyst):
        zone._luminance_hysteresis = hyst
        zone._is_dark_state = False
        out = []
        for r in readings:
            _sensors(zone, r)
            out.append(zone.is_dark())
        return out

    banded = replay(500)
    bare = replay(0)

    assert bare[1] is False, "without hysteresis the 2587.6 reading flaps to light"
    assert all(banded), "with a 500 band nothing reaches 3000, so it stays dark"
    assert sum(a != b for a, b in zip(bare, bare[1:])) == 2  # two crossings
    assert sum(a != b for a, b in zip(banded, banded[1:])) == 0


def test_zero_hysteresis_is_exactly_legacy_behaviour(zone):
    """Regression guard on the band only.

    With readable sensors and hysteresis 0, the decision must be the same bare
    comparison as before. This does NOT claim the whole function is unchanged:
    the unreadable-sensor handling changed unconditionally.
    """
    zone._luminance_hysteresis = 0
    for prior in (None, True, False):
        for value, expected in ((2499, True), (2500, False), (2501, False)):
            zone._is_dark_state = prior
            _sensors(zone, value)
            assert zone.is_dark() is expected, (prior, value)


def test_first_evaluation_uses_plain_threshold(zone):
    """No prior state (including right after a plugin restart) -> bare threshold."""
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


def test_is_dark_is_idempotent_across_a_cache_clear(zone):
    """is_dark() is a mutating getter called twice per evaluation.

    sync_indigo_device() renders it as a device state, then
    calculate_target_brightness clears the cache and calls it again. The two
    calls agree only because the trigger is a fixpoint; pin that.
    """
    for hyst in (0, 500):
        for prior in (None, True, False):
            for reading in (2400, 2600, 3000):
                zone._luminance_hysteresis = hyst
                zone._is_dark_state = prior
                _sensors(zone, reading)
                first = zone.is_dark()
                zone._runtime_cache.clear()
                second = zone.is_dark()
                assert first is second, (hyst, prior, reading)


def test_runtime_cache_short_circuits_within_one_evaluation(zone):
    """The cache must be the only reason this returns True.

    Previously this test set _luminance_dev_ids = [], which returns True on the
    no-devices path regardless of the cache, so it could not fail.
    """
    zone._luminance_hysteresis = 0
    zone._is_dark_state = None
    _sensors(zone, 9999)  # would compute False
    zone._runtime_cache["is_dark"] = True
    assert zone.is_dark() is True


def test_averages_multiple_sensors(zone):
    zone._luminance_hysteresis = 0
    zone._is_dark_state = None
    _sensors(zone, 2000, 4000)  # avg 3000
    assert zone.is_dark() is False


# --------------------------------------------------------------------------
# Hysteresis value validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["not a number", None, -250, float("nan"), float("inf"), "1e400", "-inf"],
)
def test_unusable_hysteresis_falls_back_to_zero_and_warns(zone, bad, caplog):
    """nan and inf are the dangerous ones, and they pass float() and `< 0`.

    A nan band makes `avg < threshold` always False, so the zone silently never
    turns its lights on again. An inf band makes it always dark. Both are worse
    than the malformed strings the setter was originally written for.
    """
    with caplog.at_level(logging.WARNING, logger="Plugin"):
        zone.luminance_hysteresis = bad
    assert zone.luminance_hysteresis == 0
    assert any("hysteresis" in r.message.lower() for r in caplog.records)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_unusable_hysteresis_cannot_disable_darkness_detection(zone, bad):
    """The behavioural consequence, not just the stored value."""
    zone.luminance_hysteresis = bad
    zone._is_dark_state = True
    _sensors(zone, 0)  # pitch dark
    assert zone.is_dark() is True


def test_valid_hysteresis_is_stored(zone):
    zone.luminance_hysteresis = 400
    assert zone.luminance_hysteresis == 400
    assert math.isfinite(zone.luminance_hysteresis)


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
    zone._is_dark_state = False
    _broken_sensor(zone)  # no sensorValue attribute
    assert zone.is_dark() is False  # held, not flipped to True


def test_unreadable_sensor_warns(zone, caplog):
    """Not crashing is right; staying silent is not."""
    zone._is_dark_state = False
    _broken_sensor(zone, 90501)
    with caplog.at_level(logging.WARNING, logger="Plugin"):
        zone.is_dark()
    assert any("luminance" in r.message.lower() for r in caplog.records)


def test_unreadable_sensor_warns_once_per_outage(zone, caplog):
    """A permanently dead sensor must not warn on every evaluation.

    is_dark() runs on every device change in the zone, so an unconditional
    warning floods the event log exactly when the user needs to read it.
    """
    zone._is_dark_state = False
    zone._last_luminance_read = None
    _broken_sensor(zone, 90502)
    with caplog.at_level(logging.WARNING, logger="Plugin"):
        for _ in range(5):
            zone._runtime_cache.pop("is_dark", None)
            zone.is_dark()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_recovery_after_an_outage_re_arms_the_warning(zone, caplog):
    """Second outage must warn again, and recovery should be announced."""
    zone._is_dark_state = False
    _broken_sensor(zone, 90503)
    with caplog.at_level(logging.INFO, logger="Plugin"):
        zone.is_dark()
        _sensors(zone, 100)  # recovered
        zone.is_dark()
        assert any("recovered" in r.message.lower() for r in caplog.records)
        caplog.clear()
        _broken_sensor(zone, 90504)
        zone.is_dark()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_a_stale_hold_escalates_to_error(zone, caplog):
    """Holding is a bridge, not a steady state.

    A sensor whose battery dies at 02:00 would otherwise pin the zone dark and
    run its lights all the following day behind a single old warning.
    """
    import time

    from auto_lights.zone import LUMINANCE_HOLD_MAX_SECONDS

    zone._is_dark_state = True
    zone._last_luminance_read = time.time() - (LUMINANCE_HOLD_MAX_SECONDS + 60)
    _broken_sensor(zone, 90505)
    with caplog.at_level(logging.WARNING, logger="Plugin"):
        assert zone.is_dark() is True
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_a_held_failure_does_not_seed_the_band(zone):
    """Kills the "commit the held value to _is_dark_state" mutation.

    Seeding it would mean a dead sensor at cold start fabricates a dark state,
    so when the sensor recovers the zone applies the full band on top of a value
    it never measured — holding the lights on well past where it should.
    """
    zone._luminance_hysteresis = 500
    zone._is_dark_state = None
    _broken_sensor(zone, 90506)

    assert zone.is_dark() is True
    assert zone._is_dark_state is None, "a failure must not seed hysteresis state"

    # Recovered: 2600 is above the bare threshold, and with no seeded state
    # there is no band to hold it dark.
    _sensors(zone, 2600)
    assert zone.is_dark() is False


def test_unreadable_sensor_with_no_prior_state_assumes_dark_and_warns(zone, caplog):
    """Fail-safe for a lighting plugin is to assume dark (lights on), but say so.

    This is the one case where the old silent behaviour is preserved, so the
    warning is what makes it not a swallow.
    """
    zone._is_dark_state = None
    _broken_sensor(zone, 90507)
    with caplog.at_level(logging.WARNING, logger="Plugin"):
        result = zone.is_dark()
    assert result is True
    assert any("luminance" in r.message.lower() for r in caplog.records)


def test_boolean_sensor_value_is_unreadable_not_zero_lux(zone):
    """bool is a subclass of int; True would otherwise average as 1 lux.

    1 lux reads as pitch dark, so a naive numeric check turns a broken sensor
    into a confident "turn the lights on".
    """
    zone._is_dark_state = False
    _broken_sensor(zone, 90508, sensorValue=True)
    assert zone.is_dark() is False  # held, not a 1-lux "dark"


def test_string_sensor_value_is_unreadable(zone):
    zone._is_dark_state = False
    _broken_sensor(zone, 90509, sensorValue="450")
    assert zone.is_dark() is False


def test_non_numeric_sensor_value_is_not_summed(zone):
    """sensorValue present but None previously reached sum() and raised."""
    zone._is_dark_state = False
    _broken_sensor(zone, 90510, sensorValue=None)
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
    indigo.devices[90520] = type(
        "Dev", (), {"id": 90520, "sensorValue": 4000, "name": "Good"}
    )()
    indigo.devices[90521] = type("Dev", (), {"id": 90521, "name": "Bad"})()
    zone._luminance_dev_ids = [90520, 90521]
    zone._runtime_cache.pop("is_dark", None)

    assert zone.is_dark() is False  # 4000 alone, not treated as total failure


def test_partial_failure_is_announced(zone, caplog):
    """A zone silently averaging 1 of 3 sensors is an honest-looking wrong answer."""
    import indigo

    zone._is_dark_state = None
    indigo.devices[90530] = type(
        "Dev", (), {"id": 90530, "sensorValue": 4000, "name": "Good"}
    )()
    indigo.devices[90531] = type("Dev", (), {"id": 90531, "name": "Bad"})()
    zone._luminance_dev_ids = [90530, 90531]
    zone._runtime_cache.pop("is_dark", None)

    with caplog.at_level(logging.WARNING, logger="Plugin"):
        zone.is_dark()
    assert any("unreadable" in r.message.lower() for r in caplog.records)


def test_deleted_device_is_unreadable_not_zero_lux(zone, monkeypatch):
    """A device removed from Indigo must not read as maximum darkness.

    The test stub auto-creates unknown device ids with sensorValue defaulting to
    0, so without this monkeypatch a deleted luminance device silently becomes a
    perfect 0-lux reading — the most dangerous possible wrong answer, and one no
    test could otherwise see. A plain dict raises KeyError like real Indigo.
    """
    import indigo

    monkeypatch.setattr(indigo, "devices", {})
    zone._is_dark_state = False
    zone._luminance_dev_ids = [99999]
    zone._runtime_cache.pop("is_dark", None)

    assert zone.is_dark() is False  # held, not a fabricated 0-lux "dark"


# --------------------------------------------------------------------------
# The luminance property shares the same reader
# --------------------------------------------------------------------------


def test_luminance_property_survives_non_numeric_sensor_value(zone):
    """The crash is_dark() was hardened against also lived here, and ran first.

    luminance is rendered as an Indigo device state before is_dark() in the
    runtime-state list, and sync_indigo_device has no except clause — so this
    raising took the whole zone evaluation down regardless of is_dark().
    """
    import indigo

    indigo.devices[90540] = type(
        "Dev", (), {"id": 90540, "sensorValue": None, "name": "Bad"}
    )()
    indigo.devices[90541] = type(
        "Dev", (), {"id": 90541, "sensorValue": 300, "name": "Good"}
    )()
    zone._luminance_dev_ids = [90540, 90541]
    zone._runtime_cache.pop("luminance", None)

    assert zone.luminance == 300


def test_luminance_and_is_dark_agree_on_what_is_readable(zone):
    """They were separate loops with different notions of readable.

    luminance summed True as 1 lux while is_dark() discarded it, so the plan
    could report a luminance the darkness decision had never used.
    """
    zone._is_dark_state = False
    _broken_sensor(zone, 90550, sensorValue=True)

    assert zone.is_dark() is False  # bool discarded -> held
    assert zone.luminance == 0  # not 1 lux from the bool


def test_luminance_property_survives_a_deleted_device(zone, monkeypatch):
    import indigo

    monkeypatch.setattr(indigo, "devices", {})
    zone._luminance_dev_ids = [99998]
    zone._runtime_cache.pop("luminance", None)
    assert zone.luminance == 0


# --------------------------------------------------------------------------
# Effective threshold surfaced to callers
# --------------------------------------------------------------------------


def test_effective_threshold_widens_only_while_dark(zone):
    zone._luminance_hysteresis = 500

    zone._is_dark_state = False
    assert zone.effective_darkness_threshold == 2500

    zone._is_dark_state = True
    assert zone.effective_darkness_threshold == 3000


def test_effective_threshold_equals_minimum_without_hysteresis(zone):
    zone._luminance_hysteresis = 0
    for prior in (None, True, False):
        zone._is_dark_state = prior
        assert zone.effective_darkness_threshold == 2500


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


def test_hysteresis_is_not_published_as_a_duplicate_device_state():
    """It is a config field, published via x-sync_to_indigo.

    Listing it in zone_indigo_device_runtime_states as well makes
    getDeviceStateList emit the same key twice, so it appears duplicated in
    Indigo's trigger and control-page state pickers.
    """
    from auto_lights.zone import Zone

    runtime_keys = [s["key"] for s in Zone.zone_indigo_device_runtime_states]
    assert "luminance_hysteresis" not in runtime_keys


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
