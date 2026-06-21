"""Outbound integrations / egress (plan.md §14) — additive, brand-independent, and always
**off the hot path**. A failing integration degrades to a logged warning; it never blocks
or crashes polling/persistence (CLAUDE.md). The alert-notification channels live alongside
this in `app.alerts.channels`; this package is the *readings/events* egress.
"""

from .mqtt import MqttService
from .readings_webhook import ReadingsWebhookService, readings_context

__all__ = ["ReadingsWebhookService", "MqttService", "readings_context"]
