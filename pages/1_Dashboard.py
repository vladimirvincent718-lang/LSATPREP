"""
pages/1_Dashboard.py - Course and curriculum-aware Dashboard.
"""

import os
import sys
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.auth import require_login
from src.analytics import get_dashboard_stats
from src.database import (
    get_all_curriculums,
    get_all_questions,
    get_answer_drilldown,
    get_answer_stats,
    get_course,
    get_course_question_count,
    get_curriculum_courses,
    get_material_progress,
    get_materials,
    get_mistake_journal,
    get_question_issue_metrics,
    get_question_issue_reports,
    get_review_activity,
    get_setting,
    set_setting,
)
from src.ui_theme import apply_plotly_theme
from src.utils import DIFFICULTY_LABELS, course_selector, page_header, sidebar_nav

st.set_page_config(page_title="Dashboard - StudyForge", page_icon="📊", layout="wide")

DASHBOARD_REPORTS_SETTING = "dashboard_saved_reports_v1"


def _accuracy_bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    *,
    orientation: str = "h",
    hover_data: dict | None = None,
    custom_data: list[str] | None = None,
):
    fig = px.bar(
        df,
        x=x,
        y=y,
        orientation=orientation,
        color="% Correct",
        color_continuous_scale=["#d73027", "#fee090", "#1a9850"],
        range_color=[0, 100],
        text="% Correct",
        hover_data=hover_data,
        custom_data=custom_data,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), coloraxis_showscale=False)
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="inside")
    apply_plotly_theme(fig)
    return fig


def _selection_points(event) -> list:
    if event is None:
        return []
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    if selection is None:
        return []
    points = getattr(selection, "points", None)
    if points is None and isinstance(selection, dict):
        points = selection.get("points")
    return list(points or [])


def _point_customdata(point):
    if isinstance(point, dict):
        return point.get("customdata") or point.get("custom_data") or []
    return getattr(point, "customdata", None) or getattr(point, "custom_data", None) or []


def _row_from_selection(event, df: pd.DataFrame, column: str, customdata_index: int = 0) -> dict | None:
    points = _selection_points(event)
    if not points:
        return None
    customdata = _point_customdata(points[0])
    if customdata and len(customdata) > customdata_index:
        selected_value = customdata[customdata_index]
        matches = df[df[column].astype(str) == str(selected_value)]
        if not matches.empty:
            return matches.iloc[0].to_dict()

    if isinstance(points[0], dict):
        point_index = (
            points[0].get("point_index")
            or points[0].get("pointIndex")
            or points[0].get("point_number")
            or points[0].get("pointNumber")
        )
    else:
        point_index = (
            getattr(points[0], "point_index", None)
            or getattr(points[0], "pointIndex", None)
            or getattr(points[0], "point_number", None)
            or getattr(points[0], "pointNumber", None)
        )
    if point_index is not None and 0 <= int(point_index) < len(df):
        return df.iloc[int(point_index)].to_dict()
    return None


def _materials_summary(user_id: int, course_ids: list[int]) -> tuple[int, int, int]:
    total = 0
    completed = 0
    for cid in course_ids:
        materials = get_materials(cid)
        progress = get_material_progress(user_id, cid)
        total += len(materials)
        completed += sum(
            1 for material in materials
            if progress.get(material["id"]) == "Completed"
        )
    pct = round(completed / total * 100) if total else 0
    return total, completed, pct


def _render_kpis(
    stats: dict,
    q_count: int,
    material_total: int,
    material_completed: int,
    material_pct: int,
    *,
    key_prefix: str,
    show_materials: bool = False,
) -> str | None:
    selected_metric = None
    state_key = f"{key_prefix}_selected_kpi"
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    metric_items = [
        ("questions", "Questions in Bank", q_count, None),
        ("sessions", "Sessions Completed", stats["total_attempts"], None),
        ("answered", "Total Qs Answered", stats["total_questions"], None),
        (
            "latest",
            "Latest Score",
            _format_percent(stats["latest_percent"]),
            _score_delta_label(stats),
        ),
        ("best", "Best Score", _format_percent(stats["best_percent"]), None),
        ("average", "Avg Score", _format_percent(stats["avg_percent"]), None),
    ]
    for col, (metric_key, label, value, delta) in zip(
        [k1, k2, k3, k4, k5, k6],
        metric_items,
    ):
        button_label = f"{label}\n\n{value}"
        if delta:
            button_label = f"{button_label}\n{delta}"
        with col:
            if st.button(
                button_label,
                key=f"{key_prefix}_kpi_{metric_key}",
                use_container_width=True,
            ):
                if st.session_state.get(state_key) == metric_key:
                    st.session_state[state_key] = None
                else:
                    st.session_state[state_key] = metric_key
            if st.session_state.get(state_key) == metric_key:
                selected_metric = metric_key


    if show_materials and material_total > 0:
        st.progress(
            material_pct / 100,
            text=(
                f"Materials: {material_completed}/{material_total} completed "
                f"({material_pct}%)"
            ),
        )
    return selected_metric


def _metric_label(metric_key: str) -> str:
    return {
        "questions": "Questions in Bank",
        "sessions": "Sessions Completed",
        "answered": "Total Qs Answered",
        "latest": "Latest Score",
        "best": "Best Score",
        "average": "Avg Score",
    }.get(metric_key, metric_key.replace("_", " ").title())


def _score_delta_label(stats: dict) -> str | None:
    if stats["improvement_trend"] is None:
        return None
    return f"{stats['improvement_trend']:+.1f}% trend"


def _format_percent(value) -> str:
    if value is None:
        return "-"
    return f"{value}%"


def _metric_sort_value(value):
    return -1 if value is None else value


def _reset_dashboard_defaults() -> None:
    reset_prefixes = (
        "dashboard_report_sections_",
        "course_dashboard_time_",
        "curriculum_dashboard_time_",
        "course_cards_sort_",
    )
    reset_suffixes = ("_selected_kpi",)
    for key in list(st.session_state.keys()):
        if key.startswith(reset_prefixes) or key.endswith(reset_suffixes):
            del st.session_state[key]


def _report_state_key(view_mode: str) -> str:
    return f"dashboard_report_sections_{view_mode.lower()}"


def _empty_saved_reports() -> dict:
    return {
        "Course": {"default": "", "reports": []},
        "Curriculum": {"default": "", "reports": []},
    }


def _load_saved_reports(user_id: int) -> dict:
    raw = get_setting(user_id, DASHBOARD_REPORTS_SETTING)
    saved = _empty_saved_reports()
    if not raw:
        return saved
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return saved
    for view_mode in ("Course", "Curriculum"):
        view_data = parsed.get(view_mode, {}) if isinstance(parsed, dict) else {}
        reports = view_data.get("reports", [])
        if isinstance(reports, list):
            saved[view_mode]["reports"] = [
                {
                    "name": str(report.get("name", "")).strip(),
                    "sections": list(report.get("sections", [])),
                }
                for report in reports
                if isinstance(report, dict) and str(report.get("name", "")).strip()
            ]
        saved[view_mode]["default"] = str(view_data.get("default", "")).strip()
    return saved


def _save_saved_reports(user_id: int, saved: dict) -> None:
    set_setting(user_id, DASHBOARD_REPORTS_SETTING, json.dumps(saved))


def _find_saved_report(saved: dict, view_mode: str, name: str) -> dict | None:
    for report in saved.get(view_mode, {}).get("reports", []):
        if report["name"] == name:
            return report
    return None


def _apply_saved_report(user_id: int, view_mode: str, report_name: str) -> None:
    saved = _load_saved_reports(user_id)
    report = _find_saved_report(saved, view_mode, report_name)
    if not report:
        return
    st.session_state[_report_state_key(view_mode)] = report["sections"]
    for key in list(st.session_state.keys()):
        if key.endswith("_selected_kpi"):
            del st.session_state[key]


def _set_default_saved_report(user_id: int, view_mode: str, report_name: str) -> None:
    saved = _load_saved_reports(user_id)
    if _find_saved_report(saved, view_mode, report_name):
        saved[view_mode]["default"] = report_name
        _save_saved_reports(user_id, saved)


def _delete_saved_report(user_id: int, view_mode: str, report_name: str) -> None:
    saved = _load_saved_reports(user_id)
    saved[view_mode]["reports"] = [
        report for report in saved[view_mode]["reports"]
        if report["name"] != report_name
    ]
    if saved[view_mode]["default"] == report_name:
        saved[view_mode]["default"] = ""
    _save_saved_reports(user_id, saved)


