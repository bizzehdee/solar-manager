#!/usr/bin/env python3
"""regscan.py — Modbus register-discovery tool for SolarVolt (Phase -1, see plan.md §11).

READ-ONLY. Sweeps a Modbus device's register space, decodes each register several
ways, and writes timestamped snapshots. A `report` step consolidates one or more
snapshots into a single Markdown file you can paste to Claude to (a) propose a
device profile (`profiles/<vendor>-<model>.yaml`) and (b) update plan.md.

Method (plan.md §11):
  1. `scan` while the system is in a *known* state, labelling the conditions
     (e.g. --label midday-full-sun --note "PV 6.1kW, SoC 78%, importing 0W").
  2. `scan` again after changing ONE thing (cover a panel, switch a load,
     let the battery charge). Repeat for a few distinct states.
  3. `report` over all snapshots — the registers that *changed* between states,
     correlated with what you changed, reveal the map and the sign conventions.

Nothing is ever written to the device. Holding registers are read, never set.

Usage examples:
  # one snapshot of a real inverter on RS485
  ./regscan.py scan --port /dev/ttyUSB0 --slave 1 --start 0 --end 512 \
      --label midday --note "PV 6.1kW, SoC 78%, grid 0W" \
      --vendor sunsynk --model SYNK-8K-SG05LP1 \
      --fw-protocol 2.1 --fw-mcu 5386 --fw-comm e43d

  # targeted scan: read ONLY the registers a map references (clustered into a
  # few reads), instead of sweeping a whole range:
  ./regscan.py scan --port /dev/ttyUSB0 --map sunsynk-deye.tsv --label midday
  ./regscan.py scan --port /dev/ttyUSB0 --map sunsynk-deye.tsv --variant 1PH --label midday

  # try the tool with no hardware
  ./regscan.py scan --mock --start 0 --end 64 --label demo-a
  ./regscan.py scan --mock --start 0 --end 64 --label demo-b
  ./regscan.py report                 # -> regscan-output/regscan-report.md

  # annotate the report with a candidate map: known registers get their real
  # name/group + decoded value instead of just a heuristic hint:
  ./regscan.py report --map sunsynk-deye.tsv --variant 1PH

  # add -v / --verbose to trace each step (to stderr) on any command:
  ./regscan.py scan --port /dev/ttyUSB0 --start 0 --end 512 --label x -v
  ./regscan.py scan ... -v 2>scan.log  # keep a full trace, clean stdout

  # verify a *candidate* map (e.g. the kellerza/sunsynk definitions table,
  # saved as TSV) against a scan — decode each register the way the map says
  # and eyeball it vs the inverter screen. Flags the map's own collisions.
  ./regscan.py verify --map sunsynk.tsv --variant 1PH --from snapshot-*.json

  # ...or OMIT --variant to decode EVERY variant column side by side and
  # detect the inverter type (the column with the fewest rejected registers):
  ./regscan.py verify --map sunsynk.tsv --from snapshot-*.json  # -> verify-matrix.csv

Requires `pymodbus` (>=3.0) for real scans:  pip install pymodbus pyserial
"""
from __future__ import annotations

import argparse
import csv
import glob
import inspect
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

TOOL_VERSION = "1.2"  # 1.2: cell offset/division (temps); 1.1: --map scan/verify/report
DEFAULT_OUT = "regscan-output"

# Verbose trace — set from --verbose in main(). Traces go to stderr so they
# never mix into the normal stdout summary or any piped output.
_VERBOSE = False


def vlog(msg: str) -> None:
    """Print a progress/trace line when --verbose is on (stderr)."""
    if _VERBOSE:
        print(f"  · {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Decoding helpers — present each register multiple ways so values are
# recognisable. The device's true type/scale/word-order is unknown at scan
# time; we surface candidates and let correlation pick the right one.
# --------------------------------------------------------------------------- #
def u16(v: int) -> int:
    return v & 0xFFFF


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def u32(hi: int, lo: int) -> int:
    return ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)


def s32(hi: int, lo: int) -> int:
    v = u32(hi, lo)
    return v - 0x100000000 if v & 0x80000000 else v


def decode_register(addr: int, regs: dict[int, int]) -> dict:
    """All candidate interpretations of the register at `addr`."""
    raw = regs[addr]
    out: dict = {
        "raw": raw,
        "hex": f"0x{raw:04X}",
        "uint16": u16(raw),
        "int16": s16(raw),
        "uint16_x0.1": round(u16(raw) * 0.1, 3),
        "uint16_x0.01": round(u16(raw) * 0.01, 3),
        "int16_x0.1": round(s16(raw) * 0.1, 3),
        "int16_x0.01": round(s16(raw) * 0.01, 3),
    }
    # 32-bit pairings with the *next* register, both word orders.
    nxt = regs.get(addr + 1)
    if nxt is not None:
        out["uint32_be"] = u32(raw, nxt)      # this reg = high word
        out["int32_be"] = s32(raw, nxt)
        out["uint32_le"] = u32(nxt, raw)      # next reg = high word (word-swapped)
        out["int32_le"] = s32(nxt, raw)
    return out


def plausibility_hint(dec: dict) -> str:
    """Cheap heuristics to flag what a register *might* be. Advisory only."""
    hints = []
    u = dec["uint16"]
    s = dec["int16"]
    # Frequency: 50.00 / 60.00 Hz as raw*0.01
    if 4900 <= u <= 5100 or 5900 <= u <= 6100:
        hints.append(f"grid freq? {u * 0.01:.2f}Hz")
    # Percent (SoC / load%)
    if 0 <= u <= 100:
        hints.append("0-100 -> SoC%/load%?")
    # AC voltage direct or x0.1
    if 200 <= u <= 260:
        hints.append(f"AC volts? {u}V")
    elif 2000 <= u <= 2600:
        hints.append(f"AC volts? {u * 0.1:.1f}V (x0.1)")
    # Battery / PV voltage (48V class) as x0.1 or x0.01
    if 4000 <= u <= 6000:
        hints.append(f"48V-batt/PV volts? {u * 0.1:.1f}V (x0.1) / {u * 0.01:.2f}V (x0.01)")
    # Signed power (battery/grid can be +/-)
    if s < 0:
        hints.append(f"signed -> {s} (direction/charge/discharge?)")
    # Temperature with +100 offset convention common on these inverters
    if 900 <= u <= 1300:
        hints.append(f"temp? {(u - 1000) * 0.1:.1f}C (offset-100, x0.1)")
    # Large 32-bit -> likely an energy/runtime counter
    if "uint32_be" in dec and dec["uint32_be"] > 70000:
        hints.append("large 32-bit -> energy/runtime counter?")
    return "; ".join(hints)


# --------------------------------------------------------------------------- #
# Readers — real (pymodbus) and mock. Both expose .read_block().
# --------------------------------------------------------------------------- #
class ModbusReader:
    def read_block(self, table: str, start: int, count: int) -> list[int] | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


# pymodbus has renamed the slave-id keyword across major versions:
#   2.x -> unit= , 3.0-3.x -> slave= , recent 3.x -> device_id=
# Detect the right one from the method signature instead of guessing, so a
# version bump doesn't silently turn every register into "unreadable".
_ID_KWARGS = ("slave", "device_id", "unit")


def _detect_id_kwarg(fn) -> str | None:
    """Return which slave-id keyword `fn` accepts, or None if undeterminable."""
    try:
        params = inspect.signature(fn).parameters
    except (ValueError, TypeError):  # builtin / C-wrapped — can't introspect
        return None
    for name in _ID_KWARGS:
        if name in params:
            return name
    # signature accepts **kwargs but names none of them explicitly -> let caller probe
    return None


