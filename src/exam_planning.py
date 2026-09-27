"""Personal curriculum exam appointments and dashboard metric preferences."""
import json
from contextlib import closing
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from src.database import get_connection, get_setting, set_setting


def ensure_schema():
    with closing(get_connection()) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS personal_exam_plan (
            user_id INTEGER PRIMARY KEY, curriculum_id INTEGER NOT NULL,
            exam_date TEXT NOT NULL, exam_time TEXT NOT NULL)""")


def get_exam_plan(user_id):
    ensure_schema()
    with closing(get_connection()) as conn, conn:
        row = conn.execute("SELECT * FROM personal_exam_plan WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def save_exam_plan(user_id, curriculum_id, exam_date, exam_time):
    ensure_schema()
    day = date.fromisoformat(str(exam_date))
    clock = time.fromisoformat(str(exam_time))
    with closing(get_connection()) as conn, conn:
        has_schedule = conn.execute("SELECT 1 FROM sqlite_master WHERE name='mock_exam_schedule'").fetchone()
        if has_schedule and conn.execute(
            "SELECT 1 FROM mock_exam_schedule WHERE user_id=? AND is_active=1 AND scheduled_date>=?",
            (user_id, day.isoformat()),
        ).fetchone():
            raise ValueError("Move or remove mock dates on or after the new exam date before saving it.")
        conn.execute("""INSERT INTO personal_exam_plan VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET curriculum_id=excluded.curriculum_id,
            exam_date=excluded.exam_date, exam_time=excluded.exam_time""",
            (user_id, curriculum_id, day.isoformat(), clock.isoformat()))


def exam_countdown(plan, today=None):
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    if not plan:
        return "—", "Set your appointment in Exam date & countdown"
    day = date.fromisoformat(plan["exam_date"])
    remaining = (day - today).days
    note = f"{day:%b %d, %Y} · {time.fromisoformat(plan['exam_time']):%I:%M %p}"
    return (str(remaining) if remaining > 0 else "Today" if remaining == 0 else "Passed"), note


def visible_metrics(user_id, metrics):
    raw = get_setting(user_id, "archived_practice_metrics")
    try:
        archived = json.loads(raw) if raw else ["Correct", "Incorrect"]
    except (ValueError, TypeError):
        archived = ["Correct", "Incorrect"]
    return [metric for metric in metrics if metric not in archived]


def render_metric_settings(user_id, metrics):
    import streamlit as st
    with st.expander("Manage metrics · archive / restore"):
        st.caption("Uncheck any metric to remove it from the dashboard. Check it again to restore it. Your study records stay saved.")
        with st.form("practice_metric_preferences"):
            selected = st.multiselect("Visible metrics", metrics, default=visible_metrics(user_id, metrics))
            if st.form_submit_button("Save visible metrics"):
                set_setting(user_id, "archived_practice_metrics", json.dumps([m for m in metrics if m not in selected]))
                st.rerun()


def render_exam_settings(user_id, curriculums=None, *, expanded=True):
    import streamlit as st
    if curriculums is None:
        from src.database import get_all_curriculums
        curriculums = get_all_curriculums()
    if not curriculums:
        return
    plan = get_exam_plan(user_id)
    ids = [c['id'] for c in curriculums]
    with st.expander("Exam date & countdown", expanded=expanded):
        st.caption("Save here to update your exam date, time, countdown, and final mock review boundary across Dashboard, Practice Mode, Curriculum, and Mock Review.")
        with st.form("personal_exam_appointment"):
            cid = st.selectbox("Exam curriculum", ids, index=ids.index(plan['curriculum_id']) if plan and plan['curriculum_id'] in ids else 0,
                               format_func=lambda cid: next(c['title'] for c in curriculums if c['id'] == cid))
            day = st.date_input("Actual exam date", value=date.fromisoformat(plan['exam_date']) if plan else None)
            clock = st.time_input("Appointment time (local to your test center)", value=time.fromisoformat(plan['exam_time']) if plan else time(9))
            if st.form_submit_button("Save exam appointment"):
                if day is None:
                    st.error("Choose your exam date.")
                else:
                    try:
                        save_exam_plan(user_id, cid, day, clock)
                        from src.mock_review import sync_mock_reviews
                        sync_mock_reviews(user_id)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.rerun()
