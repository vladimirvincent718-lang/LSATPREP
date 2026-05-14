"""
pages/1_Dashboard.py — Course-aware Dashboard with KPIs and charts.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.express as px
import pandas as pd

from src.auth      import require_login
from src.utils     import page_header, sidebar_nav, course_selector
from src.analytics import get_dashboard_stats
from src.database  import get_course_question_count, get_materials, get_material_progress

st.set_page_config(page_title="Dashboard · StudyForge", page_icon="📊", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
course_id = course_selector(user_id)

if course_id is None:
    page_header("📊 Dashboard", "Your performance at a glance")
    st.info("Choose an active course from the sidebar to start tracking your progress.")
    st.stop()

from src.database import get_course
course = get_course(course_id)
course_title = course["title"] if course else "Unknown Course"

page_header("📊 Dashboard", f"Course: {course_title}")

stats   = get_dashboard_stats(user_id, course_id=course_id)
q_count = get_course_question_count(course_id)

# Materials completion summary
materials = get_materials(course_id)
progress  = get_material_progress(user_id, course_id)
m_total     = len(materials)
m_completed = sum(1 for m in materials if progress.get(m["id"]) == "Completed")
m_pct       = round(m_completed / m_total * 100) if m_total else 0

# ── Top KPI row ───────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Questions in Bank", q_count)
k2.metric("Sessions Completed", stats["total_attempts"])
k3.metric("Total Qs Answered", stats["total_questions"])

if stats["latest_percent"] is not None:
    delta = None
    if stats["improvement_trend"] is not None:
        delta = f"{stats['improvement_trend']:+.1f}% trend"
    k4.metric("Latest Score", f"{stats['latest_percent']}%", delta=delta)
    k5.metric("Best Score",   f"{stats['best_percent']}%")
    k6.metric("Avg Score",    f"{stats['avg_percent']}%")
else:
    k4.metric("Latest Score", "—")
    k5.metric("Best Score",   "—")
    k6.metric("Avg Score",    "—")

# Materials progress bar
if m_total > 0:
    st.progress(m_pct / 100,
                text=f"📖 Materials: {m_completed}/{m_total} completed ({m_pct}%)")

st.divider()

if stats["total_attempts"] == 0:
    st.info(
        f"No sessions completed for **{course_title}** yet. "
        "Head to **Practice Mode** or **Timed Exam** to get started."
    )
    st.stop()

# ── Score trend + weak areas ──────────────────────────────────────────────────
col_left, col_right = st.columns([3, 2])

with col_left:
    st.markdown("### Score Trend")
    trend_df = stats["score_trend"]
    if not trend_df.empty:
        fig = px.line(
            trend_df, x="completed_at", y="percent_correct", color="mode",
            markers=True,
            labels={"completed_at": "Date", "percent_correct": "% Correct", "mode": "Mode"},
        )
        fig.update_layout(yaxis_range=[0, 100], margin=dict(l=0, r=0, t=10, b=0),
                          legend_title_text="")
        fig.add_hline(y=75, line_dash="dot", line_color="orange",
                      annotation_text="75% target")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Not enough data yet.")

with col_right:
    st.markdown("### ⚠️ Weak Areas")
    weak = stats["weak_areas"]
    if weak:
        for w in weak:
            pct   = w["percent"]
            color = "🔴" if pct < 50 else "🟡" if pct < 70 else "🟢"
            st.markdown(
                f"{color} **{w['question_type']}** — "
                f"{pct}% correct ({w['correct']}/{w['total']})"
            )
    else:
        st.caption("Answer at least 3 questions of each type to see weak areas.")

st.divider()

# ── Accuracy breakdown ────────────────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.markdown("### Accuracy by Question Type")
    acc_type = stats["accuracy_by_type"]
    if acc_type:
        df_type = pd.DataFrame([
            {"Question Type": qt, "% Correct": v["pct"], "Answered": v["total"]}
            for qt, v in acc_type.items()
        ]).sort_values("% Correct")
        fig2 = px.bar(
            df_type, x="% Correct", y="Question Type", orientation="h",
            color="% Correct",
            color_continuous_scale=["#d73027", "#fee090", "#1a9850"],
            range_color=[0, 100], text="% Correct",
        )
        fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0), coloraxis_showscale=False)
        fig2.update_traces(texttemplate="%{text:.0f}%", textposition="inside")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.caption("No data yet.")

with col_b:
    st.markdown("### Accuracy by Difficulty")
    acc_diff = stats["accuracy_by_diff"]
    if acc_diff:
        diff_labels = {1: "Easy", 2: "Med-Easy", 3: "Medium", 4: "Hard", 5: "Brutal"}
        df_diff = pd.DataFrame([
            {"Difficulty": diff_labels.get(d, str(d)),
             "% Correct": v["pct"], "_order": d}
            for d, v in acc_diff.items()
        ]).sort_values("_order")
        fig3 = px.bar(
            df_diff, x="Difficulty", y="% Correct",
            color="% Correct",
            color_continuous_scale=["#d73027", "#fee090", "#1a9850"],
            range_color=[0, 100], text="% Correct",
        )
        fig3.update_layout(yaxis_range=[0, 100],
                           margin=dict(l=0, r=0, t=10, b=0),
                           coloraxis_showscale=False)
        fig3.update_traces(texttemplate="%{text:.0f}%", textposition="inside")
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.caption("No data yet.")
