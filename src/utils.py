"""
utils.py — Shared UI helpers, course selector, and small utilities.
"""

from __future__ import annotations
from html import escape
import json
import streamlit as st
import streamlit.components.v1 as _components

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


# --- Sidebar page labels ----------------------------------------------------
def _sidebar_page_label_js(review_badge_count: int = 0) -> str:
    template = """
<script>
(function () {
    'use strict';

    var reviewBadgeCount = __REVIEW_BADGE_COUNT__;
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
            if (labelNode) {
                labelNode.textContent = 'Sign In';
            } else {
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
            if (!isReviewLink) { return; }

            link.classList.add('sf-review-nav-link');
            if (link.getAttribute('data-sf-review-count') === String(reviewBadgeCount)) { return; }

            var labelNode = link.querySelector('span, p, div') || link;
            var existingBadge = link.querySelector('.sf-review-nav-badge');
            if (reviewBadgeCount > 0) {
                if (!existingBadge) {
                    existingBadge = doc.createElement('span');
                    existingBadge.className = 'sf-review-nav-badge';
                    labelNode.appendChild(existingBadge);
                }
                existingBadge.textContent = reviewBadgeCount > 99 ? '99+' : String(reviewBadgeCount);
                link.setAttribute('aria-label', 'Review Mistakes, ' + reviewBadgeCount + ' outstanding');
                link.setAttribute('title', reviewBadgeCount + ' outstanding mistakes to review');
            } else if (existingBadge) {
                existingBadge.remove();
                link.setAttribute('aria-label', 'Review Mistakes');
                link.setAttribute('title', 'Review Mistakes');
            }
            link.setAttribute('data-sf-review-count', String(reviewBadgeCount));
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
    return template.replace("__REVIEW_BADGE_COUNT__", str(int(review_badge_count)))

_SIDEBAR_PAGE_LABEL_CSS = """
<style>
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
    align-items: center !important;
    gap: 0.5rem !important;
}

