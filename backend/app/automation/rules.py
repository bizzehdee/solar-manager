"""Rule-based automation engine — pure, suggest-first (plan.md §18; extends L03).

Where `planner.py` is one built-in *strategy* (cost-arbitrage), this is the **user-authored**
layer: condition→action rules that set inverter settings (e.g. "on weekends, set work-mode
slot 1 target SoC to 80%"). Rules are **combinable** (every matching rule contributes its
actions) and **prioritised** (on a conflicting write to the same field, the highest-priority
rule wins). The whole module is pure — plain data in, a decision out — so the decision logic
(a §21 critical surface) is unit-testable with known vectors; DB/clock/device/writes live in
the wiring layers.

Safety model (per the product decision): an action only *applies* when **both** its rule and
the action itself are affirmatively `enabled` (both default **off**). A disabled rule/action
is still evaluated and surfaced as a **preview** — "this would set X right now, if running" —
so the user can see what a rule would do before arming it. The set of writable targets is the
**inverter profile's** allow-list; a target in the profile's automation-safe subset is `ok`,
one that's writable-but-not-safe is `at_risk`, and one that isn't writable at all is `blocked`
(never applied, even if armed). With no allow-list supplied the engine treats every target as
`ok` (the wiring supplies the profile-derived list).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ..alerts.engine import compare
from ..tariff import RateSchedule

CONDITION_KINDS = ("day_of_week", "time_window", "date_range", "metric", "tariff_window")
_MATCH_MODES = ("all", "any")


# --- evaluation context --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EvalContext:
    """Everything the conditions evaluate against. `metrics` is a flat dict the wiring fills
    with the live canonical snapshot plus any forecast/derived figures (e.g.
    `forecast_pv_wh_tomorrow`); the engine stays agnostic about where they come from."""

    now: datetime
    metrics: Mapping[str, float] = field(default_factory=dict)
    import_schedule: RateSchedule | None = None


# --- allow-list (from the inverter profile) ------------------------------------
@dataclass(frozen=True, slots=True)
class AllowList:
    """Writable settings targets, split into the profile's automation-**safe** subset and the
    wider set of writable-but-riskier targets. Keys are `(section, field)` pairs."""

    safe: frozenset[tuple[str, str]] = frozenset()
    writable: frozenset[tuple[str, str]] = frozenset()

    def status(self, section: str, field_key: str) -> str:
        key = (section, field_key)
        if key in self.safe:
            return "ok"
        if key in self.writable:
            return "at_risk"
        return "blocked"


# --- model ---------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Condition:
    """One condition clause. `kind` selects the test; `params` carries its arguments. Kept as a
    serialisable (kind, params) pair so rules round-trip to/from the DB as plain JSON."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Condition":
        kind = str(d.get("kind", ""))
        if kind not in CONDITION_KINDS:
            raise ValueError(f"unknown condition kind {kind!r}")
        params = dict(d.get("params") or {})
        return cls(kind=kind, params=params)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "params": self.params}


@dataclass(frozen=True, slots=True)
class Target:
    """A reference to one writable settings field. `index` selects the slot for repeating
    sections (e.g. work-mode timer slots) and is None for flat sections."""

    section: str
    field: str
    index: int | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Target":
        idx = d.get("index")
        return cls(section=str(d["section"]), field=str(d["field"]),
                   index=int(idx) if idx is not None else None)

    def to_dict(self) -> dict:
        return {"section": self.section, "field": self.field, "index": self.index}

    @property
    def key(self) -> tuple[str, str | None, str]:
        return (self.section, self.index, self.field)


@dataclass(frozen=True, slots=True)
class Action:
    """Set `target` to `value`. Only applied when `enabled` (and its rule is enabled); otherwise
    it's surfaced as a preview."""

    target: Target
    value: Any
    enabled: bool = False

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Action":
        return cls(target=Target.from_dict(d["target"]), value=d.get("value"),
                   enabled=bool(d.get("enabled", False)))

    def to_dict(self) -> dict:
        return {"target": self.target.to_dict(), "value": self.value, "enabled": self.enabled}


@dataclass(frozen=True, slots=True)
class AutomationRule:
    id: str
    name: str
    conditions: tuple[Condition, ...] = ()
    actions: tuple[Action, ...] = ()
    match: str = "all"          # "all" ⇒ every condition must hold; "any" ⇒ at least one
    priority: int = 0           # higher wins on a conflicting write
    enabled: bool = False       # default off — must be affirmatively armed

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "AutomationRule":
        match = str(d.get("match", "all"))
        if match not in _MATCH_MODES:
            raise ValueError(f"unknown match mode {match!r}")
        return cls(
            id=str(d["id"]),
            name=str(d.get("name") or d["id"]),
            conditions=tuple(Condition.from_dict(c) for c in d.get("conditions", [])),
            actions=tuple(Action.from_dict(a) for a in d.get("actions", [])),
            match=match,
            priority=int(d.get("priority", 0)),
            enabled=bool(d.get("enabled", False)),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
            "match": self.match, "priority": self.priority, "enabled": self.enabled,
        }


