from collections import Counter
import random
import json
import pytest

from src import database
from src.neonatal_ccrn import (
    COURSE_TARGET, ensure_schema_and_catalog, get_batch_history, get_catalog,
    get_coverage, import_questions, recommend_next_batch, select_mock_questions,
    get_questions,
)


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "ccrn.db")
    database.init_database()
    course_id = ensure_schema_and_catalog()
    conn = database.get_connection()
    user_id = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES ('nurse', 'hash')"
    ).lastrowid
    conn.execute(
        "INSERT INTO course_enrollments (user_id, course_id) VALUES (?, ?)",
        (user_id, course_id),
    )
    conn.commit(); conn.close()
    return course_id, user_id


def _valid_row(module, chapter, suffix="1"):
    return {
        "module": module,
        "chapter": chapter,
        "question_text": f"Clinical question {suffix}?",
        "choice_a": "A option", "choice_b": "B option", "choice_c": "C option",
        "choice_d": "D option", "choice_e": "E option", "correct_answer": "A",
        "rationale": "Supplied rationale", "difficulty": 3, "tags": "neonatal",
        "source": "NotebookLM source", "source_page": "12",
        "clinical_condition": "Supplied condition", "quality_status": "Needs review",
    }


def test_catalog_targets_and_empty_bank(monkeypatch, tmp_path):
    course_id, user_id = _setup(monkeypatch, tmp_path)
    catalog = get_catalog(course_id)
    assert len(catalog) == 6
    assert sum(module["target_questions"] for module in catalog) == 3000
    assert sum(module["mock_questions"] for module in catalog) == 150
    assert sum(module["target_questions"] for module in catalog if module["area_name"] == "Clinical Judgment") == 2400
    assert sum(module["target_questions"] for module in catalog if module["area_name"] == "Professional Caring & Ethical Practice") == 600
    assert sum(len(module["chapters"]) for module in catalog) == 94
    coverage = get_coverage(course_id, user_id)
    assert coverage == {**coverage, "target": COURSE_TARGET, "actual": 0, "remaining": 3000, "variance": -3000, "completion": 0.0}


