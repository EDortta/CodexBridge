"""Branded HTML for every CodexBridge transactional email.

One skeleton -- hidden preheader, top accent bar, dark sidebar, eyebrow row
(uppercase label + colored dot + pill badge), title + lede, an optional
highlight card with a colored left border, signature block, footer -- reused
across every notification kind below (`EmailKind`). Only the badge label, the
accent color and the body fields change. This mirrors the pattern already in
production for other projects in this ecosystem (ZeeCred/DryWall's
`assets/email-template.html`): table-based layout, `role="presentation"`,
every rule inline, because email clients strip `<style>` blocks and
`class="..."` selectors unpredictably.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #70. Currently only
`notify.py` calls `render_email`, for the one kind it needs
(`TASK_COMPLETED`/`TASK_FAILED` on a finished task) -- the other kinds exist
so a later notification path (approval-pending, a deploy, a test run) reuses
this module instead of inventing a second template.

No inline SVG here on purpose, unlike the design canvas mock this was
approved from: Outlook's desktop renderer (Word's engine, not a browser) does
not support `<svg>` at all, and a broken icon in a completion email is worse
than no icon. The color and the text of the pill badge already carry the
distinction; nothing is lost by leaving the glyph out of the shipped email.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_INK = "#1E1B2E"
_MUTED = "#5B5A73"
_FAINT = "#9695AC"
_LINE = "#E7E6F1"
_PAGE_BG = "#EEEDF7"
_CARD_BG = "#FFFFFF"
_SIDEBAR = "#151129"
_SOFT_TINT = "#F7F7FC"


class EmailKind(str, Enum):
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    APPROVAL_NEEDED = "approval_needed"
    URGENT = "urgent"
    EMERGENCY = "emergency"
    DEPLOYMENT_NOTICE = "deployment_notice"
    TEST_ROUND = "test_round"


@dataclass(frozen=True)
class _Style:
    badge: str
    accent: str
    tint: str


# Approved on the design canvas (2026-08-30): each kind keeps a hue no other
# kind shares, so two emails never read as the same severity at a glance.
_STYLES: dict[EmailKind, _Style] = {
    EmailKind.TASK_COMPLETED: _Style("Tarefa concluída", "#059669", "#E1F5EC"),
    EmailKind.TASK_FAILED: _Style("Tarefa falhou", "#9F1239", "#FBE3E9"),
    EmailKind.APPROVAL_NEEDED: _Style("Ação necessária", "#7C3AED", "#EDE6FC"),
    EmailKind.URGENT: _Style("Urgente", "#EA580C", "#FCE7D9"),
    EmailKind.EMERGENCY: _Style("Emergência", "#DC2626", "#FBDCDC"),
    EmailKind.DEPLOYMENT_NOTICE: _Style("Implantação", "#0E7490", "#DAF0F4"),
    EmailKind.TEST_ROUND: _Style("Rodada de testes", "#64748B", "#E7E9EE"),
}


def subject_prefix(kind: EmailKind) -> str:
    """The bracketed tag this ecosystem's other notifications already use."""
    return f"[CodexBridge] {_STYLES[kind].badge}"


def _esc(value: str) -> str:
    return html.escape(str(value), quote=False)


def _kv_rows(rows: Sequence[tuple[str, str]]) -> str:
    out = []
    for i, (key, value) in enumerate(rows):
        top = f"border-top:1px solid {_LINE};" if i > 0 else ""
        pad = "0 0 9px 0" if i == 0 else "9px 0"
        out.append(
            f'<tr>'
            f'<td style="padding:{pad};{top}" width="120">'
            f'<span style="font:600 12px/1.5 {_FONT};color:{_MUTED};">{_esc(key)}</span>'
            f'</td>'
            f'<td style="padding:{pad};{top}">'
            f'<span style="font:500 13px/1.5 {_FONT};color:{_INK};">{_esc(value)}</span>'
            f'</td>'
            f'</tr>'
        )
    return "".join(out)


