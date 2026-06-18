# SolarVolt — Working Brief for Claude

This file is the standing context for every session. Read it first, then `TASKS.md`
for the ordered backlog. The full design rationale lives in `plan.md` — treat it as
the spec ("why/what"); `TASKS.md` is the "in what order".

## What this is
A **vendor-agnostic** management, statistics and control webapp for solar/battery
systems. First hardware target: a **Sunsynk SYNK-8K-SG05LP1** inverter over RS485 —
but Sunsynk is just the first *profile*, never a baked-in assumption. New brands are
added by writing a profile (YAML), not by touching core code.

Deployment context (by design): **single house, home LAN, no user auth, not
internet-exposed.** One household, no accounts/roles.

## Tech stack
- **Backend:** Python 3.11+, FastAPI (async), `pymodbus` for Modbus, `asyncio`.
- **Storage:** SQLite + rollup schema behind a repository abstraction; Alembic migrations.
- **Frontend:** Angular 21 (standalone components) + Bootstrap 5.3 (SCSS, no admin
  template), `ng-bootstrap`, icons via Bootstrap Icons, charts via `ng2-charts` (Chart.js).
  Unit tests run on Angular 21's default **vitest + jsdom** runner (headless, no browser).
  Live data over WebSocket. **No CDN — all assets (Bootstrap, Bootstrap Icons, Chart.js,
  fonts) are installed via npm and bundled/self-hosted** so the app loads with zero outbound
  requests (offline in-home LAN). Never reference an external URL from the frontend.
- **Deploy:** native on a Raspberry Pi / Ubuntu (systemd + `install.sh`) is the primary
  path; Docker/Compose is the maintained alternative.

## Repo layout
- `README.md` — **user-facing** front door (home users running the app); keep it current.
- `LICENSE` — BSD 3-Clause, © 2026 Darren Horrocks. The whole project is BSD-3 licensed.
- `plan.md` — design spec / source of truth for *what* to build.
- `TASKS.md` — ordered deliverables with done-criteria and dependencies.
- `profiles/` — device profiles as YAML (`deye-base.yaml`, `sunsynk-8k-sg05lp1.yaml`).
- `backend/` — FastAPI app (`app/main.py` → `app.main:app`), device abstraction (`app/devices/`),
  dummy simulator, YAML profile loader, poller; tests in `backend/tests/` (pytest).
- `frontend/` — Angular 21 app (standalone, `app/` shell + `core/` services + `shared/` + `pages/`);
  Bootstrap 5.3 + Bootstrap Icons self-hosted; unit tests via vitest/jsdom (no browser needed).
- `e2e/` — Playwright integration tests (drive the full app on the dummy).
- `tools/regscan.py` — read-only Modbus register-discovery CLI (Phase −1). See `tools/README.md`.
- `.vscode/` — committed debug defaults (launch/tasks/extensions). **F5 → compound "Full Stack"
  debugs backend (debugpy) + frontend (Chrome) with breakpoints.** Entry points match the
  scaffold: `backend/` (`app.main:app`), `frontend/` (dev server :4200 via `npm start`), `.venv/`.

## Commands
- **Run from the working copy (dev/test) — must always work after `git pull`:** create a
  venv, `pip install -r requirements.txt`, run Uvicorn with `--reload` from the repo root;
  frontend via `ng serve` (dev proxy) or a one-off `ng build` served by the backend. A
  `make dev` target brings both up. No systemd/Docker/hardware needed — the **dummy device
  is the default**, so a fresh clone gives a live synthetic dashboard. (See `plan.md` §13.)
- **Established commands (from repo root):**
  - `make install` — venv + `backend/requirements-dev.txt` + `frontend` npm deps.
  - `make dev` — backend (uvicorn `--reload`, :8000) + frontend (`ng serve` proxy, :4200) together.
  - `make test` — backend `pytest --cov-fail-under=80` + frontend vitest.
  - `make build` — production `ng build` (output `frontend/dist/solarvolt/browser`, served by the backend).
  - `make e2e` — Playwright suite (run `make build` first; it boots the backend serving the built UI).
  - Backend-only tests: `cd backend && ../.venv/bin/python -m pytest`.
- Register scan (real): see `tools/README.md`. `--mock` runs with no hardware.

## The two load-bearing contracts — do not break these

### 1. The device seam (`plan.md` §4, §20)
Two orthogonal seams keep the app vendor- and wire-agnostic:
- **Transport** = *how* bytes move (Modbus RTU/TCP, SolarmanV5). Knows no brand.
- **Profile** = *what* registers mean for a brand/model. Knows no wire.
- A **`Device`** = one transport + one profile. The app holds a registry of N devices,
  merged into one normalized snapshot.

**The cross-family contract is `Reading` (canonical metrics) + optional `SettingsSchema`
— NOT registers.** Keep `dict[int,int]` and all Modbus specifics *inside* the Modbus
family. Never let the register model leak above the driver — that's what makes the
text/Victron families additive later instead of a refactor.

### 2. Canonical metric vocabulary (`plan.md` §4)
Profiles translate raw registers → these brand-independent keys; everything above the
driver only ever sees these. Normalize signs **before storage**, never in the UI.
Missing ≠ zero — unreported metrics are absent, not faked (gated by `capabilities()`).
Per-phase suffixes (`grid_power_l1_w`) collapse to the unsuffixed total for single-phase.

