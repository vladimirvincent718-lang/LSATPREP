"""
pages/4_Question_Bank_Manager.py — Shared question bank per course.
All enrolled users can browse questions.
Only admins can upload or delete questions.

Changes in this version:
  - Upload summary now shows: rows read, valid, inserted, skipped-by-generated-ID,
    skipped-by-content (identical question, different ID), invalid rows, errors.
  - Content-hash duplicate detection flags questions with identical text.
  - Uploaded question_id values are ignored; course-scoped IDs are generated.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import io
import re
from datetime import datetime


def _clean_module_label(value: str) -> str:
    label = " ".join(str(value or "").split())
    return label or "Unassigned"


def _module_sort_key(label: str) -> tuple[int, int, str]:
    match = re.search(r"\b(?:module|week|unit|lesson|chapter)\s*#?\s*(\d+)", label, re.I)
    if match:
        return (0, int(match.group(1)), label.lower())
    if label == "Unassigned":
        return (2, 0, label.lower())
    return (1, 0, label.lower())


QUESTION_SEARCH_FIELDS = {
    "Bank #": ("id",),
    "Master ID": ("question_id",),
    "Course": ("_course_title",),
    "Section": ("section_type",),
    "Type": ("question_type",),
    "Difficulty": ("difficulty", "_difficulty_label"),
    "Passage": ("passage",),
    "Stimulus": ("stimulus",),
    "Choices": ("choice_a", "choice_b", "choice_c", "choice_d", "choice_e"),
    "Correct Answer": ("correct_answer",),
    "Explanation": (
        "explanation",
        "wrong_answer_a", "wrong_answer_b", "wrong_answer_c",
        "wrong_answer_d", "wrong_answer_e",
    ),
    "Source": ("source",),
    "Tags": ("tags",),
}


def _question_search_blob(
    q: dict,
    field_labels: list[str],
    course_titles: dict[int, str],
) -> str:
    values = []
    enriched = {
        **q,
        "_course_title": course_titles.get(q.get("course_id"), ""),
        "_difficulty_label": DIFFICULTY_LABELS.get(q.get("difficulty"), ""),
    }
    for label in field_labels:
        for key in QUESTION_SEARCH_FIELDS.get(label, ()):
            value = enriched.get(key, "")
            if value not in (None, ""):
                values.append(str(value))
    return " ".join(values).lower()


def _filter_questions_by_column_search(
    questions: list[dict],
    *,
    query: str,
    field_labels: list[str],
    match_mode: str,
    course_titles: dict[int, str],
) -> list[dict]:
    terms = [term.lower() for term in query.split() if term.strip()]
    phrase = query.strip().lower()
    if not phrase:
        return questions
    if not field_labels:
        return []

    matched = []
    for q in questions:
        blob = _question_search_blob(q, field_labels, course_titles)
        if match_mode == "Exact phrase":
            is_match = phrase in blob
        elif match_mode == "Any term":
            is_match = any(term in blob for term in terms)
        else:
            is_match = all(term in blob for term in terms)
        if is_match:
            matched.append(q)
    return matched


def _question_bank_analytics_rows(selected_course_ids: list[int],
                                  course_titles: dict[int, str]) -> list[dict]:
    rows = []
    for cid in selected_course_ids:
        saved_modules = [_clean_module_label(m.get("name", "")) for m in get_course_modules(cid)]
        questions_for_course = get_all_questions(course_id=cid)

        counts: dict[str, int] = {module_name: 0 for module_name in saved_modules}
        for q in questions_for_course:
            module_name = _clean_module_label(q.get("section_type", ""))
            counts[module_name] = counts.get(module_name, 0) + 1

        for module_name in sorted(counts, key=_module_sort_key):
            rows.append({
                "Course": course_titles.get(cid, ""),
                "Module": module_name,
                "Question Count": counts[module_name],
            })
    return rows

from src.auth            import require_login
from src.utils           import (
    page_header, sidebar_nav, require_course, DIFFICULTY_LABELS,
    get_effective_admin, question_reference_label,
)
from src.database        import (
    get_all_questions, get_course_question_count, delete_question,
    bulk_delete_questions,
    get_distinct_values, get_course, is_admin, get_all_courses,
    get_enrolled_courses, get_course_modules,
    QUESTION_REPORT_STATUSES, get_question_issue_metrics,
    get_question_issue_reports, update_question_issue_report,
    get_archived_questions, restore_question, archive_question,
)
from src.question_loader import (
    process_upload,
    make_template_csv,
    make_template_xlsx,
    is_open_ended_question,
)

st.set_page_config(page_title="Question Bank · StudyForge",
                   page_icon="🗂", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"
real_admin, admin = get_effective_admin(user_id)

page_header("🗂 Question Bank Manager",
            "Shared questions across active courses")

# ── Build tabs based on role ──────────────────────────────────────────────────
if admin:
    tab_browse, tab_reports, tab_archive, tab_upload, tab_template = st.tabs(
        ["🔎 Browse Questions", "Report Issues", "Archived Questions", "⬆️ Upload Files", "📄 Download Template"]
    )
else:
    tab_browse, tab_template = st.tabs(
        ["🔎 Browse Questions", "📄 Download Template"]
    )
    tab_upload = None
    tab_reports = None
    tab_archive = None


# ── Tab: Browse ───────────────────────────────────────────────────────────────
with tab_browse:
    browse_courses = get_all_courses() if admin else get_enrolled_courses(user_id)
    course_titles = {c["id"]: c["title"] for c in browse_courses}
    course_counts = {c["id"]: get_course_question_count(c["id"]) for c in browse_courses}
    default_course_ids = (
        [course_id]
        if course_id in course_titles
        else ([browse_courses[0]["id"]] if browse_courses else [])
    )

    selected_course_ids = st.multiselect(
        "Active Courses",
        options=list(course_titles.keys()),
        default=default_course_ids,
        format_func=lambda cid: f"{course_titles[cid]} ({course_counts.get(cid, 0)} Q)",
        help="Type to search, then select one or more courses to browse.",
        key="qbm_browse_courses",
    )
    selected_course_ids = [cid for cid in selected_course_ids if cid in course_titles]

    if not selected_course_ids:
        st.warning("Select at least one active course to browse its question bank.")
        st.stop()

    total = sum(course_counts.get(cid, 0) for cid in selected_course_ids)
    metric_label = (
        f"Questions in {course_titles[selected_course_ids[0]]}"
        if len(selected_course_ids) == 1
        else "Questions in selected courses"
    )
    st.metric(metric_label, total)

    if total == 0:
        selected_names = ", ".join(course_titles[cid] for cid in selected_course_ids)
        msg = f"No questions in **{selected_names}** yet."
        if admin:
            msg += " Use the **Upload CSV** tab above to add questions."
        else:
            msg += " An admin will upload questions soon."
        st.info(msg)
    else:
        st.info("📌 Questions are **shared** — all enrolled users practise from the same bank.")

        # ── Filters ───────────────────────────────────────────────────────────
        col1, col2, col3 = st.columns(3)
        with col1:
            sec_opts = ["All"] + sorted({
                val
                for cid in selected_course_ids
                for val in get_distinct_values("section_type", course_id=cid)
            })
            f_sec    = st.selectbox("Section Type", sec_opts, key="b_sec")
        with col2:
            type_opts = ["All"] + sorted({
                val
                for cid in selected_course_ids
                for val in get_distinct_values("question_type", course_id=cid)
            })
            f_type    = st.selectbox("Question Type", type_opts, key="b_type")
        with col3:
            d_min, d_max = st.select_slider(
                "Difficulty Range",
                options=[1,2,3,4,5],
                value=(1,5),
                format_func=lambda x: f"{x} - {DIFFICULTY_LABELS.get(x, x)}",
                key="b_diff",
            )

        st.markdown("#### Search Questions")
        search_col1, search_col2 = st.columns([2.4, 1])
        with search_col1:
            q_search = st.text_input(
                "Search text",
                placeholder="Bank #, master ID, module, stimulus, choices, explanation, source, tags...",
                key="qbm_question_search_text",
            )
        with search_col2:
            q_match_mode = st.selectbox(
                "Match",
                ["All terms", "Exact phrase", "Any term"],
                key="qbm_question_search_match",
            )
        q_search_fields = st.multiselect(
            "Search in columns",
            options=list(QUESTION_SEARCH_FIELDS.keys()),
            default=[
                "Bank #", "Master ID", "Section", "Type", "Stimulus",
                "Choices", "Explanation", "Source", "Tags",
            ],
            key="qbm_question_search_fields",
        )
        if q_search.strip() and not q_search_fields:
            st.warning("Choose at least one column to search.")

        questions = []
        for cid in selected_course_ids:
            questions.extend(get_all_questions(
                section_type=None  if f_sec  == "All" else f_sec,
                question_type=None if f_type == "All" else f_type,
                min_difficulty=d_min,
                max_difficulty=d_max,
                course_id=cid,
            ))
        questions.sort(
            key=lambda q: (
                course_titles.get(q.get("course_id"), ""),
                q.get("question_id") or "",
                q.get("id") or 0,
            )
        )
        questions = _filter_questions_by_column_search(
            questions,
            query=q_search,
            field_labels=q_search_fields,
            match_mode=q_match_mode,
            course_titles=course_titles,
        )

        st.caption(f"{len(questions)} question(s) match the filters")

        if not questions:
            st.info("No questions match those filters.")
        else:
            export_rows = []
            for q in questions:
                export_rows.append({
                    "bank_question_number": q.get("id", ""),
                    "course": course_titles.get(q.get("course_id"), ""),
                    "course_id": q.get("course_id", ""),
                    "question_id": q.get("question_id", ""),
                    "section_type": q.get("section_type", ""),
                    "question_type": q.get("question_type", ""),
                    "difficulty": q.get("difficulty", ""),
                    "difficulty_label": DIFFICULTY_LABELS.get(q.get("difficulty", 3), ""),
                    "passage": q.get("passage", ""),
                    "stimulus": q.get("stimulus", ""),
                    "choice_a": q.get("choice_a", ""),
                    "choice_b": q.get("choice_b", ""),
                    "choice_c": q.get("choice_c", ""),
                    "choice_d": q.get("choice_d", ""),
                    "choice_e": q.get("choice_e", ""),
                    "correct_answer": q.get("correct_answer", ""),
                    "explanation": q.get("explanation", ""),
                    "wrong_answer_a": q.get("wrong_answer_a", ""),
                    "wrong_answer_b": q.get("wrong_answer_b", ""),
                    "wrong_answer_c": q.get("wrong_answer_c", ""),
                    "wrong_answer_d": q.get("wrong_answer_d", ""),
                    "wrong_answer_e": q.get("wrong_answer_e", ""),
                    "source": q.get("source", ""),
                    "tags": q.get("tags", ""),
                })

            export_df = pd.DataFrame(export_rows)
            filename_stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            st.download_button(
                "Download Full CSV",
                data=export_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"question_bank_full_{filename_stamp}.csv",
                mime="text/csv",
                use_container_width=True,
                key="qbm_full_csv_download",
                help="Exports the full filtered questions, including answers and explanations.",
            )
            # Selection state is stored as question IDs, while the grid reports
            # selected row positions in the current filtered view.
            if "_qbm_selected_ids" not in st.session_state:
                st.session_state["_qbm_selected_ids"] = set()
            if "_qbm_grid_revision" not in st.session_state:
                st.session_state["_qbm_grid_revision"] = 0

            current_ids = {q["id"] for q in questions}   # IDs in current filter view

            # ── Admin bulk-delete toolbar ─────────────────────────────────────
            if admin:
                st.markdown("#### Bulk Delete")
                tb1, tb2, tb_spacer = st.columns([1.2, 1.2, 6.6])

                if tb1.button("☑ Select All", use_container_width=True):
                    st.session_state["_qbm_selected_ids"] = set(current_ids)
                    st.session_state["_qbm_grid_revision"] += 1
                    st.session_state.pop("qbm_confirm_delete", None)

                if tb2.button("☐ Deselect All", use_container_width=True):
                    st.session_state["_qbm_selected_ids"] = set()
                    st.session_state["_qbm_grid_revision"] += 1
                    st.session_state.pop("qbm_confirm_delete", None)

            # Build display rows for a native selectable grid.
            rows = []
            for q in questions:
                s = str(q.get("stimulus", ""))
                rows.append({
                    "ID":          q["id"],
                    "Bank #":      q["id"],
                    "Master ID":   q.get("question_id", ""),
                    "Course":      course_titles.get(q.get("course_id"), ""),
                    "Section":     q.get("section_type", ""),
                    "Type":        q.get("question_type", ""),
                    "Difficulty":  DIFFICULTY_LABELS.get(q.get("difficulty", 3), ""),
                    "Passage":     q.get("passage", ""),
                    "Stimulus":    s,
                    "Choice A":    q.get("choice_a", ""),
                    "Choice B":    q.get("choice_b", ""),
                    "Choice C":    q.get("choice_c", ""),
                    "Choice D":    q.get("choice_d", ""),
                    "Choice E":    q.get("choice_e", ""),
                    "Answer":      q.get("correct_answer", ""),
                    "Explanation": q.get("explanation", ""),
                    "Source":      q.get("source", ""),
                })
            df_all = pd.DataFrame(rows)

            # Clicking a row selects and highlights the whole row. The grid also
            # keeps native keyboard cell navigation for spreadsheet-style review.
            selection_default = {
                "selection": {
                    "rows": [
                        i
                        for i, row in df_all.iterrows()
                        if int(row["ID"]) in st.session_state["_qbm_selected_ids"]
                    ]
                }
            }
            visible_signature = abs(hash(tuple(int(q["id"]) for q in questions)))
            grid_event = st.dataframe(
                df_all.drop(columns=["ID"]),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Bank #": st.column_config.NumberColumn("Bank #", format="%d"),
                },
                on_select="rerun",
                selection_mode="multi-row",
                selection_default=selection_default,
                key=(
                    f"qbm_question_grid_"
                    f"{st.session_state['_qbm_grid_revision']}_{visible_signature}"
                ),
            )

            # Sync native row selection to our selected question IDs.
            st.session_state["_qbm_selected_ids"] = {
                int(df_all.iloc[i]["ID"])
                for i in grid_event.selection.rows
                if 0 <= i < len(df_all)
            }

            selected_ids = list(st.session_state["_qbm_selected_ids"])
            n_selected   = len(selected_ids)

            # ── Delete Selected button (admin only) ───────────────────────────
            if admin:
                del_col, _ = st.columns([2, 6])
                del_btn_disabled = n_selected == 0
                if del_col.button(
                    f"🗑 Delete Selected ({n_selected})",
                    type="primary",
                    disabled=del_btn_disabled,
                    use_container_width=True,
                    key="qbm_delete_btn",
                    help="Select at least one question first" if del_btn_disabled
                         else f"Delete {n_selected} selected question(s)",
                ):
                    st.session_state["qbm_confirm_delete"] = selected_ids

                # ── Confirmation modal ────────────────────────────────────────
                pending_ids = st.session_state.get("qbm_confirm_delete") or []
                if pending_ids:
                    n_pending = len(pending_ids)

                    st.warning(
                        f"⚠️ **Are you sure you want to delete {n_pending} "
                        f"question{'s' if n_pending != 1 else ''}?**  \n"
                        "This action **cannot be undone**. "
                        "Score history and past exam results will be preserved, "
                        "but these questions will be permanently removed from the bank."
                    )
                    conf_ok, conf_cancel, _ = st.columns([1.5, 1.5, 5])

                    if conf_ok.button(
                        f"✅ Yes, delete {n_pending} question{'s' if n_pending != 1 else ''}",
                        type="primary",
                        use_container_width=True,
                        key="qbm_confirm_yes",
                    ):
                        deleted = bulk_delete_questions(pending_ids)
                        st.session_state.pop("qbm_confirm_delete", None)
                        st.session_state["_qbm_selected_ids"] = set()   # clear checkboxes
                        st.success(
                            f"✅ {deleted} question{'s' if deleted != 1 else ''} "
                            "deleted successfully."
                        )
                        st.rerun()

                    if conf_cancel.button(
                        "Cancel",
                        use_container_width=True,
                        key="qbm_confirm_cancel",
                    ):
                        st.session_state.pop("qbm_confirm_delete", None)
                        st.rerun()

            # ── Single-question detail & delete (existing feature preserved) ──
            st.divider()
            st.markdown("#### View Question Detail" + (" / Delete" if admin else ""))
            q_ids    = [q["id"] for q in questions]
            q_labels = {
                q["id"]: f"#{q['id']} · {q.get('question_id','')} · "
                         f"{course_titles.get(q.get('course_id'), '')} · "
                         f"{str(q.get('stimulus',''))[:50]}"
                for q in questions
            }
            sel_qid = st.selectbox("Select question:", q_ids,
                                    format_func=lambda x: q_labels.get(x, str(x)))

            if sel_qid:
                q = next((x for x in questions if x["id"] == sel_qid), None)
                if q:
                    with st.expander("📋 Full Question Details", expanded=True):
                        ref_label = question_reference_label(q)
                        if ref_label:
                            st.caption(ref_label)
                        st.markdown(
                            f"**Course:** {course_titles.get(q.get('course_id'), '')}  |  "
                            f"**Section:** {q.get('section_type')}  |  "
                            f"**Type:** {q.get('question_type')}  |  "
                            f"**Difficulty:** {DIFFICULTY_LABELS.get(q.get('difficulty',3))}"
                        )
                        if q.get("passage"):
                            st.markdown("**Passage:**")
                            st.markdown(q["passage"])
                        st.markdown(f"**Stimulus:** {q.get('stimulus')}")
                        for letter in ["A","B","C","D","E"]:
                            c = q.get(f"choice_{letter.lower()}")
                            if c:
                                prefix = "✅ " if letter == q.get("correct_answer","") else ""
                                st.write(f"{prefix}**{letter}.** {c}")
                        if is_open_ended_question(q) and q.get("correct_answer"):
                            st.markdown("**Sample answer / rubric:**")
                            st.info(q.get("correct_answer"))
                        if q.get("explanation"):
                            st.info(f"💡 {q['explanation']}")
                        if q.get("tags"):
                            st.caption(f"Tags: {q['tags']}")

                        if admin:
                            if st.button("🗑 Delete This Question",
                                         key=f"del_q_{sel_qid}"):
                                delete_question(sel_qid)
                                st.success("Question deleted.")
                                st.rerun()


# ── Tab: Upload (admin only) ──────────────────────────────────────────────────
            st.divider()
            with st.expander("Question Bank Analytics", expanded=False):
                analytics_rows = _question_bank_analytics_rows(selected_course_ids, course_titles)
                if analytics_rows:
                    analytics_df = pd.DataFrame(analytics_rows)
                    total_modules = len(analytics_df)
                    total_questions_in_modules = int(analytics_df["Question Count"].sum())

                    a_col1, a_col2 = st.columns(2)
                    a_col1.metric("Modules", total_modules)
                    a_col2.metric("Questions", total_questions_in_modules)

                    if len(selected_course_ids) == 1:
                        analytics_df = analytics_df.drop(columns=["Course"])

                    st.dataframe(
                        analytics_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Question Count": st.column_config.NumberColumn(
                                "Question Count",
                                format="%d",
                            ),
                        },
                    )
                else:
                    st.info("No modules or questions are available for the selected course.")

if tab_reports is not None:
    with tab_reports:
        st.markdown("### Reported Question Issues")

        admin_courses = get_all_courses()
        admin_course_ids = [c["id"] for c in admin_courses]
        admin_course_titles = {c["id"]: c["title"] for c in admin_courses}
        metrics = get_question_issue_metrics(admin_course_ids)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total", metrics.get("total", 0))
        m2.metric("New", metrics.get("new_count", 0))
        m3.metric("Reviewing", metrics.get("reviewing_count", 0))
        m4.metric("Resolved", metrics.get("resolved_count", 0))
        m5.metric("Dismissed", metrics.get("dismissed_count", 0))

        st.divider()
        f1, f2, f3 = st.columns([1.2, 2, 2])
        with f1:
            status_filter = st.selectbox(
                "Status",
                ["All"] + QUESTION_REPORT_STATUSES,
                key="qir_status_filter",
            )
        with f2:
            report_course_ids = st.multiselect(
                "Courses",
                options=admin_course_ids,
                default=admin_course_ids,
                format_func=lambda cid: admin_course_titles.get(cid, str(cid)),
                key="qir_course_filter",
            )
        with f3:
            report_search = st.text_input(
                "Search",
                placeholder="note, user, stimulus, master ID...",
                key="qir_search",
            )

        reports = get_question_issue_reports(
            status=None if status_filter == "All" else status_filter,
            course_ids=report_course_ids,
            search=report_search.strip() or None,
        )
        st.caption(f"Showing {len(reports)} report(s)")

        if not reports:
            st.info("No question issue reports match the current filters.")
        else:
            for report in reports:
                created = str(report.get("created_at") or "")[:16] or "-"
                label = (
                    f"#{report['id']} | {report['status']} | "
                    f"{report.get('issue_type', 'Other')} | "
                    f"{report.get('course_title') or 'Unknown course'} | "
                    f"Q{report.get('question_id')} | {created}"
                )
                with st.expander(label, expanded=report.get("status") == "New"):
                    detail_cols = st.columns([2, 1])
                    with detail_cols[0]:
                        ref_label = question_reference_label(report)
                        if ref_label:
                            st.caption(ref_label)
                        st.markdown("**Reported note**")
                        st.info(report.get("note") or "No note provided.")
                        st.markdown("**Question stimulus**")
                        st.markdown(report.get("stimulus") or "")
                        if report.get("passage"):
                            with st.expander("Passage", expanded=False):
                                st.markdown(report["passage"])
                        for letter in ["A", "B", "C", "D", "E"]:
                            choice = report.get(f"choice_{letter.lower()}")
                            if choice:
                                marker = " (correct)" if letter == report.get("correct_answer") else ""
                                st.write(f"**{letter}.** {choice}{marker}")
                        if report.get("explanation"):
                            with st.expander("Explanation", expanded=False):
                                st.info(report["explanation"])
                    with detail_cols[1]:
                        st.markdown(f"**Submitted by:** {report.get('username', '-')}")
                        st.markdown(f"**Issue type:** {report.get('issue_type', '-')}")
                        st.markdown(f"**Selected answer:** {report.get('selected_answer') or '-'}")
                        st.markdown(f"**Mode:** {report.get('mode') or '-'}")
                        st.markdown(f"**Master ID:** {report.get('master_question_id') or '-'}")
                        st.markdown(f"**Section:** {report.get('section_type') or '-'}")
                        st.markdown(f"**Type:** {report.get('question_type') or '-'}")
                        archive_label = "Archived" if report.get("is_archived") else "Active"
                        st.markdown(f"**Bank status:** {archive_label}")
                        if report.get("archive_reason"):
                            st.caption(f"Archive reason: {report.get('archive_reason')}")

                    st.divider()
                    with st.form(f"qir_admin_update_{report['id']}"):
                        edit_cols = st.columns([1, 2])
                        with edit_cols[0]:
                            new_status = st.selectbox(
                                "Status",
                                QUESTION_REPORT_STATUSES,
                                index=QUESTION_REPORT_STATUSES.index(report["status"])
                                if report.get("status") in QUESTION_REPORT_STATUSES else 0,
                            )
                        with edit_cols[1]:
                            admin_notes = st.text_area(
                                "Admin notes",
                                value=report.get("admin_notes") or "",
                                height=100,
                            )
                        save_report = st.form_submit_button(
                            "Save Review", type="primary"
                        )
                    if save_report:
                        if not real_admin:
                            st.error("Permission denied. Real admin access required.")
                            st.stop()
                        update_question_issue_report(
                            report_id=report["id"],
                            status=new_status,
                            admin_notes=admin_notes,
                        )
                        st.success("Report updated.")
                        st.rerun()


if tab_archive is not None:
    with tab_archive:
        st.markdown("### Archived Questions")
        st.caption(
            "Reported questions are archived automatically and removed from new "
            "practice, timed section, full exam, and curriculum exam pools."
        )

        archive_courses = get_all_courses()
        archive_course_ids = [c["id"] for c in archive_courses]
        archive_course_titles = {c["id"]: c["title"] for c in archive_courses}

        af1, af2 = st.columns([2, 2])
        with af1:
            selected_archive_course_ids = st.multiselect(
                "Courses",
                options=archive_course_ids,
                default=archive_course_ids,
                format_func=lambda cid: archive_course_titles.get(cid, str(cid)),
                key="qbm_archive_course_filter",
            )
        with af2:
            archive_search = st.text_input(
                "Search archived questions",
                placeholder="stimulus, master ID, section, type...",
                key="qbm_archive_search",
            )

        archived_questions = get_archived_questions(
            course_ids=selected_archive_course_ids,
            search=archive_search.strip() or None,
        )
        st.metric("Archived questions", len(archived_questions))

        if not archived_questions:
            st.info("No archived questions match the current filters.")
        else:
            rows = [
                {
                    "ID": q.get("id"),
                    "Master ID": q.get("question_id", ""),
                    "Course": q.get("course_title", ""),
                    "Section": q.get("section_type", ""),
                    "Type": q.get("question_type", ""),
                    "Reports": q.get("report_count", 0),
                    "Archived At": str(q.get("archived_at") or "")[:16],
                    "Reason": q.get("archive_reason", ""),
                    "Stimulus": str(q.get("stimulus", ""))[:180],
                }
                for q in archived_questions
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            labels = {
                q["id"]: (
                    f"#{q['id']} | {q.get('course_title') or 'Unknown course'} | "
                    f"{q.get('question_id') or ''} | {str(q.get('stimulus') or '')[:70]}"
                )
                for q in archived_questions
            }
            selected_archived_id = st.selectbox(
                "Review archived question",
                options=[q["id"] for q in archived_questions],
                format_func=lambda qid: labels.get(qid, str(qid)),
                key="qbm_archived_question_select",
            )

            q = next((item for item in archived_questions if item["id"] == selected_archived_id), None)
            if q:
                with st.expander("Archived Question Detail", expanded=True):
                    ref_label = question_reference_label(q)
                    if ref_label:
                        st.caption(ref_label)
                    st.markdown(
                        f"**Course:** {q.get('course_title') or ''}  |  "
                        f"**Section:** {q.get('section_type') or ''}  |  "
                        f"**Type:** {q.get('question_type') or ''}  |  "
                        f"**Difficulty:** {DIFFICULTY_LABELS.get(q.get('difficulty', 3), q.get('difficulty', ''))}"
                    )
                    st.markdown(f"**Archive reason:** {q.get('archive_reason') or 'Issue reported'}")
                    st.markdown(f"**Report statuses:** {q.get('report_statuses') or '-'}")
                    if q.get("passage"):
                        with st.expander("Passage", expanded=False):
                            st.markdown(q["passage"])
                    st.markdown(f"**Stimulus:** {q.get('stimulus') or ''}")
                    for letter in ["A", "B", "C", "D", "E"]:
                        choice = q.get(f"choice_{letter.lower()}")
                        if choice:
                            marker = " (correct)" if letter == q.get("correct_answer") else ""
                            st.write(f"**{letter}.** {choice}{marker}")
                    if q.get("explanation"):
                        st.info(q["explanation"])

                    restore_col, rearchive_col, _ = st.columns([1.4, 1.4, 5])
                    if restore_col.button(
                        "Restore to Active Bank",
                        type="primary",
                        use_container_width=True,
                        key=f"qbm_restore_archived_{q['id']}",
                    ):
                        if not real_admin:
                            st.error("Permission denied. Real admin access required.")
                            st.stop()
                        restore_question(q["id"])
                        st.success("Question restored to the active bank.")
                        st.rerun()

                    if rearchive_col.button(
                        "Keep Archived",
                        use_container_width=True,
                        key=f"qbm_keep_archived_{q['id']}",
                    ):
                        archive_question(q["id"], q.get("archive_reason") or "Issue reported")
                        st.success("Question remains archived.")
                        st.rerun()


if tab_upload is not None:
    with tab_upload:
        st.markdown("### Upload Questions to a Shared Course")
        st.info(
            "Questions you upload become immediately available to **all users "
            "enrolled in the selected course**. You only need to upload once.  \n"
            "**Duplicates are detected automatically** — re-uploading the same "
            "file will not create duplicate questions."
        )

        # Allow admin to choose any course, not just active one
        all_courses = get_all_courses()
        course_map  = {c["id"]: c["title"] for c in all_courses}
        target_id = st.selectbox(
            "Upload to course:",
            list(course_map.keys()),
            format_func=lambda x: course_map[x],
            index=list(course_map.keys()).index(course_id)
                  if course_id in course_map else 0,
            key="upload_course_sel",
        )
        target_title = course_map.get(target_id, "")

        if "qbank_upload_nonce" not in st.session_state:
            st.session_state["qbank_upload_nonce"] = 0

        last_upload = st.session_state.get("qbank_last_upload")
        if last_upload:
            totals = last_upload["totals"]
            st.success(
                f"✅ Import complete: **{totals['inserted']}** new question(s) "
                f"added to **{last_upload['course_title']}** from "
                f"**{last_upload['file_count']}** file(s)."
            )

            with st.expander("Last upload summary", expanded=True):
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                mc1.metric("Rows in files", totals["rows_read"])
                mc2.metric("✅ Inserted", totals["inserted"])
                mc3.metric("⏭ Skipped (ID conflict)", totals["skipped_id"])
                mc4.metric("⏭ Skipped (same content)", totals["skipped_content"])
                mc5.metric("❌ Invalid rows", totals["invalid"])

                if last_upload["results"]:
                    st.markdown("**Per-file results**")
                    for file_name, result in last_upload["results"]:
                        st.caption(
                            f"**{file_name}**: "
                            f"{result['rows_read']} row(s), "
                            f"{result['inserted']} inserted, "
                            f"{result['skipped_content']} duplicate content, "
                            f"{result['invalid']} invalid"
                        )

                if totals["errors"]:
                    st.markdown("**Validation errors**")
                    for e in totals["errors"][:30]:
                        st.caption(f"• {e}")
                    if len(totals["errors"]) > 30:
                        st.caption(
                            f"… and {len(totals['errors']) - 30} more. "
                            "Fix these in your files and re-upload."
                        )

        uploaded_files = st.file_uploader(
            "Choose CSV or Excel files",
            type=["csv", "xlsx", "xlsm", "xls"],
            accept_multiple_files=True,
            help="Select one file, or hold Ctrl/Shift to select a batch.",
            key=f"qbank_upload_{st.session_state['qbank_upload_nonce']}",
        )

        if uploaded_files:
            total_size = sum(file.size for file in uploaded_files)
            st.markdown(
                f"**Selected:** {len(uploaded_files)} file(s) "
                f"({total_size:,} bytes total)"
            )
            with st.expander("Selected files", expanded=len(uploaded_files) <= 5):
                for file in uploaded_files:
                    st.caption(f"• {file.name} ({file.size:,} bytes)")

            if st.button("✅ Import Questions", type="primary"):
                results = []
                totals = {
                    "rows_read": 0,
                    "valid_rows": 0,
                    "inserted": 0,
                    "skipped_id": 0,
                    "skipped_content": 0,
                    "invalid": 0,
                    "errors": [],
                }

                with st.spinner("Processing selected files…"):
                    for file in uploaded_files:
                        result = process_upload(file, course_id=target_id)
                        results.append((file.name, result))
                        for key in [
                            "rows_read",
                            "valid_rows",
                            "inserted",
                            "skipped_id",
                            "skipped_content",
                            "invalid",
                        ]:
                            totals[key] += result[key]
                        totals["errors"].extend(
                            f"{file.name}: {error}" for error in result["errors"]
                        )

                st.session_state["qbank_last_upload"] = {
                    "course_title": target_title,
                    "file_count": len(uploaded_files),
                    "totals": totals,
                    "results": results,
                }
                st.session_state["qbank_upload_nonce"] += 1
                st.rerun()

        st.divider()
        st.metric(
            "Questions currently in " + target_title,
            get_course_question_count(target_id),
        )

        # Quick duplicate-detection explainer
        with st.expander("ℹ️ How duplicate detection works", expanded=False):
            st.markdown("""
