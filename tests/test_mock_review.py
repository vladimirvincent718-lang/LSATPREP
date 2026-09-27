from datetime import date, datetime, timedelta
import pytest

from src import database, mock_review
from src.practice_review_focus import scheduled_review, review_topics, filter_review_questions


def test_manual_scores_survive_schedule_edits_and_validate_ownership(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    dates = [date(2026, 9, 4), date(2026, 9, 19)]
    mock_review.save_mock_schedule(1, dates)
    first, second = mock_review.get_mock_schedule(1)
    mock_review.save_mock_scores(1, [{"id": first["id"], "manual_score": 62.22,
                                      "score_provider": "Kaplan Schweser"}])
    mock_review.save_mock_schedule(1, [dates[0], date(2026, 9, 20)])
    first, second = mock_review.get_mock_schedule(1)
    assert first["manual_score"] == 62.22
    assert first["score_provider"] == "Kaplan Schweser"
    assert first["completed_at"] is None
    assert second["manual_score"] is None
    for invalid in (-1, 101, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            mock_review.save_mock_scores(1, [{"id": first["id"], "manual_score": invalid}])
    with pytest.raises(ValueError):
        mock_review.save_mock_scores(2, [{"id": first["id"], "manual_score": 80}])
    with pytest.raises(ValueError):
        mock_review.save_mock_scores(1, [{"id": first["id"], "manual_score": 80},
                                        {"id": 99999, "manual_score": 70}])
    assert mock_review.get_mock_schedule(1)[0]["manual_score"] == 62.22
    for score in (0, 100, None):
        mock_review.save_mock_scores(1, [{"id": first["id"], "manual_score": score}])
        assert mock_review.get_mock_schedule(1)[0]["manual_score"] == score


def test_manual_score_section_renders_and_saves(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    _build_database(monkeypatch, tmp_path)
    mock_review.save_mock_schedule(1, [date(2026, 9, 4), date(2026, 9, 19)])
    first = mock_review.get_mock_schedule(1)[0]
    mock_review.save_mock_scores(1, [{"id": first["id"], "manual_score": 62.22,
                                      "score_provider": "Kaplan Schweser"}])
    page = (Path(__file__).parents[1] / "pages/8a_Mock_Review.py").read_text(encoding="utf-8")
    section = page.split('st.markdown("### Mock exam scores")', 1)[1].split('schedule_tab, modules_tab, review_tab', 1)[0]
    app = AppTest.from_string(
        "import streamlit as st\nimport pandas as pd\n"
        "from src.mock_review import get_mock_schedule, save_mock_scores\nuser_id = 1\n" + section
    ).run()
    assert not app.exception
    assert app.metric[0].value == "62.22%"
    app.button[0].click().run()
    assert not app.exception
    assert app.success[0].value == "Mock scores saved."
    assert mock_review.get_mock_schedule(1)[1]["manual_score"] is None


def test_practice_review_rolls_over_all_twenty_dates_and_keeps_last():
    start = date(2026, 1, 1)
    schedule = [{"id": i + 1, "scheduled_date": (start + timedelta(days=i * 7)).isoformat()}
                for i in range(20)]
    assert scheduled_review([], start) is None
    assert scheduled_review(schedule, start - timedelta(days=1))["id"] == 1
    for i in range(20):
        assert scheduled_review(schedule, start + timedelta(days=i * 7))["id"] == i + 1
        assert scheduled_review(schedule, start + timedelta(days=i * 7 + 6))["id"] == i + 1
    assert scheduled_review(schedule, start + timedelta(days=200))["id"] == 20


def test_practice_review_matches_course_and_reading_parent_without_broadening():
    questions = [
        {"id": 1, "course_id": 10, "section_type": "Learning Module 9: Income Taxes"},
        {"id": 2, "course_id": 11, "section_type": "Learning Module 9: Income Taxes"},
        {"id": 3, "course_id": 10, "section_type": "Learning Module 10: Deferred Income Taxes"},
        {"id": 4, "course_id": 10, "section_type": "Cardiac", "practice_module_label": "Cardiac / Assessment"},
    ]
    topics = [{"course_id": 10, "key": "income taxes"}, {"course_id": 10, "key": "cardiac"}]
    assert [q["id"] for q in filter_review_questions(questions, topics)] == [1, 4]
    assert filter_review_questions(questions, []) == []


def test_practice_focus_adds_new_mock_weaknesses_to_saved_plan(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    today = date.today()
    mock_review.save_mock_schedule(1, [today, today + timedelta(days=7)])
    first, second = mock_review.get_mock_schedule(1)
    mock_review.save_review_module_plan(1, first["id"], 20, {
        10: [{"topic_name": "Reading A", "match_topic": "Topic A"}],
    })
    assert [t["key"] for t in review_topics(1, first["id"])] == ["topic a"]
    conn = database.get_connection()
    conn.execute("INSERT INTO exam_attempts VALUES (100, 1, 10, 'mock_exam', ?)", (_stamp(today),))
    conn.execute("INSERT INTO user_answers VALUES (1, 100, 2, 0, ?)", (_stamp(today),))
    conn.commit()
    conn.close()
    mock_review.sync_mock_reviews(1)
    assert [t["key"] for t in review_topics(1, first["id"])] == ["topic a", "topic b"]
    assert review_topics(1, second["id"]) == []
    assert review_topics(2, first["id"]) == []
    assert review_topics(1, 99999) == []
    # Completed history retained by the planner must not resurrect a removed selection.
    item = mock_review.get_mock_review_items(1, status="all")[0]
    mock_review.update_review_item(1, item["id"], status_override="Complete", notes="Done")
    mock_review.save_review_module_plan(1, first["id"], 20, {})
    assert [t["key"] for t in review_topics(1, first["id"])] == ["topic b"]


def _build_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "mock_review.db")
    conn = database.get_connection()
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE curriculums (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE curriculum_courses (
            id INTEGER PRIMARY KEY,
            curriculum_id INTEGER,
            course_id INTEGER,
            display_order INTEGER
        );
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY,
            course_id INTEGER,
            section_type TEXT,
            question_type TEXT
        );
        CREATE TABLE exam_attempts (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            course_id INTEGER,
            mode TEXT,
            completed_at TEXT
        );
        CREATE TABLE user_answers (
            id INTEGER PRIMARY KEY,
            attempt_id INTEGER,
            question_id INTEGER,
            is_correct INTEGER,
            submitted_at TEXT
        );
        INSERT INTO users VALUES (1, 'learner', 'hash');
        INSERT INTO courses VALUES (10, 'Financial Reporting');
        INSERT INTO curriculums VALUES (20, 'CFA Level I');
        INSERT INTO curriculum_courses VALUES (1, 20, 10, 0);
        INSERT INTO questions VALUES (1, 10, 'Topic A', 'Type');
        INSERT INTO questions VALUES (2, 10, 'Topic B', 'Type');
        INSERT INTO questions VALUES (3, 10, 'Topic C', 'Type');
        INSERT INTO questions VALUES (4, 10, 'Topic D', 'Type');
        """
    )
    conn.commit()
    conn.close()
    mock_review.ensure_mock_review_schema()


def _stamp(day: date, hour: int = 12) -> str:
    return datetime.combine(day, datetime.min.time()).replace(hour=hour).isoformat(sep=" ")


def test_equal_allocation_and_automatic_practice_completion(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    start = date.today()
    next_mock = start + timedelta(days=8)
    mock_review.save_mock_schedule(1, [start, next_mock])

    conn = database.get_connection()
    conn.execute(
        "INSERT INTO exam_attempts VALUES (100, 1, 10, 'mock_exam', ?)",
        (_stamp(start),),
    )
    for answer_id, question_id in enumerate(range(1, 5), start=1):
        conn.execute(
            "INSERT INTO user_answers VALUES (?, 100, ?, 0, ?)",
            (answer_id, question_id, _stamp(start)),
        )
    review_day = start + timedelta(days=3)
    conn.execute(
        "INSERT INTO exam_attempts VALUES (200, 1, 10, 'practice', ?)",
        (_stamp(review_day),),
    )
    conn.execute(
        "INSERT INTO user_answers VALUES (20, 200, 2, 1, ?)",
        (_stamp(review_day),),
    )
    conn.commit()
    conn.close()

    mock_review.sync_mock_reviews(1)

    rows = sorted(mock_review.get_mock_review_items(1, status="all"), key=lambda row: row["topic_name"])
    assert [row["days_allocated"] for row in rows] == [2, 2, 2, 2]
    assert [row["review_deadline"] for row in rows] == [
        (start + timedelta(days=1)).isoformat(),
        (start + timedelta(days=3)).isoformat(),
        (start + timedelta(days=5)).isoformat(),
        (start + timedelta(days=7)).isoformat(),
    ]
    topic_b = next(row for row in rows if row["topic_name"] == "Topic B")
    assert topic_b["date_reviewed"] == review_day.isoformat()
    assert topic_b["review_status"] == "Complete"
    assert topic_b["retest_score"] == 100.0
    assert len(mock_review.get_mock_review_items(1, status="unfinished")) == 3

    window = mock_review.get_window_summary(1)[0]
    assert window == {
        "mock_label": "Mock 1/2",
        "days_until_next_mock": 8,
        "days_allocated": 8,
        "unallocated_buffer": 0,
    }
    countdown = mock_review.get_next_mock_summary(1, today=start)
    assert countdown["review_items_total"] == 4
    assert countdown["review_items_complete"] == 1
    assert countdown["review_items_remaining"] == 3
    assert countdown["review_progress_label"] == "1 reviewed of 4"


def test_partial_practice_and_manual_override(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    start = date.today()
    mock_review.save_mock_schedule(1, [start, start + timedelta(days=7)])
    conn = database.get_connection()
    conn.execute("INSERT INTO exam_attempts VALUES (100, 1, 10, 'mock_exam', ?)", (_stamp(start),))
    conn.execute("INSERT INTO user_answers VALUES (1, 100, 1, 0, ?)", (_stamp(start),))
    conn.execute("INSERT INTO exam_attempts VALUES (200, 1, 10, 'practice', NULL)")
    conn.execute(
        "INSERT INTO user_answers VALUES (2, 200, 1, 1, ?)",
        (_stamp(start + timedelta(days=1)),),
    )
    conn.commit()
    conn.close()

    mock_review.sync_mock_reviews(1)
    item = mock_review.get_mock_review_items(1, status="all")[0]
    assert item["review_status"] == "In Progress"
    assert item["date_reviewed"] is None

    assert mock_review.update_review_item(
        1, item["id"], status_override="Complete", notes="Reviewed offline"
    )
    assert mock_review.get_mock_review_items(1, status="unfinished") == []
    completed = mock_review.get_mock_review_items(1, status="complete")[0]
    assert completed["notes"] == "Reviewed offline"


def test_recurring_topic_creates_separate_historical_rows(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    first = date.today() - timedelta(days=16)
    second = date.today() - timedelta(days=8)
    third = date.today()
    mock_review.save_mock_schedule(1, [first, second, third])
    conn = database.get_connection()
    for attempt_id, mock_day in ((100, first), (300, second)):
        conn.execute(
            "INSERT INTO exam_attempts VALUES (?, 1, 10, 'mock_exam', ?)",
            (attempt_id, _stamp(mock_day)),
        )
        conn.execute(
            "INSERT INTO user_answers VALUES (?, ?, 1, 0, ?)",
            (attempt_id, attempt_id, _stamp(mock_day)),
        )
    conn.commit()
    conn.close()

    mock_review.sync_mock_reviews(1)
    topic_rows = [
        row for row in mock_review.get_mock_review_items(1, status="all")
        if row["topic_name"] == "Topic A"
    ]
    assert len(topic_rows) == 2
    assert len({row["mock_schedule_id"] for row in topic_rows}) == 2


def test_allocation_distributes_remainder_to_earliest_items():
    assert mock_review.allocate_review_days(10, 4) == [3, 3, 2, 2]
    assert mock_review.allocate_review_days(2, 4) == [1, 1, 0, 0]
    assert mock_review.allocate_review_days(8, 0) == []


def test_countdown_skips_a_completed_mock_scheduled_today(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    today = date.today()
    future = today + timedelta(days=8)
    mock_review.save_mock_schedule(1, [today, future])
    conn = database.get_connection()
    conn.execute("INSERT INTO exam_attempts VALUES (100, 1, 10, 'mock_exam', ?)", (_stamp(today),))
    conn.execute("INSERT INTO user_answers VALUES (1, 100, 1, 0, ?)", (_stamp(today),))
    conn.commit()
    conn.close()
    mock_review.sync_mock_reviews(1)

    summary = mock_review.get_next_mock_summary(1, today=today)
    assert summary["label"] == "Mock 2/2"
    assert summary["days_remaining"] == 8


def test_editing_a_date_preserves_the_schedule_record(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    first = date.today()
    second = first + timedelta(days=8)
    mock_review.save_mock_schedule(1, [first, second])
    original = mock_review.get_mock_schedule(1)

    edited_second = second + timedelta(days=2)
    mock_review.save_mock_schedule(1, [first, edited_second])
    edited = mock_review.get_mock_schedule(1)

    assert [row["id"] for row in edited] == [row["id"] for row in original]
    assert edited[1]["scheduled_date"] == edited_second.isoformat()


def test_selected_curriculum_modules_drive_queue_and_ignore_outside_practice(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    start = date.today()
    end = start + timedelta(days=8)
    mock_review.save_mock_schedule(1, [start, end])
    first_mock = mock_review.get_mock_schedule(1)[0]

    mock_review.save_review_module_plan(
        1,
        first_mock["id"],
        20,
        {10: [
            {"topic_name": "Reading Alpha", "match_topic": "Topic A"},
            {"topic_name": "Topic C", "match_topic": "Topic C"},
        ]},
    )
    conn = database.get_connection()
    # This completed Topic A practice is outside the review window and must not count.
    outside = start - timedelta(days=1)
    conn.execute(
        "INSERT INTO exam_attempts VALUES (400, 1, 10, 'practice', ?)",
        (_stamp(outside),),
    )
    conn.execute(
        "INSERT INTO user_answers VALUES (40, 400, 1, 1, ?)",
        (_stamp(outside),),
    )
    # Topic B was missed on the mock, but the saved module plan is authoritative.
    conn.execute(
        "INSERT INTO exam_attempts VALUES (500, 1, 10, 'mock_exam', ?)",
        (_stamp(start),),
    )
    conn.execute(
        "INSERT INTO user_answers VALUES (50, 500, 2, 0, ?)",
        (_stamp(start),),
    )
    conn.commit()
    conn.close()

    mock_review.sync_mock_reviews(1)
    rows = sorted(mock_review.get_mock_review_items(1, status="all"), key=lambda row: row["topic_name"])

    assert [row["topic_name"] for row in rows] == ["Reading Alpha", "Topic C"]
    assert [row["days_allocated"] for row in rows] == [4, 4]
    assert rows[0]["review_status"] == "Pending"
    assert rows[0]["date_reviewed"] is None
    saved = mock_review.get_review_module_plan(1, first_mock["id"])
    assert saved["curriculum_id"] == 20
    assert saved["selections"] == {10: ["Reading Alpha", "Topic C"]}

    # The same module practiced inside the window completes its linked reading.
    inside = start + timedelta(days=2)
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO exam_attempts VALUES (600, 1, 10, 'practice', ?)",
        (_stamp(inside),),
    )
    conn.execute(
        "INSERT INTO user_answers VALUES (60, 600, 1, 1, ?)",
        (_stamp(inside),),
    )
    conn.commit()
    conn.close()
    mock_review.sync_mock_reviews(1)
    reading = next(
        row for row in mock_review.get_mock_review_items(1, status="all")
        if row["topic_name"] == "Reading Alpha"
    )
    assert reading["review_status"] == "Complete"
    assert reading["date_reviewed"] == inside.isoformat()
    detected = mock_review.get_review_window_practice_sessions(1, first_mock["id"])
    assert [session["attempt_id"] for session in detected] == [600]


def test_current_review_mock_reports_position_and_exact_window(monkeypatch, tmp_path):
    _build_database(monkeypatch, tmp_path)
    today = date.today()
    mock_review.save_mock_schedule(
        1,
        [today - timedelta(days=2), today + timedelta(days=10), today + timedelta(days=20)],
    )

    current = mock_review.get_current_review_mock(1, today=today)

    assert current["mock_label"] == "Mock 1/3"
    assert current["window_start"] == today - timedelta(days=2)
    assert current["window_end"] == today + timedelta(days=10)

    summary = mock_review.get_next_mock_summary(1, today=today)
    assert summary["review_items_remaining"] == 0
    assert summary["review_progress_label"] == "No modules selected"


def test_plan_editor_preserves_other_courses_and_reopens(monkeypatch, tmp_path):
    from src import study_progress
    # This planner fixture has only schedule tables, not the enrolled-course catalog.
    monkeypatch.setattr(study_progress, "render_course_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(database, "get_enrolled_courses", lambda *args: [])
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from src import auth, utils

    _build_database(monkeypatch, tmp_path)
    conn = database.get_connection()
    conn.execute("INSERT INTO courses VALUES (11, 'Equity')")
    conn.execute("INSERT INTO curriculum_courses VALUES (2, 20, 11, 1)")
    conn.commit()
    conn.close()
    start = date.today()
    mock_review.save_mock_schedule(1, [start, start + timedelta(days=12)])
    mock_id = mock_review.get_mock_schedule(1)[0]["id"]
    mock_review.save_review_module_plan(1, mock_id, 20, {11: ["Market Structure"]})
    monkeypatch.setattr(auth, "require_login", lambda: 1)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *args: None)
    monkeypatch.setattr(utils, "page_header", lambda *args: None)
    monkeypatch.setattr(database, "get_all_curriculums", lambda: [{"id": 20, "title": "CFA"}])
    monkeypatch.setattr(database, "get_curriculum_courses", lambda _: [
        {"id": 10, "title": "Financial Reporting"}, {"id": 11, "title": "Equity"}])
    monkeypatch.setattr(database, "get_course_modules", lambda course_id: [
        {"name": "Market Structure" if course_id == 11 else "Financial Statements"}])
    monkeypatch.setattr(database, "get_distinct_values", lambda *args, **kwargs: [])
    monkeypatch.setattr(database, "get_materials", lambda _: [])
    page = str(Path(__file__).resolve().parents[1] / "pages" / "8a_Mock_Review.py")
    app = AppTest.from_file(page, default_timeout=20).run()
    assert not app.exception
    editor_key = f"mock_review_plan_editor_{mock_id}_20"
    financial_label = "Financial Reporting · Module · Financial Statements"
    app.session_state[editor_key] = {
        "edited_rows": {}, "added_rows": [{"Module / reading": financial_label}], "deleted_rows": []}
    next(button for button in app.button if button.label == "Save review plan").click().run()
    assert not app.exception
    assert mock_review.get_review_module_plan(1, mock_id)["selections"] == {
        10: ["Financial Statements"], 11: ["Market Structure"]}

    # A fresh session loads the whole saved plan, including completed items.
    equity_item = next(item for item in mock_review.get_mock_review_items(1, "all")
                       if item["course_id"] == 11)
    mock_review.update_review_item(1, equity_item["id"], status_override="Complete", notes="Reviewed")
    reopened = AppTest.from_file(page, default_timeout=20).run()
    assert not reopened.exception
    plan_table = next(table for table in reopened.dataframe
                      if "Module / reading" in table.value.columns)
    assert len(plan_table.value) == 2
    metrics = {metric.label: metric.value for metric in reopened.metric}
    assert metrics["Outstanding"] == "1"
    assert metrics["Completed"] == "1"
    reopened.selectbox(key="mock_review_queue_status").select("Complete").run()
    queue_table = next(table.value for table in reopened.dataframe
                       if "Review Status" in table.value.columns)
    assert all(value.endswith('#Complete') for value in queue_table['Review Status'])
    assert 'Review Count' in queue_table.columns
    assert 'Questions' in queue_table.columns

    # Explicit row deletion removes unfinished work without discarding other rows.
    reopened.session_state[editor_key] = {
        "edited_rows": {}, "added_rows": [], "deleted_rows": [0]}
    next(button for button in reopened.button if button.label == "Save review plan").click().run()
    assert not reopened.exception
    assert mock_review.get_review_module_plan(1, mock_id)["selections"] == {11: ["Market Structure"]}


def test_delivered_history_includes_exams_and_scopes_window_and_owner(monkeypatch, tmp_path):
    from src.mock_review_ui import item_sessions, review_link
    _build_database(monkeypatch, tmp_path)
    start = date.today()
    end = start + timedelta(days=5)
    mock_review.save_mock_schedule(1, [start, end])
    mock_id = mock_review.get_mock_schedule(1)[0]["id"]
    conn = database.get_connection()
    for aid, owner, mode, completed, activity in [
        (1, 1, 'practice', _stamp(start), _stamp(start)),
        (2, 1, 'full_exam', _stamp(start), _stamp(start)),
        (3, 1, 'practice', None, _stamp(start)),
        (4, 2, 'practice', _stamp(start), _stamp(start)),
        (5, 1, 'practice', _stamp(end), _stamp(end)),
    ]:
        conn.execute('INSERT INTO exam_attempts VALUES (?, ?, 10, ?, ?)', (aid, owner, mode, completed))
        for qid in (1, 2):
            conn.execute('INSERT INTO user_answers VALUES (?, ?, ?, 1, ?)', (aid * 10 + qid, aid, qid, activity))
    conn.commit()
    conn.close()
    sessions = mock_review.get_review_window_practice_sessions(1, mock_id, include_exams=True)
    assert {s['attempt_id'] for s in sessions} == {1, 2, 3}
    assert len({s['attempt_id'] for s in sessions if s['completed_at']}) == 2
    assert {s['attempt_id'] for s in mock_review.get_review_window_practice_sessions(1, mock_id)} == {1, 3}
    matched = item_sessions({'course_id': 10, 'topic_key': 'reading', 'match_topic_key': 'topic a'}, sessions)
    assert len(matched) == 3
    assert review_link('<unsafe>', attempt=2) == '<a target="_self" href="a_Mock_Review?attempt=2">&lt;unsafe&gt;</a>'
    assert mock_review.get_review_window_practice_sessions(2, mock_id, include_exams=True) == []


def test_attempt_link_checks_owner_and_resumes_exact_draft(monkeypatch, tmp_path):
    import pytest
    from src import mock_review_ui, exam_engine
    _build_database(monkeypatch, tmp_path)
    conn = database.get_connection()
    conn.execute("INSERT INTO exam_attempts VALUES (42, 1, 10, 'practice', NULL)")
    conn.commit()
    conn.close()
    class Stop(Exception):
        pass
    calls = []
    def stop():
        raise Stop()
    monkeypatch.setattr(mock_review_ui.st, 'markdown', lambda *a, **k: None)
    monkeypatch.setattr(mock_review_ui.st, 'error', lambda message: calls.append(message))
    monkeypatch.setattr(mock_review_ui.st, 'stop', stop)
    with pytest.raises(Stop):
        mock_review_ui.open_attempt(2, '42')
    assert calls == ['This session is no longer available.']
    calls.clear()
    monkeypatch.setattr(database, 'get_exam_draft', lambda uid, aid: {'state': {'saved': True}})
    monkeypatch.setattr(exam_engine, 'is_active', lambda: True)
    monkeypatch.setattr(exam_engine, '_st', lambda key: 99)
    monkeypatch.setattr(exam_engine, 'suspend_current_exam', lambda uid: calls.append(('save', uid)))
    def restore(uid, **kwargs):
        calls.append(('restore', uid, kwargs['attempt_id']))
        return True
    monkeypatch.setattr(exam_engine, 'restore_exam_draft', restore)
    def switch(page):
        calls.append(('page', page))
        raise Stop()
    monkeypatch.setattr(mock_review_ui.st, 'switch_page', switch)
    with pytest.raises(Stop):
        mock_review_ui.open_attempt(1, '42')
    assert calls == [('save', 1), ('restore', 1, 42), ('page', 'pages/5_Practice_Mode.py')]


def test_review_aggregate_links_reconcile_to_contributing_exams():
    from src.mock_review_ui import review_table_rows
    item = {'id': 7, 'mock_schedule_id': 1, 'mock_label': 'Mock 1/2',
            'topic_display': 'Topic A', 'topic_key': 'topic a', 'course_id': 10,
            'review_status': 'Complete'}
    sessions = [dict(attempt_id=aid, course_id=10, module_name='Topic A',
                     questions=questions, correct=correct, completed_at=completed)
                for aid, questions, correct, completed in [
                    (1, 10, 8, '2026-09-10'), (2, 20, 10, '2026-09-11'),
                    (3, 2, 1, None)]]
    row = review_table_rows([item], {1: sessions})[0]
    assert row['Review Count'] == 'a_Mock_Review?item=7&scope=completed#2'
    assert row['Questions'] == 'a_Mock_Review?item=7#32'
    assert row['Retest Score'] == 'a_Mock_Review?item=7&scope=completed#60.0%25'
    assert row['Review Status'] == 'a_Mock_Review?item=7#Complete'
    single = review_table_rows([item], {1: sessions[:1]})[0]
    assert single['Review Status'] == 'a_Mock_Review?attempt=1#Complete'


def test_course_rollups_count_filtered_items_across_mocks_by_course_identity():
    from src.mock_review_ui import course_review_groups
    items = [
        dict(id=1, course_id=10, course_title='Equity', mock_schedule_id=1, review_status='Complete'),
        dict(id=2, course_id=20, course_title='Financial Statement Analysis', mock_schedule_id=1, review_status='Pending'),
        dict(id=3, course_id=20, course_title='Financial Statement Analysis', mock_schedule_id=1, review_status='In Progress'),
        dict(id=4, course_id=20, course_title='Financial Statement Analysis', mock_schedule_id=2, review_status='Complete'),
        dict(id=5, course_id=30, course_title='Equity', mock_schedule_id=1, review_status='Pending'),
    ]
    groups = course_review_groups(items)
    assert [g['course_id'] for g in groups] == [10, 20, 30]
    assert [i['id'] for i in groups[1]['items']] == [2, 3, 4]
    assert (groups[1]['complete'], groups[1]['outstanding']) == (1, 2)
    outstanding = course_review_groups([i for i in items if i['review_status'] != 'Complete'])
    assert [g['course_id'] for g in outstanding] == [20, 30]
    assert sum(len(g['items']) for g in outstanding) == 3
    assert all(g['complete'] == 0 for g in outstanding)
    assert course_review_groups([]) == []


def test_review_queue_course_layout_controls_and_detail_columns():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
from src.mock_review_ui import review_queue_table
items = [dict(id=1, mock_schedule_id=1, mock_label="Mock 1/2",
              course_id=10, course_title="Equity", topic_name="Market Structure",
              topic_display="Equity — Market Structure", topic_key="market structure",
              review_status="Complete"),
         dict(id=2, mock_schedule_id=1, mock_label="Mock 1/2",
              course_id=20, course_title="Financial Statement Analysis", topic_name="Income Taxes",
              topic_display="Financial Statement Analysis — Income Taxes", topic_key="income taxes",
              review_status="Pending")]
review_queue_table(items, {1: []})
''').run()
    assert not app.exception
    assert len(app.expander) == 2
    assert 'Equity · 1 item · 0 outstanding · 1 complete' == app.expander[0].label
    assert all(not e.proto.expanded for e in app.expander)
    app.button(key='mock_review_Expand all').click().run()
    assert not app.exception
    assert all(e.proto.expanded for e in app.expander)
    app.button(key='mock_review_Collapse all').click().run()
    assert all(not e.proto.expanded for e in app.expander)
    app.radio(key='mock_review_queue_layout').set_value('All readings').run()
    assert not app.exception
    assert len(app.expander) == 0
    assert len(app.dataframe) == 1
    frame = app.dataframe[0].value
    assert list(frame.columns).index('Course') + 1 == list(frame.columns).index('Topic/Reading')
    assert frame['Topic/Reading'].tolist() == ['Market Structure', 'Income Taxes']


def test_actual_exam_caps_final_review_and_is_not_a_mock(monkeypatch, tmp_path):
    from src.exam_planning import save_exam_plan
    _build_database(monkeypatch, tmp_path)
    today = date.today()
    last_mock = today - timedelta(days=1)
    exam = today + timedelta(days=9)
    mock_review.save_mock_schedule(1, [last_mock])
    save_exam_plan(1, 20, exam, "09:00")
    row = mock_review.get_mock_schedule(1)[0]
    mock_review.save_review_module_plan(1, row['id'], 20, {10: ['Topic A']})
    mock_review.sync_mock_reviews(1)
    assert len(mock_review.get_mock_schedule(1)) == 1
    assert mock_review.get_mock_schedule(1)[0]['mock_label'] == 'Mock 1/1'
    current = mock_review.get_current_review_mock(1, today=today)
    assert current['window_end'] == exam
    assert mock_review.get_current_review_mock(1, today=exam) is None
    assert mock_review.get_next_mock_summary(1, today=today) is None
    item = mock_review.get_mock_review_items(1, status='all')[0]
    assert item['review_deadline'] == (exam - timedelta(days=1)).isoformat()
    assert mock_review.get_review_schedule(1)[-1]['is_actual_exam']
    assert len(mock_review.get_review_schedule(2)) == 0
    # The final window still reconciles practice, but excludes exam-day work.
    conn = database.get_connection()
    for aid, day in [(201, today), (202, exam)]:
        conn.execute("INSERT INTO exam_attempts VALUES (?, 1, 10, 'practice', ?)", (aid, _stamp(day)))
        conn.execute("INSERT INTO user_answers VALUES (?, ?, 1, 1, ?)", (aid, aid, _stamp(day)))
    conn.commit()
    conn.close()
    mock_review.sync_mock_reviews(1)
    sessions = mock_review.get_review_window_practice_sessions(1, row['id'])
    assert [session['attempt_id'] for session in sessions] == [201]
    item = mock_review.get_mock_review_items(1, status='all')[0]
    assert item['matched_practice_attempt_id'] == 201


def test_exam_date_validation_and_edit_preserve_schedule(monkeypatch, tmp_path):
    import pytest
    from src.exam_planning import save_exam_plan, get_exam_plan
    _build_database(monkeypatch, tmp_path)
    mock_review.save_mock_schedule(1, [date(2026, 9, 19)])
    save_exam_plan(1, 20, date(2026, 11, 17), "09:00")
    before = mock_review.get_mock_schedule(1)
    for invalid in (date(2026, 11, 17), date(2026, 11, 18)):
        with pytest.raises(ValueError):
            mock_review.save_mock_schedule(1, [invalid])
    with pytest.raises(ValueError):
        save_exam_plan(1, 20, date(2026, 9, 19), "09:00")
    assert mock_review.get_mock_schedule(1) == before
    assert get_exam_plan(1)['exam_date'] == '2026-11-17'
    save_exam_plan(1, 20, date(2026, 11, 10), "10:00")
    assert mock_review.get_review_schedule(1)[-1]['scheduled_date'] == '2026-11-10'


def test_exam_countdown_and_metric_archiving(monkeypatch):
    from src import exam_planning
    plan = {'exam_date': '2026-11-17', 'exam_time': '09:00'}
    assert exam_planning.exam_countdown(plan, date(2026, 9, 17))[0] == '61'
    assert exam_planning.exam_countdown(plan, date(2026, 11, 17))[0] == 'Today'
    assert exam_planning.exam_countdown(plan, date(2026, 11, 18))[0] == 'Passed'
    assert exam_planning.exam_countdown(None)[0] == '—'
    metrics = ['Days till exam', 'Daily target', 'Correct', 'Incorrect']
    monkeypatch.setattr(exam_planning, 'get_setting', lambda *args: '')
    assert exam_planning.visible_metrics(1, metrics) == metrics[:2]
    monkeypatch.setattr(exam_planning, 'get_setting', lambda *args: '[]')
    assert exam_planning.visible_metrics(1, metrics) == metrics
    monkeypatch.setattr(exam_planning, 'get_setting', lambda *args: __import__('json').dumps(metrics))
    assert exam_planning.visible_metrics(1, metrics) == []
