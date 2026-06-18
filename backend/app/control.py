"""Settings write-back orchestration + safety (plan.md §12; tasks T073–T075).

The whole high-risk write path lives here so the seven §12 rules are in one place and
heavily unit-tested: schema **validation** (bounds/enums) → **encode** → **allow-listed**
register writes → **read-back verify** → **etag/If-Match** concurrency → (audit, at the API).
The pure helpers (validate / etag / verify / contiguous_runs) take plain data so they test
without a Device; `apply_settings` glues them to a device's transport + profile.

The flow is exercised end-to-end against the dummy (in-memory writes) — dummy-first, zero
risk — before ever pointing at real hardware. The API gates all of this behind the
SOLARVOLT_ENABLE_CONTROL deploy flag; nothing here assumes it's on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .settings_schema import Section, SettingsSchema


class SettingsError(Exception):
    """Base for control write-path failures."""


class SettingsValidationError(SettingsError):
    """Proposed values failed schema validation (unknown field, bad type/bounds/enum)."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class StaleSettingsError(SettingsError):
    """The supplied If-Match etag didn't match the device's current settings — something
    changed since the client read them. Surfaces as 412 (write refused, no register touched)."""

    def __init__(self, current_etag: str) -> None:
        super().__init__("settings changed since they were read (stale If-Match)")
        self.current_etag = current_etag


class NotWritableError(SettingsError):
    """The encoder produced a register address outside the profile's allow-list. A hard
    backstop against arbitrary-address writes via the API — should never fire in practice."""

    def __init__(self, addrs: list[int]) -> None:
        super().__init__(f"refusing to write non-allow-listed registers: {addrs}")
        self.addrs = addrs


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of an apply: the verified `ok`, the before/after settings, the new etag, and
    any read-back mismatches (rollback signal, §12 rule 4)."""

    ok: bool
    section: str
    index: int | None
    before: dict
    after: dict
    changes: dict          # {field: {"old": ..., "new": ...}} for the touched section/slot
    mismatches: list[str]  # fields whose read-back value != requested (empty ⇒ verified)
    etag: str              # etag of the after-state


# --- pure helpers ---------------------------------------------------------------

def settings_etag(values: Any) -> str:
    """Stable short etag over a decoded settings structure (whole device or one section)."""
    blob = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _section(schema: SettingsSchema, key: str) -> Section:
    for s in schema.sections:
        if s.key == key:
            return s
    raise SettingsValidationError([f"unknown settings section {key!r}"])


def validate_settings(
    schema: SettingsSchema, section_key: str, values: Any, index: int | None = None
) -> dict:
    """Validate proposed values against the schema, returning a cleaned/typed dict.

    Checks the section exists, the slot index is in range for repeating sections (and absent
    otherwise), every field is known, and each value matches its type + bounds/enum. Raises
    SettingsValidationError with a per-field message list on any failure (client- and
    server-side, §12 rule 1)."""
    if not isinstance(values, Mapping) or not values:
        raise SettingsValidationError(["no values to write"])
    section = _section(schema, section_key)
    if section.repeating:
        count = section.count or 0
        if not isinstance(index, int) or isinstance(index, bool) or not (0 <= index < count):
            raise SettingsValidationError([f"section {section_key!r} requires a slot index 0..{count - 1}"])
    elif index is not None:
        raise SettingsValidationError([f"section {section_key!r} is not repeating; no index allowed"])

    fields = {f.key: f for f in section.fields}
    errors: list[str] = []
    cleaned: dict[str, Any] = {}
    for key, val in values.items():
        spec = fields.get(key)
        if spec is None:
            errors.append(f"unknown field {key!r} in section {section_key!r}")
            continue
        if not spec.writable:
            errors.append(f"field {key!r} is read-only")
            continue
        try:
            cleaned[key] = _validate_field(spec, val)
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
    if errors:
        raise SettingsValidationError(errors)
    return cleaned


def _validate_field(spec, val: Any) -> Any:
    t = spec.type
    if t == "bool":
        if isinstance(val, bool):
            return val
        if val in (0, 1):
            return bool(val)
        raise ValueError("expected a boolean")
    if t == "enum":
        allowed = {o["value"] for o in (spec.options or [])}
        iv = _as_int(val)
        if iv not in allowed:
            raise ValueError(f"not an allowed option (expected one of {sorted(allowed)})")
        return iv
    if t == "time":
        return _validate_time(val)
    if t == "int":
        iv = _as_int(val)
        _check_bounds(spec, iv)
        return iv
    # number
    fv = _as_float(val)
    _check_bounds(spec, fv)
    return fv


def _as_int(val: Any) -> int:
    if isinstance(val, bool):
        raise ValueError("expected a number, got a boolean")
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            pass
    raise ValueError("expected an integer")


def _as_float(val: Any) -> float:
    if isinstance(val, bool):
        raise ValueError("expected a number, got a boolean")
    if isinstance(val, (int, float)):
        f = float(val)
    elif isinstance(val, str):
        try:
            f = float(val)
        except ValueError:
            raise ValueError("expected a number") from None
    else:
        raise ValueError("expected a number")
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError("expected a finite number")
    return f


def _check_bounds(spec, v: float) -> None:
    if spec.min is not None and v < spec.min:
        raise ValueError(f"below minimum {spec.min}")
    if spec.max is not None and v > spec.max:
        raise ValueError(f"above maximum {spec.max}")


def _validate_time(val: Any) -> str:
    s = str(val)
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError("expected HH:MM")
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError("expected HH:MM") from None
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("not a valid 24-hour time")
    return f"{h:02d}:{m:02d}"


def contiguous_runs(writes: Mapping[int, int]) -> list[tuple[int, list[int]]]:
    """Group an addr→value map into (start, [values]) runs of consecutive addresses, so the
    transport can write a slot's adjacent registers in one transaction (atomic-ish, §12)."""
    runs: list[tuple[int, list[int]]] = []
    for addr in sorted(writes):
        if runs and addr == runs[-1][0] + len(runs[-1][1]):
            runs[-1][1].append(writes[addr])
        else:
            runs.append((addr, [writes[addr]]))
    return runs


