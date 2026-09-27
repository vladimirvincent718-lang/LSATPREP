"""Idempotent local delivery runner, called by the configured nightly automation."""
import json
from datetime import datetime, timedelta, time
from contextlib import closing

from src import database as db
from src.dashboard_report import SCHEDULE_KEY, build_snapshot, deliver_snapshot
from src.practice_calendar import ZONE


def ensure_schema():
    with closing(db.get_connection()) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS dashboard_report_deliveries (
            user_id INTEGER NOT NULL, report_date TEXT NOT NULL,
            status TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, report_date))''')


def is_due(config, now):
    frequency = config.get('frequency', 'Off')
    if frequency == 'Off' or now.time().replace(tzinfo=None) < time(0, 5):
        return False
    if frequency == 'Weekdays':
        return now.weekday() < 5
    if frequency == 'Weekly':
        return now.weekday() == config.get('weekday', 0)
    return frequency == 'Daily'


def run_due_reports(now=None):
    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    report_day = now.date() - timedelta(days=1)
    ensure_schema()
    with closing(db.get_connection()) as conn:
        configs = conn.execute('SELECT user_id, value FROM settings WHERE key=?', (SCHEDULE_KEY,)).fetchall()
    results = []
    for row in configs:
        uid = row['user_id']
        try:
            config = json.loads(row['value'])
            if not is_due(config, now):
                continue
        except (ValueError, TypeError, AttributeError):
            results.append((uid, 'Invalid schedule'))
            continue
        with closing(db.get_connection()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = conn.execute('SELECT status FROM dashboard_report_deliveries WHERE user_id=? AND report_date=?',
                                 (uid, report_day.isoformat())).fetchone()
            if prior and prior['status'] != 'build_failed':
                # A crash or uncertain SMTP response requires inspection, not blind resend.
                if prior['status'] != 'sent':
                    results.append((uid, 'Delivery requires review: ' + prior['status']))
                continue
            conn.execute('INSERT OR REPLACE INTO dashboard_report_deliveries VALUES (?, ?, ?, ?)',
                         (uid, report_day.isoformat(), 'building', now.isoformat()))
        try:
            snapshot = build_snapshot(uid, config, report_day, scheduled=True)
        except Exception:
            status = 'build_failed'
        else:
            with closing(db.get_connection()) as conn, conn:
                conn.execute('UPDATE dashboard_report_deliveries SET status=? WHERE user_id=? AND report_date=?',
                             ('sending', uid, report_day.isoformat()))
            try:
                deliver_snapshot(uid, snapshot)
            except Exception:
                status = 'delivery_unconfirmed'
            else:
                status = 'sent'
        with closing(db.get_connection()) as conn, conn:
            conn.execute('UPDATE dashboard_report_deliveries SET status=?, updated_at=? WHERE user_id=? AND report_date=?',
                         (status, datetime.now(ZONE).isoformat(), uid, report_day.isoformat()))
        results.append((uid, status))
    return results
