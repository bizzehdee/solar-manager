"""History + device-config API on the dummy (plan.md §7; tasks T044/T047)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _client(midday) -> TestClient:
    # registry=None => the app seeds its config DB (one dummy device) and builds the
    # registry from it, so /api/devices and the live registry stay consistent (as in prod).
    clock = lambda: midday  # noqa: E731
    settings = Settings(poll_interval_s=60, db_path=":memory:", persist_interval_s=3600)
    return TestClient(create_app(settings=settings, clock=clock))


def test_history_metrics_empty_until_persisted(midday):
    with _client(midday) as client:
        body = client.get("/api/history/metrics").json()
        assert body["device_id"] == "dummy"
        assert body["metrics"] == []  # nothing persisted yet (persist interval is 1h)


def test_history_query_shape(midday):
    # persist_once / aggregate / prune are covered directly in test_persistence.py;
    # here we assert the query endpoint's response shape + defaults (empty series).
    with _client(midday) as client:
        body = client.get("/api/history", params={"metric": "pv_power_w"}).json()
        assert body["metric"] == "pv_power_w"
        assert body["device_id"] == "dummy"
        assert body["resolution"] == "raw"
        assert body["end"] > body["start"]  # defaults to a 24h window ending now
        assert body["points"] == []


def test_history_bad_resolution_is_400(midday):
    with _client(midday) as client:
        r = client.get("/api/history", params={"metric": "pv_power_w", "resolution": "yearly"})
        assert r.status_code == 400


def test_devices_list_includes_status_and_capabilities(midday):
    with _client(midday) as client:
        client.get("/api/live")  # trigger a poll so the device is "online"
        body = client.get("/api/devices").json()
        dev = body["devices"][0]
        assert dev["id"] == "dummy"
        assert "battery_soc_pct" in dev["capabilities"]
        assert "online" in dev


def test_device_create_update_delete(midday):
    with _client(midday) as client:
        # create a second (dummy-transport) device
        r = client.post("/api/devices", json={"id": "dummy2", "name": "Second", "transport": "dummy"})
        assert r.status_code == 201
        assert r.json()["id"] == "dummy2"
        ids = [d["id"] for d in client.get("/api/devices").json()["devices"]]
        assert set(ids) == {"dummy", "dummy2"}

        # duplicate id -> 409
        assert client.post("/api/devices", json={"id": "dummy2", "transport": "dummy"}).status_code == 409

        # update
        r = client.put("/api/devices/dummy2", json={"name": "Renamed"})
        assert r.status_code == 200 and r.json()["name"] == "Renamed"

        # delete
        assert client.delete("/api/devices/dummy2").status_code == 204
        assert client.delete("/api/devices/dummy2").status_code == 404
        ids = [d["id"] for d in client.get("/api/devices").json()["devices"]]
        assert ids == ["dummy"]


def test_stats_daily_endpoint_shape(midday):
    with _client(midday) as client:
        body = client.get("/api/stats/daily").json()
        assert body["device_id"] == "dummy"
        assert "energy_wh" in body and "economics" in body
        assert set(body["energy_wh"]) == {"pv", "load", "import", "export", "charge", "discharge"}
        assert "savings" in body["economics"]


def test_stats_config_get_and_put(midday):
    with _client(midday) as client:
        # default tariff present
        cfg = client.get("/api/stats/config").json()
        assert "tariff" in cfg and "economics" in cfg

        # set a flat tariff + economics, read it back
        r = client.put("/api/stats/config", json={
            "tariff": {"import_rate": 0.30, "export_rate": 0.05, "currency": "GBP"},
            "economics": {"co2_intensity_g_per_kwh": 180.0},
        })
        assert r.status_code == 200
        back = r.json()
        assert back["tariff"]["import_rate"]["flat"] == 0.30
        assert back["economics"]["co2_intensity_g_per_kwh"] == 180.0


def test_device_settings_schema_and_values_ungated(midday):
    # Control is OFF by default in this client — the read-only settings endpoints must
    # still work (Phase 5 display is not gated).
    with _client(midday) as client:
        assert client.get("/api/health").json()["control_enabled"] is False

        schema = client.get("/api/devices/dummy/settings/schema").json()
        assert schema["supported"] is True
        sections = {s["key"]: s for s in schema["sections"]}
        assert sections["timer_slots"]["count"] == 6

        vals = client.get("/api/devices/dummy/settings").json()
        assert vals["supported"] is True
        assert vals["values"]["work_mode_detail"]["work_mode"] == 2
        assert len(vals["values"]["timer_slots"]) == 6
        assert vals["values"]["timer_slots"][0]["start_time"] == "00:05"

        # device list advertises that settings display is available
        dev = client.get("/api/devices").json()["devices"][0]
        assert dev["settings"] is True


def test_device_settings_unknown_device_404(midday):
    with _client(midday) as client:
        assert client.get("/api/devices/nope/settings").status_code == 404
        assert client.get("/api/devices/nope/settings/schema").status_code == 404


def test_device_create_validation(midday):
    with _client(midday) as client:
        # modbus_rtu needs profile + params.port
        assert client.post("/api/devices", json={"id": "x", "transport": "modbus_rtu"}).status_code == 422
        # unknown transport
        assert client.post("/api/devices", json={"id": "y", "transport": "carrier-pigeon"}).status_code == 422
        # missing id
        assert client.post("/api/devices", json={"transport": "dummy"}).status_code == 422
