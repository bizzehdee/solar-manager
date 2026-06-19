"""Automation service (plan.md §18; tasks L03e-2, L03e-3) — wires the pure rules engine to
live data and (opt-in) applies its winners.

Orchestration only: it loads the user's rules (stored as a JSON list in `app_config`), builds
an `EvalContext` from the clock, the device's live snapshot metrics and the import tariff,
derives the writable allow-list from the device's settings schema, and asks the pure `rules`
engine for a decision. **Preview never writes** (suggest-only). The opt-in `apply` path
(L03e-3) takes only the armed, non-blocked winners and pushes each through the §12 control
write flow (validate → write → read-back → audit); a background scheduler does the same on an
interval. Both apply paths only run when the caller has confirmed control + automation are
enabled (the API gates the endpoint; the scheduler is only started under both flags).
All the decision logic lives in the pure `rules` module; this layer just gathers inputs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .. import control
from ..devices.base import TransportError
from ..metrics import ALL_METRICS
from ..tariff import Tariff
from .rules import (
    CONDITION_KINDS,
    AllowList,
    AutomationDecision,
    AutomationRule,
    EvalContext,
    allow_list_from_schema,
    evaluate_rules,
)

_RULES_KEY = "automation_rules"
log = logging.getLogger("solarvolt")


def _local_now() -> datetime:
    return datetime.now().astimezone()


class AutomationService:
    def __init__(
        self,
        app_config,
        poller,
        registry,
        *,
        clock=_local_now,
        audit_repo=None,
        interval_s: float = 300.0,
        apply_fn=None,
    ) -> None:
        self._cfg = app_config
        self._poller = poller
        self._registry = registry
        self._clock = clock
        self._audit = audit_repo
        self._interval = interval_s
        self._apply_fn = apply_fn or control.apply_settings
        self._task: asyncio.Task | None = None

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

    async def _decide(self, device_id: str | None) -> tuple[object, EvalContext, AutomationDecision, int]:
        device = self._device(device_id)
        stored = await self.list_rules()
        rules = [AutomationRule.from_dict(r) for r in stored]
        ctx = await self._context(device_id)
        decision = evaluate_rules(rules, ctx, allow_list=self._allow_list(device_id))
        return device, ctx, decision, len(stored)

    # --- read-only outputs -----------------------------------------------------
    async def preview(self, device_id: str | None = None) -> dict:
        device, ctx, decision, rule_count = await self._decide(device_id)
        return {
            "device_id": device.device_id if device is not None else device_id,
            "now": ctx.now.isoformat(),
            "decision": decision.as_dict(),
            "rule_count": rule_count,
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

    # --- opt-in apply (L03e-3; only reached when control + automation are both on) ----
    async def apply(self, device_id: str | None = None, *, source: str = "automation") -> dict:
        """Evaluate the rules and write the armed, non-blocked winners to the device via the §12
        control flow (validate → write → read-back → audit). Actions to the same section/slot are
        coalesced into one write. Returns a per-target summary; a single failed write is recorded
        and reported but never aborts the others. With no rules armed, nothing is written."""
        device, ctx, decision, _ = await self._decide(device_id)
        result: dict = {
            "device_id": device.device_id if device is not None else device_id,
            "now": ctx.now.isoformat(),
            "applied": [],
            "failed": [],
        }
        if device is None:
            return result

        # Coalesce the winners per (section, slot) so a slot's fields write together (§12 atomicity).
        slots: dict[tuple[str, int | None], dict] = {}
        for change in decision.settings_to_apply():
            slots.setdefault((change.target.section, change.target.index), {})[change.target.field] = change.value

        for (section, index), values in slots.items():
            try:
                applied = await self._apply_fn(device, section, values, index=index)
            except (control.SettingsError, TransportError) as exc:
                await self._record(device.device_id, section, index, {}, "error", source)
                log.warning("Automation apply to %s/%s failed: %s", section, index, exc)
                result["failed"].append({"section": section, "index": index, "error": str(exc)})
                continue
            await self._record(
                device.device_id, section, index, applied.changes,
                "ok" if applied.ok else "mismatch", source,
            )
            result["applied"].append({
                "section": section, "index": index, "ok": applied.ok,
                "changes": applied.changes, "mismatches": applied.mismatches, "etag": applied.etag,
            })
        return result

    async def apply_all(self, *, source: str = "automation:scheduler") -> list[dict]:
        """Run `apply` for every configured device (the scheduler's per-tick action)."""
        return [await self.apply(d.device_id, source=source) for d in self._registry.devices]

    async def _record(self, device_id, section, index, changes, status, source) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.record(self._clock().timestamp(), device_id, section, changes,
                                     status, slot=index, source=source)
        except Exception as exc:  # audit must never break the apply loop (§12 rule 6, off the hot path)
            log.warning("Automation audit record failed: %s", exc)

    # --- background scheduler --------------------------------------------------
    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.apply_all()
            except Exception as exc:  # a bad rule/tick must not kill the scheduler
                log.warning("Automation scheduler tick failed: %s", exc)
            await asyncio.sleep(self._interval)
