"""Alerting subsystem (plan.md §15): notification channels + inbox repository.

The rule engine and AlertService were retired in L03e-5e; alert authoring and dispatch
now live in the automation system (``app.automation``). This package retains:
  - ``channels.py``  — channel drivers (webhook / email / Telegram / ntfy / Gotify / Pushover)
    and the ``build_channels`` / ``dispatch`` helpers used by AutomationService.
  - The inbox (fired/cleared alert rows) is managed by ``AlertRepository`` in storage.
"""
