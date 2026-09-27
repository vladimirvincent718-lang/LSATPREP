"""Private, editable notes attached to individual practice questions."""

import sqlite3

import streamlit as st

from src.database import get_connection
from src.notebook import init_notebook, question_note_location
from src.import_math_text import math_markdown


def ensure_question_notes_schema() -> None:
    init_notebook()


def get_question_notes(user_id: int, question_id: int) -> str:
    ensure_question_notes_schema()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT body FROM study_notes WHERE user_id = ? AND question_id = ?",
            (user_id, question_id),
        ).fetchone()
        return row["body"] if row else ""
    finally:
        conn.close()


def save_question_notes(user_id: int, question_id: int, notes: str) -> None:
    """Save the question's notepad, or clear it when the text is empty."""
    notes = notes.strip()
    ensure_question_notes_schema()
    conn = get_connection()
    try:
        with conn:
            if notes:
                course_id, chapter, title, source = question_note_location(conn, question_id)
                conn.execute(
                    """INSERT INTO study_notes (user_id, question_id, course_id, chapter, title, body, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, question_id) DO UPDATE SET
                           body = excluded.body, course_id = excluded.course_id,
                           chapter = excluded.chapter, updated_at = CURRENT_TIMESTAMP""",
                    (user_id, question_id, course_id, chapter, title, notes, source),
                )
            else:
                conn.execute(
                    "DELETE FROM study_notes WHERE user_id = ? AND question_id = ?",
                    (user_id, question_id),
                )
    finally:
        conn.close()


def render_question_notes(user_id: int, question: dict) -> None:
    question_id = question.get("id")
    if question_id is None:
        return
    key = f"question_notes_{user_id}_{question_id}"
    try:
        saved = get_question_notes(user_id, question_id)
    except sqlite3.Error:
        st.error("Your notes could not be loaded. Please try again.")
        return

    with st.expander("Add notes", expanded=bool(saved)):
        st.caption("Capture ideas, reminders, or questions to revisit. Saved to My Notebook under this question's course and chapter or module. Edits appear in both places.")
        notice = st.session_state.pop(f"{key}_notice", None)
        if notice:
            st.success(notice)
        if saved:
            st.markdown(math_markdown(saved))
        if (f"{key}_text" not in st.session_state
                or (st.session_state.get(f"{key}_loaded") != saved
                    and st.session_state.get(f"{key}_text") == st.session_state.get(f"{key}_loaded"))):
            st.session_state[f"{key}_text"] = saved
        st.session_state[f"{key}_loaded"] = saved
        editor = st.expander("Edit your notes", expanded=False) if saved else st.container()
        with editor, st.form(f"{key}_form"):
            notes = st.text_area(
                "Your notes", height=160, key=f"{key}_text",
                placeholder="What came to mind while working on this question?",
                help="Edit and save anytime. Emptying this field and saving also removes the linked notebook entry.",
            )
            if st.form_submit_button("Save notes"):
                try:
                    save_question_notes(user_id, question_id, notes)
                except ValueError as exc:
                    st.error(str(exc))
                except sqlite3.Error:
                    st.error("Could not save your notes. Your text is still here; please try again.")
                else:
                    st.session_state[f"{key}_notice"] = "Notes saved." if notes.strip() else "Notes cleared."
                    st.rerun()
