# Solar Manager

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

- **Live "Now" dashboard** — PV, battery SoC/power, grid import/export and load, updating
  in real time over a WebSocket (falls back to polling if the socket drops).
- **History & charts** — every reading is logged to a local SQLite database, rolled up
  (5-minute / hourly / daily) and charted, with metric, resolution and date-range pickers.
- **Multiple devices** — add, edit and remove devices from **Settings › Devices**; mix
  brands/models freely (each is just a profile).
- **Statistics** — daily energy totals, self-consumption & self-sufficiency, battery
  round-trip efficiency, and **cost / savings / CO₂** from a configurable tariff (flat or
  time-of-use, with seasonal variants).
- **Fault & battery-health surfacing** — decoded inverter fault codes shown as a banner;
  battery State-of-Health / cycles panel when the BMS reports them.
- **Inverter settings viewer** — the Control page shows every decoded setting (work-mode
  timer slots, charge/SoC limits, battery voltages, work mode) read-only. *Editing those
  settings is coming next, gated behind an explicit opt-in flag.*
- **Solar & battery forecast** — a weather-driven (free [Open-Meteo](https://open-meteo.com))
  PV-generation forecast for your array (tilt/azimuth/kWp), plus a projected battery-SoC
  curve with empty/full times. Switch between **today / tomorrow / 3-day / 7-day** views
  (defaults to today) with a per-day outlook (expected generation + SoC range + low-battery
  warnings). Configure your site/arrays in Settings.
- **Works with no hardware out of the box** — a built-in **dummy inverter** produces
  realistic, time-of-day-aware data, so you can try the whole app on a fresh clone.
- **Real inverter support** — read live instant data from a Sunsynk SG05LP1 over a
  USB-RS485 adapter.
- *Coming:* alerts/notifications and opt-in inverter control (work-mode timers). See
  `TASKS.md` for the roadmap.

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
export SOLAR_MANAGER_MODBUS_PORT=/dev/ttyUSB0   # your adapter
# optional: SOLAR_MANAGER_MODBUS_BAUD=9600  SOLAR_MANAGER_MODBUS_SLAVE_ID=1
make dev
```

With `SOLAR_MANAGER_MODBUS_PORT` set, the app reads your real inverter instead of the
dummy. Control/write-back stays **off** unless you explicitly enable it
(`SOLAR_MANAGER_ENABLE_CONTROL=true`) — the app is monitoring-only by default.

## Project status

**Early development.** The app is fully usable today on the built-in **dummy** inverter
(live dashboard, history & charts, multi-device config — the full canonical metric set).
**Real Sunsynk SG05LP1 instant data over Modbus RTU is wired up** and validated against
real register captures, including the **battery and grid power directions** (a daytime
capture will finalise grid *export* polarity and PV voltage under load). **Persistence +
History** (Phase 2), **Statistics — energy, self-consumption, cost/savings/CO₂, fault &
battery-health surfacing** (Phase 3), and the **solar/battery Forecast** (Phase 4) are in.
Alerts and opt-in control are still on the roadmap (`TASKS.md`).

The forecast fetches weather from Open-Meteo's free public API — the **only** outbound
request the app makes, and only when the Forecast view/config is used. Everything else
runs entirely on your LAN.

Data is stored in a local SQLite file (`solar-manager.db` by default); set
`SOLAR_MANAGER_DB_PATH` to relocate it and `SOLAR_MANAGER_RETENTION_DAYS` to tune how long
raw samples are kept (rollups are kept indefinitely).
