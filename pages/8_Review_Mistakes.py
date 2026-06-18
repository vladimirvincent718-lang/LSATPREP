"""
pages/8_Review_Mistakes.py — Browse wrong answers filtered by active course.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from streamlit_sortables import sort_items
from datetime import date, timedelta
from html import escape
import json
import re

from src.auth     import require_login
from src.utils    import (
    page_header, sidebar_nav, require_course, DIFFICULTY_LABELS,
    question_reference_label,
)
from src.database import (
    get_mistake_journal, delete_journal_entry, set_journal_entry_completed,
    get_attempts, get_attempt_answers, get_course,
    get_all_curriculums, get_curriculum_courses, get_outstanding_mistake_count,
    create_question_issue_report, get_review_activity, set_mistake_journal_order,
    get_setting, set_setting,
)

st.set_page_config(page_title="Review Mistakes · StudyForge", page_icon="🔍", layout="wide")

REVIEW_STATE_SETTING_KEY = "review_mistakes_workspace_v1"
REVIEW_TAB_LABELS = ["🧭 By Curriculum", "📓 Mistake Journal", "📋 By Session"]
REVIEW_STATE_KEYS = {
    "active_course_id",
    "mistakes_by_curriculum",
    "review_mistakes_active_tab",
    "jf_sec",
    "jf_type",
    "jf_diff",
    "jf_status",
    "cf_course",
    "cf_type",
    "cf_diff",
    "cf_status",
    "cf_course_sort",
    "review_mistakes_show_journal_answers",
    "review_mistakes_show_curriculum_answers",
    "review_mistakes_open_entry_id",
    "review_mistakes_open_course_id",
    "journal_expanded_question_ids",
    "curriculum_expanded_question_ids",
    "review_mistakes_session_id",
    "review_mistakes_session_wrong_only",
}
REVIEW_STATE_PREFIXES = (
    "review_mistakes_show_answer_",
    "review_mistakes_second_attempt_",
)


def _load_saved_review_state(uid: int) -> dict:
    try:
        saved = json.loads(get_setting(uid, REVIEW_STATE_SETTING_KEY) or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _restore_review_state(uid: int) -> None:
    restored_key = f"review_mistakes_state_restored_{uid}"
    if st.session_state.get(restored_key):
        return

    saved = _load_saved_review_state(uid)
    for key, value in saved.items():
        if key in REVIEW_STATE_KEYS or key.startswith(REVIEW_STATE_PREFIXES):
            st.session_state[key] = value

    saved_course_id = saved.get("active_course_id")
    if saved_course_id is not None:
        st.session_state["active_course_id"] = saved_course_id
        st.session_state["sidebar_course_selector"] = saved_course_id
    st.session_state[restored_key] = True


def _save_review_state(uid: int) -> None:
    state = {
        key: value
        for key, value in st.session_state.items()
        if key in REVIEW_STATE_KEYS or key.startswith(REVIEW_STATE_PREFIXES)
    }
    set_setting(uid, REVIEW_STATE_SETTING_KEY, json.dumps(state, separators=(",", ":")))


user_id  = require_login()
username = st.session_state.get("username", "")
_restore_review_state(user_id)
sidebar_nav(username)

from src.utils import course_selector
course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"

curriculums = get_all_curriculums()
curriculum_courses = {c["id"]: get_curriculum_courses(c["id"]) for c in curriculums}
default_curriculum_idx = 0
for idx, curr in enumerate(curriculums):
    if any(c["id"] == course_id for c in curriculum_courses.get(curr["id"], [])):
        default_curriculum_idx = idx
        break

def _today_bounds() -> tuple[str, str, date]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return (
        f"{today.isoformat()} 00:00:00",
        f"{tomorrow.isoformat()} 00:00:00",
        today,
    )


def _selected_curriculum_context() -> tuple[int | None, str, list[int]]:
    if not curriculums:
        return None, "No curriculum selected", []

    selected_id = st.session_state.get("mistakes_by_curriculum")
    valid_ids = {c["id"] for c in curriculums}
    if selected_id not in valid_ids:
        selected_id = curriculums[default_curriculum_idx]["id"]

    selected_title = next(
        (c["title"] for c in curriculums if c["id"] == selected_id),
        "Selected curriculum",
    )
    selected_course_ids = [
        c["id"] for c in curriculum_courses.get(selected_id, []) if c.get("id") is not None
    ]
    return selected_id, selected_title, selected_course_ids


def _latest_review_time(reviews: list[dict]) -> str:
    if not reviews:
        return "No reviews yet today"
    latest = str(reviews[0].get("completed_at") or "")
    return latest[11:16] if len(latest) >= 16 else latest


def _today_label(value: date) -> str:
    return value.strftime("%b %#d") if os.name == "nt" else value.strftime("%b %-d")


def _render_review_dashboard_strip() -> None:
    reviewed_from, reviewed_to, today = _today_bounds()
    selected_curriculum_id, selected_curriculum_title, selected_course_ids = (
        _selected_curriculum_context()
    )

    all_today_reviews = get_review_activity(
        user_id,
        reviewed_from=reviewed_from,
        reviewed_to=reviewed_to,
    )
    curriculum_today_reviews = (
        get_review_activity(
            user_id,
            course_ids=selected_course_ids,
            reviewed_from=reviewed_from,
            reviewed_to=reviewed_to,
        )
        if selected_course_ids
        else []
    )
    course_today_reviews = get_review_activity(
        user_id,
        course_id=course_id,
        reviewed_from=reviewed_from,
        reviewed_to=reviewed_to,
    )
    outstanding = (
        get_outstanding_mistake_count(user_id, course_ids=selected_course_ids)
        if selected_course_ids
        else get_outstanding_mistake_count(user_id)
    )

    safe_curriculum = escape(selected_curriculum_title)
    safe_course = escape(course_title)
    latest_time = escape(_latest_review_time(all_today_reviews))
    today_label = escape(_today_label(today))
    outstanding_scope = safe_curriculum if selected_curriculum_id else "all courses"

    st.markdown(
        f"""
