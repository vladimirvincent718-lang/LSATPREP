"""Linked review tables and authenticated attempt drill-down."""

from html import escape
from urllib.parse import urlencode, quote

import streamlit as st
import pandas as pd

from src.database import get_connection, get_attempt_answers


def review_link(label, **params):
    return f'<a target="_self" href="a_Mock_Review?{escape(urlencode(params), quote=True)}">{escape(str(label))}</a>'


def table_link(label, **params):
    """Keep the visible cell label separate from the route in the URL fragment."""
    return f"a_Mock_Review?{urlencode(params)}#{quote(str(label), safe='')}"


def linked_table(rows, link_columns=()):
    if not rows:
        st.info("No attempts match this item in its review window yet.")
        return
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, use_container_width=True,
        column_config={column: st.column_config.LinkColumn(
            column, display_text=r"#(.*)$", help="Open the exam(s) behind this value.",
        ) for column in link_columns},
    )


def history_table(sessions):
    from src.utils import format_module_label
    rows = []
    for session in sessions:
        values = {
            "Date": session.get("activity_date") or "—",
            "Course": session.get("course_title") or "Unknown Course",
            "Module": format_module_label(session.get("module_name") or "General Review"),
            "Type": str(session.get("mode") or "practice").replace("_", " ").title(),
            "Status": session["status"],
            "Review Count": int(bool(session.get("completed_at"))),
            "Questions": session.get("questions") or 0,
            "Score": f"{session['score']:.1f}%" if session.get("score") is not None else "—",
        }
        rows.append({key: table_link(value, attempt=session["attempt_id"]) if key in {
            "Status", "Review Count", "Questions", "Score"} else value for key, value in values.items()})
    linked_table(rows, ("Status", "Review Count", "Questions", "Score"))


def review_table_rows(items, window_sessions):
    rows = []
    for item in items:
        sessions = item_sessions(item, window_sessions[item["mock_schedule_id"]])
        completed = [s for s in sessions if s.get("completed_at")]
        scored_questions = sum(s["questions"] for s in completed)
        score = (100 * sum(s["correct"] for s in completed) / scored_questions
                 if scored_questions else None)
        # Status opens a single matching attempt directly, or a chooser when
        # several attempts contributed. Aggregates always show their evidence.
        target = {"attempt": sessions[0]["attempt_id"]} if len(sessions) == 1 else {"item": item["id"]}
        rows.append({
            "Mock": item["mock_label"],
            "Review Deadline": item.get("review_deadline") or "—",
            "Days Allocated": int(item.get("days_allocated") or 0),
            "Course": item.get("course_title") or "Unknown Course",
            "Topic/Reading": item.get("topic_name") or item["topic_display"],
            "Review Status": table_link(item["review_status"], **target),
            "Review Count": table_link(len({s["attempt_id"] for s in completed}), item=item["id"], scope="completed"),
            "Questions": table_link(sum(s["questions"] for s in sessions), item=item["id"]),
            "Date Reviewed": item.get("date_reviewed") or "—",
            "Retest Score": table_link(f"{score:.1f}%" if score is not None else "—", item=item["id"], scope="completed"),
            "Notes": item.get("notes") or "",
        })
    return rows


def course_review_groups(items):
    """Roll up the filtered queue by course identity, preserving reading order."""
    groups = {}
    for item in items:
        course_id = item.get("course_id")
        group = groups.setdefault(course_id, {
            "course_id": course_id,
            "course_title": item.get("course_title") or "Unknown Course",
            "items": [], "complete": 0, "outstanding": 0,
        })
        group["items"].append(item)
        group["complete" if item["review_status"] == "Complete" else "outstanding"] += 1
    return list(groups.values())


