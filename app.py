"""
app.py — Since When: personal recurring-task tracker.
Run with: streamlit run app.py
"""

import sys
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import charts
import database as db
import mailer
import scheduler

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Since When",
    page_icon="⏱️",
    layout="wide",
)

# ── DB init & background scheduler ───────────────────────────────────────────

db.init_db()
scheduler.start_scheduler()  # no-op if already running

# ── Session state ─────────────────────────────────────────────────────────────

if "undo_info" not in st.session_state:
    st.session_state.undo_info = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_elapsed(seconds: float) -> str:
    """Convert elapsed seconds to a human-readable string."""
    if seconds == sys.maxsize:
        return "Never"
    seconds = int(seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins}m ago"
    if seconds < 86400:
        hours, rem = divmod(seconds, 3600)
        mins = rem // 60
        return f"{hours}h {mins}m ago"
    days, rem = divmod(seconds, 86400)
    hours = rem // 3600
    day_str = "1 day" if days == 1 else f"{days} days"
    return f"{day_str} {hours}h ago" if hours else f"{day_str} ago"


def status_emoji(row: pd.Series) -> str:
    """Returns an emoji reflecting the overdue status of an item."""
    if row["elapsed_seconds"] == sys.maxsize:
        return "🔵"  # never done
    elapsed_days = row["elapsed_seconds"] / 86400
    expected = row["expected_days"]
    if expected is None or pd.isna(expected):
        # No target set — warn after 14 days of inactivity
        return "🟡" if elapsed_days > 14 else "🟢"
    if elapsed_days <= expected:
        return "🟢"
    overdue_by = elapsed_days - expected
    if overdue_by > expected * 0.5:
        return "🔴"
    return "🟡"


def _cell(label: str, value: str) -> None:
    """Renders a labelled value at consistent paragraph font size (avoids st.metric's large font)."""
    st.caption(label)
    st.markdown(f"**{value}**")


def format_next_due(row: pd.Series) -> str:
    """Returns a human-readable next-due string, or '—' if no target is set."""
    expected = row["expected_days"]
    if not expected or pd.isna(expected):
        return "—"
    if row["elapsed_seconds"] == sys.maxsize or row["last_logged_at"] is None:
        return "—"
    last = datetime.fromisoformat(str(row["last_logged_at"]))
    due = last + timedelta(days=float(expected))
    days_until = (due.date() - datetime.now().date()).days
    date_str = due.strftime("%b %d")
    if days_until < 0:
        return f"{date_str} ({abs(days_until)}d overdue)"
    if days_until == 0:
        return f"{date_str} (today)"
    if days_until == 1:
        return f"{date_str} (tomorrow)"
    return f"{date_str} (in {days_until}d)"


def render_dashboard_row(row: pd.Series) -> None:
    """Renders one item card on the Dashboard tab."""
    prefix = status_emoji(row)
    elapsed_str = format_elapsed(row["elapsed_seconds"])

    col_name, col_due, col_elapsed, col_count, col_done, col_custom = st.columns([3, 2, 2, 1, 1, 1])

    with col_name:
        st.markdown(
            f'<p style="font-size:1.4em; font-weight:400; margin:0">{prefix} {row["name"]}</p>',
            unsafe_allow_html=True,
        )
        expected = row["expected_days"]
        if expected and not pd.isna(expected):
            st.caption(f"Every {expected:.0f}d")
        elif row["elapsed_seconds"] == sys.maxsize:
            st.caption("Never logged")

    with col_due:
        _cell("Next due", format_next_due(row))

    with col_elapsed:
        _cell("Last done", elapsed_str)

    with col_count:
        _cell("Times", str(int(row["log_count"])))

    with col_done:
        if st.button("Done! ✓", key=f"done_{row['id']}", type="primary", use_container_width=True):
            log_id = db.log_item(int(row["id"]))
            now = datetime.now()
            st.session_state.undo_info = {
                "log_id": log_id,
                "item_name": row["name"],
                "logged_at_str": now.strftime("%b %d, %H:%M"),
                "expires_at": now + timedelta(seconds=30),
            }
            st.rerun()

    with col_custom:
        with st.popover("📅", use_container_width=True, help="Log a past date"):
            st.markdown(f"**{row['name']}** — log a past date")
            custom_date = st.date_input(
                "Date",
                value=datetime.now().date(),
                max_value=datetime.now().date(),
                key=f"cdate_{row['id']}",
            )
            if st.button("Log this date", key=f"log_custom_{row['id']}", type="primary"):
                custom_dt = datetime.combine(custom_date, datetime.now().time().replace(second=0, microsecond=0))
                if custom_dt > datetime.now():
                    st.error("Can't log a future date.")
                else:
                    log_id = db.log_item(int(row["id"]), logged_at=custom_dt)
                    st.session_state.undo_info = {
                        "log_id": log_id,
                        "item_name": row["name"],
                        "logged_at_str": custom_dt.strftime("%b %d %Y, %H:%M"),
                        "expires_at": datetime.now() + timedelta(seconds=30),
                    }
                    st.rerun()

    st.divider()


