"""Outbound email via SMTP.

Configure with environment variables:
  SMTP_HOST      e.g. smtp.gmail.com  (required to enable email)
  SMTP_PORT      default 587
  SMTP_USER      your login address
  SMTP_PASSWORD  your SMTP password / app-password
  SMTP_FROM      sender address (defaults to SMTP_USER)
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("fce_trainer")


def _smtp_configured() -> bool:
    return bool((os.environ.get("SMTP_HOST") or "").strip())


def send_reset_email(to_email: str, reset_url: str) -> bool:
    """Send a password-reset email.  Returns True on success, False on failure."""
    if not _smtp_configured():
        logger.warning(
            "SMTP not configured — password reset email NOT sent to %s. "
            "Set SMTP_HOST / SMTP_USER / SMTP_PASSWORD in your .env.",
            to_email,
        )
        return False

    host = (os.environ.get("SMTP_HOST") or "").strip()
    port = int((os.environ.get("SMTP_PORT") or "587").strip())
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = (os.environ.get("SMTP_PASSWORD") or "").strip()
    from_addr = (os.environ.get("SMTP_FROM") or user).strip()

    subject = "Reset your FCE Trainer password"
    text_body = (
        f"Hi,\n\n"
        f"Someone (hopefully you) requested a password reset for your FCE Trainer account.\n\n"
        f"Click the link below to choose a new password. The link expires in 1 hour.\n\n"
        f"{reset_url}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"— FCE Trainer"
    )
    html_body = f"""<html><body style="font-family:sans-serif;color:#333;max-width:480px">
<p>Hi,</p>
<p>Someone (hopefully you) requested a password reset for your <strong>FCE Trainer</strong> account.</p>
<p>
  <a href="{reset_url}"
     style="display:inline-block;padding:0.6rem 1.4rem;background:#0066cc;color:#fff;
            border-radius:6px;text-decoration:none;font-weight:600">
    Reset my password
  </a>
</p>
<p style="color:#666;font-size:0.9rem">Link expires in 1 hour.<br>
If you didn't request this, you can safely ignore this email.</p>
<p style="color:#999;font-size:0.85rem">— FCE Trainer</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_email], msg.as_string())
        logger.info("Password reset email sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send password reset email to %s", to_email)
        return False