def _save_current_report(user_id: int, view_mode: str, sections_key: str, name_key: str) -> None:
    report_name = str(st.session_state.get(name_key, "")).strip()
    sections = list(st.session_state.get(sections_key, []))
    if not report_name:
        st.session_state[f"{sections_key}_save_message"] = "Name the report before saving."
        return
    saved = _load_saved_reports(user_id)
    reports = [
        report for report in saved[view_mode]["reports"]
        if report["name"].lower() != report_name.lower()
    ]
    reports.append({"name": report_name, "sections": sections})
    reports.sort(key=lambda report: report["name"].lower())
    saved[view_mode]["reports"] = reports
    if not saved[view_mode]["default"]:
        saved[view_mode]["default"] = report_name
    _save_saved_reports(user_id, saved)
    st.session_state[f"{sections_key}_save_message"] = f"Saved '{report_name}'."


def _save_current_report_as_default(user_id: int, view_mode: str, sections_key: str, name_key: str) -> None:
    _save_current_report(user_id, view_mode, sections_key, name_key)
    report_name = str(st.session_state.get(name_key, "")).strip()
    if report_name:
        _set_default_saved_report(user_id, view_mode, report_name)
        st.session_state[f"{sections_key}_save_message"] = f"Saved '{report_name}' as default."


def _date_bounds(start: date | None, end: date | None) -> tuple[str | None, str | None]:
    start_value = f"{start.isoformat()} 00:00:00" if start else None
    end_value = f"{(end + timedelta(days=1)).isoformat()} 00:00:00" if end else None
    return start_value, end_value


def _month_options(months_back: int = 18) -> list[tuple[str, date, date]]:
    today = date.today().replace(day=1)
    options = []
    for offset in range(months_back):
        month_start = (pd.Timestamp(today) - pd.DateOffset(months=offset)).date()
        month_end = (pd.Timestamp(month_start) + pd.DateOffset(months=1) - pd.DateOffset(days=1)).date()
        options.append((month_start.strftime("%B %Y"), month_start, month_end))
    return options


def _dashboard_time_controls(key_prefix: str) -> dict:
    today = date.today()
    grain_options = ["Overall", "Daily", "Weekly", "Monthly", "Quarterly", "Annual"]
    preset_options = [
        "All time",
        "Last 7 days",
        "Last 30 days",
        "Last 60 days",
        "Last 90 days",
        "This month",
        "Last month",
        "Year to date",
        "Specific month",
        "Custom range",
    ]

    with st.container(border=True):
        st.markdown("### Time View")
        grain_col, preset_col, start_col, end_col = st.columns([1.2, 1.6, 1, 1])
        grain = grain_col.radio(
            "View by",
            grain_options,
            horizontal=True,
            key=f"{key_prefix}_time_grain",
        )
        preset = preset_col.selectbox(
            "Time frame",
            preset_options,
            key=f"{key_prefix}_time_preset",
        )

        start_date = None
        end_date = None
        if preset == "Last 7 days":
            start_date, end_date = today - timedelta(days=6), today
        elif preset == "Last 30 days":
            start_date, end_date = today - timedelta(days=29), today
        elif preset == "Last 60 days":
            start_date, end_date = today - timedelta(days=59), today
        elif preset == "Last 90 days":
            start_date, end_date = today - timedelta(days=89), today
        elif preset == "This month":
            start_date, end_date = today.replace(day=1), today
        elif preset == "Last month":
            month_start = (pd.Timestamp(today.replace(day=1)) - pd.DateOffset(months=1)).date()
            month_end = (pd.Timestamp(today.replace(day=1)) - pd.DateOffset(days=1)).date()
            start_date, end_date = month_start, month_end
        elif preset == "Year to date":
            start_date, end_date = date(today.year, 1, 1), today
        elif preset == "Specific month":
            months = _month_options()
            month_label = start_col.selectbox(
                "Month",
                [label for label, _, _ in months],
                key=f"{key_prefix}_specific_month",
            )
            _, start_date, end_date = next(item for item in months if item[0] == month_label)
            end_col.caption(f"Through {end_date.isoformat()}")
        elif preset == "Custom range":
            start_date = start_col.date_input(
                "Start",
                value=today - timedelta(days=29),
                key=f"{key_prefix}_custom_start",
            )
            end_date = end_col.date_input(
                "End",
                value=today,
                key=f"{key_prefix}_custom_end",
            )
            if start_date > end_date:
                st.warning("Start date is after end date. Showing the selected dates after swapping them.")
                start_date, end_date = end_date, start_date
        else:
            start_col.caption("Start: earliest")
            end_col.caption("End: latest")

        if preset not in {"Specific month", "Custom range", "All time"}:
            start_col.caption(f"Start: {start_date.isoformat()}")
            end_col.caption(f"End: {end_date.isoformat()}")

    completed_from, completed_to = _date_bounds(start_date, end_date)
    if start_date and end_date:
        label = f"{preset}: {start_date.isoformat()} to {end_date.isoformat()}"
    else:
        label = "All time"
    return {
        "grain": grain,
        "completed_from": completed_from,
        "completed_to": completed_to,
        "label": label,
    }


def _report_builder(user_id: int, view_mode: str) -> set[str]:
    course_options = [
        "Materials progress",
        "Performance overview",
        "Daily activity",
        "Review activity",
        "Score trend analysis",
        "Weakest courses",
        "Question reports",
        "Accuracy by module",
        "Question type and difficulty",
    ]
    curriculum_options = [
        "Materials progress",
        "Performance overview",
        "Daily activity",
        "Review activity",
        "Score trend analysis",
        "Weakest courses",
        "Question reports",
        "Course dashboard cards",
        "Accuracy by course",
        "Accuracy by module",
        "Question type and difficulty",
    ]
    options = course_options if view_mode == "Course" else curriculum_options
    key = _report_state_key(view_mode)
    saved_reports = _load_saved_reports(user_id)
    default_report = _find_saved_report(
        saved_reports,
        view_mode,
        saved_reports[view_mode]["default"],
    )
    if key not in st.session_state and default_report:
        st.session_state[key] = [
            section for section in default_report["sections"]
            if section in options
        ]

    with st.container(border=True):
        st.markdown("### Report Builder")
        st.caption("Add only the dashboard sections you want to see.")

        report_names = [report["name"] for report in saved_reports[view_mode]["reports"]]
        if report_names:
            selected_report = st.selectbox(
                "Saved reports",
                options=report_names,
                index=(
                    report_names.index(saved_reports[view_mode]["default"])
                    if saved_reports[view_mode]["default"] in report_names
                    else 0
                ),
                key=f"{key}_saved_report",
            )
            load_col, default_col, delete_col = st.columns(3)
            load_col.button(
                "Load",
                key=f"{key}_load_saved",
                use_container_width=True,
                on_click=_apply_saved_report,
                args=(user_id, view_mode, selected_report),
            )
            default_col.button(
                "Make default",
                key=f"{key}_default_saved",
                use_container_width=True,
                on_click=_set_default_saved_report,
                args=(user_id, view_mode, selected_report),
            )
            delete_col.button(
                "Delete",
                key=f"{key}_delete_saved",
                use_container_width=True,
                on_click=_delete_saved_report,
                args=(user_id, view_mode, selected_report),
            )
            if saved_reports[view_mode]["default"]:
                st.caption(f"Default: {saved_reports[view_mode]['default']}")

        selected = st.multiselect(
            "Dashboard sections",
            options=options,
            default=st.session_state.get(key, []),
            key=key,
        )

        name_key = f"{key}_save_name"
        st.text_input("Report name", key=name_key, placeholder="My dashboard layout")
        save_col, save_default_col = st.columns(2)
        save_col.button(
            "Save current report",
            key=f"{key}_save_current",
            use_container_width=True,
            on_click=_save_current_report,
            args=(user_id, view_mode, key, name_key),
        )
        save_default_col.button(
            "Save as default",
            key=f"{key}_save_default",
            use_container_width=True,
            on_click=_save_current_report_as_default,
            args=(user_id, view_mode, key, name_key),
        )
        if st.session_state.get(f"{key}_save_message"):
            st.caption(st.session_state[f"{key}_save_message"])

        st.button(
            "Start from scratch",
            key=f"{key}_reset",
            use_container_width=True,
            on_click=_reset_dashboard_defaults,
        )

    return set(selected)


def _dashboard_header(
    title: str,
    subtitle: str,
    view_mode: str,
    current_user_id: int | None = None,
) -> set[str]:
    header_col, builder_col = st.columns([2.1, 1], vertical_alignment="top")
    with header_col:
        page_header(title, subtitle)
    with builder_col:
        return _report_builder(current_user_id or globals()["user_id"], view_mode)


def _render_trend_and_weak_list(stats: dict, weak_key: str,
                                label_key: str, heading: str) -> dict | None:
    selected_session = None
    col_left, col_right = st.columns([3, 2])

    with col_left:
        selected_session = _render_score_trend(stats, key=f"{weak_key}_score_trend")

    with col_right:
        st.markdown(f"### {heading}")
        weak_items = stats[weak_key]
        if weak_items:
            for item in weak_items:
                pct = item["percent"]
                severity = (
                    "High priority" if pct < 50
                    else "Needs work" if pct < 70
                    else "Watch"
                )
                st.markdown(
                    f"**{item[label_key]}**  \n"
                    f"{severity} - {pct}% correct "
                    f"({item['correct']}/{item['total']})"
                )
                st.progress(max(0, min(100, pct)) / 100)
        else:
            st.caption("Nothing is below the 75% target yet.")

    return selected_session


