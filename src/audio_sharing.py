"""Explicit, private access for existing StudyForge listeners."""
import streamlit as st
from src import audio_study


def render_sharing(user_id,course_id,recording):
    if recording['user_id']!=user_id:
        st.caption('Shared with you · You can listen, comment and reply. Your playback position and listening history are private to you.')
        return
    key=f"audio_share_{user_id}_{recording['id']}"
    with st.expander('Invite a listener to this recording'):
        st.caption('Enter an existing StudyForge username. They must be enrolled in one of the covered courses. The recording will appear in their Audio Library, where they can comment and reply.')
        with st.form(key):
            username=st.text_input('Listener username')
            if st.form_submit_button('Allow listening and comments'):
                try:
                    audio_study.share_audio(user_id,course_id,recording['id'],username)
                    st.success('Access granted. The recording is now in their Audio Library.')
                except ValueError as exc:st.error(str(exc))
        for listener in audio_study.listeners(user_id,course_id,recording['id']):
            name,action=st.columns([3,1])
            name.write(listener['username'])
            if action.button('Remove access',key=key+f"_remove_{listener['id']}"):
                audio_study.unshare_audio(user_id,course_id,recording['id'],listener['id'])
                st.rerun()
