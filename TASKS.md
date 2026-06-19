# SolarVolt — Deliverables Backlog

Ordered, dependency-aware list of **deliverables** (each a shippable/demoable artifact,
not a whole phase). Work top-down within what's unblocked. See `plan.md` for the spec
and `CLAUDE.md` for the standing brief.

**Status:** `[ ]` todo · `[~]` in progress · `[x]` done · `[-]` deferred/on-demand
When you start a task set it `[~]`; when its *Done when* criteria all hold, set `[x]`.
`Deps:` lists task IDs that must be done first.

**Definition of Done (applies to every deliverable):** ships with unit tests in the same PR
(and a Playwright E2E test when the deliverable adds a user-observable flow unit tests can't
reach); the full suite is green; coverage stays within the §21 gates (backend ≥ 80% overall,
critical-logic modules ≥ 90%, frontend ~70%); the GitHub Actions CI (T021) passes — build
errors, unit-test failures, below-threshold coverage, and **Playwright E2E failures** are all
**hard gates**. See `plan.md` §21 and `CLAUDE.md`.
If the deliverable changes what users can do or how they run/install the app, **update `README.md`
(incl. its Project status notice) in the same PR** — keep the user-facing front door current.

---

## Phase −1 — Register discovery
*(regscan tool is built — `tools/regscan.py`, `tools/README.md`. One deliverable remains.)*

- [x] **T001 · Register-discovery CLI (`regscan.py`)** — scan/report/verify, `--map`,
  `--passive`, `--mock`. Built and documented.
- [x] **T000 · Project docs & license** — user-facing `README.md` (kept current with a Project
  status notice), BSD 3-Clause `LICENSE` (© 2026 Darren Horrocks), `CLAUDE.md`, `TASKS.md`,
  `plan.md`, `.vscode/` debug defaults. README upkeep is part of every deliverable's DoD.
- [x] **T002 · Confirmed sign conventions in the Sunsynk/deye-base profiles** · Deps: —
  - **Deliverable:** `profiles/deye-base.yaml` + `sunsynk-8k-sg05lp1.yaml` with zero
    `sign_unconfirmed` fields; polarity proven against a real capture.
  - **Done:** the `grid-charging-battery` capture resolved it. Unit is **discharge-positive**
    → `battery_power_w` (`scale: -1`) and `battery_current_a` (was wrongly `u16`, now `s16`,
    `scale: -0.01`) negated to canonical **+charge/−discharge** (charge read −3968 W / −73.43 A).
    `grid_power_w` is **import-positive** (+4794 W importing) → already matches canonical
    **+import/−export**, no flip. `sign_unconfirmed` markers removed; `validation:` blocks
    + plan.md §10 updated. Bonus: protocol register [2]=0x0201 decodes to "2.1" (`version_be`),
    confirming the firmware pin and fixing a false-positive in the T032 firmware check.
  - **Still open (minor):** grid **export** polarity assumed s16-negative (import is proven);
    PV1 voltage daytime under load — both covered by the pending **daytime** capture.
  - *Refs: §4, §10, §11.*

## Phase 0 — Skeleton ✅ complete (no hardware; app fully usable on the dummy from here)

- [x] **T010 · FastAPI backend skeleton serving `/api/health`** · Deps: —
  - Async FastAPI app; `/api/health` returns 200 + status payload; config from `.env`/env;
    `SOLARVOLT_ENABLE_CONTROL` read at startup (default `false`); `requirements.txt` pinned;
    run/test commands recorded in `CLAUDE.md`.
  - **Runs from the working copy:** after `git pull` + venv + `pip install -r requirements.txt`,
    `uvicorn … --reload` from the repo root starts the app — no systemd/Docker/hardware; SQLite
    DB defaults to a local file. *Refs: §3, §12, §13.*
- [x] **T011 · Angular + Bootstrap 5.3 admin shell + ThemeService** · Deps: —
  - Standalone-components scaffold builds; fixed header / offcanvas sidebar / fixed footer,
    content the only scroll region; `ThemeService` toggles `data-bs-theme`, persists to
    `localStorage`, defaults to `prefers-color-scheme`; sidebar routes to placeholder
    Now/History/Forecast/Control/Settings.
  - **Bootstrap 5.3 + Bootstrap Icons installed via npm and self-hosted — no CDN.** All CSS/JS/
    fonts/icon assets bundled by the Angular build; app must load with zero outbound requests
    (offline in-home LAN). *Refs: §8, §13.*
- [x] **T012 · Device abstraction interfaces** · Deps: —
  - `Transport`, `DeviceProfile`, `Device` protocols; `Reading` dataclass; canonical metric
    vocabulary (§4) as shared constants; register specifics confined to the Modbus family
    (no `dict[int,int]` above the driver). *Refs: §4, §20.*
- [x] **T013 · YAML profile loader (with `extends` inheritance)** · Deps: T012
  - Parse `profiles/*.yaml` into a `DeviceProfile`; resolve `extends: deye-base`; support
    types/scale/offset/sign/word-order/masks/multi-register; expose `capabilities()` + `info()`.
    Loads `sunsynk-8k-sg05lp1.yaml` without error. *Refs: §4.*
- [x] **T014 · DummyProfile + NullTransport simulator** · Deps: T012
  - Built-in fake inverter, no hardware/wiring; time-of-day-aware synthetic readings (PV bell
    curve, plausible load, battery charge-by-day/discharge-by-night, occasional grid I/O);
    reports the **complete** canonical set; deterministic-seed option for tests; default device
    on a fresh install. (Write path added in T072.) *Refs: §4 (Dummy).*
- [x] **T015 · Device registry** · Deps: T012, T014
  - Hold N devices (each transport×profile), read concurrently, merge by `device_id` into one
    normalized snapshot; absent metrics stay absent. *Refs: §4, §5.*
- [x] **T016 · Async poller** · Deps: T015
  - Polls the registry on an interval, emits a `Reading` stream; poll cadence decoupled from
    downstream consumers; honest stale-data handling on transport errors. *Refs: §10.*
- [x] **T017 · Live API: `/api/live` + `/ws/live`** · Deps: T010, T016
  - REST latest-reading endpoint and WebSocket that pushes each new `Reading`. *Refs: §7.*
- [x] **T018 · Live "Now" view end-to-end on the dummy** · Deps: T011, T017
  - Angular WebSocket service (RxJS `Observable`); a SoC/power gauge updates live from the
    dummy; status pill green/amber/red from `/api/health`; falls back to polling `/api/live`
    if the socket drops. Proves the whole stack with zero hardware. *Refs: §8.*
