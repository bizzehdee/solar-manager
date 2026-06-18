"""YAML profile loading + decode (plan.md §4, §10, §21).

Decode is the #1 bug source, so it gets table-driven vectors taken from the validated
SG05LP1 scan. Single-source of register specs is the checked-in profiles/ YAML.
"""

from __future__ import annotations

import pytest

from app.devices.yaml_profile import ModbusYamlProfile


def _profile() -> ModbusYamlProfile:
    return ModbusYamlProfile.from_name("sunsynk-8k-sg05lp1")


def test_loads_with_inheritance():
    p = _profile()
    assert p.vendor == "sunsynk"  # child overrides deye-base's vendor
    assert p.info.model == "SYNK-8K-SG05LP1"
    assert p._word_order == "low_first"  # inherited from deye-base
    # capabilities come from the inherited deye-base metric map
    assert {"battery_soc_pct", "grid_power_w", "pv1_power_w"} <= p.capabilities()


def test_firmware_pinned_from_child():
    p = _profile()
    assert p.info.firmware == {"protocol": "2.1", "mcu": "5386", "comm": "e43d"}


def test_decode_temperature_offset():
    # battery_temp_c: addr 182, u16, scale 0.1, offset -100 -> (1220*0.1)-100 = 22.0
    out = _profile().decode({182: 1220})
    assert out["battery_temp_c"] == 22.0


def test_decode_scaled_frequency():
    # grid_frequency_hz: addr 79, scale 0.01 -> 5000 * 0.01 = 50.0
    assert _profile().decode({79: 5000})["grid_frequency_hz"] == 50.0


def test_decode_signed_16bit_normalized_to_charge_positive():
    # battery_power_w: addr 190, s16, scale -1 — raw is discharge-positive, negated to
    # the canonical +charge/-discharge. raw 749 (s16 +749 discharge) -> -749 (discharge).
    assert _profile().decode({190: 749})["battery_power_w"] == -749
    # raw 0xFFFF (s16 -1, i.e. charging) -> +1 (charge positive).
    assert _profile().decode({190: 0xFFFF})["battery_power_w"] == 1
    # raw -3968 (grid-charging capture) -> +3968 W of charge.
    assert _profile().decode({190: 61568})["battery_power_w"] == 3968


def test_battery_current_is_signed_and_normalized():
    # addr 191, s16, scale -0.01. raw 58193 = s16 -7343 (charging) -> +73.43 A charge.
    assert _profile().decode({191: 58193})["battery_current_a"] == 73.43
    # raw 1522 (discharging) -> -15.22 A.
    assert _profile().decode({191: 1522})["battery_current_a"] == -15.22


def test_decode_u32_low_word_first():
    # total_pv_wh: addr [96,97], u32 low-first, scale 100.
    # low=10000, high=1 -> 10000 | (1<<16) = 75536 ; *100 = 7553600
    out = _profile().decode({96: 10000, 97: 1})
    assert out["total_pv_wh"] == 7553600


def test_missing_register_means_absent_not_zero():
    # No registers supplied -> no metrics emitted (missing != zero, plan.md §4).
    assert _profile().decode({}) == {}


def test_register_blocks_cluster_addresses():
    blocks = _profile().register_blocks()
    assert blocks, "should produce read blocks from the metric addresses"
    assert all(b.count > 0 for b in blocks)


# --- derived PV total (plan.md §4; task T031) -------------------------------------
def test_pv_power_w_is_derived_from_mppts():
    # pv1_power_w (186) + pv2_power_w (187), summed into the canonical PV total.
    out = _profile().decode({186: 3000, 187: 2000})
    assert out["pv_power_w"] == 5000.0


def test_pv_power_w_derived_from_single_mppt():
    out = _profile().decode({186: 1500})  # only MPPT1 reported
    assert out["pv_power_w"] == 1500.0


def test_pv_power_w_absent_when_no_mppt_reported():
    # Missing != zero: no MPPT register -> no derived total.
    assert "pv_power_w" not in _profile().decode({184: 50})


def test_capabilities_include_derived_pv_total():
    assert "pv_power_w" in _profile().capabilities()


# --- fault / enum decoding (plan.md §16; task T054) -------------------------------
def test_inverter_status_enum_decodes_to_string():
    assert _profile().decode({59: 2})["inverter_status"] == "normal"
    assert _profile().decode({59: 0})["inverter_status"] == "standby"
    # Unknown enum value falls back to its number as a string.
    assert _profile().decode({59: 99})["inverter_status"] == "99"


def test_run_state_from_grid_connected():
    assert _profile().decode({194: 1})["run_state"] == "on_grid"
    assert _profile().decode({194: 0})["run_state"] == "off_grid"


def test_fault_bits_decode_to_f_codes():
    # bit 0 set -> F01; bit 0 of the 2nd register (addr 104) is global bit 16 -> F17.
    out = _profile().decode({103: 0b1, 104: 0b1, 105: 0, 106: 0})
    assert out["inverter_fault_codes"] == ["F01", "F17"]


def test_no_faults_is_empty_list():
    assert _profile().decode({103: 0, 104: 0, 105: 0, 106: 0})["inverter_fault_codes"] == []


# --- writable-settings map, validated vs the inverter screen (plan.md §4/§12; T071) -----
def test_settings_map_inherited_and_complete():
    s = _profile().settings  # inherited from deye-base
    assert {"globals", "timer_slots", "battery"} <= set(s)
    g = s["globals"]
    # work_mode enum resolved: [244] = 2 -> "Zero export to CT".
    assert g["work_mode"]["addr"] == 244
    assert g["work_mode"]["values"][2] == "zero_export_to_ct"
    # newly-confirmed global settings registers are present at their screen-validated addrs.
    assert g["energy_pattern"]["addr"] == 243 and g["energy_pattern"]["values"][1] == "load_first"
    assert g["max_sell_power_w"]["addr"] == 245
    assert g["max_solar_power_w"]["addr"] == 53
    assert g["start_grid_charge_soc_pct"]["addr"] == 229


