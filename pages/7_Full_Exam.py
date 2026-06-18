"""
pages/7_Full_Exam.py — Multi-section exam simulation for the active course.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.auth       import require_login
from src.utils      import (page_header, sidebar_nav, require_course,
                              render_question, render_score_card, render_timer,
                              question_reference_label)
from src.database   import (get_all_settings, get_attempts, get_attempt_answers,
                              complete_attempt, get_course)
from src.exam_engine import (
    start_full_exam, advance_full_exam, submit_section,
    is_active, current_question, next_question, prev_question,
    record_answer, record_self_grade, toggle_flag, seconds_remaining, is_timed_out,
    clear_quiz, resume_timer, persist_current_exam, restore_exam_draft,
    _st, _set, _K, format_time,
)
from src.scoring import compute_score
from src.question_loader import is_open_ended_question
from src.question_map import render_question_map, render_question_map_legend
from src.pdf_export import generate_exam_pdf, make_pdf_filename
from src.email_notifications import notify_exam_started

st.set_page_config(page_title="Full Exam · StudyForge", page_icon="📋", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

from src.utils import course_selector
course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"
restore_exam_draft(user_id, modes={"full_exam"}, course_id=course_id)

page_header("📋 Full Exam Mode", f"Multi-section simulation — {course_title}")

if st.session_state.pop("_exam_restored_notice", False):
    st.success("Your in-progress full exam was restored with your saved answers and remaining time.")

email_notice = st.session_state.pop("exam_email_notice", None)
if email_notice:
    st.info(email_notice)

settings  = get_all_settings(user_id)
hard_mode = settings.get("hard_mode", "false") == "true"

KEY_EXAM_RUNNING  = "full_exam_running"
KEY_EXAM_COMPLETE = "full_exam_complete"
KEY_ALL_REPORTS   = "full_exam_all_reports"
KEY_CONFIRM_SUBMIT = "full_exam_confirm_submit"

def exam_running():  return st.session_state.get(KEY_EXAM_RUNNING, False)
def exam_complete(): return st.session_state.get(KEY_EXAM_COMPLETE, False)

# ── Not started ───────────────────────────────────────────────────────────────
if not exam_running() and not exam_complete():
    from src.database import get_course_question_count
    q_count = get_course_question_count(course_id)

    st.subheader("Full Exam Simulation")
    st.markdown(f"""
**Structure** (course-aware defaults):
- **4 sections**, each 35 minutes (30 min in Hard Mode)
- **3 scored** sections, **1 unscored** experimental section
- **10-minute break** after Section 2

This mode uses the section types available in the active course question bank.

