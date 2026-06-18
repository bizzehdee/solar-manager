"""DummyProfile + NullTransport — a built-in fake inverter (plan.md §4).

Needs no hardware and no wiring. Generates realistic, time-of-day-aware synthetic
readings (solar bell-curve PV, plausible load, battery charging by day / discharging
at night, occasional grid import/export) and reports the COMPLETE canonical metric set,
so every UI panel and code path is exercisable. This is the default device on a fresh
install and what tests + CI run against.

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

# Synthetic system shape (a believable ~6.5 kWp / 8 kW / 16 kWh home rig).
_PV_PEAK_W = 6500.0
_RATED_W = 8000.0
_BATT_CAPACITY_WH = 16000.0
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
    """Synthesizes the full canonical metric set from the current time."""

    vendor = "dummy"

    def __init__(self, *, clock: Clock = system_clock, seed: int = 0) -> None:
        self._clock = clock
        self._seed = seed
        self._settings = self._initial_settings()  # mutable: control writes apply in-memory
        self._clock_offset_s = 95.0  # synthetic RTC drift (inverter ~95 s ahead) until synced

    # --- DeviceProfile protocol -------------------------------------------------
    def register_blocks(self) -> list[RegBlock]:
        return []  # synthesizes directly; no wire reads

    def capabilities(self) -> set[str]:
        return set(ALL_METRICS)

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(
            vendor="dummy",
            model="Simulated Inverter",
            serial="DUMMY-0001",
            firmware={"protocol": "sim", "mcu": "sim", "comm": "sim"},
            ratings={"ac_power_w": _RATED_W, "battery_wh": _BATT_CAPACITY_WH, "mppt_count": 2},
        )

    def decode(self, raw: Mapping[int, int]) -> dict[str, MetricValue]:  # raw ignored
        return self.synthesize(self._clock())

    # --- RTC / clock sync (Phase 8 / T097) — synthesised + writable in-memory --------
    clock_syncable = True

    def clock_blocks(self) -> list[RegBlock]:
        return []  # synthesises its clock; no wire reads

    def read_clock(self, raw: Mapping[int, int]):  # raw ignored
        """The inverter's RTC: system time plus the (drifting) offset, so the Now/Control
        UI shows a non-zero drift until synced."""
        from datetime import timedelta

        return self._clock() + timedelta(seconds=self._clock_offset_s)

    def set_clock(self, dt) -> None:
        """Sync: clear the drift so the inverter clock matches system time."""
        self._clock_offset_s = 0.0

    # --- settings (read-only display, Phase 5; write path arrives in Phase 6/T072) ---
    def settings_blocks(self) -> list[RegBlock]:
        return []  # synthesizes settings directly; no wire reads

    def settings_schema(self) -> SettingsSchema:
        """The full settings surface, grouped to mirror the inverter's own menus so the
        Control page's 2-column layout is exercisable. Read-only where the real inverter
        exposes a value it won't let you set over Modbus (grid type / grid frequency)."""
        return SettingsSchema([
            # Grid: type & frequency are read-only; the voltage limits are writable.
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
                FieldSpec("grid_voltage_high_v", "Grid voltage high", "number", unit="V"),
                FieldSpec("grid_voltage_low_v", "Grid voltage low", "number", unit="V"),
            ]),
            Section("battery_type", "Battery type", [
                FieldSpec("battery_type", "Battery type", "enum",
                          options=[{"value": 0, "label": "Lithium"}, {"value": 1, "label": "AGM"}]),
                FieldSpec("lithium_protocol", "Lithium protocol", "enum",
                          options=[{"value": 0, "label": "CAN"}, {"value": 1, "label": "RS485"}]),
                FieldSpec("battery_operation", "Battery operation", "enum",
                          options=[{"value": 0, "label": "Voltage"},
                                   {"value": 1, "label": "State of charge"},
                                   {"value": 2, "label": "None"}]),
                FieldSpec("battery_capacity_ah", "Battery capacity", "number", unit="Ah", min=0, max=2000),
            ]),
            Section("battery_charging", "Battery charging", [
                FieldSpec("max_charge_current_a", "Max charge current", "number", unit="A", min=0, max=300),
                FieldSpec("max_discharge_current_a", "Max discharge current", "number", unit="A", min=0, max=300),
                FieldSpec("float_voltage_v", "Float voltage", "number", unit="V", min=40, max=60),
                FieldSpec("absorption_voltage_v", "Absorption voltage", "number", unit="V", min=40, max=60),
            ]),
            Section("work_mode", "Work mode", [
                FieldSpec("timer_enabled", "Timer enabled", "bool"),
                FieldSpec("grid_charge", "Grid charge", "bool"),
                FieldSpec("shutdown_soc_pct", "Output shutdown capacity", "number", unit="%", min=0, max=100),
                FieldSpec("low_soc_pct", "Stop discharge capacity", "number", unit="%", min=0, max=100),
                FieldSpec("start_grid_charge_soc_pct", "Start grid charge capacity", "number", unit="%", min=0, max=100),
            ]),
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
            ]),
            Section("aux_gen", "Aux / Generator", [
                FieldSpec("generator_connected_to_grid", "Generator on grid input", "bool"),
                FieldSpec("gen_start_soc_pct", "Generator start capacity", "number", unit="%", min=0, max=100),
                FieldSpec("gen_stop_soc_pct", "Generator stop capacity", "number", unit="%", min=0, max=100),
                FieldSpec("gen_max_run_time_h", "Generator max run time", "number", unit="h", min=0, max=24),
            ]),
            Section("timer_slots", "Work-mode timer", [
                FieldSpec("start_time", "Start time", "time"),
                FieldSpec("power_w", "Power", "number", unit="W", min=0, max=8000),
                FieldSpec("target_soc_pct", "Target SoC", "number", unit="%", min=0, max=100),
                FieldSpec("charge_from_grid", "Charge from grid", "bool"),
            ], repeating=True, count=6),
        ])

    @staticmethod
    def _initial_settings() -> dict:
        """Synthesized current settings — the validated cheap-night-rate plan from the real
        SG05LP1 (grid-charge to 65% overnight, 10% floor by day)."""
        soc = [65, 10, 10, 10, 10, 10]
        starts = ["00:05", "05:55", "09:00", "13:00", "17:00", "21:00"]
        return {
            "grid": {"grid_type": 0, "grid_frequency": 0, "grid_voltage_high_v": 264.0, "grid_voltage_low_v": 184.0},
            "battery_type": {"battery_type": 0, "lithium_protocol": 0, "battery_operation": 1, "battery_capacity_ah": 312.0},
            "battery_charging": {"max_charge_current_a": 140.0, "max_discharge_current_a": 180.0,
                                 "float_voltage_v": 53.6, "absorption_voltage_v": 56.0},
            "work_mode": {"timer_enabled": True, "grid_charge": True, "shutdown_soc_pct": 5.0,
                          "low_soc_pct": 10.0, "start_grid_charge_soc_pct": 30.0},
            "work_mode_detail": {"work_mode": 2, "solar_export": False, "energy_pattern": 1,
                                 "max_sell_power_w": 8000.0, "max_solar_power_w": 4800.0},
            "aux_gen": {"generator_connected_to_grid": False, "gen_start_soc_pct": 20.0,
                        "gen_stop_soc_pct": 80.0, "gen_max_run_time_h": 8.0},
            "timer_slots": [
                {"start_time": starts[i], "power_w": 8000.0, "target_soc_pct": soc[i],
                 "charge_from_grid": i == 0}
                for i in range(6)
            ],
        }

    def read_settings(self, raw: Mapping[int, int]) -> dict:  # raw ignored
        """Current in-memory settings (a deep copy so callers can't mutate our state)."""
        return copy.deepcopy(self._settings)

    def apply_settings(self, section_key: str, values: Mapping[str, Any], *, index: int | None = None) -> None:
        """Apply validated settings to the in-memory store (Phase 6 / T074). The dummy has
        no registers, so writes are mirrored directly into the state `read_settings` returns
        — exercising the full validate→write→read-back→verify flow with zero risk.
        `values` is assumed already validated by control.validate_settings."""
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

        # --- PV: a sine bell-curve between sunrise and sunset ---
        if _SUNRISE_H <= hour <= _SUNSET_H:
            day_frac = (hour - _SUNRISE_H) / (_SUNSET_H - _SUNRISE_H)
            pv_total = _PV_PEAK_W * math.sin(math.pi * day_frac) * jitter(0.06)
        else:
            pv_total = 0.0
        pv_total = _clamp(pv_total, 0.0, _RATED_W)
        pv1 = pv_total * 0.55
        pv2 = pv_total * 0.45

        # --- Load: base + morning & evening peaks ---
        load = 350.0
        load += 1800.0 * math.exp(-(((hour - 7.5) / 1.1) ** 2))   # breakfast
        load += 2600.0 * math.exp(-(((hour - 19.0) / 1.6) ** 2))  # dinner/evening
        load *= jitter(0.10)

        # --- SoC: low before dawn, climbs through the day, falls overnight ---
        soc = 55.0 - 28.0 * math.cos(math.pi * _clamp((hour - 4.0) / 12.0, 0.0, 1.0))
        soc = _clamp(soc, 12.0, 98.0)

        # --- Energy balance: PV first to load, surplus charges battery then exports ---
        surplus = pv_total - load
        if surplus >= 0:
            batt_power = _clamp(surplus, 0.0, 4000.0)        # +charge
            grid_power = -(surplus - batt_power)             # surplus beyond charge -> export (-)
        else:
            deficit = -surplus
            discharge = _clamp(deficit, 0.0, 5000.0)
            batt_power = -discharge                          # -discharge
            grid_power = deficit - discharge                 # unmet deficit -> import (+)

        batt_voltage = 51.2 + (soc - 50.0) * 0.04
        batt_current = batt_power / batt_voltage if batt_voltage else 0.0

        # --- Daily energy counters: integrate-ish from start of day to now ---
        today_pv = max(0.0, _PV_PEAK_W * 0.45 * max(0.0, hour - _SUNRISE_H)) / 1.0
        today_load = (load * 0.5 + 600.0) * hour
        net_to_grid = max(0.0, -grid_power)
        net_from_grid = max(0.0, grid_power)

        metrics: dict[str, MetricValue] = {
            "pv_power_w": round(pv_total, 1),
            "pv1_power_w": round(pv1, 1),
            "pv1_voltage_v": round(330.0 * jitter(0.02) if pv1 > 10 else 0.0, 1),
            "pv1_current_a": round(pv1 / 330.0, 2) if pv1 > 10 else 0.0,
            "pv2_power_w": round(pv2, 1),
            "pv2_voltage_v": round(325.0 * jitter(0.02) if pv2 > 10 else 0.0, 1),
            "pv2_current_a": round(pv2 / 325.0, 2) if pv2 > 10 else 0.0,
            "battery_soc_pct": round(soc, 1),
            "battery_power_w": round(batt_power, 1),
            "battery_voltage_v": round(batt_voltage, 2),
            "battery_current_a": round(batt_current, 2),
            "battery_temp_c": round(21.0 * jitter(0.03), 1),
            "grid_power_w": round(grid_power, 1),
            "grid_voltage_v": round(241.0 * jitter(0.01), 1),
            "grid_frequency_hz": round(50.0 * jitter(0.001), 2),
            "load_power_w": round(load, 1),
            "inverter_temp_c": round(34.0 + pv_total / 800.0, 1),
            "inverter_status": "running" if pv_total > 10 or abs(batt_power) > 10 else "standby",
            "today_pv_wh": round(today_pv, 0),
            "today_load_wh": round(today_load, 0),
            "today_grid_import_wh": round(net_from_grid * hour, 0),
            "today_grid_export_wh": round(net_to_grid * hour, 0),
            "today_batt_charge_wh": round(max(0.0, batt_power) * hour, 0),
            "today_batt_discharge_wh": round(max(0.0, -batt_power) * hour, 0),
            "run_state": "on_grid",
            "battery_soh_pct": 99.0,
            "battery_cycles": 128,
        }
        return metrics
