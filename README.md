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
- **Works with no hardware out of the box** — a built-in **dummy inverter** produces
  realistic, time-of-day-aware data, so you can try the whole app on a fresh clone.
- **Real inverter support** — read live instant data from a Sunsynk SG05LP1 over a
  USB-RS485 adapter.
- *Coming:* history & charts, energy/cost/CO₂ stats, solar forecast, alerts, and opt-in
  inverter control (work-mode timers). See `TASKS.md` for the roadmap.

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
(live dashboard, WebSocket, the full canonical metric set). **Real Sunsynk SG05LP1 instant
data over Modbus RTU is now wired up** and validated against real register captures —
including the **battery and grid power directions** (charge/discharge and import/export),
which are now confirmed. A daytime capture will finalise one remaining detail (grid *export*
polarity and PV voltage under load). History, statistics, forecasting and control are still
on the roadmap (`TASKS.md`).
