
import sqlite3
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv('INCIDENT_DB_PATH', str(Path(__file__).resolve().parents[1] / 'print_guardian.db')))


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
        connection.execute('''CREATE TABLE IF NOT EXISTS print_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            file_name TEXT, action TEXT NOT NULL, reason TEXT NOT NULL,
            detail TEXT NOT NULL, print_progress REAL, print_time REAL,
            outcome TEXT NOT NULL, simulated INTEGER NOT NULL)''')
        connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)')
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE name='manual_action_history'").fetchone():
            # Recover earlier dashboard commands from their accepted event entries.
            # Never invent progress/elapsed values that the old log did not capture.
            cutoff = connection.execute('SELECT MIN(timestamp) FROM print_actions').fetchone()[0]
            events = connection.execute('''SELECT * FROM printer_events
                WHERE message IN ('Pause command accepted', 'Cancel command accepted')
                AND (? IS NULL OR timestamp < ?) ORDER BY id''', (cutoff, cutoff)).fetchall()
            for event in events:
                selected = connection.execute('''SELECT message FROM printer_events
                    WHERE id < ? AND simulated=? AND message LIKE 'Selected print: %'
                    ORDER BY id DESC LIMIT 1''', (event['id'], event['simulated'])).fetchone()
                connection.execute('''INSERT INTO print_actions
                    (timestamp,file_name,action,reason,detail,outcome,simulated)
                    VALUES (?,?,?,?,?,?,?)''', (event['timestamp'],
                    selected['message'][len('Selected print: '):] if selected else None,
                    event['message'].split()[0].lower(), 'manual',
                    'Recovered from printer event log', 'Command accepted', event['simulated']))
            connection.execute("INSERT INTO schema_migrations VALUES ('manual_action_history')")
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


def save_print_action(action, reason, status, detail='', outcome='Command accepted'):
    with closing(connect()) as connection:
        connection.execute('''INSERT INTO print_actions
            (timestamp,file_name,action,reason,detail,print_progress,print_time,outcome,simulated)
            VALUES (?,?,?,?,?,?,?,?,?)''', (datetime.now(timezone.utc).isoformat(),
            status.get('file'), action, reason, detail, status.get('progress'),
            status.get('print_time'), outcome, int(status.get('simulated', False))))
        connection.commit()


def get_print_history(limit=200):
    # Automatic incidents retain their original timestamps and notification/recovery data.
    with closing(connect()) as connection:
        rows = connection.execute('''SELECT * FROM (
            SELECT 'action-' || id AS id, timestamp, file_name, action, reason, detail,
                   print_progress, print_time, outcome, simulated FROM print_actions
            UNION ALL
            SELECT 'incident-' || id AS id, timestamp, file_name, 'pause' AS action,
                   'automatic' AS reason, failure_type AS detail, print_progress, print_time,
                   CASE WHEN pause_success THEN 'Command accepted' ELSE 'Command failed' END AS outcome,
                   mode='simulation' AS simulated FROM incidents
            ) ORDER BY timestamp DESC, id DESC LIMIT ?''', (limit,)).fetchall()
    return [dict(row) for row in rows]


init_db()
