"""Alert evaluation service (plan.md §15; task T080/T082).

Mirrors the persistence service: a background task that, on its own cadence, reads the
poller's latest snapshot + health, resolves each rule's value, steps the pure engine, and
on a fire/clear writes the alert row and dispatches the rule's channels. Entirely off the
hot path — a bad rule or dead channel is caught and logged, never crashing the loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from ..storage.repository import AlertRepository
from .channels import Post, SendEmail, build_channels, dispatch
from .engine import (
    METRIC_FAULT_COUNT,
    METRIC_STALE_S,
    AlertEngine,
    AlertRule,
    default_rules,
    in_quiet_hours,
)

log = logging.getLogger("solarvolt.alerts")

_OFFLINE_STALE_S = 1e9  # finite sentinel for "no reading at all" (JSON-serialisable, unlike inf)


def _local_now() -> datetime:
    return datetime.now().astimezone()


class AlertService:
    def __init__(
        self,
        repo: AlertRepository,
        poller,
        app_config,
        *,
        interval_s: float = 30.0,
        clock=_local_now,
        post: Post | None = None,
        send_email: SendEmail | None = None,
    ) -> None:
        self._repo = repo
        self._poller = poller
        self._app_config = app_config
        self._interval = interval_s
        self._clock = clock
        self._post = post
        self._send_email = send_email
        self._engine = AlertEngine()
        self._rules: list[AlertRule] = []
        self._channels: dict = {}
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self._repo.seed_rules([r.to_dict() for r in default_rules()])
        await self.reload()
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

    async def reload(self) -> None:
        """Refresh rules + channels from storage/config (called on start + after edits)."""
        rules: list[AlertRule] = []
        for d in await self._repo.list_rules():
            try:
                rules.append(AlertRule.from_dict(d))
            except (KeyError, ValueError) as exc:
                log.warning("Skipping invalid alert rule %r: %s", d.get("id"), exc)
        self._rules = rules
        cfg = await self._app_config.get("alert_channels", {}) or {}
        self._channels = build_channels(cfg, post=self._post, send_email=self._send_email)

    async def _run(self) -> None:
        while True:
            try:
                await self.evaluate_once()
            except Exception as exc:  # the loop must survive any per-tick error
                log.warning("Alert evaluation failed: %s", exc)
            await asyncio.sleep(self._interval)

    async def evaluate_once(self) -> list[str]:
        """Step every enabled rule once; persist + dispatch fires/clears. Returns the event
        kinds produced (for tests)."""
        now_dt = self._clock()
        now = now_dt.timestamp()
        snapshot = self._poller.snapshot()
        health = {d["device_id"]: d for d in self._poller.health().get("devices", [])}
        events: list[str] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            try:
                device_id = self._device_for(rule, snapshot)
                value = self._resolve(rule, device_id, snapshot, health)
                in_quiet = in_quiet_hours(rule.quiet_hours, now_dt)
                event = self._engine.step(rule, value, now, in_quiet=in_quiet)
                if event == "fire":
                    await self._fire(rule, device_id, value, now)
                    events.append("fire")
                elif event == "clear":
                    await self._repo.clear_active(rule.id, device_id, now)
                    events.append("clear")
            except Exception as exc:  # one bad rule mustn't stop the rest
                log.warning("Alert rule %r failed: %s", rule.id, exc)
        return events

    # --- resolution -------------------------------------------------------------
    @staticmethod
    def _device_for(rule: AlertRule, snapshot: dict) -> str | None:
        if rule.device_id:
            return rule.device_id
        devices = list(snapshot.get("devices", {}).keys())
        return devices[0] if devices else None

    def _resolve(self, rule: AlertRule, device_id: str | None, snapshot: dict, health: dict) -> float | None:
        if rule.metric == METRIC_STALE_S:
            h = health.get(device_id or "")
            if h is None or not h.get("online"):
                return _OFFLINE_STALE_S
            age = h.get("last_sample_age_s")
            return float(age) if age is not None else _OFFLINE_STALE_S
        metrics = (snapshot.get("devices", {}).get(device_id or "") or {}).get("metrics", {})
        if rule.metric == METRIC_FAULT_COUNT:
            codes = metrics.get("inverter_fault_codes")
            return float(len(codes)) if isinstance(codes, list) else 0.0
        v = metrics.get(rule.metric)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    async def _fire(self, rule: AlertRule, device_id: str | None, value: float | None, now: float) -> None:
        alert = {
            "rule_id": rule.id,
            "device_id": device_id,
            "severity": rule.severity,
            "metric": rule.metric,
            "value": value,
            "message": rule.message or rule.name,
            "fired_at": now,
        }
        alert_id = await self._repo.insert_alert(**alert)
        await dispatch(self._channels, rule.channels, {**alert, "id": alert_id, "name": rule.name})
