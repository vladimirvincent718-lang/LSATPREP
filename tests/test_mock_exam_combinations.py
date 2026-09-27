import math
from pathlib import Path

from src.mock_exam_combinations import (
    compact_combination_count, metric_drilldown_script,
    non_overlapping_mock_exams, possible_mock_exams,
)


def test_possible_mock_exams_uses_current_bank_and_adjustable_size():
    assert possible_mock_exams(600, 150) == math.comb(600, 150)
    assert possible_mock_exams(3000, 150) == math.comb(3000, 150)
    assert possible_mock_exams(600, 100) == math.comb(600, 100)


def test_same_questions_in_a_different_order_are_not_counted_twice():
    assert possible_mock_exams(4, 2) == 6
    assert possible_mock_exams(4, 4) == 1


def test_impossible_or_empty_mock_has_zero_combinations():
    assert possible_mock_exams(0, 1) == 0
    assert possible_mock_exams(10, 11) == 0
    assert possible_mock_exams(10, 0) == 0


def test_large_counts_are_compact_in_metric_card():
    value = math.comb(600, 150)
    assert compact_combination_count(value) == "146-digit total"
    assert compact_combination_count(6) == "6"


def test_non_overlapping_mock_count_is_practical_capacity():
    assert non_overlapping_mock_exams(600, 150) == 4
    assert non_overlapping_mock_exams(650, 150) == 4
    assert non_overlapping_mock_exams(3000, 150) == 20


def test_metric_drilldown_requires_double_click_and_opens_settings_button():
    script = metric_drilldown_script()
    assert "addEventListener('dblclick'" in script
    assert "Open mock estimate settings" in script
    assert "button.click()" in script


def test_dashboard_hides_parameters_until_metric_drilldown(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from src import auth, database, utils
    from src.neonatal_ccrn import ensure_schema_and_catalog

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "drilldown.db")
    database.init_database()
    course_id = ensure_schema_and_catalog()
    conn = database.get_connection()
    user_id = conn.execute(
        "INSERT INTO users(username,password_hash,is_admin) VALUES ('owner','x',1)"
    ).lastrowid
    module_id = conn.execute(
        "SELECT id FROM course_module_blueprints WHERE course_id=? ORDER BY id LIMIT 1", (course_id,)
    ).fetchone()[0]
    for number in range(6):
        conn.execute(
            "INSERT INTO questions(course_id,module_id,question_id,stimulus,choice_a,choice_b,correct_answer) VALUES (?,?,?,?,?,?,?)",
            (course_id,module_id,f'T-{number}',f'Question {number}','Correct','Wrong','A'),
        )
    conn.commit(); conn.close()
    monkeypatch.setattr(auth, "require_login", lambda: user_id)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *args: None)
    path = Path(__file__).resolve().parents[1] / "pages" / "4_Question_Bank_Manager.py"
    at = AppTest.from_file(str(path), default_timeout=30)
    at.session_state["qbm_course_id"] = course_id
    at.run()
    assert not at.exception
    assert not [item for item in at.number_input if item.label == "Estimated total questions in bank"]
    assert not [item for item in at.expander if item.label == "Show exact combination count"]
    capacity = next(item for item in at.metric if item.label == "6-Question Mock Capacity")
    assert capacity.value == "1 without repeats"
    at.button(key="ccrn_open_mock_estimate_settings").click().run()
    assert not at.exception
    estimated = next(item for item in at.number_input if item.label == "Estimated total questions in bank")
    mock_size = next(item for item in at.number_input if item.label == "Questions in each mock")
    assert estimated.value == 6
    assert mock_size.value == 6
    assert next(item for item in at.metric if item.label == "All unique question combinations").value == "1"
    assert [item for item in at.expander if item.label == "Show exact combination count"]
