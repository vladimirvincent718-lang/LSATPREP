"""Private audio libraries, annotations and idempotent listening telemetry."""
import json
import math
import uuid
from contextlib import contextmanager
from pathlib import Path

from src import database

STATUSES = ('Neutral', 'Red', 'Yellow', 'Green')
MAX_AUDIO_UPLOAD_MB = 200
MIMES = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg'}


@contextmanager
def connection():
    conn = database.get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_audio():
    with connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS study_audio (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
          title TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL,
          mime TEXT NOT NULL, duration REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audio_marks (
          id INTEGER PRIMARY KEY, audio_id INTEGER NOT NULL, start REAL NOT NULL,
          end REAL NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audio_sessions (
          id TEXT PRIMARY KEY, audio_id INTEGER NOT NULL,
          opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audio_events (
          session_id TEXT NOT NULL, sequence INTEGER NOT NULL, seconds REAL NOT NULL,
          ranges TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(session_id, sequence));
        CREATE TABLE IF NOT EXISTS audio_targets (
          audio_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
          module_id INTEGER NOT NULL DEFAULT 0, chapter_id INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(audio_id,course_id,module_id,chapter_id));
        CREATE TABLE IF NOT EXISTS audio_note_submissions (
          id TEXT PRIMARY KEY, audio_id INTEGER NOT NULL, mark_id INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audio_listeners (
          audio_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
          PRIMARY KEY(audio_id,user_id));
        CREATE TABLE IF NOT EXISTS audio_listener_progress (
          audio_id INTEGER NOT NULL,user_id INTEGER NOT NULL,position REAL NOT NULL DEFAULT 0,
          processed_until REAL NOT NULL DEFAULT 0, PRIMARY KEY(audio_id,user_id));
        CREATE TABLE IF NOT EXISTS audio_plays (
          id TEXT PRIMARY KEY,session_id TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audio_completion (
          audio_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
          completed INTEGER NOT NULL CHECK(completed IN (0,1)),
          source TEXT NOT NULL CHECK(source IN ('manual','automatic')),
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(audio_id,user_id));
        CREATE TABLE IF NOT EXISTS audio_transcription_jobs (
          audio_id INTEGER PRIMARY KEY,status TEXT NOT NULL DEFAULT 'queued',
          error TEXT NOT NULL DEFAULT '',words TEXT NOT NULL DEFAULT '[]',
          generated_text TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audio_transcripts (
          audio_id INTEGER PRIMARY KEY,text TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audio_highlights (
          id TEXT PRIMARY KEY,audio_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
          start REAL NOT NULL,end REAL NOT NULL,quote TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')
        mark_fields={r['name'] for r in c.execute('PRAGMA table_info(audio_marks)')}
        for name,definition in [('parent_id','INTEGER'),('user_id','INTEGER'),('created_at','TEXT'),('is_deleted','INTEGER NOT NULL DEFAULT 0'),('quote',"TEXT NOT NULL DEFAULT ''")]:
            if name not in mark_fields:c.execute(f'ALTER TABLE audio_marks ADD COLUMN {name} {definition}')
        from src.audio_tutors import init_schema
        init_schema(c)
        c.execute('UPDATE audio_marks SET user_id=(SELECT user_id FROM study_audio WHERE id=audio_marks.audio_id) WHERE user_id IS NULL')
        session_fields={r['name'] for r in c.execute('PRAGMA table_info(audio_sessions)')}
        if 'user_id' not in session_fields:c.execute('ALTER TABLE audio_sessions ADD COLUMN user_id INTEGER')
        c.execute('UPDATE audio_sessions SET user_id=(SELECT user_id FROM study_audio WHERE id=audio_sessions.audio_id) WHERE user_id IS NULL')
        fields = {r['name'] for r in c.execute('PRAGMA table_info(study_audio)')}
        if 'drive_file_id' not in fields:
            c.execute('ALTER TABLE study_audio ADD COLUMN drive_file_id TEXT')
        c.execute('CREATE TABLE IF NOT EXISTS audio_storage_preferences (user_id INTEGER PRIMARY KEY, provider TEXT NOT NULL)')
        for name in ('position', 'processed_until'):
            if name not in fields:
                c.execute(f'ALTER TABLE study_audio ADD COLUMN {name} REAL NOT NULL DEFAULT 0')
        event_fields = {r['name'] for r in c.execute('PRAGMA table_info(audio_events)')}
        if 'processed_until' not in event_fields:
            c.execute('ALTER TABLE audio_events ADD COLUMN processed_until REAL NOT NULL DEFAULT 0')
            for row in c.execute('SELECT session_id,sequence,ranges FROM audio_events').fetchall():
                end = max((r[1] for r in json.loads(row['ranges'])), default=0)
                c.execute('UPDATE audio_events SET processed_until=? WHERE session_id=? AND sequence=?', (end,row['session_id'],row['sequence']))
            c.execute('''UPDATE study_audio SET processed_until=COALESCE((SELECT MAX(e.processed_until)
                FROM audio_events e JOIN audio_sessions s ON s.id=e.session_id WHERE s.audio_id=study_audio.id),0)''')
        c.execute('''INSERT OR IGNORE INTO audio_targets(audio_id,course_id)
            SELECT id,course_id FROM study_audio a WHERE NOT EXISTS
            (SELECT 1 FROM audio_targets t WHERE t.audio_id=a.id)''')
        c.execute('''INSERT OR IGNORE INTO audio_listener_progress(audio_id,user_id,position,processed_until)
            SELECT id,user_id,position,processed_until FROM study_audio''')
        # Earlier versions recorded listening sessions, but not individual starts.
        c.execute('''INSERT OR IGNORE INTO audio_plays(id,session_id,created_at)
            SELECT 'legacy:'||s.id,s.id,MIN(e.created_at) FROM audio_sessions s
            JOIN audio_events e ON e.session_id=s.id WHERE e.seconds>0
            AND NOT EXISTS(SELECT 1 FROM audio_plays p WHERE p.session_id=s.id) GROUP BY s.id''')


def _owned(c, user_id, course_id, audio_id):
    row = c.execute('''SELECT * FROM study_audio WHERE id=? AND user_id=? AND (course_id=? OR EXISTS
        (SELECT 1 FROM audio_targets t WHERE t.audio_id=study_audio.id AND t.course_id=?))''',
                    (audio_id, user_id, course_id, course_id)).fetchone()
    if row is None:
        raise ValueError('Audio is not available in this course.')
    return dict(row)


def _accessible(c, user_id, course_id, audio_id):
    row=c.execute('''SELECT * FROM study_audio a WHERE id=? AND
        (a.user_id=? OR EXISTS(SELECT 1 FROM audio_listeners l WHERE l.audio_id=a.id AND l.user_id=?))
        AND (a.course_id=? OR EXISTS(SELECT 1 FROM audio_targets t WHERE t.audio_id=a.id AND t.course_id=?))''',
        (audio_id,user_id,user_id,course_id,course_id)).fetchone()
    if not row:raise ValueError('Audio is not available in this course.')
    return dict(row)


def share_audio(user_id,course_id,audio_id,username):
    with connection() as c:
        _owned(c,user_id,course_id,audio_id)
        listener=c.execute('SELECT id FROM users WHERE username=?',(username.strip(),)).fetchone()
        if not listener:raise ValueError('No StudyForge account has that username.')
        if not c.execute('''SELECT 1 FROM course_enrollments e JOIN audio_targets t ON t.course_id=e.course_id
            WHERE t.audio_id=? AND e.user_id=? AND e.enrollment_status='Active' ''',(audio_id,listener['id'])).fetchone():
            raise ValueError('The listener must be enrolled in one of this recording’s assigned courses.')
        if listener['id']==user_id:raise ValueError('You already own this recording.')
        c.execute('INSERT OR IGNORE INTO audio_listeners VALUES (?,?)',(audio_id,listener['id']))


def listeners(user_id,course_id,audio_id):
    with connection() as c:
        _owned(c,user_id,course_id,audio_id)
        return [dict(r) for r in c.execute('SELECT u.id,u.username FROM audio_listeners l JOIN users u ON u.id=l.user_id WHERE l.audio_id=?',(audio_id,))]


def unshare_audio(user_id,course_id,audio_id,listener_id):
    with connection() as c:
        _owned(c,user_id,course_id,audio_id)
        c.execute('DELETE FROM audio_listeners WHERE audio_id=? AND user_id=?',(audio_id,listener_id))


def library(user_id, course_id):
    with connection() as c:
        items = [dict(r) for r in c.execute('''SELECT a.*,
            (SELECT COUNT(*) FROM audio_plays p JOIN audio_sessions s ON s.id=p.session_id WHERE s.audio_id=a.id) AS play_count
            FROM study_audio a WHERE (user_id=? OR EXISTS(SELECT 1 FROM audio_listeners l WHERE l.audio_id=a.id AND l.user_id=?)) AND EXISTS
            (SELECT 1 FROM audio_targets t WHERE t.audio_id=a.id AND t.course_id=?) ORDER BY id DESC''', (user_id,user_id, course_id))]
        return [dict(item, completion=_completion(c,user_id,item['id'],item['duration'])) for item in items]


def _validate_targets(c, user_id, targets):
    if not targets:
        raise ValueError('Choose at least one course, module or chapter.')
    for target in targets:
        cid, mid, chid = target['course_id'], target.get('module_id',0), target.get('chapter_id',0)
        if not c.execute('''SELECT 1 FROM course_enrollments e JOIN courses c ON c.id=e.course_id
            WHERE e.user_id=? AND e.course_id=? AND e.enrollment_status='Active' AND c.is_active=1''',(user_id,cid)).fetchone():
            raise ValueError('Choose a course you are actively enrolled in.')
        if mid and not c.execute('SELECT 1 FROM course_module_blueprints WHERE id=? AND course_id=?',(mid,cid)).fetchone():
            raise ValueError('Choose a module in the selected course.')
        if chid and not c.execute('SELECT 1 FROM course_chapters WHERE id=? AND course_id=? AND module_id=?',(chid,cid,mid)).fetchone():
            raise ValueError('Choose a chapter in the selected module.')


def targets(user_id, course_id, audio_id):
    with connection() as c:
        _accessible(c,user_id,course_id,audio_id)
        return [dict(r) for r in c.execute('SELECT course_id,module_id,chapter_id FROM audio_targets WHERE audio_id=?',(audio_id,))]


def set_targets(user_id, course_id, audio_ids, selected):
    with connection() as c:
        for audio_id in audio_ids:
            _owned(c,user_id,course_id,audio_id)
        _validate_targets(c,user_id,selected)
        for audio_id in audio_ids:
            c.execute('DELETE FROM audio_targets WHERE audio_id=?',(audio_id,))
            c.executemany('INSERT OR IGNORE INTO audio_targets VALUES (?,?,?,?)',
                [(audio_id,t['course_id'],t.get('module_id',0),t.get('chapter_id',0)) for t in selected])


def save_audio(user_id, course_id, title, topic, filename, content):
    return save_audio_batch(user_id, course_id, [dict(
        title=title, topic=topic, filename=filename, content=content)])[0]


def save_audio_batch(user_id, course_id, recordings, selected_targets=None):
    """Validate the whole selection, then save all rows and files together."""
    if not recordings:
        raise ValueError('Choose at least one audio file first.')
    for recording in recordings:
        suffix = Path(recording['filename']).suffix.lower()
        if not recording['title'].strip():
            raise ValueError(f"Add a title for {recording['filename']}.")
        if suffix not in MIMES or not recording['content'] or len(recording['content']) > MAX_AUDIO_UPLOAD_MB * 1024**2:
            raise ValueError(f"{recording['filename']}: choose an MP3, WAV, M4A or OGG file of up to {MAX_AUDIO_UPLOAD_MB} MB.")
    from src import drive_audio
    use_drive = storage_provider(user_id) == 'drive'
    folder = Path(database.DB_PATH).parent / 'study_audio'
    if not use_drive:
        folder.mkdir(parents=True, exist_ok=True)
    remote_created = []
    created = []
    ids = []
    try:
        with connection() as c:
            if selected_targets is not None:
                _validate_targets(c,user_id,selected_targets)
            for recording in recordings:
                suffix = Path(recording['filename']).suffix.lower()
                name = uuid.uuid4().hex + suffix
                target = folder / name
                remote_id = None
                if use_drive:
                    remote_id = drive_audio.upload(user_id, name, MIMES[suffix], recording['content'])
                    remote_created.append(remote_id)
                else:
                    created.append(target)
                    target.write_bytes(recording['content'])
                ids.append(c.execute('INSERT INTO study_audio(user_id,course_id,title,topic,filename,mime) VALUES (?,?,?,?,?,?)',
                           (user_id, course_id, recording['title'].strip(), recording['topic'].strip(), name, MIMES[suffix])).lastrowid)
                c.execute('UPDATE study_audio SET drive_file_id=? WHERE id=?', (remote_id, ids[-1]))
                c.executemany('INSERT OR IGNORE INTO audio_targets VALUES (?,?,?,?)',
                    [(ids[-1],t['course_id'],t.get('module_id',0),t.get('chapter_id',0))
                     for t in (selected_targets if selected_targets is not None else [{'course_id':course_id}])])
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        failures = []
        for file_id in remote_created:
            try:
                drive_audio.delete(user_id, file_id)
            except Exception:
                failures.append(file_id)
        if failures:
            raise drive_audio.DriveError('Batch failed; some uploaded StudyForge files remain in Drive. Remove the incomplete uploads from Drive before retrying.') from None
        raise
    return ids


def audio_bytes(user_id, course_id, audio_id):
    with connection() as c:
        row = _accessible(c, user_id, course_id, audio_id)
    if row.get('drive_file_id'):
        from src import drive_audio
        return drive_audio.download(row['user_id'], row['drive_file_id'])
    return (Path(database.DB_PATH).parent / 'study_audio' / Path(row['filename']).name).read_bytes()


def transcript(user_id,course_id,audio_id):
    with connection() as c:
        _accessible(c,user_id,course_id,audio_id)
        row=c.execute('SELECT text FROM audio_transcripts WHERE audio_id=?',(audio_id,)).fetchone()
        return row['text'] if row else ''


def save_transcript(user_id,course_id,audio_id,text):
    if not text.strip():raise ValueError('Add transcript text before saving.')
    if len(text.encode('utf-8'))>5*1024*1024:raise ValueError('The transcript must be under 5 MB.')
    with connection() as c:
        _owned(c,user_id,course_id,audio_id)
        c.execute('''INSERT INTO audio_transcripts(audio_id,text) VALUES (?,?)
            ON CONFLICT(audio_id) DO UPDATE SET text=excluded.text,updated_at=CURRENT_TIMESTAMP''',(audio_id,text.strip()))


def marks(user_id, course_id, audio_id):
    with connection() as c:
        row=_accessible(c, user_id, course_id, audio_id)
        items=[dict(r) for r in c.execute('SELECT * FROM audio_marks WHERE audio_id=? ORDER BY start,id', (audio_id,))]
        names={}
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
            names={r['id']:r['username'] for r in c.execute('SELECT id,username FROM users WHERE id IN (SELECT user_id FROM audio_marks WHERE audio_id=?)',(audio_id,))}
        from src.audio_tutors import decorate
        return decorate(c, [dict(m,author=names.get(m['user_id'],'Listener'),can_edit=user_id in (m['user_id'],row['user_id'])) for m in items], user_id, row['user_id'])


def save_mark(user_id, course_id, audio_id, start, end, note, status, mark_id=None, submission_id=None,parent_id=None,quote=''):
    with connection() as c:
        row = _accessible(c, user_id, course_id, audio_id)
        if parent_id is not None:
            parent=c.execute('SELECT * FROM audio_marks WHERE id=? AND audio_id=?',(parent_id,audio_id)).fetchone()
            if not parent:raise ValueError('The comment you are replying to is not part of this recording.')
            start,end,status=parent['start'],parent['end'],'Neutral'
            quote=''
        if submission_id:
            existing=c.execute('SELECT mark_id FROM audio_note_submissions WHERE id=? AND audio_id=?',(submission_id,audio_id)).fetchone()
            if existing:return existing['mark_id']
        if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start <= end <= row['duration']:
            raise ValueError('Choose a point or range within the audio duration.')
        if status not in STATUSES or not note.strip():
            raise ValueError('Add a note and choose a review status.')
        if mark_id is None:
            saved=c.execute('INSERT INTO audio_marks(audio_id,start,end,note,status,parent_id,user_id,quote,created_at) VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                             (audio_id, start, end, note.strip(), status,parent_id,user_id,quote.strip())).lastrowid
            if submission_id:c.execute('INSERT INTO audio_note_submissions VALUES (?,?,?)',(submission_id,audio_id,saved))
            from src.audio_tutors import human_activity
            human_activity(c,user_id,course_id,audio_id,saved)
            return saved
        if not c.execute('UPDATE audio_marks SET start=?,end=?,note=?,status=? WHERE id=? AND audio_id=? AND is_deleted=0 AND (user_id=? OR ?=?)',
                         (start, end, note.strip(), status, mark_id, audio_id,user_id,user_id,row['user_id'])).rowcount:
            raise ValueError('Note not found.')
        from src.audio_tutors import human_activity
        human_activity(c,user_id,course_id,audio_id,mark_id)


def highlights(user_id, course_id, audio_id):
    with connection() as c:
        _accessible(c,user_id,course_id,audio_id)
        return [dict(r) for r in c.execute('SELECT * FROM audio_highlights WHERE audio_id=? AND user_id=? ORDER BY start,id',(audio_id,user_id))]


def save_highlight(user_id, course_id, audio_id, start, end, quote, submission_id):
    with connection() as c:
        row=_accessible(c,user_id,course_id,audio_id)
        if not all(math.isfinite(v) for v in (start,end)) or not 0 <= start < end <= row['duration']:
            raise ValueError('Select words within the audio duration.')
        if not quote.strip() or not submission_id:
            raise ValueError('Select some transcript words to highlight.')
        c.execute('INSERT OR IGNORE INTO audio_highlights(id,audio_id,user_id,start,end,quote) VALUES (?,?,?,?,?,?)',
                  (submission_id,audio_id,user_id,start,end,quote.strip()))


def delete_highlight(user_id, course_id, audio_id, highlight_id):
    with connection() as c:
        _accessible(c,user_id,course_id,audio_id)
        if not c.execute('DELETE FROM audio_highlights WHERE id=? AND audio_id=? AND user_id=?',(highlight_id,audio_id,user_id)).rowcount:
            raise ValueError('Highlight not found.')


def delete_mark(user_id, course_id, audio_id, mark_id):
    with connection() as c:
        row=_accessible(c, user_id, course_id, audio_id)
        from src.audio_tutors import root_for
        mark=c.execute('SELECT * FROM audio_marks WHERE id=? AND audio_id=?',(mark_id,audio_id)).fetchone()
        if mark and user_id in (mark['user_id'],row['user_id']):
            root=root_for(c,mark_id,audio_id)
            # Deleting source context invalidates pending requests; deletion never starts work.
            c.execute("UPDATE audio_tutor_threads SET state='resolved',revision=revision+1 WHERE root_id=?",(root['id'],))
            c.execute("UPDATE audio_tutor_jobs SET status='cancelled' WHERE root_id=? AND status IN ('queued','blocked','running')",(root['id'],))
            c.execute('DELETE FROM audio_tutor_notifications WHERE mark_id=?',(mark_id,))
        # Retain the thread structure when a parent has replies.
        if c.execute('SELECT 1 FROM audio_marks WHERE parent_id=?',(mark_id,)).fetchone():
            c.execute("UPDATE audio_marks SET note='[Comment removed]',is_deleted=1 WHERE id=? AND audio_id=? AND (user_id=? OR ?=?)",(mark_id,audio_id,user_id,user_id,row['user_id']))
        else:
            c.execute('DELETE FROM audio_marks WHERE id=? AND audio_id=? AND (user_id=? OR ?=?)', (mark_id, audio_id,user_id,user_id,row['user_id']))


def record_event(user_id, course_id, audio_id, event):
    """Each browser batch is append-only and safely replayable after a rerun."""
    duration = float(event['duration'])
    seconds = float(event.get('seconds', 0))
    session = str(event['session'])
    sequence = int(event['sequence'])
    ranges = event.get('ranges', [])
    position = float(event.get('position', max((r[1] for r in ranges), default=0)))
    processed = float(event.get('processed_until', position))
    if not 0 < duration <= 86400 or not 0 <= seconds <= 120 or not session or len(session) > 100 or sequence < 0:
        raise ValueError('Invalid listening event.')
    if not 0 <= position <= duration or not 0 <= processed <= duration:
        raise ValueError('Invalid saved playback position.')
    if len(ranges) > 500 or any(len(r) != 2 or not all(math.isfinite(v) for v in r) or not 0 <= r[0] <= r[1] <= duration + .5 for r in ranges):
        raise ValueError('Invalid listening ranges.')
    if sum(b-a for a,b in ranges) > seconds * 4 + 2:
        raise ValueError('Listening range exceeds elapsed playback time.')
    with connection() as c:
        row=_accessible(c, user_id, course_id, audio_id)
        existing = c.execute('SELECT audio_id,user_id FROM audio_sessions WHERE id=?', (session,)).fetchone()
        if existing and (existing['audio_id'] != audio_id or existing['user_id'] != user_id):
            raise ValueError('Listening session belongs to another recording.')
        if c.execute('SELECT 1 FROM audio_events WHERE session_id=? AND sequence=?',(session,sequence)).fetchone():
            return
        c.execute('INSERT OR IGNORE INTO audio_sessions(id,audio_id,user_id) VALUES (?,?,?)', (session, audio_id,user_id))
        play_id=event.get('play_id')
        if play_id and seconds>0 and ranges:
            if not isinstance(play_id,str) or len(play_id)>100:raise ValueError('Invalid play identifier.')
            prior=c.execute('SELECT session_id FROM audio_plays WHERE id=?',(play_id,)).fetchone()
            if prior and prior['session_id']!=session:raise ValueError('Play belongs to another listening session.')
            c.execute('INSERT OR IGNORE INTO audio_plays(id,session_id) VALUES (?,?)',(play_id,session))
        latest=c.execute('SELECT MAX(sequence) FROM audio_events WHERE session_id=?',(session,)).fetchone()[0]
        inserted=c.execute('INSERT OR IGNORE INTO audio_events(session_id,sequence,seconds,ranges,processed_until) VALUES (?,?,?,?,?)',
                  (session, sequence, seconds, json.dumps(ranges),processed)).rowcount
        if inserted:
            if latest is None or sequence > latest:
                c.execute('''INSERT INTO audio_listener_progress VALUES (?,?,?,?) ON CONFLICT(audio_id,user_id)
                    DO UPDATE SET position=excluded.position,processed_until=MAX(processed_until,excluded.processed_until)''',(audio_id,user_id,position,processed))
                c.execute('UPDATE study_audio SET duration=? WHERE id=?',(duration,audio_id))
                if row['user_id']==user_id:
                    c.execute('UPDATE study_audio SET position=?,processed_until=MAX(processed_until,?) WHERE id=?',(position,processed,audio_id))
            else:
                c.execute('UPDATE audio_listener_progress SET processed_until=MAX(processed_until,?) WHERE audio_id=? AND user_id=?',(processed,audio_id,user_id))
            state=_completion(c,user_id,audio_id,duration)
            if state['completed'] and state['source']=='automatic':
                c.execute("INSERT OR IGNORE INTO audio_completion(audio_id,user_id,completed,source) VALUES (?,?,1,'automatic')",(audio_id,user_id))


def _completion(conn, user_id, audio_id, duration):
    state=conn.execute('SELECT completed,source FROM audio_completion WHERE audio_id=? AND user_id=?',
                       (audio_id,user_id)).fetchone()
    if state:
        return dict(completed=bool(state['completed']),source=state['source'])
    # Older listening history counts too, including listening split across visits.
    rows=conn.execute('SELECT e.ranges FROM audio_events e JOIN audio_sessions s ON s.id=e.session_id WHERE s.audio_id=? AND s.user_id=?',
                      (audio_id,user_id))
    ranges=[r for row in rows for r in json.loads(row['ranges'])]
    completed=bool(duration>0 and sum(b-a for a,b in merged_ranges(ranges))>=duration*.95)
    return dict(completed=completed,source='automatic' if completed else None)


def completion(user_id, course_id, audio_id):
    with connection() as conn:
        row=_accessible(conn,user_id,course_id,audio_id)
        return _completion(conn,user_id,audio_id,row['duration'])


def set_completion(user_id, course_id, audio_id, completed):
    if not isinstance(completed,bool):
        raise ValueError('Choose complete or incomplete.')
    with connection() as conn:
        _accessible(conn,user_id,course_id,audio_id)
        conn.execute("""INSERT INTO audio_completion(audio_id,user_id,completed,source) VALUES (?,?,?,'manual')
            ON CONFLICT(audio_id,user_id) DO UPDATE SET completed=excluded.completed,source='manual',updated_at=CURRENT_TIMESTAMP""",
                     (audio_id,user_id,int(completed)))


def progress(user_id, course_id, audio_id):
    with connection() as c:
        row=_accessible(c,user_id,course_id,audio_id)
        state=c.execute('SELECT position,processed_until FROM audio_listener_progress WHERE audio_id=? AND user_id=?',(audio_id,user_id)).fetchone()
        return dict(position=state['position'] if state else 0,processed_until=state['processed_until'] if state else 0,duration=row['duration'])


def play_count(user_id,course_id,audio_id):
    with connection() as c:
        _accessible(c,user_id,course_id,audio_id)
        return c.execute('SELECT COUNT(*) FROM audio_plays p JOIN audio_sessions s ON s.id=p.session_id WHERE s.audio_id=?',(audio_id,)).fetchone()[0]


def merged_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + .05:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def analytics(user_id, course_id, audio_id, window=None):
    with connection() as c:
        audio = _accessible(c, user_id, course_id, audio_id)
        sessions = c.execute('SELECT * FROM audio_sessions WHERE audio_id=? AND user_id=?', (audio_id,user_id)).fetchall()
        events = c.execute('SELECT e.* FROM audio_events e JOIN audio_sessions s ON s.id=e.session_id WHERE s.audio_id=? AND s.user_id=? ORDER BY e.created_at,e.sequence', (audio_id,user_id)).fetchall()
        plays=c.execute('SELECT p.* FROM audio_plays p JOIN audio_sessions s ON s.id=p.session_id WHERE s.audio_id=? AND s.user_id=?',(audio_id,user_id)).fetchall()
    inside = lambda value: not window or (window[0] <= value[:10] and (not window[1] or value[:10] < window[1]))
    events = [dict(e) for e in events if inside(e['created_at'])]
    by_session = {}
    for e in events:
        by_session.setdefault(e['session_id'], []).extend(json.loads(e['ranges']))
    ranges = [r for rs in by_session.values() for r in rs]
    coverage = sum(b-a for a,b in merged_ranges(ranges))
    complete = sum(sum(b-a for a,b in merged_ranges(rs)) >= audio['duration'] * .95 for rs in by_session.values()) if audio['duration'] else 0
    listened = sum(any(b > a for a,b in rs) for rs in by_session.values())
    segment_stats = []
    for mark in marks(user_id, course_id, audio_id):
        if mark['parent_id'] or mark['is_deleted']:continue
        start, end = mark['start'], max(mark['end'], mark['start'] + 1)
        hits = [(e['created_at'], e['session_id'], a,b) for e in events for a,b in json.loads(e['ranges']) if b > start and a < end]
        # Merge adjacent telemetry slices; a backward seek starts a new visit.
        visits, previous = 0, None
        for _, session,a,b in hits:
            if previous is None or session != previous[0] or abs(a - previous[1]) > .15:
                visits += 1
            previous = (session,b)
        segment_stats.append(dict(mark, visits=visits, listening_seconds=sum(max(0,min(b,end)-max(a,start)) for _,_,a,b in hits), last_listened=hits[-1][0] if hits else None))
    return dict(opens=sum(inside(s['opened_at']) for s in sessions), complete=complete,
                plays=sum(inside(p['created_at']) for p in plays),
                processed_percent=min(100,100*max((e['processed_until'] for e in events),default=0)/audio['duration']) if audio['duration'] else 0,
                partial=max(0,listened-complete), seconds=sum(e['seconds'] for e in events),
                percent=min(100,100*coverage/audio['duration']) if audio['duration'] else 0,
                last_listened=max((e['created_at'] for e in events if e['seconds'] > 0), default=None), segments=segment_stats)


def storage_provider(user_id):
    with connection() as c:
        row = c.execute('SELECT provider FROM audio_storage_preferences WHERE user_id=?', (user_id,)).fetchone()
        return row['provider'] if row else 'local'


def enable_drive(user_id):
    from src import drive_audio
    if not drive_audio.configured(user_id):
        raise drive_audio.DriveError('Connect Google Drive first.')
    with connection() as c:
        c.execute("INSERT INTO audio_storage_preferences VALUES (?,'drive') ON CONFLICT(user_id) DO UPDATE SET provider='drive'", (user_id,))


def migrate_to_drive(user_id, course_id, audio_id):
    """Verify the upload before switching the existing row; retain the local original."""
    from src import drive_audio
    with connection() as c:
        row = _owned(c, user_id, course_id, audio_id)
        if row.get('drive_file_id'):
            return
        content = (Path(database.DB_PATH).parent / 'study_audio' / Path(row['filename']).name).read_bytes()
        file_id = drive_audio.upload(user_id, row['filename'], row['mime'], content)
        try:
            c.execute('UPDATE study_audio SET drive_file_id=? WHERE id=?', (file_id, audio_id))
        except Exception:
            drive_audio.delete(user_id, file_id)
            raise
