"""Waveform component with server-side persistence on each telemetry batch."""
from pathlib import Path
import streamlit as st
from streamlit import runtime
from streamlit.runtime.scriptrunner import get_script_run_ctx
import streamlit.components.v2 as components
from src import audio_study as store
from src.audio_transcription import queue_transcription, transcription_state
from src import audio_tutors as tutors
from src.audio_attachments import media_for_marks
from src.audio_music import media_tracks

_JS = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')


def rerun_player():
    ctx=get_script_run_ctx()
    st.rerun(scope='fragment' if ctx and ctx.fragment_ids_this_run else 'app')


@st.fragment(run_every=3)
def render_player(user_id, course_id, audio, music_tracks=None):
    player = components.component('study_audio_player', js=_JS)
    key = f"audio_player_{user_id}_{course_id}_{audio['id']}"
    # Keep at most one selected recording per session; authorization is rechecked
    # even when bytes are cached, so withdrawn invitations cannot reuse them.
    with store.connection() as conn:
        store._accessible(conn, user_id, course_id, audio['id'])
    for cached_key in list(st.session_state):
        if cached_key.startswith('audio_player_') and cached_key.endswith('_bytes') and cached_key != key+'_bytes':
            del st.session_state[cached_key]
    if key+'_bytes' not in st.session_state:
        try:
            st.session_state[key+'_bytes'] = store.audio_bytes(user_id,course_id,audio['id'])
        except (ValueError, OSError, ImportError) as exc:
            st.error(str(exc) if not isinstance(exc, ImportError) else 'Install the Google Drive dependencies before playback.')
            return
    # Use Streamlit's media endpoint rather than resending a 50 MB base64 blob
    # with every progress acknowledgment.
    src=runtime.get_instance().media_file_mgr.add(st.session_state[key+'_bytes'],audio['mime'],key)
    queue_transcription(user_id,course_id,audio['id'])
    transcription = transcription_state(user_id,course_id,audio['id'])
    text=store.transcript(user_id,course_id,audio['id'])
    completion = store.completion(user_id,course_id,audio['id'])
    previous_completion = st.session_state.get(key+'_completed')
    st.session_state[key+'_completed'] = completion['completed']
    if previous_completion is not None and previous_completion != completion['completed']:
        st.rerun(scope='app')
    marks=media_for_marks(user_id,course_id,audio['id'],store.marks(user_id,course_id,audio['id']),st.session_state.get(key+'_attachment_pages',{}))
    result = player(key=key, data={'src':src,
                     'music_tracks':media_tracks(user_id,music_tracks) if music_tracks else [],
                     'music_scope':str(user_id),
                     'transcription':transcription,
                     'completion':completion,
                     'completion_result':st.session_state.get(key+'_completion_result'),
                     'transcript':text,
                     'transcript_exports':{'plain':tutors.transcript_export(text,transcription['words'],False),
                                           'timed':tutors.transcript_export(text,transcription['words'],True)},
                     'manual_tutors':True,
                     'tutor_profiles':tutors.profiles(user_id),
                     'tutor_reply_result':st.session_state.get(key+'_tutor_reply_result'),
                     'help_result':st.session_state.get(key+'_help_result'),
                     'focus_root':st.session_state.get(f'tutor_focus_{user_id}_{course_id}'),
                     'play_count':store.play_count(user_id,course_id,audio['id']),
                     'marks':marks,
                     'highlights':store.highlights(user_id,course_id,audio['id']),
                     'highlight_result':st.session_state.get(key+'_highlight_result'),
                     'progress':store.progress(user_id,course_id,audio['id']),
                     'ack':st.session_state.get(key+'_ack'),
                     'delete_result':st.session_state.get(key+'_delete_result'),
                     'note_result':st.session_state.get(key+'_note_result')},
                     default={'events':[], 'note':None, 'delete_note':None, 'completion_change':None, 'highlight_change':None, 'help_change':None, 'tutor_reply':None, 'attachment_page':None}, on_events_change=lambda:None,
                     on_note_change=lambda:None, on_delete_note_change=lambda:None, on_completion_change_change=lambda:None,
                     on_highlight_change_change=lambda:None, on_help_change_change=lambda:None, on_tutor_reply_change=lambda:None, on_attachment_page_change=lambda:None)
    changed = False
    ack = st.session_state.get(key+'_ack') or {}
    for event in result.events or []:
        if ack.get('session') == event['session'] and event['sequence'] <= ack.get('sequence',-1):
            continue
        store.record_event(user_id,course_id,audio['id'],event)
        ack = {'session':event['session'],'sequence':event['sequence']}
        st.session_state[key+'_ack'] = ack
        changed = True
    note = result.note
    if note and note['id'] != (st.session_state.get(key+'_note_result') or {}).get('id'):
        response = {'id':note['id']}
        try:
            store.save_mark(user_id,course_id,audio['id'],float(note['start']),float(note['end']),
                            note['text'],note['status'],submission_id=note['id'],parent_id=note.get('parent_id'),quote=note.get('quote',''),attachments=note.get('attachments',[]))
        except ValueError as exc:
            response['error'] = str(exc)
        st.session_state[key+'_note_result'] = response
        changed = True
    highlight = result.highlight_change
    if highlight and highlight['id'] != (st.session_state.get(key+'_highlight_result') or {}).get('id'):
        response = {'id':highlight['id']}
        try:
            if highlight.get('delete_id'):
                store.delete_highlight(user_id,course_id,audio['id'],highlight['delete_id'])
            else:
                store.save_highlight(user_id,course_id,audio['id'],float(highlight['start']),float(highlight['end']),highlight['quote'],highlight['id'])
        except (ValueError, TypeError) as exc:
            response['error'] = str(exc)
        st.session_state[key+'_highlight_result'] = response
        changed = True
    help_change=result.help_change
    tutor_reply=result.tutor_reply
    if tutor_reply and tutor_reply['id'] != (st.session_state.get(key+'_tutor_reply_result') or {}).get('id'):
        response={'id':tutor_reply['id']}
        try:
            tutors.save_manual_reply(user_id,course_id,audio['id'],int(tutor_reply['parent_id']),tutor_reply['provider'],tutor_reply['text'],tutor_reply['id'])
        except (ValueError,TypeError,KeyError) as exc:
            response['error']=str(exc)
        st.session_state[key+'_tutor_reply_result']=response
        changed=True
    if help_change and help_change['id'] != (st.session_state.get(key+'_help_result') or {}).get('id'):
        response={'id':help_change['id']}
        try:
            if help_change.get('read'):
                tutors.read_replies(user_id,course_id,audio['id'],int(help_change['root_id']))
            else:
                tutors.set_help(user_id,course_id,audio['id'],int(help_change['root_id']),help_change['opened'])
        except (ValueError,TypeError,KeyError) as exc:
            response['error']=str(exc)
        st.session_state[key+'_help_result']=response
        changed=True
    deletion = result.delete_note
    if deletion and deletion['id'] != (st.session_state.get(key+'_delete_result') or {}).get('id'):
        response = {'id':deletion['id']}
        try:
            store.delete_mark(user_id,course_id,audio['id'],int(deletion['mark_id']))
        except (ValueError, TypeError) as exc:
            response['error'] = str(exc)
        st.session_state[key+'_delete_result'] = response
        changed = True
    requested_completion = result.completion_change
    if requested_completion and requested_completion['id'] != (st.session_state.get(key+'_completion_result') or {}).get('id'):
        response = {'id':requested_completion['id']}
        try:
            store.set_completion(user_id,course_id,audio['id'],requested_completion['completed'])
            st.session_state[key+'_completed'] = requested_completion['completed']
        except ValueError as exc:
            response['error'] = str(exc)
        st.session_state[key+'_completion_result'] = response
        st.rerun(scope='app')
    attachment_page=result.attachment_page
    if attachment_page:
        available={file['id']:file for mark in marks for file in mark.get('attachments',[]) if file['mime']=='application/pdf'}
        file=available.get(attachment_page.get('id'))
        page=attachment_page.get('page')
        if file and isinstance(page,int) and 0<=page<file['pages']:
            selected=st.session_state.setdefault(key+'_attachment_pages',{})
            if selected.get(file['id'],0)!=page:
                selected[file['id']]=page
                changed=True
    if changed:
        rerun_player()
