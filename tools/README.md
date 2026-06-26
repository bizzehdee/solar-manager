# Register Discovery Tool (`regscan.py`)

Phase −1 tooling for SolarVolt (see `../plan.md` §11). **Read-only** Modbus
register scanner that helps reverse-engineer an inverter's register map by
correlating decoded values against known system states. Output is a single
Markdown report designed to be **pasted to Claude** to build a device profile
and update `plan.md`.

It never writes to the device — holding registers are read, never set.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # pymodbus + pyserial (real scans only)
```

`--mock` mode needs no dependencies and no hardware.

## The method (why this works)

Modbus is request/response and registers are undocumented, so the map is worked
out by **differential scanning**:

1. Put the system in a known, observable state and read the inverter's own
   screen (PV power, SoC, battery V/A, grid power).
2. `scan` with a `--label` and `--condition key=value` notes recording what the
   screen shows.
3. Change **one** thing (cover a panel, switch a big load, let the battery
   charge/discharge) and `scan` again with a new label.
4. Repeat for a few distinct states (e.g. high-PV, low-PV, charging,
   discharging, exporting).
5. `report` — the registers that **changed** between states, in the direction
   you'd expect, reveal the live measurements and their **sign conventions**.

## Usage

```bash
# Real inverter on RS485 — capture several labelled states
./regscan.py scan --port /dev/ttyUSB0 --slave 1 --start 0 --end 512 \
    --vendor sunsynk --model SYNK-8K-SG05LP1 \
    --fw-protocol 2.1 --fw-mcu 5386 --fw-comm e43d \
    --label midday-full-sun \
    --condition pv_w=6100 --condition soc_pct=78 --condition grid_w=0 \
    --note "clear sky, no big loads"

# ...change one condition, then:
./regscan.py scan --port /dev/ttyUSB0 --slave 1 --start 0 --end 512 \
    --label panel-covered --condition pv_w=900 --condition soc_pct=80

# Consolidate everything into the paste-to-Claude report
./regscan.py report
#   -> regscan-output/regscan-report.md     <-- paste this to Claude
#   -> regscan-output/regscan-report.json   (machine-readable)

# ...or annotate it with a candidate map so known registers are labelled:
./regscan.py report --map sunsynk-deye.tsv --variant 1PH
```

With `--map`, every known address in the report's tables is labelled with the
map's **name [group] and decoded value** (e.g. `Battery SOC [diagnostics] = 78`)
instead of the heuristic hint — so the "changed across states" table reads as
real quantities, and map **collisions** show inline (both names, decoded each
way) for you to resolve against the screen. The variant defaults to the one the
snapshot was scanned with (`scan --map --variant …`), or pass `--variant`.

### Targeted scan — read only the map's registers

Sweeping `0..708` reads hundreds of registers you don't care about. Point `scan`
at the map instead and it reads **only the addresses the map references**,
grouped into a few clustered transactions (nearby addresses share a read; big
empty gaps are skipped):

```bash
# union of all variants' registers (good for type detection — probes everything):
./regscan.py scan --port /dev/ttyUSB0 --map sunsynk-deye.tsv --label midday

# just one variant's registers (fewer reads still), to validate that variant:
./regscan.py scan --port /dev/ttyUSB0 --map sunsynk-deye.tsv --variant 1PH --label midday
```

It writes the same `snapshot-*.json` as a range scan, so `report` and `verify`
work on it unchanged. `--cluster-gap N` tunes how aggressively nearby addresses
are merged (default 8 — bigger means fewer transactions but more filler reads).
Maps are holding-register maps, so a `--map` scan defaults to `--table holding`.

You can also skip the snapshot entirely: **`verify --map … --port …`** does the
targeted read live and prints the comparison directly (no JSON in between).

### Port already in use? Sniff it passively

If something already owns the port (you'll see `Could not exclusively lock port
/dev/ttyUSB0: Resource temporarily unavailable`), don't add a second Modbus
master — collisions corrupt the bus. Instead **sniff** the traffic the existing
master (the stock logger/poller) is already generating:

```bash
./regscan.py scan --port /dev/ttyUSB0 --baud 9600 --passive --duration 120 \
    --vendor sunsynk --model SYNK-8K-SG05LP1 \
    --label midday-passive --condition pv_w=6100 --condition soc_pct=78
