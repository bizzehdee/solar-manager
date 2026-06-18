# Solar Manager — Deliverables Backlog

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
    `SOLAR_MANAGER_ENABLE_CONTROL` read at startup (default `false`); `requirements.txt` pinned;
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
    env-driven (`SOLAR_MANAGER_MODBUS_PORT` ⇒ real device, else dummy — see `config.py`).
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
    (`SOLAR_MANAGER_PERSIST_INTERVAL_S`, default 30s), dedups by timestamp, DB errors
    degrade to a warning (never blocks the poll loop).
- [x] **T043 · Aggregator / rollup jobs + retention** · Deps: T042
  - Roll raw→5m→1h→1d on a schedule; prune raw past retention; retention configurable. *Refs: §5.*
  - **Done:** `app/aggregator.py` (pure bucketing, §21 critical, 100% cov) + repository
    `aggregate()`/`prune()`; the persistence service rolls up then prunes raw past
    `SOLAR_MANAGER_RETENTION_DAYS` (default 14). Re-aggregates the open day so in-progress
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

## Phase 5 — Control / write-back (OFF by default; see CLAUDE.md safety rules)

- [ ] **T070 · `write_registers` + write-register allow-list** · Deps: T030
  - Transport write path; enforce profile allow-list so only declared holding registers are writable. *Refs: §12.*
- [ ] **T071 · `SettingsSchema` + Sunsynk work-mode-timer settings** · Deps: T013
  - `Field`/`RepeatingGroup` schema; profile `settings_schema`/`read_settings`/`encode_settings`
    for 6 timer slots + globals (timer_enabled, grid_charge, work_mode); constraints in schema. *Refs: §4, §12.*
- [ ] **T072 · Dummy accepts writes in-memory** · Deps: T014, T071
  - Dummy implements the control path (mirrors a work-mode-timer schema) so the full
    validate→write→read-back flow is testable with zero risk. *Refs: §4, §12.*
- [ ] **T073 · `apply_settings` flow** · Deps: T070, T071
  - validate → encode → write → re-read → verify → return confirmed state; atomic-ish slot
    writes; etag/`If-Match` concurrency (409 on stale). *Refs: §4, §12.*
- [ ] **T074 · Control API (flag-gated)** · Deps: T073
  - `GET …/settings/schema`, `GET …/settings`, `PUT …/settings`; 403 + hidden capability when
    `SOLAR_MANAGER_ENABLE_CONTROL` is off. *Refs: §7, §12.*
