"""
pages/5_Practice_Mode.py — Untimed practice drill, filtered by active course.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from src.auth         import require_login
from src.utils        import (page_header, sidebar_nav, require_course,
                               render_question, render_score_card, DIFFICULTY_LABELS)
from src.database     import get_all_questions, get_all_settings, get_distinct_values, get_course
from src.exam_engine  import (
    start_quiz, clear_quiz, is_active, current_question, next_question,
    prev_question, record_answer, submit_section, _st, _set, _K,
)
from src.analytics    import get_weakness_weighted_questions

st.set_page_config(page_title="Practice Mode · StudyForge", page_icon="✏️", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

from src.utils import course_selector
course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"

page_header("✏️ Practice Mode", f"Drill questions at your own pace — {course_title}")

settings  = get_all_settings(user_id)
hard_mode = settings.get("hard_mode", "false") == "true"
show_exp  = settings.get("show_explanations", "always")

# ── Setup form ────────────────────────────────────────────────────────────────
if not is_active():
    st.subheader("Set Up Your Practice Session")

    # Get section/question types specific to this course
    course_sections = get_distinct_values("section_type", course_id=course_id)
    course_qtypes   = get_distinct_values("question_type", course_id=course_id)

    section_opts = ["All"] + (course_sections if course_sections else [])
    qtype_opts   = ["All"] + (course_qtypes   if course_qtypes   else [])

    with st.form("practice_setup"):
        col1, col2 = st.columns(2)
        with col1:
            section_filter = st.selectbox("Section Type", section_opts)
            qtype_filter   = st.selectbox("Question Type", qtype_opts)
        with col2:
            diff_min    = st.slider("Min Difficulty", 1, 5, 1)
            diff_max    = st.slider("Max Difficulty", 1, 5, 5)
            n_questions = st.number_input("Number of Questions",
                                          min_value=1, max_value=100, value=10)

        use_weakness = st.checkbox(
            "⚠️ Weakness Attack Mode — prioritise my weak areas",
            value=(settings.get("question_mix") == "weakness"),
        )
        use_timer  = st.checkbox("⏱ Enable per-question timer (optional)")
        timer_secs = (
            st.number_input("Seconds per question", 30, 300, 120)
            if use_timer else None
        )
        submitted = st.form_submit_button("▶ Start Practice", use_container_width=True)

    if submitted:
        pool = get_all_questions(
            section_type=None  if section_filter == "All" else section_filter,
            question_type=None if qtype_filter   == "All" else qtype_filter,
            min_difficulty=diff_min,
            max_difficulty=diff_max,
            course_id=course_id,
        )
        if not pool:
            st.error(
                f"No questions match those filters in **{course_title}**. "
                "Upload more questions or adjust your filters."
            )
            st.stop()

        if use_weakness:
            questions = get_weakness_weighted_questions(
                user_id, pool, n=int(n_questions), course_id=course_id
            )
        else:
            import random
            questions = random.sample(pool, min(int(n_questions), len(pool)))

        time_limit = (timer_secs * len(questions)) if use_timer and timer_secs else 99999
        clear_quiz()
        start_quiz(
            user_id=user_id,
            mode="practice",
            questions=questions,
            section_type=section_filter,
            hard_mode=hard_mode,
            time_limit_seconds=time_limit,
            course_id=course_id,
        )
        st.session_state["practice_instant_fb"] = (show_exp == "always")
        st.rerun()

    from src.voice_exam import cleanup_voice_exam_panel
    cleanup_voice_exam_panel()   # remove panel if exam just ended
    st.stop()

# ── Active session ────────────────────────────────────────────────────────────
questions    = _st("questions") or []
current_idx  = _st("current_idx") or 0
answers_dict = _st("answers") or {}
flagged_set  = _st("flagged") or set()
instant_fb   = st.session_state.get("practice_instant_fb", True)

total    = len(questions)
answered = len(answers_dict)
q        = current_question()

if q is None:
    st.error("Session error: no questions loaded.")
    clear_quiz()
    st.rerun()

# ── Voice Exam Mode ───────────────────────────────────────────────────────────
from src.voice_exam import render_voice_exam_panel
render_voice_exam_panel(q, current_idx, total)

st.progress(answered / total if total else 0,
            text=f"Progress: {answered}/{total} answered")

nav_left, nav_mid, nav_right = st.columns([1, 6, 1])
with nav_left:
    if st.button("◀ Prev", disabled=(current_idx == 0)):
        prev_question(); st.rerun()
with nav_right:
    if st.button("Next ▶", disabled=(current_idx == total - 1)):
        next_question(); st.rerun()
with nav_mid:
    jump = st.selectbox(
        "Jump to question:", options=list(range(1, total + 1)),
        index=current_idx, label_visibility="collapsed",
    )
    if jump - 1 != current_idx:
        st.session_state[_K["current_idx"]] = jump - 1; st.rerun()

st.divider()

selected      = answers_dict.get(current_idx, "")
is_flagged    = current_idx in flagged_set
already_ans   = current_idx in answers_dict
show_answer   = instant_fb and already_ans

picked = render_question(
    q=q, idx=current_idx, total=total,
    selected=selected, show_answer=show_answer, is_flagged=is_flagged,
)

if not already_ans:
    if st.button("✔ Submit Answer", type="primary", use_container_width=True):
        if not picked:
            st.warning("Please select an answer before submitting.")
        else:
            record_answer(current_idx, picked); st.rerun()
else:
    if current_idx < total - 1:
        if st.button("Next Question →", type="primary", use_container_width=True):
            next_question(); st.rerun()

st.divider()

col_end, col_quit = st.columns(2)
with col_end:
    if st.button("🏁 Finish Session & See Score", use_container_width=True):
        report = submit_section(user_id)
        st.session_state["last_report"] = report
        clear_quiz(); st.rerun()
with col_quit:
    if st.button("✖ Quit Without Saving", use_container_width=True):
        clear_quiz(); st.rerun()

# ── Sidebar question map ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Question Map**")
    st.caption("🟢 Correct  🔴 Wrong  ⬜ Unanswered  🚩 Flagged")
    cols = st.columns(5)
    for i in range(total):
        ans  = answers_dict.get(i, "")
        flag = i in flagged_set
        if ans:
            correct_a = (questions[i].get("correct_answer") or "").upper()
            icon = "🟢" if ans.upper() == correct_a else "🔴"
        else:
            icon = "⬜"
        if flag:
            icon = "🚩"
        if cols[i % 5].button(icon, key=f"map_{i}"):
            st.session_state[_K["current_idx"]] = i; st.rerun()

# ── Score report ──────────────────────────────────────────────────────────────
if not is_active() and "last_report" in st.session_state:
    report = st.session_state.pop("last_report")
    st.success("Session complete!")
    render_score_card(report, "Practice Session Score")
