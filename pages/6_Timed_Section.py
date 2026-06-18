"""
pages/6_Timed_Section.py — One timed section filtered by active course.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.auth        import require_login
from src.utils       import (page_header, sidebar_nav, require_course,
                               render_question, render_score_card, render_timer,
                               question_reference_label)
from src.database    import get_all_questions, get_all_settings, get_distinct_values, get_course
from src.exam_engine import (
    start_quiz, clear_quiz, is_active, current_question,
    next_question, prev_question, record_answer, record_self_grade, submit_section,
    toggle_flag, seconds_remaining, format_time, is_timed_out,
    persist_current_exam, restore_exam_draft, _st, _set, _K,
)
from src.question_loader import is_open_ended_question
from src.question_map import render_question_map, render_question_map_legend
from src.pdf_export import generate_exam_pdf, make_pdf_filename
from src.email_notifications import notify_exam_started

TIMED_CONFIRM_SUBMIT_KEY = "timed_confirm_submit"

st.set_page_config(page_title="Timed Exam · StudyForge", page_icon="⏱", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

from src.utils import course_selector
course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"
restore_exam_draft(user_id, modes={"timed_section"}, course_id=course_id)

page_header("⏱ Timed Exam", f"One timed section — {course_title}")

if st.session_state.pop("_exam_restored_notice", False):
    st.success("Your in-progress timed section was restored with your saved answers and remaining time.")

email_notice = st.session_state.pop("exam_email_notice", None)
if email_notice:
    st.info(email_notice)

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

        open_ended_mode = st.checkbox(
            "Open-ended challenge - hide answer choices",
            help=(
                "Multiple choice is the default. Turn this on when you want to "
                "remove the options and self-grade your written response."
            ),
        )

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
        exam_label = f"Timed Section: {section_type}"
        pdf_bytes = generate_exam_pdf(
            questions=questions,
            title=exam_label,
            subtitle=f"{course_title} timed exam",
            distribution=[{"course": course_title, "q_count": len(questions)}],
        )
        pdf_filename = make_pdf_filename(exam_label)
        clear_quiz()
        start_quiz(
            user_id=user_id,
            mode="timed_section",
            questions=questions,
            section_type=section_type,
            hard_mode=hard_mode,
            time_limit_seconds=int(time_min) * 60,
            course_id=course_id,
            open_ended_mode=open_ended_mode,
        )
        result = notify_exam_started(
            user_id,
            course_name=course_title,
            module_name=section_type,
            exam_label=exam_label,
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
            question_count=len(questions),
        )
        if result.sent or result.message != "Email notifications are off.":
            st.session_state["exam_email_notice"] = result.message
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
    st.session_state.pop(TIMED_CONFIRM_SUBMIT_KEY, None)
    report = submit_section(user_id)
    st.session_state["timed_report"] = report
    clear_quiz(); st.rerun()

q = current_question()
if q is None:
    st.error("Session error."); clear_quiz(); st.rerun()

# ── Voice Exam Mode ───────────────────────────────────────────────────────────
from src.voice_exam import render_voice_exam_panel
render_voice_exam_panel(q, current_idx, total)

render_timer(remaining, total_secs, key_prefix="timed_section_timer", allow_pause=not hard)
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
        st.session_state[_K["current_idx"]] = target_idx
        persist_current_exam(user_id)
        st.rerun()
with n4:
    flag_label = "🚩 Unflag" if current_idx in flagged_set else "🏳️ Flag"
    if st.button(flag_label):
        toggle_flag(current_idx); st.rerun()

st.divider()

selected   = answers_dict.get(current_idx, "")
is_flagged = current_idx in flagged_set

open_ended = is_open_ended_question(q)
if open_ended:
    existing_grade = (_st("self_grades") or {}).get(current_idx, True)
    self_grade_choice = st.radio(
        "Self-grade this written response before scoring:",
        options=["Correct", "Incorrect"],
        index=0 if existing_grade else 1,
        horizontal=True,
        key=f"timed_self_grade_{current_idx}",
    )
    record_self_grade(current_idx, self_grade_choice == "Correct")

picked = render_question(
    q=q, idx=current_idx, total=total,
    selected=selected, show_answer=False, is_flagged=is_flagged,
)
if picked and picked != selected:
    record_answer(current_idx, picked)
    answers_dict = _st("answers") or {}
    answered = len(answers_dict)

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
        st.session_state[TIMED_CONFIRM_SUBMIT_KEY] = True
        st.rerun()
with col_quit:
    if not hard:
        if st.button("✖ Quit Without Saving", use_container_width=True):
            st.session_state.pop(TIMED_CONFIRM_SUBMIT_KEY, None)
            clear_quiz(); st.rerun()
    else:
        st.caption("⚡ Hard Mode: Quit disabled during timed section.")

if st.session_state.get(TIMED_CONFIRM_SUBMIT_KEY):
    st.warning("Are you sure you want to submit this timed section?")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("Yes, submit section", type="primary", use_container_width=True):
            st.session_state.pop(TIMED_CONFIRM_SUBMIT_KEY, None)
            report = submit_section(user_id)
            st.session_state["timed_report"] = report
            clear_quiz(); st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.pop(TIMED_CONFIRM_SUBMIT_KEY, None)
            st.rerun()

# ── Sidebar question map ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Question Map**")
    render_question_map_legend(scored=False)

    def _timed_map_state(i: int) -> dict[str, object]:
        ans  = answers_dict.get(i, "")
        flag = i in flagged_set
        icon = "🚩" if flag else ("🟢" if ans else "⬜")
        return {
            "status": "answered" if ans else "unanswered",
            "flagged": flag,
            "help": f"Go to question {i + 1}",
        }
        if cols[i % 5].button(icon, key=f"tmap_{i}"):
            st.session_state[_K["current_idx"]] = i; st.rerun()

# ── Score report ──────────────────────────────────────────────────────────────
    selected_map_idx = render_question_map(
        total=total,
        current_idx=current_idx,
        state_for_index=_timed_map_state,
        key_prefix="tmap",
    )
    if selected_map_idx is not None:
        st.session_state[_K["current_idx"]] = selected_map_idx; st.rerun()

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
                ref_label = question_reference_label(row, include_prefix=False)
                title = f"**Q{i+1}**"
                if ref_label:
                    title += f" ({ref_label})"
                st.markdown(f"{title} {icon} — Your: **{sel}** | Correct: **{corr}**")
                st.caption(row.get("stimulus", "")[:200])
                if row.get("explanation"):
                    st.info(row["explanation"])
                st.divider()