<section class="sf-review-today-dashboard" aria-label="Review dashboard">
  <div class="sf-review-today-copy">
    <p class="sf-review-today-eyebrow">Review Dashboard · {today_label}</p>
    <h2>{len(all_today_reviews)} reviewed today</h2>
    <p>Across your full curriculum library. Latest review: {latest_time}.</p>
  </div>
  <div class="sf-review-today-metrics">
    <div class="sf-review-today-metric">
      <span>{len(curriculum_today_reviews)}</span>
      <p>{safe_curriculum}</p>
      <small>reviewed today</small>
    </div>
    <div class="sf-review-today-metric">
      <span>{len(course_today_reviews)}</span>
      <p>{safe_course}</p>
      <small>active course today</small>
    </div>
    <div class="sf-review-today-metric">
      <span>{outstanding}</span>
      <p>Outstanding</p>
      <small>{outstanding_scope}</small>
    </div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )


st.markdown(
    """
<style>
[data-testid="stMain"] [data-testid="stElementContainer"]:has(#sf-feedback-fab-marker),
[data-testid="stMain"] [data-testid="stElementContainer"].st-key-sf_feedback_fab,
[data-testid="stMain"] [data-testid="stElementContainer"][height="0px"],
[data-testid="stMain"] [data-testid="stElementContainer"]:has(iframe[height="0"]),
[data-testid="stMain"] [data-testid="stElementContainer"]:has(iframe.stIFrame[height="0"]),
[data-testid="stMain"] [data-testid="stElementContainer"]:has([data-testid="stMarkdown"] style) {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
    padding: 0 !important;
}
.sf-review-today-dashboard {
    align-items: stretch;
    background:
        radial-gradient(circle at top left, rgba(20, 184, 166, 0.16), transparent 34%),
        linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
    border: 1px solid #d8dee8;
    border-radius: 8px;
    box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
    display: grid;
    gap: 1rem;
    grid-template-columns: minmax(15rem, 1.2fr) minmax(20rem, 2fr);
    margin: 0.25rem 0 1.45rem;
    padding: 1rem 1.15rem;
}
.sf-review-today-copy h2 {
    color: #0f172a;
    font-size: 1.65rem;
    line-height: 1.15;
    margin: 0.2rem 0 0.35rem;
}
.sf-review-today-copy p {
    color: #53627c;
    margin: 0;
}
.sf-review-today-eyebrow {
    color: #0f766e !important;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    margin: 0 !important;
    text-transform: uppercase;
}
.sf-review-today-metrics {
    display: grid;
    gap: 0.75rem;
    grid-template-columns: repeat(3, minmax(0, 1fr));
}
.sf-review-today-metric {
    background: rgba(255, 255, 255, 0.84);
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    min-width: 0;
    padding: 0.85rem 0.9rem;
}
.sf-review-today-metric span {
    color: #0f172a;
    display: block;
    font-size: 1.55rem;
    font-weight: 850;
    line-height: 1;
}
.sf-review-today-metric p {
    color: #172033;
    font-weight: 750;
    margin: 0.45rem 0 0.15rem;
    overflow-wrap: anywhere;
}
.sf-review-today-metric small {
    color: #64748b;
    display: block;
    font-size: 0.78rem;
    overflow-wrap: anywhere;
}
@media (max-width: 900px) {
    .sf-review-today-dashboard {
        grid-template-columns: 1fr;
    }
    .sf-review-today-metrics {
        grid-template-columns: 1fr;
    }
}
</style>
""",
    unsafe_allow_html=True,
)
_render_review_dashboard_strip()

page_header("🔍 Review Mistakes", f"Study your wrong answers — {course_title}")

saved_tab = st.session_state.get("review_mistakes_active_tab")
if saved_tab not in REVIEW_TAB_LABELS:
    saved_tab = REVIEW_TAB_LABELS[0]
tab_by_curriculum, tab_journal, tab_by_session = st.tabs(
    REVIEW_TAB_LABELS,
    default=saved_tab,
    key="review_mistakes_active_tab",
    on_change="rerun",
)


issue_notice = st.session_state.pop("review_mistakes_issue_report_notice", None)
if issue_notice:
    st.success(issue_notice)


QUESTION_ISSUE_TYPES = [
    "Incorrect answer key",
    "Bad explanation",
    "Weak or mismatched answer choices",
    "Typo or formatting issue",
    "Ambiguous wording",
    "Wrong category/type",
    "Passage or answer choice missing",
    "Other",
]


def _render_choices(
    row: dict,
    selected_answer: str | None = None,
    show_answers: bool = True,
    attempt_widget_key: str | None = None,
    attempt_on_change=None,
    attempt_change_args: tuple = (),
) -> None:
    corr = row.get("correct_answer", "")
    choices = {
        letter: row.get(f"choice_{letter.lower()}", "")
        for letter in ["A", "B", "C", "D", "E"]
        if row.get(f"choice_{letter.lower()}", "")
    }

    if attempt_widget_key:
        selected_answer = st.radio(
            "Select your answer:",
            options=list(choices.keys()),
            index=None,
            key=attempt_widget_key,
            format_func=lambda letter: f"{letter}. {choices[letter]}",
            on_change=attempt_on_change,
            args=attempt_change_args,
        ) or selected_answer
        if selected_answer and selected_answer == corr:
            st.success(f"Correct. {corr}. {choices.get(corr, '')}")
        elif selected_answer:
            st.error(f"Not quite. Your answer: {selected_answer}. {choices.get(selected_answer, '')}")
            if corr:
                st.success(f"Correct answer: {corr}. {choices.get(corr, '')}")
        elif show_answers:
            st.warning("No second-attempt answer selected for this question.")
            if corr:
                st.success(f"Correct answer: {corr}. {choices.get(corr, '')}")
        else:
            st.caption("Choose an answer to check it instantly.")
        return

    for letter, choice in choices.items():
        if not show_answers:
            st.write(f"**{letter}.** {choice}")
            continue
        if selected_answer and letter == corr and letter == selected_answer:
            st.success(f"**{letter}.** {choice}  <- Correct")
        elif selected_answer and letter == selected_answer:
            st.error(f"**{letter}.** {choice}  <- Your answer")
        elif letter == corr:
            suffix = "  <- Correct answer" if selected_answer else ""
            st.success(f"**{letter}.** {choice}{suffix}")
        else:
            st.write(f"**{letter}.** {choice}")


