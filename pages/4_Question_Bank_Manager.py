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
import html
from datetime import datetime


def _select_detail_question(question_id: int) -> None:
    """Move the detail selector before Streamlit instantiates its widget."""
    st.session_state["qbm_detail_question_id"] = question_id


def _browser_searchable_question_index(
    questions: list[dict],
    course_titles: dict[int, str],
) -> str:
    """Render grid references as real DOM text for browser Find."""
    items = []
    for q in questions:
        bank_id = html.escape(str(q.get("id", "")))
        master_id = html.escape(str(q.get("question_id", "")))
        course = html.escape(course_titles.get(q.get("course_id"), ""))
        stimulus = html.escape(" ".join(str(q.get("stimulus", "")).split()))
        items.append(
            f'<div class="qbm-browser-index-row" role="listitem" '
            f'id="qbm-browser-question-{bank_id}">'
            f'<strong>#{bank_id}</strong> · {master_id} · {course} · {stimulus}'
            "</div>"
        )

    return """
        <div class="qbm-browser-index" role="list"
             aria-label="Browser-searchable question index">
    """ + "".join(items) + "</div>"


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
from src.course_material_nav import course_material_nav
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

real_admin, admin = get_effective_admin(user_id)

page_header("🗂 Question Bank Manager",
            "Build, import, and manage question banks across subjects")
course_material_nav("questions")

available_courses = get_all_courses() if admin else get_enrolled_courses(user_id)
course_options = {c["id"]: c["title"] for c in available_courses}
if not course_options:
    st.info("No courses are available. Add a course or enroll in one to manage its question bank.")
    st.stop()
if st.session_state.get("qbm_course_id") not in course_options:
    active = st.session_state.get("active_course_id")
    st.session_state["qbm_course_id"] = active if active in course_options else next(iter(course_options))
course_id = st.selectbox("Subject / course", list(course_options),
                         format_func=lambda cid: course_options[cid], key="qbm_course_id")
course = get_course(course_id)
course_title = course_options[course_id]
if st.session_state.get("_qbm_scope") != course_id:
    # Clear pending upload files and course-bound filters before their widgets render.
    for key in list(st.session_state):
        if key.startswith(("qbank_", "qbm_detail_", "_qbm_last_search", "b_",
                           "ccrn_convert_batches", "ccrn_import_batches", "ccrn_bulk_")):
            del st.session_state[key]
    st.session_state["qbm_browse_courses"] = [course_id]
    st.session_state["answer_key_courses"] = [course_id]
    st.session_state["qir_course_filter"] = [course_id]
    st.session_state["qbm_archive_course_filter"] = [course_id]
    st.session_state["_qbm_scope"] = course_id

from src.question_lenses import get_lenses, question_lens
LENSES = get_lenses()
lens_filter = st.selectbox("Question lens", ["all", *LENSES],
    format_func=lambda value: "All lenses" if value == "all" else LENSES[value], key="b_lens")
st.caption("Choose the lens once here for this workspace and new import batches. All lenses shows every lens and creates new batches as Standard / no lens. Existing batches retain their saved labels until you explicitly apply this selection.")

is_ccrn = course_title.strip().casefold() == "neonatal ccrn"
labels = ["Dashboard", "Coverage", "Paste & Batch Import", "Manage Questions"]
if is_ccrn:
    labels.append("Exam Preparation")
workspace_tabs = st.tabs(labels)
tab_dashboard, tab_coverage, tab_imports, tab_manage = workspace_tabs[:4]
tab_queue = tab_imports
with tab_imports:
    st.caption(f"Import destination: {course_title}. Paste, convert, review, and import saved batches below.")
    if not admin:
        st.info("An administrator can import questions for this subject.")
