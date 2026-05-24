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
    get_mistake_journal, delete_journal_entry, set_journal_entry_completed,
    get_attempts, get_attempt_answers, get_course,
    get_all_curriculums, get_curriculum_courses,
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

tab_journal, tab_by_session, tab_by_curriculum = st.tabs(
    ["📓 Mistake Journal", "📋 By Session", "🧭 By Curriculum"]
)


def _render_choices(row: dict, selected_answer: str | None = None) -> None:
    corr = row.get("correct_answer", "")
    for letter in ["A", "B", "C", "D", "E"]:
        choice = row.get(f"choice_{letter.lower()}", "")
        if not choice:
            continue
        if selected_answer and letter == corr and letter == selected_answer:
            st.success(f"✅ **{letter}.** {choice}  ← Correct")
        elif selected_answer and letter == selected_answer:
            st.error(f"❌ **{letter}.** {choice}  ← Your answer")
        elif letter == corr:
            suffix = "  ← Correct answer" if selected_answer else ""
            st.success(f"✅ **{letter}.** {choice}{suffix}")
        else:
            st.write(f"**{letter}.** {choice}")


def _render_question_body(row: dict, selected_answer: str | None = None) -> None:
    if row.get("passage"):
        with st.expander("📖 Passage"):
            st.markdown(row["passage"])

    st.markdown(f"**{row.get('stimulus', '')}**")
    st.markdown("")
    _render_choices(row, selected_answer=selected_answer)

    if row.get("explanation"):
        st.info(f"💡 {row['explanation']}")

    for letter in ["A", "B", "C", "D", "E"]:
        note = row.get(f"wrong_answer_{letter.lower()}", "")
        if note and letter != row.get("correct_answer", ""):
            st.caption(f"**Why {letter} is wrong:** {note}")


def _difficulty_label(row: dict) -> str:
    diff = row.get("difficulty", 3)
    return str(DIFFICULTY_LABELS.get(diff, diff))


def _completion_counts(entries: list[dict]) -> tuple[int, int, int, int]:
    total = len(entries)
    complete = sum(1 for entry in entries if entry.get("is_completed"))
    incomplete = total - complete
    complete_pct = round((complete / total) * 100) if total else 0
    return total, complete, incomplete, complete_pct


def _render_completion_summary(entries: list[dict], label: str) -> None:
    total, complete, incomplete, complete_pct = _completion_counts(entries)
    incomplete_pct = 100 - complete_pct if total else 0

    st.markdown(f"#### Review progress - {label}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Complete", f"{complete_pct}%", f"{complete}/{total}")
    col2.metric("Incomplete", f"{incomplete_pct}%", f"{incomplete} left")
    col3.metric("Checked off", complete)
    col4.metric("Total mistakes", total)
    st.progress(complete_pct / 100 if total else 0)


def _review_status_badge(is_completed: bool) -> str:
    bg = "#dcfce7" if is_completed else "#fee2e2"
    fg = "#166534" if is_completed else "#991b1b"
    border = "#86efac" if is_completed else "#fecaca"
    label = "Reviewed" if is_completed else "Outstanding"
    return (
        f"<div style='background:{bg}; color:{fg}; border:1px solid {border}; "
        "border-radius:6px; font-weight:700; padding:0.45rem 0.65rem; "
        "text-align:center; font-size:0.85rem;'>"
        f"{label}</div>"
    )


def _render_review_checkbox(entry: dict, is_completed: bool, key_prefix: str) -> None:
    checked = st.checkbox(
        "Reviewed",
        value=is_completed,
        key=f"{key_prefix}_{entry['id']}",
        help="Mark this mistake as reviewed.",
    )
    if checked != is_completed:
        set_journal_entry_completed(entry["id"], checked)
        st.rerun()


