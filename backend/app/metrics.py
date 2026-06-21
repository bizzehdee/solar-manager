"""The canonical metric vocabulary (plan.md §4).

Profiles translate raw registers -> these brand-independent keys; everything above
the driver only ever sees these. Signs are normalized BEFORE storage, never in the UI.
Missing != zero — unreported metrics are simply absent.

The vocabulary is phase-agnostic: per-phase suffixes (e.g. `grid_power_l1_w`) collapse
to the unsuffixed total for single-phase rigs.
"""

from __future__ import annotations

# Mandatory core — power / SoC / voltages. Most profiles report these.
CORE_METRICS: frozenset[str] = frozenset(
    {
        "pv_power_w",          # sum of MPPTs
        "pv1_power_w",
        "pv1_voltage_v",
        "pv1_current_a",
        "pv2_power_w",
        "pv2_voltage_v",
        "pv2_current_a",
        "battery_soc_pct",
        "battery_power_w",     # +charge / -discharge (normalized)
        "battery_voltage_v",
        "battery_current_a",
        "battery_temp_c",
        "grid_power_w",        # +import / -export (normalized)
        "grid_voltage_v",
        "grid_frequency_hz",
        "load_power_w",
        "inverter_temp_c",
        "inverter_status",
    }
)

# Daily energy counters (Wh).
ENERGY_METRICS: frozenset[str] = frozenset(
    {
        "today_pv_wh",
        "today_load_wh",
        "today_grid_import_wh",
        "today_grid_export_wh",
        "today_batt_charge_wh",
        "today_batt_discharge_wh",
    }
)

# Optional — faults, health, run-state. Capability-gated (plan.md §16/§17).
OPTIONAL_METRICS: frozenset[str] = frozenset(
    {
        "run_state",
        "inverter_fault_codes",
        "inverter_warning_codes",
        "battery_soh_pct",
        "battery_cycles",
        "battery_capacity_ah_measured",
        # Hybrid-inverter extras (reported by some devices, e.g. via the Solar Assistant bridge).
        "ac_output_voltage_v",
        "ac_output_frequency_hz",
        "load_pct",
        "generator_power_w",
        "grid_power_ct_w",          # grid power at the CT clamp (utility tie point)
        "grid_power_ld_w",          # grid power on the load side
        "load_power_essential_w",
        "load_power_non_essential_w",
    }
)

# Derived (calculated) metrics — computed from the snapshot by `derived.derive_metrics` and merged
# into each Reading by the poller (task L16). Canonical, so charts/cards/gauges treat them uniformly.
DERIVED_METRICS: frozenset[str] = frozenset(
    {
        # Snapshot-derived ratios (derived.derive_metrics).
        "self_consumption_pct",
        "self_sufficiency_pct",
        "round_trip_efficiency_pct",
        # Stats/DB-derived (derived_stats.DerivedStatsService).
        "savings",
        "co2_avoided_kg",
        "peak_pv_w",
    }
)

ALL_METRICS: frozenset[str] = CORE_METRICS | ENERGY_METRICS | OPTIONAL_METRICS | DERIVED_METRICS
