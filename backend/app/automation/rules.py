"""Rule-based automation engine — pure, suggest-first (plan.md §18; extends L03).

Where `planner.py` is one built-in *strategy* (cost-arbitrage), this is the **user-authored**
layer: condition→action rules with three action types:
  - ``set_setting``  — write an inverter register (gated by ENABLE_CONTROL, §12 safeguards).
  - ``notify``       — dispatch a push notification via the §15 channel seam (ungated).
  - ``alert``        — create an in-app inbox alert with ack/snooze (ungated).

Rules are **combinable** and **prioritised**: for ``set_setting`` the highest-priority matching
action wins on a field conflict; ``notify``/``alert`` actions all fire independently.
Disabled rules/actions produce previews but never fire.

The ``compare`` helper lives here (moved from the retired ``alerts.engine`` in L03e-5e).

EvalContext metrics include two synthetic keys resolved by the service:
  ``__stale_s__``    — seconds since the device's last reading (offline/stale detection).
  ``__fault_count__``— count of active inverter fault codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ..tariff import RateSchedule

CONDITION_KINDS = ("day_of_week", "time_window", "date_range", "metric", "tariff_window")
ACTION_TYPES = ("set_setting", "notify", "alert")
_MATCH_MODES = ("all", "any")
_OPS = {"lt", "le", "gt", "ge", "eq", "ne"}


def compare(value: float, op: str, threshold: float) -> bool:
    """The raw firing condition ``value <op> threshold``."""
    if op == "lt":
        return value < threshold
    if op == "le":
        return value <= threshold
    if op == "gt":
        return value > threshold
    if op == "ge":
        return value >= threshold
    if op == "eq":
        return value == threshold
    if op == "ne":
        return value != threshold
    raise ValueError(f"unknown operator {op!r}")


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


def allow_list_from_schema(schema: Mapping[str, Any] | None) -> AllowList:
    """Derive the automation allow-list from a settings schema dict (the form spec exposed at
    `…/settings/schema`). `writable` = every writable field; `safe` = the profile's
    automation-safe subset. A device with no settings schema yields an empty (all-`blocked`)
    list, so automation can never write to a monitoring-only device."""
    if not schema:
        return AllowList()
    safe: set[tuple[str, str]] = set()
    writable: set[tuple[str, str]] = set()
    for section in schema.get("sections", []):
        skey = section["key"]
        for fld in section.get("fields", []):
            if fld.get("writable", True):
                writable.add((skey, fld["key"]))
                if fld.get("automation_safe"):
                    safe.add((skey, fld["key"]))
    return AllowList(safe=frozenset(safe), writable=frozenset(writable))


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
    """One action in an automation rule.

    ``action_type`` selects the kind:
      - ``set_setting``: write ``value`` to the settings ``target`` (gated by ENABLE_CONTROL).
      - ``notify``: dispatch a push message via the §15 channel seam (ungated); uses ``channels``,
        ``message``, ``severity``, ``debounce_s``.
      - ``alert``: create an in-app inbox alert (ungated); uses ``message``, ``severity``,
        ``debounce_s``.

    Both rule and action must be ``enabled`` for the action to fire; otherwise it is a preview.
    """

    action_type: str = "set_setting"
    target: Target | None = None   # set_setting only
    value: Any = None              # set_setting only
    enabled: bool = False
    channels: tuple[str, ...] = ()   # notify only
    message: str = ""                # notify + alert
    severity: str = "info"           # notify + alert
    debounce_s: float = 0.0          # notify + alert

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Action":
        action_type = str(d.get("action_type", "set_setting"))
        if action_type not in ACTION_TYPES:
            raise ValueError(f"unknown action_type {action_type!r}")
        raw_target = d.get("target")
        target = Target.from_dict(raw_target) if raw_target else None
        return cls(
            action_type=action_type,
            target=target,
            value=d.get("value"),
            enabled=bool(d.get("enabled", False)),
            channels=tuple(d.get("channels", []) or []),
            message=str(d.get("message", "")),
            severity=str(d.get("severity", "info")),
            debounce_s=float(d.get("debounce_s", 0.0)),
        )

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "target": self.target.to_dict() if self.target else None,
            "value": self.value,
            "enabled": self.enabled,
            "channels": list(self.channels),
            "message": self.message,
            "severity": self.severity,
            "debounce_s": self.debounce_s,
        }


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
    """One action a matching rule wants to take.

    ``active`` is True only when the rule and action are both enabled.
    For ``set_setting``: ``status`` is the allow-list verdict; ``will_apply`` requires
      active *and* not blocked.
    For ``notify``/``alert``: ``will_apply`` requires active only (no allow-list gate).
    """

    action_type: str              # set_setting | notify | alert
    rule_id: str
    rule_name: str
    priority: int
    active: bool
    # set_setting fields
    target: Target | None = None
    value: Any = None
    status: str = "ok"            # ok | at_risk | blocked
    # notify + alert fields
    channels: tuple[str, ...] = ()
    message: str = ""
    severity: str = "info"
    debounce_s: float = 0.0

    @property
    def will_apply(self) -> bool:
        if self.action_type == "set_setting":
            return self.active and self.status != "blocked"
        return self.active

    def as_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "rule_id": self.rule_id, "rule_name": self.rule_name, "priority": self.priority,
            "target": self.target.to_dict() if self.target else None,
            "value": self.value, "active": self.active, "status": self.status,
            "channels": list(self.channels), "message": self.message,
            "severity": self.severity, "debounce_s": self.debounce_s,
            "will_apply": self.will_apply,
        }


@dataclass(frozen=True, slots=True)
class AutomationDecision:
    """The merged outcome of evaluating all rules.

    ``changes``        — winning ``set_setting`` proposals (priority-resolved, sorted).
    ``overridden``     — ``set_setting`` proposals that lost a priority conflict.
    ``notifications``  — all matching ``notify`` actions (no conflict resolution).
    ``in_app_alerts``  — all matching ``alert`` actions (no conflict resolution).
    """

    changes: tuple[ProposedChange, ...] = ()
    overridden: tuple[ProposedChange, ...] = ()
    notifications: tuple[ProposedChange, ...] = ()
    in_app_alerts: tuple[ProposedChange, ...] = ()

    def settings_to_apply(self) -> tuple[ProposedChange, ...]:
        """Armed, non-blocked set_setting winners — what the apply path writes."""
        return tuple(c for c in self.changes if c.will_apply)

    def notify_actions(self) -> tuple[ProposedChange, ...]:
        """Armed notify actions ready to dispatch."""
        return tuple(n for n in self.notifications if n.active)

    def alert_actions(self) -> tuple[ProposedChange, ...]:
        """Armed alert actions ready to create inbox entries."""
        return tuple(a for a in self.in_app_alerts if a.active)

    def as_dict(self) -> dict:
        return {
            "changes": [c.as_dict() for c in self.changes],
            "overridden": [c.as_dict() for c in self.overridden],
            "notifications": [n.as_dict() for n in self.notifications],
            "in_app_alerts": [a.as_dict() for a in self.in_app_alerts],
        }


def evaluate_rules(
    rules: Iterable[AutomationRule],
    ctx: EvalContext,
    *,
    allow_list: AllowList | None = None,
) -> AutomationDecision:
    """Evaluate every rule against ``ctx`` and collect its actions.

    ``set_setting`` actions go through priority/conflict resolution: the highest-priority
    matching action wins per target field (ties broken by declaration order); losers land in
    ``overridden``. Disabled rules/actions are included as non-active previews.

    ``notify`` and ``alert`` actions are collected without conflict resolution — all matching
    ones are included so the service can dispatch them (with per-action debounce).
    """
    winners: dict[tuple[str, str | None, str], ProposedChange] = {}
    overridden: list[ProposedChange] = []
    notifications: list[ProposedChange] = []
    in_app_alerts: list[ProposedChange] = []

    for rule in rules:
        if not rule_matches(rule, ctx):
            continue
        active = rule.enabled
        for action in rule.actions:
            armed = active and action.enabled
            if action.action_type == "set_setting":
                if not action.target:
                    continue  # skip incomplete actions (no target chosen yet)
                status = allow_list.status(action.target.section, action.target.field) if allow_list else "ok"
                change = ProposedChange(
                    action_type="set_setting",
                    rule_id=rule.id, rule_name=rule.name, priority=rule.priority,
                    active=armed, target=action.target, value=action.value, status=status,
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
            elif action.action_type == "notify":
                notifications.append(ProposedChange(
                    action_type="notify",
                    rule_id=rule.id, rule_name=rule.name, priority=rule.priority, active=armed,
                    channels=action.channels, message=action.message,
                    severity=action.severity, debounce_s=action.debounce_s,
                ))
            elif action.action_type == "alert":
                in_app_alerts.append(ProposedChange(
                    action_type="alert",
                    rule_id=rule.id, rule_name=rule.name, priority=rule.priority, active=armed,
                    message=action.message, severity=action.severity, debounce_s=action.debounce_s,
                ))

    ordered = sorted(
        winners.values(),
        key=lambda c: (-c.priority, c.target.section if c.target else "", c.target.index or 0 if c.target else 0, c.target.field if c.target else ""),
    )
    return AutomationDecision(
        changes=tuple(ordered),
        overridden=tuple(overridden),
        notifications=tuple(notifications),
        in_app_alerts=tuple(in_app_alerts),
    )