def _section_view(values: dict, section_key: str, index: int | None) -> dict:
    """The {field: value} dict for one section (or one timer slot) of a decoded settings map."""
    block = (values or {}).get(section_key)
    if isinstance(block, list):
        return block[index or 0] if 0 <= (index or 0) < len(block) else {}
    return block or {}


def verify_settings(section_key: str, cleaned: Mapping[str, Any], index: int | None, after: dict) -> list[str]:
    """Compare requested values against the re-read state; return the fields that didn't take
    (read-back verification, §12 rule 4). Numbers compare with a small tolerance to absorb
    scale rounding (encode→register→decode); bools/enums/times compare exactly."""
    view = _section_view(after, section_key, index)
    bad: list[str] = []
    for key, want in cleaned.items():
        got = view.get(key)
        if isinstance(want, (int, float)) and not isinstance(want, bool) and isinstance(got, (int, float)):
            if abs(float(got) - float(want)) > 0.01:
                bad.append(key)
        elif got != want:
            bad.append(key)
    return bad


def diff_changes(section_key: str, index: int | None, before: dict, after: dict, keys) -> dict:
    """Per-field old→new for the touched fields (audit + UI confirm), drawn from before/after."""
    bv = _section_view(before, section_key, index)
    av = _section_view(after, section_key, index)
    return {k: {"old": bv.get(k), "new": av.get(k)} for k in keys}


# --- orchestration --------------------------------------------------------------

async def apply_settings(
    device, section_key: str, values: Any, *, index: int | None = None, if_match: str | None = None
) -> ApplyResult:
    """Run the full write flow against a Device and return the verified result.

    validate → (etag/If-Match guard) → encode → allow-listed write → re-read → verify.
    Register-backed profiles go through `encode_settings` + the transport with the profile's
    write allow-list enforced; synthesizing profiles (the dummy) apply in-memory. Raises
    SettingsValidationError / StaleSettingsError / NotWritableError / SettingsError; transport
    errors propagate (TransportError) so the API can report a write failure."""
    schema = device.settings_schema()
    if schema is None or not device.is_writable:
        raise SettingsError("device exposes no writable settings")

    cleaned = validate_settings(schema, section_key, values, index)

    before = await device.read_settings()
    before_etag = settings_etag(before)
    if if_match is not None and if_match != before_etag:
        raise StaleSettingsError(before_etag)

    profile = device.profile
    if hasattr(profile, "encode_settings"):
        raw = await device.read_settings_raw()
        try:
            writes = profile.encode_settings(section_key, cleaned, raw, index=index)
        except ValueError as exc:  # register-range guard etc. — a validation failure
            raise SettingsValidationError([str(exc)]) from exc
        allowed = profile.writable_addresses()
        bad = sorted(a for a in writes if a not in allowed)
        if bad:
            raise NotWritableError(bad)
        for start, vals in contiguous_runs(writes):
            await device.transport.write_registers(start, vals)
    else:  # synthesizing profile (dummy) — in-memory apply, mirrors read_settings
        profile.apply_settings(section_key, cleaned, index=index)

    after = await device.read_settings()
    mismatches = verify_settings(section_key, cleaned, index, after)
    return ApplyResult(
        ok=not mismatches,
        section=section_key,
        index=index,
        before=before,
        after=after,
        changes=diff_changes(section_key, index, before, after, cleaned.keys()),
        mismatches=mismatches,
        etag=settings_etag(after),
    )
