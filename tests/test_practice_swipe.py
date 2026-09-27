from pathlib import Path

from src.practice_swipe import skip_pass_indices


def test_skip_pass_only_contains_reached_unanswered_questions():
    assert skip_pass_indices(5, {0, 1, 3, 9}, {'0': 'A', 3: '__TIMEOUT__'}) == [1]
    assert skip_pass_indices(1, {0}, {}) == [0]


def test_swipe_navigation_preserves_drafts_and_does_not_score(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from src import auth, database, utils

    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'swipe.db')
    database.init_database()
    database.init_curriculum_tables()
    conn = database.get_connection()
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('swipe','x')").lastrowid
    cid = conn.execute("INSERT INTO courses(title) VALUES ('Swipe test')").lastrowid
    conn.execute('INSERT INTO course_enrollments(user_id,course_id) VALUES (?,?)', (uid, cid))
    for i in range(3):
        conn.execute("INSERT INTO questions(course_id,question_id,section_type,difficulty,stimulus,choice_a,choice_b,correct_answer) VALUES (?,?,?,?,?,?,?,?)",
                     (cid, str(i), 'LR', 1, f'Question {i}', 'Yes', 'No', 'A'))
    conn.commit()
    conn.close()
    database.set_setting(uid, 'practice_swipe_mode', 'true')
    monkeypatch.setattr(auth, 'require_login', lambda: uid)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *a: None)
    page = Path(__file__).resolve().parents[1] / 'pages/5_Practice_Mode.py'
    app = AppTest.from_string(f'''
import runpy
import streamlit as st
from src.database import get_all_questions
from src.exam_engine import start_quiz
if 'exam_active' not in st.session_state:
    st.session_state['user_id'] = {uid}
    start_quiz({uid}, 'practice', get_all_questions(course_id={cid}), 'LR', time_limit_seconds=0, course_id={cid})
runpy.run_path({str(page)!r})
''', default_timeout=30).run()
    assert not app.exception
    assert app.button(key='swipe_previous').disabled
    app.radio(key='q_radio_0').set_value('**A.** Yes').run()
    app.button(key='swipe_next').click().run()
    assert not app.exception
    assert app.session_state['exam_current_idx'] == 1
    assert app.session_state['exam_answers'] == {}
    app.button(key='swipe_previous').click().run()
    assert app.radio(key='q_radio_0').value == '**A.** Yes'
    next(b for b in app.button if b.label == '✔ Submit Answer').click().run()
    assert not app.exception
    assert app.session_state['exam_answers'][0] == 'A'
    app.button(key='swipe_jump_2').click().run()
    assert app.button(key='swipe_next').disabled
    app.button(key='swipe_skip_pass').click().run()
    assert app.session_state['exam_current_idx'] == 1
    assert app.session_state['exam_answers'] == {0: 'A'}
    app.toggle(key='swipe_mode_toggle').set_value(False).run()
    assert not app.exception
    assert database.get_setting(uid, 'practice_swipe_mode') == 'false'
