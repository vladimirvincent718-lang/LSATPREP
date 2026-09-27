"""Tutor connections, adjustable cadence and a persistent unread inbox."""
import streamlit as st
from src import audio_tutors as tutors
from src import tutor_providers as providers


def render_tutor_settings(user_id):
    prefs = tutors.settings(user_id)
    with st.expander('AI tutors · connections and response timing', expanded=False):
        st.caption('Posting a comment requests help. Resolve its thread to stop tutoring; a new comment from you reopens it. Each new message permits at most one answer and one review. AI replies never trigger more work.')
        st.info('Tutor replies use developer APIs, with billing and limits separate from the Gemini and ChatGPT apps. Enabling sends your comment thread and relevant transcript passages to the selected providers. Keys stay in Windows Credential Manager.')
        for provider, label in tutors.PROFILES.items():
            connected = providers.has_key(user_id, provider)
            st.write(f"{label} · {'Key saved' if connected else 'Not connected'}")
            with st.form(f'tutor_key_{user_id}_{provider}', clear_on_submit=True):
                key = st.text_input(f'{label} API key', type='password')
                save = st.form_submit_button('Save key')
            if save:
                try:
                    providers.save_key(user_id, provider, key)
                    st.rerun()
                except providers.TutorError as exc:
                    st.error(str(exc))
            if connected and st.button(f'Disconnect {label}', key=f'tutor_remove_{user_id}_{provider}'):
                try:
                    providers.remove_key(user_id, provider)
                    st.rerun()
                except providers.TutorError as exc:
                    st.error(str(exc))
        with st.form(f'tutor_settings_{user_id}'):
            enabled = st.checkbox('Enable automatic API tutoring', value=prefs['enabled'])
            primary = st.selectbox('First responder', list(tutors.PROFILES), index=list(tutors.PROFILES).index(prefs['primary']), format_func=tutors.PROFILES.get)
            reviewer = st.selectbox('Follow-up reviewer', ['none', *tutors.PROFILES], index=['none', *tutors.PROFILES].index(prefs['reviewer']), format_func=lambda p: 'No automatic review' if p=='none' else tutors.PROFILES[p])
            reply = st.number_input('First reply delay (minutes)', min_value=0.0, max_value=1440.0, value=float(prefs['reply_minutes']), step=1.0)
            review = st.number_input('Review delay after your latest comment (hours)', min_value=.25, max_value=168.0, value=float(prefs['review_hours']), step=.25)
            limit = st.number_input('Maximum API calls per rolling 24 hours', min_value=1, max_value=100, value=int(prefs['call_limit']))
            gemini_model = st.text_input('Gemini model ID', value=prefs['gemini_model'])
            openai_model = st.text_input('OpenAI model ID', value=prefs['openai_model'])
            st.caption('Review delays restart when you add a new comment. A review waits for the first answer and posts only when it finds a meaningful issue. Timing controls when a request starts; provider latency adds to the wait.')
            st.caption('This limit covers calls made by this app, including failed attempts. It does not measure subscription usage or guarantee a dollar spending cap. Processing continues while the local computer is awake; overdue work resumes when Audio Study opens.')
            submitted = st.form_submit_button('Save tutor settings')
        if submitted:
            try:
                if enabled and not providers.has_key(user_id, primary):
                    raise ValueError('Save an API key for the first responder before enabling tutoring.')
                tutors.save_settings(user_id, dict(enabled=enabled, primary=primary, reviewer=reviewer,
                    reply_minutes=reply, review_hours=review, call_limit=limit,
                    gemini_model=gemini_model.strip(), openai_model=openai_model.strip()))
                tutors.ensure_worker()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


@st.fragment(run_every=5)
def render_tutor_inbox(user_id, course_id):
    with tutors.store.connection() as c:
        rows = c.execute('''SELECT n.root_id,m.audio_id,m.tutor_provider,m.note,a.title,COUNT(*) AS count
          FROM audio_tutor_notifications n JOIN audio_marks m ON m.id=n.mark_id
          JOIN study_audio a ON a.id=m.audio_id WHERE n.user_id=? AND n.is_read=0 AND m.is_deleted=0
          AND (a.user_id=? OR EXISTS(SELECT 1 FROM audio_listeners l WHERE l.audio_id=a.id AND l.user_id=?))
          AND (a.course_id=? OR EXISTS(SELECT 1 FROM audio_targets t WHERE t.audio_id=a.id AND t.course_id=?))
          GROUP BY n.root_id ORDER BY MAX(m.id) DESC''', (user_id,user_id,user_id,course_id,course_id)).fetchall()
    if not rows:
        st.caption('Tutor inbox · no unread replies')
        return
    with st.expander(f"Tutor inbox · {sum(r['count'] for r in rows)} unread replies", expanded=True):
        for row in rows:
            st.write(f"{row['title']} · {row['count']} new replies")
            st.caption(row['note'][:180])
            if st.button('Open conversation', key=f"tutor_inbox_{user_id}_{row['root_id']}"):
                st.session_state[f'recording_{user_id}_{course_id}'] = row['audio_id']
                st.session_state[f'tutor_focus_{user_id}_{course_id}'] = row['root_id']
                tutors.read_replies(user_id,course_id,row['audio_id'],row['root_id'])
                st.rerun(scope='app')
