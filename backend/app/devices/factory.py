"""Building devices from configuration (plan.md §4; tasks T030/T031/T047).

Devices live in the config DB and are managed in the web UI (Settings › Devices). On first run
the DB is seeded with the **dummy** simulator, so a fresh clone gives a live synthetic dashboard
with zero hardware (plan.md §13); real devices (Modbus RTU/TCP, SolarmanV5, Solar Assistant MQTT)
are then added through the UI. `build_device_from_config` turns one stored row into a `Device`.
"""

from __future__ import annotations

from .base import Device, system_clock
from .dummy import DummyProfile, NullTransport
from .modbus_rtu import ModbusRtuConfig, ModbusRtuSource
from .modbus_tcp import ModbusTcpConfig, ModbusTcpSource
from .registry import DeviceRegistry
from .sa_mqtt import SaMqttConfig, SaMqttProfile, SaMqttSource
from .solarman_v5 import SolarmanV5Config, SolarmanV5Source
from .yaml_profile import ModbusYamlProfile


def build_modbus_device(
    device_id: str,
    profile_name: str,
    config: ModbusRtuConfig,
    *,
    clock=system_clock,
) -> Device:
    """A Modbus-RTU device = RTU transport + a YAML register-map profile."""
    transport = ModbusRtuSource(config)
    profile = ModbusYamlProfile.from_name(profile_name)
    return Device(device_id, transport, profile, clock=clock)


def build_solarman_device(
    device_id: str,
    profile_name: str,
    config: SolarmanV5Config,
    *,
    clock=system_clock,
) -> Device:
    """A SolarmanV5 device = logger-TCP transport + a YAML register-map profile (same profiles as
    RTU — only the wire differs)."""
    transport = SolarmanV5Source(config)
    profile = ModbusYamlProfile.from_name(profile_name)
    return Device(device_id, transport, profile, clock=clock)


def build_modbus_tcp_device(
    device_id: str,
    profile_name: str,
    config: ModbusTcpConfig,
    *,
    clock=system_clock,
) -> Device:
    """A Modbus-TCP device = TCP transport + a YAML register-map profile (same profiles as RTU —
    only the wire differs)."""
    transport = ModbusTcpSource(config)
    profile = ModbusYamlProfile.from_name(profile_name)
    return Device(device_id, transport, profile, clock=clock)


def build_sa_mqtt_device(device_id: str, config: SaMqttConfig, *, clock=system_clock) -> Device:
    """A Solar Assistant MQTT device = an MQTT-subscribing transport + a synthesising profile that
    hands back the latest mapped metrics (a new family — no register profile)."""
    transport = SaMqttSource(config)
    profile = SaMqttProfile(transport.latest)
    return Device(device_id, transport, profile, clock=clock)


def build_dummy_device(device_id: str = "dummy", *, clock=system_clock) -> Device:
    return Device(device_id, NullTransport(), DummyProfile(clock=clock), clock=clock)


def default_device_configs() -> list[dict]:
    """The rows to seed an empty config DB with: the dummy simulator, so a fresh install gives a
    live synthetic dashboard with zero hardware. Real devices are added via the UI (plan.md §6/§13)."""
    return [{
        "id": "dummy", "name": "Simulated Inverter", "vendor": "dummy",
        "profile": "", "transport": "dummy", "params": {},
        "bms_topology": "inverter", "enabled": True,
    }]


def build_device_from_config(row: dict, *, clock=system_clock) -> Device | None:
    """Construct a Device from a config-DB row. Returns None for a disabled or unknown
    transport (the registry just skips it)."""
    if not row.get("enabled", True):
        return None
    transport = row.get("transport", "dummy")
    device_id = row["id"]
    if transport == "dummy":
        return build_dummy_device(device_id, clock=clock)
    if transport == "modbus_rtu":
        params = row.get("params") or {}
        cfg = ModbusRtuConfig(
            port=params["port"],
            baudrate=int(params.get("baudrate", 9600)),
            slave_id=int(params.get("slave_id", 1)),
        )
        return build_modbus_device(device_id, row["profile"], cfg, clock=clock)
    if transport == "solarman_v5":
        params = row.get("params") or {}
        cfg = SolarmanV5Config(
            host=params["host"],
            serial=int(params["serial"]),
            port=int(params.get("port", 8899)),
            slave_id=int(params.get("slave_id", 1)),
        )
        return build_solarman_device(device_id, row["profile"], cfg, clock=clock)
    if transport == "modbus_tcp":
        params = row.get("params") or {}
        cfg = ModbusTcpConfig(
            host=params["host"],
            port=int(params.get("port", 502)),
            slave_id=int(params.get("slave_id", 1)),
        )
        return build_modbus_tcp_device(device_id, row["profile"], cfg, clock=clock)
    if transport == "sa_mqtt":
        params = row.get("params") or {}
        cfg = SaMqttConfig(
            host=params["host"],
            port=int(params.get("port", 1883)),
            username=(params.get("username") or None),
            password=(params.get("password") or None),
            base_topic=str(params.get("base_topic") or "solar_assistant"),
            tls=bool(params.get("tls", False)),
            include_all=bool(params.get("include_all", False)),
        )
        return build_sa_mqtt_device(device_id, cfg, clock=clock)
    return None


def build_registry_from_configs(rows: list[dict], *, clock=system_clock) -> DeviceRegistry:
    """Build the registry from config-DB rows (skipping disabled/unknown ones)."""
    registry = DeviceRegistry()
    for row in rows:
        device = build_device_from_config(row, clock=clock)
        if device is not None:
            registry.add(device)
    return registry
