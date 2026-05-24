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
    save_exam_draft, get_latest_exam_draft, delete_exam_draft,
)
from src.scoring import compute_score


# ── State key names ───────────────────────────────────────────────────────────
_K = {
    "active":          "exam_active",
    "attempt_id":      "exam_attempt_id",
    "questions":       "exam_questions",
    "current_idx":     "exam_current_idx",
    "answers":         "exam_answers",
    "self_grades":     "exam_self_grades",
    "flagged":         "exam_flagged",
    "section_num":     "exam_section_num",
    "section_started": "exam_section_started",
    "mode":            "exam_mode",
    "hard_mode":       "exam_hard_mode",
    "time_limit":      "exam_time_limit",
    "timer_visible":   "exam_timer_visible",
    "timer_paused":    "exam_timer_paused",
    "timer_paused_at": "exam_timer_paused_at",
    "score_report":    "exam_score_report",
    "course_id":       "exam_course_id",
    "open_ended_mode": "exam_open_ended_mode",
    # Full-exam extras
    "full_sections":   "exam_full_sections",
    "full_sec_idx":    "exam_full_sec_idx",
    "on_break":        "exam_on_break",
    "break_started":   "exam_break_started",
    "all_answers":     "exam_all_answers",
    "q_start_time":    "exam_q_start_time",
}

_DRAFT_PREFIXES = (
    "exam_",
    "full_exam_",
    "ceb_",
    "practice_",
    "q_radio_",
    "q_open_ended_",
    "q_self_grade_",
    "timed_self_grade_",
    "fe_self_grade_",
    "ceb_self_grade_",
)

_DRAFT_SKIP_SUFFIXES = ("_pdf", "_pdf_name")


def _st(key) -> Any:
    return st.session_state.get(_K[key])


def _set(key, val) -> None:
    st.session_state[_K[key]] = val


def _jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return {"__type__": "set", "items": [_jsonable(v) for v in value]}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [_jsonable(v) for v in value]}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _restore_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__type__") == "set":
        return set(_restore_value(v) for v in value.get("items", []))
    if isinstance(value, dict) and value.get("__type__") == "tuple":
        return tuple(_restore_value(v) for v in value.get("items", []))
    if isinstance(value, list):
        return [_restore_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _restore_value(v) for k, v in value.items()}
    return value


def _restore_index_keyed_dict(value: Any) -> dict:
    restored = _restore_value(value) or {}
    if not isinstance(restored, dict):
        return {}
    result = {}
    for key, item in restored.items():
        try:
            result[int(key)] = item
        except (TypeError, ValueError):
            result[key] = item
    return result


def _should_snapshot_key(key: str) -> bool:
    if key.endswith(_DRAFT_SKIP_SUFFIXES):
        return False
    return key in _K.values() or key.startswith(_DRAFT_PREFIXES)


def persist_current_exam(user_id: int | None = None) -> None:
    """Save the active in-progress exam/page state as a resumable draft."""
    attempt_id = _st("attempt_id")
    if not attempt_id or not _st("active"):
        return
    if user_id is None:
        user_id = st.session_state.get("user_id")
    if not user_id:
        return

    snapshot = {}
    for key, value in st.session_state.items():
        if _should_snapshot_key(str(key)):
            saved = _jsonable(value)
            if saved is not None:
                snapshot[str(key)] = saved
    snapshot["exam_remaining_seconds"] = seconds_remaining()
    snapshot["exam_current_question_elapsed"] = time_on_current_question()
    snapshot["exam_saved_at"] = time.time()
    save_exam_draft(
        user_id=user_id,
        attempt_id=attempt_id,
        mode=_st("mode") or "",
        course_id=_st("course_id"),
        state=snapshot,
    )


