"""Shared, per-user mastery colors and independent review-window activity."""
from collections import defaultdict
from html import escape

from src.database import get_all_settings, get_connection

METHODS = {"recent": "Last 3 completed sessions", "latest": "Most recent completed session", "all": "All completed sessions"}
COLORS = {"red": ("🔴", "Needs work", "#fee2e2", "#991b1b"), "yellow": ("🟡", "Building", "#fef3c7", "#854d0e"), "green": ("🟢", "Strong", "#dcfce7", "#166534"), "gray": ("⚪", "Not practiced", "#f1f5f9", "#475569")}


def preferences(settings):
    try:
        yellow, green = int(settings.get("progress_yellow", 60)), int(settings.get("progress_green", 80))
        if not 0 <= yellow < green <= 100:
            raise ValueError
    except (ValueError, TypeError):
        yellow, green = 60, 80
    method = settings.get("progress_method", "recent")
    return {"method": method if method in METHODS else "recent", "yellow": yellow, "green": green}


def review_window(user_id, review_id=None):
    from src.mock_review import get_mock_schedule, get_review_schedule
    from src.practice_review_focus import scheduled_review
    schedule = get_mock_schedule(user_id)
    row = (next((r for r in schedule if r["id"] == review_id), None)
           if review_id is not None else scheduled_review(schedule))
    if not row:
        return None
    start = str(row.get("completed_at") or row["scheduled_date"])[:10]
    later = sorted(r["scheduled_date"] for r in get_review_schedule(user_id) if r["scheduled_date"] > row["scheduled_date"])
    return start, later[0] if later else None


def summarize(rows, prefs, window=None):
    sessions = defaultdict(list)
    for row in rows:
        if row.get("completed_at"):
            sessions[(row["completed_at"], row["attempt_id"])].append(row)
    ordered = sorted(sessions, reverse=True)
    selected = ordered[:1] if prefs["method"] == "latest" else ordered[:3] if prefs["method"] == "recent" else ordered
    answers = [r for key in selected for r in sessions[key]]
    score = 100 * sum(r["is_correct"] == 1 for r in answers) / len(answers) if answers else None
    color = "gray" if score is None else "green" if score >= prefs["green"] else "yellow" if score >= prefs["yellow"] else "red"
    practiced = any(window and window[0] <= key[0][:10] and (window[1] is None or key[0][:10] < window[1])
                    and any(r.get("mode") not in {"mock_exam", "full_exam", "neonatal_mock"} for r in sessions[key])
                    for key in ordered)
    return {"score": score, "color": color, "questions": len(answers), "sessions": len(selected),
            "practiced": practiced, "last": ordered[0][0][:10] if ordered else None}


def load_progress(user_id, settings=None, review_id=None, question_ids=None):
    prefs = preferences(settings if settings is not None else get_all_settings(user_id))
    window = review_window(user_id, review_id)
    conn = get_connection()
    try:
        chapters = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM course_chapters")} if conn.execute("SELECT 1 FROM sqlite_master WHERE name='course_chapters'").fetchone() else {}
        chapter_column = "q.chapter_id" if "chapter_id" in {r["name"] for r in conn.execute("PRAGMA table_info(questions)")} else "NULL AS chapter_id"
        rows = [dict(r) for r in conn.execute(f"""SELECT ea.id AS attempt_id, ea.completed_at, ea.mode, ua.is_correct,
                  q.id AS question_id, q.course_id, q.section_type, {chapter_column}
                  FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                  JOIN questions q ON q.id=ua.question_id
                  WHERE ea.user_id=? AND ea.completed_at IS NOT NULL
                  ORDER BY ea.completed_at DESC, ea.id DESC""", (user_id,))]
    finally:
        conn.close()
    courses, modules = defaultdict(list), defaultdict(list)
    for row in rows:
        if question_ids is not None and row["question_id"] not in question_ids:
            continue
        label = row["section_type"] or ""
        if row.get("chapter_id") in chapters:
            label = f"{label or 'Chapters'} / {chapters[row['chapter_id']]}"
        courses[row["course_id"]].append(row)
        modules[(row["course_id"], progress_module_key(label))].append(row)
    return {"prefs": prefs, "window": window, "courses": courses, "modules": modules}