def _render_question_body(
    row: dict,
    selected_answer: str | None = None,
    show_answers: bool = True,
    attempt_widget_key: str | None = None,
    attempt_on_change=None,
    attempt_change_args: tuple = (),
) -> None:
    ref_label = question_reference_label(row)
    if ref_label:
        st.caption(ref_label)

    if row.get("passage"):
        with st.expander("📖 Passage"):
            st.markdown(row["passage"])

    st.markdown(f"**{row.get('stimulus', '')}**")
    st.markdown("")
    _render_choices(
        row,
        selected_answer=selected_answer,
        show_answers=show_answers,
        attempt_widget_key=attempt_widget_key,
        attempt_on_change=attempt_on_change,
        attempt_change_args=attempt_change_args,
    )

    if show_answers and row.get("explanation"):
        st.info(f"💡 {row['explanation']}")

    if show_answers:
        for letter in ["A", "B", "C", "D", "E"]:
            note = row.get(f"wrong_answer_{letter.lower()}", "")
            if note and letter != row.get("correct_answer", ""):
                st.caption(f"**Why {letter} is wrong:** {note}")
    elif not attempt_widget_key:
        st.caption("Answers are hidden. Turn on Show answers when you're ready to check.")


def _difficulty_label(row: dict) -> str:
    diff = row.get("difficulty", 3)
    return str(DIFFICULTY_LABELS.get(diff, diff))


def _completion_counts(entries: list[dict]) -> tuple[int, int, int, int]:
    total = len(entries)
    complete = sum(1 for entry in entries if entry.get("is_completed"))
    incomplete = total - complete
    complete_pct = round((complete / total) * 100) if total else 0
    return total, complete, incomplete, complete_pct


def _filter_by_review_status(entries: list[dict], status_filter: str) -> list[dict]:
    if status_filter == "Reviewed":
        return [entry for entry in entries if entry.get("is_completed")]
    if status_filter == "Outstanding":
        return [entry for entry in entries if not entry.get("is_completed")]
    return entries


def _selectbox_value(label: str, options: list, key: str, **kwargs):
    if not options:
        return None
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
    st.selectbox(
        label,
        options,
        index=options.index(st.session_state[key]),
        key=key,
        **kwargs,
    )
    return st.session_state.get(key, options[0])


def _checkbox_value(label: str, key: str, default: bool = False, **kwargs) -> bool:
    if key not in st.session_state:
        st.session_state[key] = default
    st.checkbox(label, key=key, **kwargs)
    return bool(st.session_state.get(key, default))


def _answer_visibility_key(entry_id: int) -> str:
    return f"review_mistakes_show_answer_{entry_id}"


def _answer_visibility_widget_key(key_prefix: str, entry_id: int) -> str:
    return f"{key_prefix}_show_answer_{entry_id}"


def _review_attempt_key(entry_id: int) -> str:
    return f"review_mistakes_second_attempt_{entry_id}"


def _review_attempt_widget_key(key_prefix: str, entry_id: int) -> str:
    return f"{key_prefix}_second_attempt_{entry_id}"


def _on_review_attempt_change(
    entry_id: int,
    widget_key: str,
    open_course_id: int | None = None,
) -> None:
    selected_answer = st.session_state.get(widget_key)
    st.session_state[_review_attempt_key(entry_id)] = selected_answer
    for prefix in ("journal", "curriculum"):
        sibling_key = _review_attempt_widget_key(prefix, entry_id)
        if sibling_key != widget_key:
            st.session_state[sibling_key] = selected_answer

    st.session_state["review_mistakes_open_entry_id"] = entry_id
    if open_course_id is not None:
        st.session_state["review_mistakes_open_course_id"] = open_course_id


def _question_attempt_widget_key(
    entry: dict,
    key_prefix: str,
    open_course_id: int | None = None,
) -> str:
    state_key = _review_attempt_key(entry["id"])
    widget_key = _review_attempt_widget_key(key_prefix, entry["id"])
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state.get(state_key)
    if state_key not in st.session_state:
        st.session_state[state_key] = st.session_state.get(widget_key)

    st.session_state[widget_key] = st.session_state.get(state_key)
    return widget_key


def _expanded_question_ids_key(key_prefix: str) -> str:
    return f"{key_prefix}_expanded_question_ids"


def _expanded_question_ids(key_prefix: str) -> set[int]:
    return set(st.session_state.get(_expanded_question_ids_key(key_prefix), []))


def _set_expanded_question_ids(key_prefix: str, entry_ids: set[int] | list[int]) -> None:
    st.session_state[_expanded_question_ids_key(key_prefix)] = sorted(entry_ids)


def _question_is_expanded(entry_id: int, key_prefix: str) -> bool:
    return (
        entry_id in _expanded_question_ids(key_prefix)
        or st.session_state.get("review_mistakes_open_entry_id") == entry_id
    )


