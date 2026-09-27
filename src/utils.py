"""
utils.py — Shared UI helpers, course selector, and small utilities.
"""

from __future__ import annotations
from html import escape
import json
import re
import streamlit as st
import streamlit.components.v1 as _components
from src.import_math_text import normalize_math_row, readable_question_text

DIFFICULTY_LABELS = {
    1: "Intuition & Estimation",
    2: "Beginner Calculations",
    3: "Intermediate Calculations",
    4: "Advanced Calculations",
    5: "Stretch Problems",
}
ANSWER_LETTERS    = ["A", "B", "C", "D", "E"]

SECTION_TYPES  = ["Logical Reasoning", "Reading Comprehension"]
QUESTION_TYPES = [
    "Strengthen", "Weaken", "Flaw", "Assumption", "Inference",
    "Main Point", "Must Be True", "Parallel Reasoning",
    "Principle", "Role of Statement", "Method of Reasoning",
    "Point of Disagreement", "Evaluate", "Explain",
]


_MODULE_NUMBER_RE = re.compile(r"\b(module\s*#?\s*)(\d+)\b", re.IGNORECASE)


def format_module_label(value: str, minimum_width: int = 2) -> str:
    """Zero-pad module numbers for stable, scan-friendly display labels."""
    label = str(value or "")

    def pad_number(match: re.Match) -> str:
        number = match.group(2)
        return f"{match.group(1)}{number.zfill(max(minimum_width, len(number)))}"

    return _MODULE_NUMBER_RE.sub(pad_number, label)


def module_sort_key(value: str) -> list[tuple[int, object]]:
    """Sort numbered module labels naturally while keeping text deterministic."""
    parts = re.split(r"(\d+)", str(value or "").casefold())
    return [
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
        if part
    ]


def question_reference_label(q: dict, *, include_prefix: bool = True) -> str:
    """Return a searchable question-bank reference for display."""
    master_id = q.get("master_question_id")
    if master_id not in (None, "") and q.get("question_id") not in (None, ""):
        bank_id = q.get("question_id")
    else:
        bank_id = q.get("id") or q.get("bank_question_id") or q.get("question_id")

    if master_id is None and q.get("id") is not None:
        master_id = q.get("question_id")

    parts = []
    if bank_id not in (None, ""):
        parts.append(f"Bank #{bank_id}")
    if master_id not in (None, ""):
        parts.append(f"Master {master_id}")

    label = " / ".join(parts)
    if not label:
        return ""
    return f"Question {label}" if include_prefix else label


def question_course_title(q: dict) -> str:
    """Return the course title, including for questions restored from older drafts."""
    title = str(q.get("course_title") or "").strip()
    if title or q.get("course_id") in (None, ""):
        return title

    from src.database import get_course

    course = get_course(q.get("course_id"))
    return str((course or {}).get("title") or "").strip()


# --- Sidebar page labels ----------------------------------------------------
def _sidebar_page_label_js(review_badge_count: int = 0, ccrn_badge_count: int = 0) -> str:
    template = """
<script>
(function () {
    'use strict';

    var reviewBadgeCount = __REVIEW_BADGE_COUNT__;
    var ccrnBadgeCount = __CCRN_BADGE_COUNT__;
    var P = window.parent;
    if (!P || !P.document) { return; }
    var doc = P.document;

    function relabelMainPage() {
        var nav = doc.querySelector('[data-testid="stSidebarNav"], [data-testid="stSidebarNavItems"]');
        if (!nav) { return; }

        var links = Array.prototype.slice.call(nav.querySelectorAll('a'));
        links.forEach(function (link) {
            var text = (link.textContent || '').trim();
            var normalizedText = text.toLowerCase();
            var href = link.getAttribute('href') || '';
            var isMainAppLink = normalizedText === 'app'
                || href === './'
                || href === '/'
                || href.endsWith('/?');
            if (!isMainAppLink) { return; }

            link.setAttribute('aria-label', 'Sign In');
            link.setAttribute('title', 'Sign In');

            var labelNode = link.querySelector('span, p, div');
            if (labelNode && labelNode.textContent !== 'Sign In') {
                labelNode.textContent = 'Sign In';
            } else if (!labelNode && link.textContent !== 'Sign In') {
                link.textContent = 'Sign In';
            }
        });
    }

    function decorateReviewMistakesLink() {
        var nav = doc.querySelector('[data-testid="stSidebarNav"], [data-testid="stSidebarNavItems"]');
        if (!nav) { return; }

        var links = Array.prototype.slice.call(nav.querySelectorAll('a'));
        links.forEach(function (link) {
            var href = link.getAttribute('href') || '';
            var rawText = (link.textContent || '').replace(/\\s+/g, ' ').trim();
            var isReviewLink = rawText.indexOf('Review Mistakes') !== -1
                || href.indexOf('Review_Mistakes') !== -1;
            var isMaterialsLink = href.indexOf('Course_Materials') !== -1;
            var isCcrnLink = href.indexOf('Question_Bank_Manager') !== -1 || isMaterialsLink;
            if (!isReviewLink && !isCcrnLink) { return; }
            var count = isCcrnLink ? ccrnBadgeCount : reviewBadgeCount;
            var name = isMaterialsLink ? 'Course Materials' : (isCcrnLink ? 'Question Bank Manager' : 'Review Mistakes');

            link.classList.add('sf-review-nav-link');
            var existingBadge = link.querySelector('.sf-review-nav-badge');
            if (link.getAttribute('data-sf-review-count') === String(count)
                && ((count === 0 && !existingBadge) || (count > 0 && existingBadge
                    && existingBadge.parentNode === link
                    && existingBadge.classList.contains('sf-ccrn-nav-badge') === isCcrnLink))) { return; }
            if (count > 0) {
                if (!existingBadge) {
                    existingBadge = doc.createElement('span');
                    existingBadge.className = 'sf-review-nav-badge';
                }
                if (existingBadge.parentNode !== link) { link.appendChild(existingBadge); }
                existingBadge.classList.toggle('sf-ccrn-nav-badge', isCcrnLink);
                existingBadge.textContent = isCcrnLink ? String(count) : (count > 99 ? '99+' : String(count));
                link.setAttribute('aria-label', name + ', ' + count + (isCcrnLink ? ' pending import' : ' outstanding'));
                link.setAttribute('title', count + (isCcrnLink ? ' questions pending import' : ' outstanding mistakes to review'));
            } else if (existingBadge) {
                existingBadge.remove();
                link.setAttribute('aria-label', name);
                link.setAttribute('title', name);
            }
            link.setAttribute('data-sf-review-count', String(count));
        });
    }

    relabelMainPage();
    decorateReviewMistakesLink();
    setTimeout(relabelMainPage, 100);
    setTimeout(decorateReviewMistakesLink, 100);
    setTimeout(relabelMainPage, 500);
    setTimeout(decorateReviewMistakesLink, 500);

    if (P._sfPageLabelObs) { P._sfPageLabelObs.disconnect(); }
    P._sfPageLabelObs = new MutationObserver(function () {
        relabelMainPage();
        decorateReviewMistakesLink();
    });
    P._sfPageLabelObs.observe(doc.body, { childList: true, subtree: true });
})()
</script>
"""
    return template.replace("__REVIEW_BADGE_COUNT__", str(int(review_badge_count))).replace("__CCRN_BADGE_COUNT__", str(int(ccrn_badge_count)))