def _render_score_trend(
    stats: dict,
    key: str = "score_trend",
    heading: str = "Score Trend Analysis",
    table_heading: str = "Session Table",
) -> dict | None:
    st.markdown(f"### {heading}")
    trend_df = stats["score_trend"]
    if trend_df.empty:
        st.caption("Not enough data yet.")
        return None

    col_latest, col_average, col_best, col_trend = st.columns(4)
    col_latest.metric("Latest", _format_percent(stats["latest_percent"]))
    col_average.metric("Average", _format_percent(stats["avg_percent"]))
    col_best.metric("Best", _format_percent(stats["best_percent"]))
    col_trend.metric("Trend", _score_delta_label(stats) or "-")

    fig = px.line(
        trend_df,
        x="completed_at",
        y="percent_correct",
        color="mode",
        markers=True,
        custom_data=[
            "attempt_id",
            "total_questions",
            "correct_answers",
            "mode",
        ],
        labels={
            "completed_at": "Date",
            "percent_correct": "% Correct",
            "mode": "Mode",
        },
    )
    fig.update_layout(
        yaxis_range=[0, 100],
        margin=dict(l=0, r=0, t=10, b=0),
        legend_title_text="",
    )
    apply_plotly_theme(fig)
    fig.add_hline(
        y=75,
        line_dash="dot",
        line_color="orange",
        annotation_text="75% target",
    )
    trend_event = st.plotly_chart(
        fig,
        use_container_width=True,
        on_select="rerun",
        selection_mode="points",
        key=f"{key}_chart",
    )
    session_df = trend_df.copy()
    session_df["Date"] = session_df["completed_at"].dt.strftime("%Y-%m-%d %H:%M")
    session_df = session_df.rename(
        columns={
            "mode": "Mode",
            "percent_correct": "% Correct",
            "total_questions": "Answered",
            "correct_answers": "Correct",
            "attempt_id": "Attempt ID",
        }
    )[["Date", "Mode", "% Correct", "Answered", "Correct", "Attempt ID"]]

    selected_session = None
    points = _selection_points(trend_event)
    if points:
        customdata = _point_customdata(points[0])
        if customdata:
            attempt_id = customdata[0]
            matches = session_df[session_df["Attempt ID"].astype(str) == str(attempt_id)]
            if not matches.empty:
                selected_session = matches.iloc[0].to_dict()

    st.markdown(f"#### {table_heading}")
    return _render_selectable_breakdown_table(
        session_df.sort_values("Date", ascending=False),
        f"{key}_session_table",
        "Date",
    ) or selected_session


def _session_activity_frames(
    user_id: int,
    *,
    course_id: int | None = None,
    course_ids: list[int] | None = None,
    completed_from=None,
    completed_to=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    answers = get_answer_stats(
        user_id,
        course_id=course_id,
        course_ids=course_ids,
        completed_from=completed_from,
        completed_to=completed_to,
    )
    if not answers:
        return pd.DataFrame(), pd.DataFrame()

    grouped: dict[int, dict] = {}
    for answer in answers:
        attempt_id = answer.get("attempt_id")
        if attempt_id is None:
            continue
        row = grouped.setdefault(
            int(attempt_id),
            {
                "attempt_id": int(attempt_id),
                "completed_at": answer.get("completed_at"),
                "mode": answer.get("mode") or "Unknown",
                "courses": set(),
                "total_questions": 0,
                "correct_answers": 0,
            },
        )
        row["courses"].add(answer.get("course_title") or "Unknown Course")
        row["total_questions"] += 1
        row["correct_answers"] += int(bool(answer.get("is_correct")))

    session_rows = []
    course_touch_rows = []
    for row in grouped.values():
        completed_at = pd.to_datetime(row["completed_at"])
        courses = sorted(row["courses"])
        course_mix = " + ".join(courses) if len(courses) <= 2 else f"Mixed ({len(courses)} courses)"
        session_rows.append(
            {
                "Date": completed_at.date(),
                "Completed At": completed_at.strftime("%Y-%m-%d %H:%M"),
                "Mode": row["mode"],
                "Course Mix": course_mix,
                "Courses": ", ".join(courses),
                "Answered": row["total_questions"],
                "Correct": row["correct_answers"],
                "% Correct": (
                    round(row["correct_answers"] / row["total_questions"] * 100, 1)
                    if row["total_questions"]
                    else 0
                ),
                "Attempt ID": row["attempt_id"],
            }
        )
        for course_title in courses:
            course_touch_rows.append(
                {
                    "Date": completed_at.date(),
                    "Course": course_title,
                    "Attempt ID": row["attempt_id"],
                }
            )

    return pd.DataFrame(session_rows), pd.DataFrame(course_touch_rows)


def _render_daily_activity(
    user_id: int,
    title: str,
    *,
    key_prefix: str,
    time_grain: str = "Daily",
    course_id: int | None = None,
    course_ids: list[int] | None = None,
    completed_from=None,
    completed_to=None,
) -> None:
    st.markdown(f"### Activity: {title}")
    session_df, course_touch_df = _session_activity_frames(
        user_id,
        course_id=course_id,
        course_ids=course_ids,
        completed_from=completed_from,
        completed_to=completed_to,
    )
    if session_df.empty:
        st.caption("No completed sessions yet.")
        return

    freq_map = {
        "Daily": "D",
        "Weekly": "W-MON",
        "Monthly": "M",
        "Quarterly": "Q",
        "Annual": "Y",
    }
    period_label = {
        "Daily": "Day",
        "Weekly": "Week",
        "Monthly": "Month",
        "Quarterly": "Quarter",
        "Annual": "Year",
    }.get(time_grain, "Period")
    freq = freq_map.get(time_grain, "D")
    if freq == "OVERALL":
        session_df["Period"] = "Overall"
        course_touch_df["Period"] = "Overall" if not course_touch_df.empty else pd.Series(dtype=str)
    else:
        session_df["Period"] = pd.to_datetime(session_df["Date"]).dt.to_period(freq).astype(str)
        course_touch_df["Period"] = (
            pd.to_datetime(course_touch_df["Date"]).dt.to_period(freq).astype(str)
            if not course_touch_df.empty
            else pd.Series(dtype=str)
        )

    daily_df = (
        session_df.groupby("Period")
        .agg(
            Sessions=("Attempt ID", "nunique"),
            Questions=("Answered", "sum"),
            Avg_Accuracy=("% Correct", "mean"),
        )
        .reset_index()
        .rename(columns={"Avg_Accuracy": "Avg Accuracy"})
    )

    fig = px.bar(
        daily_df,
        x="Period",
        y="Sessions",
        text="Sessions",
        hover_data={"Questions": True, "Avg Accuracy": ":.1f"},
        labels={"Sessions": "Sessions Completed"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(dtick=1))
    apply_plotly_theme(fig)
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_daily_sessions_chart")

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown(f"#### Sessions by {period_label}")
        display_daily = daily_df.copy()
        st.dataframe(
            display_daily,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Sessions": st.column_config.NumberColumn("Sessions", format="%d"),
                "Questions": st.column_config.NumberColumn("Questions", format="%d"),
                "Avg Accuracy": st.column_config.ProgressColumn(
                    "Avg Accuracy",
                    format="%.1f%%",
                    min_value=0,
                    max_value=100,
                ),
            },
        )
    with col_right:
        st.markdown("#### Course Mix")
        mix_df = (
            session_df["Course Mix"]
            .value_counts()
            .rename_axis("Course Mix")
            .reset_index(name="Sessions")
        )
        st.dataframe(mix_df, use_container_width=True, hide_index=True)

    if not course_touch_df.empty and course_ids is not None:
        st.markdown(f"#### Courses Touched by {period_label}")
        touched = (
            course_touch_df.groupby(["Period", "Course"])["Attempt ID"]
            .nunique()
            .reset_index(name="Sessions Touching Course")
        )
        fig_course = px.bar(
            touched,
            x="Period",
            y="Sessions Touching Course",
            color="Course",
            labels={"Sessions Touching Course": "Sessions"},
        )
        fig_course.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(dtick=1))
        apply_plotly_theme(fig_course)
        st.plotly_chart(fig_course, use_container_width=True, key=f"{key_prefix}_course_mix_chart")

    st.markdown("#### Completed Sessions")
    session_display = session_df.sort_values("Completed At", ascending=False)[
        ["Completed At", "Mode", "Course Mix", "Courses", "Answered", "Correct", "% Correct", "Attempt ID"]
    ]
    st.dataframe(
        session_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "% Correct": st.column_config.ProgressColumn(
                "% Correct",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
            "Attempt ID": None,
        },
    )


