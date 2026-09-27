"""Persistent practice focus derived from a learner's scheduled mock reviews."""

import json
import re
from datetime import date

from src.database import get_connection
from src.mock_review import (
    get_mock_review_items, get_mock_schedule, get_review_module_plan, sync_mock_reviews,
)


CONTENT_MODE_SETTING = "practice_content_mode"
AUTO_REVIEW_SETTING = "practice_auto_review_schedule"
REVIEW_ID_SETTING = "practice_review_schedule_id"


def scheduled_review(schedule, today=None):
    """Advance on each scheduled date; keep the final review after the last mock."""
    today = today or date.today()
    ordered = sorted(schedule, key=lambda row: (row["scheduled_date"], row["id"]))
    eligible = [row for row in ordered if date.fromisoformat(row["scheduled_date"]) <= today]
    return eligible[-1] if eligible else next(iter(ordered), None)


def topic_key(value):
    value = " ".join(str(value or "").casefold().split())
    # Older plans use bare titles; newer banks include the numbered module prefix.
    return re.sub(r"^(?:learning module|module|chapter|reading)\s+\d+\s*[:.\-–—]\s*", "", value)


def review_topics(user_id, mock_id):
    """Combine the saved review items with fresh misses, even for a manual plan."""
    owned = next((row for row in get_mock_schedule(user_id) if row["id"] == mock_id), None)
    if owned is None:
        return []
    plan = get_review_module_plan(user_id, mock_id)
    items = (list(plan["selection_items"]) if plan["configured"] else
             [row for row in get_mock_review_items(user_id, status="all")
              if row["mock_schedule_id"] == mock_id])
    attempt_ids = json.loads(owned.get("matched_attempt_ids_json") or "[]")
    if attempt_ids:
        conn = get_connection()
        try:
            placeholders = ",".join("?" for _ in attempt_ids)
            items.extend(dict(row) for row in conn.execute(
                f"""SELECT DISTINCT q.course_id,
                       COALESCE(NULLIF(TRIM(q.section_type), ''),
                                NULLIF(TRIM(q.question_type), ''), 'General Review') AS topic_name
                    FROM user_answers ua
                    JOIN questions q ON q.id = ua.question_id
                    JOIN exam_attempts ea ON ea.id = ua.attempt_id
                    WHERE ea.user_id = ? AND ea.completed_at IS NOT NULL
                      AND ea.id IN ({placeholders}) AND COALESCE(ua.is_correct, 0) = 0""",
                [int(user_id), *attempt_ids],
            ))
        finally:
            conn.close()
    topics = {}
    for item in items:
        if item.get("course_id") is None:
            continue
        key = topic_key(item.get("match_topic_key") or item["topic_name"])
        topics[(int(item["course_id"]), key)] = {
            "course_id": int(item["course_id"]), "key": key, "name": item["topic_name"],
        }
    return [topics[key] for key in sorted(topics)]


def matches_review_topic(question, topic):
    if question.get("course_id") != topic["course_id"]:
        return False
    names = (question.get("section_type"), question.get("practice_module_label"))
    if not any(names):
        names = (question.get("question_type") or "General Review",)
    return topic["key"] in {topic_key(name) for name in names if name}


def filter_review_questions(questions, topics):
    # An empty plan deliberately produces an empty pool, never all courses.
    return [question for question in questions
            if any(matches_review_topic(question, topic) for topic in topics)]


def render_review_focus(user_id, settings):
    """Render setup-only controls. Save preferences immediately, before exam start."""
    import streamlit as st
    from src.database import set_setting
    from src.mock_review_ui import review_link

    sync_mock_reviews(user_id)
    schedule = get_mock_schedule(user_id)
    if AUTO_REVIEW_SETTING not in st.session_state:
        st.session_state[AUTO_REVIEW_SETTING] = settings.get(AUTO_REVIEW_SETTING) == "true"
    automatic = st.toggle(
        "Automatically follow my review schedule", key=AUTO_REVIEW_SETTING,
        help="Remember this choice. Switch reviews on each scheduled mock date and refresh topics from its results.",
    )
    if automatic != (settings.get(AUTO_REVIEW_SETTING) == "true"):
        set_setting(user_id, AUTO_REVIEW_SETTING, str(automatic).lower())
    if not schedule:
        st.info("Add mock dates and review modules in Mock Review to use this filter.")
        st.markdown(review_link("Open Mock Review"), unsafe_allow_html=True)
        return {"id": None, "topics": [], "signature": ("review", None)}

    ids = [row["id"] for row in schedule]
    labels = {row["id"]: f"{row['mock_label'].replace('Mock ', 'Mock Review ')} · {row['scheduled_date']}"
              for row in schedule}
    current = scheduled_review(schedule)
    try:
        saved_id = int(settings.get(REVIEW_ID_SETTING, ""))
    except (TypeError, ValueError):
        saved_id = None
    if st.session_state.get(REVIEW_ID_SETTING) not in ids:
        st.session_state[REVIEW_ID_SETTING] = saved_id if saved_id in ids else current["id"]
    if automatic:
        st.session_state[REVIEW_ID_SETTING] = current["id"]
    selected_id = st.selectbox("Review to practice", ids, format_func=labels.get,
                               key=REVIEW_ID_SETTING, disabled=automatic)
    if str(selected_id) != settings.get(REVIEW_ID_SETTING):
        set_setting(user_id, REVIEW_ID_SETTING, str(selected_id))
    if automatic:
        next_mock = next((row for row in schedule if row["scheduled_date"] > date.today().isoformat()), None)
        if next_mock and next_mock["id"] != selected_id:
            st.caption(f"Next switch: {labels[next_mock['id']]}. Updates when Practice Mode loads or refreshes.")
        elif date.fromisoformat(current["scheduled_date"]) > date.today():
            st.caption("Your first review is selected ahead of its scheduled date.")
        else:
            st.caption("This is the final scheduled review. It stays selected until you add another mock.")
    st.caption("Uses this review's planned modules and weaknesses from its mock results. Narrow the courses and modules below for this practice exam.")
    st.markdown(review_link("Manage mock dates and review materials"), unsafe_allow_html=True)
    st.button("Refresh review focus", key="practice_refresh_review_focus")
    topics = review_topics(user_id, selected_id)
    if not topics:
        st.info("This review has no modules yet. Save a plan in Mock Review or complete its scheduled mock to detect weaknesses.")
    return {
        "id": selected_id, "topics": topics,
        "signature": ("review", selected_id, tuple((t["course_id"], t["key"]) for t in topics)),
    }
