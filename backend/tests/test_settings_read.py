"""Settings schema + read_settings, read-only (plan.md §4/§12; task T070)."""

from __future__ import annotations

from app.devices.base import Device, system_clock
from app.devices.dummy import DummyProfile, NullTransport
from app.devices.yaml_profile import ModbusYamlProfile


def _profile() -> ModbusYamlProfile:
    return ModbusYamlProfile.from_name("sunsynk-8k-sg05lp1")


# Raw settings registers reconstructed from the validated SG05LP1 config read-out.
_RAW = {
    # timer slots
    250: 5, 251: 555, 252: 900, 253: 1300, 254: 1700, 255: 2100,
    256: 8000, 257: 8000, 258: 8000, 259: 8000, 260: 8000, 261: 8000,
    262: 4900, 263: 4900, 264: 4900, 265: 4900, 266: 4900, 267: 4900,
    268: 65, 269: 10, 270: 10, 271: 10, 272: 10, 273: 10,
    274: 5, 275: 4, 276: 4, 277: 4, 278: 4, 279: 4,
    # globals
    248: 255, 232: 1, 244: 2, 243: 1, 247: 1, 245: 8000, 53: 4800, 229: 30,
    # battery
    201: 5600, 202: 5600, 203: 5360, 217: 5, 218: 25, 219: 10, 220: 4600,
    221: 5200, 222: 4750, 210: 140, 211: 180, 230: 80, 227: 40, 204: 312, 325: 0,
}


# --- schema ----------------------------------------------------------------------
def test_settings_schema_sections_and_types():
    schema = _profile().settings_schema().as_dict()
    sections = {s["key"]: s for s in schema["sections"]}
    assert set(sections) == {"globals", "timer_slots", "battery"}

    timer = sections["timer_slots"]
    assert timer["repeating"] is True and timer["count"] == 6
    fkeys = {f["key"]: f for f in timer["fields"]}
    assert fkeys["start_time"]["type"] == "time"
    assert fkeys["power_w"]["type"] == "number" and fkeys["power_w"]["unit"] == "W"
    assert fkeys["charge_from_grid"]["type"] == "bool"

    wm = next(f for f in sections["globals"]["fields"] if f["key"] == "work_mode")
    assert wm["type"] == "enum"
    assert {"value": 2, "label": "Zero export to CT"} in wm["options"]


def test_settings_blocks_cover_addresses():
    covered = {a for b in _profile().settings_blocks() for a in range(b.start, b.start + b.count)}
    assert {250, 255, 268, 274, 244, 203, 210, 204}.issubset(covered)


# --- read_settings decode --------------------------------------------------------
def test_read_settings_decodes_all_sections():
    out = _profile().read_settings(_RAW)

    g = out["globals"]
    assert g["timer_enabled"] is True          # 255 & 0x01
    assert g["grid_charge"] is True
    assert g["work_mode"] == 2                  # enum machine value
    assert g["solar_export"] is True           # 1 & 0x01
    assert g["max_sell_power_w"] == 8000

    slots = out["timer_slots"]
    assert len(slots) == 6
    assert slots[0]["start_time"] == "00:05" and slots[1]["start_time"] == "05:55"
    assert slots[0]["target_soc_pct"] == 65 and slots[1]["target_soc_pct"] == 10
    assert slots[0]["charge_from_grid"] is True and slots[1]["charge_from_grid"] is False
    assert slots[0]["power_w"] == 8000

    b = out["battery"]
    assert b["float_voltage_v"] == 53.6 and b["absorption_voltage_v"] == 56.0
    assert b["max_charge_current_a"] == 140 and b["max_discharge_current_a"] == 180
    assert b["battery_capacity_ah"] == 312


def test_read_settings_absent_register_is_none():
    out = _profile().read_settings({})  # nothing supplied
    assert out["battery"]["float_voltage_v"] is None
    assert out["timer_slots"][0]["start_time"] is None


# --- dummy ------------------------------------------------------------------------
def test_dummy_settings_schema_and_values():
    p = DummyProfile()
    assert p.settings_schema() is not None
    vals = p.read_settings({})
    assert vals["globals"]["work_mode"] == 2
    assert [s["start_time"] for s in vals["timer_slots"]] == \
        ["00:05", "05:55", "09:00", "13:00", "17:00", "21:00"]
    assert vals["timer_slots"][0]["charge_from_grid"] is True


# --- Device wiring ----------------------------------------------------------------
class _FakeTransport:
    def __init__(self, values):
        self._v = values

    async def connect(self):  # pragma: no cover
        return None

    async def read_registers(self, start, count, table="holding"):
        return [self._v.get(start + i, 0) for i in range(count)]

    async def write_registers(self, start, values):  # pragma: no cover
        return None

    async def close(self):  # pragma: no cover
        return None


async def test_device_read_settings_via_transport():
    dev = Device("inv", _FakeTransport(_RAW), _profile(), clock=system_clock)
    assert dev.has_settings is True
    out = await dev.read_settings()
    assert out["timer_slots"][0]["start_time"] == "00:05"
    assert out["globals"]["work_mode"] == 2


async def test_dummy_device_read_settings_no_wire():
    dev = Device("dummy", NullTransport(), DummyProfile(), clock=system_clock)
    assert dev.has_settings is True
    out = await dev.read_settings()
    assert out["globals"]["grid_charge"] is True
