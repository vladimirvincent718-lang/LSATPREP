"""Concept recall and randomized, within-person delayed retention comparisons."""
import math
import random
import re
from datetime import datetime, timedelta, timezone

from src.audio_study import connection, _owned


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_recall():
    with connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS recall_sets (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
          title TEXT NOT NULL, lyrics TEXT NOT NULL, audio_id INTEGER,
          source TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS recall_concepts (
          id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL, prompt TEXT NOT NULL,
          answer TEXT NOT NULL, keywords TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
          due_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS recall_experiments (
          id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS recall_assignments (
          experiment_id INTEGER NOT NULL, concept_id INTEGER NOT NULL, method TEXT NOT NULL,
          trained_at TEXT, PRIMARY KEY(experiment_id,concept_id));
        CREATE TABLE IF NOT EXISTS recall_attempts (
          id TEXT PRIMARY KEY, concept_id INTEGER NOT NULL, level INTEGER NOT NULL,
          response TEXT NOT NULL, score REAL NOT NULL, seconds REAL NOT NULL,
          experiment_id INTEGER, phase TEXT NOT NULL DEFAULT 'practice', delay_days INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS recall_delayed_unique
          ON recall_attempts(experiment_id,concept_id,delay_days) WHERE phase='test';
        ''')


def _set(c, user_id, course_id, set_id):
    row = c.execute('SELECT * FROM recall_sets WHERE id=? AND user_id=? AND course_id=?', (set_id,user_id,course_id)).fetchone()
    if not row:
        raise ValueError('Recall set is not available in this course.')
    return dict(row)


def sets(user_id, course_id):
    with connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM recall_sets WHERE user_id=? AND course_id=? ORDER BY id DESC',(user_id,course_id))]


def save_set(user_id, course_id, title, lyrics, concepts, audio_id=None, source=''):
    clean = [dict(prompt=str(r.get('prompt','')).strip(),answer=str(r.get('answer','')).strip(),keywords=str(r.get('keywords','')).strip()) for r in concepts]
    clean = [r for r in clean if any(r.values())]
    if not title.strip() or not lyrics.strip() or not clean or any(not all(r.values()) for r in clean):
        raise ValueError('Add a title, lyrics and complete prompt, answer and keyword fields for each concept.')
    with connection() as c:
        if audio_id is not None: _owned(c,user_id,course_id,audio_id)
        sid=c.execute('INSERT INTO recall_sets(user_id,course_id,title,lyrics,audio_id,source) VALUES (?,?,?,?,?,?)',
                      (user_id,course_id,title.strip(),lyrics.strip(),audio_id,source)).lastrowid
        c.executemany('INSERT INTO recall_concepts(set_id,prompt,answer,keywords) VALUES (?,?,?,?)',
                      [(sid,r['prompt'],r['answer'],r['keywords']) for r in clean])
        return sid


def concepts(user_id,course_id,set_id):
    with connection() as c:
        _set(c,user_id,course_id,set_id)
        return [dict(r) for r in c.execute('SELECT * FROM recall_concepts WHERE set_id=? ORDER BY due_at,id',(set_id,))]


def update_set(user_id,course_id,set_id,title,lyrics,audio_id,source):
    if not title.strip() or not lyrics.strip():
        raise ValueError('A title and lyrics are required.')
    with connection() as c:
        _set(c,user_id,course_id,set_id)
        if audio_id is not None:_owned(c,user_id,course_id,audio_id)
        c.execute('UPDATE recall_sets SET title=?,lyrics=?,audio_id=?,source=? WHERE id=?',
                  (title.strip(),lyrics.strip(),audio_id,source.strip(),set_id))


def rubric(keywords):
    return [[s.strip() for s in group.split('|') if s.strip()] for group in keywords.split(';') if group.strip()]


def suggest_score(response,keywords):
    """Transparent keyword hints; the learner confirms conceptual correctness."""
    norm=lambda s:' '.join(re.findall(r'\w+',s.casefold()))
    text=' '+norm(response)+' '
    groups=rubric(keywords)
    found=[any(' '+norm(alias)+' ' in text for alias in group) for group in groups]
    return {'score':sum(found)/len(found) if found else 0,'missing':[' / '.join(g) for g,ok in zip(groups,found) if not ok]}


def masked_lyrics(lyrics,keywords,level):
    if level==1:return lyrics
    if level==2:
        for alias in sorted({a for g in rubric(keywords) for a in g},key=len,reverse=True):
            lyrics=re.sub(r'(?<!\w)'+re.escape(alias)+r'(?!\w)','____',lyrics,flags=re.I)
        return lyrics
    if level==3:return '\n'.join(''.join(re.findall(r'\[\d+:\d+(?:\.\d+)?\]',line))+'________________' if i%2==0 and line.strip() else line for i,line in enumerate(lyrics.splitlines()))
    return 'Recall the concepts using the music.' if level==4 else ''


def start_experiment(user_id,course_id,set_id):
    with connection() as c:
        row=_set(c,user_id,course_id,set_id)
        ids=[r['id'] for r in c.execute('SELECT id FROM recall_concepts WHERE set_id=?',(set_id,))]
        if len(ids)<2 or not row['audio_id']:
            raise ValueError('Add a song and at least two comparable concepts before starting a comparison.')
        if c.execute('SELECT id FROM recall_experiments WHERE set_id=?',(set_id,)).fetchone():
            raise ValueError('This set already has a retention comparison.')
        random.SystemRandom().shuffle(ids)
        eid=c.execute('INSERT INTO recall_experiments(set_id) VALUES (?)',(set_id,)).lastrowid
        c.executemany('INSERT INTO recall_assignments(experiment_id,concept_id,method) VALUES (?,?,?)',
                      [(eid,cid,'Music' if i%2==0 else 'Standard') for i,cid in enumerate(ids)])
        return eid


def experiment(user_id,course_id,set_id):
    with connection() as c:
        _set(c,user_id,course_id,set_id)
        return [dict(r) for r in c.execute('''SELECT a.*,q.prompt,q.answer,q.keywords FROM recall_assignments a
            JOIN recall_experiments e ON e.id=a.experiment_id JOIN recall_concepts q ON q.id=a.concept_id
            WHERE e.set_id=? ORDER BY q.id''',(set_id,))]


def attempts(user_id,course_id,set_id):
    with connection() as c:
        _set(c,user_id,course_id,set_id)
        return [dict(r) for r in c.execute('''SELECT a.*,q.prompt,x.method FROM recall_attempts a
            JOIN recall_concepts q ON q.id=a.concept_id LEFT JOIN recall_assignments x
            ON x.experiment_id=a.experiment_id AND x.concept_id=a.concept_id
            WHERE q.set_id=? ORDER BY a.created_at,a.id''',(set_id,))]


def record_attempt(user_id,course_id,set_id,concept_id,attempt_id,level,response,score,seconds,
                   experiment_id=None,phase='practice',delay_days=None,at=None):
    at=at or now()
    if level not in range(1,6) or not math.isfinite(score) or not 0<=score<=1 or not math.isfinite(seconds) or seconds<0 or not response.strip():
        raise ValueError('Enter a recall response and a valid score.')
    if phase not in ('practice','training','test') or (phase=='practice') != (experiment_id is None):
        raise ValueError('Invalid attempt type.')
    with connection() as c:
        _set(c,user_id,course_id,set_id)
        q=c.execute('SELECT * FROM recall_concepts WHERE id=? AND set_id=?',(concept_id,set_id)).fetchone()
        if not q:raise ValueError('Concept not found.')
        if c.execute('SELECT id FROM recall_attempts WHERE id=?',(attempt_id,)).fetchone():return
        if experiment_id is not None:
            assignment=c.execute('SELECT * FROM recall_assignments WHERE experiment_id=? AND concept_id=?',(experiment_id,concept_id)).fetchone()
            if not assignment:raise ValueError('Concept not assigned to this experiment.')
            if phase=='test':
                if level!=5 or delay_days not in (1,7,14) or not assignment['trained_at'] or at<datetime.fromisoformat(assignment['trained_at'])+timedelta(days=delay_days):
                    raise ValueError('This non-musical delayed test is not due yet.')
                if c.execute("SELECT id FROM recall_attempts WHERE experiment_id=? AND concept_id=? AND phase='test' AND delay_days=?",(experiment_id,concept_id,delay_days)).fetchone():
                    return
            elif assignment['trained_at']:
                raise ValueError('Initial training has already been recorded.')
        previous=c.execute('SELECT created_at FROM recall_attempts WHERE concept_id=? ORDER BY created_at DESC LIMIT 1',(concept_id,)).fetchone()
        c.execute('INSERT INTO recall_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (attempt_id,concept_id,level,response,score,seconds,experiment_id,phase,delay_days,at.isoformat(sep=' ')))
        # Repeated practice in one day must not turn one good session into mastery.
        advance=not previous or previous['created_at'][:10]!=at.date().isoformat()
        stage=min(q['stage']+1,5) if score>=.8 and advance else q['stage'] if score>=.8 else 0
        due=at+timedelta(days=(1,3,7,14,30,60)[stage])
        c.execute('UPDATE recall_concepts SET stage=?,due_at=? WHERE id=?',(stage,due.isoformat(sep=' '),concept_id))
        if phase=='training':
            c.execute('UPDATE recall_assignments SET trained_at=? WHERE experiment_id=? AND concept_id=?',
                      (at.isoformat(sep=' '),experiment_id,concept_id))
