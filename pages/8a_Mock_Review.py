"""Automated mock schedule and review queue."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
from src.mock_review_ui import review_link, history_table, item_sessions, open_attempt, review_queue_table

from src.auth import require_login
from src.exam_planning import get_exam_plan, exam_countdown, render_exam_settings
from src.mock_review import get_review_schedule
from src.mock_review import (
    AUTO_STATUS,
    get_current_review_mock,
    get_mock_review_items,
    get_mock_schedule,
    get_next_mock_summary,
    get_review_module_plan,
    get_review_window_practice_sessions,
    get_window_summary,
    save_review_module_plan,
    save_mock_schedule,
    save_mock_scores,
    sync_mock_reviews,
    update_review_item,
)
from src.database import (
    get_all_curriculums,
    get_course_modules,
    get_curriculum_courses,
    get_distinct_values,
    get_materials,
)
from src.utils import format_module_label, module_sort_key, page_header, sidebar_nav


st.set_page_config(page_title="Mock Review · StudyForge", page_icon="🗓️", layout="wide")


user_id = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

if st.query_params.get("attempt"):
    open_attempt(user_id, st.query_params["attempt"])

sync_mock_reviews(user_id)
summary = get_next_mock_summary(user_id)
current_review = get_current_review_mock(user_id)
review_title = "🗓️ Mock Review"
review_subtitle = "Schedule mocks once; StudyForge plans and tracks the review work"
if current_review:
    review_number = current_review["mock_label"].removeprefix("Mock ")
    review_title = f"🗓️ Mock Review {review_number}"
    review_subtitle = (
        f"Review window: {current_review['window_start'].strftime('%B %d, %Y')} through "
        f"{(current_review['window_end'] - pd.Timedelta(days=1)).strftime('%B %d, %Y')}"
    )
page_header(review_title, review_subtitle)
exam_plan = get_exam_plan(user_id)
if exam_plan:
    days, appointment = exam_countdown(exam_plan)
    st.metric("Days till exam", days, help=appointment)
    st.caption(f"Actual exam: {appointment}")
render_exam_settings(user_id, expanded=False)

from src.study_progress import render_course_progress
from src.database import get_enrolled_courses
render_course_progress(user_id, [c["id"] for c in get_enrolled_courses(user_id)], review_id=current_review["id"] if current_review else None)

if st.query_params.get("item"):
    selected_item = next((item for item in get_mock_review_items(user_id, status="all")
                          if str(item["id"]) == st.query_params["item"]), None)
    st.markdown(review_link("← Back to Mock Review"), unsafe_allow_html=True)
    if selected_item:
        st.subheader(selected_item["topic_display"])
        sessions = item_sessions(selected_item, get_review_window_practice_sessions(
            user_id, selected_item["mock_schedule_id"], include_exams=False))
        if st.query_params.get("scope") == "completed":
            sessions = [session for session in sessions if session.get("completed_at")]
        st.caption("Choose an exam using its status, questions, or score link. In-progress exams resume where you left off.")
        c1, c2, c3 = st.columns(3)
        c1.metric("Review Count", len({s["attempt_id"] for s in sessions if s.get("completed_at")}))
        c2.metric("Questions", sum(s["questions"] for s in sessions))
        completed = [s for s in sessions if s.get("completed_at")]
        scored = sum(s["questions"] for s in completed)
        c3.metric("Retest Score", f"{100 * sum(s['correct'] for s in completed) / scored:.1f}%" if scored else "—")
        history_table(sessions)
    else:
        st.error("This review item is no longer available.")
    st.stop()

if summary:
    st.markdown("### Next Mock Countdown")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Next Mock Exam", summary["label"])
    c2.metric("Scheduled", summary["scheduled_date"].strftime("%B %d, %Y"))
    c3.metric("Days Remaining", summary["days_remaining"])
    c4.metric(
        "Review Items Remaining",
        summary["review_items_remaining"],
        delta=summary["review_progress_label"],
        delta_color="off",
    )
else:
    st.info("Add your upcoming mock dates below to start the automated plan.")

st.markdown("### Mock exam scores")
score_schedule = get_mock_schedule(user_id)
recorded_scores = [row for row in score_schedule if row.get("manual_score") is not None]
if recorded_scores:
    latest_score = recorded_scores[-1]
    st.metric("Latest recorded grade", f"{latest_score['manual_score']:.2f}%")
    st.caption(
        f"{latest_score['mock_label']} · {pd.Timestamp(latest_score['scheduled_date']).strftime('%B %d, %Y')}"
        + (f" · {latest_score['score_provider']}" if latest_score.get("score_provider") else "")
    )
else:
    st.caption("No mock scores entered yet.")
if score_schedule:
    with st.expander("Enter or edit mock scores", expanded=not recorded_scores):
        st.caption("Enter the percentage reported by your exam provider. Leave scores blank until available; clear a score to remove it.")
        with st.form("mock_scores_form"):
            score_frame = pd.DataFrame([
                {"Mock": row["mock_label"], "Scheduled Date": pd.Timestamp(row["scheduled_date"]),
                 "Score (%)": row.get("manual_score"), "Provider": row.get("score_provider") or ""}
                for row in score_schedule
            ])
            score_frame["Score (%)"] = score_frame["Score (%)"].astype(float)
            edited_scores = st.data_editor(
                score_frame, hide_index=True, use_container_width=True,
                disabled=["Mock", "Scheduled Date"],
                column_config={
                    "Scheduled Date": st.column_config.DateColumn(format="MMMM DD, YYYY"),
                    "Score (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.01, format="%.2f%%"),
                    "Provider": st.column_config.TextColumn(help="For example, Kaplan Schweser"),
                },
                key="mock_scores_editor",
            )
            if st.form_submit_button("Save mock scores", type="primary", use_container_width=True):
                try:
                    save_mock_scores(user_id, [
                        {"id": mock["id"], "manual_score": None if pd.isna(edited["Score (%)"]) else float(edited["Score (%)"]),
                         "score_provider": edited["Provider"]}
                        for mock, edited in zip(score_schedule, edited_scores.to_dict("records"))
                    ])
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["mock_scores_saved"] = True
                    st.rerun()
    if st.session_state.pop("mock_scores_saved", False):
        st.success("Mock scores saved.")
else:
    st.info("Add mock dates below to start recording grades.")

schedule_tab, modules_tab, review_tab = st.tabs(
    ["Mock Schedule", "Review Modules", "Review Queue"],
    key="mock_review_tabs", default="Review Queue",
)

with schedule_tab:
    st.markdown("### Mock dates")
    st.caption(
        "Enter only scheduled exam dates. Add or delete rows as plans change; mock labels, "
        "review windows, deadlines, and completion matching are automatic."
    )
    schedule = get_mock_schedule(user_id)
    schedule_df = pd.DataFrame(
        {"Scheduled Date": [pd.to_datetime(row["scheduled_date"]) for row in schedule]}
    )
    if schedule_df.empty:
        schedule_df = pd.DataFrame({"Scheduled Date": pd.Series(dtype="datetime64[ns]")})
    edited_schedule = st.data_editor(
        schedule_df,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        column_config={
            "Scheduled Date": st.column_config.DateColumn(
                "Scheduled Date",
                format="MMMM DD, YYYY",
                required=True,
            )
        },
        key="mock_schedule_editor",
    )
    if st.button("Save mock dates", type="primary", use_container_width=True):
        dates = []
        invalid = False
        for value in edited_schedule.get("Scheduled Date", []):
            if pd.isna(value):
                invalid = True
                continue
            dates.append(pd.Timestamp(value).date())
        if invalid:
            st.error("Every schedule row needs a date. Complete or delete the blank row.")
        elif len(dates) != len(set(dates)):
            st.error("Each mock needs a unique scheduled date.")
        elif exam_plan and any(d.isoformat() >= exam_plan['exam_date'] for d in dates):
            st.error("All mock exams must be before your actual exam date.")
        else:
            save_mock_schedule(user_id, dates)
            sync_mock_reviews(user_id)
            st.success("Mock schedule saved and review plan refreshed.")
            st.rerun()

    if exam_plan:
        st.info(f"🏁 Actual exam · {exam_countdown(exam_plan)[1]} — final schedule milestone")
        st.caption("The final mock's review window ends the day before this exam.")
    windows = get_window_summary(user_id)
    if windows:
        st.markdown("### Review window reconciliation")
        st.dataframe(
            pd.DataFrame([
                {
                    "Mock": row["mock_label"],
                    "Days Until Next Mock / Exam": row["days_until_next_mock"],
                    "Days Allocated": row["days_allocated"],
                    "Unallocated Buffer": row["unallocated_buffer"],
                }
                for row in windows
            ]),
            hide_index=True,
            use_container_width=True,
        )

with modules_tab:
    st.markdown("### Current review plan")
    st.caption(
        "Keep the full plan for each mock here. Add a row to choose a module or reading; "
        "select a row to delete it. Save your changes before switching mocks or curriculums."
    )
    schedule = get_mock_schedule(user_id)
    plannable_mocks = get_review_schedule(user_id)[:-1]
    curriculums = get_all_curriculums()
    if not plannable_mocks:
        st.info("Add a mock date and an actual exam appointment (or a second mock) before selecting review modules.")
    elif not curriculums:
        st.info("Create a curriculum and add its courses before selecting review modules.")
    else:
        today = pd.Timestamp.today().date()
        default_mock_index = 0
        for index, mock in enumerate(plannable_mocks):
            if pd.Timestamp(mock["scheduled_date"]).date() <= today:
                default_mock_index = index
        mock_id = st.selectbox(
            "Review after",
            options=[mock["id"] for mock in plannable_mocks],
            index=default_mock_index,
            format_func=lambda selected_id: next(
                f"{mock['mock_label']} · {pd.Timestamp(mock['scheduled_date']).strftime('%B %d, %Y')}"
                for mock in plannable_mocks if mock["id"] == selected_id
            ),
            key="mock_review_module_mock",
        )
        saved_plan = get_review_module_plan(user_id, mock_id)
        curriculum_ids = [curriculum["id"] for curriculum in curriculums]
        saved_curriculum_id = saved_plan.get("curriculum_id")
        curriculum_index = (
            curriculum_ids.index(saved_curriculum_id)
            if saved_curriculum_id in curriculum_ids else 0
        )
        curriculum_id = st.selectbox(
            "Curriculum",
            options=curriculum_ids,
            index=curriculum_index,
            format_func=lambda selected_id: next(
                curriculum["title"] for curriculum in curriculums
                if curriculum["id"] == selected_id
            ),
            key=f"mock_review_curriculum_{mock_id}",
        )
        courses = get_curriculum_courses(curriculum_id)
        if not courses:
            st.warning("This curriculum does not contain any active courses.")
        else:
            catalog = []
            for course in courses:
                course_id = int(course["id"])
                configured_modules = {
                    str(module.get("name") or "").strip()
                    for module in get_course_modules(course_id)
                    if str(module.get("name") or "").strip()
                }
                question_modules = {
                    str(module or "").strip()
                    for module in get_distinct_values("section_type", course_id=course_id)
                    if str(module or "").strip()
                }
                module_options = sorted(
                    configured_modules | question_modules,
                    key=module_sort_key,
                )
                for module_name in module_options:
                    normalized = " ".join(module_name.casefold().split())
                    catalog.append({
                        "id": f"module:{course_id}:{normalized}",
                        "course_id": course_id,
                        "Course": course["title"],
                        "Section": module_name,
                        "Type": "Module",
                        "Topic/Reading": format_module_label(module_name),
                        "topic_name": module_name,
                        "match_topic": module_name,
                    })
                for material in get_materials(course_id):
                    title = str(material.get("title") or "").strip()
                    if not title:
                        continue
                    parent_module = str(material.get("module_name") or "").strip()
                    section = parent_module or str(material.get("material_section") or "Course Materials")
                    catalog.append({
                        "id": f"material:{material['id']}",
                        "course_id": course_id,
                        "Course": course["title"],
                        "Section": section,
                        "Type": str(material.get("material_type") or "Reading"),
                        "Topic/Reading": title,
                        "topic_name": title,
                        # A reading is completed by practice for its parent module.
                        "match_topic": parent_module or title,
                    })

            if not catalog:
                st.warning("No modules or course readings are configured in this curriculum yet.")

            # The editor always contains the whole saved plan. Catalog choices are
            # stable: searching a dropdown cannot narrow or replace its existing rows.
            saved_items = saved_plan.get("selection_items", [])
            if not saved_plan.get("configured"):
                saved_items = [
                    item for item in get_mock_review_items(user_id, status="all")
                    if item["mock_schedule_id"] == mock_id
                ]
            saved_labels = []
            def choice_label(row):
                return f"{row['Course']} · {row['Type']} · {row['topic_name']}"

            choices = {choice_label(row): row for row in catalog}
            for saved in saved_items:
                saved_name = " ".join(str(saved["topic_name"]).casefold().split())
                saved_match = saved.get("match_topic_key") or saved_name
                matching = next((
                    row for row in catalog
                    if row["course_id"] == saved["course_id"]
                    and " ".join(row["topic_name"].casefold().split()) == saved_name
                    and " ".join(row["match_topic"].casefold().split()) == saved_match
                ), None)
                if matching is None:
                    # Keep saved readings even if their source catalog was renamed
                    # or removed. Only deleting a plan row should remove a choice.
                    matching = {
                        "course_id": saved["course_id"],
                        "Course": next((course["title"] for course in courses
                                        if course["id"] == saved["course_id"]),
                                       f"Course {saved['course_id']}"),
                        "Type": "Saved item",
                        "topic_name": saved["topic_name"],
                        "match_topic": saved_match,
                    }
                label = choice_label(matching)
                choices[label] = matching
                saved_labels.append(label)

            with st.form(f"mock_review_plan_form_{mock_id}_{curriculum_id}"):
                edited_plan = st.data_editor(
                    pd.DataFrame({"Module / reading": pd.Series(saved_labels, dtype="str")}),
                    num_rows="dynamic",
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Module / reading": st.column_config.SelectboxColumn(
                            "Course · Type · Module / reading",
                            options=list(choices),
                            required=True,
                            width="large",
                            help="Add a row, then type in its dropdown to find a module or reading.",
                        ),
                    },
                    key=f"mock_review_plan_editor_{mock_id}_{curriculum_id}",
                )
                save_plan = st.form_submit_button(
                    "Save review plan", type="primary", use_container_width=True,
                )
            st.caption(
                "This is the complete plan, including completed work. "
                "Track outstanding and completed items in Review Queue."
            )
            if save_plan:
                labels = edited_plan["Module / reading"].tolist()
                if any(pd.isna(label) or label not in choices for label in labels):
                    st.error("Choose a module or reading for every row, or delete the blank row.")
                else:
                    selected_by_course: dict[int, list[dict]] = {}
                    for label in dict.fromkeys(labels):
                        row = choices[label]
                        selected_by_course.setdefault(row["course_id"], []).append({
                            "topic_name": row["topic_name"],
                            "match_topic": row["match_topic"],
                        })
                    try:
                        save_review_module_plan(user_id, mock_id, curriculum_id, selected_by_course)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        sync_mock_reviews(user_id)
                        st.rerun()

with review_tab:
    st.markdown("### Review Queue")
    all_review_items = get_mock_review_items(user_id, status="all")
    queue_schedule = get_mock_schedule(user_id, include_inactive=True)
    mock_labels = {mock["id"]: mock["mock_label"] for mock in queue_schedule}
    queue_mock_options = [None, *mock_labels]
    queue_left, queue_right = st.columns(2)
    queue_mock_id = queue_left.selectbox(
        "Mock", options=queue_mock_options,
        index=queue_mock_options.index(current_review["id"]) if current_review else 0,
        format_func=lambda value: mock_labels.get(value, "All mocks"),
        key="mock_review_queue_mock",
    )
    scoped_items = [item for item in all_review_items
                    if queue_mock_id is None or item["mock_schedule_id"] == queue_mock_id]
    view = queue_right.selectbox(
        "Show", ["Outstanding", "All", "Complete", "Pending", "In Progress"],
        key="mock_review_queue_status",
    )
    completed_count = sum(item["review_status"] == "Complete" for item in scoped_items)
    total_count = len(scoped_items)
    total_col, outstanding_col, completed_col = st.columns(3)
    total_col.metric("Total review items", total_count)
    outstanding_col.metric("Outstanding", total_count - completed_count)
    completed_col.metric("Completed", completed_count)
    if total_count:
        st.progress(completed_count / total_count,
                    text=f"{completed_count} of {total_count} review items completed")
    items = [item for item in scoped_items
             if view == "All"
             or (view == "Outstanding" and item["review_status"] != "Complete")
             or item["review_status"] == view]
    if not items:
        if all_review_items:
            st.info(
                "No review items match this view. Switch Show to All or choose another mock."
            )
        elif get_mock_schedule(user_id):
            st.info(
                "No review items match this filter. Choose modules in Review Modules, or "
                "complete a scheduled Full Exam or Weighted Mock for automatic detection."
            )
        else:
            st.info("Add mock dates in the Mock Schedule tab first.")
    else:
        window_sessions = {item["mock_schedule_id"]: get_review_window_practice_sessions(
            user_id, item["mock_schedule_id"], include_exams=False)
            for item in {row["mock_schedule_id"]: row for row in items}.values()}
        review_queue_table(items, window_sessions)
        st.caption(
            "Review Count = completed attempts for this topic. Questions includes all attempts; "
            "Retest Score combines completed attempts, weighted by question count. "
            "Click a status, count, question total, or score to open the contributing exams."
        )

        with st.expander("Manual status override or notes"):
            item_map = {
                item["id"]: f"{item['mock_label']} · {item['topic_display']}"
                for item in items
            }
            selected_id = st.selectbox(
                "Review item",
                options=list(item_map),
                format_func=lambda item_id: item_map[item_id],
            )
            selected = next(item for item in items if item["id"] == selected_id)
            override_options = ["Automatic", *AUTO_STATUS]
            current_override = selected.get("status_override") or "Automatic"
            override = st.selectbox(
                "Review Status",
                override_options,
                index=override_options.index(current_override),
                help="Automatic follows Test Bank history. Choose another value only when needed.",
            )
            notes = st.text_area("Notes", value=selected.get("notes") or "")
            if st.button("Save override and notes", use_container_width=True):
                update_review_item(
                    user_id,
                    selected_id,
                    status_override=None if override == "Automatic" else override,
                    notes=notes,
                )
                st.success("Review item updated.")
                st.rerun()

    history_mock_ids = [queue_mock_id] if queue_mock_id else list(mock_labels)
    for history_mock_id in history_mock_ids:
        current_sessions = get_review_window_practice_sessions(user_id, history_mock_id, include_exams=False)
        with st.expander(
            f"Practice history inside {mock_labels[history_mock_id]} review window "
            f"({len({s['attempt_id'] for s in current_sessions})} attempts)",
            expanded=True,
        ):
            if current_sessions:
                history_table(current_sessions)
                if not all_review_items:
                    st.warning(
                        "Practice was found, but no review modules are saved for this mock. "
                        "Select the matching modules in Review Modules, then view All to see "
                        "items that were completed by those sessions."
                    )
                elif not items:
                    st.info(
                        "The mapped review items are complete and hidden by the current filter. "
                        "Set Show to All or Complete to display them."
                    )
            else:
                st.caption("No practice activity falls inside this review window yet.")
