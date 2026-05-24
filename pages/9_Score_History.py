"""
pages/9_Score_History.py — Score history filtered by active course.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.express as px
import pandas as pd
import io

from src.auth      import require_login
from src.utils     import page_header, sidebar_nav, require_course
from src.ui_theme  import apply_plotly_theme
from src.analytics import get_score_history
from src.database  import get_attempt_answers, get_course

st.set_page_config(page_title="Score History · StudyForge", page_icon="📈", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

from src.utils import course_selector
course_id    = require_course(user_id)
course       = get_course(course_id)
course_title = course["title"] if course else "Unknown"

page_header("📈 Score History", f"Every session for: {course_title}")

df = get_score_history(user_id, course_id=course_id)

if df.empty:
    st.info(
        f"No completed sessions yet for **{course_title}**. "
        "Complete a practice session or timed exam to see your history here."
    )
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("Sessions",         len(df))
k2.metric("Avg % Correct",    f"{df['% Correct'].mean():.1f}%")
k3.metric("Best % Correct",   f"{df['% Correct'].max():.1f}%")
k4.metric("Latest % Correct", f"{df.iloc[0]['% Correct']:.1f}%")

st.divider()

# ── Score trend ───────────────────────────────────────────────────────────────
st.markdown("### Score Trend")
chart_df = df[["Date", "% Correct", "Mode"]].copy().sort_values("Date")
fig = px.line(
    chart_df, x="Date", y="% Correct", color="Mode",
    markers=True, labels={"Date": "Date", "% Correct": "% Correct"},
)
fig.update_layout(yaxis_range=[0, 100], margin=dict(l=0, r=0, t=20, b=0))
apply_plotly_theme(fig)
fig.add_hline(y=75, line_dash="dot", line_color="orange", annotation_text="75% target")
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Mode breakdown + distribution ────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.markdown("### Sessions by Mode")
    mode_counts = df["Mode"].value_counts().reset_index()
    mode_counts.columns = ["Mode", "Count"]
    fig2 = px.pie(mode_counts, names="Mode", values="Count", hole=0.4)
    fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    apply_plotly_theme(fig2)
    st.plotly_chart(fig2, use_container_width=True)

with col_b:
    st.markdown("### Score Distribution")
    fig3 = px.histogram(df, x="% Correct", nbins=10,
                        labels={"% Correct": "% Correct", "count": "Sessions"})
    fig3.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    apply_plotly_theme(fig3)
    st.plotly_chart(fig3, use_container_width=True)

st.divider()

# ── Full table ────────────────────────────────────────────────────────────────
st.markdown("### All Sessions")
display_df = df.drop(columns=["attempt_id"]).copy()
display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
st.dataframe(display_df, use_container_width=True, hide_index=True)

st.divider()

# ── Export ────────────────────────────────────────────────────────────────────
col_e1, col_e2 = st.columns(2)
with col_e1:
    csv_data = display_df.to_csv(index=False)
    st.download_button(
        "⬇️ Export as CSV",
        data=csv_data,
        file_name=f"score_history_{course_title.replace(' ','_')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with col_e2:
    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            display_df.to_excel(writer, index=False, sheet_name="Score History")
        st.download_button(
            "⬇️ Export as Excel",
            data=buf.getvalue(),
            file_name=f"score_history_{course_title.replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except ImportError:
        st.caption("Install openpyxl for Excel export.")

st.divider()

# ── Session drill-down ────────────────────────────────────────────────────────
st.markdown("### Drill Into a Session")

session_options = {
    row["attempt_id"]: f"{row['Date']}  ·  {row['Mode']}  ·  {row['% Correct']:.0f}%"
    for _, row in df.iterrows()
}
chosen = st.selectbox(
    "Select session:", list(session_options.keys()),
    format_func=lambda x: session_options[x],
)

if chosen:
    ans_rows = get_attempt_answers(chosen)
    if ans_rows:
        from src.scoring import compute_score
        report = compute_score(ans_rows)
        c1, c2, c3 = st.columns(3)
        c1.metric("Correct",    f"{report['correct']} / {report['total']}")
        c2.metric("% Correct",  f"{report['percent_correct']}%")
        c3.metric("Est. Scaled", report.get("scaled_score") or "—")

        if report.get("by_question_type"):
            rows_type = [
                {"Type": qt, "Correct": v["correct"],
                 "Total": v["total"], "% Correct": v["percent"]}
                for qt, v in sorted(
                    report["by_question_type"].items(),
                    key=lambda x: x[1]["percent"],
                )
            ]
            st.dataframe(pd.DataFrame(rows_type), use_container_width=True, hide_index=True)
    else:
        st.caption("No detailed answers found for this session.")
