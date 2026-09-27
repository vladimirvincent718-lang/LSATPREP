"""Private, course-scoped notes. Markdown is stored verbatim."""
import sqlite3
from contextlib import contextmanager
from src import database


@contextmanager
def connection():
    conn = database.get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_notebook():
    with connection() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS study_notes (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL, chapter TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL, body TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS study_notes_owner
            ON study_notes(user_id, course_id);
        ''')
        conn.execute('BEGIN IMMEDIATE')
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(study_notes)')}
        if 'question_id' not in columns:
            conn.execute('ALTER TABLE study_notes ADD COLUMN question_id INTEGER')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS study_notes_question ON study_notes(user_id, question_id)')
        # Move the initial standalone notepads into the notebook atomically.
        # Consuming migrated rows prevents deleted notes from being resurrected.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_question_notes'").fetchone():
            for old in conn.execute('SELECT * FROM user_question_notes').fetchall():
                try:
                    course_id, chapter, title, source = question_note_location(conn, old['question_id'])
                except (ValueError, sqlite3.IntegrityError):
                    continue
                conn.execute('''INSERT INTO study_notes
                    (user_id,course_id,chapter,title,body,source,question_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,question_id) DO NOTHING''',
                    (old['user_id'], course_id, chapter, title, old['notes'], source,
                     old['question_id'], old['created_at'], old['updated_at']))
                conn.execute('DELETE FROM user_question_notes WHERE user_id=? AND question_id=?',
                             (old['user_id'], old['question_id']))


def question_note_location(conn, question_id):
    """Resolve the question's own course and the same labels used in practice."""
    row = conn.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
    if row is None:
        raise sqlite3.IntegrityError('This question is no longer available.')
    q = dict(row)
    if not q.get('course_id'):
        raise ValueError('Assign this question to a course before saving course notes.')
    module = q.get('section_type') or ''
    chapter = ''
    if q.get('chapter_id') and conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='course_chapters'"
    ).fetchone():
        chapter_row = conn.execute('SELECT name FROM course_chapters WHERE id=? AND course_id=?',
                                  (q['chapter_id'], q['course_id'])).fetchone()
        if chapter_row:
            chapter = chapter_row['name']
    label = f"{module or 'Chapters'} / {chapter}" if chapter else module
    code = q.get('question_id') or str(question_id)
    return q['course_id'], label, f'Question {code} notes', f'Practice question {code} · Question Bank #{question_id}'


def list_notes(user_id, course_id, query='', chapter=None):
    with connection() as conn:
        rows = conn.execute('''SELECT * FROM study_notes
            WHERE user_id=? AND course_id=? ORDER BY pinned DESC, updated_at DESC, id DESC''',
            (user_id, course_id)).fetchall()
    needle = query.strip().casefold()
    return [dict(r) for r in rows
            if (chapter is None or r['chapter'] == chapter)
            and (not needle or needle in '\n'.join(
                r[k] for k in ('title', 'body', 'chapter', 'source')).casefold())]


def save_note(user_id, course_id, title, body, chapter='', source='', pinned=False, note_id=None):
    if not title.strip() or not body.strip():
        raise ValueError('Add a title and some notes before saving.')
    values = (title.strip(), body, chapter.strip(), source.strip(), int(pinned))
    with connection() as conn:
        if note_id is None:
            return conn.execute('''INSERT INTO study_notes
                (title,body,chapter,source,pinned,user_id,course_id) VALUES (?,?,?,?,?,?,?)''',
                (*values, user_id, course_id)).lastrowid
        result = conn.execute('''UPDATE study_notes SET title=?,body=?,chapter=?,source=?,pinned=?,
            updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND course_id=?''',
            (*values, note_id, user_id, course_id))
        if not result.rowcount:
            raise ValueError('This note is no longer available in your notebook.')
    return note_id


def delete_note(user_id, course_id, note_id):
    with connection() as conn:
        conn.execute('DELETE FROM study_notes WHERE id=? AND user_id=? AND course_id=?',
                     (note_id, user_id, course_id))