with tab_manage:
    manage_labels = ["Browse Questions"]
    if is_ccrn:
        manage_labels.append("Module & Batch Filters")
    if admin:
        manage_labels += ["Report Issues", "Archived Questions", "Answer Key", "Lenses"]
    manage_tabs = dict(zip(manage_labels, st.tabs(manage_labels)))
    tab_browse = manage_tabs["Browse Questions"]
    tab_reports = manage_tabs.get("Report Issues")
    tab_archive = manage_tabs.get("Archived Questions")
    tab_answer_key = manage_tabs.get("Answer Key")

if is_ccrn:
    from src.neonatal_ccrn import ensure_schema_and_catalog
    from src.ccrn_bank_workspace import render_ccrn_workspace
    ensure_schema_and_catalog()
    render_ccrn_workspace(course_id, user_id, admin, [
        tab_dashboard, workspace_tabs[4], tab_coverage, tab_queue,
        manage_tabs["Module & Batch Filters"],
    ])
else:
    from src.question_bank_workspace import render_subject_workspace
    render_subject_workspace(course_id, course_title, user_id, admin,
                             tab_dashboard, tab_coverage, tab_queue)


if admin:
    with tab_answer_key:
        from src.answer_key_ui import render_answer_key
        key_scope = [course_id]
        render_answer_key(key_scope, user_id)

if admin:
    with manage_tabs['Lenses']:
        from src.question_lens_ui import render_lens_manager
        render_lens_manager(course_id, course_title)

