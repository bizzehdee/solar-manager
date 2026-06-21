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
- **Customisable dashboards** — "Now" and "History" are built-in dashboards on a drag-and-drop
  grid. Hit **Edit** to rearrange, resize, add or remove widgets (gauges, metric cards, charts,
  the energy-flow diagram) and pick which metric each one shows. Build **your own dashboards** too,
  and **export/import** them as JSON files to share or back up. Built-ins can be tweaked and reset
  to default any time.
- **Multiple devices & connection types** — add, edit and remove devices from **Settings ›
  Devices**; mix brands/models freely (each is just a profile). Connect over **Modbus RTU**
  (USB-RS485), **Modbus TCP** (port 502 over the LAN), a **SolarmanV5** Wi-Fi logger stick, or
  bridge in **Solar Assistant** over MQTT (read its sensors to run both side-by-side while
  testing). Adding one is point-and-click — pick the connection, the model profile, then **Test
  connection** to confirm it responds before saving.
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
  USB-RS485 adapter, Modbus TCP, or a SolarmanV5 logger.
- **Alerts** — a rule engine (low battery SoC, device offline/stale, inverter fault, over-temp…)
  with thresholds, hysteresis, debounce and quiet hours; sensible rules shipped on, and a
  **rule editor** to add/edit/enable/delete your own. Active/history **inbox** with acknowledge &
  snooze and a header **bell badge**. Push delivery via **email (SMTP), Telegram, ntfy, Gotify,
  Pushover, or any number of custom webhooks** — each webhook with its own URL, headers and
  **payload template** (Slack/Discord/HA presets included), so you can POST whatever shape a service
  expects. Configure any, then pick channels per rule (with a one-click test). All off the hot path —
  a failing notifier never disrupts monitoring.
- **Automation** — build your own **rules** that set inverter settings (e.g. work-mode slot 1
  target SoC) from conditions you combine: **day of week, time/date window, metric thresholds or
  tariff window**. Rules and individual actions carry **priorities** (the highest wins on a
  conflict) and are **disabled by default** — a live **"what it would do now"** panel shows each
  proposed change with a safe / at-risk / blocked badge, so you preview everything before arming it.
  Building and previewing rules needs no special setup; once you arm a rule, an **"Apply now"**
  button and a background scheduler write the changes to the inverter — but only if you've enabled
  control (the same `SOLARVOLT_ENABLE_CONTROL` switch that guards all write-back). Without it,
  automation stays preview-only.
- **Integrations** — an **MQTT publisher with Home Assistant auto-discovery** (every metric shows up
  as an HA sensor with no manual YAML), a **Prometheus `/metrics`** endpoint for Grafana users, and
  **outbound readings webhooks** — any number of endpoints, each posting the latest snapshot on its
  own interval with a custom payload template (Node-RED / IFTTT / custom). (PVOutput is on the roadmap.)
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

Add your device in the app — **Settings › Devices › Add device**. Pick a connection type
(Modbus RTU over a USB-RS485 adapter, Modbus TCP, a SolarmanV5 logger, or a Solar Assistant
MQTT bridge), choose the serial port/host and the model profile, then **Test connection** to
confirm it responds before saving. Devices are stored in the app's database, so they persist
and you can add/edit/remove as many as you like — no config files or env vars to set.

Control/write-back stays **off** unless you explicitly enable it
(`SOLARVOLT_ENABLE_CONTROL=true`) — the app is monitoring-only by default.

## Install it for good (Raspberry Pi / Ubuntu)

To run SolarVolt unattended — starting on boot and restarting on failure — install it as a
system service. From a clone on the Pi (fresh Ubuntu is fine):

```sh
sudo ./install.sh
```

That one script sets everything up **in place**: a Python virtualenv, a one-time frontend
build, a `solarvolt` **systemd service** serving the UI + API on **port 8000**, a database
under `/var/lib/solarvolt/`, serial access (adds you to the `dialout` group) and — if a
USB-RS485 adapter is plugged in — a **stable `/dev/solarvolt-rs485`** device path so it
doesn't move between reboots. Prefer to look before you leap? `./install.sh --check` prints
exactly what it will do and changes nothing.

Then open `http://<your-pi>:8000/`. Settings live in **`/etc/solarvolt/solarvolt.env`** —
edit it (serial port, control flag, tariff cadence…) and `sudo systemctl restart solarvolt`.
Your config and database are kept across upgrades.

```sh
journalctl -u solarvolt -f          # follow the logs
sudo systemctl restart solarvolt    # after editing the config
git pull && sudo ./install.sh       # update to a newer version
sudo ./uninstall.sh                 # remove the service (keeps your data; --purge wipes it)
```

To turn on inverter write-back, either run `sudo ./install.sh --enable-control` or set
`SOLARVOLT_ENABLE_CONTROL=true` in the env file and restart.

### Prefer Docker?

A maintained Compose path is included:

```sh
docker compose up -d            # build + run on :8000
docker compose logs -f
```

The single container serves the UI + API; the database persists in a named volume. Edit the
environment in `docker-compose.yml` (same `SOLARVOLT_*` variables), and uncomment the `devices:` /
`group_add:` lines to pass a USB-RS485 adapter through to a real inverter. The image is multi-arch
(arm64 + amd64), so it runs on a Pi or an x86 box.

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
background scheduler) once control is enabled. Both deployment paths are in — a **native systemd
install** for Raspberry Pi / Ubuntu (`./install.sh`) and a **Docker/Compose** path. Notification/webhook
automation actions, the remaining integrations (MQTT/Home Assistant, PVOutput) and extra notification
channels are on the roadmap (`TASKS.md`).

The forecast fetches weather from Open-Meteo's free public API — the **only** outbound
request the app makes, and only when the Forecast view/config is used. Everything else
runs entirely on your LAN.

Data is stored in a local SQLite file (`solarvolt.db` by default); set
`SOLARVOLT_DB_PATH` to relocate it and `SOLARVOLT_RETENTION_DAYS` to tune how long
raw samples are kept (rollups are kept indefinitely).