```

Passive mode opens the port **non-exclusively**, reconstructs Modbus RTU frames
by their inter-byte gaps, CRC-checks them, and pairs each read-response with the
request that asked for it (responses don't carry the address — the request does).
You only capture registers the other master actually polls, so sniff for a while
(`--duration`) to catch its full cycle. Baud/parity **must match** the real
master, and your adapter must be tapping the same A/B pair.

> If you can instead **stop the other process** (e.g. `systemctl stop` the stock
> poller, unplug the Wi-Fi dongle), an **active** scan (no `--passive`) is more
> thorough — it reads the whole range you specify, not just what someone polls.

### No hardware? Try it with `--mock`

```bash
./regscan.py scan --mock --start 0 --end 64 --label demo-a
./regscan.py scan --mock --start 0 --end 64 --label demo-b
./regscan.py report
```

(Mock data is synthetic, so its plausibility hints are meaningless — it only
demonstrates the workflow and output format.)

### Got a candidate map already? Verify it (`verify`)

For well-known inverters a community register map may already exist — e.g. the
**[kellerza/sunsynk definitions table](https://kellerza.github.io/sunsynk/reference/definitions#available-sensors)**,
which covers the Deye/Sunsynk family in `1PH` / `1PH-16kw` / `3PH` / `3PH-hv`
variants. That's a huge head-start, but these maps **contain errors and address
collisions** and vary by model/firmware, so they must be *verified*, not trusted
blindly. `verify` turns Phase −1 from blind discovery into targeted checking:

The Deye/Sunsynk table is **already bundled** as [`sunsynk-deye.tsv`](sunsynk-deye.tsv)
(columns `name`, `1PH`, `1PH-16kw`, `3PH`, `3PH-hv`, `group`). Cells use the
table's own syntax: `[184]` · `[183] * 0.01` · `[190] S` · `[232] & 0x01` ·
`[63,64] * 0.1` · `[182] * 0.1 - 100` (`S` = signed, `&` = bitmask, `[a,b]` =
multi-register, trailing `- N`/`+ N` = offset — Sunsynk temps are `(°C+100)×10`,
so the bundled file decodes them as `* 0.1 - 100`).

```bash
# Capture a normal scan in a known state, then verify the bundled map against it.
# The SG05LP1 is single-phase, so use --variant 1PH:
./regscan.py scan --port /dev/ttyUSB0 --start 0 --end 700 --label midday \
    --condition soc_pct=78 --condition pv_w=6100
./regscan.py verify --map sunsynk-deye.tsv --variant 1PH \
    --from regscan-output/snapshot-*.json
```

For each map entry it prints the value **decoded the way the map says**, so you
tick it against the inverter's own screen — a match confirms the address/scale/
sign for *your* model; a mismatch means the map is wrong here. It also flags the
map's **self-collisions** (e.g. 1PH `[184]` is listed for both Battery SOC and
AUX L1 current). Output: a console table + `regscan-output/verify-report.md`.

You can also verify live (`--port`, reads only the addresses the map needs) or
with no hardware (`--mock`). Default register table is `holding` (what Sunsynk
uses); override with `--table input`.

### Don't know the variant? Detect the inverter type

**Omit `--variant`** and `verify` decodes **every** variant column side by side
from one scan, so the column whose registers actually respond (and read sane)
tells you the inverter type:

```bash
# Scan the full union range so wrong-variant addresses get probed and error out:
./regscan.py scan --port /dev/ttyUSB0 --start 0 --end 708 --label probe
./regscan.py verify --map sunsynk-deye.tsv --from regscan-output/snapshot-*.json
```

```
  variant       readable  rejected  not-scanned   match
  ------------------------------------------------------
  1PH                141         2            0     99%  <= likely
  1PH-16kw           141         2            0     99%
  3PH                131       106            0     55%
  3PH-hv             165       115            0     59%
