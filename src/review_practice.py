"""Configure and freeze queued practice exams using the existing question bank."""
from collections import Counter
from datetime import date
import json
import random
import uuid

from src import database as db, review_tasks as tasks
from src.practice_allocation import practice_questions
from src.practice_review_focus import filter_review_questions, topic_key
from src.question_ordering import arrange_question_dependencies
from src.analytics import get_smart_review_questions


def question_pool(user_id,mock_id,course_id,topics):
    allowed = tasks.topic_names(tasks.review_scope(user_id,mock_id),course_id)
    if not topics or not {topic_key(t) for t in topics}.issubset(allowed):
        raise ValueError('Choose topics in this mock’s review window.')
    with tasks.connection() as c:
        tasks._scope(c,user_id,mock_id,course_id)
    return filter_review_questions(practice_questions([course_id]),
                                   [{'course_id':course_id,'key':topic_key(t)} for t in topics])


def save_exam(user_id,mock_id,course_id,*,title,topics,quotas,due_date,order='Random',
              smart_review=False,timer_seconds=120,open_ended_levels=(),task_id=None):
    """Validate exact type/difficulty counts and save questions and settings atomically."""
    due = date.fromisoformat(str(due_date)).isoformat()
    if not str(title).strip():
        raise ValueError('Give the practice exam a name.')
    if order not in ('Random','By difficulty') or not 0<=int(timer_seconds)<=600:
        raise ValueError('Choose a valid order and timer between 0 and 600 seconds.')
    pool = question_pool(user_id,mock_id,course_id,topics)
    counts = {}
    selected = []
    for row in quotas:
        difficulty, kind, count = int(row['difficulty']),str(row['type']),row['count']
        if difficulty not in range(1,6) or isinstance(count,bool) or int(count)!=count or count<0:
            raise ValueError('Question counts must be nonnegative whole numbers.')
        key = (kind,difficulty)
        if key in counts:
            raise ValueError('Each question type and difficulty must appear only once.')
        counts[key] = int(count)
        bucket = [q for q in pool if (q.get('question_type') or 'Unspecified')==kind and int(q.get('difficulty') or 3)==difficulty]
        if count>len(bucket):
            raise ValueError(f'Only {len(bucket)} {kind} questions at difficulty {difficulty} are available.')
        selected.extend(get_smart_review_questions(user_id,bucket,n=int(count),course_id=course_id)
                        if smart_review and count else random.sample(bucket,int(count)))
    if not selected:
        raise ValueError('Select at least one question.')
    if order=='Random':
        random.shuffle(selected)
    else:
        selected.sort(key=lambda q:int(q.get('difficulty') or 3))
    selected = arrange_question_dependencies(selected,pool,target_count=len(selected))
    actual = Counter((q.get('question_type') or 'Unspecified',int(q.get('difficulty') or 3)) for q in selected)
    if actual != Counter({k:v for k,v in counts.items() if v}):
        raise ValueError('Linked questions cannot fit these exact counts. Adjust the counts or topics.')
    levels = sorted({str(int(d)) for d in open_ended_levels})
    if not set(levels).issubset({'1','2','3','4','5'}):
        raise ValueError('Choose a difficulty from 1 to 5 for open-ended mode.')
    settings = dict(topics=list(topics),quotas=[dict(type=k[0],difficulty=k[1],count=v) for k,v in counts.items()],
                    order=order,smart_review=bool(smart_review),timer_seconds=int(timer_seconds),open_ended_levels=levels)
    values = (str(title).strip(),topics[0],due,max(1,round(len(selected)*(timer_seconds or 120)/60)),
              json.dumps([q['id'] for q in selected]),json.dumps(settings))
    with tasks.connection() as c:
        tasks._scope(c,user_id,mock_id,course_id)
        if task_id is not None:
            task = c.execute('SELECT * FROM review_tasks WHERE id=? AND user_id=? AND mock_id=? AND course_id=?',
                             (task_id,user_id,mock_id,course_id)).fetchone()
            if not task or task['kind']!='Practice' or task['attempt_id'] or task['completed']:
                raise ValueError('Only an unstarted practice task can be configured.')
            c.execute('''UPDATE review_tasks SET title=?,topic=?,due_date=?,estimated_minutes=?,question_ids=?,settings_json=?
                WHERE id=?''',(*values,task_id))
        else:
            task_id = c.execute('''INSERT INTO review_tasks(title,topic,due_date,estimated_minutes,question_ids,settings_json,
                user_id,mock_id,course_id,kind,source_key,position) VALUES(?,?,?,?,?,?,?,?,?,'Practice',?,
                COALESCE((SELECT MAX(position)+1 FROM review_tasks WHERE user_id=? AND mock_id=? AND course_id=?),0))''',
                (*values,user_id,mock_id,course_id,'practice:'+uuid.uuid4().hex,user_id,mock_id,course_id)).lastrowid
    return task_id
