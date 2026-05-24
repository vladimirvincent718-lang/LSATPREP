"""
pages/5_Practice_Mode.py — Untimed practice drill, filtered by active course.
"""

import sys, os
import json
import re
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import random

from src.auth         import require_login
from src.utils        import (page_header, sidebar_nav,
                               render_question, render_score_card, render_timer, DIFFICULTY_LABELS)
from src.database     import (
    get_all_questions, get_all_settings, get_distinct_values,
    get_enrolled_courses, get_course_question_count, set_setting,
)
from src.exam_engine  import (
    start_quiz, clear_quiz, is_active, current_question, next_question,
    prev_question, record_answer, record_self_grade, pause_timer, resume_timer,
    time_on_current_question, submit_section, persist_current_exam,
    restore_exam_draft, _st, _set, _K,
)
from src.analytics    import get_smart_review_questions
from src.question_loader import is_open_ended_question
from src.pdf_export import generate_exam_pdf, make_pdf_filename

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
PRACTICE_N_QUESTIONS_KEY = "practice_n_questions"
PRACTICE_DIFFICULTY_COUNT_PREFIX = "practice_difficulty_count"
PRACTICE_BULK_DIFFICULTY_COUNT_KEY = "practice_bulk_difficulty_count"
PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY = "practice_last_applied_bulk_difficulty_count"
PRACTICE_QTYPE_KEY = "practice_qtype_filter"
PRACTICE_MODULES_KEY = "practice_module_filters"
PRACTICE_QUESTION_ORDER_KEY = "practice_question_order"
PRACTICE_OPEN_ENDED_MODE_KEY = "practice_open_ended_mode"
PRACTICE_TIMEOUT_NOTICE_KEY = "practice_timeout_notice"
PRACTICE_TIMED_OUT_QUESTIONS_KEY = "practice_timed_out_questions"
PRACTICE_TIMEOUT_ANSWER = "__TIMEOUT__"
PRACTICE_SKIPPED_NOTICE_KEY = "practice_skipped_notice"
PRACTICE_SKIPPED_QUESTIONS_KEY = "practice_skipped_questions"
PRACTICE_SKIPPED_ANSWER = "__SKIPPED__"
MODULE_ALL = "All modules (randomized)"
MODULE_RANDOM = "Random module"
PRACTICE_LAST_SETTINGS_KEY = "practice_mode_last_settings"
QUESTION_ORDER_RANDOM = "Randomized"
QUESTION_ORDER_BY_DIFFICULTY = "By difficulty (1 to 5)"
QUESTION_ORDER_OPTIONS = [QUESTION_ORDER_RANDOM, QUESTION_ORDER_BY_DIFFICULTY]


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


def _start_practice_question_clock() -> None:
    if st.session_state.get(PRACTICE_TIMER_ENABLED_KEY):
        resume_timer()
        _set("q_start_time", time.time())


def _go_to_practice_question(idx: int) -> None:
    questions = _st("questions") or []
    if not questions:
        return
    st.session_state[_K["current_idx"]] = max(0, min(idx, len(questions) - 1))
    _start_practice_question_clock()


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


def _mark_current_question_timed_out(current_idx: int, q: dict) -> None:
    record_answer(current_idx, _timed_out_answer_for_current_question(current_idx, q))
    if is_open_ended_question(q):
        record_self_grade(current_idx, False)
    timed_out_questions = st.session_state.get(PRACTICE_TIMED_OUT_QUESTIONS_KEY, set())
    timed_out_questions.add(current_idx)
    st.session_state[PRACTICE_TIMED_OUT_QUESTIONS_KEY] = timed_out_questions
    _open_answer_review_for_question(current_idx)
    pause_timer()
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
    pause_timer()
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

page_header("✏️ Practice Mode", "Drill questions at your own pace")

if st.session_state.pop("_exam_restored_notice", False):
    st.success("Your in-progress practice session was restored right where you left off.")