_SIDEBAR_PAGE_LABEL_CSS = """
<style>
/* Keep existing routes accessible through the Course Materials workspace. */
[data-testid="stSidebarNav"] li:has(a[href$="/a_Flashcards"]),
[data-testid="stSidebarNav"] li:has(a[href$="/b_Notebook"]),
[data-testid="stSidebarNav"] li:has(a[href$="/c_Audio_Study"]),
[data-testid="stSidebarNav"] li:has(a[href$="/Question_Bank_Manager"]) {
    display: none !important;
}
[data-testid="stSidebarNav"]:has(a[aria-current="page"]:is(
    [href$="/a_Flashcards"], [href$="/b_Notebook"], [href$="/c_Audio_Study"], [href$="/Question_Bank_Manager"]
)) a[href$="/Course_Materials"] {
    background: #334155 !important;
    color: #ffffff !important;
    font-weight: 700 !important;
}
[data-testid="stSidebarNav"] a[href="./"] span,
[data-testid="stSidebarNavItems"] a[href="./"] span {
    font-size: 0 !important;
}

[data-testid="stSidebarNav"] a[href="./"] span::after,
[data-testid="stSidebarNavItems"] a[href="./"] span::after {
    content: "Sign In";
    font-size: 14px;
}

[data-testid="stSidebarNav"] a.sf-review-nav-link,
[data-testid="stSidebarNavItems"] a.sf-review-nav-link {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 0.5rem !important;
}

.sf-review-nav-badge {
    flex: 0 0 auto !important;
    align-items: center !important;
    background: #dc2626 !important;
    border-radius: 999px !important;
    color: #ffffff !important;
    display: inline-flex !important;
    font-size: 0.7rem !important;
    font-weight: 800 !important;
    justify-content: center !important;
    line-height: 1 !important;
    margin-left: auto !important;
    min-width: 1.35rem !important;
    padding: 0.22rem 0.42rem !important;
}
.sf-review-nav-badge.sf-ccrn-nav-badge {
    background: #92400e !important;
    color: #ffffff !important;
    font-size: 0.72rem !important;
    font-weight: 900 !important;
    text-shadow: 0 1px 1px rgba(0, 0, 0, 0.28) !important;
}
</style>
"""


def _review_mistakes_outstanding_count(user_id: int | None) -> int:
    if not user_id:
        return 0

    try:
        from src.database import (
            get_all_curriculums,
            get_curriculum_courses,
            get_outstanding_mistake_count,
        )

        curriculums = get_all_curriculums()
        if not curriculums:
            return 0

        curriculum_courses = {c["id"]: get_curriculum_courses(c["id"]) for c in curriculums}
        active_course_id = st.session_state.get("active_course_id")
        selected_curriculum_id = None

        for curr in curriculums:
            if any(c["id"] == active_course_id for c in curriculum_courses.get(curr["id"], [])):
                selected_curriculum_id = curr["id"]
                break

        if selected_curriculum_id is None:
            selected_curriculum_id = curriculums[0]["id"]

        course_ids = [
            c["id"] for c in curriculum_courses.get(selected_curriculum_id, [])
        ]
        if course_ids:
            return get_outstanding_mistake_count(user_id, course_ids=course_ids)
        if active_course_id:
            return get_outstanding_mistake_count(user_id, course_id=active_course_id)
        return 0
    except Exception:
        return 0


def inject_sidebar_page_labels(review_badge_count: int = 0, ccrn_badge_count: int = 0) -> None:
    """Rename Streamlit's default app.py sidebar label to the user-facing page name."""
    st.markdown(_SIDEBAR_PAGE_LABEL_CSS, unsafe_allow_html=True)
    _components.html(_sidebar_page_label_js(review_badge_count, ccrn_badge_count), height=0, scrolling=False)


def _ccrn_pending_count() -> int:
    from src.database import get_connection
    from src.ccrn_import_queue import pending_question_counts
    conn = get_connection()
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ccrn_import_queue'").fetchone():
            return 0
        drafts = [dict(row) for row in conn.execute("SELECT * FROM ccrn_import_queue WHERE imported_batch_id IS NULL")]
        return sum(pending_question_counts(drafts).values())
    finally:
        conn.close()


@st.fragment(run_every="10s")
def _live_sidebar_badges(user_id):
    inject_sidebar_page_labels(_review_mistakes_outstanding_count(user_id), _ccrn_pending_count() if user_id else 0)


# ── Native sidebar controls and legacy cleanup ──────────────────────────────
# Use Streamlit's native sidebar state on desktop and mobile. The former
# body-class toggle could not reopen a sidebar hidden by Streamlit itself.
_SIDEBAR_CSS = """
<style>
@media (max-width: 768px) {
    section[data-testid="stSidebar"][aria-expanded="true"] {
        min-width: min(280px, 85vw) !important;
        max-width: min(320px, 85vw) !important;
        width: 85vw !important;
        transform: none !important;
        visibility: visible !important;
    }
}
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stExpandSidebarButton"] button {
    min-width: 44px;
    min-height: 44px;
}
</style>
"""

# Clean up controls left in an existing browser tab by the previous version.
_SIDEBAR_JS = """
<script>
(function () {
    var P = window.parent, doc = P.document;
    if (P._sfSbObs) { P._sfSbObs.disconnect(); P._sfSbObs = null; }
    if (P._sfSbTimer) { P.clearInterval(P._sfSbTimer); P._sfSbTimer = null; }
    doc.body.classList.remove('sf-sb-collapsed');
    ['sf-sb-btn', 'sf-sb-overlay'].forEach(function(id) {
        var el = doc.getElementById(id); if (el) el.remove();
    });
})();
</script>
"""


def _inject_sidebar_toggle() -> None:
    st.markdown(_SIDEBAR_CSS, unsafe_allow_html=True)
    _components.html(_SIDEBAR_JS, height=0, scrolling=False)


