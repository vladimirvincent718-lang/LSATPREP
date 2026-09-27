"""Chapter-based flashcard library and personal study workspace."""
import csv
import io
import random
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
import streamlit as st
from src.auth import require_login
from src.course_material_nav import course_material_nav
from src.database import get_course, get_materials
from src.utils import sidebar_nav, require_course, page_header
from src.flashcards import (init_flashcards, seed_cfa, list_decks, get_cards,
                            save_deck, mark_card, draft_cards, extract_text, material_text, starter_data)

st.set_page_config(page_title='Flashcards · StudyForge', page_icon='🗃️', layout='wide')
user_id = require_login()
sidebar_nav(st.session_state.get('username', ''))
course_id = require_course(user_id)
init_flashcards()
seed_cfa(user_id, course_id)
scope = f'fc_{user_id}_{course_id}'
page_header('Flashcards', f"{get_course(course_id)['title']} · A little practice. A lot of progress.")
course_material_nav("flashcards")
st.markdown('''<style>
.fc-banner {background:linear-gradient(115deg,#eef0ff,#f6f5ff);border:1px solid #dfe2ff;
 padding:24px 30px;border-radius:18px;margin:8px 0 24px;color:#25264b}
.fc-eyebrow {font-size:12px;font-weight:750;letter-spacing:1.7px;color:#5962c5;text-transform:uppercase}
.fc-banner h2 {margin:8px 0!important;font-size:28px!important;color:#25264b!important}
.fc-card {min-height:300px;display:flex;flex-direction:column;justify-content:center;align-items:center;
 border:1px solid #dfe2f2;border-bottom:5px solid #6568ef;border-radius:22px;
 background:linear-gradient(155deg,#fff,#f8f8ff);box-shadow:0 12px 34px #25264b0d;
 padding:42px 8%;text-align:center;color:#25264b;margin:14px 0;overflow-wrap:anywhere}
.fc-card .fc-text {font-size:clamp(22px,3vw,34px);line-height:1.5;white-space:pre-wrap;margin:26px 0}
.fc-card small {color:#727690}.fc-answer {border-bottom-color:#26a88d}
@media(max-width:600px){.fc-card{padding:25px 18px;min-height:270px}.fc-banner{padding:20px}}
</style>''', unsafe_allow_html=True)


def editor(cards, key):
    frame = pd.DataFrame(cards, columns=['front', 'back']).fillna('')
    return st.data_editor(frame, num_rows='dynamic', hide_index=True, width='stretch',
                          column_config={'front': st.column_config.TextColumn('Term / question', width='medium'),
                                         'back': st.column_config.TextColumn('Definition / answer', width='large')},
                          key=key).fillna('').to_dict('records')


library, create = st.tabs(['My study sets', '＋ Create a set'])
with create:
    st.subheader('Turn your chapter into a study set')
    st.caption('Extract term–definition pairs from your notes, then review and edit before saving. Sets and progress are private to you.')
    source_type = st.radio('Start with', ['Course material', 'Upload a chapter', 'Paste notes'], horizontal=True, key=scope+'input')
    source = 'Pasted chapter notes'
    raw = ''
    material = None
    upload = None
    if source_type == 'Course material':
        materials = get_materials(course_id)
        if materials:
            material = st.selectbox('Chapter material', materials, format_func=lambda m: (m.get('module_name') or 'Course') + ' · ' + m['title'], key=scope+'material')
            source = material['title']
        else:
            st.info('No course materials yet. Upload a chapter or paste your notes.')
    elif source_type == 'Upload a chapter':
        upload = st.file_uploader('Chapter file', type=['pdf', 'docx', 'txt', 'md', 'tsv'], key=scope+'upload')
        if upload:
            source = upload.name
    else:
        raw = st.text_area('Chapter notes', height=180, placeholder='Duration: Measures sensitivity of bond price to yield changes.\nCurrent yield: Annual coupon / price.', key=scope+'notes')
    if st.button('Generate draft cards', type='primary', key=scope+'generate'):
        try:
            if material:
                raw = material_text(material)
            elif upload:
                raw = extract_text(upload.name, upload.getvalue())
            generated = draft_cards(raw)
            if not generated:
                raise ValueError('Add chapter text with definitions or explanations first.')
            st.session_state[scope+'draft'] = generated
            st.session_state[scope+'source'] = source
            st.session_state[scope+'revision'] = st.session_state.get(scope+'revision', 0) + 1
        except Exception as exc:
            st.error(f'Could not read this material: {exc}')
    if st.button('Start with blank cards', key=scope+'blank'):
        st.session_state[scope+'draft'] = [{'front': '', 'back': ''}]
        st.session_state[scope+'source'] = 'Handwritten study notes'
        st.session_state[scope+'revision'] = st.session_state.get(scope+'revision', 0) + 1
    if scope+'draft' in st.session_state:
        st.caption('Drafts preserve the source wording. Review formulas and rewrite recall prompts as needed. Delete unwanted rows or add your own.')
        title = st.text_input('Set title', value='My chapter flashcards', key=scope+'title')
        edited = editor(st.session_state[scope+'draft'], scope+'draft_editor'+str(st.session_state.get(scope+'revision', 0)))
        if st.button('Save study set', type='primary', key=scope+'save'):
            try:
                saved = save_deck(user_id, course_id, title, st.session_state[scope+'source'], edited)
                st.session_state[scope+'selected'] = saved
                del st.session_state[scope+'draft']
                st.session_state[scope+'notice'] = 'Your study set is saved. Find it in My study sets.'
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if scope+'notice' in st.session_state:
        st.success(st.session_state.pop(scope+'notice'))