class PymodbusReader(ModbusReader):
    def __init__(self, args):
        try:
            from pymodbus.client import ModbusSerialClient
        except Exception as e:  # pragma: no cover - import guard
            sys.exit(
                "ERROR: pymodbus is required for real scans.\n"
                "  pip install pymodbus pyserial\n"
                f"(import failed: {e})"
            )
        self.slave = args.slave
        self.retries = args.retries
        self.backoff = args.backoff
        self.client = ModbusSerialClient(
            port=args.port,
            baudrate=args.baud,
            parity=args.parity,
            stopbits=args.stopbits,
            bytesize=args.bytesize,
            timeout=args.timeout,
        )
        vlog(f"opening {args.port} @ {args.baud} "
             f"{args.bytesize}{args.parity}{args.stopbits}, "
             f"slave {args.slave}, timeout {args.timeout}s")
        if not self.client.connect():
            sys.exit(f"ERROR: could not open serial port {args.port}")
        vlog(f"serial port {args.port} open")
        # Figure out this pymodbus version's slave-id keyword up front.
        self._id_kw = _detect_id_kwarg(self.client.read_holding_registers)
        vlog("pymodbus slave-id keyword: "
             + (repr(self._id_kw) if self._id_kw
                else "undetermined (will probe on first read)"))

    def _call(self, fn, start: int, count: int, id_kw: str):
        return fn(address=start, count=count, **{id_kw: self.slave})

    def _read_once(self, table: str, start: int, count: int):
        fn = (
            self.client.read_holding_registers
            if table == "holding"
            else self.client.read_input_registers
        )
        # Fast path: use the keyword we detected.
        if self._id_kw is not None:
            return self._call(fn, start, count, self._id_kw)
        # Detection was inconclusive — probe the known names once, then cache
        # the winner so we only pay this on the very first read.
        last_err: TypeError | None = None
        for name in _ID_KWARGS:
            try:
                rr = self._call(fn, start, count, name)
            except TypeError as e:
                last_err = e
                continue
            self._id_kw = name
            vlog(f"pymodbus slave-id keyword resolved to {name!r}")
            return rr
        # None worked — surface the real error instead of masking it as a bad read.
        raise last_err if last_err else TypeError("no usable slave-id keyword")

    def read_block(self, table: str, start: int, count: int) -> list[int] | None:
        for attempt in range(self.retries + 1):
            try:
                rr = self._read_once(table, start, count)
                if rr is not None and not rr.isError():
                    return list(rr.registers)
                vlog(f"[{table}] {start}+{count}: device returned an error response"
                     f"{' (retrying)' if attempt < self.retries else ''}")
            except Exception as e:
                vlog(f"[{table}] {start}+{count}: read raised {type(e).__name__}: {e}"
                     f"{' (retrying)' if attempt < self.retries else ''}")
            if attempt < self.retries:
                time.sleep(self.backoff * (attempt + 1))
        return None

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass


class MockReader(ModbusReader):
    """Deterministic-ish synthetic device so the tool and its output format can
    be exercised with no hardware. Values shift with wall-clock seconds so two
    scans a moment apart produce a meaningful diff."""

    def read_block(self, table: str, start: int, count: int) -> list[int] | None:
        import math

        t = time.time()
        regs = []
        for a in range(start, start + count):
            base = (a * 37) % 1000
            wave = int(500 + 400 * math.sin(t / 5.0 + a))
            if table == "holding":
                # a few "settings-like" stable values
                regs.append((a % 6) if a < 50 else base)
            else:
                regs.append(max(0, (base + wave) % 6000))
        # pretend a couple of addresses are unreadable to test gap handling
        return regs


# --------------------------------------------------------------------------- #
# Passive sniffer — listen to RS485 traffic from ANOTHER master (e.g. the real
# logger/poller) without being a master ourselves. Useful when the port is
# already in use, or to capture the exact registers the stock system reads.
# We open the port non-exclusively, reconstruct Modbus RTU frames by inter-byte
# gaps, CRC-check them, and pair read-responses with their preceding requests
# (responses don't carry the address, so the request tells us where the data
# lives).
# --------------------------------------------------------------------------- #
def modbus_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc  # on the wire: low byte first, then high byte


