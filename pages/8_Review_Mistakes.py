"""
pages/8_Review_Mistakes.py — Browse wrong answers filtered by active course.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd

from src.auth     import require_login
from src.utils    import page_header, sidebar_nav, require_course, DIFFICULTY_LABELS
from src.database import (
    get_mistake_journal, delete_journal_entry,
    get_attempts, get_attempt_answers, get_course,
)

st.set_page_config(page_title="Review Mistakes · StudyForge", page_icon="🔍", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

from src.utils import course_selector
course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"

page_header("🔍 Review Mistakes", f"Study your wrong answers — {course_title}")

tab_journal, tab_by_session = st.tabs(["📓 Mistake Journal", "📋 By Session"])

# ── Tab 1: Mistake journal ────────────────────────────────────────────────────
with tab_journal:
    journal = get_mistake_journal(user_id, course_id=course_id)

    if not journal:
        st.info(
            f"No mistakes recorded yet for **{course_title}**. "
            "Complete a practice session to populate this list."
        )
        st.stop()

    st.caption(f"{len(journal)} mistake(s) recorded for {course_title}")

    col1, col2, col3 = st.columns(3)
    with col1:
        section_opts = ["All"] + sorted({j["section_type"] for j in journal if j.get("section_type")})
        filter_sec   = st.selectbox("Section Type", section_opts, key="jf_sec")
    with col2:
        type_opts  = ["All"] + sorted({j["question_type"] for j in journal if j.get("question_type")})
        filter_type = st.selectbox("Question Type", type_opts, key="jf_type")
    with col3:
        diff_opts  = ["All"] + [str(d) for d in sorted({j["difficulty"] for j in journal if j.get("difficulty")})]
        filter_diff = st.selectbox("Difficulty", diff_opts, key="jf_diff")

    filtered = journal
    if filter_sec  != "All": filtered = [j for j in filtered if j.get("section_type")  == filter_sec]
    if filter_type != "All": filtered = [j for j in filtered if j.get("question_type") == filter_type]
    if filter_diff != "All": filtered = [j for j in filtered if str(j.get("difficulty")) == filter_diff]

    st.divider()

    for entry in filtered:
        diff  = entry.get("difficulty", 3)
        qtype = entry.get("question_type", "")
        sec   = entry.get("section_type", "")
        note  = entry.get("note", "")
        corr  = entry.get("correct_answer", "")

        with st.expander(
            f"[{DIFFICULTY_LABELS.get(diff, diff)}] {sec} · {qtype} — "
            f"Correct: **{corr}**",
            expanded=False,
        ):
            if entry.get("passage"):
                st.caption("📖 Passage excerpt:")
                st.markdown(f"> {str(entry['passage'])[:400]}…")

            st.markdown(f"**{entry.get('stimulus', '')}**")
            st.markdown("")

            for letter in ["A", "B", "C", "D", "E"]:
                choice = entry.get(f"choice_{letter.lower()}", "")
                if choice:
                    if letter == corr:
                        st.success(f"✅ **{letter}.** {choice}")
                    else:
                        st.write(f"**{letter}.** {choice}")

            if entry.get("explanation"):
                st.info(f"💡 {entry['explanation']}")
            if note:
                st.caption(f"📝 Note: {note}")

            col_note, col_del = st.columns([3, 1])
            with col_note:
                new_note = st.text_input("Add / update note:", value=note,
                                          key=f"note_{entry['id']}")
                if st.button("Save Note", key=f"save_{entry['id']}"):
                    from src.database import get_connection
                    conn = get_connection()
                    conn.execute("UPDATE mistake_journal SET note = ? WHERE id = ?",
                                 (new_note, entry["id"]))
                    conn.commit(); conn.close()
                    st.success("Note saved."); st.rerun()
            with col_del:
                st.markdown("")
                if st.button("🗑 Remove", key=f"del_{entry['id']}"):
                    delete_journal_entry(entry["id"]); st.rerun()

# ── Tab 2: By session ─────────────────────────────────────────────────────────
with tab_by_session:
    attempts = get_attempts(user_id, limit=20, course_id=course_id)
    if not attempts:
        st.info(f"No completed sessions for **{course_title}** yet.")
        st.stop()

    rows = []
    for a in attempts:
        rows.append({
            "ID":        a["id"],
            "Date":      (a["completed_at"] or "")[:10],
            "Mode":      a["mode"],
            "Section":   a["section_type"],
            "Score":     f"{a['correct_answers']}/{a['total_questions']}",
            "% Correct": f"{a['percent_correct']:.0f}%",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df.drop(columns=["ID"]), use_container_width=True, hide_index=True)

    selected_id = st.selectbox(
        "Select a session to review:",
        options=[a["id"] for a in attempts],
        format_func=lambda x: next(
            f"{a['completed_at'][:10]} · {a['mode']} · {a['section_type']}"
            for a in attempts if a["id"] == x
        ),
    )

    if selected_id:
        ans_rows   = get_attempt_answers(selected_id)
        wrong_only = st.checkbox("Show wrong answers only", value=True)
        if wrong_only:
            ans_rows = [r for r in ans_rows if not r["is_correct"]]

        st.caption(f"Showing {len(ans_rows)} questions")
        st.divider()

        for i, row in enumerate(ans_rows):
            icon = "✅" if row["is_correct"] else "❌"
            diff = DIFFICULTY_LABELS.get(row.get("difficulty", 3), 3)
            corr = row.get("correct_answer", "")
            sel  = row.get("selected_answer", "—")

            with st.expander(
                f"Q{i+1}  {icon}  [{diff}]  {row.get('question_type', '')}  "
                f"— You: **{sel}** | Correct: **{corr}**"
            ):
                if row.get("passage"):
                    with st.expander("📖 Passage"):
                        st.markdown(row["passage"])

                st.markdown(f"**{row.get('stimulus', '')}**")
                st.markdown("")

                for letter in ["A", "B", "C", "D", "E"]:
                    choice = row.get(f"choice_{letter.lower()}", "")
                    if choice:
                        if letter == corr and letter == sel:
                            st.success(f"✅ **{letter}.** {choice}  ← Correct")
                        elif letter == corr:
                            st.success(f"✅ **{letter}.** {choice}  ← Correct answer")
                        elif letter == sel:
                            st.error(f"❌ **{letter}.** {choice}  ← Your answer")
                        else:
                            st.write(f"**{letter}.** {choice}")

                if row.get("explanation"):
                    st.info(f"💡 {row['explanation']}")
                for letter in ["A", "B", "C", "D", "E"]:
                    note = row.get(f"wrong_answer_{letter.lower()}", "")
                    if note and letter != corr:
                        st.caption(f"**Why {letter} is wrong:** {note}")
