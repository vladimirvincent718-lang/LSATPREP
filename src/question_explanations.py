"""Personal explanations saved independently of shared question content."""

import sqlite3

import streamlit as st

from src.database import get_connection
from src.import_math_text import math_markdown


def ensure_question_explanations_schema() -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_question_explanations (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    explanation TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, question_id)
                )
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(user_question_explanations)")}
            if "created_at" not in columns:
                # The old updated_at cannot establish when an explanation was
                # first submitted. Leave historical creation dates unknown.
                conn.execute("ALTER TABLE user_question_explanations ADD COLUMN created_at TIMESTAMP")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_explanations_user_created "
                         "ON user_question_explanations(user_id, created_at)")
    finally:
        conn.close()


def get_question_explanation(user_id: int, question_id: int) -> str:
    # Also supports an already-running practice session after an app update.
    ensure_question_explanations_schema()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT explanation FROM user_question_explanations "
            "WHERE user_id = ? AND question_id = ?",
            (user_id, question_id),
        ).fetchone()
        return row["explanation"] if row else ""
    finally:
        conn.close()


def save_question_explanation(user_id: int, question_id: int, explanation: str) -> None:
    explanation = explanation.strip()
    if not explanation:
        raise ValueError("Paste or write an explanation before saving.")
    ensure_question_explanations_schema()
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """INSERT INTO user_question_explanations
                   (user_id, question_id, explanation, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id, question_id) DO UPDATE SET
                       explanation = excluded.explanation,
                       updated_at = CURRENT_TIMESTAMP""",
                (user_id, question_id, explanation),
            )
    finally:
        conn.close()


def get_new_question_explanations(user_id: int, created_from: str, created_to: str) -> list[dict]:
    """First submissions in a half-open UTC interval, across the user's courses.

    Callers supply local-day UTC bounds; edits never change the creation date.
    Legacy explanations with unknown creation dates are excluded.
    """
    ensure_question_explanations_schema()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT question_id, explanation, created_at FROM user_question_explanations "
            "WHERE user_id = ? AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at, question_id",
            (user_id, created_from, created_to),
        )]
    finally:
        conn.close()


def render_personal_explanation(user_id: int, question: dict) -> None:
    question_id = question.get("id")
    if question_id is None:
        return
    key = f"personal_explanation_{user_id}_{question_id}"
    try:
        saved = get_question_explanation(user_id, question_id)
    except sqlite3.Error:
        st.error("Your saved explanation could not be loaded. Please try again.")
        return

    if st.session_state.pop(f"{key}_saved", False):
        st.success("Explanation saved. It will appear after you answer this question next time.")
    if saved:
        with st.expander("Your saved explanation", expanded=True):
            st.markdown(math_markdown(saved))

    label = "Edit your explanation" if saved else "Add your own explanation (optional)"
    if f"{key}_text" not in st.session_state:
        st.session_state[f"{key}_text"] = saved
    with st.expander(label):
        st.caption(
            "Optional: add your own reasoning alongside the question's supplied rationale. "
            "Saved to your account for this question and shown after you answer it."
        )
        with st.form(f"{key}_form"):
            explanation = st.text_area(
                "Explanation", height=220,
                placeholder="Paste or write the reasoning behind the answer…",
                key=f"{key}_text",
            )
            if st.form_submit_button("Save explanation", type="primary"):
                try:
                    save_question_explanation(user_id, question_id, explanation)
                except ValueError as exc:
                    st.error(str(exc))
                except sqlite3.Error:
                    st.error("Could not save your explanation. Your text is still here; please try again.")
                else:
                    st.session_state[f"{key}_saved"] = True
                    st.rerun()
