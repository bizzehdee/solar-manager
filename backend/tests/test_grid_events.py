"""Grid-outage detection (plan.md §19 / T095): inference, transition detection, service."""

from __future__ import annotations

from datetime import datetime, timezone

from app.grid_events import GridEventDetector, GridEventService, grid_up
from app.storage.repository import SqliteHistoryRepository


# --- grid_up inference ----------------------------------------------------------
def test_grid_up_prefers_run_state_then_voltage():
    assert grid_up({"run_state": "on_grid"}) is True
    assert grid_up({"run_state": "off_grid"}) is False
    assert grid_up({"grid_voltage_v": 240.0}) is True
    assert grid_up({"grid_voltage_v": 0.0}) is False
    assert grid_up({}) is None                       # unknown ≠ down
    assert grid_up({"run_state": "weird"}) is None


# --- transition detector --------------------------------------------------------
def test_detector_emits_start_and_end_on_transitions():
    d = GridEventDetector()
    assert d.step("inv", True, 0.0) is None           # initial state, no event
    assert d.step("inv", True, 1.0) is None            # steady
    assert d.step("inv", False, 2.0) == "outage_start"  # grid lost
    assert d.step("inv", False, 3.0) is None           # still out
    assert d.step("inv", True, 4.0) == "outage_end"     # grid back
    assert d.step("inv", None, 5.0) is None             # unknown doesn't flip state


# --- service writes events ------------------------------------------------------
class _FakePoller:
    def __init__(self) -> None:
        self.metrics: dict = {}

    def snapshot(self) -> dict:
        return {"devices": {"inv": {"metrics": self.metrics}}}


async def test_service_logs_outage_events():
    repo = await SqliteHistoryRepository.open(":memory:")
    poller = _FakePoller()
    clock = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    svc = GridEventService(repo, poller, clock=lambda: clock)

    poller.metrics = {"run_state": "on_grid"}
    assert await svc.evaluate_once() == []           # initial, no event
    poller.metrics = {"run_state": "off_grid"}
    assert await svc.evaluate_once() == ["outage_start"]
    poller.metrics = {"run_state": "on_grid"}
    assert await svc.evaluate_once() == ["outage_end"]

    events = await repo.list_grid_events()
    assert [e["event"] for e in events] == ["outage_end", "outage_start"]  # newest first
    assert all(e["device_id"] == "inv" for e in events)