# ── Floating Feedback Button CSS ─────────────────────────────────────────────
_FEEDBACK_BTN_CSS = """
<style>
/* StudyForge — Floating Feedback FAB
   Uses a hidden marker + adjacent-sibling CSS to grab the st.button
   that follows it and pin it to the viewport corner. */

#sf-feedback-fab-marker { display: none; }

#sf-feedback-fab-container {
    position: fixed !important;
    bottom: 18px !important;
    left: 18px !important;
    z-index: 99999 !important;
    width: fit-content !important;
    height: auto !important;
    overflow: visible !important;
}

#sf-feedback-fab-container button {
    background: linear-gradient(135deg, #1D4ED8 0%, #0F766E 100%) !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.42) !important;
    border-radius: 50px !important;
    padding: 10px 20px !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    box-shadow: 0 6px 20px rgba(29,78,216,0.42), 0 2px 8px rgba(0,0,0,0.18) !important;
    cursor: pointer !important;
    white-space: nowrap !important;
    letter-spacing: 0 !important;
    width: auto !important;
    transition: transform 0.18s ease, box-shadow 0.18s ease !important;
}

#sf-feedback-fab-container button:hover {
    background: linear-gradient(135deg, #2563EB 0%, #14B8A6 100%) !important;
    box-shadow: 0 8px 26px rgba(29,78,216,0.52), 0 4px 12px rgba(0,0,0,0.20) !important;
    transform: translateY(-2px) !important;
}

#sf-feedback-fab-container button:active {
    transform: translateY(0) scale(0.98) !important;
    box-shadow: 0 3px 12px rgba(29,78,216,0.45), 0 1px 5px rgba(0,0,0,0.18) !important;
}

/* Pin the element-container that wraps the FAB button */
[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] {
    position: fixed !important;
    bottom: 18px !important;
    left: 18px !important;
    z-index: 99999 !important;
    width: fit-content !important;
    height: auto !important;
    overflow: visible !important;
}

/* Style the button itself */
[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] button {
    background: linear-gradient(135deg, #1D4ED8 0%, #0F766E 100%) !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.42) !important;
    border-radius: 50px !important;
    padding: 10px 20px !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    box-shadow: 0 6px 20px rgba(29,78,216,0.42), 0 2px 8px rgba(0,0,0,0.18) !important;
    cursor: pointer !important;
    white-space: nowrap !important;
    letter-spacing: 0 !important;
    width: auto !important;
    transition: transform 0.18s ease, box-shadow 0.18s ease !important;
}
[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] button:hover {
    background: linear-gradient(135deg, #2563EB 0%, #14B8A6 100%) !important;
    box-shadow: 0 8px 26px rgba(29,78,216,0.52), 0 4px 12px rgba(0,0,0,0.20) !important;
    transform: translateY(-2px) !important;
}
[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] button:active {
    transform: translateY(0) scale(0.98) !important;
    box-shadow: 0 3px 12px rgba(29,78,216,0.45), 0 1px 5px rgba(0,0,0,0.18) !important;
}

/* Hide the sidebar auto-generated Feedback entry */
#sf-feedback-fab {
    position: fixed !important;
    bottom: 18px !important;
    left: 18px !important;
    z-index: 9999999 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 7px !important;
    min-height: 42px !important;
    padding: 10px 20px !important;
    border: 1px solid rgba(255,255,255,0.42) !important;
    border-radius: 999px !important;
    background: linear-gradient(135deg, #1D4ED8 0%, #0F766E 100%) !important;
    color: #ffffff !important;
    box-shadow: 0 6px 20px rgba(29,78,216,0.42), 0 2px 8px rgba(0,0,0,0.18) !important;
    cursor: pointer !important;
    font: 700 14px/1.2 sans-serif !important;
    letter-spacing: 0 !important;
    white-space: nowrap !important;
    transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease !important;
}

#sf-feedback-fab:hover {
    background: linear-gradient(135deg, #2563EB 0%, #14B8A6 100%) !important;
    box-shadow: 0 8px 26px rgba(29,78,216,0.52), 0 4px 12px rgba(0,0,0,0.20) !important;
    transform: translateY(-2px) !important;
}

#sf-feedback-fab:active {
    transform: translateY(0) scale(0.98) !important;
    box-shadow: 0 3px 12px rgba(29,78,216,0.45), 0 1px 5px rgba(0,0,0,0.18) !important;
}

#sf-feedback-fab:focus-visible {
    outline: 3px solid rgba(255,176,0,0.38) !important;
    outline-offset: 3px !important;
}

[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] {
    position: absolute !important;
    left: -9999px !important;
    bottom: auto !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
}

[data-testid="stSidebarNavItems"] a[href*="feedback"],
[data-testid="stSidebarNavItems"] a[href*="Feedback"],
[data-testid="stSidebarNavItems"] a[href*="11_Feedback"] {
    display: none !important;
}
</style>
"""

_FEEDBACK_BTN_JS = """
<script>
(function () {
    'use strict';

    var P = window.parent;
    if (!P || !P.document) { return; }
    var doc = P.document;
    var MARKER = 'sf-feedback-fab-marker';
    var CONTAINER = 'sf-feedback-fab-container';

    function isAfterMarker(marker, node) {
        return !!(marker.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING);
    }

    function findFeedbackButton() {
        var marker = doc.getElementById(MARKER);
        if (!marker) { return null; }
        var buttons = Array.prototype.slice.call(doc.querySelectorAll('button'));
        for (var i = 0; i < buttons.length; i += 1) {
            var btn = buttons[i];
            if (isAfterMarker(marker, btn) && /Feedback/i.test(btn.textContent || '')) {
                return btn;
            }
        }
        return null;
    }

    function pinButton() {
        var btn = findFeedbackButton();
        if (!btn) { return; }
        var container = btn.closest('[data-testid="element-container"]') || btn.parentElement;
        if (!container) { return; }
        container.id = CONTAINER;
        btn.setAttribute('aria-label', 'Open feedback');
        btn.title = 'Open feedback';
    }

    pinButton();
    setTimeout(pinButton, 50);
    setTimeout(pinButton, 250);
    setTimeout(pinButton, 1000);

    if (P._sfFeedbackObs) { P._sfFeedbackObs.disconnect(); }
    P._sfFeedbackObs = new MutationObserver(pinButton);
    P._sfFeedbackObs.observe(doc.body, { childList: true, subtree: true });
})();
</script>
"""

_FEEDBACK_BTN_JS = """
<script>
(function () {
    'use strict';

    var P = window.parent;
    if (!P || !P.document) { return; }
    var doc = P.document;
    var BTN_ID = 'sf-feedback-fab';
    var MARKER_ID = 'sf-feedback-fab-marker';

    function findStreamlitFeedbackButton() {
        var marker = doc.getElementById(MARKER_ID);
        if (!marker) { return null; }
        var buttons = Array.prototype.slice.call(doc.querySelectorAll('button'));
        for (var i = 0; i < buttons.length; i += 1) {
            var btn = buttons[i];
            var followsMarker = !!(marker.compareDocumentPosition(btn) & 4);
            if (followsMarker && /Feedback/i.test(btn.textContent || '')) {
                return btn;
            }
        }
        return null;
    }

    function ensureFab() {
        var existing = doc.getElementById(BTN_ID);
        if (existing) { return existing; }

        var fab = doc.createElement('button');
        fab.id = BTN_ID;
        fab.type = 'button';
        fab.innerHTML = '<span aria-hidden="true">&#128172;</span><span>Feedback</span>';
        fab.title = 'Open feedback';
        fab.setAttribute('aria-label', 'Open feedback');
        fab.addEventListener('click', function () {
            var streamlitButton = findStreamlitFeedbackButton();
            if (streamlitButton) { streamlitButton.click(); }
        });
        doc.body.appendChild(fab);
        return fab;
    }

    ensureFab();
    setTimeout(ensureFab, 100);
    setTimeout(ensureFab, 500);

    if (P._sfFeedbackFabObs) { P._sfFeedbackFabObs.disconnect(); }
    P._sfFeedbackFabObs = new MutationObserver(ensureFab);
    P._sfFeedbackFabObs.observe(doc.body, { childList: true, subtree: false });
})();
</script>
"""