def review_queue_table(items, window_sessions, *, user_id=None, mock_schedule_id=None, progress_items=None,
                       render_course_queue=None, task_rows=None):
    """A compact course outline with independently expandable detail tables."""
    from src.mock_review import get_review_course_order, move_review_course

    can_reorder = user_id is not None and mock_schedule_id is not None
    if can_reorder:
        order = get_review_course_order(user_id, mock_schedule_id)
        ranks = {course_id: index for index, course_id in enumerate(order)}
        items = sorted(items, key=lambda item: ranks.get(item.get("course_id"), len(ranks)))
    view_col, expand_col, collapse_col = st.columns([3, 1, 1], vertical_alignment="bottom")
    view = view_col.radio("Queue layout", ["By course", "All readings"],
                          horizontal=True, key="mock_review_queue_layout")
    links = ("Review Status", "Review Count", "Questions", "Retest Score")
    if view == "All readings":
        linked_table(review_table_rows(items, window_sessions), links)
        return

    # Changing the generation resets all expander defaults; otherwise stable keys
    # let each course retain its own open/closed state across ordinary reruns.
    for column, label, expanded in ((expand_col, "Expand all", True),
                                    (collapse_col, "Collapse all", False)):
        if column.button(label, key=f"mock_review_{label}", use_container_width=True):
            st.session_state["mock_review_courses_expanded"] = expanded
            st.session_state["mock_review_courses_generation"] = (
                st.session_state.get("mock_review_courses_generation", 0) + 1)
    generation = st.session_state.get("mock_review_courses_generation", 0)
    expanded = st.session_state.get("mock_review_courses_expanded", False)
    groups = course_review_groups(progress_items if render_course_queue and progress_items is not None else items)
    if can_reorder:
        groups.sort(key=lambda group: ranks.get(group['course_id'],len(ranks)))
    progress_groups = {g['course_id']: g for g in course_review_groups(
        progress_items if progress_items is not None else items)}
    st.caption(f"{len(groups)} courses · {len(items)} review items in the current filters. "
               "Open a course to see its topics/readings.")
    if can_reorder:
        st.caption("Use ↑ and ↓ to put courses in priority order. Changes save automatically for this mock. "
                   "Review deadlines stay the same.")
    elif user_id is not None:
        st.caption("Select one mock above to arrange its courses by priority.")
    for index, group in enumerate(groups):
        count = len(group["items"])
        progress_group = progress_groups[group['course_id']]
        progress_total = len(progress_group['items'])
        progress_complete = progress_group['complete']
        course_tasks = [t for t in (task_rows or []) if t['course_id']==group['course_id']]
        label = (f"{group['course_title']} · {count} {'item' if count == 1 else 'items'}"
                 f" · {progress_complete / progress_total:.0%} complete overall"
                 f" · {group['outstanding']} outstanding · {group['complete']} complete")
        if course_tasks:
            progress_total = len(course_tasks)
            progress_complete = sum(bool(t['completed']) for t in course_tasks)
            label = (f"{group['course_title']} · {progress_total} tasks · {count} {'topic' if count == 1 else 'topics'}"
                     f" · {progress_complete/progress_total:.0%} queue complete"
                     f" · {progress_total-progress_complete} tasks left")
        if can_reorder:
            body, up, down = st.columns([14, 1, 1], vertical_alignment="top")
            for column, direction, offset in ((up, "↑", -1), (down, "↓", 1)):
                target = index + offset
                disabled = (not 0 <= target < len(groups) or group['course_id'] is None
                            or (0 <= target < len(groups) and groups[target]['course_id'] is None))
                if column.button(direction,
                                 key=f"review_move_{mock_schedule_id}_{group['course_id']}_{offset}",
                                 help=f"Move {group['course_title']} {'up' if offset < 0 else 'down'}",
                                 disabled=disabled, use_container_width=True):
                    move_review_course(user_id, mock_schedule_id, group['course_id'],
                                       groups[target]['course_id'])
                    st.rerun()
        else:
            body = st
        # The heading itself is the progress track, including when collapsed.
        progress_key = f"review_heading_{mock_schedule_id}_{group['course_id']}"
        percent = 100 * progress_complete / progress_total
        st.markdown(f'''<style>
            .st-key-{progress_key} [data-testid="stExpander"] details > summary {{
                background: linear-gradient(to right, rgba(16,150,136,.30) 0%,
                    rgba(16,150,136,.30) {percent:.3f}%,
                    rgba(120,145,170,.09) {percent:.3f}%, rgba(120,145,170,.09) 100%);
                border-radius: 6px;
            }}
            </style>''', unsafe_allow_html=True)
        with body.container(key=progress_key):
            section = st.expander(label, expanded=expanded,
                                  key=f"mock_review_course_{mock_schedule_id}_{group['course_id']}_{generation}",
                                  on_change='rerun' if render_course_queue else 'ignore')
            with section:
                if render_course_queue:
                    if not section.open:
                        continue
                    render_course_queue(group['course_id'])
                    st.markdown('**Topic review results**')
                visible_items = [item for item in items if item['course_id']==group['course_id']]
                if visible_items:
                    linked_table(review_table_rows(visible_items, window_sessions), links)
                else:
                    st.caption('No topics match the current status filter. Your course queue is shown above.')


