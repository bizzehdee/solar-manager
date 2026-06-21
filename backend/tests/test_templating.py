"""Shared templating (L15) — critical-logic (§21, ≥90%): substitution, format specs,
unknown-key passthrough, JSON-escaping, and malformed-template fallback to the default body."""

from __future__ import annotations

import json

from app.templating import render_body, render_message, render_template


def test_substitutes_known_placeholders():
    assert render_template("SoC {soc}%", {"soc": 42}) == "SoC 42%"


def test_supports_format_specs():
    assert render_template("{pv:.1f} kW", {"pv": 3.456}) == "3.5 kW"


def test_unknown_placeholder_left_literal():
    assert render_template("{soc} / {missing}", {"soc": 50}) == "50 / {missing}"


def test_empty_or_plain_template_returned_as_is():
    assert render_template("", {"x": 1}) == ""
    assert render_template("no fields here", {"x": 1}) == "no fields here"


def test_render_message_falls_back_to_raw_on_bad_spec():
    # A bad format spec must not raise — the user still gets the (unrendered) template.
    assert render_message("{soc:.1fZ}", {"soc": 42}) == "{soc:.1fZ}"


def test_render_body_empty_template_is_default_json():
    default = {"type": "readings", "ts": 1}
    assert render_body("", {}, default) == json.dumps(default)
    assert render_body(None, {}, default) == json.dumps(default)


def test_render_body_renders_and_json_escapes_values():
    # A value containing a quote must be escaped so the body stays valid JSON.
    ctx = {"name": 'he said "hi"', "soc": 42}
    body = render_body('{"msg": "{name}", "soc": {soc}}', ctx, {"fallback": True})
    assert json.loads(body) == {"msg": 'he said "hi"', "soc": 42}


def test_render_body_escapes_newlines_and_backslashes():
    body = render_body('{"m": "{v}"}', {"v": "a\nb\\c"}, {})
    assert json.loads(body) == {"m": "a\nb\\c"}


def test_render_body_malformed_template_falls_back_to_default():
    default = {"ok": False}
    # Bad spec inside the template → don't crash egress, send the default JSON instead.
    body = render_body('{"x": {soc:.1fZ}}', {"soc": 42}, default)
    assert json.loads(body) == default


def test_render_body_non_json_content_skips_escaping():
    # For a non-JSON body the author may not want JSON escaping.
    body = render_body("text={v}", {"v": 'a"b'}, {}, json_escape=False)
    assert body == 'text=a"b'