def _inject_feedback_button() -> None:
    """Inject the floating Feedback FAB into every authenticated page."""
    st.markdown(_FEEDBACK_BTN_CSS, unsafe_allow_html=True)
    st.markdown('<div id="sf-feedback-fab-marker"></div>', unsafe_allow_html=True)
    if st.button("💬 Feedback", key="sf_feedback_fab"):
        st.switch_page("pages/11_Feedback.py")
    _components.html(_FEEDBACK_BTN_JS, height=0, scrolling=False)


# ── Admin view-mode helpers ───────────────────────────────────────────────────

def get_effective_admin(user_id: int) -> tuple[bool, bool]:
    """
    Return (real_is_admin, effective_is_admin).

    real_is_admin      — True when the DB says the user is an admin.
                         Always use this for security-critical backend actions
                         (deleting courses, force-unenrolling users, etc.).

    effective_is_admin — True when the user is a real admin AND has not chosen
                         to preview the app in User View mode via the sidebar
                         toggle.  Use this for all UI visibility decisions
                         (showing/hiding admin-only tabs, buttons, panels).

    Non-admin users always get (False, False).
    """
    from src.database import is_admin as _db_is_admin
    real_admin = _db_is_admin(user_id)
    if not real_admin:
        return False, False
    # Read the view-mode choice from session state (set by sidebar_nav)
    view_mode = st.session_state.get("admin_view_mode", "Admin View")
    effective = view_mode == "Admin View"
    return real_admin, effective


# ── Page chrome ───────────────────────────────────────────────────────────────
def page_header(title: str, subtitle: str = "") -> None:
    safe_title = escape(title)
    safe_subtitle = escape(subtitle)
    subtitle_html = f'<p class="sf-page-subtitle">{safe_subtitle}</p>' if subtitle else ""
    st.markdown(
        f"""
<section class="sf-page-header">
  <p class="sf-page-eyebrow">StudyForge</p>
  <h1 class="sf-page-title">{safe_title}</h1>
  {subtitle_html}
</section>
""",
        unsafe_allow_html=True,
    )


def sidebar_nav(username: str) -> None:
    from src.ui_theme import inject_modern_theme
    from src.app_status import deployment_caption

    uid = st.session_state.get("user_id")

    inject_modern_theme()
    _live_sidebar_badges(uid)
    # Inject collapsible-sidebar (CSS via markdown, JS via iframe component)
    _inject_sidebar_toggle()
    # Inject responsive layout CSS from admin-managed config
    try:
        from src.responsive_layout import inject_responsive_css
        inject_responsive_css()
    except Exception:
        pass

    with st.sidebar:
        st.markdown(f"**Logged in as:** {username}")

        real_admin = False
        if uid:
            from src.database import is_admin as _db_is_admin
            real_admin = _db_is_admin(uid)
            if real_admin:
                # Show badge that reflects current view mode
                view_mode = st.session_state.get("admin_view_mode", "Admin View")
                if view_mode == "Admin View":
                    st.caption("🔑 Admin")
                else:
                    st.caption("🔑 Admin · 👁 User Preview")

        if st.button("Log Out", use_container_width=True):
            from src.auth import logout
            logout()
            st.rerun()

        # ── Admin View-Mode Toggle (real admins only) ─────────────────────
        if real_admin:
            st.divider()
            st.markdown("**View Mode**")
            st.radio(
                "view_mode_radio",
                options=["Admin View", "User View"],
                index=0 if st.session_state.get("admin_view_mode", "Admin View") == "Admin View" else 1,
                key="admin_view_mode",
                label_visibility="collapsed",
            )
            if st.session_state.get("admin_view_mode") == "User View":
                st.caption(
                    "👁 Previewing as regular user.  "
                    "Admin permissions are not removed."
                )

        st.divider()
        st.caption(deployment_caption())

    # Inject floating feedback FAB
    _inject_feedback_button()
    # Install the collapsible BA II Plus-style calculator on every signed-in page.
    from src.financial_calculator import inject_financial_calculator
    inject_financial_calculator()


# ── Course selector (enrollment-based) ───────────────────────────────────────
def course_selector(user_id: int, label: str = "📚 Active Course", *, main: bool = False) -> int | None:
    """
    Render synchronized sidebar and optional main-screen course pickers.
    Shows only courses the user is enrolled in.
    Returns the selected course_id, or None if user has no active enrollments.
    """
    from src.database import get_enrolled_courses
    enrolled = get_enrolled_courses(user_id)

    if not enrolled:
        with st.sidebar:
            st.warning("Not enrolled in any courses.")
            st.caption("No active courses are available for your account yet.")
        return None

    from src.study_progress import load_progress, status, label as progress_label
    progress = load_progress(user_id)
    options    = {c["id"]: c["title"] for c in enrolled}
    option_ids = list(options.keys())

    stored = st.session_state.get("active_course_id")
    if stored not in options:
        st.session_state["active_course_id"] = option_ids[0]
        stored = option_ids[0]

    def changed(key):
        st.session_state['active_course_id'] = st.session_state[key]

    # Synchronize before rendering either widget, including after page navigation.
    st.session_state['sidebar_course_selector'] = stored
    if main:
        st.session_state['main_course_selector'] = stored

    with st.sidebar:
        st.markdown(f"**{label}**")
        selected_id = st.selectbox(
            "course_select",
            options=option_ids,
            format_func=lambda x: progress_label(options[x], status(progress, [x]), progress["window"]),
            index=option_ids.index(stored),
            key="sidebar_course_selector",
            on_change=changed, args=('sidebar_course_selector',),
            label_visibility="collapsed",
        )
        st.divider()

    if main:
        selected_id = st.selectbox('Course',option_ids,
            format_func=lambda x: options[x],key='main_course_selector',
            on_change=changed,args=('main_course_selector',),
            help='Switch the course shown in Material Library and Audio Study.')

    return selected_id


def require_course(user_id: int, *, main: bool = False) -> int:
    """
    Show course selector and stop execution if user has no enrollments.
    Returns course_id.
    """
    cid = course_selector(user_id, main=main)
    if cid is None:
        st.warning(
            "You are not enrolled in any courses yet. "
            "No active courses are available for your account yet."
        )
        st.stop()
    return cid


