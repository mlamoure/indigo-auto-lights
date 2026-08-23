import json
import datetime
import pytest
from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.auto_lights_agent import AutoLightsAgent
from tests.helpers import make_device, load_yaml

# Freeze "now" to a constant to make lighting periods deterministic
class FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2020, 1, 1, 12, 0, 0)

@pytest.fixture(autouse=True)
def freeze_datetime(monkeypatch):
    import auto_lights.lighting_period as lp_mod
    import auto_lights.zone as zone_mod
    monkeypatch.setattr(lp_mod.datetime, "datetime", FixedDateTime)
    monkeypatch.setattr(zone_mod.datetime, "datetime", FixedDateTime)

@pytest.fixture
def load_scenario(tmp_path):
    def _load(scenario_file):
        data = load_yaml(scenario_file)
        config_json = {
            "plugin_config": data.get("plugin_config", {}),
            "zones": data.get("zones", []),
            "lighting_periods": data.get("lighting_periods", []),
        }
        conf_path = tmp_path / "conf.json"
        conf_path.write_text(json.dumps(config_json))
        cfg = AutoLightsConfig(str(conf_path))
        agent = AutoLightsAgent(cfg)
        cfg.agent = agent
        for dev_id, st in data.get("device_states", {}).items():
            make_device(int(dev_id), **st)
        return data, cfg
    return _load

SCENARIOS = [
    "scenario1_presence_dark_adjust_false.yaml",
    "scenario2_presence_dark_adjust_true.yaml",
    "scenario3_presence_bright.yaml",
    "scenario4_no_presence.yaml",
    "scenario5_off_only_mode.yaml",
    "scenario5_off_only_no_presence.yaml",
    "scenario7_force_off_behavior.yaml",
    "scenario8_device_exclusion.yaml",
    "scenario9_limit_brightness.yaml",
    "scenario10_global_off.yaml",
    "scenario11_variable_threshold.yaml",
    "scenario12_per_device_brightness.yaml",
    "scenario13_per_device_brightness_limit.yaml",
    "scenario14_limit_brightness_adjust_false.yaml",
    "scenario16_zero_minimum_adjust_true.yaml",
]

@pytest.mark.parametrize("fname", SCENARIOS)
def test_zone_plan(load_scenario, fname):
    data, cfg = load_scenario(f"tests/configs/{fname}")
    zone = cfg.zones[0]
    plan = zone.calculate_target_brightness()
    exp = data["expected"]
    assert plan.new_targets == exp["new_targets"]
    assert plan.exclusions == exp["exclusions"]
    assert plan.device_changes == exp["device_changes"]

def test_locked_zone(load_scenario):
    # Scenario: locked zone should be skipped by agent
    data, cfg = load_scenario("tests/configs/scenario6_locked_zone.yaml")
    zone = cfg.zones[0]
    # lock the zone
    zone.locked = True
    result = cfg.agent.process_zone(zone)
    assert result is False

# --------------------------------------------------------------------------
# Hysteresis band + adjust_brightness (issue #7)
#
# scenario15 configures minimum_luminance=100, luminance_hysteresis=50, so the
# effective darkness threshold widens to 150 once the zone is dark. These tests
# hold that band and drive the brightness formula through it — deliberately
# not part of the SCENARIOS matrix above, since each needs to prime the
# Schmitt trigger before the single assertion the parametrized test makes.
# --------------------------------------------------------------------------

def _enter_band(zone, sensor_dev_id, dark_lux, band_lux):
    """Prime the Schmitt trigger dark, then move the reading into the band."""
    import indigo
    indigo.devices[sensor_dev_id].sensorValue = dark_lux
    zone._runtime_cache.clear()
    assert zone.is_dark() is True
    indigo.devices[sensor_dev_id].sensorValue = band_lux