def _time_grain_parts(time_grain: str) -> tuple[str, str]:
    if time_grain == "Overall":
        return "OVERALL", "Overall"
    freq_map = {
        "Daily": "D",
        "Weekly": "W-MON",
        "Monthly": "M",
        "Quarterly": "Q",
        "Annual": "Y",
    }
    period_label = {
        "Daily": "Day",
        "Weekly": "Week",
        "Monthly": "Month",
        "Quarterly": "Quarter",
        "Annual": "Year",
    }.get(time_grain, "Period")
    return freq_map.get(time_grain, "D"), period_label


def _render_review_activity(
    user_id: int,
    title: str,
    *,
    key_prefix: str,
    time_grain: str = "Daily",
    course_id: int | None = None,
    course_ids: list[int] | None = None,
    completed_from=None,
    completed_to=None,
) -> None:
    st.markdown(f"### Review Activity: {title}")

    journal = get_mistake_journal(user_id, course_id=course_id, course_ids=course_ids)
    total_mistakes = len(journal)
    reviewed_total = sum(1 for entry in journal if entry.get("is_completed"))
    outstanding = total_mistakes - reviewed_total
    completion_pct = round(reviewed_total / total_mistakes * 100) if total_mistakes else 0

    reviews = get_review_activity(
        user_id,
        course_id=course_id,
        course_ids=course_ids,
        reviewed_from=completed_from,
        reviewed_to=completed_to,
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Reviews in Time Frame", len(reviews))
    k2.metric("Reviewed Total", reviewed_total)
    k3.metric("Outstanding", outstanding)
    k4.metric("Review Complete", f"{completion_pct}%")
    if total_mistakes:
        st.progress(completion_pct / 100)

    if not reviews:
        st.caption("No mistakes were marked reviewed in this time frame.")
        return

    freq, period_label = _time_grain_parts(time_grain)
    df = pd.DataFrame(reviews)
    df["Reviewed At"] = pd.to_datetime(df["completed_at"])
    if freq == "OVERALL":
        df["Period"] = "Overall"
    else:
        df["Period"] = df["Reviewed At"].dt.to_period(freq).astype(str)
    df["Course"] = df["course_title"].fillna("Unknown Course")
    df["Module"] = df["section_type"].fillna("Unknown Module")
    df["Question Type"] = df["question_type"].fillna("Unknown")

    period_df = (
        df.groupby("Period")
        .size()
        .reset_index(name="Reviews")
        .sort_values("Period")
    )

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown(f"#### Reviews by {period_label}")
        st.dataframe(
            period_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Reviews": st.column_config.NumberColumn("Reviews", format="%d"),
            },
        )
    with col_right:
        st.markdown("#### Review Mix")
        mix_df = (
            df["Question Type"]
            .value_counts()
            .rename_axis("Question Type")
            .reset_index(name="Reviews")
        )
        st.dataframe(mix_df, use_container_width=True, hide_index=True)

    if course_ids is not None:
        st.markdown(f"#### Reviews by Course and {period_label}")
        course_df = (
            df.groupby(["Period", "Course"])
            .size()
            .reset_index(name="Reviews")
            .sort_values(["Period", "Course"])
        )
        st.dataframe(course_df, use_container_width=True, hide_index=True)

    st.markdown("#### Reviewed Mistakes")
    display = df.sort_values("Reviewed At", ascending=False)[
        ["Reviewed At", "Course", "Module", "Question Type", "difficulty"]
    ].rename(columns={"difficulty": "Difficulty"})
    display["Reviewed At"] = display["Reviewed At"].dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_question_reports(
    title: str,
    *,
    key_prefix: str,
    time_grain: str = "Daily",
    course_id: int | None = None,
    course_ids: list[int] | None = None,
) -> None:
    st.markdown(f"### Question Reports: {title}")
    scoped_course_ids = course_ids if course_ids is not None else ([course_id] if course_id is not None else None)
    reports = get_question_issue_reports(course_ids=scoped_course_ids)
    metrics = get_question_issue_metrics(course_ids=scoped_course_ids)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Reports", metrics.get("total", 0))
    k2.metric("New", metrics.get("new_count", 0))
    k3.metric("Reviewing", metrics.get("reviewing_count", 0))
    k4.metric("Resolved", metrics.get("resolved_count", 0))
    k5.metric("Dismissed", metrics.get("dismissed_count", 0))

    if not reports:
        st.caption("No question reports match this scope yet.")
        return

    df = pd.DataFrame(reports)
    df["Created At"] = pd.to_datetime(df["created_at"])
    df["Course"] = df["course_title"].fillna("Unknown Course")
    df["Issue Type"] = df["issue_type"].fillna("Other")
    df["Status"] = df["status"].fillna("New")
    df["Module"] = df["section_type"].fillna("Unknown Module")
    df["Question Type"] = df["question_type"].fillna("Unknown")

    issue_df = (
        df["Issue Type"]
        .value_counts()
        .rename_axis("Issue Type")
        .reset_index(name="Reports")
    )
    status_df = (
        df["Status"]
        .value_counts()
        .rename_axis("Status")
        .reset_index(name="Reports")
    )

    col_issue, col_status = st.columns(2)
    with col_issue:
        st.markdown("#### Reports by Issue Type")
        fig_issue = px.bar(
            issue_df,
            x="Reports",
            y="Issue Type",
            orientation="h",
            text="Reports",
        )
        fig_issue.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis=dict(dtick=1))
        apply_plotly_theme(fig_issue)
        st.plotly_chart(fig_issue, use_container_width=True, key=f"{key_prefix}_issue_type_chart")
        st.dataframe(issue_df, use_container_width=True, hide_index=True)

    with col_status:
        st.markdown("#### Reports by Status")
        fig_status = px.bar(
            status_df,
            x="Status",
            y="Reports",
            color="Status",
            text="Reports",
        )
        fig_status.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(dtick=1))
        apply_plotly_theme(fig_status)
        st.plotly_chart(fig_status, use_container_width=True, key=f"{key_prefix}_status_chart")
        st.dataframe(status_df, use_container_width=True, hide_index=True)

    freq, period_label = _time_grain_parts(time_grain)
    if freq == "OVERALL":
        df["Period"] = "Overall"
    else:
        df["Period"] = df["Created At"].dt.to_period(freq).astype(str)
    period_df = (
        df.groupby(["Period", "Issue Type"])
        .size()
        .reset_index(name="Reports")
        .sort_values(["Period", "Issue Type"])
    )
    st.markdown(f"#### Reports by {period_label}")
    fig_period = px.bar(
        period_df,
        x="Period",
        y="Reports",
        color="Issue Type",
        labels={"Reports": "Question Reports"},
    )
    fig_period.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(dtick=1))
    apply_plotly_theme(fig_period)
    st.plotly_chart(fig_period, use_container_width=True, key=f"{key_prefix}_period_chart")

    if scoped_course_ids is not None and len(scoped_course_ids) > 1:
        st.markdown("#### Reports by Course")
        course_df = (
            df.groupby(["Course", "Status"])
            .size()
            .reset_index(name="Reports")
            .sort_values(["Course", "Status"])
        )
        fig_course = px.bar(
            course_df,
            x="Reports",
            y="Course",
            color="Status",
            orientation="h",
            labels={"Reports": "Question Reports"},
        )
        fig_course.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis=dict(dtick=1))
        apply_plotly_theme(fig_course)
        st.plotly_chart(fig_course, use_container_width=True, key=f"{key_prefix}_course_chart")

    st.markdown("#### Weekly Reconciliation Queue")
    queue = df[df["Status"].isin(["New", "Reviewing"])].copy()
    if queue.empty:
        st.success("No open question reports to reconcile.")
        return
    queue_display = queue.sort_values("Created At", ascending=False)[
        [
            "Created At",
            "Status",
            "Issue Type",
            "Course",
            "Module",
            "Question Type",
            "master_question_id",
            "username",
            "note",
        ]
    ].rename(columns={
        "master_question_id": "Question ID",
        "username": "Reported By",
        "note": "Note",
    })
    queue_display["Created At"] = queue_display["Created At"].dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(queue_display, use_container_width=True, hide_index=True)


def _render_selectable_breakdown_table(
    df: pd.DataFrame,
    key: str,
    label: str,
) -> dict | None:
    display_df = df.rename(columns={"% Correct": "Accuracy"})
    column_config = {
        "Accuracy": st.column_config.ProgressColumn(
            "Accuracy",
            format="%.1f%%",
            min_value=0,
            max_value=100,
        ),
        "Answered": st.column_config.NumberColumn("Answered", format="%d"),
        "Missed": st.column_config.NumberColumn("Missed", format="%d"),
    }
    if "Course ID" in display_df.columns:
        column_config["Course ID"] = None
    if "Attempt ID" in display_df.columns:
        column_config["Attempt ID"] = None

    try:
        event = st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
            on_select="rerun",
            selection_mode="single-row",
            key=key,
        )
        selected_rows = event.selection.rows
        if selected_rows:
            return df.iloc[selected_rows[0]].to_dict()
    except TypeError:
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
        )
        selected = st.selectbox(
            f"Drill into {label}",
            options=df[label].tolist(),
            key=f"{key}_fallback",
        )
        return df[df[label] == selected].iloc[0].to_dict()

    return None


