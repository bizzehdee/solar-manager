"""Alert rule engine (plan.md §15) — pure, numeric, §21-critical logic.

A rule is a numeric condition on a resolved value (`op` threshold) with **hysteresis**
(recover past threshold±hysteresis to clear), **debounce** (condition must hold N seconds
before firing), **quiet hours** (suppress *new* fires in a window — clears still happen),
and a severity + channel list. The engine knows nothing about where the value came from:
the service resolves each rule's `metric` to a number (a canonical metric, the stale-age in
seconds, or a fault count) and steps the engine. Stepping a rule yields at most one event —
`"fire"` or `"clear"` — and mutates the rule's tracked state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

AlertEvent = Literal["fire", "clear"]

# Synthetic metric keys the service resolves specially (everything else is a canonical metric).
METRIC_STALE_S = "__stale_s__"        # seconds since the device's last reading (offline/stale)
METRIC_FAULT_COUNT = "__fault_count__"  # number of active inverter fault codes

_OPS = {"lt", "le", "gt", "ge", "eq", "ne"}


def compare(value: float, op: str, threshold: float) -> bool:
    """The raw firing condition `value <op> threshold`."""
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


def in_quiet_hours(quiet_hours: tuple[int, int] | None, dt: datetime) -> bool:
    """Whether `dt` (local) falls in [start, end) — wrap-aware (e.g. 22→7 spans midnight)."""
    if not quiet_hours:
        return False
    start, end = quiet_hours
    h = dt.hour
    if start == end:
        return False
    if start < end:
        return start <= h < end
    return h >= start or h < end  # wraps midnight


@dataclass(frozen=True, slots=True)
class AlertRule:
    id: str
    name: str
    metric: str                          # canonical key, or METRIC_STALE_S / METRIC_FAULT_COUNT
    op: str = "lt"
    threshold: float = 0.0
    hysteresis: float = 0.0              # clear margin past the threshold (units of value)
    debounce_s: float = 0.0             # condition must hold this long before firing
    severity: str = "warning"           # info | warning | critical
    channels: tuple[str, ...] = ()      # channel names; in-app inbox is always recorded
    quiet_hours: tuple[int, int] | None = None
    device_id: str | None = None        # None ⇒ the default/first device
    message: str = ""                   # optional human message template
    enabled: bool = True

    def clears(self, value: float) -> bool:
        """Whether `value` has recovered far enough (past the hysteresis band) to clear."""
        if self.op in ("eq", "ne"):
            return not compare(value, self.op, self.threshold)
        h = self.hysteresis
        if self.op in ("lt", "le"):
            return value >= self.threshold + h
        return value <= self.threshold - h  # gt / ge

    @classmethod
    def from_dict(cls, d: dict) -> "AlertRule":
        op = d.get("op", "lt")
        if op not in _OPS:
            raise ValueError(f"unknown operator {op!r}")
        q = d.get("quiet_hours")
        quiet = (int(q[0]), int(q[1])) if q else None
        return cls(
            id=str(d["id"]),
            name=str(d.get("name") or d["id"]),
            metric=str(d["metric"]),
            op=op,
            threshold=float(d.get("threshold", 0.0)),
            hysteresis=float(d.get("hysteresis", 0.0)),
            debounce_s=float(d.get("debounce_s", 0.0)),
            severity=str(d.get("severity", "warning")),
            channels=tuple(d.get("channels", []) or []),
            quiet_hours=quiet,
            device_id=d.get("device_id"),
            message=str(d.get("message", "")),
            enabled=bool(d.get("enabled", True)),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "metric": self.metric, "op": self.op,
            "threshold": self.threshold, "hysteresis": self.hysteresis,
            "debounce_s": self.debounce_s, "severity": self.severity,
            "channels": list(self.channels),
            "quiet_hours": list(self.quiet_hours) if self.quiet_hours else None,
            "device_id": self.device_id, "message": self.message, "enabled": self.enabled,
        }


@dataclass(slots=True)
class AlertState:
    breaching_since: float | None = None  # epoch when the condition first held (debounce timer)
    active: bool = False                  # currently firing
    fired_at: float | None = None


def step(rule: AlertRule, value: float | None, state: AlertState, now: float, *, in_quiet: bool) -> AlertEvent | None:
    """Advance one rule by one tick against its resolved `value` (None ⇒ metric absent),
    mutating `state`. Returns "fire"/"clear"/None. Quiet hours suppress *new* fires only."""
    if value is None:
        # Missing value can't breach; a missing value doesn't auto-clear an active alert
        # (the metric simply wasn't reported this tick — missing ≠ recovered).
        state.breaching_since = None
        return None

    if compare(value, rule.op, rule.threshold):
        if state.breaching_since is None:
            state.breaching_since = now
        if not state.active and (now - state.breaching_since) >= rule.debounce_s and not in_quiet:
            state.active = True
            state.fired_at = now
            return "fire"
        return None

    # Not breaching. Reset the debounce timer; clear only once past the hysteresis band.
    state.breaching_since = None
    if state.active and rule.clears(value):
        state.active = False
        state.fired_at = None
        return "clear"
    return None


class AlertEngine:
    """Holds per-rule state and steps a batch of rules against resolved values."""

    def __init__(self) -> None:
        self._states: dict[str, AlertState] = {}

    def state(self, rule_id: str) -> AlertState:
        return self._states.setdefault(rule_id, AlertState())

    def forget(self, rule_id: str) -> None:
        self._states.pop(rule_id, None)

    def step(self, rule: AlertRule, value: float | None, now: float, *, in_quiet: bool) -> AlertEvent | None:
        return step(rule, value, self.state(rule.id), now, in_quiet=in_quiet)

    def active_rule_ids(self) -> set[str]:
        return {rid for rid, st in self._states.items() if st.active}


def default_rules() -> list[AlertRule]:
    """Sensible alerts shipped on (plan.md §15): low SoC, device stale/offline, inverter fault."""
    return [
        AlertRule(id="low_soc", name="Low battery SoC", metric="battery_soc_pct",
                  op="lt", threshold=20.0, hysteresis=5.0, debounce_s=60.0, severity="warning",
                  message="Battery SoC is low"),
        AlertRule(id="device_stale", name="Device offline / stale data", metric=METRIC_STALE_S,
                  op="gt", threshold=120.0, hysteresis=30.0, debounce_s=0.0, severity="critical",
                  message="No fresh data from the inverter"),
        AlertRule(id="inverter_fault", name="Inverter fault", metric=METRIC_FAULT_COUNT,
                  op="gt", threshold=0.0, debounce_s=0.0, severity="critical",
                  message="Inverter reported a fault"),
    ]
