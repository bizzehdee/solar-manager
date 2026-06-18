"""Profiles as data, not code (plan.md §4).

Loads a `profiles/<vendor>-<model>.yaml` register map into a `DeviceProfile`,
resolving `extends:` inheritance (e.g. sunsynk-8k-sg05lp1 extends deye-base — one
map maintained once covers the Sunsynk / Sol-Ark / Deye rebadge family). Decodes a
raw register map -> canonical metrics, honouring type / scale / offset / word order /
bitmask / multi-register, per the conventions documented in the YAML headers.

Decode is the #1 bug source (plan.md §10), so it is the most heavily unit-tested code
(test_yaml_profile.py), with vectors taken from the validated SG05LP1 scan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from ..models import DeviceInfo, MetricValue
from ..settings_schema import FieldSpec, Section, SettingsSchema, enum_options, humanize, unit_for
from .base import RegBlock

# Friendlier labels for the known settings sections (falls back to humanize()).
# Friendly labels for the inverter's own menu groups (falls back to humanize()).
_SECTION_LABELS = {
    "grid": "Grid",
    "battery_type": "Battery type",
    "battery_charging": "Battery charging",
    "work_mode": "Work mode",
    "work_mode_detail": "Work mode detail",
    "aux_gen": "Aux / Generator",
    "timer_slots": "Work-mode timer",
    # legacy keys (older profiles)
    "globals": "Work mode & limits",
    "battery": "Battery",
}

# Where the checked-in profile YAMLs live (repo-root/profiles).
PROFILES_DIR = Path(__file__).resolve().parents[3] / "profiles"

_MAX_BLOCK = 64  # registers per read transaction when clustering (Phase 1 transport)


def _signed(value: int, bits: int) -> int:
    if value >= 1 << (bits - 1):
        value -= 1 << bits
    return value


def _norm_fw(value: Any) -> str:
    """Normalize a firmware token for comparison: strip, lowercase, and drop a trailing
    `.0` so an int register (21) and a string pin ("21") compare equal."""
    s = str(value).strip().lower()
    if s.endswith(".0"):
        s = s[:-2]
    return s


class ModbusYamlProfile:
    """A register-map profile backed by YAML."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec
        self.vendor: str = spec.get("vendor", "unknown")
        self._word_order: str = spec.get("word_order", "low_first")
        self._table: str = spec.get("register_table", "holding")
        self._metrics: dict[str, dict[str, Any]] = spec.get("metrics", {})
        self._identity: dict[str, dict[str, Any]] = spec.get("info", {})

    # --- loading + inheritance --------------------------------------------------
    @classmethod
    def from_file(cls, path: str | Path) -> "ModbusYamlProfile":
        path = Path(path)
        spec = cls._load_with_inheritance(path)
        return cls(spec)

    @classmethod
    def from_name(cls, name: str) -> "ModbusYamlProfile":
        """Load by bare profile name from the standard profiles dir (no extension)."""
        return cls.from_file(PROFILES_DIR / f"{name}.yaml")

    @staticmethod
    def _load_with_inheritance(path: Path) -> dict[str, Any]:
        spec = yaml.safe_load(path.read_text()) or {}
        parent_name = spec.get("extends")
        if not parent_name:
            return spec
        parent = ModbusYamlProfile._load_with_inheritance(path.with_name(f"{parent_name}.yaml"))
        return ModbusYamlProfile._merge(parent, spec)

    @staticmethod
    def _merge(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
        """Child overrides parent. `metrics`/`settings` merge per-key; `overrides` under
        `metrics` is applied on top so a child can tweak one field of an inherited metric."""
        merged: dict[str, Any] = dict(parent)
        for key, value in child.items():
            if key == "overrides":
                continue
            if key in ("metrics", "settings", "info", "ratings") and isinstance(value, dict):
                base = dict(parent.get(key, {}))
                base.update(value)
                merged[key] = base
            else:
                merged[key] = value
        # `overrides:` lets a child patch individual inherited metrics.
        for mkey, patch in (child.get("overrides") or {}).items():
            base_metric = dict(merged.get("metrics", {}).get(mkey, {}))
            base_metric.update(patch)
            merged.setdefault("metrics", {})[mkey] = base_metric
        return merged

    # --- DeviceProfile protocol -------------------------------------------------
    def capabilities(self) -> set[str]:
        caps = set(self._metrics.keys())
        # `pv_power_w` (sum of MPPTs, plan.md §4) is derived, not a raw register —
        # advertise it whenever the per-MPPT powers are present.
        if any(k.startswith("pv") and k.endswith("_power_w") and k != "pv_power_w" for k in caps):
            caps.add("pv_power_w")
        return caps

    @property
    def settings(self) -> dict[str, Any]:
        """The writable-settings map (globals / timer_slots / battery, plan.md §4/§12).
        Consumed by the Phase 5 SettingsSchema; exposed here so it's inspectable/testable."""
        return self._spec.get("settings", {})

    # --- settings schema + read (plan.md §4/§12; task T070) ---------------------
    def settings_schema(self) -> SettingsSchema | None:
        """Build a render-ready SettingsSchema from the YAML `settings:` map, or None when
        the profile declares no settings (read-only-monitoring device)."""
        spec = self.settings
        if not spec:
            return None
        sections: list[Section] = []
        for skey, sval in spec.items():
            label = _SECTION_LABELS.get(skey, humanize(skey))
            if skey == "timer_slots":
                fields = [self._field_spec(k, v) for k, v in sval.get("fields", {}).items()]
                sections.append(Section(skey, label, fields, repeating=True, count=int(sval.get("count", 0))))
            else:
                fields = [self._field_spec(k, v) for k, v in sval.items()]
                sections.append(Section(skey, label, fields))
        return SettingsSchema(sections)

    @staticmethod
    def _field_spec(key: str, spec: dict[str, Any]) -> FieldSpec:
        t = spec.get("type", "u16")
        w = bool(spec.get("writable", True))   # `writable: false` ⇒ display-only (no write)
        if t == "bool":
            return FieldSpec(key, humanize(key), "bool", writable=w)
        if t == "enum":
            return FieldSpec(key, humanize(key), "enum", options=enum_options(spec.get("values", {})), writable=w)
        if t == "time_hhmm":
            return FieldSpec(key, humanize(key), "time", writable=w)
        lo, hi = ModbusYamlProfile._field_bounds(key, spec)
        if t == "bits":
            return FieldSpec(key, humanize(key), "int", min=lo, max=hi, writable=w)
        return FieldSpec(key, humanize(key), "number", unit=unit_for(key), min=lo, max=hi, writable=w)

    @staticmethod
    def _field_bounds(key: str, spec: dict[str, Any]) -> tuple[float | None, float | None]:
        """Write bounds for a numeric field: explicit YAML `min`/`max` win; otherwise a
        percentage (…_pct) defaults to 0–100. Everything else is unbounded here and only
        clamped to the register's u16/s16 range by the encoder (write-safety, §12)."""
        lo = spec.get("min")
        hi = spec.get("max")
        if lo is None and hi is None and key.endswith("_pct"):
            return 0.0, 100.0
        return lo, hi

    def settings_blocks(self) -> list[RegBlock]:
        """Register blocks covering every settings address (for the transport read)."""
        return self._blocks_for(self._settings_addresses())

    def _settings_addresses(self, *, writable_only: bool = False) -> set[int]:
        """All settings addresses (for the read), or only writable ones (the write allow-list).
        A field with `writable: false` is read+displayed but never in the allow-list (§12)."""
        addrs: set[int] = set()
        for skey, sval in self.settings.items():
            if skey == "timer_slots":
                count = int(sval.get("count", 0))
                for spec in sval.get("fields", {}).values():
                    if writable_only and not spec.get("writable", True):
                        continue
                    addrs.update(spec["base_addr"] + i for i in range(count))
            else:
                for spec in sval.values():
                    if writable_only and not spec.get("writable", True):
                        continue
                    if spec.get("addr") is not None:
                        addrs.add(int(spec["addr"]))
        return addrs

    def read_settings(self, raw: Mapping[int, int]) -> dict:
        """Decode the current settings values from a raw register map into a structured
        dict: {section_key: {field: value}} (or a list of `count` rows for timer_slots)."""
        out: dict = {}
        for skey, sval in self.settings.items():
            if skey == "timer_slots":
                count = int(sval.get("count", 0))
                fields = sval.get("fields", {})
                out[skey] = [
                    {k: self._decode_setting(spec, raw, spec["base_addr"] + i) for k, spec in fields.items()}
                    for i in range(count)
                ]
            else:
                out[skey] = {k: self._decode_setting(spec, raw, spec.get("addr")) for k, spec in sval.items()}
        return out

    def _decode_setting(self, spec: dict[str, Any], raw: Mapping[int, int], addr) -> Any:
        if addr is None or addr not in raw:
            return None
        v = raw[addr] & 0xFFFF
        t = spec.get("type", "u16")
        if t == "bool":
            return bool(v & spec.get("mask", 0xFFFF))
        if t == "enum":
            return v  # the machine value; UI maps to a label via the schema's options
        if t == "time_hhmm":
            return f"{v // 100:02d}:{v % 100:02d}"
        if t == "bits":
            mask = spec.get("mask", 0xFFFF)
            shift = (mask & -mask).bit_length() - 1
            return (v & mask) >> shift
        if t == "s16":
            v = _signed(v, 16)
        return round(v * spec.get("scale", 1) + spec.get("offset", 0), 3)

    # --- settings encode + write allow-list (plan.md §12; tasks T073/T074) -------
    def writable_addresses(self) -> set[int]:
        """The ONLY holding registers the API may write — the settings-map addresses minus
        any `writable: false` (read-only) fields (§12 allow-list). No arbitrary-address
        writes, ever. A subset of what `settings_blocks()` reads, so writes are re-readable."""
        return self._settings_addresses(writable_only=True)

    def encode_settings(
        self, section_key: str, values: Mapping[str, Any], current_raw: Mapping[int, int], *, index: int | None = None
    ) -> dict[int, int]:
        """Encode typed settings → `{addr: register_value}` for one section (slot `index`
        for the repeating timer). Bool/bits fields are read-modify-write against
        `current_raw` so co-located bits in one register compose without clobbering each
        other; numeric values are bounds-checked to the register's u16/s16 range.

        Assumes `values` already passed schema validation (control.validate_settings) — this
        is the register-level encode + the hard u16/s16 range guard."""
        sset = self.settings.get(section_key)
        if sset is None:
            raise KeyError(f"unknown settings section {section_key!r}")
        if section_key == "timer_slots":
            fields = sset.get("fields", {})
            slot = index or 0
            addr_of = lambda spec: spec["base_addr"] + slot
        else:
            fields = sset
            addr_of = lambda spec: spec.get("addr")

        writes: dict[int, int] = {}
        for key, val in values.items():
            spec = fields[key]
            addr = addr_of(spec)
            if addr is None:
                raise KeyError(f"field {key!r} in {section_key!r} has no address")
            # Compose onto the working value (prior write this call, else the live register)
            # so multiple bit-fields sharing one register merge correctly.
            base = writes.get(addr, current_raw.get(addr, 0)) & 0xFFFF
            writes[addr] = self._encode_setting(spec, val, base)
        return writes

    @staticmethod
    def _encode_setting(spec: dict[str, Any], val: Any, current: int) -> int:
        t = spec.get("type", "u16")
        if t == "bool":
            mask = spec.get("mask", 0xFFFF)
            return (current & ~mask | (mask if val else 0)) & 0xFFFF
        if t == "bits":
            mask = spec.get("mask", 0xFFFF)
            shift = (mask & -mask).bit_length() - 1
            return (current & ~mask | ((int(val) << shift) & mask)) & 0xFFFF
        if t == "enum":
            return int(val) & 0xFFFF
        if t == "time_hhmm":
            hh, mm = str(val).split(":")
            return (int(hh) * 100 + int(mm)) & 0xFFFF
        # numeric u16 / s16
        scale = spec.get("scale", 1)
        offset = spec.get("offset", 0)
        raw = round((float(val) - offset) / scale)
        if t == "s16":
            if not -32768 <= raw <= 32767:
                raise ValueError(f"value {val} out of signed 16-bit range after scaling")
            return raw & 0xFFFF
        if not 0 <= raw <= 65535:
            raise ValueError(f"value {val} out of 16-bit register range after scaling")
        return raw

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(
            vendor=self.vendor,
            model=self._spec.get("model", ""),
            firmware=self._spec.get("firmware"),
            ratings=self._spec.get("ratings"),
        )

    # --- identity + firmware pin (plan.md §4, Decision #1; task T032) ------------
    def pinned_firmware(self) -> dict[str, str] | None:
        """The firmware the register map was validated against, or None if unpinned.
        Mismatch ⇒ addresses may have shifted; re-run regscan to re-validate."""
        fw = self._spec.get("firmware")
        return dict(fw) if isinstance(fw, dict) else None

    def identity_blocks(self) -> list[RegBlock]:
        """Register blocks covering the `info:` identity fields (serial/protocol/…)."""
        return self._blocks_for(self._addresses_of(self._identity))

    def decode_identity(self, raw: Mapping[int, int]) -> dict[str, MetricValue]:
        """Decode the `info:` identity registers (serial, protocol, device type, …)."""
        out: dict[str, MetricValue] = {}
        for key, spec in self._identity.items():
            value = self._decode_one(spec, raw)
            if value is not None:
                out[key] = value
        return out

    def firmware_mismatches(self, observed: Mapping[str, MetricValue]) -> list[str]:
        """Compare the pinned firmware against an observed identity map, returning a
        human-readable mismatch per pinned key we could actually observe. Keys absent
        from the identity map (e.g. mcu/comm have no register addr yet) are skipped —
        we never warn about something we couldn't read. Comparison is string-wise so
        `2.1` matches whether the register decoded to `2.1`, `"2.1"`, or `21`/`2.1`."""
        pinned = self.pinned_firmware() or {}
        mismatches: list[str] = []
        for key, want in pinned.items():
            if key not in observed:
                continue
            got = observed[key]
            if _norm_fw(got) != _norm_fw(want):
                mismatches.append(f"{key}: profile pinned {want!r} but device reports {got!r}")
        return mismatches

    def register_blocks(self) -> list[RegBlock]:
        return self._blocks_for(self._all_addresses())

    def _blocks_for(self, address_set: set[int]) -> list[RegBlock]:
        """Cluster a set of addresses into contiguous-ish read transactions: split on a
        gap > 8 registers or once a block reaches _MAX_BLOCK registers."""
        addrs = sorted(address_set)
        blocks: list[RegBlock] = []
        if not addrs:
            return blocks
        start = prev = addrs[0]
        for addr in addrs[1:]:
            if addr - prev > 8 or (addr - start) >= _MAX_BLOCK:
                blocks.append(RegBlock(start, prev - start + 1, self._table))
                start = addr
            prev = addr
        blocks.append(RegBlock(start, prev - start + 1, self._table))
        return blocks

    def decode(self, raw: Mapping[int, int]) -> dict[str, MetricValue]:
        out: dict[str, MetricValue] = {}
        for key, spec in self._metrics.items():
            value = self._decode_one(spec, raw)
            if value is not None:
                out[key] = value
        self._derive(out)
        return out

    @staticmethod
    def _derive(out: dict[str, MetricValue]) -> None:
        """Fill canonical totals that aren't single registers (plan.md §4).

        `pv_power_w` is the sum of the per-MPPT powers. Single register maps rarely
        expose a PV total, so derive it whenever at least one MPPT reported — keeping
        the Now dashboard's headline PV figure identical across real + dummy devices.
        Missing != zero: if no MPPT power was decoded, leave it absent."""
        if "pv_power_w" not in out:
            mppt = [v for k, v in out.items()
                    if k.startswith("pv") and k.endswith("_power_w") and isinstance(v, (int, float))]
            if mppt:
                out["pv_power_w"] = round(sum(mppt), 1)

    # --- internals --------------------------------------------------------------
    def _all_addresses(self) -> set[int]:
        return self._addresses_of(self._metrics)

    @staticmethod
    def _addresses_of(specs: Mapping[str, dict[str, Any]]) -> set[int]:
        addrs: set[int] = set()
        for spec in specs.values():
            addr = spec.get("addr")
            if isinstance(addr, list):
                addrs.update(int(a) for a in addr)
            elif addr is not None:
                t = spec.get("type", "u16")
                addrs.add(int(addr))
                if t in ("u32", "s32"):
                    addrs.add(int(addr) + 1)
        return addrs

    def _decode_one(self, spec: dict[str, Any], raw: Mapping[int, int]) -> MetricValue | None:
        t = spec.get("type", "u16")
        addr = spec.get("addr")
        scale = spec.get("scale", 1)
        offset = spec.get("offset", 0)
        try:
            if t == "ascii":
                words = [raw[a] for a in addr]  # 2 chars per 16-bit word
                chars = []
                for w in words:
                    chars.append(chr((w >> 8) & 0xFF))
                    chars.append(chr(w & 0xFF))
                return "".join(chars).strip("\x00 ").strip()
            if t == "version_be":
                # Firmware/protocol packed as high.low bytes: 0x0201 -> "2.1".
                v = raw[addr] & 0xFFFF
                return f"{(v >> 8) & 0xFF}.{v & 0xFF}"
            if t == "enum":
                raw_v = raw[addr] & 0xFFFF
                values = spec.get("values", {})
                return values.get(raw_v, str(raw_v))
            if t == "bits":
                addrs = addr if isinstance(addr, list) else [addr]
                mask = spec.get("mask")
                raw_val = 0
                for i, a in enumerate(addrs):
                    raw_val |= (raw[a] & 0xFFFF) << (16 * i)
                if mask is not None:
                    raw_val &= mask
                # With a flag map or bit-prefix, decode set bits to human-readable codes
                # (plan.md §16): inverter_fault_codes -> ["F01", "F23", ...].
                flags = spec.get("flags")
                prefix = spec.get("bit_prefix")
                if flags or prefix:
                    names: list[str] = []
                    for bit in range(16 * len(addrs)):
                        if raw_val & (1 << bit):
                            if flags and bit in flags:
                                names.append(flags[bit])
                            elif prefix:
                                names.append(f"{prefix}{bit + 1:02d}")
                            else:
                                names.append(f"bit{bit}")
                    return names
                return raw_val
            if t in ("u16", "s16"):
                v = raw[addr] & 0xFFFF
                if t == "s16":
                    v = _signed(v, 16)
                return v * scale + offset
            if t in ("u32", "s32"):
                low_addr, high_addr = (addr[0], addr[1]) if isinstance(addr, list) else (addr, addr + 1)
                low, high = raw[low_addr] & 0xFFFF, raw[high_addr] & 0xFFFF
                if self._word_order == "low_first":
                    v = low | (high << 16)
                else:
                    v = high | (low << 16)
                if t == "s32":
                    v = _signed(v, 32)
                return v * scale + offset
        except KeyError:
            # A register this metric needs wasn't in the raw map — metric simply absent.
            return None
        return None
