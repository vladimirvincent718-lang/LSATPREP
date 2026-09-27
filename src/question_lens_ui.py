"""Shared lens definitions and manual question assignments."""
import pandas as pd
import streamlit as st

from src.database import get_all_questions
from src.question_lenses import get_lenses, question_lens, save_lens, set_question_lenses


def render_lens_manager(course_id, course_title):
    lenses = get_lenses()
    st.subheader('Manage lenses')
    st.caption('This shared list is used in Practice Mode, batch imports, and question filters. Renaming a lens preserves its question assignments.')
    with st.form('lens_definition'):
        selected = st.selectbox('Lens to edit', ['new', *lenses], format_func=lambda key: 'Create a new lens' if key == 'new' else lenses[key])
        name = st.text_input('Lens name', help='Enter a new name to create a lens, or the replacement name for the selected lens.')
        if st.form_submit_button('Save lens'):
            try:
                save_lens(name, None if selected == 'new' else selected)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun()
    st.subheader(f'Assign questions · {course_title}')
    questions = get_all_questions(course_id=course_id)
    # Search across source lenses so questions can be moved to the top-selected target.
    current = 'all'
    query = st.text_input('Find questions to assign', key=f'lens_search_{course_id}')
    matching = [q for q in questions if (current == 'all' or question_lens(q) == current)
                and (not query.strip() or query.casefold() in f"{q['id']} {q['question_id']} {q['stimulus']}".casefold())]
    st.caption(f'{len(matching)} matching questions')
    if not matching:
        st.info('No questions match. Choose All lenses to find questions to move into this lens.')
        return
    by_id = {q['id']: q for q in matching}
    chosen = st.multiselect('Questions to update', list(by_id),
        format_func=lambda qid: f"#{qid} · {by_id[qid]['stimulus'][:110]}", key=f'lens_assign_ids_{course_id}')
    if chosen:
        st.dataframe(pd.DataFrame([{'Bank #': qid, 'Question': by_id[qid]['stimulus'],
            'Current lens': lenses.get(question_lens(by_id[qid]), question_lens(by_id[qid]))} for qid in chosen]), hide_index=True)
    target = st.session_state.get('b_lens', 'all')
    st.caption('Assignment target: the Question lens selected at the top of the page.')
    if st.button('Update selected questions', disabled=not chosen or target not in lenses, key=f'lens_assign_save_{course_id}'):
        count = set_question_lenses(course_id, chosen, target)
        st.session_state[f'lens_saved_{course_id}'] = f'Updated {count} questions to {lenses[target]}.'
        st.rerun()
    notice = st.session_state.pop(f'lens_saved_{course_id}', None)
    if notice:
        st.success(notice)
