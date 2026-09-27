from datetime import datetime
from unittest.mock import call, patch
from zoneinfo import ZoneInfo

from src import exam_engine


def test_suspend_keeps_draft_and_clears_live_exam_state():
    session = {
        "user_id": 7,
        "exam_active": True,
        "exam_attempt_id": 42,
        "exam_mode": "curriculum_exam",
        "exam_questions": [{"id": 1}],
        "exam_answers": {0: "B"},
        "exam_time_limit": 0,
    }

    with (
        patch.object(exam_engine.st, "session_state", session),
        patch.object(exam_engine, "save_exam_draft", return_value=True) as save_draft,
        patch.object(exam_engine, "delete_exam_draft") as delete_draft,
    ):
        assert exam_engine.suspend_current_exam(7)

    save_draft.assert_called_once()
    delete_draft.assert_not_called()
    assert "exam_active" not in session
    assert "exam_attempt_id" not in session


def test_dashboard_button_state_is_never_saved_in_exam_drafts():
    assert not exam_engine._should_snapshot_key(
        "practice_dashboard_toggle_button_v2"
    )


def test_restore_can_target_one_of_multiple_drafts():
    session = {}
    selected_draft = {
        "attempt_id": 22,
        "mode": "curriculum_exam",
        "course_id": 5,
        "state": {
            "exam_active": True,
            "exam_attempt_id": 22,
            "exam_mode": "curriculum_exam",
            "exam_course_id": 5,
            "exam_questions": [{"id": 2}],
            "exam_answers": {"0": "C"},
            "exam_time_limit": 0,
            "ceb_stage": "running",
        },
    }

    with (
        patch.object(exam_engine.st, "session_state", session),
        patch.object(exam_engine, "get_exam_draft", return_value=selected_draft) as get_draft,
        patch.object(exam_engine, "save_exam_draft", return_value=True),
    ):
        restored = exam_engine.restore_exam_draft(
            7,
            modes={"curriculum_exam"},
            course_id=5,
            attempt_id=22,
        )

    assert restored
    get_draft.assert_called_once_with(7, 22)
    assert session["exam_attempt_id"] == 22
    assert session["exam_answers"] == {0: "C"}
    assert session["ceb_stage"] == "running"


def test_restore_discards_legacy_dashboard_button_state():
    session = {"practice_dashboard_toggle_button_v2": True}
    selected_draft = {
        "attempt_id": 23,
        "mode": "practice",
        "course_id": 5,
        "state": {
            "exam_active": True,
            "exam_attempt_id": 23,
            "exam_mode": "practice",
            "exam_course_id": 5,
            "exam_questions": [{"id": 2}],
            "exam_answers": {},
            "exam_time_limit": 0,
            "practice_dashboard_toggle_button_v2": False,
        },
    }

    with (
        patch.object(exam_engine.st, "session_state", session),
        patch.object(exam_engine, "get_exam_draft", return_value=selected_draft),
        patch.object(exam_engine, "save_exam_draft", return_value=True),
    ):
        restored = exam_engine.restore_exam_draft(
            7,
            modes={"practice"},
            attempt_id=23,
        )

    assert restored
    assert "practice_dashboard_toggle_button_v2" not in session
    assert session["exam_attempt_id"] == 23


def test_selected_draft_must_match_requested_mode():
    session = {}
    wrong_mode = {
        "attempt_id": 9,
        "mode": "full_exam",
        "course_id": 5,
        "state": {"exam_active": True},
    }

    with (
        patch.object(exam_engine.st, "session_state", session),
        patch.object(exam_engine, "get_exam_draft", return_value=wrong_mode),
    ):
        restored = exam_engine.restore_exam_draft(
            7,
            modes={"curriculum_exam"},
            attempt_id=9,
        )

    assert not restored
    assert session == {}


def test_previous_day_practice_is_finished_at_local_day_end():
    local_zone = ZoneInfo("America/New_York")
    yesterday_saved = datetime(2026, 9, 4, 20, 30, tzinfo=local_zone).timestamp()
    today_saved = datetime(2026, 9, 5, 8, 0, tzinfo=local_zone).timestamp()
    questions = [
        {"id": 101, "correct_answer": "A"},
        {"id": 102, "correct_answer": "C"},
        {"id": 103, "correct_answer": "D"},
    ]
    stale = {
        "attempt_id": 41,
        "mode": "practice",
        "state": {
            "exam_saved_at": yesterday_saved,
            "exam_questions": questions,
            "exam_answers": {"0": "A"},
            "exam_self_grades": {},
            "exam_flagged": {"__type__": "set", "items": [1]},
            "exam_section_num": 1,
            "practice_reached_questions": {"__type__": "set", "items": [0, 1]},
        },
    }
    current = {
        "attempt_id": 42,
        "mode": "practice",
        "state": {
            "exam_saved_at": today_saved,
            "exam_questions": questions,
            "practice_reached_questions": {"__type__": "set", "items": [0]},
        },
    }

    with (
        patch.object(exam_engine, "get_exam_drafts", return_value=[stale, current]),
        patch.object(exam_engine, "save_answer", return_value=True) as save_answer,
        patch.object(exam_engine, "complete_attempt") as complete_attempt,
        patch.object(exam_engine, "delete_exam_draft") as delete_draft,
        patch.object(exam_engine, "add_to_journal"),
    ):
        finalized = exam_engine.finalize_stale_practice_drafts(
            7,
            now=datetime(2026, 9, 5, 9, 0, tzinfo=local_zone),
        )

    assert finalized == [{
        "attempt_id": 41,
        "total": 2,
        "correct": 1,
        "incorrect": 1,
        "percent_correct": 50.0,
        "auto_finished": True,
    }]
    assert save_answer.call_count == 2
    assert save_answer.call_args_list == [
        call(
            attempt_id=41,
            question_id=101,
            selected="A",
            is_correct=True,
            time_spent=0.0,
            is_flagged=False,
            section_num=1,
            submitted_at="2026-09-05 03:59:59",
        ),
        call(
            attempt_id=41,
            question_id=102,
            selected="",
            is_correct=False,
            time_spent=0.0,
            is_flagged=True,
            section_num=1,
            submitted_at="2026-09-05 03:59:59",
        ),
    ]
    complete_attempt.assert_called_once()
    assert complete_attempt.call_args.kwargs["completed_at"] == "2026-09-05 03:59:59"
    delete_draft.assert_called_once_with(41)
