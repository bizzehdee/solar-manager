"""Firmware-pin verification at connect (plan.md §4, Decision #1; task T032).

The SG05LP1 register map is pinned to a firmware (Protocol/MCU/COMM) in the profile
YAML. Firmware updates can shift register addresses, so on connect we read the
device's identity registers and compare them to the pin. A mismatch is a **warning,
never a hard failure** — egress/diagnostics are off the hot path (plan.md), and a unit
that merely shifted one address still reads most metrics correctly. The warning tells
the operator to re-run regscan and re-validate.

This is best-effort: we only compare pinned keys the profile actually maps to a
register (today that's `protocol`; `mcu`/`comm` have no address in the map yet), and a
transport error while reading identity downgrades to a single warning rather than
aborting startup.
"""

from __future__ import annotations

import logging

from .base import Device, TransportError

log = logging.getLogger("solarvolt.firmware")


async def verify_firmware(device: Device, *, logger: logging.Logger = log) -> list[str]:
    """Read `device`'s identity registers and compare to its profile's firmware pin.

    Returns the list of mismatch descriptions (empty when matched, unpinned, or
    unreadable). Logs a warning for any mismatch or for an identity read that failed.
    Never raises — firmware checking must not block polling/persistence.
    """
    profile = device.profile
    # Only register-backed profiles carry a pin + identity registers (not the dummy).
    pinned = getattr(profile, "pinned_firmware", None)
    decode_identity = getattr(profile, "decode_identity", None)
    identity_blocks = getattr(profile, "identity_blocks", None)
    if not callable(pinned) or not callable(decode_identity) or not callable(identity_blocks):
        return []
    if not pinned():
        return []

    try:
        raw: dict[int, int] = {}
        for block in identity_blocks():
            regs = await device.transport.read_registers(block.start, block.count, block.table)
            for offset, value in enumerate(regs):
                raw[block.start + offset] = value
        observed = decode_identity(raw)
    except TransportError as exc:
        logger.warning(
            "Could not read identity from device %s to verify firmware pin: %s",
            device.device_id, exc,
        )
        return []

    mismatches = profile.firmware_mismatches(observed)
    if mismatches:
        logger.warning(
            "Device %s firmware does not match the profile pin — register addresses may "
            "have shifted; re-run regscan to re-validate. %s",
            device.device_id, "; ".join(mismatches),
        )
    return mismatches
