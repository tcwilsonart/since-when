"""
database.py — All SQLite operations for Since When tracker.
No Streamlit imports; fully testable in isolation.
"""

import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

# In Docker, set DATA_DIR=/data (mounted volume). Locally defaults to cwd.
DB_PATH = Path(os.environ.get("DATA_DIR", ".")) / "since_when.db"


# ── Connection ────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Returns a connection with row_factory and WAL mode for safe concurrent reads."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Creates tables and indexes if they don't exist. Safe to call every startup."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL UNIQUE,
                expected_days REAL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active        INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS logs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id   INTEGER NOT NULL REFERENCES items(id),
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                note      TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_logs_item_id   ON logs(item_id);
            CREATE INDEX IF NOT EXISTS idx_logs_logged_at ON logs(logged_at);

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # Migrate: add last_notified_at if upgrading from an older DB
        try:
            conn.execute("ALTER TABLE items ADD COLUMN last_notified_at TIMESTAMP")
        except sqlite3.OperationalError:
            pass  # column already exists


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    """Returns the value for a settings key, or default if not set."""
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Upserts a settings key-value pair."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ── Items CRUD ────────────────────────────────────────────────────────────────

def add_item(name: str, expected_days: float | None = None) -> int:
    """INSERT into items. Returns new item id. Raises IntegrityError on duplicate name."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO items (name, expected_days) VALUES (?, ?)",
            (name.strip(), expected_days),
        )
        return cur.lastrowid


def get_all_items() -> list[dict]:
    """All active items ordered by name."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, expected_days, created_at FROM items WHERE active=1 ORDER BY name ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def rename_item(item_id: int, new_name: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE items SET name=? WHERE id=?", (new_name.strip(), item_id))


def set_expected_days(item_id: int, expected_days: float | None) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE items SET expected_days=? WHERE id=?", (expected_days, item_id))


def soft_delete_item(item_id: int) -> None:
    """Soft-delete: sets active=0. Logs are retained in DB."""
    with get_connection() as conn:
        conn.execute("UPDATE items SET active=0 WHERE id=?", (item_id,))


def get_last_notified_at(item_id: int) -> datetime | None:
    """Returns the last_notified_at timestamp for an item, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_notified_at FROM items WHERE id=?", (item_id,)
        ).fetchone()
    if row is None or row["last_notified_at"] is None:
        return None
    return datetime.fromisoformat(row["last_notified_at"])


def set_last_notified_at(item_id: int) -> None:
    """Stamps last_notified_at to now for an item."""
    ts = datetime.now().isoformat(sep=" ", timespec="seconds")
    with get_connection() as conn:
        conn.execute("UPDATE items SET last_notified_at=? WHERE id=?", (ts, item_id))


# ── Logs CRUD ─────────────────────────────────────────────────────────────────

def log_item(item_id: int, note: str = "", logged_at: datetime | None = None) -> int:
    """INSERT into logs. logged_at defaults to datetime.now() (local time). Returns new log id."""
    ts = (logged_at or datetime.now()).isoformat(sep=" ", timespec="seconds")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO logs (item_id, logged_at, note) VALUES (?, ?, ?)",
            (item_id, ts, note),
        )
        return cur.lastrowid


def undo_log(log_id: int) -> None:
    """DELETE a log entry by id."""
    with get_connection() as conn:
        conn.execute("DELETE FROM logs WHERE id=?", (log_id,))


def update_log(log_id: int, new_date, new_note: str) -> None:
    """Update the date and note of a log entry. Preserves the original time-of-day."""
    with get_connection() as conn:
        row = conn.execute("SELECT logged_at FROM logs WHERE id=?", (log_id,)).fetchone()
        if row is None:
            return
        original_time = datetime.fromisoformat(row["logged_at"]).time()
        new_dt = datetime.combine(new_date, original_time)
        conn.execute(
            "UPDATE logs SET logged_at=?, note=? WHERE id=?",
            (new_dt.isoformat(sep=" ", timespec="seconds"), new_note.strip(), log_id),
        )


def get_last_log_id_for_item(item_id: int) -> int | None:
    """Returns the most recent log id for an item, or None if no logs."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM logs WHERE item_id=? ORDER BY logged_at DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        return row["id"] if row else None


def get_history(item_id: int | None = None) -> pd.DataFrame:
    """
    All logs ordered newest-first.
    Columns: log_id, item_name, logged_at, note
    Optionally filtered to a single item.
    """
    sql = """
        SELECT l.id AS log_id, i.name AS item_name, l.logged_at, l.note
        FROM logs l
        JOIN items i ON i.id = l.item_id
        {where}
        ORDER BY l.logged_at DESC
    """
    with get_connection() as conn:
        if item_id is not None:
            df = pd.read_sql_query(
                sql.format(where="WHERE l.item_id=?"), conn, params=(item_id,)
            )
        else:
            df = pd.read_sql_query(sql.format(where=""), conn)
    return df


# ── Dashboard Query ───────────────────────────────────────────────────────────

