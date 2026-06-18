"""Phase 6 write-back logic (plan.md §12; tasks T073–T075).

The high-risk path, unit-tested hardest (§21): schema validation, register encode with
read-modify-write + the u16 range guard, the write allow-list, etag/If-Match concurrency,
and read-back verification — exercised against the dummy (in-memory) AND a YAML profile over
a fake register file (encode → allow-listed write → re-read), with zero hardware.
"""

from __future__ import annotations

import pytest

from app import control
from app.control import (
    NotWritableError,
    SettingsValidationError,
    StaleSettingsError,
    contiguous_runs,
    settings_etag,
    validate_settings,
    verify_settings,
)
from app.devices.base import Device
from app.devices.dummy import DummyProfile, NullTransport
from app.devices.yaml_profile import ModbusYamlProfile


# --- fake register transport (no hardware) --------------------------------------
class FakeRegisters:
    """An in-memory holding-register file implementing the Transport protocol, so the
    YAML-profile write path (encode → write → read-back) runs with no serial port."""

    def __init__(self, initial: dict[int, int] | None = None) -> None:
        self.regs: dict[int, int] = dict(initial or {})
        self.writes: list[tuple[int, list[int]]] = []

    async def connect(self) -> None:
        return None

    async def read_registers(self, start: int, count: int, table: str = "holding") -> list[int]:
        return [self.regs.get(start + i, 0) for i in range(count)]

    async def write_registers(self, start, values) -> None:
        values = list(values)
        self.writes.append((start, values))
        for i, v in enumerate(values):
            self.regs[start + i] = v & 0xFFFF

    async def close(self) -> None:
        return None


def _dummy_device() -> Device:
    return Device("dummy", NullTransport(), DummyProfile())


def _yaml_device(initial: dict[int, int] | None = None) -> tuple[Device, FakeRegisters]:
    transport = FakeRegisters(initial)
    profile = ModbusYamlProfile.from_name("sunsynk-8k-sg05lp1")
    return Device("inv", transport, profile), transport


# --- pure helpers ---------------------------------------------------------------
def test_settings_etag_is_stable_and_order_independent():
    a = {"globals": {"x": 1, "y": 2}}
    b = {"globals": {"y": 2, "x": 1}}
    assert settings_etag(a) == settings_etag(b)
    assert settings_etag(a) != settings_etag({"globals": {"x": 1, "y": 3}})


def test_contiguous_runs_groups_adjacent_addresses():
    assert contiguous_runs({250: 5, 251: 555, 256: 8000}) == [(250, [5, 555]), (256, [8000])]
    assert contiguous_runs({5: 1}) == [(5, [1])]
    assert contiguous_runs({}) == []


def test_verify_settings_tolerates_scale_rounding_but_flags_real_diffs():
    after = {"battery_charging": {"float_voltage_v": 53.6, "max_charge_current_a": 140.0}}
    assert verify_settings("battery_charging", {"float_voltage_v": 53.603}, None, after) == []  # within tolerance
    assert verify_settings("battery_charging", {"float_voltage_v": 54.0}, None, after) == ["float_voltage_v"]


# --- validation (§12 rule 1) ----------------------------------------------------
def _schema():
    return DummyProfile().settings_schema()


def test_validate_rejects_unknown_section_field_and_empty():
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "nope", {"x": 1})
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "work_mode_detail", {"bogus": 1})
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "work_mode_detail", {})


def test_validate_enum_must_be_allowed_option():
    assert validate_settings(_schema(), "work_mode_detail", {"work_mode": 2}) == {"work_mode": 2}
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "work_mode_detail", {"work_mode": 9})


def test_validate_percentage_bounds_and_time_and_bool():
    assert validate_settings(_schema(), "timer_slots", {"target_soc_pct": 80}, index=0) == {"target_soc_pct": 80}
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "timer_slots", {"target_soc_pct": 150}, index=0)
    assert validate_settings(_schema(), "timer_slots", {"start_time": "5:5"}, index=0) == {"start_time": "05:05"}
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "timer_slots", {"start_time": "25:00"}, index=0)
    assert validate_settings(_schema(), "work_mode", {"grid_charge": 1}) == {"grid_charge": True}


def test_validate_repeating_index_required_and_bounded():
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "timer_slots", {"target_soc_pct": 50})  # no index
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "timer_slots", {"target_soc_pct": 50}, index=99)
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "work_mode", {"grid_charge": True}, index=0)  # not repeating


# --- apply against the dummy (in-memory, §12 dummy-first) ------------------------
@pytest.mark.asyncio
async def test_apply_globals_against_dummy_verifies_readback():
    device = _dummy_device()
    before = await device.read_settings()
    assert before["work_mode_detail"]["max_sell_power_w"] == 8000.0

    result = await control.apply_settings(device, "work_mode_detail", {"max_sell_power_w": 5000})
    assert result.ok and result.mismatches == []
    assert result.after["work_mode_detail"]["max_sell_power_w"] == 5000
    assert result.changes == {"max_sell_power_w": {"old": 8000.0, "new": 5000}}
    assert result.etag == settings_etag(result.after)
    # Persisted in-memory: a fresh read reflects it.
    assert (await device.read_settings())["work_mode_detail"]["max_sell_power_w"] == 5000