def _expanded_question_caption(entries: list[dict], key_prefix: str) -> str:
    if not entries:
        return "No visible questions to open"
    expanded_count = len(_expanded_question_ids(key_prefix) & {entry["id"] for entry in entries})
    return f"{expanded_count}/{len(entries)} visible questions open"


def _render_review_action_bar(
    visible_entries: list[dict],
    all_entries: list[dict],
    key_prefix: str,
    show_answers_key: str,
) -> bool:
    entry_ids = {entry["id"] for entry in visible_entries}
    expanded_ids = _expanded_question_ids(key_prefix) & entry_ids
    _set_expanded_question_ids(key_prefix, expanded_ids)

    controls = st.columns([1.1, 1.25, 1.1, 3.2])
    with controls[0]:
        show_answers = _checkbox_value(
            "Show answers",
            key=show_answers_key,
            default=False,
            help="Turn this on after you have tried the question again.",
            on_change=_on_master_show_answers_change,
            args=(show_answers_key, all_entries),
        )
    with controls[1]:
        if st.button(
            "Open visible",
            key=f"{key_prefix}_open_visible_questions",
            use_container_width=True,
            disabled=not visible_entries,
        ):
            _set_expanded_question_ids(key_prefix, entry_ids)
            st.session_state.pop("review_mistakes_open_entry_id", None)
            st.rerun()
    with controls[2]:
        if st.button(
            "Close all",
            key=f"{key_prefix}_close_questions",
            use_container_width=True,
            disabled=not visible_entries and not expanded_ids,
        ):
            _set_expanded_question_ids(key_prefix, set())
            st.session_state.pop("review_mistakes_open_entry_id", None)
            st.rerun()
    with controls[3]:
        st.caption(_expanded_question_caption(visible_entries, key_prefix))
    return show_answers


def _on_master_show_answers_change(master_key: str, entries: list[dict]) -> None:
    show_answers = bool(st.session_state.get(master_key, False))
    for entry in entries:
        st.session_state[_answer_visibility_key(entry["id"])] = show_answers
        for prefix in ("journal", "curriculum"):
            st.session_state[_answer_visibility_widget_key(prefix, entry["id"])] = show_answers


def _on_question_show_answers_change(
    entry_id: int,
    widget_key: str,
    open_course_id: int | None = None,
) -> None:
    show_answers = bool(st.session_state.get(widget_key, False))
    st.session_state[_answer_visibility_key(entry_id)] = show_answers
    for prefix in ("journal", "curriculum"):
        sibling_key = _answer_visibility_widget_key(prefix, entry_id)
        if sibling_key != widget_key:
            st.session_state[sibling_key] = show_answers

    st.session_state["review_mistakes_open_entry_id"] = entry_id
    if open_course_id is not None:
        st.session_state["review_mistakes_open_course_id"] = open_course_id


def _question_show_answers_value(
    entry: dict,
    master_value: bool,
    key_prefix: str,
    open_course_id: int | None = None,
) -> bool:
    state_key = _answer_visibility_key(entry["id"])
    if state_key not in st.session_state:
        st.session_state[state_key] = master_value

    widget_key = _answer_visibility_widget_key(key_prefix, entry["id"])
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state[state_key]

    st.checkbox(
        "Show answers",
        key=widget_key,
        help="Show or hide the answer key and explanation for this question.",
        on_change=_on_question_show_answers_change,
        args=(entry["id"], widget_key, open_course_id),
    )
    st.session_state[state_key] = bool(st.session_state.get(widget_key, master_value))
    return bool(st.session_state.get(state_key, master_value))


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


def _render_outstanding_notice(incomplete: int) -> None:
    if incomplete:
        st.markdown(
            (
                "<div style='display:flex; align-items:center; gap:0.65rem; "
                "border:1px solid #fecaca; background:#fef2f2; color:#7f1d1d; "
                "border-radius:8px; padding:0.8rem 0.95rem; margin:0.85rem 0 1rem 0;'>"
                "<span style='display:inline-flex; align-items:center; justify-content:center; "
                "min-width:2rem; height:2rem; border-radius:999px; background:#dc2626; "
                "color:#ffffff; font-weight:800;'>"
                f"{incomplete}</span>"
                "<span style='font-weight:750;'>"
                f"{incomplete} outstanding mistake"
                f"{'' if incomplete == 1 else 's'} left to review"
                "</span></div>"
            ),
            unsafe_allow_html=True,
        )
    else:
        st.success("All mistakes in this curriculum are reviewed.")


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


def _render_review_checkbox(
    entry: dict,
    is_completed: bool,
    key_prefix: str,
    open_course_id: int | None = None,
) -> None:
    key = f"{key_prefix}_{entry['id']}"
    st.session_state[key] = bool(is_completed)
    st.checkbox(
        "Reviewed",
        key=key,
        help="Mark this mistake as reviewed.",
        on_change=_on_review_checkbox_change,
        args=(entry["id"], key, open_course_id),
    )


def _on_review_checkbox_change(
    entry_id: int,
    key: str,
    open_course_id: int | None = None,
) -> None:
    checked = bool(st.session_state.get(key, False))
    st.session_state["review_mistakes_open_entry_id"] = entry_id
    if open_course_id is not None:
        st.session_state["review_mistakes_open_course_id"] = open_course_id
    set_journal_entry_completed(entry_id, checked)

    for prefix in ("complete", "curriculum_complete"):
        sibling_key = f"{prefix}_{entry_id}"
        if sibling_key != key:
            st.session_state[sibling_key] = checked