def test_next_batch_is_dynamic_and_always_exact(monkeypatch, tmp_path):
    course_id, _ = _setup(monkeypatch, tmp_path)
    initial = recommend_next_batch(150, course_id)
    assert sum(row["recommended"] for row in initial) == 150

    catalog = get_catalog(course_id)
    cardio = catalog[0]
    conn = database.get_connection()
    chapter_id = cardio["chapters"][0]["id"]
    for index in range(cardio["target_questions"]):
        conn.execute(
            """INSERT INTO questions
               (course_id, question_id, section_type, stimulus, content_hash, area_id, module_id, chapter_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (course_id, f"TEST-{index}", cardio["name"], f"Q {index}", f"hash-{index}", cardio["area_id"], cardio["id"], chapter_id),
        )
    conn.commit(); conn.close()
    updated = recommend_next_batch(150, course_id)
    assert sum(row["recommended"] for row in updated) == 150
    assert next(row for row in updated if row["name"] == "Cardiovascular")["recommended"] == 0


def test_import_batch_links_full_hierarchy_and_history(monkeypatch, tmp_path):
    course_id, _ = _setup(monkeypatch, tmp_path)
    catalog = get_catalog(course_id)
    module = catalog[1]
    chapter = module["chapters"][0]
    result = import_questions("CCRN Batch 001 — 2 Questions", [
        _valid_row(module["name"], chapter["name"], "1"),
        _valid_row(module["name"], chapter["name"], "2"),
    ], course_id)
    assert result["inserted"] == 2
    assert result["distribution"][module["name"]] == 2
    conn = database.get_connection()
    questions = conn.execute("SELECT * FROM questions WHERE import_batch_id=?", (result["batch_id"],)).fetchall()
    conn.close()
    assert len(questions) == 2
    assert all(q["area_id"] and q["module_id"] and q["chapter_id"] for q in questions)
    assert questions[0]["source_page"] == "12"
    assert "Supplied condition" in questions[0]["metadata_json"]
    history = get_batch_history(course_id)
    assert history[0]["questions_imported"] == 2
    respiratory = next(row for row in history[0]["modules"] if row["name"] == module["name"])
    assert (respiratory["before_count"], respiratory["added_count"], respiratory["after_count"]) == (0, 2, 2)


def test_invalid_import_is_atomic(monkeypatch, tmp_path):
    course_id, _ = _setup(monkeypatch, tmp_path)
    result = import_questions("Bad Batch", [_valid_row("Not a module", "Not a chapter")], course_id)
    assert result["inserted"] == 0
    assert result["errors"]
    assert get_coverage(course_id)["actual"] == 0
    assert get_batch_history(course_id) == []


def test_mock_reports_shortages_without_substitution(monkeypatch, tmp_path):
    course_id, user_id = _setup(monkeypatch, tmp_path)
    result = select_mock_questions(user_id, course_id=course_id)
    assert result["questions"] == []
    assert len(result["shortages"]) == 6
    assert sum(row["shortage"] for row in result["shortages"]) == 150


def test_mock_uses_exact_allocation_and_no_duplicates(monkeypatch, tmp_path):
    course_id, user_id = _setup(monkeypatch, tmp_path)
    catalog = get_catalog(course_id)
    conn = database.get_connection()
    expected = {}
    sequence = 0
    for module in catalog:
        expected[module["name"]] = module["mock_questions"]
        for _ in range(module["mock_questions"]):
            sequence += 1
            conn.execute(
                """INSERT INTO questions
                   (course_id, question_id, section_type, question_type, difficulty, stimulus,
                    content_hash, area_id, module_id, chapter_id)
                   VALUES (?, ?, ?, 'Multiple Choice', 3, ?, ?, ?, ?, ?)""",
                (course_id, f"MOCK-{sequence}", module["name"], f"Mock question {sequence}", f"mock-{sequence}",
                 module["area_id"], module["id"], module["chapters"][0]["id"]),
            )
    conn.commit(); conn.close()
    result = select_mock_questions(user_id, "Mostly New Questions", course_id, random.Random(7))
    assert result["shortages"] == []
    assert len(result["questions"]) == 150
    assert len({q["id"] for q in result["questions"]}) == 150
    assert Counter(q["section_type"] for q in result["questions"]) == expected
    assert len(select_mock_questions(user_id, course_id=course_id, difficulty=3)["questions"]) == 150
    filtered = select_mock_questions(user_id, course_id=course_id, difficulty=5)
    assert filtered["questions"] == []
    assert sum(s["shortage"] for s in filtered["shortages"]) == 150


def test_supplied_batches_round_trip_and_deduplicate(monkeypatch, tmp_path):
    from scripts.import_ccrn_supplied import CHAPTERS, NEUROLOGICAL, parse_supplied
    course_id, _ = _setup(monkeypatch, tmp_path)
    for section in CHAPTERS:
        rows = parse_supplied(section)
        assert len(rows) == 25
        result = import_questions(section, rows, course_id)
        assert not result["errors"]
        assert result["inserted"] == 25
        duplicate = import_questions(section + " repeat", rows, course_id)
        assert duplicate["inserted"] == 0
        assert duplicate["skipped_content"] == 25
        saved = get_questions(course_id, batch_id=result["batch_id"])
        by_number = {json.loads(q["metadata_json"])["source_question_number"]: q for q in saved}
        for row in rows:
            q = by_number[row["source_question_number"]]
            from src.import_math_text import readable_math
            assert q["stimulus"] == readable_math(row["question_text"])
            assert q["explanation"] == readable_math(row["rationale"])
            assert ("Why the other answers are wrong:" if section == NEUROLOGICAL else "Distractor Analysis:") in q["explanation"]
            assert "Clinical Pearl:" in q["explanation"]
            assert "Would you like" not in q["explanation"]
            assert q["correct_answer"] == row["correct_answer"]
            assert q["chapter_name"] == row["chapter"]
            assert q["module_name"] == section
            assert q["difficulty"] == 5
            assert q["choice_e"] == ""
            for letter in "abcd":
                assert q[f"choice_{letter}"] == readable_math(row[f"choice_{letter}"])
    assert len(get_questions(course_id, difficulty=5)) == 150
    mock = select_mock_questions(0, course_id=course_id, difficulty=5)
    assert mock["questions"] == []
    assert sorted(s["shortage"] for s in mock["shortages"]) == [5, 6, 6]
    assert get_questions(course_id, difficulty=3) == []


@pytest.mark.parametrize("difficulty", [None, "", "Stretch", "5"])
def test_four_choices_and_stretch_default(monkeypatch, tmp_path, difficulty):
    course_id, _ = _setup(monkeypatch, tmp_path)
    module = get_catalog(course_id)[0]
    row = _valid_row(module["name"], module["chapters"][0]["name"])
    row.pop("choice_e")
    row["difficulty"] = difficulty
    assert import_questions("Four options", [row], course_id)["inserted"] == 1
    assert get_questions(course_id)[0]["difficulty"] == 5
    row["correct_answer"] = "E"
    assert import_questions("Missing answer", [row], course_id)["errors"]


@pytest.mark.parametrize("letters", ["abc", "abce", "abde", "abcde"])
def test_variable_choice_counts_pass_review_and_import(monkeypatch, tmp_path, letters):
    from src.ccrn_import_ui import _draft_stage
    course_id, _ = _setup(monkeypatch, tmp_path)
    module = get_catalog(course_id)[0]
    row = _valid_row(module['name'], module['chapters'][0]['name'])
    for letter in 'abcde':
        if letter not in letters:
            row[f'choice_{letter}'] = ''
    draft = {'name': 'Saved three-choice batch', 'rows_json': json.dumps([row])}
    assert _draft_stage(course_id, draft)['code'] == 'ready'
    assert import_questions(draft['name'], [row], course_id)['inserted'] == 1
    saved = get_questions(course_id)[0]
    assert saved['correct_answer'] == 'A'
    for letter in 'abcde':
        assert bool(saved[f'choice_{letter}']) == (letter in letters)


def test_variable_choices_still_require_valid_answer_and_three_options(monkeypatch, tmp_path):
    course_id, _ = _setup(monkeypatch, tmp_path)
    module = get_catalog(course_id)[0]
    row = _valid_row(module['name'], module['chapters'][0]['name'])
    row.update(choice_d='', choice_e='', correct_answer='D')
    result = import_questions('Empty correct choice', [row], course_id)
    assert any('references an empty choice' in error for error in result['errors'])
    row.update(choice_c='', correct_answer='A')
    result = import_questions('Too few options', [row], course_id)
    assert any('at least three' in error for error in result['errors'])
    assert get_questions(course_id) == []


def test_page_filters_practice_and_starts_filtered_exam(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from src import auth, utils
    from scripts.import_ccrn_supplied import ROOT, parse_supplied
    course_id, user_id = _setup(monkeypatch, tmp_path)
    import_questions("Cardio", parse_supplied("Cardiovascular"), course_id)
    monkeypatch.setattr(auth, "require_login", lambda: user_id)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *a: None)
    at = AppTest.from_file(str(ROOT / "pages" / "4_Question_Bank_Manager.py"), default_timeout=30)
    at.session_state["qbm_course_id"] = course_id
    at.run()
    assert not at.exception
    assert at.selectbox(key="ccrn_exam_difficulty").value == 5
    at.selectbox(key="ccrn_exam_difficulty").set_value(3).run()
    next(b for b in at.button if b.label == "Start practice").click().run()
    assert not at.exception
    assert any("No questions match" in w.value for w in at.warning)
    at.selectbox(key="ccrn_exam_difficulty").set_value(5).run()
    next(b for b in at.button if b.label == "Start practice").click().run()
    assert not at.exception
    questions = at.session_state["exam_questions"]
    assert len(questions) == 10
    assert all(q["difficulty"] == 5 and q["section_type"] == "Cardiovascular" for q in questions)
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM exam_drafts").fetchone()[0] == 1
    conn.close()
