"""
pages/7a_Curriculum_Exam.py — Flexible exam builder with curriculum support.

Exam source options
  A. Single Course          — explicit question-count control, one course.
  B. Multiple Courses       — flat pool from several courses.
  C. Curriculum Standard    — equal-weighted split across all curriculum courses.
  D. Weighted Mock          — preset or manual % weights, preview, validate.
  E. Random Mix Generator   — randomly assigns questions across selected courses.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import random
import streamlit as st

from src.auth       import require_login
from src.utils      import page_header, sidebar_nav, render_question, render_timer
from src.database   import (
    get_all_courses, get_all_curriculums,
    get_curriculum_courses, get_weight_presets,
    get_all_questions, get_course_question_count,
    get_attempt_answers, create_weight_preset,
    init_curriculum_tables,
)
from src.exam_engine import (
    start_quiz, submit_section, is_active, current_question,
    next_question, prev_question, record_answer, record_self_grade, toggle_flag,
    seconds_remaining, is_timed_out, clear_quiz,
    persist_current_exam, restore_exam_draft, _K, _st, _set, format_time,
)
from src.question_loader import is_open_ended_question
from src.curriculum_allocation import (
    equal_allocation, preset_allocation, manual_allocation, random_allocation,
    AllocationResult,
)
from src.pdf_export import generate_exam_pdf, make_pdf_filename
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Curriculum Exam · StudyForge",
                   page_icon="📝", layout="wide")

init_curriculum_tables()
user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
restore_exam_draft(user_id, modes={"curriculum_exam"})
page_header("📝 Curriculum Exam Builder",
            "Build exams from a single course, multiple courses, or a full curriculum")

KEY_STAGE        = "ceb_stage"
KEY_EXAM_SOURCE  = "ceb_exam_source"
KEY_REPORT       = "ceb_report"
KEY_DISTRIBUTION = "ceb_distribution"
KEY_EXAM_PDF     = "ceb_exam_pdf"
KEY_EXAM_PDF_NAME = "ceb_exam_pdf_name"
KEY_CONFIRM_SUBMIT = "ceb_confirm_submit"
KEY_OPEN_ENDED_MODE = "ceb_open_ended_mode"

if st.session_state.pop("_exam_restored_notice", False):
    st.success("Your in-progress exam was restored with your saved answers and remaining time.")

def get_stage():  return st.session_state.get(KEY_STAGE, "setup")
def set_stage(s): st.session_state[KEY_STAGE] = s


def _launch_exam(uid, questions, label, timed, mins, course_id, dist):
    if not questions:
        st.error("No questions assembled. Check settings and try again.")
        return
    st.session_state[KEY_EXAM_PDF] = generate_exam_pdf(
        questions=questions,
        title=label,
        subtitle="Generated practice test",
        distribution=dist,
    )
    st.session_state[KEY_EXAM_PDF_NAME] = make_pdf_filename(label)
    start_quiz(
        user_id=uid, mode="curriculum_exam", questions=questions,
        section_type="Mixed", hard_mode=False,
        time_limit_seconds=(mins * 60) if timed else 0,
        section_num=1, course_id=course_id,
        open_ended_mode=st.session_state.get(KEY_OPEN_ENDED_MODE, False),
    )
    st.session_state[KEY_EXAM_SOURCE]  = label
    st.session_state[KEY_DISTRIBUTION] = dist
    set_stage("running")
    persist_current_exam(uid)
    st.rerun()


def _show_allocation_table(result: AllocationResult, total_q: int):
    """Render a clean breakdown of course -> pct -> questions."""
    rows = []
    for r in result.rows:
        rows.append({
            "Course":    r["course_title"],
            "Allocation": f"{r['pct']:.1f}%",
            "Requested": r["requested"],
            "Available": r["available"],
            "Will Use":  r["final"],
            "Status":    "OK" if r["final"] >= r["requested"]
                         else f"Short by {r['requested'] - r['final']}",
        })
    st.table(rows)
    st.caption(
        f"**Total questions that will be generated: {result.final_total}** "
        f"(requested: {total_q})"
    )


def _render_pdf_download(label: str = "Download Exam PDF") -> None:
    pdf_bytes = st.session_state.get(KEY_EXAM_PDF)
    if not pdf_bytes:
        return
    st.download_button(
        label,
        data=pdf_bytes,
        file_name=st.session_state.get(KEY_EXAM_PDF_NAME, "generated_exam.pdf"),
        mime="application/pdf",
        use_container_width=True,
    )


# ═════════════════════════════════════════════════════════════════════════════
# COMPLETE
# ═════════════════════════════════════════════════════════════════════════════
if get_stage() == "complete":
    report = st.session_state.get(KEY_REPORT, {})
    dist   = st.session_state.get(KEY_DISTRIBUTION, [])
    st.balloons()
    st.success("Exam complete!")
    c1, c2, c3 = st.columns(3)
    c1.metric("Raw Score",  f"{report.get('correct',0)} / {report.get('total',0)}")
    c2.metric("% Correct",  f"{report.get('percent_correct',0):.1f}%")
    c3.metric("Avg Time/Q", f"{report.get('avg_time_seconds',0):.0f}s")
    if dist:
        st.divider()
        method_label = dist[0].get("method", "").replace("_", " ").title() if dist else ""
        if method_label:
            st.caption(f"**Allocation method used:** {method_label}")
        st.markdown("**Exam Composition:**")
        st.table([{
            "Course":     d["course"],
            "Allocation": f"{d['weight']:.1f}%" if d.get("weight") is not None else "N/A",
            "Questions":  d["q_count"],
        } for d in dist])
    st.divider()
    with st.expander("Review Questions"):
        attempt_id = _st("attempt_id")
        if attempt_id:
            for i, row in enumerate(get_attempt_answers(attempt_id)):
                icon = "OK" if row["is_correct"] else "X"
                st.markdown(
                    f"**Q{i+1}** {icon}  "
                    f"Your: **{row['selected_answer'] or 'skipped'}** | "
                    f"Correct: **{row['correct_answer']}**"
                )
                st.caption(str(row["stimulus"])[:200])
                if row.get("explanation"): st.info(row["explanation"])
    _render_pdf_download("Download Exam PDF")
    if st.button("Build Another Exam", type="primary", use_container_width=True):
        for k in [KEY_STAGE, KEY_EXAM_SOURCE, KEY_REPORT, KEY_DISTRIBUTION, KEY_EXAM_PDF, KEY_EXAM_PDF_NAME]:
            st.session_state.pop(k, None)
        clear_quiz(); st.rerun()
    st.stop()


# ═════════════════════════════════════════════════════════════════════════════
# RUNNING
# ═════════════════════════════════════════════════════════════════════════════
if get_stage() == "running":
    if not is_active():
        st.error("Exam state lost."); set_stage("setup"); clear_quiz(); st.rerun()
    st_autorefresh(interval=10_000, key="ceb_autorefresh")
    questions    = _st("questions") or []
    current_idx  = _st("current_idx") or 0
    answers_dict = _st("answers") or {}
    flagged_set  = _st("flagged") or set()
    total_secs   = _st("time_limit") or 0
    total        = len(questions)
    answered     = len(answers_dict)
    remaining    = seconds_remaining()
    timed        = total_secs > 0
    if timed and is_timed_out():
        st.warning("Time is up!")
        st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
        report = submit_section(user_id)
        st.session_state[KEY_REPORT] = report
        set_stage("complete"); st.rerun()
    src_lbl = st.session_state.get(KEY_EXAM_SOURCE, "Exam")
    st.markdown(f"### {src_lbl}")
    _render_pdf_download()
    if timed: render_timer(remaining, total_secs, key_prefix="curriculum_exam_timer")
    st.progress(answered/total if total else 0, text=f"{answered}/{total} answered")
    n1,n2,n3,n4 = st.columns([1,1,4,2])
    with n1:
        if st.button("Prev", disabled=(current_idx==0), key="ceb_prev"):
            prev_question(); st.rerun()
    with n2:
        if st.button("Next", disabled=(current_idx==total-1), key="ceb_next"):
            next_question(); st.rerun()
    with n3:
        jump = st.selectbox("Go to:", [f"Q{i+1}" for i in range(total)],
                            index=current_idx, label_visibility="collapsed", key="ceb_jump")
        tidx = int(jump[1:])-1
        if tidx != current_idx:
            st.session_state[_K["current_idx"]] = tidx
            persist_current_exam(user_id)
            st.rerun()
    with n4:
        flabel = "Unflag" if current_idx in flagged_set else "Flag"
        if st.button(flabel, key="ceb_flag"): toggle_flag(current_idx); st.rerun()
    st.divider()
    q = current_question()
    if q:
        # ── Voice Exam Mode ───────────────────────────────────────────────
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
                key=f"ceb_self_grade_{current_idx}",
            )
            record_self_grade(current_idx, self_grade_choice == "Correct")

        picked = render_question(q=q, idx=current_idx, total=total,
                                 selected=answers_dict.get(current_idx,""),
                                 show_answer=False, is_flagged=(current_idx in flagged_set))
        if picked and picked != answers_dict.get(current_idx, ""):
            record_answer(current_idx, picked)
            answers_dict = _st("answers") or {}
            answered = len(answers_dict)
        if st.button("Record Answer", type="primary", use_container_width=True, key="ceb_rec"):
            if not picked: st.warning("Select an answer first.")
            else:
                record_answer(current_idx, picked)
                if current_idx < total-1: next_question()
                st.rerun()
    st.divider()
    unanswered = total - answered
    c_submit, c_quit = st.columns(2)
    with c_submit:
        if st.button("Submit Exam", type="primary", use_container_width=True):
            st.session_state[KEY_CONFIRM_SUBMIT] = True
            st.rerun()
    with c_quit:
        if st.button("Quit", use_container_width=True):
            set_stage("setup")
            for k in [KEY_DISTRIBUTION, KEY_EXAM_PDF, KEY_EXAM_PDF_NAME]:
                st.session_state.pop(k, None)
            st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
            clear_quiz(); st.rerun()
    if st.session_state.get(KEY_CONFIRM_SUBMIT):
        detail = (
            f" {unanswered} question(s) are unanswered."
            if unanswered > 0 else ""
        )
        st.warning(f"Are you sure you want to submit this exam?{detail}")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Yes, submit exam", type="primary", use_container_width=True):
                st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
                report = submit_section(user_id)
                st.session_state[KEY_REPORT] = report
                set_stage("complete"); st.rerun()
        with cancel_col:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pop(KEY_CONFIRM_SUBMIT, None)
                st.rerun()
    with st.sidebar:
        st.markdown("**Question Map**")
        st.caption("Green=Answered  White=Skipped  Flag=Flagged")
        mcols = st.columns(5)
        for i in range(total):
            flag = i in flagged_set
            icon = "F" if flag else ("+" if answers_dict.get(i,"") else "o")
            if mcols[i%5].button(icon, key=f"cebmap_{i}"):
                st.session_state[_K["current_idx"]] = i; st.rerun()
    st.stop()


# ═════════════════════════════════════════════════════════════════════════════
# SETUP
# ═════════════════════════════════════════════════════════════════════════════
st.subheader("Step 1 - Choose Exam Source")
SOURCE_OPTIONS = [
    "Single Course",
    "Multiple Courses",
    "Curriculum - Standard",
    "Curriculum - Weighted Mock",
    "Random Mix Generator",
]
source = st.radio("What should the exam draw questions from?", SOURCE_OPTIONS,
                  horizontal=False, key="ceb_source_radio")
st.divider()
all_courses = get_all_courses()
curriculums = get_all_curriculums()
st.checkbox(
    "Open-ended challenge - hide answer choices",
    key=KEY_OPEN_ENDED_MODE,
    help=(
        "Multiple choice is the default. Turn this on when you want to "
        "remove the options and self-grade your written response."
    ),
)


# ── A: Single Course ──────────────────────────────────────────────────────────
if source == SOURCE_OPTIONS[0]:
    st.subheader("Single Course Exam")
    if not all_courses:
        st.warning("No courses available."); st.stop()
    cid_map = {c["id"]: c["title"] for c in all_courses}
    sel_cid = st.selectbox("Course", list(cid_map.keys()),
                           format_func=lambda x: cid_map[x], key="sc_cid")
    q_count = get_course_question_count(sel_cid)
    st.caption(f"Available questions: **{q_count}**")
    if q_count < 1:
        st.warning("No questions in this course yet."); st.stop()
    num_q = st.slider("Number of questions", 1, min(q_count, 150), min(25, q_count), key="sc_numq")
    timed = st.checkbox("Timed exam?", key="sc_timed")
    mins  = st.number_input("Time limit (minutes)", 5, 180, 35, key="sc_mins") if timed else 0
    if st.button("Generate Exam", type="primary", use_container_width=True, key="sc_gen"):
        pool = get_all_questions(course_id=sel_cid)
        random.shuffle(pool)
        _launch_exam(user_id, pool[:num_q], f"Single Course: {cid_map[sel_cid]}", timed, mins,
                     sel_cid,
                     [{"course": cid_map[sel_cid], "weight": 100.0,
                       "q_count": min(num_q, len(pool)), "method": "single_course"}])


# ── B: Multiple Courses ───────────────────────────────────────────────────────
elif source == SOURCE_OPTIONS[1]:
    st.subheader("Multiple Courses Exam")
    if not all_courses:
        st.warning("No courses available."); st.stop()
    cid_map  = {c["id"]: c["title"] for c in all_courses}
    sel_cids = st.multiselect("Select courses to include", list(cid_map.keys()),
                              format_func=lambda x: cid_map[x], key="mc_cids")
    total_avail = sum(get_course_question_count(cid) for cid in sel_cids)
    if sel_cids: st.caption(f"Total available: **{total_avail}**")
    max_sl = max(5, min(total_avail, 200)) if sel_cids else 5
    def_q  = min(30, max(1, total_avail)) if sel_cids else 5
    num_q  = st.slider("Number of questions", 1, max_sl, def_q, key="mc_numq", disabled=not sel_cids)
    timed  = st.checkbox("Timed?", key="mc_timed")
    mins   = st.number_input("Time limit (minutes)", 5, 180, 35, key="mc_mins") if timed else 0
    if st.button("Generate Exam", type="primary", use_container_width=True, key="mc_gen"):
        if not sel_cids:
            st.error("Select at least one course."); st.stop()
        pool = []
        for cid in sel_cids: pool.extend(get_all_questions(course_id=cid))
        random.shuffle(pool)
        questions = pool[:num_q]
        dist = [{"course": cid_map[cid], "weight": None,
                 "q_count": sum(1 for q in questions if q["course_id"] == cid),
                 "method": "multi_course"}
                for cid in sel_cids]
        _launch_exam(user_id, questions, "Multi-Course Exam", timed, mins, None, dist)


# ── C: Curriculum Standard ────────────────────────────────────────────────────
elif source == SOURCE_OPTIONS[2]:
    st.subheader("Curriculum - Standard Exam")
    st.caption("Questions are distributed equally across the selected courses.")
    if not curriculums:
        st.warning("No curriculums found. Create one in Curriculum Builder."); st.stop()

    curr_map     = {c["id"]: c["title"] for c in curriculums}
    sel_curr     = st.selectbox("Curriculum", list(curr_map.keys()),
                                format_func=lambda x: curr_map[x], key="cs_curr")
    curr_courses = get_curriculum_courses(sel_curr)
    if not curr_courses:
        st.warning("This curriculum has no courses yet."); st.stop()

    avail_map   = {c["id"]: get_course_question_count(c["id"]) for c in curr_courses}
    total_avail = sum(avail_map.values())

    all_cids = [c["id"] for c in curr_courses]
    sel_cids = st.multiselect(
        "Courses to include (default: all)",
        options=all_cids,
        default=all_cids,
        format_func=lambda x: next(c["title"] for c in curr_courses if c["id"] == x),
        key="cs_sel_courses",
    )
    if not sel_cids:
        st.warning("Select at least one course."); st.stop()

    sel_courses     = [c for c in curr_courses if c["id"] in sel_cids]
    sel_avail_map   = {c["id"]: avail_map[c["id"]] for c in sel_courses}
    sel_total_avail = sum(sel_avail_map.values())
    st.caption(f"Total available questions across selected courses: **{sel_total_avail}**")

    max_sl = max(5, min(sel_total_avail, 200))
    def_q  = min(50, max(1, sel_total_avail))
    num_q  = st.slider("Number of questions", 1, max_sl, def_q, key="cs_numq")

    # Live equal-weighting breakdown
    result = equal_allocation(sel_courses, num_q, sel_avail_map)
    n_sel  = len(sel_courses)
    pct_each = 100.0 / n_sel if n_sel else 0.0

    with st.container(border=True):
        st.markdown(
            f"**Allocation method: Equal weighting across {n_sel} selected "
            f"course(s)** ({pct_each:.1f}% each)"
        )
        _show_allocation_table(result, num_q)
        for w in result.warnings:
            st.warning(w)

    timed = st.checkbox("Timed?", key="cs_timed")
    mins  = st.number_input("Time limit (minutes)", 5, 180, 60, key="cs_mins") if timed else 0

    if st.button("Generate Exam", type="primary", use_container_width=True, key="cs_gen"):
        result = equal_allocation(sel_courses, num_q, sel_avail_map)
        if not result.valid:
            for e in result.errors: st.error(e)
            st.stop()
        questions = []
        for r in result.rows:
            pool = get_all_questions(course_id=r["course_id"])
            random.shuffle(pool)
            questions.extend(pool[:r["final"]])
        random.shuffle(questions)
        _launch_exam(user_id, questions,
                     f"Curriculum Standard: {curr_map[sel_curr]}",
                     timed, mins, None, result.as_dist())


# ── D: Weighted Mock ──────────────────────────────────────────────────────────
elif source == SOURCE_OPTIONS[3]:
    st.subheader("Curriculum - Weighted Mock Exam")
    st.caption("Define percentage from each course. Weights must total 100%.")
    if not curriculums:
        st.warning("No curriculums found."); st.stop()

    curr_map     = {c["id"]: c["title"] for c in curriculums}
    sel_curr     = st.selectbox("Curriculum", list(curr_map.keys()),
                                format_func=lambda x: curr_map[x], key="wm_curr")
    curr_courses = get_curriculum_courses(sel_curr)
    if not curr_courses:
        st.warning("No courses in this curriculum."); st.stop()

    avail_map = {c["id"]: get_course_question_count(c["id"]) for c in curr_courses}
    presets   = get_weight_presets(sel_curr)

    col_p, col_t = st.columns([3, 2])
    with col_p:
        preset_opts = {"__none__": "Set weights manually"} | \
                      {str(p["id"]): p["name"] for p in presets}
        chosen_preset = st.selectbox(
            "Load a preset (optional)",
            list(preset_opts.keys()),
            format_func=lambda x: preset_opts[x],
            key="wm_preset_sel",
        )
    with col_t:
        total_q = st.number_input("Total number of questions", 10, 500, 100, step=5,
                                  key="wm_total_q")

    # Resolve preset
    active_preset_data: dict = {}
    active_preset_name: str  = ""
    if chosen_preset != "__none__":
        for p in presets:
            if str(p["id"]) == chosen_preset:
                active_preset_data = p["weights"]
                active_preset_name = p["name"]
                break

    if active_preset_name:
        st.success(f"Loaded preset: **{active_preset_name}**")
        with st.expander("View preset weights", expanded=False):
            norm_pw: dict[int, float] = {}
            for k, v in active_preset_data.items():
                try: norm_pw[int(k)] = float(v)
                except Exception: pass
            p_rows = [{"Course": c["title"],
                       "Preset Weight": f"{norm_pw.get(c['id'], 0.0):.1f}%"}
                      for c in curr_courses]
            st.table(p_rows)
        st.caption(
            "The weight inputs below have been populated from the preset. "
            "You can adjust them before generating."
        )

    st.markdown("**Assign weights per course (must total 100%):**")

    weight_inputs: dict[int, float] = {}
    total_weight = 0.0
    for c in curr_courses:
        q_avail   = avail_map[c["id"]]
        default_w = 0.0
        if active_preset_data:
            default_w = float(
                active_preset_data.get(str(c["id"]),
                active_preset_data.get(c["id"], 0.0))
            )
        w = st.number_input(
            f"{c['title']}  (available: {q_avail})",
            min_value=0.0, max_value=100.0,
            value=default_w, step=0.5, format="%.1f",
            # Key includes chosen_preset so widgets remount with new defaults on preset change
            key=f"wm_w_{sel_curr}_{c['id']}_{chosen_preset}",
        )
        weight_inputs[c["id"]] = w
        total_weight += w

    # Running total
    if abs(total_weight - 100.0) < 0.01:
        st.success(f"Current total: {total_weight:.1f}% - valid")
    elif total_weight > 100.0:
        st.error(f"Current total: {total_weight:.1f}% - exceeds 100%. Please reduce some weights.")
    else:
        remaining_pct = 100.0 - total_weight
        st.warning(
            f"Current total: {total_weight:.1f}%. "
            f"Please adjust to 100% ({remaining_pct:.1f}% still unallocated)."
        )

    normalize_weights = False
    if abs(total_weight - 100.0) > 0.5:
        normalize_weights = st.checkbox(
            "Auto-normalise weights to 100%",
            value=False, key="wm_normalize",
            help="Scales all entered percentages proportionally so they sum to 100%.",
        )

    weights_valid = abs(total_weight - 100.0) < 0.5 or normalize_weights
    if weights_valid and total_q >= 1:
        st.subheader("Preview - Question Distribution")

        if normalize_weights and total_weight > 0:
            norm_wi = {c["id"]: (weight_inputs[c["id"]] / total_weight * 100.0)
                       for c in curr_courses}
        else:
            norm_wi = weight_inputs

        result = manual_allocation(
            courses=curr_courses,
            weight_inputs=norm_wi,
            total_q=int(total_q),
            avail_map=avail_map,
        )

        method_tag   = "preset" if active_preset_name else "manual"
        method_label = (f"Preset weighting ({active_preset_name})"
                        if active_preset_name else "Manual weighting")
        st.caption(f"**Allocation method:** {method_label}")

        _show_allocation_table(result, int(total_q))
        for w in result.warnings: st.warning(w)
        for e in result.errors:   st.error(e)

        if result.valid:
            timed = st.checkbox("Timed exam?", key="wm_timed")
            mins  = st.number_input("Time limit (minutes)", 5, 180,
                                    max(10, result.final_total), key="wm_mins") if timed else 0

            with st.expander("Save these weights as a preset"):
                sp_name = st.text_input("Preset name", key="wm_sp_name",
                                        placeholder="e.g. CFA L1 Official Weights")
                if st.button("Save Preset", key="wm_save_preset"):
                    if not sp_name.strip():
                        st.error("Preset name required.")
                    else:
                        str_w = {str(cid): wv for cid, wv in norm_wi.items()}
                        pid, err = create_weight_preset(sel_curr, sp_name, str_w)
                        if err: st.error(err)
                        else: st.success(f'Preset "{sp_name}" saved.')

            if st.button("Generate Weighted Exam", type="primary",
                         use_container_width=True, key="wm_gen"):
                if result.final_total < 1:
                    st.error("No questions available."); st.stop()
                questions = []
                for r in result.rows:
                    if r["final"] < 1: continue
                    pool = get_all_questions(course_id=r["course_id"])
                    random.shuffle(pool)
                    questions.extend(pool[:r["final"]])
                random.shuffle(questions)
                dist = result.as_dist()
                for d in dist: d["method"] = method_tag
                _launch_exam(user_id, questions,
                             f"Weighted Mock: {curr_map[sel_curr]}",
                             timed, mins, None, dist)
    else:
        st.info("Adjust weights to total 100% (or enable auto-normalise) to preview the distribution.")


# ── E: Random Mix Generator ───────────────────────────────────────────────────
elif source == SOURCE_OPTIONS[4]:
    st.subheader("Random Mix Generator")
    st.caption(
        "Randomly assign question counts across your selected courses. "
        "Regenerate until you find a mix you like, then click Use This Mix."
    )

    if not all_courses:
        st.warning("No courses available."); st.stop()

    cid_map  = {c["id"]: c["title"] for c in all_courses}
    sel_cids = st.multiselect(
        "Courses to include in the random mix",
        options=list(cid_map.keys()),
        default=list(cid_map.keys())[:min(4, len(all_courses))],
        format_func=lambda x: cid_map[x],
        key="rm_cids",
    )
    if not sel_cids:
        st.warning("Select at least one course."); st.stop()

    sel_courses = [c for c in all_courses if c["id"] in sel_cids]
    avail_map   = {c["id"]: get_course_question_count(c["id"]) for c in sel_courses}
    total_avail = sum(avail_map.values())
    st.caption(f"Total available across selected courses: **{total_avail}**")

    col_q, col_mode = st.columns([2, 2])
    with col_q:
        max_q = max(5, min(total_avail, 300))
        num_q = st.slider("Total questions", 1, max_q, min(50, max_q), key="rm_numq")
    with col_mode:
        st.markdown("")
        st.markdown("")
        aggressive = st.toggle(
            "Aggressive randomisation",
            value=False, key="rm_aggressive",
            help=(
                "Balanced: no course takes more than ~40%. "
                "Aggressive: fully random — one course may dominate."
            ),
        )

    MIX_KEY = "rm_current_mix"

    def _generate_mix():
        seed = random.randint(0, 999_999)
        r    = random_allocation(
            courses=sel_courses,
            total_q=num_q,
            avail_map=avail_map,
            balanced=not aggressive,
            seed=seed,
        )
        st.session_state[MIX_KEY] = {
            "result": r, "seed": seed,
            "num_q": num_q, "aggressive": aggressive,
            "sel_cids": list(sel_cids),
        }

    stored_mix = st.session_state.get(MIX_KEY)
    params_changed = (
        stored_mix is None
        or stored_mix.get("num_q") != num_q
        or stored_mix.get("aggressive") != aggressive
        or set(stored_mix.get("sel_cids", [])) != set(sel_cids)
    )
    if params_changed:
        _generate_mix()

    current_mix: AllocationResult = st.session_state[MIX_KEY]["result"]

    st.divider()
    mode_str = "Aggressive random" if aggressive else "Balanced random"
    st.markdown(f"**Generated mix — {mode_str} — {len(sel_courses)} courses**")

    for w in current_mix.warnings:
        st.warning(w)

    mix_rows = [
        {
            "Course":     r["course_title"],
            "Allocation": f"{r['pct']:.1f}%",
            "Questions":  r["final"],
            "Available":  r["available"],
        }
        for r in current_mix.rows
    ]
    st.table(mix_rows)
    st.caption(f"**Total: {current_mix.final_total} question(s)**")

    btn1, btn2, btn3 = st.columns(3)
    with btn1:
        if st.button("Generate Random Mix", use_container_width=True, key="rm_generate"):
            _generate_mix(); st.rerun()
    with btn2:
        if st.button("Regenerate Mix", use_container_width=True, key="rm_regen"):
            _generate_mix(); st.rerun()
    with btn3:
        use_this = st.button("Use This Mix", type="primary",
                             use_container_width=True, key="rm_use",
                             disabled=(not current_mix.valid))

    if not current_mix.valid:
        st.error("Cannot generate exam - no questions available with this mix.")
        st.stop()

    st.divider()
    timed = st.checkbox("Timed exam?", key="rm_timed")
    if timed:
        st.number_input("Time limit (minutes)", 5, 180,
                        max(5, current_mix.final_total), key="rm_mins")

    if use_this:
        timed_val = st.session_state.get("rm_timed", False)
        mins_val  = st.session_state.get("rm_mins", max(5, current_mix.final_total))
        questions = []
        for r in current_mix.rows:
            if r["final"] < 1: continue
            pool = get_all_questions(course_id=r["course_id"])
            random.shuffle(pool)
            questions.extend(pool[:r["final"]])
        random.shuffle(questions)
        _launch_exam(user_id, questions, "Random Mix Exam",
                     timed_val, mins_val, None, current_mix.as_dist())
