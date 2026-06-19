"""Pure rule-based automation engine (§18; extends L03) — conditions, combining, priority,
the enable/preview semantics, and the profile allow-list. No DB/IO."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.automation.rules import (
    Action,
    AllowList,
    AutomationRule,
    Condition,
    EvalContext,
    Target,
    evaluate_condition,
    evaluate_rules,
    rule_matches,
)
from app.tariff import RateSchedule

# 2026-06-20 is a Saturday (weekday()==5); 2026-06-22 is a Monday (0).
SAT = datetime(2026, 6, 20, 14, 30)
MON = datetime(2026, 6, 22, 14, 30)


def _ctx(now=SAT, metrics=None, schedule=None) -> EvalContext:
    return EvalContext(now=now, metrics=metrics or {}, import_schedule=schedule)


def _soc_action(index=1, value=80, enabled=True) -> Action:
    return Action(target=Target("timer_slots", "target_soc_pct", index), value=value, enabled=enabled)


# --- conditions ----------------------------------------------------------------
def test_day_of_week_condition():
    cond = Condition("day_of_week", {"days": [5, 6]})  # weekend
    assert evaluate_condition(cond, _ctx(SAT)) is True
    assert evaluate_condition(cond, _ctx(MON)) is False


def test_time_window_condition_wraps_midnight():
    cond = Condition("time_window", {"start_hour": 22, "end_hour": 6})
    assert evaluate_condition(cond, _ctx(datetime(2026, 6, 20, 23, 0))) is True
    assert evaluate_condition(cond, _ctx(datetime(2026, 6, 20, 5, 0))) is True
    assert evaluate_condition(cond, _ctx(datetime(2026, 6, 20, 12, 0))) is False


def test_date_range_condition_wraps_year():
    winter = Condition("date_range", {"start": "11-01", "end": "02-28"})
    assert evaluate_condition(winter, _ctx(datetime(2026, 1, 15, 0, 0))) is True
    assert evaluate_condition(winter, _ctx(datetime(2026, 12, 5, 0, 0))) is True
    assert evaluate_condition(winter, _ctx(datetime(2026, 6, 20, 0, 0))) is False
    summer = Condition("date_range", {"start": "05-01", "end": "08-31"})
    assert evaluate_condition(summer, _ctx(SAT)) is True


def test_metric_condition_compares_and_handles_absent():
    cond = Condition("metric", {"metric": "battery_soc_pct", "op": "lt", "threshold": 30})
    assert evaluate_condition(cond, _ctx(metrics={"battery_soc_pct": 12})) is True
    assert evaluate_condition(cond, _ctx(metrics={"battery_soc_pct": 55})) is False
    # Absent / non-numeric metric never matches (missing ≠ zero).
    assert evaluate_condition(cond, _ctx(metrics={})) is False
    assert evaluate_condition(cond, _ctx(metrics={"battery_soc_pct": True})) is False


def test_tariff_window_condition():
    # Cheap 00:00–05:00, peak 16:00–19:00, flat otherwise.
    sched = RateSchedule.from_dict({"flat": 0.20, "windows": [
        {"start_hour": 0, "end_hour": 5, "rate": 0.07},
        {"start_hour": 16, "end_hour": 19, "rate": 0.40},
    ]})
    cheap = Condition("tariff_window", {"window": "cheapest"})
    peak = Condition("tariff_window", {"window": "peak"})
    assert evaluate_condition(cheap, _ctx(datetime(2026, 6, 20, 2, 0), schedule=sched)) is True
    assert evaluate_condition(cheap, _ctx(datetime(2026, 6, 20, 12, 0), schedule=sched)) is False
    assert evaluate_condition(peak, _ctx(datetime(2026, 6, 20, 17, 0), schedule=sched)) is True
    # No schedule supplied ⇒ never matches (can't disrupt on missing data).
    assert evaluate_condition(cheap, _ctx(datetime(2026, 6, 20, 2, 0))) is False


def test_unknown_condition_kind_rejected_on_parse():
    with pytest.raises(ValueError):
        Condition.from_dict({"kind": "phase_of_moon"})


# --- match modes ---------------------------------------------------------------
def test_rule_match_all_vs_any():
    weekend = Condition("day_of_week", {"days": [5, 6]})
    afternoon = Condition("time_window", {"start_hour": 12, "end_hour": 18})
    monday = Condition("day_of_week", {"days": [0]})

    all_rule = AutomationRule("r", "r", conditions=(weekend, afternoon), match="all")
    assert rule_matches(all_rule, _ctx(SAT)) is True  # both hold on Sat afternoon

    any_rule = AutomationRule("r", "r", conditions=(monday, afternoon), match="any")
    assert rule_matches(any_rule, _ctx(SAT)) is True  # afternoon holds even though not Monday

    none_rule = AutomationRule("r", "r", conditions=(monday,), match="all")
    assert rule_matches(none_rule, _ctx(SAT)) is False


def test_rule_with_no_conditions_never_matches():
    assert rule_matches(AutomationRule("r", "r", conditions=()), _ctx(SAT)) is False


# --- evaluate_rules: enable/preview + combining + priority ---------------------
def test_disabled_rule_is_preview_not_applied():
    rule = AutomationRule("weekend", "Weekend SoC", conditions=(Condition("day_of_week", {"days": [5, 6]}),),
                          actions=(_soc_action(),), enabled=False)
    decision = evaluate_rules([rule], _ctx(SAT))
    assert len(decision.changes) == 1
    change = decision.changes[0]
    assert change.value == 80 and change.active is False and change.will_apply is False
    assert decision.settings_to_apply() == ()  # nothing armed


def test_armed_rule_and_action_applies():
    rule = AutomationRule("weekend", "Weekend SoC", conditions=(Condition("day_of_week", {"days": [5, 6]}),),
                          actions=(_soc_action(enabled=True),), enabled=True)
    decision = evaluate_rules([rule], _ctx(SAT))
    assert decision.changes[0].will_apply is True
    assert decision.settings_to_apply() == decision.changes


def test_action_disabled_even_when_rule_enabled_is_preview():
    rule = AutomationRule("r", "r", conditions=(Condition("day_of_week", {"days": [5]}),),
                          actions=(_soc_action(enabled=False),), enabled=True)
    assert evaluate_rules([rule], _ctx(SAT)).changes[0].active is False


def test_non_matching_rule_contributes_nothing():
    rule = AutomationRule("r", "r", conditions=(Condition("day_of_week", {"days": [0]}),),
                          actions=(_soc_action(),), enabled=True)
    assert evaluate_rules([rule], _ctx(SAT)).changes == ()


def test_priority_resolves_conflicts_on_the_same_target():
    cond = Condition("day_of_week", {"days": [5]})
    low = AutomationRule("low", "Low", conditions=(cond,), actions=(_soc_action(value=70),),
                         priority=1, enabled=True)
    high = AutomationRule("high", "High", conditions=(cond,), actions=(_soc_action(value=90),),
                          priority=5, enabled=True)
    decision = evaluate_rules([low, high], _ctx(SAT))
    assert len(decision.changes) == 1 and decision.changes[0].value == 90
    assert decision.changes[0].rule_id == "high"
    assert [c.rule_id for c in decision.overridden] == ["low"]


def test_non_conflicting_actions_all_merge():
    cond = Condition("day_of_week", {"days": [5]})
    r1 = AutomationRule("a", "A", conditions=(cond,),
                        actions=(Action(Target("timer_slots", "target_soc_pct", 1), 80, enabled=True),),
                        enabled=True)
    r2 = AutomationRule("b", "B", conditions=(cond,),
                        actions=(Action(Target("timer_slots", "target_soc_pct", 2), 60, enabled=True),),
                        enabled=True)
    decision = evaluate_rules([r1, r2], _ctx(SAT))
    assert {c.target.index for c in decision.changes} == {1, 2}
    assert decision.overridden == ()


# --- allow-list ----------------------------------------------------------------
def test_allow_list_marks_safe_at_risk_and_blocks():
    allow = AllowList(
        safe=frozenset({("timer_slots", "target_soc_pct")}),
        writable=frozenset({("timer_slots", "target_soc_pct"), ("globals", "max_charge_current")}),
    )
    cond = Condition("day_of_week", {"days": [5]})
    safe_rule = AutomationRule("s", "s", conditions=(cond,), actions=(_soc_action(enabled=True),), enabled=True)
    risky = AutomationRule("k", "k", conditions=(cond,),
                           actions=(Action(Target("globals", "max_charge_current"), 30, enabled=True),), enabled=True)
    blocked = AutomationRule("x", "x", conditions=(cond,),
                             actions=(Action(Target("globals", "grid_sell_enable"), 1, enabled=True),), enabled=True)
    decision = evaluate_rules([safe_rule, risky, blocked], _ctx(SAT), allow_list=allow)
    status = {c.target.section + "." + c.target.field: c.status for c in decision.changes}
    assert status["timer_slots.target_soc_pct"] == "ok"
    assert status["globals.max_charge_current"] == "at_risk"
    assert status["globals.grid_sell_enable"] == "blocked"
    # Blocked never applies even though armed; at_risk still applies (user opted in).
    applied = {c.target.field for c in decision.settings_to_apply()}
    assert applied == {"target_soc_pct", "max_charge_current"}


# --- serialisation round-trip --------------------------------------------------
def test_rule_dict_round_trip():
    d = {
        "id": "weekend", "name": "Weekend top-up", "match": "all", "priority": 3, "enabled": True,
        "conditions": [{"kind": "day_of_week", "params": {"days": [5, 6]}},
                       {"kind": "metric", "params": {"metric": "battery_soc_pct", "op": "lt", "threshold": 50}}],
        "actions": [{"target": {"section": "timer_slots", "field": "target_soc_pct", "index": 1},
                     "value": 80, "enabled": True}],
    }
    rule = AutomationRule.from_dict(d)
    assert rule.to_dict() == d
    assert rule.priority == 3 and rule.enabled is True


def test_invalid_match_mode_rejected():
    with pytest.raises(ValueError):
        AutomationRule.from_dict({"id": "r", "match": "most"})


def test_evaluate_condition_unknown_kind():
    # A kind that bypassed from_dict's guard still raises at evaluation time.
    bogus = object.__new__(Condition)
    object.__setattr__(bogus, "kind", "nope")
    object.__setattr__(bogus, "params", {})
    with pytest.raises(ValueError):
        evaluate_condition(bogus, _ctx())


def test_tariff_window_unknown_param_raises():
    sched = RateSchedule.from_dict({"flat": 0.2, "windows": [{"start_hour": 0, "end_hour": 5, "rate": 0.07}]})
    bad = Condition("tariff_window", {"window": "sideways"})
    with pytest.raises(ValueError):
        evaluate_condition(bad, _ctx(datetime(2026, 6, 20, 2, 0), schedule=sched))


def test_time_window_zero_width_never_matches():
    cond = Condition("time_window", {"start_hour": 8, "end_hour": 8})
    assert evaluate_condition(cond, _ctx(datetime(2026, 6, 20, 8, 0))) is False


def test_equal_priority_keeps_first_declared():
    cond = Condition("day_of_week", {"days": [5]})
    first = AutomationRule("first", "First", conditions=(cond,), actions=(_soc_action(value=70),),
                           priority=2, enabled=True)
    second = AutomationRule("second", "Second", conditions=(cond,), actions=(_soc_action(value=90),),
                            priority=2, enabled=True)
    decision = evaluate_rules([first, second], _ctx(SAT))
    assert decision.changes[0].rule_id == "first"  # declared first wins ties
    assert decision.overridden[0].rule_id == "second"


def test_decision_as_dict_serialises():
    cond = Condition("day_of_week", {"days": [5]})
    rule = AutomationRule("r", "R", conditions=(cond,), actions=(_soc_action(enabled=True),), enabled=True)
    d = evaluate_rules([rule], _ctx(SAT)).as_dict()
    assert d["changes"][0]["value"] == 80 and d["changes"][0]["will_apply"] is True
    assert d["changes"][0]["target"]["section"] == "timer_slots"
    assert d["overridden"] == []
