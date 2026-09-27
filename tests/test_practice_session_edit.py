import json
from pathlib import Path

import pytest

from src.practice_session_edit import (
    HISTORY_KEY, SCOPE_KEY, initialize_edit_state, addition_candidates,
    removal_error, remove_question_state, remove_saved_answer,
)


def question(qid, **kwargs):
    return dict(id=qid, course_id=1, section_type='Taxes', difficulty=3, **kwargs)


def test_removal_remaps_answers_flags_and_unsent_widgets():
    state = dict(exam_attempt_id=9, exam_questions=[question(i) for i in range(4)],
                 exam_answers={'0': 'A', '1': 'B', '3': 'C'},
                 exam_self_grades={'3': True}, exam_flagged={1, 3},
                 practice_reached_questions={0, 1, 3}, q_radio_1='B',
                 q_open_ended_2='Unsent draft', q_self_grade_3=True)
    remove_question_state(state, 1)
    assert [q['id'] for q in state['exam_questions']] == [0, 2, 3]
    assert state['exam_answers'] == {0: 'A', 2: 'C'}
    assert state['exam_self_grades'] == {2: True}
    assert state['exam_flagged'] == {2}
    assert state['practice_reached_questions'] == {0, 2}
    assert state['q_open_ended_1'] == 'Unsent draft'
    assert state['q_self_grade_2'] is True
    assert 'q_radio_1' not in state
    assert state[HISTORY_KEY] == {0, 1, 2, 3}
    remove_question_state(state, 2)
    assert state['exam_current_idx'] == 1


def test_additions_keep_original_scope_and_exclude_used_and_dependent_questions():
    state = dict(exam_attempt_id=9, exam_questions=[question(1, chapter_id=10), question(2, chapter_id=11)])
    initialize_edit_state(state)
    remove_question_state(state, 1)
    pool = [question(2, chapter_id=11), question(3, chapter_id=11),
            question(4, chapter_id=12), question(5, chapter_id=10, stimulus='Using data from Question 21'),
            question(6, chapter_id=10, stimulus='Use the previous question'),
            question(7, chapter_id=10, is_archived=1)]
    assert [q['id'] for q in addition_candidates(state, pool, 3)] == [3]
    assert addition_candidates(state, pool, 4) == []
    state['exam_attempt_id'] = 10
    initialize_edit_state(state)
    assert state[HISTORY_KEY] == {1}
    assert len(state[SCOPE_KEY]) == 1


def test_removal_protects_last_question_and_prerequisite():
    assert 'at least one' in removal_error([question(1)], 0)
    questions = [question(1), question(2, stimulus='Use the previous question')]
    assert 'next question' in removal_error(questions, 0)
    assert removal_error(questions, 1) == ''


@pytest.fixture
def practice_db(tmp_path, monkeypatch):
    from src import auth, database, utils
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'editing.db')
    database.init_database()
    database.init_curriculum_tables()
    conn = database.get_connection()
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('editing','x')").lastrowid
    cid = conn.execute("INSERT INTO courses(title) VALUES ('Financial Statement Analysis')").lastrowid
    conn.execute('INSERT INTO course_enrollments(user_id,course_id) VALUES (?,?)', (uid, cid))
    ids = []
    for i in range(7):
        ids.append(conn.execute('''INSERT INTO questions(course_id,question_id,section_type,difficulty,stimulus,choice_a,choice_b,correct_answer)
            VALUES (?,?,?,?,?,?,?,?)''', (cid, f'TAX-{i}', 'Taxes' if i < 6 else 'Other module',
                                       3, f'Compute the independent amount: {i}', 'Yes', 'No', 'A')).lastrowid)
    conn.commit()
    conn.close()
    monkeypatch.setattr(auth, 'require_login', lambda: uid)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *args: None)
    return uid, cid, ids