def _render_note_editor(
    entry: dict,
    key_prefix: str,
    open_course_id: int | None = None,
) -> None:
    note = entry.get("note") or ""
    note_label = f"Reflection note for mistake {entry['id']}"
    st.markdown("**Reflection note**")
    new_note = st.text_area(
        note_label,
        value=note,
        key=f"{key_prefix}_reflection_note_{entry['id']}",
        height=110,
        placeholder=(
            "What pulled you toward the wrong answer? "
            "What should you watch for next time?"
        ),
        label_visibility="collapsed",
    )
    _render_note_voice_control(note_label, f"{key_prefix}_{entry['id']}")

    if st.button("Save note", key=f"{key_prefix}_save_note_{entry['id']}"):
        st.session_state["review_mistakes_open_entry_id"] = entry["id"]
        if open_course_id is not None:
            st.session_state["review_mistakes_open_course_id"] = open_course_id
        from src.database import get_connection

        conn = get_connection()
        conn.execute(
            "UPDATE mistake_journal SET note = ? WHERE id = ?",
            (new_note.strip(), entry["id"]),
        )
        conn.commit()
        conn.close()
        st.success("Note saved.")
        st.rerun()


def _render_issue_report(entry: dict, key_prefix: str, open_course_id: int | None = None) -> None:
    report_key = f"review_mistakes_issue_open_{key_prefix}_{entry['id']}"

    if st.button("Report Issue", key=f"{key_prefix}_report_issue_btn_{entry['id']}"):
        st.session_state[report_key] = True
        st.session_state["review_mistakes_open_entry_id"] = entry["id"]
        if open_course_id is not None:
            st.session_state["review_mistakes_open_course_id"] = open_course_id
        st.rerun()

    if not st.session_state.get(report_key):
        return

    with st.form(f"{key_prefix}_question_report_form_{entry['id']}"):
        st.markdown("**Report Issue**")
        issue_type = st.selectbox(
            "Issue type",
            QUESTION_ISSUE_TYPES,
            key=f"{key_prefix}_issue_type_{entry['id']}",
        )
        note = st.text_area(
            "Optional note",
            placeholder="Example: I think the terminal value should be 13.22, not the keyed answer.",
            height=90,
            key=f"{key_prefix}_issue_note_{entry['id']}",
        )
        form_cols = st.columns(2)
        submit_report = form_cols[0].form_submit_button(
            "Submit Report", type="primary", use_container_width=True
        )
        cancel_report = form_cols[1].form_submit_button(
            "Cancel", use_container_width=True
        )

    if submit_report:
        report_id, err = create_question_issue_report(
            user_id=user_id,
            question_id=entry.get("question_id"),
            attempt_id=entry.get("attempt_id"),
            issue_type=issue_type,
            note=note,
            selected_answer=entry.get("selected_answer") or "",
            mode="Review Mistakes",
        )
        if err:
            st.error(f"Could not save report: {err}")
        else:
            st.session_state.pop(report_key, None)
            st.session_state["review_mistakes_issue_report_notice"] = (
                f"Report submitted. Reference #{report_id}."
            )
            st.rerun()

    if cancel_report:
        st.session_state.pop(report_key, None)
        st.rerun()


def _render_note_voice_control(target_label: str, key: str) -> None:
    safe_target = escape(target_label, quote=True)
    safe_key = escape(key, quote=True)
    st.markdown(
        f"""
<div class="sf-note-voice" data-sf-note-target="{safe_target}" data-sf-note-key="{safe_key}">
  <button class="sf-note-mic" type="button">🎙 Dictate note</button>
  <div class="sf-note-wave" aria-hidden="true">
    <span></span><span></span><span></span><span></span><span></span>
  </div>
  <span class="sf-note-status">Use your mic or press Ctrl+Shift+M while typing.</span>
</div>
""",
        unsafe_allow_html=True,
    )


