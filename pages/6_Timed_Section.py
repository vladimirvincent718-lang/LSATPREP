"""
pages/6_Timed_Section.py — One timed section filtered by active course.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.auth        import require_login
from src.utils       import (page_header, sidebar_nav, require_course,
                               render_question, render_score_card, render_timer)
from src.database    import get_all_questions, get_all_settings, get_distinct_values, get_course
from src.exam_engine import (
    start_quiz, clear_quiz, is_active, current_question,
    next_question, prev_question, record_answer, submit_section,
    toggle_flag, seconds_remaining, format_time, is_timed_out,
    _st, _set, _K,
)

st.set_page_config(page_title="Timed Exam · StudyForge", page_icon="⏱", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

from src.utils import course_selector
course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"

page_header("⏱ Timed Exam", f"One timed section — {course_title}")

settings  = get_all_settings(user_id)
hard_mode = settings.get("hard_mode", "false") == "true"

# ── Setup form ────────────────────────────────────────────────────────────────
if not is_active():
    st.subheader("Configure Your Timed Section")

    course_sections = get_distinct_values("section_type", course_id=course_id)
    section_opts    = course_sections if course_sections else ["General"]

    with st.form("timed_setup"):
        col1, col2 = st.columns(2)
        with col1:
            section_type = st.selectbox("Section Type", section_opts)
            n_questions  = st.number_input("Number of Questions", 5, 50, 25)
        with col2:
            if hard_mode:
                time_min = st.number_input(
                    "Time Limit (minutes) — Hard Mode",
                    min_value=15, max_value=35,
                    value=int(settings.get("hard_mode_time_minutes", "30")),
                )
            else:
                time_min = st.number_input(
                    "Time Limit (minutes)",
                    min_value=5, max_value=120,
                    value=int(settings.get("section_time_minutes", "35")),
                )
            diff_max = 5 if hard_mode else int(settings.get("max_difficulty", "5"))
            diff_min = 4 if hard_mode else int(settings.get("min_difficulty", "1"))

        if hard_mode:
            st.warning("⚡ Hard Mode is ON — shorter timer, harder questions, no pausing.")

        go = st.form_submit_button("▶ Start Section", use_container_width=True)

    if go:
        import random
        pool = get_all_questions(
            section_type=section_type,
            min_difficulty=diff_min, max_difficulty=diff_max,
            course_id=course_id,
        )
        if not pool:
            st.error(
                f"No questions found for section type '{section_type}' in **{course_title}**. "
                "Upload questions first."
            )
            st.stop()
        questions = random.sample(pool, min(int(n_questions), len(pool)))
        clear_quiz()
        start_quiz(
            user_id=user_id,
            mode="timed_section",
            questions=questions,
            section_type=section_type,
            hard_mode=hard_mode,
            time_limit_seconds=int(time_min) * 60,
            course_id=course_id,
        )
        st.rerun()
    from src.voice_exam import cleanup_voice_exam_panel
    cleanup_voice_exam_panel()
    st.stop()

# ── Auto-refresh every 10 s ───────────────────────────────────────────────────
st_autorefresh(interval=10_000, key="timed_section_refresh")

# ── Active timed section ──────────────────────────────────────────────────────
questions    = _st("questions") or []
current_idx  = _st("current_idx") or 0
answers_dict = _st("answers") or {}
flagged_set  = _st("flagged") or set()
hard         = _st("hard_mode") or False
total_secs   = _st("time_limit") or (35 * 60)

total     = len(questions)
answered  = len(answers_dict)
remaining = seconds_remaining()

if is_timed_out():
    st.warning("⏰ Time's up! Submitting your answers now…")
    report = submit_section(user_id)
    st.session_state["timed_report"] = report
    clear_quiz(); st.rerun()

q = current_question()
if q is None:
    st.error("Session error."); clear_quiz(); st.rerun()

# ── Voice Exam Mode ───────────────────────────────────────────────────────────
from src.voice_exam import render_voice_exam_panel
render_voice_exam_panel(q, current_idx, total)

render_timer(remaining, total_secs)
st.progress(answered / total if total else 0, text=f"{answered}/{total} answered")

n1, n2, n3, n4 = st.columns([1, 1, 4, 2])
with n1:
    if st.button("◀", disabled=(current_idx == 0)):
        prev_question(); st.rerun()
with n2:
    if st.button("▶", disabled=(current_idx == total - 1)):
        next_question(); st.rerun()
with n3:
    jump = st.selectbox(
        "Go to:", options=[f"Q{i+1}" for i in range(total)],
        index=current_idx, label_visibility="collapsed",
    )
    target_idx = int(jump[1:]) - 1
    if target_idx != current_idx:
        st.session_state[_K["current_idx"]] = target_idx; st.rerun()
with n4:
    flag_label = "🚩 Unflag" if current_idx in flagged_set else "🏳️ Flag"
    if st.button(flag_label):
        toggle_flag(current_idx); st.rerun()

st.divider()

selected   = answers_dict.get(current_idx, "")
is_flagged = current_idx in flagged_set

picked = render_question(
    q=q, idx=current_idx, total=total,
    selected=selected, show_answer=False, is_flagged=is_flagged,
)

if st.button("✔ Record Answer", type="primary", use_container_width=True):
    if not picked:
        st.warning("Select an answer first.")
    else:
        record_answer(current_idx, picked)
        if current_idx < total - 1:
            next_question()
        st.rerun()

st.divider()

unanswered = total - answered
if unanswered > 0:
    st.caption(f"⚠️ {unanswered} question(s) unanswered — you can still submit.")

col_sub, col_quit = st.columns(2)
with col_sub:
    if st.button("🏁 Submit Section", type="primary", use_container_width=True):
        report = submit_section(user_id)
        st.session_state["timed_report"] = report
        clear_quiz(); st.rerun()
with col_quit:
    if not hard:
        if st.button("✖ Quit Without Saving", use_container_width=True):
            clear_quiz(); st.rerun()
    else:
        st.caption("⚡ Hard Mode: Quit disabled during timed section.")

# ── Sidebar question map ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Question Map**")
    st.caption("🟢 Answered  ⬜ Unanswered  🚩 Flagged")
    cols = st.columns(5)
    for i in range(total):
        ans  = answers_dict.get(i, "")
        flag = i in flagged_set
        icon = "🚩" if flag else ("🟢" if ans else "⬜")
        if cols[i % 5].button(icon, key=f"tmap_{i}"):
            st.session_state[_K["current_idx"]] = i; st.rerun()

# ── Score report ──────────────────────────────────────────────────────────────
if not is_active() and "timed_report" in st.session_state:
    report = st.session_state.pop("timed_report")
    st.success("Section complete!")
    render_score_card(report, "Timed Section Score")

    with st.expander("📋 Review All Answers"):
        from src.database import get_attempts, get_attempt_answers
        recent = get_attempts(user_id, limit=1, course_id=course_id)
        if recent:
            ans_rows = get_attempt_answers(recent[0]["id"])
            for i, row in enumerate(ans_rows):
                sel    = row.get("selected_answer", "")
                corr   = row.get("correct_answer", "")
                icon   = "✅" if row.get("is_correct") else "❌"
                st.markdown(f"**Q{i+1}** {icon} — Your: **{sel}** | Correct: **{corr}**")
                st.caption(row.get("stimulus", "")[:200])
                if row.get("explanation"):
                    st.info(row["explanation"])
                st.divider()