def _crc_ok(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    calc = modbus_crc16(frame[:-2])
    return (frame[-2] | (frame[-1] << 8)) == calc


def passive_sniff(args) -> tuple[dict, list, dict]:
    """Sniff the bus for `--duration` seconds. Returns (raw_by_table, [], stats)."""
    try:
        import serial  # pyserial
    except Exception as e:  # pragma: no cover
        sys.exit(f"ERROR: pyserial required for passive mode. pip install pyserial ({e})")

    # 3.5-character inter-frame gap (assume ~11 bits/char to be safe), min 1.75ms.
    char_time = 11.0 / args.baud
    gap = max(3.5 * char_time, 0.00175)
    ser = serial.Serial(
        port=args.port, baudrate=args.baud, parity=args.parity,
        stopbits=args.stopbits, bytesize=args.bytesize,
        timeout=max(gap, 0.005), exclusive=False,  # <-- non-exclusive: don't lock the port
    )

    holding: dict[int, int] = {}
    inputs: dict[int, int] = {}
    pending: dict[int, tuple[int, int, int]] = {}  # slave -> (func, addr, count)
    stats = {"frames": 0, "crc_ok": 0, "requests": 0, "responses": 0, "mapped": 0}

    end = time.time() + args.duration
    buf = bytearray()
    last = time.monotonic()

    def flush(frame: bytes):
        if not frame:
            return
        stats["frames"] += 1
        if not _crc_ok(frame):
            vlog(f"frame dropped: CRC fail ({len(frame)} bytes)")
            return
        stats["crc_ok"] += 1
        slave, func = frame[0], frame[1]
        if func not in (3, 4):  # only read-holding / read-input
            vlog(f"frame ignored: slave {slave} func {func} (not read-holding/input)")
            return
        table = "holding" if func == 3 else "input"
        body = frame[:-2]
        # Request form is exactly 8 bytes: slave,func,addrHi,addrLo,cntHi,cntLo,crc
        if len(frame) == 8:
            addr = (body[2] << 8) | body[3]
            count = (body[4] << 8) | body[5]
            pending[slave] = (func, addr, count)
            stats["requests"] += 1
            vlog(f"request:  slave {slave} read {table} {addr}..{addr + count - 1} "
                 f"({count} regs)")
            return
        # Response form: slave,func,byteCount,data...,crc  (len == 5 + byteCount)
        bc = body[2]
        if bc > 0 and bc % 2 == 0 and len(frame) == 5 + bc:
            stats["responses"] += 1
            req = pending.pop(slave, None)
            if not req or req[0] != func:
                vlog(f"response: slave {slave} func {func}, {bc // 2} words — "
                     f"no matching request, can't place addresses")
                return
            _, addr, count = req
            words = bc // 2
            target = holding if func == 3 else inputs
            for i in range(min(words, count)):
                hi = body[3 + i * 2]
                lo = body[3 + i * 2 + 1]
                target[addr + i] = (hi << 8) | lo
                stats["mapped"] += 1
            vlog(f"response: slave {slave} {table} {words} words -> "
                 f"{addr}..{addr + min(words, count) - 1}")

    try:
        print(f"Passively sniffing {args.port} for {args.duration}s "
              f"(non-exclusive, gap={gap*1000:.1f}ms)... Ctrl-C to stop early.")
        while time.time() < end:
            b = ser.read(1)
            now = time.monotonic()
            if b:
                if buf and (now - last) > gap:
                    flush(bytes(buf))
                    buf = bytearray()
                buf += b
                last = now
            elif buf and (time.monotonic() - last) > gap:
                flush(bytes(buf))
                buf = bytearray()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if buf:
            flush(bytes(buf))
        ser.close()

    raw_by_table = {}
    if holding:
        raw_by_table["holding"] = holding
    if inputs:
        raw_by_table["input"] = inputs
    print(f"Frames seen {stats['frames']}, CRC-ok {stats['crc_ok']}, "
          f"requests {stats['requests']}, responses {stats['responses']}, "
          f"registers mapped {len(holding) + len(inputs)}.")
    if not raw_by_table:
        print("WARNING: nothing decoded. Check baud/parity match the other master, "
              "and that A/B lines are connected (sniffers tap the same pair).")
    return raw_by_table, [], stats


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #
@dataclass
class Snapshot:
    tool_version: str
    timestamp_utc: str
    label: str
    note: str
    conditions: dict
    vendor: str
    model: str
    firmware: dict
    connection: dict
    # address(str) -> {table, raw, decodings..., hint}
    registers: dict = field(default_factory=dict)
    unreadable: list = field(default_factory=list)


def _collect_active(args) -> tuple[dict, list, list]:
    reader: ModbusReader = MockReader() if args.mock else PymodbusReader(args)
    tables = ["holding", "input"] if args.table == "both" else [args.table]
    total = (args.end - args.start + 1) * len(tables)
    vlog(f"active sweep: {tables} over {args.start}..{args.end} "
         f"({total} registers, {args.block_size}/read, "
         f"{'mock' if args.mock else f'{args.gap}s between reads'})")
    raw_by_table: dict[str, dict[int, int]] = {}
    unreadable: list[str] = []
    try:
        for table in tables:
            values: dict[int, int] = {}
            vlog(f"[{table}] sweeping {args.start}..{args.end}")
            addr = args.start
            while addr <= args.end:
                count = min(args.block_size, args.end - addr + 1)
                vlog(f"[{table}] read {addr}..{addr + count - 1} ({count} regs)")
                block = reader.read_block(table, addr, count)
                if block is None:
                    # Isolate: a single bad address shouldn't blank the block.
                    vlog(f"[{table}] block {addr}..{addr + count - 1} failed — "
                         f"isolating each address")
                    for a in range(addr, addr + count):
                        one = reader.read_block(table, a, 1)
                        if one is None:
                            unreadable.append(f"{table}:{a}")
                            vlog(f"[{table}] {a} unreadable")
                        else:
                            values[a] = one[0]
                else:
                    for i, v in enumerate(block):
                        values[addr + i] = v
                addr += count
                if not args.mock:
                    time.sleep(args.gap)
            vlog(f"[{table}] done: {len(values)} read, "
                 f"{sum(1 for u in unreadable if u.startswith(table + ':'))} unreadable")
            raw_by_table[table] = values
    finally:
        reader.close()
    return raw_by_table, unreadable, tables


def cluster_addresses(addrs, max_gap: int = 8, max_block: int = 32) -> list[tuple[int, int]]:
    """Group sparse addresses into a few contiguous (start, count) reads.

    Addresses within `max_gap` of each other share a block (reading a few filler
    registers is cheaper than another Modbus transaction); larger gaps split,
    and no block exceeds `max_block` registers. So a map scattered across
    0..708 becomes a handful of small reads instead of one 709-register sweep.
    """
    addrs = sorted(set(addrs))
    blocks: list[tuple[int, int]] = []
    if not addrs:
        return blocks
    start = prev = addrs[0]
    for a in addrs[1:]:
        if a - prev <= max_gap and a - start + 1 <= max_block:
            prev = a
        else:
            blocks.append((start, prev - start + 1))
            start = prev = a
    blocks.append((start, prev - start + 1))
    return blocks


def read_targeted(reader: ModbusReader, table: str, needed, gap: float, mock: bool,
                  max_gap: int = 8, max_block: int = 32) -> tuple[dict, list]:
    """Read only the `needed` addresses (clustered), returning (values, unreadable)."""
    needset = set(needed)
    blocks = cluster_addresses(needset, max_gap, max_block)
    covered = sum(c for _, c in blocks)
    vlog(f"[{table}] targeted read: {len(needset)} addresses in {len(blocks)} block(s), "
         f"{covered} registers touched (vs a full sweep), max_gap {max_gap}")
    values: dict[int, int] = {}
    unreadable: list[str] = []
    for start, count in blocks:
        vlog(f"[{table}] read {start}..{start + count - 1} ({count} regs)")
        block = reader.read_block(table, start, count)
        if block is None:
            vlog(f"[{table}] block {start}..{start + count - 1} failed — isolating")
            for a in range(start, start + count):
                one = reader.read_block(table, a, 1)
                if one is None:
                    if a in needset:
                        unreadable.append(f"{table}:{a}")
                        vlog(f"[{table}] {a} unreadable")
                else:
                    values[a] = one[0]
        else:
            for i, v in enumerate(block):
                values[start + i] = v
        if not mock:
            time.sleep(gap)
    return values, unreadable


def _map_addresses(args) -> tuple[set[int], str]:
    """Addresses a candidate map references — one variant, or the union of all."""
    variants, rows = load_multi_map(args.map)
    if args.variant:
        if args.variant not in variants:
            sys.exit(f"ERROR: variant {args.variant!r} not in {args.map}. "
                     f"Columns: {', '.join(variants)}")
        ents = entries_for_variant(rows, args.variant)
        return {a for e in ents for a in e.addresses}, args.variant
    addrs: set[int] = set()
    for row in rows:
        for cell in row["cells"].values():
            spec = parse_map_cell(cell)
            if spec:
                addrs.update(spec["addresses"])
    return addrs, "all variants"


def _collect_map_targeted(args) -> tuple[dict, list, list]:
    addrs, scope = _map_addresses(args)
    if not addrs:
        sys.exit("No addresses found in the map (check --map / --variant).")
    # The kellerza map is a holding-register map, so default to holding; honor an
    # explicit --table input/both if the user really wants the input space too.
    tables = ["holding"] if args.table == "both" else [args.table]
    vlog(f"map-targeted scan: {len(addrs)} addresses ({scope}) from "
         f"{os.path.basename(args.map)} on {tables}")
    reader: ModbusReader = MockReader() if args.mock else PymodbusReader(args)
    raw_by_table: dict[str, dict[int, int]] = {}
    unreadable: list[str] = []
    try:
        for table in tables:
            values, unread = read_targeted(reader, table, addrs, args.gap, args.mock,
                                           args.cluster_gap, args.block_size)
            raw_by_table[table] = values
            unreadable.extend(unread)
    finally:
        reader.close()
    return raw_by_table, unreadable, tables


def do_scan(args) -> str:
    if args.map:
        raw_by_table, unreadable, tables = _collect_map_targeted(args)
        mode = "mock" if args.mock else "active"
    elif args.passive:
        raw_by_table, unreadable, _ = passive_sniff(args)
        tables = list(raw_by_table.keys())
        mode = "passive"
    else:
        raw_by_table, unreadable, tables = _collect_active(args)
        mode = "mock" if args.mock else "active"

    # Build decoded snapshot.
    snap = Snapshot(
        tool_version=TOOL_VERSION,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        label=args.label,
        note=args.note,
        conditions=_parse_conditions(args.condition),
        vendor=args.vendor,
        model=args.model,
        firmware={"protocol": args.fw_protocol, "mcu": args.fw_mcu, "comm": args.fw_comm},
        connection={
            "mode": mode,
            "mock": args.mock,
            "port": None if args.mock else args.port,
            "baud": args.baud,
            "slave": args.slave,
            "range": None if (args.passive or args.map) else [args.start, args.end],
            "tables": tables,
            "map": os.path.basename(args.map) if args.map else None,
            "map_variant": args.variant if args.map else None,
        },
        unreadable=unreadable,
    )
    vlog(f"decoding {sum(len(v) for v in raw_by_table.values())} registers "
         f"(multi-way decode + plausibility hints)")
    hinted = 0
    for table, values in raw_by_table.items():
        for a in sorted(values):
            dec = decode_register(a, values)
            hint = plausibility_hint(dec)
            if hint:
                hinted += 1
                vlog(f"[{table}] {a}: {hint}")
            snap.registers[f"{table}:{a}"] = {
                "table": table,
                "address": a,
                **dec,
                "hint": hint,
            }
    vlog(f"{hinted} register(s) drew a plausibility hint")

    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in args.label)
    base = os.path.join(args.out, f"snapshot-{stamp}-{safe_label}")

    with open(base + ".json", "w") as f:
        json.dump(asdict(snap), f, indent=2)
    _write_csv(base + ".csv", snap)

    print(f"Scanned {sum(len(v) for v in raw_by_table.values())} registers "
          f"({', '.join(tables)}), {len(unreadable)} unreadable.")
    print(f"  {base}.json")
    print(f"  {base}.csv")
    print(f"Run more scans in different states, then: {sys.argv[0]} report --out {args.out}")
    return base + ".json"


