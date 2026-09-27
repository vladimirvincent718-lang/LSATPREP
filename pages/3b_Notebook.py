"""A personal notebook for explanations worth keeping."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import streamlit as st
from src.auth import require_login
from src.course_material_nav import course_material_nav
from src.database import get_course, get_course_modules
from src.utils import sidebar_nav, require_course, page_header
from src.notebook import init_notebook, list_notes, save_note, delete_note
from src.import_math_text import math_markdown

st.set_page_config(page_title='Notebook · StudyForge', page_icon='📓', layout='wide')
user_id = require_login()
sidebar_nav(st.session_state.get('username', ''))
course_id = require_course(user_id)
init_notebook()
scope = f'notebook_{user_id}_{course_id}_'
page_header('📓 My Notebook', f"{get_course(course_id)['title']} · Keep the explanation that made it click.")
course_material_nav("notebook")
st.caption('Private to you. Write your own notes or paste useful answers from ChatGPT or Gemini. Save them under any chapter or module.')
if scope+'notice' in st.session_state:
    st.success(st.session_state.pop(scope+'notice'))
notes = list_notes(user_id, course_id)
chapters = list(dict.fromkeys([m['name'] for m in get_course_modules(course_id)] +
                            [n['chapter'] for n in notes if n['chapter']]))
requested = st.session_state.pop(f'notebook_open_{course_id}', None)
if requested is not None:
    if requested not in chapters:
        chapters.append(requested)
    st.session_state[scope+'filter'] = requested


def start_editor(note=None, example=False):
    note = note or {}
    st.session_state[scope+'editing'] = note.get('id', 'new')
    st.session_state[scope+'title'] = note.get('title', '')
    st.session_state[scope+'body'] = note.get('body', '')
    st.session_state[scope+'source'] = note.get('source', '')
    st.session_state[scope+'pinned'] = bool(note.get('pinned', False))
    current = st.session_state.get(scope+'filter') or ''
    st.session_state[scope+'chapter'] = note.get('chapter', current)
    if example:
        st.session_state[scope+'title'] = 'Inventory and impairment: MIN vs. MAX'
        st.session_state[scope+'chapter'] = next((c for c in chapters if 'financial statement' in c.lower() or c.upper() == 'FSA'), 'Financial Statement Analysis')
        st.session_state[scope+'source'] = 'ChatGPT explanation saved from my study conversation'
        st.session_state[scope+'body'] = (ROOT / 'data/notebook/fsa_min_max.md').read_text(encoding='utf-8-sig')


# Keep the editor separate from library controls so filtering cannot discard a draft.
if scope+'editing' in st.session_state:
    editing = st.session_state[scope+'editing']
    st.subheader('New note' if editing == 'new' else 'Edit note')
    title = st.text_input('Note title', key=scope+'title', placeholder='The explanation I want to remember')
    editor_chapters = list(dict.fromkeys([''] + chapters + [st.session_state[scope+'chapter']]))
    chapter = st.selectbox('Chapter / module', editor_chapters, key=scope+'chapter',
                           format_func=lambda c: c or 'General course notes', accept_new_options=True)
    source = st.text_input('Source / conversation link (optional)', key=scope+'source')
    body = st.text_area('Notes', key=scope+'body', height=390,
                        placeholder='Paste or write here. Markdown tables, headings, lists, and LaTeX formulas are supported.')
    st.caption('Use the chat answer’s Copy button to preserve Markdown tables. Click outside the editor to refresh the preview. Changes are saved only when you choose Save note.')
    pinned = st.checkbox('Pin for quick reference', key=scope+'pinned')
    with st.expander('Preview formatting', expanded=True):
        if body:
            st.markdown(math_markdown(body))
        else:
            st.caption('Your formatted note will appear here.')
    save_col, cancel_col = st.columns(2)
    if save_col.button('Save note', type='primary'):
        try:
            save_note(user_id, course_id, title, body, chapter or '', source, pinned,
                      note_id=None if editing == 'new' else editing)
            del st.session_state[scope+'editing']
            st.session_state[scope+'notice'] = 'Note saved to your notebook.'
            st.session_state[scope+'filter'] = chapter or ''
            st.session_state[scope+'search'] = ''
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if cancel_col.button('Discard changes'):
        del st.session_state[scope+'editing']
        st.rerun()
    st.stop()

left, right = st.columns([2, 1])
query = left.text_input('Search notes', key=scope+'search', placeholder='Search titles, explanations, or formulas…')
chapter_filter = right.selectbox('Chapter / module', [None, ''] + chapters,
    format_func=lambda c: 'All chapters' if c is None else c or 'General course notes', key=scope+'filter')
if st.button('＋ New note', type='primary'):
    start_editor()
    st.rerun()
course = get_course(course_id)
if 'cfa' in (course['title'] + ' ' + (course.get('category') or '')).lower():
    if st.button('Use FSA example: inventory MIN / MAX'):
        start_editor(example=True)
        st.rerun()
filtered = list_notes(user_id, course_id, query, chapter_filter)
st.caption(f'{len(filtered)} of {len(notes)} notes · Pinned notes appear first')
if not filtered:
    st.info('No notes match yet. Create a note for this chapter or try a different search.')
for note in filtered:
    nid = note['id']
    with st.expander(('📌 ' if note['pinned'] else '') + note['title']):
        st.caption(f"{note['chapter'] or 'General course notes'} · Saved {note['updated_at']} UTC")
        if note['source']:
            st.text('Source: ' + note['source'])
        if note.get('question_id') is not None:
            st.caption('Linked to your practice question notes. Edits here also appear on the question.')
        st.markdown(math_markdown(note['body']))
        edit_col, pin_col, export_col = st.columns(3)
        if edit_col.button('Edit note', key=f'{scope}edit_{nid}'):
            start_editor(note)
            st.rerun()
        if pin_col.button('Unpin' if note['pinned'] else 'Pin', key=f'{scope}pin_{nid}'):
            save_note(user_id, course_id, note['title'], note['body'], note['chapter'],
                      note['source'], not note['pinned'], note_id=nid)
            st.rerun()
        export_col.download_button('Download Markdown', note['body'], file_name=f'note-{nid}.md',
                                   mime='text/markdown', key=f'{scope}export_{nid}')
        with st.popover('Delete note'):
            st.caption('Permanently delete this saved note?' if note.get('question_id') is None
                       else 'Delete this note from both your notebook and the practice question?')
            if st.button('Delete permanently', key=f'{scope}delete_{nid}'):
                delete_note(user_id, course_id, nid)
                st.session_state[scope+'notice'] = 'Note deleted.'
                st.rerun()
