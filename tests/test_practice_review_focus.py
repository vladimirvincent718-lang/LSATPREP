"""Exercise the actual practice controls, persistence, and resulting exam pool."""

from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import auth, database, mock_review, utils
from src.practice_review_focus import AUTO_REVIEW_SETTING, CONTENT_MODE_SETTING, REVIEW_ID_SETTING


def test_review_selection_persists_rolls_over_and_scopes_exam(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "practice_review.db")
    database.init_database()
    database.init_curriculum_tables()
    conn = database.get_connection()
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('review_student','x')").lastrowid
    curriculum = conn.execute("INSERT INTO curriculums(title) VALUES ('Review Curriculum')").lastrowid
    courses = []
    for name in ("Course A", "Course B"):
        cid = conn.execute("INSERT INTO courses(title) VALUES (?)", (name,)).lastrowid
        courses.append(cid)
        conn.execute("INSERT INTO course_enrollments(user_id,course_id) VALUES (?,?)", (uid, cid))
        conn.execute("INSERT INTO curriculum_courses(curriculum_id,course_id) VALUES (?,?)", (curriculum, cid))
        for i, topic in enumerate(("Topic A", "Topic B")):
            conn.execute("""INSERT INTO questions(course_id,question_id,section_type,difficulty,
                         stimulus,choice_a,choice_b,correct_answer) VALUES (?,?,?,?,?,?,?,?)""",
                         (cid, f"{cid}-{i}", topic, 3, f"Question {i}", "Yes", "No", "A"))
    conn.commit()
    conn.close()
    today = date.today()
    mock_review.save_mock_schedule(uid, [today - timedelta(days=7), today, today + timedelta(days=7)])
    first, second, third = mock_review.get_mock_schedule(uid)
    mock_review.save_review_module_plan(uid, first["id"], curriculum, {courses[0]: ["Topic A"]})
    mock_review.save_review_module_plan(uid, second["id"], curriculum, {courses[1]: ["Topic B"]})
    monkeypatch.setattr(auth, "require_login", lambda: uid)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *args: None)
    path = str(Path(__file__).resolve().parents[1] / "pages/5_Practice_Mode.py")
    app = AppTest.from_file(path, default_timeout=30).run()
    app.radio(key=CONTENT_MODE_SETTING).set_value("Mock Review").run()
    assert not app.exception
    app.selectbox(key=REVIEW_ID_SETTING).set_value(first["id"]).run()
    assert app.multiselect(key="practice_course_ids").value == [courses[0]]
    assert app.session_state["practice_module_filters"] == ["Topic A"]
    assert database.get_setting(uid, REVIEW_ID_SETTING) == str(first["id"])

    # A new browser session restores the focus before any exam has been started.
    app = AppTest.from_file(path, default_timeout=30).run()
    assert not app.exception
    assert app.radio(key=CONTENT_MODE_SETTING).value == "Mock Review"
    assert app.selectbox(key=REVIEW_ID_SETTING).value == first["id"]
    app.toggle(key=AUTO_REVIEW_SETTING).set_value(True).run()
    assert not app.exception
    assert app.selectbox(key=REVIEW_ID_SETTING).disabled
    assert app.selectbox(key=REVIEW_ID_SETTING).value == second["id"]
    assert app.multiselect(key="practice_course_ids").value == [courses[1]]
    assert app.session_state["practice_module_filters"] == ["Topic B"]
    assert database.get_setting(uid, AUTO_REVIEW_SETTING) == "true"

    app = AppTest.from_file(path, default_timeout=30).run()
    assert app.toggle(key=AUTO_REVIEW_SETTING).value
    app.toggle(key=AUTO_REVIEW_SETTING).set_value(False).run()
    app.selectbox(key=REVIEW_ID_SETTING).set_value(third["id"]).run()
    assert not app.exception
    assert app.multiselect(key="practice_course_ids").value == []
    assert next(b for b in app.button if b.label == "Start Practice Exam").disabled
    app.selectbox(key=REVIEW_ID_SETTING).set_value(first["id"]).run()
    # The single vertical selector controls the actual exam pool; empty means none.
    assert not [m for m in app.multiselect if m.key == "practice_module_filters"]
    app.button(key="practice_module_filters_none").click().run()
    assert app.session_state["practice_module_filters"] == []
    assert next(b for b in app.button if b.label == "Start Practice Exam").disabled
    app.button(key="practice_module_filters_all").click().run()
    app.number_input(key="practice_difficulty_count_3").set_value(1).run()
    next(b for b in app.button if b.label == "Start Practice Exam").click().run()
    assert not app.exception
    questions = app.session_state["exam_questions"]
    assert len(questions) == 1
    assert questions[0]["course_id"] == courses[0]
    assert questions[0]["section_type"] == "Topic A"
    assert not [r for r in app.radio if r.key == CONTENT_MODE_SETTING]
