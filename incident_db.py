
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "print_guardian.db"


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with closing(connect()) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                mode TEXT NOT NULL,
                failure_type TEXT NOT NULL,
                risk_score REAL NOT NULL,
                camera_confidence REAL NOT NULL,
                filament_runout INTEGER NOT NULL,
                pause_success INTEGER NOT NULL,
                pause_message TEXT NOT NULL,
                notification_sent INTEGER NOT NULL
            )
        """)
        connection.commit()


def save_incident(
    mode,
    failure_type,
    risk_score,
    camera_confidence,
    filament_runout,
    pause_success,
    pause_message,
    notification_sent
):
    timestamp = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    with closing(connect()) as connection:
        cursor = connection.execute("""
            INSERT INTO incidents (
                timestamp,
                mode,
                failure_type,
                risk_score,
                camera_confidence,
                filament_runout,
                pause_success,
                pause_message,
                notification_sent
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            mode,
            failure_type,
            float(risk_score),
            float(camera_confidence),
            int(filament_runout),
            int(pause_success),
            str(pause_message),
            int(notification_sent)
        ))

        connection.commit()
        return cursor.lastrowid


def get_incidents(limit=100):
    with closing(connect()) as connection:
        rows = connection.execute("""
            SELECT *
            FROM incidents
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return [dict(row) for row in rows]


def get_incident_stats():
    with closing(connect()) as connection:
        row = connection.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(pause_success), 0) AS paused,
                COALESCE(SUM(notification_sent), 0) AS notified,
                COALESCE(AVG(risk_score), 0) AS average_risk
            FROM incidents
        """).fetchone()

    return dict(row)


init_db()
