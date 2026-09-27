import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from src import database, question_notes
from src import notebook
from src.question_explanations import get_new_question_explanations, get_question_explanation, save_question_explanation
from src.question_notes import get_question_notes, save_question_notes


@pytest.fixture
def notes_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "notes.db")
    conn = database.get_connection()
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE questions (id INTEGER PRIMARY KEY, course_id INTEGER, section_type TEXT,
            question_id TEXT, chapter_id INTEGER);
        INSERT INTO users VALUES (1), (2);
        INSERT INTO questions VALUES (10, 14, 'Long-Term Assets', 'CC-0286', NULL),
            (20, 15, 'Other module', 'OTHER-1', NULL);
    """)
    conn.close()


def test_notes_scope_edit_clear_and_explanation_count(notes_db):
    save_question_explanation(1, 10, "Explanation")
    before = get_new_question_explanations(1, "2000-01-01", "2100-01-01")
    save_question_notes(1, 10, "  First idea  ")
    save_question_notes(2, 10, "Private to user 2")
    assert get_question_notes(1, 10) == "First idea"
    assert get_question_notes(1, 20) == ""
    save_question_notes(1, 10, "A revised idea")
    assert get_question_notes(1, 10) == "A revised idea"
    assert get_question_notes(2, 10) == "Private to user 2"
    save_question_notes(1, 10, " \n ")
    assert get_question_notes(1, 10) == ""
    assert get_question_notes(2, 10) == "Private to user 2"
    assert get_question_explanation(1, 10) == "Explanation"
    assert get_new_question_explanations(1, "2000-01-01", "2100-01-01") == before
    with pytest.raises(sqlite3.IntegrityError):
        save_question_notes(1, 999, "Missing question")


APP = '''
from src.question_explanations import render_personal_explanation
from src.question_notes import render_question_notes
render_personal_explanation(1, {"id": 10})
render_question_notes(1, {"id": 10})
'''


def test_notes_below_explanation_save_reload_edit_and_clear(notes_db):
    save_question_explanation(1, 10, "Reasoning")
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert [e.label for e in app.expander] == ["Your saved explanation", "Edit your explanation", "Add notes"]
    app.text_area[1].set_value("Remember to revisit amortization")
    app.button[1].click().run()
    assert not app.exception
    assert app.success[0].value == "Notes saved."
    revisited = AppTest.from_string(APP).run()
    assert revisited.text_area[1].value == "Remember to revisit amortization"
    revisited.text_area[1].set_value("Updated reminder")
    revisited.button[1].click().run()
    assert get_question_notes(1, 10) == "Updated reminder"
    revisited.run()
    revisited.text_area[1].set_value("")
    revisited.button[1].click().run()
    assert not revisited.exception
    assert get_question_notes(1, 10) == ""


def test_failed_notes_save_preserves_text(notes_db, monkeypatch):
    save_question_notes(1, 10, "Existing notes")

    def fail(*args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(question_notes, "save_question_notes", fail)
    app = AppTest.from_string(APP).run()
    app.text_area[1].set_value("Keep my idea")
    app.button[1].click().run()
    assert not app.exception
    assert app.error
    assert app.text_area[1].value == "Keep my idea"
    assert get_question_notes(1, 10) == "Existing notes"


def test_saved_notes_have_formatted_reading_view_and_collapsed_editor(notes_db):
    source = (
        r"$$ \text{CA} \rightarrow \text{Undiscounted CF} \rightarrow \text{Fair Value} $$"
        "\n\nThen IFRS feels simpler because it skips that first recoverability screen:\n\n"
        r"$$ \text{Recoverable Amount}=\max(\text{VIU},\text{FVLCTS}) $$"
        "\n\n" + r"Answer: \(\boxed{$8,000}\)"
    )
    app = AppTest.from_string(APP).run()
    app.text_area[1].set_value(source)
    app.button[1].click().run()
    assert not app.exception
    expected = source.replace(r"\(\boxed{$8,000}\)", r"$\boxed{\$8,000}$")
    assert any(m.value == expected for m in app.markdown)
    editor = next(e for e in app.expander if e.label == "Edit your notes")
    assert not editor.proto.expanded
    assert editor.text_area[0].value == source
    assert get_question_notes(1, 10) == source
    revisited = AppTest.from_string(APP).run()
    assert not revisited.exception
    assert any(m.value == expected for m in revisited.markdown)


def test_notebook_routing_and_two_way_edits(notes_db):
    save_question_notes(1, 10, "Asset shortcut")
    note = notebook.list_notes(1, 14, chapter='Long-Term Assets')[0]
    assert note['body'] == 'Asset shortcut'
    assert note['question_id'] == 10
    assert 'CC-0286' in note['source']
    assert not notebook.list_notes(1, 15)
    assert not notebook.list_notes(2, 14)
    notebook.save_note(1, 14, 'My shortcut', 'Notebook edit', note['chapter'], note['source'], True, note['id'])
    assert get_question_notes(1, 10) == 'Notebook edit'
    save_question_notes(1, 10, 'Practice edit')
    notes = notebook.list_notes(1, 14)
    assert len(notes) == 1
    assert notes[0]['title'] == 'My shortcut'
    assert notes[0]['pinned'] == 1
    assert notes[0]['body'] == 'Practice edit'
    notebook.delete_note(1, 14, note['id'])
    assert get_question_notes(1, 10) == ''
    assert not notebook.list_notes(1, 14)


def test_chapter_routing_and_legacy_migration(notes_db):
    conn = database.get_connection()
    with conn:
        conn.executescript('''
            CREATE TABLE course_chapters (id INTEGER PRIMARY KEY, course_id INTEGER, name TEXT);
            INSERT INTO course_chapters VALUES (7, 14, 'Impairment');
            UPDATE questions SET chapter_id=7 WHERE id=10;
            CREATE TABLE user_question_notes (user_id INTEGER, question_id INTEGER, notes TEXT,
                created_at TEXT, updated_at TEXT, PRIMARY KEY (user_id, question_id));
            INSERT INTO user_question_notes VALUES
                (1,10,'Earlier idea','2026-09-17 08:00:00','2026-09-17 08:01:00');
        ''')
    conn.close()
    notebook.init_notebook()
    note = notebook.list_notes(1, 14, chapter='Long-Term Assets / Impairment')[0]
    assert note['body'] == 'Earlier idea'
    assert note['created_at'] == '2026-09-17 08:00:00'
    assert note['updated_at'] == '2026-09-17 08:01:00'
    notebook.init_notebook()
    assert len(notebook.list_notes(1, 14)) == 1
    notebook.delete_note(1, 14, note['id'])
    notebook.init_notebook()
    assert not notebook.list_notes(1, 14)
    assert get_question_notes(1, 10) == ''


def test_notebook_edit_refreshes_practice_editor(notes_db):
    save_question_notes(1, 10, 'Original')
    app = AppTest.from_string(APP).run()
    note = notebook.list_notes(1, 14)[0]
    notebook.save_note(1, 14, note['title'], 'Changed in notebook', note['chapter'], note_id=note['id'])
    app.run()
    assert not app.exception
    assert app.text_area[1].value == 'Changed in notebook'
