"""External-provider import controls and in-app reminders."""
from datetime import date, timedelta
import streamlit as st
from src import database
from src.provider_import import parse_kaplan, import_kaplan, next_reminder, valid_provider_url
from src.provider_reminders import range_label, requested_range, submission_url, confirm_no_new_quizzes


def render_provider_reminder(user_id):
    due = next_reminder(user_id)
    if due and due <= date.today():
        st.info('Please update your Kaplan results: ' + range_label(user_id))
        st.page_link('pages/13_Kaplan_Update.py', label='Submit Kaplan update')
        url = database.get_setting(user_id, 'kaplan_provider_url')
        if url and valid_provider_url(url):
            st.link_button('Open Kaplan to copy results', url)


def render_provider_import(user_id):
    with st.expander('Import Kaplan results & reminders', expanded=True):
        st.info('Requested update: ' + range_label(user_id))
        st.caption('Coverage advances only when you confirm a complete date range. A quiz date alone does not prove every earlier day was copied.')
        _, yesterday = requested_range(user_id)
        through = st.date_input('History complete through', value=yesterday, max_value=yesterday)
        complete = st.checkbox('This includes all completed quizzes through that date, including days with no practice.')
        st.caption('Open My Quizzes, load the history you want, select all and copy. Paste below or upload a saved .txt file. Repeated imports do not duplicate quizzes. Dates use the quiz timestamp shown by Kaplan.')
        url = database.get_setting(user_id, 'kaplan_provider_url')
        if url and valid_provider_url(url):
            st.link_button('Open Kaplan / sign in', url)
        text = st.text_area('Paste Kaplan page text', height=160, key='kaplan_paste')
        upload = st.file_uploader('Or upload copied page text', type=['txt'], key='kaplan_upload')
        if upload:
            try:
                text = upload.getvalue().decode('utf-8-sig')
            except UnicodeDecodeError:
                st.error('Save the text file using UTF-8 encoding.')
                text = ''
        if text.strip():
            try:
                parsed = parse_kaplan(text)
                quizzes = parsed['quizzes']
                correct = sum(q['correct_count'] for q in quizzes)
                total = sum(q['correct_count'] + q['incorrect_count'] for q in quizzes)
                st.write(f"{len(quizzes)} completed quizzes · {total:,} question attempts · {correct:,} correct · {total-correct:,} incorrect")
                st.caption(f"{parsed['skipped']} unfinished quizzes skipped. Repeat attempts count separately; these totals may differ from Kaplan's QBank summary. Timer durations are retained with each quiz but are not added to active study time.")
                with st.expander('Preview quiz history'):
                    st.dataframe([{k:v for k,v in q.items() if k != 'quiz_key'} for q in quizzes], hide_index=True)
                replace = st.checkbox('Replace existing manually entered Kaplan totals on imported dates', help='Use only when this history covers those dates completely. Other dates and providers are preserved.')
                if st.button('Import Kaplan results', type='primary'):
                    result = import_kaplan(user_id, text, replace, complete_through=through if complete else None)
                    st.session_state['external_practice_saved_notice'] = f"Kaplan imported: {result['added']} new quizzes; {result['days']} dates updated."
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if not text.strip():
            none = st.checkbox('I checked Kaplan: there are no new completed or unfinished quizzes in the requested range.')
            if st.button('Confirm no new quizzes', disabled=not (none and complete)):
                try:
                    confirm_no_new_quizzes(user_id, through)
                    st.session_state['external_practice_saved_notice'] = 'Kaplan coverage updated; existing daily counts are unchanged.'
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with st.form('kaplan_preferences'):
            link = st.text_input('Kaplan page link', value=url, placeholder='https://…')
            days = st.number_input('Remind me every N days (0 = off)', min_value=0, max_value=365, value=int(database.get_setting(user_id, 'kaplan_reminder_days') or '7'))
            enabled = st.checkbox('Email me requests for missing Kaplan history', value=database.get_setting(user_id, 'kaplan_email_enabled') == 'true')
            app_url = st.text_input('StudyForge app address', value=database.get_setting(user_id, 'kaplan_app_url'), placeholder='https://your-app.example.com')
            st.caption('Emails use your address and SMTP setup in Settings. The scheduled email runner must run daily, even when the app is closed. Requests repeat at this interval after your last import or emailed request and cover full days through yesterday. Use an app address accessible from the device where you read email.')
            if st.form_submit_button('Save link and reminder interval'):
                if link.strip() and not valid_provider_url(link.strip()):
                    st.error('Enter an HTTPS page link without embedded credentials.')
                else:
                    try:
                        if app_url.strip() or enabled:
                            submission_url(app_url)
                        if enabled and not database.get_setting(user_id, 'profile_email').strip():
                            raise ValueError('Add your email address in Settings first.')
                        if enabled and days == 0:
                            raise ValueError('Choose an interval greater than zero to enable email requests.')
                    except ValueError as exc:
                        st.error(str(exc))
                        return
                    database.set_setting(user_id, 'kaplan_provider_url', link.strip())
                    database.set_setting(user_id, 'kaplan_reminder_days', str(days))
                    database.set_setting(user_id, 'kaplan_email_enabled', str(enabled).lower())
                    database.set_setting(user_id, 'kaplan_app_url', app_url.strip())
                    st.rerun()
        due = next_reminder(user_id)
        if due:
            st.caption(f'Next reminder: {due:%B %d, %Y}')