def item_sessions(item, sessions):
    topic = item.get("match_topic_key") or item["topic_key"]
    return [s for s in sessions if s.get("course_id") == item.get("course_id")
            and ' '.join(s["module_name"].casefold().split()) == topic]


def open_attempt(user_id, raw_id):
    """Authorize before showing answers, PDFs or restoring a saved exam."""
    try:
        attempt_id = int(raw_id)
    except (ValueError, TypeError):
        st.error("Invalid session link.")
        st.stop()
    conn = get_connection()
    attempt = conn.execute("SELECT * FROM exam_attempts WHERE id = ? AND user_id = ?", (attempt_id, user_id)).fetchone()
    conn.close()
    st.markdown(review_link("← Back to Mock Review"), unsafe_allow_html=True)
    if not attempt:
        st.error("This session is no longer available.")
        st.stop()
    attempt = dict(attempt)
    if not attempt.get("completed_at"):
        from src.exam_engine import restore_exam_draft, suspend_current_exam, is_active, _st
        from src.database import get_exam_draft
        pages = {"practice": "pages/5_Practice_Mode.py", "timed_section": "pages/6_Timed_Section.py",
                 "full_exam": "pages/7_Full_Exam.py", "curriculum_exam": "pages/7a_Curriculum_Exam.py"}
        page = pages.get(attempt["mode"])
        draft = get_exam_draft(user_id, attempt_id)
        if page and (draft or (is_active() and _st("attempt_id") == attempt_id)):
            if is_active() and _st("attempt_id") != attempt_id:
                suspend_current_exam(user_id)
            if (is_active() and _st("attempt_id") == attempt_id) or restore_exam_draft(user_id, attempt_id=attempt_id):
                if attempt.get("course_id"):
                    st.session_state["active_course_id"] = attempt["course_id"]
                st.switch_page(page)
        st.info("This session has no resumable online draft. Its saved work is shown below.")
    st.subheader(f"Session #{attempt_id} · {'Complete' if attempt.get('completed_at') else 'In Progress'}")
    from src.offline_exams import exam_for_attempt, get_offline_exam
    document = exam_for_attempt(user_id, attempt_id)
    if document:
        document = get_offline_exam(user_id, document["serial"])
    if document and document.get("pdf"):
        st.download_button("Download exam PDF", document["pdf"], file_name=f"exam-{attempt_id}.pdf", mime="application/pdf")
    answers = get_attempt_answers(attempt_id)
    if answers:
        from src.scoring import compute_score
        from src.utils import render_score_card
        render_score_card(compute_score(answers))
        for index, answer in enumerate(answers, 1):
            with st.expander(f"Question {index} · {'Correct' if answer.get('is_correct') else 'Incorrect'}"):
                st.write(answer.get("stimulus") or "")
                st.write(answer.get("question_text") or "")
                for choice in "abcde":
                    if answer.get(f"choice_{choice}"):
                        st.write(f"{choice.upper()}. {answer[f'choice_{choice}']}")
                st.write(f"Your answer: {answer.get('selected_answer') or '—'} · Correct answer: {answer.get('correct_answer') or '—'}")
                if answer.get("explanation"):
                    st.info(answer["explanation"])
    else:
        st.caption("No saved answers for this session yet.")
    st.stop()
