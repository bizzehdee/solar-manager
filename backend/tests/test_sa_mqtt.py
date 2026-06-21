"""Solar Assistant MQTT transport (plan.md §4, §20; task L20).

Exercised against a fake paho client — no broker. Covers topic→canonical mapping, numeric parsing,
the device→Reading path, connect-failure → TransportError, and the read-only write guard.
"""

from __future__ import annotations

import types

import pytest

from app.devices.base import Device, TransportError, system_clock
from app.devices.sa_mqtt import SaMqttConfig, SaMqttProfile, SaMqttSource, map_measurement


class FakeMqtt:
    """Minimal paho stand-in. `connect` records args (or raises); `deliver` simulates a message
    by invoking the registered on_message with a topic + payload."""

    def __init__(self, *, connect_exc=None):
        self._connect_exc = connect_exc
        self.on_connect = None
        self.on_message = None
        self.subscribed: list[str] = []
        self.looping = False
        self.connected_to = None

    def connect(self, host, port, keepalive):
        if self._connect_exc is not None:
            raise self._connect_exc
        self.connected_to = (host, port)

    def loop_start(self):
        self.looping = True
        if self.on_connect:
            self.on_connect(self, None, {}, 0)

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def loop_stop(self):
        self.looping = False

    def disconnect(self):
        self.connected_to = None

    def deliver(self, topic, payload):
        msg = types.SimpleNamespace(topic=topic, payload=payload.encode() if isinstance(payload, str) else payload)
        self.on_message(self, None, msg)


def _source(client=None, **cfg):
    client = client or FakeMqtt()
    config = SaMqttConfig(host=cfg.pop("host", "10.0.0.2"), **cfg)
    return SaMqttSource(config, client_factory=lambda c: client), client


def test_map_measurement_resolves_known_topics_only():
    # Topics validated against a live Solar Assistant instance (Sunsynk, inverter_1/ + total/).
    m = lambda t: map_measurement(t, "solar_assistant")
    assert m("solar_assistant/inverter_1/pv_power/state") == "pv_power_w"
    assert m("solar_assistant/inverter_1/grid_power/state") == "grid_power_w"
    assert m("solar_assistant/inverter_1/battery_voltage/state") == "battery_voltage_v"
    assert m("solar_assistant/total/battery_state_of_charge/state") == "battery_soc_pct"
    assert m("solar_assistant/total/battery_power/state") == "battery_power_w"
    assert m("solar_assistant/total/battery_temperature/state") == "battery_temp_c"
    # Inverter temperature is bare "temperature" under the inverter device segment.
    assert m("solar_assistant/inverter_1/temperature/state") == "inverter_temp_c"
    # …but a battery's bare temperature must NOT mis-map to the inverter key.
    assert m("solar_assistant/battery_1/temperature/state") is None
    # SA settings topics (work_mode, time_point_*, capacity_point_*, …) are not metrics → None.
    assert m("solar_assistant/inverter_1/work_mode/state") is None
    assert m("solar_assistant/inverter_1/load_power_essential/state") is None
    # Wrong base, not a /state topic, or an unmapped measurement → None.
    assert m("other/inverter_1/pv_power/state") is None
    assert m("solar_assistant/inverter_1/pv_power/config") is None
    assert m("solar_assistant/inverter_1/mystery/state") is None


@pytest.mark.asyncio
async def test_connect_subscribes_and_messages_map_to_canonical_metrics():
    src, client = _source()
    await src.connect()
    assert client.connected_to == ("10.0.0.2", 1883)
    assert client.subscribed == ["solar_assistant/#"]

    client.deliver("solar_assistant/inverter_1/pv_power/state", "4200")
    client.deliver("solar_assistant/battery_1/state_of_charge/state", "87.5")
    client.deliver("solar_assistant/inverter_1/grid_power/state", "-1500")

    assert src.latest() == {"pv_power_w": 4200.0, "battery_soc_pct": 87.5, "grid_power_w": -1500.0}
    assert src.comms_stats()["messages"] == 3 and src.comms_stats()["mapped"] == 3


@pytest.mark.asyncio
async def test_non_numeric_and_unmapped_payloads_are_skipped():
    src, client = _source()
    await src.connect()
    client.deliver("solar_assistant/inverter_1/inverter_state/state", "Solar/Battery")  # unmapped
    client.deliver("solar_assistant/inverter_1/pv_power/state", "not-a-number")          # mapped key, bad value
    assert src.latest() == {}


@pytest.mark.asyncio
async def test_device_read_returns_reading_of_latest_metrics():
    src, client = _source()
    device = Device("sa", src, SaMqttProfile(src.latest), clock=system_clock)
    await device.connect()
    client.deliver("solar_assistant/total/load_power/state", "950")
    reading = await device.read()
    assert reading.device_id == "sa"
    assert reading.metrics["load_power_w"] == 950.0


@pytest.mark.asyncio
async def test_connect_failure_raises_transport_error():
    src, _ = _source(FakeMqtt(connect_exc=ConnectionRefusedError("refused")))
    with pytest.raises(TransportError):
        await src.connect()


@pytest.mark.asyncio
async def test_writes_are_rejected_read_only():
    src, _ = _source()
    with pytest.raises(TransportError):
        await src.write_registers(0, [1])


@pytest.mark.asyncio
async def test_close_stops_loop_and_disconnects():
    src, client = _source()
    await src.connect()
    await src.close()
    assert client.looping is False and client.connected_to is None
    await src.close()  # idempotent — no client, no error


def test_profile_exposes_capabilities_and_info():
    profile = SaMqttProfile(lambda: {})
    assert "pv_power_w" in profile.capabilities()
    assert profile.register_blocks() == []
    assert profile.info.vendor == "solar-assistant"


@pytest.mark.asyncio
async def test_custom_base_topic_is_honoured():
    src, client = _source(base_topic="sa")
    await src.connect()
    assert client.subscribed == ["sa/#"]
    client.deliver("sa/inverter_1/load_power/state", "120")
    assert src.latest() == {"load_power_w": 120.0}
