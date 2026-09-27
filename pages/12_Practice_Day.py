"""Dedicated drill-down page linked from the 30-day practice calendar."""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

from src.auth import require_login
from src.utils import page_header, sidebar_nav
from src.practice_calendar import ZONE, duration, percent
from src.practice_day import load_day_records, parse_day
from src.practice_report import render_report, report_rows, summarize

st.set_page_config(page_title='Practice day · StudyForge', page_icon='📅', layout='wide')
user_id = require_login()
sidebar_nav(st.session_state.get('username', ''))
today = datetime.now(ZONE).date()
day = parse_day(st.query_params.get('date'), today)
metric = st.query_params.get('metric', 'accuracy')
st.markdown('<a href="Dashboard" target="_self">← Back to dashboard</a>', unsafe_allow_html=True)
page_header(f'Practice · {day:%A, %B %d, %Y}', 'All courses + external practice · America/New_York')
st.caption('This detail page opens separately so your calendar and dashboard filters stay in the original tab.')
chosen = st.date_input('Explore another day', value=day, max_value=today)
if chosen != day:
    st.query_params['date'] = chosen.isoformat()
    st.rerun()
# Clear drill-down filters when navigating between dates, retaining them on ordinary reruns.
if st.session_state.get('practice_detail_date') != day.isoformat():
    for key in list(st.session_state):
        if key.startswith('drill_filter_') or key in ('drill_record', 'drill_report_metric'):
            del st.session_state[key]
    st.session_state['practice_detail_date'] = day.isoformat()
answers, external, timers = load_day_records(user_id, day)
rows = report_rows(answers, external)
total = sum(r['Total'] for r in rows)
correct = sum(r['Correct'] for r in rows)
seconds = sum(float(r['active_seconds']) for r in timers)
cols = st.columns(4)
cols[0].metric('Total questions', total)
cols[1].metric('Correct / incorrect', f'{correct} / {total - correct}')
cols[2].metric('Daily accuracy', percent(correct / total * 100 if total else None))
cols[3].metric('Active time', duration(seconds))
st.caption('These are the same records used by the calendar. Timed exams are excluded. Active time excludes pauses and external study time. Older answers without submission timestamps use session completion dates.')
if not rows and not timers:
    st.info('No practice activity was recorded for this day.')
render_report(answers, external, timers, 0, day, date_label='Selected day',
              metrics=('Total questions', 'Correct', 'Incorrect', 'Accuracy', 'Active time'))
with st.expander('Explore trailing 7-day accuracy', expanded=metric == 'rolling'):
    window_answers, window_external, _ = load_day_records(user_id, day, days=7)
    window_rows = report_rows(window_answers, window_external)
    window_total = sum(r['Total'] for r in window_rows)
    window_correct = sum(r['Correct'] for r in window_rows)
    st.metric('Trailing 7-day accuracy', percent(window_correct / window_total * 100 if window_total else None))
    st.caption(f'{day - timedelta(days=6):%b %d, %Y} – {day:%b %d, %Y} · {window_correct} correct / {window_total} answered. Question-weighted, including days before the visible calendar when needed.')
    if window_rows:
        st.dataframe(summarize(window_rows, 'Source'), hide_index=True, use_container_width=True)
        st.dataframe(window_rows, hide_index=True, use_container_width=True)
    else:
        st.info('No answers recorded in this seven-day window.')