def test_settings_battery_and_timer_addresses():
    s = _profile().settings
    b = s["battery"]
    assert b["max_charge_current_a"]["addr"] == 210 and b["max_discharge_current_a"]["addr"] == 211
    assert b["gen_charge_current_a"]["addr"] == 227
    assert b["battery_capacity_ah"]["addr"] == 204      # 312 Ah on this unit
    assert b["bms_protocol"]["values"][0] == "can"
    # 6 cyclic timer slots, base addresses match the validated screen read-out.
    t = s["timer_slots"]
    assert t["count"] == 6
    assert t["fields"]["start_time"]["base_addr"] == 250
    assert t["fields"]["target_soc_pct"]["base_addr"] == 268
    assert t["fields"]["charge_from_grid"]["base_addr"] == 274
    assert t["fields"]["charge_from_grid"]["mask"] == 0x01


# --- identity / firmware registers (task T032) ------------------------------------
def test_decode_identity_protocol_and_rated_power():
    # info: protocol addr 2 (version_be, 0x0201 -> "2.1"); rated_power_w [16,17] u32
    # low-first scale 0.1. Values from the real capture.
    ident = _profile().decode_identity({2: 0x0201, 16: 14464, 17: 1})
    assert ident["protocol"] == "2.1"
    assert ident["rated_power_w"] == 8000.0


def test_identity_blocks_cover_info_addresses():
    blocks = _profile().identity_blocks()
    covered = {a for b in blocks for a in range(b.start, b.start + b.count)}
    assert {2, 16, 17}.issubset(covered)  # protocol + rated-power registers


# --- validation against the real SG05LP1 captures (plan.md §10; tasks T002/T033) ---
def test_decodes_real_idle_capture_to_screen_values():
    """Raw registers from the real '11pm' idle scan decode to the inverter's own screen
    values. Pins decode/scale/offset against known-good real data — no hardware needed.
    At idle/night the battery covers the load (discharging), so battery_power < 0."""
    raw = {
        184: 70,      # battery_soc_pct          -> 70 %
        183: 5287,    # battery_voltage_v ×0.01   -> 52.87 V
        191: 1522,    # battery_current_a s16 ×-0.01 -> -15.22 A (discharging)
        190: 804,     # battery_power_w s16 ×-1   -> -804 W (discharging)
        182: 1220,    # battery_temp_c ×0.1 −100  -> 22.0 °C
        150: 2499,    # grid_voltage_v ×0.1       -> 249.9 V
        79: 5006,     # grid_frequency_hz ×0.01   -> 50.06 Hz
        91: 1300,     # inverter_temp_c ×0.1 −100 -> 30.0 °C
        90: 1381,     # dc_transformer_temp_c     -> 38.1 °C
        16: 14464, 17: 1,  # rated_power_w u32 low-first ×0.1 -> 8000 W
        2: 0x0201,    # protocol -> "2.1"
    }
    out = _profile().decode(raw)
    assert out["battery_soc_pct"] == 70
    assert out["battery_voltage_v"] == pytest.approx(52.87)
    assert out["battery_current_a"] == pytest.approx(-15.22)   # discharging -> negative
    assert out["battery_power_w"] == -804           # discharging -> negative
    # P = V×I holds with the shared sign: (-15.22 A)(52.87 V) ≈ -804 W
    assert out["battery_voltage_v"] * out["battery_current_a"] == pytest.approx(out["battery_power_w"], abs=5)
    assert out["battery_temp_c"] == pytest.approx(22.0)
    assert out["grid_voltage_v"] == pytest.approx(249.9)
    assert out["inverter_temp_c"] == pytest.approx(30.0)
    assert out["dc_transformer_temp_c"] == pytest.approx(38.1)
    assert _profile().decode_identity(raw)["protocol"] == "2.1"
    assert _profile().decode_identity(raw)["rated_power_w"] == 8000.0


def test_decodes_real_grid_charging_capture_signs():
    """The 'grid-charging-battery' capture — the scan that resolved T002. Grid imports
    to charge the battery: battery_power/current are NEGATIVE raw (discharge-positive
    unit) and must normalize to +charge; grid_power is +import and stays positive.
    Energy balance: grid_in ≈ load + charge + losses."""
    raw = {
        190: 61568,   # battery_power s16 -3968 -> +3968 W charge (normalized)
        191: 58193,   # battery_current s16 -7343 -> +73.43 A charge (normalized)
        183: 5404,    # battery_voltage ×0.01 -> 54.04 V
        184: 64,      # battery_soc_pct -> 64 %
        169: 4794,    # grid_power s16 -> +4794 W (importing)
        178: 471,     # load_power -> 471 W
    }
    out = _profile().decode(raw)
    assert out["battery_power_w"] == 3968           # charging -> POSITIVE (canonical)
    assert out["battery_current_a"] == pytest.approx(73.43)   # charging -> POSITIVE
    assert out["grid_power_w"] == 4794              # importing -> POSITIVE (canonical)
    assert out["load_power_w"] == 471
    # P = V×I on the normalized signs: 73.43 A × 54.04 V ≈ 3968 W
    assert out["battery_voltage_v"] * out["battery_current_a"] == pytest.approx(out["battery_power_w"], abs=5)
    # Energy balance: import ≈ load + battery charge + conversion losses.
    losses = out["grid_power_w"] - out["load_power_w"] - out["battery_power_w"]
    assert 0 < losses < 600
