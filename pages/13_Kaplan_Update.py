"""Direct email destination for Kaplan history updates."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from src.auth import is_logged_in, restore_session_from_cookie, wait_for_cookie_load, login_register_form, require_login
from src.database import init_database
from src.provider_import_ui import render_provider_import

st.set_page_config(page_title='Kaplan update · StudyForge', page_icon='📋', layout='wide')
init_database()
restore_session_from_cookie()
if not is_logged_in():
    wait_for_cookie_load()
    st.title('Sign in to submit your Kaplan update')
    login_register_form()
    st.stop()
user_id = require_login()
st.title('Update your Kaplan question counts')
notice = st.session_state.pop('external_practice_saved_notice', None)
if notice:
    st.success(notice)
render_provider_import(user_id)
st.page_link('pages/1_Dashboard.py', label='View updated dashboard')
