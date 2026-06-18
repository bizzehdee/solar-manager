"""Rollup bucketing (plan.md §5; task T043) — §21 critical logic."""

from __future__ import annotations

from app.aggregator import Bucket, INTERVALS, bucket_rows, floor_to


def test_floor_to_interval():
    assert floor_to(0.0, 300) == 0.0
    assert floor_to(299.0, 300) == 0.0
    assert floor_to(301.0, 300) == 300.0
    assert floor_to(3661.0, 3600) == 3600.0


def test_buckets_average_min_max_last():
    rows = [
        (0.0, "d", "pv_power_w", 100.0),
        (60.0, "d", "pv_power_w", 200.0),
        (120.0, "d", "pv_power_w", 300.0),
    ]
    [b] = bucket_rows(rows, 300)
    assert b.bucket == 0.0 and b.n == 3
    assert b.avg == 200.0 and b.min == 100.0 and b.max == 300.0
    assert b.last == 300.0  # value at the greatest ts in the bucket


def test_last_resolves_by_timestamp_not_input_order():
    # Unsorted input — last must be the value at the max ts (250), i.e. 999.
    rows = [
        (250.0, "d", "m", 999.0),
        (10.0, "d", "m", 1.0),
        (100.0, "d", "m", 2.0),
    ]
    [b] = bucket_rows(rows, 300)
    assert b.last == 999.0


def test_separate_buckets_per_interval_and_metric():
    rows = [
        (0.0, "d", "pv_power_w", 100.0),
        (301.0, "d", "pv_power_w", 400.0),   # next 5m bucket
        (10.0, "d", "load_power_w", 50.0),   # different metric, same bucket
    ]
    buckets = bucket_rows(rows, 300)
    assert len(buckets) == 3
    # deterministic sort: by bucket, device, metric
    assert buckets[0] == Bucket(0.0, "d", "load_power_w", 50.0, 50.0, 50.0, 50.0, 1)
    assert buckets[1].metric == "pv_power_w" and buckets[1].bucket == 0.0
    assert buckets[2].bucket == 300.0 and buckets[2].avg == 400.0


def test_hourly_and_daily_grouping():
    rows = [(t, "d", "m", float(t)) for t in (0.0, 1800.0, 3600.0)]
    assert len(bucket_rows(rows, INTERVALS["1h"])) == 2   # 0-3600, 3600-7200
    assert len(bucket_rows(rows, INTERVALS["1d"])) == 1   # all same day


def test_empty_rows():
    assert bucket_rows([], 300) == []