def _render_question_choices(row: dict) -> None:
    selected_answer = (row.get("selected_answer") or "").upper()
    correct_answer = (row.get("correct_answer") or "").upper()
    for letter in ["A", "B", "C", "D", "E"]:
        choice = row.get(f"choice_{letter.lower()}", "")
        if not choice:
            continue
        prefix = f"**{letter}.**"
        if letter == selected_answer and letter == correct_answer:
            st.success(f"{prefix} {choice} - correct selection")
        elif letter == selected_answer:
            st.error(f"{prefix} {choice} - your selection")
        elif letter == correct_answer:
            st.success(f"{prefix} {choice} - correct answer")
        else:
            st.write(f"{prefix} {choice}")


def _questions_for_scope(
    course_id: int | None = None,
    course_ids: list[int] | None = None,
) -> list[dict]:
    if course_ids is not None:
        rows = []
        for cid in course_ids:
            rows.extend(get_all_questions(course_id=cid))
        return rows
    if course_id is not None:
        return get_all_questions(course_id=course_id)
    return []


def _render_question_bank_drilldown(
    title: str,
    *,
    course_id: int | None = None,
    course_ids: list[int] | None = None,
) -> None:
    questions = _questions_for_scope(course_id=course_id, course_ids=course_ids)
    st.markdown(f"#### Drilldown: {title}")
    if not questions:
        st.caption("No questions are in this bank yet.")
        return

    df = pd.DataFrame(
        [
            {
                "Module": question.get("section_type") or "Unknown Module",
                "Question Type": question.get("question_type") or "Unknown",
                "Difficulty": DIFFICULTY_LABELS.get(
                    question.get("difficulty"),
                    question.get("difficulty") or "Unknown",
                ),
            }
            for question in questions
        ]
    )

    col_module, col_type, col_diff = st.columns(3)
    with col_module:
        st.dataframe(
            df["Module"].value_counts().rename_axis("Module").reset_index(name="Questions"),
            use_container_width=True,
            hide_index=True,
        )
    with col_type:
        st.dataframe(
            df["Question Type"].value_counts().rename_axis("Question Type").reset_index(name="Questions"),
            use_container_width=True,
            hide_index=True,
        )
    with col_diff:
        st.dataframe(
            df["Difficulty"].value_counts().rename_axis("Difficulty").reset_index(name="Questions"),
            use_container_width=True,
            hide_index=True,
        )


def _render_kpi_drilldown(
    metric_key: str | None,
    stats: dict,
    title: str,
    user_id: int,
    *,
    key_prefix: str,
    time_grain: str = "Daily",
    course_id: int | None = None,
    course_ids: list[int] | None = None,
    completed_from=None,
    completed_to=None,
) -> None:
    if metric_key is None:
        return

    metric_label = _metric_label(metric_key)
    st.markdown(f"### Drilldown: {title} / {metric_label}")
    st.caption("Click the selected KPI box again to close this drilldown.")

    if metric_key == "questions":
        _render_question_bank_drilldown(
            f"{title} / {metric_label}",
            course_id=course_id,
            course_ids=course_ids,
        )
    elif metric_key == "sessions":
        _render_daily_activity(
            user_id,
            title,
            key_prefix=f"{key_prefix}_sessions_activity",
            time_grain=time_grain,
            course_id=course_id,
            course_ids=course_ids,
            completed_from=completed_from,
            completed_to=completed_to,
        )
        selected_session = _render_score_trend(
            stats,
            key=f"{key_prefix}_{metric_key}_trend",
            heading=f"{metric_label} Score Trend",
            table_heading=f"{metric_label} Session Accuracy",
        )
        if selected_session:
            _render_answer_drilldown(
                user_id,
                title=f"{title} / {metric_label} / Session - {selected_session['Date']}",
                attempt_id=int(selected_session["Attempt ID"]),
                course_id=course_id,
                course_ids=course_ids,
                completed_from=completed_from,
                completed_to=completed_to,
            )
    elif metric_key == "answered":
        _render_answer_drilldown(
            user_id,
            title=f"{title} / {metric_label}",
            course_id=course_id,
            course_ids=course_ids,
            completed_from=completed_from,
            completed_to=completed_to,
        )
    else:
        selected_session = _render_score_trend(
            stats,
            key=f"{key_prefix}_{metric_key}_trend",
            heading=f"{metric_label} Trend",
            table_heading=f"{metric_label} Sessions",
        )
        if selected_session:
            _render_answer_drilldown(
                user_id,
                title=f"{title} / {metric_label} / Session - {selected_session['Date']}",
                attempt_id=int(selected_session["Attempt ID"]),
                course_id=course_id,
                course_ids=course_ids,
                completed_from=completed_from,
                completed_to=completed_to,
            )


def _render_answer_drilldown(
    user_id: int,
    *,
    title: str,
    attempt_id: int | None = None,
    course_id: int | None = None,
    course_ids: list[int] | None = None,
    section_type: str | None = None,
    question_type: str | None = None,
    difficulty: int | None = None,
    completed_from=None,
    completed_to=None,
) -> None:
    st.markdown(f"#### Drilldown: {title}")
    answer_filter = st.radio(
        "Answers",
        ["Missed only", "All", "Correct only"],
        horizontal=True,
        key=f"answer_filter_{title}_{course_id}_{section_type}_{question_type}_{difficulty}",
    )
    is_correct = None
    if answer_filter == "Missed only":
        is_correct = False
    elif answer_filter == "Correct only":
        is_correct = True

    rows = get_answer_drilldown(
        user_id,
        attempt_id=attempt_id,
        course_id=course_id,
        course_ids=course_ids,
        section_type=section_type,
        question_type=question_type,
        difficulty=difficulty,
        is_correct=is_correct,
        completed_from=completed_from,
        completed_to=completed_to,
    )
    if not rows:
        st.caption("No answered questions match this drilldown.")
        return

    detail_df = pd.DataFrame(
        [
            {
                "Date": str(row.get("completed_at") or "")[:16],
                "Course": row.get("course_title") or "Unknown Course",
                "Module": row.get("section_type") or "Unknown Module",
                "Question Type": row.get("question_type") or "Unknown",
                "Difficulty": DIFFICULTY_LABELS.get(row.get("difficulty"), row.get("difficulty")),
                "Result": "Correct" if row.get("is_correct") else "Missed",
                "Selected": row.get("selected_answer") or "-",
                "Correct": row.get("correct_answer") or "-",
                "_answer_id": row.get("answer_id"),
            }
            for row in rows
        ]
    )
    selected_answer_id = None
    try:
        event = st.dataframe(
            detail_df.drop(columns=["_answer_id"]),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"answer_rows_{title}_{course_id}_{section_type}_{question_type}_{difficulty}",
        )
        selected_rows = event.selection.rows
        if selected_rows:
            selected_answer_id = detail_df.iloc[selected_rows[0]]["_answer_id"]
    except TypeError:
        st.dataframe(detail_df.drop(columns=["_answer_id"]), use_container_width=True, hide_index=True)

    if selected_answer_id is None:
        st.caption("Select an answered question row to open the full question, answer choices, and explanation.")
        selected_rows = rows[:5]
    else:
        selected_rows = [row for row in rows if row.get("answer_id") == selected_answer_id]

    for idx, row in enumerate(selected_rows, start=1):
        status = "Correct" if row.get("is_correct") else "Missed"
        label = (
            f"{status} | {row.get('course_title') or 'Unknown Course'} | "
            f"{row.get('section_type') or 'Unknown Module'} | "
            f"{str(row.get('stimulus') or '')[:90]}"
        )
        with st.expander(label, expanded=selected_answer_id is not None or idx == 1):
            if row.get("passage"):
                st.markdown("**Passage**")
                st.markdown(row["passage"])
            st.markdown("**Question**")
            st.markdown(row.get("stimulus") or "")
            _render_question_choices(row)
            if row.get("explanation"):
                st.info(row["explanation"])
            meta = []
            if row.get("source"):
                meta.append(f"Source: {row['source']}")
            if row.get("tags"):
                meta.append(f"Tags: {row['tags']}")
            if meta:
                st.caption(" | ".join(meta))


def _render_breakdown_table(df: pd.DataFrame) -> None:
    st.dataframe(
        df.rename(columns={"% Correct": "Accuracy"}),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Accuracy": st.column_config.ProgressColumn(
                "Accuracy",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
            "Answered": st.column_config.NumberColumn("Answered", format="%d"),
            "Missed": st.column_config.NumberColumn("Missed", format="%d"),
        },
    )


