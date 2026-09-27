"""Explicit question classification, independent of source-document formatting."""
import json
import re

from src import database

from src.professional_specialty import SPECIALTY_LABELS

LENSES = {**SPECIALTY_LABELS, "standard": "Standard / no lens", "hip_hop": "Hip Hop", "movement": "Movement"}


def get_lenses():
    conn = database.get_connection()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS question_lenses (id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE)')
        conn.executemany('INSERT OR IGNORE INTO question_lenses(id,name) VALUES (?,?)', LENSES.items())
        conn.commit()
        return {row['id']: row['name'] for row in conn.execute('SELECT id,name FROM question_lenses ORDER BY rowid')}
    finally:
        conn.close()


def save_lens(name, lens_id=None):
    name = ' '.join(name.split())
    if not name:
        raise ValueError('Enter a lens name.')
    lenses = get_lenses()
    if any(label.casefold() == name.casefold() and key != lens_id for key, label in lenses.items()):
        raise ValueError('A lens with this name already exists.')
    if lens_id is not None and lens_id not in lenses:
        raise ValueError('Unknown lens.')
    if lens_id is None:
        base = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_') or 'lens'
        lens_id = base
        counter = 2
        while lens_id in lenses:
            lens_id = f'{base}_{counter}'
            counter += 1
    conn = database.get_connection()
    try:
        with conn:
            conn.execute('INSERT INTO question_lenses(id,name) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name', (lens_id,name))
        return lens_id
    finally:
        conn.close()


def set_question_lenses(course_id, question_ids, lens):
    validate_lens(lens)
    conn = database.get_connection()
    try:
        with conn:
            rows = []
            for qid in set(question_ids):
                row = conn.execute('SELECT id,metadata_json FROM questions WHERE id=? AND course_id=?', (qid,course_id)).fetchone()
                if not row:
                    raise ValueError('A selected question does not belong to this subject.')
                rows.append(row)
            for row in rows:
                metadata = json.loads(row['metadata_json'] or '{}')
                metadata['lens'] = lens
                conn.execute('UPDATE questions SET metadata_json=? WHERE id=?', (json.dumps(metadata),row['id']))
            return len(rows)
    finally:
        conn.close()


def validate_lens(lens):
    if lens not in get_lenses():
        raise ValueError("Choose a supported question lens.")
    return lens


def question_lens(question):
    try:
        value = json.loads(question.get("metadata_json") or "{}").get("lens", "standard")
    except (ValueError, TypeError, AttributeError):
        value = "standard"
    return value if isinstance(value, str) and value else "standard"


def set_batch_lens(course_id, batch_id, lens, *, imported=False):
    validate_lens(lens)
    table = "question_import_batches" if imported else "ccrn_import_queue"
    conn = database.get_connection()
    try:
        with conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND course_id=?", (batch_id, course_id)).fetchone()
            if not row or (not imported and row['imported_batch_id'] is not None):
                raise ValueError("This batch is unavailable for editing.")
            conn.execute(f"UPDATE {table} SET lens=? WHERE id=? AND course_id=?", (lens, batch_id, course_id))
            if imported:
                questions = conn.execute('SELECT id,metadata_json FROM questions WHERE course_id=? AND import_batch_id=?',
                                         (course_id, batch_id)).fetchall()
                for question in questions:
                    metadata = json.loads(question['metadata_json'] or '{}')
                    metadata['lens'] = lens
                    conn.execute('UPDATE questions SET metadata_json=? WHERE id=?', (json.dumps(metadata), question['id']))
                return len(questions)
    finally:
        conn.close()
