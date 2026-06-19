"""Automation service (plan.md §18; tasks L03e-2, L03e-3, L03e-5b) — wires the pure rules engine
to live data, dispatches non-write actions (notify/alert), and (opt-in) applies set_setting winners.

Orchestration only: loads user rules from `app_config`, builds an `EvalContext` from the clock,
live snapshot metrics (including synthetic ``__stale_s__`` / ``__fault_count__`` keys) and the
import tariff, derives the writable allow-list from the device's settings schema, and asks the
pure `rules` engine for a decision.

Action dispatch:
  - ``notify`` actions (push channels) and ``alert`` actions (in-app inbox) fire **whenever their
    rule/action is armed**, regardless of ``ENABLE_CONTROL``. Per-action ``debounce_s`` prevents
    re-firing within the window.
  - ``set_setting`` writes go through the §12 control flow (validate→write→read-back→audit) and
    are guarded by ``write=True`` — set only when ``ENABLE_CONTROL`` is on.

The background scheduler always starts (so notify/alert dispatch works on monitoring-only deploys);
it only does set_setting writes when started with ``write_enabled=True``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .. import control
from ..alerts.channels import Post, SendEmail, build_channels, dispatch
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
_OFFLINE_STALE_S = 1e9  # sentinel for "no reading at all" — matches alerts.service convention
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
        alert_repo=None,
        interval_s: float = 300.0,
        apply_fn=None,
        post: Post | None = None,
        send_email: SendEmail | None = None,
    ) -> None:
        self._cfg = app_config
        self._poller = poller
        self._registry = registry
        self._clock = clock
        self._audit = audit_repo
        self._alert_repo = alert_repo
        self._interval = interval_s
        self._apply_fn = apply_fn or control.apply_settings
        self._post = post
        self._send_email = send_email
        self._channels: dict = {}
        self._debounce: dict[tuple, float] = {}  # (rule_id, action_type, *key) → last-fire epoch
        self._write_enabled: bool = False
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
        dev_snap = snap.get(device_id) if device_id else None
        actual_id = device_id
        if dev_snap is None and snap:
            actual_id = next(iter(snap))
            dev_snap = snap[actual_id]
        raw = (dev_snap or {}).get("metrics", {})
        metrics: dict[str, float] = {k: float(v) for k, v in raw.items()
                                      if isinstance(v, (int, float)) and not isinstance(v, bool)}
        # Synthetic keys so metric conditions can target system state (mirrors alerts.service).
        health_list = self._poller.health().get("devices", []) if hasattr(self._poller, "health") else []
        h = next((d for d in health_list if d["device_id"] == actual_id), None) if actual_id else None
        if h is None or not h.get("online"):
            metrics["__stale_s__"] = _OFFLINE_STALE_S
        else:
            age = h.get("last_sample_age_s")
            metrics["__stale_s__"] = float(age) if age is not None else _OFFLINE_STALE_S
        codes = raw.get("inverter_fault_codes")
        metrics["__fault_count__"] = float(len(codes)) if isinstance(codes, list) else 0.0
        return metrics

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
            "metrics": sorted(ALL_METRICS) + ["__stale_s__", "__fault_count__"],
            "match_modes": ["all", "any"],
            "severities": ["info", "warning", "critical"],
            "channels": list(self._channels.keys()),
            "targets": targets,
        }

    # --- channel management ----------------------------------------------------
    async def reload_channels(self) -> None:
        """Rebuild the notification channel map from the current alert_channels config."""
        cfg = await self._cfg.get("alert_channels", {}) or {}
        self._channels = build_channels(cfg, post=self._post, send_email=self._send_email)

    # --- notify / alert dispatch (ungated by ENABLE_CONTROL) -------------------
    def _debounce_key(self, action_type: str, rule_id: str, message: str, channels: tuple) -> tuple:
        return (rule_id, action_type, message, channels)

    async def _dispatch_notifications(
        self, device_id: str | None, decision: AutomationDecision, now: float
    ) -> None:
        for notif in decision.notify_actions():
            key = self._debounce_key("notify", notif.rule_id, notif.message, tuple(sorted(notif.channels)))
            if now - self._debounce.get(key, 0.0) < notif.debounce_s:
                continue
            self._debounce[key] = now
            payload = {
                "rule_id": notif.rule_id, "name": notif.rule_name,
                "message": notif.message or notif.rule_name,
                "severity": notif.severity, "device_id": device_id,
            }
            try:
                await dispatch(self._channels, notif.channels, payload)
            except Exception as exc:  # off the hot path — a dead channel must not disrupt the loop
                log.warning("Automation notify dispatch failed for rule %r: %s", notif.rule_id, exc)

    async def _create_alerts(
        self, device_id: str | None, decision: AutomationDecision, now: float
    ) -> None:
        if self._alert_repo is None:
            return
        for alert_action in decision.alert_actions():
            key = self._debounce_key("alert", alert_action.rule_id, alert_action.message, ())
            if now - self._debounce.get(key, 0.0) < alert_action.debounce_s:
                continue
            self._debounce[key] = now
            try:
                await self._alert_repo.insert_alert(
                    rule_id=alert_action.rule_id,
                    device_id=device_id,
                    severity=alert_action.severity,
                    metric=None,
                    value=None,
                    message=alert_action.message or alert_action.rule_name,
                    fired_at=now,
                )
            except Exception as exc:
                log.warning("Automation alert create failed for rule %r: %s", alert_action.rule_id, exc)

    # --- opt-in apply (L03e-3; write path gated by ENABLE_CONTROL) ------------
    async def apply(self, device_id: str | None = None, *, source: str = "automation",
                    write: bool = True) -> dict:
        """Evaluate rules, dispatch notify/alert actions (always), and optionally write
        armed set_setting winners via the §12 flow (validate→write→read-back→audit).

        ``write=False`` skips the register-write path entirely (used by the scheduler when
        ``ENABLE_CONTROL`` is off so notify/alert still dispatch on monitoring-only deploys).
        Coalesces same-section/slot fields into one write. A failed write is recorded and
        reported but never aborts the others."""
        device, ctx, decision, _ = await self._decide(device_id)
        now = ctx.now.timestamp()
        device_id_str = device.device_id if device is not None else device_id
        result: dict = {"device_id": device_id_str, "now": ctx.now.isoformat(), "applied": [], "failed": []}

        # Notify/alert dispatch is ungated (runs even without ENABLE_CONTROL).
        await self._dispatch_notifications(device_id_str, decision, now)
        await self._create_alerts(device_id_str, decision, now)

        if not write or device is None:
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

    async def apply_all(self, *, source: str = "automation:scheduler", write: bool = True) -> list[dict]:
        """Run ``apply`` for every configured device."""
        return [await self.apply(d.device_id, source=source, write=write) for d in self._registry.devices]

    async def _record(self, device_id, section, index, changes, status, source) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.record(self._clock().timestamp(), device_id, section, changes,
                                     status, slot=index, source=source)
        except Exception as exc:  # audit must never break the apply loop (§12 rule 6, off the hot path)
            log.warning("Automation audit record failed: %s", exc)

    # --- background scheduler --------------------------------------------------
    async def start(self, *, write_enabled: bool = False) -> None:
        """Start the background scheduler.

        Always starts so notify/alert dispatch works on monitoring-only deploys.
        ``write_enabled=True`` enables set_setting writes each tick (requires ENABLE_CONTROL).
        """
        self._write_enabled = write_enabled
        await self.reload_channels()
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
                await self.apply_all(source="automation:scheduler", write=self._write_enabled)
            except Exception as exc:  # a bad tick must not kill the scheduler
                log.warning("Automation scheduler tick failed: %s", exc)
            await asyncio.sleep(self._interval)
