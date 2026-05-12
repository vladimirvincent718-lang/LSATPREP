"""
exam_engine.py — Manages in-progress quiz/exam state in st.session_state.
All state keys are namespaced under "exam_*" to avoid collisions.
"""

from __future__ import annotations
import time
import random
from typing import Any

import streamlit as st

from src.database import (
    create_attempt, save_answer, complete_attempt,
    add_to_journal, get_all_questions, get_setting,
)
from src.scoring import compute_score


# ── State key names ───────────────────────────────────────────────────────────
_K = {
    "active":          "exam_active",
    "attempt_id":      "exam_attempt_id",
    "questions":       "exam_questions",
    "current_idx":     "exam_current_idx",
    "answers":         "exam_answers",
    "flagged":         "exam_flagged",
    "section_num":     "exam_section_num",
    "section_started": "exam_section_started",
    "mode":            "exam_mode",
    "hard_mode":       "exam_hard_mode",
    "time_limit":      "exam_time_limit",
    "score_report":    "exam_score_report",
    "course_id":       "exam_course_id",
    # Full-exam extras
    "full_sections":   "exam_full_sections",
    "full_sec_idx":    "exam_full_sec_idx",
    "on_break":        "exam_on_break",
    "break_started":   "exam_break_started",
    "all_answers":     "exam_all_answers",
    "q_start_time":    "exam_q_start_time",
}


def _st(key) -> Any:
    return st.session_state.get(_K[key])


def _set(key, val) -> None:
    st.session_state[_K[key]] = val


# ── Start / stop ──────────────────────────────────────────────────────────────
def start_quiz(
    user_id: int,
    mode: str,
    questions: list[dict],
    section_type: str,
    hard_mode: bool = False,
    time_limit_seconds: int = 35 * 60,
    section_num: int = 1,
    course_id: int | None = None,
) -> int:
    """Initialise session state and create a DB attempt row. Returns attempt_id."""
    attempt_id = create_attempt(
        user_id, mode, section_type,
        settings_snapshot={"hard_mode": hard_mode, "time_limit": time_limit_seconds},
        is_hard_mode=hard_mode,
        course_id=course_id,
    )
    _set("active",          True)
    _set("attempt_id",      attempt_id)
    _set("questions",       questions)
    _set("current_idx",     0)
    _set("answers",         {})
    _set("flagged",         set())
    _set("section_num",     section_num)
    _set("section_started", time.time())
    _set("q_start_time",    time.time())
    _set("mode",            mode)
    _set("hard_mode",       hard_mode)
    _set("time_limit",      time_limit_seconds)
    _set("score_report",    None)
    _set("course_id",       course_id)
    return attempt_id


def clear_quiz() -> None:
    for k in _K.values():
        st.session_state.pop(k, None)


def is_active() -> bool:
    return bool(_st("active"))


# ── Navigation ────────────────────────────────────────────────────────────────
def current_question() -> dict | None:
    qs  = _st("questions") or []
    idx = _st("current_idx") or 0
    return qs[idx] if 0 <= idx < len(qs) else None


def go_to(idx: int) -> None:
    qs  = _st("questions") or []
    idx = max(0, min(idx, len(qs) - 1))
    _set("current_idx", idx)
    _set("q_start_time", time.time())


def next_question() -> None:
    go_to((_st("current_idx") or 0) + 1)


def prev_question() -> None:
    go_to((_st("current_idx") or 0) - 1)


def toggle_flag(idx: int | None = None) -> None:
    if idx is None:
        idx = _st("current_idx") or 0
    flags = _st("flagged") or set()
    if idx in flags:
        flags.discard(idx)
    else:
        flags.add(idx)
    _set("flagged", flags)


def record_answer(idx: int, selected: str) -> None:
    ans     = _st("answers") or {}
    ans[idx] = selected
    _set("answers", ans)


# ── Timing ────────────────────────────────────────────────────────────────────
def seconds_remaining() -> float:
    started = _st("section_started") or time.time()
    limit   = _st("time_limit") or (35 * 60)
    return max(0.0, limit - (time.time() - started))


def time_on_current_question() -> float:
    q_start = _st("q_start_time") or time.time()
    return time.time() - q_start


def format_time(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m:02d}:{s:02d}"


def is_timed_out() -> bool:
    if _st("mode") == "practice":
        return False
    return seconds_remaining() <= 0