# ── Question rendering ────────────────────────────────────────────────────────
def _question_text_card_html(
    question_text: str,
    dom_id: str,
    compact_tools: bool = False,
) -> str:
    question_text = readable_question_text(question_text)
    tools = f"""
      <button type="button" class="sf-question-tool" data-sf-copy-question="{escape(dom_id, quote=True)}">Copy Text</button>
      <button type="button" class="sf-question-tool" data-sf-copy-screenshot="{escape(dom_id, quote=True)}">Copy Screenshot</button>
      <button type="button" class="sf-question-tool" data-sf-play-question="{escape(dom_id, quote=True)}">&#9654; Play</button>
"""
    actions = f'<span class="sf-question-actions">{tools}</span>'
    return f"""
<div class="sf-question-text-card" id="{escape(dom_id, quote=True)}">
  <div class="sf-question-actionbar">
    <span class="sf-question-action-label">Question text</span>
    {actions}
  </div>
  <textarea class="sf-question-copy-block sf-question-copy-area" aria-label="Question text for copying" readonly>{escape(question_text)}</textarea>
</div>
"""


def _inject_question_text_tools(question_text: str, dom_id: str) -> None:
    text_json = json.dumps(readable_question_text(question_text))
    dom_id_json = json.dumps(dom_id)
    script = f"""
<script>
(function() {{
  var P = window.parent;
  var doc = P && P.document;
  if (!P || !doc) return;

  var id = {dom_id_json};
  var text = {text_json};

  function ensureStyles() {{
    if (doc.getElementById('sf-question-text-tools-style-v2')) return;
    var style = doc.createElement('style');
    style.id = 'sf-question-text-tools-style-v2';
    style.textContent = `
      .sf-question-text-card {{
        background:#fff;
        border:1px solid #e5e7eb;
        border-radius:8px;
        box-shadow:0 10px 24px rgba(15,23,42,.06);
        margin:0 0 1rem 0;
        overflow:hidden;
      }}
      .sf-question-actionbar {{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:.75rem;
        padding:.55rem .75rem;
        border-bottom:1px solid #edf2f7;
        background:#f8fafc;
      }}
      .sf-question-action-label {{
        color:#475569;
        font-size:.78rem;
        font-weight:700;
        letter-spacing:.04em;
        text-transform:uppercase;
      }}
      .sf-question-actions {{
        display:flex;
        align-items:center;
        gap:.4rem;
        flex-shrink:0;
      }}
      .sf-question-tool {{
        border:1px solid #cbd5e1;
        border-radius:7px;
        background:#fff;
        color:#0f172a;
        cursor:pointer;
        font-size:.84rem;
        font-weight:650;
        line-height:1;
        min-height:32px;
        padding:.42rem .62rem;
        white-space:nowrap;
      }}
      .sf-question-tool:hover {{ background:#f1f5f9; }}
      .sf-question-tool:active {{ transform:scale(.97); }}
      .sf-question-tool.sf-question-tool-ok {{
        background:#dcfce7;
        border-color:#86efac;
        color:#166534;
      }}
      .sf-question-copy-block {{
        border:0;
        display:block;
        margin:0;
        min-height:3.2rem;
        outline:none;
        padding:.9rem 1rem;
        resize:none;
        white-space:pre-wrap;
        width:100%;
        word-break:normal;
        overflow-wrap:anywhere;
        color:#0f172a;
        font:600 1.2rem/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
        background:#fff;
      }}
      [class*="st-key-q_radio_"] [role="radiogroup"] {{ gap:14px; }}
      [class*="st-key-q_radio_"] label[data-baseweb="radio"] {{
        width:100%;
        box-sizing:border-box;
        min-height:68px;
        margin:0;
        padding:16px 20px;
        border:1px solid #cbd5e1;
        border-radius:10px;
        background:#fff;
        align-items:center;
        cursor:pointer;
      }}
      [class*="st-key-q_radio_"] label[data-baseweb="radio"]:hover {{
        background:#eff6ff;
        border-color:#60a5fa;
      }}
      [class*="st-key-q_radio_"] label[data-baseweb="radio"]:focus-within {{
        outline:3px solid #2563eb;
        outline-offset:2px;
      }}
      [class*="st-key-q_radio_"] label[data-baseweb="radio"]:has(input:checked) {{
        background:#eff6ff;
        border-color:#2563eb;
      }}
      [class*="st-key-q_radio_"] label p,
      [class*="st-key-sf_answer_review_"] p {{
        font-size:1.2rem !important;
        line-height:1.65 !important;
      }}
      [class*="st-key-sf_answer_review_"] {{
        min-height:68px;
        padding:12px 20px;
        border:1px solid #dbe3ef;
        border-radius:10px;
        background:#fff;
      }}
      .sf-question-copy-block:focus {{ box-shadow:inset 0 0 0 2px rgba(37,99,235,.18); }}
      @media (max-width: 640px) {{
        .sf-question-actionbar {{ align-items:flex-start; flex-direction:column; }}
        .sf-question-actions {{ width:100%; }}
        .sf-question-tool {{ flex:1; }}
      }}
    `;
    (doc.head || doc.documentElement).appendChild(style);
  }}

  function flash(button, label) {{
    var original = button.getAttribute('data-sf-original-label') || button.textContent;
    button.setAttribute('data-sf-original-label', original);
    button.textContent = label;
    button.classList.add('sf-question-tool-ok');
    setTimeout(function() {{
      button.textContent = original;
      button.classList.remove('sf-question-tool-ok');
    }}, 1100);
  }}

  function fallbackCopy(value) {{
    var area = doc.createElement('textarea');
    area.value = value;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.left = '-9999px';
    doc.body.appendChild(area);
    area.select();
    try {{ doc.execCommand('copy'); }} catch (e) {{}}
    area.remove();
  }}

  function currentCard() {{
    var cards = doc.querySelectorAll('.sf-question-text-card');
    var fallback = null;
    for (var i = cards.length - 1; i >= 0; i -= 1) {{
      if (cards[i].id !== id) continue;
      fallback = fallback || cards[i];
      if (cards[i].getClientRects().length && cards[i].offsetParent !== null) {{
        return cards[i];
      }}
    }}
    return fallback;
  }}

  function selectQuestionText(button) {{
    var card = (button && button.closest('.sf-question-text-card')) || currentCard();
    var area = card && card.querySelector('.sf-question-copy-area');
    if (area) {{
      area.focus({{ preventScroll: true }});
      area.select();
      return;
    }}
    var code = card && card.querySelector('.sf-question-copy-block code');
    var selection = P.getSelection ? P.getSelection() : doc.getSelection();
    if (!code || !selection || !doc.createRange) return;
    var range = doc.createRange();
    range.selectNodeContents(code);
    selection.removeAllRanges();
    selection.addRange(range);
  }}

  function copyText(button) {{
    selectQuestionText(button);
    var clipboard = (window.navigator && window.navigator.clipboard)
      || (P.navigator && P.navigator.clipboard);
    if (clipboard && clipboard.writeText) {{
      clipboard.writeText(text).then(function() {{
        flash(button, 'Copied');
      }}).catch(function() {{
        fallbackCopy(text);
        flash(button, 'Copied');
      }});
    }} else {{
      fallbackCopy(text);
      flash(button, 'Copied');
    }}
  }}

  function roundedRect(ctx, x, y, width, height, radius) {{
    var r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }}

  function wrapCanvasText(ctx, value, maxWidth) {{
    var lines = [];
    String(value || '').split(/\\r?\\n/).forEach(function(paragraph) {{
      if (!paragraph) {{ lines.push(''); return; }}
      var words = paragraph.split(/\\s+/);
      var line = '';
      words.forEach(function(word) {{
        var candidate = line ? line + ' ' + word : word;
        if (line && ctx.measureText(candidate).width > maxWidth) {{
          lines.push(line);
          line = word;
        }} else {{
          line = candidate;
        }}
      }});
      lines.push(line);
    }});
    return lines.length ? lines : [''];
  }}

  function drawScreenshotButton(ctx, label, right, top) {{
    ctx.font = '650 13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
    var width = Math.ceil(ctx.measureText(label).width) + 20;
    var left = right - width;
    roundedRect(ctx, left, top, width, 32, 7);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = '#0f172a';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, left + width / 2, top + 16);
    return left - 6;
  }}

  function makeQuestionScreenshot(card) {{
    var rect = card.getBoundingClientRect();
    var cardWidth = Math.max(320, Math.round(rect.width || 900));
    var outerPad = 14;
    var bodyPadX = 16;
    var mobile = cardWidth <= 640;
    var headerHeight = mobile ? 86 : 56;
    var lineHeight = 23;
    var measuring = doc.createElement('canvas').getContext('2d');
    measuring.font = '600 16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
    var lines = wrapCanvasText(measuring, text, cardWidth - bodyPadX * 2);
    var bodyHeight = Math.max(76, lines.length * lineHeight + 34);
    var cardHeight = headerHeight + bodyHeight;
    var scale = Math.min(2, Math.max(1, P.devicePixelRatio || 1));
    var canvas = doc.createElement('canvas');
    canvas.width = Math.ceil((cardWidth + outerPad * 2) * scale);
    canvas.height = Math.ceil((cardHeight + outerPad * 2) * scale);
    var ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);

    ctx.fillStyle = '#f1f5f9';
    ctx.fillRect(0, 0, cardWidth + outerPad * 2, cardHeight + outerPad * 2);
    ctx.save();
    ctx.shadowColor = 'rgba(15,23,42,.08)';
    ctx.shadowBlur = 12;
    ctx.shadowOffsetY = 5;
    roundedRect(ctx, outerPad, outerPad, cardWidth, cardHeight, 8);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.restore();

    ctx.save();
    roundedRect(ctx, outerPad, outerPad, cardWidth, cardHeight, 8);
    ctx.clip();
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(outerPad, outerPad, cardWidth, headerHeight);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(outerPad, outerPad + headerHeight, cardWidth, bodyHeight);
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(outerPad, outerPad + headerHeight + .5);
    ctx.lineTo(outerPad + cardWidth, outerPad + headerHeight + .5);
    ctx.stroke();
    ctx.restore();

    roundedRect(ctx, outerPad + .5, outerPad + .5, cardWidth - 1, cardHeight - 1, 8);
    ctx.strokeStyle = '#e5e7eb';
    ctx.stroke();

    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = '#475569';
    ctx.font = '700 12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
    ctx.fillText('QUESTION TEXT', outerPad + 13, outerPad + 24);

    var buttonTop = outerPad + (mobile ? 42 : 12);
    var buttonRight = outerPad + cardWidth - 12;
    buttonRight = drawScreenshotButton(ctx, '\u25b6 Play', buttonRight, buttonTop);
    buttonRight = drawScreenshotButton(ctx, 'Copy Screenshot', buttonRight, buttonTop);
    drawScreenshotButton(ctx, 'Copy Text', buttonRight, buttonTop);

    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = '#0f172a';
    ctx.font = '600 16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
    var textY = outerPad + headerHeight + 27;
    lines.forEach(function(line, index) {{
      ctx.fillText(line, outerPad + bodyPadX, textY + index * lineHeight);
    }});
    return canvas;
  }}

  function canvasPng(canvas) {{
    return new Promise(function(resolve, reject) {{
      canvas.toBlob(function(blob) {{
        if (blob) resolve(blob);
        else reject(new Error('Could not create screenshot'));
      }}, 'image/png');
    }});
  }}

  function saveScreenshot(blob) {{
    var url = P.URL.createObjectURL(blob);
    var link = doc.createElement('a');
    link.href = url;
    link.download = 'studyforge-question.png';
    doc.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function() {{ P.URL.revokeObjectURL(url); }}, 1000);
  }}

  function copyScreenshot(button) {{
    var card = (button && button.closest('.sf-question-text-card')) || currentCard();
    if (!card || button.dataset.sfScreenshotBusy === '1') return;
    var originalLabel = button.getAttribute('data-sf-original-label') || button.textContent;
    button.setAttribute('data-sf-original-label', originalLabel);
    button.dataset.sfScreenshotBusy = '1';
    button.disabled = true;
    button.textContent = 'Copying…';

    function finish(label) {{
      button.dataset.sfScreenshotBusy = '';
      button.disabled = false;
      flash(button, label);
    }}

    var canvas = makeQuestionScreenshot(card);
    var png = canvasPng(canvas);
    var clipboard = (P.navigator && P.navigator.clipboard)
      || (window.navigator && window.navigator.clipboard);
    var ClipboardItemCtor = P.ClipboardItem || window.ClipboardItem;

    if (clipboard && clipboard.write && ClipboardItemCtor) {{
      try {{
        clipboard.write([new ClipboardItemCtor({{ 'image/png': png }})]).then(function() {{
          finish('Screenshot Copied');
        }}).catch(function() {{
          png.then(function(blob) {{
            saveScreenshot(blob);
            finish('Image Saved');
          }}).catch(function() {{ finish('Copy failed'); }});
        }});
        return;
      }} catch (e) {{}}
    }}
    png.then(function(blob) {{
      saveScreenshot(blob);
      finish('Image Saved');
    }}).catch(function() {{ finish('Copy failed'); }});
  }}

  function fallbackSpeak(value, button) {{
    var ss = P.speechSynthesis;
    if (!ss || !P.SpeechSynthesisUtterance) return;
    if (P._sfQuestionFallbackSpeaking) {{
      try {{ ss.cancel(); }} catch (e) {{}}
      P._sfQuestionFallbackSpeaking = false;
      button.innerHTML = '&#9654; Play';
      return;
    }}
    try {{ ss.cancel(); }} catch (e) {{}}
    var utterance = new P.SpeechSynthesisUtterance(value);
    var speed = P._sfVoiceState && P._sfVoiceState.speed ? P._sfVoiceState.speed : 1;
    utterance.rate = parseFloat(speed) || 1;
    utterance.volume = 1;
    utterance.lang = 'en-US';
    utterance.onend = utterance.onerror = function() {{
      P._sfQuestionFallbackSpeaking = false;
      button.innerHTML = '&#9654; Play';
    }};
    P._sfQuestionFallbackSpeaking = true;
    button.textContent = 'Stop';
    setTimeout(function() {{ try {{ ss.speak(utterance); }} catch (e) {{}} }}, 60);
  }}

  function playText(button) {{
    if (P._sfQuestionAudio && P._sfQuestionAudio.isSpeaking && P._sfQuestionAudio.isSpeaking()) {{
      P._sfQuestionAudio.stop();
      button.innerHTML = '&#9654; Play';
      return;
    }}
    if (P._sfQuestionAudio && P._sfQuestionAudio.playText) {{
      P._sfQuestionAudio.playText(text, {{ openPanel: false }});
      button.textContent = 'Stop';
      setTimeout(function poll() {{
        if (!P._sfQuestionAudio || !P._sfQuestionAudio.isSpeaking || !P._sfQuestionAudio.isSpeaking()) {{
          button.innerHTML = '&#9654; Play';
          return;
        }}
        setTimeout(poll, 400);
      }}, 400);
      return;
    }}
    fallbackSpeak(text, button);
  }}

  function installQuestionTools() {{
    var card = currentCard();
    if (!card) return false;
    card.setAttribute('data-sf-question-text', text);
    var area = card.querySelector('.sf-question-copy-area');
    if (area) {{
      area.value = text;
      area.style.height = 'auto';
      area.style.height = Math.max(52, area.scrollHeight) + 'px';
      // Browser zoom and narrower viewports change wrapping after initial load.
      // Observe width only so updating height does not create a resize loop.
      if (area._sfResizeObserver) area._sfResizeObserver.disconnect();
      var lastWidth = area.getBoundingClientRect().width;
      var resizeObserver = new P.ResizeObserver(function() {{
        var width = area.getBoundingClientRect().width;
        if (!width || width === lastWidth) return;
        lastWidth = width;
        area.style.height = 'auto';
        area.style.height = Math.max(52, area.scrollHeight) + 'px';
      }});
      resizeObserver.observe(area);
      area._sfResizeObserver = resizeObserver;
      window.addEventListener('pagehide', function() {{ resizeObserver.disconnect(); }}, {{once:true}});
    }}

    var copyButton = card.querySelector('[data-sf-copy-question="' + id + '"]');
    if (copyButton) {{
      copyButton.dataset.sfQuestionBound = '1';
      copyButton.onclick = function(event) {{
        event.preventDefault();
        copyText(copyButton);
      }};
    }}

    var screenshotButton = card.querySelector('[data-sf-copy-screenshot="' + id + '"]');
    if (screenshotButton) {{
      screenshotButton.dataset.sfQuestionBound = '1';
      screenshotButton.onclick = function(event) {{
        event.preventDefault();
        copyScreenshot(screenshotButton);
      }};
    }}

    var playButton = card.querySelector('[data-sf-play-question="' + id + '"]');
    if (playButton) {{
      playButton.dataset.sfQuestionBound = '1';
      playButton.onclick = function(event) {{
        event.preventDefault();
        playText(playButton);
      }};
    }}
    return true;
  }}

  ensureStyles();
  if (!installQuestionTools()) {{
    var observer = new MutationObserver(function() {{
      if (installQuestionTools()) observer.disconnect();
    }});
    observer.observe(doc.body, {{ childList: true, subtree: true }});
    setTimeout(installQuestionTools, 100);
    setTimeout(installQuestionTools, 350);
    setTimeout(installQuestionTools, 900);
    setTimeout(installQuestionTools, 1800);
    setTimeout(function() {{ observer.disconnect(); }}, 5000);
  }}
}})();
</script>
"""
    _components.html(script, height=0, scrolling=False)


