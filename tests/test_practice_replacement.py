import pytest

from src.practice_replacement import closest_replacements, replacement_pool


def question(qid, course=1, module="Analysis of Taxes", **extra):
    return dict(id=qid, course_id=course, section_type=module, difficulty=3, **extra)


def test_cfa_widens_only_after_closer_scope_is_exhausted():
    current = question(1)
    pool = [current, question(2), question(3, module="Inventories"), question(4, course=2)]
    assert closest_replacements(current, pool, {1}) == ([pool[1]], "same chapter/module")
    assert closest_replacements(current, pool, {1, 2}) == ([pool[2]], "same course")
    assert closest_replacements(current, pool, {1, 2, 3}) == ([pool[3]], "same curriculum")
    assert closest_replacements(current, pool, {1, 2, 3, 4}) == ([], "")


def test_ccrn_prefers_actual_chapter_over_shared_topic():
    current = question(1, module="Clinical Judgment", chapter_id=10)
    other_chapter = question(2, module="Clinical Judgment", chapter_id=11)
    same_chapter = question(3, module="Clinical Judgment", chapter_id=10)
    same_chapter["difficulty"] = 5
    assert closest_replacements(current, [other_chapter, same_chapter], {1})[0] == [same_chapter]
    assert closest_replacements(current, [other_chapter, same_chapter], {1, 3}) == ([other_chapter], "same course")


def test_exclusions_and_difficulty_preference():
    current = question(1)
    same = question(2)
    harder = question(3)
    harder["difficulty"] = 5
    archived = question(4, is_archived=1)
    linked = question(5, stimulus="Based on the previous question, what is the answer?")
    assert closest_replacements(current, [same, harder, archived, linked], {1})[0] == [same]
    assert closest_replacements(current, [same, harder, archived, linked], {1, 2})[0] == [harder]


def test_pool_loads_beyond_session_but_stays_in_enrolled_curriculum(monkeypatch, tmp_path):
    from src import database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "replacement.db")
    database.init_database()
    database.init_curriculum_tables()
    conn = database.get_connection()
    curriculum = conn.execute("INSERT INTO curriculums(title) VALUES ('CFA')").lastrowid
    ids = []
    for i, title in enumerate(("Financial Statement Analysis", "Fixed Income", "CCRN", "Unenrolled")):
        cid = conn.execute("INSERT INTO courses(title) VALUES (?)", (title,)).lastrowid
        ids.append(cid)
        if i != 2:
            conn.execute("INSERT INTO curriculum_courses(curriculum_id,course_id) VALUES (?,?)", (curriculum, cid))
        conn.execute("INSERT INTO questions(course_id,question_id,section_type,difficulty,stimulus) VALUES (?,?,?,?,?)",
                     (cid, str(i), "Module", 3, "Question"))
    conn.commit()
    conn.close()
    pool = replacement_pool(question(1, course=ids[0]), ids[:3])
    assert {q["course_id"] for q in pool} == set(ids[:2])
    assert {q["course_id"] for q in replacement_pool(question(1, course=ids[2]), ids[:3])} == {ids[2]}


@pytest.mark.parametrize('with_pdf', [False, True])
def test_switch_button_expands_exhausted_session_pool(monkeypatch, tmp_path, with_pdf):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from src import auth, database, utils

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "switch.db")
    database.init_database()
    database.init_curriculum_tables()
    conn = database.get_connection()
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('switch','x')").lastrowid
    curriculum = conn.execute("INSERT INTO curriculums(title) VALUES ('CFA')").lastrowid
    courses = []
    for title in ("Financial Statement Analysis", "Fixed Income"):
        cid = conn.execute("INSERT INTO courses(title) VALUES (?)", (title,)).lastrowid
        courses.append(cid)
        conn.execute("INSERT INTO course_enrollments(user_id,course_id) VALUES (?,?)", (uid, cid))
        conn.execute("INSERT INTO curriculum_courses(curriculum_id,course_id) VALUES (?,?)", (curriculum, cid))
        conn.execute("INSERT INTO questions(course_id,question_id,section_type,difficulty,stimulus,choice_a,choice_b,correct_answer) VALUES (?,?,?,?,?,?,?,?)",
                     (cid, title, "Taxes", 3, "Question", "Yes", "No", "A"))
    conn.commit()
    conn.close()
    monkeypatch.setattr(auth, "require_login", lambda: uid)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *args: None)
    page = Path(__file__).resolve().parents[1] / "pages/5_Practice_Mode.py"
    app = AppTest.from_string(f'''
import runpy
import streamlit as st
from src.database import get_all_questions
from src.exam_engine import start_quiz
if 'exam_active' not in st.session_state:
    st.session_state['user_id'] = {uid}
    questions = get_all_questions(course_id={courses[0]})
    st.session_state['practice_question_pool'] = questions
    start_quiz({uid}, 'practice', questions, 'Taxes', time_limit_seconds=0, course_id={courses[0]})
    if {with_pdf!r}:
        from src.offline_exams import export_offline_exam
        export_offline_exam(user_id={uid}, attempt_id=st.session_state['exam_attempt_id'], questions=questions, title='Taxes')
runpy.run_path({str(page)!r})
''', default_timeout=30).run()
    assert not app.exception
    next(b for b in app.button if b.label == "Switch out question").click().run()
    assert not app.exception
    assert app.session_state["exam_questions"][0]["course_id"] == courses[1]
    assert any("same curriculum" in message.value for message in [*app.success, *app.info])
    replacement_id = app.session_state['exam_questions'][0]['id']
    next(b for b in app.button if b.label == 'Switch out question').click().run()
    assert not app.exception
    assert app.session_state['exam_questions'][0]['id'] == replacement_id
    assert any('Previously switched-out' in message.value for message in app.warning)
    if with_pdf:
        from src import offline_exams
        import json
        aid = app.session_state['exam_attempt_id']
        linked = offline_exams.exam_for_attempt(uid, aid)
        assert json.loads(linked['questions_json'])[0]['course_id'] == courses[1]
        assert len(offline_exams.list_offline_exams(uid)) == 2
        assert not app.error
        app.run()
        assert not app.exception
        assert len(offline_exams.list_offline_exams(uid)) == 2
