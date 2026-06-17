"""Shared fixtures. A fixed clock makes the dummy fully deterministic (plan.md §21)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture
def midday() -> datetime:
    # 13:00 local — PV producing, a deterministic point on the synthetic bell curve.
    return datetime(2026, 6, 17, 13, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def midnight() -> datetime:
    return datetime(2026, 6, 17, 0, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def fixed_clock(midday):
    return lambda: midday
