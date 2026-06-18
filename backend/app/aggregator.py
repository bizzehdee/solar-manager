"""Rollup bucketing (plan.md §5; task T043) — a §21 critical-logic module.

Raw samples are rolled up into fixed time buckets (5-minute, hourly, daily) so history
queries stay cheap and raw data can be pruned past its retention window. The bucketing
is a **pure function** of (rows, interval) — no DB, no clock — so it's unit-tested with
known vectors; the repository just calls it and upserts the result.

Each bucket keeps avg / min / max / last / count:
- **avg/min/max** suit instantaneous metrics (power, SoC, temperature).
- **last** is what cumulative counters (`today_*_wh`, `total_*_wh`) need — the counter's
  value at the end of the bucket, not its average.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Standard bucket widths in seconds.
INTERVALS: dict[str, int] = {"5m": 300, "1h": 3600, "1d": 86400}


@dataclass(frozen=True, slots=True)
class Bucket:
    bucket: float          # epoch seconds, floored to the interval
    device_id: str
    metric: str
    avg: float
    min: float
    max: float
    last: float
    n: int


# A raw row: (epoch_seconds, device_id, metric, value).
Row = tuple[float, str, str, float]


def floor_to(ts: float, interval: int) -> float:
    """Floor an epoch timestamp to the start of its interval bucket."""
    return float(int(ts // interval) * interval)


def bucket_rows(rows: Iterable[Row], interval: int) -> list[Bucket]:
    """Group raw rows into buckets of `interval` seconds, one Bucket per
    (bucket, device_id, metric). Rows need not be sorted; `last` is resolved by the
    greatest timestamp seen within each bucket. Result is sorted for determinism."""
    acc: dict[tuple[float, str, str], _Acc] = {}
    for ts, device_id, metric, value in rows:
        key = (floor_to(ts, interval), device_id, metric)
        a = acc.get(key)
        if a is None:
            acc[key] = _Acc(value, value, value, value, ts, 1)
        else:
            a.add(ts, value)
    out = [
        Bucket(b, dev, met, a.total / a.n, a.min, a.max, a.last, a.n)
        for (b, dev, met), a in acc.items()
    ]
    out.sort(key=lambda x: (x.bucket, x.device_id, x.metric))
    return out


@dataclass(slots=True)
class _Acc:
    total: float
    min: float
    max: float
    last: float
    last_ts: float
    n: int

    def add(self, ts: float, value: float) -> None:
        self.total += value
        self.min = min(self.min, value)
        self.max = max(self.max, value)
        self.n += 1
        if ts >= self.last_ts:
            self.last = value
            self.last_ts = ts