## Working conventions (how we build here)
- **Dummy-first.** Build and test every code path against `DummyProfile` + `NullTransport`
  (a fake inverter, no hardware) before pointing at real hardware. The dummy reports the
  full canonical set and accepts writes in-memory.
- **Validate against the device's own screen.** Every register address/scale/sign in a
  profile is confirmed against the inverter display — community maps (kellerza/sunsynk)
  are a seed to verify, never to trust blindly. Register-map accuracy is the #1 bug source.
- **Profiles are data, not code.** Adding a brand = adding YAML (+ rare custom decode).
  Sunsynk/Sol-Ark/Deye share `deye-base`; extend, don't fork.
- **Pin profiles to firmware.** The SG05LP1 map is tied to Protocol 2.1 / MCU 5386 /
  COMM e43d. Warn on mismatch at connect — firmware updates can shift addresses.
- **Egress/integrations are off the hot path.** A failing integration degrades to a
  warning, never blocks polling/persistence.
- **Keep `README.md` current.** It's the user-facing front door — aimed at home users, focused on
  how simple it is to run, the feature set, and that it's free/open-source (BSD-3). When a change
  affects what users can do or how they run/install it, update the README in the same PR, including
  its **Project status** notice. Don't let the README drift behind reality. (Design detail lives in
  `plan.md`, roadmap in `TASKS.md` — README stays user-focused, not a spec dump.)
- **License: BSD 3-Clause, © 2026 Darren Horrocks** — the whole project. New source files inherit it;
  don't introduce dependencies or code under incompatible licenses.
- **Tests are part of "done" (§21).** No deliverable is complete without tests in the same PR.
  Use the deterministic dummy (fixed seed) and checked-in `regscan` snapshots as fixtures — no
  hardware needed. Test the gnarly pure logic hardest: profile decode/normalization, sign
  conventions, settings encode/read round-trip, write-safety (allow-list + bounds), energy
  accounting, forecast math, stats.

## Testing bar (§21)
- **Backend:** `pytest` + `pytest-cov` + `pytest-asyncio`. **CI gate: suite must be 100% green;
  overall backend line coverage ≥ 80%; critical-logic modules (decode/normalization, settings
  encode/read, write-safety, energy accounting, forecast, stats) ≥ 90%.** Coverage thresholds
  fail the build. Targets are reasonable, not vanity-100% — cover what can corrupt data or
  mis-program the inverter; don't chase coverage on glue.
- **Frontend:** Angular test runner; presentational components + services (schema-form, WS,
  Theme) unit-tested; ~70%+ reasonable.
- **Integration/E2E:** **Playwright** drives the full app in **dummy mode** (no hardware,
  seed-deterministic) as an automated user. Reserve E2E for what unit tests *can't* reach —
  cross-layer, user-observable flows (live WS → DOM updates, socket-drop → polling fallback,
  Control validate→confirm→write→read-back round-trip against the dummy, schema-generated form,
  theming/nav/charts). Decode/encode/energy/forecast/stats/allow-list math stays **unit-tested**,
  never duplicated in E2E. E2E is a pass/fail CI gate (not coverage-measured).
- **CI = GitHub Actions** (`.github/workflows/ci.yml`, task T021), on every push + PR via the
  working-copy path — no hardware/Docker. **Hard gates that fail the build (not warnings):**
  build/compile errors (`pip install` + `ng build`, lint/types), any unit-test failure, coverage
  below the thresholds above, **any Playwright E2E failure**, and the no-CDN check (§8). Branch
  protection requires it green.
- **Releases (`.github/workflows/release.yml`, task T022):** pushing a git tag `version/x.y`
  cuts a release — re-runs the CI gates, parses `x.y` from the tag as the single source of
  truth (stamped into the footer + `/api/health`), builds the `solarvolt-x.y.tar.gz`
  bundle (+ optional GHCR image), and publishes a **GitHub Release titled `x.y`**. Don't
  hand-edit version constants; the tag drives it.

## Write-back safety (`plan.md` §12) — the highest-risk feature
Control is **off by default** behind the `SOLARVOLT_ENABLE_CONTROL` deploy flag
(env var). When off: write endpoints 403, Control UI hidden, `control` capability
suppressed. When building any write path, ALL of these apply:
1. Schema validation (bounds/enums), client- **and** server-side, before any register is touched.
2. **Write-register allow-list** — only the holding registers in the profile's settings
   map are writable. No arbitrary-address writes through the API, ever.
3. Explicit confirmation (UI shows current→proposed diff).
4. Read-back verification — re-read after write; mismatch ⇒ surface rollback, not success.
5. Atomic-ish slot writes + etag/`If-Match` concurrency (409 on stale).
6. Audit log of every write (when / source / old→new / result).
7. Dummy-first — exercise the whole flow against the dummy before real hardware.

## Updating this file
When you establish build/test commands, add a backend/frontend dir, or change a
load-bearing contract, update the relevant section here so the next session inherits it.
Keep `plan.md` as the spec and `TASKS.md` as the backlog — don't duplicate task tracking here.
