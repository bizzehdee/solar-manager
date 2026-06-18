"""Alerting subsystem (plan.md §15): a rule engine + evaluation service + notification
channels. Off the hot path — a failing channel degrades to a warning, never blocks polling.

The engine (`engine.py`) is pure, numeric, and heavily unit-tested (§21 critical logic);
the service (`service.py`) resolves each rule's value from the live snapshot/health, steps
the engine, persists fired/cleared events, and dispatches channels."""

from .engine import (
    AlertEngine,
    AlertEvent,
    AlertRule,
    AlertState,
    compare,
    default_rules,
    in_quiet_hours,
)

__all__ = [
    "AlertEngine",
    "AlertEvent",
    "AlertRule",
    "AlertState",
    "compare",
    "default_rules",
    "in_quiet_hours",
]