```

The right variant reads its own registers (few **rejected**); wrong variants hit
out-of-range addresses and error out, so the **match %** (rejection rate, not raw
count) is the discriminator. It writes a full **`verify-matrix.csv`** — a
`name × variant` grid of decoded values you open as a spreadsheet to confirm the
winning column row-by-row against the screen — plus `verify-matrix.md`. (Scanning
the full `0..708` range matters here: addresses you never scan show as
`not-scanned`, which carries no signal — only *rejected* does.)

### Verify scale factors against the API — `dump`

Once you have a profile, use `dump` to continuously read its registers by name so
you can cross-reference raw values against decoded values from another source (e.g.
the Sunsynk cloud API) to confirm scale/sign assumptions:

```bash
# Single shot — print all metrics to stdout (no hardware: --mock)
./regscan.py dump --profile profiles/deye-base.yaml --mock

# Poll every 10 s, append named rows to CSV for later analysis
./regscan.py dump --profile profiles/deye-base.yaml \
    --port /dev/ttyUSB0 --interval 10 --out deye-raw.csv

# Only the BMS CAN aggregate and per-pack metrics (TBC scales)
./regscan.py dump --profile profiles/deye-base.yaml \
    --port /dev/ttyUSB0 --interval 30 --out bms-packs.csv \
    --filter bms_can,pack1,pack2,pack3

# Child profile — extends: deye-base is resolved automatically
./regscan.py dump --profile profiles/sunsynk-8k-sg05lp1.yaml \
    --port /dev/ttyUSB0 --interval 10 --out dump.csv
```

The CSV has columns: `timestamp_utc`, `metric`, `addr`, `raw`, `decoded`.
Open it alongside the cloud API's decoded values and the `raw` column lets you
work out the exact scale factor for any metric marked TBC in the profile.

`--filter` accepts comma-separated name **prefixes** — `--filter pack` matches all
`pack1_*`, `pack2_*`, etc. Omit to dump every metric.

Requires `pyyaml`: `pip install pyyaml`.

## Key options (`scan`)

| Option | Meaning |
|--------|---------|
| `--port` / `--baud` / `--slave` | serial connection (baud default 9600, slave default 1) |
| `--start` / `--end` | register address range (inclusive) |
| `--table holding\|input\|both` | which register space to sweep (default both) |
| `--block-size` | registers per read (default 32; lower if the device is fussy) |
| `--retries` / `--backoff` | resilience for a flaky RS485 link |
| `--label` (required) | short name for this system state |
| `--condition k=v` (repeatable) | values read off the inverter screen — the ground truth |
| `--note` | free-text description |
| `--vendor` / `--model` / `--fw-*` | provenance, stamped into output (ties a map to its firmware) |
| `--passive` / `--duration` | sniff another master's traffic (non-exclusive open) for N seconds, instead of polling |
| `--mock` | synthetic device, no hardware/deps |
| `-v` / `--verbose` | trace each step (port open, every block/frame read, retries, per-register hints, decode) to **stderr** |

`-v` is available on both `scan` and `report`. Traces go to **stderr**, so the
normal summary on stdout (and anything you pipe) stays clean — e.g.
`./regscan.py scan ... -v 2>scan.log` keeps a full trace while the terminal shows
only the result. On a real scan it's the easiest way to see exactly which blocks
read cleanly, which addresses are unreadable, and (in `--passive`) how request/
response frames are being paired.

## Output

Per `scan`: `snapshot-<ts>-<label>.json` (full decodings) + `.csv` (flat table).
Per `report`: `regscan-report.md` (for Claude) + `regscan-report.json`.
Per `verify` (one `--variant`): `verify-report.md` (decoded-per-map + collisions).
Per `verify` (all variants): `verify-matrix.csv` + `verify-matrix.md` (name×variant
grid of decoded values + per-variant readable/rejected coverage for type detection).

Each register is decoded several ways (uint16/int16, 32-bit pairs in both word
orders, ×0.1/×0.01 scalings) with advisory plausibility hints. Discovery doesn't
commit to a type — it surfaces candidates and lets correlation pick the truth.

## Reuse

The tool is vendor-neutral. Point it at any Modbus inverter/BMS (`--vendor` /
`--model`) to bootstrap a new profile — it's the standard "onboard a new device"
utility, not a Sunsynk one-off.
