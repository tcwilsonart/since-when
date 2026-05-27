"""
scheduler.py — Background overdue-check job for Since When.

Starts a single APScheduler BackgroundScheduler thread when the Streamlit
app launches. Uses a module-level singleton so Streamlit re-runs don't
spawn duplicate schedulers.

Check interval is controlled by the CHECK_INTERVAL_HOURS env var (default 1).

Notification logic:
  - Item must have expected_days set
  - Item must be overdue (elapsed > expected_days)
  - last_notified_at must be NULL or older than last_logged_at
    (i.e. don't re-notify until the user completes it and it goes overdue again)
"""

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

import database as db
import mailer

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _check_overdue_items() -> None:
    """Job function — runs on the scheduler thread."""
    if not mailer.is_configured():
        log.debug("Mailer not configured, skipping overdue check.")
        return

    try:
        dash = db.get_dashboard_data()
    except Exception as exc:
        log.error("Overdue check: failed to query DB: %s", exc)
        return

    import sys
    import pandas as pd

    for _, row in dash.iterrows():
        expected = row["expected_days"]
        if not expected or pd.isna(expected):
            continue
        if row["elapsed_seconds"] == sys.maxsize:
            continue

        elapsed_days = row["elapsed_seconds"] / 86400
        if elapsed_days <= expected:
            continue

        # Item is overdue — has it already been notified since last completion?
        last_notified = db.get_last_notified_at(int(row["id"]))
        last_logged_str = row["last_logged_at"]

        if last_notified is not None and last_logged_str is not None:
            from datetime import datetime
            last_logged = datetime.fromisoformat(str(last_logged_str))
            if last_notified >= last_logged:
                continue  # already notified for this overdue cycle

        days_overdue = elapsed_days - expected
        log.info("Sending overdue notification for '%s' (%.1fd overdue)", row["name"], days_overdue)

        try:
            mailer.send_overdue_email(row["name"], days_overdue)
            db.set_last_notified_at(int(row["id"]))
        except Exception as exc:
            log.error("Failed to send email for '%s': %s", row["name"], exc)


def start_scheduler() -> None:
    """
    Starts the background scheduler if it isn't already running.
    Safe to call multiple times — only one scheduler will ever run.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        return

    interval_hours = float(mailer._get("check_interval", "CHECK_INTERVAL_HOURS", "1"))

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _check_overdue_items,
        trigger="interval",
        hours=interval_hours,
        id="overdue_check",
        replace_existing=True,
    )
    _scheduler.start()
    log.info("Since When scheduler started (check every %.1fh)", interval_hours)
