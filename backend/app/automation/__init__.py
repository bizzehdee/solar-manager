"""Smart automation & scheduling (plan.md §18).

Tariff (§5) + forecast (§6) driven scheduling of the inverter's work-mode timer, built
strictly on the Control (§12) safeguards and **suggest-only first**. This package starts
with the pure planning engine (`planner.py`) — no DB, no I/O, no writes — so the brain is
unit-tested in isolation before anything is wired to a live device or allowed to write.
"""

from __future__ import annotations

from .planner import (
    AutomationPlan,
    AutomationStrategy,
    SlotChange,
    cheapest_window,
    overnight_target_soc_pct,
    peak_window,
    plan_timer,
)
from .rules import (
    Action,
    AllowList,
    AutomationDecision,
    AutomationRule,
    Condition,
    EvalContext,
    ProposedChange,
    Target,
    allow_list_from_schema,
    evaluate_condition,
    evaluate_rules,
    rule_matches,
)

__all__ = [
    "AutomationPlan",
    "AutomationStrategy",
    "SlotChange",
    "cheapest_window",
    "overnight_target_soc_pct",
    "peak_window",
    "plan_timer",
    "Action",
    "AllowList",
    "AutomationDecision",
    "AutomationRule",
    "Condition",
    "EvalContext",
    "ProposedChange",
    "Target",
    "allow_list_from_schema",
    "evaluate_condition",
    "evaluate_rules",
    "rule_matches",
]
