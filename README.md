# SolarVolt

A free, open-source web app to **monitor, chart and (optionally) control your home
solar + battery system** — from your own LAN, with no cloud account and no subscription.

It runs happily on a Raspberry Pi next to your inverter. Open it on your phone or laptop
and watch your panels, battery and grid in real time.

- **Vendor-agnostic.** First hardware target is the **Sunsynk SYNK-8K-SG05LP1** inverter
  (over RS485 / Modbus), but support for a new brand is *data, not code* — you add a
  profile, not a patch. Sunsynk / Sol-Ark / Deye already share one map.
- **Yours, locally.** Single house, home LAN, no logins. Nothing is sent to the cloud and
  the app loads with **zero outbound requests** — every asset is bundled and self-hosted.
- **Free & open.** BSD 3-Clause licensed. © 2026 Darren Horrocks.

## What it does

- **Live "Now" dashboard** — an at-a-glance **energy-flow diagram** (solar, battery, house, grid and
  inverter, with animated arrows showing which way power is moving right now) plus PV, battery
  SoC/power, grid import/export and load gauges — updating in real time over a WebSocket (falls back
  to polling if the socket drops).
- **History & charts** — every reading is logged to a local SQLite database, rolled up
  (5-minute / hourly / daily) and charted, with metric, resolution and date-range pickers.
- **Multiple devices** — add, edit and remove devices from **Settings › Devices**; mix
  brands/models freely (each is just a profile). Adding one is point-and-click: pick the
  serial port from a list of detected adapters and the model from a profile dropdown, then
  **Test connection** to confirm the inverter responds before saving.
- **Statistics** — daily energy totals, self-consumption & self-sufficiency, battery
  round-trip efficiency, and **cost / savings / CO₂** from a configurable tariff: a fixed
  **standing charge**, **flat or time-of-use** import rates (multiple daily windows, e.g. a
  cheap overnight rate), a flat export rate, and optional seasonal variants.
- **Fault & battery-health surfacing** — decoded inverter fault codes shown as a banner;
  battery State-of-Health / cycles panel when the BMS reports them.
- **Inverter settings — view & (optionally) edit** — the Control page shows every decoded
  setting (work-mode timer slots, charge/SoC limits, battery voltages, work mode). Viewing is
  always available; **editing is opt-in** (`SOLARVOLT_ENABLE_CONTROL=true`) and, when on, every
  change is validated, shown as a current→proposed **diff to confirm**, written, then **read
  back and verified** (a mismatch is flagged, not reported as success). Every write is recorded
  in an audit log. Off by default — the app is monitoring-only until you turn control on.