- [ ] **T075 · Schema-driven Control UI** · Deps: T074, T011, T024
  - Generic `<schema-form>`/`<schema-field>` builder renders any device's schema; current→proposed
    diff + confirm dialog; read-back result / rollback on mismatch. Works against the dummy first.
  - **Playwright E2E (high value):** edit a work-mode-timer slot → see the diff → confirm → assert
    the read-back-verified confirmed state renders (full validate→confirm→write→read-back loop
    against the dummy's in-memory write path, control enabled in the test env). *Refs: §8, §12, §21.*
- [ ] **T076 · Write audit log** · Deps: T073
  - Record every write (when / source client / old→new / result). No "who" (no accounts). *Refs: §12.*

## Phase 6 — Alerts & integrations (off the hot path, brand-independent)

- [ ] **T080 · Alert rule engine** · Deps: T042
  - User conditions on any canonical metric/state (low SoC, device offline/stale, inverter fault,
    forecast depletion, over-temp) with thresholds, hysteresis, debounce, quiet hours;
    sensible defaults shipped on. *Refs: §15.*
- [ ] **T081 · Notification channels** · Deps: T080
  - Pluggable: email (SMTP), Telegram, ntfy, Pushover/Gotify, webhook, in-app; selectable per rule. *Refs: §15.*
- [ ] **T082 · Alert API + inbox UI** · Deps: T080, T011
  - `/api/alerts`, `/api/alert-rules` CRUD; inbox with ack/snooze/history; header bell badge. *Refs: §7, §15.*
- [ ] **T083 · MQTT publisher + Home Assistant auto-discovery** · Deps: T016
  - Publish each `Reading` + per-device status; emit HA discovery configs (zero manual YAML). *Refs: §14.*
- [ ] **T084 · PVOutput.org upload** · Deps: T050
  - Optional periodic upload (generation, consumption, SoC, temp); API key + system id in Settings. *Refs: §14.*
- [ ] **T085 · Prometheus `/metrics` endpoint** · Deps: T016
  - Expose live metrics for Grafana users. *Refs: §7, §14.*
- [ ] **T086 · Generic outbound webhook** · Deps: T016
  - POST readings/events to a user URL (Node-RED/IFTTT/custom). *Refs: §14.*

## Phase 7 — Polish & operational

- [ ] **T090 · First-run setup wizard** · Deps: T047, T064, T051
  - Guided onboarding: device (dummy preselected), location, array segments, battery, tariffs. *Refs: §19.*
- [ ] **T091 · Backup/restore + CSV/Excel export** · Deps: T044
  - One-click SQLite backup/restore in UI; `/api/export`; export current History view. *Refs: §7, §19.*
- [ ] **T092 · Diagnostics page + `/api/diagnostics`** · Deps: T030, T040
  - Per-device Modbus comms stats (success/timeout/retry, last error, RTT), DB size, rollup lag;
    structured level-configurable logging. *Refs: §7, §19.*
- [ ] **T093 · Localization & formatting** · Deps: T011
  - Configurable currency, units, date/time format, timezone; i18n scaffolding (English ships first). *Refs: §19.*
- [ ] **T094 · Installable PWA** · Deps: T018
  - Manifest + service worker; installs to phone home screen; rides out brief network blips. *Refs: §19.*
- [ ] **T095 · Grid-outage / backup-power event log** · Deps: T042
  - Detect & log grid loss/return (islanding) from grid metrics; timeline view. *Refs: §19.*
- [ ] **T096 · Calibrate performance-ratio factor** · Deps: T063, T046
  - Tune PR empirically against measured history. *Refs: §6, §19.*
- [ ] **T097 · Inverter clock sync** · Deps: T074
  - Read inverter time drift; optionally correct under control. *Refs: §19.*

## Phase 8 — Deployment, packaging & release (ship to real hardware / users)

*Not needed for dev on the dummy (the working-copy `make dev` path covers Phases 0–7) —
relocated here from Phase 0. These matter once running unattended on a Pi or cutting
versioned releases.*

- [ ] **T019 · Native install path** · Deps: T010, T011
  - `systemd` unit (`solar-manager.service`), `install.sh` (venv, frontend build, unit install,
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
    bundle `solar-manager-x.y.tar.gz` (prod `ng build` + backend + `install.sh` + systemd unit);
    optionally push multi-arch Docker image to GHCR tagged `x.y`/`latest`.
  - **Creates a GitHub Release titled `x.y`** with auto-generated notes (changelog since the
    previous `version/*` tag) and uploads the artifacts. Activates once the repo is on GitHub. *Refs: §13, §21.*

## Later — More vendors, transports & automation (on demand)

- [-] **L01 · `SolarmanV5Source` transport** — `pysolarmanv5` TCP to the logger; reuses the
  exact same profiles (SolarmanV5 wraps the identical Modbus payload). *Refs: §4, §20.*
- [-] **L02 · Sol-Ark & Deye profiles** — thin `extends: deye-base` profiles, near-free once
  the base map is validated in Phase 1. *Refs: §4, §20.*
- [-] **L03 · Smart automation & scheduling** — tariff+forecast-driven auto-scheduling of the
  work-mode timer; opt-in, separate automation flag, **dry-run/suggest-only first**; built
  entirely on the §12 safeguards. *Refs: §18.*
- [-] **L04 · More vendors / protocol families** — Growatt/Solis/Sungrow/… (new YAML each);
  generic SunSpec profile; text-command family (Voltronic/Must) + Victron family each carry a
  one-time transport+profile-contract cost, then siblings are cheap. *Refs: §20.*