def test_live_add_remove_pdf_and_resume_preserve_question_identity(practice_db):
    from streamlit.testing.v1 import AppTest
    from src import database, offline_exams
    uid, cid, ids = practice_db
    page = Path(__file__).resolve().parents[1] / 'pages/5_Practice_Mode.py'
    app = AppTest.from_string(f'''
import runpy
import streamlit as st
from src.database import get_all_questions
from src.exam_engine import start_quiz, restore_exam_draft
from src.offline_exams import export_offline_exam
st.session_state['user_id'] = {uid}
if 'exam_active' not in st.session_state:
    questions = sorted(get_all_questions(course_id={cid}), key=lambda q: q['id'])[:3]
    start_quiz({uid}, 'practice', questions, 'Taxes', time_limit_seconds=0, course_id={cid})
    st.session_state['exam_answers'] = {{0: 'A', 1: 'B', 2: 'B'}}
    st.session_state['exam_current_idx'] = 1
    export_offline_exam(user_id={uid}, attempt_id=st.session_state['exam_attempt_id'], questions=questions, title='Editing')
if st.session_state.pop('test_restore', False):
    aid = st.session_state['exam_attempt_id']
    for key in list(st.session_state):
        if key.startswith(('exam_', 'practice_', 'q_')):
            del st.session_state[key]
    restore_exam_draft({uid}, attempt_id=aid)
runpy.run_path({str(page)!r})
''', default_timeout=30).run()
    assert not app.exception
    aid = app.session_state['exam_attempt_id']
    next(b for b in app.button if b.label == 'Remove current question').click().run()
    assert not app.exception
    assert app.session_state['exam_answers'] == {0: 'A', 1: 'B'}
    assert [q['id'] for q in app.session_state['exam_questions']] == [ids[0], ids[2]]
    assert {r['question_id'] for r in database.get_attempt_answers(aid)} == {ids[0], ids[2]}
    app.selectbox(key='practice_add_difficulty').set_value(3).run()
    app.number_input(key='practice_add_count').set_value(2).run()
    next(b for b in app.button if b.label == 'Add questions').click().run()
    assert not app.exception
    questions = app.session_state['exam_questions']
    assert len(questions) == 4
    assert {q['id'] for q in questions[2:]} <= set(ids[3:6])
    linked = offline_exams.exam_for_attempt(uid, aid)
    assert [q['id'] for q in json.loads(linked['questions_json'])] == [q['id'] for q in questions]
    exported = offline_exams.progress_pdf(uid, linked['serial'])
    result = offline_exams.inspect_submission(uid, linked['serial'], exported)
    assert [r['selected'] for r in result['rows']] == ['A', 'B', '', '']
    app.session_state['test_restore'] = True
    app.run()
    assert not app.exception
    assert app.session_state['exam_answers'] == {0: 'A', 1: 'B'}
    assert ids[1] in app.session_state[HISTORY_KEY]
    assert len(app.session_state['exam_questions']) == 4
    app.number_input(key='practice_add_count').set_value(5).run()
    next(b for b in app.button if b.label == 'Add questions').click().run()
    assert len(app.session_state['exam_questions']) == 4
    assert any('Only 1 matching' in w.value for w in app.warning)


def test_removing_saved_answer_preserves_other_attempts(practice_db):
    from src import database
    uid, _, ids = practice_db
    first = database.create_attempt(uid, 'practice', 'Taxes', {})
    second = database.create_attempt(uid, 'practice', 'Taxes', {})
    for aid in (first, second):
        database.save_answer(aid, ids[0], 'B', False, 1, False, 1)
    database.add_to_journal(uid, ids[0], second)
    remove_saved_answer(uid, second, ids[0])
    assert len(database.get_attempt_answers(first)) == 1
    assert database.get_attempt_answers(second) == []
    conn = database.get_connection()
    assert conn.execute('SELECT attempt_id FROM mistake_journal WHERE user_id=? AND question_id=?', (uid, ids[0])).fetchone()[0] == first
    conn.close()
