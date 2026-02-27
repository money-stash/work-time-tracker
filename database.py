import sqlite3
import os
from datetime import datetime, date, timedelta
from contextlib import contextmanager

DB_FILE = "workbot.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS work_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                planned_minutes INTEGER NOT NULL DEFAULT 120,
                worked_minutes INTEGER NOT NULL DEFAULT 0,
                sessions_completed INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                finished_at TEXT,
                completed BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS work_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_day_id INTEGER NOT NULL,
                session_number INTEGER NOT NULL,
                duration_minutes INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY (work_day_id) REFERENCES work_days(id)
            )
        """)

def get_or_create_today() -> int:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM work_days WHERE date = ?", (today,)).fetchone()
        if row:
            return row["id"]
        from storage import get_setting
        planned = get_setting("work_duration_minutes")
        conn.execute(
            "INSERT INTO work_days (date, planned_minutes, started_at) VALUES (?, ?, ?)",
            (today, planned, datetime.now().isoformat())
        )
        return conn.execute("SELECT id FROM work_days WHERE date = ?", (today,)).fetchone()["id"]

def record_session_start(session_number: int, duration_minutes: int) -> int:
    day_id = get_or_create_today()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO work_sessions (work_day_id, session_number, duration_minutes, started_at) VALUES (?, ?, ?, ?)",
            (day_id, session_number, duration_minutes, datetime.now().isoformat())
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def record_session_end(session_id: int, duration_minutes: int):
    day_id = get_or_create_today()
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE work_sessions SET finished_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id)
        )
        conn.execute("""
            UPDATE work_days
            SET worked_minutes = worked_minutes + ?,
                sessions_completed = sessions_completed + 1
            WHERE date = ?
        """, (duration_minutes, today))

def record_day_complete(total_minutes: int):
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute("""
            UPDATE work_days
            SET completed = 1, finished_at = ?, worked_minutes = ?
            WHERE date = ?
        """, (datetime.now().isoformat(), total_minutes, today))

def get_stats_today() -> dict:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM work_days WHERE date = ?", (today,)).fetchone()
        if not row:
            return {"exists": False}
        sessions = conn.execute(
            "SELECT * FROM work_sessions WHERE work_day_id = ? ORDER BY session_number",
            (row["id"],)
        ).fetchall()
        return {
            "exists": True,
            "date": row["date"],
            "worked_minutes": row["worked_minutes"],
            "planned_minutes": row["planned_minutes"],
            "sessions_completed": row["sessions_completed"],
            "completed": bool(row["completed"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "sessions": [dict(s) for s in sessions]
        }

def get_stats_week() -> dict:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    return _get_stats_for_dates(days, "неделя")

def get_stats_month() -> dict:
    today = date.today()
    days = []
    d = today.replace(day=1)
    while d.month == today.month:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return _get_stats_for_dates(days, "месяц")

def get_stats_custom(days_back: int) -> dict:
    today = date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in range(days_back - 1, -1, -1)]
    return _get_stats_for_dates(days, f"последние {days_back} дней")

def _get_stats_for_dates(dates: list, period_name: str) -> dict:
    placeholders = ",".join("?" * len(dates))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM work_days WHERE date IN ({placeholders}) ORDER BY date",
            dates
        ).fetchall()
    
    rows = [dict(r) for r in rows]
    total_worked = sum(r["worked_minutes"] for r in rows)
    total_planned = sum(r["planned_minutes"] for r in rows)
    days_worked = len([r for r in rows if r["worked_minutes"] > 0])
    days_completed = len([r for r in rows if r["completed"]])
    total_sessions = sum(r["sessions_completed"] for r in rows)
    avg_per_day = total_worked / days_worked if days_worked > 0 else 0

    return {
        "period": period_name,
        "total_worked_minutes": total_worked,
        "total_planned_minutes": total_planned,
        "days_worked": days_worked,
        "days_completed": days_completed,
        "total_sessions": total_sessions,
        "avg_per_day_minutes": round(avg_per_day),
        "days": rows,
        "total_days": len(dates)
    }

def get_all_time_stats() -> dict:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_days,
                SUM(worked_minutes) as total_minutes,
                SUM(sessions_completed) as total_sessions,
                SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as completed_days,
                MIN(date) as first_day,
                MAX(date) as last_day
            FROM work_days WHERE worked_minutes > 0
        """).fetchone()
    return dict(row) if row else {}
