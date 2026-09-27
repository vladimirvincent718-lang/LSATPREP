"""
pages/5_Practice_Mode.py — Untimed practice drill, filtered by active course.
"""

import sys, os
import json
import re
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import streamlit as st
import streamlit.components.v1 as components
import random

from src.auth         import require_login
from src.utils        import (page_header, sidebar_nav,
                               render_question, render_score_card, DIFFICULTY_LABELS,
                               get_effective_admin)
from src.database     import (
    get_all_questions, get_all_settings, get_distinct_values,
    get_enrolled_courses, get_course_question_count, set_setting,
    get_answer_stats, save_answer, add_to_journal,
    get_external_practice_entries, get_external_practice_sources,
    save_external_practice_entry, update_external_practice_entry,
    delete_external_practice_entry,
    add_study_time, get_study_time_entries, get_study_time_total,
    get_exam_drafts, delete_exam_draft,
    get_all_curriculums, get_curriculum_courses,
)
from src.practice_report import METRICS, open_report, render_report
from src.exam_planning import get_exam_plan, exam_countdown, visible_metrics, render_metric_settings, render_exam_settings
from src.practice_allocation import allocation_plan, question_group, module_label, practice_questions
from src.practice_replacement import closest_replacements, replacement_pool
from src.practice_session_edit import (
    HISTORY_KEY, SCOPE_KEY, initialize_edit_state, addition_candidates,
    removal_error, remove_question_state, remove_saved_answer,
)
from src.practice_review_focus import (
    CONTENT_MODE_SETTING, filter_review_questions, matches_review_topic, render_review_focus,
)
from src.practice_allocation_editor import editor_config, render_allocation_editor
from src.practice_swipe import install_swipe_view, install_swipe_gestures, skip_pass_indices
from src.exam_engine  import (
    start_quiz, clear_quiz, is_active, current_question, next_question,
    prev_question, record_answer, record_self_grade,
    submit_section, persist_current_exam,
    restore_exam_draft, suspend_current_exam, _st, _set, _K,
    time_on_current_question,
)
from src.analytics    import get_smart_review_questions
from src.question_ordering import arrange_question_dependencies, references_previous_question
from src.question_loader import is_open_ended_question
from src.question_map import render_question_map, render_question_map_legend
from src.question_explanations import render_personal_explanation, get_new_question_explanations
from src.question_notes import render_question_notes
from src.pdf_export import make_pdf_filename
from src.offline_exams import export_offline_exam, render_offline_exams
from src.email_notifications import send_take_home_exam_pdf
from src.professional_specialty import (
    DEFAULT_SPECIALTY,
    PROFESSIONAL_SPECIALTY_SETTING,
    normalize_specialty,
    professional_context_cue,
    specialty_label,
)

PRACTICE_POOL_KEY = "practice_question_pool"
PRACTICE_NOTICE_KEY = "practice_session_notice"
PRACTICE_PDF_KEY = "practice_pdf"
PRACTICE_PDF_NAME_KEY = "practice_pdf_name"
PRACTICE_CONFIRM_FINISH_KEY = "practice_confirm_finish"
PRACTICE_SESSION_LABEL_KEY = "practice_session_label"
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
PRACTICE_TIMER_ACTIVITY_LAST_TICK_KEY = "practice_timer_activity_last_tick_at"
PRACTICE_TIMER_ACTIVITY_REMAINING_KEY = "practice_timer_activity_remaining_at_tick"
PRACTICE_N_QUESTIONS_KEY = "practice_n_questions"
PRACTICE_DIFFICULTY_COUNT_PREFIX = "practice_difficulty_count"
PRACTICE_BULK_DIFFICULTY_COUNT_KEY = "practice_bulk_difficulty_count"
PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY = "practice_last_applied_bulk_difficulty_count"
PRACTICE_AVAILABLE_DIFFICULTY_COUNTS_KEY = "practice_available_difficulty_counts"
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
PRACTICE_DASHBOARD_OPEN_KEY = "practice_dashboard_open"
PRACTICE_DAILY_TARGET_SETTING = "practice_daily_question_target"
PRACTICE_DEFAULT_TIMER_SECONDS = 120
MODULE_ALL = "All modules (randomized)"
MODULE_RANDOM = "Random module"
PRACTICE_LAST_SETTINGS_KEY = "practice_mode_last_settings"
PRACTICE_SPECIALTY_KEY = "practice_professional_specialty"
QUESTION_ORDER_RANDOM = "Randomized"
QUESTION_ORDER_BY_DIFFICULTY = "By difficulty (1 to 5)"
QUESTION_ORDER_OPTIONS = [QUESTION_ORDER_RANDOM, QUESTION_ORDER_BY_DIFFICULTY]
QUESTION_MODE_MULTIPLE_CHOICE = "Multiple choice"
QUESTION_MODE_OPEN_ENDED = "Open-ended challenge"
QUESTION_MODE_OPTIONS = [QUESTION_MODE_MULTIPLE_CHOICE, QUESTION_MODE_OPEN_ENDED]


def _today_bounds() -> tuple[str, str, date]:
    local_zone = ZoneInfo("America/New_York")
    today = datetime.now(local_zone).date()
    tomorrow = today + timedelta(days=1)
    local_start = datetime.combine(today, datetime.min.time(), tzinfo=local_zone)
    local_end = datetime.combine(tomorrow, datetime.min.time(), tzinfo=local_zone)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
        local_end.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
        today,
    )


def _today_label(value: date) -> str:
    return value.strftime("%b %#d") if os.name == "nt" else value.strftime("%b %-d")


def _latest_practice_time(answers: list[dict]) -> str:
    if not answers:
        return "No scored practice yet today"
    latest = max(str(answer.get("completed_at") or "") for answer in answers)
    return latest[11:16] if len(latest) >= 16 else latest


def _format_active_time(seconds: float, *, include_seconds: bool = False) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s" if include_seconds else f"{minutes}m"
    return f"{secs}s" if include_seconds else "<1m"


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
    return f" Current session: {answered}/{total} answered and saved as you go."


def _install_practice_dashboard_styles() -> None:
    st.markdown(
        """
<style>
.st-key-practice_dashboard_summary {
    background:
        radial-gradient(circle at top left, rgba(37, 99, 235, .16), transparent 35%),
        linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    box-shadow: 0 12px 30px rgba(15, 23, 42, .08);
    padding: 1rem 1.1rem 1.1rem;
    transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.st-key-practice_dashboard_toggle_button_v2 .stButton {
    display: flex;
    justify-content: flex-end;
}
.st-key-practice_dashboard_toggle_button_v2 .stButton > button {
    background: #eff6ff;
    border: 1px solid #93c5fd;
    border-radius: 999px;
    color: #1d4ed8;
    cursor: pointer;
    font-size: .8rem;
    font-weight: 800;
    height: 2rem;
    min-height: 2rem;
    min-width: 2rem;
    padding: 0;
    width: 2rem;
}
.st-key-practice_dashboard_toggle_button_v2 .stButton > button:hover {
    background: #dbeafe;
    border-color: #60a5fa;
    color: #1e40af;
}
.st-key-practice_dashboard_summary:has(button:focus-visible) {
    outline: 3px solid rgba(37, 99, 235, .35);
    outline-offset: 2px;
}
.st-key-practice_timer_tools_resume_control .stButton,
.st-key-practice_timer_resume_control .stButton,
.st-key-practice_timer_pause_control .stButton,
.st-key-practice_timer_tools_pause_control .stButton {
    display: flex;
    justify-content: center;
}
.st-key-practice_timer_tools_resume_control .stButton > button,
.st-key-practice_timer_resume_control .stButton > button,
.st-key-practice_timer_pause_control .stButton > button,
.st-key-practice_timer_tools_pause_control .stButton > button {
    border-radius: 999px;
    font-size: 1.05rem;
    font-weight: 900;
    height: 2.65rem;
    min-height: 2.65rem;
    min-width: 2.65rem;
    padding: 0;
    width: 2.65rem;
}
.st-key-practice_timer_tools_resume_control .stButton > button,
.st-key-practice_timer_resume_control .stButton > button {
    background: #ecfdf5;
    border-color: #6ee7b7;
    color: #047857;
}
.st-key-practice_timer_tools_resume_control .stButton > button:hover,
.st-key-practice_timer_resume_control .stButton > button:hover {
    background: #d1fae5;
    border-color: #34d399;
    color: #065f46;
}
.st-key-practice_timer_tools_pause_control .stButton > button,
.st-key-practice_timer_pause_control .stButton > button {
    background: #fff7ed;
    border-color: #fdba74;
    color: #c2410c;
}
.st-key-practice_timer_tools_pause_control .stButton > button:hover,
.st-key-practice_timer_pause_control .stButton > button:hover {
    background: #ffedd5;
    border-color: #fb923c;
    color: #9a3412;
}
.sf-timer-label-row {
    align-items: center;
    display: flex;
    gap: .75rem;
    justify-content: space-between;
}
.sf-timer-active-total {
    color: #047857;
    font-size: .82rem;
    font-weight: 800;
    text-align: right;
}
.sf-timer-label-row .sf-timer-label {
    margin-bottom: 0;
}
.sf-dashboard-summary {
    margin: 0;
}
.st-key-practice_dashboard_summary:hover {
    border-color: #93b4f5;
    box-shadow: 0 16px 34px rgba(30, 64, 175, .13);
    transform: translateY(-1px);
}
.sf-dashboard-heading {
    align-items: center;
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    margin: 0;
}
.sf-dashboard-eyebrow {
    color: #1d4ed8;
    font-size: .72rem;
    font-weight: 800;
    letter-spacing: .08em;
    margin: 0 0 .2rem;
    text-transform: uppercase;
}
.sf-dashboard-heading h2 {
    color: #0f172a;
    font-size: 1.35rem;
    margin: 0;
}
.st-key-drill_metric_cards [data-testid="stHorizontalBlock"] {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: .7rem;
}
.st-key-drill_metric_cards [data-testid="stColumn"] {
    width: 100%;
    min-width: 0;
}
.st-key-drill_metric_cards .stButton > button {
    background: rgba(255, 255, 255, .88);
    border: 1px solid #e2e8f0 !important;
    border-radius: 9px !important;
    width: 100%;
    min-height: 6rem !important;
    height: 6rem !important;
    padding: .72rem .8rem;
    justify-content: flex-start;
    text-align: left;
    color: #172033;
    transition: border-color .15s ease, box-shadow .15s ease;
}
.st-key-drill_metric_cards .stButton > button > div,
.st-key-drill_metric_cards .stButton > button > div > span,
.st-key-drill_metric_cards .stButton > button [data-testid="stMarkdownContainer"] { width: 100%; }
.st-key-drill_metric_cards .stButton > button p {
    color: #64748b;
    font-size: .67rem;
    font-weight: 800;
    letter-spacing: .05em;
    line-height: 1.2;
    margin: 0;
    text-transform: uppercase;
}
.st-key-drill_metric_cards .stButton > button p:has(strong) {
    margin-top: .28rem;
    color: #172033;
    font-size: 1.45rem;
    letter-spacing: normal;
    text-transform: none;
}
.st-key-drill_metric_cards .stButton > button p:has(em) {
    margin-top: .18rem;
    font-size: .68rem;
    font-weight: 400;
    letter-spacing: normal;
    text-transform: none;
}
.st-key-drill_metric_cards .stButton > button em { font-style: normal; }
[class*="sf-variance-positive"] .stButton > button { background: #ecfdf3; border-color: #86efac !important; }
[class*="sf-variance-warning"] .stButton > button { background: #fffbeb; border-color: #fcd34d !important; }
[class*="sf-variance-negative"] .stButton > button { background: #fef2f2; border-color: #fca5a5 !important; }
.st-key-drill_metric_cards [class*="sf-variance-positive"] button p:is(:has(strong), :has(em)) { color: #166534; }
.st-key-drill_metric_cards [class*="sf-variance-warning"] button p:is(:has(strong), :has(em)) { color: #92400e; }
.st-key-drill_metric_cards [class*="sf-variance-negative"] button p:is(:has(strong), :has(em)) { color: #991b1b; }
.st-key-drill_metric_cards .stButton > button:hover {
    border-color: #60a5fa !important;
    box-shadow: 0 2px 8px rgba(37, 99, 235, .15);
}
.st-key-drill_metric_cards .stButton > button:focus-visible {
    outline: 3px solid #93c5fd;
    outline-offset: 2px;
}
@media (max-width: 1100px) {
    .st-key-drill_metric_cards [data-testid="stHorizontalBlock"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
    .sf-dashboard-heading { align-items: flex-start; flex-direction: column; gap: .35rem; }
    .st-key-drill_metric_cards [data-testid="stHorizontalBlock"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
""",
        unsafe_allow_html=True,
    )