- [x] **T024 · Playwright E2E harness (full app on the dummy)** · Deps: T018
  - Playwright (TS) project with a fixture that boots the full stack in **dummy mode** on an
    ephemeral port (seed-deterministic) and tears it down; headless in CI. First spec proves the
    **live path**: a `Reading` pushed over the WebSocket updates the gauges in the DOM. Establishes
    the pattern later feature deliverables add E2E to.
  - **Scope rule:** E2E covers only cross-layer, user-observable flows unit tests can't reach;
    decode/encode/energy/forecast/stats/allow-list math stays unit-tested. *Refs: §21, §8.*
- [x] **T019a · `make dev` — one-command working-copy run** · Deps: T010, T011, T014
  - `Makefile` target brings up backend (`uvicorn --reload`) + frontend (`ng serve` proxy, or
    `ng build` served by the backend) together from a fresh clone; dummy device default ⇒ live
    synthetic dashboard with zero config/hardware. This is the CI/contributor path — keep it
    working. *Refs: §13.*
- [x] **T023 · VSCode F5 debugging works for both tiers** · Deps: T010, T011
  - The committed `.vscode/` defaults (launch/tasks/extensions) actually work against the
    scaffold: **F5 → "Full Stack" compound** launches backend under `debugpy` (uvicorn
    `app.main:app`) and frontend in Chrome (after `ng serve` is up), and **breakpoints bind and
    hit on both sides**. Scaffold entry points (`backend/app/main.py`, `frontend/` dev server
    :4200, `./.venv`) match what the configs assume. *Refs: §13.*
- [x] **T021 · GitHub Actions CI with hard gates** · Deps: T010, T011, T014
  - `.github/workflows/ci.yml` runs on every push + PR via the working-copy path (no hardware/
    Docker). Separate backend/frontend jobs. **Hard gates (red on failure, not warnings):**
    (1) build/compile — `pip install` + `ng build` succeed, lint/type errors fail;
    (2) unit tests — `pytest` + frontend suites, any failure fails CI;
    (3) coverage — `pytest-cov` enforces backend ≥ 80% overall / critical-logic ≥ 90%, frontend
    ~70%; below threshold fails the build;
    (4) Playwright E2E (T024) — boot the app in dummy mode, run the integration suite headless,
    any failure fails CI (pass/fail gate, not coverage-measured);
    (5) no-CDN check — grep built frontend for external URLs, fail if any leaked in.
  - Establish the test harness here (`pytest`/`pytest-cov`/`pytest-asyncio`, frontend runner,
    deterministic dummy seed, `regscan` snapshot fixtures) so every later task inherits it.
    Activates once the repo is on GitHub; branch protection requires it. *Refs: §21, §8, §13.*

## Phase 1 — Real instant data

- [x] **T030 · `ModbusRtuSource` transport** · Deps: T012
  - `pymodbus` async serial client over `/dev/ttyUSB*`; config port/baud/slave-id;
    timeouts/retries/backoff; brand-agnostic. *Refs: §4.*
  - **Done:** `app/devices/modbus_rtu.py` (`ModbusRtuConfig` + `ModbusRtuSource`); reads
    holding/input tables, bounded retries with exponential capped backoff, raises
    `TransportError` so the registry degrades the device to stale (§10). Injectable
    client factory + sleep ⇒ fully unit-tested with no hardware (`test_modbus_rtu.py`, 100%).
- [x] **T031 · `SunsynkProfile` reading real data** · Deps: T013, T030, T002
  - Drive the SG05LP1 from `sunsynk-8k-sg05lp1.yaml` over RTU; decode the full canonical set. *Refs: §4.*
  - **Done:** `app/devices/factory.py` pairs `ModbusRtuSource` + `ModbusYamlProfile`;
    env-driven (`SOLARVOLT_MODBUS_PORT` ⇒ real device, else dummy — see `config.py`).
    Canonical `pv_power_w` derived from the per-MPPT powers in `ModbusYamlProfile`.
    Signs now resolved (T002): battery normalized to +charge/−discharge, grid +import/−export.
- [x] **T032 · Firmware-pin mismatch warning at connect** · Deps: T031
  - Read Protocol/MCU/COMM, compare to the profile's pinned firmware, warn on mismatch. *Refs: §4, Decision #1.*
  - **Done:** `app/devices/firmware.py` `verify_firmware()` runs in the app lifespan after
    connect; reads the profile's `info:` identity registers, compares to the YAML `firmware:`
    pin, logs a warning (never blocks) and tells the operator to re-run regscan.
  - *Note:* only `protocol` is currently mapped to a register; MCU/COMM have no address in
    the map yet, so they're skipped (never falsely warned). The comparison auto-covers them
    once addresses are added. *(verified vs the inverter's protocol register; full screen
    cross-check is T033.)*
- [~] **T033 · Validate live readings vs the inverter display** · Deps: T031, T018
  - Cross-check every metric against the unit's own screen; Now dashboard runs on real data;
    record discrepancies as profile fixes. *Refs: §10.*
  - **Partial:** decode pinned against **two real captures** as regression vectors
    (`test_decodes_real_idle_capture…` + `test_decodes_real_grid_charging_capture_signs`)
    — magnitudes and now **signs** match the screen, with the grid-charging energy balance
    (import ≈ load + charge + losses) asserted. The Now dashboard already consumes real data
    via the same registry→poller→WS path once a device is configured.
  - **Remaining (needs the unit + daylight):** live full-screen cross-check with PV producing,
    confirming grid **export** polarity and PV1 voltage under load — the pending daytime capture.

## Phase 2 — Persistence & history ✅ complete

- [x] **T040 · Storage repository + SQLite schema** · Deps: T012
  - Repository abstraction; `samples(ts,device_id,metric,value)` + `rollup_5m/1h/1d`. *Refs: §5.*
  - **Done:** `app/storage/` — `SqliteHistoryRepository` over an `AsyncDb` (one sqlite
    connection pinned to a single worker thread → off the event loop, serialized, no
    cross-thread crash). `samples` (ts epoch REAL) + `rollup_5m/1h/1d` (avg/min/max/last/n).
- [x] **T041 · Migrations on startup** · Deps: T040
  - Versioned schema, migrations run on boot behind the repository so upgrades never lose history. *Refs: §5, §19.*
  - **Done:** `app/storage/migrations.py` — a lightweight versioned migration runner
    (`schema_version` + ordered, additive (version, SQL) steps applied on boot).
  - **Deviation from task name:** uses a hand-rolled runner, **not Alembic**. Rationale:
    Alembic pulls in SQLAlchemy, a heavy dep that fights the project's repeatedly-stated
    Pi-leanness goal; the runner meets the same done-criteria (versioned, on-boot, additive).
    Swapping to Alembic later is contained to the storage package. Documented in the module.