# --- condition evaluation ------------------------------------------------------
def _in_hour_window(hour: float, start: float, end: float) -> bool:
    """Half-open [start, end) over a 24h clock, wrap-aware (start==end ⇒ never)."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _md(value: str) -> tuple[int, int]:
    """Parse a 'MM-DD' marker into (month, day)."""
    month, day = value.split("-")
    return int(month), int(day)


def _in_date_range(now: datetime, start: str, end: str) -> bool:
    """Inclusive month-day range, year-agnostic and wrap-aware (e.g. 11-01 → 02-28 = winter)."""
    cur = (now.month, now.day)
    lo, hi = _md(start), _md(end)
    if lo <= hi:
        return lo <= cur <= hi
    return cur >= lo or cur <= hi  # wraps the year boundary


def _current_rate_is(schedule: RateSchedule | None, now: datetime, want: str) -> bool:
    """Whether the active import rate at `now` is the cheapest/peak of the day."""
    if schedule is None:
        return False
    rates = [schedule.rate_at(h + 0.5) for h in range(24)]
    here = schedule.rate_at(now.hour + now.minute / 60.0)
    if want in ("cheapest", "cheap", "min"):
        return here == min(rates)
    if want in ("peak", "max"):
        return here == max(rates)
    raise ValueError(f"unknown tariff window {want!r}")


def evaluate_condition(cond: Condition, ctx: EvalContext) -> bool:
    p = cond.params
    if cond.kind == "day_of_week":
        days = {int(d) for d in p.get("days", [])}
        return ctx.now.weekday() in days  # Mon=0 … Sun=6
    if cond.kind == "time_window":
        hour = ctx.now.hour + ctx.now.minute / 60.0
        return _in_hour_window(hour, float(p["start_hour"]), float(p["end_hour"]))
    if cond.kind == "date_range":
        return _in_date_range(ctx.now, str(p["start"]), str(p["end"]))
    if cond.kind == "metric":
        value = ctx.metrics.get(str(p["metric"]))
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False  # absent/non-numeric metric can't match (missing ≠ zero, §4)
        return compare(float(value), str(p.get("op", "lt")), float(p["threshold"]))
    if cond.kind == "tariff_window":
        return _current_rate_is(ctx.import_schedule, ctx.now, str(p.get("window", "cheapest")))
    raise ValueError(f"unknown condition kind {cond.kind!r}")


def rule_matches(rule: AutomationRule, ctx: EvalContext) -> bool:
    """Whether a rule's conditions hold under its match mode. A rule with no conditions never
    matches (an always-on automation must be explicit, not an empty-condition accident)."""
    if not rule.conditions:
        return False
    results = (evaluate_condition(c, ctx) for c in rule.conditions)
    return all(results) if rule.match == "all" else any(results)


# --- decision ------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProposedChange:
    """One action a matching rule wants to take. `active` is True only when the rule and the
    action are both enabled (else it's a preview). `status` is the allow-list verdict; a change
    is actually applied only when `active and status != 'blocked'` (see `will_apply`)."""

    rule_id: str
    rule_name: str
    priority: int
    target: Target
    value: Any
    active: bool
    status: str  # ok | at_risk | blocked

    @property
    def will_apply(self) -> bool:
        return self.active and self.status != "blocked"

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "rule_name": self.rule_name, "priority": self.priority,
            "target": self.target.to_dict(), "value": self.value,
            "active": self.active, "status": self.status, "will_apply": self.will_apply,
        }


@dataclass(frozen=True, slots=True)
class AutomationDecision:
    """The merged outcome: `changes` are the winning per-target proposals (sorted), `overridden`
    are proposals that lost a priority conflict (kept for transparency in the UI)."""

    changes: tuple[ProposedChange, ...] = ()
    overridden: tuple[ProposedChange, ...] = ()

    def settings_to_apply(self) -> tuple[ProposedChange, ...]:
        """Just the winning changes that are armed and not blocked — what the apply path writes."""
        return tuple(c for c in self.changes if c.will_apply)

    def as_dict(self) -> dict:
        return {
            "changes": [c.as_dict() for c in self.changes],
            "overridden": [c.as_dict() for c in self.overridden],
        }


def evaluate_rules(
    rules: Iterable[AutomationRule],
    ctx: EvalContext,
    *,
    allow_list: AllowList | None = None,
) -> AutomationDecision:
    """Evaluate every rule against `ctx`, gather the actions of the matching ones, then resolve
    conflicts by priority. For each target field, the highest-priority matching action wins
    (ties broken by the order rules are given — declare important rules first); the losers are
    recorded in `overridden`. Allow-list status is stamped on every change.

    Disabled rules/actions are *included* (as non-`active` previews) so the UI can show what a
    rule would do before it's armed — they simply never get `will_apply=True`."""
    winners: dict[tuple[str, str | None, str], ProposedChange] = {}
    overridden: list[ProposedChange] = []

    for rule in rules:
        if not rule_matches(rule, ctx):
            continue
        for action in rule.actions:
            status = allow_list.status(action.target.section, action.target.field) if allow_list else "ok"
            change = ProposedChange(
                rule_id=rule.id,
                rule_name=rule.name,
                priority=rule.priority,
                target=action.target,
                value=action.value,
                active=rule.enabled and action.enabled,
                status=status,
            )
            key = action.target.key
            incumbent = winners.get(key)
            if incumbent is None:
                winners[key] = change
            elif change.priority > incumbent.priority:
                winners[key] = change
                overridden.append(incumbent)
            else:
                overridden.append(change)

    ordered = sorted(
        winners.values(),
        key=lambda c: (-c.priority, c.target.section, c.target.index or 0, c.target.field),
    )
    return AutomationDecision(changes=tuple(ordered), overridden=tuple(overridden))
