"""Durable, bounded tutor tickets. Only human activity creates work."""
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import audio_study as store, database

PROFILES = {'gemini': 'AI Tutor · Gemini', 'openai': 'AI Tutor · ChatGPT'}
DEFAULTS = dict(enabled=False, primary='gemini', reviewer='openai', reply_minutes=0,
                review_hours=24, call_limit=20, gemini_model='gemini-2.5-flash',
                openai_model='gpt-4.1-mini')


def now():
    return datetime.now(timezone.utc).timestamp()


def init_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS audio_tutor_settings(user_id INTEGER PRIMARY KEY, settings TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audio_tutor_worker_state(id INTEGER PRIMARY KEY, heartbeat REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS audio_tutor_threads(
      root_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
      state TEXT NOT NULL DEFAULT 'open', revision INTEGER NOT NULL DEFAULT 0,
      activity_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS audio_tutor_jobs(
      id INTEGER PRIMARY KEY, root_id INTEGER NOT NULL, revision INTEGER NOT NULL,
      kind TEXT NOT NULL, provider TEXT NOT NULL, due_at REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued', started_at REAL, error TEXT NOT NULL DEFAULT '',
      UNIQUE(root_id,revision,kind));
    CREATE TABLE IF NOT EXISTS audio_tutor_notifications(
      mark_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, root_id INTEGER NOT NULL,
      is_read INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS audio_tutor_due ON audio_tutor_jobs(status,due_at);
    ''')
    fields = {r['name'] for r in c.execute('PRAGMA table_info(audio_marks)')}
    for name, definition in [('tutor_provider', "TEXT NOT NULL DEFAULT ''"),
                             ('tutor_kind', "TEXT NOT NULL DEFAULT ''"), ('tutor_job_id', 'INTEGER')]:
        if name not in fields:
            c.execute(f'ALTER TABLE audio_marks ADD COLUMN {name} {definition}')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS audio_tutor_reply_once ON audio_marks(tutor_job_id)')


def settings(user_id, c=None):
    if c is None:
        with store.connection() as conn:
            return settings(user_id, conn)
    row = c.execute('SELECT settings FROM audio_tutor_settings WHERE user_id=?', (user_id,)).fetchone()
    return {**DEFAULTS, **(json.loads(row['settings']) if row else {})}


def save_settings(user_id, values):
    values = {**DEFAULTS, **values}
    if (type(values['enabled']) is not bool or values['primary'] not in PROFILES or
            values['reviewer'] not in (*PROFILES, 'none') or values['reviewer'] == values['primary']):
        raise ValueError('Choose a primary tutor and a different reviewer, or no reviewer.')
    for name, low, high in [('reply_minutes', 0, 1440), ('review_hours', .25, 168), ('call_limit', 1, 100)]:
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Choose valid reply delays and usage limits.')
    if int(values['call_limit']) != values['call_limit']:
        raise ValueError('The call limit must be a whole number.')
    for field in ('gemini_model', 'openai_model'):
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', values[field]):
            raise ValueError('Enter a valid model ID.')
    with store.connection() as c:
        c.execute('INSERT OR REPLACE INTO audio_tutor_settings VALUES (?,?)', (user_id, json.dumps(values)))
        # Change only unstarted jobs. Already completed reviews never run again.
        for thread in c.execute("SELECT * FROM audio_tutor_threads WHERE user_id=? AND state='open'", (user_id,)).fetchall():
            _queue(c, dict(thread), values)


def root_for(c, mark_id, audio_id):
    seen = set()
    while mark_id not in seen and len(seen) < 1000:
        seen.add(mark_id)
        row = c.execute('SELECT * FROM audio_marks WHERE id=? AND audio_id=?', (mark_id, audio_id)).fetchone()
        if not row:
            break
        if row['parent_id'] is None:
            return dict(row)
        mark_id = row['parent_id']
    raise ValueError('Conversation not found.')


def _queue(c, thread, prefs):
    for kind, provider, delay in [('reply', prefs['primary'], prefs['reply_minutes'] * 60),
                                  ('review', prefs['reviewer'], prefs['review_hours'] * 3600)]:
        if provider == 'none':
            c.execute("UPDATE audio_tutor_jobs SET status='cancelled' WHERE root_id=? AND kind=? AND status IN ('queued','blocked')", (thread['root_id'], kind))
            continue
        c.execute('''INSERT INTO audio_tutor_jobs(root_id,revision,kind,provider,due_at)
          VALUES (?,?,?,?,?) ON CONFLICT(root_id,revision,kind) DO UPDATE SET
          provider=excluded.provider,due_at=excluded.due_at,status='queued',error=''
          WHERE audio_tutor_jobs.status IN ('queued','blocked','cancelled') AND audio_tutor_jobs.started_at IS NULL''',
          (thread['root_id'], thread['revision'], kind, provider, thread['activity_at'] + delay))


def human_activity(c, user_id, course_id, audio_id, mark_id):
    mark = c.execute('SELECT tutor_provider FROM audio_marks WHERE id=?', (mark_id,)).fetchone()
    if not mark or mark['tutor_provider']:
        return
    root = root_for(c, mark_id, audio_id)
    if root['is_deleted']:
        return
    thread = c.execute('SELECT * FROM audio_tutor_threads WHERE root_id=?', (root['id'],)).fetchone()
    # Shared listeners cannot silently enable calls against someone else's account.
    if thread and thread['user_id'] != user_id:
        return
    if not thread and root['user_id'] != user_id:
        return
    activity = now()
    c.execute('''INSERT INTO audio_tutor_threads(root_id,user_id,course_id,state,revision,activity_at)
      VALUES (?,?,?,'open',1,?) ON CONFLICT(root_id) DO UPDATE SET
      state='open',revision=revision+1,activity_at=excluded.activity_at''', (root['id'], user_id, course_id, activity))
    c.execute("UPDATE audio_tutor_jobs SET status='cancelled' WHERE root_id=? AND status IN ('queued','blocked','running')", (root['id'],))
    thread = dict(c.execute('SELECT * FROM audio_tutor_threads WHERE root_id=?', (root['id'],)).fetchone())
    _queue(c, thread, settings(user_id, c))


def set_help(user_id, course_id, audio_id, root_id, opened):
    if type(opened) is not bool:
        raise ValueError('Choose open or resolved.')
    with store.connection() as c:
        recording = store._accessible(c, user_id, course_id, audio_id)
        root = root_for(c, root_id, audio_id)
        if root['id'] != root_id or user_id not in (root['user_id'], recording['user_id']):
            raise ValueError('Only the comment author or recording owner can manage help.')
        if opened:
            if user_id != root['user_id'] or root['is_deleted']:
                raise ValueError('Only the comment author can request tutor help.')
            thread = c.execute('SELECT state FROM audio_tutor_threads WHERE root_id=?', (root_id,)).fetchone()
            if thread and thread['state'] == 'open':
                return
            human_activity(c, user_id, course_id, audio_id, root_id)
        else:
            c.execute("UPDATE audio_tutor_threads SET state='resolved',revision=revision+1 WHERE root_id=?", (root_id,))
            c.execute("UPDATE audio_tutor_jobs SET status='cancelled' WHERE root_id=? AND status IN ('queued','blocked','running')", (root_id,))


def decorate(c, marks, user_id, owner_id):
    root_ids = [m['id'] for m in marks if m['parent_id'] is None]
    placeholders = ','.join('?' for _ in root_ids) or 'NULL'
    threads = {r['root_id']: dict(r) for r in c.execute(f'SELECT * FROM audio_tutor_threads WHERE root_id IN ({placeholders})', root_ids)}
    unread = {r['mark_id'] for r in c.execute('SELECT mark_id FROM audio_tutor_notifications WHERE user_id=? AND is_read=0', (user_id,))}
    for mark in marks:
        if mark['tutor_provider']:
            mark['author'] = PROFILES.get(mark['tutor_provider'], 'AI Tutor')
            mark['can_edit'] = user_id == owner_id
        mark['unread'] = mark['id'] in unread
        if mark['parent_id'] is not None:
            continue
        thread = threads.get(mark['id'])
        mark['help_state'] = thread['state'] if thread else 'inactive'
        mark['can_manage_help'] = not mark['is_deleted'] and user_id in (mark['user_id'], owner_id)
        mark['can_request_help'] = not mark['is_deleted'] and user_id == mark['user_id']
        jobs = [] if not thread else [dict(r) for r in c.execute(
            'SELECT kind,status,due_at,error,provider FROM audio_tutor_jobs WHERE root_id=? AND revision=? ORDER BY kind', (mark['id'], thread['revision']))]
        mark['tutor_jobs'] = jobs
    return marks


def read_replies(user_id, course_id, audio_id, root_id):
    with store.connection() as c:
        store._accessible(c, user_id, course_id, audio_id)
        root = root_for(c, root_id, audio_id)
        c.execute('UPDATE audio_tutor_notifications SET is_read=1 WHERE user_id=? AND root_id=?', (user_id, root['id']))


def launch_worker():
    root = Path(__file__).resolve().parent.parent
    python = root / '.venv' / 'Scripts' / 'python.exe'
    subprocess.Popen([str(python) if python.exists() else sys.executable, '-m', 'src.audio_tutor_worker', str(database.DB_PATH.resolve())],
                     cwd=root, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_worker():
    """Do not spawn anything until a user has explicitly enabled API tutoring."""
    with store.connection() as c:
        heartbeat = c.execute('SELECT heartbeat FROM audio_tutor_worker_state WHERE id=1').fetchone()
        if heartbeat and heartbeat['heartbeat'] > now() - 120:
            return True
        active = any(settings(row['user_id'], c)['enabled'] for row in c.execute(
            "SELECT DISTINCT t.user_id FROM audio_tutor_threads t JOIN audio_tutor_jobs j ON j.root_id=t.root_id WHERE t.state='open' AND j.status IN ('queued','blocked')"))
    if active:
        try:
            launch_worker()
        except OSError:
            return False
    return True


def timestamp(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


def transcript_export(text, words, include_timestamps):
    if words:
        passages = []
        for word in words:
            if not passages or passages[-1]['cue'] != word.get('cue'):
                passages.append(dict(cue=word.get('cue'), start=word['start'], text=[]))
            passages[-1]['text'].append(word['text'])
        return '\n\n'.join((f"[{timestamp(p['start'])}] " if include_timestamps else '') + ' '.join(p['text']) for p in passages)
    if include_timestamps:
        return text
    stamp = r'(?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d+)?'
    lines = []
    source_lines=text.splitlines()
    for index,line in enumerate(source_lines):
        is_index=line.strip().isdigit() and index+1<len(source_lines) and re.match(rf'^\s*{stamp}\s*-->',source_lines[index+1])
        if is_index or re.match(r'^\s*WEBVTT\b', line) or re.match(rf'^\s*{stamp}\s*-->', line):
            continue
        lines.append(re.sub(rf'^\s*\[?{stamp}\]?\s+', '', line))
    return '\n'.join(lines).strip()


def transcript_context(text, words, start, end):
    if words:
        nearby = [w for w in words if w['end'] >= max(0, start - 90) and w['start'] <= min(end, start + 180) + 90]
        return transcript_export('', nearby, True)[:14000], True
    # Imported timestamps are source anchors; do not invent alignment for plain text.
    stamp = r'(?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d+)?'
    cues = []
    for block in re.split(r'\n\s*\n', text):
        for line in block.splitlines():
            match = re.match(rf'^\s*\[?({stamp})\]?(?:\s*-->.*|\s+.*)$', line)
            if match:
                clock = 0
                for part in match[1].replace(',', '.').split(':'):
                    clock = clock * 60 + float(part)
                cues.append((clock, []))
            if cues:
                cues[-1][1].append(line)
    if cues:
        relevant = [cue for i, cue in enumerate(cues) if cue[0] <= end + 90 and
                    (cues[i+1][0] if i+1 < len(cues) else float('inf')) >= start - 90]
        return '\n\n'.join('\n'.join(lines) for _, lines in relevant)[:14000], True
    return text[:14000], False


def build_context(c, job):
    root = c.execute('SELECT * FROM audio_marks WHERE id=? AND is_deleted=0', (job['root_id'],)).fetchone()
    if not root:
        raise ValueError('Conversation removed.')
    audio = store._accessible(c, job['user_id'], job['course_id'], root['audio_id'])
    transcript = c.execute('SELECT text FROM audio_transcripts WHERE audio_id=?', (audio['id'],)).fetchone()
    text = transcript['text'] if transcript else ''
    speech = c.execute('SELECT words,generated_text FROM audio_transcription_jobs WHERE audio_id=?', (audio['id'],)).fetchone()
    words = json.loads(speech['words']) if speech and speech['generated_text'] == text else []
    passage, timed = transcript_context(text, words, root['start'], root['end'])
    rows = c.execute('''WITH RECURSIVE thread AS (
      SELECT *,0 AS depth FROM audio_marks WHERE id=?
      UNION ALL SELECT m.*,t.depth+1 FROM audio_marks m JOIN thread t ON m.parent_id=t.id WHERE t.depth<100)
      SELECT * FROM thread WHERE is_deleted=0 ORDER BY id''', (root['id'],)).fetchall()
    # Include the original question even on long threads.
    chosen = [rows[0], *rows[-23:]] if len(rows) > 24 else rows
    messages = [dict(author=PROFILES.get(r['tutor_provider'], 'Learner'), text=r['note'][:2000], quote=r['quote'][:2000]) for r in chosen]
    return dict(recording=audio['title'], comment_time=timestamp(root['start']),
                transcript=passage, transcript_has_real_timestamps=timed,
                transcript_truncated=len(text) > 14000 and not timed,
                conversation=messages)


def claim_job(clock=None):
    clock = now() if clock is None else clock
    with store.connection() as c:
        c.execute('BEGIN IMMEDIATE')
        candidates = c.execute('''SELECT j.*,t.user_id,t.course_id,t.state,t.revision AS current_revision
          FROM audio_tutor_jobs j JOIN audio_tutor_threads t ON t.root_id=j.root_id
          WHERE j.status IN ('queued','blocked') AND j.due_at<=? ORDER BY j.due_at,j.id LIMIT 100''', (clock,)).fetchall()
        for row in candidates:
            job = dict(row)
            if job['state'] != 'open' or job['revision'] != job['current_revision']:
                c.execute("UPDATE audio_tutor_jobs SET status='cancelled' WHERE id=?", (job['id'],));continue
            prefs = settings(job['user_id'], c)
            if not prefs['enabled']:
                c.execute("UPDATE audio_tutor_jobs SET status='blocked',error='Enable API tutoring in Tutor settings.' WHERE id=?", (job['id'],));continue
            from src.tutor_providers import has_key
            if not has_key(job['user_id'], job['provider']):
                c.execute("UPDATE audio_tutor_jobs SET status='blocked',error='Connect this tutor in Tutor settings.' WHERE id=?", (job['id'],));continue
            if job['kind'] == 'review':
                primary = c.execute("SELECT status FROM audio_tutor_jobs WHERE root_id=? AND revision=? AND kind='reply'", (job['root_id'], job['revision'])).fetchone()
                if primary and primary['status'] in ('error','cancelled'):
                    c.execute("UPDATE audio_tutor_jobs SET status='cancelled',error='The first reply did not finish. Reopen help to retry.' WHERE id=?", (job['id'],));continue
                if not primary or primary['status'] not in ('done', 'quiet'):
                    continue
            usage = c.execute('''SELECT COUNT(*) AS count,MIN(started_at) AS first FROM audio_tutor_jobs j
              JOIN audio_tutor_threads t ON t.root_id=j.root_id WHERE t.user_id=? AND started_at>?''', (job['user_id'], clock-86400)).fetchone()
            if usage['count'] >= prefs['call_limit']:
                c.execute("UPDATE audio_tutor_jobs SET due_at=?,error='Waiting for your 24-hour call limit.' WHERE id=?", (usage['first']+86401, job['id']));continue
            try:
                context = build_context(c, job)
            except ValueError:
                c.execute("UPDATE audio_tutor_jobs SET status='cancelled',error='Conversation no longer available.' WHERE id=?", (job['id'],));continue
            c.execute("UPDATE audio_tutor_jobs SET status='running',started_at=?,error='' WHERE id=?", (clock, job['id']))
            return {**job, 'context': context, 'model': prefs[job['provider']+'_model']}
    return None


def finish_job(job, result):
    with store.connection() as c:
        c.execute('BEGIN IMMEDIATE')
        current = c.execute('''SELECT j.status,t.state,t.revision,t.user_id,t.course_id
          FROM audio_tutor_jobs j JOIN audio_tutor_threads t ON t.root_id=j.root_id WHERE j.id=?''', (job['id'],)).fetchone()
        if not current or current['status'] != 'running' or current['state'] != 'open' or current['revision'] != job['revision']:
            return
        # Settings can be paused or changed during an API call. Never publish then.
        prefs = settings(current['user_id'], c)
        provider = prefs['primary'] if job['kind'] == 'reply' else prefs['reviewer']
        from src.tutor_providers import has_key
        if not prefs['enabled'] or provider != job['provider'] or not has_key(current['user_id'], job['provider']):
            c.execute("UPDATE audio_tutor_jobs SET status='cancelled' WHERE id=?", (job['id'],));return
        try:
            build_context(c, job)  # Recheck access and root deletion before publishing.
        except ValueError:
            c.execute("UPDATE audio_tutor_jobs SET status='cancelled' WHERE id=?", (job['id'],));return
        message = result['reply'].strip()
        if job['kind'] == 'review' and not result['needs_followup']:
            c.execute("UPDATE audio_tutor_jobs SET status='quiet' WHERE id=?", (job['id'],));return
        if not message or len(message) > 8000:
            raise ValueError('The tutor returned an invalid reply.')
        root = c.execute('SELECT * FROM audio_marks WHERE id=?', (job['root_id'],)).fetchone()
        mark_id = c.execute('''INSERT INTO audio_marks(audio_id,start,end,note,status,parent_id,user_id,quote,created_at,tutor_provider,tutor_kind,tutor_job_id)
          VALUES (?,?,?,?,'Neutral',?,?,'',CURRENT_TIMESTAMP,?,?,?)''',
          (root['audio_id'], root['start'], root['end'], message, root['id'], current['user_id'], job['provider'], job['kind'], job['id'])).lastrowid
        c.execute('INSERT INTO audio_tutor_notifications(mark_id,user_id,root_id) VALUES (?,?,?)', (mark_id,current['user_id'],root['id']))
        c.execute("UPDATE audio_tutor_jobs SET status='done' WHERE id=?", (job['id'],))
        # Intentionally no human_activity call: tutor output never creates work.


def fail_job(job, message):
    with store.connection() as c:
        c.execute("UPDATE audio_tutor_jobs SET status='error',error=? WHERE id=? AND status='running'", (message, job['id']))
        if job['kind'] == 'reply':
            c.execute("UPDATE audio_tutor_jobs SET status='cancelled',error='The first reply failed. Reopen help to retry.' WHERE root_id=? AND revision=? AND kind='review' AND status IN ('queued','blocked')", (job['root_id'],job['revision']))
