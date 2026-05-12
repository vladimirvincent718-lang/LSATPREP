"""
pages/3_Course_Materials.py — Shared course materials.
All enrolled users can view materials and track their own completion.
Only admins can add, edit, or archive materials.
"""

import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from src.auth     import require_login
from src.utils    import page_header, sidebar_nav, require_course, get_effective_admin
from src.database import (
    get_materials, create_material, update_material,
    archive_material, delete_material,
    set_material_progress, get_material_progress, get_course,
    MATERIAL_TYPES, is_admin,
)

st.set_page_config(page_title="Course Materials · StudyForge",
                   page_icon="📖", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"
real_admin, admin = get_effective_admin(user_id)

page_header("📖 Course Materials", f"Course: {course_title}")

# ── Constants ─────────────────────────────────────────────────────────────────
PROGRESS_OPTIONS = ["Not Started", "In Progress", "Completed"]
STATUS_ICONS     = {"Not Started": "⬜", "In Progress": "🔄", "Completed": "✅"}
STATUS_COLORS    = {"Not Started": "#6B7280", "In Progress": "#F59E0B", "Completed": "#10B981"}

TYPE_META = {
    "Reading":           ("📖", "#3B82F6"),
    "Video":             ("🎬", "#EF4444"),
    "Link":              ("🔗", "#10B981"),
    "Notes":             ("📝", "#F59E0B"),
    "PDF/Document Link": ("📄", "#F97316"),
    "Other":             ("📦", "#9CA3AF"),
}

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.mat-card {
    border: 1px solid #E5E7EB;
    border-radius: 14px;
    padding: 0;
    margin-bottom: 16px;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 10px rgba(0,0,0,.04);
    transition: box-shadow .2s, transform .2s;
    overflow: hidden;
}
.mat-card:hover {
    box-shadow: 0 4px 18px rgba(0,0,0,.10);
    transform: translateY(-1px);
}
.mat-card-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px;
    border-bottom: 1px solid #F3F4F6;
}
.mat-accent-bar {
    width: 5px;
    height: 100%;
    min-height: 52px;
    border-radius: 3px;
    flex-shrink: 0;
}
.mat-icon {
    font-size: 24px;
    width: 42px;
    height: 42px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 10px;
    flex-shrink: 0;
}
.mat-title-block { flex: 1; min-width: 0; }
.mat-title {
    font-size: 15px;
    font-weight: 700;
    color: #111827;
    line-height: 1.3;
    margin-bottom: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.mat-subtitle {
    font-size: 12px;
    color: #9CA3AF;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}
.mat-subtitle span { display: flex; align-items: center; gap: 3px; }
.mat-status-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: .03em;
    border-radius: 99px;
    padding: 4px 11px;
    white-space: nowrap;
    flex-shrink: 0;
}
/* Content rendered as markdown */
.mat-body {
    padding: 20px 24px;
    font-size: 14px;
    line-height: 1.75;
    color: #374151;
}
.mat-body h1 { font-size: 1.35em; font-weight: 800; margin: .9em 0 .35em; color: #111827; }
.mat-body h2 { font-size: 1.15em; font-weight: 700; margin: .8em 0 .3em; color: #1F2937; border-bottom: 1px solid #E5E7EB; padding-bottom: .2em; }
.mat-body h3 { font-size: 1.02em; font-weight: 700; margin: .7em 0 .25em; color: #374151; }
.mat-body p  { margin: .5em 0; }
.mat-body hr { border: none; border-top: 1px solid #E5E7EB; margin: 1.2em 0; }
.mat-body ul, .mat-body ol { padding-left: 1.4em; margin: .4em 0; }
.mat-body li { margin: .25em 0; }
.mat-body table { width: 100%; border-collapse: collapse; font-size: 13px; margin: .8em 0; }
.mat-body th, .mat-body td { border: 1px solid #E5E7EB; padding: 7px 12px; text-align: left; }
.mat-body th { background: #F9FAFB; font-weight: 600; }
.mat-body code { background: #F3F4F6; border-radius: 4px; padding: 1px 5px; font-size: .9em; }
.mat-link-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border-radius: 9px;
    background: #EFF6FF;
    color: #1D4ED8 !important;
    text-decoration: none !important;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid #BFDBFE;
    transition: background .15s;
}
.mat-link-btn:hover { background: #DBEAFE; }
.mat-notes-callout {
    display: flex;
    gap: 8px;
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 8px;
    padding: 9px 13px;
    font-size: 12.5px;
    color: #92400E;
    margin-top: 12px;
}
@media (prefers-color-scheme: dark) {
    .mat-card { background: #1F2937; border-color: rgba(255,255,255,.08); }
    .mat-card-header { border-bottom-color: rgba(255,255,255,.06); }
    .mat-title { color: #F9FAFB; }
    .mat-body  { color: #D1D5DB; }
    .mat-body h1,.mat-body h2,.mat-body h3 { color: #F9FAFB; }
    .mat-body hr,.mat-body th,.mat-body td  { border-color: #374151; }
    .mat-body th  { background: #111827; }
    .mat-body code { background: #111827; }
    .mat-notes-callout { background: #111827; border-color: #78350F; color: #FCD34D; }
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_display_title(raw: str, max_len: int = 68) -> str:
    """
    Return a clean, single-line display title from raw text that may contain
    full markdown document content (headers, dividers, long paragraphs).
    """
    if not raw:
        return "Untitled"
    for line in raw.split("\n"):
        clean = re.sub(r"^[#\->\s]+", "", line).strip()
        if clean:
            return (clean[:max_len - 1] + "…") if len(clean) > max_len else clean
    return raw[:max_len]


def _is_document_content(raw: str) -> bool:
    """True when the title field looks like a full document, not a short label."""
    return len(raw) > 120 or "\n" in raw or bool(re.search(r"(#{1,3} |---|^\*\*)", raw, re.MULTILINE))


def _render_mat_card(mat: dict, status: str, user_id: int,
                     course_id: int, admin: bool) -> None:
    mat_id     = mat["id"]
    m_type     = mat.get("material_type", "Other")
    type_icon, accent = TYPE_META.get(m_type, ("📦", "#9CA3AF"))
    icon_bg    = accent + "18"

    stat_icon  = STATUS_ICONS.get(status, "⬜")
    stat_color = STATUS_COLORS.get(status, "#6B7280")
    stat_bg    = stat_color + "18"

    raw_title    = (mat.get("title") or "Untitled").strip()
    display_title = _extract_display_title(raw_title)
    is_doc        = _is_document_content(raw_title)

    est      = mat.get("estimated_minutes") or 0
    added    = (mat.get("created_at") or "")[:10]
    est_part = f"<span>⏱&thinsp;{est}&thinsp;min</span>" if est else ""
    add_part = f"<span>📅&thinsp;{added}</span>" if added else ""

    # ── Card header (always visible, never contains document text) ────────────
    st.markdown(f"""
<div class="mat-card">
  <div class="mat-card-header">
    <div class="mat-accent-bar" style="background:{accent}"></div>
    <div class="mat-icon" style="background:{icon_bg}">{type_icon}</div>
    <div class="mat-title-block">
      <div class="mat-title" title="{display_title}">{display_title}</div>
      <div class="mat-subtitle">{est_part}{add_part}<span style="color:{accent};font-weight:600">{m_type}</span></div>
    </div>
    <span class="mat-status-pill" style="color:{stat_color};background:{stat_bg}">{stat_icon}&thinsp;{status}</span>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Expandable body ───────────────────────────────────────────────────────
    with st.expander("View content & mark progress", expanded=False):

        # Choose what to show as body text
        content_text = (mat.get("content_text") or "").strip()
        body = content_text or (raw_title if is_doc else "")

        if body:
            st.markdown(body)      # renders full markdown: headers, tables, lists

        # URL / link
        url = (mat.get("external_url") or "").strip()
        if url:
            if m_type == "Video":
                link_label = "🎬 Open video"
                if "youtube.com/watch?v=" in url or "youtu.be/" in url:
                    try:
                        vid_id = (
                            url.split("youtu.be/")[-1].split("?")[0]
                            if "youtu.be/" in url
                            else url.split("v=")[-1].split("&")[0]
                        )
                        st.markdown(
                            f'<iframe width="100%" height="315" '
                            f'src="https://www.youtube.com/embed/{vid_id}" '
                            f'frameborder="0" allowfullscreen></iframe>',
                            unsafe_allow_html=True,
                        )
                    except Exception:
                        pass
            elif m_type == "PDF/Document Link":
                link_label = "📄 Open document"
            else:
                link_label = "🔗 Open link"

            st.markdown(
                f'<a class="mat-link-btn" href="{url}" target="_blank">{link_label} ↗</a>',
                unsafe_allow_html=True,
            )

        if mat.get("notes"):
            st.markdown(
                f'<div class="mat-notes-callout">📝&thinsp;<strong>Note:</strong>&ensp;{mat["notes"]}</div>',
                unsafe_allow_html=True,
            )

        if admin:
            st.caption(f"Display order: {mat.get('display_order', 0)}")

        st.markdown("---")
        st.markdown("**Your progress:**")
        prog_cols = st.columns(len(PROGRESS_OPTIONS))
        for i, opt in enumerate(PROGRESS_OPTIONS):
            s_icon   = STATUS_ICONS[opt]
            is_active = status == opt
            if prog_cols[i].button(
                f"{s_icon} {opt}",
                key=f"prog_{mat_id}_{opt}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
            ):
                set_material_progress(user_id, mat_id, course_id, opt)
                st.rerun()

        if admin:
            st.markdown("---")
            a1, a2, a3 = st.columns(3)
            with a1:
                if st.button("✏️ Edit", key=f"edit_{mat_id}", use_container_width=True):
                    st.session_state[f"editing_{mat_id}"] = True
                    st.rerun()
            with a2:
                if st.button("🗃 Archive", key=f"arc_{mat_id}", use_container_width=True):
                    archive_material(mat_id)
                    st.success(f'"{display_title}" archived.')
                    st.rerun()
            with a3:
                if st.button("🗑 Delete", key=f"del_{mat_id}", use_container_width=True):
                    delete_material(mat_id)
                    st.rerun()

            if st.session_state.get(f"editing_{mat_id}"):
                with st.form(f"edit_mat_{mat_id}"):
                    st.markdown("**Edit material**")
                    e_title = st.text_input("Title", value=mat["title"])
                    e_type  = st.selectbox(
                        "Type", MATERIAL_TYPES,
                        index=(MATERIAL_TYPES.index(mat["material_type"])
                               if mat["material_type"] in MATERIAL_TYPES else 0),
                    )
                    e_content = st.text_area(
                        "Content (text / notes)",
                        value=mat.get("content_text", ""),
                        height=180,
                    )
                    e_url   = st.text_input("External URL", value=mat.get("external_url", ""))
                    e_notes = st.text_input("Notes / tags",  value=mat.get("notes", ""))
                    ec1, ec2 = st.columns(2)
                    e_order = ec1.number_input(
                        "Display order", min_value=0, max_value=9999,
                        value=int(mat.get("display_order") or 0), step=1,
                    )
                    e_mins = ec2.number_input(
                        "Est. minutes", min_value=0, max_value=600,
                        value=int(mat.get("estimated_minutes") or 0), step=5,
                    )
                    bc1, bc2 = st.columns(2)
                    save_e   = bc1.form_submit_button("💾 Save", use_container_width=True)
                    cancel_e = bc2.form_submit_button("Cancel", use_container_width=True)

                if save_e:
                    update_material(
                        mat_id, e_title, e_type,
                        e_content, e_url, e_notes,
                        display_order=e_order, estimated_minutes=e_mins,
                    )
                    st.session_state.pop(f"editing_{mat_id}", None)
                    st.rerun()
                if cancel_e:
                    st.session_state.pop(f"editing_{mat_id}", None)
                    st.rerun()


# ── Build tabs ────────────────────────────────────────────────────────────────
if admin:
    tab_view, tab_add = st.tabs(["📋 Materials", "➕ Add Material"])
else:
    (tab_view,) = st.tabs(["📋 Materials"])
    tab_add = None


# ── Tab 1: View materials ─────────────────────────────────────────────────────
with tab_view:
    materials = get_materials(course_id)
    progress  = get_material_progress(user_id, course_id)

    if not materials:
        msg = "No materials have been added to this course yet."
        if admin:
            msg += " Use the **Add Material** tab above to get started."
        st.info(msg)
    else:
        m_total     = len(materials)
        m_completed = sum(1 for m in materials if progress.get(m["id"]) == "Completed")
        m_pct = round(m_completed / m_total * 100) if m_total else 0
        st.progress(
            m_pct / 100,
            text=f"Your progress: {m_completed}/{m_total} completed ({m_pct}%)",
        )
        st.caption("📌 Materials are shared. Your completion status is private to you.")
        st.markdown("")

        type_filter = st.selectbox(
            "Filter by type:", ["All"] + MATERIAL_TYPES, key="mat_filter"
        )
        filtered = materials if type_filter == "All" else [
            m for m in materials if m["material_type"] == type_filter
        ]

        if not filtered:
            st.info(f"No {type_filter} materials in this course yet.")
        else:
            st.markdown("")
            for mat in filtered:
                status = progress.get(mat["id"], "Not Started")
                _render_mat_card(mat, status, user_id, course_id, admin)


# ── Tab 2: Add material (admin only) ─────────────────────────────────────────
if tab_add is not None:
    with tab_add:
        st.markdown("### Add a Shared Material")
        st.info(
            f"Materials you add are **shared** — all users enrolled in "
            f"**{course_title}** will see them immediately.  "
            "Duplicate titles (same course, same title) are not allowed."
        )

        with st.form("add_material_form", clear_on_submit=True):
            a_title = st.text_input(
                "Title *",
                placeholder="e.g., Chapter 1 Reading, Intro Video, Practice Problem Set",
            )
            a_type = st.selectbox("Material Type *", MATERIAL_TYPES)

            st.markdown("---")
            st.markdown("**Content**")
            st.caption(
                "For Reading / Notes: paste text below (Markdown supported).  "
                "For Video / Link / PDF: provide the URL.  You can use both."
            )

            a_content = st.text_area(
                "Content text",
                height=180,
                placeholder=(
                    "Paste reading text, lecture notes, summaries…\n"
                    "Markdown is supported: ## Headings, **bold**, tables, lists."
                ),
            )
            a_url = st.text_input(
                "External URL",
                placeholder="https://www.youtube.com/watch?v=...  or  https://example.com/file.pdf",
            )

            st.markdown("---")
            a_notes = st.text_input(
                "Notes / tags (optional)",
                placeholder="e.g., 'Required reading', 'Chapter 3', 'Week 2'",
            )

            col1, col2 = st.columns(2)
            with col1:
                a_order = st.number_input(
                    "Display order", min_value=0, max_value=9999, value=0, step=1,
                    help="Materials are sorted by this number (low → high).",
                )
            with col2:
                a_mins = st.number_input(
                    "Estimated time (minutes)", min_value=0, max_value=600, value=0, step=5,
                )

            a_active = st.radio(
                "Status",
                ["Active (visible to learners)", "Inactive (hidden for now)"],
                horizontal=True,
            )

            add_btn = st.form_submit_button(
                "➕ Add Material", use_container_width=True, type="primary"
            )

        if add_btn:
            if not a_title.strip():
                st.error("⚠️ Title is required.")
            elif not a_content.strip() and not a_url.strip():
                st.error("⚠️ Please provide either content text or an external URL.")
            else:
                is_active_val = 1 if "Active" in a_active else 0
                mid, err = create_material(
                    course_id=course_id,
                    title=a_title.strip(),
                    material_type=a_type,
                    content_text=a_content.strip(),
                    external_url=a_url.strip(),
                    notes=a_notes.strip(),
                    created_by_user_id=user_id,
                    display_order=int(a_order),
                    estimated_minutes=int(a_mins),
                    is_active=is_active_val,
                )
                if err:
                    st.error(f"⚠️ {err}")
                else:
                    status_word = "added" if is_active_val else "saved as draft"
                    st.success(
                        f"✅ **{a_title.strip()}** {status_word} successfully! "
                        + ("Visible to all enrolled users now."
                           if is_active_val
                           else "Switch it to Active when ready.")
                    )
                    st.rerun()

        st.divider()
        with st.expander("💡 Tips for each material type", expanded=False):
            st.markdown("""
**📖 Reading** — paste full text, chapter summaries, or study notes.  Markdown renders as formatted content.

**🎬 Video** — paste a YouTube or Vimeo URL. YouTube links auto-embed.

**🔗 Link** — any external URL (article, interactive tool, website).

**📝 Notes** — structured key points, formulas, or mnemonics.

**📄 PDF/Document Link** — paste a direct link to a PDF (Google Drive, Dropbox, etc.).

**Display order** — controls the sequence. Lower numbers appear first.

**Duplicate titles** — each material in a course must have a unique title.
            """)
