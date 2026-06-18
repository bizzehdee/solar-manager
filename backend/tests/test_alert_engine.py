"""Alert rule engine (plan.md §15) — pure logic, tested hardest (§21).

Covers the firing condition, hysteresis (recover past the band to clear), debounce (hold
before firing), quiet-hours suppression, missing values, and rule (de)serialisation.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.alerts.engine import (
    AlertEngine,
    AlertRule,
    AlertState,
    compare,
    default_rules,
    in_quiet_hours,
    step,
)


def _rule(**kw) -> AlertRule:
    base = dict(id="r", name="r", metric="battery_soc_pct", op="lt", threshold=20.0)
    base.update(kw)
    return AlertRule(**base)


# --- compare + quiet hours ------------------------------------------------------
def test_compare_operators():
    assert compare(10, "lt", 20) and not compare(30, "lt", 20)
    assert compare(20, "le", 20) and compare(30, "gt", 20) and compare(20, "ge", 20)
    assert compare(5, "eq", 5) and compare(5, "ne", 6)
    with pytest.raises(ValueError):
        compare(1, "??", 2)


def test_quiet_hours_wraps_midnight():
    night = (22, 7)
    assert in_quiet_hours(night, datetime(2026, 6, 18, 23, 0))   # 23:00 in window
    assert in_quiet_hours(night, datetime(2026, 6, 18, 3, 0))    # 03:00 in window
    assert not in_quiet_hours(night, datetime(2026, 6, 18, 12, 0))
    assert not in_quiet_hours(None, datetime(2026, 6, 18, 3, 0))
    assert not in_quiet_hours((8, 8), datetime(2026, 6, 18, 8, 0))  # empty window


# --- firing + clearing ----------------------------------------------------------
def test_fires_when_breached_and_clears_past_hysteresis():
    rule = _rule(hysteresis=5.0)
    st = AlertState()
    assert step(rule, 15.0, st, now=0.0, in_quiet=False) == "fire"  # 15 < 20 → fire
    assert st.active and st.fired_at == 0.0
    # In the hysteresis band (20–25): still breached-ish but neither re-fires nor clears.
    assert step(rule, 22.0, st, now=1.0, in_quiet=False) is None
    assert st.active
    # Recovered past 20 + 5 = 25 → clear.
    assert step(rule, 26.0, st, now=2.0, in_quiet=False) == "clear"
    assert not st.active


def test_does_not_refire_while_active():
    rule = _rule()
    st = AlertState()
    assert step(rule, 10.0, st, now=0.0, in_quiet=False) == "fire"
    assert step(rule, 9.0, st, now=1.0, in_quiet=False) is None  # still breached, already active


def test_debounce_delays_firing():
    rule = _rule(debounce_s=60.0)
    st = AlertState()
    assert step(rule, 10.0, st, now=0.0, in_quiet=False) is None    # breach starts, debouncing
    assert step(rule, 10.0, st, now=30.0, in_quiet=False) is None   # still within debounce
    assert step(rule, 10.0, st, now=60.0, in_quiet=False) == "fire"  # held 60 s → fire


def test_debounce_resets_when_condition_clears():
    rule = _rule(debounce_s=60.0)
    st = AlertState()
    step(rule, 10.0, st, now=0.0, in_quiet=False)
    assert step(rule, 30.0, st, now=10.0, in_quiet=False) is None   # recovered → timer resets
    assert st.breaching_since is None
    assert step(rule, 10.0, st, now=20.0, in_quiet=False) is None   # breach restarts at 20
    assert step(rule, 10.0, st, now=79.0, in_quiet=False) is None   # only 59 s held
    assert step(rule, 10.0, st, now=80.0, in_quiet=False) == "fire"  # 60 s held


def test_quiet_hours_suppress_new_fires_but_allow_clears():
    rule = _rule(hysteresis=5.0)
    st = AlertState()
    assert step(rule, 10.0, st, now=0.0, in_quiet=True) is None  # suppressed
    assert not st.active
    # Once quiet ends it fires; a later clear is never suppressed.
    assert step(rule, 10.0, st, now=1.0, in_quiet=False) == "fire"
    assert step(rule, 30.0, st, now=2.0, in_quiet=True) == "clear"


def test_missing_value_does_not_breach_or_clear():
    rule = _rule()
    st = AlertState()
    assert step(rule, None, st, now=0.0, in_quiet=False) is None
    # An active alert stays active when the metric goes missing (missing ≠ recovered).
    step(rule, 10.0, st, now=1.0, in_quiet=False)
    assert st.active
    assert step(rule, None, st, now=2.0, in_quiet=False) is None
    assert st.active


def test_gt_rule_clears_below_threshold_minus_hysteresis():
    rule = _rule(metric="inverter_temp_c", op="gt", threshold=50.0, hysteresis=5.0)
    st = AlertState()
    assert step(rule, 55.0, st, now=0.0, in_quiet=False) == "fire"
    assert step(rule, 47.0, st, now=1.0, in_quiet=False) is None    # in band (45–50)
    assert step(rule, 44.0, st, now=2.0, in_quiet=False) == "clear"  # below 50−5


# --- engine wrapper + defaults --------------------------------------------------
def test_engine_tracks_state_and_active_ids():
    eng = AlertEngine()
    rule = _rule(id="soc")
    assert eng.step(rule, 10.0, now=0.0, in_quiet=False) == "fire"
    assert eng.active_rule_ids() == {"soc"}
    assert eng.step(rule, 50.0, now=1.0, in_quiet=False) == "clear"
    assert eng.active_rule_ids() == set()
    eng.forget("soc")
    assert eng.state("soc").active is False


def test_rule_roundtrips_through_dict():
    rule = _rule(id="x", channels=("webhook",), quiet_hours=(22, 7), debounce_s=30.0)
    again = AlertRule.from_dict(rule.to_dict())
    assert again == rule
    with pytest.raises(ValueError):
        AlertRule.from_dict({"id": "x", "metric": "m", "op": "bogus"})


def test_default_rules_present_and_sane():
    rules = {r.id: r for r in default_rules()}
    assert {"low_soc", "device_stale", "inverter_fault"} <= set(rules)
    assert rules["low_soc"].op == "lt" and rules["low_soc"].threshold == 20.0
    assert rules["inverter_fault"].metric == "__fault_count__"
