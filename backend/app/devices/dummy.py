"""DummyProfile + NullTransport — a built-in fake inverter (plan.md §4).

Needs no hardware and no wiring. Generates realistic, time-of-day-aware synthetic
readings (solar bell-curve PV, plausible load, battery charging by day / discharging
at night, occasional grid import/export) and reports the COMPLETE canonical metric set,
so every UI panel and code path is exercisable. This is the default device on a fresh
install and what tests + CI run against.

The synthetic system mirrors a real Sunsynk SYNK-8K-SG05LP1 with a 312 Ah LiFePO4
pack (~16 kWh) on a cheap-night tariff (grid-charge overnight to 65%, 10% floor by
day). Settings values match the validated register read-out from 2026-06-18.

Determinism: synthesis is a pure function of the timestamp (+ an optional seed), so a
fixed clock yields identical readings — see tests. Control (in-memory writes) is added
in Phase 6 (T074); for now the dummy is read-only.
"""

from __future__ import annotations

import copy
import math
import random
from datetime import datetime
from typing import Any, Mapping, Sequence

from ..metrics import ALL_METRICS
from ..models import DeviceInfo, MetricValue
from ..settings_schema import FieldSpec, Section, SettingsSchema
from .base import Clock, RegBlock, system_clock

# Synthetic system shape: Sunsynk SYNK-8K-SG05LP1, 312 Ah LiFePO4 pack, ~6.5 kWp.
_PV_PEAK_W = 6500.0
_RATED_W = 8000.0
_BATT_CAPACITY_WH = 16384.0   # 312 Ah × 52.5 V ≈ 16.4 kWh
_BATT_NOMINAL_V = 51.2        # LiFePO4 nominal
_SUNRISE_H = 6.0
_SUNSET_H = 20.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class NullTransport:
    """A transport that moves no bytes — pairs with synthesizing profiles."""

    async def connect(self) -> None:  # noqa: D401
        return None

    async def read_registers(self, start: int, count: int, table: str = "holding") -> list[int]:
        return [0] * count

    async def write_registers(self, start: int, values: Sequence[int]) -> None:
        return None

    async def close(self) -> None:
        return None