def progress_module_key(module):
    """A placeholder General chapter is the same topic as older unchaptered records."""
    from src.practice_review_focus import topic_key
    value = str(module or "").strip()
    if value.casefold().endswith(" / general"):
        value = value[:-len(" / general")]
    return topic_key(value)


def status(progress, course_ids, module=None):
    groups = progress["courses"] if module is None else progress["modules"]
    rows = [row for cid in course_ids for row in groups.get(cid if module is None else (cid, progress_module_key(module)), [])]
    return summarize(rows, progress["prefs"], progress["window"])


def label(text, value, window=None):
    icon, name, _, _ = COLORS[value["color"]]
    score = f"{value['score']:.1f}%" if value["score"] is not None else name
    activity = " · ✓ Practiced this window" if window and value["practiced"] else " · Not yet this window" if window else ""
    check = " ✓" if window and value["practiced"] else ""
    return f"{icon}{check} {text} · {score}{activity}"


def render_progress(progress, entries, *, expanded=False, dashboard_context=None):
    import streamlit as st
    prefs = progress["prefs"]
    if dashboard_context:
        from src.dashboard_layout import tracked_expander
        panel = tracked_expander('Course & module progress', *dashboard_context, 'progress', default=expanded)
    else:
        panel = st.expander("Course & module progress", expanded=expanded)
    with panel:
        st.caption(f"🔴 Below {prefs['yellow']}% · 🟡 {prefs['yellow']}–<{prefs['green']}% · 🟢 {prefs['green']}%+ · ⚪ Not practiced. {METHODS[prefs['method']]}; weighted by questions answered.")
        if progress["window"]:
            start, end = progress["window"]
            st.caption(f"Review window: {start} to {end + ' (exclusive)' if end else 'next scheduled mock'}. ✓ means at least one completed practice or section session included this topic; it does not mean the entire module is finished.")
        st.caption("Scores use completed sessions across exam modes. Change colors and scoring in Settings → General → Progress colors.")
        cards = []
        for title, value in entries:
            _, name, bg, fg = COLORS[value["color"]]
            text = label(title, value, progress["window"])
            detail = f"{name} · {value['questions']} scored questions in {value['sessions']} session(s) · Last practiced: {value['last'] or 'Never'}"
            cards.append(f'<div style="background:{bg};color:{fg};border:1px solid {fg};border-radius:8px;padding:9px 12px;margin:6px 0"><strong>{escape(text)}</strong><br><small>{escape(detail)}</small></div>')
        st.markdown('<div style="max-height:440px;overflow-y:auto">' + "".join(cards) + "</div>" if cards else "No modules available.", unsafe_allow_html=True)


def render_course_progress(user_id, course_ids, *, review_id=None, dashboard_mode=None):
    from src.practice_allocation import practice_questions, module_label
    from src.database import get_course
    progress = load_progress(user_id, review_id=review_id)
    entries = []
    for cid in course_ids:
        title = (get_course(cid) or {}).get("title", "Course")
        entries.append((title, status(progress, [cid])))
        for module in sorted({module_label(q) for q in practice_questions([cid]) if module_label(q)}):
            entries.append((f"{title} / {module}", status(progress, [cid], module)))
    render_progress(progress, entries, dashboard_context=(user_id, dashboard_mode) if dashboard_mode else None)


def render_selector_colors():
    """Color only progress-decorated tags; keep Streamlit selection behavior."""
    import streamlit as st
    rules = []
    for icon, _, bg, fg in COLORS.values():
        selector = f'[data-baseweb="tag"]:has([title^="{icon}"])'
        rules.append(f'{selector} {{background-color:{bg} !important;color:{fg} !important;border:1px solid {fg} !important}} {selector} span, {selector} svg {{color:{fg} !important}}')
    st.markdown("<style>" + "\n".join(rules) + "</style>", unsafe_allow_html=True)
