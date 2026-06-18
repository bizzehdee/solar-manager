"""PV generation model (plan.md §6; task T061) — §21 critical logic.

Turns weather (global horizontal irradiance, air temperature) into expected AC power for
one or more array segments:

1. **Solar position** — the PSA algorithm (Blanco-Muriel 2001): sun elevation/azimuth from
   lat/lon/UTC time. Compact and accurate to ~0.01°.
2. **Transposition** — GHI → plane-of-array irradiance for a tilted/oriented panel, via an
   Erbs diffuse split + isotropic sky model (+ ground reflection).
3. **Cell temperature** — NMOT model: warmer cells lose power.
4. **DC→AC power** — `kWp × POA/1000 × (1 + γ_Pmax·(T_cell−25)) × performance_ratio`,
   summed across segments.

All pure functions of their inputs. Datasheet defaults (plan.md Decision #4):
γ_Pmax = −0.26 %/°C, NMOT = 41 °C.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Datasheet defaults (plan.md Decision #4).
DEFAULT_GAMMA_PMAX = -0.26   # %/°C, power temperature coefficient
DEFAULT_NMOT = 41.0          # °C, nominal module operating temperature
DEFAULT_PR = 0.85            # performance ratio (inverter + wiring + soiling losses)
GROUND_ALBEDO = 0.2
SOLAR_CONSTANT = 1361.0      # W/m², extraterrestrial irradiance

_RAD = math.pi / 180.0


@dataclass(frozen=True, slots=True)
class ArraySegment:
    """One PV string/MPPT: peak power + orientation + (optional) panel thermal coeffs."""

    name: str
    kwp: float
    tilt: float           # degrees from horizontal (0 = flat, 90 = vertical)
    azimuth: float        # degrees from north, clockwise (180 = due south)
    gamma_pmax: float = DEFAULT_GAMMA_PMAX
    nmot: float = DEFAULT_NMOT

    @classmethod
    def from_dict(cls, d: dict) -> "ArraySegment":
        return cls(
            name=str(d.get("name", "array")),
            kwp=float(d["kwp"]),
            tilt=float(d.get("tilt", 30.0)),
            azimuth=float(d.get("azimuth", 180.0)),
            gamma_pmax=float(d.get("gamma_pmax", DEFAULT_GAMMA_PMAX)),
            nmot=float(d.get("nmot", DEFAULT_NMOT)),
        )


def solar_elevation_azimuth(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Sun elevation + azimuth (degrees) for a location/time (PSA algorithm).

    Azimuth is measured from north, clockwise (so due south = 180°). Elevation is negative
    when the sun is below the horizon. `when` is treated as UTC."""
    when = when.astimezone(timezone.utc)
    decimal_hours = when.hour + when.minute / 60.0 + when.second / 3600.0
    y, m, d = when.year, when.month, when.day
    aux1 = (m - 14) // 12
    jd = (
        (1461 * (y + 4800 + aux1)) // 4
        + (367 * (m - 2 - 12 * aux1)) // 12
        - (3 * ((y + 4900 + aux1) // 100)) // 4
        + d - 32075
    ) - 0.5 + decimal_hours / 24.0
    n = jd - 2451545.0

    omega = 2.1429 - 0.0010394594 * n
    mean_long = 4.8950630 + 0.017202791698 * n
    mean_anom = 6.2400600 + 0.0172019699 * n
    ecl_long = (
        mean_long + 0.03341607 * math.sin(mean_anom) + 0.00034894 * math.sin(2 * mean_anom)
        - 0.0001134 - 0.0000203 * math.sin(omega)
    )
    ecl_obliq = 0.4090928 - 6.2140e-9 * n + 0.0000396 * math.cos(omega)

    sin_ecl_long = math.sin(ecl_long)
    ra = math.atan2(math.cos(ecl_obliq) * sin_ecl_long, math.cos(ecl_long))
    if ra < 0:
        ra += 2 * math.pi
    decl = math.asin(math.sin(ecl_obliq) * sin_ecl_long)

    gmst = 6.6974243242 + 0.0657098283 * n + decimal_hours
    lmst = (gmst * 15 + lon) * _RAD
    hour_angle = lmst - ra

    lat_r = lat * _RAD
    cos_hour = math.cos(hour_angle)
    zenith = math.acos(
        math.cos(lat_r) * cos_hour * math.cos(decl) + math.sin(decl) * math.sin(lat_r)
    )
    az = math.atan2(-math.sin(hour_angle), math.tan(decl) * math.cos(lat_r) - math.sin(lat_r) * cos_hour)
    if az < 0:
        az += 2 * math.pi
    # Parallax correction (Earth radius / AU).
    zenith += (6371.01 / 149597890.0) * math.sin(zenith)
    return 90.0 - zenith / _RAD, az / _RAD


def _erbs_diffuse_fraction(ghi: float, elevation_deg: float, day_of_year: int) -> float:
    """Erbs correlation: fraction of GHI that is diffuse, from the clearness index kt."""
    if ghi <= 0 or elevation_deg <= 0:
        return 1.0
    cos_z = math.sin(elevation_deg * _RAD)
    e0 = 1.0 + 0.033 * math.cos(2 * math.pi * day_of_year / 365.0)  # earth-sun distance factor
    extra = SOLAR_CONSTANT * e0 * cos_z
    if extra <= 0:
        return 1.0
    kt = max(0.0, min(1.0, ghi / extra))
    if kt <= 0.22:
        return 1.0 - 0.09 * kt
    if kt <= 0.80:
        return 0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4
    return 0.165


def poa_irradiance(
    ghi: float, elevation_deg: float, azimuth_deg: float, tilt: float, panel_azimuth: float,
    day_of_year: int, albedo: float = GROUND_ALBEDO,
) -> float:
    """Plane-of-array irradiance (W/m²) from GHI via Erbs split + isotropic sky model.

    POA = beam·cos(AOI) + diffuse·(1+cos tilt)/2 + GHI·albedo·(1−cos tilt)/2. Returns 0 at
    night / for a sun below the horizon."""
    if ghi <= 0 or elevation_deg <= 0:
        return 0.0
    zenith = (90.0 - elevation_deg) * _RAD
    cos_z = math.cos(zenith)
    df = _erbs_diffuse_fraction(ghi, elevation_deg, day_of_year)
    dhi = ghi * df
    dni = (ghi - dhi) / max(cos_z, 0.05)

    tilt_r = tilt * _RAD
    # angle of incidence between sun and panel normal
    cos_aoi = (
        math.cos(zenith) * math.cos(tilt_r)
        + math.sin(zenith) * math.sin(tilt_r) * math.cos((azimuth_deg - panel_azimuth) * _RAD)
    )
    cos_aoi = max(0.0, cos_aoi)
    beam = dni * cos_aoi
    sky_diffuse = dhi * (1 + math.cos(tilt_r)) / 2.0
    ground = ghi * albedo * (1 - math.cos(tilt_r)) / 2.0
    return beam + sky_diffuse + ground


def cell_temperature(poa: float, air_temp_c: float, nmot: float) -> float:
    """Module cell temperature from the NMOT model. At 800 W/m² the cell sits (NMOT−20)
    above ambient; scales linearly with irradiance."""
    return air_temp_c + (nmot - 20.0) / 800.0 * poa


def segment_power_w(
    segment: ArraySegment, ghi: float, air_temp_c: float, elevation_deg: float,
    azimuth_deg: float, day_of_year: int, performance_ratio: float = DEFAULT_PR,
) -> float:
    """Expected AC power (W) from one segment for the given weather + sun position."""
    poa = poa_irradiance(ghi, elevation_deg, azimuth_deg, segment.tilt, segment.azimuth, day_of_year)
    if poa <= 0:
        return 0.0
    t_cell = cell_temperature(poa, air_temp_c, segment.nmot)
    temp_factor = 1.0 + segment.gamma_pmax / 100.0 * (t_cell - 25.0)
    watts = segment.kwp * 1000.0 * (poa / 1000.0) * temp_factor * performance_ratio
    return max(0.0, watts)


def expected_power_w(
    segments: list[ArraySegment], lat: float, lon: float, when: datetime,
    ghi: float, air_temp_c: float, performance_ratio: float = DEFAULT_PR,
) -> float:
    """Total expected AC power (W) across all segments at one instant."""
    elevation, azimuth = solar_elevation_azimuth(lat, lon, when)
    doy = when.timetuple().tm_yday
    return sum(
        segment_power_w(s, ghi, air_temp_c, elevation, azimuth, doy, performance_ratio)
        for s in segments
    )