def _breakdown_df(grouped: dict, label: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                label: name,
                **({"Course ID": values["course_id"]} if "course_id" in values else {}),
                "% Correct": values["pct"],
                "Answered": values["total"],
                "Missed": values["total"] - values["correct"],
            }
            for name, values in grouped.items()
        ]
    ).sort_values(["% Correct", "Answered"], ascending=[True, False])


def _render_course_accuracy(stats: dict) -> dict | None:
    st.markdown("### Accuracy by Course")
    acc_course = stats["accuracy_by_course"]
    if not acc_course:
        st.caption("No course-level answer data yet.")
        return None

    df_course = _breakdown_df(acc_course, "Course")
    fig_course = _accuracy_bar(
        df_course,
        "% Correct",
        "Course",
        hover_data={"Answered": True, "Missed": True, "% Correct": ":.1f"},
        custom_data=["Course", "Course ID"],
    )
    fig_course.update_layout(
        xaxis_range=[0, 100],
        yaxis=dict(categoryorder="array", categoryarray=df_course["Course"].tolist()[::-1]),
    )
    chart_event = st.plotly_chart(
        fig_course,
        use_container_width=True,
        on_select="rerun",
        selection_mode="points",
        key="course_accuracy_chart",
    )
    selected = _row_from_selection(chart_event, df_course, "Course")
    return selected or _render_selectable_breakdown_table(df_course, "course_accuracy_table", "Course")


def _course_card_rows(
    user_id: int,
    courses: list[dict],
    *,
    completed_from=None,
    completed_to=None,
) -> list[dict]:
    rows = []
    for index, course in enumerate(courses):
        course_id = int(course["id"])
        stats = get_dashboard_stats(
            user_id,
            course_id=course_id,
            completed_from=completed_from,
            completed_to=completed_to,
        )
        q_count = get_course_question_count(course_id)
        material_total, material_completed, material_pct = _materials_summary(user_id, [course_id])
        rows.append(
            {
                "display_order": index,
                "course": course,
                "course_id": course_id,
                "title": course["title"],
                "stats": stats,
                "q_count": q_count,
                "material_total": material_total,
                "material_completed": material_completed,
                "material_pct": material_pct,
                "sort_title": course["title"].lower(),
                "sort_questions": q_count,
                "sort_sessions": stats["total_attempts"],
                "sort_answered": stats["total_questions"],
                "sort_latest": _metric_sort_value(stats["latest_percent"]),
                "sort_best": _metric_sort_value(stats["best_percent"]),
                "sort_average": _metric_sort_value(stats["avg_percent"]),
                "sort_materials": material_pct,
            }
        )
    return rows


def _render_course_card_sort_controls(rows: list[dict]) -> list[dict]:
    sort_fields = {
        "Curriculum order": "display_order",
        "Course title": "sort_title",
        "Questions in bank": "sort_questions",
        "Sessions completed": "sort_sessions",
        "Total Qs answered": "sort_answered",
        "Latest score": "sort_latest",
        "Best score": "sort_best",
        "Avg score": "sort_average",
        "Materials progress": "sort_materials",
    }

    with st.container(border=True):
        st.markdown("#### Sort Courses")
        cols = st.columns([2, 1, 2, 1, 2, 1])
        level_1 = cols[0].selectbox(
            "Sort by",
            options=list(sort_fields.keys()),
            key="course_cards_sort_1",
        )
        direction_1 = cols[1].selectbox(
            "Order",
            ["Ascending", "Descending"],
            key="course_cards_sort_1_direction",
        )
        level_2 = cols[2].selectbox(
            "Then by",
            options=["None", *sort_fields.keys()],
            key="course_cards_sort_2",
        )
        direction_2 = cols[3].selectbox(
            "Order",
            ["Ascending", "Descending"],
            key="course_cards_sort_2_direction",
        )
        level_3 = cols[4].selectbox(
            "Then by",
            options=["None", *sort_fields.keys()],
            key="course_cards_sort_3",
        )
        direction_3 = cols[5].selectbox(
            "Order",
            ["Ascending", "Descending"],
            key="course_cards_sort_3_direction",
        )

    sort_levels = [
        (level_1, direction_1),
        (level_2, direction_2),
        (level_3, direction_3),
    ]
    sorted_rows = list(rows)
    for field_label, direction in reversed(sort_levels):
        if field_label == "None":
            continue
        sorted_rows.sort(
            key=lambda row: row[sort_fields[field_label]],
            reverse=(direction == "Descending"),
        )
    return sorted_rows


def _render_weakest_courses(
    user_id: int,
    courses: list[dict],
    *,
    completed_from=None,
    completed_to=None,
) -> dict | None:
    st.markdown("### Weakest Courses")
    st.caption(
        "Ranked by lowest latest score in the selected time frame. "
        "Ties use lower average score, then more answered questions."
    )
    rows = [
        row
        for row in _course_card_rows(
            user_id,
            courses,
            completed_from=completed_from,
            completed_to=completed_to,
        )
        if row["stats"]["latest_percent"] is not None
    ]
    if not rows:
        st.caption("No completed course sessions match this time frame yet.")
        return None

    weakest_rows = sorted(
        rows,
        key=lambda row: (
            row["stats"]["latest_percent"],
            row["stats"]["avg_percent"] if row["stats"]["avg_percent"] is not None else 101,
            -row["stats"]["total_questions"],
            row["title"].lower(),
        ),
    )[:3]

    display_df = pd.DataFrame(
        [
            {
                "Rank": rank,
                "Course": row["title"],
                "Latest Score": row["stats"]["latest_percent"],
                "Avg Score": row["stats"]["avg_percent"],
                "Sessions": row["stats"]["total_attempts"],
                "Answered": row["stats"]["total_questions"],
                "Questions in Bank": row["q_count"],
                "Course ID": row["course_id"],
            }
            for rank, row in enumerate(weakest_rows, start=1)
        ]
    )

    fig = px.bar(
        display_df.sort_values("Latest Score", ascending=False),
        x="Latest Score",
        y="Course",
        orientation="h",
        color="Latest Score",
        color_continuous_scale=["#d73027", "#fee090", "#1a9850"],
        range_color=[0, 100],
        text="Latest Score",
        custom_data=["Course ID", "Course"],
    )
    fig.update_layout(
        xaxis_range=[0, 100],
        margin=dict(l=0, r=0, t=10, b=0),
        coloraxis_showscale=False,
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="inside")
    apply_plotly_theme(fig)
    chart_event = st.plotly_chart(
        fig,
        use_container_width=True,
        on_select="rerun",
        selection_mode="points",
        key="weakest_courses_chart",
    )

    selected = None
    points = _selection_points(chart_event)
    if points:
        customdata = _point_customdata(points[0])
        if customdata:
            matches = display_df[display_df["Course ID"].astype(str) == str(customdata[0])]
            if not matches.empty:
                selected = matches.iloc[0].to_dict()

    table_selected = _render_selectable_breakdown_table(
        display_df,
        "weakest_courses_table",
        "Course",
    )
    return table_selected or selected


def _comparison_courses_for_active_course(active_course_id: int) -> tuple[str, list[dict]]:
    for curriculum in get_all_curriculums():
        courses = get_curriculum_courses(curriculum["id"])
        if any(course["id"] == active_course_id for course in courses):
            return curriculum["title"], courses
    return "Active Course", [get_course(active_course_id)]


def _render_curriculum_course_dashboards(
    user_id: int,
    courses: list[dict],
    *,
    time_grain: str = "Daily",
    completed_from=None,
    completed_to=None,
) -> None:
    st.markdown("### Course Dashboard Cards")
    course_rows = _render_course_card_sort_controls(
        _course_card_rows(
            user_id,
            courses,
            completed_from=completed_from,
            completed_to=completed_to,
        )
    )

    for row in course_rows:
        course = row["course"]
        course_id = row["course_id"]
        stats = row["stats"]
        q_count = row["q_count"]
        material_total = row["material_total"]
        material_completed = row["material_completed"]
        material_pct = row["material_pct"]

        with st.container(border=True):
            st.markdown(f"#### {course['title']}")

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            selected_metric = None
            metric_items = [
                ("questions", "Questions in Bank", q_count, None),
                ("sessions", "Sessions Completed", stats["total_attempts"], None),
                ("answered", "Total Qs Answered", stats["total_questions"], None),
                (
                    "latest",
                    "Latest Score",
                    _format_percent(stats["latest_percent"]),
                    _score_delta_label(stats),
                ),
                ("best", "Best Score", _format_percent(stats["best_percent"]), None),
                ("average", "Avg Score", _format_percent(stats["avg_percent"]), None),
            ]
            key_prefix = f"course_card_{course_id}"
            state_key = f"{key_prefix}_selected_kpi"
            for col, (metric_key, label, value, delta) in zip(
                [c1, c2, c3, c4, c5, c6],
                metric_items,
            ):
                button_label = f"{label}\n\n{value}"
                if delta:
                    button_label = f"{button_label}\n{delta}"
                with col:
                    if st.button(
                        button_label,
                        key=f"{key_prefix}_kpi_{metric_key}",
                        use_container_width=True,
                    ):
                        if st.session_state.get(state_key) == metric_key:
                            st.session_state[state_key] = None
                        else:
                            st.session_state[state_key] = metric_key
                    if st.session_state.get(state_key) == metric_key:
                        selected_metric = metric_key

            if material_total > 0:
                st.progress(
                    material_pct / 100,
                    text=(
                        f"Materials: {material_completed}/{material_total} completed "
                        f"({material_pct}%)"
                    ),
                )
            _render_kpi_drilldown(
                selected_metric,
                stats,
                course["title"],
                user_id,
                key_prefix=key_prefix,
                time_grain=time_grain,
                course_id=course_id,
                completed_from=completed_from,
                completed_to=completed_to,
            )