def _render_course_progress_strip(title: str, entries: list[dict]) -> None:
    total, complete, incomplete, complete_pct = _completion_counts(entries)
    bg = "linear-gradient(90deg, #22c55e 0%, #22c55e {pct}%, #fecaca {pct}%, #fecaca 100%)"
    st.markdown(
        (
            "<div style='border:1px solid #d8dee8; border-radius:8px; "
            "background:#ffffff; padding:0.7rem 0.9rem; margin:0.85rem 0 0.35rem 0;'>"
            "<div style='display:flex; align-items:center; justify-content:space-between; "
            "gap:1rem; flex-wrap:wrap;'>"
            f"<strong>{title}</strong>"
            f"<span style='font-weight:700; color:#166534;'>{complete}/{total} reviewed</span>"
            f"<span style='font-weight:700; color:#991b1b;'>{incomplete} outstanding</span>"
            f"<span style='font-weight:800;'>{complete_pct}% complete</span>"
            "</div>"
            "<div style='height:0.7rem; border-radius:999px; overflow:hidden; "
            "background:#fee2e2; margin-top:0.55rem;'>"
            f"<div style='height:100%; width:100%; background:{bg.format(pct=complete_pct)};'></div>"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


# ── Tab 1: Mistake journal ────────────────────────────────────────────────────
with tab_journal:
    journal = get_mistake_journal(user_id, course_id=course_id)

    if not journal:
        st.info(
            f"No mistakes recorded yet for **{course_title}**. "
            "Complete a practice session to populate this list."
        )
    else:
        st.caption(f"{len(journal)} mistake(s) recorded for {course_title}")
        _render_completion_summary(journal, course_title)

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

        if len(filtered) != len(journal):
            _render_completion_summary(filtered, "current filters")

        st.divider()

        for entry in filtered:
            qtype = entry.get("question_type", "")
            sec   = entry.get("section_type", "")
            note  = entry.get("note", "")
            corr  = entry.get("correct_answer", "")
            done  = bool(entry.get("is_completed"))

            panel_col, status_col, check_col = st.columns([7, 1.4, 1.2])
            with panel_col:
                with st.expander(
                    f"[{_difficulty_label(entry)}] {sec} · {qtype} - Correct: {corr}",
                    expanded=False,
                ):
                    _render_question_body(entry)
                    if note:
                        st.caption(f"📝 Note: {note}")

                    col_note, col_del = st.columns([3, 1])
                    with col_note:
                        new_note = st.text_input(
                            "Add / update note:",
                            value=note,
                            key=f"note_{entry['id']}",
                        )
                        if st.button("Save Note", key=f"save_{entry['id']}"):
                            from src.database import get_connection
                            conn = get_connection()
                            conn.execute(
                                "UPDATE mistake_journal SET note = ? WHERE id = ?",
                                (new_note, entry["id"]),
                            )
                            conn.commit()
                            conn.close()
                            st.success("Note saved.")
                            st.rerun()
                    with col_del:
                        st.markdown("")
                        if st.button("🗑 Remove", key=f"del_{entry['id']}"):
                            delete_journal_entry(entry["id"])
                            st.rerun()
            with status_col:
                st.markdown(_review_status_badge(done), unsafe_allow_html=True)
            with check_col:
                _render_review_checkbox(entry, done, "complete")

# ── Tab 2: By session ─────────────────────────────────────────────────────────
with tab_by_session:
    attempts = get_attempts(user_id, limit=20, course_id=course_id)
    if not attempts:
        st.info(f"No completed sessions for **{course_title}** yet.")
    else:
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
                corr = row.get("correct_answer", "")
                sel  = row.get("selected_answer", "—")

                with st.expander(
                    f"Q{i+1}  {icon}  [{_difficulty_label(row)}]  "
                    f"{row.get('question_type', '')} — You: {sel} | Correct: {corr}"
                ):
                    _render_question_body(row, selected_answer=sel)

# ── Tab 3: By curriculum ──────────────────────────────────────────────────────
with tab_by_curriculum:
    curriculums = get_all_curriculums()
    if not curriculums:
        st.info("No curriculums have been created yet. Create one in Curriculum Builder.")
    else:
        curriculum_courses = {c["id"]: get_curriculum_courses(c["id"]) for c in curriculums}
        default_idx = 0
        for idx, curr in enumerate(curriculums):
            if any(c["id"] == course_id for c in curriculum_courses.get(curr["id"], [])):
                default_idx = idx
                break

        selected_curriculum_id = st.selectbox(
            "Curriculum",
            options=[c["id"] for c in curriculums],
            index=default_idx,
            format_func=lambda cid: next(c["title"] for c in curriculums if c["id"] == cid),
            key="mistakes_by_curriculum",
            help="Defaults to the curriculum that contains your active course.",
        )

        courses = curriculum_courses.get(selected_curriculum_id, [])
        if not courses:
            st.warning("This curriculum does not have any courses yet.")
        else:
            course_ids = [c["id"] for c in courses]
            journal = get_mistake_journal(user_id, course_ids=course_ids)

            if not journal:
                st.info("No mistakes recorded yet across this curriculum.")
            else:
                course_title_by_id = {c["id"]: c["title"] for c in courses}
                count_by_course = {
                    cid: sum(1 for j in journal if j.get("q_course_id") == cid)
                    for cid in course_ids
                }

                st.caption(
                    f"{len(journal)} mistake(s) recorded across "
                    f"{len([cid for cid, count in count_by_course.items() if count])} "
                    f"course(s) in this curriculum."
                )
                _render_completion_summary(journal, "selected curriculum")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    course_filter = st.selectbox(
                        "Course",
                        ["All"] + course_ids,
                        format_func=lambda cid: "All" if cid == "All" else course_title_by_id.get(cid, "Unknown"),
                        key="cf_course",
                    )
                with col2:
                    type_opts = ["All"] + sorted({j["question_type"] for j in journal if j.get("question_type")})
                    type_filter = st.selectbox("Question Type", type_opts, key="cf_type")
                with col3:
                    diff_opts = ["All"] + [str(d) for d in sorted({j["difficulty"] for j in journal if j.get("difficulty")})]
                    diff_filter = st.selectbox("Difficulty", diff_opts, key="cf_diff")
                with col4:
                    course_sort = st.selectbox(
                        "Sort Courses",
                        ["Name", "Review progress"],
                        key="cf_course_sort",
                    )

                filtered = journal
                if course_filter != "All":
                    filtered = [j for j in filtered if j.get("q_course_id") == course_filter]
                if type_filter != "All":
                    filtered = [j for j in filtered if j.get("question_type") == type_filter]
                if diff_filter != "All":
                    filtered = [j for j in filtered if str(j.get("difficulty")) == diff_filter]

                if len(filtered) != len(journal):
                    _render_completion_summary(filtered, "current curriculum filters")

                st.divider()

                course_groups = []
                for course_row in courses:
                    course_entries = [
                        j for j in filtered if j.get("q_course_id") == course_row["id"]
                    ]
                    if not course_entries:
                        continue
                    total, complete, incomplete, complete_pct = _completion_counts(course_entries)
                    course_groups.append(
                        {
                            "course": course_row,
                            "entries": course_entries,
                            "total": total,
                            "complete": complete,
                            "incomplete": incomplete,
                            "complete_pct": complete_pct,
                        }
                    )

                if course_sort == "Review progress":
                    course_groups.sort(
                        key=lambda group: (
                            -group["complete_pct"],
                            -group["complete"],
                            group["course"]["title"].lower(),
                        )
                    )
                else:
                    course_groups.sort(key=lambda group: group["course"]["title"].lower())

                for group in course_groups:
                    course_row = group["course"]
                    course_entries = group["entries"]
                    _render_course_progress_strip(course_row["title"], course_entries)

                    with st.expander(
                        (
                            f"{course_row['title']} - {group['complete']}/{group['total']} reviewed "
                            f"({group['complete_pct']}%), {group['incomplete']} outstanding"
                        ),
                        expanded=course_row["id"] == course_id,
                    ):
                        st.caption(
                            "Curriculum order view: review mistakes course-by-course "
                            "as they appear in the selected curriculum."
                        )

                        for entry in course_entries:
                            qtype = entry.get("question_type", "")
                            sec   = entry.get("section_type", "")
                            corr  = entry.get("correct_answer", "")
                            done  = bool(entry.get("is_completed"))

                            panel_col, status_col, check_col = st.columns([7, 1.4, 1.2])
                            with panel_col:
                                with st.expander(
                                    f"[{_difficulty_label(entry)}] {sec} · {qtype} - Correct: {corr}",
                                    expanded=False,
                                ):
                                    _render_question_body(entry)
                                    if entry.get("note"):
                                        st.caption(f"📝 Note: {entry['note']}")
                            with status_col:
                                st.markdown(_review_status_badge(done), unsafe_allow_html=True)
                            with check_col:
                                _render_review_checkbox(entry, done, "curriculum_complete")
