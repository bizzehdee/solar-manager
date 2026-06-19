"""Automation service (plan.md §18; task L03e-2) — wires the pure rules engine to live data.

Thin orchestration only: it loads the user's rules (stored as a JSON list in `app_config`),
builds an `EvalContext` from the clock, the device's live snapshot metrics and the import
tariff, derives the writable allow-list from the device's settings schema, and returns the
engine's decision. **It never writes** — preview/suggest only (the opt-in apply path is L03e-3).
All the decision logic lives in the pure `rules` module; this layer just gathers inputs.
"""

from __future__ import annotations

from datetime import datetime

from ..metrics import ALL_METRICS
from ..tariff import Tariff
from .rules import (
    CONDITION_KINDS,
    AllowList,
    AutomationRule,
    EvalContext,
    allow_list_from_schema,
    evaluate_rules,
)

_RULES_KEY = "automation_rules"


def _local_now() -> datetime:
    return datetime.now().astimezone()


class AutomationService:
    def __init__(self, app_config, poller, registry, *, clock=_local_now) -> None:
        self._cfg = app_config
        self._poller = poller
        self._registry = registry
        self._clock = clock

    # --- rule storage (JSON list in app_config) --------------------------------
    async def list_rules(self) -> list[dict]:
        return await self._cfg.get(_RULES_KEY, []) or []

    async def upsert_rule(self, data: dict) -> dict:
        """Validate (by round-tripping the model) and store one rule, replacing any with the
        same id. Raises ValueError/KeyError on an invalid rule."""
        rule = AutomationRule.from_dict(data).to_dict()
        rules = [r for r in await self.list_rules() if r.get("id") != rule["id"]]
        rules.append(rule)
        await self._cfg.set(_RULES_KEY, rules)
        return rule

    async def delete_rule(self, rule_id: str) -> bool:
        rules = await self.list_rules()
        kept = [r for r in rules if r.get("id") != rule_id]
        if len(kept) == len(rules):
            return False
        await self._cfg.set(_RULES_KEY, kept)
        return True

    # --- context assembly ------------------------------------------------------
    def _device(self, device_id: str | None):
        if device_id:
            return self._registry.get(device_id)
        devices = self._registry.devices
        return devices[0] if devices else None

    async def _import_schedule(self, now: datetime):
        tariff = Tariff.from_dict(await self._cfg.get("tariff", {}) or {})
        return tariff.schedules_for(now)[0]  # the import schedule, season-aware

    def _metrics(self, device_id: str | None) -> dict[str, float]:
        snap = self._poller.snapshot().get("devices", {})
        dev = snap.get(device_id) if device_id else None
        if dev is None and snap:
            dev = next(iter(snap.values()))
        metrics = (dev or {}).get("metrics", {})
        return {k: float(v) for k, v in metrics.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}

    async def _context(self, device_id: str | None) -> EvalContext:
        now = self._clock()
        return EvalContext(now=now, metrics=self._metrics(device_id),
                           import_schedule=await self._import_schedule(now))

    def _allow_list(self, device_id: str | None) -> AllowList:
        device = self._device(device_id)
        schema = device.settings_schema() if device is not None else None
        return allow_list_from_schema(schema.as_dict() if schema is not None else None)

    # --- read-only outputs -----------------------------------------------------
    async def preview(self, device_id: str | None = None) -> dict:
        device = self._device(device_id)
        rules = [AutomationRule.from_dict(r) for r in await self.list_rules()]
        ctx = await self._context(device_id)
        decision = evaluate_rules(rules, ctx, allow_list=self._allow_list(device_id))
        return {
            "device_id": device.device_id if device is not None else device_id,
            "now": ctx.now.isoformat(),
            "decision": decision.as_dict(),
            "rule_count": len(rules),
        }

    def options(self, device_id: str | None = None) -> dict:
        """Field choices for the rule editor: condition kinds, metric keys, comparison operators,
        and the settable targets (from the device schema, each tagged ok/at_risk by safety)."""
        device = self._device(device_id)
        schema = device.settings_schema() if device is not None else None
        allow = self._allow_list(device_id)
        targets: list[dict] = []
        for section in (schema.as_dict()["sections"] if schema is not None else []):
            for fld in section["fields"]:
                if not fld.get("writable", True):
                    continue
                targets.append({
                    "section": section["key"],
                    "section_label": section["label"],
                    "field": fld["key"],
                    "label": fld["label"],
                    "type": fld["type"],
                    "repeating": section.get("repeating", False),
                    "count": section.get("count"),
                    "status": allow.status(section["key"], fld["key"]),
                })
        return {
            "condition_kinds": list(CONDITION_KINDS),
            "ops": ["lt", "le", "gt", "ge", "eq", "ne"],
            "metrics": sorted(ALL_METRICS),
            "match_modes": ["all", "any"],
            "targets": targets,
        }