- [x] **T042 · Persist poller output** · Deps: T016, T040
  - Write samples at a persistence rate decoupled from poll rate. *Refs: §5, §10.*
  - **Done:** `app/persistence.py` `PersistenceService` — own cadence
    (`SOLARVOLT_PERSIST_INTERVAL_S`, default 30s), dedups by timestamp, DB errors
    degrade to a warning (never blocks the poll loop).
- [x] **T043 · Aggregator / rollup jobs + retention** · Deps: T042
  - Roll raw→5m→1h→1d on a schedule; prune raw past retention; retention configurable. *Refs: §5.*
  - **Done:** `app/aggregator.py` (pure bucketing, §21 critical, 100% cov) + repository
    `aggregate()`/`prune()`; the persistence service rolls up then prunes raw past
    `SOLARVOLT_RETENTION_DAYS` (default 14). Re-aggregates the open day so in-progress
    buckets stay correct.
- [x] **T044 · History API (`/api/history`)** · Deps: T043
  - Query by metric/range/resolution (raw|5m|1h|1d). *Refs: §7.*
  - **Done:** `GET /api/history` + `GET /api/history/metrics`; epoch or ISO start/end,
    defaults to last 24h; returns ts/value(+min/max/last/n for rollups).
- [x] **T045 · History view + charts** · Deps: T044, T011
  - `ng2-charts` time-series + energy bars; date-range + resolution pickers;
    reusable `<time-series-chart>`. *Refs: §8.*
  - **Done:** `pages/history/` + shared `<app-time-series-chart>` (self-hosted ng2-charts;
    line for power/SoC, bars for `_wh`); metric + resolution + range presets.
- [x] **T046 · Energy accounting** · Deps: T042
  - Wh by integrating power OR diffing daily counters (prefer counters; detect midnight
    reset; handle missed samples). *Refs: §5, §10.*
  - **Done:** `app/energy.py` (§21 critical, 100% cov) — `integrate_wh` (gap-capped
    trapezoid), `counter_to_wh` (reset/jitter-aware), self-consumption/-sufficiency ratios.
    Consumed by the Phase 3 stats engine.
- [x] **T047 · Config DB + Device CRUD (`/api/devices`) + Settings › Devices UI** · Deps: T015, T040, T011
  - Devices table + BMS-topology field; CRUD API exposing status + capabilities; Settings
    page to add/edit/remove devices (dummy preconfigured). *Refs: §5, §7, §8.*
  - **Done:** `devices` table + `DeviceConfigRepository`; registry is **built from the
    config DB** on boot (seeded with the dummy / env-configured device); `GET/POST/PUT/DELETE
    /api/devices` live-update the registry; `pages/settings/` Devices UI.

## Phase 3 — Statistics ✅ complete

- [x] **T050 · Daily/monthly stats engine** · Deps: T043, T046
  - Energy totals, self-consumption %, self-sufficiency/autonomy %. *Refs: §3, §7.*
  - **Done:** `app/stats.py` `StatsService.daily()` — energy per stream (prefers the daily
    `today_*_wh` counters via the 1d rollup `last`, falls back to integrating power),
    self-consumption / self-sufficiency / peak PV / round-trip efficiency (100% cov).
- [x] **T051 · Tariff model + config** · Deps: T047
  - Import & export, each flat *or* time-of-use windows + optional seasonal variants. *Refs: §5, Decision #5.*
  - **Done:** `app/tariff.py` — `RateSchedule` (flat + TOU windows, midnight-wrap), `Season`
    overrides, `Tariff` with dict round-trip; `hourly_deltas` attributes counter energy to
    windows. Stored in the `app_config` table; edited via `PUT /api/stats/config`.
- [x] **T052 · Cost / savings / CO₂ / ROI stats** · Deps: T050, T051
  - Cost & savings from tariffs; CO₂ avoided; payback/ROI. *Refs: §3, §19.*
  - **Done:** `app/economics.py` (100% cov) — import cost / export revenue / net / baseline
    (TOU-priced) / savings / CO₂ avoided, plus `payback_years` + `roi_percent`. Wired into
    `StatsService` (cost via TOU-bucketed hourly deltas).
- [x] **T053 · Stats API + KPI cards** · Deps: T052, T045
  - `/api/stats/daily`; History KPI cards (self-consumption, peak, cost saved, CO₂, RTE). *Refs: §7, §8.*
  - **Done:** `GET /api/stats/daily` + `GET/PUT /api/stats/config`; History page KPI-card row
    + `<app-stat-card>`; tariff/economics editor in Settings.
- [x] **T054 · Inverter fault/alarm decoding** · Deps: T031, T042
  - Profile maps fault/warning registers → human-readable code lists; Now-view fault banner. *Refs: §4, §16.*
  - **Done:** profile `bits` decode gained `flags`/`bit_prefix` → `inverter_fault_codes`
    decodes to Sunsynk `F01..F64` (active bits); `enum` type → `inverter_status` + derived
    `run_state` (on/off-grid). Now-view fault banner + run-state badge.
  - *Note:* no warning register is mapped on this unit (not invented — regscan showed none),
    so `inverter_warning_codes` is omitted until a register is confirmed. Fault *event*
    history (an events table) is deferred; faults are surfaced live (non-numeric ⇒ not a sample).
- [x] **T055 · Battery-health metrics** · Deps: T031
  - Capability-gated SoH / cycles / capacity, round-trip efficiency; battery-detail panel. *Refs: §4, §17.*
  - **Done:** round-trip efficiency in `StatsService`/`economics`; Now-view battery-health
    panel shown only when `battery_soh_pct`/`battery_cycles` are reported.

## Phase 4 — Forecast (Projected) ✅ complete

- [x] **T060 · Open-Meteo client + cache** · Deps: T010
  - Fetch `shortwave_radiation`, cloud cover, `temperature_2m`; cache, refresh a few times/day. *Refs: §6.*
  - **Done:** `app/forecast/openmeteo.py` — async client (injectable `fetch` ⇒ network-free
    tests), 6 h TTL cache; a failed refresh degrades to last-cached/empty + warning (off the
    hot path). `httpx` added to runtime deps.
