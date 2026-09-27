import ast
from pathlib import Path
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from src import database
from src.question_explanations import get_question_explanation, save_question_explanation, get_new_question_explanations


@pytest.fixture
def explanation_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "explanations.db")
    conn = database.get_connection()
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE questions (id INTEGER PRIMARY KEY, explanation TEXT);
        INSERT INTO users VALUES (1), (2);
        INSERT INTO questions VALUES (10, 'Original explanation'), (20, NULL);
    """)
    conn.close()


def test_explanations_persist_and_are_scoped_to_user_and_question(explanation_db):
    assert get_question_explanation(1, 10) == ""
    save_question_explanation(1, 10, "  **Margin call**\n\n$5,000 − $3,800 = $1,200.  ")
    assert get_question_explanation(1, 10) == "**Margin call**\n\n$5,000 − $3,800 = $1,200."
    assert get_question_explanation(2, 10) == ""
    assert get_question_explanation(1, 20) == ""
    save_question_explanation(1, 10, "Updated reasoning")
    assert get_question_explanation(1, 10) == "Updated reasoning"
    conn = database.get_connection()
    assert conn.execute("SELECT explanation FROM questions WHERE id = 10").fetchone()[0] == "Original explanation"
    assert conn.execute("SELECT COUNT(*) FROM user_question_explanations").fetchone()[0] == 1
    conn.close()


def test_invalid_save_keeps_existing_explanation(explanation_db):
    save_question_explanation(1, 10, "Keep this")
    with pytest.raises(ValueError):
        save_question_explanation(1, 10, " \n ")
    assert get_question_explanation(1, 10) == "Keep this"
    with pytest.raises(sqlite3.IntegrityError):
        save_question_explanation(1, 999, "Unknown question")


def test_first_submission_count_uses_day_bounds_and_excludes_edits(explanation_db):
    save_question_explanation(1, 10, "First")
    save_question_explanation(1, 20, "Next day")
    save_question_explanation(2, 10, "Other user")
    conn = database.get_connection()
    with conn:
        conn.execute("UPDATE user_question_explanations SET created_at = '2026-09-17 04:00:00'")
        conn.execute("UPDATE user_question_explanations SET created_at = '2026-09-18 04:00:00' WHERE question_id = 20")
    conn.close()
    save_question_explanation(1, 10, "Edited")
    rows = get_new_question_explanations(1, "2026-09-17 04:00:00", "2026-09-18 04:00:00")
    assert len(rows) == 1
    assert rows[0] == dict(question_id=10, explanation="Edited", created_at="2026-09-17 04:00:00")
    assert len(get_new_question_explanations(1, "2026-09-18 04:00:00", "2026-09-19 04:00:00")) == 1
    assert get_new_question_explanations(1, "2026-09-16 04:00:00", "2026-09-17 04:00:00") == []


def test_legacy_migration_preserves_unknown_dates_and_tracks_new_saves(explanation_db):
    conn = database.get_connection()
    with conn:
        conn.executescript("""
            CREATE TABLE user_question_explanations (
                user_id INTEGER, question_id INTEGER, explanation TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, question_id));
            INSERT INTO user_question_explanations (user_id, question_id, explanation)
                VALUES (1, 10, 'Legacy');
        """)
    conn.close()
    assert get_question_explanation(1, 10) == "Legacy"
    save_question_explanation(1, 10, "Legacy edited")
    save_question_explanation(1, 20, "New")
    rows = get_new_question_explanations(1, "2000-01-01", "2100-01-01")
    assert [row["question_id"] for row in rows] == [20]
    assert rows[0]["created_at"]


APP = """
from src.question_explanations import render_personal_explanation
render_personal_explanation(1, {"id": 10})
"""


def test_saved_explanation_renders_pasted_math_without_changing_original(explanation_db):
    source = r"**Answer:** \(\boxed{$221.1\text{ million}}\)" + "\n\n" + r"$$24.8\% - 23.6\% = 1.2\%$$"
    save_question_explanation(1, 10, source)
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert app.markdown[0].value == (
        r"**Answer:** $\boxed{\$221.1\text{ million}}$" + "\n\n" + r"$$24.8\% - 23.6\% = 1.2\%$$"
    )
    assert app.text_area[0].value == source
    assert get_question_explanation(1, 10) == source


def test_save_edit_and_reload_explanation(explanation_db):
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert app.expander[0].label == "Add your own explanation (optional)"
    app.text_area[0].set_value("My saved reasoning")
    app.button[0].click().run()
    assert not app.exception
    assert "Explanation saved" in app.success[0].value
    assert app.markdown[0].value == "My saved reasoning"
    assert app.expander[1].label == "Edit your explanation"

    # A fresh session loads from SQLite, independently of quiz/session snapshots.
    revisited = AppTest.from_string(APP).run()
    assert revisited.markdown[0].value == "My saved reasoning"
    revisited.text_area[0].set_value("Better reasoning")
    revisited.button[0].click().run()
    assert get_question_explanation(1, 10) == "Better reasoning"
    revisited.run()  # Settle the explicit rerun after the successful form submit.
    revisited.text_area[0].set_value(" ")
    revisited.button[0].click().run()
    assert revisited.error
    assert get_question_explanation(1, 10) == "Better reasoning"


def test_failed_save_preserves_pasted_text(explanation_db, monkeypatch):
    from src import question_explanations

    def fail(*args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(question_explanations, "save_question_explanation", fail)
    app = AppTest.from_string(APP).run()
    app.text_area[0].set_value("Do not lose this explanation")
    app.button[0].click().run()
    assert not app.exception
    assert app.error
    assert app.text_area[0].value == "Do not lose this explanation"


@pytest.mark.parametrize("answered", [False, True])
def test_practice_supplied_rationale_is_visible_only_after_answer(answered):
    page = Path(__file__).resolve().parents[1] / "pages" / "5_Practice_Mode.py"
    call = next(
        node for node in ast.walk(ast.parse(page.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "render_question"
    )
    explanation_arg = next(kw.value for kw in call.keywords if kw.arg == "show_explanation")
    show_explanation = ast.literal_eval(explanation_arg)
    app = AppTest.from_string(f'''
from src.utils import render_question
render_question(
    q={{"id": 6300, "stimulus": "Why use LIFO?", "question_type": "Multiple Choice",
       "choice_a": "Higher taxes", "choice_b": "Lower taxes", "correct_answer": "B",
       "explanation": "Supplied rationale: higher COGS reduces taxable income.",
       "wrong_answer_a": "Cash taxes decrease."}},
    idx=0, total=1, selected={"'B'" if answered else "''"},
    show_answer={answered!r}, auto_expand_answer=True,
    show_explanation={show_explanation!r}, compact_actions=True,
)
''').run()
    assert not app.exception
    rationale_visible = any("Supplied rationale:" in item.value for item in app.info)
    assert rationale_visible is answered
    assert any("Cash taxes decrease." in item.value for item in app.caption) is answered