def render_question(
    q: dict,
    idx: int,
    total: int,
    selected: str = "",
    show_answer: bool = False,
    is_flagged: bool = False,
    auto_expand_answer: bool = False,
    show_explanation: bool = True,
    compact_actions: bool = False,
    compact_text_tools: bool = False,
    stacked_header: bool = False,
) -> str | None:
    from src.question_loader import is_open_ended_question

    q = normalize_math_row(q)
    review_state = q.get("_smart_review_state") or {}
    correct = (q.get("correct_answer") or "").upper()
    choices = {
        k: q.get(f"choice_{k.lower()}", "")
        for k in ["A", "B", "C", "D", "E"]
    }
    choices = {k: v for k, v in choices.items() if v}

    # A narrow card (or browser zoom) cannot spare one sixth of its width for
    # the action label. Give each header section a full row in that layout.
    col_l, col_r = (st.container(), st.container()) if stacked_header else st.columns([5, 1])
    with col_l:
        diff = q.get("difficulty", 3)
        meta_parts = [
            f"Question {idx + 1} of {total}",
            question_reference_label(q),
            question_course_title(q),
            q.get("section_type", ""),
            q.get("question_type", ""),
            f"Difficulty: {DIFFICULTY_LABELS.get(diff, diff)}",
        ]
        meta = " | ".join(str(part) for part in meta_parts if part)
        st.markdown(
            f'<div class="sf-question-meta">{escape(meta)}</div>',
            unsafe_allow_html=True,
        )
        if review_state:
            review_bits = [
                f"seen {int(review_state.get('times_seen') or 0)}x",
                f"misses {int(review_state.get('misses') or 0)}",
                f"streak {int(review_state.get('correct_streak') or 0)}",
                f"mastery {int(review_state.get('mastery_level') or 0)}/5",
            ]
            st.info(
                "Smart Review Queue: this question is returning from your prior "
                f"work ({', '.join(review_bits)})."
            )
    with col_r:
        flag_label = "🚩 Flagged" if is_flagged else "🏳️ Flag"
        report_key = f"question_report_open_{q.get('id', idx)}_{idx}"
        action_context = st.popover("Question actions") if compact_actions else st.container()
        with action_context:
            st.button(flag_label, key=f"flag_btn_{idx}", on_click=_flag_cb, args=(idx,))
            if st.button("Report Issue", key=f"report_issue_btn_{idx}"):
                st.session_state[report_key] = True

    if st.session_state.get(report_key):
        issue_types = [
            "Incorrect answer key",
            "Bad explanation",
            "Weak or mismatched answer choices",
            "Typo or formatting issue",
            "Ambiguous wording",
            "Wrong category/type",
            "Passage or answer choice missing",
            "Other",
        ]
        with st.form(f"question_report_form_{q.get('id', idx)}_{idx}"):
            st.markdown("**Report Issue**")
            issue_type = st.selectbox("Issue type", issue_types)
            note = st.text_area(
                "Optional note",
                placeholder="Example: I think B and D both work here.",
                height=90,
            )
            form_cols = st.columns(2)
            submit_report = form_cols[0].form_submit_button(
                "Submit Report", type="primary", use_container_width=True
            )
            cancel_report = form_cols[1].form_submit_button(
                "Cancel", use_container_width=True
            )
        if submit_report:
            from src.database import create_question_issue_report

            report_id, err = create_question_issue_report(
                user_id=st.session_state.get("user_id"),
                question_id=q.get("id"),
                attempt_id=st.session_state.get("exam_attempt_id"),
                issue_type=issue_type,
                note=note,
                selected_answer=selected or "",
                mode=st.session_state.get("exam_mode", ""),
            )
            if err:
                st.error(f"Could not save report: {err}")
            else:
                st.session_state.pop(report_key, None)
                st.success(f"Report submitted. Reference #{report_id}.")
                st.rerun()
        if cancel_report:
            st.session_state.pop(report_key, None)
            st.rerun()

    if q.get("passage"):
        tags = str(q.get("tags") or "").lower()
        supporting_material_label = (
            "📊 Question Exhibit" if "exhibit" in tags else "📖 Read Passage"
        )
        with st.expander(supporting_material_label, expanded=True):
            st.markdown(q["passage"])

    stimulus = str(q.get("stimulus", "")).strip()
    question_dom_id = f"sf-question-text-{q.get('id', idx)}-{idx}"
    st.markdown(
        _question_text_card_html(stimulus, question_dom_id, compact_tools=compact_text_tools),
        unsafe_allow_html=True,
    )
    _inject_question_text_tools(stimulus, question_dom_id)

    if is_open_ended_question(q):
        sample_answer = str(q.get("_sample_answer") or "").strip()
        if not sample_answer and correct in choices:
            sample_answer = str(choices.get(correct) or "").strip()
        if not sample_answer:
            sample_answer = str(q.get("correct_answer") or "").strip()
        if show_answer:
            if selected:
                st.markdown("**Your response:**")
                st.info(selected)
            if sample_answer:
                with st.expander("Sample answer / rubric", expanded=auto_expand_answer):
                    st.success(sample_answer)
            if show_explanation and q.get("explanation"):
                with st.expander("Explanation", expanded=auto_expand_answer):
                    st.info(q["explanation"])
            return selected

        return st.text_area(
            "Write your answer:",
            value=selected or "",
            height=180,
            key=f"q_open_ended_{idx}",
        ).strip()

    option_keys = list(choices.keys())

    if show_answer:
        for letter, text in choices.items():
            with st.container(key=f"sf_answer_review_{idx}_{letter}"):
                if letter == correct and letter == selected:
                    st.success(f"✅ **{letter}.** {text}  ← Correct")
                elif letter == correct:
                    st.success(f"✅ **{letter}.** {text}  ← Correct answer")
                elif letter == selected:
                    st.error(f"❌ **{letter}.** {text}  ← Your answer")
                else:
                    st.write(f"**{letter}.** {text}")
        if show_explanation and q.get("explanation"):
            with st.expander("💡 Explanation", expanded=auto_expand_answer):
                st.info(q["explanation"])
                for letter in ["A", "B", "C", "D", "E"]:
                    note = q.get(f"wrong_answer_{letter.lower()}", "")
                    if note and letter != correct:
                        st.caption(f"**Why {letter} is wrong:** {note}")
        return selected
    else:
        options     = [f"**{k}.** {v}" for k, v in choices.items()]
        default_idx = option_keys.index(selected) if selected in option_keys else None
        picked = st.radio(
            "Select your answer:",
            options=options,
            index=default_idx,
            key=f"q_radio_{idx}",
        )
        return picked[2] if picked else None