def _inject_note_voice_dictation() -> None:
    html = f"""
<script>
(function() {{
  var P = window.parent;
  if (!P || !P.document) return;
  if (P._sfNoteVoice && P._sfNoteVoice.cleanup) P._sfNoteVoice.cleanup();

  var doc = P.document;
  var style = doc.getElementById('sf-note-voice-style');
  if (!style) {{
    style = doc.createElement('style');
    style.id = 'sf-note-voice-style';
    style.textContent = `
      .sf-note-voice {{
        align-items: center;
        display: flex;
        gap: 0.65rem;
        margin: 0.4rem 0 0.75rem;
        min-height: 2.4rem;
      }}
      .sf-note-mic {{
        align-items: center;
        background: #0f766e;
        border: 0;
        border-radius: 999px;
        color: #fff;
        cursor: pointer;
        display: inline-flex;
        font: 700 0.88rem system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        gap: 0.4rem;
        padding: 0.45rem 0.8rem;
      }}
      .sf-note-mic.listening {{ background: #dc2626; }}
      .sf-note-wave {{
        align-items: center;
        display: none;
        gap: 0.18rem;
        height: 1.35rem;
      }}
      .sf-note-wave.active {{ display: inline-flex; }}
      .sf-note-wave span {{
        animation: sf-note-wave 0.72s ease-in-out infinite;
        background: #0f766e;
        border-radius: 999px;
        display: block;
        height: 0.45rem;
        width: 0.22rem;
      }}
      .sf-note-wave span:nth-child(2) {{ animation-delay: 0.08s; }}
      .sf-note-wave span:nth-child(3) {{ animation-delay: 0.16s; }}
      .sf-note-wave span:nth-child(4) {{ animation-delay: 0.24s; }}
      .sf-note-wave span:nth-child(5) {{ animation-delay: 0.32s; }}
      .sf-note-status {{
        color: #475569;
        font: 0.82rem system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      @keyframes sf-note-wave {{
        0%, 100% {{ height: 0.4rem; opacity: 0.45; }}
        50% {{ height: 1.25rem; opacity: 1; }}
      }}
    `;
    doc.head.appendChild(style);
  }}

  var SpeechRecognition = P.SpeechRecognition || P.webkitSpeechRecognition;
  var recognition = null;
  var listening = false;
  var activeControl = null;
  var activeTargetLabel = null;

  function setListening(on) {{
    listening = on;
    var button = activeControl ? activeControl.querySelector('.sf-note-mic') : null;
    var wave = activeControl ? activeControl.querySelector('.sf-note-wave') : null;
    var status = activeControl ? activeControl.querySelector('.sf-note-status') : null;
    if (!button || !wave || !status) return;
    button.classList.toggle('listening', on);
    wave.classList.toggle('active', on);
    button.textContent = on ? '■ Stop' : '🎙 Dictate note';
    status.textContent = on ? 'Listening...' : 'Use your mic or press Ctrl+Shift+M while typing.';
  }}

  function setStatus(control, message) {{
    var status = control ? control.querySelector('.sf-note-status') : null;
    if (status) status.textContent = message;
  }}

  function findTextarea(targetLabel) {{
    var areas = Array.prototype.slice.call(doc.querySelectorAll('textarea'));
    return areas.find(function(area) {{
      return area.getAttribute('aria-label') === targetLabel;
    }});
  }}

  function findControlForTextarea(textarea) {{
    if (!textarea) return null;
    var label = textarea.getAttribute('aria-label');
    if (!label || label.indexOf('Reflection note for mistake ') !== 0) return null;
    var controls = Array.prototype.slice.call(doc.querySelectorAll('.sf-note-voice'));
    return controls.find(function(control) {{
      return control.getAttribute('data-sf-note-target') === label;
    }});
  }}

  function appendToTextarea(text) {{
    var textarea = findTextarea(activeTargetLabel);
    if (!textarea || !text) return false;
    var current = textarea.value || '';
    var spacer = current && !/\\s$/.test(current) ? ' ' : '';
    var next = current + spacer + text.trim();
    var setter = Object.getOwnPropertyDescriptor(P.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, next);
    textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
    textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
    textarea.focus();
    setStatus(activeControl, 'Added transcript to note.');
    return true;
  }}

  function startForControl(control) {{
    if (!SpeechRecognition) {{
      setStatus(control, 'Voice dictation is not supported in this browser.');
      return;
    }}
    if (listening && recognition) {{
      try {{ recognition.stop(); }} catch (e) {{}}
      return;
    }}

    activeControl = control;
    activeTargetLabel = control.getAttribute('data-sf-note-target');
    var textarea = findTextarea(activeTargetLabel);
    if (!textarea) {{
      setStatus(control, 'Open or focus the note box first.');
      return;
    }}

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onstart = function() {{
      setListening(true);
    }};

    recognition.onresult = function(ev) {{
      var finalText = '';
      var interimText = '';
      for (var i = ev.resultIndex; i < ev.results.length; i++) {{
        var transcript = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalText += transcript;
        else interimText += transcript;
      }}
      if (interimText.trim()) setStatus(activeControl, 'Capturing voice...');
      if (finalText.trim()) appendToTextarea(finalText);
    }};

    recognition.onerror = function(ev) {{
      if (ev.error === 'not-allowed') setStatus(activeControl, 'Microphone blocked. Allow mic access and try again.');
      else if (ev.error === 'no-speech') setStatus(activeControl, 'No speech detected. Try again.');
      else setStatus(activeControl, 'Mic error: ' + ev.error);
      setListening(false);
    }};

    recognition.onend = function() {{
      setListening(false);
      recognition = null;
    }};

    try {{
      recognition.start();
    }} catch (err) {{
      setStatus(activeControl, 'Could not start mic: ' + err.message);
      setListening(false);
    }}
  }}

  function onClick(ev) {{
    var button = ev.target.closest ? ev.target.closest('.sf-note-mic') : null;
    if (!button) return;
    var control = button.closest('.sf-note-voice');
    if (!control) return;
    ev.preventDefault();
    startForControl(control);
  }}

  function onKeydown(ev) {{
    if (!(ev.ctrlKey && ev.shiftKey && ev.key.toLowerCase() === 'm')) return;
    var textarea = doc.activeElement;
    if (!textarea || textarea.tagName !== 'TEXTAREA') return;
    var control = findControlForTextarea(textarea);
    if (!control) return;
    ev.preventDefault();
    startForControl(control);
  }}

  doc.addEventListener('click', onClick);
  doc.addEventListener('keydown', onKeydown);
  P._sfNoteVoice = {{
    cleanup: function() {{
      doc.removeEventListener('click', onClick);
      doc.removeEventListener('keydown', onKeydown);
      if (recognition) {{
        try {{ recognition.stop(); }} catch (e) {{}}
      }}
    }}
  }};
}})();
</script>
"""
    components.html(html, height=0, scrolling=False)


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


def _master_cc_sort_key(entry: dict) -> tuple[int, str, int]:
    raw_id = entry.get("master_question_id")
    if raw_id in (None, ""):
        raw_id = entry.get("question_id")

    text_id = str(raw_id or "").strip()
    match = re.search(r"\d+", text_id)
    numeric_id = int(match.group(0)) if match else 10**12
    return numeric_id, text_id.lower(), int(entry.get("id") or 0)


def _sort_entries_by_master_cc(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=_master_cc_sort_key)


def _queue_card_label(entry: dict, duplicate_labels: set[str]) -> str:
    reference = question_reference_label(entry) or f"Question {entry['id']}"
    stimulus = " ".join(str(entry.get("stimulus") or "").split())
    if len(stimulus) > 115:
        stimulus = f"{stimulus[:112]}..."
    label = f"{reference} | {stimulus}" if stimulus else reference
    if label in duplicate_labels:
        label = f"{label} | Review #{entry['id']}"
    return label