def _parse_conditions(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _write_csv(path: str, snap: Snapshot) -> None:
    cols = ["table", "address", "hex", "raw", "uint16", "int16",
            "uint16_x0.1", "uint16_x0.01", "uint32_be", "int32_be",
            "uint32_le", "int32_le", "hint"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for entry in snap.registers.values():
            w.writerow([entry.get(c, "") for c in cols])


# --------------------------------------------------------------------------- #
# Report — consolidate snapshots into one LLM-ready Markdown file.
# --------------------------------------------------------------------------- #
def _build_map_index(entries: list) -> dict[int, list]:
    """address -> [MapEntry, ...] (bitfields/composites/collisions all kept)."""
    idx: dict[int, list] = {}
    for e in entries:
        for a in e.addresses:
            idx.setdefault(a, []).append(e)
    return idx


def _resolve_report_variant(args, snaps) -> str | None:
    """Pick the map column for report annotation: explicit --variant, else the
    variant the snapshot was scanned with, else the only column."""
    variants, _rows = load_multi_map(args.map)
    if args.variant:
        if args.variant not in variants:
            sys.exit(f"ERROR: variant {args.variant!r} not in {args.map}. "
                     f"Columns: {', '.join(variants)}")
        return args.variant
    if len(variants) == 1:
        return variants[0]
    snap_v = snaps[0].get("connection", {}).get("map_variant")
    if snap_v in variants:
        vlog(f"map: using variant {snap_v!r} recorded in the snapshot")
        return snap_v
    sys.exit("ERROR: --variant is required for a multi-column map. "
             f"Columns: {', '.join(variants)}")


def _map_names(addr: int, mapidx: dict | None) -> str:
    if not mapidx or addr not in mapidx:
        return ""
    return "; ".join(e.name for e in mapidx[addr])


def _map_annotation(key: str, mapidx: dict | None, rawfn, fallback: str) -> str:
    """Authoritative label for a register from the map (name [group] = decoded),
    falling back to the heuristic hint when the address isn't in the map."""
    table, a_str = key.split(":")
    a = int(a_str)
    if table != "holding" or not mapidx or a not in mapidx:
        return fallback
    parts = []
    for e in mapidx[a]:
        label = e.name + (f" [{e.group}]" if e.group else "")
        if len(e.addresses) > 1:
            label += f" (w{e.addresses.index(a) + 1}/{len(e.addresses)})"
        else:
            d = decode_map_entry(e, rawfn)
            if d["status"] == "ok":
                label += f" = {d['display']}"
        parts.append(label)
    return "; ".join(parts).replace("|", "\\|")


def do_report(args) -> str:
    paths = sorted(args.snapshots) if args.snapshots else sorted(
        glob.glob(os.path.join(args.out, "snapshot-*.json"))
    )
    if not paths:
        sys.exit(f"No snapshots found in {args.out} (run `scan` first).")

    vlog(f"consolidating {len(paths)} snapshot(s) from {args.out}")
    snaps = []
    for p in paths:
        s = json.load(open(p))
        vlog(f"loaded {os.path.basename(p)}: label='{s.get('label')}', "
             f"{len(s.get('registers', {}))} registers")
        snaps.append(s)
    meta = snaps[0]
    vendor = meta.get("vendor") or "unknown"
    model = meta.get("model") or "unknown"
    fw = meta.get("firmware", {})

    # Optional: annotate known registers from a candidate map.
    mapidx: dict[int, list] | None = None
    map_variant = map_name = None
    if args.map:
        map_variant = _resolve_report_variant(args, snaps)
        _variants, rows = load_multi_map(args.map)
        mapidx = _build_map_index(entries_for_variant(rows, map_variant))
        map_name = os.path.basename(args.map)
        vlog(f"map: indexed {len(mapidx)} addresses from {map_name} "
             f"(variant {map_variant})")

    # Union of addresses across snapshots.
    keys = set()
    for s in snaps:
        keys.update(s["registers"].keys())

    def addr_sort(k):
        t, a = k.split(":")
        return (t, int(a))

    keys = sorted(keys, key=addr_sort)

    # Which registers changed across the labelled states (the gold).
    changed = []
    for k in keys:
        vals = []
        for s in snaps:
            e = s["registers"].get(k)
            vals.append(e["raw"] if e else None)
        present = [v for v in vals if v is not None]
        if len(set(present)) > 1:
            changed.append((k, vals))
            vlog(f"changed across states: {k} raw={present}")

    out_md = os.path.join(args.out, "regscan-report.md")
    out_json = os.path.join(args.out, "regscan-report.json")
    labels = [s["label"] for s in snaps]

    with open(out_md, "w") as f:
        f.write(_report_markdown(vendor, model, fw, snaps, labels, keys, changed,
                                 mapidx, map_variant, map_name))
    json.dump(
        {"vendor": vendor, "model": model, "firmware": fw,
         "map": map_name, "map_variant": map_variant,
         "snapshots": [{"label": s["label"], "note": s.get("note"),
                        "conditions": s.get("conditions"),
                        "timestamp_utc": s["timestamp_utc"]} for s in snaps],
         "changed_registers": [{"reg": k, "map": _map_names(int(k.split(":")[1]), mapidx)}
                               if mapidx else k for k, _ in changed],
         "register_count": len(keys)},
        open(out_json, "w"), indent=2,
    )

    print(f"Consolidated {len(snaps)} snapshot(s), {len(keys)} registers, "
          f"{len(changed)} changed across states.")
    print(f"  {out_md}   <-- paste this to Claude")
    print(f"  {out_json}")
    return out_md


def _report_markdown(vendor, model, fw, snaps, labels, keys, changed,
                     mapidx=None, map_variant=None, map_name=None) -> str:
    lines: list[str] = []
    A = lines.append

    def rawfn(addr: int):
        key = f"holding:{addr}"
        for s in reversed(snaps):
            e = s["registers"].get(key)
            if e:
                return e["raw"]
        return None

    hint_col = "map (name · decoded)" if mapidx else "hint"

    A("# Register Discovery Report")
    A("")
    A("<!-- GENERATED BY tools/regscan.py — paste this whole file to Claude. -->")
    A("")
    A("## Instructions for Claude")
    A("")
    A("You are updating this repo's `plan.md` and creating a device profile from a "
      "read-only Modbus register scan. Using the data below:")
    A("")
    A(f"1. Propose register mappings for `profiles/{vendor.lower()}-{model.lower()}.yaml` "
      "(and the shared `deye-base` map where applicable). For each canonical metric "
      "in plan.md §4, pick the address + type + scale + signedness + word order whose "
      "decoded value matches the stated **conditions**, and whose **changes across "
      "states** move in the expected direction.")
    A("2. Use the **\"Registers that changed across states\"** table first — those are "
      "the live measurements (PV/load/battery/grid power, SoC). Static registers are "
      "likely settings, ratings, or status enums.")
    if mapidx:
        A(f"   - Registers are **annotated from the candidate map `{map_name}` "
          f"(variant `{map_variant}`)**: the final column gives the map's known "
          "name [group] and its decoded value. Treat these as the *expected* "
          "identity — **confirm the decoded value matches the stated conditions**, "
          "and call out any where it doesn't (the map may be wrong for this "
          "model/firmware). Multiple names on one address = a map collision to resolve.")
    A("3. Determine **sign conventions** (battery charge +/- , grid import/export) from "
      "the direction of change versus what was changed.")
    A("4. Flag anything ambiguous and say what additional labelled scan would "
      "disambiguate it (e.g. \"scan while exporting to grid\").")
    A("5. Report unmapped canonical metrics as still-needed.")
    A("")
    A("Do **not** invent addresses that aren't in the data. Tie the profile to the "
      "firmware below.")
    A("")
    A("## Device")
    A("")
    A(f"- **Vendor / model:** {vendor} / {model}")
    A(f"- **Firmware:** protocol `{fw.get('protocol')}`, MCU `{fw.get('mcu')}`, "
      f"COMM `{fw.get('comm')}`")
    conn = snaps[0].get("connection", {})
    src = "MOCK" if conn.get("mock") else conn.get("port")
    A(f"- **Capture mode:** {conn.get('mode', 'active')}"
      + (f" (sniffed from another master)" if conn.get("mode") == "passive" else ""))
    A(f"- **Scan range:** {conn.get('range')} on tables {conn.get('tables')} "
      f"(slave {conn.get('slave')}, {src})")
    if mapidx:
        A(f"- **Annotated with map:** `{map_name}` (variant `{map_variant}`) — "
          f"{len(mapidx)} known addresses")
    A("")
    A("## Snapshots (system states captured)")
    A("")
    A("| # | Label | Timestamp (UTC) | Conditions / note |")
    A("|---|-------|-----------------|-------------------|")
    for i, s in enumerate(snaps):
        cond = ", ".join(f"{k}={v}" for k, v in (s.get("conditions") or {}).items())
        note = s.get("note") or ""
        detail = " · ".join(x for x in (cond, note) if x)
        A(f"| {i} | `{s['label']}` | {s['timestamp_utc']} | {detail} |")
    A("")

    # Changed registers — the most informative table.
    A("## Registers that changed across states (map these first)")
    A("")
    if not changed:
        A("_No registers changed between snapshots. Capture scans in genuinely "
          "different states (e.g. high vs low PV, charging vs discharging)._")
    else:
        hdr = "| Reg | " + " | ".join(f"raw@{l}" for l in labels) + \
              f" | int16 (last) | candidate decodings (last) | {hint_col} |"
        A(hdr)
        A("|-----|" + "|".join("-----" for _ in labels) + "|-----|-----|-----|")
        for k, vals in changed:
            last_entry = None
            for s in reversed(snaps):
                if k in s["registers"]:
                    last_entry = s["registers"][k]
                    break
            raws = " | ".join("" if v is None else str(v) for v in vals)
            dec = _decode_brief(last_entry)
            note = _map_annotation(k, mapidx, rawfn, last_entry.get("hint", ""))
            A(f"| `{k}` | {raws} | {last_entry.get('int16','')} | {dec} | {note} |")
    A("")

    # Full dump (per snapshot raw is verbose; give last-state decodings).
    A("## Full register dump (latest snapshot)")
    A("")
    A("<details><summary>Expand — every readable register with decodings</summary>")
    A("")
    A(f"| Reg | hex | uint16 | int16 | u16·0.1 | u16·0.01 | uint32_be | {hint_col} |")
    A("|-----|-----|--------|-------|---------|----------|-----------|------|")
    latest = snaps[-1]["registers"]
    for k in keys:
        e = latest.get(k)
        if not e:
            continue
        note = _map_annotation(k, mapidx, rawfn, e.get("hint", ""))
        A(f"| `{k}` | {e.get('hex','')} | {e.get('uint16','')} | {e.get('int16','')} "
          f"| {e.get('uint16_x0.1','')} | {e.get('uint16_x0.01','')} "
          f"| {e.get('uint32_be','')} | {note} |")
    A("")
    A("</details>")
    A("")

    # Unreadable
    unread = snaps[-1].get("unreadable") or []
    if unread:
        A("## Unreadable addresses (latest snapshot)")
        A("")
        A(", ".join(f"`{u}`" for u in unread))
        A("")

    A("---")
    A(f"_Generated by regscan.py v{TOOL_VERSION}. Source data: "
      f"{len(snaps)} snapshot JSON file(s) in this directory._")
    A("")
    return "\n".join(lines)


def _decode_brief(entry: dict) -> str:
    if not entry:
        return ""
    parts = [f"u16={entry.get('uint16')}"]
    if entry.get("int16") != entry.get("uint16"):
        parts.append(f"s16={entry.get('int16')}")
    parts.append(f"·0.1={entry.get('uint16_x0.1')}")
    if "uint32_be" in entry:
        parts.append(f"u32be={entry.get('uint32_be')}")
    return ", ".join(str(p) for p in parts)


# --------------------------------------------------------------------------- #
# Verify — check a *candidate* register map (e.g. the kellerza/sunsynk
# definitions table) against real observed values. The community maps are a
# huge head-start but contain errors and address collisions, so this surfaces
# the map's decoded value per register next to the live raw, for you to tick
# off against the inverter's own screen before trusting it (see plan.md §11).
# --------------------------------------------------------------------------- #
@dataclass
class MapEntry:
    name: str
    group: str
    cell: str               # original map cell, e.g. "[190] S" or "[63,64] * 0.1"
    addresses: list[int]
    scale: float
    signed: bool
    mask: int | None
    offset: float = 0.0     # added after scaling, e.g. "[182] * 0.1 - 100" (temps)


def _trailing_zeros(mask: int) -> int:
    if mask == 0:
        return 0
    n = 0
    while not (mask >> n) & 1:
        n += 1
    return n


def parse_map_cell(cell: str) -> dict | None:
    """Parse a sunsynk-style cell into a spec.

    Understands: `[184]`, `[183] * 0.01`, `[169] * 10`, `[190] S` (signed),
    `[232] & 0x01` (bitmask, shifted to LSB), `[63,64] * 0.1` (multi-register),
    and a trailing additive **offset** `[182] * 0.1 - 100` (Sunsynk temperatures
    are stored as (°C + 100) × 10), also `/` for division.
    Returns None for blanks / `const` / anything without an address list.
    """
    cell = (cell or "").strip()
    if not cell or cell.lower() == "const":
        return None
    m = re.search(r"\[([0-9,\s]+)\]", cell)
    if not m:
        return None
    addrs = [int(x) for x in m.group(1).split(",") if x.strip()]
    if not addrs:
        return None
    signed = bool(re.search(r"(?<![\w])S(?![\w])", cell))  # standalone 'S'
    scale = 1.0
    ms = re.search(r"\*\s*([0-9]*\.?[0-9]+)", cell)
    if ms:
        scale = float(ms.group(1))
    md = re.search(r"/\s*([0-9]*\.?[0-9]+)", cell)
    if md:
        scale /= float(md.group(1))
    mask = None
    mm = re.search(r"&\s*(0x[0-9a-fA-F]+|\d+)", cell)
    if mm:
        mask = int(mm.group(1), 0)
    # trailing "+N" / "-N" (not part of a * or / term) -> additive offset
    offset = 0.0
    mo = re.search(r"(?<![*/])\s*([+-])\s*([0-9]*\.?[0-9]+)\s*$", cell)
    if mo:
        offset = float(mo.group(1) + mo.group(2))
    return {"addresses": addrs, "scale": scale, "signed": signed,
            "mask": mask, "offset": offset}


def load_multi_map(path: str) -> tuple[list[str], list[dict]]:
    """Load a candidate map, keeping *every* variant column. Two formats:
      * JSON: a flat {name: cell} object (or {"entries": {...}}) -> one column.
      * TSV/CSV: header with a `name` column, one column per variant
        (e.g. 1PH / 1PH-16kw / 3PH / 3PH-hv) and an optional `group` column.
    Returns (variants, rows) where each row is {name, group, cells: {variant: cell}}.
    """
    if path.endswith(".json"):
        data = json.load(open(path))
        items = data.get("entries", data) if isinstance(data, dict) else {}
        rows = [{"name": str(n), "group": "", "cells": {"map": str(c)}}
                for n, c in items.items()]
        return ["map"], rows

    with open(path, newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        # Cells contain commas ([3,4,5,6,7], [63,64]) which fool the sniffer,
        # so prefer tab whenever the file actually has tabs.
        if "\t" in sample:
            dialect = csv.excel_tab
        else:
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            except csv.Error:
                dialect = csv.excel
        reader = csv.reader(f, dialect)
        header = next(reader, None)
        if not header:
            sys.exit(f"ERROR: empty map file {path}")
        cols = [h.strip() for h in header]
        lower = [c.lower() for c in cols]
        name_idx = lower.index("name") if "name" in lower else 0
        group_idx = lower.index("group") if "group" in lower else None
        variants = [c for i, c in enumerate(cols)
                    if i not in (name_idx, group_idx) and c]
        rows = []
        for row in reader:
            if len(row) <= name_idx or not row[name_idx].strip():
                continue
            name = row[name_idx].strip()
            group = (row[group_idx].strip()
                     if group_idx is not None and len(row) > group_idx else "")
            cells = {v: (row[cols.index(v)].strip() if len(row) > cols.index(v) else "")
                     for v in variants}
            rows.append({"name": name, "group": group, "cells": cells})
        return variants, rows


def entries_for_variant(rows: list[dict], variant: str) -> list[MapEntry]:
    """Build MapEntry list for one variant column, skipping blank/const cells."""
    entries: list[MapEntry] = []
    skipped = 0
    for row in rows:
        cell = row["cells"].get(variant, "")
        spec = parse_map_cell(cell)
        if spec is None:
            skipped += 1
            continue
        entries.append(MapEntry(name=row["name"], group=row["group"], cell=cell, **spec))
    vlog(f"map[{variant}]: {len(entries)} usable entries"
         + (f" ({skipped} blank/const for this variant)" if skipped else ""))
    return entries


def _raw_lookup_from_snapshot(snap: dict, table_pref: str):
    """Build a raw(addr) lookup from a saved snapshot, preferring `table_pref`."""
    by_table: dict[str, dict[int, int]] = {}
    for entry in snap.get("registers", {}).values():
        by_table.setdefault(entry["table"], {})[int(entry["address"])] = entry["raw"]
    order = [table_pref] + [t for t in ("holding", "input") if t != table_pref]

    def raw(addr: int):
        for t in order:
            if addr in by_table.get(t, {}):
                return by_table[t][addr]
        return None

    return raw, by_table


def _raw_lookup_from_reader(reader: ModbusReader, table: str, addrs: set[int],
                            gap: float, mock: bool, cluster_gap: int = 8):
    """Targeted read of just the map's addresses (clustered) -> raw(addr) lookup."""
    if not addrs:
        return (lambda a: None), {}
    values, _ = read_targeted(reader, table, addrs, gap, mock, cluster_gap)
    return (lambda addr: values.get(addr)), {table: values}


def _resolve_source(args, needed: set[int]):
    """Get observed values from a snapshot, a live read, or the mock device.

    Returns (raw, status_of, src) where status_of(addr) is one of:
      'ok'         — register was read,
      'unreadable' — attempted but the device rejected it (strong wrong-variant
                     / wrong-address signal),
      'absent'     — outside what was scanned (no information).
    """
    if args.from_snapshot:
        snap = json.load(open(args.from_snapshot))
        vlog(f"verifying against snapshot {os.path.basename(args.from_snapshot)} "
             f"(label '{snap.get('label')}')")
        raw, by_table = _raw_lookup_from_snapshot(snap, args.table)
        present: set[int] = set()
        for t in by_table.values():
            present.update(t)
        unread: set[int] = set()
        for u in snap.get("unreadable", []):
            try:
                unread.add(int(str(u).split(":")[-1]))
            except ValueError:
                pass

        def status_of(a: int) -> str:
            if a in present:
                return "ok"
            if a in unread:
                return "unreadable"
            return "absent"

        return raw, status_of, f"snapshot {os.path.basename(args.from_snapshot)}"

    reader: ModbusReader = MockReader() if args.mock else PymodbusReader(args)
    try:
        raw, tv = _raw_lookup_from_reader(reader, args.table, needed, args.gap, args.mock)
    finally:
        reader.close()
    values = tv.get(args.table, {})
    lo = min(needed) if needed else 0
    hi = max(needed) if needed else -1

    def status_of(a: int) -> str:
        if a in values:
            return "ok"
        return "unreadable" if lo <= a <= hi else "absent"

    return raw, status_of, ("mock device" if args.mock else f"live {args.port}")


def _entry_status(addresses: list[int], status_of) -> str:
    sts = {status_of(a) for a in addresses}
    if sts == {"ok"}:
        return "ok"
    if "unreadable" in sts:
        return "unreadable"
    if "ok" in sts:
        return "partial"
    return "absent"


def decode_map_entry(entry: MapEntry, raw) -> dict:
    """Decode an entry's register(s) the way the map says, for eyeballing."""
    vals = [raw(a) for a in entry.addresses]
    if all(v is None for v in vals):
        return {"status": "not-scanned", "display": "(not in scan range)"}

    if len(entry.addresses) == 1:
        r = vals[0]
        if r is None:
            return {"status": "not-scanned", "display": "(not scanned)"}
        if entry.mask is not None:
            base = (u16(r) & entry.mask) >> _trailing_zeros(entry.mask)
            value = round(base * entry.scale, 4)   # bitfields take no offset
        else:
            base = s16(r) if entry.signed else u16(r)
            value = round(base * entry.scale + entry.offset, 4)
        return {"status": "ok", "raw": r, "value": value, "display": str(value)}

    # Multi-register: the map can't tell us "32-bit pair" from "separate phases",
    # so show each register AND the 2-word combo, and let the human decide.
    per = [f"r{a}=" + ("?" if v is None else str(s16(v) if entry.signed else u16(v)))
           for a, v in zip(entry.addresses, vals)]
    combo = ""
    if len(entry.addresses) == 2 and all(v is not None for v in vals):
        lo, hi = vals  # convention: [low_word, high_word]
        c = s32(hi, lo) if entry.signed else u32(hi, lo)
        combo = f"  |  u32[lo,hi]={round(c * entry.scale + entry.offset, 4)}"
    return {"status": "ok", "raw": vals, "display": "; ".join(per) + combo}


def _find_collisions(entries: list[MapEntry]) -> dict[int, list[str]]:
    """The map's own *contradictions* — same register, conflicting meanings.
    Two single-register entries conflict only if their bit-masks overlap: a
    full-register read vs a bitfield is just a sub-view, and composite/derived
    sensors ([175,169,166]) reuse registers legitimately, so both are excluded.
    """
    full = 0xFFFF
    addr_claims: dict[int, list[tuple[str, int]]] = {}
    for e in entries:
        if len(e.addresses) > 1:
            continue
        mask = e.mask if e.mask is not None else full
        for a in e.addresses:
            addr_claims.setdefault(a, []).append((e.name, mask))
    collisions: dict[int, list[str]] = {}
    for a, claims in addr_claims.items():
        conflicting: list[str] = []
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                mi, mj = claims[i][1], claims[j][1]
                if (mi == full) ^ (mj == full):
                    continue
                if mi & mj:
                    for n in (claims[i][0], claims[j][0]):
                        if n not in conflicting:
                            conflicting.append(n)
        if conflicting:
            collisions[a] = conflicting
    return collisions


def do_verify(args) -> str:
    variants, rows = load_multi_map(args.map)
    if not rows:
        sys.exit("No usable entries in the candidate map.")
    # Effective variant: explicit --variant, or the only column, else all-variants.
    if args.variant:
        if args.variant not in variants:
            sys.exit(f"ERROR: variant {args.variant!r} not in map. "
                     f"Columns: {', '.join(variants)}")
        return _verify_single(args, rows, args.variant)
    if len(variants) == 1:
        return _verify_single(args, rows, variants[0])
    return _verify_all_variants(args, variants, rows)


def _verify_single(args, rows: list[dict], variant: str) -> str:
    """Decode one variant column against observed values + flag map collisions."""
    entries = entries_for_variant(rows, variant)
    if not entries:
        sys.exit(f"No usable entries for variant {variant!r}.")
    collisions = _find_collisions(entries)
    needed = {a for e in entries for a in e.addresses}
    raw, _status, src = _resolve_source(args, needed)

    out_rows = []
    n_ok = n_missing = 0
    for e in sorted(entries, key=lambda x: (x.addresses[0], x.name)):
        dec = decode_map_entry(e, raw)
        n_ok += dec["status"] == "ok"
        n_missing += dec["status"] != "ok"
        out_rows.append((e, dec))

    print(f"Verifying {len(entries)} map entries ({variant}) against {src}:")
    print(f"  {'name':32} {'cell':18} {'decoded (per map)':40} group")
    print("  " + "-" * 100)
    for e, dec in out_rows:
        is_coll = len(e.addresses) == 1 and e.name in collisions.get(e.addresses[0], [])
        flag = " ⚠collision" if is_coll else ""
        print(f"  {e.name[:32]:32} {e.cell[:18]:18} "
              f"{dec['display'][:40]:40} {e.group}{flag}")

    if collisions:
        print(f"\n  ⚠ {len(collisions)} address collision(s) in the map itself "
              f"(same register, different meanings — verify these against the screen):")
        for a in sorted(collisions):
            print(f"     [{a}] -> {', '.join(collisions[a])}")
    print(f"\n{n_ok} decoded, {n_missing} not in scan range.")

    os.makedirs(args.out, exist_ok=True)
    out_md = os.path.join(args.out, "verify-report.md")
    with open(out_md, "w") as f:
        f.write(_verify_markdown(args, variant, src, out_rows, collisions, n_ok, n_missing))
    print(f"  {out_md}")
    return out_md


def _matrix_cell(status: str, display: str) -> str:
    """Short cell for the comparison matrix."""
    return {"ok": display,
            "partial": f"{display} ?",
            "unreadable": "ERR",
            "absent": "·",
            "none": ""}.get(status, "")


def _verify_all_variants(args, variants: list[str], rows: list[dict]) -> str:
    """Scan once, decode EVERY variant column, and lay them side by side so the
    column whose values are sane reveals the inverter type and each row can be
    validated against the screen (see plan.md §11)."""
    # Union of every address any variant needs, so one scan covers them all.
    needed: set[int] = set()
    for row in rows:
        for cell in row["cells"].values():
            spec = parse_map_cell(cell)
            if spec:
                needed.update(spec["addresses"])
    raw, status_of, src = _resolve_source(args, needed)

    # Decode each (row, variant): value + status.
    matrix: list[dict] = []
    for row in rows:
        cells = {}
        any_def = False
        for v in variants:
            spec = parse_map_cell(row["cells"].get(v, ""))
            if spec is None:
                cells[v] = {"status": "none", "disp": ""}
                continue
            any_def = True
            e = MapEntry(row["name"], row["group"], row["cells"][v], **spec)
            dec = decode_map_entry(e, raw)
            st = _entry_status(e.addresses, status_of)
            cells[v] = {"status": st, "disp": dec["display"]}
        if any_def:
            matrix.append({"name": row["name"], "group": row["group"], "cells": cells})

    # Per-variant coverage — the inverter-type discriminator. 'unreadable' means
    # the device rejected that variant's address (a wrong-variant tell); 'absent'
    # is just outside the scan (no info), so the score ignores it.
    summary = {}
    for v in variants:
        ok = unread = absent = 0
        for m in matrix:
            st = m["cells"][v]["status"]
            ok += st == "ok"
            unread += st == "unreadable"
            absent += st in ("absent", "partial")
        attempted = ok + unread
        summary[v] = {"ok": ok, "unreadable": unread, "absent": absent,
                      "score": (ok / attempted) if attempted else 0.0,
                      "attempted": attempted}
    # The discriminator is the *rejection rate*, not how many sensors a variant
    # happens to define — the right variant reads its own registers (few
    # rejections); wrong ones hit out-of-range addresses and error out. Rank by
    # match score, but require a meaningful number of attempts so a sparse
    # all-readable column can't win on a technicality.
    floor = max(20, int(0.25 * max((summary[v]["attempted"] for v in variants), default=0)))
    eligible = [v for v in variants if summary[v]["attempted"] >= floor] or variants
    best = max(eligible, key=lambda v: (summary[v]["score"], summary[v]["ok"]))

    print(f"All-variants comparison against {src} "
          f"({len(matrix)} sensors, {len(needed)} registers):\n")
    print(f"  {'variant':12} {'readable':>9} {'rejected':>9} {'not-scanned':>12} {'match':>7}")
    print("  " + "-" * 54)
    for v in variants:
        s = summary[v]
        mark = "  <= likely" if v == best and s["attempted"] else ""
        print(f"  {v:12} {s['ok']:>9} {s['unreadable']:>9} {s['absent']:>12} "
              f"{s['score']*100:>6.0f}%{mark}")
    any_rejected = any(summary[v]["unreadable"] for v in variants)
    if not any_rejected:
        print("\n  Note: no addresses were rejected — to tell variants apart, scan the "
              "full union range (e.g. --start 0 --end 708) so wrong-variant addresses "
              "get probed and error out.")
    print(f"\n  Likely inverter type: {best} "
          f"({summary[best]['ok']} readable, {summary[best]['unreadable']} rejected). "
          "Confirm by checking its column against the inverter screen.")

    os.makedirs(args.out, exist_ok=True)
    out_csv = os.path.join(args.out, "verify-matrix.csv")
    out_md = os.path.join(args.out, "verify-matrix.md")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "group"] + variants)
        for m in matrix:
            w.writerow([m["name"], m["group"]]
                       + [_matrix_cell(m["cells"][v]["status"], m["cells"][v]["disp"])
                          for v in variants])
    with open(out_md, "w") as f:
        f.write(_matrix_markdown(args, src, variants, summary, best, matrix))
    print(f"\n  {out_csv}   <- open as a spreadsheet; the sane column is your variant")
    print(f"  {out_md}")
    return out_csv


def _matrix_markdown(args, src, variants, summary, best, matrix) -> str:
    L: list[str] = []
    A = L.append
    A("# Candidate-map all-variants comparison")
    A("")
    A(f"- **Map:** `{args.map}`")
    A(f"- **Observed from:** {src}")
    A(f"- **Likely inverter type:** **{best}** "
      f"({summary[best]['ok']} readable, {summary[best]['unreadable']} rejected)")
    A("")
    A("| Variant | Readable | Rejected | Not scanned | Match |")
    A("|---------|---------:|---------:|------------:|------:|")
    for v in variants:
        s = summary[v]
        A(f"| {'**' + v + '**' if v == best else v} | {s['ok']} | "
          f"{s['unreadable']} | {s['absent']} | {s['score']*100:.0f}% |")
    A("")
    A("`ERR` = device rejected that variant's address (wrong-variant tell); "
      "`·` = outside the scan range. The column with the most readable, sane "
      "values is your inverter; check it against the screen.")
    A("")
    A("| Name | Group | " + " | ".join(variants) + " |")
    A("|------|-------|" + "|".join("------" for _ in variants) + "|")
    for m in matrix:
        cells = [_matrix_cell(m["cells"][v]["status"], m["cells"][v]["disp"]).replace("|", "\\|")
                 for v in variants]
        A(f"| {m['name']} | {m['group']} | " + " | ".join(cells) + " |")
    A("")
    return "\n".join(L)


def _verify_markdown(args, variant, src, rows, collisions, n_ok, n_missing) -> str:
    L: list[str] = []
    A = L.append
    A(f"# Candidate-map verification — {variant}")
    A("")
    A(f"- **Map:** `{args.map}`")
    A(f"- **Observed from:** {src}")
    A(f"- **Result:** {n_ok} decoded, {n_missing} not in scan range, "
      f"{len(collisions)} address collision(s) in the map.")
    A("")
    A("Compare each **decoded (per map)** value to the inverter's own screen for "
      "the captured state. A match confirms the address + scale + sign; a mismatch "
      "means the map entry is wrong for this model/firmware.")
    A("")
    A("| Reg | Name | Cell | Decoded (per map) | Group | Note |")
    A("|-----|------|------|-------------------|-------|------|")
    for e, dec in rows:
        is_collision = len(e.addresses) == 1 and e.name in collisions.get(e.addresses[0], [])
        note = "⚠ collision" if is_collision else (
            "" if dec["status"] == "ok" else "not scanned")
        addr = ",".join(str(a) for a in e.addresses)
        disp = dec["display"].replace("|", "\\|")  # don't break the MD table
        A(f"| `{addr}` | {e.name} | `{e.cell}` | {disp} | {e.group} | {note} |")
    A("")
    if collisions:
        A("## Map self-collisions (same address, multiple meanings)")
        A("")
        for a in sorted(collisions):
            A(f"- `[{a}]` → {', '.join(collisions[a])}")
        A("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="regscan.py",
        description="Read-only Modbus register-discovery tool (SolarVolt, plan.md §11).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--version", action="version", version=f"regscan.py {TOOL_VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="take one read-only snapshot of the register space")
    # connection
    s.add_argument("--port", help="serial device, e.g. /dev/ttyUSB0")
    s.add_argument("--baud", type=int, default=9600)
    s.add_argument("--slave", type=int, default=1, help="Modbus slave/unit id")
    s.add_argument("--parity", default="N", choices=["N", "E", "O"])
    s.add_argument("--stopbits", type=int, default=1)
    s.add_argument("--bytesize", type=int, default=8)
    s.add_argument("--timeout", type=float, default=1.0)
    s.add_argument("--mock", action="store_true", help="synthetic device, no hardware")
    s.add_argument("--passive", action="store_true",
                   help="don't be a master — sniff another master's RS485 traffic "
                        "(opens the port non-exclusively; use when it's already in use)")
    s.add_argument("--duration", type=float, default=60.0,
                   help="passive: seconds to sniff (default 60)")
    # range — sweep a contiguous range, OR target only a map's registers
    s.add_argument("--start", type=int, default=0)
    s.add_argument("--end", type=int, default=512, help="last register address (inclusive)")
    s.add_argument("--map",
                   help="targeted scan: read ONLY the registers a candidate map "
                        "(TSV/JSON) references, clustered into a few reads, instead "
                        "of sweeping --start..--end")
    s.add_argument("--variant",
                   help="with --map: restrict to one variant column's registers "
                        "(default: the union of all variants)")
    s.add_argument("--cluster-gap", type=int, default=8,
                   help="with --map: merge addresses within this gap into one read "
                        "(default 8; bigger = fewer reads but more filler registers)")
    s.add_argument("--table", default="both", choices=["holding", "input", "both"])
    s.add_argument("--block-size", type=int, default=32, help="registers per read")
    s.add_argument("--gap", type=float, default=0.02, help="seconds between reads")
    s.add_argument("--retries", type=int, default=2)
    s.add_argument("--backoff", type=float, default=0.2)
    # labelling / provenance
    s.add_argument("--label", required=True, help="short state label, e.g. midday-full-sun")
    s.add_argument("--note", default="", help="free-text description of conditions")
    s.add_argument("--condition", action="append", default=[],
                   help="key=value reading off the inverter screen, repeatable "
                        "(e.g. --condition soc_pct=78 --condition pv_w=6100)")
    s.add_argument("--vendor", default="")
    s.add_argument("--model", default="")
    s.add_argument("--fw-protocol", default="")
    s.add_argument("--fw-mcu", default="")
    s.add_argument("--fw-comm", default="")
    s.add_argument("--out", default=DEFAULT_OUT)
    s.add_argument("-v", "--verbose", action="store_true",
                   help="trace each step (port, every block/frame, decode) to stderr")
    s.set_defaults(func=do_scan)

    r = sub.add_parser("report", help="consolidate snapshots into Markdown for Claude")
    r.add_argument("snapshots", nargs="*", help="snapshot JSON files (default: all in --out)")
    r.add_argument("--map",
                   help="annotate known registers with a candidate map (TSV/JSON): "
                        "label each address with the map's name/group and decoded value "
                        "instead of just the heuristic hint")
    r.add_argument("--variant",
                   help="with --map: which column to use (default: the variant the "
                        "snapshot was scanned with, or the only column)")
    r.add_argument("--out", default=DEFAULT_OUT)
    r.add_argument("-v", "--verbose", action="store_true",
                   help="trace each loaded snapshot and changed register to stderr")
    r.set_defaults(func=do_report)

    v = sub.add_parser("verify",
                       help="check a candidate register map (e.g. kellerza/sunsynk) "
                            "against observed values")
    v.add_argument("--map", required=True,
                   help="candidate map: TSV/CSV (paste the sunsynk table; pick --variant) "
                        "or JSON {name: cell}")
    v.add_argument("--variant",
                   help="which column to check, e.g. 1PH / 1PH-16kw / 3PH / 3PH-hv. "
                        "OMIT to compare ALL variants side by side and detect the "
                        "inverter type (writes verify-matrix.csv).")
    v.add_argument("--table", default="holding", choices=["holding", "input"],
                   help="register table the map's addresses live in (Sunsynk uses holding)")
    # value source: a prior snapshot, or a fresh mock/live read of just what's needed
    v.add_argument("--from", dest="from_snapshot", metavar="SNAPSHOT.json",
                   help="verify against an existing snapshot from `scan` (recommended)")
    v.add_argument("--mock", action="store_true", help="synthetic values, no hardware")
    v.add_argument("--port", help="live read instead: serial device, e.g. /dev/ttyUSB0")
    v.add_argument("--baud", type=int, default=9600)
    v.add_argument("--slave", type=int, default=1)
    v.add_argument("--parity", default="N", choices=["N", "E", "O"])
    v.add_argument("--stopbits", type=int, default=1)
    v.add_argument("--bytesize", type=int, default=8)
    v.add_argument("--timeout", type=float, default=1.0)
    v.add_argument("--retries", type=int, default=2)
    v.add_argument("--backoff", type=float, default=0.2)
    v.add_argument("--gap", type=float, default=0.02)
    v.add_argument("--out", default=DEFAULT_OUT)
    v.add_argument("-v", "--verbose", action="store_true",
                   help="trace map parsing and the verification read to stderr")
    v.set_defaults(func=do_verify)
    return p


def main(argv=None):
    global _VERBOSE
    args = build_parser().parse_args(argv)
    _VERBOSE = getattr(args, "verbose", False)
    if args.cmd == "scan" and not args.mock and not args.port:
        sys.exit("ERROR: --port is required for a real scan (or use --mock).")
    if args.cmd == "verify" and not (args.from_snapshot or args.mock or args.port):
        sys.exit("ERROR: verify needs a value source: --from SNAPSHOT.json, "
                 "--mock, or --port.")
    args.func(args)


if __name__ == "__main__":
    main()
