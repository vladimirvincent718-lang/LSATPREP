"""Create a missing course before uploading its private study recordings."""
import streamlit as st

from src.database import create_course, is_admin
from src.utils import get_effective_admin


def render_course_setup(user_id):
    if not get_effective_admin(user_id)[1]:
        return
    notice = st.session_state.pop('audio_course_created', None)
    if notice:
        st.success(notice)
    with st.expander('Add a course for study audio'):
        st.caption('Creates a shared course in this app. Uploaded recordings remain private to you.')
        with st.form('audio_create_course'):
            title = st.text_input('New course title')
            description = st.text_area('Course description (optional)')
            submitted = st.form_submit_button('Create course')
        if submitted:
            if not is_admin(user_id):
                st.error('Only an administrator can create a course.')
                return
            course_id, error = create_course(user_id, title, description)
            if error:
                st.error(error)
            else:
                st.session_state['active_course_id'] = course_id
                st.session_state['audio_course_created'] = f'Created {title.strip()}. Upload your recordings below.'
                st.rerun()
