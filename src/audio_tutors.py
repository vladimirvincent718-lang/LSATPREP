"""Manual tutor profiles and saved responses; automatic API tutoring is disabled."""
import json
import re
import uuid
from datetime import datetime, timezone

from src import audio_study as store, database

PROFILES = {'gemini': 'AI Tutor · Gemini', 'openai': 'AI Tutor · ChatGPT'}
DEFAULTS = {'enabled': False}


def now():
    return datetime.now(timezone.utc).timestamp()


def init_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS audio_tutor_settings(user_id INTEGER PRIMARY KEY, settings TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audio_tutor_profiles(user_id INTEGER NOT NULL, provider TEXT NOT NULL,
      label TEXT NOT NULL, PRIMARY KEY(user_id,provider));
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
    disable_automation(c)


def disable_automation(c):
    """Persist the shutdown, including jobs left over from earlier versions."""
    for row in c.execute('SELECT user_id,settings FROM audio_tutor_settings').fetchall():
        values=json.loads(row['settings'])
        if values.get('enabled'):
            values['enabled']=False
            c.execute('UPDATE audio_tutor_settings SET settings=? WHERE user_id=?',(json.dumps(values),row['user_id']))
    c.execute("UPDATE audio_tutor_jobs SET status='cancelled',error='Automatic API tutoring is disabled.' WHERE status IN ('queued','blocked','running')")


def profiles(user_id,c=None):
    if c is None:
        with store.connection() as conn:return profiles(user_id,conn)
    return {**PROFILES, **{r['provider']:r['label'] for r in c.execute('SELECT provider,label FROM audio_tutor_profiles WHERE user_id=? ORDER BY label',(user_id,))}}


def add_profile(user_id,label):
    label=' '.join(label.split()).strip()
    if not label or len(label)>80:
        raise ValueError('Enter a tutor name of up to 80 characters.')
    if not label.startswith('AI Tutor · '):label='AI Tutor · '+label
    with store.connection() as c:
        if label.casefold() in {p.casefold() for p in profiles(user_id,c).values()}:
            raise ValueError('This tutor profile already exists.')
        provider='custom_'+uuid.uuid4().hex
        c.execute('INSERT INTO audio_tutor_profiles VALUES (?,?,?)',(user_id,provider,label))
        return provider


def save_manual_reply(user_id,course_id,audio_id,parent_id,provider,text,submission_id):
    if not isinstance(text,str) or not text.strip() or len(text)>100000:
        raise ValueError('Paste a response of up to 100,000 characters.')
    if not isinstance(submission_id,str) or not 1<=len(submission_id)<=100:
        raise ValueError('Invalid response submission.')
    with store.connection() as c:
        store._accessible(c,user_id,course_id,audio_id)
        if provider not in profiles(user_id,c):
            raise ValueError('Choose one of your saved tutor profiles.')
        parent=c.execute('SELECT * FROM audio_marks WHERE id=? AND audio_id=? AND is_deleted=0',(parent_id,audio_id)).fetchone()
        if not parent:raise ValueError('Choose an available comment to attach this response to.')
        existing=c.execute('SELECT * FROM audio_note_submissions WHERE id=?',(submission_id,)).fetchone()
        if existing:
            mark=c.execute('SELECT * FROM audio_marks WHERE id=?',(existing['mark_id'],)).fetchone()
            if not mark or existing['audio_id']!=audio_id or mark['user_id']!=user_id or mark['tutor_kind']!='manual':
                raise ValueError('This submission belongs to another comment.')
            return existing['mark_id']
        mark=c.execute('''INSERT INTO audio_marks(audio_id,start,end,note,status,parent_id,user_id,quote,created_at,tutor_provider,tutor_kind)
          VALUES (?,?,?,?,'Neutral',?,?,'',CURRENT_TIMESTAMP,?,'manual')''',
          (audio_id,parent['start'],parent['end'],text,parent_id,user_id,provider)).lastrowid
        c.execute('INSERT INTO audio_note_submissions VALUES (?,?,?)',(submission_id,audio_id,mark))
        return mark


def saved_responses(user_id,course_id,provider=None):
    with store.connection() as c:
        rows=c.execute('''SELECT m.*,a.title,p.note AS question,p.quote AS question_quote
          FROM audio_marks m JOIN study_audio a ON a.id=m.audio_id
          LEFT JOIN audio_marks p ON p.id=m.parent_id
          WHERE m.user_id=? AND m.tutor_provider!='' AND m.is_deleted=0
          AND (a.user_id=? OR EXISTS(SELECT 1 FROM audio_listeners l WHERE l.audio_id=a.id AND l.user_id=?))
          AND (a.course_id=? OR EXISTS(SELECT 1 FROM audio_targets t WHERE t.audio_id=a.id AND t.course_id=?))
          ORDER BY m.created_at DESC,m.id DESC''',(user_id,user_id,user_id,course_id,course_id)).fetchall()
        return [dict(r,author=profiles(r['user_id'],c).get(r['tutor_provider'],'AI Tutor')) for r in rows if not provider or r['tutor_provider']==provider]


def settings(user_id, c=None):
    if c is None:
        with store.connection() as conn:
            return settings(user_id, conn)
    row = c.execute('SELECT settings FROM audio_tutor_settings WHERE user_id=?', (user_id,)).fetchone()
    return {**DEFAULTS, **(json.loads(row['settings']) if row else {}),'enabled':False}


def save_settings(user_id, values):
    if values.get('enabled'):
        raise ValueError('Automatic API tutoring is disabled. Save tutor responses manually.')
    with store.connection() as c:
        c.execute('INSERT OR REPLACE INTO audio_tutor_settings VALUES (?,?)', (user_id, json.dumps({**values, 'enabled': False})))


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
    return  # Manual-only mode never queues API work.


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
            mark['author'] = profiles(mark['user_id'],c).get(mark['tutor_provider'], 'AI Tutor')
            mark['can_edit'] = user_id in (mark['user_id'],owner_id)
        mark['can_save_tutor_reply'] = not mark['is_deleted']
        mark['unread'] = mark['id'] in unread
        if mark['parent_id'] is not None:
            continue
        thread = threads.get(mark['id'])
        mark['help_state'] = thread['state'] if thread else 'inactive'
        mark['can_manage_help'] = not mark['is_deleted'] and user_id in (mark['user_id'], owner_id)
        mark['can_request_help'] = not mark['is_deleted'] and user_id == mark['user_id']
        mark['tutor_jobs'] = []
    return marks


def read_replies(user_id, course_id, audio_id, root_id):
    with store.connection() as c:
        store._accessible(c, user_id, course_id, audio_id)
        root = root_for(c, root_id, audio_id)
        c.execute('UPDATE audio_tutor_notifications SET is_read=1 WHERE user_id=? AND root_id=?', (user_id, root['id']))


def launch_worker():
    return  # Automatic tutoring has been retired.


def ensure_worker():
    return True  # Nothing to start in manual-only mode.


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
    return None


def finish_job(job, result):
    return  # Suppress results from any retired automatic job.
        # Intentionally no human_activity call: tutor output never creates work.


def fail_job(job, message):
    with store.connection() as c:
        c.execute("UPDATE audio_tutor_jobs SET status='cancelled',error='Automatic API tutoring is disabled.' WHERE id=?", (job['id'],))