@pytest.mark.asyncio
async def test_apply_timer_slot_only_touches_that_slot():
    device = _dummy_device()
    result = await control.apply_settings(device, "timer_slots", {"target_soc_pct": 80}, index=2)
    assert result.ok
    after = await device.read_settings()
    assert after["timer_slots"][2]["target_soc_pct"] == 80
    assert after["timer_slots"][0]["target_soc_pct"] == 65  # slot 0 untouched


@pytest.mark.asyncio
async def test_apply_if_match_concurrency():
    device = _dummy_device()
    current = settings_etag(await device.read_settings())
    with pytest.raises(StaleSettingsError):
        await control.apply_settings(device, "work_mode", {"grid_charge": False}, if_match="stale")
    # Correct etag goes through.
    result = await control.apply_settings(device, "work_mode", {"grid_charge": False}, if_match=current)
    assert result.ok and result.after["work_mode"]["grid_charge"] is False


# --- apply over a YAML profile + fake registers (encode + allow-list) ------------
@pytest.mark.asyncio
async def test_apply_yaml_encodes_writes_and_reads_back():
    device, transport = _yaml_device()
    result = await control.apply_settings(device, "work_mode_detail", {"max_sell_power_w": 4800})
    assert result.ok
    assert transport.regs[245] == 4800  # confirmed addr for max_sell_power_w
    assert result.after["work_mode_detail"]["max_sell_power_w"] == 4800


@pytest.mark.asyncio
async def test_apply_yaml_read_modify_write_preserves_neighbour_bits():
    # Slot 0 'charge_from_grid' (bit0) and 'mode' (bits2-4) share register 274. Setting one
    # must not clobber the other.
    device, transport = _yaml_device({274: 0b11000})  # mode bits set, grid-charge off
    result = await control.apply_settings(device, "timer_slots", {"charge_from_grid": True}, index=0)
    assert result.ok
    assert transport.regs[274] & 0x01 == 1          # grid-charge now on
    assert transport.regs[274] & 0x1C == 0b11000    # mode bits preserved


@pytest.mark.asyncio
async def test_apply_only_writes_allow_listed_registers():
    device, transport = _yaml_device()
    allowed = device.profile.writable_addresses()
    await control.apply_settings(device, "timer_slots", {"start_time": "06:30", "power_w": 7000}, index=1)
    written = {addr for start, vals in transport.writes for addr in range(start, start + len(vals))}
    assert written and written <= allowed  # never writes outside the allow-list


@pytest.mark.asyncio
async def test_encode_u16_range_guard_rejects_overflow():
    device, _ = _yaml_device()
    # 70000 is above both the explicit YAML max (16000) and the u16 register range — either
    # the bounds check or the encoder will reject it (§12 safety).
    with pytest.raises(control.SettingsError):
        await control.apply_settings(device, "work_mode_detail", {"max_solar_power_w": 70000})


# --- read-back mismatch ⇒ rollback signal (§12 rule 4) --------------------------
class _StubbornProfile:
    """A writable profile whose writes never 'take' — to exercise the mismatch/rollback path."""

    vendor = "stub"

    def settings_schema(self):
        return DummyProfile().settings_schema()

    def settings_blocks(self):
        return []

    def read_settings(self, raw):
        return {"work_mode": {"grid_charge": True}}

    def apply_settings(self, section, values, *, index=None):
        return None  # ignores the write


@pytest.mark.asyncio
async def test_apply_reports_mismatch_when_readback_disagrees():
    device = Device("stub", NullTransport(), _StubbornProfile())
    result = await control.apply_settings(device, "work_mode", {"grid_charge": False})
    assert result.ok is False
    assert result.mismatches == ["grid_charge"]


def test_not_writable_error_carries_addrs():
    err = NotWritableError([99, 100])
    assert err.addrs == [99, 100]


# --- read-only fields (writable: false) -----------------------------------------
def test_validate_rejects_writing_a_readonly_field():
    # The dummy's Grid section is read-only (grid_type / grid_frequency).
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "grid", {"grid_type": 1})


@pytest.mark.asyncio
async def test_apply_readonly_field_is_refused_on_dummy():
    device = _dummy_device()
    with pytest.raises(SettingsValidationError):
        await control.apply_settings(device, "grid", {"grid_frequency": 1})
    # Read-only value is unchanged + still displayed.
    assert (await device.read_settings())["grid"]["grid_type"] == 0


