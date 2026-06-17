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


class ModbusYamlProfile:
    """A register-map profile backed by YAML."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec
        self.vendor: str = spec.get("vendor", "unknown")
        self._word_order: str = spec.get("word_order", "low_first")
        self._table: str = spec.get("register_table", "holding")
        self._metrics: dict[str, dict[str, Any]] = spec.get("metrics", {})

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
        return set(self._metrics.keys())

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(
            vendor=self.vendor,
            model=self._spec.get("model", ""),
            firmware=self._spec.get("firmware"),
            ratings=self._spec.get("ratings"),
        )

    def register_blocks(self) -> list[RegBlock]:
        addrs = sorted(self._all_addresses())
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
        return out

    # --- internals --------------------------------------------------------------
    def _all_addresses(self) -> set[int]:
        addrs: set[int] = set()
        for spec in self._metrics.values():
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
            if t == "bits":
                addrs = addr if isinstance(addr, list) else [addr]
                mask = spec.get("mask")
                raw_val = 0
                for i, a in enumerate(addrs):
                    raw_val |= (raw[a] & 0xFFFF) << (16 * i)
                if mask is not None:
                    raw_val &= mask
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
