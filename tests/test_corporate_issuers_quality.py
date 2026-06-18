import re
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "lsat_app.db"
V2_SOURCES = {
    "LM1CORPISS25V2",
    "LM2CORPISS25V2",
    "LM3CORPISS25V2",
    "LM4CORPISS25V2",
    "LM5CORPISS25V2",
}


def corporate_questions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM questions WHERE course_id = 9 AND COALESCE(is_archived, 0) = 0"
            )
        ]
    finally:
        conn.close()


def test_active_corporate_questions_have_valid_keys_and_unique_choices():
    for question in corporate_questions():
        answer = question["correct_answer"].lower()
        assert answer in "abcde", question["id"]
        choices = [
            str(question[f"choice_{letter}"] or "").strip().casefold()
            for letter in "abcde"
            if str(question[f"choice_{letter}"] or "").strip()
        ]
        assert question[f"choice_{answer}"], question["id"]
        assert len(choices) == len(set(choices)), question["id"]


def test_unreliable_v2_batch_is_not_active():
    assert not V2_SOURCES.intersection({question["source"] for question in corporate_questions()})


def test_active_questions_are_self_contained_and_not_truncated():
    for question in corporate_questions():
        stimulus = question["stimulus"] or ""
        assert not re.search(r"\bQuestion \d+\b|previous question", stimulus, re.I), question["id"]
        assert not stimulus.rstrip().endswith("$"), question["id"]


def test_reported_repairs_are_active_and_corrected():
    by_id = {question["id"]: question for question in corporate_questions()}
    assert by_id[1008]["choice_b"] == "Limited partnership"
    assert by_id[1008]["correct_answer"] == "B"
    assert "double taxation" in by_id[1010]["explanation"].lower()
    assert by_id[1017]["choice_c"] == "21"
    assert by_id[1017]["correct_answer"] == "C"
    assert by_id[1229]["choice_c"] == "47024"
    assert by_id[1229]["correct_answer"] == "C"