def test_readonly_fields_excluded_from_write_allow_list():
    # A profile with one read-only and one writable field in a section.
    spec = {
        "vendor": "x",
        "settings": {
            "grid": {
                "grid_type": {"addr": 500, "type": "enum", "values": {0: "single_phase"}, "writable": False},
                "grid_voltage_high_v": {"addr": 501, "type": "u16"},
            }
        },
    }
    profile = ModbusYamlProfile(spec)
    allowed = profile.writable_addresses()
    assert 501 in allowed and 500 not in allowed  # read-only addr excluded
    # …but the read still covers it (so it's displayed).
    read = {a for b in profile.settings_blocks() for a in range(b.start, b.start + b.count)}
    assert 500 in read and 501 in read


# --- validation helper edge cases (typed coercion + bounds + time) --------------
def _yaml_schema():
    return ModbusYamlProfile.from_name("sunsynk-8k-sg05lp1").settings_schema()


def test_validate_bool_rejects_non_boolean():
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "work_mode", {"grid_charge": 5})


def test_validate_enum_rejects_unparseable():
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "work_mode_detail", {"work_mode": "abc"})


def test_validate_rejects_boolean_for_numeric_fields():
    # A bool must not sneak in where an enum/number is expected (bool is an int subclass).
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "work_mode_detail", {"work_mode": True})
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "battery_charging", {"float_voltage_v": True})


def test_validate_number_coerces_string_and_rejects_garbage_and_nonfinite():
    # number field accepts a numeric string…
    assert validate_settings(_schema(), "battery_charging", {"float_voltage_v": "53.6"}) == {"float_voltage_v": 53.6}
    # …but rejects non-numeric strings, wrong types, and non-finite values.
    for bad in ("abc", [1], float("inf"), float("nan")):
        with pytest.raises(SettingsValidationError):
            validate_settings(_schema(), "battery_charging", {"float_voltage_v": bad})


def test_validate_number_bounds_both_directions():
    with pytest.raises(SettingsValidationError):  # below min (0)
        validate_settings(_schema(), "timer_slots", {"target_soc_pct": -5}, index=0)
    with pytest.raises(SettingsValidationError):  # above max (8000)
        validate_settings(_schema(), "timer_slots", {"power_w": 9000}, index=0)


def test_validate_int_field_coerces_float_and_string():
    # The YAML timer 'mode' is a bits→int field; accepts an int-valued float and a string.
    assert validate_settings(_yaml_schema(), "timer_slots", {"mode": 2.0}, index=0) == {"mode": 2}
    assert validate_settings(_yaml_schema(), "timer_slots", {"mode": "3"}, index=0) == {"mode": 3}
    with pytest.raises(SettingsValidationError):
        validate_settings(_yaml_schema(), "timer_slots", {"mode": "x"}, index=0)


def test_yaml_writable_numeric_fields_have_bounds():
    """Every writable number/int field in the YAML profile must declare min and max so
    the API never accepts physically-dangerous values (§12 rule 1)."""
    schema = _yaml_schema()
    missing = []
    for section in schema.sections:
        for f in section.fields:
            if f.writable and f.type in ("number", "int"):
                if f.min is None or f.max is None:
                    missing.append(f"{section.key}.{f.key}")
    assert missing == [], f"writable numeric fields missing bounds: {missing}"


def test_validate_time_formats():
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "timer_slots", {"start_time": "12:30:00"}, index=0)
    with pytest.raises(SettingsValidationError):
        validate_settings(_schema(), "timer_slots", {"start_time": "ab:cd"}, index=0)


# --- not-writable device --------------------------------------------------------
class _ReadOnlyProfile:
    vendor = "ro"

    def settings_schema(self):
        return None

    def register_blocks(self):
        return []

    def decode(self, raw):
        return {}

    def capabilities(self):
        return set()


@pytest.mark.asyncio
async def test_apply_on_non_writable_device_raises():
    device = Device("ro", NullTransport(), _ReadOnlyProfile())
    with pytest.raises(control.SettingsError):
        await control.apply_settings(device, "work_mode", {"grid_charge": False})


class _RogueProfile:
    """A register profile whose encoder emits an address OUTSIDE its own allow-list — the
    case the allow-list guard exists to catch (§12: no arbitrary-address writes)."""

    vendor = "rogue"

    def settings_schema(self):
        return DummyProfile().settings_schema()

    def settings_blocks(self):
        return []

    def read_settings(self, raw):
        return {"work_mode": {"grid_charge": True}}

    def writable_addresses(self):
        return {232}  # the legitimate grid_charge register

    def encode_settings(self, section, values, raw, *, index=None):
        return {9999: 1}  # but the encoder targets a forbidden address


@pytest.mark.asyncio
async def test_apply_rejects_write_outside_allow_list():
    device = Device("rogue", FakeRegisters(), _RogueProfile())
    with pytest.raises(NotWritableError):
        await control.apply_settings(device, "work_mode", {"grid_charge": False})