def _render_module_accuracy(stats: dict, key: str = "module_accuracy_table") -> dict | None:
    st.markdown("### Accuracy by Module")
    acc_module = stats["accuracy_by_module"]
    if not acc_module:
        st.caption("No module data yet.")
        return None

    df_module = _breakdown_df(acc_module, "Module")
    fig_module = _accuracy_bar(
        df_module,
        "% Correct",
        "Module",
        hover_data={"Answered": True, "Missed": True, "% Correct": ":.1f"},
        custom_data=["Module"],
    )
    fig_module.update_layout(
        xaxis_range=[0, 100],
        yaxis=dict(categoryorder="array", categoryarray=df_module["Module"].tolist()[::-1]),
    )
    chart_event = st.plotly_chart(
        fig_module,
        use_container_width=True,
        on_select="rerun",
        selection_mode="points",
        key=f"{key}_chart",
    )
    selected = _row_from_selection(chart_event, df_module, "Module")
    return selected or _render_selectable_breakdown_table(df_module, key, "Module")


def _render_type_and_difficulty(stats: dict) -> tuple[dict | None, dict | None]:
    selected_type = None
    selected_diff = None
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### Accuracy by Question Type")
        acc_type = stats["accuracy_by_type"]
        if acc_type:
            df_type = pd.DataFrame(
                [
                    {
                        "Question Type": qt,
                        "% Correct": value["pct"],
                        "Answered": value["total"],
                    }
                    for qt, value in acc_type.items()
                ]
            ).sort_values("% Correct")
            type_event = st.plotly_chart(
                _accuracy_bar(
                    df_type,
                    "% Correct",
                    "Question Type",
                    custom_data=["Question Type"],
                ),
                use_container_width=True,
                on_select="rerun",
                selection_mode="points",
                key="question_type_accuracy_chart",
            )
            selected_type = _row_from_selection(type_event, df_type, "Question Type")
            selected_type = _render_selectable_breakdown_table(
                df_type,
                "question_type_accuracy_table",
                "Question Type",
            ) or selected_type
        else:
            st.caption("No data yet.")

    with col_b:
        st.markdown("### Accuracy by Difficulty")
        acc_diff = stats["accuracy_by_diff"]
        if acc_diff:
            df_diff = pd.DataFrame(
                [
                    {
                        "Difficulty": DIFFICULTY_LABELS.get(d, str(d)),
                        "% Correct": value["pct"],
                        "_order": d,
                    }
                    for d, value in acc_diff.items()
                ]
            ).sort_values("_order")
            fig_diff = _accuracy_bar(
                df_diff,
                "Difficulty",
                "% Correct",
                orientation="v",
                custom_data=["Difficulty", "_order"],
            )
            fig_diff.update_layout(yaxis_range=[0, 100])
            diff_event = st.plotly_chart(
                fig_diff,
                use_container_width=True,
                on_select="rerun",
                selection_mode="points",
                key="difficulty_accuracy_chart",
            )
            df_diff_select = df_diff.rename(columns={"Difficulty": "Difficulty Label"})
            selected_diff = _row_from_selection(
                diff_event,
                df_diff_select,
                "Difficulty Label",
            )
            selected_diff = _render_selectable_breakdown_table(
                df_diff_select,
                "difficulty_accuracy_table",
                "Difficulty Label",
            ) or selected_diff
        else:
            st.caption("No data yet.")

    return selected_type, selected_diff


user_id = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
course_id = course_selector(user_id)

if course_id is None:
    page_header("📊 Dashboard", "Your performance at a glance")
    st.info("Choose an active course from the sidebar to start tracking your progress.")
    st.stop()

view_mode = st.radio(
    "Dashboard scope",
    ["Curriculum", "Course"],
    horizontal=True,
    index=0,
    key="dashboard_scope",
    label_visibility="collapsed",
)

if view_mode == "Course":
    course = get_course(course_id)
    title = course["title"] if course else "Unknown Course"
    report_sections = _dashboard_header("📊 Dashboard", f"Course: {title}", view_mode)
    time_context = _dashboard_time_controls("course_dashboard")

    stats = get_dashboard_stats(
        user_id,
        course_id=course_id,
        completed_from=time_context["completed_from"],
        completed_to=time_context["completed_to"],
    )
    q_count = get_course_question_count(course_id)
    material_total, material_completed, material_pct = _materials_summary(user_id, [course_id])

    selected_kpi = _render_kpis(
        stats,
        q_count,
        material_total,
        material_completed,
        material_pct,
        key_prefix="course_summary",
        show_materials=("Materials progress" in report_sections),
    )
    st.divider()

    _render_kpi_drilldown(
        selected_kpi,
        stats,
        title,
        user_id,
        key_prefix="course_summary",
        time_grain=time_context["grain"],
        course_id=course_id,
        completed_from=time_context["completed_from"],
        completed_to=time_context["completed_to"],
    )

    supplemental_sections = {"Review activity", "Question reports"}
    if stats["total_attempts"] == 0 and not (supplemental_sections & report_sections):
        st.info(
            f"No sessions completed for **{title}** yet. "
            "Head to **Practice Mode** or **Timed Exam** to get started."
        )
        st.stop()
    elif stats["total_attempts"] == 0:
        st.info(
            f"No completed practice sessions for **{title}** in this time frame. "
            "Showing any review activity below."
        )

    if not report_sections:
        st.info("Use **Report Builder** above to add charts and drilldowns.")

    if "Score trend analysis" in report_sections and "Performance overview" not in report_sections:
        selected_session = _render_score_trend(stats, key="course_standalone_score_trend")
        if selected_session:
            _render_answer_drilldown(
                user_id,
                title=f"Session - {selected_session['Date']}",
                attempt_id=int(selected_session["Attempt ID"]),
                course_id=course_id,
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )

    if "Daily activity" in report_sections:
        st.divider()
        _render_daily_activity(
            user_id,
            title,
            key_prefix="course_daily_activity",
            time_grain=time_context["grain"],
            course_id=course_id,
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )

    if "Review activity" in report_sections:
        st.divider()
        _render_review_activity(
            user_id,
            title,
            key_prefix="course_review_activity",
            time_grain=time_context["grain"],
            course_id=course_id,
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )

    if "Question reports" in report_sections:
        st.divider()
        _render_question_reports(
            title,
            key_prefix="course_question_reports",
            time_grain=time_context["grain"],
            course_id=course_id,
        )

    if "Weakest courses" in report_sections:
        st.divider()
        comparison_title, comparison_courses = _comparison_courses_for_active_course(course_id)
        st.caption(f"Comparing courses in: {comparison_title}")
        selected_weak_course = _render_weakest_courses(
            user_id,
            comparison_courses,
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )
        if selected_weak_course:
            selected_course_id = int(selected_weak_course["Course ID"])
            selected_course_stats = get_dashboard_stats(
                user_id,
                course_id=selected_course_id,
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )
            selected_session = _render_score_trend(
                selected_course_stats,
                key=f"course_scope_weakest_course_{selected_course_id}_trend",
                heading=f"{selected_weak_course['Course']} Score Trend",
                table_heading=f"{selected_weak_course['Course']} Sessions",
            )
            if selected_session:
                _render_answer_drilldown(
                    user_id,
                    title=f"{selected_weak_course['Course']} / Session - {selected_session['Date']}",
                    attempt_id=int(selected_session["Attempt ID"]),
                    course_id=selected_course_id,
                    completed_from=time_context["completed_from"],
                    completed_to=time_context["completed_to"],
                )

    if "Performance overview" in report_sections:
        selected_session = _render_trend_and_weak_list(
            stats,
            weak_key="weak_modules",
            label_key="module",
            heading="Module Weak Spots",
        )
        if selected_session:
            _render_answer_drilldown(
                user_id,
                title=f"Session - {selected_session['Date']}",
                attempt_id=int(selected_session["Attempt ID"]),
                course_id=course_id,
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )

    if "Accuracy by module" in report_sections:
        st.divider()
        selected_module = _render_module_accuracy(stats, key="course_module_accuracy_table")
        if selected_module:
            _render_answer_drilldown(
                user_id,
                title=f"Module - {selected_module['Module']}",
                course_id=course_id,
                section_type=selected_module["Module"],
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )

    if "Question type and difficulty" in report_sections:
        st.divider()
        selected_type, selected_diff = _render_type_and_difficulty(stats)
        if selected_type:
            _render_answer_drilldown(
                user_id,
                title=f"Question Type - {selected_type['Question Type']}",
                course_id=course_id,
                question_type=selected_type["Question Type"],
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )
        if selected_diff:
            _render_answer_drilldown(
                user_id,
                title=f"Difficulty - {selected_diff['Difficulty Label']}",
                course_id=course_id,
                difficulty=int(selected_diff["_order"]),
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )

