"""Isolated browser fixture: no login, database, or user's exam state."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import streamlit as st
from src.practice_allocation_editor import editor_config, render_allocation_editor

st.set_page_config(layout='wide')
st.session_state['page_runs'] = st.session_state.get('page_runs', 0) + 1
st.caption(f"Full page runs: {st.session_state['page_runs']}")
st.subheader('Question allocation')
total = st.number_input('Total questions', min_value=1, max_value=40, value=20)
questions = [
    {'id': index * 20 + i, 'course_id': cid, 'section_type': name, 'difficulty': 5}
    for index, (cid, name) in enumerate([(1, 'Module 1'), (1, 'Module 2'), (2, 'Chapter 1'), (2, 'Chapter 2')])
    for i in range(20)
]
config = editor_config([1, 2], {1: 'CFA Equity', 2: 'CCRN'}, questions, total)
counts, error = render_allocation_editor(config, questions, {5: total})
if st.button('Start Practice Exam'):
    if error:
        st.error(error)
    else:
        st.success(f"Exam ready: {sum(counts.values())} questions")
        st.json({f'{cid}/{module}': n for (cid, module), n in counts.items()})
