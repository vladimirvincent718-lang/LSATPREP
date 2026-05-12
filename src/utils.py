"""
utils.py — Shared UI helpers, course selector, and small utilities.
"""

from __future__ import annotations
import streamlit as st
import streamlit.components.v1 as _components

DIFFICULTY_LABELS = {1: "Easy", 2: "Medium-Easy", 3: "Medium", 4: "Hard", 5: "Brutal"}
ANSWER_LETTERS    = ["A", "B", "C", "D", "E"]

SECTION_TYPES  = ["Logical Reasoning", "Reading Comprehension"]
QUESTION_TYPES = [
    "Strengthen", "Weaken", "Flaw", "Assumption", "Inference",
    "Main Point", "Must Be True", "Parallel Reasoning",
    "Principle", "Role of Statement", "Method of Reasoning",
    "Point of Disagreement", "Evaluate", "Explain",
]


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

/* Pin the element-container that wraps the FAB button */
[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] {
    position: fixed !important;
    bottom: 28px !important;
    right: 28px !important;
    z-index: 99999 !important;
    width: fit-content !important;
    height: auto !important;
    overflow: visible !important;
}

/* Style the button itself */
[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] button {
    background: linear-gradient(135deg, #4A90D9 0%, #357ABD 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 50px !important;
    padding: 10px 20px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    box-shadow: 0 4px 16px rgba(74,144,217,0.45), 0 2px 6px rgba(0,0,0,0.15) !important;
    cursor: pointer !important;
    white-space: nowrap !important;
    letter-spacing: 0.01em !important;
    width: auto !important;
    transition: transform 0.18s ease, box-shadow 0.18s ease !important;
}
[data-testid="element-container"]:has(#sf-feedback-fab-marker)
  + [data-testid="element-container"] button:hover {
    background: linear-gradient(135deg, #5BA0E8 0%, #4A90D9 100%) !important;
    box-shadow: 0 6px 22px rgba(74,144,217,0.55), 0 3px 10px rgba(0,0,0,0.18) !important;
    transform: translateY(-2px) !important;
}

/* Hide the sidebar auto-generated Feedback entry */
[data-testid="stSidebarNavItems"] a[href*="feedback"],
[data-testid="stSidebarNavItems"] a[href*="Feedback"],
[data-testid="stSidebarNavItems"] a[href*="11_Feedback"] {
    display: none !important;
}
</style>
"""

def _inject_feedback_button() -> None:
    """Inject the floating Feedback FAB into every authenticated page."""
    st.markdown(_FEEDBACK_BTN_CSS, unsafe_allow_html=True)
    st.markdown('<div id="sf-feedback-fab-marker"></div>', unsafe_allow_html=True)
    if st.button("💬 Feedback", key="sf_feedback_fab"):
        st.switch_page("pages/11_Feedback.py")


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
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)
    st.divider()


def sidebar_nav(username: str) -> None:
    # Inject collapsible-sidebar (CSS via markdown, JS via iframe component)
    _inject_sidebar_toggle()

    with st.sidebar:
        st.markdown(f"**Logged in as:** {username}")
        uid = st.session_state.get("user_id")

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
            st.caption("Go to **Course Manager** to enroll.")
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
            "Go to **Course Manager** in the sidebar to browse and enroll."
        )
        st.stop()
    return cid


# ── Question rendering ────────────────────────────────────────────────────────
def render_question(
    q: dict,
    idx: int,
    total: int,
    selected: str = "",
    show_answer: bool = False,
    is_flagged: bool = False,
) -> str | None:
    correct = (q.get("correct_answer") or "").upper()
    choices = {
        k: q.get(f"choice_{k.lower()}", "")
        for k in ["A", "B", "C", "D", "E"]
    }
    choices = {k: v for k, v in choices.items() if v}

    col_l, col_r = st.columns([5, 1])
    with col_l:
        diff = q.get("difficulty", 3)
        st.caption(
            f"Question {idx + 1} of {total}  ·  "
            f"{q.get('section_type', '')}  ·  "
            f"{q.get('question_type', '')}  ·  "
            f"Difficulty: {DIFFICULTY_LABELS.get(diff, diff)}"
        )
    with col_r:
        flag_label = "🚩 Flagged" if is_flagged else "🏳️ Flag"
        st.button(flag_label, key=f"flag_btn_{idx}", on_click=_flag_cb, args=(idx,))

    if q.get("passage"):
        with st.expander("📖 Read Passage", expanded=True):
            st.markdown(q["passage"])

    st.markdown(f"**{q.get('stimulus', '')}**")
    st.markdown("")

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
            with st.expander("💡 Explanation"):
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
    st.markdown(f"### {title}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Raw Score",   f"{report['correct']} / {report['total']}")
    c2.metric("% Correct",   f"{report['percent_correct']}%")
    c3.metric("Est. Scaled", report.get("scaled_score") or "—")
    c4.metric("Avg Time/Q",  f"{report.get('avg_time_seconds', 0):.0f}s")
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
def render_timer(seconds: float, total_seconds: float) -> None:
    pct  = max(0.0, min(1.0, seconds / total_seconds)) if total_seconds else 0
    m, s = divmod(int(seconds), 60)
    st.progress(pct, text=f"⏱ {m:02d}:{s:02d} remaining")