def _toggle_practice_dashboard() -> None:
    st.session_state[PRACTICE_DASHBOARD_OPEN_KEY] = not bool(
        st.session_state.get(PRACTICE_DASHBOARD_OPEN_KEY, False)
    )


def _render_practice_dashboard_strip(
    enrolled_course_ids: list[int],
) -> None:
    completed_from, completed_to, today = _today_bounds()
    today_explanations = get_new_question_explanations(user_id, completed_from, completed_to)
    today_answers = [
        answer for answer in get_answer_stats(
            user_id,
            course_ids=enrolled_course_ids,
            completed_from=completed_from,
            completed_to=completed_to,
            include_in_progress_practice=True,
            include_answer_details=True,
        )
        if answer.get("mode") == "practice"
    ]
    external_today = get_external_practice_entries(
        user_id,
        entry_from=today.isoformat(),
        entry_to=(today + timedelta(days=1)).isoformat(),
    )
    today_study_time = get_study_time_entries(
        user_id,
        entry_from=today.isoformat(),
        entry_to=(today + timedelta(days=1)).isoformat(),
        mode="practice",
    )

    today_active_seconds = sum(float(row["active_seconds"]) for row in today_study_time)

    app_correct = sum(1 for answer in today_answers if answer.get("is_correct"))
    app_total = len(today_answers)
    external_correct = sum(int(row["correct_count"]) for row in external_today)
    external_incorrect = sum(int(row["incorrect_count"]) for row in external_today)
    combined_correct = app_correct + external_correct
    combined_incorrect = (app_total - app_correct) + external_incorrect
    combined_total = combined_correct + combined_incorrect
    combined_accuracy = round(combined_correct / combined_total * 100) if combined_total else None
    dashboard_settings = get_all_settings(user_id)
    daily_target = _valid_int(
        dashboard_settings.get(PRACTICE_DAILY_TARGET_SETTING),
        30,
        1,
        1000,
    )
    variance = combined_total - daily_target
    if variance >= 0:
        variance_class = "sf-variance-positive"
        variance_note = "Target met"
    elif variance >= -5:
        variance_class = "sf-variance-warning"
        variance_note = "Nearly there"
    else:
        variance_class = "sf-variance-negative"
        variance_note = "Behind target"

    difficulty_results = {
        difficulty: {"Correct": 0, "Incorrect": 0, "Total": 0}
        for difficulty in DIFFICULTY_LABELS
    }
    for answer in today_answers:
        try:
            difficulty = int(answer.get("difficulty") or 3)
        except (TypeError, ValueError):
            difficulty = 3
        if difficulty in difficulty_results:
            bucket = difficulty_results[difficulty]
            result_key = "Correct" if answer.get("is_correct") else "Incorrect"
            bucket[result_key] += 1
            bucket["Total"] += 1

    dashboard_open = bool(st.session_state.get(PRACTICE_DASHBOARD_OPEN_KEY, False))
    _install_practice_dashboard_styles()
    with st.container(key="practice_dashboard_summary"):
        header_col, toggle_col = st.columns([20, 1], vertical_alignment="center")
        with header_col:
            st.markdown(
                f"""<div class="sf-dashboard-heading"><div><p class="sf-dashboard-eyebrow">Practice Dashboard · {_today_label(today).upper()}</p><h2>All practice today</h2></div></div>""",
                unsafe_allow_html=True,
            )
        with toggle_col:
            toggle_icon = "▲" if dashboard_open else "▼"
            toggle_help = "Close dashboard details" if dashboard_open else "Open dashboard details"
            # Older app versions used this widget key as state. Streamlit buttons
            # reject values assigned through session_state, so discard that stale
            # browser-session entry and use a dedicated button identity.
            st.session_state.pop("practice_dashboard_toggle", None)
            st.button(
                toggle_icon,
                key="practice_dashboard_toggle_button_v2",
                help=toggle_help,
                on_click=_toggle_practice_dashboard,
            )

        accuracy_label = f"{combined_accuracy}%" if combined_accuracy is not None else "—"
        variance_label = f"{variance:+d}"
        active_time_label = _format_active_time(today_active_seconds)
        card_values = [
            (str(combined_total), "All sources"),
            (str(combined_correct), "Questions"),
            (str(combined_incorrect), "Questions"),
            (f"{combined_total}/{daily_target}", f"{variance_label} · {variance_note}"),
            (accuracy_label, "All sources"),
            (active_time_label, "Timer running today"),
            (str(len(today_explanations)), "New submissions today"),
        ]
        values = dict(zip(METRICS, card_values))
        values["Days till exam"] = exam_countdown(get_exam_plan(user_id), today)
        metric_order = ("Days till exam", "Daily target", "Total questions", "Accuracy", "Active time", "Explanations", "Correct", "Incorrect")
        shown = visible_metrics(user_id, metric_order)
        with st.container(key="drill_metric_cards"):
            for index, (col, metric) in enumerate(zip(st.columns(len(shown)), shown) if shown else []):
                value, note = values[metric]
                with col:
                    card_style = variance_class if metric == "Daily target" else "neutral"
                    with st.container(key=f"drill_card_{index}_{card_style}"):
                        if metric == "Days till exam":
                            st.button(
                                f"{metric}\n\n**{value}**\n\n*{note}*",
                                key="drill_open_exam_countdown",
                                on_click=lambda: st.session_state.update(
                                    {PRACTICE_DASHBOARD_OPEN_KEY: True}
                                ),
                                use_container_width=True,
                            )
                        else:
                            st.button(
                                f"{metric}\n\n**{value}**\n\n*{note}*",
                                key=f"drill_open_{metric}",
                                on_click=open_report, args=(metric,),
                                use_container_width=True,
                            )
        if dashboard_open:
            render_metric_settings(user_id, metric_order)
            render_exam_settings(user_id, expanded=False)

    external_notice = st.session_state.pop("external_practice_saved_notice", None)
    if external_notice:
        st.success(external_notice)

    if dashboard_open:
        render_report(today_answers, external_today, today_study_time, daily_target, today,
                      explanations=today_explanations)
        st.markdown("##### Additional details and settings")
        breakdown_tab, time_tab, entry_tab, target_tab = st.tabs(
            ["Breakdown", "Study time", "External practice", "Daily target"]
        )

        with breakdown_tab:
            st.markdown("##### Questions by source")
            source_rows = [
                {
                    "Source": "StudyForge",
                    "Incorrect": app_total - app_correct,
                    "Correct": app_correct,
                    "Total": app_total,
                },
                *[
                    {
                        "Source": row["source"],
                        "Incorrect": int(row["incorrect_count"]),
                        "Correct": int(row["correct_count"]),
                        "Total": int(row["total_count"]),
                    }
                    for row in external_today
                ],
            ]
            st.dataframe(source_rows, hide_index=True, use_container_width=True)

            st.markdown("##### StudyForge questions by difficulty")
            short_labels = {
                1: "Intuition & Estimation",
                2: "Beginner",
                3: "Intermediate",
                4: "Advanced",
                5: "Stretch",
            }
            difficulty_rows = [
                {"Difficulty": short_labels[difficulty], **difficulty_results[difficulty]}
                for difficulty in DIFFICULTY_LABELS
            ]
            st.dataframe(difficulty_rows, hide_index=True, use_container_width=True)

        with time_tab:
            st.caption(
                "Active time counts only while the Practice Mode timer is running. "
                "Paused time is excluded."
            )
            recent_study_time = get_study_time_entries(
                user_id,
                entry_from=(today - timedelta(days=27)).isoformat(),
                entry_to=(today + timedelta(days=1)).isoformat(),
                course_ids=enrolled_course_ids,
                mode="practice",
            )
            if recent_study_time:
                st.dataframe(
                    [
                        {
                            "Date": date.fromisoformat(row["activity_date"]).strftime("%b %d, %Y"),
                            "Course": row["course_title"],
                            "Active time": _format_active_time(row["active_seconds"]),
                        }
                        for row in recent_study_time
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("Your active study-time trail will appear here once a timer runs.")

        with entry_tab:
            from src.provider_import_ui import render_provider_import
            render_provider_import(user_id)
            st.caption(
                "Enter totals from outside StudyForge. Saving the same source and date "
                "updates that row instead of creating a duplicate."
            )
            add_source_label = "Add another source…"
            source_options = [*get_external_practice_sources(user_id), add_source_label]
            selected_source = st.selectbox(
                "Source",
                source_options,
                key="external_practice_source",
                help="Choose Kaplan here so its name remains consistent every week.",
            )
            custom_source = ""
            if selected_source == add_source_label:
                custom_source = st.text_input(
                    "New source name",
                    key="external_practice_custom_source",
                )

            with st.form("external_practice_entry_form"):
                entry_date = st.date_input("Date", value=today)
                correct_input, incorrect_input = st.columns(2)
                correct_count = correct_input.number_input(
                    "Correct", min_value=0, step=1, value=0
                )
                incorrect_count = incorrect_input.number_input(
                    "Incorrect", min_value=0, step=1, value=0
                )
                save_external = st.form_submit_button(
                    "Save external practice", use_container_width=True
                )

            if save_external:
                source = custom_source if selected_source == add_source_label else selected_source
                if not str(source).strip():
                    st.error("Enter a source name.")
                elif int(correct_count) + int(incorrect_count) == 0:
                    st.error("Enter at least one correct or incorrect question.")
                else:
                    save_external_practice_entry(
                        user_id=user_id,
                        entry_date=entry_date.isoformat(),
                        source=source,
                        correct_count=int(correct_count),
                        incorrect_count=int(incorrect_count),
                    )
                    st.session_state["external_practice_saved_notice"] = (
                        f"External practice saved for {entry_date.strftime('%b %d')}."
                    )
                    st.rerun()

            recent_entries = get_external_practice_entries(
                user_id,
                entry_from=(today - timedelta(days=28)).isoformat(),
                entry_to=(today + timedelta(days=1)).isoformat(),
            )
            if recent_entries:
                st.markdown("##### Recent external practice")
                st.dataframe(
                    [
                        {
                            "Date": row["entry_date"],
                            "Source": row["source"],
                            "Incorrect": int(row["incorrect_count"]),
                            "Correct": int(row["correct_count"]),
                            "Total": int(row["total_count"]),
                        }
                        for row in recent_entries
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
                with st.expander("Edit or delete a saved entry"):
                    entries_by_id = {int(row["id"]): row for row in recent_entries}
                    selected_entry_id = st.selectbox(
                        "Saved entry",
                        list(entries_by_id),
                        format_func=lambda entry_id: (
                            f'{entries_by_id[entry_id]["entry_date"]} · '
                            f'{entries_by_id[entry_id]["source"]} · '
                            f'{int(entries_by_id[entry_id]["total_count"])} questions'
                        ),
                        key="external_practice_entry_to_edit",
                    )
                    selected_entry = entries_by_id[int(selected_entry_id)]
                    with st.form(f"edit_external_practice_{selected_entry_id}"):
                        edited_date = st.date_input(
                            "Date",
                            value=date.fromisoformat(selected_entry["entry_date"]),
                        )
                        edited_source = st.text_input(
                            "Source",
                            value=selected_entry["source"],
                        )
                        edited_correct_col, edited_incorrect_col = st.columns(2)
                        edited_correct = edited_correct_col.number_input(
                            "Correct",
                            min_value=0,
                            step=1,
                            value=int(selected_entry["correct_count"]),
                        )
                        edited_incorrect = edited_incorrect_col.number_input(
                            "Incorrect",
                            min_value=0,
                            step=1,
                            value=int(selected_entry["incorrect_count"]),
                        )
                        update_col, delete_col = st.columns(2)
                        update_entry = update_col.form_submit_button(
                            "Save changes",
                            use_container_width=True,
                        )
                        delete_entry = delete_col.form_submit_button(
                            "Delete entry",
                            use_container_width=True,
                        )

                    if update_entry:
                        try:
                            updated = update_external_practice_entry(
                                user_id=user_id,
                                entry_id=int(selected_entry_id),
                                entry_date=edited_date.isoformat(),
                                source=edited_source,
                                correct_count=int(edited_correct),
                                incorrect_count=int(edited_incorrect),
                            )
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            if updated:
                                st.session_state["external_practice_saved_notice"] = (
                                    f"External practice updated for {edited_date.strftime('%b %d')}."
                                )
                                st.rerun()
                            else:
                                st.error("That entry could not be found.")

                    if delete_entry:
                        deleted = delete_external_practice_entry(
                            user_id=user_id,
                            entry_id=int(selected_entry_id),
                        )
                        if deleted:
                            st.session_state.pop("external_practice_entry_to_edit", None)
                            st.session_state["external_practice_saved_notice"] = (
                                "External practice entry deleted."
                            )
                            st.rerun()
                        else:
                            st.error("That entry could not be found.")

        with target_tab:
            st.caption(
                "Set the daily question goal used to calculate variance. "
                "It stays in effect until you change it."
            )
            with st.form("practice_daily_target_form"):
                target_input = st.number_input(
                    "Daily question target",
                    min_value=1,
                    max_value=1000,
                    value=daily_target,
                    step=1,
                )
                save_target = st.form_submit_button(
                    "Save daily target", use_container_width=True
                )
            if save_target:
                set_setting(
                    user_id,
                    PRACTICE_DAILY_TARGET_SETTING,
                    str(int(target_input)),
                )
                st.session_state["external_practice_saved_notice"] = (
                    f"Daily target updated to {int(target_input)} questions."
                )
                st.rerun()


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
            difficulty: max(
                0,
                _valid_int(
                    raw.get(str(difficulty), raw.get(difficulty)),
                    0,
                    0,
                    2_147_483_647,
                ),
            )
            for difficulty in range(1, 6)
        }

    total = _valid_int(saved.get("n_questions"), 10, 1, 2_147_483_647)
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
    available_counts = st.session_state.get(
        PRACTICE_AVAILABLE_DIFFICULTY_COUNTS_KEY,
        {},
    )
    total_available = sum(
        max(0, int(available_counts.get(difficulty, 0)))
        for difficulty in range(1, 6)
    )
    bulk_count = _valid_int(
        st.session_state.get(PRACTICE_BULK_DIFFICULTY_COUNT_KEY),
        0,
        0,
        total_available,
    )
    for difficulty in range(1, 6):
        st.session_state[_difficulty_count_key(difficulty)] = min(
            bulk_count,
            max(0, int(available_counts.get(difficulty, 0))),
        )
    st.session_state[PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY] = bulk_count


def _available_difficulty_counts(
    course_ids: list[int],
    selected_modules: list[str],
    question_type: str,
) -> dict[int, int]:
    """Return the selectable bank size for each difficulty under the current filters."""
    module_filters = [
        module for module in selected_modules
        if module != MODULE_RANDOM
    ]
    # A random module has not been chosen yet, so expose the full filtered bank.
    # The eventual random-module selection still reports any module-level shortage.
    sections = [None] if MODULE_RANDOM in selected_modules or not module_filters else module_filters
    counts = {}
    for difficulty in range(1, 6):
        question_ids = set()
        anonymous_count = 0
        for section_type in sections:
            for course_id in course_ids:
                for question in get_all_questions(
                    section_type=section_type,
                    question_type=None if question_type == "All" else question_type,
                    min_difficulty=difficulty,
                    max_difficulty=difficulty,
                    course_id=course_id,
                ):
                    question_id = question.get("id")
                    if question_id is None:
                        anonymous_count += 1
                    else:
                        question_ids.add(question_id)
        counts[difficulty] = len(question_ids) + anonymous_count
    return counts


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


def _live_practice_score(
    questions: list[dict],
    answers: dict,
    self_grades: dict,
) -> tuple[int, int, int]:
    """Return correct, graded, and answered counts for the active session."""
    correct = 0
    graded = 0
    answered = 0
    for idx, question in enumerate(questions):
        if not _dict_has_idx(answers, idx):
            continue
        answered += 1
        if is_open_ended_question(question):
            if not _dict_has_idx(self_grades, idx):
                continue
            is_correct = bool(_dict_get_idx(self_grades, idx, False))
        else:
            selected = str(_dict_get_idx(answers, idx, "") or "").upper()
            expected = str(question.get("correct_answer") or "").upper()
            is_correct = bool(selected) and selected == expected
        graded += 1
        correct += int(is_correct)
    return correct, graded, answered


def _persist_scored_practice_answer(
    user_id: int,
    idx: int,
    question: dict,
    *,
    time_spent: float = 0.0,
) -> bool:
    """Save one answer as soon as it can be scored, without ending the session."""
    attempt_id = _st("attempt_id")
    answers = _st("answers") or {}
    self_grades = _st("self_grades") or {}
    if not attempt_id or not _dict_has_idx(answers, idx):
        return False

    selected = str(_dict_get_idx(answers, idx, "") or "")
    if is_open_ended_question(question):
        if not _dict_has_idx(self_grades, idx):
            return False
        is_correct = bool(selected.strip()) and bool(_dict_get_idx(self_grades, idx, False))
    else:
        is_correct = selected.upper() == str(question.get("correct_answer") or "").upper()

    inserted = save_answer(
        attempt_id=attempt_id,
        question_id=question["id"],
        selected=selected,
        is_correct=is_correct,
        time_spent=max(0.0, float(time_spent)),
        is_flagged=idx in (_st("flagged") or set()),
        section_num=_st("section_num") or 1,
    )
    if inserted and selected and not is_correct:
        add_to_journal(user_id, question["id"], attempt_id)
    return inserted


def _persist_restored_practice_answers(user_id: int) -> int:
    """Backfill answers from drafts created before per-question saving existed."""
    if not is_active() or _st("mode") != "practice":
        return 0
    questions = _st("questions") or []
    answers = _st("answers") or {}
    inserted = 0
    for idx, question in enumerate(questions):
        if _dict_has_idx(answers, idx):
            inserted += int(_persist_scored_practice_answer(user_id, idx, question))
    return inserted


def _practice_pool() -> list[dict]:
    return replacement_pool(
        current_question() or {}, {course["id"] for course in enrolled_courses}
    )


def _swap_current_question() -> bool:
    questions = _st("questions") or []
    current_idx = _st("current_idx") or 0
    if not questions or not (0 <= current_idx < len(questions)):
        return False
    if (
        current_idx + 1 < len(questions)
        and references_previous_question(questions[current_idx + 1])
    ):
        # Replacing this item would silently break the next question's context.
        return False

    initialize_edit_state(st.session_state)
    used_ids = st.session_state[HISTORY_KEY]
    original = questions[current_idx]
    candidates, scope = closest_replacements(original, _practice_pool(), used_ids)
    if not candidates:
        return False

    replacement = random.choice(candidates)
    if original.get("_force_open_ended"):
        replacement = _open_ended_question_copy(replacement)
    remove_saved_answer(user_id, _st('attempt_id'), original['id'])
    st.session_state[HISTORY_KEY].add(replacement['id'])
    questions[current_idx] = replacement
    st.session_state[PRACTICE_NOTICE_KEY] = (
        f"Question switched out from the {scope}. This slot now has a fresh unanswered question."
    )
    _set("questions", questions)

    answers = _st("answers") or {}
    _dict_pop_idx(answers, current_idx)
    _set("answers", answers)
    self_grades = _st("self_grades") or {}
    _dict_pop_idx(self_grades, current_idx)
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
    _set('q_start_time', time.time())
    _start_practice_question_clock()
    persist_current_exam(user_id)
    return True


def _render_session_question_editor() -> None:
    st.markdown('**Add or remove questions**')
    st.caption('Add questions from this session’s original modules or chapters. Questions already used, switched out, or removed are excluded.')
    scopes = st.session_state[SCOPE_KEY]
    allowed_courses = {course['id'] for course in enrolled_courses}
    pool = practice_questions(sorted({scope[0] for scope in scopes if scope[0] in allowed_courses}))
    difficulty = st.selectbox('Difficulty of added questions', list(DIFFICULTY_LABELS),
                             format_func=lambda d: DIFFICULTY_LABELS[d], key='practice_add_difficulty')
    candidates = addition_candidates(st.session_state, pool, difficulty)
    st.caption(f'{len(candidates)} unused questions available at this difficulty.')
    count = int(st.number_input('Questions to add', min_value=1, max_value=500, value=1,
                               step=1, key='practice_add_count'))
    if st.button('Add questions', use_container_width=True, disabled=not candidates):
        if count > len(candidates):
            st.warning(f'Only {len(candidates)} matching questions are available. Lower the count or choose another difficulty.')
        else:
            added = random.sample(candidates, count)
            if (current_question() or {}).get('_force_open_ended'):
                added = [_open_ended_question_copy(q) for q in added]
            _set('questions', [*(_st('questions') or []), *added])
            st.session_state[HISTORY_KEY].update(q['id'] for q in added)
            st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
            st.session_state[PRACTICE_NOTICE_KEY] = f'Added {count} questions at the end of the session. Your existing answers are saved.'
            persist_current_exam(user_id)
            st.rerun()
    questions = _st('questions') or []
    idx = _st('current_idx') or 0
    error = removal_error(questions, idx)
    st.caption('Remove the question currently on screen and its score from this session.')
    if st.button('Remove current question', use_container_width=True, disabled=bool(error),
                 help=error or 'Other questions and their answers stay in the session.'):
        remove_saved_answer(user_id, _st('attempt_id'), questions[idx]['id'])
        remove_question_state(st.session_state, idx)
        _set('q_start_time', time.time())
        _start_practice_question_clock()
        st.session_state[PRACTICE_NOTICE_KEY] = f'Removed question {idx + 1}. This session now has {len(questions) - 1} questions.'
        persist_current_exam(user_id)
        st.rerun()


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


def _practice_activity_course() -> tuple[int | None, str]:
    question = current_question() or {}
    course_id = question.get("course_id") or _st("course_id")
    course_title = str(question.get("course_title") or "this course")
    try:
        return int(course_id), course_title
    except (TypeError, ValueError):
        return None, course_title


def _reset_practice_activity_heartbeat() -> None:
    now = time.time()
    st.session_state[PRACTICE_TIMER_ACTIVITY_LAST_TICK_KEY] = now
    st.session_state[PRACTICE_TIMER_ACTIVITY_REMAINING_KEY] = _practice_timer_remaining()


def _record_practice_active_time() -> float:
    """Persist timer-running time since the prior live heartbeat."""
    if (
        not is_active()
        or _st("mode") != "practice"
        or not st.session_state.get(PRACTICE_TIMER_ENABLED_KEY)
        or st.session_state.get(PRACTICE_TIMER_PAUSED_KEY)
    ):
        return 0.0

    now = time.time()
    remaining = _practice_timer_remaining()
    last_tick = st.session_state.get(PRACTICE_TIMER_ACTIVITY_LAST_TICK_KEY)
    remaining_at_tick = st.session_state.get(PRACTICE_TIMER_ACTIVITY_REMAINING_KEY)
    st.session_state[PRACTICE_TIMER_ACTIVITY_LAST_TICK_KEY] = now
    st.session_state[PRACTICE_TIMER_ACTIVITY_REMAINING_KEY] = remaining
    if last_tick is None or remaining_at_tick is None:
        return 0.0

    elapsed = max(0.0, now - float(last_tick))
    # Never count beyond the point at which the question timer reached zero.
    elapsed = min(elapsed, max(0.0, float(remaining_at_tick)))
    course_id, _ = _practice_activity_course()
    attempt_id = _st("attempt_id")
    if elapsed <= 0 or course_id is None or not attempt_id:
        return 0.0

    add_study_time(
        user_id=user_id,
        attempt_id=int(attempt_id),
        course_id=course_id,
        active_seconds=elapsed,
        activity_date=date.today().isoformat(),
        mode="practice",
    )
    return elapsed


def _pause_practice_timer() -> None:
    if not st.session_state.get(PRACTICE_TIMER_ENABLED_KEY):
        return
    _record_practice_active_time()
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
    _reset_practice_activity_heartbeat()
    _sync_practice_timer_to_exam_state()
    persist_current_exam(user_id)


def _set_practice_timer_visibility(visible: bool) -> None:
    st.session_state[PRACTICE_TIMER_VISIBLE_KEY] = bool(visible)
    _sync_practice_timer_to_exam_state()
    persist_current_exam(user_id)


def _set_practice_timer_paused(paused: bool) -> None:
    # Apply the state represented by the clicked label instead of toggling the
    # latest value. This is deterministic even if a background rerun completed
    # between the button being drawn and the click arriving.
    if paused:
        _pause_practice_timer()
    else:
        _resume_practice_timer()


def _render_practice_timer(
    seconds: float,
    total_seconds: float,
    key_prefix: str,
    *,
    today_active_seconds: float = 0.0,
    course_title: str = "this course",
) -> None:
    shortcut_script = (Path(__file__).resolve().parents[1] / "src/practice_timer_shortcut.js").read_text(encoding="utf-8")
    components.html(f"<script>{shortcut_script}</script>", height=0)
    visible = bool(st.session_state.get(PRACTICE_TIMER_VISIBLE_KEY, True))
    paused = bool(st.session_state.get(PRACTICE_TIMER_PAUSED_KEY))
    pct = max(0.0, min(1.0, seconds / total_seconds)) if total_seconds else 0
    m, s = divmod(int(seconds), 60)

    if visible:
        suffix = "paused" if paused else "remaining"
        timer_col, control_col = st.columns([1, 0.075], vertical_alignment="center")
        with timer_col:
            st.markdown(
                '<div class="sf-timer-card"><div class="sf-timer-label-row">'
                f'<div class="sf-timer-label">{m:02d}:{s:02d} {suffix}</div>'
                f'<div class="sf-timer-active-total">Today · {_format_active_time(today_active_seconds, include_seconds=True)} active<br>'
                f'<span>{escape(course_title)}</span></div></div></div>',
                unsafe_allow_html=True,
            )
        with control_col:
            if _render_practice_pause_button(key_prefix):
                # Keep the duplicate control in Practice tools in sync too.
                st.rerun(scope="app")
        st.progress(pct)
    else:
        st.caption("Timer hidden. Open Practice tools to show it again.")


def _render_practice_pause_button(key_prefix: str) -> bool:
    paused = bool(st.session_state.get(PRACTICE_TIMER_PAUSED_KEY))
    control_state = "resume" if paused else "pause"
    with st.container(key=f"{key_prefix}_{control_state}_control"):
        return st.button(
            "▶" if paused else "❚❚",
            key=f"{key_prefix}_pause",
            help="Resume timer (Pause/Break key)" if paused else "Pause timer (Pause/Break key)",
            on_click=_set_practice_timer_paused,
            args=(not paused,),
        )


def _render_practice_timer_controls(key_prefix: str) -> None:
    visible = bool(st.session_state.get(PRACTICE_TIMER_VISIBLE_KEY, True))
    show_col, pause_col = st.columns([1, 0.28], vertical_alignment="center")
    with show_col:
        show_label = "Hide" if visible else "Show"
        st.button(
            show_label,
            key=f"{key_prefix}_show",
            use_container_width=True,
            on_click=_set_practice_timer_visibility,
            args=(not visible,),
        )
    with pause_col:
        _render_practice_pause_button(key_prefix)


@st.fragment(run_every=1.0)
def _render_practice_timer_fragment(
    current_idx: int,
    q: dict,
    question_time_limit: int,
) -> None:
    """Update the countdown without rerunning and closing the rest of the page."""
    answers = _st("answers") or {}
    current_answered = _dict_has_idx(answers, current_idx)
    _record_practice_active_time()
    remaining = _practice_timer_remaining()
    _sync_practice_timer_to_exam_state()
    if (
        not current_answered
        and not st.session_state.get(PRACTICE_TIMER_PAUSED_KEY)
        and remaining <= 0
    ):
        _mark_current_question_timed_out(current_idx, q)
        st.rerun(scope="app")
    course_id, course_title = _practice_activity_course()
    today_active_seconds = get_study_time_total(
        user_id,
        entry_from=date.today().isoformat(),
        entry_to=(date.today() + timedelta(days=1)).isoformat(),
        course_id=course_id,
        mode="practice",
    )
    _render_practice_timer(
        remaining,
        question_time_limit,
        key_prefix="practice_timer",
        today_active_seconds=today_active_seconds,
        course_title=course_title,
    )


def _start_practice_question_clock() -> None:
    if st.session_state.get(PRACTICE_TIMER_ENABLED_KEY):
        _record_practice_active_time()
        seconds = _practice_question_time_limit()
        st.session_state[PRACTICE_TIMER_REMAINING_KEY] = float(seconds)
        st.session_state[PRACTICE_TIMER_LAST_STARTED_KEY] = time.time()
        st.session_state[PRACTICE_TIMER_PAUSED_KEY] = False
        st.session_state[PRACTICE_TIMER_VISIBLE_KEY] = True
        st.session_state[PRACTICE_TIMER_CURRENT_IDX_KEY] = _st("current_idx") or 0
        _sync_practice_timer_to_exam_state()
        _reset_practice_activity_heartbeat()


def _apply_active_question_timer_settings(
    enabled: bool,
    seconds: int,
    save_as_default: bool,
) -> None:
    seconds = _valid_int(seconds, PRACTICE_DEFAULT_TIMER_SECONDS, 15, 600)
    _record_practice_active_time()
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
    # Widget values otherwise disappear when their question leaves the screen.
    drafts = st.session_state.setdefault("practice_swipe_drafts", {})
    old_idx = _st("current_idx")
    for prefix in ("q_radio_", "q_open_ended_"):
        old_key = f"{prefix}{old_idx}"
        if old_key in st.session_state:
            drafts[old_key] = st.session_state[old_key]
        new_key = f"{prefix}{idx}"
        if new_key in drafts:
            st.session_state[new_key] = drafts[new_key]
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


def _jump_to_practice_question_from_tools() -> None:
    target = int(st.session_state.get("practice_tools_jump", 1)) - 1
    _go_to_practice_question(target)


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
    _persist_scored_practice_answer(user_id, current_idx, q, time_spent=time_on_current_question())
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
    _persist_scored_practice_answer(user_id, current_idx, q, time_spent=time_on_current_question())
    skipped_questions = st.session_state.get(PRACTICE_SKIPPED_QUESTIONS_KEY, set())
    skipped_questions.add(current_idx)
    st.session_state[PRACTICE_SKIPPED_QUESTIONS_KEY] = skipped_questions
    _open_answer_review_for_question(current_idx)
    _pause_practice_timer()
    st.session_state[PRACTICE_SKIPPED_NOTICE_KEY] = current_idx

def _sync_practice_pdf() -> None:
    """Recover an outdated PDF link after a swap, including restored sessions."""
    from src.offline_exams import exam_for_attempt
    if not is_active() or not _st('attempt_id'):
        return
    linked = exam_for_attempt(user_id, _st('attempt_id'))
    if not linked:
        return
    questions = _st('questions') or []
    if [q.get('id') for q in questions] == [q.get('id') for q in json.loads(linked['questions_json'])]:
        return
    persist_current_exam(user_id)
    st.session_state[PRACTICE_PDF_KEY] = export_offline_exam(
        user_id=user_id, attempt_id=_st('attempt_id'),
        questions=questions, title=linked['title'], replace_changed_questions=True,
    )


def _render_pdf_download(label: str = "Download Practice PDF") -> None:
    pdf_bytes = st.session_state.get(PRACTICE_PDF_KEY)
    from src.offline_exams import exam_for_attempt, progress_pdf
    linked = exam_for_attempt(user_id, _st('attempt_id')) if _st('attempt_id') else None
    if linked and is_active():
        persist_current_exam(user_id)
        pdf_bytes = progress_pdf(user_id, linked['serial'])
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
settings = get_all_settings(user_id)
swipe_mode = st.session_state.get("swipe_mode_toggle", settings.get("practice_swipe_mode", "false") == "true")
username = st.session_state.get("username", "")
sidebar_nav(username)
real_admin, admin = get_effective_admin(user_id)
if _persist_restored_practice_answers(user_id):
    # Refresh once so the dashboard immediately reflects legacy queued answers.
    st.rerun()

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
_render_practice_dashboard_strip(
    enrolled_course_ids=list(course_titles.keys()),
)

if is_active():
    initialize_edit_state(st.session_state)
_sync_practice_pdf()

if swipe_mode:
    st.subheader("Practice")
else:
    page_header("✏️ Practice Mode", "Drill questions at your own pace")
    render_offline_exams(user_id, preferred_course_id=active_course_id)

if st.session_state.pop("_exam_restored_notice", False):
    st.success("Your in-progress practice session was restored right where you left off.")

if st.session_state.pop("_exam_exit_notice", False):
    st.success("Practice session saved. Resume it below or start another one.")

if st.session_state.pop("_practice_discard_notice", False):
    st.success("Practice session discarded.")

daily_rollover = st.session_state.pop("_practice_daily_rollover", [])
if daily_rollover:
    rollover_questions = sum(int(row.get("total") or 0) for row in daily_rollover)
    rollover_sessions = len(daily_rollover)
    st.info(
        f"Daily reset complete: {rollover_questions} reached question(s) from "
        f"{rollover_sessions} previous-day session(s) were automatically finished "
        "and scored. Today's board starts fresh."
    )

swipe_mode = st.toggle(
    "Swipe mode · mobile preview",
    value=settings.get("practice_swipe_mode", "false") == "true",
    key="swipe_mode_toggle",
    help="A phone-width question card. Swipe left to move on, right to go back. Tap answers as usual.",
)
if swipe_mode != (settings.get("practice_swipe_mode", "false") == "true"):
    set_setting(user_id, "practice_swipe_mode", "true" if swipe_mode else "false")
if swipe_mode:
    install_swipe_view()
hard_mode = settings.get("hard_mode", "false") == "true"
show_exp  = settings.get("show_explanations", "always")
auto_submit_answers = settings.get("auto_submit_answers", "false") == "true"
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
    saved_sessions = get_exam_drafts(user_id, modes={"practice"})
    if saved_sessions:
        st.subheader("Practice sessions in progress")
        st.caption("Resume or discard a saved session, or create another session below.")
        st.markdown(
            """
            <style>
            [class*="st-key-discard_practice_"] button {
                background: #b91c1c !important;
                border-color: #b91c1c !important;
                color: #ffffff !important;
            }
            [class*="st-key-discard_practice_"] button p {
                color: #ffffff !important;
            }
            [class*="st-key-discard_practice_"] button:hover {
                background: #991b1b !important;
                border-color: #991b1b !important;
            }
            [class*="st-key-discard_practice_"] button:focus-visible {
                outline: 2px solid #b91c1c !important;
                outline-offset: 3px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        for draft in saved_sessions:
            state = draft.get("state") or {}
            label = state.get(PRACTICE_SESSION_LABEL_KEY) or "Practice Session"
            questions = state.get(_K["questions"]) or []
            answers = state.get(_K["answers"]) or {}
            info_col, pdf_col, resume_col, discard_col = st.columns([3, 1, 1, 0.7])
            from src.offline_exams import exam_for_attempt, progress_pdf
            from src.pdf_export import display_exam_number
            saved_pdf_exam = exam_for_attempt(user_id, draft['attempt_id'])
            if saved_pdf_exam:
                try:
                    pdf_col.download_button(
                        'Download / print PDF',
                        progress_pdf(user_id, saved_pdf_exam['serial']),
                        file_name=f"{display_exam_number(saved_pdf_exam['serial'])}.pdf",
                        mime='application/pdf',
                        key=f"draft_pdf_{draft['attempt_id']}",
                        use_container_width=True,
                    )
                except ValueError as exc:
                    pdf_col.caption(str(exc))
            info_col.markdown(
                f"**{label}**  \n"
                f"{len(answers)}/{len(questions)} answered · saved {draft.get('updated_at', '')}"
            )
            if resume_col.button(
                "Resume",
                key=f"resume_practice_{draft['attempt_id']}",
                use_container_width=True,
            ):
                if restore_exam_draft(
                    user_id,
                    modes={"practice"},
                    attempt_id=int(draft["attempt_id"]),
                ):
                    st.rerun()
                st.error("That practice session is no longer available to resume.")
            if discard_col.button(
                "Discard",
                key=f"discard_practice_{draft['attempt_id']}",
                help="Discard this saved practice session without submitting it.",
                use_container_width=True,
            ):
                delete_exam_draft(int(draft["attempt_id"]))
                st.session_state["_practice_discard_notice"] = True
                st.rerun()
        st.divider()

    st.subheader("Set Up Your Practice Exam")
    content_modes = ["Courses", "Curriculum", "Mock Review"]
    if st.session_state.get(CONTENT_MODE_SETTING) not in content_modes:
        saved_mode = settings.get(CONTENT_MODE_SETTING, "Courses")
        st.session_state[CONTENT_MODE_SETTING] = saved_mode if saved_mode in content_modes else "Courses"
    source_mode = st.radio("Choose exam content by", content_modes, horizontal=True,
                           key=CONTENT_MODE_SETTING)
    if source_mode != settings.get(CONTENT_MODE_SETTING, "Courses"):
        set_setting(user_id, CONTENT_MODE_SETTING, source_mode)
    review_focus = render_review_focus(user_id, settings) if source_mode == "Mock Review" else None
    eligible_course_ids = list(course_titles)
    curriculum_id = None
    if source_mode == "Curriculum":
        curriculums = get_all_curriculums()
        curriculum_titles = {c['id']: c['title'] for c in curriculums}
        curriculum_id = st.selectbox(
            "Curriculum", list(curriculum_titles),
            format_func=lambda cid: curriculum_titles[cid],
        )
        eligible_course_ids = [
            c['id'] for c in (get_curriculum_courses(curriculum_id) if curriculum_id else [])
            if c['id'] in course_titles
        ]
        if not eligible_course_ids:
            st.info("No enrolled courses are available in this curriculum.")

    if review_focus is not None:
        review_course_ids = {topic["course_id"] for topic in review_focus["topics"]}
        eligible_course_ids = [cid for cid in course_titles if cid in review_course_ids]
        if review_course_ids - set(course_titles):
            st.warning("Some review courses are not enrolled. Enroll in those courses to include their questions.")

    source_signature = review_focus["signature"] if review_focus is not None else (source_mode, curriculum_id)
    review_focus_changed = (review_focus is not None
                            and st.session_state.get("practice_content_source") != source_signature)

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
    if st.session_state.get("practice_content_source") != source_signature:
        if source_mode in ("Curriculum", "Mock Review"):
            st.session_state["practice_course_ids"] = eligible_course_ids
        st.session_state["practice_content_source"] = source_signature
    st.session_state["practice_course_ids"] = [
        cid for cid in st.session_state["practice_course_ids"] if cid in eligible_course_ids
    ]

    from src.study_progress import load_progress, status, label as progress_label, render_progress, render_selector_colors
    render_selector_colors()
    course_progress = load_progress(user_id, settings, review_focus["id"] if review_focus else None)
    selected_course_ids = st.multiselect(
        "Courses",
        options=eligible_course_ids,
        format_func=lambda cid: progress_label(f"{course_titles[cid]} ({course_counts.get(cid, 0)} Q)", status(course_progress, [cid]), course_progress["window"]),
        help="Type to search, then select one or more courses for this practice session.",
        key="practice_course_ids",
    )

    selected_course_ids = [cid for cid in selected_course_ids if cid in course_titles]
    setup_questions = practice_questions(selected_course_ids)
    if review_focus is not None:
        missing_topics = [topic["name"] for topic in review_focus["topics"]
                          if topic["course_id"] in selected_course_ids
                          and not any(matches_review_topic(q, topic) for q in setup_questions)]
        setup_questions = filter_review_questions(setup_questions, review_focus["topics"])
        if missing_topics:
            with st.expander(f"Review topics without practice questions ({len(missing_topics)})"):
                st.write("These topics remain in your review plan. Add matching questions to practice them here.")
                for topic_name in missing_topics:
                    st.write(f"• {topic_name}")
    from src.question_lenses import get_lenses, question_lens
    LENSES = get_lenses()
    if 'practice_question_lens' not in st.session_state:
        saved_lens = last_practice_settings.get('question_lens', settings.get(PROFESSIONAL_SPECIALTY_SETTING, 'all'))
        st.session_state['practice_question_lens'] = saved_lens if saved_lens in LENSES or saved_lens == 'all' else 'all'
    elif st.session_state['practice_question_lens'] not in ['all', *LENSES]:
        st.session_state['practice_question_lens'] = 'all'
    selected_question_lens = st.selectbox("Question lens", ["all", *LENSES],
        format_func=lambda value: "All lenses" if value == "all" else LENSES[value],
        key="practice_question_lens", help="Filter by the lens assigned during question import.")
    if selected_question_lens != "all":
        setup_questions = [q for q in setup_questions if question_lens(q) == selected_question_lens]

    course_modules = sorted({module_label(q) for q in setup_questions if module_label(q)}, key=_natural_sort_key)
    course_qtypes = sorted({q['question_type'] for q in setup_questions if q.get('question_type')})

    module_progress = course_progress
    module_status = {module: status(module_progress, selected_course_ids, module) for module in course_modules}
    module_opts = course_modules
    qtype_opts = ["All"] + course_qtypes
    review_module_signature = (source_signature, tuple(selected_course_ids), selected_question_lens)
    if review_focus is not None and (
        review_focus_changed or st.session_state.get("practice_review_module_signature") != review_module_signature
    ):
        st.session_state[PRACTICE_MODULES_KEY] = list(module_opts)
        st.session_state[PRACTICE_QTYPE_KEY] = "All"
    st.session_state["practice_review_module_signature"] = review_module_signature
    if review_focus is not None and selected_course_ids and not setup_questions and review_focus["topics"]:
        st.info("No practice questions match this review and question lens. Try All lenses or add questions for these modules.")

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
            last_practice_settings.get("bulk_difficulty_count"),
            0,
            0,
            2_147_483_647,
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
        ) or list(module_opts)
    else:
        st.session_state[PRACTICE_MODULES_KEY] = [
            module for module in st.session_state[PRACTICE_MODULES_KEY]
            if module in module_opts
        ]
    selected_specialty = selected_question_lens if selected_question_lens != 'all' else DEFAULT_SPECIALTY
    st.session_state[PRACTICE_SPECIALTY_KEY] = selected_specialty

    with st.container(border=True):
        st.caption(f"Question lens: {LENSES.get(selected_question_lens, 'All lenses')} · {len(setup_questions):,} questions available before module and difficulty filters.")
        from src.practice_module_selector import render_module_selector
        module_titles = {module: ", ".join(course_titles[cid] for cid in selected_course_ids
                          if any(q["course_id"] == cid and module_label(q) == module for q in setup_questions))
                          + " / " + module for module in module_opts}
        selected_modules = render_module_selector(module_opts, module_titles, module_status,
                                                  module_progress, key=PRACTICE_MODULES_KEY)
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
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

        filtered_questions = [q for q in setup_questions
                              if module_label(q) in selected_modules
                              and (qtype_filter == 'All' or q.get('question_type') == qtype_filter)]
        available_difficulty_counts = {
            d: sum(int(q['difficulty']) == d for q in filtered_questions) for d in range(1, 6)
        }
        total_available_questions = sum(available_difficulty_counts.values())
        st.session_state[PRACTICE_AVAILABLE_DIFFICULTY_COUNTS_KEY] = (
            available_difficulty_counts
        )

        # Filter changes can lower a widget's maximum. Normalize persisted widget
        # values before rendering so Streamlit never receives an out-of-range value.
        st.session_state[PRACTICE_BULK_DIFFICULTY_COUNT_KEY] = _valid_int(
            st.session_state.get(PRACTICE_BULK_DIFFICULTY_COUNT_KEY),
            0,
            0,
            total_available_questions,
        )
        for difficulty, available_count in available_difficulty_counts.items():
            difficulty_key = _difficulty_count_key(difficulty)
            st.session_state[difficulty_key] = _valid_int(
                st.session_state.get(difficulty_key),
                0,
                0,
                available_count,
            )

        with col2:
            st.markdown("##### Questions by Difficulty")
            st.number_input(
                "Set all difficulties to",
                min_value=0,
                max_value=total_available_questions,
                key=PRACTICE_BULK_DIFFICULTY_COUNT_KEY,
                on_change=_apply_bulk_difficulty_count,
                help=(
                    "Enter a high value to select every matching question. Each "
                    "difficulty is automatically capped at its available bank count."
                ),
            )
            current_bulk_count = _valid_int(
                st.session_state.get(PRACTICE_BULK_DIFFICULTY_COUNT_KEY),
                0,
                0,
                total_available_questions,
            )
            if current_bulk_count != st.session_state.get(
                PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY
            ):
                for difficulty in range(1, 6):
                    st.session_state[_difficulty_count_key(difficulty)] = min(
                        current_bulk_count,
                        available_difficulty_counts[difficulty],
                    )
                st.session_state[
                    PRACTICE_LAST_APPLIED_BULK_DIFFICULTY_COUNT_KEY
                ] = current_bulk_count
            difficulty_counts = {}
            for difficulty in range(1, 6):
                available_count = available_difficulty_counts[difficulty]
                if not available_count:
                    difficulty_counts[difficulty] = 0
                    continue
                difficulty_counts[difficulty] = st.number_input(
                    (
                        f"{difficulty} - {DIFFICULTY_LABELS.get(difficulty, difficulty)} "
                        f"({available_count} available)"
                    ),
                    min_value=0,
                    max_value=available_count,
                    key=_difficulty_count_key(difficulty),
                )
            n_questions = sum(int(count) for count in difficulty_counts.values())
            st.caption(
                f"Total selected: {n_questions} of {total_available_questions} "
                "available questions"
            )
            if not total_available_questions:
                st.info("No questions match these filters. Select courses or adjust the filters.")

        allocation_enabled = st.toggle("Allocate questions by course and module / chapter")
        group_counts = {}
        allocation_error = None
        if allocation_enabled and selected_course_ids:
            st.markdown("##### Question allocation")
            st.caption("Course percentages total 100%. Module / chapter percentages total 100% within each course. Counts are rounded to whole questions.")
            allocation_config = editor_config(
                selected_course_ids, course_titles, filtered_questions, n_questions,
            )
            group_counts, allocation_error = render_allocation_editor(
                allocation_config, filtered_questions, difficulty_counts,
            )

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
            available_levels = [d for d, count in available_difficulty_counts.items() if count]
            mode_cols = st.columns(max(1, len(available_levels)))
            for difficulty, mode_col in zip(available_levels, mode_cols):
                with mode_col:
                    difficulty_modes[difficulty] = st.selectbox(
                        f"Level {difficulty}",
                        QUESTION_MODE_OPTIONS,
                        key=_difficulty_mode_key(difficulty),
                        help=DIFFICULTY_LABELS.get(difficulty, ""),
                    )
        take_home_exam = False
        use_timer = False
        timer_secs = None
        submitted = st.button("Start Practice Exam", use_container_width=True,
                              disabled=n_questions <= 0)

    if submitted:
        if allocation_error:
            st.error(allocation_error)
            st.stop()
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
            "mock_review_schedule_id": review_focus["id"] if review_focus is not None else None,
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
            "professional_specialty": normalize_specialty(selected_specialty),
            "question_lens": selected_question_lens,
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
        for question in filtered_questions:
            difficulty = int(question['difficulty'])
            if difficulty in pool_by_difficulty:
                pool_by_difficulty[difficulty].append(question)

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
        planned_buckets = None
        if allocation_enabled:
            try:
                planned_buckets = allocation_plan(pool, group_counts, requested_difficulty_counts)
            except ValueError as exc:
                st.error(str(exc))
                st.stop()
        for difficulty, requested_count in requested_difficulty_counts.items():
            difficulty_pool = pool_by_difficulty[difficulty]
            if planned_buckets is not None:
                for (group, level), count in planned_buckets.items():
                    if level != difficulty or not count:
                        continue
                    candidates = [q for q in difficulty_pool if question_group(q) == group]
                    questions.extend(
                        get_smart_review_questions(user_id, candidates, n=count, course_id=group[0])
                        if use_weakness else random.sample(candidates, count)
                    )
                replacement_pool.extend(difficulty_pool)
                continue
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

        questions = arrange_question_dependencies(
            questions,
            pool,
            target_count=len(questions),
        )
        if allocation_enabled:
            from collections import Counter
            actual_groups = Counter(question_group(q) for q in questions)
            actual_difficulties = Counter(int(q['difficulty']) for q in questions)
            if (any(actual_groups[g] != count for g, count in group_counts.items())
                    or actual_difficulties != Counter(requested_difficulty_counts)):
                st.error("Linked questions could not fit this allocation. Adjust the counts or filters and try again.")
                st.stop()

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
        st.session_state.pop(PRACTICE_TIMER_ACTIVITY_LAST_TICK_KEY, None)
        st.session_state.pop(PRACTICE_TIMER_ACTIVITY_REMAINING_KEY, None)
        st.session_state[PRACTICE_TIMED_OUT_QUESTIONS_KEY] = set()
        st.session_state[PRACTICE_SKIPPED_QUESTIONS_KEY] = set()
        st.session_state.pop("practice_swipe_drafts", None)
        st.session_state[PRACTICE_EXPANDED_ANSWER_KEY] = set()
        st.session_state[PRACTICE_REACHED_QUESTIONS_KEY] = {0}
        st.session_state.pop(PRACTICE_TIMEOUT_NOTICE_KEY, None)
        st.session_state.pop(PRACTICE_SKIPPED_NOTICE_KEY, None)
        section_label = (
            selected_module
            if random_module
            else (", ".join(selected_module_filters) if selected_module_filters else "All Modules / Chapters")
        )
        practice_label = f"Practice Session: {section_label}"
        st.session_state[PRACTICE_SESSION_LABEL_KEY] = practice_label
        specialty_name = specialty_label(selected_specialty)
        pdf_subtitle = (
            "Generated practice test"
            if normalize_specialty(selected_specialty) == DEFAULT_SPECIALTY
            else f"Generated practice test · Question lens: {specialty_name}"
        )
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
        st.session_state[PRACTICE_PDF_KEY] = export_offline_exam(
            user_id=user_id, attempt_id=_st("attempt_id"),
            questions=st.session_state.get("exam_questions", questions),
            title=practice_label,
            subtitle=pdf_subtitle,
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
        st.session_state["exam_offline_pending"] = True
        persist_current_exam(user_id)
        if take_home_exam:
            suspend_current_exam(user_id)
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
# Older saved practice drafts predate the dedicated Practice Mode timer keys.
# Hydrate them once so the controls do not display an inferred timer while their
# click handlers see the timer as disabled and silently return.
if timer_enabled and PRACTICE_TIMER_ENABLED_KEY not in st.session_state:
    legacy_timer_seconds = _valid_int(
        session_time_limit,
        PRACTICE_DEFAULT_TIMER_SECONDS,
        15,
        600,
    )
    st.session_state[PRACTICE_TIMER_ENABLED_KEY] = True
    st.session_state[PRACTICE_TIMER_SECONDS_KEY] = legacy_timer_seconds
    st.session_state[PRACTICE_TIMER_REMAINING_KEY] = float(legacy_timer_seconds)
    st.session_state[PRACTICE_TIMER_LAST_STARTED_KEY] = time.time()
    st.session_state[PRACTICE_TIMER_PAUSED_KEY] = bool(_st("timer_paused"))
    st.session_state[PRACTICE_TIMER_VISIBLE_KEY] = bool(_st("timer_visible"))
    st.session_state[PRACTICE_TIMER_CURRENT_IDX_KEY] = current_idx
    st.session_state.pop(PRACTICE_TIMER_ACTIVITY_LAST_TICK_KEY, None)
    st.session_state.pop(PRACTICE_TIMER_ACTIVITY_REMAINING_KEY, None)
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

from src.question_lenses import question_lens as active_question_lens
active_specialty = normalize_specialty(active_question_lens(q))
active_context_cue = professional_context_cue(
    active_specialty,
    q.get("section_type", ""),
)
if active_context_cue and not swipe_mode:
    st.info(
        f"**Question lens · {specialty_label(active_specialty)}**  \n"
        f"{active_context_cue}"
    )

# ── Voice Exam Mode ───────────────────────────────────────────────────────────
from src.voice_exam import render_voice_exam_panel
if not swipe_mode:
    render_voice_exam_panel(q, current_idx, total)

if timer_enabled:
    _render_practice_timer_fragment(current_idx, q, question_time_limit)

selected      = _dict_get_idx(answers_dict, current_idx, "")
is_flagged    = current_idx in flagged_set
already_ans   = _dict_has_idx(answers_dict, current_idx)
show_answer   = (instant_fb or auto_submit_answers) and already_ans
expanded_answers = st.session_state.get(PRACTICE_EXPANDED_ANSWER_KEY, set())
auto_expand_answer = show_answer and current_idx in expanded_answers
timed_out_notice_idx = st.session_state.pop(PRACTICE_TIMEOUT_NOTICE_KEY, None)
skipped_notice_idx = st.session_state.pop(PRACTICE_SKIPPED_NOTICE_KEY, None)
timed_out_current = current_idx in timed_out_questions
skipped_current = current_idx in skipped_questions
self_grades = _st("self_grades") or {}
live_correct, live_graded, live_answered = _live_practice_score(
    questions,
    answers_dict,
    self_grades,
)
live_accuracy = round(live_correct / live_graded * 100) if live_graded else 0

if swipe_mode:
    st.caption(f"{live_answered}/{total} answered · {live_correct}/{live_graded} correct")
    tools_col = st.container()
else:
    score_col, accuracy_col, progress_col, tools_col = st.columns([1, 1, 1, 1.35])
    score_col.metric("Live score", f"{live_correct} / {live_graded}")
    accuracy_col.metric("Accuracy", f"{live_accuracy}%" if live_graded else "—")
    progress_col.metric("Answered", f"{live_answered} / {total}")

with tools_col:
    with st.popover("Practice tools", use_container_width=True):
        if swipe_mode:
            render_offline_exams(user_id, preferred_course_id=active_course_id)
            if st.checkbox("Enable voice controls", key="swipe_voice_controls"):
                render_voice_exam_panel(q, current_idx, total)
        st.markdown("**Timer**")
        if timer_enabled:
            _render_practice_timer_controls(key_prefix="practice_timer_tools")
        with st.expander("Timer settings", expanded=False):
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
                    "Make this my default timer",
                    value=False,
                )
                save_timer_settings = st.form_submit_button(
                    "Apply timer settings",
                    use_container_width=True,
                )
        if save_timer_settings:
            _apply_active_question_timer_settings(
                active_timer_enabled,
                active_timer_seconds,
                save_default_timer,
            )
            st.rerun()

        st.markdown("**Question and session**")
        if st.session_state.get("practice_tools_jump") != current_idx + 1:
            st.session_state["practice_tools_jump"] = current_idx + 1
        st.selectbox(
            "Jump to question",
            options=list(range(1, total + 1)),
            index=current_idx,
            key="practice_tools_jump",
            on_change=_jump_to_practice_question_from_tools,
        )
        _render_pdf_download()
        if st.button("Skip and mark incorrect" if swipe_mode else "Skip question", use_container_width=True):
            _skip_current_question()
            st.rerun()
        if st.button("Switch out question", use_container_width=True,
                     help="Tries the same chapter/module, then the same course, then enrolled courses in the same curriculum. Prefers the same difficulty within each scope."):
            if _swap_current_question():
                st.rerun()
            else:
                st.warning("No unused replacement is available, or the next question depends on this one. Previously switched-out questions will not be reused.")
        _render_session_question_editor()
        if admin and already_ans:
            if st.button("Admin: reset this question", use_container_width=True):
                if not real_admin:
                    st.error("Permission denied. Real admin access required.")
                elif _reset_practice_question_for_redo(current_idx):
                    st.session_state[PRACTICE_NOTICE_KEY] = (
                        f"Question {current_idx + 1} was reset. It will count like a fresh attempt."
                    )
                    st.rerun()
                else:
                    st.warning("This question could not be reset.")
        st.divider()
        if st.button("Finish and score reached questions", use_container_width=True):
            _pause_practice_timer()
            reached_indices = _practice_reached_indices(current_idx)
            ungraded_open_ended = [
                i for i, question in enumerate(questions)
                if i in reached_indices
                and is_open_ended_question(question)
                and str(_dict_get_idx(answers_dict, i, "") or "").strip()
                and not _dict_has_idx(self_grades, i)
            ]
            if ungraded_open_ended:
                _set("current_idx", ungraded_open_ended[0])
                st.session_state[PRACTICE_NOTICE_KEY] = (
                    "Self-grade each submitted written response before scoring."
                )
            else:
                st.session_state[PRACTICE_CONFIRM_FINISH_KEY] = True
            st.rerun()
        exit_col, discard_col = st.columns(2)
        if exit_col.button("Save & Exit", use_container_width=True):
            _record_practice_active_time()
            _pause_practice_timer()
            st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
            suspend_current_exam(user_id)
            st.session_state["_exam_exit_notice"] = True
            st.rerun()
        if discard_col.button("Discard Session", use_container_width=True):
            _record_practice_active_time()
            st.session_state.pop(PRACTICE_PDF_KEY, None)
            st.session_state.pop(PRACTICE_PDF_NAME_KEY, None)
            st.session_state.pop(PRACTICE_CONFIRM_FINISH_KEY, None)
            clear_quiz()
            st.rerun()

st.progress(
    answered / total if total else 0,
    text=f"Question {current_idx + 1} of {total} · {answered} answered",
)
if not swipe_mode:
    st.divider()

open_ended = is_open_ended_question(q)
if swipe_mode:
    st.caption("Swipe left: next / skip for later · Right: previous. Tap to choose an answer; scroll to read more.")
with st.container(key="practice_swipe_card" if swipe_mode else "practice_standard_card"):
    picked = render_question(
        q=q, idx=current_idx, total=total,
        selected=selected, show_answer=show_answer, is_flagged=is_flagged,
        auto_expand_answer=auto_expand_answer,
        show_explanation=True,
        compact_actions=True,
        compact_text_tools=True,
        stacked_header=swipe_mode,
    )

if auto_submit_answers and not open_ended and not already_ans:
    submitted_answer = _pending_practice_answer(current_idx, q, picked)
    if submitted_answer:
        record_answer(current_idx, submitted_answer)
        _pause_practice_timer()
        _persist_scored_practice_answer(
            user_id,
            current_idx,
            q,
            time_spent=time_on_current_question(),
        )
        _open_answer_review_for_question(current_idx)
        st.rerun()

persist_current_exam(user_id)

if timed_out_notice_idx == current_idx or selected == PRACTICE_TIMEOUT_ANSWER or timed_out_current:
    st.error("Time expired before you submitted. This question was marked wrong.")
if skipped_notice_idx == current_idx or selected == PRACTICE_SKIPPED_ANSWER or skipped_current:
    st.error("Question skipped. This question was marked wrong.")

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
            selected_grade = self_grade_choice == "Correct"
            grade_changed = (
                not has_existing_grade
                or bool(existing_grade) != selected_grade
            )
            record_self_grade(current_idx, selected_grade)
            if grade_changed:
                _persist_scored_practice_answer(
                    user_id,
                    current_idx,
                    q,
                    time_spent=time_on_current_question(),
                )
                st.rerun()
            self_grades = _st("self_grades") or {}
        else:
            st.info("Mark this written response correct or incorrect before scoring the session.")

if show_answer:
    render_personal_explanation(user_id, q)
    render_question_notes(user_id, q)

if not already_ans and (open_ended or not auto_submit_answers):
    if st.button("✔ Submit Answer", type="primary", use_container_width=True):
        submitted_answer = _pending_practice_answer(current_idx, q, picked)
        if not submitted_answer and not open_ended:
            _skip_current_question()
            st.rerun()
        else:
            record_answer(current_idx, submitted_answer)
            _pause_practice_timer()
            if not open_ended:
                _persist_scored_practice_answer(
                    user_id,
                    current_idx,
                    q,
                    time_spent=time_on_current_question(),
                )
            _open_answer_review_for_question(current_idx)
            st.rerun()
elif not swipe_mode:
    if current_idx < total - 1:
        if st.button("Next Question →", type="primary", use_container_width=True):
            next_question(); _start_practice_question_clock(); st.rerun()

if swipe_mode:
    pending = skip_pass_indices(total, _practice_reached_indices(current_idx), answers_dict)
    with st.container(key="practice_swipe_nav"):
        back, forward = st.columns(2)
        back.button("← Previous", key="swipe_previous", disabled=current_idx == 0,
                    use_container_width=True, on_click=_go_to_practice_question,
                    args=(current_idx - 1,))
        forward.button("Next →" if already_ans else "Skip for later →",
                       key="swipe_next", disabled=current_idx == total - 1,
                       use_container_width=True, on_click=_go_to_practice_question,
                       args=(current_idx + 1,))
    other_pending = [i for i in pending if i != current_idx]
    next_pending = next((i for i in other_pending if i > current_idx),
                        other_pending[0] if other_pending else current_idx)
    st.button(f"Skip pass · {len(pending)} unanswered", key="swipe_skip_pass",
              disabled=not other_pending, use_container_width=True,
              on_click=_go_to_practice_question, args=(next_pending,))
    with st.popover("Go to question", use_container_width=True):
        for row_start in range(0, total, 5):
            cols = st.columns(5)
            for offset, column in enumerate(cols):
                target = row_start + offset
                if target < total:
                    status = " ✓" if _dict_has_idx(answers_dict, target) else ""
                    column.button(f"{target + 1}{status}", key=f"swipe_jump_{target}",
                                  disabled=target == current_idx,
                                  on_click=_go_to_practice_question, args=(target,))
    if current_idx == total - 1:
        st.info("End of the questions. Use Skip pass to return to unanswered questions, or finish in Practice tools.")
    st.caption("Skipped-for-later questions stay unscored until you answer or finish. Unanswered reached questions count as incorrect when you finish.")
    install_swipe_gestures(current_idx)

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