def _merge_visible_queue_order(
    all_entries: list[dict],
    visible_entry_ids: list[int],
) -> list[int]:
    visible_ids = set(visible_entry_ids)
    reordered = iter(visible_entry_ids)
    return [
        next(reordered) if entry["id"] in visible_ids else entry["id"]
        for entry in all_entries
    ]


def _render_drag_queue(
    visible_entries: list[dict],
    all_entries: list[dict],
    key: str,
    open_course_id: int | None = None,
) -> list[dict]:
    if len(visible_entries) < 2:
        return visible_entries

    base_labels = []
    for entry in visible_entries:
        reference = question_reference_label(entry) or f"Question {entry['id']}"
        stimulus = " ".join(str(entry.get("stimulus") or "").split())
        base_labels.append(f"{reference} | {stimulus}" if stimulus else reference)
    duplicate_labels = {label for label in base_labels if base_labels.count(label) > 1}

    label_to_entry = {
        _queue_card_label(entry, duplicate_labels): entry for entry in visible_entries
    }
    current_labels = list(label_to_entry)
    st.caption(
        "Drag these question cards up or down to set the review order. "
        "The full question panels below follow this order."
    )
    sorted_labels = sort_items(
        current_labels,
        direction="vertical",
        key=key,
        custom_style="""
            .sortable-component.vertical { gap: 0.35rem; }
            .sortable-item {
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                color: #172033;
                cursor: grab;
                font-size: 0.82rem;
                line-height: 1.25;
                padding: 0.55rem 0.7rem;
            }
            .sortable-item:active { cursor: grabbing; }
        """,
    )
    sorted_entries = [label_to_entry[label] for label in sorted_labels]
    sorted_ids = [entry["id"] for entry in sorted_entries]
    current_ids = [entry["id"] for entry in visible_entries]
    if sorted_ids != current_ids:
        merged_ids = _merge_visible_queue_order(all_entries, sorted_ids)
        set_mistake_journal_order(user_id, merged_ids)
        if open_course_id is not None:
            st.session_state["review_mistakes_open_course_id"] = open_course_id
        st.rerun()
    return sorted_entries