with library:
    decks = list_decks(user_id, course_id)
    st.caption(f"{len(decks)} study sets · {sum(d['total'] for d in decks)} cards · {sum(d['known'] for d in decks)} learned")
    search_column, set_column = st.columns([1, 2])
    query = search_column.text_input('Search study sets', placeholder='Find a chapter…', key=scope+'search')
    filtered = [d for d in decks if query.casefold() in d['title'].casefold()]
    if not filtered:
        st.info('No matching sets. Create a set from your chapter materials to get started.')
    else:
        ids = [d['id'] for d in filtered]
        if st.session_state.get(scope+'selected') not in ids:
            st.session_state[scope+'selected'] = ids[0]
        selected = set_column.selectbox('Choose a study set', ids, format_func=lambda i: next(f"{d['title']} · {d['total']} cards" for d in filtered if d['id']==i), key=scope+'selected')
        deck = next(d for d in decks if d['id'] == selected)
        cards = get_cards(user_id, course_id, selected)
        st.subheader(deck['title'])
        st.caption('Source: '+deck['source'])
        chapter_source = next((chapter for chapter in starter_data()['chapters']
                               if deck.get('seed_key') == 'cfa-v1:' + chapter['title']), None)
        if chapter_source and chapter_source.get('coverage_note'):
            with st.expander('Source coverage'):
                st.write(chapter_source['coverage_note'])
        study, terms, edit = st.tabs(['Flashcards', 'Terms in this set', 'Edit set'])
        with study:
            mode = st.radio('Study mode', ['All cards', 'Still learning', 'Starred'], horizontal=True, key=scope+'mode')
            reverse = st.toggle('Show answer first', key=scope+'reverse')
            active = [c for c in cards if mode == 'All cards' or (mode == 'Still learning' and not c['known']) or (mode == 'Starred' and c['starred'])]
            state_key = f'{scope}_{selected}_{mode}_{reverse}'
            available = {c['id']: c for c in active}
            order = st.session_state.get(state_key+'order', [])
            order = [i for i in order if i in available] + [i for i in available if i not in order]
            st.session_state[state_key+'order'] = order
            if not order:
                st.success('All caught up!' if mode == 'Still learning' else 'No starred cards yet. Star cards in All cards to study them here.')
            else:
                idx = st.session_state.get(state_key+'index', 0) % len(order)
                card = available[order[idx]]
                flip_key = state_key+f"flip_{card['id']}"
                flipped = st.session_state.get(flip_key, False)
                answer = flipped != reverse
                st.progress(deck['known']/max(deck['total'], 1), text=f"{deck['known']} of {deck['total']} learned")
                st.markdown(f'<div class="fc-card {"fc-answer" if answer else ""}"><div class="fc-eyebrow">{"Answer" if answer else "Term / question"}</div><div class="fc-text">{escape(card["back"] if answer else card["front"])}</div><small>{idx+1} / {len(order)} · {"Learned" if card["known"] else "Still learning"}</small></div>', unsafe_allow_html=True)
                left, flip, right = st.columns([1, 2, 1])
                def navigate(delta):
                    st.session_state[state_key+'index'] = (idx + delta) % len(order)
                    for i in order:
                        st.session_state[state_key+f'flip_{i}'] = False
                left.button('← Previous', on_click=navigate, args=(-1,), width='stretch', key=state_key+'prev')
                if flip.button('Flip card ↻', type='primary', width='stretch', key=state_key+'flip'):
                    st.session_state[flip_key] = not flipped
                    st.rerun()
                right.button('Next →', on_click=navigate, args=(1,), width='stretch', key=state_key+'next')
                learn, know, star, shuffle = st.columns(4)
                for column, label, field, value in [(learn, '↺ Still learning', 'known', False), (know, '✓ Got it', 'known', True), (star, '★ Starred' if card['starred'] else '☆ Star', 'starred', not card['starred'])]:
                    if column.button(label, width='stretch', key=state_key+field+str(value)):
                        mark_card(user_id, course_id, card['id'], field, value)
                        if field == 'known':
                            navigate(1 if mode == 'All cards' or not value else 0)
                        st.rerun()
                if shuffle.button('⤨ Shuffle', width='stretch', key=state_key+'shuffle'):
                    random.shuffle(order)
                    st.session_state[state_key+'order'] = order
                    st.session_state[state_key+'index'] = 0
                    for i in order:
                        st.session_state[state_key+f'flip_{i}'] = False
                    st.rerun()
        with terms:
            for i, card in enumerate(cards, 1):
                with st.container(border=True):
                    l, r = st.columns([1, 2])
                    l.markdown(f"**{i}. {card['front']}**")
                    r.write(card['back'])
            output = io.StringIO()
            writer = csv.writer(output, delimiter='\t')
            writer.writerows((c['front'], c['back']) for c in cards)
            st.download_button('Export terms (.tsv)', output.getvalue(), file_name='flashcards.tsv', mime='text/tab-separated-values', key=scope+'export')
        with edit:
            new_title = st.text_input('Title', deck['title'], key=f'{scope}_{selected}_edit_title')
            updated = editor(cards, f'{scope}_{selected}_edit_cards')
            st.caption('Progress is retained for unchanged cards. Changed cards start as still learning.')
            if st.button('Save changes', key=f'{scope}_{selected}_update'):
                try:
                    save_deck(user_id, course_id, new_title, deck['source'], updated, deck_id=selected)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
