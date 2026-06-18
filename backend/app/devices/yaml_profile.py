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
from .base import RegBlock

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