_inject_note_voice_dictation()


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

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            section_opts = ["All"] + sorted({j["section_type"] for j in journal if j.get("section_type")})
            filter_sec   = _selectbox_value("Section Type", section_opts, key="jf_sec")
        with col2:
            type_opts  = ["All"] + sorted({j["question_type"] for j in journal if j.get("question_type")})
            filter_type = _selectbox_value("Question Type", type_opts, key="jf_type")
        with col3:
            diff_opts  = ["All"] + [str(d) for d in sorted({j["difficulty"] for j in journal if j.get("difficulty")})]
            filter_diff = _selectbox_value("Difficulty", diff_opts, key="jf_diff")
        with col4:
            status_filter = _selectbox_value(
                "Review Status",
                ["All", "Outstanding", "Reviewed"],
                key="jf_status",
            )

        filtered = journal
        if filter_sec  != "All": filtered = [j for j in filtered if j.get("section_type")  == filter_sec]
        if filter_type != "All": filtered = [j for j in filtered if j.get("question_type") == filter_type]
        if filter_diff != "All": filtered = [j for j in filtered if str(j.get("difficulty")) == filter_diff]
        filtered = _filter_by_review_status(filtered, status_filter)

        show_journal_answers = _render_review_action_bar(
            filtered,
            journal,
            "journal",
            "review_mistakes_show_journal_answers",
        )

        if len(filtered) != len(journal):
            _render_completion_summary(filtered, "current filters")

        st.divider()

        if not filtered:
            st.info("No mistakes match the current filters.")

        for entry in filtered:
            qtype = entry.get("question_type", "")
            sec   = entry.get("section_type", "")
            note  = entry.get("note", "")
            corr  = entry.get("correct_answer", "")
            done  = bool(entry.get("is_completed"))

            panel_col, status_col, check_col = st.columns([7, 1.4, 1.2])
            with panel_col:
                with st.expander(
                    f"[{_difficulty_label(entry)}] {sec} · {qtype}",
                    expanded=_question_is_expanded(entry["id"], "journal"),
                ):
                    entry_show_answers = _question_show_answers_value(
                        entry,
                        show_journal_answers,
                        "journal",
                    )
                    attempt_widget_key = _question_attempt_widget_key(entry, "journal")
                    _render_question_body(
                        entry,
                        show_answers=entry_show_answers,
                        attempt_widget_key=attempt_widget_key,
                        attempt_on_change=_on_review_attempt_change,
                        attempt_change_args=(entry["id"], attempt_widget_key),
                    )
                    st.divider()
                    _render_issue_report(entry, "journal")
                    st.divider()
                    _render_note_editor(entry, "journal")

                    if st.button("🗑 Remove", key=f"del_{entry['id']}"):
                        st.session_state.pop("review_mistakes_open_entry_id", None)
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

        attempt_ids = [a["id"] for a in attempts]
        if st.session_state.get("review_mistakes_session_id") not in attempt_ids:
            st.session_state["review_mistakes_session_id"] = attempt_ids[0]
        selected_id = st.selectbox(
            "Select a session to review:",
            options=attempt_ids,
            key="review_mistakes_session_id",
            format_func=lambda x: next(
                f"{a['completed_at'][:10]} · {a['mode']} · {a['section_type']}"
                for a in attempts if a["id"] == x
            ),
        )

        if selected_id:
            ans_rows   = get_attempt_answers(selected_id)
            wrong_only = st.checkbox(
                "Show wrong answers only",
                value=True,
                key="review_mistakes_session_wrong_only",
            )
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
    if not curriculums:
        st.info("No curriculums have been created yet. Create one in Curriculum Builder.")
    else:
        curriculum_ids = [c["id"] for c in curriculums]
        if st.session_state.get("mistakes_by_curriculum") not in curriculum_ids:
            st.session_state["mistakes_by_curriculum"] = curriculum_ids[default_curriculum_idx]
        selected_curriculum_id = st.selectbox(
            "Curriculum",
            options=curriculum_ids,
            index=default_curriculum_idx,
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
                _render_outstanding_notice(
                    get_outstanding_mistake_count(user_id, course_ids=course_ids)
                )
                _render_completion_summary(journal, "selected curriculum")

                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    course_filter_options = ["All"] + [str(cid) for cid in course_ids]
                    course_filter = _selectbox_value(
                        "Course",
                        course_filter_options,
                        format_func=(
                            lambda cid: "All"
                            if cid == "All"
                            else course_title_by_id.get(int(cid), "Unknown")
                        ),
                        key="cf_course",
                    )
                with col2:
                    type_opts = ["All"] + sorted({j["question_type"] for j in journal if j.get("question_type")})
                    type_filter = _selectbox_value("Question Type", type_opts, key="cf_type")
                with col3:
                    diff_opts = ["All"] + [str(d) for d in sorted({j["difficulty"] for j in journal if j.get("difficulty")})]
                    diff_filter = _selectbox_value("Difficulty", diff_opts, key="cf_diff")
                with col4:
                    status_filter = _selectbox_value(
                        "Review Status",
                        ["All", "Outstanding", "Reviewed"],
                        key="cf_status",
                    )
                with col5:
                    course_sort = _selectbox_value(
                        "Sort by",
                        ["Course name", "Review progress", "Master CC number"],
                        key="cf_course_sort",
                    )

                filtered = journal
                if course_filter != "All":
                    selected_course_id = int(course_filter)
                    filtered = [j for j in filtered if j.get("q_course_id") == selected_course_id]
                if type_filter != "All":
                    filtered = [j for j in filtered if j.get("question_type") == type_filter]
                if diff_filter != "All":
                    filtered = [j for j in filtered if str(j.get("difficulty")) == diff_filter]
                filtered = _filter_by_review_status(filtered, status_filter)

                show_curriculum_answers = _render_review_action_bar(
                    filtered,
                    journal,
                    "curriculum",
                    "review_mistakes_show_curriculum_answers",
                )

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
                    if course_sort == "Master CC number":
                        course_entries = _sort_entries_by_master_cc(course_entries)
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

                if not course_groups:
                    st.info("No mistakes match the current curriculum filters.")

                if course_sort == "Master CC number":
                    course_groups.sort(
                        key=lambda group: (
                            _master_cc_sort_key(group["entries"][0]),
                            group["course"]["title"].lower(),
                        )
                    )
                elif course_sort == "Review progress":
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
                    open_course_id = st.session_state.get("review_mistakes_open_course_id", course_id)
                    _render_course_progress_strip(course_row["title"], course_entries)

                    with st.expander(
                        (
                            f"{course_row['title']} - {group['complete']}/{group['total']} reviewed "
                            f"({group['complete_pct']}%), {group['incomplete']} outstanding"
                        ),
                        expanded=course_row["id"] == open_course_id,
                    ):
                        if course_sort == "Master CC number":
                            st.caption(
                                "Master CC view: visible mistakes are sorted by source question number "
                                "inside each course."
                            )
                        else:
                            st.caption(
                                "Curriculum order view: review mistakes course-by-course "
                                "as they appear in the selected curriculum."
                            )

                        if course_sort == "Master CC number":
                            st.caption(
                                "Choose Course name or Review progress to drag questions "
                                "into a custom review order."
                            )
                        else:
                            all_course_entries = [
                                entry
                                for entry in journal
                                if entry.get("q_course_id") == course_row["id"]
                            ]
                            course_entries = _render_drag_queue(
                                course_entries,
                                all_course_entries,
                                key=f"curriculum_review_queue_{user_id}_{course_row['id']}",
                                open_course_id=course_row["id"],
                            )

                        for entry in course_entries:
                            qtype = entry.get("question_type", "")
                            sec   = entry.get("section_type", "")
                            corr  = entry.get("correct_answer", "")
                            done  = bool(entry.get("is_completed"))

                            panel_col, status_col, check_col = st.columns([7, 1.4, 1.2])
                            with panel_col:
                                with st.expander(
                                    f"[{_difficulty_label(entry)}] {sec} · {qtype}",
                                    expanded=_question_is_expanded(entry["id"], "curriculum"),
                                ):
                                    entry_show_answers = _question_show_answers_value(
                                        entry,
                                        show_curriculum_answers,
                                        "curriculum",
                                        open_course_id=course_row["id"],
                                    )
                                    attempt_widget_key = _question_attempt_widget_key(
                                        entry,
                                        "curriculum",
                                        open_course_id=course_row["id"],
                                    )
                                    _render_question_body(
                                        entry,
                                        show_answers=entry_show_answers,
                                        attempt_widget_key=attempt_widget_key,
                                        attempt_on_change=_on_review_attempt_change,
                                        attempt_change_args=(
                                            entry["id"],
                                            attempt_widget_key,
                                            course_row["id"],
                                        ),
                                    )
                                    st.divider()
                                    _render_issue_report(
                                        entry,
                                        "curriculum",
                                        open_course_id=course_row["id"],
                                    )
                                    st.divider()
                                    _render_note_editor(
                                        entry,
                                        "curriculum",
                                        open_course_id=course_row["id"],
                                    )
                            with status_col:
                                st.markdown(_review_status_badge(done), unsafe_allow_html=True)
                            with check_col:
                                _render_review_checkbox(
                                    entry,
                                    done,
                                    "curriculum_complete",
                                    open_course_id=course_row["id"],
                                )


_save_review_state(user_id)
