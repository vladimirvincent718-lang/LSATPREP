"""Personal flashcard decks, source extraction, and persistent study state."""
import hashlib
import io
import json
import re
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from src import database

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def connection():
    conn = database.get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_flashcards():
    with connection() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS flashcard_decks (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
          title TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', seed_key TEXT,
          UNIQUE(user_id, course_id, seed_key));
        CREATE TABLE IF NOT EXISTS flashcards (
          id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL REFERENCES flashcard_decks(id),
          position INTEGER NOT NULL, front TEXT NOT NULL, back TEXT NOT NULL,
          starred INTEGER NOT NULL DEFAULT 0, known INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS flashcard_seed_updates (
          deck_id INTEGER NOT NULL REFERENCES flashcard_decks(id),
          revision INTEGER NOT NULL,
          PRIMARY KEY(deck_id, revision));
        ''')


def starter_data():
    return json.loads((ROOT / 'data/flashcards/cfa_cheatsheet.json').read_text(encoding='utf-8'))


def validate_cards(cards):
    cleaned = []
    for card in cards:
        front, back = str(card.get('front') or '').strip(), str(card.get('back') or '').strip()
        if not front and not back:
            continue
        if not front or not back:
            raise ValueError('Every card needs both a term and an answer.')
        cleaned.append({'front': front, 'back': back})
    if not cleaned:
        raise ValueError('Add at least one complete card.')
    return cleaned


def save_deck(user_id, course_id, title, source, cards, deck_id=None, seed_key=None):
    cards = validate_cards(cards)
    if not title.strip():
        raise ValueError('Give your set a title.')
    with connection() as conn:
        if deck_id is None:
            cur = conn.execute('INSERT INTO flashcard_decks(user_id,course_id,title,source,seed_key) VALUES (?,?,?,?,?)',
                               (user_id, course_id, title.strip(), source, seed_key))
            deck_id = cur.lastrowid
            previous = {}
        else:
            if not conn.execute('SELECT id FROM flashcard_decks WHERE id=? AND user_id=? AND course_id=?',
                                (deck_id, user_id, course_id)).fetchone():
                raise ValueError('Set not found.')
            previous = {(r['front'], r['back']): (r['starred'], r['known']) for r in
                        conn.execute('SELECT * FROM flashcards WHERE deck_id=?', (deck_id,))}
            conn.execute('UPDATE flashcard_decks SET title=?,source=? WHERE id=?', (title.strip(), source, deck_id))
            conn.execute('DELETE FROM flashcards WHERE deck_id=?', (deck_id,))
        for i, c in enumerate(cards):
            star, known = previous.get((c['front'], c['back']), (0, 0))
            conn.execute('INSERT INTO flashcards(deck_id,position,front,back,starred,known) VALUES (?,?,?,?,?,?)',
                         (deck_id, i, c['front'], c['back'], star, known))
    return deck_id


def seed_cfa(user_id, course_id):
    """Seed attached material and apply new card batches once, preserving user edits."""
    data = starter_data()
    materials = database.get_materials(course_id)
    if not any(Path(m.get('stored_file_path') or '').name == data['source'] for m in materials):
        from src.curriculum_materials import has_curriculum_source
        if not has_curriculum_source(course_id, data['source']):
            return
    with connection() as conn:
        # Serialize seeding with other tabs; card insertion and update markers commit together.
        conn.execute('BEGIN IMMEDIATE')
        for chapter in data['chapters']:
            key = 'cfa-v1:' + chapter['title']
            row = conn.execute('SELECT id FROM flashcard_decks WHERE user_id=? AND course_id=? AND seed_key=?',
                               (user_id, course_id, key)).fetchone()
            fresh = row is None
            deck_id = (conn.execute('INSERT INTO flashcard_decks(user_id,course_id,title,source,seed_key) VALUES (?,?,?,?,?)',
                                   (user_id, course_id, chapter['title'], data['source'], key)).lastrowid
                       if fresh else row['id'])
            applied = {r[0] for r in conn.execute('SELECT revision FROM flashcard_seed_updates WHERE deck_id=?', (deck_id,))}
            # Existing decks already received revision 1. Do not restore cards a user removed.
            if not fresh:
                applied.add(1)
            fronts = {r[0] for r in conn.execute('SELECT front FROM flashcards WHERE deck_id=?', (deck_id,))}
            position = conn.execute('SELECT COALESCE(MAX(position),-1)+1 FROM flashcards WHERE deck_id=?', (deck_id,)).fetchone()[0]
            revisions = {int(c.get('seed_revision', 1)) for c in chapter['cards']}
            for card in chapter['cards']:
                if int(card.get('seed_revision', 1)) in applied or card['front'] in fronts:
                    continue
                conn.execute('INSERT INTO flashcards(deck_id,position,front,back) VALUES (?,?,?,?)',
                             (deck_id, position, card['front'], card['back']))
                fronts.add(card['front'])
                position += 1
            conn.executemany('INSERT OR IGNORE INTO flashcard_seed_updates(deck_id,revision) VALUES (?,?)',
                             [(deck_id, revision) for revision in revisions])


def list_decks(user_id, course_id):
    with connection() as conn:
        return [dict(r) for r in conn.execute('''SELECT d.*, COUNT(c.id) AS total,
          COALESCE(SUM(c.known),0) AS known FROM flashcard_decks d
          LEFT JOIN flashcards c ON c.deck_id=d.id WHERE d.user_id=? AND d.course_id=?
          GROUP BY d.id ORDER BY d.id''', (user_id, course_id))]


def get_cards(user_id, course_id, deck_id):
    with connection() as conn:
        return [dict(r) for r in conn.execute('''SELECT c.* FROM flashcards c JOIN flashcard_decks d ON d.id=c.deck_id
          WHERE d.user_id=? AND d.course_id=? AND d.id=? ORDER BY c.position''', (user_id, course_id, deck_id))]


def mark_card(user_id, course_id, card_id, field, value):
    if field not in ('known', 'starred'):
        raise ValueError('Unknown study field.')
    with connection() as conn:
        conn.execute(f'''UPDATE flashcards SET {field}=? WHERE id=? AND deck_id IN
          (SELECT id FROM flashcard_decks WHERE user_id=? AND course_id=?)''', (int(bool(value)), card_id, user_id, course_id))


def extract_text(name, content):
    suffix = Path(name).suffix.lower()
    if suffix == '.docx':
        data = starter_data()
        if hashlib.sha256(content).hexdigest() == data['sha256']:
            return '\n'.join('# ' + c['title'] + '\n' + '\n'.join(x['front'] + '\t' + x['back'] for x in c['cards']) for c in data['chapters'])
        with ZipFile(io.BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = '\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns))
    elif suffix == '.pdf':
        from pypdf import PdfReader
        text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(content)).pages)
    elif suffix in ('.txt', '.md', '.tsv'):
        text = content.decode('utf-8-sig')
    else:
        raise ValueError('Use a PDF, DOCX, TXT, Markdown, or TSV file.')
    if not text.strip():
        raise ValueError('This document has no readable text. Paste its transcribed chapter notes to create cards.')
    return text


def draft_cards(text):
    """Extract explicit pairs; turn remaining prose into source-preserving recall prompts."""
    cards, heading = [], 'Chapter notes'
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            heading = line.lstrip('# ').strip()
            continue
        line = re.sub(r'^[-•*]\s+', '', line)
        parts = re.split(r'\t+|\s+[—–]\s+|:\s+', line, maxsplit=1)
        if len(parts) == 2 and all(p.strip() for p in parts):
            cards.append({'front': parts[0].strip(), 'back': parts[1].strip()})
        elif '=' in line and all(part.strip() for part in line.split('=', 1)):
            cards.append({'front': 'Formula for ' + line.split('=', 1)[0].strip(), 'back': line})
        elif len(line) > 35:
            cue = ' '.join(line.split()[:7])
            cards.append({'front': f'{heading}: explain “{cue}…”', 'back': line})
        else:
            heading = line
    seen = set()
    return [c for c in cards if not ((c['front'], c['back']) in seen or seen.add((c['front'], c['back'])))]


def material_text(material):
    text = material.get('content_text') or ''
    raw = material.get('stored_file_path')
    if raw:
        path = (ROOT / raw).resolve()
        if not path.is_relative_to((ROOT / 'data/material_files').resolve()):
            raise ValueError('Material file is outside the course library.')
        text += '\n' + extract_text(path.name, path.read_bytes())
    if not text.strip():
        raise ValueError('This material contains only a link. Paste its chapter text below.')
    return text
