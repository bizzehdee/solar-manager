"""Device factory + env-driven registry selection (plan.md §4/§13; task T031)."""

from __future__ import annotations

from app.config import Settings
from app.devices.factory import (
    build_dummy_device,
    build_modbus_device,
    build_registry_from_settings,
)
from app.devices.modbus_rtu import ModbusRtuConfig, ModbusRtuSource
from app.devices.yaml_profile import ModbusYamlProfile


def test_build_modbus_device_pairs_rtu_transport_with_yaml_profile():
    dev = build_modbus_device(
        "sunsynk", "sunsynk-8k-sg05lp1", ModbusRtuConfig(port="/dev/ttyUSB0")
    )
    assert dev.device_id == "sunsynk"
    assert isinstance(dev.transport, ModbusRtuSource)
    assert isinstance(dev.profile, ModbusYamlProfile)
    assert dev.profile.vendor == "sunsynk"


def test_default_registry_is_dummy_when_no_port():
    reg = build_registry_from_settings(Settings())
    assert [d.device_id for d in reg.devices] == ["dummy"]
    assert reg.get("dummy").profile.vendor == "dummy"


def test_registry_builds_real_device_when_port_set():
    settings = Settings(modbus_port="/dev/ttyUSB0", modbus_slave_id=1)
    reg = build_registry_from_settings(settings)
    assert [d.device_id for d in reg.devices] == ["sunsynk"]
    dev = reg.get("sunsynk")
    assert isinstance(dev.transport, ModbusRtuSource)
    assert dev.profile.vendor == "sunsynk"


def test_settings_from_env_reads_modbus(monkeypatch):
    monkeypatch.setenv("SOLAR_MANAGER_MODBUS_PORT", "/dev/ttyUSB1")
    monkeypatch.setenv("SOLAR_MANAGER_MODBUS_BAUD", "19200")
    monkeypatch.setenv("SOLAR_MANAGER_MODBUS_SLAVE_ID", "5")
    s = Settings.from_env()
    assert s.modbus_port == "/dev/ttyUSB1"
    assert s.modbus_baudrate == 19200
    assert s.modbus_slave_id == 5


def test_settings_from_env_defaults_to_no_port(monkeypatch):
    monkeypatch.delenv("SOLAR_MANAGER_MODBUS_PORT", raising=False)
    assert Settings.from_env().modbus_port is None


def test_build_dummy_device_helper():
    dev = build_dummy_device()
    assert dev.device_id == "dummy" and dev.profile.vendor == "dummy"


# --- config-DB-driven building (T047) ---------------------------------------------
from app.devices.factory import (  # noqa: E402
    build_device_from_config,
    build_registry_from_configs,
    default_device_configs,
)


def test_default_configs_dummy_when_no_port():
    rows = default_device_configs(Settings())
    assert len(rows) == 1 and rows[0]["transport"] == "dummy"


def test_default_configs_modbus_when_port_set():
    rows = default_device_configs(Settings(modbus_port="/dev/ttyUSB0"))
    assert rows[0]["transport"] == "modbus_rtu"
    assert rows[0]["params"]["port"] == "/dev/ttyUSB0"


def test_build_device_from_config_dummy_and_modbus():
    dummy = build_device_from_config({"id": "d", "transport": "dummy", "params": {}})
    assert isinstance(dummy.transport, type(build_dummy_device().transport))

    modbus = build_device_from_config(
        {"id": "inv", "transport": "modbus_rtu", "profile": "sunsynk-8k-sg05lp1",
         "params": {"port": "/dev/ttyUSB0", "slave_id": 2}}
    )
    assert isinstance(modbus.transport, ModbusRtuSource)
    assert modbus.profile.vendor == "sunsynk"


def test_build_device_from_config_disabled_or_unknown_returns_none():
    assert build_device_from_config({"id": "d", "transport": "dummy", "enabled": False}) is None
    assert build_device_from_config({"id": "d", "transport": "carrier-pigeon"}) is None


def test_build_registry_from_configs_skips_disabled():
    rows = [
        {"id": "a", "transport": "dummy"},
        {"id": "b", "transport": "dummy", "enabled": False},
        {"id": "c", "transport": "carrier-pigeon"},
    ]
    reg = build_registry_from_configs(rows)
    assert [d.device_id for d in reg.devices] == ["a"]