def restore_exam_draft(
    user_id: int,
    modes: list[str] | tuple[str, ...] | set[str] | None = None,
    course_id=None,
) -> bool:
    """Restore the newest unfinished draft into session_state."""
    if is_active():
        return False
    draft = get_latest_exam_draft(user_id, modes=modes, course_id=course_id)
    if not draft or not draft.get("state"):
        return False

    state = draft["state"]
    for key, value in state.items():
        if key in {"exam_remaining_seconds", "exam_current_question_elapsed", "exam_saved_at"}:
            continue
        if key in {_K["answers"], _K["self_grades"]}:
            st.session_state[key] = _restore_index_keyed_dict(value)
        else:
            st.session_state[key] = _restore_value(value)

    limit = st.session_state.get(_K["time_limit"]) or 0
    remaining = state.get("exam_remaining_seconds")
    if limit and remaining is not None:
        elapsed = max(0.0, float(limit) - float(remaining))
        now = time.time()
        st.session_state[_K["section_started"]] = now - elapsed
        q_elapsed = max(0.0, float(state.get("exam_current_question_elapsed") or 0.0))
        st.session_state[_K["q_start_time"]] = now - q_elapsed
        st.session_state[_K["timer_paused"]] = False
        st.session_state[_K["timer_paused_at"]] = None

    st.session_state["_exam_restored_notice"] = True
    persist_current_exam(user_id)
    return True


def _open_ended_question_copy(q: dict) -> dict:
    question = dict(q)
    correct = str(question.get("correct_answer") or "").strip().upper()
    if correct in {"A", "B", "C", "D", "E"}:
        question["_sample_answer"] = str(
            question.get(f"choice_{correct.lower()}") or ""
        ).strip()
    question["_force_open_ended"] = True
    return question


def _apply_open_ended_mode(questions: list[dict], enabled: bool) -> list[dict]:
    if not enabled:
        return questions
    return [_open_ended_question_copy(q) for q in questions]


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
    open_ended_mode: bool = False,
) -> int:
    """Initialise session state and create a DB attempt row. Returns attempt_id."""
    questions = _apply_open_ended_mode(questions, open_ended_mode)
    attempt_id = create_attempt(
        user_id, mode, section_type,
        settings_snapshot={
            "hard_mode": hard_mode,
            "time_limit": time_limit_seconds,
            "open_ended_mode": open_ended_mode,
        },
        is_hard_mode=hard_mode,
        course_id=course_id,
    )
    _set("active",          True)
    _set("attempt_id",      attempt_id)
    _set("questions",       questions)
    _set("current_idx",     0)
    _set("answers",         {})
    _set("self_grades",     {})
    _set("flagged",         set())
    _set("section_num",     section_num)
    _set("section_started", time.time())
    _set("q_start_time",    time.time())
    _set("mode",            mode)
    _set("hard_mode",       hard_mode)
    _set("time_limit",      time_limit_seconds)
    _set("timer_visible",   time_limit_seconds > 0)
    _set("timer_paused",    False)
    _set("timer_paused_at", None)
    _set("score_report",    None)
    _set("course_id",       course_id)
    _set("open_ended_mode", open_ended_mode)
    persist_current_exam(user_id)
    return attempt_id


def clear_quiz() -> None:
    attempt_id = _st("attempt_id")
    if attempt_id:
        delete_exam_draft(attempt_id)
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
    persist_current_exam()


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
    persist_current_exam()


def record_answer(idx: int, selected: str) -> None:
    ans     = _st("answers") or {}
    ans[idx] = selected
    _set("answers", ans)
    persist_current_exam()


def record_self_grade(idx: int, is_correct: bool) -> None:
    grades = _st("self_grades") or {}
    grades[idx] = bool(is_correct)
    _set("self_grades", grades)
    persist_current_exam()


# ── Timing ────────────────────────────────────────────────────────────────────
def seconds_remaining() -> float:
    started = _st("section_started") or time.time()
    limit   = _st("time_limit") or (35 * 60)
    if limit <= 0:
        return 0.0
    now = _st("timer_paused_at") if is_timer_paused() else time.time()
    return max(0.0, limit - (now - started))


def time_on_current_question() -> float:
    q_start = _st("q_start_time") or time.time()
    now = _st("timer_paused_at") if is_timer_paused() else time.time()
    return now - q_start


