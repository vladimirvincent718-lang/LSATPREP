"""
pages/2a_Curriculum_Builder.py — Create and manage curriculum groups.

A Curriculum is a named collection of existing courses.  Courses remain
globally available; adding a course to a curriculum never hides it elsewhere.

Admin users can:
  - Create / edit / delete curriculums
  - Add / remove courses from a curriculum
  - View question counts per course inside a curriculum
  - Manage saved weighting presets (used by the Curriculum Exam Builder)

Non-admin users can browse and view curriculums.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from src.auth     import require_login
from src.utils    import page_header, sidebar_nav, get_effective_admin
from src.database import (
    is_admin,
    get_all_curriculums, get_curriculum, create_curriculum,
    update_curriculum, delete_curriculum, archive_curriculum,
    get_curriculum_courses, get_courses_not_in_curriculum,
    add_course_to_curriculum, remove_course_from_curriculum,
    get_weight_presets, create_weight_preset,
    update_weight_preset, delete_weight_preset,
    get_course_question_count, init_curriculum_tables,
)

st.set_page_config(
    page_title="Curriculum Builder · StudyForge",
    page_icon="🎓",
    layout="wide",
)

# Ensure tables exist before any DB call
init_curriculum_tables()

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
page_header("🎓 Curriculum Builder",
            "Group courses into larger learning paths")

real_admin, admin = get_effective_admin(user_id)

# ── Tab setup ─────────────────────────────────────────────────────────────────
if admin:
    tabs = st.tabs([
        "📋 Browse Curriculums",
        "➕ Create Curriculum",
        "✏️ Edit Curriculum",
        "⚖️ Weight Presets",
    ])
    tab_browse, tab_create, tab_edit, tab_presets = tabs
else:
    tab_browse, = st.tabs(["📋 Browse Curriculums"])
    tab_create = tab_edit = tab_presets = None


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Browse Curriculums
# ═══════════════════════════════════════════════════════════════════════════════
with tab_browse:
    curriculums = get_all_curriculums()

    if not curriculums:
        if admin:
            st.info("No curriculums yet. Use the **Create Curriculum** tab to add one.")
        else:
            st.info("No curriculums have been created yet.")
        st.stop()

    st.caption(
        f"**{len(curriculums)}** curriculum(s) available.  "
        "Courses inside a curriculum remain globally accessible — adding a course here "
        "does **not** move or hide it."
    )
    st.divider()

    for curr in curriculums:
        courses = get_curriculum_courses(curr["id"])
        total_q = sum(get_course_question_count(c["id"]) for c in courses)

        with st.container(border=True):
            col_info, col_stats = st.columns([4, 2])

            with col_info:
                st.markdown(f"### 🎓 {curr['title']}")
                if curr.get("description"):
                    st.write(curr["description"])
                if courses:
                    st.markdown("**Courses:**")
                    for c in courses:
                        q = get_course_question_count(c["id"])
                        st.markdown(f"  - 📘 **{c['title']}** — {q} question(s)")
                else:
                    st.caption("_No courses added yet._")

            with col_stats:
                st.metric("Courses", len(courses))
                st.metric("Total Questions", total_q)
                if admin:
                    if st.button("✏️ Edit", key=f"edit_btn_{curr['id']}"):
                        st.session_state["edit_curriculum_id"] = curr["id"]
                        st.info("Switch to the **Edit Curriculum** tab.")

        st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Create Curriculum  (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
if tab_create is not None:
    with tab_create:
        st.subheader("Create a New Curriculum")
        st.caption(
            "A curriculum groups existing courses into one learning path. "
            "You can add courses after creation."
        )

        with st.form("create_curriculum_form"):
            new_title = st.text_input("Curriculum Title *",
                                      placeholder="e.g. CFA Level I, Bar Exam Prep…")
            new_desc  = st.text_area("Description",
                                     placeholder="Optional — describe what this curriculum covers.",
                                     height=100)
            submitted = st.form_submit_button("✅ Create Curriculum", type="primary",
                                              use_container_width=True)

        if submitted:
            if not new_title.strip():
                st.error("Curriculum title is required.")
            else:
                cid, err = create_curriculum(user_id, new_title, new_desc)
                if err:
                    st.error(err)
                else:
                    st.success(f"✅ Curriculum **\"{new_title}\"** created (ID {cid})!")
                    st.session_state["edit_curriculum_id"] = cid
                    st.info("Switch to **Edit Curriculum** to add courses now.")
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Edit Curriculum  (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
if tab_edit is not None:
    with tab_edit:
        curriculums = get_all_curriculums()

        if not curriculums:
            st.info("No curriculums yet. Create one first.")
            st.stop()

        # Curriculum picker
        curr_options = {c["id"]: c["title"] for c in curriculums}
        default_id   = st.session_state.get("edit_curriculum_id")
        default_idx  = (
            list(curr_options.keys()).index(default_id)
            if default_id and default_id in curr_options else 0
        )

        selected_cid = st.selectbox(
            "Select Curriculum to Edit",
            options=list(curr_options.keys()),
            format_func=lambda x: curr_options[x],
            index=default_idx,
            key="edit_curr_select",
        )
        curr = get_curriculum(selected_cid)
        if not curr:
            st.error("Curriculum not found.")
            st.stop()

        st.divider()

        # ── Edit title / description ──────────────────────────────────────────
        with st.expander("✏️ Edit Name & Description", expanded=False):
            with st.form(f"edit_meta_{selected_cid}"):
                e_title = st.text_input("Title", value=curr["title"])
                e_desc  = st.text_area("Description", value=curr.get("description", ""),
                                       height=80)
                if st.form_submit_button("💾 Save Changes", type="primary"):
                    if not e_title.strip():
                        st.error("Title cannot be empty.")
                    else:
                        update_curriculum(selected_cid, e_title, e_desc)
                        st.success("Curriculum updated.")
                        st.rerun()

        # ── Add courses ───────────────────────────────────────────────────────
        st.subheader(f"Courses in **{curr['title']}**")

        current_courses  = get_curriculum_courses(selected_cid)
        available_courses = get_courses_not_in_curriculum(selected_cid)

        if current_courses:
            for c in current_courses:
                q_count = get_course_question_count(c["id"])
                col_name, col_q, col_rm = st.columns([5, 2, 1])
                with col_name:
                    st.markdown(f"📘 **{c['title']}**")
                    if c.get("description"):
                        st.caption(c["description"][:80])
                with col_q:
                    st.caption(f"{q_count} question(s)")
                with col_rm:
                    if st.button("➖", key=f"rm_{selected_cid}_{c['id']}",
                                 help=f"Remove {c['title']} from curriculum"):
                        remove_course_from_curriculum(selected_cid, c["id"])
                        st.success(f"Removed **{c['title']}**.")
                        st.rerun()
        else:
            st.info("No courses added yet. Add courses below.")

        st.divider()
        st.subheader("Add a Course")

        if available_courses:
            add_options = {c["id"]: c["title"] for c in available_courses}
            to_add = st.selectbox(
                "Choose a course to add",
                options=list(add_options.keys()),
                format_func=lambda x: add_options[x],
                key=f"add_course_select_{selected_cid}",
            )
            if st.button("➕ Add to Curriculum", type="primary"):
                ok, err = add_course_to_curriculum(selected_cid, to_add)
                if ok:
                    added_name = add_options[to_add]
                    st.success(f"Added **{added_name}**.")
                    st.rerun()
                else:
                    st.error(err)
        else:
            st.success("✅ All active courses are already in this curriculum.")

        st.divider()

        # ── Danger zone: delete ───────────────────────────────────────────────
        with st.expander("🗑️ Delete Curriculum", expanded=False):
            st.warning(
                "⚠️ This permanently deletes the curriculum and all its course "
                "associations and weight presets.  **Courses themselves are not affected.**"
            )
            confirm = st.text_input(
                f'Type the curriculum name to confirm: **{curr["title"]}**',
                key=f"del_confirm_{selected_cid}",
            )
            if st.button("🗑️ Delete Permanently", type="secondary"):
                if confirm.strip() == curr["title"]:
                    delete_curriculum(selected_cid)
                    st.success("Curriculum deleted.")
                    st.session_state.pop("edit_curriculum_id", None)
                    st.rerun()
                else:
                    st.error("Name doesn't match. Deletion cancelled.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Weight Presets  (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
if tab_presets is not None:
    with tab_presets:
        st.subheader("⚖️ Weighting Presets")
        st.caption(
            "Save percentage distributions for weighted mock exams. "
            "Presets are per-curriculum and can be loaded in the **Curriculum Exam Builder**."
        )

        curriculums = get_all_curriculums()
        if not curriculums:
            st.info("Create a curriculum first.")
            st.stop()

        curr_options = {c["id"]: c["title"] for c in curriculums}
        sel_cid = st.selectbox(
            "Curriculum",
            options=list(curr_options.keys()),
            format_func=lambda x: curr_options[x],
            key="preset_curr_sel",
        )

        courses = get_curriculum_courses(sel_cid)
        if not courses:
            st.warning("Add courses to this curriculum first.")
            st.stop()

        presets = get_weight_presets(sel_cid)

        # ── Existing presets ──────────────────────────────────────────────────
        if presets:
            st.markdown("**Saved Presets:**")
            for p in presets:
                with st.container(border=True):
                    cols = st.columns([4, 1, 1])
                    cols[0].markdown(f"**{p['name']}**")

                    # Show distribution
                    w = p["weights"]
                    total_w = sum(float(v) for v in w.values())
                    rows_md = []
                    for c in courses:
                        pct = float(w.get(str(c["id"]), w.get(c["id"], 0)))
                        rows_md.append(f"  - {c['title']}: **{pct}%**")
                    rows_md.append(f"\n  **Total: {total_w:.1f}%**")
                    st.markdown("\n".join(rows_md))

                    with cols[1]:
                        if st.button("✏️ Edit", key=f"ep_edit_{p['id']}"):
                            st.session_state[f"editing_preset_{sel_cid}"] = p["id"]
                            st.rerun()
                    with cols[2]:
                        if st.button("🗑️ Delete", key=f"ep_del_{p['id']}"):
                            delete_weight_preset(p["id"])
                            st.success("Preset deleted.")
                            st.rerun()

        st.divider()

        # ── Create or edit preset ─────────────────────────────────────────────
        editing_pid = st.session_state.get(f"editing_preset_{sel_cid}")
        editing_preset = None
        if editing_pid:
            for p in presets:
                if p["id"] == editing_pid:
                    editing_preset = p
                    break

        form_title = f"✏️ Edit Preset: {editing_preset['name']}" if editing_preset else "➕ Create New Preset"
        st.subheader(form_title)

        default_name = editing_preset["name"] if editing_preset else ""
        preset_name  = st.text_input("Preset Name", value=default_name,
                                     placeholder="e.g. CFA L1 Official Weights",
                                     key=f"pname_{sel_cid}_{editing_pid}")

        st.markdown("**Set weight (%) for each course — must total 100%:**")
        weight_inputs = {}
        total_weight  = 0.0

        for c in courses:
            existing_w = 0.0
            if editing_preset:
                w = editing_preset["weights"]
                existing_w = float(w.get(str(c["id"]), w.get(c["id"], 0)))

            val = st.number_input(
                f"{c['title']}",
                min_value=0.0,
                max_value=100.0,
                value=existing_w,
                step=0.5,
                format="%.1f",
                key=f"w_{sel_cid}_{c['id']}_{editing_pid}",
            )
            weight_inputs[c["id"]] = val
            total_weight += val

        # Live total indicator
        if abs(total_weight - 100.0) < 0.01:
            st.success(f"✅ Total: {total_weight:.1f}% — valid")
        elif total_weight > 100.0:
            st.error(f"❌ Total: {total_weight:.1f}% — exceeds 100%. Please reduce some weights.")
        else:
            remaining = 100.0 - total_weight
            st.warning(f"⚠️ Total: {total_weight:.1f}% — still {remaining:.1f}% unallocated.")

        col_save, col_cancel = st.columns(2)
        with col_save:
            if st.button("💾 Save Preset", type="primary", use_container_width=True):
                if not preset_name.strip():
                    st.error("Preset name is required.")
                elif abs(total_weight - 100.0) >= 0.1:
                    st.error(f"Weights must total 100%. Currently: {total_weight:.1f}%")
                else:
                    str_weights = {str(cid): w for cid, w in weight_inputs.items()}
                    if editing_preset:
                        update_weight_preset(editing_pid, preset_name, str_weights)
                        st.success(f"Preset **\"{preset_name}\"** updated.")
                        st.session_state.pop(f"editing_preset_{sel_cid}", None)
                    else:
                        pid, err = create_weight_preset(sel_cid, preset_name, str_weights)
                        if err:
                            st.error(err)
                        else:
                            st.success(f"Preset **\"{preset_name}\"** saved.")
                    st.rerun()

        with col_cancel:
            if editing_preset:
                if st.button("✖ Cancel Edit", use_container_width=True):
                    st.session_state.pop(f"editing_preset_{sel_cid}", None)
                    st.rerun()
