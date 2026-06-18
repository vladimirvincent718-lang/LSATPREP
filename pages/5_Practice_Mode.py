"""
pages/5_Practice_Mode.py — Untimed practice drill, filtered by active course.
"""

import sys, os
import json
import re
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from html import escape
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import random

from src.auth         import require_login
from src.utils        import (page_header, sidebar_nav,
                               render_question, render_score_card, DIFFICULTY_LABELS,
                               get_effective_admin)
from src.database     import (
    get_all_questions, get_all_settings, get_distinct_values,
    get_enrolled_courses, get_course_question_count, set_setting,
    get_answer_stats,
)
from src.exam_engine  import (
    start_quiz, clear_quiz, is_active, current_question, next_question,
    prev_question, record_answer, record_self_grade,
    submit_section, persist_current_exam,
    restore_exam_draft, _st, _set, _K,
)
from src.analytics    import get_smart_review_questions
from src.question_loader import is_open_ended_question
from src.question_map import render_question_map, render_question_map_legend
from src.pdf_export import generate_exam_pdf, make_pdf_filename
from src.email_notifications import send_take_home_exam_pdf

PRACTICE_POOL_KEY = "practice_question_pool"
PRACTICE_NOTICE_KEY = "practice_session_notice"
PRACTICE_PDF_KEY = "practice_pdf"
PRACTICE_PDF_NAME_KEY = "practice_pdf_name"
PRACTICE_CONFIRM_FINISH_KEY = "practice_confirm_finish"
PRACTICE_MIN_DIFFICULTY_KEY = "practice_min_difficulty"
PRACTICE_MAX_DIFFICULTY_KEY = "practice_max_difficulty"
PRACTICE_PREV_MIN_DIFFICULTY_KEY = "practice_prev_min_difficulty"
PRACTICE_USE_WEAKNESS_KEY = "practice_use_weakness"
PRACTICE_USE_TIMER_KEY = "practice_use_timer"
PRACTICE_EXPANDED_ANSWER_KEY = "practice_expanded_answer_idxs"
PRACTICE_TIMER_ENABLED_KEY = "practice_timer_enabled"
PRACTICE_TIMER_SECONDS_KEY = "practice_timer_seconds"
PRACTICE_SETUP_TIMER_SECONDS_KEY = "practice_setup_timer_seconds"
PRACTICE_TIMER_CURRENT_IDX_KEY = "practice_timer_current_idx"
PRACTICE_TIMER_REMAINING_KEY = "practice_timer_remaining_seconds"
PRACTICE_TIMER_LAST_STARTED_KEY = "practice_timer_last_started_at"
PRACTICE_TIMER_PAUSED_KEY = "practice_timer_paused"
PRACTICE_TIMER_VISIBLE_KEY = "practice_timer_visible"
PRACTICE_N_QUESTIONS_KEY = "practice_n_questions"
PRACTICE_DIFFICULTY_COUNT_PREFIX = "practice_difficulty_count"
PRACTICE_BULK_DIFFICULTY_COUNT_KEY = "practice_bulk_difficulty_count"
PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY = "practice_last_applied_bulk_difficulty_count"
PRACTICE_QTYPE_KEY = "practice_qtype_filter"
PRACTICE_MODULES_KEY = "practice_module_filters"
PRACTICE_QUESTION_ORDER_KEY = "practice_question_order"
PRACTICE_DIFFICULTY_MODE_PREFIX = "practice_difficulty_mode"
PRACTICE_TAKE_HOME_KEY = "practice_take_home_exam"
PRACTICE_TIMEOUT_NOTICE_KEY = "practice_timeout_notice"
PRACTICE_TIMED_OUT_QUESTIONS_KEY = "practice_timed_out_questions"
PRACTICE_TIMEOUT_ANSWER = "__TIMEOUT__"
PRACTICE_SKIPPED_NOTICE_KEY = "practice_skipped_notice"
PRACTICE_SKIPPED_QUESTIONS_KEY = "practice_skipped_questions"
PRACTICE_SKIPPED_ANSWER = "__SKIPPED__"
PRACTICE_REACHED_QUESTIONS_KEY = "practice_reached_questions"
PRACTICE_DEFAULT_TIMER_SECONDS = 120
MODULE_ALL = "All modules (randomized)"
MODULE_RANDOM = "Random module"
PRACTICE_LAST_SETTINGS_KEY = "practice_mode_last_settings"
QUESTION_ORDER_RANDOM = "Randomized"
QUESTION_ORDER_BY_DIFFICULTY = "By difficulty (1 to 5)"
QUESTION_ORDER_OPTIONS = [QUESTION_ORDER_RANDOM, QUESTION_ORDER_BY_DIFFICULTY]
QUESTION_MODE_MULTIPLE_CHOICE = "Multiple choice"
QUESTION_MODE_OPEN_ENDED = "Open-ended challenge"
QUESTION_MODE_OPTIONS = [QUESTION_MODE_MULTIPLE_CHOICE, QUESTION_MODE_OPEN_ENDED]


def _today_bounds() -> tuple[str, str, date]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return (
        f"{today.isoformat()} 00:00:00",
        f"{tomorrow.isoformat()} 00:00:00",
        today,
    )


def _today_label(value: date) -> str:
    return value.strftime("%b %#d") if os.name == "nt" else value.strftime("%b %-d")


def _latest_practice_time(answers: list[dict]) -> str:
    if not answers:
        return "No scored practice yet today"
    latest = max(str(answer.get("completed_at") or "") for answer in answers)
    return latest[11:16] if len(latest) >= 16 else latest


def _current_practice_progress() -> str:
    if not is_active() or _st("mode") != "practice":
        return ""

    questions = _st("questions") or []
    answers = _st("answers") or {}
    answered = len({
        int(idx) if isinstance(idx, int) or str(idx).isdigit() else idx
        for idx in answers.keys()
    })
    total = len(questions)
    if not total:
        return ""
    return f" Current session: {answered}/{total} answered; it joins today's total when scored."


