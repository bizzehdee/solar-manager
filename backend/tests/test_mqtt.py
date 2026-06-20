"""MQTT publisher + Home Assistant discovery (L07): the pure metric→sensor mapping, the
off-hot-path service, and the config/test API.

The broker publish is injected so nothing here needs a broker or the `paho` dependency.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.integrations import MqttService
from app.integrations.mqtt import (
    discovery_messages,
    metric_descriptor,
    state_message,
    state_topic,
)
from app.main import create_app

_BASE = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)

_SNAP = {
    "ts": "2026-06-21T12:00:00+00:00",
    "devices": {
        "dummy": {
            "ts": "2026-06-21T12:00:00+00:00",
            "metrics": {
                "battery_soc_pct": 55.0,
                "pv_power_w": 3200.0,
                "grid_frequency_hz": 50.0,
                "inverter_temp_c": 41.5,
                "today_pv_wh": 12000.0,
                "run_state": "on_grid",
                "inverter_fault_codes": ["F01", "F23"],
            },
        }
    },
}


class _Poller:
    def __init__(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> dict:
        return self._snapshot


class _Info:
    def __init__(self, vendor: str, model: str) -> None:
        self.vendor = vendor
        self.model = model


class _Device:
    def __init__(self, device_id: str, vendor: str, model: str) -> None:
        self.device_id = device_id
        self.info = _Info(vendor, model)


class _Registry:
    def __init__(self, devices) -> None:
        self.devices = devices


class _Config:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    async def get(self, key: str, default=None):
        return self._data.get(key, default)

    async def set(self, key: str, value) -> None:
        self._data[key] = value


def _recorder():
    sent: list[tuple[dict, list]] = []

    async def publish(conn: dict, messages: list) -> None:
        sent.append((conn, messages))

    return sent, publish


def _service(cfg: _Config | None = None, *, publish=None):
    reg = _Registry([_Device("dummy", "sunsynk", "SYNK-8K-SG05LP1")])
    return MqttService(_Poller(_SNAP), reg, cfg or _Config(), publish=publish)


# --- pure helpers --------------------------------------------------------------

def test_metric_descriptor_infers_units_and_classes_from_the_suffix():
    assert metric_descriptor("pv_power_w") == {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
    assert metric_descriptor("today_pv_wh")["state_class"] == "total_increasing"
    assert metric_descriptor("grid_frequency_hz")["device_class"] == "frequency"
    assert metric_descriptor("inverter_temp_c")["unit_of_measurement"] == "°C"
    # SoC percent gets the battery device_class; a generic percent does not.
    assert metric_descriptor("battery_soc_pct")["device_class"] == "battery"
    assert "device_class" not in metric_descriptor("some_ratio_pct")
    # Unclassifiable keys (run-state, status) → no descriptor fields.
    assert metric_descriptor("run_state") == {}


def test_state_message_is_one_json_blob_with_lists_joined():
    topic, payload, retain = state_message("solarvolt", "dummy", _SNAP["devices"]["dummy"]["metrics"])
    assert topic == "solarvolt/dummy/state" == state_topic("solarvolt", "dummy")
    assert retain is False
    body = json.loads(payload)
    assert body["battery_soc_pct"] == 55.0
    assert body["inverter_fault_codes"] == "F01, F23"  # list → joined string


def test_discovery_messages_one_retained_config_per_scalar_metric():
    metrics = _SNAP["devices"]["dummy"]["metrics"]
    msgs = discovery_messages("solarvolt", "homeassistant", "dummy", {"name": "dummy", "vendor": "sunsynk", "model": "X"}, metrics)
    topics = {t for (t, _p, _r) in msgs}
    # A config per scalar metric; the fault-code LIST is excluded (it isn't a sensor).
    assert "homeassistant/sensor/solarvolt_dummy/battery_soc_pct/config" in topics
    assert "homeassistant/sensor/solarvolt_dummy/run_state/config" in topics
    assert not any("inverter_fault_codes" in t for t in topics)
    assert all(r is True for (_t, _p, r) in msgs)  # discovery is retained

    cfg = json.loads(next(p for (t, p, _r) in msgs if "battery_soc_pct" in t))
    assert cfg["state_topic"] == "solarvolt/dummy/state"
    assert cfg["value_template"] == "{{ value_json.battery_soc_pct }}"
    assert cfg["unique_id"] == "solarvolt_dummy_battery_soc_pct"
    assert cfg["device"]["identifiers"] == ["solarvolt_dummy"]
    assert cfg["device"]["manufacturer"] == "sunsynk"


# --- service -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_once_sends_discovery_then_state():
    sent, publish = _recorder()
    svc = _service(publish=publish)
    n = await svc.publish_once({"host": "broker", "base_topic": "solarvolt", "discovery": True})
    assert n > 0
    conn, messages = sent[0]
    assert conn["host"] == "broker"
    topics = [t for (t, _p, _r) in messages]
    assert "solarvolt/dummy/state" in topics
    assert any(t.startswith("homeassistant/sensor/") for t in topics)


@pytest.mark.asyncio
async def test_discovery_emitted_once_until_shape_changes():
    sent, publish = _recorder()
    svc = _service(publish=publish)
    cfg = {"host": "broker", "discovery": True}

    await svc.publish_once(cfg)
    first = [t for (t, _p, _r) in sent[0][1]]
    assert any(t.startswith("homeassistant/") for t in first)

    # Second publish: same metric shape → state only, no repeated discovery.
    await svc.publish_once(cfg)
    second = [t for (t, _p, _r) in sent[1][1]]
    assert not any(t.startswith("homeassistant/") for t in second)

    # force_discovery() re-arms it (config change / manual test).
    svc.force_discovery()
    await svc.publish_once(cfg)
    third = [t for (t, _p, _r) in sent[2][1]]
    assert any(t.startswith("homeassistant/") for t in third)


@pytest.mark.asyncio
async def test_publish_once_skips_when_no_reading_yet():
    sent, publish = _recorder()
    reg = _Registry([])
    svc = MqttService(_Poller({"ts": "…", "devices": {}}), reg, _Config(), publish=publish)
    assert await svc.publish_once({"host": "broker"}) == 0
    assert sent == []


@pytest.mark.asyncio
async def test_tick_publishes_only_when_enabled_and_configured():
    sent, publish = _recorder()
    cfg = _Config({"mqtt": {"host": "broker", "enabled": False, "interval_s": 20}})
    svc = _service(cfg, publish=publish)

    assert await svc._tick() == 20.0  # disabled → no publish, configured interval still drives sleep
    assert sent == []

    cfg._data["mqtt"]["enabled"] = True
    await svc._tick()
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_tick_clamps_interval_and_swallows_broker_failure():
    async def boom(conn: dict, messages: list) -> None:
        raise RuntimeError("broker unreachable")

    cfg = _Config({"mqtt": {"host": "broker", "enabled": True, "interval_s": 1}})
    svc = _service(cfg, publish=boom)
    assert await svc._tick() == 5.0  # clamped to the floor; the failure is swallowed (no raise)


@pytest.mark.asyncio
async def test_start_stop_is_clean():
    svc = _service(publish=_recorder()[1])
    await svc.start()
    await svc.stop()


# --- API surface ---------------------------------------------------------------

def _client() -> TestClient:
    settings = Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)
    return TestClient(create_app(settings=settings, clock=lambda: _BASE))


def test_mqtt_config_round_trip_and_defaults():
    with _client() as client:
        assert client.get("/api/integrations/mqtt").json() == {
            "enabled": False, "host": None, "port": 1883, "username": None, "password": None,
            "tls": False, "base_topic": "solarvolt", "interval_s": 30.0,
            "discovery": True, "discovery_prefix": "homeassistant",
        }
        saved = client.put("/api/integrations/mqtt", json={
            "enabled": True, "host": "  broker.lan  ", "port": 8883, "tls": True,
            "interval_s": 1, "base_topic": "house", "discovery_prefix": "ha",
        }).json()
        assert saved["host"] == "broker.lan"  # trimmed
        assert saved["port"] == 8883
        assert saved["interval_s"] == 5.0  # clamped to the floor
        assert saved["base_topic"] == "house" and saved["discovery_prefix"] == "ha"
        assert client.get("/api/integrations/mqtt").json()["enabled"] is True


def test_mqtt_test_endpoint_requires_host_then_publishes():
    with _client() as client:
        assert client.post("/api/integrations/mqtt/test").status_code == 400  # no host

        client.put("/api/integrations/mqtt", json={"host": "broker", "enabled": True})
        sent, publish = _recorder()
        client.app.state.mqtt._publish = publish
        body = client.post("/api/integrations/mqtt/test").json()
        assert body["ok"] is True and body["published"] >= 1
        assert sent and sent[0][0]["host"] == "broker"


def test_mqtt_test_endpoint_surfaces_failure():
    with _client() as client:
        client.put("/api/integrations/mqtt", json={"host": "broker", "enabled": True})

        async def boom(conn: dict, messages: list) -> None:
            raise RuntimeError("connection refused")

        client.app.state.mqtt._publish = boom
        assert client.post("/api/integrations/mqtt/test").status_code == 502