- [x] **T061 · PV generation model (per array segment)** · Deps: T060, T064
  - POA from GHI via tilt/azimuth; NMOT thermal derate (γ_Pmax, NMOT); sum segments; PR. *Refs: §6.*
  - **Done:** `app/forecast/model.py` (§21 critical) — PSA solar position, Erbs split +
    isotropic transposition, NMOT cell-temp derate, per-segment `kWp×POA×temp×PR`, summed.
    Defaults γ_Pmax −0.26 %/°C, NMOT 41 °C (Decision #4).
- [x] **T062 · Battery trajectory / SoC projection** · Deps: T061, T050
  - Forecast PV − forecast load → projected SoC; flag depletion/full times. *Refs: §6.*
  - **Done:** `app/forecast/battery.py` (§21 critical) — `project_soc` (charge/discharge
    bounded by power limits + SoC window, surplus/deficit to grid) + depletion/full detection;
    load profile = historical average by hour-of-day from the 1h rollups.
- [x] **T063 · Forecast API + Forecast view** · Deps: T062, T045
  - `/api/forecast`; expected-generation curve, projected SoC line. *Refs: §6, §7, §8.*
  - **Done:** `app/forecast/service.py` + `GET /api/forecast` + `GET/PUT /api/forecast/config`;
    `pages/forecast/` view (generation curve, projected-SoC line, depletion/full + expected-today KPIs).
  - **Multi-day report:** `/api/forecast?days=N` (1–7, default 7) + `daily_summary()` ⇒ a
    per-day outlook (expected Wh, SoC min/max, depletion flag); the view has a 1/3/7-day
    horizon selector and a per-day table. Open-Meteo client fetches up to 7 days, cached per range.
  - *Note:* forecast-vs-actual **accuracy** is a lightweight `expected_today_wh` for now; a
    stored-forecast accuracy history is a future refinement.
- [x] **T064 · Array & site spec config** · Deps: T047
  - Settings captures kWp/tilt/azimuth, lat/lon, γ_Pmax & NMOT; multiple segments. *Refs: §5, Decision #4.*
  - **Done:** site/arrays/battery stored in `app_config`; editable in Settings (array-segment
    list editor); `ArraySegment.from_dict` applies the datasheet defaults.

## Phase 5 — Settings display (read-only, ungated)

*Show every device setting and its current value. This is read-only — no register is
written — so it is **not** gated behind `SOLARVOLT_ENABLE_CONTROL` (reading settings is
just more monitoring). The settings register map is already screen-validated in
`profiles/deye-base.yaml` (`settings:` block — work-mode timer, globals, battery). Writing
those settings is Phase 6.*

- [x] **T070 · `SettingsSchema` + `read_settings` (schema + decode current values)** · Deps: T013, T031
  - `Field`/`RepeatingGroup` schema model; profile declares `settings_schema()` + `read_settings()`
    covering the **work-mode timer** (6 slots) + **globals** + **battery**. Decodes live holding
    registers → typed settings. The dummy implements `read_settings`. *Refs: §4, §12.*
  - **Done:** `app/settings_schema.py` (Field/Section/SettingsSchema, 100% cov) + `ModbusYamlProfile`
    `settings_schema()`/`settings_blocks()`/`read_settings()` (built from the validated `settings:`
    map); `DummyProfile` synthesizes the validated cheap-night-rate plan; `Device.read_settings()`
    reads the settings registers via transport then decodes.
- [x] **T071 · Settings read API (`GET …/settings` + `…/settings/schema`)** · Deps: T070
  - Expose the schema (form spec) + current decoded values per device. **Ungated** —
    read-only; the `SOLARVOLT_ENABLE_CONTROL` flag is not required to view settings. *Refs: §7, §12.*
  - **Done:** `GET /api/devices/{id}/settings/schema` + `…/settings` (404 unknown device); device
    list advertises `settings: bool`. Tested ungated (control off → still 200).
- [x] **T072 · Settings display UI (read-only)** · Deps: T071, T011
  - Schema-driven read-only view of every device setting + current value (Control page; reused by
    the Phase-6 edit form). Value formatting per field type (enum→label, bool→Yes/No, units). *Refs: §8.*
  - **Done:** `pages/control/` renders the schema as section cards (repeating timer-slots as a
    table) via a reusable presentational `<app-setting-value>` (no innerHTML). Playwright E2E
    drives the full stack (dummy decode → API → DOM). Editing arrives in Phase 6.

## Phase 6 — Settings control / write-back ✅ complete (OFF by default; see CLAUDE.md §12 safety rules)

*Add the ability to **modify** the settings surfaced in Phase 5. Gated behind
`SOLARVOLT_ENABLE_CONTROL`: when off, the write endpoint 403s and the edit UI/“control”
capability are suppressed — but the Phase-5 read-only view stays available. All seven §12
write-safety rules apply (allow-list, validation, confirm, read-back, etag, audit, dummy-first).*

*Status-code note: a failed `If-Match` returns **412 Precondition Failed** (the correct HTTP
semantics) rather than 409; **409 Conflict** is reserved for a read-back mismatch (the write
didn't verify ⇒ rollback signal). Validation ⇒ 422, control disabled ⇒ 403.*

- [x] **T073 · `write_registers` + write-register allow-list** · Deps: T030
  - Transport write path; enforce the profile allow-list so only the holding registers declared
    in the settings map are writable — never arbitrary addresses through the API. *Refs: §12.*
- [x] **T074 · `encode_settings` + dummy in-memory writes** · Deps: T070, T014
  - Profile `encode_settings()` (typed settings → register writes, bounds/enum validation); the
    dummy applies writes in-memory (mirroring its `read_settings`) so the whole
    validate→write→read-back flow is testable with zero risk. *Refs: §4, §12.*
- [x] **T075 · `apply_settings` flow** · Deps: T073, T074
  - validate → encode → write → re-read → verify → return confirmed state; atomic-ish slot
    writes; etag/`If-Match` concurrency (409 on stale). *Refs: §4, §12.*
- [x] **T076 · Control write API (flag-gated)** · Deps: T075
  - `PUT …/settings`; 403 + write/“control” capability suppressed when
    `SOLARVOLT_ENABLE_CONTROL` is off (the T071 read endpoints stay available either way). *Refs: §7, §12.*
- [x] **T077 · Schema-driven Control UI (edit + diff + confirm)** · Deps: T076, T072, T024
  - Extend the Phase-5 read-only form with **editing**: current→proposed diff + confirm dialog;
    read-back result / rollback on mismatch; edit controls shown only when the flag is on. Works
    against the dummy first.
  - **Playwright E2E (high value):** edit a work-mode-timer slot → see the diff → confirm → assert
    the read-back-verified confirmed state renders (full validate→confirm→write→read-back loop
    against the dummy's in-memory write path, control enabled in the test env). *Refs: §8, §12, §21.*
- [x] **T078 · Write audit log** · Deps: T075
  - Record every write (when / source client / old→new / result). No "who" (no accounts). *Refs: §12.*

## Phase 7 — Alerts & integrations ✅ complete (core; remaining integrations in Later)

*Alerts engine + inbox + Prometheus shipped. The standalone egress publishers (MQTT/HA,
PVOutput, a readings webhook), the extra notification channels, and the rule-editor UI were
deferred — tracked under "Later — Integrations & notifications" below.*

- [x] **T080 · Alert rule engine** · Deps: T042
  - User conditions on any canonical metric/state (low SoC, device offline/stale, inverter fault,
    over-temp) with thresholds, hysteresis, debounce, quiet hours; sensible defaults shipped on.
    Pure engine (`app/alerts/engine.py`, 98% covered) + evaluation service off the hot path. *Refs: §15.*
- [x] **T081 · Notification channels** · Deps: T080
  - Pluggable channel seam + **in-app inbox** + **generic webhook** (failure→warning, off the hot
    path). More channels (email/Telegram/ntfy/Pushover) → Later (L10). *Refs: §15.*
- [x] **T082 · Alert API + inbox UI** · Deps: T080, T011
  - `/api/alerts` (+ack/snooze) and `/api/alert-rules` CRUD; inbox with active/history + ack/snooze;
    header bell badge. Rule-editor UI → Later (L11; rules seed with defaults, editable via API). *Refs: §7, §15.*
- [x] **T085 · Prometheus `/metrics` endpoint** · Deps: T016
  - Exposes live numeric metrics (`solarvolt_<metric>{device=…}`) for Grafana users. *Refs: §7, §14.*

## Phase 8 — Polish & operational ✅ complete (first-run wizard moved to Later/L13)

- [x] **T091 · Backup/restore + CSV/Excel export** · Deps: T044
  - `/api/backup` (VACUUM-INTO snapshot download), `/api/restore` (validated upload → atomic
    live-DB swap on the single DB thread), `/api/export` (CSV of any metric/range). UI: Backup &
    data card in Settings (download + restore); CSV export button on History. *Refs: §7, §19.*
- [x] **T092 · Diagnostics page + `/api/diagnostics`** · Deps: T030, T040
  - `/api/diagnostics` + Diagnostics page: build/schema version, DB size, rollup lag, active
    alerts, and per-device online + Modbus comms stats (transactions/failures/retries, last
    error, RTT — tracked in `ModbusRtuSource`). *Refs: §7, §19.*
- [x] **T093 · Localization & formatting** · Deps: T011
  - Configurable **locale** (drives date/number formatting) persisted in `app_config` +
    localStorage; `LOCALE_ID` resolved at bootstrap, formatting data for en-US/en-GB/de/fr/es
    bundled (no CDN). `/api/preferences` + a Formatting card in Settings. Currency stays with
    the tariff; UI strings remain English (scaffolding in place). *Refs: §19.*
- [x] **T094 · Installable PWA** · Deps: T018
  - Self-hosted `manifest.webmanifest` + SVG icon + hand-written `sw.js` (network-first
    navigations, stale-while-revalidate assets, never caches /api·/ws); registered in
    production only (main.ts, `isDevMode` guard) so it can't fight `ng serve`. No new deps,
    no CDN. *Refs: §19.*
- [x] **T095 · Grid-outage / backup-power event log** · Deps: T042
  - `grid_events.py`: infer grid presence (run_state / grid voltage) + a pure transition
    detector → log outage_start/outage_end. `GridEventService` runs off the poller (off the hot
    path); `/api/grid-events` + a timeline on the Diagnostics page. *Refs: §19.*
- [x] **T096 · Calibrate performance-ratio factor** · Deps: T063, T046
  - `model.calibrate_pr()` scales the PR by measured/modelled PV (clamped); `ForecastService
    .calibrate()` compares today's expected-so-far vs `today_pv_wh`. `/api/forecast/calibrate`
    + a "suggest from history" button on the Settings PR field. *Refs: §6, §19.*
- [x] **T097 · Inverter clock sync** · Deps: T076
  - Reads the inverter RTC and shows drift vs system time (Now page); **Sync** correction gated
    behind the control flag AND confirmed-writable RTC registers. Dummy: synthetic drift +
    in-memory sync; real SG05LP1: candidate RTC regs 22–24 read-only until pinned. *Refs: §19.*

## Phase 9 — Deployment, packaging & release (ship to real hardware / users)

*Not needed for dev on the dummy (the working-copy `make dev` path covers Phases 0–8) —
relocated here from Phase 0. These matter once running unattended on a Pi or cutting
versioned releases.*

- [ ] **T019 · Native install path** · Deps: T010, T011
  - `systemd` unit (`solarvolt.service`), `install.sh` (venv, frontend build, unit install,
    `dialout` group, udev rule pinning the USB-RS485 adapter), `EnvironmentFile` config,
    `Makefile`. FastAPI serves the built Angular static files (one process/port). *Refs: §13.*
- [-] **T020 · Docker/Compose path (optional)** · Deps: T010, T011
  - Multi-stage `Dockerfile` + `docker-compose.yml`, multi-arch (arm64+amd64), serial
    passthrough, named volume for the DB, same env flags. *Refs: §13.*
- [ ] **T022 · Tag-triggered release workflow → GitHub Releases** · Deps: T021, T019
  - `.github/workflows/release.yml` triggers on `push` of tags matching **`version/*`**
    (e.g. `version/1.0`). Parses **`x.y`** from the tag as the single source of truth.
  - **Re-runs the CI hard gates first** (build/tests/coverage/no-CDN, §21) — no release from a
    red build. Then: stamp `x.y` into the app (footer §8 + `/api/health`); build the versioned
    bundle `solarvolt-x.y.tar.gz` (prod `ng build` + backend + `install.sh` + systemd unit);
    optionally push multi-arch Docker image to GHCR tagged `x.y`/`latest`.
  - **Creates a GitHub Release titled `x.y`** with auto-generated notes (changelog since the
    previous `version/*` tag) and uploads the artifacts. Activates once the repo is on GitHub. *Refs: §13, §21.*

## Later — More vendors, transports & automation (on demand)

- [-] **L01 · `SolarmanV5Source` transport** — `pysolarmanv5` TCP to the logger; reuses the
  exact same profiles (SolarmanV5 wraps the identical Modbus payload). *Refs: §4, §20.*
- [-] **L02 · Sol-Ark & Deye profiles** — thin `extends: deye-base` profiles, near-free once
  the base map is validated in Phase 1. *Refs: §4, §20.*
- **L03 · Smart automation & scheduling** — tariff+forecast-driven auto-scheduling of the
  work-mode timer; opt-in, separate automation flag, **dry-run/suggest-only first**; built
  entirely on the §12 safeguards. *Refs: §18.* Split into deliverables, risk-increasing
  (suggest-only before any write), each shippable on its own:
  - [x] **L03a · Automation planning engine (pure, suggest-only core)** · Deps: T051, T060
    - **Deliverable:** `backend/app/automation/planner.py` — a pure function that, given the
      import `RateSchedule` (§5 tariff), `BatterySpec`, current SoC, current timer slots, and
      tomorrow's expected PV/load Wh (§6 forecast), proposes timer-slot changes (cost-arbitrage:
      force grid-charge in the cheapest window to a forecast-aware target SoC; reserve the battery
      for the peak) with a per-change rationale and a first-order estimated daily saving.
    - **Done:** pure (no DB/I/O/writes). `plan_timer()` + `cheapest_window`/`peak_window`/
      `overnight_target_soc_pct` (reuses `tariff.RateSchedule` + `forecast.BatterySpec`). No-action
      paths covered: flat tariff, spread below threshold, solar-covers-load, already-optimal.
      `test_automation_planner.py` (13 tests) incl. midnight-wrap window + saving math; module
      **100%** coverage; full backend suite green (278 passed). *Refs: §18, §5, §6.*
  - [ ] **L03b · Suggest-only plan API** · Deps: L03a, T047, T060
    - `GET /api/automation/plan` wires the engine to the live forecast/tariff/device and returns the
      proposed plan + current→proposed diff. **Never writes** — always available, no flag.
      *Refs: §18, §12.*
  - [ ] **L03c · Automation UI (suggest-only)** · Deps: L03b
    - A page/panel showing the proposed daily plan, per-slot current→proposed diff, projected
      saving and rationale — "what it would do," read-only. *Refs: §18, §8.*
  - [ ] **L03d · Opt-in auto-apply (scheduler + write)** · Deps: L03c, T076
    - Only when `ENABLE_CONTROL` is on (the single gate on register writes): a scheduler (+ manual
      "apply now") that applies the plan through the §12 path (`control.apply_settings`:
      validate→write→read-back→audit). Playwright E2E of the full round-trip on the dummy.
      *Refs: §18, §12.*
  - **L03e · User-authored rule-based automation** — condition→action rules that set inverter
    settings (e.g. "on weekends set work-mode slot 1 target SoC to 80%"); rules are **combinable**
    (every matching rule contributes) and **prioritised** (highest priority wins a conflicting
    write). Extends the `automation` package alongside the cost-arbitrage planner. Safety: an
    action applies only when **both** its rule and the action are affirmatively `enabled` (both
    default off); a disabled rule/action is shown as a **preview** ("would set X now, if running").
    Writable targets come from the **inverter profile** allow-list (safe subset → `ok`, writable
    but riskier → `at_risk`, not writable → `blocked`/never applied). Sliced:
    - [x] **L03e-1 · Pure rules engine** · Deps: L03a
      - **Done:** `app/automation/rules.py` — `AutomationRule`/`Condition`/`Action`/`Target` model
        (JSON round-trip), conditions `day_of_week`/`time_window`/`date_range`(season)/`metric`
        (reuses `alerts.engine.compare`)/`tariff_window` (reuses `tariff.RateSchedule`), per-rule
        all/any match, `evaluate_rules()` that combines matching rules and resolves same-target
        conflicts by priority (losers kept in `overridden` for transparency), enable/preview
        semantics (`active`/`will_apply`) and `AllowList` status. Pure (no DB/IO/writes).
        `test_automation_rules.py` (22 tests) incl. midnight/year wraps, priority + ties, allow-list
        block, serialisation; module **100%**; full backend suite green (319 passed). *Refs: §18.*
    - [x] **L03e-2 · Persist rules + suggest-only API** · Deps: L03e-1, T071
      - Store rules in the DB; `GET/PUT/DELETE /api/automation/rules`; `GET /api/automation/preview`
        wires the engine to the live clock/metrics/forecast/tariff + the profile-derived allow-list
        and returns the decision (what each rule would set now, armed or preview). **Never writes.**
        Profile gains an `automation_safe` marking on its settings allow-list. *Refs: §18, §12.*
      - **Done:** `AutomationService` (`app/automation/service.py`) stores rules as a JSON list in
        `app_config`, builds the `EvalContext` from the clock + the device's live snapshot metrics +
        the import tariff (`Tariff.schedules_for`), and derives the `AllowList` from the device
        settings schema. `FieldSpec` gained `automation_safe`; the deye-base + dummy work-mode-timer
        scheduling fields (start/power/target SoC/grid-charge) are marked safe. Endpoints (no flag —
        always available): `GET/PUT/DELETE /api/automation/rules`, `GET /api/automation/options`
        (condition kinds/ops/metrics + settable targets tagged ok/at_risk), `GET /api/automation/preview`
        (the decision — armed changes + previews, **never writes**). `test_automation_api.py`
        (CRUD+validation, options safety status, preview armed/preview/metric-condition). `rules.py`
        100%, `service.py` 98%. *(Rule-editor UI is L03e-4; forecast-derived metrics in the context
        are a later enrichment.)* **Gating revised in L03e-3** — the originally-planned
        `SOLARVOLT_ENABLE_AUTOMATION` flag was dropped; automation is always available and only
        register *writes* are gated, by `SOLARVOLT_ENABLE_CONTROL`.
    - [x] **L03e-3 · Opt-in apply (scheduler + write)** · Deps: L03e-2, T076
      - Gated by `ENABLE_CONTROL` only (the single gate on register writes — `ENABLE_AUTOMATION` was
        dropped): a background scheduler + an "apply now" endpoint write the armed winning changes
        through `control.apply_settings` (validate→write→read-back→audit). *Refs: §18, §12.*
      - **Done:** `AutomationService.apply()` coalesces the decision's armed, non-blocked winners per
        `(section, slot)` and pushes each through `control.apply_settings`; failures are recorded and
        reported but never abort the rest. Every write is audited (`source="automation:manual"` /
        `"automation:scheduler"`). `apply_all()` + a cancellable `start()/stop()` loop
        (`automation_interval_s`, default 300s) run it on a schedule — started in `lifespan` **only
        when `ENABLE_CONTROL`** is on. New `POST /api/automation/apply` (403 without control);
        `/api/health` advertises `automation_can_write`. **Removed** `SOLARVOLT_ENABLE_AUTOMATION`
        (config + all endpoints/UI/e2e). Frontend: "Apply now" button (shown under
        `automation_can_write`) + a preview-only banner otherwise; `applyAutomation()` API.
        `test_automation_service.py` (10: coalesce, read-back+audit, failure-continue, scheduler
        tick/stop) + `test_automation_api.py` (control-gated apply, real write+audit, health flag);
        `service.py` 98%. E2E extended: build armed rule → preview "would apply" → Apply now →
        success banner (real dummy write). Backend 338 passed (96%), frontend 132, e2e 14.
    - [x] **L03e-4 · Rule-editor UI + live preview** · Deps: L03e-2
      - Build/edit/prioritise rules; per-rule and per-action enable; a live "what it would do now"
        panel; current→proposed diff with the safe/at-risk/blocked badge. *Refs: §18, §8.*
    - [ ] **L03e-5 · Absorb alerts into automation (notify + alert action types; retire AlertService)** · Deps: L03e-3, L10
      - The standalone `AlertRule`/`AlertEngine`/`AlertService` is replaced by automation rules that
        carry `notify` and `alert` action types alongside the existing `set_setting` type. One rule
        engine, one editor, all output types. *Refs: §18, §15.*
      - Sub-tasks (implement in order, ask before each):
        - [ ] **L03e-5a · Engine: add action types** — Extend `Action` in `rules.py` with `action_type`
          (`"set_setting"` | `"notify"` | `"alert"`), `channels: list[str]`, `message: str`,
          `severity: str`, `debounce_s: float`. `settings_to_apply()` filters to `set_setting` only.
          Add `notify_actions()` + `alert_actions()` on `AutomationDecision`. Move the `compare`
          helper into `rules.py` (was imported from `alerts.engine`). Add `__stale_s__` /
          `__fault_count__` as resolved-by-service synthetic keys documented in `EvalContext`.
        - [ ] **L03e-5b · Service: wire dispatch + debounce** — `AutomationService` resolves
          `__stale_s__` and `__fault_count__` into `EvalContext.metrics`. After each evaluation, for
          every armed `notify` action: check debounce, dispatch via `channels.dispatch()`, swallow
          failures. For every armed `alert` action: check debounce, insert inbox row via
          `AlertRepository`. Track per-(rule-id, action-index) last-fire epoch in service state.
          Seed default automation rules (low-SoC, device-stale, inverter-fault) as `notify`+`alert`
          actions on first start (replacing `AlertService.seed_rules`).
        - [ ] **L03e-5c · API: remove alert-rules CRUD; keep inbox + channels** — Delete
          `GET/PUT/DELETE /api/alert-rules` and `GET /api/alert-rules/options` endpoints. Keep all
          `/api/alerts` inbox endpoints (ack/snooze) and all `/api/alert-channels` endpoints.
          Update `/api/automation/options` to return available notification channels + severity list.
          Remove `AlertService` from `lifespan`; `AutomationService` handles evaluation.
        - [ ] **L03e-5d · Frontend: automation editor gets notify/alert actions; Alerts page = inbox only** —
          Action-type picker in the rule editor ("Set setting" / "Send notification" / "Create in-app alert").
          For `notify`: channel multi-select, message, severity, debounce field. For `alert`: severity,
          message, debounce. Remove the Rules tab from the Alerts page (rule authoring is in Automation);
          Alerts page becomes inbox-only (active/history, ack/snooze, bell badge unchanged). Remove
          alert-rules API calls from `api.service.ts`.
        - [ ] **L03e-5e · Remove alerts engine + service** — Delete `backend/app/alerts/engine.py`
          and `backend/app/alerts/service.py`. Update `alerts/__init__.py`. Delete or fold
          `test_alert_engine.py` and `test_alert_api.py` alert-rules tests (inbox + channel tests stay).
          Update `main.py` imports. `compare` now lives in `automation/rules.py`.
- [-] **L04 · More vendors / protocol families** — Growatt/Solis/Sungrow/… (new YAML each);
  generic SunSpec profile; text-command family (Voltronic/Must) + Victron family each carry a
  one-time transport+profile-contract cost, then siblings are cheap. *Refs: §20.*

## Later — Post-MVP features (on request)

*Captured ideas, not yet scheduled. Both assume the core (Phases 0–4) is in.*

- [-] **L05 · Import historical data from a Solar Assistant backup** · Deps: T040, T043, T046
  - **Deliverable:** a one-off importer (CLI + an upload in Settings) that ingests a
    [Solar Assistant](https://solar-assistant.io) backup, maps its series to our **canonical
    metric vocabulary** (§4), bulk-loads into `samples`, and re-runs the rollups — so people
    migrating off Solar Assistant keep their history.
  - **Backup format:** a `tar.gz` of **metadata files + `.tsm` files** → SA stores its
    time-series in **InfluxDB**, and `.tsm` = InfluxDB's *Time-Structured Merge* shard format
    (the metadata is the Influx catalog/retention info). So the importer reads InfluxDB data,
    not CSV. Realistic ingestion paths, cheapest-first:
    1. **`influx_inspect export … -out <lineprotocol>`** → parse InfluxDB **line protocol**
       (simple text: `measurement,tags field=val ts`) → map → load. Needs the `influx_inspect`
       binary but no running server; preferred.
    2. Restore the backup into a throwaway **InfluxDB** instance and query it out (heavier; pulls
       in InfluxDB as a migration-time dependency).
    3. Parse raw **`.tsm`** directly (documented format, but fiddly — last resort).
  - **Done when:** a real SA backup imports into a fresh DB and History/Stats show the
    back-filled data; import is **idempotent** (re-running doesn't double-count) and reports
    rows imported / skipped / unmapped.
  - **Confirmed against a real backup** (`horrocks-2026-06-18`, ~4 weeks 22 May–18 Jun 2026):
    it's an **InfluxDB 1.x portable backup** — sets of `*.meta` + `*.manifest` + `*.sNN.tar.gz`,
    each tar holding `solar_assistant/autogen/<shard>/*.tsm` (DB `solar_assistant`, RP `autogen`,
    6 weekly shards). TSM blocks are compressed → not greppable; needs Influx tooling to read.
    `influx_inspect`/`influxd` aren't installed, but **docker + go are** → path 2 (restore into
    `influxdb:1.8` then `influx_inspect export` to line protocol) is the pragmatic route; it costs
    a ~250 MB image pull at migration time.
  - **Mapping pinned** (SA measurement, field `combined` → canonical): `PV power`→`pv_power_w`,
    `Battery power`→`battery_power_w`, `Battery state of charge`→`battery_soc_pct`,
    `Battery voltage/current/temperature`→`battery_voltage_v`/`_current_a`/`_temp_c`,
    `Grid power`→`grid_power_w`, `Grid voltage/frequency`→`grid_voltage_v`/`grid_frequency_hz`,
    `Load power`→`load_power_w`, inverter/AC temp+voltage where present. **Skip** `PV power
    predicted` (a forecast, not measured) and the `* hourly` CQ energy series (we derive energy
    from integrated power in the stats/energy layer — keep it internally consistent).
  - **Three gotchas to handle:** (1) **Sign conventions** — verify SA vs canonical polarity
    (`battery_power_w` +charge/−discharge, `grid_power_w` +import/−export) against a known
    midday window before committing; flip per-metric as needed (same risk class as profile decode,
    cf. T002). (2) **Raw retention prunes after 14 days but rollups are kept forever (T043)** — so
    backfill must **write the 5m/1h/1d rollups directly** for the whole window (reuse the pure
    `aggregator.bucket_rows()` over each `INTERVALS` width and upsert; bypass the watermark-based
    `aggregate()` which isn't built for bulk weeks-old backfill), and write raw `samples` only for
    the last 14 days; then set the rollup watermark to "now". (3) **Volume** — SA logs ~every 5 s
    (~5 M+ rows over 4 weeks) → **downsample to 1-minute** on import.
  - *Build note:* `tools/import_solar_assistant.py` — offline, idempotent (upsert), with
    `--db/--device-id/--resolution/--since/--until/--dry-run`; attach to the real device id
    (e.g. `sunsynk`), not `dummy`. Tests use a small hand-written **line-protocol fixture** (no
    docker/hardware) covering mapping, sign-flips, downsampling and rollup backfill. Reuse the
    energy-counter handling (§5) for any cumulative series. *Refs: §5, §19.*

- [-] **L13 · First-run setup wizard** *(was T090)* · Deps: T047, T064, T051
  - Guided onboarding: device (dummy preselected), location, array segments, battery, tariffs —
    so a fresh install reaches a useful state without hand-editing config. Settings already
    expose every piece (devices/forecast/tariff); this is the guided-flow wrapper. *Refs: §19.*

- [-] **L06 · Customisable dashboards (incl. the home/Now dashboard)** · Deps: T018, T045, T047
  - **Deliverable:** a widget-based dashboard the user can arrange — pick which cards / gauges /
    charts appear, reorder/resize them, and **edit the home (Now) view itself**; optionally
    multiple named dashboards. Layout persists in the config DB (`app_config`) — single
    household, no auth, so one layout set per install (§3).
  - **Done when:** a user can add/remove/rearrange widgets on the Now page and the layout
    survives reload; widgets are driven by the canonical metrics + existing reusable components
    (`metric-card`, `soc-gauge`, `time-series-chart`, `stat-card`) via a small widget registry.
  - *Notes:* larger UX effort (edit mode + layout model + a drag/grid lib, self-hosted per §8 —
    no CDN). Keep presentational widgets dumb; the dashboard config is just data. *Refs: §8.*

## Later — Integrations & notifications (deferred from Phase 7, on request)

*The alerting core (engine + inbox + Prometheus) shipped in Phase 7; these are the remaining,
self-contained egress/notification pieces — each additive, off the hot path, brand-independent.*

- [-] **L07 · MQTT publisher + Home Assistant auto-discovery** *(was T083)* · Deps: T016
  - Publish each normalized `Reading` + per-device status to a broker; emit HA MQTT discovery
    configs so every metric appears as an HA sensor with zero manual YAML. *Refs: §14.*
- [-] **L08 · PVOutput.org upload** *(was T084)* · Deps: T050
  - Optional periodic upload (generation, consumption, SoC, temperature); API key + system id
    in Settings. *Refs: §14.*
- [x] **L09 · Generic outbound readings/events webhook** *(was T086)* · Deps: T016
  - Periodic POST of readings/events to a user URL (Node-RED/IFTTT/custom). Alert egress is
    already covered by the Phase-7 webhook channel; this adds the readings stream. *Refs: §14.*
  - **Done:** `app/integrations/readings_webhook.py` `ReadingsWebhookService` — own background
    cadence like persistence/alerts, re-reads its config each tick (URL/interval/enabled live),
    POSTs `{"type":"readings", …snapshot}`, **off the hot path** (a dead endpoint is logged and
    swallowed, never blocks polling). Config in the `readings_webhook` app-config blob; injectable
    `post` ⇒ network-free tests. `GET/PUT /api/integrations/readings-webhook` (+ interval clamp ≥5s)
    and `POST …/test` (send one now, surface failures). Settings › *Outbound readings webhook* card
    (URL/interval/enabled + Save + Send test). `test_readings_webhook.py` (service + API, 92% module;
    only the real-httpx glue uncovered); full backend suite green (287 passed, 95% cov).
- [x] **L10 · More notification channels** *(remainder of T081)* · Deps: T081
  - email (SMTP), Telegram, ntfy, Pushover/Gotify — all webhook-shaped, slotting in behind the
    existing channel seam; selectable per rule. *Refs: §15.*
  - **Done:** `app/alerts/channels.py` gains `Telegram`/`Ntfy`/`Gotify`/`Pushover`/`Email` channels
    behind the one `Channel` seam (HTTP ones share the injectable `post`; SMTP uses stdlib `smtplib`
    via `asyncio.to_thread` + an injectable `send_email` — **no new dep**). Shared `format_alert()`
    builds title/body; per-severity priority mapped to each provider's scale. `build_channels` only
    enables a channel when its required fields are present. `GET/PUT /api/alert-channels` (config +
    which are fully `configured`) reloads the engine on save; `POST /api/alert-channels/{name}/test`
    sends a synthetic alert. The rule-editor channel list (`/api/alert-rules/options`) now reflects
    the **configured** channels, so they're selectable per rule. Settings › *Notification channels*
    card (per-provider fields + per-channel Test). Off the hot path — a dead channel is logged and
    swallowed. Tests: `test_alert_channels.py` (each channel's request shape + SMTP message build +
    dispatch swallow) and channel-config/test API in `test_alert_api.py`; channels module 97%, full
    backend suite green (296 passed, 95% cov); frontend 124 passed. *No `https://` literal ships in
    the bundle (no-CDN gate green) — provider defaults live server-side.*
- [x] **L11 · Alert rule-editor UI** *(remainder of T082)* · Deps: T082
  - Create/edit/delete alert rules from the Alerts page (the API + engine already support it;
    rules currently seed with sensible defaults and are editable via `/api/alert-rules`). *Refs: §15.*
  - **Done:** Alerts page gains an **Inbox | Rules** tab switch; the Rules tab lists every rule
    (enable/disable switch, severity badge, metric/op/threshold summary) with an inline add/edit
    form (metric/op/severity/device dropdowns, threshold/hysteresis/debounce, quiet-hours, message,
    channels). Saving PUTs to `/api/alert-rules/{id}` (engine reloads next tick); delete via DELETE.
    New backend `GET /api/alert-rules/options` feeds the dropdowns (canonical vocabulary + the two
    synthetic engine keys + ops/severities/channels). **Ungated** (rule editing isn't behind the
    control flag). Frontend unit tests (list/create/validate/toggle/delete) + Playwright E2E
    (create→list→delete on the dummy); frontend suite 123 green, e2e green.
- [-] **L12 · Fault-event history log** *(deferred from T054)* · Deps: T042
  - An events table logging inverter fault / run-state transitions so intermittent faults are
    catchable after the fact (today faults are surfaced live only). *Refs: §16.*
