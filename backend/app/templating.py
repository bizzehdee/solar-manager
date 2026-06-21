"""Shared payload / message templating (plan.md §14, task L15).

One renderer for automation notify/alert messages *and* both webhook egress paths (alert
channels + readings). A template is plain text with ``{placeholder}`` / ``{placeholder:.2f}``
fields drawn from a context dict; unknown placeholders are left literal so the user can see
what didn't resolve. Two front-ends:

- ``render_message`` — plain text (automation messages). A malformed format spec falls back
  to the raw template (never raises).
- ``render_body`` — an HTTP body for a webhook. An empty template yields the JSON of the
  default object (today's behaviour, so existing setups are unchanged); otherwise the rendered
  template, with substituted values **JSON-escaped** so the body stays valid JSON. A malformed
  template falls back to the default JSON — egress must never crash on a bad template (§14).
"""

from __future__ import annotations

import json
import re
from typing import Any

# Only ``{name}`` / ``{name:spec}`` where name is an identifier — so literal JSON braces in a
# payload template (``{"text": …}``) are left untouched and don't need doubling. Specs can't
# contain braces (keeps matching unambiguous against surrounding JSON).
_FIELD = re.compile(r"\{([A-Za-z_]\w*)(?::([^{}]*))?\}")


def render_template(template: str, context: dict, *, json_escape: bool = False) -> str:
    """Substitute ``{key}`` / ``{key:.2f}`` placeholders from *context*. Unknown keys are left
    literal. Raises ``ValueError`` on a malformed format spec (callers decide the fallback)."""
    if not template or "{" not in template:
        return template or ""
    data = context or {}

    def repl(m: re.Match) -> str:
        key, spec = m.group(1), m.group(2) or ""
        if key not in data:
            return m.group(0)  # leave an unknown placeholder literal
        s = format(data[key], spec)  # may raise ValueError on a bad spec
        if json_escape:
            s = json.dumps(s)[1:-1]  # escape quotes/backslashes/control chars (no wrapping "")
        return s

    return _FIELD.sub(repl, template)


def render_message(template: str, context: dict) -> str:
    """Plain-text message (automation notify/alert). A malformed spec falls back to the raw
    template rather than erroring — the user still sees something."""
    try:
        return render_template(template, context)
    except (ValueError, IndexError):
        return template


def render_body(template: str | None, context: dict, default_obj: Any, *, json_escape: bool = True) -> str:
    """The HTTP body for a webhook. Empty template ⇒ ``json.dumps(default_obj)`` (the legacy
    default body). Otherwise the rendered template; a malformed template falls back to the
    default JSON so a bad template can never break egress."""
    if not template:
        return json.dumps(default_obj)
    try:
        return render_template(template, context, json_escape=json_escape)
    except (ValueError, IndexError):
        return json.dumps(default_obj)