> **Note:** Full Exam works best with at least 20+ questions covering multiple section types.
    """)

    if q_count < 10:
        st.warning(
            f"⚠️ Only {q_count} question(s) in **{course_title}**. "
            "Upload more questions for a realistic exam experience."
        )

    if hard_mode:
        st.warning("⚡ Hard Mode is ON — 30-minute sections, harder questions.")

    open_ended_mode = st.checkbox(
        "Open-ended challenge - hide answer choices",
        help=(
            "Multiple choice is the default. Turn this on when you want to "
            "remove the options and self-grade your written response."
        ),
    )

    if st.button("▶ Begin Full Exam", type="primary", use_container_width=True):
        from src.database import get_all_questions
        pool = get_all_questions(course_id=course_id)
        if len(pool) < 5:
            st.error(f"Need at least 5 questions in **{course_title}** to run a full exam.")
            st.stop()

        start_full_exam(
            user_id,
            hard_mode=hard_mode,
            course_id=course_id,
            open_ended_mode=open_ended_mode,
        )
        sections = st.session_state.get(_K["full_sections"], [])
        exam_questions = [
            question
            for section in sections
            for question in section.get("questions", [])
        ]
        exam_label = "Full Exam"
        pdf_bytes = generate_exam_pdf(
            questions=exam_questions,
            title=exam_label,
            subtitle=f"{course_title} full exam simulation",
            distribution=[{"course": course_title, "q_count": len(exam_questions)}],
        )
        result = notify_exam_started(
            user_id,
            course_name=course_title,
            module_name=exam_label,
            exam_label=exam_label,
            pdf_bytes=pdf_bytes,
            pdf_filename=make_pdf_filename(exam_label),
            question_count=len(exam_questions),
        )
        if result.sent or result.message != "Email notifications are off.":
            st.session_state["exam_email_notice"] = result.message
        st.session_state[KEY_EXAM_RUNNING]  = True
        st.session_state[KEY_EXAM_COMPLETE] = False
        st.session_state[KEY_ALL_REPORTS]   = []
        persist_current_exam(user_id)
        st.rerun()

    st.stop()

# ── Exam complete ─────────────────────────────────────────────────────────────
if exam_complete():
    st.balloons()
    st.success("🎉 Exam complete!")

    all_reports = st.session_state.get(KEY_ALL_REPORTS, [])
    sections    = st.session_state.get(_K["full_sections"], [])

    for i, (rep, sec) in enumerate(zip(all_reports, sections)):
        scored = sec.get("is_scored", True)
        tag    = "" if scored else "  *(Experimental — not scored)*"
        st.markdown(f"#### Section {i+1}: {sec.get('section_type', '')} {tag}")
        if scored:
            c1, c2, c3 = st.columns(3)
            c1.metric("Raw Score",   f"{rep['correct']} / {rep['total']}")
            c2.metric("% Correct",   f"{rep['percent_correct']}%")
            c3.metric("Est. Scaled", rep.get("scaled_score") or "—")
        else:
            st.caption(f"Unscored — {rep['correct']}/{rep['total']} correct")
        st.divider()

    scored_reps = [r for r, s in zip(all_reports, sections) if s.get("is_scored", True)]
    if scored_reps:
        total_q = sum(r["total"]   for r in scored_reps)
        total_c = sum(r["correct"] for r in scored_reps)
        pct     = round(total_c / total_q * 100, 1) if total_q else 0
        from src.scoring import estimate_scaled_score
        scaled = estimate_scaled_score(total_c, total_q)
        st.markdown("### Overall Scored Performance")
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Total Raw Score",    f"{total_c} / {total_q}")
        cc2.metric("Overall % Correct",  f"{pct}%")
        cc3.metric("Est. Scaled Score",  scaled or "—")

    if st.button("🔄 Take Another Exam"):
        for k in [KEY_EXAM_RUNNING, KEY_EXAM_COMPLETE, KEY_ALL_REPORTS]:
            st.session_state.pop(k, None)
        clear_quiz(); st.rerun()

    with st.expander("📋 Review All Questions"):
        recent = get_attempts(user_id, limit=4, course_id=course_id)
        for attempt in recent:
            st.markdown(f"**{attempt['mode']} — {attempt['section_type']}**")
            rows = get_attempt_answers(attempt["id"])
            for i, row in enumerate(rows):
                icon = "✅" if row["is_correct"] else "❌"
                ref_label = question_reference_label(row, include_prefix=False)
                title = f"**Q{i+1}**"
                if ref_label:
                    title += f" ({ref_label})"
                st.markdown(
                    f"{title} {icon}  Your: **{row['selected_answer'] or '—'}** "
                    f"| Correct: **{row['correct_answer']}**"
                )
                st.caption(str(row["stimulus"])[:200])
                if row.get("explanation"):
                    st.info(row["explanation"])
            st.divider()
    st.stop()

# ── Exam in progress ──────────────────────────────────────────────────────────
st_autorefresh(interval=10_000, key="full_exam_refresh")

on_break      = st.session_state.get(_K["on_break"], False)
break_started = st.session_state.get(_K["break_started"], time.time())
BREAK_SECONDS = 10 * 60

if on_break:
    break_remaining = max(0.0, BREAK_SECONDS - (time.time() - break_started))
    m, s = divmod(int(break_remaining), 60)
    st.markdown("## ☕ 10-Minute Break")
    st.markdown("Stand up, stretch, breathe. Section 3 starts when the timer ends.")
    st.progress(max(0.0, break_remaining / BREAK_SECONDS),
                text=f"Break ends in {m:02d}:{s:02d}")

    if break_remaining <= 0 or st.button("▶ Resume Exam Now"):
        st.session_state[_K["on_break"]] = False
        sec_idx  = st.session_state.get(_K["full_sec_idx"], 2)
        sections = st.session_state.get(_K["full_sections"], [])
        if is_active() and (_st("section_num") or 0) == sec_idx + 1:
            resume_timer()
            persist_current_exam(user_id)
        else:
            from src.exam_engine import _start_full_section
            _start_full_section(user_id, sec_idx, sections, hard_mode, course_id)
        st.rerun()
    st.stop()

if not is_active():
    st.error("Exam state lost. Please start a new exam.")
    st.session_state.pop(KEY_EXAM_RUNNING, None)
    clear_quiz(); st.rerun()

questions    = _st("questions") or []
current_idx  = _st("current_idx") or 0
answers_dict = _st("answers") or {}
flagged_set  = _st("flagged") or set()
total_secs   = _st("time_limit") or (35 * 60)
section_num  = _st("section_num") or 1
sections     = st.session_state.get(_K["full_sections"], [])
sec_idx      = st.session_state.get(_K["full_sec_idx"], 0)

total     = len(questions)
answered  = len(answers_dict)
remaining = seconds_remaining()

current_sec = sections[sec_idx] if sec_idx < len(sections) else {}

if is_timed_out():
    st.warning("⏰ Time's up!")
    st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
    report      = submit_section(user_id)
    all_reports = st.session_state.get(KEY_ALL_REPORTS, [])
    all_reports.append(report)
    st.session_state[KEY_ALL_REPORTS] = all_reports
    outcome = advance_full_exam(user_id)
    if outcome == "complete":
        st.session_state[KEY_EXAM_COMPLETE] = True
        st.session_state[KEY_EXAM_RUNNING]  = False
    st.rerun()

sec_type = current_sec.get("section_type", "")
st.markdown(f"### Section {section_num} of 4 — {sec_type}")
render_timer(
    remaining,
    total_secs,
    key_prefix=f"full_exam_timer_s{section_num}",
    allow_pause=not hard_mode,
)
st.progress(answered / total if total else 0, text=f"{answered}/{total} answered")

n1, n2, n3, n4 = st.columns([1, 1, 4, 2])
with n1:
    if st.button("◀", disabled=(current_idx == 0), key="fe_prev"):
        prev_question(); st.rerun()
with n2:
    if st.button("▶", disabled=(current_idx == total - 1), key="fe_next"):
        next_question(); st.rerun()
with n3:
    jump = st.selectbox("Go to:", [f"Q{i+1}" for i in range(total)],
                        index=current_idx, label_visibility="collapsed", key="fe_jump")
    tidx = int(jump[1:]) - 1
    if tidx != current_idx:
        st.session_state[_K["current_idx"]] = tidx
        persist_current_exam(user_id)
        st.rerun()
with n4:
    flabel = "🚩 Unflag" if current_idx in flagged_set else "🏳️ Flag"
    if st.button(flabel, key="fe_flag"):
        toggle_flag(current_idx); st.rerun()

st.divider()

q = current_question()
if q:
    # ── Voice Exam Mode ───────────────────────────────────────────────────
    from src.voice_exam import render_voice_exam_panel
    render_voice_exam_panel(q, current_idx, total)

    open_ended = is_open_ended_question(q)
    if open_ended:
        existing_grade = (_st("self_grades") or {}).get(current_idx, True)
        self_grade_choice = st.radio(
            "Self-grade this written response before scoring:",
            options=["Correct", "Incorrect"],
            index=0 if existing_grade else 1,
            horizontal=True,
            key=f"fe_self_grade_{section_num}_{current_idx}",
        )
        record_self_grade(current_idx, self_grade_choice == "Correct")

    picked = render_question(
        q=q, idx=current_idx, total=total,
        selected=answers_dict.get(current_idx, ""),
        show_answer=False, is_flagged=(current_idx in flagged_set),
    )
    if picked and picked != answers_dict.get(current_idx, ""):
        record_answer(current_idx, picked)
        answers_dict = _st("answers") or {}
        answered = len(answers_dict)
    if st.button("✔ Record Answer", type="primary", use_container_width=True, key="fe_submit_ans"):
        if not picked:
            st.warning("Select an answer first.")
        else:
            record_answer(current_idx, picked)
            if current_idx < total - 1:
                next_question()
            st.rerun()

st.divider()

unanswered   = total - answered
col_s, col_q = st.columns(2)
with col_s:
    btn_label = "🏁 Submit Section & Continue" if sec_idx < 3 else "🏁 Submit Final Section"
    if st.button(btn_label, type="primary", use_container_width=True):
        st.session_state.pop("confirm_submit_fe", None)
        st.session_state[KEY_CONFIRM_SUBMIT] = True
        st.rerun()

with col_q:
    if not hard_mode:
        if st.button("✖ Quit Exam", use_container_width=True):
            for k in [KEY_EXAM_RUNNING, KEY_EXAM_COMPLETE]:
                st.session_state.pop(k, None)
            st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
            clear_quiz(); st.rerun()

if st.session_state.get(KEY_CONFIRM_SUBMIT):
    detail = (
        f" {unanswered} question(s) are unanswered."
        if unanswered > 0 else ""
    )
    st.warning(f"Are you sure you want to submit this section?{detail}")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("Yes, submit section", type="primary", use_container_width=True):
            st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
            report      = submit_section(user_id)
            all_reports = st.session_state.get(KEY_ALL_REPORTS, [])
            all_reports.append(report)
            st.session_state[KEY_ALL_REPORTS] = all_reports
            outcome = advance_full_exam(user_id)
            if outcome == "complete":
                st.session_state[KEY_EXAM_COMPLETE] = True
                st.session_state[KEY_EXAM_RUNNING]  = False
            st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
            st.rerun()

with st.sidebar:
    st.markdown(f"**Section {section_num}/4 Question Map**")
    render_question_map_legend(scored=False)

    def _full_exam_map_state(i: int) -> dict[str, object]:
        ans  = answers_dict.get(i, "")
        flag = i in flagged_set
        icon = "🚩" if flag else ("🟢" if ans else "⬜")
        return {
            "status": "answered" if ans else "unanswered",
            "flagged": flag,
            "help": f"Go to question {i + 1}",
        }
        if mcols[i % 5].button(icon, key=f"femap_{i}"):
            st.session_state[_K["current_idx"]] = i; st.rerun()

    selected_map_idx = render_question_map(
        total=total,
        current_idx=current_idx,
        state_for_index=_full_exam_map_state,
        key_prefix="femap",
    )
    if selected_map_idx is not None:
        st.session_state[_K["current_idx"]] = selected_map_idx; st.rerun()
