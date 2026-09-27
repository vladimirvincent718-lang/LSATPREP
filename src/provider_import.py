"""Parse Kaplan exports and merge quiz history without duplicate daily counts."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from src import database
from src.practice_calendar import ZONE


def parse_kaplan(text):
    text = text.replace('\u200b', '').replace('\xa0', ' ')
    pattern = re.compile(
        r'(?P<title>[^\n]+)\n\s*'
        r'(?P<date>[A-Za-z]+ \d{1,2}, \d{4})\s*-\s*(?P<time>\d{1,2}:\d{2}\s*[AP]M)\s+'
        r'(?P<count>\d+) Questions?\s+(?P<duration>\d+:\d{2}:\d{2})\s+'
        r'(?:time spent[^\n]*\s+)?(?P<score>\d+(?:\.\d+)?%|IN PROGRESS)', re.I)
    quizzes, skipped = {}, 0
    matches = list(pattern.finditer(text))
    expected = len(re.findall(r'\b\d+\s+Questions?\s*\n', text, re.I))
    if expected != len(matches):
        raise ValueError('Some quiz rows could not be read. Copy the complete My Quizzes page again.')
    for match in matches:
        row = match.groupdict()
        if row['score'].upper() == 'IN PROGRESS':
            skipped += 1
            continue
        stamp = datetime.strptime(row['date'] + ' ' + row['time'].upper(), '%B %d, %Y %I:%M %p')
        count, score = int(row['count']), float(row['score'][:-1])
        correct = round(count * score / 100)
        if count <= 0 or not 0 <= score <= 100 or abs(correct * 100 / count - score) > .011:
            raise ValueError(f"Invalid question count or score for {row['title']}.")
        title = ' '.join(row['title'].split())
        key = hashlib.sha256(f'{title}|{stamp.isoformat()}'.encode()).hexdigest()
        quiz = dict(quiz_key=key, title=title, started_at=stamp.isoformat(),
                    entry_date=stamp.date().isoformat(), correct_count=correct,
                    incorrect_count=count-correct, duration=row['duration'])
        if key in quizzes and quizzes[key] != quiz:
            raise ValueError('Conflicting results for the same quiz. Please submit one page export.')
        quizzes[key] = quiz
    if not quizzes:
        raise ValueError('No completed Kaplan quizzes found. Copy the My Quizzes list, including dates and scores.')
    return {'quizzes': list(quizzes.values()), 'skipped': skipped}


def _ensure(conn):
    database._ensure_external_practice_table(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS provider_quizzes (
        user_id INTEGER NOT NULL, quiz_key TEXT NOT NULL, entry_date TEXT NOT NULL,
        payload TEXT NOT NULL, PRIMARY KEY(user_id, quiz_key))''')
    conn.commit()


def import_kaplan(user_id, text, replace_existing=False, complete_through=None):
    parsed = parse_kaplan(text)
    if complete_through is not None:
        complete_through = date.fromisoformat(str(complete_through))
        if complete_through >= datetime.now(ZONE).date():
            raise ValueError('Confirm only fully finished days, through yesterday or earlier.')
        if parsed['skipped']:
            raise ValueError('Unfinished quizzes remain in this history. Import without confirming coverage, then include them once completed.')
    conn = database.get_connection()
    try:
        _ensure(conn)
        conn.execute('BEGIN IMMEDIATE')
        dates = {q['entry_date'] for q in parsed['quizzes']}
        # A manual edit to previously imported totals also requires explicit replacement.
        for day in dates:
            old = conn.execute("SELECT correct_count, incorrect_count FROM external_practice_entries WHERE user_id=? AND source='Kaplan' AND entry_date=?", (user_id, day)).fetchone()
            ledger = [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM provider_quizzes WHERE user_id=? AND entry_date=?', (user_id, day))]
            prior = tuple(sum(q[k] for q in ledger) for k in ('correct_count', 'incorrect_count'))
            if old and (not ledger or tuple(old) != prior) and not replace_existing:
                raise ValueError(f'Existing Kaplan totals on {day} need review. Select replacement to use the imported quiz history for this date.')
        added = 0
        for quiz in parsed['quizzes']:
            exists = conn.execute('SELECT 1 FROM provider_quizzes WHERE user_id=? AND quiz_key=?', (user_id, quiz['quiz_key'])).fetchone()
            added += int(not exists)
            conn.execute('INSERT INTO provider_quizzes VALUES (?, ?, ?, ?) ON CONFLICT(user_id, quiz_key) DO UPDATE SET payload=excluded.payload', (user_id, quiz['quiz_key'], quiz['entry_date'], json.dumps(quiz)))
        for day in dates:
            rows = [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM provider_quizzes WHERE user_id=? AND entry_date=?', (user_id, day))]
            correct = sum(q['correct_count'] for q in rows)
            incorrect = sum(q['incorrect_count'] for q in rows)
            conn.execute('''INSERT INTO external_practice_entries (user_id, entry_date, source, correct_count, incorrect_count)
                VALUES (?, ?, 'Kaplan', ?, ?) ON CONFLICT(user_id, entry_date, source) DO UPDATE SET
                correct_count=excluded.correct_count, incorrect_count=excluded.incorrect_count, updated_at=CURRENT_TIMESTAMP''', (user_id, day, correct, incorrect))
        conn.execute("INSERT INTO settings(user_id,key,value) VALUES (?, 'kaplan_last_import', ?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (user_id, datetime.now(ZONE).date().isoformat()))
        if complete_through is not None:
            conn.execute("INSERT INTO settings(user_id,key,value) VALUES (?, 'kaplan_complete_through', ?) ON CONFLICT(user_id,key) DO UPDATE SET value=MAX(value, excluded.value)", (user_id, complete_through.isoformat()))
        conn.commit()
        return dict(added=added, days=len(dates), completed=len(parsed['quizzes']), skipped=parsed['skipped'])
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def valid_provider_url(value):
    parts = urlsplit(value)
    return parts.scheme == 'https' and bool(parts.hostname) and not parts.username and not parts.password


def next_reminder(user_id):
    days = int(database.get_setting(user_id, 'kaplan_reminder_days') or '7')
    last = database.get_setting(user_id, 'kaplan_last_import')
    if days == 0:
        return None
    return date.fromisoformat(last) + timedelta(days=days) if last else date.today()