# ── Tabs ──────────────────────────────────────────────────────────────────────

st.title("⏱️ Since When")
st.caption("Track recurring tasks and see how long it's been.")

tab_dashboard, tab_manage, tab_history, tab_analytics, tab_notify = st.tabs(
    ["📋 Dashboard", "⚙️ Manage Items", "📜 History", "📊 Analytics", "🔔 Notifications"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Dashboard
# ══════════════════════════════════════════════════════════════════════════════

with tab_dashboard:
    # Undo banner
    if st.session_state.undo_info:
        info = st.session_state.undo_info
        if datetime.now() < info["expires_at"]:
            col_msg, col_undo = st.columns([7, 1])
            with col_msg:
                st.success(f"✅ Logged **{info['item_name']}** at {info['logged_at_str']}")
            with col_undo:
                if st.button("Undo", key="undo_btn"):
                    db.undo_log(info["log_id"])
                    st.session_state.undo_info = None
                    st.rerun()
        else:
            st.session_state.undo_info = None

    dash_df = db.get_dashboard_data()

    if dash_df.empty:
        st.info("No items tracked yet. Go to **⚙️ Manage Items** to add some.")
    else:
        # Summary counts
        total = len(dash_df)
        overdue = sum(
            1 for _, r in dash_df.iterrows()
            if r["expected_days"]
            and not pd.isna(r["expected_days"])
            and r["elapsed_seconds"] != sys.maxsize
            and r["elapsed_seconds"] / 86400 > r["expected_days"]
        )
        never = sum(1 for _, r in dash_df.iterrows() if r["elapsed_seconds"] == sys.maxsize)

        m1, m2, m3 = st.columns(3)
        m1.metric("Total items", total)
        m2.metric("Overdue", overdue, delta=None)
        m3.metric("Never done", never)

        st.markdown("---")

        for _, row in dash_df.iterrows():
            render_dashboard_row(row)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Manage Items
# ══════════════════════════════════════════════════════════════════════════════

with tab_manage:
    st.header("Manage Items")

    # ── Add new item ──────────────────────────────────────────────────────────
    with st.expander("➕ Add New Item", expanded=True):
        col_name, col_freq, col_add = st.columns([3, 2, 1])
        with col_name:
            new_name = st.text_input("Item name", placeholder="e.g. Wash dog")
        with col_freq:
            freq_input = st.number_input(
                "Must do every N days",
                min_value=0.0,
                value=0.0,
                step=1.0,
                format="%.0f",
                help="Leave at 0 to set no target. Example: 30 means 'every 30 days max'.",
            )
        with col_add:
            st.write("")  # vertical alignment spacer
            st.write("")
            if st.button("Add Item", type="primary"):
                if not new_name.strip():
                    st.error("Item name cannot be empty.")
                else:
                    try:
                        db.add_item(
                            new_name.strip(),
                            expected_days=freq_input if freq_input > 0 else None,
                        )
                        st.success(f"Added **{new_name.strip()}**")
                        st.rerun()
                    except Exception:
                        st.error(f"**{new_name.strip()}** already exists.")

    # ── Edit existing items ───────────────────────────────────────────────────
    st.subheader("Existing Items")
    items = db.get_all_items()

    if not items:
        st.info("No items yet. Add one above.")
    else:
        for item in items:
            with st.expander(f"**{item['name']}**"):
                col_rename, col_freq2, col_del = st.columns([3, 2, 1])

                with col_rename:
                    new_name_val = st.text_input(
                        "Name", value=item["name"], key=f"rename_{item['id']}"
                    )
                    if st.button("Save name", key=f"save_rename_{item['id']}"):
                        if new_name_val.strip():
                            db.rename_item(item["id"], new_name_val.strip())
                            st.rerun()
                        else:
                            st.error("Name cannot be empty.")

                with col_freq2:
                    current_freq = item["expected_days"] or 0.0
                    new_freq = st.number_input(
                        "Must do every N days",
                        value=float(current_freq),
                        min_value=0.0,
                        step=1.0,
                        format="%.0f",
                        key=f"freq_{item['id']}",
                        help="Set to 0 to remove the target.",
                    )
                    if st.button("Save target", key=f"save_freq_{item['id']}"):
                        db.set_expected_days(
                            item["id"],
                            new_freq if new_freq > 0 else None,
                        )
                        st.rerun()

                with col_del:
                    st.write("")
                    if st.button(
                        "Delete", key=f"del_{item['id']}", type="secondary"
                    ):
                        st.session_state[f"confirm_del_{item['id']}"] = True

                    if st.session_state.get(f"confirm_del_{item['id']}"):
                        st.warning("This hides the item (history is kept). Sure?")
                        col_yes, col_no = st.columns(2)
                        with col_yes:
                            if st.button("Yes, delete", key=f"confirm_{item['id']}"):
                                db.soft_delete_item(item["id"])
                                st.session_state.pop(f"confirm_del_{item['id']}", None)
                                st.rerun()
                        with col_no:
                            if st.button("Cancel", key=f"cancel_del_{item['id']}"):
                                st.session_state.pop(f"confirm_del_{item['id']}", None)
                                st.rerun()

                # ── Log a past entry ──────────────────────────────────────────
                st.markdown("**Log a past entry**")
                st.caption("Use this to record something that happened before today.")
                col_pd, col_pb = st.columns([3, 1])
                with col_pd:
                    past_date = st.date_input(
                        "Date",
                        value=datetime.now().date(),
                        max_value=datetime.now().date(),
                        key=f"past_date_{item['id']}",
                    )
                with col_pb:
                    st.write("")
                    st.write("")
                    if st.button("Log it", key=f"log_past_{item['id']}", type="primary"):
                        past_dt = datetime.combine(past_date, datetime.now().time().replace(second=0, microsecond=0))
                        if past_dt > datetime.now():
                            st.error("Can't log a future date.")
                        else:
                            db.log_item(item["id"], logged_at=past_dt)
                            st.success(f"Logged {past_dt.strftime('%b %d %Y')}")
                            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — History
# ══════════════════════════════════════════════════════════════════════════════

with tab_history:
    st.header("Log History")

    items = db.get_all_items()
    item_options = {"All items": None} | {i["name"]: i["id"] for i in items}
    selected_label = st.selectbox("Filter by item", list(item_options.keys()))
    selected_id = item_options[selected_label]

    history_df = db.get_history(item_id=selected_id)

    if history_df.empty:
        st.info("No logs yet — go to the Dashboard and press Done! on something.")
    else:
        n = len(history_df)
        st.caption(f"{n} log entr{'y' if n == 1 else 'ies'}")

        # Header row
        hc1, hc2, hc3, hc4, hc5 = st.columns([1, 1, 3, 3, 4])
        hc3.markdown("**Item**")
        hc4.markdown("**When**")
        hc5.markdown("**Note**")
        st.divider()

        for _, row in history_df.iterrows():
            log_id = int(row["log_id"])
            logged_at_dt = pd.to_datetime(row["logged_at"])
            logged_at_str = logged_at_dt.strftime("%Y-%m-%d")

            c1, c2, c3, c4, c5 = st.columns([1, 1, 3, 3, 4])
            if c1.button("🗑️", key=f"del_log_{log_id}", help="Delete this entry"):
                db.undo_log(log_id)
                st.rerun()
            with c2.popover("✏️", help="Edit this entry"):
                st.markdown(f"**Edit entry** — {row['item_name']}")
                edit_date = st.date_input(
                    "Date",
                    value=logged_at_dt.date(),
                    max_value=datetime.now().date(),
                    key=f"edit_date_{log_id}",
                )
                edit_note = st.text_input(
                    "Note",
                    value=row["note"] or "",
                    key=f"edit_note_{log_id}",
                )
                if st.button("Save", key=f"save_log_{log_id}", type="primary"):
                    db.update_log(log_id, edit_date, edit_note)
                    st.rerun()
            c3.write(row["item_name"])
            c4.write(logged_at_str)
            c5.write(row["note"] or "")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Analytics
# ══════════════════════════════════════════════════════════════════════════════

with tab_analytics:
    st.header("Analytics")

    items = db.get_all_items()

    if not items:
        st.info("Add items and start logging to see analytics here.")
    else:
        # ── Section A: Interval timeline ──────────────────────────────────────
        st.subheader("Interval Timeline")
        st.caption("How many days passed between each completion.")

        ALL_LABEL = "— All items —"
        item_choices = [ALL_LABEL] + [i["name"] for i in items]
        selected_item_name = st.selectbox(
            "Select item",
            item_choices,
            key="analytics_item_select",
        )

        if selected_item_name == ALL_LABEL:
            all_intervals_df = db.get_all_intervals()
            fig_timeline = charts.chart_interval_timeline_all(all_intervals_df)
        else:
            selected_item = next(i for i in items if i["name"] == selected_item_name)
            interval_df = db.get_intervals_for_item(selected_item["id"])
            fig_timeline = charts.chart_interval_timeline(
                interval_df,
                selected_item_name,
                expected_days=selected_item["expected_days"],
            )

        st.plotly_chart(fig_timeline, use_container_width=True, key="chart_timeline")

        st.divider()

        # ── Section B: On time vs late ────────────────────────────────────────
        st.subheader("On Time vs Late")
        st.caption("For items with a target set — how often each was completed within the deadline.")

        ontime_df = db.get_ontime_stats()
        st.plotly_chart(
            charts.chart_ontime_vs_late(ontime_df),
            use_container_width=True,
            key="chart_ontime",
        )

        st.divider()

        # ── Section C: Completions per month ─────────────────────────────────
        st.subheader("Completions per Month")
        st.caption("Total tasks logged across all items each month.")

        month_df = db.get_logs_per_month()
        st.plotly_chart(
            charts.chart_tasks_per_month(month_df),
            use_container_width=True,
            key="chart_monthly",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Notifications
# ══════════════════════════════════════════════════════════════════════════════

with tab_notify:
    st.header("Notifications")
    st.caption("Email alerts when a task becomes overdue. Settings are saved to the database.")

    cfg = mailer.get_all_settings()

    # ── SMTP ──────────────────────────────────────────────────────────────────
    st.subheader("SMTP (outgoing mail)")
    col_host, col_port = st.columns([3, 1])
    with col_host:
        smtp_host = st.text_input("SMTP host", value=cfg["smtp_host"], placeholder="smtp.gmail.com")
    with col_port:
        smtp_port = st.text_input("Port", value=cfg["smtp_port"], placeholder="587")

    smtp_user = st.text_input("From address", value=cfg["smtp_user"], placeholder="you@gmail.com")
    st.caption(
        "Use an App Password, not your login password. "
        "Generate one at https://myaccount.google.com/apppasswords"
    )
    smtp_password = st.text_input(
        "App password",
        value=cfg["smtp_password"],
        type="password",
        placeholder="Gmail App Password",
    )

    if st.button("Save SMTP settings", type="primary"):
        db.set_setting("smtp_host",     smtp_host.strip())
        db.set_setting("smtp_port",     smtp_port.strip())
        db.set_setting("smtp_user",     smtp_user.strip())
        db.set_setting("smtp_password", smtp_password)
        st.success("SMTP settings saved.")

    st.divider()

    # ── Recipients ────────────────────────────────────────────────────────────
    st.subheader("Recipients")
    notify_emails = st.text_input(
        "Notify email(s)",
        value=cfg["notify_emails"],
        placeholder="you@gmail.com, partner@gmail.com",
        help="Comma-separated. Defaults to the From address if left blank.",
    )

    if st.button("Save recipients", type="primary"):
        db.set_setting("notify_emails", notify_emails.strip())
        st.success("Recipients saved.")

    st.divider()

    # ── Schedule ──────────────────────────────────────────────────────────────
    st.subheader("Check schedule")
    check_interval = st.number_input(
        "Check for overdue items every N hours",
        value=float(cfg["check_interval"]),
        min_value=0.25,
        step=0.25,
        format="%.2f",
        help="Changes take effect after restarting the app.",
    )

    if st.button("Save schedule", type="primary"):
        db.set_setting("check_interval", str(check_interval))
        st.info(f"Schedule saved. Restart the app to apply the new {check_interval}h interval.")

    st.divider()

    # ── Test ──────────────────────────────────────────────────────────────────
    st.subheader("Test")
    if not mailer.is_configured():
        st.warning("Enter and save SMTP credentials above before sending a test.")
    else:
        recipients_display = cfg["notify_emails"] or cfg["smtp_user"]
        st.caption(f"Will send to: **{recipients_display}**")
        if st.button("Send test email"):
            try:
                mailer.send_test_email()
                st.success("Test email sent — check your inbox.")
            except Exception as exc:
                st.error(f"Failed: {exc}")
