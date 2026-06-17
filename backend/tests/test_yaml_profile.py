"""YAML profile loading + decode (plan.md §4, §10, §21).

Decode is the #1 bug source, so it gets table-driven vectors taken from the validated
SG05LP1 scan. Single-source of register specs is the checked-in profiles/ YAML.
"""

from __future__ import annotations

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


def test_decode_signed_16bit():
    # battery_power_w: addr 190, s16. 0xFFFF -> -1
    assert _profile().decode({190: 0xFFFF})["battery_power_w"] == -1
    assert _profile().decode({190: 749})["battery_power_w"] == 749


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
