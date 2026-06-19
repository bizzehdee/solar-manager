"""Device settings schema (plan.md §4, §12; task T070).

A brand-independent description of a device's *settings* — the writable holding registers
(work-mode timer, globals, battery limits) — as a form spec the UI can render generically.
Phase 5 uses it **read-only** (display current values); Phase 6 reuses it to drive edits.

The cross-family contract is `SettingsSchema` (+ a decoded values dict), NOT registers — so
the Modbus specifics stay inside the profile, exactly like `Reading` for live metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Acronyms to upper-case when humanising a snake_case key into a label.
_ACRONYMS = {"soc": "SoC", "bms": "BMS", "pv": "PV", "ct": "CT", "ah": "Ah", "hz": "Hz"}
# Trailing key tokens that denote a unit (and the unit string to show).
_UNITS = {"v": "V", "a": "A", "w": "W", "wh": "Wh", "hz": "Hz", "pct": "%", "ah": "Ah", "c": "°C"}


def unit_for(key: str) -> str | None:
    """Infer a display unit from a key's trailing token (e.g. float_voltage_v → V)."""
    return _UNITS.get(key.rsplit("_", 1)[-1])


def humanize(key: str) -> str:
    """snake_case → a readable label, dropping a trailing unit token and fixing acronyms.
    e.g. `target_soc_pct` → "Target SoC", `float_voltage_v` → "Float voltage"."""
    parts = key.split("_")
    if len(parts) > 1 and parts[-1] in _UNITS:
        parts = parts[:-1]
    words = [_ACRONYMS.get(p, p) for p in parts]
    if words:
        words[0] = words[0] if words[0] in _ACRONYMS.values() else words[0].capitalize()
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label: str
    type: str                       # bool | enum | number | time | int
    unit: str | None = None
    options: list[dict] | None = None   # for enum: [{value, label}, ...]
    # Write bounds (Phase 6): inclusive min/max on the *decoded* value. None ⇒ unbounded
    # (numeric writes still clamp to the register's u16/s16 range in the encoder). The UI
    # uses these for input constraints; validation enforces them server-side.
    min: float | None = None
    max: float | None = None
    # Read-only fields are displayed but never written: excluded from the write allow-list,
    # rejected by validation, and shown without edit controls (some inverter values — e.g.
    # grid type / grid frequency — are observable but not settable over Modbus).
    writable: bool = True
    # Whether this field is in the profile's **automation-safe** subset (L03e): rule actions may
    # target it without an at-your-own-risk override. A conservative, profile-curated allow-list —
    # writable-but-not-safe fields are still settable by automation, but flagged `at_risk`.
    automation_safe: bool = False

    def as_dict(self) -> dict:
        d = {"key": self.key, "label": self.label, "type": self.type}
        if self.unit:
            d["unit"] = self.unit
        if self.options is not None:
            d["options"] = self.options
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if not self.writable:
            d["writable"] = False
        if self.automation_safe:
            d["automation_safe"] = True
        return d


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    label: str
    fields: list[FieldSpec]
    repeating: bool = False         # True ⇒ values are a list of `count` rows (timer slots)
    count: int | None = None

    def as_dict(self) -> dict:
        d = {
            "key": self.key,
            "label": self.label,
            "repeating": self.repeating,
            "fields": [f.as_dict() for f in self.fields],
        }
        if self.count is not None:
            d["count"] = self.count
        return d


@dataclass(frozen=True, slots=True)
class SettingsSchema:
    sections: list[Section] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"sections": [s.as_dict() for s in self.sections]}


def enum_options(values: dict) -> list[dict]:
    """Turn a profile enum `{2: zero_export_to_ct}` into UI options with readable labels."""
    return [{"value": k, "label": humanize(str(v))} for k, v in values.items()]
