"""Persistent, private spaced review for shared course materials."""
from contextlib import contextmanager
from datetime import date, timedelta

from src import database

INTERVALS = (1, 3, 7, 14, 30, 60)


@contextmanager
def connection():
    conn = database.get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_reviews():
    with connection() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS material_review_sources (
            material_id INTEGER PRIMARY KEY, source_name TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS material_review_state (
            user_id INTEGER NOT NULL, material_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, stage INTEGER NOT NULL DEFAULT 0,
            due_date TEXT NOT NULL, last_review TEXT, interval_days INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, material_id));
        CREATE TABLE IF NOT EXISTS material_review_history (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, material_id INTEGER NOT NULL,
            reviewed_on TEXT NOT NULL, rating TEXT NOT NULL, recall TEXT NOT NULL DEFAULT '',
            due_date TEXT NOT NULL, UNIQUE(user_id, material_id, reviewed_on));
        CREATE TABLE IF NOT EXISTS material_slide_views (
            user_id INTEGER NOT NULL, material_id INTEGER NOT NULL,
            slide_number INTEGER NOT NULL CHECK(slide_number > 0),
            viewed_on TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 1 CHECK(views > 0),
            PRIMARY KEY(user_id, material_id, slide_number, viewed_on));
        ''')


def register_cheat_sheet(material_id, source_name):
    with connection() as conn:
        conn.execute('INSERT OR IGNORE INTO material_review_sources VALUES (?, ?)',
                     (material_id, source_name))


def list_reviews(user_id, course_id=None, today=None):
    """Include unenrolled schedules nowhere; newly attached sheets start due today."""
    today = today or date.today()
    with connection() as conn:
        rows = conn.execute('''
            SELECT m.*, c.title AS course_title, s.source_name,
                CASE WHEN s.material_id IS NOT NULL THEN 1 ELSE 0 END AS is_cheat_sheet,
                COALESCE(r.enabled, CASE WHEN s.material_id IS NOT NULL THEN 1 ELSE 0 END) AS review_enabled,
                COALESCE(r.stage, 0) AS stage, COALESCE(r.due_date, ?) AS due_date,
                r.last_review, COALESCE(r.interval_days, 0) AS interval_days
            FROM course_materials m
            JOIN courses c ON c.id=m.course_id
            JOIN course_enrollments e ON e.course_id=m.course_id AND e.user_id=?
            LEFT JOIN material_review_sources s ON s.material_id=m.id
            LEFT JOIN material_review_state r ON r.material_id=m.id AND r.user_id=?
            WHERE COALESCE(m.is_active, 1)=1 AND c.is_active=1
              AND e.enrollment_status='Active' AND (? IS NULL OR m.course_id=?)
            ORDER BY due_date, m.title
        ''', (today.isoformat(), user_id, user_id, course_id, course_id)).fetchall()
    return [dict(r, is_due=bool(r['review_enabled'] and r['due_date'] <= today.isoformat())) for r in rows]


def _check_material(conn, user_id, material_id):
    if not conn.execute('''SELECT m.id FROM course_materials m
        JOIN courses c ON c.id=m.course_id
        JOIN course_enrollments e ON e.course_id=m.course_id
        WHERE m.id=? AND e.user_id=? AND e.enrollment_status='Active'
        AND c.is_active=1 AND COALESCE(m.is_active,1)=1''', (material_id, user_id)).fetchone():
        raise ValueError('This material is not available in your active courses.')


def set_enabled(user_id, material_id, enabled, today=None):
    today = today or date.today()
    with connection() as conn:
        _check_material(conn, user_id, material_id)
        conn.execute('''INSERT INTO material_review_state(user_id,material_id,enabled,due_date)
            VALUES (?,?,?,?) ON CONFLICT(user_id,material_id) DO UPDATE SET enabled=excluded.enabled''',
            (user_id, material_id, int(enabled), today.isoformat()))


def record_review(user_id, material_id, rating, recall='', today=None):
    """Only an explicit assessment schedules a review; repeat submissions are harmless."""
    if rating not in ('again', 'hard', 'good'):
        raise ValueError('Choose a review rating.')
    today = today or date.today()
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        _check_material(conn, user_id, material_id)
        prior = conn.execute('''SELECT due_date FROM material_review_history
            WHERE user_id=? AND material_id=? AND reviewed_on=?''',
            (user_id, material_id, today.isoformat())).fetchone()
        if prior:
            return prior['due_date']
        state = conn.execute('SELECT * FROM material_review_state WHERE user_id=? AND material_id=?',
                             (user_id, material_id)).fetchone()
        stage = state['stage'] if state else 0
        if rating == 'again':
            stage, days = 0, 1
        elif rating == 'hard':
            days = max(1, (state['interval_days'] if state else 0) // 2)
        else:
            days = INTERVALS[min(stage, len(INTERVALS) - 1)]
            stage = min(stage + 1, len(INTERVALS) - 1)
        due = (today + timedelta(days=days)).isoformat()
        conn.execute('''INSERT INTO material_review_state
            (user_id,material_id,enabled,stage,due_date,last_review,interval_days)
            VALUES (?,?,1,?,?,?,?) ON CONFLICT(user_id,material_id) DO UPDATE SET
            enabled=1,stage=excluded.stage,due_date=excluded.due_date,
            last_review=excluded.last_review,interval_days=excluded.interval_days''',
            (user_id, material_id, stage, due, today.isoformat(), days))
        conn.execute('''INSERT INTO material_review_history
            (user_id,material_id,reviewed_on,rating,recall,due_date) VALUES (?,?,?,?,?,?)''',
            (user_id, material_id, today.isoformat(), rating, recall.strip(), due))
    return due


def review_history(user_id, material_id):
    with connection() as conn:
        _check_material(conn, user_id, material_id)
        return [dict(r) for r in conn.execute('''SELECT * FROM material_review_history
            WHERE user_id=? AND material_id=? ORDER BY reviewed_on DESC LIMIT 20''',
            (user_id, material_id))]


def record_slide_view(user_id, material_id, slide_number, today=None):
    """Count a slide visit atomically, independently of the review schedule.

    Dates use the app's local calendar, like the spaced-review schedule.
    The viewer is responsible for suppressing non-navigation reruns.
    """
    if not isinstance(slide_number, int) or isinstance(slide_number, bool) or slide_number < 1:
        raise ValueError('Choose a valid slide number.')
    today = today or date.today()
    with connection() as conn:
        _check_material(conn, user_id, material_id)
        conn.execute('''INSERT INTO material_slide_views
            (user_id, material_id, slide_number, viewed_on) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, material_id, slide_number, viewed_on)
            DO UPDATE SET views=material_slide_views.views + 1''',
            (user_id, material_id, slide_number, today.isoformat()))


def slide_view_history(user_id, material_id):
    """Private daily counts for every visited slide; unvisited slides have no rows."""
    with connection() as conn:
        _check_material(conn, user_id, material_id)
        return [dict(r) for r in conn.execute('''
            SELECT slide_number, viewed_on, views FROM material_slide_views
            WHERE user_id=? AND material_id=? ORDER BY viewed_on DESC, slide_number
        ''', (user_id, material_id))]
