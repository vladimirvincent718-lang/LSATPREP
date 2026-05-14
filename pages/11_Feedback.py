"""
pages/11_Feedback.py — Feedback & Suggestions for StudyForge.

Regular users:
  - Submit new feedback (bug, feature request, etc.)
  - View their own submission history + admin responses

Admin users:
  - All of the above
  - Full feedback management panel with filters, inline editing, and metrics
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime

from src.auth     import require_login
from src.utils    import page_header, sidebar_nav, get_effective_admin
from src.database import (
    is_admin,
    create_feedback_item,
    get_user_feedback,
    get_all_feedback,
    update_feedback_item,
    get_feedback_metrics,
)

st.set_page_config(
    page_title="Feedback · StudyForge",
    page_icon="💬",
    layout="wide",
)

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
page_header("💬 Feedback & Suggestions",
            "Report issues, suggest features, or share ideas to improve StudyForge")

# ── Admin checks ───────────────────────────────────────────────────────────────
# real_admin → controls whether the Admin Panel tab is actually functional
# effective_admin → controls whether the Admin Panel tab is *visible* in the UI
real_admin, effective_admin = get_effective_admin(user_id)
FEEDBACK_TYPES  = ["Bug", "Feature Request", "Improvement", "Content Issue", "Other"]
AREAS           = ["", "Dashboard", "Curriculum Builder",
                   "Course Materials", "Question Bank", "Practice Mode",
                   "Timed Exam", "Full Exam", "Curriculum Exam",
                   "Score History", "Review Mistakes", "Settings", "Other"]
USER_PRIORITIES = ["Low", "Medium", "High"]
ADMIN_STATUSES  = ["New", "Reviewed", "Planned", "In Progress",
                   "Implemented", "Rejected", "Duplicate", "Needs More Info"]
ADMIN_PRIORITIES = ["Low", "Medium", "High", "Critical"]

STATUS_ICONS = {
    "New":            "🆕",
    "Reviewed":       "👀",
    "Planned":        "📋",
    "In Progress":    "🔧",
    "Implemented":    "✅",
    "Rejected":       "❌",
    "Duplicate":      "🔁",
    "Needs More Info": "❓",
}

TYPE_ICONS = {
    "Bug":             "🐛",
    "Feature Request": "✨",
    "Improvement":     "⚡",
    "Content Issue":   "📝",
    "Other":           "💬",
}

admin = effective_admin  # alias: UI visibility controlled by view-mode preview

# ── Tab layout ─────────────────────────────────────────────────────────────────
if admin:
    tab_submit, tab_mine, tab_admin = st.tabs(
        ["📨 Submit Feedback", "📂 My Submissions", "🔑 Admin Panel"]
    )
else:
    tab_submit, tab_mine = st.tabs(
        ["📨 Submit Feedback", "📂 My Submissions"]
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SUBMIT FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════
with tab_submit:
    st.markdown("### Submit New Feedback")
    st.caption("All fields marked with \\* are required.")

    with st.form("submit_feedback_form", clear_on_submit=True):
        col_type, col_priority = st.columns([2, 1])
        with col_type:
            fb_type = st.selectbox(
                "Feedback Type *",
                options=FEEDBACK_TYPES,
                index=0,
            )
        with col_priority:
            fb_priority = st.selectbox(
                "Your Priority",
                options=USER_PRIORITIES,
                index=1,
                help="How urgent is this from your perspective?",
            )

        fb_title = st.text_input(
            "Short Summary *",
            max_chars=120,
            placeholder="One-line description of your feedback…",
        )

        fb_description = st.text_area(
            "Detailed Description *",
            height=140,
            placeholder=(
                "Describe the issue or idea in detail.\n"
                "For bugs: include steps to reproduce and what you expected to happen."
            ),
        )

        col_area, _ = st.columns([2, 1])
        with col_area:
            fb_area = st.selectbox(
                "Area / Page Affected (optional)",
                options=AREAS,
                format_func=lambda x: x if x else "— Not specified —",
            )

        submitted = st.form_submit_button("Submit Feedback", type="primary",
                                          use_container_width=True)

    if submitted:
        fid, err = create_feedback_item(
            user_id=user_id,
            feedback_type=fb_type,
            title=fb_title,
            description=fb_description,
            area=fb_area or "",
            user_priority=fb_priority,
        )
        if err:
            st.error(f"❌ {err}")
        else:
            st.success(
                f"✅ **Feedback submitted!** (#{fid})  \n"
                "Thank you — your submission has been recorded and will be reviewed."
            )
            st.balloons()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MY SUBMISSIONS
# ══════════════════════════════════════════════════════════════════════════════
with tab_mine:
    st.markdown("### My Submitted Feedback")

    my_items = get_user_feedback(user_id)

    if not my_items:
        st.info("You haven't submitted any feedback yet. Use the **Submit Feedback** tab to get started.")
    else:
        st.caption(f"Showing {len(my_items)} submission(s)")

        for item in my_items:
            status_icon = STATUS_ICONS.get(item["status"], "•")
            type_icon   = TYPE_ICONS.get(item["feedback_type"], "💬")
            created     = item.get("created_at", "")[:10] if item.get("created_at") else "—"
            implemented_marker = " ✅" if item.get("is_implemented") else ""

            header = (
                f"{type_icon} **{item['title']}** "
                f"&nbsp;|&nbsp; {status_icon} {item['status']}{implemented_marker} "
                f"&nbsp;|&nbsp; {item['feedback_type']} "
                f"&nbsp;|&nbsp; 📅 {created}"
            )
            with st.expander(header, expanded=False):
                col_l, col_r = st.columns([3, 1])
                with col_l:
                    st.markdown(f"**Description:**")
                    st.markdown(item["description"])
                with col_r:
                    st.markdown(f"**Type:** {item['feedback_type']}")
                    st.markdown(f"**Your Priority:** {item.get('user_priority', '—')}")
                    if item.get("area"):
                        st.markdown(f"**Area:** {item['area']}")
                    if item.get("implemented_at"):
                        st.markdown(f"**Implemented:** {str(item['implemented_at'])[:10]}")

                if item.get("admin_notes"):
                    st.divider()
                    st.markdown("**📩 Admin Response:**")
                    st.info(item["admin_notes"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ADMIN PANEL  (admin only)
# ══════════════════════════════════════════════════════════════════════════════
if admin:
    with tab_admin:
        st.markdown("### Feedback Management")

        # ── Metrics ──────────────────────────────────────────────────────────
        metrics = get_feedback_metrics()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total",       metrics.get("total", 0))
        c2.metric("New",         metrics.get("new_count", 0))
        c3.metric("Active",      metrics.get("active_count", 0),
                  help="In Progress + Planned")
        c4.metric("Implemented", metrics.get("implemented_count", 0))
        c5.metric("Closed",      metrics.get("closed_count", 0),
                  help="Rejected + Duplicate")

        st.divider()

        # ── Filters ───────────────────────────────────────────────────────────
        with st.expander("🔍 Filters & Search", expanded=True):
            fc1, fc2, fc3, fc4, fc5 = st.columns(5)
            with fc1:
                f_search = st.text_input("Keyword search", placeholder="title / description / user…")
            with fc2:
                f_status = st.selectbox("Status", ["All"] + ADMIN_STATUSES)
            with fc3:
                f_type = st.selectbox("Type", ["All"] + FEEDBACK_TYPES)
            with fc4:
                f_priority = st.selectbox("User Priority", ["All"] + USER_PRIORITIES)
            with fc5:
                f_impl = st.selectbox("Implemented?", ["All", "Yes", "No"])

        # Resolve filter values
        filter_status   = None if f_status   == "All" else f_status
        filter_type     = None if f_type     == "All" else f_type
        filter_priority = None if f_priority == "All" else f_priority
        filter_impl     = None if f_impl     == "All" else (f_impl == "Yes")
        filter_search   = f_search.strip() or None

        all_items = get_all_feedback(
            status=filter_status,
            feedback_type=filter_type,
            priority=filter_priority,
            implemented=filter_impl,
            search=filter_search,
        )

        st.caption(f"Showing {len(all_items)} item(s)")

        if not all_items:
            st.info("No feedback items match the current filters.")
        else:
            for item in all_items:
                status_icon = STATUS_ICONS.get(item["status"], "•")
                type_icon   = TYPE_ICONS.get(item["feedback_type"], "💬")
                created     = item.get("created_at", "")[:10] if item.get("created_at") else "—"
                impl_badge  = " ✅ Implemented" if item.get("is_implemented") else ""

                exp_label = (
                    f"[#{item['id']}] {type_icon} **{item['title']}** "
                    f"&nbsp;|&nbsp; {status_icon} {item['status']}{impl_badge} "
                    f"&nbsp;|&nbsp; 👤 {item.get('username', '?')} "
                    f"&nbsp;|&nbsp; 📅 {created}"
                )

                with st.expander(exp_label, expanded=False):
                    # ── Read-only detail row ──────────────────────────────────
                    info_cols = st.columns([2, 1, 1, 1])
                    with info_cols[0]:
                        st.markdown(f"**Description:**")
                        st.markdown(item["description"])
                    with info_cols[1]:
                        st.markdown(f"**Type:** {item['feedback_type']}")
                        st.markdown(f"**Area:** {item.get('area') or '—'}")
                        st.markdown(f"**User Priority:** {item.get('user_priority', '—')}")
                    with info_cols[2]:
                        st.markdown(f"**Submitted by:** {item.get('username', '—')}")
                        st.markdown(f"**Submitted:** {created}")
                        upd = item.get("updated_at", "")
                        st.markdown(f"**Last updated:** {upd[:10] if upd else '—'}")
                    with info_cols[3]:
                        if item.get("implemented_at"):
                            st.markdown(f"**Impl. date:** {str(item['implemented_at'])[:10]}")
                        else:
                            st.markdown("**Impl. date:** —")

                    st.divider()

                    # ── Editable admin section ────────────────────────────────
                    form_key = f"admin_edit_{item['id']}"
                    with st.form(form_key):
                        edit_cols = st.columns([2, 1, 1])
                        with edit_cols[0]:
                            new_status = st.selectbox(
                                "Status",
                                options=ADMIN_STATUSES,
                                index=ADMIN_STATUSES.index(item["status"])
                                      if item["status"] in ADMIN_STATUSES else 0,
                                key=f"status_{item['id']}",
                            )
                            new_admin_priority = st.selectbox(
                                "Admin Priority",
                                options=ADMIN_PRIORITIES,
                                index=ADMIN_PRIORITIES.index(item.get("admin_priority", "Medium"))
                                      if item.get("admin_priority") in ADMIN_PRIORITIES else 1,
                                key=f"aprio_{item['id']}",
                            )
                        with edit_cols[1]:
                            new_implemented = st.checkbox(
                                "Mark as Implemented",
                                value=bool(item.get("is_implemented")),
                                key=f"impl_{item['id']}",
                            )
                            # Allow admin to manually override the implemented date
                            current_impl_date = ""
                            if item.get("implemented_at"):
                                try:
                                    current_impl_date = str(item["implemented_at"])[:10]
                                except Exception:
                                    current_impl_date = ""
                            new_impl_date = st.text_input(
                                "Implemented Date (YYYY-MM-DD)",
                                value=current_impl_date,
                                placeholder="Leave blank to auto-set",
                                key=f"impldate_{item['id']}",
                            )
                        with edit_cols[2]:
                            new_notes = st.text_area(
                                "Admin Notes / Response",
                                value=item.get("admin_notes") or "",
                                height=120,
                                key=f"notes_{item['id']}",
                                placeholder="Visible to the submitting user…",
                            )

                        save_btn = st.form_submit_button(
                            "💾 Save Changes", type="primary"
                        )

                    if save_btn:
                        # Security guard: only a real admin can persist changes
                        if not real_admin:
                            st.error("❌ Permission denied. Real admin access required.")
                            st.stop()
                        # Validate optional date input
                        impl_date_to_save = new_impl_date.strip() or None
                        if impl_date_to_save:
                            try:
                                datetime.strptime(impl_date_to_save, "%Y-%m-%d")
                            except ValueError:
                                st.error("Invalid date format. Use YYYY-MM-DD.")
                                st.stop()

                        # Auto-set status to Implemented when checkbox is ticked
                        resolved_status = new_status
                        if new_implemented and resolved_status not in ("Implemented",):
                            resolved_status = "Implemented"

                        update_feedback_item(
                            feedback_id=item["id"],
                            status=resolved_status,
                            admin_priority=new_admin_priority,
                            is_implemented=new_implemented,
                            admin_notes=new_notes,
                            implemented_at=impl_date_to_save,
                        )
                        st.success("✅ Changes saved.")
                        st.rerun()
