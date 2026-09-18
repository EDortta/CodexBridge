from __future__ import annotations

import asyncio
import hashlib
import html
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import aiosmtplib
from fastapi import APIRouter, BackgroundTasks, Form
from fastapi.responses import HTMLResponse

from gateway.app.core.config import settings
from gateway.app.core.users import lookup_user, set_user_password
from gateway.app.services.notify import _load_email_credentials

router = APIRouter()

_RESET_TTL = timedelta(minutes=30)
_RESET_TOKENS: dict[str, "ResetGrant"] = {}
_RESET_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class ResetGrant:
    user_id: str
    expires_at: datetime


def _page(*, title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{html.escape(title)} · CodexBridge</title>
  <style>
    :root {{ color-scheme: dark; }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; min-height:100vh; display:grid; place-items:center;
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:
        radial-gradient(circle at 20% 20%, rgba(28,210,187,.16), transparent 32rem),
        linear-gradient(145deg,#07111f,#0b1627 55%,#08131f);
      color:#eaf2f8; padding:24px;
    }}
    .card {{
      width:min(100%,460px); background:rgba(13,26,43,.92); border:1px solid rgba(147,197,253,.12);
      border-radius:20px; padding:32px; box-shadow:0 24px 80px rgba(0,0,0,.42);
    }}
    .brand {{ display:flex; align-items:center; gap:12px; margin-bottom:28px; font-weight:700; }}
    .mark {{
      width:42px; height:42px; border-radius:12px; display:grid; place-items:center;
      background:linear-gradient(135deg,#12bfa8,#4dd8c7); color:#07111f; font-weight:900; font-size:19px;
      box-shadow:0 8px 30px rgba(18,191,168,.24);
    }}
    h1 {{ margin:0 0 10px; font-size:26px; letter-spacing:-.02em; }}
    p {{ color:#aebdcb; line-height:1.55; margin:0 0 20px; }}
    label {{ display:block; margin:16px 0 7px; color:#d9e4ee; font-size:14px; font-weight:600; }}
    input {{
      width:100%; border:1px solid #31445a; border-radius:10px; background:#091624; color:white;
      padding:12px 14px; outline:none; font-size:15px;
    }}
    input:focus {{ border-color:#2ad0ba; box-shadow:0 0 0 3px rgba(42,208,186,.12); }}
    button {{
      width:100%; margin-top:20px; border:0; border-radius:10px; padding:12px 16px;
      background:#25cbb4; color:#04120f; font-weight:800; font-size:15px; cursor:pointer;
    }}
    button:hover {{ filter:brightness(1.06); }}
    a {{ color:#55dbc8; text-decoration:none; }}
    .muted {{ color:#8ea1b3; font-size:13px; margin-top:18px; }}
    .error {{ background:#34161b; border:1px solid #74313c; color:#ffbec8; padding:11px 12px; border-radius:9px; }}
    .success {{ background:#0d2c28; border:1px solid #216d61; color:#baf4e8; padding:11px 12px; border-radius:9px; }}
  </style>
</head>
<body>
  <main class="card">
    <div class="brand"><div class="mark">&lt;/&gt;</div><span>CodexBridge</span></div>
    {body}
  </main>
</body>
</html>"""
    )


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _purge_expired() -> None:
    now = datetime.now(timezone.utc)
    async with _RESET_LOCK:
        stale = [key for key, grant in _RESET_TOKENS.items() if grant.expires_at <= now]
        for key in stale:
            _RESET_TOKENS.pop(key, None)


async def _send_reset_email(email: str, token: str) -> None:
    if not settings.notification_email_config_file:
        return
    credentials = _load_email_credentials(settings.notification_email_config_file)
    reset_url = f"{settings.public_base_url.rstrip('/')}/oauth/password/reset?token={token}"

    message = EmailMessage()
    message["From"] = credentials.account
    message["To"] = email
    message["Subject"] = "CodexBridge · password recovery"
    message.set_content(
        "A password reset was requested for your CodexBridge account.\n\n"
        f"Open this link within 30 minutes:\n{reset_url}\n\n"
        "If you did not request this, ignore this message."
    )
    message.add_alternative(
        f"""<p>A password reset was requested for your CodexBridge account.</p>
<p><a href="{html.escape(reset_url)}">Reset your password</a></p>
<p>This link expires in 30 minutes and can be used once.</p>
<p>If you did not request this, ignore this message.</p>""",
        subtype="html",
    )
    await aiosmtplib.send(
        message,
        hostname=credentials.smtp_host,
        port=credentials.smtp_port,
        username=credentials.account,
        password=credentials.app_password,
        use_tls=credentials.smtp_port == 465,
        start_tls=credentials.smtp_port != 465,
    )


@router.get("/oauth/password/forgot", response_class=HTMLResponse)
async def forgot_password_form() -> HTMLResponse:
    return _page(
        title="Recover password",
        body="""
          <h1>Recover your password</h1>
          <p>Enter the email address associated with your CodexBridge account.</p>
          <form method="post" action="/oauth/password/forgot">
            <label for="email">Email</label>
            <input id="email" name="email" type="email" autocomplete="email" required />
            <button type="submit">Send recovery link</button>
          </form>
          <p class="muted"><a href="javascript:history.back()">Back to sign in</a></p>
        """,
    )


@router.post("/oauth/password/forgot", response_class=HTMLResponse)
async def forgot_password_submit(
    background_tasks: BackgroundTasks,
    email: str = Form(...),
) -> HTMLResponse:
    await _purge_expired()
    user = lookup_user(settings.user_registry_file, email.strip())
    if user is not None and user.enabled:
        token = secrets.token_urlsafe(32)
        async with _RESET_LOCK:
            _RESET_TOKENS[_token_key(token)] = ResetGrant(
                user_id=user.user_id,
                expires_at=datetime.now(timezone.utc) + _RESET_TTL,
            )
        background_tasks.add_task(_send_reset_email, user.email, token)

    # Deliberately identical whether the account exists or not.
    return _page(
        title="Check your email",
        body="""
          <h1>Check your email</h1>
          <div class="success">If that address belongs to an enabled CodexBridge account, a recovery link has been sent.</div>
          <p class="muted">The link expires in 30 minutes and can be used once.</p>
        """,
    )


@router.get("/oauth/password/reset", response_class=HTMLResponse)
async def reset_password_form(token: str) -> HTMLResponse:
    await _purge_expired()
    grant = _RESET_TOKENS.get(_token_key(token))
    if grant is None:
        return _page(
            title="Invalid recovery link",
            body="""
              <h1>Recovery link unavailable</h1>
              <div class="error">This recovery link is invalid, expired, or has already been used.</div>
              <p class="muted"><a href="/oauth/password/forgot">Request a new link</a></p>
            """,
        )
    safe_token = html.escape(token)
    return _page(
        title="Choose a new password",
        body=f"""
          <h1>Choose a new password</h1>
          <p>Use at least 12 characters.</p>
          <form method="post" action="/oauth/password/reset">
            <input type="hidden" name="token" value="{safe_token}" />
            <label for="password">New password</label>
            <input id="password" name="password" type="password" autocomplete="new-password" minlength="12" required />
            <label for="confirm_password">Confirm password</label>
            <input id="confirm_password" name="confirm_password" type="password" autocomplete="new-password" minlength="12" required />
            <button type="submit">Update password</button>
          </form>
        """,
    )


@router.post("/oauth/password/reset", response_class=HTMLResponse)
async def reset_password_submit(
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
) -> HTMLResponse:
    await _purge_expired()

    if len(password) < 12 or password != confirm_password:
        message = "Passwords must match and contain at least 12 characters."
        return _page(
            title="Choose a new password",
            body=f"""
              <h1>Choose a new password</h1>
              <div class="error">{html.escape(message)}</div>
              <p class="muted"><a href="/oauth/password/reset?token={html.escape(token)}">Try again</a></p>
            """,
        )

    key = _token_key(token)
    async with _RESET_LOCK:
        grant = _RESET_TOKENS.pop(key, None)

    if grant is None or grant.expires_at <= datetime.now(timezone.utc):
        return _page(
            title="Invalid recovery link",
            body="""
              <h1>Recovery link unavailable</h1>
              <div class="error">This recovery link is invalid, expired, or has already been used.</div>
              <p class="muted"><a href="/oauth/password/forgot">Request a new link</a></p>
            """,
        )

    try:
        await asyncio.to_thread(set_user_password, settings.user_registry_file, grant.user_id, password)
    except Exception:
        # Do not make a broken registry recoverable through repeated token replay.
        return _page(
            title="Password not changed",
            body="""
              <h1>Password not changed</h1>
              <div class="error">CodexBridge could not update the account safely. Request a new recovery link after the operator repairs the account registry.</div>
            """,
        )

    return _page(
        title="Password updated",
        body="""
          <h1>Password updated</h1>
          <div class="success">Your CodexBridge password has been changed.</div>
          <p class="muted">Return to the application that opened the authorization window and sign in again.</p>
        """,
    )
