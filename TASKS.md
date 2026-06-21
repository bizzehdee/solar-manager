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
  - **Update:** `DiagnosticsPage` is now embedded as the **Diagnostics tab inside Settings**
    (the Settings page was split into tabs — Devices / Solar & battery / Tariff / Notifications /
    System & data / Diagnostics) rather than a top-level sidebar item; `/diagnostics` redirects to
    `settings`. The component is unchanged and loads its own data when the tab is first opened.
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

- [x] **L01 · `SolarmanV5Source` transport** — `pysolarmanv5` TCP to the logger; reuses the
  exact same profiles (SolarmanV5 wraps the identical Modbus payload). *Refs: §4, §20.*
  - **Done:** `devices/solarman_v5.py` (`SolarmanV5Source` + `SolarmanV5Config{host, serial, port,
    slave_id}`) implements the `Transport` protocol behind the same seam as `modbus_rtu` — bounded
    retries/backoff, `comms_stats`, lazy `pysolarmanv5` import, injectable client factory (fully
    unit-testable, no hardware). `factory.py` gains `build_solarman_device` + a `solarman_v5` branch;
    `main.py` validation accepts the transport (needs `params.host` + `params.serial`). Settings ›
    Devices add-form: a `solarman_v5` option with host / logger-serial / port fields (profile + Test
    shared across real transports). `pysolarmanv5>=3.0` added to requirements. Tests:
    `test_solarman_v5.py` (16, module 100%), factory + settings-form specs. Backend 391, frontend 182,
    e2e 24 green. *Hardware handshake validation pending (no logger on hand) — the protocol layer is
    fully faked/tested, same as `modbus_rtu` shipped before the RS485 bus arrived.*
- [-] **L02 · Sol-Ark & Deye profiles** — thin `extends: deye-base` profiles, near-free once
  the base map is validated in Phase 1. *Refs: §4, §20.*
