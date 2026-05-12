"""
pages/2_Course_Manager.py — Browse and enroll in shared courses.
Admin users can also create, edit, archive, and clean up duplicate courses.

Changes in this version:
  - create_course() now checks for duplicate titles (case-insensitive).
  - New "🧹 Cleanup Duplicates" tab lets admins find and merge duplicate courses.
  - "Edit / Archive" tab also shows a safe-delete option for empty courses.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from src.auth     import require_login
from src.utils    import page_header, sidebar_nav, get_effective_admin
from src.database import (
    get_all_courses, get_enrolled_courses, get_course,
    enroll_user, unenroll_user, is_enrolled, get_enrollment_stats,
    create_course, update_course, archive_course, restore_course,
    delete_course_if_safe,
    force_unenroll_all_from_course,
    force_unenroll_users_from_course,
    get_course_enrollment_records,
    get_course_question_count, get_attempts, is_admin,
    get_materials, get_duplicate_course_groups, merge_into_course,
    get_all_courses_including_archived,
)

st.set_page_config(page_title="Course Manager · StudyForge",
                   page_icon="📚", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
page_header("📚 Course Manager", "Browse shared courses and manage your enrollments")

admin = is_admin(user_id)

# ── Admin view-mode: real_admin for security, admin for UI display ─────────────
real_admin, admin = get_effective_admin(user_id)

CATEGORIES = [
    "LSAT", "Bar Exam", "CPA / CFA", "Medical / USMLE",
    "Programming", "Mathematics", "Science", "Language",
    "History / Social Studies", "Business", "Other",
]

# ── Tab setup ─────────────────────────────────────────────────────────────────
if admin:
    tabs = st.tabs([
        "📋 All Courses",
        "➕ Create Course",
        "✏️ Edit / Archive",
        "🧹 Cleanup Duplicates",
    ])
    tab_browse, tab_create, tab_edit, tab_cleanup = tabs
else:
    tab_browse, = st.tabs(["📋 All Courses"])
    tab_create = tab_edit = tab_cleanup = None


# ── Tab 1: Browse all shared courses ─────────────────────────────────────────
with tab_browse:
    all_courses      = get_all_courses()
    enrolled_courses = get_enrolled_courses(user_id)
    enrolled_ids     = {c["id"] for c in enrolled_courses}

    if not all_courses:
        st.info(
            "No courses have been created yet."
            + (" Use the **Create Course** tab to add the first one." if admin else "")
        )
        st.stop()

    st.info(
        "📌 Courses are **shared** — everyone enrolled studies the same question bank "
        "and materials. Your scores and progress are always private to you."
    )

    active_id = st.session_state.get("active_course_id")
    if active_id and active_id in enrolled_ids:
        active = get_course(active_id)
        if active:
            st.success(f"✅ Active course: **{active['title']}**")

    st.divider()

    search_query = st.text_input(
        "🔍 Search courses",
        placeholder="Search by title, description, or category...",
    ).strip().lower()
    st.caption("Search by course title, description, or category.")

    if search_query:
        filtered_courses = [
            c for c in all_courses
            if search_query in (c.get("title") or "").lower()
            or search_query in (c.get("description") or "").lower()
            or search_query in (c.get("category") or "").lower()
        ]
    else:
        filtered_courses = all_courses

    if search_query and not filtered_courses:
        st.info("No courses matched your search.")

    for c in filtered_courses:
        cid       = c["id"]
        enrolled  = cid in enrolled_ids
        q_count   = get_course_question_count(cid)
        m_count   = len(get_materials(cid))
        enr_stats = get_enrollment_stats(cid)
        cat_badge = f"*{c['category']}*  ·  " if c.get("category") else ""

        with st.container(border=True):
            col_info, col_actions = st.columns([5, 2])

            with col_info:
                enrolled_tag = "  ✅ Enrolled" if enrolled else ""
                st.markdown(f"### 📘 {c['title']}{enrolled_tag}")
                if c.get("description"):
                    st.write(c["description"])
                st.caption(
                    f"{cat_badge}"
                    f"🗂 {q_count} questions  ·  "
                    f"📖 {m_count} materials  ·  "
                    f"👥 {enr_stats['active_learners']} learners enrolled"
                )

            with col_actions:
                st.markdown("")  # spacer

                if enrolled:
                    if st.button("📌 Set Active", key=f"active_{cid}",
                                 use_container_width=True):
                        st.session_state["active_course_id"] = cid
                        st.success(f"**{c['title']}** is now your active course.")
                        st.rerun()

                    if len(enrolled_ids) > 1:
                        if st.button("🚪 Leave Course", key=f"leave_{cid}",
                                     use_container_width=True):
                            unenroll_user(user_id, cid)
                            if st.session_state.get("active_course_id") == cid:
                                remaining = [x for x in enrolled_courses
                                             if x["id"] != cid]
                                if remaining:
                                    st.session_state["active_course_id"] = \
                                        remaining[0]["id"]
                            st.rerun()
                    else:
                        st.caption("(Must be in at least one course)")
                else:
                    if st.button("✅ Enroll", key=f"enroll_{cid}",
                                 use_container_width=True, type="primary"):
                        enroll_user(user_id, cid)
                        st.session_state["active_course_id"] = cid
                        st.success(f"Enrolled in **{c['title']}**!")
                        st.rerun()

    st.divider()
    st.caption(
        "Your enrolled courses appear in the sidebar dropdown on every page. "
        "Switch your active course there at any time."
    )


# ── Tab 2: Create course (admin only) ─────────────────────────────────────────
if tab_create is not None:
    with tab_create:
        st.markdown("### Create a New Shared Course")
        st.info(
            "This course will be immediately available to all users. "
            "Everyone will be auto-enrolled when a new course is created."
        )

        with st.form("create_course_form"):
            title       = st.text_input(
                "Course Title *",
                placeholder="e.g., LSAT Prep, Python Basics, CFA Level 1 – Ethics",
            )
            description = st.text_area(
                "Description",
                placeholder="What will students learn?",
                height=80,
            )
            category    = st.selectbox("Category", [""] + CATEGORIES)
            submitted   = st.form_submit_button("✅ Create Shared Course",
                                                 use_container_width=True)

        if submitted:
            if not title.strip():
                st.error("Course title is required.")
            else:
                cid, err = create_course(user_id, title.strip(), description, category)
                if err:
                    st.error(f"⚠️ {err}")
                else:
                    st.success(
                        f"✅ **{title.strip()}** created and shared with all users. "
                        "Go to **Question Bank Manager** to upload questions, "
                        "or **Course Materials** to add readings."
                    )
                    st.session_state["active_course_id"] = cid
                    st.rerun()


# ── Tab 3: Edit / archive (admin only) ────────────────────────────────────────
if tab_edit is not None:
    with tab_edit:
        all_c = get_all_courses()
        if not all_c:
            st.info("No courses to edit yet.")
            st.stop()

        course_opts = {c["id"]: c["title"] for c in all_c}
        sel_id = st.selectbox(
            "Choose a course to edit:",
            list(course_opts.keys()),
            format_func=lambda x: course_opts[x],
        )

        if sel_id:
            c = get_course(sel_id)
            if c:
                st.markdown(f"### Editing: {c['title']}")

                with st.form("edit_course_form"):
                    new_title = st.text_input("Course Title *", value=c["title"])
                    new_desc  = st.text_area(
                        "Description",
                        value=c.get("description", ""),
                        height=80,
                    )
                    cat_list  = [""] + CATEGORIES
                    cat_idx   = cat_list.index(c["category"]) \
                                if c.get("category") in cat_list else 0
                    new_cat   = st.selectbox("Category", cat_list, index=cat_idx)
                    save_btn  = st.form_submit_button("💾 Save Changes",
                                                       use_container_width=True)

                if save_btn:
                    if not new_title.strip():
                        st.error("Title cannot be empty.")
                    else:
                        update_course(sel_id, new_title.strip(), new_desc, new_cat)
                        st.success("Changes saved.")
                        st.rerun()

                st.divider()
                st.markdown("#### ⚠️ Archive Course")
                st.caption(
                    "Archiving hides this course from all users. "
                    "All questions, materials, and scores are preserved — nothing is deleted."
                )
                enr = get_enrollment_stats(sel_id)
                if enr["active_learners"] > 0:
                    st.warning(
                        f"⚠️ {enr['active_learners']} user(s) are currently enrolled. "
                        "Archiving will remove it from their sidebar."
                    )

                if st.checkbox(f"I want to archive **{c['title']}**",
                               key="archive_chk"):
                    if len(all_c) <= 1:
                        st.error("Cannot archive the only remaining course.")
                    elif st.button("🗃 Archive This Course", type="secondary"):
                        archive_course(sel_id)
                        st.success("Course archived.")
                        st.rerun()

                st.divider()
                st.markdown("#### 🗑 Delete Course (only if empty)")
                st.caption(
                    "A course can only be permanently deleted if it has "
                    "no questions, materials, attempts, or enrollments."
                )
                q_count = get_course_question_count(sel_id)
                m_count = len(get_materials(sel_id))
                if q_count or m_count:
                    st.info(
                        f"This course has **{q_count} question(s)** and "
                        f"**{m_count} material(s)** — it cannot be deleted. "
                        "Archive it instead."
                    )
                else:
                    # ── Session-state keys scoped to this course ──────────
                    _show_enr_key   = f"show_enr_panel_{sel_id}"
                    _selected_key   = f"enr_selected_{sel_id}"

                    if st.checkbox(f"Permanently delete **{c['title']}**",
                                   key="delete_chk"):

                        # ── Primary delete attempt ────────────────────────
                        if st.button("🗑 Delete permanently",
                                     key="delete_btn", type="secondary"):
                            ok, reason = delete_course_if_safe(sel_id)
                            if ok:
                                st.success("✅ Course deleted successfully.")
                                st.session_state.pop(_show_enr_key, None)
                                st.session_state.pop(_selected_key, None)
                                st.rerun()
                            elif reason and "enrollment" in reason.lower() and real_admin:
                                # Flip the panel open; don't nest another button.
                                st.session_state[_show_enr_key] = True
                            elif reason:
                                st.error(f"❌ {reason}")

                        # ── Admin enrollment panel (persists across reruns) ─
                        if real_admin and st.session_state.get(_show_enr_key):
                            enr_records = get_course_enrollment_records(sel_id)

                            st.warning(
                                f"⚠️ **{len(enr_records)} enrollment record(s)** "
                                "are blocking deletion (including stale / ghost "
                                "records). Select the records to remove below, "
                                "then delete the course."
                            )

                            if enr_records:
                                # ── Select-all checkbox ───────────────────
                                all_ids = [r["user_id"] for r in enr_records]
                                if _selected_key not in st.session_state:
                                    st.session_state[_selected_key] = set()

                                select_all = st.checkbox(
                                    "☑ Select all",
                                    key=f"sel_all_{sel_id}",
                                )
                                if select_all:
                                    st.session_state[_selected_key] = set(all_ids)

                                # ── Per-row checkboxes ────────────────────
                                st.markdown(
                                    "| | **Username** | **Status** | **Enrolled** |"
                                    "\n|---|---|---|---|"
                                )
                                for rec in enr_records:
                                    uid     = rec["user_id"]
                                    uname   = rec["username"]
                                    status  = rec["enrollment_status"]
                                    enr_at  = (rec["enrolled_at"] or "")[:10]
                                    row_key = f"enr_chk_{sel_id}_{uid}"
                                    checked = st.checkbox(
                                        f"**{uname}** — {status} *(enrolled {enr_at})*",
                                        value=(uid in st.session_state[_selected_key]),
                                        key=row_key,
                                    )
                                    if checked:
                                        st.session_state[_selected_key].add(uid)
                                    else:
                                        st.session_state[_selected_key].discard(uid)

                                selected = st.session_state[_selected_key]
                                st.caption(
                                    f"{len(selected)} of {len(enr_records)} "
                                    "record(s) selected."
                                )

                                col_remove, col_cancel = st.columns(2)

                                with col_remove:
                                    remove_label = (
                                        "🔓 Remove All Enrollments"
                                        if len(selected) == len(enr_records)
                                        else f"🔓 Remove {len(selected)} Selected"
                                    )
                                    if st.button(
                                        remove_label,
                                        key=f"remove_enr_{sel_id}",
                                        type="primary",
                                        use_container_width=True,
                                        disabled=(len(selected) == 0),
                                    ):
                                        removed, err = force_unenroll_users_from_course(
                                            sel_id, list(selected)
                                        )
                                        if err:
                                            st.error(f"❌ Failed: {err}")
                                        else:
                                            st.success(
                                                f"✅ {removed} enrollment record(s) removed."
                                            )
                                            st.session_state.pop(_selected_key, None)
                                            # Retry delete automatically
                                            ok2, reason2 = delete_course_if_safe(sel_id)
                                            if ok2:
                                                st.success("✅ Course deleted successfully.")
                                                st.session_state.pop(_show_enr_key, None)
                                                st.rerun()
                                            else:
                                                # Remaining records — refresh the panel
                                                st.rerun()

                                with col_cancel:
                                    if st.button(
                                        "✖ Cancel",
                                        key=f"cancel_enr_{sel_id}",
                                        use_container_width=True,
                                    ):
                                        st.session_state.pop(_show_enr_key, None)
                                        st.session_state.pop(_selected_key, None)
                                        st.rerun()
                            else:
                                st.info(
                                    "No enrollment records found — try deleting again."
                                )
                                if st.button("Retry Delete", key=f"retry_del_{sel_id}"):
                                    st.session_state.pop(_show_enr_key, None)
                                    st.rerun()


# ── Tab 4: Cleanup duplicate courses (admin only) ─────────────────────────────
if tab_cleanup is not None:
    with tab_cleanup:
        st.markdown("### 🧹 Clean Up Duplicate Courses")
        st.info(
            "This tool finds courses that have the **same title** "
            "(ignoring capitalisation and spaces), shows them as groups, "
            "and lets you choose which one to keep. "
            "All questions, materials, and exam history from the duplicates "
            "will be moved into the course you keep, then the duplicates "
            "will be **archived** (not deleted — your data is safe)."
        )

        dup_groups = get_duplicate_course_groups()

        if not dup_groups:
            st.success("✅ No duplicate courses found! Your course list is clean.")
        else:
            st.warning(
                f"Found **{len(dup_groups)} duplicate group(s)**. "
                "Use the forms below to resolve each one."
            )

            for gi, group in enumerate(dup_groups):
                normalized = group[0].get("normalized_title", group[0]["title"])
                st.markdown(f"---\n#### Group {gi + 1}: \"{normalized}\"")
                st.caption(f"{len(group)} courses share this title:")

                for crs in group:
                    qc = get_course_question_count(crs["id"])
                    mc = len(get_materials(crs["id"]))
                    enr = get_enrollment_stats(crs["id"])
                    st.markdown(
                        f"- **ID {crs['id']}** · \"{crs['title']}\"  "
                        f"| {qc} questions · {mc} materials · "
                        f"{enr['active_learners']} learners"
                    )

                keep_options = {
                    c["id"]: f"ID {c['id']} – \"{c['title']}\" "
                             f"({get_course_question_count(c['id'])} Q, "
                             f"{len(get_materials(c['id']))} M)"
                    for c in group
                }

                with st.form(f"merge_form_{gi}"):
                    keep_id = st.selectbox(
                        "Keep this course (all others will be archived):",
                        list(keep_options.keys()),
                        format_func=lambda x: keep_options[x],
                        key=f"keep_{gi}",
                    )
                    confirm = st.checkbox(
                        "I understand the other courses in this group "
                        "will be archived after their content is moved.",
                        key=f"confirm_{gi}",
                    )
                    merge_btn = st.form_submit_button(
                        "✅ Merge & Archive Duplicates",
                        use_container_width=True,
                    )

                if merge_btn:
                    if not confirm:
                        st.warning("Please tick the confirmation box first.")
                    else:
                        archive_ids = [c["id"] for c in group if c["id"] != keep_id]
                        summary = merge_into_course(keep_id, archive_ids)
                        st.success(
                            f"✅ Done!  "
                            f"Moved {summary['questions_moved']} question(s), "
                            f"{summary['materials_moved']} material(s) "
                            f"({summary['materials_skipped']} skipped — title conflict), "
                            f"{summary['attempts_moved']} attempt(s).  "
                            f"Archived {summary['archived']} duplicate course(s)."
                        )
                        st.rerun()

        # ── Show archived courses (optional restore) ──────────────────────────
        st.divider()
        st.markdown("#### Archived Courses")
        st.caption(
            "These courses are hidden from users but their data is preserved. "
            "You can restore them if needed."
        )
        all_with_archived = get_all_courses_including_archived()
        archived = [c for c in all_with_archived if not c["is_active"]]
        if not archived:
            st.caption("No archived courses.")
        else:
            for c in archived:
                col_a, col_b = st.columns([5, 2])
                with col_a:
                    qc = get_course_question_count(c["id"])
                    st.markdown(
                        f"🗃 **{c['title']}** (ID {c['id']})  —  {qc} questions"
                    )
                with col_b:
                    if st.button("♻️ Restore", key=f"restore_{c['id']}",
                                 use_container_width=True):
                        restore_course(c["id"])
                        st.success(f"**{c['title']}** restored.")
                        st.rerun()