else:
    curriculums = get_all_curriculums()
    if not curriculums:
        page_header("📊 Dashboard", "Curriculum view")
        st.info("No curriculums have been created yet.")
        st.stop()

    curriculum_courses = {
        curriculum["id"]: get_curriculum_courses(curriculum["id"])
        for curriculum in curriculums
    }
    default_index = 0
    for idx, curriculum in enumerate(curriculums):
        if any(course["id"] == course_id for course in curriculum_courses[curriculum["id"]]):
            default_index = idx
            break

    curriculum_id = st.selectbox(
        "Curriculum",
        options=[curriculum["id"] for curriculum in curriculums],
        index=default_index,
        format_func=lambda cid: next(
            curriculum["title"] for curriculum in curriculums
            if curriculum["id"] == cid
        ),
    )
    curriculum_title = next(
        curriculum["title"] for curriculum in curriculums
        if curriculum["id"] == curriculum_id
    )
    courses = curriculum_courses[curriculum_id]
    course_ids = [course["id"] for course in courses]

    report_sections = _dashboard_header(
        "📊 Dashboard",
        f"Curriculum: {curriculum_title}",
        view_mode,
    )
    time_context = _dashboard_time_controls("curriculum_dashboard")

    if not course_ids:
        st.info("This curriculum does not have any courses yet.")
        st.stop()

    stats = get_dashboard_stats(
        user_id,
        course_ids=course_ids,
        completed_from=time_context["completed_from"],
        completed_to=time_context["completed_to"],
    )
    q_count = sum(get_course_question_count(cid) for cid in course_ids)
    material_total, material_completed, material_pct = _materials_summary(user_id, course_ids)

    selected_kpi = None
    if "Course dashboard cards" not in report_sections:
        selected_kpi = _render_kpis(
            stats,
            q_count,
            material_total,
            material_completed,
            material_pct,
            key_prefix="curriculum_summary",
            show_materials=("Materials progress" in report_sections),
        )
        st.divider()

    if not report_sections:
        st.info("Use **Report Builder** above to add charts and drilldowns.")

    if "Course dashboard cards" in report_sections:
        _render_curriculum_course_dashboards(
            user_id,
            courses,
            time_grain=time_context["grain"],
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )
        st.markdown("### Curriculum Total")
        selected_kpi = _render_kpis(
            stats,
            q_count,
            material_total,
            material_completed,
            material_pct,
            key_prefix="curriculum_summary",
            show_materials=("Materials progress" in report_sections),
        )
        st.divider()

    _render_kpi_drilldown(
        selected_kpi,
        stats,
        curriculum_title,
        user_id,
        key_prefix="curriculum_summary",
        time_grain=time_context["grain"],
        course_ids=course_ids,
        completed_from=time_context["completed_from"],
        completed_to=time_context["completed_to"],
    )

    supplemental_sections = {"Review activity", "Question reports"}
    if stats["total_attempts"] == 0 and not (supplemental_sections & report_sections):
        st.info(
            f"No sessions completed for **{curriculum_title}** yet. "
            "Use Practice Mode or Curriculum Exam to generate performance data."
        )
        st.stop()
    elif stats["total_attempts"] == 0:
        st.info(
            f"No completed practice sessions for **{curriculum_title}** in this time frame. "
            "Showing any review activity below."
        )

    if "Score trend analysis" in report_sections and "Performance overview" not in report_sections:
        selected_session = _render_score_trend(stats, key="curriculum_standalone_score_trend")
        if selected_session:
            _render_answer_drilldown(
                user_id,
                title=f"Curriculum Session - {selected_session['Date']}",
                attempt_id=int(selected_session["Attempt ID"]),
                course_ids=course_ids,
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )

    if "Daily activity" in report_sections:
        st.divider()
        _render_daily_activity(
            user_id,
            curriculum_title,
            key_prefix="curriculum_daily_activity",
            time_grain=time_context["grain"],
            course_ids=course_ids,
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )

    if "Review activity" in report_sections:
        st.divider()
        _render_review_activity(
            user_id,
            curriculum_title,
            key_prefix="curriculum_review_activity",
            time_grain=time_context["grain"],
            course_ids=course_ids,
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )

    if "Question reports" in report_sections:
        st.divider()
        _render_question_reports(
            curriculum_title,
            key_prefix="curriculum_question_reports",
            time_grain=time_context["grain"],
            course_ids=course_ids,
        )

    if "Weakest courses" in report_sections:
        st.divider()
        selected_weak_course = _render_weakest_courses(
            user_id,
            courses,
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )
        if selected_weak_course:
            selected_course_id = int(selected_weak_course["Course ID"])
            selected_course_stats = get_dashboard_stats(
                user_id,
                course_id=selected_course_id,
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )
            selected_session = _render_score_trend(
                selected_course_stats,
                key=f"weakest_course_{selected_course_id}_trend",
                heading=f"{selected_weak_course['Course']} Score Trend",
                table_heading=f"{selected_weak_course['Course']} Sessions",
            )
            if selected_session:
                _render_answer_drilldown(
                    user_id,
                    title=f"{selected_weak_course['Course']} / Session - {selected_session['Date']}",
                    attempt_id=int(selected_session["Attempt ID"]),
                    course_id=selected_course_id,
                    completed_from=time_context["completed_from"],
                    completed_to=time_context["completed_to"],
                )

    if "Performance overview" in report_sections:
        selected_session = _render_trend_and_weak_list(
            stats,
            weak_key="weak_courses",
            label_key="course",
            heading="Course Weak Spots",
        )
        if selected_session:
            _render_answer_drilldown(
                user_id,
                title=f"Curriculum Session - {selected_session['Date']}",
                attempt_id=int(selected_session["Attempt ID"]),
                course_ids=course_ids,
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )

    if "Accuracy by course" in report_sections:
        st.divider()
        selected_course = _render_course_accuracy(stats)
        if selected_course:
            selected_course_id = int(selected_course["Course ID"])
            selected_course_stats = get_dashboard_stats(
                user_id,
                course_id=selected_course_id,
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )
            st.markdown(f"### Course Drilldown: {selected_course['Course']}")
            selected_course_module = _render_module_accuracy(
                selected_course_stats,
                key=f"curriculum_course_{selected_course_id}_module_accuracy_table",
            )
            if selected_course_module:
                _render_answer_drilldown(
                    user_id,
                    title=f"{selected_course['Course']} / {selected_course_module['Module']}",
                    course_id=selected_course_id,
                    section_type=selected_course_module["Module"],
                    completed_from=time_context["completed_from"],
                    completed_to=time_context["completed_to"],
                )
            else:
                _render_answer_drilldown(
                    user_id,
                    title=f"Course - {selected_course['Course']}",
                    course_id=selected_course_id,
                    completed_from=time_context["completed_from"],
                    completed_to=time_context["completed_to"],
                )

        drill_course_id = st.selectbox(
            "Drill into course",
            options=course_ids,
            format_func=lambda cid: next(course["title"] for course in courses if course["id"] == cid),
        )
        selected_course_title = next(course["title"] for course in courses if course["id"] == drill_course_id)
        _render_answer_drilldown(
            user_id,
            title=f"Course - {selected_course_title}",
            course_id=drill_course_id,
            completed_from=time_context["completed_from"],
            completed_to=time_context["completed_to"],
        )

    if "Accuracy by module" in report_sections:
        st.divider()
        selected_module = _render_module_accuracy(stats, key="curriculum_module_accuracy_table")
        if selected_module:
            _render_answer_drilldown(
                user_id,
                title=f"Curriculum Module - {selected_module['Module']}",
                course_ids=course_ids,
                section_type=selected_module["Module"],
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )

    if "Question type and difficulty" in report_sections:
        st.divider()
        selected_type, selected_diff = _render_type_and_difficulty(stats)
        if selected_type:
            _render_answer_drilldown(
                user_id,
                title=f"Curriculum Question Type - {selected_type['Question Type']}",
                course_ids=course_ids,
                question_type=selected_type["Question Type"],
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )
        if selected_diff:
            _render_answer_drilldown(
                user_id,
                title=f"Curriculum Difficulty - {selected_diff['Difficulty Label']}",
                course_ids=course_ids,
                difficulty=int(selected_diff["_order"]),
                completed_from=time_context["completed_from"],
                completed_to=time_context["completed_to"],
            )