- **L03 · Smart automation & scheduling** — tariff+forecast-driven auto-scheduling of the
  work-mode timer; opt-in, **dry-run/suggest-only first**; built entirely on the §12 safeguards.
  *Refs: §18.*
  - **Status (largely delivered via the rule-based path).** The automation feature shipped through
    **L03e** (user-authored condition→action rules): the engine, persistence, API, the opt-in
    scheduler + apply + write path, the Automation page with live preview, and the absorption of
    alerts are all **done**. The originally-planned **cost-arbitrage auto-planner** (L03a–d) has a
    pure engine (L03a, done + tested) but was **never surfaced**, and its dedicated apply path (L03d)
    is now **redundant** — L03e-3 built a shared scheduler/apply/write path. What remains is purely
    optional: exposing the planner's auto-proposed daily plan on top of the existing infra (L03b/c,
    on-demand). The `SOLARVOLT_ENABLE_AUTOMATION` flag in the original split was dropped — automation
    is always available and only register *writes* are gated, by `SOLARVOLT_ENABLE_CONTROL`.
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
    - *Note:* the module exists and is tested but is **not yet wired** to any API/UI — the shipped
      automation surface is the rule engine (L03e), not this strategy. Surfacing it is L03b/c.
  - [-] **L03b · Suggest-only plan API** *(on-demand — planner not yet surfaced)* · Deps: L03a, T047, T060
    - `GET /api/automation/plan` would wire `plan_timer()` to the live forecast/tariff/device and
      return the proposed plan + current→proposed diff. **Never writes.** Not built; the rule-based
      automation (L03e) covers the day-to-day need, so this auto-planner exposure is optional future
      work. If built, it applies through the existing L03e-3 path — no new write/scheduler plumbing.
      *Refs: §18, §12.*
  - [-] **L03c · Automation UI (suggest-only)** *(on-demand — would surface on the existing Automation page)* · Deps: L03b
    - The proposed daily plan + per-slot diff + projected saving/rationale. **Superseded as a separate
      page** by the Automation page (L03e-4), which already shows a live "what it would do now"
      preview; the planner output would surface there rather than a new view. *Refs: §18, §8.*
  - [-] **L03d · Opt-in auto-apply (scheduler + write)** *(irrelevant — superseded by L03e-3)* · Deps: L03c, T076
    - **Made redundant.** The opt-in scheduler + "apply now" + §12 write path (validate→write→
      read-back→audit, gated by `ENABLE_CONTROL`) was built generically in **L03e-3** and is shared by
      any automation output — there is no planner-specific apply to build. Kept for history only.
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
      - **Done:** the **Automation page** (`pages/automation/automation.ts`) — rule list with
        per-rule arm switch + priority, an inline editor (conditions: day-of-week/time-window/
        date-range/metric/tariff-window; actions with target picker + slot + value + per-action arm),
        and a live **"what it would do now"** card driven by `GET /api/automation/preview`
        (settings changes + would-apply/preview state with the ok/at-risk/blocked badge). "Apply now"
        shows only under `automation_can_write`. Frontend unit tests + Playwright E2E
        (create→list→preview→apply on the dummy).
    - [x] **L03e-5 · Absorb alerts into automation (notify + alert action types; retire AlertService)** · Deps: L03e-3, L10
      - The standalone `AlertRule`/`AlertEngine`/`AlertService` is replaced by automation rules that
        carry `notify` and `alert` action types alongside the existing `set_setting` type. One rule
        engine, one editor, all output types. *Refs: §18, §15.*
      - **Done (all five sub-steps below shipped).** Automation rules now drive notifications and
        in-app alerts; the standalone alert engine/service are deleted (the `alerts` package is
        channels-only). The `/api/alert-rules` CRUD is gone; the inbox (`/api/alerts` ack/snooze) and
        channels (`/api/alert-channels`) endpoints remain. Rule authoring lives only on the Automation
        page; the Alerts page is inbox-only. This is also recorded in `plan.md` §15 ("Architecture
        revision (L03e-5)"). A later commit added **message-template rendering** for notify/alert
        action messages (`{metric:.1f}` placeholders) — the shared renderer L15 will reuse.
        - [x] **L03e-5a · Engine: add action types** — `Action` in `rules.py` carries `action_type`
          (`"set_setting"` | `"notify"` | `"alert"`), `channels`, `message`, `severity`, `debounce_s`;
          `settings_to_apply()` filters to `set_setting`; `notify_actions()`/`alert_actions()` on the
          decision; `compare` moved into `rules.py`; `__stale_s__` / `__fault_count__` documented as
          service-resolved synthetic keys.
        - [x] **L03e-5b · Service: wire dispatch + debounce** — `AutomationService` resolves
          `__stale_s__`/`__fault_count__` into the metrics context, dispatches armed `notify` actions
          via `channels.dispatch()` (failures swallowed) and inserts armed `alert` actions into the
          inbox via `AlertRepository`, with per-(rule-id, action) debounce. Default rules (low-SoC,
          device-stale, inverter-fault) seeded as notify+alert actions on first start.
        - [x] **L03e-5c · API: remove alert-rules CRUD; keep inbox + channels** — `/api/alert-rules`
          (+ options) removed; `/api/alerts` inbox + `/api/alert-channels` kept; `/api/automation/
          options` returns available channels + severities; `AlertService` removed from `lifespan`.
        - [x] **L03e-5d · Frontend: automation editor gets notify/alert actions; Alerts page = inbox only** —
          action-type picker in the rule editor (set-setting / notify / alert) with channel multi-select,
          message, severity, debounce; the Alerts page is inbox-only (Rules tab removed); alert-rules
          API calls dropped from `api.service.ts`. *(commit `5209c84`)*
        - [x] **L03e-5e · Remove alerts engine + service** — `alerts/engine.py` and `alerts/service.py`
          deleted; `alerts/__init__.py` + `main.py` imports updated; `compare` now lives in
          `automation/rules.py`; the `alerts` package is channels-only. *(commit `c3ae97e`)*
    - [ ] **L03e-6 · Inverse / else actions on rules** · Deps: L03e-4
      - Add an optional `else_actions` tuple to `AutomationRule` (alongside `actions`). When the rule **matches**, its `actions` fire (today's behaviour); when it **does not match**, its `else_actions` fire instead. This gives single-rule if-else patterns without a mirror-image second rule: "if Monday → grid-charge slot 0 on, else → off", "if winter → target SoC 80%, else → 50%". `else_actions` are full `Action` objects, so any action type is allowed in the else branch (`set_setting`/`notify`/`alert`) — the UI (below) only surfaces the common `set_setting` case.
      - **Two invariants to preserve (the sharp edges):**
        1. **No conditions ⇒ neither branch fires.** `rule_matches()` already returns `False` for a rule with zero conditions (an always-on automation must be explicit, not an empty-condition accident). Adding else must *not* turn that into "always fires the else branch" — a rule with no conditions is inert in both branches. Encode this explicitly in the engine, not as an accident of control flow.
        2. **Disabled rule ⇒ both branches are previews.** The else branch goes through the same `armed = rule.enabled and action.enabled` gate as the primary branch; a disabled rule (or disabled else action) yields non-`active` `ProposedChange`s only.
      - **Engine change (`evaluate_rules`, `rules.py`):** replace the current `if not rule_matches(rule, ctx): continue` skip with: compute `matched = rule_matches(...)`; if the rule has no conditions, skip entirely (invariant 1); otherwise iterate `rule.actions if matched else rule.else_actions`. Both branches feed the **same** `set_setting` priority/conflict resolution, allow-list status check, and `notify`/`alert` collection that exist today — an else `set_setting` competes for its target on equal footing with any matched primary `set_setting` from another rule. `AutomationRule.from_dict`/`to_dict` gain `else_actions` (default `()`), mirroring how `actions` is (de)serialised.
      - **Branch tagging:** add `branch: str` (`"primary"` | `"else"`) to `ProposedChange`, set per emission and included in `as_dict()`. This is what lets the preview, audit log, and decision JSON say *which* branch a change came from. (No new collection on `AutomationDecision` — else changes land in the existing `changes`/`overridden`/`notifications`/`in_app_alerts` tuples, distinguished by `branch`.)
      - **Service change (minimal):** `apply()` / `_decide()` need **no structural change** — they already consume `decision.settings_to_apply()` / `notify_actions()` / `alert_actions()`, which span whichever branch the engine emitted. The only additions: carry `branch` into the audit-log entry written per applied change, and into the dispatched notify/alert metadata, so the history says "applied (else branch)".
      - **Preview/decision response:** because every `ProposedChange` now carries `branch`, the API response is unchanged in shape; the frontend renders the branch. Preview reads e.g. "Rule X: conditions not met → applying else actions" / "Rule X: matched → applying actions".
      - **UI (`automation.ts` rule editor) — `set_setting` else-value sugar:** each `set_setting` action row gains a small **"else" toggle**; when on, an **else value** input appears beside the primary value (target/slot/section picker stays shared — only the value differs). On save, the editor compiles each such action into a primary `actions` entry plus a mirrored `else_actions` entry (same `target`, `enabled`, action type; `value` = the else value). On load, the editor **reconstitutes** the toggle only when it detects this mirror pattern (an `else_actions` entry whose target matches a primary action 1:1); any `else_actions` that don't fit the mirror pattern (e.g. a different target, or a notify/alert in the else branch authored via the API) render as a read-only **"advanced else (edit as JSON)"** note rather than being silently dropped or corrupted on round-trip. The preview card shows both branches: "would set SoC slot 0 to 100% (Mon) / 20% (other days)".
      - **Done when:** a rule with `else_actions` round-trips through JSON serialisation (engine + API); a matched rule applies its `actions` and a non-matched rule applies its `else_actions` instead; a **no-condition** rule fires neither branch; a **disabled** rule/else-action stays preview-only; priority resolution correctly handles a conflict between a matched primary from one rule and a non-matched else from another rule on the same target (the **priority cross-over** case); every applied change records its `branch` in the audit log; the preview shows both branches clearly; the UI toggle compiles to/from the mirror pattern and preserves non-mirror `else_actions` on round-trip. **Tests** cover: match→primary, no-match→else, empty-`else_actions` on no-match (nothing fires), no-conditions (neither branch), disabled-rule (preview only), priority cross-over, `branch` tagging in `as_dict`, and full serialisation round-trip — plus a frontend test for the toggle compile/reconstitute. *Refs: §18.*
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

- [x] **L06 · Dynamic dashboards** · Deps: T018, T045, T047  *(all sub-tasks T_DB1–T_DB8 complete)*
  - **Deliverable:** a 12-column widget grid (powered by `gridstack`, self-hosted via npm — no CDN)
    with two built-in dashboards (**Now** and **History**) and unlimited user-created dashboards.
    Edit mode exposes drag-and-drop repositioning (snap-to-grid), resize handles, add/remove widgets,
    and per-widget config. Layouts persist server-side in `app_config`. Dashboards are exportable and
    importable as JSON files (download/upload in the UI).
  - **Grid spec:** 12 columns; gauge/card widgets default to 2×2; energy-flow widget is 6×6.
  - **Widget registry:** `energy-flow`, `metric-gauge`, `metric-card`, `stat-card`, `time-series-chart`.
    `metric-gauge` and `metric-card` are **generic** — pick any metric and optionally override its
    name/unit (and, for the gauge, full-scale + colour); there is no dedicated battery-SoC widget
    (just a `metric-gauge` on `battery_soc_pct`). Each type declares its minimum size, default size,
    and a config schema. Widgets remain dumb presentational components — the dashboard host provides data.
  - **Now built-in layout (col×row, all 2×2 except energy-flow):**
    `energy-flow` 0×0 (6×6) · `solar` 6×0 · `load` 10×0 · `battery-soc` 6×2 · `battery-power` 8×2
    · `grid-power` 10×2 · `grid-v` 6×4 · `grid-hz` 8×4 · `today-solar` 10×4.
  - **History built-in layout:** current History page (metric selector + time-series chart + stat cards)
    expressed as a dashboard layout; the `/history` route becomes an alias.
  - **User dashboards:** create/rename/delete via a management UI; appear in the nav sidebar below the
    built-ins. Built-in dashboards cannot be deleted (but can be personalised and reset to default).
  - **Done when:** both built-ins render correctly on the dummy, a user can create a custom dashboard,
    drag widgets to new positions that persist across reload, export it as JSON and re-import it on a
    fresh install. No-CDN gate must stay green. *Refs: §8.*
  - **Sub-tasks:** T_DB1–T_DB8 (see below).

- [x] **L14 · `<energy-flow>` widget — animated topology diagram on the Now page** · Deps: T018
  - **Deliverable:** the five-node energy-flow widget specified in §8 (Componentisation): inverter
    centre, **solar** top-left / **house** top-right / **battery** bottom-left / **grid** bottom-right,
    each corner connected to the inverter by a line; node **ring colours** green/red/grey by per-node
    status; **direction-aware animated flow** along each active edge in the energy-flow direction.
  - **State mapping** (from the canonical vocabulary, §4 — never re-derive signs in the UI):
    solar green producing (`pv_power_w > 0`) / grey idle; battery green charging / red discharging /
    grey idle (sign of `battery_power_w`, +charge/−discharge); grid green exporting / red importing /
    grey idle (sign of `grid_power_w`, +import/−export); **house always grey**; inverter green
    online / red fault-or-offline (run-state / connection health, §16). Colours map to Bootstrap
    `success`/`danger`/`secondary` (theme-aware, light & dark).
  - **Presentational & dumb:** `app-energy-flow` takes `@Input() metrics` + `@Input() inverterOnline`,
    no services/HTTP; the Now container feeds it from the existing WebSocket path. Render with
    Canvas (generated geometry, not hand-authored SVG paths). **Magnitude is not encoded in the
    flow** — the adjacent power gauges already show wattage (where vs. how much).
  - **Done when:** the widget renders on the Now page, ring colours + flow direction track live
    dummy metrics (every node/flow state reachable via the deterministic dummy), and
    `prefers-reduced-motion` suppresses animation in favour of a static directional dashed stroke
    while keeping ring colours. Unit tests cover the pure metric→{ring colour, flow direction} mapping
    (incl. the sign boundaries and house-always-grey); a Playwright E2E asserts the widget appears and
    its node states change across dummy scenarios. *Refs: §8 (Componentisation), §4, §16, §21.*
  - **Done:** `shared/energy-flow.ts` (`<app-energy-flow>`) — dumb/presentational (`[metrics]` +
    `[inverterOnline]` inputs, no services), so it drops straight into the L06 widget registry. Pure
    `computeEnergyFlow()` does the metric→{ring colour, flow direction} mapping (signs read straight
    from the canonical vocabulary, never re-derived); flow colour = the corner node's own status, the
    house leg stays grey, and an offline inverter suppresses every flow. **SVG + Bootstrap CSS
    variables** (not Canvas — theme-aware with no redraw, DOM-testable, consistent with the gauges):
    HTML nodes carry the Bootstrap-Icon glyphs, an SVG layer draws the trimmed connector wires + a
    tinted "lit" wire per active edge, and chevrons ride a CSS `offset-path` (`offset-rotate:auto`
    aligns them to the travel direction) animating `offset-distance`. `prefers-reduced-motion` drops
    the chevrons for a static arrowhead near the destination; rings stay coloured. Wired into the Now
    page above the gauges; `inverterOnline` = a live reading with no active faults and not in a
    fault/standby/shutdown run-state. Tests: `energy-flow.spec.ts` (7 pure-mapping incl. sign
    boundaries/idle/offline/null + 4 DOM render/colour) — frontend suite 141 green; Now E2E asserts
    five nodes, four wires, a green inverter ring and an active flow on the dummy; e2e 15 green.
    *Gotcha logged:* Angular's per-property style bindings (`[style.offset-path]`, `[style.--ep]`)
    silently no-op on these SVG `<path>` nodes — the offset-path must be written via `[attr.style]`.

- [x] **L16 · Derived (calculated) metrics as first-class canonical metrics** · Deps: T043, T051
  - **Why:** the daily KPIs (self-consumption %, self-sufficiency %, round-trip efficiency, savings,
    CO₂ avoided, peak PV) should be usable *anywhere a metric is* — metric-cards, gauges, and
    time-series charts — not locked inside the bespoke `daily-kpis` widget. The clean way (chosen over a
    frontend-only fetch-merge, which can't feed the DB-backed charts) is to **compute them server-side
    and treat them as canonical metrics**: add them to each poll's `Reading.metrics`, so they flow
    through the live snapshot (cards/gauges) *and* get persisted to `samples`/rollups (charts) with zero
    frontend special-casing. They're "running today" values that evolve through the day, so a chart shows
    their intraday build-up. Missing ≠ zero — a derived metric is omitted when its inputs are absent or
    the denominator is 0 (§4).
  - **L16-1 ✅ done · Engine: pure energy-ratio metrics** *(no new deps)* — `app/derived.py` `derive_metrics(metrics)`
    pure function computing, from the existing `today_*_wh` counters: `self_consumption_pct`
    (= self-consumed PV / PV), `self_sufficiency_pct` (= (load − import) / load), `round_trip_efficiency_pct`
    (= discharge / charge). Reuse `economics.self_consumed_pv_wh`. Add the three keys to
    `metrics.ALL_METRICS` (a new `DERIVED_METRICS` set). Hook into `Poller.poll_once` to merge the result
    into each `Reading.metrics` before broadcast/persist. **Done when:** the dummy snapshot and
    `/api/history/metrics` expose the three derived keys, charts plot them, and the pure function is
    unit-tested (ratios, omitted-on-missing-input, zero-denominator). ≥ 90% coverage on `derived.py`.
  - **L16-2 ✅ done · Engine: economics + stateful metrics** · Deps: L16-1 — adds `savings`,
    `co2_avoided_kg`, `peak_pv_w`. Implemented via `app/derived_stats.py` `DerivedStatsService`: a
    periodic task that reuses `StatsService.daily` (so savings/CO₂ are **TOU-accurate and match
    `/api/stats/daily`**, and peak = the day's rollup max), caches today's values per device, and the
    poller merges the cache into each `Reading` off the hot path (`Poller(derived_provider=…)`). Wired
    into the lifespan (start before poll, stop on shutdown). Keys added to `metrics.DERIVED_METRICS`.
    Verified end-to-end in `/api/live`. Tests: `test_derived_stats.py` (cache rounding, peak-omitted,
    poller merge). *(Peak comes from the daily rollup rather than a separate running-max, so it's
    consistent with stats and survives restarts.)*
  - **L16-3 ✅ done · Frontend: unit hints + retire the bespoke widget** · Deps: L16-1 — `core/metric-units.ts`
    `metricUnit(key)` (suffix heuristic: `_w`→W, `_pct`→%, `_kg`→kg, …) used as the **default unit** in the
    metric-card/gauge/stat-card registry adapters and as the **placeholder** in the editor's unit field, so
    a picked metric carries a sensible unit without typing one (covers existing metrics too). Then **split
    the History `daily-kpis` widget into individual metric-cards** (one per derived KPI) in the `_HISTORY`
    seed and **remove the `daily-kpis` widget** (registry + component) now that the KPIs are ordinary
    metrics. `savings` has no unit suffix (currency is locale/config-specific) → its card unit is set
    explicitly. **Done when:** the History dashboard shows individual KPI cards fed by the derived metrics,
    the KPIs are selectable in card/gauge/chart metric pickers with auto units, and `daily-kpis` is gone;
    `test_dashboards` + frontend specs updated. *Refs: §4, §8, §10, §21.*

### L06 sub-tasks

- [x] **T_DB1 · Dashboard model + backend API** · Required by: T_DB2
  - `DashboardConfig` type: `{ id, name, builtin, widgets: [{ type, x, y, w, h, config }] }`.
    Stored as JSON blobs under `app_config` keys `dashboard:<id>`. Endpoints:
    `GET /api/dashboards` (list all, builtin flag included), `GET /api/dashboards/{id}`,
    `PUT /api/dashboards/{id}` (create/update user dashboards; 403 on builtin writes),
    `DELETE /api/dashboards/{id}` (user only). Builtins are seeded from code, not the DB.
    Export = `GET /api/dashboards/{id}` (the JSON is the wire format); import = `PUT` with a
    user-chosen id. Tests: CRUD round-trip, builtin protection, unknown-id 404.
  - **Done:** `app/dashboards.py` — `BUILTINS` (Now + History) seeded from code with the L06
    layout; `DashboardStore` over `app_config` (one `dashboard:<id>` blob per user dashboard).
    `_validate()` coerces/validates the wire shape (name required, widgets list, each widget typed,
    config an object) and stamps `builtin: false` so imports always land as user dashboards. Added
    `AppConfigRepository.delete()` + `.list_prefix()` (LIKE-escaped) for per-id storage/enumeration.
    Routes in `main.py` (`/api/dashboards[/{id}]`, GET/PUT/DELETE) map `BuiltinProtected`→403,
    `DashboardNotFound`→404, `ValueError`→422. Tests: `test_dashboards.py` (10) — CRUD round-trip,
    export→import under a new id, builtin write/delete 403, unknown 404, validation 422; module 100%.

- [x] **T_DB2 · Frontend grid engine** · Deps: T_DB1 · Required by: T_DB3
  - Install `gridstack` via npm (self-hosted, no CDN — verify no-CDN gate still green).
    `DashboardHostComponent` loads a `DashboardConfig`, initialises a GridStack instance
    (12 columns, `cellHeight` = a rem-based unit consistent with Bootstrap spacing), and renders
    each widget into a `<div class="grid-stack-item">` with `gs-x/gs-y/gs-w/gs-h` from the config.
    In **view mode** GridStack is static (no drag, no resize). In **edit mode** drag + resize are
    enabled; on `change` events the component emits the updated layout for persistence.
    No widget logic here — host is purely layout.
  - **Done:** `gridstack@12` installed; its CSS added to `angular.json` styles (bundled/self-hosted,
    no-CDN gate stays green — verified in built `styles-*.css`). `shared/dashboard-host.ts`
    (`<app-dashboard-host>`) — signal inputs `[dashboard]` / `[editable]` / `[cellHeight]` (default
    `5rem`), output `(layoutChange)`. Snapshots the config's widgets once per dashboard id (GridStack
    owns the DOM thereafter), renders each as a `.grid-stack-item` with `gs-id`(=index)/`gs-x/y/w/h`,
    and inits GridStack (12 cols, `float`, `margin 0.5rem`, `staticGrid` = view mode) in
    `ngAfterViewInit`. An `effect` flips `setStatic` on edit-mode change; the `change` event reads
    `grid.save()` and emits the merged layout. Pure exported `mergeLayout()` maps saved nodes back to
    widgets by `gs-id` (type/config preserved, sorted by y,x, unknown ids dropped) — unit-tested
    without a DOM. GridStack init is wrapped so headless unit tests (no ResizeObserver) still render
    the testable placeholder markup. Widget content is a typed placeholder card — T_DB3 plugs in the
    registry. Models `DashboardConfig`/`DashboardWidget` + `ApiService` dashboard CRUD added. Tests:
    `dashboard-host.spec.ts` (4: mergeLayout mapping/drop/fallback + DOM render of grid attrs);
    frontend suite 150 green; e2e 16 green.

- [x] **T_DB3 · Widget registry** · Deps: T_DB2 · Required by: T_DB4, T_DB5
  - A `WIDGET_REGISTRY` map: `type → { component, label, minW, minH, defaultW, defaultH, configSchema }`.
    Initial entries: `energy-flow` (6×6, no config), `soc-gauge` (2×2, metric fixed to
    `battery_soc_pct`), `power-gauge` (2×2, config: metric key + label + maxW setting),
    `metric-card` (2×2, config: metric key + label + unit + icon + role), `time-series-chart`
    (4×4 min, config: metric key + resolution + range). The host resolves type → component via the
    registry and passes `config` + live data as inputs. Tests: registry completeness, unknown-type
    fallback renders a placeholder not a crash.
  - **Done:** `shared/widget-registry.ts` — `WIDGET_REGISTRY` with five types: `energy-flow`,
    `metric-gauge`, `metric-card`, `stat-card`, `time-series-chart`. **`metric-gauge` and
    `metric-card` are generic** — pick any metric and override name/unit (gauge also full-scale +
    colour); no dedicated SoC widget (battery SoC is a `metric-gauge` on `battery_soc_pct`, unit `%`,
    full-scale 100). Each `WidgetDef` carries `component`, `label`, `minW/minH/defaultW/defaultH`, a
    `configSchema` (typed fields — `metric`/`text`/`number`/`icon`/`role` — for the T_DB7 editor), and
    an `inputs(config, data)` **adapter** mapping stored config + live `DashboardData` to the
    component's inputs. Keeps widgets dumb (plan.md §8): the gauge shows magnitude (`abs`, signs not
    re-derived), absent metrics stay `undefined` (≠ 0), time-series points come from
    `data.series[metric]`. `DashboardHost` resolves type via `widgetDef()` + `*ngComponentOutlet`
    (`inputs:` bag); unknown types fall back to an "Unknown widget" card, not a crash. Added
    `DashboardData` model. Tests: `widget-registry.spec.ts` (7: completeness + per-type adapter incl.
    SoC-via-metric-gauge) + host render/fallback; frontend 158 green, build + no-CDN gate green.

- [x] **T_DB4 · "Now" built-in dashboard** · Deps: T_DB3 · Required by: T_DB6
  - Seed the Now built-in with the specified layout (see L06 spec above). The Now page route
    (`/now`) renders `DashboardHostComponent` with the Now config; the existing WS subscription
    moves to a `DashboardDataService` that feeds live metrics to whichever widgets need them.
    Built-in cannot be deleted; a "Reset to default" action restores the seed layout.
    E2E: Now dashboard renders, energy-flow visible, battery SoC gauge visible.
  - **Done:** `core/dashboard-data.service.ts` (`DashboardDataService`) — single WS-backed source:
    derives `metrics`/`faultCodes`/`runState`/`inverterOnline` from `LiveService` and exposes the
    `DashboardData` bag (`data()`) the host feeds widgets. `pages/now/now.ts` now loads the `now`
    built-in (`api.getDashboard('now')`) and renders `<app-dashboard-host [dashboard] [data]>` (view
    mode) for the grid, keeping the non-widget device chrome — fault banner, run-state badge,
    inverter clock drift/sync, battery-health panel — sourced from the service. A **Reset to default**
    button re-fetches the server-seeded layout. The dynamic per-install gauge auto-scaling and the
    battery/grid direction sublabels are dropped in favour of the generic `metric-gauge` (static
    `max`/unit from config) — consistent with the new widget model. Removed the now-unused
    `shared/soc-gauge.ts` (battery SoC is a `metric-gauge`). Tests: `now.spec.ts` rewritten (8 — chrome
    + host render + reset) reading from a faked `LiveService` via the service; E2E `now.spec.ts` adds a
    grid-host assertion and retargets the SoC check to the metric-gauge. Frontend 158 green, e2e 17
    green, build + no-CDN gate green.

- [x] **T_DB5 · "History" built-in dashboard** · Deps: T_DB3 · Required by: T_DB6
  - Seed the History built-in with the existing History page layout (time-series chart + stat
    cards). `/history` route renders `DashboardHostComponent` with the History config. The
    time-series-chart widget wraps the existing `<app-time-series-chart>` component; the metric
    selector, resolution picker, and date range controls move into the widget's own config panel.
    E2E: History dashboard renders, chart visible, metric selector works.
  - **Done:** two **container widgets** (a deliberate, task-authorised exception to dumb widgets —
    History is interactive exploration, not a live snapshot): `shared/daily-kpis.ts` (the today's-KPI
    stat-card row, fetches `/api/stats/daily`) and `shared/history-chart.ts` (metric/resolution/range
    selectors + CSV export, fetches `/api/history`, seeds initial selection from widget `config`,
    wraps the dumb `<app-time-series-chart>`). Both registered in `WIDGET_REGISTRY` (7 types now); their
    `inputs` adapters pass only `config` since they self-fetch. History builtin (`dashboards.py`) =
    `daily-kpis` (12×2) over `history-chart` (12×6). `pages/history/history.ts` is now a thin host
    container (loads the `history` built-in + Reset to default), mirroring Now. Tests: `daily-kpis.spec.ts`
    (2), `history-chart.spec.ts` (5 — metric load, config seed, CSV href, no-data, switch metric),
    rewritten `history.spec.ts` (2 — host render + reset), backend `test_get_builtin_history_layout`;
    new E2E `history.spec.ts` (2). Frontend 161 green, backend 374 green, e2e 19 green, build + no-CDN green.

- [x] **T_DB6 · Dashboard switcher + management** · Deps: T_DB4, T_DB5 · Required by: T_DB7
  - Nav sidebar lists Now → History → (separator) → user dashboards (in creation order) → "+ New".
    "New" prompts for a name, creates a blank 12-col dashboard via `PUT /api/dashboards/{id}`,
    navigates to it. Dashboard item context menu (⋯): Rename, Export JSON (triggers download),
    Delete (user only; confirm dialog). Settings › Dashboards page lists all dashboards with the
    same actions plus an Import button (file picker → `PUT`). Tests: create/rename/delete
    round-trip; builtin delete attempt shows error not 500.
  - **Done:** `core/dashboards.service.ts` (`DashboardsService`) — shared `dashboards` signal +
    builtins/user split + `create/rename/remove` (slugified unique ids) feeding both views.
    `core/dashboard-file.ts` — `downloadDashboard()` / `parseDashboard()`. Sidebar (`app.ts`)
    restructured into a **dashboards group** (built-ins → user dashboards → "New dashboard") with a
    per-user-dashboard ⋯ menu (Rename / Export JSON / Delete, document-click to dismiss) above the
    tools group; built-ins route to `/now`+`/history`, user dashboards to the new generic
    `/dashboard/:id` page (`pages/dashboard/dashboard.ts`, reacts to param changes). **Settings ›
    Dashboards** tab lists all with Export/Rename/Delete + New + **Import** (file → `parseDashboard`
    → `PUT` under a unique slug). Also fixed a latent shell timer leak (`ngOnDestroy` clears the
    intervals). Tests: `dashboards.service.spec.ts` (5: slugify/uniqueId/CRUD), updated `app.spec.ts`
    + settings tab count; E2E `dashboards.spec.ts` (2: create→sidebar→delete; builtin has no delete)
    + retargeted `now.spec.ts` nav assertions. Frontend 166 green, e2e 21 green, build + no-CDN green.

- [x] **T_DB7 · Dashboard editor (drag-drop + widget management)** · Deps: T_DB6 · Required by: T_DB8
  - Edit-mode toggle button in the dashboard header (pencil icon). In edit mode:
    GridStack enables drag-and-drop + resize (snap to 12-col grid); a widget toolbar appears at
    top with "+ Add widget" (opens a picker: widget type → places it at the first free slot at
    default size); each widget gets a remove button (×) and a configure button (⚙) that opens a
    sidebar/modal with the widget's config fields (metric key, label, etc. from the registry schema).
    "Save" persists the updated layout via `PUT /api/dashboards/{id}`; "Discard" reverts.
    Editing a built-in creates a personalised copy (stored in `app_config`) — the seed layout is
    preserved as the reset target. Tests: edit → save → reload preserves layout; discard reverts;
    add/remove widget round-trip.
  - **Done:** `DashboardHost` is now a self-contained editor: an Edit toggle reveals an add-widget
    picker (from the registry) + Save/Discard; GridStack goes interactive (drag/resize); each widget
    gets ⚙ (configure) + × (remove) overlays in edit mode. The ⚙ opens an inline config panel built
    from the widget's `configSchema` (metric fields render a dropdown of live metric keys; number/text
    inputs otherwise). Save emits `(layoutSaved)`; the page `PUT`s it. **Backend personalisation:**
    `DashboardStore` now overlays builtins with an app_config override (`PUT` to a builtin id stores a
    personalised copy keeping `builtin:true`; `DELETE` = reset to the code seed). `main.py` drops the
    builtin-write 403s; Now/History "Reset to default" now `DELETE`s the override. Fixed two host
    robustness bugs found via E2E: `mergeLayout` now **preserves all widgets** (only applies matched
    positions — an empty/partial GridStack `save()` during re-init no longer wipes the layout), and
    re-init runs on a macrotask after Angular flushes the DOM (+ timer cleared on destroy). Tests:
    host editor specs (add/remove/save/discard/setConfig), rewritten `mergeLayout` specs, backend
    personalise/reset (`test_dashboards.py`, module 100%), E2E edit→add→save→reload round-trip.
    Frontend 175 green, backend 375 green, e2e 22 green, build + no-CDN gate green.

- [x] **T_DB8 · Export / import JSON** · Deps: T_DB7
  - Export: the "Export JSON" action downloads `dashboard-<name>.json` (the raw `DashboardConfig`
    wire format from `GET /api/dashboards/{id}`). Import: the "Import" button in Settings ›
    Dashboards accepts a `.json` file, validates it client-side against the widget registry
    (unknown types → warning, not hard error), then `PUT`s it as a new user dashboard (name taken
    from the JSON; disambiguated with a suffix if it collides). A successfully imported dashboard
    is navigated to immediately. Tests: export → re-import produces identical layout; invalid JSON
    shows error; unknown widget type in import file shows warning but succeeds.
  - **Done:** `downloadDashboard()` now names the file from the dashboard name slug. Import in
    Settings › Dashboards: `parseDashboard()` validates the file shape (friendly error on bad JSON),
    `unknownWidgetTypes()` (new registry helper) flags unregistered types as a **warning** (still
    imported — they render the "Unknown widget" placeholder), name de-duped via
    `DashboardsService.uniqueName()` + a unique slug id. A **clean** import navigates straight to the
    new dashboard; an import with unknown types stays on the page so the warning is seen. Tests:
    `dashboard-file.spec.ts` (parse valid/default/invalid), `unknownWidgetTypes` + `uniqueName` specs,
    E2E export→re-import round-trip + invalid-JSON error + unknown-type-warns-but-creates. Frontend
    181 green, e2e 24 green, build + no-CDN gate green.

## Later — Integrations & notifications (deferred from Phase 7, on request)

*The alerting core (engine + inbox + Prometheus) shipped in Phase 7; these are the remaining,
self-contained egress/notification pieces — each additive, off the hot path, brand-independent.*

- [x] **L07 · MQTT publisher + Home Assistant auto-discovery** *(was T083)* · Deps: T016
  - Publish each normalized `Reading` + per-device status to a broker; emit HA MQTT discovery
    configs so every metric appears as an HA sensor with zero manual YAML. *Refs: §14.*
  - **Done:** `app/integrations/mqtt.py` `MqttService` — own background cadence like the readings
    webhook, re-reads the `mqtt` app-config blob each tick (host/auth/tls/base_topic/interval/
    discovery, live), **off the hot path** (an unreachable broker is logged and swallowed, never
    blocks polling). Publishes **one compact JSON state message per device** to
    `{base_topic}/{device_id}/state`, and **retained HA discovery** configs to
    `{discovery_prefix}/sensor/solarvolt_{device}/{metric}/config` (one per scalar metric, grouped
    under a single HA `device`, referencing the state topic via `value_template`). Sensor
    metadata (unit / device_class / state_class) is **inferred from the canonical key suffix**
    (`_w`→power/W, `_wh`→energy/total_increasing, `_v`/`_a`/`_hz`/`_c`/`_pct`…) so it's brand-
    independent and covers the whole vocabulary; list-valued metrics (fault/warning codes) ride the
    state JSON only. Discovery is re-emitted only when the device/metric shape changes (or on a
    config change / manual test). Broker publish is via **`paho-mqtt`** (`publish.multiple`, run off
    the loop in a thread) and **injectable** ⇒ network-free tests. `GET/PUT /api/integrations/mqtt`
    (+ interval clamp ≥5s, defaults) and `POST …/test` (publish once now, surface failures as 502).
    Settings › Notifications gains an **MQTT + Home Assistant** card (host/port/auth/tls/base topic/
    interval/discovery + Save + Publish test). New runtime dep `paho-mqtt>=2.0` (pure-Python, no
    broker bundled). Tests: `test_mqtt.py` (pure suffix→sensor mapping, discovery/state message
    shapes, dedup-until-shape-changes, enabled/disabled tick, interval clamp + failure swallow, API
    round-trip + test endpoint) — module 94% (only the real-paho glue uncovered); backend suite
    green (360 passed, 95% cov). Frontend: `MqttConfig` + API methods + 2 settings unit tests; suite
    146 green. E2E `mqtt.spec.ts` (card saves + persists on the dummy); e2e green. *No `mqtt://` or
    broker URL ships in the bundle — config is user data (no-CDN gate green).*
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

## Later — ML-driven smart optimization

*Train a lightweight scikit-learn model on historical data (energy/grid/battery/solar/tariff + time features) to automatically suggest inverter timer-settings that minimise cost or maximise ROI. Model output feeds through the existing automation preview + apply path (§18/§12). See `plan.md` §22 for the full design.*

**Code home (decided):** a new `backend/app/ml/` package mirroring the per-concern layout of
`forecast/` and `automation/` — `ml/features.py` (M001), `ml/training.py` (M002), `ml/inference.py`
(M003), `ml/store.py` (model/version persistence), `ml/service.py` (background-task orchestration +
wiring into the persist loop and the automation decision). Tests in `backend/tests/test_ml_*.py`.

**New dependencies (added in M002, called out here so it isn't a surprise):** `scikit-learn` +
`joblib` (which pull `numpy`/`scipy`). These are sizeable and must resolve to prebuilt **ARM64
wheels** so `pip install` on a Pi stays binary-only (no source build). Pin versions in
`backend/requirements.txt`; the no-hardware CI path installs them too. If wheel size/ARM build risk
proves unacceptable, the §22 fallback is a `Ridge`-with-interactions model (still scikit-learn) — same
pipeline, lighter footprint.

- [ ] **M001 · Feature engineering pipeline** · Deps: T043, T051, T078 · Required by: M002, M006
  - Pure functions in `ml/features.py` to extract labelled training examples from history: per complete
    day, a feature vector → target. Returns plain `list[dict]` rows (or a numpy `(X, y)` via a thin
    adapter) so the module has **no scikit-learn dependency** — it stays pure/unit-testable; encoding to
    arrays happens in M002. Reads `rollup_1d`/`rollup_1h` (via `StorageRepository`), `app_config`
    tariff/site/economics, and the `audit` table.
  - **Features (input):** time encoding (hour, weekday, day-of-year → sin/cos; is_weekend; season),
    **actual** PV Wh and load Wh for the window (from rollups — retrospective training uses actuals, not
    forecast), starting SoC %, battery capacity (from config), the active tariff import/export rates +
    cheapest/peak window flags, and the **timer-slot settings active during that window**. Label features
    (`has_ev_charging`, …) are **added in M006** — M001 ships without them first.
  - **Target (label):** net cost for the window (import_cost − export_revenue) computed via the existing
    **`economics.compute_economics()` + `tariff.RateSchedule`** — reuse the app's cost math so training
    target == what History/Stats report (no divergent cost function).
  - **Train/serve skew (the subtle bit, call it out):** the same feature column is *actual* PV/load at
    training time but *forecast* PV/load at inference (M003). Name the columns by role (`pv_wh_window`,
    `load_wh_window`) and document that the inference path fills them from the forecast service — so the
    model isn't trained on a feature it can't get at serve time.
  - **Reconstructing active settings (the gnarliest bit — the current spec understated this):** the
    `audit` table stores **change deltas** (`changes` = JSON `{field: {old, new}}`, with `section`/`slot`/
    `ts`/`result`), **not** the settings active at a given time. So "settings active during window W" must
    be **reconstructed by replaying** successful (`result='ok'`) audit rows forward from a base state,
    keyed by `(section, slot, field)`. Define the base state explicitly: before the first audit entry the
    value is **unknown** → examples whose settings are wholly unknown are **excluded** (don't impute a
    fake baseline). Helper: `settings_at(audit_rows, ts) -> dict[(section,slot,field), value]`,
    unit-tested directly.
  - **Confidence gate:** `count(complete_examples) < MIN_TRAINING_DAYS` (default 14, configurable via
    `Settings`) returns an `insufficient_data` status carrying the shortfall (`have`, `need`) — never a
    crash or a silent empty set. "Complete" = both rollup data and reconstructable settings exist for the
    day.
  - **Done when:** `make_train_examples(window_days=N, device_id)` returns examples + a status from
    recorded dummy data; time features cyclic-encoded; tariff windows correctly attributed; `settings_at`
    correctly replays the audit log (covered by its own test incl. the unknown-base exclusion); below the
    gate it returns `insufficient_data{have,need}`. Module ≥ 90% coverage. *Refs: §22.*

- [ ] **M002 · Continuous model training** · Deps: M001
  - Training pipeline in `ml/training.py` + persistence in `ml/store.py`. Pulls examples from M001,
    checks the confidence gate, **encodes** (standardise numerics, one-hot/cyclic-encode time features —
    this is where scikit-learn enters), trains a `GradientBoostingRegressor`, holds out the latest 7 days
    for validation, applies the accuracy gate (reject if MAE > 1.5× the previous model's), and records
    versioned metrics (MAE, R², trained-at, feature count, example count).
  - **Adds the scikit-learn/joblib/numpy dependencies** (see section preamble) to
    `backend/requirements.txt`, pinned to ARM64-wheel-available versions.
  - **Model store (decided):** persist each version as `<data_dir>/models/v{N}.joblib` (model + scaler +
    feature metadata bundled). `<data_dir>` is **configurable, defaults beside the SQLite `db_path`, and
    is gitignored** — never inside the repo working copy (a `git pull` / read-only deploy must not clobber
    or lose models). Version **history + the active-version pointer** go in a new `ml_models` table
    (append a `(version, sql)` tuple to `MIGRATIONS` in `storage/migrations.py`) so M005's `/history`
    endpoint is a simple query; the previous model is retained as fallback and a failed/rejected run never
    becomes active.
  - **Trigger cadence (refined — don't retrain on every persist):** a new training *example* only appears
    once a day is **complete**, so retraining more often is wasted work. Gate the background retrain on
    "a new complete day exists since `last_trained_day`", debounced; still also triggerable on-demand via
    API (M005). Runs as a low-priority background task off the hot path (`ml/service.py`).
  - **Done when:** training on deterministic dummy data converges to a model predicting daily cost within
    a known error bound; a retrain preserves the old model; a worse retrain is rejected + logged and the
    old model stays active; a failed retrain doesn't break inference; below the gate status is
    `insufficient_data` and no training is attempted; redundant triggers (no new complete day) are
    no-ops. Module ≥ 90% coverage. *Refs: §22.*

- [ ] **M003 · Inference / suggestion engine** · Deps: M002
  - `ml/inference.py`: load the active model, respect the confidence gate, enumerate a **bounded** set of
    candidate timer-slot configurations — target SoC ∈ {20,40,60,80,100}, grid-charge ∈ {on,off}, slot
    start ∈ the user's actual tariff windows (non-optimised slots fixed to current values to keep the
    space small) — fill the forecast-derived feature columns (train/serve skew note from M001) from the
    **forecast service**, predict cost per candidate, and return the lowest-cost proposal + predicted
    improvement vs. current settings.
  - **Allow-list constraint (new — ties to the rules engine):** candidate configs may only touch targets
    the profile marks automation-**safe** (`automation.rules.AllowList.safe`, derived from the settings
    schema). The enumerator filters by the allow-list so ML can never propose a write the rule engine
    itself wouldn't be allowed to make.
  - **Fallback:** no model / gate unmet → return `null` with a clear status (`insufficient_data{have,need}`
    or `no_model`); rule-based automation (L03) is unaffected.
  - **Done when:** with a trained model + tomorrow's forecast + current settings (above the gate) the
    engine returns a proposed config (allow-list-filtered) with a predicted saving; below the gate / with
    no model it degrades gracefully with a clear status. Module ≥ 90% coverage. *Refs: §22.*

- [ ] **M004 · Integration with automation preview + apply (dry-run + live)** · Deps: M003, L03e-3
  - Surface the ML proposal in the existing `GET /api/automation/preview` (built by
    `AutomationService.preview()` → `evaluate_rules`). The ML proposal enters as synthetic
    `set_setting` `ProposedChange`(s): add a **`source` field** to `ProposedChange` (`"rule"` default |
    `"ml"`) plus `predicted_improvement` + `confidence`, and feed them through the **same priority
    resolution** as rules (the ML proposal is treated as one rule at a configurable priority; conflicts
    with rule proposals resolve per §18). `as_dict()` carries the new fields.
  - **Apply wiring:** the scheduler/`apply` path composes the rule decision **and** the ML proposal
    *before* `settings_to_apply()`, so live-mode ML writes go through the unchanged
    `AutomationService.apply()` → `control.apply_settings()` → §12 chain (validate → write → read-back →
    audit). No new write plumbing; the audit entry records `source='ml'`.
  - **Mode toggle:** `ml_mode: "dry_run" | "live"` (stored in `app_config`, see M005). Dry-run → proposal
    appears in preview only, never auto-applied. Live → scheduler applies it. Live additionally requires
    `Settings.enable_control` (`SOLARVOLT_ENABLE_CONTROL`); if control is off the effective mode is forced
    to dry-run regardless of the stored toggle.
  - **Done when:** preview returns an ML proposal (with `source:"ml"`, improvement, confidence) when a
    model exists above the gate; manual apply and live auto-apply both succeed through the existing safety
    path with `source='ml'` in the audit; dry-run never auto-applies; live auto-applies only when both the
    toggle and `enable_control` are on; ML↔rule priority conflicts resolve deterministically; below the
    gate neither mode proposes. Tests cover all combinations against the dummy. *Refs: §18, §12, §22.*

- [ ] **M005 · Model management API + Settings UI** · Deps: M004
  - Backend: `GET /api/automation/model` (active version, trained-at, validation MAE/R², feature count,
    example count, gate progress `have/need`, status `insufficient_data|training|ready|error`),
    `POST /api/automation/model/train` (trigger a background retrain → 202 + task id),
    `GET /api/automation/model/history` (past runs from the `ml_models` table with per-version metrics),
    and `GET/PUT /api/automation/config` for `ml_mode` (`dry_run|live`, persisted in `app_config`).
    Training never blocks the response.
  - Frontend: an **ML Automation** card in Settings (new sub-tab under the existing Automation/Settings
    tab system, which is now query-param driven — `?tab=`) showing model status, a gate progress bar
    ("12 of 14 minimum days"), last-trained date, validation MAE/R², feature count, a dry-run/live toggle
    (disabled + greyed when `enable_control` is off, with a tooltip explaining why), and a "Train now"
    button (spinner while running, metrics refresh on completion). Add the calls to `api.service.ts` +
    types to `models.ts`.
  - **Done when:** the user can see status (incl. gate progress), toggle dry-run/live (persisted), trigger
    training, and watch metrics update on completion; the live toggle is forced/greyed to dry-run when
    control is off. Frontend unit tests + a Playwright E2E asserting "Train now" updates the status pill
    and the mode toggle persists across reload. *Refs: §22.*

- [ ] **M006 · Usage annotation (label time windows on History)** · Deps: T044, T045 · Extends: M001
  - Users mark time regions on the History chart with descriptive labels (e.g. "EV charging", "cooking",
    "washing"). These become one-hot features in M001's pipeline so the model learns the cost effect of
    specific loads and can factor planned usage into suggestions.
  - **Storage:** a `usage_labels` table (`id, device_id, starts_at, ends_at, label, notes, created_at,
    updated_at`) added by **appending a new `(version, sql)` tuple to `MIGRATIONS` in
    `storage/migrations.py`** (the integer-versioned runner; the exact number is whatever is next when
    this lands). Backend API `GET/POST/PUT/DELETE /api/usage-labels` per device, with overlap detection
    (warn — don't reject — on overlapping labels for the same device).
  - **Label taxonomy:** built-in set — `ev_charging`, `cooking`, `washing_drying`, `heating`, `cooling`,
    `pool_pump`, `water_heating`, plus a free-text `other` with a user-defined name; `GET
    /api/usage-labels/labels` returns the taxonomy.
  - **Annotation UX on History:** the History chart is now the `history-chart` **dashboard widget**
    (post-L06), so the label layer is added there, not to a standalone page. Drag-select a time region →
    popup to pick a taxonomy label (or type a custom "other") → render as a translucent colour band keyed
    by label type; existing bands are clickable to resize (drag edges), re-label, or delete; the layer
    shares the chart's time axis so pan/zoom keeps bands aligned.
  - **ML integration (extends M001/M003):** M001 joins `usage_labels` on overlap with each training
    window → one-hot features (`has_ev_charging`, …). At inference (M003) the user can optionally declare
    planned labels for the forecast window in the preview UI ("I will charge the EV tomorrow"), encoded as
    predicted features.
  - **Done when:** backend CRUD round-trips with overlap warnings; the History widget shows labelled
    bands that persist across reload; create/resize/re-label/delete all work and survive reload; M001
    picks up the labels as one-hot features. E2E: create a band → assert it renders → refresh → assert it
    persists. *Refs: §22.*

- [ ] **L15 · Multiple custom webhooks + user-defined payloads** · Deps: L09, L10, L11
  - **Deliverable:** lift the single-webhook limit on **both** egress paths — alert/notification
    webhooks (L10) and outbound readings webhooks (L09) — to **any number of user-defined endpoints**,
    each with a **user-definable payload** (§14 *Custom webhooks*). The app should be able to POST
    whatever shape a downstream service expects (Slack/Discord/HA REST/custom) without code changes.
  - **Endpoint model (data, not code):** each webhook is a config entry — stable `id` (slug) + `label`,
    `url`, `method` (POST default), optional **`headers`** (auth; secret, stored in `app_config` like
    other channel secrets), `content_type` (default `application/json`), optional **`payload_template`**,
    `enabled`. **Readings** endpoints also carry their **own `interval_s`** (per-endpoint cadence, clamp
    ≥ 5 s); **alert** endpoints are event-driven.
  - **Payload templating:** promote the automation message renderer (`_render_message`, `automation/
    service.py`) to a shared **`app/templating.py`** `render_template(template, context)`, used by
    automation messages *and* both webhook types. Empty template ⇒ today's default body (raw alert dict /
    full readings snapshot) so existing setups are unchanged. Context = alert fields + metrics (alerts) /
    `ts` + flattened per-device metrics (readings). **JSON-escape** substituted values so the body stays
    valid JSON; malformed templates fall back to the default (never crash egress). Ship Slack/Discord/
    plain **presets** in the UI.
  - **Per-rule selection:** each alert webhook becomes its own channel `webhook:<id>`; `build_channels`
    (`alerts/channels.py`) iterates the endpoint list, and `/api/automation/options` lists them by label
    so a rule can target specific endpoints. Other channel types (Telegram/ntfy/Gotify/Pushover/Email)
    stay single-config.
  - **No migration:** the single-webhook config was never used, so the list shape simply replaces it —
    drop the old single `webhook` (in `alert_channels`) and single `readings_webhook` config; no
    compatibility shim or alias needed.
  - **API:** evolve `GET/PUT /api/alert-channels` + `/api/integrations/readings-webhook` to the list
    shape (or add list-aware endpoints), keep the per-endpoint **test** action (send a sample through one
    endpoint, surface failures).
  - **Frontend (Settings › Notifications):** replace the two single-webhook forms with **dynamic
    add/edit/remove lists** — per endpoint: label, URL, headers, content-type, a **payload-template editor**
    (textarea + an "available placeholders" hint + preset buttons), `enabled`, and (readings) `interval_s`,
    each with a **Test** button. Alert webhooks appear by label in the per-rule channel picker.
  - **Done when:** a user can add several webhooks of each type, give each a custom payload, and target
    specific alert webhooks per rule. All §14 invariants hold (off the hot path, per-endpoint enable,
    dead endpoint logged not fatal, secrets server-side, interval clamp, no-CDN gate green). Tests:
    extend `test_alert_channels.py` / `test_readings_webhook.py` / `test_alert_api.py` for the list shape
    and template rendering (incl. JSON-escaping + malformed-template fallback) — the templating module is
    critical-logic (§21, ≥ 90%); frontend unit tests for the dynamic list + an E2E that adds/tests a
    webhook on the dummy. *Refs: §14 (Custom webhooks), §15, §21.*

- [x] **L17 · Merge time-series-chart + history-chart into one `chart` widget** · Deps: L16
  - **Why:** after the History chart's inline controls moved into the editor modal and both charts
    gained a header, `time-series-chart` and `history-chart` were near-duplicate self-fetching wrappers
    around the dumb `<app-time-series-chart>` — differing only in how the window was expressed (range-in-
    days vs "last N min/hours/days"), auto vs pinned resolution, and a refresh timer. Two near-identical
    widgets meant a "which chart do I pick?" choice with no real distinction.
  - **Done:** single `shared/chart-widget.ts` (`ChartWidget`) — config `{ metric?, label?, unit?, window?,
    window_unit?, resolution? }`; window = value + unit (minutes/hours/days); resolution auto-derived from
    the window span (≤3h raw, ≤3d 5m, else 1h) unless pinned (raw/5m/1h/1d via an **Auto** option);
    first-available-metric fallback; 30 s refresh timer + config-driven `effect` refetch; header
    (`{label|humanised} · last {N unit}`); counters (…_wh) → kWh bars. Registry collapses to one `chart`
    type; the old `time-series-chart`/`history-chart` keys resolve via `WIDGET_ALIASES` (the unified
    component reads the legacy `{resolution, range}` shape) so existing stored dashboards still render and
    the "Add widget" menu shows one **Chart** entry. History built-in seed now uses `chart`
    (`window:24, window_unit:hours, resolution:1h`). Deleted `time-trend-chart.*` + `history-chart.*`;
    `chart-widget.spec.ts` (window/auto-resolution/pinned/legacy-shape/fallback/refetch/header/no-data),
    `widget-registry.spec.ts` (alias resolution), `test_dashboards.py`, and the History E2E updated.
    *Refs: §8, §9, §21.*