settings  = get_all_settings(user_id)
hard_mode = settings.get("hard_mode", "false") == "true"
show_exp  = settings.get("show_explanations", "always")
last_practice_settings = _read_last_practice_settings(settings)

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
    if PRACTICE_USE_WEAKNESS_KEY not in st.session_state:
        st.session_state[PRACTICE_USE_WEAKNESS_KEY] = bool(
            last_practice_settings.get("use_weakness", True)
        )
    if PRACTICE_USE_TIMER_KEY not in st.session_state:
        st.session_state[PRACTICE_USE_TIMER_KEY] = bool(
            last_practice_settings.get("use_timer", True)
        )
    if PRACTICE_SETUP_TIMER_SECONDS_KEY not in st.session_state:
        st.session_state[PRACTICE_SETUP_TIMER_SECONDS_KEY] = _valid_int(
            last_practice_settings.get("timer_seconds"), 120, 30, 300
        )
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
    if PRACTICE_OPEN_ENDED_MODE_KEY not in st.session_state:
        st.session_state[PRACTICE_OPEN_ENDED_MODE_KEY] = bool(
            last_practice_settings.get("open_ended_mode", False)
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
        open_ended_mode = st.checkbox(
            "Open-ended challenge - hide answer choices",
            key=PRACTICE_OPEN_ENDED_MODE_KEY,
            help=(
                "Multiple choice is the default. Turn this on when you want to "
                "remove the options and self-grade your written response."
            ),
        )
        use_timer = st.checkbox(
            "⏱ Enable per-question timer (optional)",
            key=PRACTICE_USE_TIMER_KEY,
        )
        timer_secs = (
            st.number_input(
                "Seconds per question",
                30,
                300,
                key=PRACTICE_SETUP_TIMER_SECONDS_KEY,
            )
            if use_timer else None
        )
        submitted = st.button("▶ Start Practice", use_container_width=True)

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
            "use_weakness": bool(use_weakness),
            "open_ended_mode": bool(open_ended_mode),
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

        question_time_limit = int(timer_secs or 0) if use_timer else 0
        clear_quiz()
        st.session_state[PRACTICE_POOL_KEY] = replacement_pool
        st.session_state[PRACTICE_TIMER_ENABLED_KEY] = bool(question_time_limit)
        st.session_state[PRACTICE_TIMER_SECONDS_KEY] = question_time_limit
        st.session_state[PRACTICE_TIMED_OUT_QUESTIONS_KEY] = set()
        st.session_state[PRACTICE_SKIPPED_QUESTIONS_KEY] = set()
        st.session_state[PRACTICE_EXPANDED_ANSWER_KEY] = set()
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
        )
        st.session_state[PRACTICE_PDF_NAME_KEY] = make_pdf_filename(practice_label)
        start_quiz(
            user_id=user_id,
            mode="practice",
            questions=questions,
            section_type=section_label,
            hard_mode=hard_mode,
            time_limit_seconds=question_time_limit,
            course_id=attempt_course_id,
            open_ended_mode=open_ended_mode,
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
question_time_limit = int(
    st.session_state.get(PRACTICE_TIMER_SECONDS_KEY)
    or session_time_limit
    or 0
)
if question_time_limit > 300 and len(questions):
    question_time_limit = max(1, int(question_time_limit / len(questions)))
timer_enabled = bool(st.session_state.get(PRACTICE_TIMER_ENABLED_KEY)) or (
    0 < session_time_limit < 99999
)

total    = len(questions)
answered = len(answers_dict)
q        = current_question()

if q is None:
    st.error("Session error: no questions loaded.")
    clear_quiz()
    st.rerun()

if timer_enabled and current_idx not in answers_dict:
    question_elapsed = time_on_current_question()
    if question_time_limit and question_elapsed >= question_time_limit:
        _mark_current_question_timed_out(current_idx, q)
        st.rerun()

notice = st.session_state.pop(PRACTICE_NOTICE_KEY, None)
if notice:
    st.info(notice)

# ── Voice Exam Mode ───────────────────────────────────────────────────────────
from src.voice_exam import render_voice_exam_panel
render_voice_exam_panel(q, current_idx, total)

if timer_enabled and current_idx not in answers_dict:
    st_autorefresh(interval=1_000, key="practice_timer_refresh")
    remaining = max(0.0, question_time_limit - time_on_current_question())
    render_timer(remaining, question_time_limit, key_prefix="practice_timer")
elif timer_enabled:
    remaining = max(0.0, question_time_limit - time_on_current_question())
    render_timer(remaining, question_time_limit, key_prefix="practice_timer")

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

selected      = answers_dict.get(current_idx, "")
is_flagged    = current_idx in flagged_set
already_ans   = current_idx in answers_dict
show_answer   = instant_fb and already_ans
expanded_answers = st.session_state.get(PRACTICE_EXPANDED_ANSWER_KEY, set())
auto_expand_answer = show_answer and current_idx in expanded_answers
timed_out_notice_idx = st.session_state.pop(PRACTICE_TIMEOUT_NOTICE_KEY, None)
skipped_notice_idx = st.session_state.pop(PRACTICE_SKIPPED_NOTICE_KEY, None)

picked = render_question(
    q=q, idx=current_idx, total=total,
    selected=selected, show_answer=show_answer, is_flagged=is_flagged,
    auto_expand_answer=auto_expand_answer,
)
persist_current_exam(user_id)

timed_out_current = current_idx in timed_out_questions
skipped_current = current_idx in skipped_questions
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
        has_existing_grade = current_idx in self_grades
        existing_grade = self_grades.get(current_idx)
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
        if not picked and not open_ended:
            _skip_current_question()
            st.rerun()
        else:
            record_answer(current_idx, picked)
            pause_timer()
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
    if st.button("🏁 Finish Session & See Score", use_container_width=True):
        ungraded_open_ended = [
            i for i, question in enumerate(questions)
            if is_open_ended_question(question)
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
    st.warning("Are you sure you want to submit this session and see your score?")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("Yes, submit session", type="primary", use_container_width=True):
            st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
            report = submit_section(user_id)
            st.session_state["last_report"] = report
            clear_quiz(); st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
            st.rerun()

# ── Sidebar question map ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Question Map**")
    st.caption("🟢 Correct  🔴 Wrong  ⬜ Unanswered  🚩 Flagged")
    cols = st.columns(5)
    for i in range(total):
        ans  = answers_dict.get(i, "")
        flag = i in flagged_set
        if i in skipped_questions or i in timed_out_questions:
            icon = "ðŸ”´"
        elif i in answers_dict:
            if is_open_ended_question(questions[i]):
                if i in self_grades:
                    icon = "🟢" if self_grades[i] else "🔴"
                else:
                    icon = "⬜"
            else:
                correct_a = (questions[i].get("correct_answer") or "").upper()
                icon = "🟢" if ans.upper() == correct_a else "🔴"
        else:
            icon = "⬜"
        if flag:
            icon = "🚩"
        if cols[i % 5].button(icon, key=f"map_{i}"):
            _go_to_practice_question(i); st.rerun()

# ── Score report ──────────────────────────────────────────────────────────────
if not is_active() and "last_report" in st.session_state:
    report = st.session_state.pop("last_report")
    st.success("Session complete!")
    render_score_card(report, "Practice Session Score")
    _render_pdf_download()
