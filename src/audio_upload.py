"""Multi-track upload with filename titles that remain editable before saving."""
import hashlib
import streamlit as st
from src import audio_study
from src.audio_assignment import assignment_picker


def render_audio_upload(user_id, course_id):
    scope = f'audio_upload_{user_id}_{course_id}'
    revision = st.session_state.get(scope + '_revision', 0)
    if scope + '_notice' in st.session_state:
        st.success(st.session_state.pop(scope + '_notice'))
    with st.expander('Upload study audio'):
        uploads = st.file_uploader(
            f'Study recordings · up to {audio_study.MAX_AUDIO_UPLOAD_MB} MB per file',
            type=['mp3', 'wav', 'm4a', 'ogg'], accept_multiple_files=True,
            max_upload_size=audio_study.MAX_AUDIO_UPLOAD_MB, key=f'{scope}_files_{revision}',
        )
        st.caption('Select one or more tracks. Each title starts with its filename; edit any title before saving.')
        selected_targets=assignment_picker(user_id,course_id,f'{scope}_coverage_{revision}')
        with st.form(f'{scope}_form_{revision}'):
            topic = st.text_input('Optional description', placeholder='For example: complete course overview, parts I–IV')
            titles = []
            for index, upload in enumerate(uploads):
                token = hashlib.sha256(str(upload.file_id).encode()).hexdigest()[:16]
                titles.append(st.text_input(
                    f'Track {index + 1} title', value=upload.name,
                    key=f'{scope}_title_{revision}_{token}', help=f'Original file: {upload.name}',
                ))
            submitted = st.form_submit_button('Save recordings', disabled=not uploads)
        if submitted:
            try:
                saved_ids = audio_study.save_audio_batch(user_id, course_id, [dict(
                    title=title, topic=topic, filename=upload.name, content=upload.getvalue(),
                ) for upload, title in zip(uploads, titles)], selected_targets=selected_targets)
            except (ValueError, OSError) as exc:
                st.error(str(exc))
            else:
                from src.audio_transcription import queue_transcription
                for audio_id in saved_ids:
                    queue_transcription(user_id,course_id,audio_id)
                st.session_state[scope + '_notice'] = f'{len(uploads)} recording(s) saved to your private library.'
                st.session_state[scope + '_revision'] = revision + 1
                st.rerun()
