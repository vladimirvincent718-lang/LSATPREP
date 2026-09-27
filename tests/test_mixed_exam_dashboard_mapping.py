from unittest.mock import patch

import pytest

from src import analytics, exam_engine


def _exam_state(mode: str) -> dict:
    return {
        "questions": [
            {"id": 101, "correct_answer": "A", "section_type": "Module 1"},
            {"id": 202, "correct_answer": "B", "section_type": "Module 2"},
        ],
        "answers": {0: "A", 1: "A"},
        "self_grades": {},
        "flagged": set(),
        "attempt_id": 77,
        "section_num": 1,
        "section_started": 100.0,
        "mode": mode,
        "timer_paused": False,
        "timer_paused_at": None,
    }


@pytest.mark.parametrize("mode", ["practice", "timed_section", "curriculum_exam", "full_exam"])
def test_submitted_quiz_modes_finalize_for_dashboard(mode):
    state = _exam_state(mode)

    with (
        patch.object(exam_engine, "_st", side_effect=lambda key: state.get(key)),
        patch.object(exam_engine, "_set", side_effect=lambda key, value: state.__setitem__(key, value)),
        patch.object(exam_engine, "save_answer") as save_answer,
        patch.object(exam_engine, "complete_attempt") as complete_attempt,
        patch.object(exam_engine, "add_to_journal"),
        patch.object(exam_engine, "delete_exam_draft"),
        patch.object(exam_engine.time, "time", return_value=110.0),
    ):
        report = exam_engine.submit_section(user_id=5)

    assert report["total"] == 2
    assert report["correct"] == 1
    assert save_answer.call_count == 2
    complete_attempt.assert_called_once()
    assert complete_attempt.call_args.args == (77,)
    assert complete_attempt.call_args.kwargs["total"] == 2
    assert complete_attempt.call_args.kwargs["correct"] == 1


def test_mixed_attempt_answers_are_attributed_to_each_questions_module():
    answers = [
        {
            "attempt_id": 77,
            "is_correct": True,
            "section_type": "Module 1",
            "question_type": "Type A",
            "difficulty": 2,
            "question_course_id": 10,
            "course_title": "Course A",
            "mode": "curriculum_exam",
            "completed_at": "2026-07-12 10:00:00",
        },
        {
            "attempt_id": 77,
            "is_correct": False,
            "section_type": "Module 1",
            "question_type": "Type A",
            "difficulty": 2,
            "question_course_id": 10,
            "course_title": "Course A",
            "mode": "curriculum_exam",
            "completed_at": "2026-07-12 10:00:00",
        },
        {
            "attempt_id": 77,
            "is_correct": True,
            "section_type": "Module 2",
            "question_type": "Type B",
            "difficulty": 3,
            "question_course_id": 10,
            "course_title": "Course A",
            "mode": "curriculum_exam",
            "completed_at": "2026-07-12 10:00:00",
        },
    ]

    with patch.object(analytics, "get_answer_stats", return_value=answers):
        stats = analytics.get_dashboard_stats(user_id=5, course_id=10)

    assert stats["total_attempts"] == 1
    assert stats["total_questions"] == 3
    assert stats["accuracy_by_module"]["Module 1"] == {
        "total": 2,
        "correct": 1,
        "pct": 50.0,
    }
    assert stats["accuracy_by_module"]["Module 2"] == {
        "total": 1,
        "correct": 1,
        "pct": 100.0,
    }
    assert stats["accuracy_by_module_difficulty"]["Module 1"][2] == {
        "total": 2,
        "correct": 1,
        "pct": 50.0,
    }
    assert stats["accuracy_by_module_difficulty"]["Module 2"][3] == {
        "total": 1,
        "correct": 1,
        "pct": 100.0,
    }
