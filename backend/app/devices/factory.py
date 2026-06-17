"""Building real devices from configuration (plan.md §4; tasks T030/T031).

Phase 1 has no device-config DB yet (that lands in Phase 2, T047), so a real inverter
is wired from environment variables: set `SOLAR_MANAGER_MODBUS_PORT` and the default
registry serves a real Sunsynk over RTU instead of the dummy. With nothing set, the
dummy remains the default — a fresh clone still gives a live synthetic dashboard with
zero hardware (plan.md §13).
"""

from __future__ import annotations

from .base import Device, system_clock
from .dummy import DummyProfile, NullTransport
from .modbus_rtu import ModbusRtuConfig, ModbusRtuSource
from .registry import DeviceRegistry
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


def build_dummy_device(device_id: str = "dummy", *, clock=system_clock) -> Device:
    return Device(device_id, NullTransport(), DummyProfile(clock=clock), clock=clock)


def build_registry_from_settings(settings, *, clock=system_clock) -> DeviceRegistry:
    """The default registry: a real RTU device when a Modbus port is configured,
    otherwise the dummy inverter (plan.md §4/§13)."""
    registry = DeviceRegistry()
    if getattr(settings, "modbus_port", None):
        registry.add(
            build_modbus_device(
                settings.modbus_device_id,
                settings.modbus_profile,
                ModbusRtuConfig(
                    port=settings.modbus_port,
                    baudrate=settings.modbus_baudrate,
                    slave_id=settings.modbus_slave_id,
                ),
                clock=clock,
            )
        )
    else:
        registry.add(build_dummy_device(clock=clock))
    return registry
