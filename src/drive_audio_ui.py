"""Drive setup for this locally hosted Windows app."""
import streamlit as st
from src import audio_study as audio, drive_audio as drive


def render_drive_settings(user_id, course_id):
    with st.expander('Google Drive audio storage'):
        st.caption('Connect the app to private Drive files. This does not authorize ChatGPT or a ChatGPT Drive connector. Existing assignments, notes and progress stay in StudyForge.')
        st.write('For this local Windows installation: enable Google Drive API in Google Cloud, configure Google Auth Platform with yourself as a test user, and create an OAuth client of type Desktop app. Download its JSON and upload it below. Google One storage is used by Drive; it does not supply OAuth credentials.')
        st.link_button('Google Cloud setup', 'https://console.cloud.google.com/apis/library/drive.googleapis.com')
        st.caption('Open this app on the Windows computer running it. The Google consent window opens there, using a temporary loopback callback. Remote/cloud hosting needs a separate web OAuth deployment.')
        config = st.file_uploader('Desktop OAuth client JSON', type=['json'], key=f'drive_config_{user_id}')
        try:
            if st.button('Save OAuth configuration', disabled=config is None):
                drive.configure(user_id, config.getvalue())
                st.success('Configuration stored in Windows Credential Manager.')
            if st.button('Connect Google Drive'):
                with st.spinner('Approve Google access in the browser on this computer (up to two minutes)…'):
                    drive.connect(user_id)
                    audio.enable_drive(user_id)
                st.success('Connected. New recordings will be saved only to Drive.')
            connected = drive.configured(user_id)
            st.caption('New uploads: ' + ('Google Drive' if audio.storage_provider(user_id) == 'drive' else 'local storage (connect Drive to switch)'))
            if connected and st.button('Disconnect and revoke Google access'):
                drive.disconnect(user_id)
                st.success('Google access revoked. Drive uploads and playback require reconnection; files remain in Drive.')
            local = [r for r in audio.library(user_id, course_id) if r['user_id'] == user_id and not r.get('drive_file_id')]
            if local:
                selection = st.multiselect('Existing recordings to copy to Drive', local, format_func=lambda r:r['title'])
                st.caption('Uploads are checksum verified before switching playback to Drive. Local originals are retained; nothing is deleted.')
                if st.button('Copy selected recordings to Drive', disabled=not connected or not selection):
                    for row in selection:
                        audio.migrate_to_drive(user_id, course_id, row['id'])
                    st.success('Selected recordings now play from Drive. Local originals retained.')
        except (ValueError, OSError, ImportError):
            st.error('Drive setup or operation failed. Ensure dependencies are installed, use Desktop app OAuth JSON, and complete Google consent. Reconnect if authorization expired. Existing recordings are retained.')
