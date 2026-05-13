"""Smoke tests for utils.PerfClock.

PerfClock is logging instrumentation, not logic — these tests guard against
import/typing regressions and verify the elapsed-time math doesn't drift.
"""

import time

from auto_lights.utils import PerfClock


def test_perf_clock_construction():
    clock = PerfClock(event_age_ms=42, trigger="motion sensor")
    assert clock.event_age_ms == 42
    assert clock.trigger == "motion sensor"
    assert clock.t() >= 0


def test_perf_clock_t_increases():
    clock = PerfClock(event_age_ms=None, trigger="x")
    t1 = clock.t()
    time.sleep(0.01)
    t2 = clock.t()
    assert t2 > t1
    assert t2 < 1000  # sanity: not orders-of-magnitude off


def test_perf_clock_accepts_none_event_age():
    clock = PerfClock(event_age_ms=None, trigger="variable change")
    assert clock.event_age_ms is None