def test_band_held_dark_with_adjust_brightness_keeps_a_positive_level(load_scenario):
    """Kills the divide-by-bare-minimum mutation.

    Old code divided by minimum_luminance (100): ceil((1-120/100)*100) is
    negative, clamps to 0, and the ON branch turns the dimmer off. Dividing by
    the effective threshold (150) instead gives 20.
    """
    data, cfg = load_scenario(
        "tests/configs/scenario15_hysteresis_band_adjust_true.yaml"
    )
    zone = cfg.zones[0]
    _enter_band(zone, 201, dark_lux=40, band_lux=120)

    plan = zone.calculate_target_brightness()

    assert plan.new_targets == [{"dev_id": 101, "brightness": 20}]
    assert not any("turned off" in msg for _emoji, msg in plan.device_changes)

def test_brightness_decays_monotonically_to_one_across_the_hysteresis_band(
    load_scenario,
):
    """No cliff at the old minimum_luminance boundary.

    Old code gave 34/0/0 at 99/100/101 lux (the 0s from the negative term
    clamping once luminance passed the bare minimum). Dividing by the widened
    150 threshold instead, the level decays smoothly to 34/34/33.
    """
    import indigo
    data, cfg = load_scenario(
        "tests/configs/scenario15_hysteresis_band_adjust_true.yaml"
    )
    zone = cfg.zones[0]
    _enter_band(zone, 201, dark_lux=40, band_lux=60)

    levels = []
    for lux in (60, 80, 99, 100, 101, 120, 149):
        indigo.devices[201].sensorValue = lux
        plan = zone.calculate_target_brightness()
        assert len(plan.new_targets) == 1
        levels.append(plan.new_targets[0]["brightness"])

    assert levels == [60, 47, 34, 34, 33, 20, 1]
    assert all(level >= 1 for level in levels)
    assert all(a >= b for a, b in zip(levels, levels[1:])), "must be non-increasing"

def test_leaving_the_band_turns_lights_off_only_at_the_widened_threshold(load_scenario):
    """At exactly minimum + hysteresis, is_dark() flips and the OFF path fires."""
    import indigo
    data, cfg = load_scenario(
        "tests/configs/scenario15_hysteresis_band_adjust_true.yaml"
    )
    zone = cfg.zones[0]
    _enter_band(zone, 201, dark_lux=40, band_lux=120)

    indigo.devices[201].sensorValue = 150  # == minimum (100) + hysteresis (50)
    plan = zone.calculate_target_brightness()

    assert plan.new_targets == [{"dev_id": 101, "brightness": 0}]

def test_band_held_dark_with_adjust_brightness_off_still_targets_full_brightness(
    load_scenario,
):
    """Regression guard: passes pre-fix too. adjust_brightness=False bypasses
    the formula entirely, so this is unaffected by the divisor change — kept
    here because the other adjust-off cases (scenarios 1 and 14) never
    exercise a widened band.
    """
    data, cfg = load_scenario(
        "tests/configs/scenario15_hysteresis_band_adjust_true.yaml"
    )
    zone = cfg.zones[0]
    _enter_band(zone, 201, dark_lux=40, band_lux=120)
    zone.adjust_brightness = False

    plan = zone.calculate_target_brightness()

    assert plan.new_targets == [{"dev_id": 101, "brightness": 100}]

def test_negative_term_from_a_stale_luminance_reading_still_clamps_to_zero(
    load_scenario, monkeypatch
):
    """Kills the "remove the max(0, ...) clamp" mutation.

    is_dark() and the formula both read luminance, but not atomically:
    variable-backed thresholds re-read Indigo between the two calls, so they
    can disagree in production. Simulate that by monkeypatching the luminance
    property to a value inconsistent with the real (in-band) sensor reading
    is_dark() used, and confirm the clamp still holds at 0 rather than going
    negative.
    """
    from auto_lights.zone import Zone

    data, cfg = load_scenario(
        "tests/configs/scenario15_hysteresis_band_adjust_true.yaml"
    )
    zone = cfg.zones[0]
    _enter_band(zone, 201, dark_lux=40, band_lux=120)
    monkeypatch.setattr(Zone, "luminance", property(lambda self: 10_000))

    plan = zone.calculate_target_brightness()

    assert plan.new_targets == [{"dev_id": 101, "brightness": 0}]
