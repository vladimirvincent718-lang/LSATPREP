"""Persistent, user-owned execution plans for mock review windows."""
from contextlib import contextmanager
from datetime import date
import json
import math

from src import database as db


@contextmanager
def connection():
    conn = db.get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_tasks():
    with connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS review_tasks (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            mock_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
            source_key TEXT NOT NULL, kind TEXT NOT NULL, source_id INTEGER,
            title TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '',
            due_date TEXT NOT NULL, estimated_minutes INTEGER NOT NULL DEFAULT 15,
            position INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
            attempt_id INTEGER, question_ids TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,mock_id,course_id,source_key));
        CREATE TABLE IF NOT EXISTS review_task_time (
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            minutes REAL NOT NULL CHECK(minutes>0), recorded_on TEXT NOT NULL);
        ''')
        if 'settings_json' not in {r['name'] for r in c.execute('PRAGMA table_info(review_tasks)')}:
            c.execute("ALTER TABLE review_tasks ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}'")


def _scope(c, user_id, mock_id, course_id):
    if not c.execute('SELECT 1 FROM mock_exam_schedule WHERE id=? AND user_id=?',
                     (mock_id, user_id)).fetchone():
        raise ValueError('This mock schedule is unavailable.')
    if not c.execute('''SELECT 1 FROM course_enrollments e JOIN courses c ON c.id=e.course_id
        WHERE e.user_id=? AND e.course_id=? AND e.enrollment_status='Active' AND c.is_active=1''',
                     (user_id, course_id)).fetchone():
        raise ValueError('Choose one of your active courses.')


def review_scope(user_id, mock_id):
    with connection() as c:
        return [dict(r) for r in c.execute('''SELECT * FROM mock_review_items
            WHERE user_id=? AND mock_schedule_id=?''', (user_id,mock_id))]


def topic_names(items, course_id):
    from src.practice_review_focus import topic_key
    return {topic_key(name) for item in items if item['course_id']==course_id
            for name in (item.get('topic_name'),item.get('match_topic_key')) if name}


def catalog(user_id, course_id, mock_id=None):
    from src import audio_study
    from src.practice_review_focus import topic_key
    audio_study.init_audio()
    names = topic_names(review_scope(user_id,mock_id),course_id) if mock_id is not None else None
    if names == set():
        return []
    result = [dict(key=f"material:{m['id']}", kind=m['material_type'], source_id=m['id'],
                   title=m['title'], topic=m.get('module_name') or '',
                   estimated_minutes=m.get('estimated_minutes') or 15)
              for m in db.get_materials(course_id)
              if names is None or names.intersection({topic_key(m.get('module_name')),topic_key(m['title'])})]
    with connection() as c:
        has_sheets = c.execute("SELECT 1 FROM sqlite_master WHERE name='material_review_sources'").fetchone()
        sheets = {r[0] for r in c.execute('SELECT material_id FROM material_review_sources')} if has_sheets else set()
    for material in result:
        if material['source_id'] in sheets or any(word in material['title'].casefold() for word in ('cheat sheet','cheatsheet')):
            material['category'] = 'Cheat sheets'
    from src import flashcards
    flashcards.init_flashcards()
    material_titles = {topic_key(m['title']) for m in result}
    result += [dict(key=f"flashcards:{d['id']}",kind='Flashcards',source_id=d['id'],title=d['title'],
                    topic=d['title'],estimated_minutes=max(5,math.ceil(d['total']/2)))
               for d in flashcards.list_decks(user_id,course_id)
               if d['total'] and (names is None or topic_key(d['title']) in names
                                  or topic_key(d['source']) in names or topic_key(d['source']) in material_titles)]
    for a in audio_study.library(user_id, course_id):
        if names is not None:
            assignments = [t for t in audio_study.targets(user_id,course_id,a['id']) if t['course_id']==course_id]
            matched = False
            with connection() as c:
                tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for target in assignments:
                    if not target['module_id']:
                        # A course overview covers all review topics in this course.
                        matched = True
                    for table, field in (('course_module_blueprints','module_id'),('course_chapters','chapter_id')):
                        if table in tables and target[field]:
                            row = c.execute(f'SELECT name FROM {table} WHERE id=? AND course_id=?',
                                            (target[field],course_id)).fetchone()
                            matched = matched or bool(row and topic_key(row['name']) in names)
            if not matched and not (not assignments and topic_key(a.get('topic')) in names):
                continue
        result.append(dict(key=f"audio:{a['id']}", kind='Audio', source_id=a['id'],
                    title=a['title'], topic=a.get('topic') or '',
                    estimated_minutes=max(1, math.ceil(a['duration']/60)) if a['duration'] else 15))
    return result


def add_task(user_id, mock_id, course_id, source, due_date):
    due = date.fromisoformat(str(due_date)).isoformat()
    with connection() as c:
        _scope(c, user_id, mock_id, course_id)
        from src.practice_review_focus import topic_key
        names = topic_names(review_scope(user_id,mock_id),course_id)
        if not names or (source['kind']=='Practice' and topic_key(source.get('topic')) not in names):
            raise ValueError('Choose a topic in this mock’s review plan.')
        if source['kind'] != 'Practice':
            source = next((s for s in catalog(user_id, course_id, mock_id) if s['key'] == source['key']), None)
            if source is None:
                raise ValueError('This resource is no longer available.')
        c.execute('''INSERT OR IGNORE INTO review_tasks
            (user_id,mock_id,course_id,source_key,kind,source_id,title,topic,due_date,estimated_minutes,position)
            VALUES (?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT MAX(position)+1 FROM review_tasks
                WHERE user_id=? AND mock_id=? AND course_id=?),0))''',
            (user_id,mock_id,course_id,source['key'],source['kind'],source.get('source_id'),
             source['title'],source.get('topic',''),due,source.get('estimated_minutes',15),
             user_id,mock_id,course_id))


def tasks(user_id, mock_id):
    with connection() as c:
        # Only the exact linked exam completes a practice task.
        c.execute('''UPDATE review_tasks SET completed=1 WHERE user_id=? AND mock_id=?
            AND attempt_id IN (SELECT id FROM exam_attempts WHERE user_id=? AND completed_at IS NOT NULL)''',
                  (user_id,mock_id,user_id))
        return [dict(r) for r in c.execute('''SELECT t.*, c.title AS course_title,
            COALESCE((SELECT SUM(minutes) FROM review_task_time x WHERE x.task_id=t.id),0) AS minutes
            FROM review_tasks t JOIN courses c ON c.id=t.course_id
            JOIN course_enrollments e ON e.course_id=t.course_id AND e.user_id=t.user_id
            WHERE t.user_id=? AND t.mock_id=? AND c.is_active=1 AND e.enrollment_status='Active'
            ORDER BY t.position,t.id''', (user_id,mock_id))]


def scoped_tasks(user_id,mock_id):
    from src.practice_review_focus import topic_key
    items = review_scope(user_id,mock_id)
    saved = tasks(user_id,mock_id)
    allowed = {cid: {s['key'] for s in catalog(user_id,cid,mock_id)}
               for cid in {r['course_id'] for r in saved if r['kind']!='Practice'}}
    return [r for r in saved if
            (r['kind']=='Practice' and practice_topics_in_scope(r,items)) or
            (r['kind']!='Practice' and r['source_key'] in allowed.get(r['course_id'],set()))]


def practice_topics_in_scope(task,items):
    from src.practice_review_focus import topic_key
    topics = json.loads(task.get('settings_json') or '{}').get('topics') or [task['topic']]
    return bool(topics) and {topic_key(t) for t in topics}.issubset(topic_names(items,task['course_id']))


def update_task(user_id, task_id, *, completed=None, due_date=None, minutes=None):
    with connection() as c:
        row = c.execute('SELECT * FROM review_tasks WHERE id=? AND user_id=?', (task_id,user_id)).fetchone()
        if row is None:
            raise ValueError('Task unavailable.')
        _scope(c,user_id,row['mock_id'],row['course_id'])
        if completed is not None:
            c.execute('UPDATE review_tasks SET completed=? WHERE id=?', (int(bool(completed)),task_id))
        if due_date is not None:
            due = date.fromisoformat(str(due_date)).isoformat()
            c.execute('UPDATE review_tasks SET due_date=? WHERE id=?', (due,task_id))
        if minutes is not None:
            if not math.isfinite(float(minutes)) or not 0 < float(minutes) <= 1440:
                raise ValueError('Enter review minutes between 0 and 1,440.')
            if row['kind'] in ('Audio','Practice'):
                raise ValueError('Audio and practice time are tracked by their players.')
            c.execute('INSERT INTO review_task_time(task_id,user_id,minutes,recorded_on) VALUES (?,?,?,?)',
                      (task_id,user_id,float(minutes),date.today().isoformat()))


def reorder(user_id, mock_id, course_id, ordered_ids):
    with connection() as c:
        _scope(c,user_id,mock_id,course_id)
        existing = {r['id'] for r in c.execute('SELECT id FROM review_tasks WHERE user_id=? AND mock_id=? AND course_id=?',
                                              (user_id,mock_id,course_id))}
        visible = {r['id'] for r in scoped_tasks(user_id,mock_id) if r['course_id']==course_id}
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != visible:
            raise ValueError('The plan changed. Refresh before arranging it again.')
        for position, task_id in enumerate([*ordered_ids,*sorted(existing-visible)]):
            c.execute('UPDATE review_tasks SET position=? WHERE id=?', (position,task_id))


def build_plan(user_id, mock_id, review_items):
    """Idempotent: refresh adds new work without resetting dates or completion."""
    from src.practice_review_focus import topic_key
    for item in review_items:
        if item['mock_schedule_id'] != mock_id or item.get('course_id') is None:
            continue
        topic = item.get('match_topic_key') or item['topic_name']
        due = item.get('review_deadline') or date.today().isoformat()
        source = dict(key=f"practice:{topic.casefold()}", kind='Practice',
                      title=f"Practice · {item['topic_name']}", topic=topic, estimated_minutes=15)
        add_task(user_id,mock_id,item['course_id'],source,due)
        normalized = topic_key(topic)
        for material in catalog(user_id,item['course_id'],mock_id):
            if material['kind']=='Audio' or normalized and normalized == topic_key(material['topic']):
                add_task(user_id,mock_id,item['course_id'],material,due)


def prepare_practice(user_id, task_id, count):
    """Save a fixed question set now so execution never requires rebuilding it."""
    from src.practice_review_focus import filter_review_questions, topic_key
    from src.question_ordering import arrange_question_dependencies
    import random
    if not 1 <= int(count) <= 180:
        raise ValueError('Choose 1–180 questions.')
    with connection() as c:
        row = c.execute('SELECT * FROM review_tasks WHERE id=? AND user_id=?', (task_id,user_id)).fetchone()
        if row is None or row['kind'] != 'Practice':
            raise ValueError('Practice task unavailable.')
        _scope(c,user_id,row['mock_id'],row['course_id'])
        if not practice_topics_in_scope(dict(row),review_scope(user_id,row['mock_id'])):
            raise ValueError('This practice topic is outside the selected review plan.')
        from src.practice_allocation import practice_questions
        pool = practice_questions([row['course_id']])
        settings = json.loads(row['settings_json'])
        topics = settings.get('topics') or [row['topic']]
        pool = filter_review_questions(pool,[{'course_id':row['course_id'],'key':topic_key(t)} for t in topics])
        saved = json.loads(row['question_ids'])
        if saved:
            by_id = {q['id']:q for q in pool}
            if any(qid not in by_id for qid in saved):
                raise ValueError('Some saved questions are unavailable. Add a new practice task.')
            return [dict(by_id[qid], _force_open_ended=True)
                    if str(by_id[qid].get('difficulty')) in settings.get('open_ended_levels',[]) else by_id[qid]
                    for qid in saved]
        if not pool:
            raise ValueError('No questions match this topic in the question bank yet.')
        selected = arrange_question_dependencies(random.sample(pool,min(int(count),len(pool))),pool)
        if not selected:
            raise ValueError('No complete question sets are available for this topic.')
        c.execute('UPDATE review_tasks SET question_ids=? WHERE id=?',
                  (json.dumps([q['id'] for q in selected]),task_id))
        return selected


def link_attempt(user_id, task_id, attempt_id):
    with connection() as c:
        task = c.execute('SELECT * FROM review_tasks WHERE id=? AND user_id=?', (task_id,user_id)).fetchone()
        if not task or task['kind'] != 'Practice' or task['attempt_id'] is not None:
            raise ValueError('This task is unavailable or already started.')
        _scope(c,user_id,task['mock_id'],task['course_id'])
        if not c.execute('SELECT 1 FROM exam_attempts WHERE id=? AND user_id=? AND course_id=?',
                         (attempt_id,user_id,task['course_id'])).fetchone():
            raise ValueError('Exam unavailable.')
        c.execute('UPDATE review_tasks SET attempt_id=? WHERE id=?', (attempt_id,task_id))
