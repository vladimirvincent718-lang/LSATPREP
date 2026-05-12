"""
pages/4_Question_Bank_Manager.py — Shared question bank per course.
All enrolled users can browse questions.
Only admins can upload or delete questions.

Changes in this version:
  - Upload summary now shows: rows read, valid, inserted, skipped-by-ID,
    skipped-by-content (identical question, different ID), invalid rows, errors.
  - Content-hash duplicate detection flags questions with identical text.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import io

from src.auth            import require_login
from src.utils           import page_header, sidebar_nav, require_course, DIFFICULTY_LABELS, get_effective_admin
from src.database        import (
    get_all_questions, get_course_question_count, delete_question,
    bulk_delete_questions,
    get_distinct_values, get_course, is_admin, get_all_courses,
)
from src.question_loader import process_upload, make_template_csv

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
            f"Shared questions — Course: {course_title}")

# ── Build tabs based on role ──────────────────────────────────────────────────
if admin:
    tab_browse, tab_upload, tab_template = st.tabs(
        ["🔎 Browse Questions", "⬆️ Upload CSV", "📄 Download Template"]
    )
else:
    tab_browse, tab_template = st.tabs(
        ["🔎 Browse Questions", "📄 Download Template"]
    )
    tab_upload = None


# ── Tab: Browse ───────────────────────────────────────────────────────────────
with tab_browse:
    total = get_course_question_count(course_id)
    st.metric(f"Questions in {course_title}", total)

    if total == 0:
        msg = f"No questions in **{course_title}** yet."
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
            sec_opts = ["All"] + get_distinct_values("section_type", course_id=course_id)
            f_sec    = st.selectbox("Section Type", sec_opts, key="b_sec")
        with col2:
            type_opts = ["All"] + get_distinct_values("question_type", course_id=course_id)
            f_type    = st.selectbox("Question Type", type_opts, key="b_type")
        with col3:
            d_min, d_max = st.select_slider(
                "Difficulty Range", options=[1,2,3,4,5], value=(1,5), key="b_diff"
            )

        questions = get_all_questions(
            section_type=None  if f_sec  == "All" else f_sec,
            question_type=None if f_type == "All" else f_type,
            min_difficulty=d_min,
            max_difficulty=d_max,
            course_id=course_id,
        )

        st.caption(f"{len(questions)} question(s) match the filters")

        if not questions:
            st.info("No questions match those filters.")
        else:
            # ── Selection state — managed entirely in our own key, never
            #    touching the data_editor widget key (Streamlit forbids that).
            #    _qbm_selected_ids is a set of integer question IDs.
            if "_qbm_selected_ids" not in st.session_state:
                st.session_state["_qbm_selected_ids"] = set()

            current_ids = {q["id"] for q in questions}   # IDs in current filter view

            # ── Admin bulk-delete toolbar ─────────────────────────────────────
            if admin:
                st.markdown("#### Bulk Delete")
                tb1, tb2, tb_spacer = st.columns([1.2, 1.2, 6.6])

                if tb1.button("☑ Select All", use_container_width=True):
                    st.session_state["_qbm_selected_ids"] = set(current_ids)
                    st.session_state.pop("qbm_confirm_delete", None)

                if tb2.button("☐ Deselect All", use_container_width=True):
                    st.session_state["_qbm_selected_ids"] = set()
                    st.session_state.pop("qbm_confirm_delete", None)

            # ── Build display rows — Select column reflects our own state ─────
            selected_set = st.session_state["_qbm_selected_ids"]
            rows = []
            for q in questions:
                s = str(q.get("stimulus", ""))
                rows.append({
                    "Select":      q["id"] in selected_set,   # driven by our state
                    "ID":          q["id"],
                    "question_id": q.get("question_id", ""),
                    "Section":     q.get("section_type", ""),
                    "Type":        q.get("question_type", ""),
                    "Difficulty":  DIFFICULTY_LABELS.get(q.get("difficulty", 3), ""),
                    "Stimulus":    s[:80] + "…" if len(s) > 80 else s,
                    "Source":      q.get("source", ""),
                })
            df_all = pd.DataFrame(rows)

            # ── Editable table with checkboxes ────────────────────────────────
            # We pass a fresh df on every render with Select values matching
            # _qbm_selected_ids.  The editor returns edited_df; we read it back
            # and sync to _qbm_selected_ids so the state persists across reruns.
            # We never write to st.session_state["qbm_question_editor"] directly
            # — Streamlit forbids that for widget keys.
            edited_df = st.data_editor(
                df_all.drop(columns=["ID"]),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Select": st.column_config.CheckboxColumn(
                        "Select",
                        help="Tick to include in bulk delete",
                        default=False,
                        width="small",
                    ),
                },
                disabled=["question_id","Section","Type","Difficulty","Stimulus","Source"],
                key="qbm_question_editor",
            )

            # Sync editor output → our state (handles individual checkbox clicks)
            st.session_state["_qbm_selected_ids"] = {
                int(df_all.iloc[i]["ID"])
                for i, row in edited_df.iterrows()
                if row["Select"]
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
                         f"{str(q.get('stimulus',''))[:50]}"
                for q in questions
            }
            sel_qid = st.selectbox("Select question:", q_ids,
                                    format_func=lambda x: q_labels.get(x, str(x)))

            if sel_qid:
                q = next((x for x in questions if x["id"] == sel_qid), None)
                if q:
                    with st.expander("📋 Full Question Details", expanded=True):
                        st.markdown(
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

        uploaded = st.file_uploader("Choose a CSV file", type=["csv"],
                                    key="qbank_upload")

        if uploaded is not None:
            st.markdown(f"**File:** {uploaded.name}  ({uploaded.size:,} bytes)")

            if st.button("✅ Import Questions", type="primary"):
                with st.spinner("Processing CSV…"):
                    result = process_upload(uploaded, course_id=target_id)

                st.divider()
                st.markdown("#### 📊 Upload Summary")

                # Metrics row
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                mc1.metric("Rows in file",     result["rows_read"])
                mc2.metric("✅ Inserted",       result["inserted"],
                           help="New questions added to the course")
                mc3.metric("⏭ Skipped (same ID)",
                           result["skipped_id"],
                           help="question_id already exists — skipped safely")
                mc4.metric("⏭ Skipped (same content)",
                           result["skipped_content"],
                           help="Identical question text already in this course "
                                "(same stimulus + choices + answer)")
                mc5.metric("❌ Invalid rows",   result["invalid"],
                           help="Rows with missing required fields or bad values")

                # Result message
                if result["inserted"]:
                    st.success(
                        f"✅ **{result['inserted']}** new question(s) added to "
                        f"**{target_title}**. All enrolled users can practise them now."
                    )
                elif result["skipped_id"] + result["skipped_content"] > 0:
                    st.info(
                        "All rows in this file are already in the database — "
                        "nothing new was added. "
                        f"({result['skipped_id']} matched by ID, "
                        f"{result['skipped_content']} matched by content)"
                    )
                else:
                    st.warning("No questions were imported. Check the errors below.")

                if result["skipped_content"] > 0:
                    st.warning(
                        f"⚠️ **{result['skipped_content']} question(s)** were skipped "
                        "because their content (stimulus + answer choices) is identical "
                        "to questions already in this course, even though the question_id "
                        "may differ. This usually means you uploaded the same questions "
                        "under new IDs."
                    )

                if result["errors"]:
                    with st.expander(
                        f"⚠️ {len(result['errors'])} validation error(s) — click to view",
                        expanded=True,
                    ):
                        for e in result["errors"][:30]:
                            st.caption(f"• {e}")
                        if len(result["errors"]) > 30:
                            st.caption(
                                f"… and {len(result['errors']) - 30} more. "
                                "Fix these in your CSV and re-upload."
                            )

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

1. **Same question_id** — if a row's `question_id` already exists in the database
   (across any course), it is skipped.  The `question_id` column is globally unique.

2. **Same content** — a fingerprint (hash) is computed from the question's
   *stimulus + all five choices + correct answer*.  If an identical fingerprint
   already exists in the **same course**, the row is skipped — even if it has a
   different `question_id`.  This catches re-uploaded batches with renamed IDs.

**Re-uploading the same CSV** will always result in 0 inserted and all rows
being skipped by one of the two checks above — no duplicates are created.
            """)


# ── Tab: Template ─────────────────────────────────────────────────────────────
with tab_template:
    st.markdown("### CSV Template")
    st.markdown("""
Download this template, fill in your questions, and upload via the **Upload CSV** tab.

**Required columns:**  
`question_id`, `stimulus`, `choice_a` through `choice_e`, `correct_answer`

**Optional but useful:**  
`section_type`, `question_type`, `difficulty` (1–5), `passage`, `explanation`,  
`wrong_answer_a–e`, `source`, `tags`

`section_type` — any text: `Logical Reasoning`, `Python Basics`, `Chapter 3`, etc.  
`question_type` — any text: `Weaken`, `Multiple Choice`, `True/False`, etc.  
`correct_answer` — must be `A`, `B`, `C`, `D`, or `E`  
`difficulty` — 1 (Easy) to 5 (Brutal), default 3
    """)

    csv_str = make_template_csv()
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
