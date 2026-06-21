"""Solar Assistant MQTT transport (plan.md §4, §20; task L20).

A **new device family**: instead of reading registers and decoding them (the Modbus family), this
subscribes to a **Solar Assistant** MQTT publisher and reads its already-decoded sensor values,
mapping them onto our canonical metric vocabulary. It lets a user run SolarVolt *alongside* Solar
Assistant against the same inverter — handy for side-by-side comparison while testing — without a
second RS485 connection.

The cross-family contract is `Reading` (canonical metrics), not registers (CLAUDE.md). So this
slots in as a `Transport` + `DeviceProfile` pair where the transport keeps the latest value per
topic in memory (updated on each MQTT message) and the profile just hands that map back as a
`Reading` — `register_blocks()` is empty, like the dummy.

Solar Assistant publishes to ``<base>/<device>/<measurement>/state`` (default base
``solar_assistant``), e.g. ``solar_assistant/inverter_1/pv_power/state``. `SA_MEASUREMENT_MAP`
translates the measurement segment → a canonical key. **It's a seed to verify against the user's
own instance, never trusted blindly** (CLAUDE.md): SA's measurement names vary slightly by version,
and its sign conventions are passed through as-is (flag for comparison). `paho-mqtt` (already a
dependency for the publisher) does the work; the client factory is injectable so tests need no
broker.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from ..models import DeviceInfo, MetricValue, Reading
from .base import TransportError

# Solar Assistant measurement (the topic's second-to-last segment) → canonical metric key.
# Validated against a live SA instance (Sunsynk via inverter_1/ + total/): SA publishes one
# value per measurement topic and matches our sign convention (battery +charge/-discharge,
# grid +import/-export — confirmed against a discharging snapshot). Aggregate values live under
# `total/` (battery SoC/power/temp); per-inverter ones under `inverter_1/`. Bare ambiguous names
# (`voltage`, `current`, `power`) are deliberately omitted; bare `temperature` is disambiguated by
# device segment in `map_measurement` (inverter temperature is published as `<inverter>/temperature`,
# while battery temperature is the explicit `battery_temperature`). The non-essential/CT variants
# (`grid_power_ct`, `load_power_essential`, …) are intentionally left out so one topic owns each key.
SA_MEASUREMENT_MAP: dict[str, str] = {
    "pv_power": "pv_power_w",
    "pv_power_1": "pv1_power_w",
    "pv_voltage_1": "pv1_voltage_v",
    "pv_current_1": "pv1_current_a",
    "pv_power_2": "pv2_power_w",
    "pv_voltage_2": "pv2_voltage_v",
    "pv_current_2": "pv2_current_a",
    "load_power": "load_power_w",
    "grid_power": "grid_power_w",
    "grid_voltage": "grid_voltage_v",
    "grid_frequency": "grid_frequency_hz",
    "battery_power": "battery_power_w",
    "battery_voltage": "battery_voltage_v",
    "battery_current": "battery_current_a",
    "battery_state_of_charge": "battery_soc_pct",
    "state_of_charge": "battery_soc_pct",
    "battery_temperature": "battery_temp_c",
    "battery_state_of_health": "battery_soh_pct",
    "inverter_temperature": "inverter_temp_c",  # alias for SA versions that name it explicitly
}


@dataclass(frozen=True, slots=True)
class SaMqttConfig:
    """Connection parameters for the Solar Assistant MQTT broker."""

    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    base_topic: str = "solar_assistant"
    tls: bool = False
    connect_timeout_s: float = 10.0


ClientFactory = Callable[[SaMqttConfig], "object"]


def _default_client_factory(config: SaMqttConfig):
    """Build a real paho-mqtt client. Imported lazily so the dummy-only path (and most tests) never
    need paho present at import time."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config.username:
        client.username_pw_set(config.username, config.password or "")
    if config.tls:
        client.tls_set()
    return client


def map_measurement(topic: str, base_topic: str) -> str | None:
    """Resolve a SA topic to a canonical metric key, or None if it isn't a mapped state topic."""
    prefix = base_topic.rstrip("/") + "/"
    if not topic.startswith(prefix) or not topic.endswith("/state"):
        return None
    parts = topic.split("/")
    if len(parts) < 2:
        return None
    measurement = parts[-2]
    key = SA_MEASUREMENT_MAP.get(measurement)
    if key is None and measurement == "temperature":
        # Bare "temperature" is the inverter's (battery temp is the explicit measurement). Only
        # accept it under an inverter device segment so a battery's bare temp can't mis-map.
        device = parts[-3] if len(parts) >= 3 else ""
        if device.startswith("inverter"):
            key = "inverter_temp_c"
    return key


class SaMqttSource:
    """MQTT-subscribing transport. Implements the register-shaped `Transport` protocol nominally
    (`read_registers` is unused — there are no registers), but its real job is to keep `latest()`
    fresh from the broker. The paired `SaMqttProfile` reads `latest()`."""

    def __init__(self, config: SaMqttConfig, *, client_factory: ClientFactory = _default_client_factory) -> None:
        self._config = config
        self._client_factory = client_factory
        self._client = None
        self._lock = threading.Lock()
        self._metrics: dict[str, MetricValue] = {}
        self._stats = {"messages": 0, "mapped": 0, "last_error": None, "last_message_ts": None}

    # --- shared state -----------------------------------------------------------
    def latest(self) -> dict[str, MetricValue]:
        with self._lock:
            return dict(self._metrics)

    def comms_stats(self) -> dict:
        return dict(self._stats)

    # --- paho callbacks ---------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc, *args) -> None:
        client.subscribe(self._config.base_topic.rstrip("/") + "/#")

    def _on_message(self, client, userdata, msg) -> None:
        with self._lock:
            self._stats["messages"] += 1
            self._stats["last_message_ts"] = time.time()
        key = map_measurement(msg.topic, self._config.base_topic)
        if key is None:
            return
        try:
            value = float(msg.payload.decode().strip())
        except (ValueError, AttributeError):
            return  # non-numeric payload (status string etc.) — skip
        with self._lock:
            self._metrics[key] = value
            self._stats["mapped"] += 1

    # --- Transport protocol -----------------------------------------------------
    async def connect(self) -> None:
        client = self._client_factory(self._config)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        try:
            await asyncio.to_thread(client.connect, self._config.host, self._config.port,
                                    int(self._config.connect_timeout_s))
        except Exception as exc:  # DNS / refused / auth
            self._stats["last_error"] = str(exc)
            raise TransportError(
                f"SA MQTT connect failed to {self._config.host}:{self._config.port}: {exc}"
            ) from exc
        client.loop_start()
        self._client = client

    async def read_registers(self, start: int, count: int, table: str = "holding") -> list[int]:
        return []  # no registers in this family

    async def write_registers(self, start, values) -> None:
        raise TransportError("sa_mqtt is read-only")

    async def close(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            finally:
                self._client = None


class SaMqttProfile:
    """Synthesising profile (like the dummy): no register blocks; `decode` returns the transport's
    latest MQTT-sourced metrics as canonical values."""

    vendor = "solar-assistant"

    def __init__(self, latest: Callable[[], dict[str, MetricValue]], *, model: str = "MQTT") -> None:
        self._latest = latest
        self._model = model

    def register_blocks(self):
        return []

    def decode(self, raw: Mapping[int, int]) -> dict[str, MetricValue]:
        return self._latest()

    def capabilities(self) -> set[str]:
        # What's reported depends on what SA publishes; advertise the keys we can map.
        return set(SA_MEASUREMENT_MAP.values())

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(vendor=self.vendor, model=self._model)