class DummyProfile:
    """Synthesizes the full canonical metric set from the current time.

    Identity and settings mirror a real SYNK-8K-SG05LP1 so the Control page,
    dashboard, and statistics pages all exercise realistic data paths.
    """

    vendor = "dummy"  # profile type identifier; info.vendor carries the real brand

    def __init__(self, *, clock: Clock = system_clock, seed: int = 0) -> None:
        self._clock = clock
        self._seed = seed
        self._settings = self._initial_settings()  # mutable: control writes apply in-memory
        self._clock_offset_s = 95.0  # synthetic RTC drift (inverter ~95 s ahead) until synced

    # --- DeviceProfile protocol -------------------------------------------------
    def register_blocks(self) -> list[RegBlock]:
        return []  # synthesises directly; no wire reads

    def capabilities(self) -> set[str]:
        return set(ALL_METRICS)

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(
            vendor="sunsynk",
            model="SYNK-8K-SG05LP1",
            serial="SN2406SIM1",
            firmware={"protocol": "2.1", "mcu": "5386", "comm": "e43d"},
            ratings={"ac_power_w": _RATED_W, "battery_wh": _BATT_CAPACITY_WH, "mppt_count": 2},
        )

    def decode(self, raw: Mapping[int, int]) -> dict[str, MetricValue]:  # raw ignored
        return self.synthesize(self._clock())

    # --- RTC / clock sync (Phase 8 / T097) — synthesised + writable in-memory --------
    clock_syncable = True

    def clock_blocks(self) -> list[RegBlock]:
        return []  # synthesises its clock; no wire reads

    def read_clock(self, raw: Mapping[int, int]):
        """The inverter's RTC: system time plus the (drifting) offset."""
        from datetime import timedelta
        return self._clock() + timedelta(seconds=self._clock_offset_s)

    def set_clock(self, dt) -> None:
        """Sync: clear the drift so the inverter clock matches system time."""
        self._clock_offset_s = 0.0

    # --- settings ---------------------------------------------------------------
    def settings_blocks(self) -> list[RegBlock]:
        return []  # synthesises settings directly; no wire reads

    def settings_schema(self) -> SettingsSchema:
        """Full settings surface mirroring the SYNK-8K-SG05LP1's own menus.

        Read-only fields (`writable=False`) are values the real inverter exposes over
        Modbus as observable but not settable (e.g. battery_operation when CAN BMS is
        in control). All section/field keys match the YAML profile so the Control page
        layout is fully exercisable against the dummy.
        """
        return SettingsSchema([
            # Grid: type & frequency are read-only; voltage/frequency limits are writable.
            Section("grid", "Grid", [
                FieldSpec(
                    "grid_type", "Grid type", "enum", writable=False,
                    options=[
                        {"value": 0, "label": "220/230/240V single phase"},
                        {"value": 1, "label": "120/240V two phase"},
                        {"value": 2, "label": "120/208V three phase"},
                        {"value": 3, "label": "120V single phase"},
                    ],
                ),
                FieldSpec(
                    "grid_frequency", "Grid frequency", "enum", writable=False,
                    options=[{"value": 0, "label": "50 Hz"}, {"value": 1, "label": "60 Hz"}],
                ),
                FieldSpec("grid_voltage_high_v", "Grid voltage high", "number", unit="V", min=220.0, max=270.0),
                FieldSpec("grid_voltage_low_v", "Grid voltage low", "number", unit="V", min=100.0, max=230.0),
                FieldSpec("grid_frequency_high_hz", "Grid frequency high", "number", unit="Hz", min=49.0, max=55.0),
                FieldSpec("grid_frequency_low_hz", "Grid frequency low", "number", unit="Hz", min=45.0, max=51.0),
                FieldSpec("grid_peak_shaving", "Grid peak shaving", "bool"),
                FieldSpec("grid_peak_shaving_power_w", "Grid peak shaving power", "number", unit="W", min=0, max=8000),
            ]),
            # Battery type / protocol. battery_operation is read-only: CAN BMS controls it.
            Section("battery_type", "Battery type", [
                FieldSpec("battery_type", "Battery type", "enum",
                          options=[{"value": 0, "label": "Lithium"}, {"value": 1, "label": "AGM"}]),
                FieldSpec("lithium_protocol", "Lithium protocol", "enum",
                          options=[{"value": 0, "label": "CAN"}, {"value": 1, "label": "RS485"}]),
                FieldSpec("battery_operation", "Battery operation", "enum", writable=False,
                          options=[{"value": 0, "label": "Voltage"},
                                   {"value": 1, "label": "State of charge"},
                                   {"value": 2, "label": "None"}]),
                FieldSpec("battery_capacity_ah", "Battery capacity", "number", unit="Ah", min=1, max=9999),
                FieldSpec("battery_empty_voltage_v", "Battery empty voltage", "number", unit="V", writable=False),
                FieldSpec("battery_charging_efficiency_pct", "Charging efficiency", "number", unit="%", writable=False),
            ]),
            # Battery charging limits — all confirmed writable on the real unit.
            Section("battery_charging", "Battery charging", [
                FieldSpec("max_charge_current_a", "Max charge current", "number", unit="A", min=0, max=200),
                FieldSpec("max_discharge_current_a", "Max discharge current", "number", unit="A", min=0, max=200),
                FieldSpec("grid_charge_current_a", "Grid charge current", "number", unit="A", min=0, max=200),
                FieldSpec("gen_charge_current_a", "Generator charge current", "number", unit="A", min=0, max=200),
                FieldSpec("float_voltage_v", "Float voltage", "number", unit="V", min=44.0, max=60.0),
                FieldSpec("absorption_voltage_v", "Absorption voltage", "number", unit="V", min=44.0, max=60.0),
                FieldSpec("equalization_voltage_v", "Equalization voltage", "number", unit="V", min=44.0, max=60.0),
                FieldSpec("shutdown_voltage_v", "Shutdown voltage", "number", unit="V", min=40.0, max=58.0),
                FieldSpec("restart_voltage_v", "Restart voltage", "number", unit="V", min=40.0, max=58.0),
                FieldSpec("low_voltage_v", "Low voltage", "number", unit="V", min=40.0, max=58.0),
            ]),
            # Work mode — timer, charge sources, SoC thresholds.
            Section("work_mode", "Work mode", [
                FieldSpec("timer_enabled", "Timer enabled", "bool"),
                FieldSpec("grid_charge", "Grid charge", "bool"),
                FieldSpec("generator_charge", "Generator charge", "bool"),
                FieldSpec("force_generator_on", "Force generator on", "bool"),
                FieldSpec("remote_switch", "Remote switch", "bool", writable=False),
                FieldSpec("shutdown_soc_pct", "Output shutdown capacity", "number", unit="%", min=0, max=100),
                FieldSpec("low_soc_pct", "Stop discharge capacity", "number", unit="%", min=0, max=100),
                FieldSpec("restart_soc_pct", "Start discharge capacity", "number", unit="%", min=0, max=100),
                FieldSpec("start_grid_charge_soc_pct", "Start grid charge capacity", "number", unit="%", min=0, max=100),
            ]),
            # Work mode detail — energy management model.
            Section("work_mode_detail", "Work mode detail", [
                FieldSpec("work_mode", "Work mode", "enum",
                          options=[{"value": 0, "label": "Selling first"},
                                   {"value": 1, "label": "Zero export to load"},
                                   {"value": 2, "label": "Zero export to CT"}]),
                FieldSpec("solar_export", "Solar export when battery full", "bool"),
                FieldSpec("energy_pattern", "Energy pattern", "enum",
                          options=[{"value": 0, "label": "Battery first"}, {"value": 1, "label": "Load first"}]),
                FieldSpec("max_sell_power_w", "Max sell power", "number", unit="W", min=0, max=8000),
                FieldSpec("max_solar_power_w", "Max solar power", "number", unit="W", min=0, max=12000),
                FieldSpec("grid_trickle_feed_w", "Grid trickle feed", "number", unit="W", min=0, max=500),
            ]),
            # External meter / CT — reg 326 bitfield; read-only (phase/ratio config rarely changed).
            Section("meter", "Meter / CT", [
                FieldSpec("meter_phases", "Meter phases", "number", writable=False),
                FieldSpec("ct_ratio", "CT ratio", "number", writable=False),
            ]),
            # Aux / Generator port.
            Section("aux_gen", "Aux / Generator", [
                FieldSpec("auxiliary_port", "Auxiliary port", "enum",
                          options=[{"value": 0, "label": "Disabled"},
                                   {"value": 1, "label": "Output"},
                                   {"value": 2, "label": "Input"}]),
                FieldSpec("generator_connected_to_grid", "Generator on grid input", "bool", writable=False),
                FieldSpec("gen_peak_shaving", "Generator peak shaving", "bool"),
                FieldSpec("gen_peak_shaving_power_w", "Gen peak shaving power", "number", unit="W", writable=False),
                FieldSpec("gen_start_soc_pct", "Generator start capacity", "number", unit="%", min=0, max=100),
                FieldSpec("gen_stop_soc_pct", "Generator stop capacity", "number", unit="%", min=0, max=100),
                FieldSpec("gen_max_run_time_h", "Generator max run time", "number", unit="h", min=0, max=24),
                FieldSpec("gen_down_time_h", "Generator down time", "number", unit="h", min=0, max=24),
            ]),
            # Work-mode timer: 6 repeating slots.
            Section("timer_slots", "Work-mode timer", [
                FieldSpec("start_time", "Start time", "time"),
                FieldSpec("power_w", "Power", "number", unit="W", min=0, max=8000),
                FieldSpec("target_soc_pct", "Target SoC", "number", unit="%", min=0, max=100),
                FieldSpec("voltage_v", "Target voltage", "number", unit="V", min=44.0, max=60.0),
                FieldSpec("charge_from_grid", "Charge from grid", "bool"),
                FieldSpec("charge_from_gen", "Charge from generator", "bool"),
            ], repeating=True, count=6),
        ])

    @staticmethod
    def _initial_settings() -> dict:
        """Validated SYNK-8K-SG05LP1 config (cheap-night-rate plan, 2026-06-18 read-out).

        Values match the hardware register read-out exactly:
          - Grid-charge overnight (slot 1: 00:05–05:55, 65% SoC target, grid on)
          - 10% floor the rest of the day (slots 2–6, grid charge off)
          - Zero-export-to-CT, load-first, max sell 8 kW, max solar 4.8 kW
        """
        starts = ["00:05", "05:55", "09:00", "13:00", "17:00", "21:00"]
        soc = [65, 10, 10, 10, 10, 10]
        return {
            "grid": {
                "grid_type": 0,              # 220/230/240V single phase
                "grid_frequency": 0,         # 50 Hz
                "grid_voltage_high_v": 254.0,
                "grid_voltage_low_v": 184.0,
                "grid_frequency_high_hz": 51.0,
                "grid_frequency_low_hz": 49.0,
                "grid_peak_shaving": False,
                "grid_peak_shaving_power_w": 3000.0,
            },
            "battery_type": {
                "battery_type": 0,           # lithium
                "lithium_protocol": 0,       # CAN
                "battery_operation": 1,      # state-of-charge mode (controlled by BMS)
                "battery_capacity_ah": 312.0,
                "battery_empty_voltage_v": 47.0,
                "battery_charging_efficiency_pct": 95.0,
            },
            "battery_charging": {
                "max_charge_current_a": 140.0,    # confirmed [210]=140
                "max_discharge_current_a": 180.0, # confirmed [211]=180
                "grid_charge_current_a": 80.0,    # confirmed [230]=80
                "gen_charge_current_a": 40.0,     # confirmed [227]=40
                "float_voltage_v": 53.6,          # confirmed [203]=5360
                "absorption_voltage_v": 56.0,     # confirmed [202]=5600
                "equalization_voltage_v": 56.0,   # confirmed [201]=5600
                "shutdown_voltage_v": 46.0,       # confirmed [220]=4600
                "restart_voltage_v": 48.0,        # approximate [221]=4800 (not in validated _RAW but typical)
                "low_voltage_v": 47.5,            # confirmed [222]=4750
            },
            "work_mode": {
                "timer_enabled": True,        # [248] bit0=1
                "grid_charge": True,          # [232] bit0=1
                "generator_charge": False,
                "force_generator_on": False,
                "remote_switch": True,        # [20]=0xFF observed (all control bits on)
                "shutdown_soc_pct": 5.0,      # [217]=5
                "low_soc_pct": 10.0,          # [219]=10
                "restart_soc_pct": 25.0,      # [218]=25
                "start_grid_charge_soc_pct": 30.0,  # [229]=30
            },
            "work_mode_detail": {
                "work_mode": 2,              # Zero export to CT — confirmed [244]=2
                "solar_export": False,       # [247] bit0=0 (no export when full)
                "energy_pattern": 1,         # Load first — confirmed [243]=1
                "max_sell_power_w": 8000.0,  # confirmed [245]=8000
                "max_solar_power_w": 4800.0, # confirmed [53]=4800
                "grid_trickle_feed_w": 0.0,  # [206]=0 (no trickle)
            },
            "meter": {
                "meter_phases": 1,   # single-phase meter
                "ct_ratio": 1,
            },
            "aux_gen": {
                "auxiliary_port": 0,          # disabled
                "generator_connected_to_grid": False,
                "gen_peak_shaving": False,
                "gen_peak_shaving_power_w": 0.0,
                "gen_start_soc_pct": 20.0,
                "gen_stop_soc_pct": 80.0,
                "gen_max_run_time_h": 8.0,
                "gen_down_time_h": 4.0,
            },
            "timer_slots": [
                {
                    "start_time": starts[i],
                    "power_w": 8000.0,
                    "target_soc_pct": soc[i],
                    "voltage_v": 49.0,         # [262..267]=4900 raw → 49.00 V (unused in SoC mode)
                    "charge_from_grid": i == 0,  # slot 1 only: [274]=5 (bit0=1)
                    "charge_from_gen": False,
                }
                for i in range(6)
            ],
        }

    def read_settings(self, raw: Mapping[int, int]) -> dict:  # raw ignored
        """Current in-memory settings (deep copy so callers can't mutate our state)."""
        return copy.deepcopy(self._settings)

    def apply_settings(self, section_key: str, values: Mapping[str, Any], *, index: int | None = None) -> None:
        """Apply validated settings to the in-memory store (Phase 6 / T074)."""
        if section_key == "timer_slots":
            self._settings[section_key][index or 0].update(values)
        else:
            self._settings[section_key].update(values)

    # --- synthesis (pure function of ts; deterministic per second) --------------
    def synthesize(self, ts: datetime) -> dict[str, MetricValue]:
        rng = random.Random(hash((self._seed, int(ts.timestamp()))))
        hour = ts.hour + ts.minute / 60.0 + ts.second / 3600.0

        def jitter(frac: float) -> float:
            return 1.0 + rng.uniform(-frac, frac)

        # PV: sine bell-curve between sunrise and sunset, split 55/45 across two MPPTs.
        if _SUNRISE_H <= hour <= _SUNSET_H:
            day_frac = (hour - _SUNRISE_H) / (_SUNSET_H - _SUNRISE_H)
            pv_total = _PV_PEAK_W * math.sin(math.pi * day_frac) * jitter(0.06)
        else:
            pv_total = 0.0
        pv_total = _clamp(pv_total, 0.0, _RATED_W)
        pv1 = pv_total * 0.55
        pv2 = pv_total * 0.45

        # Load: base + breakfast and dinner/evening peaks.
        load = 350.0
        load += 1800.0 * math.exp(-(((hour - 7.5) / 1.1) ** 2))
        load += 2600.0 * math.exp(-(((hour - 19.0) / 1.6) ** 2))
        load *= jitter(0.10)

        # SoC: low before dawn, climbs through the day, falls overnight.
        soc = 55.0 - 28.0 * math.cos(math.pi * _clamp((hour - 4.0) / 12.0, 0.0, 1.0))
        soc = _clamp(soc, 12.0, 98.0)

        # Energy balance: PV first to load; surplus charges battery then exports.
        surplus = pv_total - load
        if surplus >= 0:
            batt_power = _clamp(surplus, 0.0, 4000.0)   # +charge
            grid_power = -(surplus - batt_power)          # export (-)
        else:
            deficit = -surplus
            discharge = _clamp(deficit, 0.0, 5000.0)
            batt_power = -discharge                       # -discharge
            grid_power = deficit - discharge              # import (+)

        batt_voltage = _BATT_NOMINAL_V + (soc - 50.0) * 0.04
        batt_current = batt_power / batt_voltage if batt_voltage else 0.0

        # Inverter output on single-phase 230 V.
        inv_voltage = 230.0 * jitter(0.005)
        inv_current = load / inv_voltage if inv_voltage else 0.0
        inv_freq = 50.0 * jitter(0.001)

        # Grid side.
        grid_voltage = 241.0 * jitter(0.01)

        # Temperatures scale with output.
        inv_temp = 33.0 + pv_total / 500.0 + abs(batt_power) / 1000.0
        dc_temp = 28.0 + pv_total / 800.0

        # Daily energy counters: simple running-total approximation.
        today_pv = max(0.0, _PV_PEAK_W * 0.45 * max(0.0, hour - _SUNRISE_H))
        today_load = (load * 0.5 + 600.0) * hour
        net_to_grid = max(0.0, -grid_power)
        net_from_grid = max(0.0, grid_power)

        active = pv_total > 10 or abs(batt_power) > 10 or abs(grid_power) > 50

        return {
            # PV
            "pv_power_w": round(pv_total, 1),
            "pv1_power_w": round(pv1, 1),
            "pv1_voltage_v": round(330.0 * jitter(0.02) if pv1 > 10 else 0.0, 1),
            "pv1_current_a": round(pv1 / 330.0, 2) if pv1 > 10 else 0.0,
            "pv2_power_w": round(pv2, 1),
            "pv2_voltage_v": round(325.0 * jitter(0.02) if pv2 > 10 else 0.0, 1),
            "pv2_current_a": round(pv2 / 325.0, 2) if pv2 > 10 else 0.0,
            # Battery
            "battery_soc_pct": round(soc, 1),
            "battery_power_w": round(batt_power, 1),
            "battery_voltage_v": round(batt_voltage, 2),
            "battery_current_a": round(batt_current, 2),
            "battery_temp_c": round(21.0 * jitter(0.03), 1),
            # Grid
            "grid_power_w": round(grid_power, 1),
            "grid_ct_power_w": round(grid_power * jitter(0.005), 1),
            "grid_voltage_v": round(grid_voltage, 1),
            "grid_frequency_hz": round(50.0 * jitter(0.001), 2),
            # Load / inverter output
            "load_power_w": round(load, 1),
            "inverter_power_w": round(load, 1),
            "inverter_voltage_v": round(inv_voltage, 1),
            "inverter_current_a": round(inv_current, 2),
            "inverter_frequency_hz": round(inv_freq, 2),
            # Temperatures
            "inverter_temp_c": round(inv_temp, 1),
            "dc_transformer_temp_c": round(dc_temp, 1),
            # Status
            "inverter_status": "normal" if active else "standby",
            "grid_connected": 1,
            "run_state": "on_grid",
            "inverter_fault_codes": [],
            # Battery health
            "battery_soh_pct": 99.0,
            "battery_cycles": 128,
            "battery_capacity_ah_measured": round(_BATT_CAPACITY_WH / _BATT_NOMINAL_V, 0),
            # Daily energy
            "today_pv_wh": round(today_pv, 0),
            "today_load_wh": round(today_load, 0),
            "today_grid_import_wh": round(net_from_grid * hour, 0),
            "today_grid_export_wh": round(net_to_grid * hour, 0),
            "today_batt_charge_wh": round(max(0.0, batt_power) * hour, 0),
            "today_batt_discharge_wh": round(max(0.0, -batt_power) * hour, 0),
        }