# ── Tab: Browse ───────────────────────────────────────────────────────────────
with tab_browse:
    browse_courses = get_all_courses() if admin else get_enrolled_courses(user_id)
    course_titles = {c["id"]: c["title"] for c in browse_courses}
    course_counts = {c["id"]: get_course_question_count(c["id"]) for c in browse_courses}
    selected_course_ids = [course_id]

    total = sum(course_counts.get(cid, 0) for cid in selected_course_ids)
    metric_label = (
        f"Questions in {course_titles[selected_course_ids[0]]}"
        if len(selected_course_ids) == 1
        else "Questions in selected courses"
    )
    matching_count = sum(1 for q in get_all_questions(course_id=course_id)
                         if lens_filter == 'all' or question_lens(q) == lens_filter)
    st.metric(metric_label + (f" · {LENSES[lens_filter]}" if lens_filter != 'all' else ''), matching_count)
    st.caption(f"{total:,} total active questions in this subject across all lenses.")

    if total == 0:
        selected_names = ", ".join(course_titles[cid] for cid in selected_course_ids)
        msg = f"No questions in **{selected_names}** yet." if selected_names else "No courses selected for browsing."
        if admin:
            msg += " Use the **Paste & Batch Import** tab above to add questions."
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
        st.caption(
            "Tip: this search automatically opens the first matching question below. "
            "For Ctrl+F or Cmd+F, use the browser-searchable index beneath the filters."
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
        if lens_filter != "all":
            questions = [q for q in questions if question_lens(q) == lens_filter]
        st.caption(f"{len(questions):,} questions match the selected filters and lens.")
        questions.sort(
            key=lambda q: (
                course_titles.get(q.get("course_id"), ""),
                q.get("question_id") or "",
                q.get("id") or 0,
            )
        )
        # Keep the non-text-filtered list for Previous/Next. A Bank # search may
        # return one row, but the user still needs to inspect its nearest neighbor.
        navigation_questions = list(questions)
        questions = _filter_questions_by_column_search(
            questions,
            query=q_search,
            field_labels=q_search_fields,
            match_mode=q_match_mode,
            course_titles=course_titles,
        )

        navigation_ids = [q["id"] for q in navigation_questions]
        search_signature = (
            q_search.strip(),
            q_match_mode,
            tuple(q_search_fields),
            tuple(q["id"] for q in questions),
        )
        if q_search.strip() and questions:
            if st.session_state.get("_qbm_last_search_signature") != search_signature:
                st.session_state["qbm_detail_question_id"] = questions[0]["id"]
            st.session_state["_qbm_last_search_signature"] = search_signature
        else:
            st.session_state["_qbm_last_search_signature"] = None

        if (
            navigation_ids
            and st.session_state.get("qbm_detail_question_id") not in navigation_ids
        ):
            st.session_state["qbm_detail_question_id"] = navigation_ids[0]

        st.caption(f"{len(questions)} question(s) match the filters")

        if not questions:
            st.info("No questions match those filters.")
        else:
            st.markdown("##### Browser-searchable question index")
            st.caption(
                "Use Ctrl+F (Windows) or Cmd+F (Mac) here. Browser Find will scroll "
                "this index to the matching Bank # and keep nearby questions visible."
            )
            # Keep the style and content in separate HTML elements. The app's
            # global theme intentionally hides style-only Streamlit containers.
            st.html("""
                <style>
                    .qbm-browser-index {
                        max-height: 11rem;
                        overflow: auto;
                        border: 1px solid rgba(128, 128, 128, 0.28);
                        border-radius: 0.5rem;
                        background: rgba(128, 128, 128, 0.04);
                        scroll-padding-block: 2.5rem;
                    }
                    .qbm-browser-index-row {
                        padding: 0.38rem 0.65rem;
                        border-bottom: 1px solid rgba(128, 128, 128, 0.16);
                        font-size: 0.84rem;
                        line-height: 1.3;
                    }
                    .qbm-browser-index-row:last-child { border-bottom: 0; }
                </style>
            """)
            st.html(_browser_searchable_question_index(questions, course_titles))

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
            previously_selected_ids = set(st.session_state["_qbm_selected_ids"])
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
            grid_selected_ids = {
                int(df_all.iloc[i]["ID"])
                for i in grid_event.selection.rows
                if 0 <= i < len(df_all)
            }
            st.session_state["_qbm_selected_ids"] = grid_selected_ids

            # A row click also opens that question in the detail panel. Keep this
            # separate from Select All so bulk actions do not unexpectedly move it.
            newly_selected_ids = grid_selected_ids - previously_selected_ids
            if len(newly_selected_ids) == 1:
                st.session_state["qbm_detail_question_id"] = newly_selected_ids.pop()

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
            q_ids    = navigation_ids
            q_labels = {
                q["id"]: f"#{q['id']} · {q.get('question_id','')} · "
                         f"{course_titles.get(q.get('course_id'), '')} · "
                         f"{str(q.get('stimulus',''))[:50]}"
                for q in navigation_questions
            }

            selected_index = q_ids.index(st.session_state["qbm_detail_question_id"])
            prev_col, select_col, next_col = st.columns([1, 4, 1])
            with prev_col:
                st.button(
                    "← Previous",
                    disabled=selected_index == 0,
                    use_container_width=True,
                    key="qbm_previous_question",
                    on_click=_select_detail_question,
                    args=(q_ids[max(0, selected_index - 1)],),
                )
            with select_col:
                sel_qid = st.selectbox(
                    "Select question:",
                    q_ids,
                    format_func=lambda x: q_labels.get(x, str(x)),
                    key="qbm_detail_question_id",
                )
            with next_col:
                st.button(
                    "Next →",
                    disabled=selected_index == len(q_ids) - 1,
                    use_container_width=True,
                    key="qbm_next_question",
                    on_click=_select_detail_question,
                    args=(q_ids[min(len(q_ids) - 1, selected_index + 1)],),
                )

            selected_index = q_ids.index(sel_qid)
            st.caption(
                f"Question {selected_index + 1} of {len(q_ids)} in the current "
                "course and filters. Previous/Next remains available while searching."
            )

            if sel_qid:
                q = next((x for x in navigation_questions if x["id"] == sel_qid), None)
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
        metrics = get_question_issue_metrics([course_id])
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
            report_course_ids = [course_id]

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
            selected_archive_course_ids = [course_id]

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
