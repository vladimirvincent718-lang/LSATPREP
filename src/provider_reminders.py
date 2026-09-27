"""Date-aware Kaplan update requests using the existing SMTP configuration."""
from contextlib import closing
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlsplit, urlunsplit

from src import database as db
from src.email_notifications import _load_smtp_settings, _missing_smtp_message, _send_message
from src.practice_calendar import ZONE


def submission_url(base):
    parts = urlsplit(base.strip())
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Enter the full StudyForge app address without embedded credentials.')
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') + '/Kaplan_Update', '', ''))


def requested_range(user_id, today=None):
    today = today or datetime.now(ZONE).date()
    covered = db.get_setting(user_id, 'kaplan_complete_through')
    start = date.fromisoformat(covered) + timedelta(days=1) if covered else None
    return start, today - timedelta(days=1)


def range_label(user_id, today=None):
    start, end = requested_range(user_id, today)
    if start and start > end:
        return 'Your Kaplan history is complete through yesterday.'
    return f'{start:%B %d, %Y} through {end:%B %d, %Y}' if start else f'all history through {end:%B %d, %Y}'


def confirm_no_new_quizzes(user_id, through):
    through = date.fromisoformat(str(through))
    start, end = requested_range(user_id)
    if through > end or (start and through < start):
        raise ValueError('Choose a date in the outstanding range, no later than yesterday.')
    with closing(db.get_connection()) as conn, conn:
        conn.execute("INSERT INTO settings(user_id,key,value) VALUES (?, 'kaplan_complete_through', ?) ON CONFLICT(user_id,key) DO UPDATE SET value=MAX(value, excluded.value)", (user_id, through.isoformat()))
        conn.execute("INSERT INTO settings(user_id,key,value) VALUES (?, 'kaplan_last_import', ?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (user_id, datetime.now(ZONE).date().isoformat()))


def build_request(user_id, today):
    recipient = db.get_setting(user_id, 'profile_email').strip()
    if not recipient:
        raise ValueError('Add your email address in Settings.')
    link = submission_url(db.get_setting(user_id, 'kaplan_app_url'))
    smtp = _load_smtp_settings()
    missing = _missing_smtp_message(smtp)
    if missing:
        raise ValueError(missing)
    msg = EmailMessage()
    msg['To'], msg['From'] = recipient, smtp['from_email']
    msg['Subject'] = '[StudyForge] Please update your Kaplan question counts'
    msg.set_content(
        f'Please submit your Kaplan My Quizzes history for {range_label(user_id, today)}.\n\n'
        f'Paste and submit here: {link}\n\n'
        'Copy the quiz rows with dates, question counts, and scores. Confirm the last full day covered. '
        'If there were no new completed quizzes, record that on the same page. '
        'Overlapping rows are safe: existing quizzes are not counted twice. '
        'Submission updates your daily dashboard counts.\n\n'
        'Keep any unfinished quizzes in your next update once they are completed.'
    )
    return msg, smtp


def run_due_requests(now=None):
    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    today = now.date()
    with closing(db.get_connection()) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS kaplan_request_deliveries (
            user_id INTEGER NOT NULL, request_date TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY(user_id, request_date))''')
        users = conn.execute("SELECT user_id FROM settings WHERE key='kaplan_email_enabled' AND value='true'").fetchall()
    results = []
    for row in users:
        uid = row['user_id']
        try:
            days = int(db.get_setting(uid, 'kaplan_reminder_days') or '7')
            if days <= 0:
                continue
            start, end = requested_range(uid, today)
            if start and start > end:
                continue
            with closing(db.get_connection()) as conn:
                prior = conn.execute('SELECT MAX(request_date) FROM kaplan_request_deliveries WHERE user_id=?', (uid,)).fetchone()[0]
            last_import = db.get_setting(uid, 'kaplan_last_import')
            anchors = [date.fromisoformat(v) for v in (prior, last_import) if v]
            if anchors and today < max(anchors) + timedelta(days=days):
                continue
            msg, smtp = build_request(uid, today)
        except (ValueError, TypeError):
            results.append((uid, 'Kaplan request configuration needs review'))
            continue
        with closing(db.get_connection()) as conn, conn:
            claimed = conn.execute('INSERT OR IGNORE INTO kaplan_request_deliveries VALUES (?, ?, ?)', (uid, today.isoformat(), 'sending')).rowcount
        if not claimed:
            continue
        try:
            _send_message(msg, smtp)
            status = 'sent'
        except Exception:
            status = 'delivery_unconfirmed'
        with closing(db.get_connection()) as conn, conn:
            conn.execute('UPDATE kaplan_request_deliveries SET status=? WHERE user_id=? AND request_date=?', (status, uid, today.isoformat()))
        results.append((uid, status))
    return results