def get_dashboard_data() -> pd.DataFrame:
    """
    One row per active item with elapsed time computed in Python.
    Sorted by elapsed_seconds DESC (longest overdue / never-done first).
    Columns: id, name, expected_days, last_logged_at, elapsed_seconds, log_count
    """
    sql = """
        SELECT
            i.id,
            i.name,
            i.expected_days,
            MAX(l.logged_at)  AS last_logged_at,
            COUNT(l.id)       AS log_count
        FROM items i
        LEFT JOIN logs l ON l.item_id = i.id
        WHERE i.active = 1
        GROUP BY i.id, i.name, i.expected_days
        ORDER BY last_logged_at ASC
    """
    with get_connection() as conn:
        df = pd.read_sql_query(sql, conn)

    now = datetime.now()

    def compute_elapsed(ts_str):
        if ts_str is None or pd.isna(ts_str):
            return sys.maxsize
        last = datetime.fromisoformat(ts_str)
        return (now - last).total_seconds()

    df["elapsed_seconds"] = df["last_logged_at"].apply(compute_elapsed)

    def sort_key(row):
        elapsed_days = row["elapsed_seconds"] / 86400 if row["elapsed_seconds"] != sys.maxsize else None
        expected = row["expected_days"] if pd.notna(row["expected_days"]) else None
        if elapsed_days is None:          # never done → top
            return (0, 0.0)
        if expected:
            diff = elapsed_days - expected
            if diff > 0:                  # overdue → most overdue first
                return (1, -diff)
            else:                         # has target, not yet overdue → nearest deadline first
                return (2, expected - elapsed_days)  # days remaining; smaller = sooner
        return (3, -elapsed_days)         # no target → most elapsed first

    keys = df.apply(sort_key, axis=1)
    df["_g"] = keys.apply(lambda x: x[0])
    df["_v"] = keys.apply(lambda x: x[1])
    df = df.sort_values(["_g", "_v"]).drop(columns=["_g", "_v"]).reset_index(drop=True)
    return df


# ── Analytics Queries ─────────────────────────────────────────────────────────

def get_intervals_for_item(item_id: int) -> pd.DataFrame:
    """
    Returns DataFrame with columns [logged_at, interval_days].
    Needs ≥2 logs; returns empty DataFrame otherwise.
    """
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT logged_at FROM logs WHERE item_id=? ORDER BY logged_at ASC",
            conn,
            params=(item_id,),
        )
    if df.empty:
        return pd.DataFrame(columns=["logged_at", "interval_days"])

    df["logged_at"] = pd.to_datetime(df["logged_at"])
    df["interval_days"] = df["logged_at"].diff().dt.total_seconds() / 86400
    df = df.dropna(subset=["interval_days"]).reset_index(drop=True)
    return df


def get_all_logs_for_heatmap() -> pd.DataFrame:
    """
    Returns DataFrame with columns [date, item_name, count] for the activity heatmap.
    """
    sql = """
        SELECT DATE(l.logged_at) AS date, i.name AS item_name, COUNT(*) AS count
        FROM logs l
        JOIN items i ON i.id = l.item_id
        WHERE i.active = 1
        GROUP BY date, item_name
        ORDER BY date ASC
    """
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn)


def get_average_intervals() -> pd.DataFrame:
    """
    One row per active item with aggregate interval statistics.
    Columns: item_name, avg_days, min_days, max_days, longest_gap_days,
             most_recent_gap_days, log_count
    Only includes items with ≥2 logs.
    """
    items = get_all_items()
    records = []
    for item in items:
        df = get_intervals_for_item(item["id"])
        if df.empty:
            continue
        records.append(
            {
                "item_name": item["name"],
                "avg_days": df["interval_days"].mean(),
                "min_days": df["interval_days"].min(),
                "max_days": df["interval_days"].max(),
                "longest_gap_days": df["interval_days"].max(),
                "most_recent_gap_days": df["interval_days"].iloc[-1],
                "log_count": len(df) + 1,  # intervals = logs - 1
            }
        )
    if not records:
        return pd.DataFrame(
            columns=[
                "item_name", "avg_days", "min_days", "max_days",
                "longest_gap_days", "most_recent_gap_days", "log_count",
            ]
        )
    return pd.DataFrame(records)


def get_all_intervals() -> pd.DataFrame:
    """
    Intervals for every active item combined.
    Columns: [item_name, logged_at, interval_days]
    Only items with ≥2 logs are included.
    """
    items = get_all_items()
    frames = []
    for item in items:
        df = get_intervals_for_item(item["id"])
        if not df.empty:
            df["item_name"] = item["name"]
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["item_name", "logged_at", "interval_days"])
    return pd.concat(frames, ignore_index=True).sort_values("logged_at").reset_index(drop=True)


def get_ontime_stats() -> pd.DataFrame:
    """
    On-time vs late counts per item. Only items with expected_days set and ≥2 logs.
    Columns: [item_name, on_time, late, expected_days]
    """
    items = [i for i in get_all_items() if i["expected_days"]]
    records = []
    for item in items:
        df = get_intervals_for_item(item["id"])
        if df.empty:
            continue
        on_time = int((df["interval_days"] <= item["expected_days"]).sum())
        late = int((df["interval_days"] > item["expected_days"]).sum())
        records.append({
            "item_name": item["name"],
            "on_time": on_time,
            "late": late,
            "expected_days": item["expected_days"],
        })
    if not records:
        return pd.DataFrame(columns=["item_name", "on_time", "late", "expected_days"])
    return pd.DataFrame(records)


def get_logs_per_month() -> pd.DataFrame:
    """
    Total log entries per calendar month across all active items.
    Columns: [month, count]  (month formatted as 'YYYY-MM')
    """
    sql = """
        SELECT strftime('%Y-%m', l.logged_at) AS month, COUNT(*) AS count
        FROM logs l
        JOIN items i ON i.id = l.item_id
        WHERE i.active = 1
        GROUP BY month
        ORDER BY month ASC
    """
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn)
