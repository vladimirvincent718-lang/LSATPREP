"""Collapsed download and recovery options for automatic transcripts."""
import re
from pathlib import Path
import streamlit as st
from src import audio_study


def transcript_filename(title):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',Path(title).stem).strip(' .') or 'recording'
    return name[:150]+'_transcript.txt'


@st.fragment(run_every=5)
def render_transcript(user_id,course_id,recording):
    aid=recording['id']
    key=f'audio_transcript_{user_id}_{aid}'
    text=audio_study.transcript(user_id,course_id,aid)
    with st.expander('Transcript options', expanded=False):
        if text:
            from src.audio_tutors import transcript_export
            from src.audio_transcription import transcription_state
            words=transcription_state(user_id,course_id,aid)['words']
            timed=st.checkbox('Include timestamps in download',value=False,key=key+'_timed')
            export=transcript_export(text,words,timed)
            if timed and not words and export==text and not re.search(r'\d+:\d{2}',text):
                st.caption('This transcript has no saved timestamps. Export keeps the original text.')
            st.download_button('Download transcript (.txt)',export.encode('utf-8'),
                               transcript_filename(recording['title']),'text/plain',
                               key=key+'_download',on_click='ignore')
        from src.audio_transcription import transcription_state, queue_transcription
        state=transcription_state(user_id,course_id,aid)
        if state['status'] in ('error','empty') and not text:
            st.caption(state.get('error') or 'No speech was detected.')
            if st.button('Retry transcription',key=key+'_retry'):
                queue_transcription(user_id,course_id,aid,retry=True)
                st.rerun(scope='app')
        elif not text:
            st.caption('A transcript is generated automatically from this recording. You can keep listening while it processes.')
        if text:
            st.caption('Automatically generated transcripts may contain mistakes.')