def _flag_cb(idx: int) -> None:
    from src.exam_engine import toggle_flag
    toggle_flag(idx)


# ── Score display ─────────────────────────────────────────────────────────────
def render_score_card(report: dict, title: str = "Score Report") -> None:
    st.markdown(
        f'<section class="sf-score-shell"><h2 class="sf-score-title">{escape(title)}</h2></section>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Raw Score",   f"{report['correct']} / {report['total']}")
    c2.metric("% Correct",   f"{report['percent_correct']}%")
    c3.metric("Est. Scaled", report.get("scaled_score") or "—")
    c4.metric("Avg Time/Q",  f"{report.get('avg_time_seconds', 0):.0f}s")
    excluded = int(report.get("excluded_unreached") or 0)
    planned_total = int(report.get("planned_total") or report.get("total") or 0)
    scored_total = int(report.get("scored_total") or report.get("total") or 0)
    if excluded:
        st.caption(
            f"Scored from {scored_total} reached question(s). "
            f"{excluded} of {planned_total} planned question(s) were excluded."
        )
    if report.get("by_question_type"):
        st.markdown("**Accuracy by Question Type**")
        import pandas as pd
        rows = [
            {"Type": qt, "Correct": v["correct"],
             "Total": v["total"], "% Correct": v["percent"]}
            for qt, v in sorted(
                report["by_question_type"].items(),
                key=lambda x: x[1]["percent"],
            )
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Timer bar ─────────────────────────────────────────────────────────────────
def render_timer(
    seconds: float,
    total_seconds: float,
    key_prefix: str = "exam_timer",
    allow_pause: bool = True,
) -> None:
    from src.exam_engine import (
        is_timer_paused, is_timer_visible,
        toggle_timer_pause, toggle_timer_visibility,
    )

    pct  = max(0.0, min(1.0, seconds / total_seconds)) if total_seconds else 0
    m, s = divmod(int(seconds), 60)
    paused = is_timer_paused()
    visible = is_timer_visible()

    if visible:
        suffix = "paused" if paused else "remaining"
        st.markdown(
            f'<div class="sf-timer-card"><div class="sf-timer-label">{m:02d}:{s:02d} {suffix}</div></div>',
            unsafe_allow_html=True,
        )
        st.progress(pct)
    else:
        st.caption("Timer hidden. You can turn it back on from any question.")

    show_col, pause_col = st.columns(2)
    with show_col:
        show_label = "Hide" if visible else "Show"
        if st.button(show_label, key=f"{key_prefix}_show", use_container_width=True):
            toggle_timer_visibility()
            st.rerun()
    with pause_col:
        pause_label = "Resume" if paused else "Pause"
        if st.button(
            pause_label,
            key=f"{key_prefix}_pause",
            use_container_width=True,
            disabled=not allow_pause,
        ):
            toggle_timer_pause()
            st.rerun()
        if not allow_pause:
            st.caption("Hard Mode")