# ── Submit section ────────────────────────────────────────────────────────────
def submit_section(user_id: int) -> dict:
    """
    Save all answers to DB, mark attempt complete, return score report.
    For full-exam mode, accumulates answers but does NOT mark complete yet.
    """
    questions       = _st("questions") or []
    answers         = _st("answers") or {}
    flagged         = _st("flagged") or set()
    attempt_id      = _st("attempt_id")
    section_num     = _st("section_num") or 1
    section_started = _st("section_started") or time.time()
    mode            = _st("mode")

    answer_rows = []
    for idx, q in enumerate(questions):
        selected   = answers.get(idx, "")
        is_correct = selected.upper() == (q.get("correct_answer") or "").upper()
        time_spent = max(0.0, (time.time() - section_started) / max(len(questions), 1))

        save_answer(
            attempt_id=attempt_id,
            question_id=q["id"],
            selected=selected,
            is_correct=is_correct,
            time_spent=time_spent,
            is_flagged=(idx in flagged),
            section_num=section_num,
        )

        if selected and not is_correct:
            add_to_journal(user_id, q["id"], attempt_id)

        answer_rows.append({
            **q,
            "selected_answer":    selected,
            "is_correct":         is_correct,
            "time_spent_seconds": time_spent,
            "is_flagged":         idx in flagged,
            "section_number":     section_num,
        })

    report = compute_score(answer_rows)

    if mode in ("practice", "timed_section"):
        complete_attempt(
            attempt_id,
            total=report["total"],
            correct=report["correct"],
            section_scores={str(section_num): report},
        )

    _set("score_report", report)
    _set("active", False)
    return report


# ── Full-exam helpers ─────────────────────────────────────────────────────────
def build_full_exam_sections(
    user_id: int,
    hard_mode: bool = False,
    course_id: int | None = None,
) -> list[dict]:
    """Build section configs for the full exam from the selected course."""
    structure = [
        {"section_type": "Logical Reasoning",    "is_scored": True},
        {"section_type": "Logical Reasoning",    "is_scored": True},
        {"section_type": "Reading Comprehension","is_scored": True},
        {"section_type": "Logical Reasoning",    "is_scored": False, "label": "Experimental"},
    ]
    random.shuffle(structure)

    sections = []
    for s in structure:
        q_pool = get_all_questions(
            section_type=s["section_type"],
            min_difficulty=4 if hard_mode else 1,
            max_difficulty=5,
            course_id=course_id,
        )
        if hard_mode:
            hard_pool = [q for q in q_pool if q.get("difficulty", 3) >= 4]
            if len(hard_pool) >= 10:
                q_pool = hard_pool + [q for q in q_pool if q.get("difficulty", 3) < 4]

        chosen = q_pool[:25]
        random.shuffle(chosen)
        sections.append({**s, "questions": chosen})

    return sections


def start_full_exam(user_id: int, hard_mode: bool = False,
                    course_id: int | None = None) -> None:
    sections = build_full_exam_sections(user_id, hard_mode, course_id=course_id)
    _set("full_sections", sections)
    _set("full_sec_idx",  0)
    _set("on_break",      False)
    _set("all_answers",   [])
    _set("hard_mode",     hard_mode)
    _set("course_id",     course_id)
    _start_full_section(user_id, 0, sections, hard_mode, course_id)


def _start_full_section(
    user_id: int, sec_idx: int,
    sections: list[dict], hard_mode: bool,
    course_id: int | None = None,
) -> None:
    sec      = sections[sec_idx]
    time_min = 30 if hard_mode else 35
    start_quiz(
        user_id=user_id,
        mode="full_exam",
        questions=sec["questions"],
        section_type=sec["section_type"],
        hard_mode=hard_mode,
        time_limit_seconds=time_min * 60,
        section_num=sec_idx + 1,
        course_id=course_id,
    )


def advance_full_exam(user_id: int) -> str:
    """Called after each section. Returns 'break' | 'next_section' | 'complete'."""
    sec_idx  = st.session_state.get(_K["full_sec_idx"], 0)
    sections = st.session_state.get(_K["full_sections"], [])
    course_id = _st("course_id")

    next_idx = sec_idx + 1
    _set("full_sec_idx", next_idx)

    if sec_idx == 1:
        _set("on_break",      True)
        _set("break_started", time.time())
        return "break"

    if next_idx >= len(sections):
        return "complete"

    _start_full_section(user_id, next_idx, sections,
                        _st("hard_mode") or False, course_id)
    return "next_section"