def _cta_button(label: str, url: str, accent: str) -> str:
    href = html.escape(url, quote=True)
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:12px;">'
        f'<tr><td style="border-radius:7px;background:{accent};">'
        f'<a href="{href}" style="display:inline-block;padding:10px 20px;'
        f'font:700 13px/1 {_FONT};color:#ffffff;text-decoration:none;border-radius:7px;">'
        f'{_esc(label)}</a></td></tr></table>'
    )


def render_email(
    kind: EmailKind,
    *,
    preheader: str,
    title: str,
    lede: str,
    rows: Sequence[tuple[str, str]] = (),
    sign_line1: str = "Notificação automática de",
    sign_line2: str = "CodexBridge",
    cta: tuple[str, str] | None = None,
) -> str:
    """Render one full HTML document for `kind`. Every text argument is

    plain text and is HTML-escaped here -- callers must never pre-escape or
    pass markup, including for values sourced from a resolved issue (that
    text is untrusted; see `agent/codex_bridge_agent/instructions.py`) or
    from a task's own error message.
    """
    style = _STYLES[kind]
    rows_html = _kv_rows(rows)
    card_html = ""
    if rows or cta:
        cta_html = _cta_button(cta[0], cta[1], style.accent) if cta else ""
        card_html = f'''
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_SOFT_TINT};border-radius:8px;margin:0 0 24px 0;">
          <tr><td style="border-left:3px solid {style.accent};border-radius:8px;padding:16px 20px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows_html}</table>
            {cta_html}
          </td></tr>
        </table>'''

    return f'''<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{_PAGE_BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;color:{_PAGE_BG};">{_esc(preheader)}</div>
<div style="background:{_PAGE_BG};padding:36px 20px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" align="center" style="width:600px;max-width:600px;margin:0 auto;background:{_CARD_BG};border-radius:14px;overflow:hidden;">
    <tr><td colspan="2" style="height:4px;line-height:4px;font-size:0;background:{style.accent};">&nbsp;</td></tr>
    <tr>
      <td valign="top" width="10" style="width:10px;background:{_SIDEBAR};">&nbsp;</td>
      <td valign="top" style="padding:34px 38px 30px 34px;">

        <table role="presentation" cellpadding="0" cellspacing="0"><tr>
          <td style="font:800 11px/1 {_FONT};letter-spacing:.09em;color:{_FAINT};text-transform:uppercase;">CODEXBRIDGE</td>
          <td style="padding:0 8px;">
            <table role="presentation" cellpadding="0" cellspacing="0"><tr><td width="4" height="4" style="width:4px;height:4px;line-height:4px;font-size:0;background:{style.accent};border-radius:2px;">&nbsp;</td></tr></table>
          </td>
          <td>
            <table role="presentation" cellpadding="0" cellspacing="0" style="background:{style.tint};border-radius:999px;">
              <tr><td style="padding:4px 11px;font:800 10.5px/1 {_FONT};letter-spacing:.05em;color:{style.accent};text-transform:uppercase;">{_esc(style.badge)}</td></tr>
            </table>
          </td>
        </tr></table>

        <h1 style="margin:17px 0 8px 0;font:700 21px/1.35 {_FONT};color:{_INK};">{_esc(title)}</h1>
        <p style="margin:0 0 22px 0;font:400 14.5px/1.65 {_FONT};color:{_MUTED};">{_esc(lede)}</p>
        {card_html}
        <p style="margin:0 0 4px 0;font:400 13.5px/1.6 {_FONT};color:{_MUTED};">{_esc(sign_line1)}</p>
        <p style="margin:0 0 22px 0;font:600 13.5px/1.6 {_FONT};color:{_INK};">{_esc(sign_line2)}</p>

        <div style="border-top:1px solid {_LINE};margin:0 0 20px 0;"></div>

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td>
            <span style="font:800 13px/1 {_FONT};color:{_INK};">Codex<span style="color:{style.accent};">Bridge</span></span>
            <div style="margin-top:4px;font:400 11.5px/1.5 {_FONT};color:{_FAINT};">Ponte entre ChatGPT/Claude e seus repositórios locais.</div>
          </td>
        </tr></table>

      </td>
    </tr>
  </table>
</div>
</body>
</html>
'''