.sf-review-nav-badge {
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


def inject_sidebar_page_labels(review_badge_count: int = 0) -> None:
    """Rename Streamlit's default app.py sidebar label to the user-facing page name."""
    st.markdown(_SIDEBAR_PAGE_LABEL_CSS, unsafe_allow_html=True)
    _components.html(_sidebar_page_label_js(review_badge_count), height=0, scrolling=False)


# ── Collapsible sidebar ───────────────────────────────────────────────────────
#
# WHY TWO SEPARATE INJECTIONS
# ──────────────────────────────────────────────────────────────────────────────
# st.markdown(unsafe_allow_html=True) works via React's dangerouslySetInnerHTML
# which calls element.innerHTML under the hood.  Browsers deliberately do NOT
# execute <script> tags added via innerHTML — it's a longstanding browser
# security rule.  CSS <style> tags DO apply from innerHTML, so CSS stays in
# st.markdown.
#
# st.components.v1.html() renders a genuine <iframe> with its own document.
# Scripts inside it execute normally.  The iframe runs on the same origin
# (localhost:8501), so window.parent gives full access to the Streamlit page.
# This is exactly how streamlit-autorefresh works.
#
# LAYOUT (Streamlit 1.32 – 1.57+)
# ──────────────────────────────────────────────────────────────────────────────
# stAppViewContainer → display:flex; flex-direction:row
#   section[stSidebar] → position:relative; min-width/max-width own the flex space
#   div (main)         → width:100%; min-width:0  — fills remaining space
#
# Collapse = min-width:0; max-width:0; translateX(-600px).
# Main expands automatically because it is flex: width 100%.


# ── Part 1: CSS — safe to inject via st.markdown ─────────────────────────────
_SIDEBAR_CSS = """
<style>
/* StudyForge — Collapsible Sidebar */

/* Smooth transitions always active */
section[data-testid="stSidebar"] {
    transition:
        min-width  0.28s cubic-bezier(0.4,0,0.2,1),
        max-width  0.28s cubic-bezier(0.4,0,0.2,1),
        transform  0.28s cubic-bezier(0.4,0,0.2,1),
        visibility 0.28s,
        opacity    0.22s !important;
    will-change: min-width, max-width, transform;
    overflow: hidden !important;
}

/* Collapsed state */
body.sf-sb-collapsed section[data-testid="stSidebar"] {
    min-width:  0         !important;
    max-width:  0         !important;
    transform:  translateX(-600px) !important;
    visibility: hidden    !important;
    opacity:    0         !important;
    overflow:   hidden    !important;
}

/* Hide Streamlit's own toggle buttons — we supply ours */
[data-testid="stSidebarCollapseButton"],
[data-testid="stExpandSidebarButton"] {
    display: none !important;
}

/* Toggle button (created via JS, appended to parent body) */
#sf-sb-btn {
    position:        fixed;
    top:             10px;
    left:            var(--sf-btn-left, 290px);
    z-index:         9999999;
    width:           32px;
    height:          32px;
    border:          1px solid rgba(49,51,63,.20);
    border-radius:   8px;
    background:      var(--background-color, #ffffff);
    cursor:          pointer;
    display:         flex;
    align-items:     center;
    justify-content: center;
    padding:         0;
    box-shadow:      0 1px 4px rgba(0,0,0,.10);
    transition:      left .28s cubic-bezier(.4,0,.2,1),
                     background .15s, box-shadow .15s;
    color:           rgb(49,51,63);
    outline:         none;
    font-family:     inherit;
}
body.sf-sb-collapsed #sf-sb-btn { left: 10px; }
#sf-sb-btn:hover         { background: rgba(49,51,63,.08); box-shadow: 0 2px 8px rgba(0,0,0,.14); }
#sf-sb-btn:focus-visible { outline: 2px solid #4A90D9; outline-offset: 2px; }
#sf-sb-btn svg           {
    width:16px; height:16px; stroke:currentColor; fill:none;
    stroke-width:2.2; stroke-linecap:round; stroke-linejoin:round;
    pointer-events:none; flex-shrink:0;
}

/* Mobile overlay */
#sf-sb-overlay {
    display:    none;
    position:   fixed;
    inset:      0;
    background: rgba(0,0,0,.45);
    z-index:    9999990;
    cursor:     pointer;
}
@media (max-width: 768px) {
    body:not(.sf-sb-collapsed) #sf-sb-overlay { display: block; }
    body:not(.sf-sb-collapsed) #sf-sb-btn     { left: 10px; }
    section[data-testid="stSidebar"]           { z-index: 9999995 !important; }
}

/* Dark theme */
[data-theme="dark"] #sf-sb-btn,
.stApp[data-theme="dark"] #sf-sb-btn        { background: rgba(255,255,255,.06);
                                               border-color: rgba(255,255,255,.22);
                                               color: rgb(250,250,250); }
[data-theme="dark"] #sf-sb-btn:hover,
.stApp[data-theme="dark"] #sf-sb-btn:hover  { background: rgba(255,255,255,.13); }
@media (prefers-color-scheme: dark) {
    #sf-sb-btn       { background: rgba(255,255,255,.06);
                       border-color: rgba(255,255,255,.22); color: rgb(250,250,250); }
    #sf-sb-btn:hover { background: rgba(255,255,255,.13); }
}
</style>
"""

# ── Part 2: JS — must run via components.html (same-origin iframe) ────────────
# All DOM queries use window.parent.document so we reach the real Streamlit page.
_SIDEBAR_JS = """
<script>
(function () {
    'use strict';

    /* Reach the parent Streamlit page from inside the iframe */
    var P = window.parent;
    if (!P || !P.document) { return; }
    var doc  = P.document;
    var body = doc.body;

    var KEY = 'sf_sidebar_collapsed';
    var BTN = 'sf-sb-btn';
    var OVL = 'sf-sb-overlay';
    var CLS = 'sf-sb-collapsed';

    /* localStorage — same origin so parent's storage is accessible */
    function getLS()  { try { return P.localStorage.getItem(KEY) === '1'; } catch(e) { return false; } }
    function setLS(v) { try { P.localStorage.setItem(KEY, v ? '1' : '0'); } catch(e) {} }
    function isColl() { return body.classList.contains(CLS); }

    /* Measure sidebar width to position the button at its right edge */
    var _left = 290;
    function measure() {
        if (isColl()) { return; }
        var sb = doc.querySelector('section[data-testid="stSidebar"]');
        if (!sb) { return; }
        var w = sb.getBoundingClientRect().width;
        if (w > 60) {
            _left = Math.round(w - 44);
            doc.documentElement.style.setProperty('--sf-btn-left', _left + 'px');
        }
    }

    /* SVG icons */
    var CHEVRON = '<svg viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"/></svg>';
    var BURGER  = '<svg viewBox="0 0 24 24">'
                + '<line x1="3" y1="6"  x2="21" y2="6"/>'
                + '<line x1="3" y1="12" x2="21" y2="12"/>'
                + '<line x1="3" y1="18" x2="21" y2="18"/>'
                + '</svg>';

    /* Apply collapse/expand to the parent document */
    function applyState(c) {
        if (c) { body.classList.add(CLS); } else { body.classList.remove(CLS); }
        var btn = doc.getElementById(BTN);
        if (btn) {
            btn.innerHTML = c ? BURGER : CHEVRON;
            var lbl = c ? 'Expand sidebar' : 'Collapse sidebar';
            btn.title = lbl;
            btn.setAttribute('aria-label',   lbl);
            btn.setAttribute('aria-expanded', c ? 'false' : 'true');
            if (!c) { btn.style.left = _left + 'px'; }
        }
        if (!c) { setTimeout(measure, 320); }
    }

    function toggle() {
        var next = !isColl();
        setLS(next);
        applyState(next);
    }

    /* Ensure button exists in parent document */
    function ensureButton() {
        if (doc.getElementById(BTN)) { return; }
        var btn = doc.createElement('button');
        btn.id   = BTN;
        btn.type = 'button';
        btn.setAttribute('tabindex',    '0');
        btn.setAttribute('aria-label',  'Toggle sidebar');
        btn.setAttribute('aria-expanded', 'true');
        btn.addEventListener('click', toggle);
        btn.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
        });
        body.appendChild(btn);
    }

    /* Ensure mobile overlay exists in parent document */
    function ensureOverlay() {
        if (doc.getElementById(OVL)) { return; }
        var o = doc.createElement('div');
        o.id  = OVL;
        o.setAttribute('aria-hidden', 'true');
        o.addEventListener('click', function () { setLS(true); applyState(true); });
        body.appendChild(o);
    }

    /* MutationObserver — recreate button/overlay if React removes them.
       Store on parent window so each new iframe run replaces the old one.  */
    if (P._sfSbObs) { P._sfSbObs.disconnect(); }
    P._sfSbObs = new MutationObserver(function () {
        if (!doc.getElementById(BTN) || !doc.getElementById(OVL)) {
            ensureButton();
            ensureOverlay();
            applyState(getLS());
        }
    });
    P._sfSbObs.observe(body, { childList: true, subtree: false });

    /* Periodic guard — re-sync if a Streamlit Python rerun clears body class  */
    if (P._sfSbTimer) { clearInterval(P._sfSbTimer); }
    P._sfSbTimer = setInterval(function () {
        if (getLS() !== isColl()) { applyState(getLS()); }
    }, 800);

    /* Run immediately */
    ensureButton();
    ensureOverlay();
    measure();
    applyState(getLS());
})();
</script>
"""


def _inject_sidebar_toggle() -> None:
    """
    Inject the collapsible-sidebar system.  Called once per page from sidebar_nav().

    CSS  → st.markdown (style tags apply even from innerHTML; no execution needed)
    JS   → st.components.v1.html height=0 (real iframe, script executes, uses
           window.parent.document to reach the Streamlit page DOM)
    """
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

    uid = st.session_state.get("user_id")
    review_badge_count = _review_mistakes_outstanding_count(uid)

    inject_modern_theme()
    inject_sidebar_page_labels(review_badge_count)
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

    # Inject floating feedback FAB
    _inject_feedback_button()


# ── Course selector (enrollment-based) ───────────────────────────────────────
def course_selector(user_id: int, label: str = "📚 Active Course") -> int | None:
    """
    Render the active-course picker in the sidebar.
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

    options    = {c["id"]: c["title"] for c in enrolled}
    option_ids = list(options.keys())

    stored = st.session_state.get("active_course_id")
    if stored not in options:
        st.session_state["active_course_id"] = option_ids[0]
        stored = option_ids[0]

    with st.sidebar:
        st.markdown(f"**{label}**")
        selected_id = st.selectbox(
            "course_select",
            options=option_ids,
            format_func=lambda x: options[x],
            index=option_ids.index(stored),
            key="sidebar_course_selector",
            label_visibility="collapsed",
        )
        st.session_state["active_course_id"] = selected_id
        st.divider()

    return selected_id


def require_course(user_id: int) -> int:
    """
    Show course selector and stop execution if user has no enrollments.
    Returns course_id.
    """
    cid = course_selector(user_id)
    if cid is None:
        st.warning(
            "You are not enrolled in any courses yet. "
            "No active courses are available for your account yet."
        )
        st.stop()
    return cid


# ── Question rendering ────────────────────────────────────────────────────────
def _question_text_card_html(question_text: str, dom_id: str) -> str:
    return f"""
<div class="sf-question-text-card" id="{escape(dom_id, quote=True)}">
  <div class="sf-question-actionbar">
    <span class="sf-question-action-label">Question text</span>
    <span class="sf-question-actions">
      <button type="button" class="sf-question-tool" data-sf-copy-question="{escape(dom_id, quote=True)}">Copy</button>
      <button type="button" class="sf-question-tool" data-sf-play-question="{escape(dom_id, quote=True)}">&#9654; Play</button>
    </span>
  </div>
  <textarea class="sf-question-copy-block sf-question-copy-area" aria-label="Question text for copying" readonly>{escape(question_text)}</textarea>
</div>
"""


def _inject_question_text_tools(question_text: str, dom_id: str) -> None:
    text_json = json.dumps(question_text)
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
    if (doc.getElementById('sf-question-text-tools-style')) return;
    var style = doc.createElement('style');
    style.id = 'sf-question-text-tools-style';
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
        font:600 1rem/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
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

  function selectQuestionText() {{
    var card = doc.getElementById(id);
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
    selectQuestionText();
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
    var card = doc.getElementById(id);
    if (!card) return false;
    card.setAttribute('data-sf-question-text', text);
    var area = card.querySelector('.sf-question-copy-area');
    if (area) {{
      area.value = text;
      area.style.height = 'auto';
      area.style.height = Math.max(52, area.scrollHeight) + 'px';
    }}

    var copyButton = card.querySelector('[data-sf-copy-question="' + id + '"]');
    if (copyButton && !copyButton.dataset.sfQuestionBound) {{
      copyButton.dataset.sfQuestionBound = '1';
      copyButton.addEventListener('click', function() {{ copyText(copyButton); }});
    }}

    var playButton = card.querySelector('[data-sf-play-question="' + id + '"]');
    if (playButton && !playButton.dataset.sfQuestionBound) {{
      playButton.dataset.sfQuestionBound = '1';
      playButton.addEventListener('click', function() {{ playText(playButton); }});
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
) -> str | None:
    from src.question_loader import is_open_ended_question

    review_state = q.get("_smart_review_state") or {}
    correct = (q.get("correct_answer") or "").upper()
    choices = {
        k: q.get(f"choice_{k.lower()}", "")
        for k in ["A", "B", "C", "D", "E"]
    }
    choices = {k: v for k, v in choices.items() if v}

    col_l, col_r = st.columns([5, 1])
    with col_l:
        diff = q.get("difficulty", 3)
        meta_parts = [
            f"Question {idx + 1} of {total}",
            question_reference_label(q),
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
        st.button(flag_label, key=f"flag_btn_{idx}", on_click=_flag_cb, args=(idx,))
        report_key = f"question_report_open_{q.get('id', idx)}_{idx}"
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
        with st.expander("📖 Read Passage", expanded=True):
            st.markdown(q["passage"])

    stimulus = str(q.get("stimulus", "")).strip()
    question_dom_id = f"sf-question-text-{q.get('id', idx)}-{idx}"
    st.markdown(
        _question_text_card_html(stimulus, question_dom_id),
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
            if q.get("explanation"):
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
            if letter == correct and letter == selected:
                st.success(f"✅ **{letter}.** {text}  ← Correct")
            elif letter == correct:
                st.success(f"✅ **{letter}.** {text}  ← Correct answer")
            elif letter == selected:
                st.error(f"❌ **{letter}.** {text}  ← Your answer")
            else:
                st.write(f"**{letter}.** {text}")
        if q.get("explanation"):
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