def format_time(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m:02d}:{s:02d}"


def is_timed_out() -> bool:
    if _st("mode") == "practice":
        return False
    if is_timer_paused():
        return False
    return seconds_remaining() <= 0


def has_timer() -> bool:
    return (_st("time_limit") or 0) > 0


def is_timer_visible() -> bool:
    return bool(_st("timer_visible")) if has_timer() else False


def set_timer_visible(visible: bool) -> None:
    if has_timer():
        _set("timer_visible", bool(visible))
        persist_current_exam()


def toggle_timer_visibility() -> None:
    set_timer_visible(not is_timer_visible())


def is_timer_paused() -> bool:
    return bool(_st("timer_paused"))


def pause_timer() -> None:
    if has_timer() and not is_timer_paused():
        _set("timer_paused", True)
        _set("timer_paused_at", time.time())
        persist_current_exam()


def resume_timer() -> None:
    if not is_timer_paused():
        return
    paused_at = _st("timer_paused_at") or time.time()
    paused_for = max(0.0, time.time() - paused_at)

    if _st("section_started") is not None:
        _set("section_started", _st("section_started") + paused_for)
    if _st("q_start_time") is not None:
        _set("q_start_time", _st("q_start_time") + paused_for)

    _set("timer_paused", False)
    _set("timer_paused_at", None)
    persist_current_exam()


def toggle_timer_pause() -> None:
    if is_timer_paused():
        resume_timer()
    else:
        pause_timer()


# ── Submit section ────────────────────────────────────────────────────────────
def submit_section(user_id: int) -> dict:
    """
    Save all answers to DB, mark attempt complete, return score report.
    For full-exam mode, accumulates answers but does NOT mark complete yet.
    """
    questions       = _st("questions") or []
    answers         = _st("answers") or {}
    self_grades     = _st("self_grades") or {}
    flagged         = _st("flagged") or set()
    attempt_id      = _st("attempt_id")
    section_num     = _st("section_num") or 1
    section_started = _st("section_started") or time.time()
    mode            = _st("mode")
    submitted_at    = _st("timer_paused_at") if is_timer_paused() else time.time()

    from src.question_loader import is_open_ended_question

    answer_rows = []
    for idx, q in enumerate(questions):
        selected   = answers.get(idx, "")
        if is_open_ended_question(q):
            is_correct = bool(selected.strip()) and bool(self_grades.get(idx, False))
        else:
            is_correct = selected.upper() == (q.get("correct_answer") or "").upper()
        time_spent = max(0.0, (submitted_at - section_started) / max(len(questions), 1))

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
    if attempt_id:
        delete_exam_draft(attempt_id)
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
                    course_id: int | None = None,
                    open_ended_mode: bool = False) -> None:
    sections = build_full_exam_sections(user_id, hard_mode, course_id=course_id)
    _set("full_sections", sections)
    _set("full_sec_idx",  0)
    _set("on_break",      False)
    _set("all_answers",   [])
    _set("hard_mode",     hard_mode)
    _set("course_id",     course_id)
    _set("open_ended_mode", open_ended_mode)
    _start_full_section(user_id, 0, sections, hard_mode, course_id, open_ended_mode)


def _start_full_section(
    user_id: int, sec_idx: int,
    sections: list[dict], hard_mode: bool,
    course_id: int | None = None,
    open_ended_mode: bool | None = None,
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
        open_ended_mode=(
            _st("open_ended_mode") if open_ended_mode is None else open_ended_mode
        ),
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
        _start_full_section(
            user_id,
            next_idx,
            sections,
            _st("hard_mode") or False,
            course_id,
            _st("open_ended_mode") or False,
        )
        pause_timer()
        return "break"

    if next_idx >= len(sections):
        return "complete"

    _start_full_section(user_id, next_idx, sections,
                        _st("hard_mode") or False, course_id,
                        _st("open_ended_mode") or False)
    return "next_section"
