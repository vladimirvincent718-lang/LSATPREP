"""Shared answer-key dashboard for course and question-bank management."""
import pandas as pd
import sqlite3
import streamlit as st
from src import database
from src.answer_key import counts, load_questions, make_preview, commit_preview, fingerprint, distribution_health


def render_answer_key(course_ids, user_id, key='answer_key'):
    st.subheader('Answer-key distribution')
    st.caption('Counts cover all active questions in the selected courses, including questions outside the browse filters.')
    rows = load_questions(course_ids)
    current = counts(rows)
    st.write(f"**{len(rows):,} questions** · {sum(current.values()):,} A–E answers")
    preview_key = key + '_preview'
    if st.session_state.get(key+'_notice'):
        st.success(st.session_state.pop(key+'_notice'))
    preview = st.session_state.get(preview_key)
    bank_fingerprint = fingerprint(rows)
    if preview and (preview['course_ids'] != list(course_ids) or preview['fingerprint'] != bank_fingerprint):
        st.session_state.pop(preview_key, None)
        st.session_state.pop(key+'_question', None)
        preview = None
    setting = 'answer_key_tolerance_pp'
    tolerance_key = key + '_tolerance'
    if tolerance_key not in st.session_state:
        saved = database.get_setting(user_id, setting)
        st.session_state[tolerance_key] = float(saved) if saved else 5.0
    def save_tolerance():
        database.set_setting(user_id, setting, st.session_state[tolerance_key])
    tolerance = st.number_input('Allowed deviation (percentage points)', min_value=0.0,
                               max_value=50.0, step=1.0, key=tolerance_key, on_change=save_tolerance)
    st.caption('Automatically checked whenever this page loads or updates. Target: equal shares among available choices '
               '(25% each for A–D; 20% each for A–E). A tolerance of 5 allows 20–30% for A–D. '
               'Groups with fewer than 20 valid questions are not flagged. Your tolerance is saved for future visits.')
    health = distribution_health(rows, tolerance)
    check_token = (bank_fingerprint, tuple(course_ids), tolerance)
    if health['breaches']:
        worst = max(health['breaches'], key=lambda item: item['Deviation (pp)'])
        st.warning(f"Answer-key imbalance: {worst['Answer']} is {worst['Current %']:.1f}% of "
                   f"{worst['Choices']} answers (target {worst['Target %']:.1f}%, "
                   f"tolerance ±{tolerance:g} points). Review and apply a balanced shuffle below.")
        if not preview and st.session_state.get(key+'_auto_checked') != check_token:
            preview = make_preview(rows, course_ids, balanced=True)
            st.session_state[preview_key] = preview
            st.session_state.pop(key+'_question', None)
        st.session_state[key+'_auto_checked'] = check_token
        if preview and preview['method'] == 'Evenly balanced':
            st.info('A balanced shuffle preview is ready. Choose “Commit this shuffle” to apply the adjustment.')
    elif health['checked']:
        st.success('Answer-key distribution is within your tolerance. No adjustment is needed.')
    else:
        st.info('Automatic checks need at least 20 valid questions with the same available choices.')
    if health['excluded']:
        st.caption(f"{health['excluded']:,} written-response or invalid answer keys excluded from the tolerance check.")
    if health['details']:
        with st.expander('Tolerance check details'):
            st.dataframe(pd.DataFrame(health['details']).round(2), hide_index=True, use_container_width=True)
    mode = st.radio('Shuffle method', ['Random shuffle', 'Evenly balanced'], horizontal=True, key=key+'_mode')
    st.caption('Random shuffle gives a new allocation each time. Evenly balanced spreads correct letters as evenly as possible among questions with the same available choices.')
    def generate():
        st.session_state[preview_key] = make_preview(rows, course_ids, balanced=st.session_state[key+'_mode'] == 'Evenly balanced')
        st.session_state.pop(key+'_question', None)
    st.button('Try again' if preview else 'Generate shuffle preview', key=key+'_generate', disabled=not rows, on_click=generate)
    data = [{'Answer':c, 'Current':current[c], **({'Proposed':preview['after'][c]} if preview else {})} for c in 'ABCDE']
    st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)
    st.bar_chart(pd.DataFrame(data).set_index('Answer'))
    if not preview:
        return
    st.info(f"{preview['method']} preview: {len(preview['edits']):,} questions eligible. Nothing is saved until you commit.")
    if preview['skipped']:
        st.warning(f"{len(preview['skipped'])} questions stay unchanged because their choices cannot safely be shuffled.")
        st.dataframe(pd.DataFrame(preview['skipped']), hide_index=True)
    proposed = {e['before']['id']: e['after'] for e in preview['edits']}
    if distribution_health([proposed.get(q['id'], q) for q in rows], tolerance)['breaches']:
        st.warning('This preview still exceeds your tolerance. Unshufflable questions or the chosen shuffle '
                   'may prevent reaching the target. Review the proposed totals before applying.')
    with st.expander('Review proposed choice order'):
        edits = preview['edits']
        if edits:
            index = st.selectbox('Preview question', range(len(edits)), format_func=lambda i: str(edits[i]['before'].get('question_id', edits[i]['before']['id'])), key=key+'_question')
            edit = edits[index]
            st.write(edit['before']['stimulus'])
            st.dataframe(pd.DataFrame([{'Letter':c, 'Current choice':edit['before'].get('choice_'+c.lower(),''), 'Proposed choice':edit['after'].get('choice_'+c.lower(),'')} for c in 'ABCDE']), hide_index=True)
            st.write(f"Correct answer: {edit['before']['correct_answer']} → {edit['after']['correct_answer']}")
    left, right = st.columns(2)
    if left.button('Commit this shuffle', type='primary', key=key+'_commit', disabled=not preview['edits']):
        try:
            n = commit_preview(preview,user_id)
        except (ValueError, sqlite3.Error) as exc:
            st.error(str(exc))
        else:
            st.session_state.pop(preview_key,None)
            st.session_state[key+'_notice'] = f'Saved the proposed answer order for {n:,} questions.'
            st.rerun()
    def discard():
        st.session_state.pop(preview_key,None)
    right.button('Discard preview', key=key+'_discard', on_click=discard)
