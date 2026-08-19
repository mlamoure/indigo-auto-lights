"""Unit tests for Zone.dev_period_brightness().

The device_period_map cell is deliberately polymorphic — False excludes, True
includes with no explicit level, and 1-100 pins a level — so these cover the
type discrimination directly rather than only through a zone plan.
"""

import logging

import pytest

from auto_lights.lighting_period import LightingPeriod


class DummyPeriod:
    """Minimal stand-in for a LightingPeriod: only id and name are read."""

    def __init__(self, period_id=1, name="All Day"):
        self.id = period_id
        self.name = name


@pytest.fixture
def zone():
    """A bare Zone with only the attributes dev_period_brightness touches."""
    from auto_lights.zone import Zone

    z = Zone.__new__(Zone)
    z._name = "TestZone"
    z._device_period_map = {}
    z.logger = logging.getLogger("Plugin")
    return z


PERIOD = DummyPeriod()


@pytest.mark.parametrize(
    "cell, expected",
    [
        (10, 10),  # explicit level
        (1, 1),  # lower bound
        (100, 100),  # upper bound
        (True, None),  # included, no explicit level -> zone calculation applies
        (False, None),  # excluded -> handled by has_dev_lighting_mapping_exclusion
    ],
)
def test_recognised_cell_values(zone, cell, expected):
    zone._device_period_map = {"101": {"1": cell}}
    assert zone.dev_period_brightness(101, PERIOD) == expected


def test_true_is_not_treated_as_brightness_one(zone):
    """bool is a subclass of int — True must not slip through as level 1."""
    zone._device_period_map = {"101": {"1": True}}
    assert zone.dev_period_brightness(101, PERIOD) is None


@pytest.mark.parametrize("cell", [0, 101, -5, 1000])
def test_out_of_range_falls_back_and_warns(zone, cell, caplog):
    zone._device_period_map = {"101": {"1": cell}}
    with caplog.at_level(logging.WARNING, logger="Plugin"):
        assert zone.dev_period_brightness(101, PERIOD) is None
    assert "out-of-range brightness" in caplog.text


@pytest.mark.parametrize("cell", ["50", 50.5, None, [], {}])
def test_non_integer_cells_fall_back_silently(zone, cell):
    """Wrong types are not user-facing config errors — just no explicit level."""
    zone._device_period_map = {"101": {"1": cell}}
    assert zone.dev_period_brightness(101, PERIOD) is None


def test_missing_device_and_missing_period(zone):
    zone._device_period_map = {"101": {"1": 10}}
    # device not in the map at all
    assert zone.dev_period_brightness(999, PERIOD) is None
    # device present but this period is not
    assert zone.dev_period_brightness(101, DummyPeriod(period_id=2)) is None


def test_works_with_a_real_lighting_period(zone):
    """Guard against the helper relying on anything beyond id/name."""
    period = LightingPeriod("Evening", "On and Off")
    period.id = 7
    zone._device_period_map = {"101": {"7": 45}}
    assert zone.dev_period_brightness(101, period) == 45
