"""
mailer.py — Email notifications for Since When.

Settings are read from the database first (configured via the UI),
falling back to environment variables for Docker / headless deployments.

DB key          Env var fallback       Description
──────────────  ─────────────────────  ──────────────────────────────
smtp_host       SMTP_HOST              Default: smtp.gmail.com
smtp_port       SMTP_PORT              Default: 587
smtp_user       SMTP_USER              Gmail address used to send
smtp_password   SMTP_PASSWORD          Gmail App Password
notify_emails   NOTIFY_EMAIL           Comma-separated recipients
check_interval  CHECK_INTERVAL_HOURS   Scheduler interval in hours
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _get(db_key: str, env_key: str, default: str = "") -> str:
    """Read from DB settings first, then env var, then default."""
    try:
        import database as db
        val = db.get_setting(db_key)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(env_key, default)


def get_all_settings() -> dict:
    """Returns the full current config as a dict (for the UI)."""
    return {
        "smtp_host":      _get("smtp_host",     "SMTP_HOST",             "smtp.gmail.com"),
        "smtp_port":      _get("smtp_port",     "SMTP_PORT",             "587"),
        "smtp_user":      _get("smtp_user",     "SMTP_USER",             ""),
        "smtp_password":  _get("smtp_password", "SMTP_PASSWORD",         ""),
        "notify_emails":  _get("notify_emails", "NOTIFY_EMAIL",          ""),
        "check_interval": _get("check_interval","CHECK_INTERVAL_HOURS",  "1"),
    }


def is_configured() -> bool:
    """Returns True if the minimum SMTP credentials are present."""
    cfg = get_all_settings()
    return bool(cfg["smtp_user"] and cfg["smtp_password"])


def _recipient_list(raw: str, fallback: str) -> list[str]:
    """Parses a comma-separated email string into a list."""
    source = raw or fallback
    return [e.strip() for e in source.split(",") if e.strip()]


def send_overdue_email(item_name: str, days_overdue: float) -> None:
    """
    Sends a single overdue notification to all configured recipients.
    Silently does nothing if SMTP credentials are not configured.
    """
    if not is_configured():
        return

    cfg = get_all_settings()
    smtp_host = cfg["smtp_host"]
    smtp_port = int(cfg["smtp_port"])
    smtp_user = cfg["smtp_user"]
    smtp_password = cfg["smtp_password"]
    recipients = _recipient_list(cfg["notify_emails"], smtp_user)

    days_str = f"{days_overdue:.1f}".rstrip("0").rstrip(".")
    subject = f"⏱️ Since When: {item_name} is overdue by {days_str}d"

    text_body = (
        f"{item_name} is overdue by {days_str} day(s).\n\n"
        f"Open Since When to log it when done."
    )
    html_body = f"""
    <html><body style="font-family: sans-serif; color: #222;">
      <h2 style="color: #e74c3c;">⏱️ {item_name} is overdue</h2>
      <p>This task is <strong>{days_str} day(s)</strong> past its target.</p>
      <p style="color: #888; font-size: 0.9em;">
        You'll receive this reminder once per overdue cycle —
        it won't repeat until you log a completion and the item becomes overdue again.
      </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, recipients, msg.as_string())


def send_test_email() -> None:
    """Sends a test email to verify the current configuration."""
    cfg = get_all_settings()
    smtp_user = cfg["smtp_user"]
    recipients = _recipient_list(cfg["notify_emails"], smtp_user)
    smtp_port = int(cfg["smtp_port"])

    subject = "⏱️ Since When — test email"

    text_body = (
        "Your email notifications are configured correctly. "
        "This is what the real thing will look like:\n\n"
        "---\n"
        "Wash dog is overdue by 3 day(s).\n\n"
        "Open Since When to log it when done."
    )
    html_body = """
    <html><body style="font-family: sans-serif; color: #222;">
      <p>Your email notifications are configured correctly.
      This is what the real thing will look like:</p>
      <hr style="border: none; border-top: 1px solid #ddd; margin: 16px 0;">
      <h2 style="color: #e74c3c;">⏱️ Wash dog is overdue</h2>
      <p>This task is <strong>3 day(s)</strong> past its target.</p>
      <p style="color: #888; font-size: 0.9em;">
        You'll receive this reminder once per overdue cycle —
        it won't repeat until you log a completion and the item becomes overdue again.
      </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(cfg["smtp_host"], smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, cfg["smtp_password"])
        server.sendmail(smtp_user, recipients, msg.as_string())
