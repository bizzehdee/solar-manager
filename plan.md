# SolarVolt — Implementation Plan

A **vendor-agnostic** management & statistics webapp for solar/battery systems — inverters, battery banks, and PV arrays — built so that any brand can be added via a driver/profile.
Goal: **instant**, **historical**, and **projected** (forecast) views of the system.

First hardware target is a **Sunsynk** inverter over RS485, but Sunsynk is just the first *profile*, not a baked-in assumption. Other brands (Deye, Growatt, Victron, SunSpec-compliant kit, etc.) are added by writing a profile, not by touching the core.

---

## 1. Scope & Core Requirements

| Capability | Description |
|---|---|
| **Instant** | Live readings — PV power, load, battery SoC/voltage/current/temp, grid import/export, inverter state. Polled every few seconds. |
| **Historical** | Persisted time-series. Browse/aggregate by hour/day/month. Energy totals (kWh), self-consumption, autonomy, costs. |
| **Projected** | Forecast PV generation & expected battery trajectory using [Open-Meteo](https://open-meteo.com) irradiance + system config. |
| **Pluggable transport** | Start on **RS485 (Modbus RTU)**; swap to **Solarman / SolarmanV5 Wi-Fi**, Modbus TCP, etc. later with no changes above the driver layer. |
| **Pluggable vendors** | Each brand is a **device profile** (register map + decode); adding one never touches core logic. **Sunsynk / Sol-Ark / Deye share the same Deye-built firmware & protocol**, so one profile family covers all three. Others (Growatt, Victron, generic SunSpec) added as needed. Mixed-brand systems supported (e.g. inverter from vendor A + battery BMS from vendor B). |
| **Control / write-back** | Read **and write** device settings — the inverter **work-mode timer** (per-slot time, target SoC, power, grid-charge / gen-charge toggles) + global work mode, and **BMS settings where writable** (through the inverter if it relays writes, else via a direct BMS connection — see Decision #3). Edit in the UI and push to the device. Writes are guarded (validate → confirm → write → read-back verify); see §4 & §12. |

**Deployment context (by design, not just v1):** a **single house, installed on the home LAN**. No multi-site, and **no user authentication** — it is not internet-exposed and serves one household, so there are no accounts, logins, or roles to build. This keeps the app simple; security relies on it living behind the home network (don't port-forward it). *(Control is **in scope** — see §4 & §12 — but writes are gated behind a deploy flag, validation, confirmation, and read-back verification, not behind user auth.)*

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                        Frontend (SPA)                     │
│   Instant dashboard · History charts · Forecast view      │
└───────────────▲──────────────────────────────────────────┘
                │ REST + WebSocket (JSON)
┌───────────────┴──────────────────────────────────────────┐
│                       Backend (API)                       │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ Poller   │  │ Aggregator/  │  │ Forecast service   │   │
│  │ (async)  │  │ Stats engine │  │ (Open-Meteo)       │   │
│  └────┬─────┘  └──────┬───────┘  └─────────┬──────────┘   │
│       │               │                    │              │
│  ┌────▼───────────────▼────────────────────▼──────────┐   │
│  │              Time-series store + config DB          │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Device registry — N devices, each = Transport×Profile│  │
│  │                                                       │  │
│  │   Transport (how bytes move)   Profile (what they mean)│ │
│  │   ├ ModbusRtuSource (RS485)    ├ Sunsynk/Sol-Ark/Deye  │  │
│  │   ├ SolarmanV5Source (Wi-Fi)   ├ Growatt               │  │
│  │   └ ModbusTcpSource (later)    └ SunSpec / Victron …   │  │
│  └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

The driver layer has **two orthogonal seams**:
1. **Transport** — *how* register reads happen (serial cable vs. TCP socket vs. Solarman frame).
2. **Device profile** — *what* the registers mean for a given brand/model (map, scaling, sign conventions).

Everything above the driver works only in **normalized units** and never knows the brand or the wire. A running system is a set of **devices**, each pairing one transport with one profile — so a Sunsynk inverter on RS485 and a separate battery BMS on Modbus TCP coexist, and their readings merge into one system view.

---

## 3. Technology Choices

> Recommendations, not hard requirements. Rationale given so they can be swapped.

- **Backend language: Python 3.11+** — richest Modbus/solar ecosystem (`pymodbus`, `umodbus`, `pysolarmanv5`, plus community register maps for Sunsynk/Deye/Growatt and the SunSpec models that cover many brands). Async via `asyncio`.
- **Web framework: FastAPI** — async, typed, auto OpenAPI docs, native WebSocket support for live push.
- **Time-series storage: SQLite + a rollup schema** for v1 (zero-ops, single file, perfect for one household). Abstract behind a repository so it can move to **TimescaleDB/InfluxDB** if retention/volume grows.
- **Frontend: Angular + Bootstrap 5.3 admin UI** (see §8) — fixed header/footer/sidebar shell, light & dark themes via Bootstrap's standard color system, icons via **Bootstrap Icons**, charts via **Chart.js**, live updates over WebSocket. **All frontend assets (CSS, JS, fonts, icon webfont) are bundled and self-hosted — no CDN** (the app is built for offline, in-home LAN deployment with no guaranteed internet).
- **Deployment: native install on a Raspberry Pi (primary) — fresh Ubuntu**, Docker optional. Designed to run on a Pi / small Linux box physically wired to the RS485 adapter. See §13 for both paths.

---

## 4. The Device Abstraction (most important design decision)

Two **orthogonal** seams keep the app vendor- and wire-agnostic:

- **Transport** = *how* to read/write registers (Modbus RTU over serial, SolarmanV5 over TCP, Modbus TCP…). Knows nothing about brands.
- **Profile** = *what* the registers mean for a brand/model (address map, scaling, word order, sign conventions, daily-counter registers). Knows nothing about the wire.

A **`Device`** composes one transport + one profile. A running system has a **registry of N devices** whose readings are merged into one normalized snapshot.

### Interfaces

```python
@dataclass
class Reading:
    ts: datetime
    device_id: str
    metrics: dict[str, float]   # normalized keys + SI-ish units (W, Wh, V, A, %, °C)

# How bytes move — no brand knowledge.
class Transport(Protocol):
    async def connect(self) -> None: ...
    async def read_registers(self, start: int, count: int) -> list[int]: ...
    async def write_registers(self, start: int, values: list[int]) -> None: ...  # control
    async def close(self) -> None: ...

# What the registers mean — no wire knowledge.
class DeviceProfile(Protocol):
    vendor: str                                  # "sunsynk", "deye", "sunspec"…
    def register_blocks(self) -> list[RegBlock]: ...        # what to read
    def decode(self, raw: dict[int, int]) -> dict[str, float]: ...  # -> normalized keys
    # --- control (optional; absent => read-only device) ---
    def settings_schema(self) -> SettingsSchema | None: ...  # what's writable (e.g. work-mode timer)
    def read_settings(self, raw: dict[int, int]) -> Settings: ...     # registers -> typed settings
    def encode_settings(self, s: Settings) -> dict[int, int]: ...     # typed settings -> registers
    @property
    def info(self) -> DeviceInfo: ...            # serial, model, firmware

# Composition the rest of the app consumes.
class Device:
    def __init__(self, transport: Transport, profile: DeviceProfile): ...
    async def read(self) -> Reading: ...             # transport.read_registers → profile.decode
    async def get_settings(self) -> Settings: ...    # read current control settings
    async def apply_settings(self, s: Settings) -> Settings: ...
        # validate → encode → write_registers → re-read → verify → return confirmed state
```

**Reads and writes are separate capabilities.** Control is **optional** on a profile: if `settings_schema()` returns `None` the device is read-only and the app hides all control UI for it (presence of a schema *is* the "supports control" signal, surfaced to the UI via `/api/devices`). The dummy and any monitor-only devices simply don't implement the write path.

Profiles are mostly **data, not code**: a versioned `profiles/<vendor>.yaml` declaring each metric's register address, scale, signedness, word order, and unit. Adding a brand = adding a YAML (+ rare custom decode for odd ones). A **`SunSpec` profile** can cover many standards-compliant brands at once.

**Shared base profiles via inheritance.** Sunsynk, Sol-Ark, and Deye are the *same* Deye-built hardware/firmware, so they share one base register map. Model the YAML with a **`deye-base` profile** that the three brands extend, overriding only what differs (model-size power ratings, the odd address, branding). One map maintained once → three brands supported; the same pattern serves any future rebadge family.

### Normalized metric vocabulary (canonical keys)
Profiles translate raw registers → these keys. The rest of the app only ever sees these (brand-independent):

```
pv_power_w (sum of MPPTs), pv1_power_w, pv1_voltage_v, pv1_current_a,
pv2_power_w, pv2_voltage_v, pv2_current_a,
battery_soc_pct, battery_power_w (+charge/-discharge), battery_voltage_v,
battery_current_a, battery_temp_c,
grid_power_w (+import/-export), grid_voltage_v, grid_frequency_hz,
load_power_w, inverter_temp_c,
today_pv_wh, today_load_wh, today_grid_import_wh, today_grid_export_wh,
today_batt_charge_wh, today_batt_discharge_wh,
inverter_status, run_state, inverter_fault_codes, inverter_warning_codes,
battery_soh_pct, battery_cycles, battery_capacity_ah_measured
```

Keys split into **mandatory core** (power/SoC/voltages — most profiles report these) and **optional** (faults, SoH, cell detail — capability-gated, §17). Status/fault keys carry *decoded* values (a list of human-readable codes), not raw bitfields. The vocabulary is **phase-agnostic**: single- vs. three-phase is handled by per-phase suffixes (`grid_power_l1_w`…) that collapse to the unsuffixed total for single-phase rigs, so the SG05LP1 and a future 3-phase inverter share the same UI.

### Control settings model (schema-driven, inverter-agnostic)
Writable settings are described by a **declarative `SettingsSchema`** the profile returns — the UI is **generated from this schema**, never hard-coded per brand. The same Settings/Control page renders whatever any inverter advertises:

```python
class Field:        # one writable setting
    key: str; label: str
    type: Literal["int","float","bool","enum","time"]
    unit: str | None; min: float | None; max: float | None; step: float | None
    options: list[str] | None          # for enum
    group: str                          # UI grouping, e.g. "Timer slot 3"

class SettingsSchema:
    fields: list[Field]
    repeating: list[RepeatingGroup]     # e.g. the 6 work-mode timer slots
```

**Sunsynk work-mode timer** is the first concrete instance — modeled as a repeating group of **time slots** (the SG05LP1 has 6), each slot a normalized record:
```
slot: { start_time, target_soc_pct, power_w,
        charge_from_grid: bool, charge_from_gen: bool }
plus globals: { timer_enabled: bool, work_mode: enum[...] }
```
The profile maps these typed fields ↔ the actual holding registers (`encode_settings`/`read_settings`); the front end only ever sees the schema + typed values, so it works identically for a Deye, Growatt, etc. once their profile declares its own schema. Constraints (SoC 0–100, power ≤ inverter rating, valid times) live in the schema and are enforced both client- and server-side.

### Each profile self-describes (declares everything it can report)
A profile isn't just a decode table — it **advertises its capabilities** so the rest of the app (and the UI) adapt to whatever device is connected:
```python
class DeviceProfile(Protocol):
    vendor: str
    def capabilities(self) -> set[str]   # which normalized metric keys this device provides
    def info(self) -> DeviceInfo         # vendor, model, firmware, serial, ratings (kW, kWh)
```
The UI hides panels for metrics a device doesn't report (e.g. a DC-coupled battery BMS that has no grid data). Missing ≠ zero: unreported metrics are absent, not faked.

### Keeping the seam protocol-agnostic (beyond Modbus)
The `Transport`/`DeviceProfile` interfaces above are the **Modbus-family form** — they speak in *registers* (`read_registers`, `decode(raw: dict[int,int])`). Most target vendors are Modbus, but **not all are**, so the *cross-family* contract is deliberately narrower: a `Device` only owes the rest of the app a **`Reading` (canonical metrics)** and an optional **`SettingsSchema`** (§7 vocabulary). *How* a device produces those is a **protocol family**, and Transport+Profile are paired **within** a family:
- **Modbus family** (RTU / TCP / SolarmanV5): the register interface shown above; profiles are YAML register maps. Covers the large majority of vendors and **SunSpec** (one profile, many compliant brands).
- **Text command/response family**: proprietary ASCII protocols (Voltronic/Axpert & many Must models speak `PI30`/`QPIGS…` command→response with a CRC, over serial or USB-HID). No register space — the profile is a *command set + field layout*, the transport sends commands and returns frames. The register Protocol does **not** fit; this family has its own transport+profile contract.
- **Victron family**: its own ecosystem — integrate via Venus OS (GX) Modbus-TCP or MQTT, or VE.Direct text on smaller units. Again its own transport(s)+profile.

All three still emit the **same normalized `Reading`**, so everything above the driver (storage, stats, forecast, UI, egress, alerts) is untouched. The lesson for v1: **don't let the register model leak above the driver** — keep `dict[int,int]` and Modbus specifics inside the Modbus family, so adding the text/Victron families later is additive, not a refactor. See §20 for the vendor roadmap this enables.

### v1 transport — `ModbusRtuSource`
- `pymodbus` async serial client over `/dev/ttyUSB0` (USB↔RS485 adapter).
- Config: serial port, baud (9600/default), Modbus slave id. Brand-agnostic.

### First profile — `SunsynkProfile` (target: `SYNK-8K-SG05LP1`)
- Built on the shared **`deye-base`** map (since Sunsynk = Sol-Ark = Deye firmware); `profiles/sunsynk-8k-sg05lp1.yaml` extends it with this model's ratings/overrides (address, scale, signedness, word order, unit).
- **Sol-Ark and Deye come almost for free** — once `deye-base` is validated here, they're thin profiles pointing at the same map.
- Battery metrics come **via the inverter** (it manages the LiFePO₄ BMS), so `capabilities()` includes the battery keys — no separate BMS device on this rig.
- Handle Sunsynk quirks: signed values, 16/32-bit registers, scaling factors, sign conventions for battery/grid direction.
- Reports the full canonical metric set above; validated against the inverter's own display.
- **Control:** implements `settings_schema`/`read_settings`/`encode_settings` for the **work-mode timer** (6 slots + globals) — the writable holding registers, also discovered/validated via §11. Only active when the control deploy-flag is on (§12).

#### Validation status (first real scan — drafted into `profiles/`)
**Draft profiles `profiles/deye-base.yaml` + `profiles/sunsynk-8k-sg05lp1.yaml` exist now**, built from a `regscan --map` capture of the actual unit and cross-checked against physics. Confirmed against the live device:
- **It is a 1PH unit** (the 3PH register bank 500–708 reads all-zero) → the kellerza **`1PH` column** is correct.
- **Internal consistency**: `battery_power 749 W = 52.85 V × 14.18 A`; `inverter_current 2.7 A ≈ 656 W / 248.6 V`; `rated_power [16,17] = 8000 W`; frequencies/voltages all sane.
- **32-bit word order is LOW-WORD-FIRST** (proven by rated power + energy counters; note `total_grid_import [78,80]` is non-adjacent — 79 is grid frequency).
- **Temperatures use Sunsynk `(°C+100)×10`** — decode `raw/10 − 100` (battery 22.0, radiator 33.3, DC-xfmr 39.4 °C). The kellerza TSV's plain `×0.1` is wrong here; regscan's cell syntax now supports a trailing offset (`[182] * 0.1 - 100`) and the bundled `sunsynk-deye.tsv` carries it.
- **Work-mode timer control map confirmed**: 6 slots at Time `[250-255]`, Power `[256-261]`, Capacity/target-SoC `[268-273]`, charge/mode bits `[274-279]`, plus `Use Timer [248]&0x01` and `Grid charge [232]&0x01`. Serial is ASCII at `[3-7]`.
- **✓ Sign conventions resolved (grid-charging capture)**: while grid-charging the battery, `battery_power [190] = −3968 W` and `battery_current [191] = s16 −73.43 A` (−73.43 × 54.04 V = −3968 W ✓) → this unit is **discharge-positive**, so `battery_power_w`/`battery_current_a` are **negated** to the canonical **+charge/−discharge** (the latter was also wrongly typed `u16` — it is `s16`). `grid_power [169] = +4794 W` while importing → **import-positive**, which already matches canonical **+import/−export** (no flip). A daytime capture also confirmed `pv1_voltage_v` (265.1 V under load) and the `solar_export [247]` setting (toggle-verified 0→1). *Remaining:* grid **export** polarity (assumed s16-negative) still needs a **battery-full + PV-surplus** scan — the daytime capture didn't export (battery at 61 %).

### Dummy / simulator profile — `DummyProfile` (build FIRST)
- A built-in **fake inverter** that needs no hardware and no wiring — pairs with a `NullTransport` (or any transport, ignored).
- Generates **realistic, time-of-day-aware** synthetic readings: a solar bell-curve for PV, a plausible load profile, a battery that charges by day / discharges at night, occasional grid import/export — so charts, stats, and forecast all have believable data.
- Reports the **complete** canonical metric set, so every UI panel and code path is exercisable.
- Deterministic seed option for tests; also drives unit/integration tests and CI without serial hardware.
- **Accepts writes in-memory** — implements the control path (mirrors a work-mode-timer schema), so the entire validate→write→read-back flow and Control UI can be developed and tested with zero risk before going near a real inverter.
- This is the default device on a fresh install until real hardware is configured.

### Later transport — `SolarmanV5Source`
- `pysolarmanv5` (TCP to the logger on port 8899, needs logger serial number).
- **Reuses the exact same profiles** — SolarmanV5 wraps the identical Modbus payload, so only the framing/transport differs; the Sunsynk (or any) profile decodes unchanged.
- Selected purely via config (`transport: modbus_rtu | solarman_v5 | modbus_tcp`); no code changes upstream.

---

## 5. Data Model & Storage

**Raw samples** (high-frequency, short retention e.g. 7–30 days) — tagged by device:
```
samples(ts, device_id, metric, value)   -- narrow table; device_id supports mixed-brand systems
```

**Rollups** (downsampled, long retention) — also tagged by device, same as raw:
```
rollup_5m(bucket_ts, device_id, metric, avg, min, max, last)
rollup_1h(bucket_ts, device_id, metric, ...)
rollup_1d(date, device_id, metric, energy_wh, soc_min, soc_max, ...)
```

- Aggregator job rolls raw → 5m → 1h → 1d on a schedule; prune raw past retention. **Retention windows are user-configurable** in Settings.
- **Schema migrations via Alembic** (§19) so app upgrades never lose accumulated history; migrations run on startup, behind the repository abstraction.
- Energy (Wh) derived by integrating power over time **or** by diffing the inverter's own daily counters (prefer counters where available, they're authoritative; reset detection at midnight).

**Config DB** (small relational tables / JSON):
- **Devices**: `id`, `vendor/profile`, `transport` + its params (port/baud/slave-id or host/serial), poll interval, enabled flag. One row per physical device; a system can hold several. A **direct-connected BMS is just another device row** (its own transport + BMS profile).
- **BMS topology** (per battery): `inverter_relayed_read` | `inverter_relayed_readwrite` | `direct` — see Decision #3. Tells the app where battery metrics come from and **whether/where BMS settings are writable** (on the inverter's control page vs. a separate BMS device's). For `direct`, references the BMS device row above.
- System spec: **one or more array segments** (each: kWp, tilt, azimuth, string layout, **+ panel datasheet params: Temperature Coefficient of Pmax %/°C and NMOT °C**) for the inverter's 2 MPPTs; battery capacity (inverter reports **Ah**, e.g. 312 Ah → kWh via nominal voltage; auto-detected when the inverter exposes it, else user-set, **inverter wins** — see Decision #3) & chemistry; inverter model; location (lat/lon/timezone). All user-editable in Settings.
- Tariffs: **import (purchase)** and **export (feed-in)** each modeled as flat *or* time-of-use windows (with optional seasonal variants) for cost/savings stats.

---

## 6. Forecast Service (Projected)

- Source: **Open-Meteo Forecast API** — `shortwave_radiation` (GHI), plus cloud cover and **air temperature** (`temperature_2m`, drives the thermal derate below); free, no key, hourly.
- Convert irradiance → expected PV power **per array segment** (the SG05LP1 has 2 MPPTs; user may have e.g. east + west strings at different tilt/azimuth), then sum:
  `P_segment ≈ kWp × (POA_irradiance / 1000) × performance_ratio × temp_derate`
  - POA from GHI via each segment's tilt/azimuth transposition (start simple: GHI×factor; refine with a transposition model later).
  - **`temp_derate` from the panel datasheet** (these ABC modules) rather than a fixed fudge:
    - Cell temp via the NMOT model: `T_cell = T_air + (NMOT − 20)/800 × POA_irradiance` (W/m²).
    - Power derate: `temp_derate = 1 + (γ_Pmax / 100) × (T_cell − 25)`, where **γ_Pmax = Temperature Coefficient of Pmax** (%/°C, negative) and **NMOT** are entered per module type. So on hot, bright days the forecast correctly drops.
  - `performance_ratio` (wiring/inverter/soiling losses) still calibrated empirically against measured history — now a smaller correction since temperature is modeled explicitly.
- Outputs:
  - **Expected generation curve** for today/tomorrow (overlay on actuals).
  - **Battery trajectory projection**: forecast PV − forecast load (from historical load profile by hour/weekday) → projected SoC over next 24–48h; flag predicted depletion or full-charge times.
- Cache forecasts; refresh a few times/day. Store forecast-vs-actual to track model accuracy.

---

## 7. API Surface (sketch)

```
GET  /api/live                     -> latest Reading (also pushed via WS /ws/live)
GET  /api/history?metric=&from=&to=&res=5m|1h|1d
GET  /api/stats/daily?date=        -> energy totals, self-consumption %, autonomy %, cost
GET  /api/forecast                 -> generation + SoC projection
GET  /api/config / PUT /api/config -> system spec (array segments, battery), tariffs, location
GET  /api/health                   -> per-device connection status, last sample age
GET  /api/diagnostics              -> Modbus comms stats, DB size, rollup lag (§19)
GET  /api/export?metric=&from=&to= -> CSV/Excel history export (§19)
GET  /metrics                      -> Prometheus exposition (§14)

# Alerts (§15)
GET    /api/alerts                 -> active + recent alerts
GET/PUT /api/alert-rules           -> CRUD alerting rules + channels

# Integrations (§14) — MQTT / HA-discovery / PVOutput / webhook config
GET  /api/integrations / PUT /api/integrations

# Device management (CRUD) — drives the Settings > Devices UI
GET    /api/devices                -> list devices + status + capabilities
POST   /api/devices                -> add (vendor/profile + transport + params)
PUT    /api/devices/{id}            -> edit / enable-disable
DELETE /api/devices/{id}            -> remove

# Control (write-back) — per device (only when control flag enabled, §12)
GET  /api/devices/{id}/settings/schema   -> SettingsSchema (drives the generic UI)
GET  /api/devices/{id}/settings          -> current settings + read revision/etag
PUT  /api/devices/{id}/settings          -> validate→write→read-back; returns confirmed state
                                            (If-Match etag for optimistic concurrency; 409 on stale)
```

---

## 8. Frontend — Bootstrap Admin UI

### Shell & layout
A classic fixed admin layout built on **Bootstrap 5.3** (no heavyweight admin template dependency — just Bootstrap + a thin custom layout so it stays maintainable):

```
┌────────────────────────────────────────────────────┐
│  Fixed header (brand · live status pill · theme   ▮ │  ← fixed-top navbar
├──────────┬─────────────────────────────────────────┤
│ Fixed    │                                         │
│ sidebar  │   Scrollable content area               │
│ (nav)    │   (the only part that scrolls)          │
│          │                                         │
├──────────┴─────────────────────────────────────────┤
│  Fixed footer (version · last-sample age · clock) ▮ │  ← fixed-bottom
└────────────────────────────────────────────────────┘
```

- **Fixed header** (`navbar fixed-top`): brand, live connection status pill (green/amber/red driven by `/api/health`), theme toggle, sidebar collapse button.
- **Fixed sidebar**: vertical nav to the views below; collapses to icons / off-canvas (`offcanvas`) on narrow screens for mobile.
- **Fixed footer** (`fixed-bottom`): app version, last-sample age ("updated 3s ago"), wall clock.
- **Content** is the only scrolling region (offset by header/footer/sidebar via CSS padding/margins).

### Theming — light & dark
- Use Bootstrap 5.3's **native color modes**: `data-bs-theme="light" | "dark"` on `<html>`. No custom CSS framework needed.
- Stick to **standard Bootstrap semantic colors** — `primary/success/warning/danger/info` and theme-aware surface variables (`--bs-body-bg`, `--bs-secondary-bg` for cards/sidebar). This keeps both themes consistent for free.
- Suggested semantic mapping for the domain: PV/solar = `warning` (yellow), battery = `success` (green), grid import = `danger`, grid export/feed-in = `info`, load = `primary`.
- Theme toggle persists to `localStorage`; default follows `prefers-color-scheme`.

### Charts & live update
- **Chart.js** (theme-aware: re-read CSS color variables on theme switch) for time-series lines, stacked energy bars, and gauges/doughnuts for SoC.
- **Live update path**: WebSocket `/ws/live` pushes each new `Reading`; a small client store updates gauges/flow diagram instantly and appends to the rolling live chart without a full refetch. History/forecast charts load via REST and refresh on demand.
- Graceful degradation: if the socket drops, status pill goes amber and the client falls back to polling `/api/live`.

### Views (sidebar nav)
1. **Now** — the **`<energy-flow>` widget** (five-node solar/inverter/house/battery/grid topology with direction-aware animated flow; see Componentisation below), live SoC & power gauges, connection health, and a **fault/alarm banner** when the inverter reports faults (§16). Optional battery-detail panel (SoH, cell voltages) when the BMS exposes it (§17).
2. **History** — selectable metrics, date range, resolution; stacked energy bars (day/month); **day/period comparison overlay** (yesterday, same day last year); KPI cards (self-consumption, self-sufficiency, peak, **cost saved, CO₂ avoided, ROI/payback** §19). CSV/Excel export of the current view.
3. **Forecast** — tomorrow's expected generation curve, projected SoC line, "battery expected to reach X% by HH:MM", forecast-vs-actual accuracy.
4. **Control / Device Settings** — **device-agnostic, schema-driven** page, **per writable device**. Renders entirely from the selected device's `settings_schema()` (§4): a generic form builder maps `Field`/`RepeatingGroup` → Bootstrap inputs (number/toggle/enum/time), so the **same page edits any device's writable settings**. For the Sunsynk inverter it shows the **6 work-mode timer slots** (time, target SoC, power, charge-from-grid, charge-from-gen) plus global timer enable & work mode. **BMS settings appear here too, in the right place per topology** (Decision #3): on the *inverter's* page if it relays writes, or on a *separate BMS device's* page if directly connected. Flow: load current settings → edit → client+server validation → **confirm dialog** → write → read-back → show confirmed state (or diff/rollback on mismatch). Devices without a schema (dummy, monitor-only, read-only BMS) simply don't show this page.
5. **Settings** — a **tabbed** page grouping configuration by concern: **Devices** (add/edit/remove; pick vendor profile + transport + connection params; the dummy inverter is preconfigured), **Solar & battery** (forecast site/array/battery), **Tariff** (import/export/economics), **Notifications** (alert channels + outbound readings webhook), **System & data** (locale/formatting + backup/restore), and **Diagnostics** (the read-only operational snapshot — §19 — embedded here rather than a separate nav item). UI panels driven by each device's advertised capabilities.

### Build approach
- **Angular 21 (standalone components) + TypeScript**, Bootstrap 5.3 added via styles (SCSS) rather than a heavyweight admin template.
- Bootstrap components via **`ng-bootstrap`** (native Angular widgets, no jQuery) — offcanvas sidebar, modals, toasts for alerts.
- Icons via **Bootstrap Icons** (`bootstrap-icons` npm package), used as the self-hosted SVG sprite / webfont — pairs natively with Bootstrap 5.3.
- Charts via **`ng2-charts`** (the Angular wrapper around Chart.js).
- **No CDN — self-host everything.** Bootstrap 5.3, Bootstrap Icons, Chart.js and any fonts are installed via npm and bundled by the Angular build into the static assets FastAPI serves. The deployed app must load with **zero outbound requests** (offline in-home LAN, §13); never reference `cdn.jsdelivr.net`, Google Fonts, or any external URL from the frontend. CI/install should fail if a CDN reference sneaks in.
- Live data via an Angular **service wrapping the WebSocket** as an RxJS `Observable` (e.g. `connect()` → stream of `Reading`s); components subscribe and update via the `async` pipe / signals. REST via `HttpClient` with TanStack-style caching optional.
- Theme handled by a `ThemeService` that sets `data-bs-theme` on `<html>` and persists to `localStorage`.
- Build the layout shell (header/sidebar/footer), `ThemeService`, and the WebSocket service as the first frontend pieces in Phase 0.

### Componentisation — everything reusable
The UI is built as **small, self-contained, reusable components**, not page-specific markup. The four pages are thin compositions of a shared component library.

- **Presentational vs. container split.** *Presentational* (dumb) components take data via `@Input()` and emit via `@Output()` — no services, no HTTP, no knowledge of where data comes from, so they're reusable and trivially testable. *Container* (smart) components wire services to presentational ones. A `<gauge>` doesn't care if its value is live, historical, or from the dummy.
- **Shared component library** (`shared/components/`) — reusable building blocks, each used in multiple places:
  - `<metric-card>` — labelled value + unit + trend (used across Now/History/Forecast).
  - `<gauge>` / `<soc-gauge>` — radial gauge for SoC, power, etc.
  - `<time-series-chart>` — wraps Chart.js; takes series + theme, used by History, Forecast, and the live chart.
  - `<energy-flow>` — the PV→house/battery/grid diagram, fed normalized metrics.
  - `<stat-tile>`, `<status-pill>`, `<date-range-picker>`, `<resolution-selector>`, `<confirm-dialog>`.
  - `<schema-form>` / `<schema-field>` — the generic form builder that renders any device's `settings_schema` (§4); already reusable by design, one field component per `Field.type`.
- **Configurable, not hard-coded.** Components are parameterised (units, colour role, thresholds, min/max) via inputs and use the theme's semantic colours — so the same `<gauge>` serves SoC, power, or temperature by configuration alone.
- **Standalone components + `OnPush` change detection**, typed input/output models shared with the API DTOs, and **signals** for reactive local state. Each component ships with its own unit test; consider **Storybook** to develop/showcase the library in isolation (and double as visual regression).
- **Smart/dumb keeps live-update isolated:** only container components subscribe to the WebSocket; presentational ones just re-render on input change — so reuse never drags data-fetching along.

### The `<energy-flow>` widget (Now view centrepiece)
The flagship presentational component on the Now page: a compact, square topology diagram of where
energy is moving *right now*. Five nodes, four connecting lines, direction-aware animated flow.

```
   ┌─────────┐                 ┌─────────┐
   │ ☀ Solar │                 │ ⌂ House │
   └────╲────┘                 └────╱────┘
         ╲                        ╱
          ╲      ┌─────────┐     ╱
           ╲─────│ ↯ Inv.  │────╱
           ╱     └─────────┘    ╲
          ╱                      ╲
   ┌────╱────┐                 ┌──╲──────┐
   │ ⚡ Batt │                 │ 🗲 Grid │
   └─────────┘                 └─────────┘
```

- **Layout.** Inverter centre; **solar** top-left, **house** top-right, **battery** bottom-left,
  **grid** bottom-right. A line connects each corner node to the inverter (corners never connect to
  each other — all energy routes through the inverter). Square 1:1 aspect, scales to its container.
- **Node ring colour** encodes per-node status, mapped to the standard Bootstrap semantic palette
  (theme-aware, light/dark) — **green = `success`, red = `danger`, grey = `secondary`**:
  - **Solar** — green producing (`pv_power_w > 0`), grey idle.
  - **Battery** — green charging, red discharging, grey idle (sign of `battery_power_w`: +charge / −discharge per §4).
  - **Grid** — green exporting, red importing, grey idle (sign of `grid_power_w`: +import / −export per §4).
  - **House** — **always grey.** Load is a sink, not a source; colour would carry no directional meaning.
  - **Inverter** — green online/connected, red fault or offline (from run-state / connection health, §16).
- **Animated flow.** Each *active* edge carries motion travelling **in the energy-flow direction**
  (solar→inverter, inverter→house, inverter↔battery and grid↔inverter flip with the sign). Direction
  is read from motion, not decoded from a static arrowhead. Flow takes the **receiving** node's status
  colour (green particles toward a charging battery; red away from a discharging one), reinforcing cause
  and effect without a legend. **Magnitude is deliberately not encoded in the flow** — wattage already
  lives in the adjacent power gauges/cards; the widget answers *where*, the gauges answer *how much*.
- **Rendering.** Pure **SVG + Bootstrap CSS variables** (consistent with `<soc-gauge>`/`<power-gauge>`):
  theme-aware for free (rings/flow read `--bs-success`/`--bs-danger`/`--bs-secondary`, so the widget
  re-colours on the light/dark toggle with no redraw), and DOM-testable. Geometry is computed (node
  positions + trimmed connector lines), not hand-authored path data; flow is animated in **CSS**
  (chevrons travelling node→node along each active edge). Fed normalized metrics only — a dumb
  presentational component (`@Input() metrics`, `@Input() inverterOnline`), no services, no HTTP; the
  Now container subscribes to the WebSocket and feeds it.
- **Reduced motion.** Respects `prefers-reduced-motion`: the travelling chevrons are suppressed and each
  active edge shows a static directional dashed stroke + arrowhead instead; node ring colours remain
  fully visible.

---

## 9. Delivery Phases

- **Phase −1 — Register discovery (runs on the target machine):** a standalone **register-scanner CLI** (`tools/regscan.py`) — see §11 — that connects over RS485 to the SYNK-8K-SG05LP1 and **probes the full Modbus register space**, dumping each register's raw value (and common decodings). Run it repeatedly while changing known conditions to **reverse-engineer the map from observed values**, producing a first-cut `profiles/sunsynk-8k-sg05lp1.yaml`. Prerequisite to Phase 1; needs only Python + the USB-RS485 adapter, not the full app.
- **Phase 0 — Skeleton:** repo, FastAPI + Angular scaffolds, **native install path (systemd unit + `install.sh`) and an optional Dockerfile/Compose** (§13), `Transport`/`DeviceProfile`/`Device` interfaces, **`DummyProfile` simulator + `NullTransport`**, device registry, live WebSocket end-to-end driven by the dummy inverter. (No hardware needed — the whole app is usable from here. Can proceed in parallel with Phase −1.)
- **Phase 1 — Real instant data:** `ModbusRtuSource` transport + `SunsynkProfile` built from the Phase −1 map (`profiles/sunsynk-8k-sg05lp1.yaml`), validate readings against the Sunsynk's own display, live dashboard. Dummy remains for tests/CI.
- **Phase 2 — Persistence & history:** storage layer, poller writing samples, rollup jobs, history API + charts.
- **Phase 3 — Statistics:** daily/monthly energy, self-consumption/autonomy, tariff costs, **CO₂ & savings/ROI** (§19). Fault/alarm decoding (§16) and battery-health metrics (§17) land here too — they're just more decoded keys.
- **Phase 4 — Forecast:** Open-Meteo integration, PV model, SoC projection, forecast-vs-actual.
- **Phase 5 — Settings display (read-only, §4/§12):** profile `settings_schema`/`read_settings` for the Sunsynk work-mode timer + globals + battery, a settings **read** API, and a schema-driven **read-only** view that surfaces every setting and its current value. **Not gated** — reading settings is just more monitoring. Sequenced so the picture is visible before any write path exists.
- **Phase 6 — Control / write-back (§12):** add the ability to **modify** those settings — `write_registers` + allow-list, `encode_settings`, `apply_settings` (validate→confirm→write→read-back), a flag-gated write API, the edit/diff/confirm UI, and a write audit log. **Off by default** behind the deploy flag; the Phase-5 read-only view stays available when off. Exercise the whole path against the **dummy inverter** (which accepts writes in-memory) before touching real hardware. Sequenced after monitoring + settings-display are rock-solid.
- **Phase 7 — Alerts & integrations (§15, §14):** rule-based alerting + notification channels; MQTT publisher with **Home Assistant auto-discovery**; optional PVOutput / Prometheus / webhook egress. These are off the hot path and brand-independent (driven by the canonical vocabulary), so they come free for every profile.
- **Phase 8 — Polish & operational (§19):** energy-flow UI, first-run setup wizard, backup/restore & CSV export, diagnostics page, installable PWA, calibrate PR factor.
- **Later — Smart automation (§18):** tariff + forecast-driven auto-scheduling of the work-mode timer, opt-in and built on the Phase-6 control safeguards (Predbat-style). Listed last; the architecture is laid so it slots in without core changes.
- **Later — More vendors & transports:** `SolarmanV5Source`; **Sol-Ark & Deye profiles are near-free** (thin extends of the shared `deye-base` map validated in Phase 1); further families (Growatt, Victron, SunSpec) as demand arises — each a new YAML (+ its own settings schema for control), not a core change.
- **Later — Post-MVP features (on request):** **import historical data from a Solar Assistant backup** (map its series → canonical vocabulary, bulk-load + re-roll-up, idempotent) for people migrating in; **customisable dashboards** — 12-column widget grid (gridstack, self-hosted) with two built-in dashboards (Now + History) and unlimited user dashboards; edit mode has drag-and-drop + resize; layouts persist in `app_config`; export/import as JSON. See `TASKS.md` L06 + T_DB1–T_DB8.

---

## 10. Key Risks & Decisions to Lock Early

- **Register map accuracy** — maps vary by vendor *and* by model/firmware within a vendor; verify every value against the device screen. Biggest source of bugs. Each profile needs its own validation pass.
- **Sign conventions** — battery charge/discharge & grid import/export polarity differ between brands; pin them **in each profile**, normalize before storage, never in the UI.
- **Capability variance** — devices report different subsets; the app and UI must handle absent metrics gracefully (driven by `capabilities()`), not assume every device provides everything.
- **Energy accounting** — counters vs. integration; handle midnight resets and missed samples.
- **RS485 reliability** — serial timeouts/retries, backoff, surfacing "stale data" honestly in the UI.
- **Polling cadence** — fast enough to feel live (~2–5s) without saturating the bus; decouple poll rate from persistence rate.
- **Write-back is the highest-risk feature** — a wrong holding-register write can mis-program the inverter (bad SoC targets, wrong charge windows). Mitigated by §12: off by default, schema-validated, confirmed, read-back-verified, write-register allow-list. Treat with more caution than everything else combined.

---

## 11. Register Discovery Tool (Phase −1)

A standalone CLI, **`tools/regscan.py`** (built — see `tools/README.md`), run **on the target machine** (the box wired to the inverter) to reverse-engineer the Sunsynk register map from observed values. Self-contained: Python + `pymodbus` + a USB-RS485 adapter; **no app, DB, or Angular needed**. A `--mock` mode runs the whole workflow with no hardware.

> **Head-start: a known community map exists.** The Deye/Sunsynk family is already mapped by the **[kellerza/sunsynk](https://kellerza.github.io/sunsynk/reference/definitions#available-sensors)** project, in four variants (`1PH`, `1PH-16kw`, `3PH`, `3PH-hv`). The **SG05LP1 target is single-phase → the `1PH` column**, and that map already hands us almost the whole canonical metric set *and* the full work-mode-timer control registers (its `Prog1..6` Time/Power/Capacity/Charge/Voltage/Mode = the 6 timer slots of §4/§12). This **empirically validates the `deye-base` + per-variant-override design** (§4) and the per-phase vocabulary (§4). **But community maps contain errors and internal address collisions** (e.g. in the `1PH` column `[184]` is listed for *both* Battery SOC and AUX L1 current; the per-phase Gen/AUX block looks mis-applied to single-phase) and shift with firmware — so the map is a **seed to verify, never to trust blindly** (§10 register-map-accuracy risk). Phase −1 therefore becomes *targeted verification* rather than blind discovery, but is **not skippable**: every address/scale/sign is still confirmed against the inverter's own screen.

Three subcommands:
- **`scan`** — one read-only snapshot, labelled with the system state and the values read off the inverter screen (`--label`, `--condition key=value`, `--note`). Writes `snapshot-*.json` + `.csv`. Stamps vendor/model/firmware into each file. Reads either a contiguous range (`--start..--end`) **or**, with **`--map sunsynk-deye.tsv` (optionally `--variant`), only the registers a candidate map references** — clustered into a few transactions (nearby addresses merged, empty gaps skipped) so onboarding doesn't sweep hundreds of irrelevant registers. Two capture modes:
  - *active* (default): act as the Modbus master and poll the range.
  - *passive* (`--passive`): when the port is already in use by another master (the stock logger/poller), **sniff** its RS485 traffic instead — open the port non-exclusively, reconstruct + CRC-check Modbus RTU frames, and pair each response with its request to recover addresses. No second master on the bus, so no collisions; captures only what the other master polls.
- **`report`** — consolidates all snapshots into **`regscan-report.md`**, a Markdown file **designed to be pasted to Claude**: it carries an instructions preamble, the device/firmware metadata, the captured states, a "registers that changed across states" table (the map-these-first list), and a full decoded dump. A matching `regscan-report.json` is emitted for machine use. With **`--map sunsynk-deye.tsv` (optionally `--variant`)** it annotates every known register with the map's **name [group] + decoded value** (e.g. `Battery SOC [diagnostics] = 78`) instead of the heuristic hint, surfacing map **collisions** inline for resolution against the screen — turning the report into a validation of the candidate map rather than blind discovery.
- **`verify`** — checks a **candidate map** (the kellerza/sunsynk table saved as TSV, or a JSON `{name: cell}`) against observed values from `--from` a prior snapshot, `--mock`, or live `--port`. It decodes each register **the way the map says** (`[190] S` → signed, `[183] * 0.01` → scaled, `[232] & 0x01` → masked, `[63,64]` → multi-register), so it can be ticked against the inverter screen. Two modes:
  - **Single variant** (`--variant 1PH`): a per-register decode table + the map's own **address-collision** flags. This confirms the kellerza seed for *this* model/firmware before it becomes `profiles/sunsynk-8k-sg05lp1.yaml`.
  - **All variants** (omit `--variant`): decodes **every** column (`1PH`/`1PH-16kw`/`3PH`/`3PH-hv`) side by side from one scan and reports per-variant **readable-vs-rejected** coverage to **detect the inverter type** — the correct variant reads its own registers (few rejections) while wrong ones hit out-of-range addresses and error out. Emits a `name × variant` decoded-value grid (`verify-matrix.csv`) to confirm the winning column row-by-row. (Scan the full `0..708` union range so wrong-variant addresses are actually probed.)

### What it does
- **Sweep** a configurable register range (holding *and* input registers) for a given Modbus slave id — read in safe block sizes, handle gaps/exceptions gracefully, retry with backoff.
- **Decode each register multiple ways** so values are recognisable: raw `uint16`, `int16`, and adjacent-pair `uint32`/`int32` (both word orders), plus common scalings (×0.1, ×0.01). Print all candidates per address.
- **Annotate** with plausibility hints (e.g. a value near 50.0 with ×0.01 → grid Hz; 0–100 → could be SoC %; ~230/400 → voltage).
- **Read-only.** Never writes a holding register — discovery must not change inverter settings.

### How the map gets worked out (the actual method)
- **Correlate against the inverter's own display.** Note SoC %, PV power, battery V/A, grid power on the screen, run a scan, and find the register whose decoded value matches → that's the address + scaling + signedness.
- **Differential scanning.** Snapshot, change one known condition (cover a panel, switch a load, let the battery charge/discharge), snapshot again, and **diff** — the registers that moved in the expected direction reveal PV/load/battery/grid power and the **sign convention**.
- **Timestamped logging.** Each scan writes a CSV/JSON snapshot (`ts, address, raw, decodings…`) so multiple runs can be diffed offline and the reasoning is auditable.

### Output
- The **`regscan-report.md`** consolidated report — paste to Claude, which proposes a first-cut **`profiles/sunsynk-8k-sg05lp1.yaml`** (address, type, scale, signedness, word order, unit, canonical-metric key) — the input to `SunsynkProfile` in Phase 1.
- The **writable settings map** (work-mode timer slots + globals) for the control feature: change a timer slot **on the inverter's own panel**, re-scan, and diff to locate the holding registers behind each setting → feeds the profile's `settings_schema`/`encode`. (Discovery itself stays read-only; the tool only *finds* the writable registers, it doesn't write them.)
- Raw `snapshot-*.json`/`.csv` logs kept in-repo as evidence / for re-deriving if firmware changes.

### Reuse
- Same tool serves **any future vendor/model** — point it at a different device to bootstrap a new profile. It's the standard "onboard a new inverter" utility, not a one-off.
- Records the connected unit's **Protocol/MCU/COMM versions** (2.1 / 5386 / e43d here) in each scan so a map is always tied to the firmware it was derived from.

---

## 12. Write-Back / Control Safety

Writing to the inverter is the one feature that can do harm, so it's deliberately constrained:

### Gated off by default (deployment flag)
- A single deploy flag — **`SOLARVOLT_ENABLE_CONTROL`** (env var / compose setting), default **`false`** — governs all write capability.
- When **off**: write endpoints return **403**, the Control page is hidden, and the device's `"control"` capability is suppressed. The app is **monitoring-only out of the box**, so someone who doesn't know what they're doing can't accidentally reprogram their inverter.
- When **on**: control surfaces for devices whose profile declares a `settings_schema`. The flag is intentionally a *deployment* decision (not a UI toggle a casual user flips) — opt-in, documented, with a clear "you are enabling writes to your inverter" warning.
- No user roles/auth (single-house LAN install, §1) — the deploy flag *is* the gate. Protection is the flag + the layered write safeguards below, not login permissions.

### Layered write protections (all apply when control is enabled)
1. **Schema validation** — every field bounded by `SettingsSchema` (SoC 0–100, power ≤ inverter rating, valid times, enum membership). Enforced client- **and** server-side; reject before any register is touched.
2. **Write-register allow-list** — the profile may only write the specific holding registers in its settings map. No arbitrary-address writes are possible through the API.
3. **Explicit confirmation** — UI shows a **diff** (current → proposed) and requires confirm before sending.
4. **Read-back verification** — after writing, re-read the affected registers; if they don't match the intended values, surface a **mismatch/rollback** rather than reporting success.
5. **Atomic-ish slot writes & concurrency** — apply a timer slot as a coherent set; use the settings **etag/`If-Match`** so a stale edit can't clobber a change made elsewhere (409 on conflict).
6. **Audit log** — every write recorded (when / source client / old→new / result) for traceability and to undo. (No "who" — single-house install has no user accounts, §1.)
7. **Dummy-first** — the whole flow is built and tested against the in-memory dummy inverter before being pointed at real hardware.

---

## Resolved Decisions (answers to the open questions)

1. **Inverter model: Sunsynk `SYNK-8K-SG05LP1`** — 8 kW single-phase hybrid. Concrete target for `SunsynkProfile`; build `profiles/sunsynk-8k-sg05lp1.yaml` against this model's register map.
   **Firmware (confirmed on the unit):** Protocol version **2.1**, MCU version **5386**, COMM version **e43d**. Pin the profile to these; if a future firmware update changes them, re-validate the register map (firmware can shift addresses). Record these in the profile metadata so a mismatch can be detected/warned at connect time.
2. **Wiring: the combined BMS/RS485 port.** First transport reads Modbus RTU off this port via a USB-RS485 adapter. **Confirmed: reading does not interrupt inverter↔BMS comms** — no bus contention, so this port is the supported v1 connection.
3. **Battery: Lithium (LiFePO₄), managed by the inverter over CAN.** Inverter config (confirmed on the unit): Battery type **Lithium**, Lithium protocol **CAN (protocol 0)**, Battery operation **State of Charge**, Battery capacity **312 Ah**. The inverter talks to the BMS over CAN and is in **SoC mode**, so SoC comes from the BMS (accurate, not voltage-estimated) and battery metrics (SoC, V, A, temp) come *through the inverter's registers* — no separate BMS device needed on this rig. **But inverters differ on both reading and writing the BMS**, so the model must support these topologies (a per-battery **BMS topology** config setting selects which):
   - **Inverter-relayed BMS, read-only:** battery metrics decoded from the inverter profile; BMS not writable.
   - **Inverter-relayed BMS, read + write** (some inverters, possibly this one): BMS settings are exposed as writable holding registers *on the inverter*, so BMS control rides the inverter's `settings_schema` (§4) and the same write-safety path (§12).
   - **Direct BMS connection:** the inverter does **not** relay (or doesn't relay writes), so the BMS is a **separate `Device`** — its own transport (its own RS485/CAN-bridge link + a BMS profile) — contributing battery metrics *and* its own `settings_schema` for BMS control, merged by `device_id` into the system view.
   The profile's `capabilities()` declares whether it provides battery metrics, and `settings_schema()` whether the BMS is writable through it; if neither, the system expects a separate BMS device. Config records the chosen topology + (for direct) the BMS connection params.
   **Live battery level = SoC (%), not kWh.** The inverter reports **State of Charge as a percentage** — that's the authoritative live battery metric (canonical key `battery_soc_pct`), stored and charted as-is. It does **not** report energy-in-battery directly.
   **kWh is derived, only when needed** (battery trajectory projection in §6, "hours of autonomy" stats): `energy_kWh ≈ (SoC% / 100) × capacity_kWh`, where `capacity_kWh = capacity_Ah × V_nom`. The inverter reports **capacity = 312 Ah**; nominal pack voltage (48 V-class ≈ 51.2 V → ~16 kWh) comes from inverter/BMS if exposed, else user-set. **Inverter wins** for any value it reports; user config is fallback only. *Usable* energy additionally factors the configured min-SoC / depth-of-discharge.
4. **Array & site spec: fully user-configurable** (not hard-coded). Settings UI captures **kWp, tilt, azimuth, string/array layout, lat/lon**, and the **panel datasheet params — Temperature Coefficient of Pmax (%/°C) and NMOT (°C)** (these are ABC panels); the forecast service (§6) uses the latter two for the thermal derate. **Current values (confirmed):** γ_Pmax = **−0.26 %/°C**, NMOT = **41 °C** — use these as the defaults for this array. Support **multiple array segments** (e.g. east + west strings at different tilt/azimuth, possibly different module types) since the SG05LP1 has two MPPTs — each segment forecast separately and summed.
5. **Tariffs: flat *and* time-of-use, for both directions.** Model both **import (purchase)** and **export (feed-in)** rates, each as either a flat rate or a set of **time-of-use windows** (and seasonal variants). Cost/savings stats in §3/§7 consume this.
6. **Host: a Raspberry Pi running fresh Ubuntu, native install (primary path); Docker optional.** Could also be a NAS or home server. Low-footprint design (SQLite, no heavy DB) keeps it Pi-friendly. **Native is the supported default** (see §13); Docker support is maintained as an alternative. The host with the USB-RS485 adapter must be physically near the inverter; if it can't be, that's a reason to move to the **SolarmanV5 Wi-Fi transport** later, which removes the proximity constraint.

### Still to confirm on-site (pre-Phase 1)
- **Battery capacity** — ✓ **resolved** from the inverter config: **312 Ah** (reg [204]), Lithium / CAN / SoC-mode (reg [325]=0). At the ~51.2 V class that's **≈16 kWh** (matches the forecast default `capacity_wh:16000` and the dummy). Usable depth: min-SoC (stop-discharge) **10 %**, output-shutdown 5 %.
- **Battery & grid power sign conventions** — ✓ **resolved** by the grid-charging capture (battery is discharge-positive → negated to +charge/−discharge; grid is import-positive → matches canonical). A daytime PV capture (2026-06-18) further confirmed **`pv1_voltage_v` = 265.1 V under load** (×0.1) and PV producing (441 W). **Still open (one item):** grid **export** polarity (assumed s16-negative) — the daytime scan had PV but the battery was at 61 % (not full), so it never exported; needs a **battery-full + PV-surplus** scan to confirm directly.

---

## 13. Deployment

Three ways to run, the same app in each — only packaging differs. **Running from the
working copy** is the dev/test path (no install, no hardware); **native install** is the
primary production path for the target (Raspberry Pi on fresh Ubuntu); **Docker** is
maintained as an alternative.

### Running from the working copy (development & testing) — must always work
The repo must be runnable **straight after a `git pull` + basic setup**, with no systemd,
no Docker, no hardware, and nothing to provision:
- **Backend:** `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`,
  then run **Uvicorn with `--reload`** from the repo root (e.g. `uvicorn app.main:app --reload`).
- **Frontend:** either `npm install && ng serve` (Angular dev server, proxying API/WS to the
  backend) for live reload, **or** a one-off `ng build` that the backend then serves — so the
  whole UI is reachable with just the backend running.
- **Defaults make it work with zero config:** the **`DummyProfile` simulator is the default
  device**, the DB is a local SQLite file in the working dir, and `SOLARVOLT_ENABLE_CONTROL`
  is off — so a fresh clone produces a live, populated dashboard (synthetic data) on first run.
- A **`make dev`** target (and documented manual steps) brings up backend + frontend together.
- This path is what CI and contributors use; keep it working — if a change can only run under
  systemd/Docker, that's a regression.
- **VSCode debugging out of the box (`.vscode/`):** committed default launch profiles so opening
  the repo and pressing **F5** debugs both tiers. A **compound "Full Stack" profile** launches the
  **backend under `debugpy`** (uvicorn `app.main:app`, no `--reload` so breakpoints bind reliably)
  and the **frontend in Chrome** against the Angular dev server (a background task starts `ng serve`
  and the launch waits until it's serving), giving real breakpoints/step-through on both sides.
  `tasks.json` backs the dev-server start and a `pytest` task; `extensions.json` recommends the
  Python/Angular/JS-debug extensions. **The Phase 0 scaffold must keep these entry points
  (`backend/` → `app.main:app`, `frontend/` → dev server on :4200, venv at `./.venv`) in sync**
  so F5 keeps working.

### A. Native install on Raspberry Pi / Ubuntu (primary)
- **Targets:** fresh **Ubuntu** (Server/Desktop) on a Raspberry Pi (ARM64); also any Debian/Ubuntu x86 box.
- **Backend:** Python venv (`python3 -m venv`), `pip install -r requirements.txt`, run **Uvicorn/Gunicorn** under a **systemd service** (`solarvolt.service`) so it starts on boot and restarts on failure.
- **Frontend:** Angular built to static files (`ng build`) and **served by the FastAPI app itself** (or nginx) — one process, one port, no separate web server needed.
- **Database:** SQLite file under `/var/lib/solarvolt/` (or the service user's home). Nothing to provision.
- **Serial access:** add the service user to the **`dialout`** group for `/dev/ttyUSB*` access to the USB-RS485 adapter; pin the adapter to a stable path via a **udev rule** (so it isn't `ttyUSB0` one boot and `ttyUSB1` the next).
- **Config:** a single `.env` / config file (DB path, serial port, poll interval, `SOLARVOLT_ENABLE_CONTROL`, etc.); systemd `EnvironmentFile`.
- **Install ergonomics:** an **`install.sh`** (and a `Makefile`) that creates the venv, builds the frontend, installs the systemd unit, sets up the udev rule and group — fresh-Ubuntu-to-running in one script. Document the manual steps too.
- **Updates:** `git pull` + rebuild + `systemctl restart`; SQLite makes backup a file copy.

### B. Docker (optional, maintained)
- **`Dockerfile`** (multi-stage: build Angular, assemble Python app) + **`docker-compose.yml`**.
- **Multi-arch image** (ARM64 + amd64) so the same Compose file runs on the Pi or an x86 server.
- Pass the serial device through (`devices: ["/dev/ttyUSB0:/dev/ttyUSB0"]`), persist the DB via a named volume, supply config via env.
- Same single container serves API + static frontend; same env flags (incl. control flag).

### Releases (tag-triggered → GitHub Releases)
Cutting a release is driven entirely by **pushing a git tag matching `version/x.y`** (e.g. `version/1.0`, `version/2.3`) — a GitHub Actions workflow does the rest:
- **Trigger:** `.github/workflows/release.yml` runs on `push` of tags matching `version/*`.
- **Gate first:** the release build **re-runs the full CI hard gates (§21)** — build, unit tests, coverage, no-CDN check. A red build never produces a release.
- **Version derivation:** the **`x.y`** is parsed from the tag (`version/x.y` → `x.y`) and is the single source of truth — it **names the GitHub Release** (release title = `x.y`), tags the artifacts, and is **stamped into the app** so the footer (§8) and `/api/health` report the running version (no hand-edited version constants).
- **Artifacts attached to the release:**
  - a versioned source/runtime bundle (`solarvolt-x.y.tar.gz`) containing the production `ng build` output (self-hosted assets, no CDN), the backend, `install.sh`, and the systemd unit — i.e. a native-install-ready package;
  - optionally the multi-arch (arm64+amd64) Docker image pushed to **GHCR** tagged `x.y` (and `latest`).
- **Publish:** the workflow creates the GitHub Release named `x.y` with auto-generated release notes (changelog from commits/PRs since the previous `version/*` tag) and uploads the artifacts. Releases live on the repo the Project tracks; the workflow activates once the repo is on GitHub.

### Shared principles
- **No build step required at runtime** in either path beyond the one-time frontend build (baked into the image / done by `install.sh`).
- **One config surface** (env vars) used identically by both paths — so docs and the control flag behave the same way.
- Keep the dependency set lean (SQLite, no external broker/DB) precisely so the **native Pi install stays trivial**.

---

## 14. Integrations & Data Egress

This class of app is judged heavily on how well it plays with the rest of a home stack. All of the below are **optional, config-gated, and off the hot path** — egress runs in a separate async task fed off the poller's reading stream, so a failing integration degrades to a warning, never blocks polling/persistence. All are driven by the **canonical metric vocabulary** (§4), so they're brand-independent and come free for every profile.

- **MQTT publisher** — publish each normalized `Reading` + per-device status to a broker. The single most-requested integration for self-hosted solar.
  - **Home Assistant MQTT auto-discovery** — emit HA discovery configs so every metric appears as an HA sensor with **zero manual YAML** (dashboards, automations, HA Energy panel). Makes the system a first-class HA citizen.
- **PVOutput.org** — optional periodic upload (generation, consumption, SoC, temperature) to the popular community comparison service. API key + system id in Settings.
- **Prometheus `/metrics` endpoint** — expose live metrics for users already running Grafana, so they can build their own dashboards/alerts.
- **Generic outbound webhooks** — POST readings/events to user URLs (Node-RED, IFTTT, custom). **Any
  number of endpoints, each with a user-defined payload** — see *Custom webhooks* below.
- The read-only **REST + WebSocket API (§7) is already the inbound/public surface**; these add *push*-style egress.

### Custom webhooks (multiple endpoints + templated payloads)
Both webhook egress paths — **alert/notification** webhooks (§15) and **outbound readings** webhooks —
started as a *single* configurable URL each. They become **lists of user-defined endpoints**, and the
**payload is user-definable**, so the app can speak whatever shape a downstream service expects (Slack,
Discord, Home Assistant REST, a custom collector) without code changes.

- **A webhook endpoint is data, not code.** Each entry: a stable `id` (slug) + user `label`, `url`,
  `method` (POST default), optional **`headers`** (auth tokens etc.; secret, stored in `app_config`
  like other channel secrets), `content_type` (default `application/json`), an **optional
  `payload_template`**, and `enabled`. **Readings** endpoints additionally carry their **own
  `interval_s`** (each fires on its own cadence); **alert** endpoints are event-driven (no interval).
- **Payload templating.** A `payload_template` is a string with `{placeholder}` substitution; an empty
  template keeps today's **default body** (the raw alert dict / the full readings snapshot) so existing
  setups are unchanged. Reuse the automation message renderer (`_render_message`, §18) — **promote it to
  a shared `app/templating.py`** (`render_template(template, context)`) used by automation messages *and*
  both webhook types. Context: for **alerts**, the alert fields (`name`, `message`, `severity`, `metric`,
  `value`, `device_id`, `fired_at`) plus current metrics; for **readings**, the snapshot (`ts` + flattened
  per-device metric keys). Values substituted into a JSON template are **JSON-escaped** so the body stays
  valid JSON; malformed templates fall back safely (never crash egress). Ship a couple of **presets**
  (Slack/Discord/plain) as starting points in the UI.
- **Each alert webhook is its own selectable channel.** With N webhooks, the per-rule channel picker
  (§15) lists them by label as `webhook:<id>`, so a rule can target specific endpoints (e.g. critical →
  Slack + ntfy, info → a logging collector). The other channel types (Telegram/ntfy/Gotify/Pushover/
  Email) are unchanged — still one config each.
- **No migration needed.** The single-webhook config was never used in practice, so the list shape
  simply replaces it — the old single `webhook` (inside `alert_channels`) and single `readings_webhook`
  config are dropped, not migrated.
- **Same §14 invariants.** Off the hot path, per-endpoint `enabled`, a dead endpoint is logged and never
  blocks polling/persistence/alerting, readings intervals clamp to ≥ 5 s each, and no external URL ships
  in the bundle (endpoints are user data — the no-CDN gate is unaffected).

## 15. Alerts & Notifications

A rule-driven alerting subsystem (the original Phase-6 one-liner, fleshed out — alerting is table-stakes for unattended power systems):

- **Rule engine** — user-defined conditions on any canonical metric or system state: `battery_soc_pct < 20`, sustained high grid import, **device offline / stale data**, **inverter fault/alarm raised** (§16), forecast predicts depletion, over-temperature. With thresholds, hysteresis, debounce, and **quiet hours**.
- **Notification channels** (pluggable, like transports): email (SMTP), **Telegram**, **ntfy**, **Pushover/Gotify**, **any number of custom webhooks** (each with a user-defined payload — see §14 *Custom webhooks*; selectable individually per rule), and in-app toast/inbox. Selectable per rule.
- **Alert inbox & history** — active + acknowledged alerts, past-firing log, snooze/ack; surfaced via a header bell badge.
- **Sensible defaults shipped on** — low-SoC, source-offline/stale-data, inverter-fault — all editable.

**Architecture revision (L03e-5):** The standalone alert-rule engine (`AlertRule`, `AlertEngine`, `AlertService`) is retired in favour of the §18 automation engine, which now supports `notify` and `alert` action types alongside the existing `set_setting` type. Rule authoring moves to the Automation page. The notification channels (`alerts/channels.py`) and the alert inbox (database rows, ack/snooze, bell badge) remain; they are now driven by automation rules. Default alert rules become seeded automation rules. The `/api/alert-rules` CRUD endpoints are removed; the inbox endpoints (`/api/alerts`, ack/snooze) stay.

## 16. Inverter Alarms & Fault Decoding

Beyond `inverter_status`, real inverters expose **fault/alarm bitfields and run-state codes** users depend on for diagnosis:
- Canonical keys `inverter_fault_codes`, `inverter_warning_codes`, `run_state` (§4).
- Each profile maps its raw fault/warning registers → a **normalized list of human-readable codes**, declared in the profile YAML alongside metrics (so it's per-brand data, not core code).
- Surfaced on the **Now** view (fault banner), fed into the alert engine (§15), and **logged to history** so intermittent faults are catchable after the fact.

## 17. Battery Health & BMS Detail

SoC alone undersells what owners want from a battery:
- **State of Health (SoH)**, **cycle count**, **measured full-charge capacity / degradation** where the BMS exposes them — optional canonical keys (`battery_soh_pct`, `battery_cycles`, `battery_capacity_ah_measured`).
- **Cell-level detail** for direct-BMS topologies (Decision #3): per-cell voltages, min/max/delta, cell temperatures, **balancing status** — a dedicated battery-detail panel, gated by `capabilities()`.
- **Round-trip efficiency** and charge/discharge throughput derived from history.
- All capability-driven: rigs that only report SoC simply don't show these (missing ≠ zero, §4).

## 18. Smart Automation & Scheduling (built on Control)

The natural high-value extension once monitoring + forecast + control + tariffs all exist — and the flagship feature of comparable tools (Predbat, Sunsynk smart-load):
- **Automation engine** that *writes* the work-mode timer automatically from rules: "force grid-charge during the cheapest ToU window", "raise target SoC when tomorrow's forecast is poor", "hold charge for an expected evening peak".
- **Tariff + forecast optimization** — combine §5 tariffs and §6 forecast into a proposed daily timer plan that minimizes cost / maximizes self-consumption.
- **User-authored rules too** — beyond the built-in cost-arbitrage planner, condition→action rules the user combines (day-of-week, time/date/season, metric thresholds, tariff window), each rule and action **prioritised** (highest wins a conflicting write) and **armed individually** (both default off; a disabled rule/action is shown as a live preview — "would set X now, if running").
- **Inverse / else actions.** Each rule carries an optional `else_actions` list alongside its primary `actions`. When the rule's conditions evaluate to **true**, the primary `actions` fire (existing behavior). When they evaluate to **false**, the `else_actions` fire instead — enabling an if-else pattern within a single rule (e.g. "if Monday → target SoC 100%, else → 20%"). Else actions go through the same priority resolution, allow-list checks, and write-safety path as primary actions. In the rule editor, each action slot has an optional "else" value field; if left empty, no else action fires for that slot.
- **One gate, on writes only.** Building, previewing and arming rules needs **no flag** — automation is always available. Anything that *writes an inverter register* (the planner's apply, a rule's "set setting" action, the background scheduler) runs entirely on the **§12 safeguards** (validate→write→read-back→audit) and is gated by the single **`SOLARVOLT_ENABLE_CONTROL`** flag — the same switch that guards all write-back. There is **no separate automation flag**. **Suggest/preview is always available; apply is opt-in via control.**
- **Non-write actions are ungated.** Automation actions that touch no register — **send a notification** (`notify` action type, the §15 channel seam: email/Telegram/ntfy/Gotify/Pushover/webhook), **create an in-app alert** (`alert` action type, written to the inbox with ack/snooze/badge) — run whenever their rule/action is armed, even on a monitoring-only deploy with control off. These action types absorb the standalone §15 alert-rule system: one rule engine, one editor, all output types.
- **Debounce on notify/alert actions.** A `debounce_s` field on each notify/alert action prevents re-firing within the window; the service tracks per-action last-fire time. Without debounce, a matched condition would dispatch on every scheduler tick.
- **Synthetic metrics in the eval context.** The two system-state metrics the old alert engine resolved specially — `__stale_s__` (seconds since last reading) and `__fault_count__` (active inverter fault codes) — are injected into the automation `EvalContext.metrics` by the service, so users can create "device offline" or "inverter fault" automation conditions using the existing `metric` condition kind.
- Sequenced **after** Control (in "Later") — the schema-driven settings + forecast + tariffs are deliberately laid so this slots in with no core changes.

## 19. Operational & UX Essentials

Cross-cutting items expected of a polished self-hosted app:
- **First-run setup wizard** — guided onboarding: confirm device (dummy preselected), location (lat/lon auto-suggested, editable), array segments, battery, tariffs — so a fresh install reaches a useful state without hand-editing config.
- **Backup / restore & data export** — one-click SQLite backup + restore in the UI; **CSV/Excel export** of history for any metric/range (documented file-copy backup stays trivial with SQLite).
- **Database migrations** — schema versioned via **Alembic** (§5) so upgrades preserve history.
- **Diagnostics / observability** — structured, level-configurable logging and a **Diagnostics page** extending `/api/health`: per-device Modbus comms stats (success/timeout/retry counts, last error, round-trip time), DB size, rollup lag.
- **Localization & formatting** — configurable **currency** (tariffs/savings), units, date/time format, timezone; i18n scaffolding (strings externalized) even if only English ships first.
- **Installable PWA** — manifest + service worker so the dashboard installs to a phone home screen and rides out brief network blips; pairs with the existing offcanvas mobile layout.
- **Grid-outage / backup-power event log** — detect and log loss/return of grid (islanding) from grid metrics — a commonly-wanted timeline for hybrid/backup systems.
- **Environmental & ROI stats** — **CO₂ avoided** and **savings / payback (ROI)** on the History view, reusing existing energy + tariff data.
- **Inverter clock sync** — optionally read and (under control) correct inverter time drift; a frequent real-world annoyance.
- **Free & open source (BSD 3-Clause, © Darren Horrocks)** — the whole project is BSD-3 licensed (`LICENSE`); keep dependencies license-compatible.
- **User-facing `README.md`, kept current** — the front door for home users: how simple it is to run, the feature set, and that it's free/open-source. It carries a **Project status** notice that's updated as the app progresses, and is the primary "get people running it at home" surface (design detail stays in `plan.md`).

---

## 20. Vendor Roadmap & Protocol Families

The architecture exists to make **adding a vendor a data/plugin task, not a core change**. Beyond the Sunsynk/Sol-Ark/Deye family already targeted, the following are **candidate vendors, added on demand** (per support request) — listed here to keep the design honest about what it must accommodate. They are **not homogeneous**, which is exactly why the device seam is kept protocol-agnostic (§4):

### By protocol family (how each connects)
- **Modbus register-map family** (RTU / TCP / SolarmanV5) — the common case; each is a versioned `profiles/<vendor>-<model>.yaml` (+ rare custom decode), often sharing a base map per firmware family (like `deye-base`):
  **Goodwe, Growatt, Solis (Ginlong), Sungrow, SAJ, SRNE, LuxPower, Sigenergy, Senergy, Megarevo, Afore, Sumry, Felicity, Huawei (SUN2000, Modbus-TCP), Midnite Solar (charge controllers), Must (Modbus models).** Three-phase models are covered by the per-phase canonical keys (§4). **SunSpec-compliant** units (some Goodwe, Huawei, etc.) can be read by **one generic SunSpec profile** rather than a bespoke map.
- **Text command/response family** (proprietary ASCII, no register space) — `PI30`/`QPIGS`-style command→response with CRC over serial or USB-HID:
  **Voltronic (Axpert/MKS), Must (PV18/PI30 models), and similar low-cost hybrids.** Needs a *text-command transport* + a *command-set profile* (which queries to poll, where each field sits in the reply) — a different intra-family contract from registers, but it still emits the same normalized `Reading`.
- **Victron family** — its own ecosystem; integrate via **Venus OS (GX) Modbus-TCP or MQTT**, or **VE.Direct** text on smaller units. Its own transport(s)+profile; metrics normalize like everything else.

### What "in a place that allows this" requires (and the plan already provides)
1. **Protocol-agnostic seam (§4):** the cross-family contract is `Reading` + optional `SettingsSchema`, *not* registers — so the text/Victron families are additive, never a refactor. **This is the load-bearing decision; protect it in v1** by keeping `dict[int,int]`/Modbus specifics inside the Modbus family.
2. **Profiles as versioned data + a registry:** drop a YAML (or, for the odd protocol, a small profile module) into `profiles/` and a registry auto-discovers it; nothing in core changes. **Per-firmware pinning** (as done for the SG05LP1) and **shared base inheritance** generalise to every rebadge family.
3. **Capability-driven UI (§4):** each profile advertises which canonical metrics/settings it provides, so wildly different devices (a Midnite charge controller vs a 3-phase Sungrow vs a Voltronic off-grid unit) each render only what they actually report — no per-vendor UI code.
4. **Schema-driven control (§4/§12):** every vendor's writable settings come from its own `SettingsSchema`, so the generic Control page already handles them.
5. **Onboarding tooling reality check:** `regscan` (§11) bootstraps the **Modbus family** only. The **text** and **Victron** families will need their own (smaller) onboarding helpers — noted now so it isn't a surprise; not built until a request for one of those vendors lands.

**Sequencing:** demand-driven, in *Later* (§9). Each Modbus vendor is a new YAML; the first **text-family** and first **Victron** vendor each carry a one-time cost (build that family's transport + profile contract), after which their siblings are cheap. Mixed-brand systems (e.g. a Sungrow inverter + a separate BMS) already work via the multi-device registry (§4/§5).

---

## 21. Testing & Quality

**Unit testing is mandatory, not optional.** Every deliverable (§9 / `TASKS.md`) ships with tests as part of its *Definition of Done* — code without tests is not done. The **dummy-first** design (§4) exists partly to make this possible: the whole stack runs and is testable with **no hardware**, deterministically.

### What gets tested (and how hard)
The codebase splits cleanly into pure logic (cheap, high-value to test) and I/O glue (harder, lower return), so coverage expectations are **tiered**, not a flat number:

- **Critical pure logic — target ≥ 90% line coverage, near-100% on the gnarly bits:**
  - **Profile decode/normalization** — register → canonical metric: scaling, signed/unsigned, 16/32-bit word order, offsets (the `(°C+100)×10` temp), bitfield/fault decoding, and **sign-convention normalization** (battery charge/discharge, grid import/export). This is the #1 bug source (§10), so it's tested hardest — table-driven cases with known raw→expected vectors captured from real `regscan` snapshots.
  - **Settings encode/read round-trip** (§4) — typed settings ↔ holding registers must round-trip exactly; property-based tests where practical.
  - **Write-safety logic** (§12) — schema validation bounds/enums, the **write-register allow-list** (assert out-of-allow-list addresses are rejected), read-back-verify mismatch handling. Safety code is tested adversarially.
  - **Energy accounting** (§5) — counter-diff vs integration, midnight-reset detection, missed-sample handling.
  - **Forecast model** (§6) — POA transposition, NMOT thermal derate, SoC trajectory — against hand-computed expected values.
  - **Stats** (§3) — self-consumption/autonomy/cost/ROI from fixture series.
- **I/O & glue — lighter, behaviour-focused:** transports (Modbus/Solarman framing) tested against recorded/faked byte exchanges, not live hardware; API endpoints via FastAPI `TestClient`; repository against an in-memory/temp SQLite.
- **Frontend** — presentational components and services unit-tested (each component ships its own test, §8); ~70%+ is reasonable given UI glue. Schema-form builder and the WebSocket/Theme services are tested explicitly.

### Integration / end-to-end tests — Playwright, driving the real app on the dummy
A second test tier covers what unit tests **structurally cannot**: behaviour that only emerges when the whole app is actually running and a user drives it through the browser. These run the **full stack** (FastAPI serving the built Angular app) against the **`DummyProfile` + `NullTransport`** config — deterministic (fixed seed), no hardware — and exercise it as an automated user.

**Scope discipline — integration tests cover only the un-unit-testable.** If a thing can be checked by calling a function or a single endpoint, it stays a unit test. Playwright is reserved for **cross-layer, user-observable flows end-to-end**, e.g.:
- **Live data path:** a `Reading` pushed over the WebSocket actually updates the gauges/flow diagram in the DOM (poller → WS → RxJS store → component render — a chain no unit test spans).
- **Socket-drop degradation:** kill the socket, assert the status pill goes amber and the client falls back to polling `/api/live` and keeps updating (§8).
- **Control round-trip against the dummy's in-memory write path (§4/§12):** open the schema-driven Control page, edit a work-mode-timer slot, see the current→proposed **diff**, confirm, and assert the **read-back-verified confirmed state** renders — the whole validate→confirm→write→read-back loop through real UI + API + device, with control enabled in the test env.
- **Schema-driven UI generation:** the Control form is *generated* from the dummy's `settings_schema` — assert the right fields/inputs appear, proving the generic form builder works against a live schema.
- **Navigation, theming, charts:** theme toggle persists across reload; History/Forecast charts render for a known fixture range; first-run wizard reaches a usable state.

What stays **out** of Playwright: register decode/scaling/sign math, settings encode/read, energy/forecast/stats arithmetic, allow-list rejection logic — all of that is faster and more thorough as unit tests (above). E2E asserts the *wiring and the user experience*, not the arithmetic.

- **Mechanics:** Playwright (TS) with headless Chromium/WebKit; a fixture boots the app in dummy mode on an ephemeral port and tears it down; tests are seed-deterministic so live values are assertable. Control-flow tests set `SOLARVOLT_ENABLE_CONTROL=true` only in that test env.

### The bar (CI gate)
- **All tests pass — 100% green is the merge gate.** Non-negotiable; a red unit **or Playwright E2E** suite blocks merge.
- **Overall backend line coverage ≥ 80%**, with the critical-logic modules above held to **≥ 90%** (enforced per-package, so high coverage of trivial code can't mask an untested decoder). Coverage thresholds fail the build, not just warn.
- These numbers are deliberately *reasonable, not vanity 100%* — the goal is that everything that can silently corrupt data or mis-program the inverter is covered, while not chasing coverage on glue where it adds little.

### Mechanics
- **Backend:** `pytest` + `pytest-cov` (coverage gate), `pytest-asyncio` for async, deterministic **dummy with a fixed seed** for reproducible readings; `regscan` snapshots checked in as decode fixtures.
- **Frontend:** Angular 21's default **vitest + jsdom** runner for component/service specs — headless, no browser needed (good for CI); optional Storybook (§8) doubling as visual regression.
- **Integration/E2E:** **Playwright** (TS) driving the full app in dummy mode (above); a fixture boots backend+frontend on an ephemeral port, seed-deterministic, torn down after.
- **CI = GitHub Actions** (`.github/workflows/ci.yml`), runs on every push and pull request using the **working-copy run path** (§13) — no hardware, no Docker required. Tests live alongside code and land in the same PR as the feature. (The workflow file lives in-repo and activates once the repo is on GitHub.)

### CI pipeline & hard gates
The Action is the enforcement point — **every one of these is a hard gate that fails the build (red), not a warning:**
1. **Build/compile** — backend imports & installs cleanly (`pip install -r requirements.txt`); frontend `ng build` succeeds with **no build errors** (and lint/type errors treated as errors).
2. **Unit tests** — full `pytest` + frontend suites run; **any test failure fails CI**. 100% green is required to merge.
3. **Coverage** — `pytest-cov` (and the frontend coverage reporter) enforce the §21 thresholds: **overall backend ≥ 80%, critical-logic modules ≥ 90%**, frontend ~70%. **Below threshold fails the build**, same as a test failure.
4. **Playwright E2E** — boot the full app in dummy mode and run the integration suite headless; **any failure fails CI**. (E2E is a pass/fail gate, not a coverage-measured one.)
5. **No-CDN check** (§8) — a step that greps the built frontend for external URLs and fails if any CDN/font reference leaked in.

Backend and frontend run as separate jobs (matrix where useful); a clone with no hardware must go green, so the dummy default + checked-in fixtures are what CI exercises. Branch protection should require this workflow to pass before merge once the repo is on GitHub.

---

## 22. ML-Based Smart Optimization

### Overview
After sufficient historical data has accumulated, train a **lightweight ML model** that learns the relationship between system conditions, inverter settings, and outcomes (cost, self-consumption, ROI). At inference time, the model proposes optimal timer-settings for the coming period, fed through the existing automation apply path (§18) and §12 write-safety chain.

Two modes:
- **Dry-run mode (default)** — the model runs and its suggestions are shown in the UI preview but never automatically applied. The user sees "the model would set X, saving an estimated £Y" and can choose to apply manually.
- **Live mode (opt-in)** — the model's proposals are automatically applied by the background scheduler (subject to the same §12 safety gates as any automation write: validate → write → read-back → audit). Gated behind a user-facing toggle, separate from the existing `SOLARVOLT_ENABLE_CONTROL` flag (which must also be on for any write to proceed).

### Design principles
- **Lightweight, Pi-runnable.** No GPU, no heavy framework. Use `scikit-learn` for feature engineering + model training/inference — it's already a common Python ML library, pure-CPU, and runs comfortably on an ARM64 Pi. Avoid TensorFlow/PyTorch unless the problem demands it (unlikely for tabular time-series + settings optimisation).
- **Feature engineering is the hard part; invest there.** The model is only as good as the features. Design a repeatable pipeline that transforms raw historical data into training examples.
- **Dummy-first, same as the rest of the app.** Train and validate the full pipeline against the deterministic dummy (which generates realistic, time-of-day-aware synthetic data) before any real-data training run.
- **Continuous training.** The model retrains on an ongoing basis as new data arrives — every new day of history is another training example. Training runs as a low-priority background task, not on the hot path, but it runs whenever the system is idle rather than on a fixed nightly schedule.
- **Minimum confidence gate.** The model is not used (neither dry-run nor live) until a minimum threshold of training data is met. Default: **14 days** of continuous history with known settings (configurable). Below the gate, the UI shows "ML: insufficient data". The gate prevents nonsensical suggestions from an undertrained model.

### Feature engineering pipeline
The pipeline converts raw historical data into labeled training examples. Each example = one time window (a day or a timer-slot period):

#### Features (input vector)
- **Time-based:** hour of day, day of week (1–7, sin/cos encoded), day of year (sin/cos encoded for seasonality), month, is_weekend, season (categorical: spring/summer/autumn/winter).
- **Weather / forecast:** forecast PV Wh for the window (from the existing §6 forecast service), actual PV Wh if known (retrospective training).
- **Historical load:** expected load Wh for the window (from the historical load profile by hour/weekday, §6).
- **Battery state:** starting SoC (%), battery capacity (Ah/kWh from config).
- **Tariff:** import rate(s) and export rate(s) active during the window, the cheapest import window in the day, the most expensive (peak) window.
- **Current settings:** the timer-slot configuration active during that window (start time, target SoC, grid-charge enabled/disabled, power limit).
- **User-annotated usage labels:** if the user has labelled time windows (e.g. "EV charging", "cooking", "washing"), each label type is one-hot encoded as a feature. This tells the model that certain load signatures are predictable, shiftable loads — improving both the load forecast and the optimisation suggestion.

#### Target (label)
- **Net cost for the window** (import_cost − export_revenue), derived from the existing tariff + energy accounting (§3/§5). This is the primary optimisation objective.
- Optionally also predict **self-consumption ratio** or **grid independence %** as secondary objectives (multi-output or separate models).

#### Data sources (all already stored)
- `samples` + `rollup_5m` / `rollup_1h` — power/SoC/voltage time series.
- `today_*_wh` daily counters — daily energy totals.
- `app_config` tariff + site config (§5).
- Settings audit log (T078) — what settings were active when (for labeling).
- Forecast cache (§6) — weather + PV prediction for the window.
- `usage_labels` table (M006) — user-annotated time windows with label types. Joined on overlap with the training window to produce label features.

### Usage annotation
Users can mark time windows in their historical data with labels describing what was consuming power. This transforms opaque load spikes into structured features the model can learn from.

#### Label taxonomy
Built-in labels (user-extensible):
- **EV charging** — high power (~7 kW), sustained 1–8 hours, often overnight
- **Cooking (hob/oven)** — moderate power (~4 kW), ~1 hour, typically 5–7 pm
- **Washing/drying** — moderate power (2–3 kW), 1–3 hours, variable timing
- **Heating (heat pump / resistive)** — sustained seasonal load
- **Cooling (AC)** — seasonal, daytime
- **Pool pump** — regular daily schedule, low power
- **Water heating (immersion)** — high power, short duration
- **Other** — free-text custom label for anything else

#### Annotation UX
- On the **History** chart, the user can drag-select a time region and choose a label from the list (or type a custom one). The labelled region is overlaid on the chart with a translucent colour band + label text.
- Existing labels can be edited (resized, re-labelled, deleted) by clicking on them.
- The History page already shows time-series lines; annotation overlays extend this with a new `<svg>` / canvas layer aligned to the same time axis.

#### Storage
A `usage_labels` table (migration M006-1):
```
usage_labels(id, device_id, starts_at, ends_at, label, notes, created_at, updated_at)
```
Labels reference a device so mixed-brand systems keep annotations scoped. The feature engineering pipeline (M001) joins this table on overlap with each training window to produce the one-hot encoded label features.

#### Model integration
- During training, each window's overlapping labels become binary features (`has_ev_charging`, `has_cooking`, etc.). The model learns that certain labels correlate with higher load and specific tariff responses.
- During inference, the user can optionally tell the model "I will charge the EV tomorrow" — setting an expected label for the forecast window via the UI, which the model factors into its suggestion.
- Over time, the model may also learn to **predict** likely labels from historical patterns (e.g. "every Tuesday at 10pm the EV charges") — a future enhancement.

### Model
- **Primary model:** `GradientBoostingRegressor` (or `RandomForestRegressor`) from scikit-learn, predicting **net cost per day** given features + candidate settings. These models handle mixed tabular data well, are robust to outliers, and run inference in milliseconds on a Pi.
- **Alternative:** if the search space is small enough, a **linear model with interaction terms** (e.g. `Ridge` with polynomial features) — simpler, more interpretable, faster to train.
- **Optimisation at inference:** to propose settings for tomorrow, enumerate a set of plausible timer-slot configurations (discrete options: e.g. target SoC ∈ {20, 40, 60, 80, 100}, grid-charge ∈ {on/off}, slot start ∈ plausible hours), predict cost for each via the trained model, and pick the configuration with the lowest predicted cost. The enumeration space stays manageable by limiting to the user's actual tariff windows and fixing non-optimised slots to the current values.
- **Fallback:** if no model is trained yet (below the minimum confidence gate on a fresh install), the system degrades gracefully — the existing rule-based automation (L03) continues as before, and the ML preview shows "insufficient data (N of M minimum days)".

### Training pipeline (continuous)
1. **Trigger:** runs automatically after each persist cycle (new sample data has been written), debounced so rapid successive triggers coalesce into one retrain. Also triggers on-demand via API. Runs as a low-priority background task — never on the hot path.
2. **Minimum confidence gate:** skip the training run entirely if `count(training_examples) < MIN_TRAINING_DAYS` (default 14, configurable). The model stays in `insufficient_data` status and no inference is attempted.
3. **Window extraction:** iterate the historical daily rollups + settings audit log to build (features, label) pairs for each complete day where both data and settings are known.
4. **Incremental or full retrain:** for simplicity, always retrain from scratch on the full history window. Given the small data volume (hundreds to low thousands of days per device), full retrains complete in seconds on a Pi. The previous model is kept as a fallback until the new one passes validation.
5. **Train/validate split:** hold out the most recent N days (default 7) as a validation set.
6. **Feature scaling + encoding:** standardise numeric features, one-hot / cyclic-encode time features.
7. **Train:** fit the regressor.
8. **Accuracy gate:** after training, check validation-set MAE/R² against the previous model. If the new model is significantly worse (MAE > 1.5× previous), reject the retrain, log a warning, and keep the previous model.
9. **Persist:** save the trained model + scaler + feature metadata to a versioned file (e.g. `models/v{N}.joblib`), update the active model pointer.
10. **Accuracy tracking:** record per-version validation metrics (MAE, R², training date, feature count, example count) so the user can see whether the model is improving over retrains.

### Integration with existing automation (§18)
- The ML model exposes its proposed settings through the same `GET /api/automation/preview` endpoint, alongside rule-based proposals. The preview shows the **ML-suggested** settings, the predicted cost improvement, and a confidence indicator (model validation score).
- "Apply now" routes through the same existing `POST /api/automation/apply` → `AutomationService.apply()` → `control.apply_settings()` → §12 write-safety path. No new write plumbing.
- **Dry-run vs. live:** a user-facing toggle (`ml_mode: "dry_run" | "live"`) controls whether the scheduler automatically applies ML proposals. In dry-run mode, ML proposals appear in the preview only; the user must manually trigger apply. In live mode, the scheduler applies them on each tick (alongside any rule-based actions, with priority conflict resolved as documented in §18). Live mode requires `SOLARVOLT_ENABLE_CONTROL` to be on (the existing master write gate) — if control is off, the toggle is forced to dry-run.
- The user can have both rule-based and ML-based automation enabled; the ML proposal is treated as one additional "rule" (highest priority or a separate slot).

### Dummy-first training
- The `DummyProfile` already generates realistic, time-of-day-aware synthetic data (§4). Seed a training run against months of dummy data: the pipeline should produce a model that predicts dummy outcomes with reasonable accuracy (the dummy's deterministic behaviour is fully learnable).
- Tests assert that after training on dummy data, the model's suggestions are at least as good as the default settings (measured by simulated cost).
- The dummy also accepts writes in-memory, so the full train → suggest → apply → read-back cycle is exercisable without hardware.

### Roadmap
1. **Data pipeline / feature engineering module** — pure functions to build training examples from storage + settings audit + forecast + usage labels. Includes minimum-confidence gate logic. Testable against deterministic dummy data. (§21 critical — target ≥ 90% coverage.)
2. **Usage annotation** — `usage_labels` table, REST API, History-chart annotation overlay (drag-select time region → pick label → persist). Backend + frontend + tests.
3. **Model training (continuous)** — scikit-learn training pipeline, model persistence, versioning, accuracy tracking, accuracy gate (reject regressions), minimum-confidence gate. Triggered on new data and on-demand via API.
4. **Inference / suggestion engine** — load trained model, enumerate candidate settings, predict best configuration. Respects minimum-confidence gate (no suggestions below threshold). Supports optional "planned usage labels" for the forecast window. Exposed through the existing automation preview endpoint.
5. **Integration with automation apply path** — dry-run vs. live toggle, ML suggestions appear alongside rule-based proposals with `source: "ml"`; "apply" routes through existing §18/§12 path. Live mode gated behind both the dry-run/live toggle and `SOLARVOLT_ENABLE_CONTROL`.
5. **Model management UI** — training status, model version, validation metrics, minimum-confidence gate progress bar (e.g. "12 of 14 days"), dry-run/live toggle, and a "train now" trigger in Settings.

---

