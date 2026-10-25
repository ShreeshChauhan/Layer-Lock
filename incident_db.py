
import sqlite3
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv('INCIDENT_DB_PATH', str(Path(__file__).resolve().parent / 'print_guardian.db')))


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
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(incidents)')}
        for name, kind in {
            'file_name': 'TEXT', 'print_progress': 'REAL', 'print_time': 'REAL',
            'resolution': "TEXT NOT NULL DEFAULT 'pending'", 'resolved_at': 'TEXT'
        }.items():
            if name not in columns:
                connection.execute(f'ALTER TABLE incidents ADD COLUMN {name} {kind}')
        connection.execute('''CREATE TABLE IF NOT EXISTS printer_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            message TEXT NOT NULL, simulated INTEGER NOT NULL)''')
        connection.commit()


def save_incident(
    mode,
    failure_type,
    risk_score,
    camera_confidence,
    filament_runout,
    pause_success,
    pause_message,
    notification_sent,
    file_name=None,
    print_progress=None,
    print_time=None
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
                notification_sent, file_name, print_progress, print_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            mode,
            failure_type,
            float(risk_score),
            float(camera_confidence),
            int(filament_runout),
            int(pause_success),
            str(pause_message),
            int(notification_sent), file_name, print_progress, print_time
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


def update_notification(incident_id, sent):
    with closing(connect()) as connection:
        connection.execute('UPDATE incidents SET notification_sent=? WHERE id=?', (int(sent), incident_id))
        connection.commit()


def resolve_incident(incident_id, resolution):
    with closing(connect()) as connection:
        connection.execute('''UPDATE incidents SET resolution=?, resolved_at=?
            WHERE resolution='pending' AND mode=(SELECT mode FROM incidents WHERE id=?)
            AND file_name IS (SELECT file_name FROM incidents WHERE id=?)''',
            (resolution, datetime.now(timezone.utc).isoformat(), incident_id, incident_id))
        connection.commit()


def open_incident(mode, file_name):
    with closing(connect()) as connection:
        row = connection.execute('''SELECT * FROM incidents WHERE mode=? AND file_name IS ?
            AND resolution='pending' ORDER BY id DESC LIMIT 1''', (mode, file_name)).fetchone()
    return dict(row) if row else None


def save_event(message, simulated):
    with closing(connect()) as connection:
        connection.execute('INSERT INTO printer_events(timestamp,message,simulated) VALUES(?,?,?)',
                           (datetime.now(timezone.utc).isoformat(), message, int(simulated)))
        connection.commit()


def get_events(limit=100):
    with closing(connect()) as connection:
        rows = connection.execute('SELECT * FROM printer_events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(row) for row in rows]


init_db()
