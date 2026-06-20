"""MQTT publisher + Home Assistant auto-discovery (plan.md §14; task L07).

Publishes each normalized snapshot to a user's MQTT broker and emits Home Assistant MQTT
**discovery** configs so every metric shows up as an HA sensor with zero manual YAML. Like the
other integrations (readings webhook, persistence) it runs as its own background task on its own
cadence, re-reads its config every tick, and is **off the hot path** — a dead/unreachable broker
is logged and swallowed so it can never disrupt polling/persistence (CLAUDE.md).

Config lives in the `mqtt` app-config blob:
    {"enabled": true, "host": "…", "port": 1883, "username": …, "password": …, "tls": false,
     "base_topic": "solarvolt", "interval_s": 30.0,
     "discovery": true, "discovery_prefix": "homeassistant"}

Topics (one compact JSON state message per device, the idiomatic HA shape):
    state:     {base_topic}/{device_id}/state          → {"battery_soc_pct": 55.0, …}
    discovery: {discovery_prefix}/sensor/solarvolt_{device_id}/{metric}/config  (retained)

The discovery configs reference the state topic via a `value_template`, so N metrics ride one
state message. The broker publish is injectable so tests run with no broker and no `paho` import.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

log = logging.getLogger("solarvolt.integrations")

# A single broker message: (topic, payload-string, retain).
Message = tuple[str, str, bool]
# publish(conn, messages) -> None. `conn` is the connection sub-config (host/port/auth/tls).
# Injected so tests never touch a broker (mirrors the webhook channels' `post`).
Publish = Callable[[dict, list[Message]], Awaitable[None]]

MIN_INTERVAL_S = 5.0
DEFAULT_INTERVAL_S = 30.0
DEFAULT_PORT = 1883
DEFAULT_BASE_TOPIC = "solarvolt"
DEFAULT_DISCOVERY_PREFIX = "homeassistant"


def _paho_publish(conn: dict, messages: list[Message]) -> None:
    """Blocking one-shot publish via paho's `publish.multiple` (connect → publish all → disconnect),
    run off the event loop in a thread. Imported lazily so the module loads without `paho` and tests
    that inject a fake publisher never need the dependency."""
    import paho.mqtt.publish as publish

    auth = None
    if conn.get("username"):
        auth = {"username": conn["username"], "password": conn.get("password") or ""}
    tls = {} if conn.get("tls") else None
    msgs = [{"topic": t, "payload": p, "qos": 0, "retain": r} for (t, p, r) in messages]
    publish.multiple(
        msgs,
        hostname=conn["host"],
        port=int(conn.get("port") or DEFAULT_PORT),
        auth=auth,
        tls=tls,
        client_id=conn.get("client_id") or "solarvolt",
    )


async def _paho_publish_async(conn: dict, messages: list[Message]) -> None:
    await asyncio.to_thread(_paho_publish, conn, messages)


# ── Pure helpers (unit-tested): canonical metric → HA sensor metadata, topics, payloads ──

# (unit, device_class, state_class) inferred from the canonical key's suffix (plan.md §4 — the
# vocabulary is suffix-typed). Daily Wh counters reset at midnight, so `total_increasing` (HA
# treats a reset as a new cycle, the right model for the Energy dashboard).
def metric_descriptor(key: str) -> dict:
    """HA discovery fields for a canonical metric key, or {} when we can't classify it."""
    if key.endswith("_wh"):
        return {"unit_of_measurement": "Wh", "device_class": "energy", "state_class": "total_increasing"}
    if key.endswith("_w"):
        return {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
    if key.endswith("_v"):
        return {"unit_of_measurement": "V", "device_class": "voltage", "state_class": "measurement"}
    if key.endswith("_a"):
        return {"unit_of_measurement": "A", "device_class": "current", "state_class": "measurement"}
    if key.endswith("_hz"):
        return {"unit_of_measurement": "Hz", "device_class": "frequency", "state_class": "measurement"}
    if key.endswith("_c"):
        return {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}
    if key.endswith("_pct"):
        d = {"unit_of_measurement": "%", "state_class": "measurement"}
        if "soc" in key:
            d["device_class"] = "battery"
        return d
    return {}  # run_state, *_cycles, *_status, etc. — a plain sensor, no class


def _pretty(key: str) -> str:
    """A readable sensor name from a canonical key: drop the unit suffix, de-snake, capitalise.
    `battery_soc_pct` → "Battery soc"; `grid_frequency_hz` → "Grid frequency"."""
    for suf in ("_pct", "_wh", "_hz", "_w", "_v", "_a", "_c"):
        if key.endswith(suf):
            key = key[: -len(suf)]
            break
    text = key.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _jsonable(value):
    """State value coerced to something MQTT/JSON-friendly: lists (fault codes) → a joined string."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return value


def state_topic(base_topic: str, device_id: str) -> str:
    return f"{base_topic}/{device_id}/state"


def state_message(base_topic: str, device_id: str, metrics: dict) -> Message:
    """One retained-false JSON state message carrying every metric for a device."""
    payload = json.dumps({k: _jsonable(v) for k, v in metrics.items()})
    return (state_topic(base_topic, device_id), payload, False)


def discovery_messages(base_topic: str, discovery_prefix: str, device_id: str, device_meta: dict, metrics: dict) -> list[Message]:
    """Retained HA discovery config per scalar metric, all grouped under one HA `device`."""
    node = f"solarvolt_{device_id}"
    device_block = {
        "identifiers": [node],
        "name": device_meta.get("name") or device_id,
        "manufacturer": device_meta.get("vendor") or "SolarVolt",
        "model": device_meta.get("model") or "inverter",
    }
    st = state_topic(base_topic, device_id)
    out: list[Message] = []
    for key, value in metrics.items():
        if isinstance(value, (list, tuple, dict)):
            continue  # fault/warning lists aren't sensors — they ride the state JSON only
        cfg = {
            "name": _pretty(key),
            "unique_id": f"{node}_{key}",
            "object_id": f"{node}_{key}",
            "state_topic": st,
            "value_template": f"{{{{ value_json.{key} }}}}",
            "device": device_block,
            **metric_descriptor(key),
        }
        topic = f"{discovery_prefix}/sensor/{node}/{key}/config"
        out.append((topic, json.dumps(cfg), True))
    return out


class MqttService:
    def __init__(
        self,
        poller,
        registry,
        app_config,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        publish: Publish | None = None,
    ) -> None:
        self._poller = poller
        self._registry = registry
        self._app_config = app_config
        self._interval = interval_s
        self._publish = publish or _paho_publish_async
        self._task: asyncio.Task | None = None
        # Signature of the last-published discovery set, so we only re-emit configs when the
        # device/metric shape changes rather than every tick.
        self._discovery_sig: str | None = None

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
            interval = await self._tick()
            await asyncio.sleep(interval)

    def _device_meta(self) -> dict:
        meta: dict[str, dict] = {}
        for device in getattr(self._registry, "devices", []) or []:
            info = getattr(device, "info", None)
            meta[device.device_id] = {
                "name": device.device_id,
                "vendor": getattr(info, "vendor", None),
                "model": getattr(info, "model", None),
            }
        return meta

    def _conn(self, cfg: dict) -> dict:
        return {
            "host": cfg["host"],
            "port": int(cfg.get("port") or DEFAULT_PORT),
            "username": cfg.get("username") or None,
            "password": cfg.get("password") or None,
            "tls": bool(cfg.get("tls", False)),
        }

    def _build_messages(self, cfg: dict) -> list[Message]:
        """State message per device, plus discovery configs when enabled and the shape changed."""
        base = cfg.get("base_topic") or DEFAULT_BASE_TOPIC
        snapshot = self._poller.snapshot()
        devices = snapshot.get("devices") or {}
        messages: list[Message] = []

        if cfg.get("discovery", True):
            prefix = cfg.get("discovery_prefix") or DEFAULT_DISCOVERY_PREFIX
            meta = self._device_meta()
            sig = json.dumps(
                {d: sorted(body.get("metrics", {}).keys()) for d, body in devices.items()},
                sort_keys=True,
            )
            if sig != self._discovery_sig:
                for device_id, body in devices.items():
                    messages += discovery_messages(base, prefix, device_id, meta.get(device_id, {}), body.get("metrics", {}))
                self._discovery_sig = sig

        for device_id, body in devices.items():
            messages.append(state_message(base, device_id, body.get("metrics", {})))
        return messages

    async def _tick(self) -> float:
        cfg = await self._app_config.get("mqtt", {}) or {}
        interval = max(float(cfg.get("interval_s") or self._interval), MIN_INTERVAL_S)
        if cfg.get("enabled") and cfg.get("host"):
            try:
                await self.publish_once(cfg)
            except Exception as exc:  # an unreachable broker must not disrupt the loop
                log.warning("MQTT publish to %r failed: %s", cfg.get("host"), exc)
        return interval

    async def publish_once(self, cfg: dict) -> int:
        """Publish state (+ discovery when due) once. Returns the message count (0 when there's no
        reading yet). Raises on broker failure — the loop swallows it; the test endpoint surfaces it."""
        messages = self._build_messages(cfg)
        if not messages:
            return 0
        await self._publish(self._conn(cfg), messages)
        return len(messages)

    def force_discovery(self) -> None:
        """Drop the cached signature so the next publish re-emits discovery (used by the test action
        and after a config change, so HA picks up new topics/units immediately)."""
        self._discovery_sig = None