- **Solar & battery forecast** — a weather-driven (free [Open-Meteo](https://open-meteo.com))
  PV-generation forecast for your array (tilt/azimuth/kWp), plus a projected battery-SoC
  curve with empty/full times. Switch between **today / tomorrow / 3-day / 7-day** views
  (defaults to today) with a per-day outlook (expected generation + SoC range + low-battery
  warnings). Configure your site/arrays in Settings.
- **Works with no hardware out of the box** — a built-in **dummy inverter** produces
  realistic, time-of-day-aware data, so you can try the whole app on a fresh clone.
- **Real inverter support** — read live instant data from a Sunsynk SG05LP1 over a
  USB-RS485 adapter.
- **Alerts** — a rule engine (low battery SoC, device offline/stale, inverter fault, over-temp…)
  with thresholds, hysteresis, debounce and quiet hours; sensible rules shipped on, and a
  **rule editor** to add/edit/enable/delete your own. Active/history **inbox** with acknowledge &
  snooze and a header **bell badge**. Push delivery via **webhook, email (SMTP), Telegram, ntfy,
  Gotify or Pushover** — configure any, then pick channels per rule (with a one-click test). All off
  the hot path — a failing notifier never disrupts monitoring.
- **Automation** — build your own **rules** that set inverter settings (e.g. work-mode slot 1
  target SoC) from conditions you combine: **day of week, time/date window, metric thresholds or
  tariff window**. Rules and individual actions carry **priorities** (the highest wins on a
  conflict) and are **disabled by default** — a live **"what it would do now"** panel shows each
  proposed change with a safe / at-risk / blocked badge, so you preview everything before arming it.
  Building and previewing rules needs no special setup; once you arm a rule, an **"Apply now"**
  button and a background scheduler write the changes to the inverter — but only if you've enabled
  control (the same `SOLARVOLT_ENABLE_CONTROL` switch that guards all write-back). Without it,
  automation stays preview-only.
- **Integrations** — a **Prometheus `/metrics`** endpoint exposes live readings for Grafana users,
  and an **outbound readings webhook** posts each snapshot as JSON to a URL of your choice
  (Node-RED / IFTTT / custom). (MQTT / Home-Assistant discovery and PVOutput are on the roadmap.)
- **Operational niceties** — **backup / restore** the database and **export any metric to CSV**;
  a **Diagnostics** tab in Settings (DB size, rollup lag, per-device Modbus comms health, grid-outage log);
  **inverter clock drift** with one-click sync; a **performance-ratio calibration** that tunes the
  forecast from measured history; selectable **locale** for date/number formatting; and an
  **installable PWA** (add to home screen, rides out brief network blips) — all self-hosted.
- *Coming:* MQTT + Home Assistant discovery, PVOutput. See `TASKS.md`.

## Try it (no hardware needed)

From a fresh clone:

```sh
make install     # Python venv + frontend npm deps
make dev         # backend (:8000) + Angular dev server (:4200)
```

Open <http://localhost:4200> — you'll get a live synthetic dashboard driven by the dummy
inverter. No inverter, no config, no cloud.

## Connecting a real inverter

Plug a USB-RS485 adapter into the inverter's RS485 port and point the app at it:

```sh
export SOLARVOLT_MODBUS_PORT=/dev/ttyUSB0   # your adapter
# optional: SOLARVOLT_MODBUS_BAUD=9600  SOLARVOLT_MODBUS_SLAVE_ID=1
make dev
```

With `SOLARVOLT_MODBUS_PORT` set, the app reads your real inverter instead of the
dummy. Control/write-back stays **off** unless you explicitly enable it
(`SOLARVOLT_ENABLE_CONTROL=true`) — the app is monitoring-only by default.

## Project status

**Early development.** The app is fully usable today on the built-in **dummy** inverter
(live dashboard, history & charts, multi-device config — the full canonical metric set).
**Real Sunsynk SG05LP1 instant data over Modbus RTU is wired up** and validated against
real register captures, including the **battery and grid power directions** (a daytime
capture will finalise grid *export* polarity and PV voltage under load). **Persistence +
History** (Phase 2), **Statistics — energy, self-consumption, cost/savings/CO₂, fault &
battery-health surfacing** (Phase 3), the **solar/battery Forecast** (Phase 4), the read-only
**settings viewer** (Phase 5) and **opt-in settings control / write-back** (Phase 6, off by
default, with validation → confirm → read-back-verify → audit) and the **alerts engine +
inbox + Prometheus endpoint** (Phase 7) are all in. **Rule-based automation** (combine
day/time/metric/tariff conditions to drive inverter settings, with a rule editor and a live "what
it would do now" panel) is in — preview always, and **opt-in apply** (an "Apply now" button plus a
background scheduler) once control is enabled. Notification/webhook automation actions, the
remaining integrations (MQTT/Home Assistant, PVOutput) and extra notification channels are on the
roadmap (`TASKS.md`).

The forecast fetches weather from Open-Meteo's free public API — the **only** outbound
request the app makes, and only when the Forecast view/config is used. Everything else
runs entirely on your LAN.

Data is stored in a local SQLite file (`solarvolt.db` by default); set
`SOLARVOLT_DB_PATH` to relocate it and `SOLARVOLT_RETENTION_DAYS` to tune how long
raw samples are kept (rollups are kept indefinitely).
