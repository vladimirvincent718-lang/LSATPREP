"""Drill down into the exact records behind today's practice metrics."""

import csv
import io

import streamlit as st

from src.database import get_question_by_id


METRICS = ("Total questions", "Correct", "Incorrect", "Daily target", "Accuracy", "Active time", "Explanations")


def report_rows(answers, external):
    rows = []
    for answer in answers:
        correct = int(bool(answer.get("is_correct")))
        rows.append({
            "Source": "StudyForge", "Course": answer.get("course_title") or "Unassigned",
            "Module": answer.get("section_type") or "Unassigned",
            "Difficulty": str(answer.get("difficulty") or "Unassigned"),
            "Correct": correct, "Incorrect": 1 - correct, "Total": 1,
            "Record": f"Answer {answer['answer_id']} · Session {answer['attempt_id']}",
            "Question ID": answer["question_id"],
            "Your answer": answer.get("selected_answer") or "—",
            "Recorded (UTC)": answer.get("completed_at") or "",
        })
    for entry in external:
        correct, incorrect = int(entry["correct_count"]), int(entry["incorrect_count"])
        rows.append({
            "Source": entry["source"], "Course": "External totals",
            "Module": "External totals", "Difficulty": "External totals",
            "Correct": correct, "Incorrect": incorrect, "Total": correct + incorrect,
            "Record": f"External entry {entry['id']} · {entry['entry_date']}",
            "Question ID": None, "Your answer": "Not recorded",
            "Recorded (UTC)": entry.get("updated_at") or "",
        })
    return rows


def summarize(rows, dimension):
    groups = {}
    for row in rows:
        group = groups.setdefault(row[dimension], {dimension: row[dimension], "Correct": 0, "Incorrect": 0, "Total": 0})
        for field in ("Correct", "Incorrect", "Total"):
            group[field] += row[field]
    for group in groups.values():
        group["Accuracy"] = f"{group['Correct'] / group['Total']:.0%}" if group["Total"] else "—"
    return list(groups.values())


def open_report(metric):
    st.session_state["practice_dashboard_open"] = True
    st.session_state["drill_report_metric"] = metric
    for key in list(st.session_state):
        if key.startswith("drill_filter_") or key == "drill_record":
            del st.session_state[key]


def render_report(answers, external, study_time, target, today, *, explanations=(), date_label="Today", metrics=METRICS):
    st.markdown("#### Practice drill-down report")
    if st.session_state.get("drill_report_metric") not in metrics:
        st.session_state.pop("drill_report_metric", None)
    metric = st.selectbox("Metric", metrics, key="drill_report_metric")
    st.caption(f"{date_label} · {today:%b %d, %Y} · America/New_York. Choose a group to narrow the report.")
    if metric == "Explanations":
        st.metric("New explanations today", len(explanations))
        st.caption("First submissions across your courses. Editing a saved explanation does not add to the count. "
                   "Tracking starts with this update; older explanations have no recorded first-submission date.")
        if explanations:
            st.dataframe([{"Question ID": r["question_id"], "Submitted (UTC)": r["created_at"],
                           "Explanation": r["explanation"]} for r in explanations],
                         hide_index=True, use_container_width=True)
        else:
            st.info("No new explanations submitted today.")
        return
    if metric == "Active time":
        st.metric("Active time · " + date_label.lower(), f"{sum(float(r['active_seconds']) for r in study_time):,.0f} seconds")
        st.caption("Timer-running time, grouped by course. Paused time is excluded.")
        if study_time:
            st.dataframe([{"Date": r["activity_date"], "Course": r["course_title"], "Active seconds": round(r["active_seconds"], 2)} for r in study_time], hide_index=True, use_container_width=True)
        else:
            st.info("No active study time recorded today." if date_label == "Today" else "No active study time recorded for this date.")
        return

    rows = report_rows(answers, external)
    total = sum(r["Total"] for r in rows)
    if metric == "Daily target":
        st.progress(min(total / target, 1.0), text=f"{total}/{target} questions · {max(0, target - total)} remaining")
        st.caption("The daily target applies to all sources. The rows below show contributions to it.")
    # External rows are aggregates: keep both counts visible, never invent answers.
    if metric in ("Correct", "Incorrect"):
        rows = [r for r in rows if r[metric] > 0]
    path = [metric]
    for dimension in ("Source", "Course", "Module", "Difficulty"):
        if not rows:
            break
        options = sorted({r[dimension] for r in rows})
        key = f"drill_filter_{metric}_{dimension}_{repr(path)}"
        selection = st.selectbox(dimension, [None, *options], format_func=lambda v: "All" if v is None else v, key=key)
        if selection is None:
            st.dataframe(summarize(rows, dimension), hide_index=True, use_container_width=True)
            break
        rows = [r for r in rows if r[dimension] == selection]
        path.append(selection)
    st.caption(" › ".join(path))
    correct = sum(r["Correct"] for r in rows)
    incorrect = sum(r["Incorrect"] for r in rows)
    count = correct + incorrect
    value = correct if metric == "Correct" else incorrect if metric == "Incorrect" else count
    if metric == "Accuracy":
        st.metric("Filtered accuracy", f"{correct / count:.0%}" if count else "—")
    else:
        st.metric("Matching " + (metric.lower() if metric in ("Correct", "Incorrect") else "questions"), value)
    st.caption(f"{correct} correct · {incorrect} incorrect · {count} total in the matching records.")
    if not rows:
        st.info("No matching practice records today." if date_label == "Today" else "No matching practice records for this date.")
        return
    st.markdown("##### Underlying records")
    st.caption("External entries contain source/date totals; individual questions were not recorded. Answer timestamps are UTC.")
    st.dataframe(rows, hide_index=True, use_container_width=True)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    # Prevent spreadsheet formulas in user-provided source names or answers.
    writer.writerows({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in row.items()} for row in rows)
    st.download_button("Download filtered report (CSV)", output.getvalue(), file_name=f"practice-{today}.csv", mime="text/csv", key="drill_export")
    app_rows = {r["Record"]: r for r in rows if r["Question ID"] is not None}
    if app_rows:
        choices = [None, *app_rows]
        if st.session_state.get("drill_record") not in choices:
            st.session_state.pop("drill_record", None)
        selected = st.selectbox("Inspect an answer", choices, format_func=lambda v: v or "Choose an answer…", key="drill_record")
        if selected:
            row = app_rows[selected]
            question = get_question_by_id(row["Question ID"])
            if question:
                st.markdown(f"**{row['Record']} · {'Correct' if row['Correct'] else 'Incorrect'}**")
                for field in ("passage", "stimulus"):
                    if question.get(field):
                        st.markdown(question[field])
                for letter in "abcde":
                    if question.get(f"choice_{letter}"):
                        st.write(f"{letter.upper()}. {question[f'choice_{letter}']}")
                st.write(f"Your answer: {row['Your answer']} · Correct answer: {question.get('correct_answer') or 'Self-graded'}")
                if question.get("explanation"):
                    st.markdown(question["explanation"])
