"""Solar/battery forecasting (plan.md §6).

A weather-driven PV-generation model plus a battery-SoC projection. The physics/maths
(`model.py`, `battery.py`) are pure and unit-tested; `openmeteo.py` is the only network
edge (off the hot path — failures degrade to a warning); `service.py` orchestrates them.
"""
