"""`gateway.app.services.email_templates` -- pure rendering, no I/O.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #70. Only
`TASK_COMPLETED`/`TASK_FAILED` are wired to a real sender today
(`notify.py`); every `EmailKind` is exercised here anyway, since the module
promises they all share one skeleton and never leak markup from a caller's
field values.
"""

from __future__ import annotations

import re

import pytest

from gateway.app.services.email_templates import EmailKind, render_email, subject_prefix


def test_every_kind_renders_a_complete_html_document() -> None:
    for kind in EmailKind:
        html_body = render_email(
            kind,
            preheader="preview text",
            title="Some title",
            lede="Some lede.",
            rows=[("Projeto", "p1")],
        )
        assert html_body.startswith("<!doctype html>")
        assert "</html>" in html_body


def test_every_kind_has_a_distinct_accent_color_and_badge_label() -> None:
    """Approved on the design canvas: no two kinds should read as the same
    severity at a glance -- both the accent hex and the badge text must be
    unique across the whole enum."""
    from gateway.app.services.email_templates import _STYLES  # the module's own source of truth

    accents = [style.accent for style in _STYLES.values()]
    badges = [style.badge for style in _STYLES.values()]
    assert len(accents) == len(set(accents)), "two EmailKind values share an accent color"
    assert len(badges) == len(set(badges)), "two EmailKind values share a badge label"
    assert set(_STYLES.keys()) == set(EmailKind)


def test_subject_prefix_is_bracketed_and_kind_specific() -> None:
    prefixes = {subject_prefix(kind) for kind in EmailKind}
    assert len(prefixes) == len(EmailKind)
    for prefix in prefixes:
        assert prefix.startswith("[CodexBridge] ")


@pytest.mark.parametrize(
    "value",
    [
        "<script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "normal & <b>bold</b>",
    ],
)
def test_every_text_field_is_html_escaped(value: str) -> None:
    """Every argument is caller-controlled text -- some of it, per `render_email`'s
    own docstring, may originate from an untrusted resolved issue or a task's
    error message. None of it may reach the output as live markup."""
    html_body = render_email(
        EmailKind.TASK_FAILED,
        preheader=value,
        title=value,
        lede=value,
        rows=[(value, value)],
        sign_line1=value,
        sign_line2=value,
    )
    assert "<script>" not in html_body
    # `_esc` escapes `<`/`>`/`&` only (quote=False -- these values are only
    # ever placed as text content, never inside an attribute, so a raw `"`
    # is inert here). The literal substring "onerror=" can survive as inert
    # text; what must not survive is a live `<img ...>` tag able to fire it.
    assert "<img" not in html_body.lower()
    assert "<b>bold</b>" not in html_body


def test_a_cta_link_escapes_its_href_and_label() -> None:
    html_body = render_email(
        EmailKind.APPROVAL_NEEDED,
        preheader="p",
        title="t",
        lede="l",
        rows=[("k", "v")],
        cta=('"><script>x</script>', 'javascript:alert(1)"><script>x</script>'),
    )
    assert "<script>x</script>" not in html_body


def test_no_style_block_and_no_class_attribute() -> None:
    """Email clients strip <style> blocks and class selectors unpredictably
    -- the whole point of this module is every rule inline."""
    for kind in EmailKind:
        html_body = render_email(kind, preheader="p", title="t", lede="l", rows=[("k", "v")])
        assert "<style" not in html_body
        assert re.search(r'class\s*=', html_body) is None


def test_no_inline_svg_shipped_in_a_real_email() -> None:
    """Outlook's desktop renderer does not support <svg> -- a broken icon in
    a completion email is worse than no icon (see the module docstring)."""
    for kind in EmailKind:
        html_body = render_email(kind, preheader="p", title="t", lede="l", rows=[("k", "v")])
        assert "<svg" not in html_body


def test_no_rows_and_no_cta_omits_the_highlight_card() -> None:
    html_body = render_email(EmailKind.TASK_COMPLETED, preheader="p", title="t", lede="l")
    assert "border-left:3px solid" not in html_body