**Two layers of duplicate detection:**

1. **Generated master ID** — uploaded `question_id` values are ignored. The app
   assigns a new ID using the selected course abbreviation plus a number, such as
   `BIO-0001`. That ID is unique inside the course.

2. **Same content** — a fingerprint (hash) is computed from the question's
   *stimulus + all five choices + correct answer*.  If an identical fingerprint
   already exists in the **same course**, the row is skipped — even if it has a
   different uploaded ID.  This catches re-uploaded batches.

**Re-uploading the same CSV** will always result in 0 inserted and all rows
being skipped by one of the two checks above — no duplicates are created.
            """)


# ── Tab: Template ─────────────────────────────────────────────────────────────
with tab_template:
    st.markdown("### Question Bank Template")
    st.markdown("""
Download this template, fill in your questions, and upload via the **Upload CSV** tab.

**Required columns:**  
`stimulus`, `question_type`

**Optional but useful:**  
`question_id` (ignored on import), `section_type`, `question_type`, `difficulty` (1–5), `passage`, `explanation`,  
`wrong_answer_a–e`, `source`, `tags`

`section_type` — any text: `Logical Reasoning`, `Python Basics`, `Chapter 3`, etc.  
`question_type` — any text: `Weaken`, `Multiple Choice`, `True/False`, etc.  
`correct_answer` — must be `A`, `B`, `C`, `D`, or `E`  
`difficulty` — 1 Intuition & Estimation, 2 Beginner Calculations, 3 Intermediate Calculations, 4 Advanced Calculations, 5 Stretch Problems; default 3
    """)

    csv_str = make_template_csv()
    st.info(
        "For open-ended questions, set question_type to Open-Ended. "
        "Choices can be blank, and correct_answer can hold a sample answer or rubric."
    )
    st.download_button(
        "Download Excel template with dropdowns",
        data=make_template_xlsx(),
        file_name="question_bank_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.download_button(
        "⬇️ Download question_bank_template.csv",
        data=csv_str,
        file_name="question_bank_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.divider()
    st.markdown("**Preview (2 example rows):**")
    st.dataframe(
        pd.read_csv(io.StringIO(csv_str)),
        use_container_width=True, hide_index=True,
    )