def _render_practice_dashboard_strip(
    enrolled_course_ids: list[int],
    active_course_id: int | None,
    active_course_title: str,
) -> None:
    completed_from, completed_to, today = _today_bounds()
    today_answers = [
        answer for answer in get_answer_stats(
            user_id,
            course_ids=enrolled_course_ids,
            completed_from=completed_from,
            completed_to=completed_to,
        )
        if answer.get("mode") == "practice"
    ]
    active_course_answers = [
        answer for answer in today_answers
        if active_course_id is not None
        and answer.get("question_course_id") == active_course_id
    ]
    session_count = len({
        answer.get("attempt_id")
        for answer in today_answers
        if answer.get("attempt_id") is not None
    })
    modules_today = {
        str(answer.get("section_type") or "Unknown Module").strip() or "Unknown Module"
        for answer in today_answers
    }
    correct_today = sum(1 for answer in today_answers if answer.get("is_correct"))
    accuracy_today = (
        round(correct_today / len(today_answers) * 100)
        if today_answers
        else None
    )

    latest_time = escape(_latest_practice_time(today_answers))
    today_label = escape(_today_label(today))
    safe_course = escape(active_course_title)
    progress_note = escape(_current_practice_progress())
    accuracy_label = f"{accuracy_today}%" if accuracy_today is not None else "-"

    st.markdown(
        f"""
<section class="sf-practice-today-dashboard" aria-label="Practice dashboard">
  <div class="sf-practice-today-copy">
    <p class="sf-practice-today-eyebrow">Practice Dashboard - {today_label}</p>
    <h2>{len(today_answers)} questions today</h2>
    <p>Scored practice questions across your enrolled courses. Latest scored session: {latest_time}.{progress_note}</p>
  </div>
  <div class="sf-practice-today-metrics">
    <div class="sf-practice-today-metric">
      <span>{session_count}</span>
      <p>Practice Sessions</p>
      <small>completed today</small>
    </div>
    <div class="sf-practice-today-metric">
      <span>{len(modules_today)}</span>
      <p>Modules</p>
      <small>practiced today</small>
    </div>
    <div class="sf-practice-today-metric">
      <span>{len(active_course_answers)}</span>
      <p>{safe_course}</p>
      <small>active course today</small>
    </div>
    <div class="sf-practice-today-metric">
      <span>{accuracy_label}</span>
      <p>Accuracy</p>
      <small>practice today</small>
    </div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )


def _install_practice_dashboard_styles() -> None:
    st.markdown(
        """
<style>
.sf-practice-today-dashboard {
    align-items: stretch;
    background:
        radial-gradient(circle at top left, rgba(29, 78, 216, 0.15), transparent 34%),
        linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
    border: 1px solid #d8dee8;
    border-radius: 8px;
    box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
    display: grid;
    gap: 1rem;
    grid-template-columns: minmax(15rem, 1.1fr) minmax(22rem, 2.4fr);
    margin: 0.25rem 0 1.45rem;
    padding: 1rem 1.15rem;
}
.sf-practice-today-copy h2 {
    color: #0f172a;
    font-size: 1.65rem;
    line-height: 1.15;
    margin: 0.2rem 0 0.35rem;
}
.sf-practice-today-copy p {
    color: #53627c;
    margin: 0;
}
.sf-practice-today-eyebrow {
    color: #1d4ed8 !important;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    margin: 0 !important;
    text-transform: uppercase;
}
.sf-practice-today-metrics {
    display: grid;
    gap: 0.75rem;
    grid-template-columns: repeat(4, minmax(0, 1fr));
}
.sf-practice-today-metric {
    background: rgba(255, 255, 255, 0.84);
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    min-width: 0;
    padding: 0.85rem 0.9rem;
}
.sf-practice-today-metric span {
    color: #0f172a;
    display: block;
    font-size: 1.55rem;
    font-weight: 850;
    line-height: 1;
}
.sf-practice-today-metric p {
    color: #172033;
    font-weight: 750;
    margin: 0.45rem 0 0.15rem;
    overflow-wrap: anywhere;
}
.sf-practice-today-metric small {
    color: #64748b;
    display: block;
    font-size: 0.78rem;
    overflow-wrap: anywhere;
}
@media (max-width: 1000px) {
    .sf-practice-today-dashboard {
        grid-template-columns: 1fr;
    }
    .sf-practice-today-metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
@media (max-width: 640px) {
    .sf-practice-today-metrics {
        grid-template-columns: 1fr;
    }
}
</style>
""",
        unsafe_allow_html=True,
    )


def _read_last_practice_settings(settings: dict) -> dict:
    try:
        saved = json.loads(settings.get(PRACTICE_LAST_SETTINGS_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        return {}
    return saved if isinstance(saved, dict) else {}


def _valid_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(parsed, max_value))


def _default_question_time_seconds(settings: dict) -> int:
    return _valid_int(
        settings.get("question_time_seconds"),
        PRACTICE_DEFAULT_TIMER_SECONDS,
        15,
        600,
    )


def _saved_list(saved: dict, key: str, valid_values: set | None = None) -> list:
    raw = saved.get(key, [])
    if not isinstance(raw, list):
        raw = [raw] if raw not in (None, "") else []
    values = []
    for item in raw:
        if item in (None, ""):
            continue
        if valid_values is not None and item not in valid_values:
            continue
        values.append(item)
    return values


def _saved_difficulty_counts(saved: dict) -> dict[int, int]:
    raw = saved.get("difficulty_counts")
    if isinstance(raw, dict):
        return {
            difficulty: _valid_int(raw.get(str(difficulty), raw.get(difficulty)), 0, 0, 100)
            for difficulty in range(1, 6)
        }

    total = _valid_int(saved.get("n_questions"), 10, 1, 100)
    return {difficulty: (total if difficulty == 1 else 0) for difficulty in range(1, 6)}


def _difficulty_mode_key(difficulty: int) -> str:
    return f"{PRACTICE_DIFFICULTY_MODE_PREFIX}_{difficulty}"


def _saved_difficulty_modes(saved: dict) -> dict[int, str]:
    legacy_open_ended = bool(saved.get("open_ended_mode", False))
    default_mode = QUESTION_MODE_OPEN_ENDED if legacy_open_ended else QUESTION_MODE_MULTIPLE_CHOICE
    raw = saved.get("difficulty_modes")
    if not isinstance(raw, dict):
        return {difficulty: default_mode for difficulty in range(1, 6)}

    return {
        difficulty: (
            raw.get(str(difficulty), raw.get(difficulty))
            if raw.get(str(difficulty), raw.get(difficulty)) in QUESTION_MODE_OPTIONS
            else default_mode
        )
        for difficulty in range(1, 6)
    }


def _open_ended_question_copy(q: dict) -> dict:
    question = dict(q)
    correct = str(question.get("correct_answer") or "").strip().upper()
    if correct in {"A", "B", "C", "D", "E"}:
        question["_sample_answer"] = str(
            question.get(f"choice_{correct.lower()}") or ""
        ).strip()
    question["_force_open_ended"] = True
    return question


def _apply_difficulty_question_modes(
    questions: list[dict],
    difficulty_modes: dict[int, str],
) -> list[dict]:
    transformed = []
    for question in questions:
        difficulty = _valid_int(question.get("difficulty"), 3, 1, 5)
        if difficulty_modes.get(difficulty) == QUESTION_MODE_OPEN_ENDED:
            transformed.append(_open_ended_question_copy(question))
        else:
            transformed.append(question)
    return transformed


def _difficulty_count_key(difficulty: int) -> str:
    return f"{PRACTICE_DIFFICULTY_COUNT_PREFIX}_{difficulty}"


def _apply_bulk_difficulty_count() -> None:
    bulk_count = _valid_int(
        st.session_state.get(PRACTICE_BULK_DIFFICULTY_COUNT_KEY),
        0,
        0,
        100,
    )
    for difficulty in range(1, 6):
        st.session_state[_difficulty_count_key(difficulty)] = bulk_count
    st.session_state[PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY] = bulk_count


def _natural_sort_key(value: str) -> list:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value or "")
    ]


def _question_id(q: dict) -> int | None:
    return q.get("id")


def _answer_key_variants(idx: int) -> tuple[int, str]:
    return idx, str(idx)


def _dict_get_idx(data: dict, idx: int, default=None):
    for key in _answer_key_variants(idx):
        if key in data:
            return data.get(key)
    return default


def _dict_has_idx(data: dict, idx: int) -> bool:
    return any(key in data for key in _answer_key_variants(idx))


def _dict_pop_idx(data: dict, idx: int) -> None:
    for key in _answer_key_variants(idx):
        data.pop(key, None)


def _practice_pool() -> list[dict]:
    pool = st.session_state.get(PRACTICE_POOL_KEY)
    if pool:
        return pool

    course_id = _st("course_id")
    if course_id is not None:
        return get_all_questions(course_id=course_id)

    enrolled_ids = {course["id"] for course in enrolled_courses}
    return [
        q for q in get_all_questions()
        if q.get("course_id") in enrolled_ids
    ]


def _swap_current_question() -> bool:
    questions = _st("questions") or []
    current_idx = _st("current_idx") or 0
    if not questions or not (0 <= current_idx < len(questions)):
        return False

    used_ids = {
        _question_id(question)
        for question in questions
        if _question_id(question) is not None
    }
    candidates = [
        question for question in _practice_pool()
        if _question_id(question) not in used_ids
    ]
    if not candidates:
        return False

    questions[current_idx] = random.choice(candidates)
    _set("questions", questions)

    answers = _st("answers") or {}
    answers.pop(current_idx, None)
    _set("answers", answers)
    self_grades = _st("self_grades") or {}
    self_grades.pop(current_idx, None)
    _set("self_grades", self_grades)
    expanded_answers = st.session_state.get(PRACTICE_EXPANDED_ANSWER_KEY, set())
    expanded_answers.discard(current_idx)
    st.session_state[PRACTICE_EXPANDED_ANSWER_KEY] = expanded_answers
    timed_out_questions = st.session_state.get(PRACTICE_TIMED_OUT_QUESTIONS_KEY, set())
    timed_out_questions.discard(current_idx)
    st.session_state[PRACTICE_TIMED_OUT_QUESTIONS_KEY] = timed_out_questions
    skipped_questions = st.session_state.get(PRACTICE_SKIPPED_QUESTIONS_KEY, set())
    skipped_questions.discard(current_idx)
    st.session_state[PRACTICE_SKIPPED_QUESTIONS_KEY] = skipped_questions
    st.session_state.pop(f"q_radio_{current_idx}", None)
    st.session_state.pop(f"q_open_ended_{current_idx}", None)
    st.session_state.pop(f"q_self_grade_{current_idx}", None)

    flagged = _st("flagged") or set()
    flagged.discard(current_idx)
    _set("flagged", flagged)
    _start_practice_question_clock()
    return True


def _practice_question_time_limit() -> int:
    return _valid_int(
        st.session_state.get(PRACTICE_TIMER_SECONDS_KEY),
        PRACTICE_DEFAULT_TIMER_SECONDS,
        15,
        600,
    )


def _practice_timer_remaining() -> float:
    if not st.session_state.get(PRACTICE_TIMER_ENABLED_KEY):
        return 0.0
    seconds = _practice_question_time_limit()
    remaining = float(st.session_state.get(PRACTICE_TIMER_REMAINING_KEY, seconds))
    if st.session_state.get(PRACTICE_TIMER_PAUSED_KEY):
        return max(0.0, min(float(seconds), remaining))
    started_at = float(st.session_state.get(PRACTICE_TIMER_LAST_STARTED_KEY) or time.time())
    return max(0.0, min(float(seconds), remaining - (time.time() - started_at)))


def _sync_practice_timer_to_exam_state() -> None:
    seconds = _practice_question_time_limit()
    remaining = _practice_timer_remaining()
    now = time.time()
    _set("time_limit", seconds)
    _set("section_started", now - (seconds - remaining))
    _set("q_start_time", now - (seconds - remaining))
    _set("timer_paused", bool(st.session_state.get(PRACTICE_TIMER_PAUSED_KEY)))
    _set("timer_paused_at", now if st.session_state.get(PRACTICE_TIMER_PAUSED_KEY) else None)
    _set("timer_visible", bool(st.session_state.get(PRACTICE_TIMER_VISIBLE_KEY, True)))


def _pause_practice_timer() -> None:
    if not st.session_state.get(PRACTICE_TIMER_ENABLED_KEY):
        return
    st.session_state[PRACTICE_TIMER_REMAINING_KEY] = _practice_timer_remaining()
    st.session_state[PRACTICE_TIMER_PAUSED_KEY] = True
    _sync_practice_timer_to_exam_state()
    persist_current_exam(user_id)


def _resume_practice_timer() -> None:
    if not st.session_state.get(PRACTICE_TIMER_ENABLED_KEY):
        return
    st.session_state[PRACTICE_TIMER_REMAINING_KEY] = _practice_timer_remaining()
    st.session_state[PRACTICE_TIMER_LAST_STARTED_KEY] = time.time()
    st.session_state[PRACTICE_TIMER_PAUSED_KEY] = False
    _sync_practice_timer_to_exam_state()
    persist_current_exam(user_id)


def _render_practice_timer(seconds: float, total_seconds: float, key_prefix: str) -> None:
    visible = bool(st.session_state.get(PRACTICE_TIMER_VISIBLE_KEY, True))
    paused = bool(st.session_state.get(PRACTICE_TIMER_PAUSED_KEY))
    pct = max(0.0, min(1.0, seconds / total_seconds)) if total_seconds else 0
    m, s = divmod(int(seconds), 60)

    if visible:
        suffix = "paused" if paused else "remaining"
        st.markdown(
            f'<div class="sf-timer-card"><div class="sf-timer-label">{m:02d}:{s:02d} {suffix}</div></div>',
            unsafe_allow_html=True,
        )
        st.progress(pct)
    else:
        st.caption("Timer hidden. You can turn it back on from any question.")

    show_col, pause_col = st.columns(2)
    with show_col:
        show_label = "Hide" if visible else "Show"
        if st.button(show_label, key=f"{key_prefix}_show", use_container_width=True):
            st.session_state[PRACTICE_TIMER_VISIBLE_KEY] = not visible
            _sync_practice_timer_to_exam_state()
            st.rerun()
    with pause_col:
        pause_label = "Resume" if paused else "Pause"
        if st.button(pause_label, key=f"{key_prefix}_pause", use_container_width=True):
            if paused:
                _resume_practice_timer()
            else:
                _pause_practice_timer()
            st.rerun()


def _start_practice_question_clock() -> None:
    if st.session_state.get(PRACTICE_TIMER_ENABLED_KEY):
        seconds = _practice_question_time_limit()
        st.session_state[PRACTICE_TIMER_REMAINING_KEY] = float(seconds)
        st.session_state[PRACTICE_TIMER_LAST_STARTED_KEY] = time.time()
        st.session_state[PRACTICE_TIMER_PAUSED_KEY] = False
        st.session_state[PRACTICE_TIMER_VISIBLE_KEY] = True
        st.session_state[PRACTICE_TIMER_CURRENT_IDX_KEY] = _st("current_idx") or 0
        _sync_practice_timer_to_exam_state()


def _apply_active_question_timer_settings(
    enabled: bool,
    seconds: int,
    save_as_default: bool,
) -> None:
    seconds = _valid_int(seconds, PRACTICE_DEFAULT_TIMER_SECONDS, 15, 600)
    st.session_state[PRACTICE_TIMER_ENABLED_KEY] = bool(enabled)
    st.session_state[PRACTICE_TIMER_SECONDS_KEY] = int(seconds) if enabled else 0
    st.session_state[PRACTICE_SETUP_TIMER_SECONDS_KEY] = int(seconds)
    st.session_state[PRACTICE_TIMER_VISIBLE_KEY] = bool(enabled)
    if enabled:
        _start_practice_question_clock()
    else:
        _set("time_limit", 0)
        _set("timer_visible", False)
        _set("timer_paused", False)
        _set("timer_paused_at", None)
    if save_as_default:
        set_setting(user_id, "question_time_seconds", str(int(seconds)))
    persist_current_exam(user_id)


def _go_to_practice_question(idx: int) -> None:
    questions = _st("questions") or []
    if not questions:
        return
    st.session_state[_K["current_idx"]] = max(0, min(idx, len(questions) - 1))
    _start_practice_question_clock()


def _mark_practice_question_reached(idx: int) -> None:
    questions = _st("questions") or []
    if not questions or not (0 <= idx < len(questions)):
        return
    reached = st.session_state.get(PRACTICE_REACHED_QUESTIONS_KEY, set())
    if not isinstance(reached, set):
        reached = set(reached or [])
    reached.add(idx)
    st.session_state[PRACTICE_REACHED_QUESTIONS_KEY] = reached


def _practice_reached_indices(current_idx: int) -> set[int]:
    questions = _st("questions") or []
    answers = _st("answers") or {}
    reached = st.session_state.get(PRACTICE_REACHED_QUESTIONS_KEY, set())
    if not isinstance(reached, set):
        reached = set(reached or [])
    for idx in answers.keys():
        if isinstance(idx, int) or str(idx).isdigit():
            reached.add(int(idx))
    if questions:
        reached.add(max(0, min(current_idx, len(questions) - 1)))
    return {idx for idx in reached if 0 <= idx < len(questions)}


def _timed_out_answer_for_current_question(current_idx: int, q: dict) -> str:
    if is_open_ended_question(q):
        draft = str(st.session_state.get(f"q_open_ended_{current_idx}", "")).strip()
        return draft or "Timed out before submission"
    return PRACTICE_TIMEOUT_ANSWER


def _skipped_answer_for_current_question(current_idx: int, q: dict) -> str:
    if is_open_ended_question(q):
        return str(st.session_state.get(f"q_open_ended_{current_idx}", "")).strip()
    return PRACTICE_SKIPPED_ANSWER


def _open_answer_review_for_question(current_idx: int) -> None:
    expanded_answers = st.session_state.get(PRACTICE_EXPANDED_ANSWER_KEY, set())
    expanded_answers.add(current_idx)
    st.session_state[PRACTICE_EXPANDED_ANSWER_KEY] = expanded_answers


def _reset_practice_question_for_redo(idx: int) -> bool:
    questions = _st("questions") or []
    if not questions or not (0 <= idx < len(questions)):
        return False

    answers = _st("answers") or {}
    _dict_pop_idx(answers, idx)
    _set("answers", answers)

    self_grades = _st("self_grades") or {}
    _dict_pop_idx(self_grades, idx)
    _set("self_grades", self_grades)

    expanded_answers = st.session_state.get(PRACTICE_EXPANDED_ANSWER_KEY, set())
    expanded_answers.discard(idx)
    st.session_state[PRACTICE_EXPANDED_ANSWER_KEY] = expanded_answers

    timed_out_questions = st.session_state.get(PRACTICE_TIMED_OUT_QUESTIONS_KEY, set())
    timed_out_questions.discard(idx)
    st.session_state[PRACTICE_TIMED_OUT_QUESTIONS_KEY] = timed_out_questions

    skipped_questions = st.session_state.get(PRACTICE_SKIPPED_QUESTIONS_KEY, set())
    skipped_questions.discard(idx)
    st.session_state[PRACTICE_SKIPPED_QUESTIONS_KEY] = skipped_questions

    st.session_state.pop(PRACTICE_TIMEOUT_NOTICE_KEY, None)
    st.session_state.pop(PRACTICE_SKIPPED_NOTICE_KEY, None)
    st.session_state.pop(f"q_radio_{idx}", None)
    st.session_state.pop(f"q_open_ended_{idx}", None)
    st.session_state.pop(f"q_self_grade_{idx}", None)

    _set("current_idx", idx)
    if not st.session_state.get(PRACTICE_TIMER_ENABLED_KEY) and (_st("time_limit") or 0) > 0:
        st.session_state[PRACTICE_TIMER_ENABLED_KEY] = True
        st.session_state[PRACTICE_TIMER_SECONDS_KEY] = int(_st("time_limit") or PRACTICE_DEFAULT_TIMER_SECONDS)
    _start_practice_question_clock()
    persist_current_exam(user_id)
    return True


def _pending_practice_answer(current_idx: int, q: dict, rendered_answer: str | None) -> str:
    if is_open_ended_question(q):
        return str(
            rendered_answer
            if rendered_answer is not None
            else st.session_state.get(f"q_open_ended_{current_idx}", "")
        ).strip()

    if rendered_answer:
        return rendered_answer

    widget_value = st.session_state.get(f"q_radio_{current_idx}")
    match = re.match(r"\*\*([A-E])\.\*\*", str(widget_value or ""))
    return match.group(1) if match else ""


def _mark_current_question_timed_out(current_idx: int, q: dict) -> None:
    record_answer(current_idx, _timed_out_answer_for_current_question(current_idx, q))
    if is_open_ended_question(q):
        record_self_grade(current_idx, False)
    timed_out_questions = st.session_state.get(PRACTICE_TIMED_OUT_QUESTIONS_KEY, set())
    timed_out_questions.add(current_idx)
    st.session_state[PRACTICE_TIMED_OUT_QUESTIONS_KEY] = timed_out_questions
    _open_answer_review_for_question(current_idx)
    _pause_practice_timer()
    st.session_state[PRACTICE_TIMEOUT_NOTICE_KEY] = current_idx


def _skip_current_question() -> None:
    q = current_question()
    current_idx = _st("current_idx") or 0
    if q is None:
        return
    record_answer(current_idx, _skipped_answer_for_current_question(current_idx, q))
    if is_open_ended_question(q):
        record_self_grade(current_idx, False)
    skipped_questions = st.session_state.get(PRACTICE_SKIPPED_QUESTIONS_KEY, set())
    skipped_questions.add(current_idx)
    st.session_state[PRACTICE_SKIPPED_QUESTIONS_KEY] = skipped_questions
    _open_answer_review_for_question(current_idx)
    _pause_practice_timer()
    st.session_state[PRACTICE_SKIPPED_NOTICE_KEY] = current_idx

def _render_pdf_download(label: str = "Download Practice PDF") -> None:
    pdf_bytes = st.session_state.get(PRACTICE_PDF_KEY)
    if not pdf_bytes:
        return
    st.download_button(
        label,
        data=pdf_bytes,
        file_name=st.session_state.get(PRACTICE_PDF_NAME_KEY, "practice_session.pdf"),
        mime="application/pdf",
        use_container_width=True,
    )


st.set_page_config(page_title="Practice Mode · StudyForge", page_icon="✏️", layout="wide")

def _clamp_practice_max_difficulty() -> None:
    diff_min = int(st.session_state.get(PRACTICE_MIN_DIFFICULTY_KEY, 1))
    st.session_state[PRACTICE_MAX_DIFFICULTY_KEY] = diff_min


def _keep_practice_max_at_or_above_min() -> None:
    diff_min = int(st.session_state.get(PRACTICE_MIN_DIFFICULTY_KEY, 1))
    diff_max = int(st.session_state.get(PRACTICE_MAX_DIFFICULTY_KEY, 5))
    if diff_max < diff_min:
        st.session_state[PRACTICE_MAX_DIFFICULTY_KEY] = diff_min


def _install_difficulty_slider_helpers() -> None:
    labels_json = json.dumps(DIFFICULTY_LABELS)
    components.html(
        f"""
<script>
(function () {{
    const P = window.parent;
    if (!P || !P.document) return;
    const doc = P.document;
    const labels = {labels_json};
    const fadeDelay = 3600;
    const styleId = "sf-difficulty-slider-style";

    if (!doc.getElementById(styleId)) {{
        const style = doc.createElement("style");
        style.id = styleId;
        style.textContent = `
            [data-testid="stSlider"].sf-difficulty-slider {{
                position: relative;
            }}
            .sf-difficulty-bubble {{
                position: absolute;
                z-index: 50;
                transform: translate(-50%, -100%);
                padding: 0.18rem 0.48rem;
                border: 1px solid rgba(29, 78, 216, 0.24);
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.98);
                color: #111827;
                box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16);
                font-size: 0.72rem;
                font-weight: 750;
                line-height: 1.15;
                max-width: min(15rem, 46vw);
                text-align: center;
                white-space: normal;
                pointer-events: none;
                opacity: 0;
                transition: opacity 0.42s ease;
            }}
            .sf-difficulty-bubble.sf-visible {{
                opacity: 1;
            }}
            @media (prefers-color-scheme: dark) {{
                .sf-difficulty-bubble {{
                    background: rgba(17, 24, 39, 0.98);
                    color: #f8fafc;
                    border-color: rgba(255, 255, 255, 0.16);
                }}
            }}
        `;
        doc.head.appendChild(style);
    }}

    function sliderValue(root) {{
        const thumb = root.querySelector('[role="slider"]');
        const value = thumb ? thumb.getAttribute("aria-valuenow") : null;
        return String(value || "").trim();
    }}

    function positionBubble(root, bubble) {{
        const thumb = root.querySelector('[role="slider"]');
        if (!thumb) return;
        const thumbRect = thumb.getBoundingClientRect();
        const rootRect = root.getBoundingClientRect();
        bubble.style.left = `${{thumbRect.left + thumbRect.width / 2 - rootRect.left}}px`;
        bubble.style.top = `${{Math.max(0, thumbRect.top - rootRect.top - 10)}}px`;
    }}

    function showBubble(root) {{
        const value = sliderValue(root);
        const bubble = root.querySelector(".sf-difficulty-bubble");
        if (!bubble || !labels[value]) return;
        bubble.textContent = labels[value];
        positionBubble(root, bubble);
        bubble.classList.add("sf-visible");
        clearTimeout(root._sfDifficultyFadeTimer);
    }}

    function fadeBubble(root) {{
        clearTimeout(root._sfDifficultyFadeTimer);
        root._sfDifficultyFadeTimer = setTimeout(function () {{
            const bubble = root.querySelector(".sf-difficulty-bubble");
            if (bubble) bubble.classList.remove("sf-visible");
        }}, fadeDelay);
    }}

    function install(root) {{
        if (root._sfDifficultyInstalled) return;
        const text = root.textContent || "";
        if (!text.includes("Min Difficulty") && !text.includes("Max Difficulty")) return;

        root._sfDifficultyInstalled = true;
        root.classList.add("sf-difficulty-slider");

        const bubble = doc.createElement("div");
        bubble.className = "sf-difficulty-bubble";
        root.appendChild(bubble);

        const thumb = root.querySelector('[role="slider"]');
        const eventTargets = thumb && thumb !== root ? [root, thumb] : [root];
        eventTargets.forEach(function (eventTarget) {{
            ["pointerdown", "mousedown", "touchstart", "focus", "keydown"].forEach(function (eventName) {{
                eventTarget.addEventListener(eventName, function () {{ showBubble(root); }}, true);
            }});
            ["pointerup", "mouseup", "touchend", "blur", "keyup"].forEach(function (eventName) {{
                eventTarget.addEventListener(eventName, function () {{
                    showBubble(root);
                    fadeBubble(root);
                }}, true);
            }});
        }});

        const observer = new MutationObserver(function () {{
            showBubble(root);
            fadeBubble(root);
        }});
        if (thumb) observer.observe(thumb, {{ attributes: true, attributeFilter: ["aria-valuenow"] }});
    }}

    function installAll() {{
        doc.querySelectorAll('[data-testid="stSlider"]').forEach(install);
    }}

    installAll();
    setTimeout(installAll, 250);
    setTimeout(installAll, 900);
}})();
</script>
""",
        height=0,
        scrolling=False,
    )


user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
real_admin, admin = get_effective_admin(user_id)
restore_exam_draft(user_id, modes={"practice"})

enrolled_courses = get_enrolled_courses(user_id)
if not enrolled_courses:
    st.warning(
        "You are not enrolled in any courses yet. "
        "Choose an active course from the sidebar first."
    )
    st.stop()

course_titles = {c["id"]: c["title"] for c in enrolled_courses}
course_counts = {c["id"]: get_course_question_count(c["id"]) for c in enrolled_courses}
active_course_id = st.session_state.get("active_course_id")
default_course_ids = (
    [active_course_id]
    if active_course_id in course_titles
    else [enrolled_courses[0]["id"]]
)
dashboard_active_course_id = default_course_ids[0]
dashboard_active_course_title = course_titles[dashboard_active_course_id]
_install_practice_dashboard_styles()
_render_practice_dashboard_strip(
    enrolled_course_ids=list(course_titles.keys()),
    active_course_id=dashboard_active_course_id,
    active_course_title=dashboard_active_course_title,
)

page_header("✏️ Practice Mode", "Drill questions at your own pace")

if st.session_state.pop("_exam_restored_notice", False):
    st.success("Your in-progress practice session was restored right where you left off.")

settings  = get_all_settings(user_id)
hard_mode = settings.get("hard_mode", "false") == "true"
show_exp  = settings.get("show_explanations", "always")
last_practice_settings = _read_last_practice_settings(settings)
default_question_time_seconds = _default_question_time_seconds(settings)

if not is_active() and "last_report" in st.session_state:
    report = st.session_state.pop("last_report")
    st.success("Session complete!")
    render_score_card(report, "Practice Session Score")
    _render_pdf_download()
    from src.voice_exam import cleanup_voice_exam_panel
    cleanup_voice_exam_panel()
    st.stop()

# ── Setup form ────────────────────────────────────────────────────────────────
if not is_active():
    st.subheader("Set Up Your Practice Session")

    saved_course_ids = [
        int(cid)
        for cid in _saved_list(
            last_practice_settings,
            "course_ids",
            valid_values={str(cid) for cid in course_titles} | set(course_titles),
        )
    ]
    if saved_course_ids:
        default_course_ids = saved_course_ids
    if "practice_course_ids" not in st.session_state:
        st.session_state["practice_course_ids"] = default_course_ids

    selected_course_ids = st.multiselect(
        "Courses",
        options=list(course_titles.keys()),
        format_func=lambda cid: f"{course_titles[cid]} ({course_counts.get(cid, 0)} Q)",
        help="Type to search, then select one or more courses for this practice session.",
        key="practice_course_ids",
    )

    selected_course_ids = [cid for cid in selected_course_ids if cid in course_titles]
    course_modules = sorted({
        val
        for cid in selected_course_ids
        for val in get_distinct_values("section_type", course_id=cid)
        if val
    }, key=_natural_sort_key)
    course_qtypes = sorted({
        val
        for cid in selected_course_ids
        for val in get_distinct_values("question_type", course_id=cid)
        if val
    })

    module_opts = [MODULE_RANDOM] + course_modules
    qtype_opts = ["All"] + course_qtypes

    saved_difficulty_counts = _saved_difficulty_counts(last_practice_settings)
    for difficulty, saved_count in saved_difficulty_counts.items():
        difficulty_key = _difficulty_count_key(difficulty)
        if difficulty_key not in st.session_state:
            st.session_state[difficulty_key] = saved_count
    saved_difficulty_modes = _saved_difficulty_modes(last_practice_settings)
    for difficulty, saved_mode in saved_difficulty_modes.items():
        difficulty_mode_key = _difficulty_mode_key(difficulty)
        if difficulty_mode_key not in st.session_state:
            st.session_state[difficulty_mode_key] = saved_mode
        elif st.session_state[difficulty_mode_key] not in QUESTION_MODE_OPTIONS:
            st.session_state[difficulty_mode_key] = QUESTION_MODE_MULTIPLE_CHOICE
    if PRACTICE_USE_WEAKNESS_KEY not in st.session_state:
        st.session_state[PRACTICE_USE_WEAKNESS_KEY] = bool(
            last_practice_settings.get("use_weakness", True)
        )
    if PRACTICE_USE_TIMER_KEY not in st.session_state:
        st.session_state[PRACTICE_USE_TIMER_KEY] = bool(
            last_practice_settings.get("use_timer", True)
        )
    if PRACTICE_SETUP_TIMER_SECONDS_KEY not in st.session_state:
        st.session_state[PRACTICE_SETUP_TIMER_SECONDS_KEY] = default_question_time_seconds
    else:
        st.session_state[PRACTICE_SETUP_TIMER_SECONDS_KEY] = default_question_time_seconds
    if PRACTICE_BULK_DIFFICULTY_COUNT_KEY not in st.session_state:
        st.session_state[PRACTICE_BULK_DIFFICULTY_COUNT_KEY] = _valid_int(
            last_practice_settings.get("bulk_difficulty_count"), 0, 0, 100
        )
    if PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY not in st.session_state:
        st.session_state[PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY] = st.session_state[
            PRACTICE_BULK_DIFFICULTY_COUNT_KEY
        ]
    if PRACTICE_QTYPE_KEY not in st.session_state:
        saved_qtype = last_practice_settings.get("question_type", "All")
        st.session_state[PRACTICE_QTYPE_KEY] = saved_qtype if saved_qtype in qtype_opts else "All"
    elif st.session_state[PRACTICE_QTYPE_KEY] not in qtype_opts:
        st.session_state[PRACTICE_QTYPE_KEY] = "All"
    if PRACTICE_QUESTION_ORDER_KEY not in st.session_state:
        saved_order = last_practice_settings.get("question_order", QUESTION_ORDER_RANDOM)
        st.session_state[PRACTICE_QUESTION_ORDER_KEY] = (
            saved_order if saved_order in QUESTION_ORDER_OPTIONS else QUESTION_ORDER_RANDOM
        )
    if PRACTICE_TAKE_HOME_KEY not in st.session_state:
        st.session_state[PRACTICE_TAKE_HOME_KEY] = bool(
            last_practice_settings.get("take_home_exam", False)
        )
    if PRACTICE_MODULES_KEY not in st.session_state:
        st.session_state[PRACTICE_MODULES_KEY] = _saved_list(
            last_practice_settings,
            "modules",
            valid_values=set(module_opts),
        )
    else:
        st.session_state[PRACTICE_MODULES_KEY] = [
            module for module in st.session_state[PRACTICE_MODULES_KEY]
            if module in module_opts
        ]

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            selected_modules = st.multiselect(
                "Module",
                module_opts,
                key=PRACTICE_MODULES_KEY,
                help=(
                    "Choose one or more learning modules. Leave blank to use all modules, "
                    "or choose Random module to let StudyForge pick one module."
                ),
            )
            qtype_filter = st.selectbox(
                "Question Type",
                qtype_opts,
                key=PRACTICE_QTYPE_KEY,
            )
            question_order = st.radio(
                "Question Order",
                QUESTION_ORDER_OPTIONS,
                key=PRACTICE_QUESTION_ORDER_KEY,
                horizontal=True,
            )
        with col2:
            st.markdown("##### Questions by Difficulty")
            st.number_input(
                "Set all difficulties to",
                min_value=0,
                max_value=100,
                key=PRACTICE_BULK_DIFFICULTY_COUNT_KEY,
                on_change=_apply_bulk_difficulty_count,
            )
            current_bulk_count = _valid_int(
                st.session_state.get(PRACTICE_BULK_DIFFICULTY_COUNT_KEY),
                0,
                0,
                100,
            )
            if current_bulk_count != st.session_state.get(
                PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY
            ):
                for difficulty in range(1, 6):
                    st.session_state[_difficulty_count_key(difficulty)] = current_bulk_count
                st.session_state[
                    PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY
                ] = current_bulk_count
            difficulty_counts = {}
            for difficulty in range(1, 6):
                difficulty_counts[difficulty] = st.number_input(
                    f"{difficulty} - {DIFFICULTY_LABELS.get(difficulty, difficulty)}",
                    min_value=0,
                    max_value=100,
                    key=_difficulty_count_key(difficulty),
                )
            n_questions = sum(int(count) for count in difficulty_counts.values())
            st.caption(f"Total selected: {n_questions} questions")

        use_weakness = st.checkbox(
            "Smart Review Queue - prioritize due weak areas",
            key=PRACTICE_USE_WEAKNESS_KEY,
            help=(
                "Missed questions return sooner. Repeated correct answers push "
                "questions farther out, and mastered items appear less often."
            ),
        )
        with st.expander("Advanced"):
            st.markdown("##### Question Mode by Difficulty")
            st.caption(
                "Use open-ended challenge to hide answer choices for selected "
                "difficulty levels while keeping other levels multiple choice."
            )
            difficulty_modes = {}
            mode_cols = st.columns(5)
            for difficulty, mode_col in zip(range(1, 6), mode_cols):
                with mode_col:
                    difficulty_modes[difficulty] = st.selectbox(
                        f"Level {difficulty}",
                        QUESTION_MODE_OPTIONS,
                        key=_difficulty_mode_key(difficulty),
                        help=DIFFICULTY_LABELS.get(difficulty, ""),
                    )
        take_home_exam = st.checkbox(
            "Create take-home exam PDF and email it to me",
            key=PRACTICE_TAKE_HOME_KEY,
            help=(
                "Generate the same practice set as a PDF, send it to your email on file, "
                "and keep a download button available here."
            ),
        )
        use_timer = st.checkbox(
            "Enable per-question timer (optional)",
            key=PRACTICE_USE_TIMER_KEY,
        )
        timer_secs = (
            st.number_input(
                "Seconds per question",
                15,
                600,
                key=PRACTICE_SETUP_TIMER_SECONDS_KEY,
                step=5,
            )
            if use_timer else None
        )
        start_label = "Create Take-Home Exam" if take_home_exam else "Start Practice"
        submitted = st.button(start_label, use_container_width=True)

    if submitted:
        if not selected_course_ids:
            st.error("Select at least one course for practice.")
            st.stop()
        if n_questions <= 0:
            st.error("Choose at least one question across the difficulty levels.")
            st.stop()

        requested_difficulty_counts = {
            difficulty: int(count)
            for difficulty, count in difficulty_counts.items()
            if int(count) > 0
        }
        diff_min = min(requested_difficulty_counts)
        diff_max = max(requested_difficulty_counts)

        set_setting(user_id, PRACTICE_LAST_SETTINGS_KEY, json.dumps({
            "course_ids": selected_course_ids,
            "modules": selected_modules,
            "question_type": qtype_filter,
            "min_difficulty": int(diff_min),
            "max_difficulty": int(diff_max),
            "n_questions": int(n_questions),
            "bulk_difficulty_count": int(st.session_state.get(PRACTICE_BULK_DIFFICULTY_COUNT_KEY, 0)),
            "difficulty_counts": {
                str(difficulty): int(count)
                for difficulty, count in difficulty_counts.items()
            },
            "difficulty_modes": {
                str(difficulty): mode
                for difficulty, mode in difficulty_modes.items()
            },
            "use_weakness": bool(use_weakness),
            "open_ended_mode": all(
                mode == QUESTION_MODE_OPEN_ENDED
                for mode in difficulty_modes.values()
            ),
            "take_home_exam": bool(take_home_exam),
            "use_timer": bool(use_timer),
            "question_order": question_order,
            "timer_seconds": int(timer_secs or st.session_state.get(PRACTICE_SETUP_TIMER_SECONDS_KEY, 120)),
        }))

        random_module = MODULE_RANDOM in selected_modules
        selected_module_filters = [
            module for module in selected_modules
            if module != MODULE_RANDOM
        ]
        modules_to_try = (
            course_modules
            if random_module
            else (selected_module_filters or [None])
        )

        if random_module and not modules_to_try:
            st.error("No modules are available for the selected course(s).")
            st.stop()

        if random_module:
            random.shuffle(modules_to_try)

        selected_module = None
        pool_by_difficulty = {difficulty: [] for difficulty in requested_difficulty_counts}
        for module_name in modules_to_try:
            candidate_by_difficulty = {difficulty: [] for difficulty in requested_difficulty_counts}
            for difficulty in requested_difficulty_counts:
                for cid in selected_course_ids:
                    candidate_by_difficulty[difficulty].extend(get_all_questions(
                        section_type=module_name,
                        question_type=None if qtype_filter == "All" else qtype_filter,
                        min_difficulty=difficulty,
                        max_difficulty=difficulty,
                        course_id=cid,
                    ))

            if any(candidate_by_difficulty.values()):
                for difficulty, candidates in candidate_by_difficulty.items():
                    pool_by_difficulty[difficulty].extend(candidates)
                selected_module = module_name
                if random_module:
                    break

        pool = [
            question
            for candidates in pool_by_difficulty.values()
            for question in candidates
        ]
        if not pool:
            selected_names = ", ".join(course_titles[cid] for cid in selected_course_ids)
            module_msg = (
                "any module"
                if not selected_module_filters and not random_module
                else ("a random module" if random_module else ", ".join(selected_module_filters))
            )
            st.error(
                f"No questions match those filters in **{selected_names}** for **{module_msg}**. "
                "Upload more questions or adjust your filters."
            )
            st.stop()

        attempt_course_id = selected_course_ids[0] if len(selected_course_ids) == 1 else None
        questions = []
        replacement_pool = []
        shortage_messages = []
        for difficulty, requested_count in requested_difficulty_counts.items():
            difficulty_pool = pool_by_difficulty[difficulty]
            if len(difficulty_pool) < requested_count:
                shortage_messages.append(
                    f"Only {len(difficulty_pool)} level {difficulty} questions match; using all available."
                )

            if use_weakness:
                selected_questions = get_smart_review_questions(
                    user_id,
                    difficulty_pool,
                    n=min(requested_count, len(difficulty_pool)),
                    course_id=attempt_course_id,
                )
                replacement_pool.extend(get_smart_review_questions(
                    user_id,
                    difficulty_pool,
                    n=len(difficulty_pool),
                    course_id=attempt_course_id,
                ))
            else:
                selected_questions = random.sample(
                    difficulty_pool,
                    min(requested_count, len(difficulty_pool)),
                )
                replacement_pool.extend(difficulty_pool)
            questions.extend(selected_questions)

        if question_order == QUESTION_ORDER_RANDOM:
            random.shuffle(questions)

        questions = _apply_difficulty_question_modes(questions, difficulty_modes)
        replacement_pool = _apply_difficulty_question_modes(
            replacement_pool,
            difficulty_modes,
        )

        question_time_limit = _valid_int(
            timer_secs,
            PRACTICE_DEFAULT_TIMER_SECONDS,
            15,
            600,
        ) if use_timer else 0
        clear_quiz()
        st.session_state[PRACTICE_POOL_KEY] = replacement_pool
        st.session_state[PRACTICE_TIMER_ENABLED_KEY] = bool(question_time_limit)
        st.session_state[PRACTICE_TIMER_SECONDS_KEY] = question_time_limit
        st.session_state[PRACTICE_TIMER_REMAINING_KEY] = float(question_time_limit)
        st.session_state[PRACTICE_TIMER_LAST_STARTED_KEY] = time.time()
        st.session_state[PRACTICE_TIMER_PAUSED_KEY] = False
        st.session_state[PRACTICE_TIMER_VISIBLE_KEY] = bool(question_time_limit)
        st.session_state[PRACTICE_TIMED_OUT_QUESTIONS_KEY] = set()
        st.session_state[PRACTICE_SKIPPED_QUESTIONS_KEY] = set()
        st.session_state[PRACTICE_EXPANDED_ANSWER_KEY] = set()
        st.session_state[PRACTICE_REACHED_QUESTIONS_KEY] = {0}
        st.session_state.pop(PRACTICE_TIMEOUT_NOTICE_KEY, None)
        st.session_state.pop(PRACTICE_SKIPPED_NOTICE_KEY, None)
        section_label = (
            selected_module
            if random_module
            else (", ".join(selected_module_filters) if selected_module_filters else "All Modules")
        )
        practice_label = f"Practice Session: {section_label}"
        st.session_state[PRACTICE_PDF_KEY] = generate_exam_pdf(
            questions=questions,
            title=practice_label,
            subtitle="Generated practice test",
            distribution=[
                {
                    "course": course_titles[cid],
                    "q_count": sum(1 for q in questions if q.get("course_id") == cid),
                }
                for cid in selected_course_ids
            ],
            include_answer_key=not take_home_exam,
        )
        st.session_state[PRACTICE_PDF_NAME_KEY] = make_pdf_filename(practice_label)
        if take_home_exam:
            course_name = (
                course_titles[selected_course_ids[0]]
                if len(selected_course_ids) == 1
                else "Multiple Courses"
            )
            result = send_take_home_exam_pdf(
                user_id,
                course_name=course_name,
                module_name=section_label,
                exam_label=practice_label,
                pdf_bytes=st.session_state[PRACTICE_PDF_KEY],
                pdf_filename=st.session_state[PRACTICE_PDF_NAME_KEY],
                question_count=len(questions),
            )
            if result.sent:
                st.success(result.message)
            else:
                st.warning(result.message)
            if selected_module:
                st.info(f"Generated module: {selected_module}")
            for shortage in shortage_messages:
                st.info(shortage)
            _render_pdf_download("Download Take-Home Exam PDF")
            from src.voice_exam import cleanup_voice_exam_panel
            cleanup_voice_exam_panel()
            st.stop()
        start_quiz(
            user_id=user_id,
            mode="practice",
            questions=questions,
            section_type=section_label,
            hard_mode=hard_mode,
            time_limit_seconds=question_time_limit,
            course_id=attempt_course_id,
            open_ended_mode=False,
        )
        notices = []
        if selected_module:
            notices.append(f"Practicing module: {selected_module}")
        notices.extend(shortage_messages)
        if notices:
            st.session_state[PRACTICE_NOTICE_KEY] = " ".join(notices)
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
timed_out_questions = st.session_state.get(PRACTICE_TIMED_OUT_QUESTIONS_KEY, set())
skipped_questions = st.session_state.get(PRACTICE_SKIPPED_QUESTIONS_KEY, set())
session_time_limit = _st("time_limit") or 0
timer_enabled = (
    bool(st.session_state.get(PRACTICE_TIMER_ENABLED_KEY))
    if PRACTICE_TIMER_ENABLED_KEY in st.session_state
    else (0 < session_time_limit < 99999)
)
question_time_limit = _practice_question_time_limit() if timer_enabled else 0

total    = len(questions)
answered = len({
    int(idx) if isinstance(idx, int) or str(idx).isdigit() else idx
    for idx in answers_dict.keys()
})
q        = current_question()
_mark_practice_question_reached(current_idx)
current_answered = _dict_has_idx(answers_dict, current_idx)

if q is None:
    st.error("Session error: no questions loaded.")
    clear_quiz()
    st.rerun()

if timer_enabled:
    st.session_state[PRACTICE_TIMER_SECONDS_KEY] = question_time_limit
    _set("time_limit", question_time_limit)
    if (
        not current_answered
        and (
            PRACTICE_TIMER_REMAINING_KEY not in st.session_state
            or PRACTICE_TIMER_LAST_STARTED_KEY not in st.session_state
            or _st("q_start_time") is None
            or session_time_limit != question_time_limit
            or st.session_state.get(PRACTICE_TIMER_CURRENT_IDX_KEY) != current_idx
            or bool(_st("timer_paused")) != bool(st.session_state.get(PRACTICE_TIMER_PAUSED_KEY, False))
        )
    ):
        _start_practice_question_clock()

if timer_enabled and not current_answered:
    remaining = _practice_timer_remaining()
    _sync_practice_timer_to_exam_state()
    if (
        question_time_limit
        and not st.session_state.get(PRACTICE_TIMER_PAUSED_KEY)
        and remaining <= 0
    ):
        _mark_current_question_timed_out(current_idx, q)
        st.rerun()

notice = st.session_state.pop(PRACTICE_NOTICE_KEY, None)
if notice:
    st.info(notice)

# ── Voice Exam Mode ───────────────────────────────────────────────────────────
from src.voice_exam import render_voice_exam_panel
render_voice_exam_panel(q, current_idx, total)

if timer_enabled and not current_answered:
    st_autorefresh(interval=1_000, key="practice_timer_refresh")
    remaining = _practice_timer_remaining()
    _render_practice_timer(remaining, question_time_limit, key_prefix="practice_timer")
elif timer_enabled:
    remaining = _practice_timer_remaining()
    _render_practice_timer(remaining, question_time_limit, key_prefix="practice_timer")

with st.expander("Timer Settings"):
    with st.form("active_practice_timer_settings"):
        active_timer_enabled = st.toggle(
            "Enable per-question timer",
            value=bool(timer_enabled),
        )
        active_timer_seconds = st.number_input(
            "Seconds per question",
            min_value=15,
            max_value=600,
            value=int(question_time_limit or default_question_time_seconds),
            step=5,
            disabled=not active_timer_enabled,
        )
        save_default_timer = st.checkbox(
            "Make this my default per-question timer",
            value=False,
        )
        save_timer_settings = st.form_submit_button(
            "Apply Timer Settings",
            use_container_width=True,
        )
    if save_timer_settings:
        _apply_active_question_timer_settings(
            active_timer_enabled,
            active_timer_seconds,
            save_default_timer,
        )
        st.success("Timer settings updated for this practice session.")
        st.rerun()

st.progress(answered / total if total else 0,
            text=f"Progress: {answered}/{total} answered")

nav_left, nav_mid, nav_right = st.columns([1, 6, 1])
with nav_left:
    if st.button("◀ Prev", disabled=(current_idx == 0)):
        prev_question(); _start_practice_question_clock(); st.rerun()
with nav_right:
    if st.button("Next ▶", disabled=(current_idx == total - 1)):
        next_question(); _start_practice_question_clock(); st.rerun()
with nav_mid:
    jump = st.selectbox(
        "Jump to question:", options=list(range(1, total + 1)),
        index=current_idx, label_visibility="collapsed",
    )
    if jump - 1 != current_idx:
        _go_to_practice_question(jump - 1); st.rerun()
st.divider()

selected      = _dict_get_idx(answers_dict, current_idx, "")
is_flagged    = current_idx in flagged_set
already_ans   = _dict_has_idx(answers_dict, current_idx)
show_answer   = instant_fb and already_ans
expanded_answers = st.session_state.get(PRACTICE_EXPANDED_ANSWER_KEY, set())
auto_expand_answer = show_answer and current_idx in expanded_answers
timed_out_notice_idx = st.session_state.pop(PRACTICE_TIMEOUT_NOTICE_KEY, None)
skipped_notice_idx = st.session_state.pop(PRACTICE_SKIPPED_NOTICE_KEY, None)
timed_out_current = current_idx in timed_out_questions
skipped_current = current_idx in skipped_questions

if admin and already_ans:
    with st.expander("Admin correction", expanded=timed_out_current or skipped_current):
        st.caption(
            "Use this when a timer or app glitch marked the question before the student "
            "had a fair attempt."
        )
        if st.button("Redo this question: clear answer and reset timer", use_container_width=True):
            if not real_admin:
                st.error("Permission denied. Real admin access required.")
            elif _reset_practice_question_for_redo(current_idx):
                st.session_state[PRACTICE_NOTICE_KEY] = (
                    f"Question {current_idx + 1} was reset. It will count like a fresh attempt."
                )
                st.rerun()
            else:
                st.warning("This question could not be reset.")

picked = render_question(
    q=q, idx=current_idx, total=total,
    selected=selected, show_answer=show_answer, is_flagged=is_flagged,
    auto_expand_answer=auto_expand_answer,
)
persist_current_exam(user_id)

if timed_out_notice_idx == current_idx or selected == PRACTICE_TIMEOUT_ANSWER or timed_out_current:
    st.error("Time expired before you submitted. This question was marked wrong.")
if skipped_notice_idx == current_idx or selected == PRACTICE_SKIPPED_ANSWER or skipped_current:
    st.error("Question skipped. This question was marked wrong.")

open_ended = is_open_ended_question(q)
self_grades = _st("self_grades") or {}
if open_ended and already_ans:
    self_grades = _st("self_grades") or {}
    if timed_out_current or skipped_current:
        record_self_grade(current_idx, False)
        self_grades = _st("self_grades") or {}
    else:
        has_existing_grade = _dict_has_idx(self_grades, current_idx)
        existing_grade = _dict_get_idx(self_grades, current_idx)
        self_grade_choice = st.radio(
            "Self-grade this written response:",
            options=["Correct", "Incorrect"],
            index=(0 if existing_grade else 1) if has_existing_grade else None,
            horizontal=True,
            key=f"q_self_grade_{current_idx}",
        )
        if self_grade_choice is not None:
            record_self_grade(current_idx, self_grade_choice == "Correct")
            self_grades = _st("self_grades") or {}
        else:
            st.info("Mark this written response correct or incorrect before scoring the session.")

if not already_ans:
    if st.button("✔ Submit Answer", type="primary", use_container_width=True):
        submitted_answer = _pending_practice_answer(current_idx, q, picked)
        if not submitted_answer and not open_ended:
            _skip_current_question()
            st.rerun()
        else:
            record_answer(current_idx, submitted_answer)
            _pause_practice_timer()
            _open_answer_review_for_question(current_idx)
            st.rerun()
else:
    if current_idx < total - 1:
        if st.button("Next Question →", type="primary", use_container_width=True):
            next_question(); _start_practice_question_clock(); st.rerun()

_render_pdf_download()

action_skip, action_swap = st.columns(2)
with action_skip:
    if st.button("Skip Question", use_container_width=True):
        _skip_current_question()
        st.rerun()
with action_swap:
    if st.button("Switch Out Question", use_container_width=True):
        if _swap_current_question():
            st.session_state[PRACTICE_NOTICE_KEY] = (
                "Question switched out. This slot now has a fresh unanswered question."
            )
            st.rerun()
        else:
            st.warning("No unused replacement questions are available for this session.")

st.divider()

col_end, col_quit = st.columns(2)
with col_end:
    if st.button("Finish and Score Reached Questions", use_container_width=True):
        reached_indices = _practice_reached_indices(current_idx)
        ungraded_open_ended = [
            i for i, question in enumerate(questions)
            if i in reached_indices
            and is_open_ended_question(question)
            and str(answers_dict.get(i, "")).strip()
            and i not in self_grades
        ]
        if ungraded_open_ended:
            st.session_state[_K["current_idx"]] = ungraded_open_ended[0]
            st.warning("Please self-grade each submitted written response before scoring.")
            st.rerun()
        else:
            st.session_state[PRACTICE_CONFIRM_FINISH_KEY] = True
            st.rerun()
with col_quit:
    if st.button("✖ Quit Without Saving", use_container_width=True):
        st.session_state.pop(PRACTICE_PDF_KEY, None)
        st.session_state.pop(PRACTICE_PDF_NAME_KEY, None)
        st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
        clear_quiz(); st.rerun()

if st.session_state.get(PRACTICE_CONFIRM_FINISH_KEY):
    reached_indices = _practice_reached_indices(current_idx)
    reached_count = len(reached_indices)
    excluded_count = max(0, total - reached_count)
    st.warning("Finish this practice session and score only the questions you reached?")
    st.caption(
        f"You reached {reached_count} of {total} question(s). "
        f"When you finish, {excluded_count} unreached question(s) will not count "
        "as wrong or appear in Review Mistakes. This session will close immediately."
    )
    st.caption("Skipped questions and submitted blank answers still count as incorrect.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button(
            f"Score {reached_count} and End Session",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
            # Close the active UI before writing results so a simultaneous
            # rerun or second click cannot keep this session open.
            _set("active", False)
            with st.spinner("Scoring and closing this practice session..."):
                report = submit_section(user_id, question_indices=reached_indices)
            st.session_state["last_report"] = report
            clear_quiz(); st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
            st.rerun()

# ── Sidebar question map ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Question Map**")
    render_question_map_legend(scored=True)

    def _practice_map_state(i: int) -> dict[str, object]:
        ans  = _dict_get_idx(answers_dict, i, "")
        flag = i in flagged_set
        if i in skipped_questions or i in timed_out_questions:
            icon = "ðŸ”´"
        elif _dict_has_idx(answers_dict, i):
            if is_open_ended_question(questions[i]):
                if _dict_has_idx(self_grades, i):
                    icon = "🟢" if _dict_get_idx(self_grades, i) else "🔴"
                else:
                    icon = "⬜"
            else:
                correct_a = (questions[i].get("correct_answer") or "").upper()
                icon = "🟢" if ans.upper() == correct_a else "🔴"
        else:
            icon = "⬜"
        if flag:
            icon = "🚩"
        if i in skipped_questions or i in timed_out_questions:
            status = "wrong"
        elif _dict_has_idx(answers_dict, i):
            if is_open_ended_question(questions[i]):
                if _dict_has_idx(self_grades, i):
                    status = "correct" if _dict_get_idx(self_grades, i) else "wrong"
                else:
                    status = "unanswered"
            else:
                correct_a = (questions[i].get("correct_answer") or "").upper()
                status = "correct" if ans.upper() == correct_a else "wrong"
        else:
            status = "unanswered"
        return {
            "status": status,
            "flagged": flag,
            "help": f"Go to question {i + 1}",
        }
        if cols[i % 5].button(icon, key=f"map_{i}"):
            _go_to_practice_question(i); st.rerun()

    selected_map_idx = render_question_map(
        total=total,
        current_idx=current_idx,
        state_for_index=_practice_map_state,
        key_prefix="map",
    )
    if selected_map_idx is not None:
        _go_to_practice_question(selected_map_idx); st.rerun()

# ── Score report ──────────────────────────────────────────────────────────────
if not is_active() and "last_report" in st.session_state:
    report = st.session_state.pop("last_report")
    st.success("Session complete!")
    render_score_card(report, "Practice Session Score")
    _render_pdf_download()
