"""Manual tutor profiles and a searchable collection of saved responses."""
import streamlit as st
from src import audio_tutors as tutors


def render_tutor_profiles(user_id):
    with st.expander('AI tutors · save responses from your chats', expanded=False):
        st.caption('Automatic tutor replies and reviews are disabled. Ask your question in ChatGPT, Gemini or another app, then use Save tutor response on the relevant comment to paste its answer. This app makes no tutor API requests.')
        for label in tutors.profiles(user_id).values():
            st.write(label)
        with st.form(f'manual_tutor_profile_{user_id}', clear_on_submit=True):
            name=st.text_input('Additional tutor name', placeholder='For example, Claude')
            save=st.form_submit_button('Add tutor profile')
        if save:
            try:
                tutors.add_profile(user_id,name)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def render_saved_responses(user_id,course_id):
    st.subheader('Saved tutor responses')
    st.caption('Responses you pasted, grouped by tutor and linked to their recording and original comment.')
    labels=tutors.profiles(user_id)
    choices=['all',*labels]
    selected=st.selectbox('Tutor profile',choices,format_func=lambda value:'All tutors' if value=='all' else labels[value],key=f'tutor_bucket_{user_id}_{course_id}')
    search=st.text_input('Search saved responses',key=f'tutor_search_{user_id}_{course_id}').strip().casefold()
    rows=tutors.saved_responses(user_id,course_id,None if selected=='all' else selected)
    rows=[r for r in rows if not search or search in ' '.join([r['note'],r['question'] or '',r['title']]).casefold()]
    st.caption(f"{len(rows)} saved response{'s' if len(rows)!=1 else ''}")
    if not rows:
        st.info('Use Save tutor response beneath a comment to start this collection.')
        return
    exports=[]
    for row in rows:
        title=f"{row['author']} · {row['title']} · {tutors.timestamp(row['start'])}"
        with st.expander(title,expanded=len(rows)<=3):
            st.caption(('Pasted response' if row['tutor_kind']=='manual' else 'Previously generated response')+' · '+str(row['created_at'] or '')+' UTC')
            if row['question']:
                st.write('Original comment')
                st.text(row['question'])
            if row['question_quote']:
                st.text(row['question_quote'])
            st.write('Saved response')
            st.text(row['note'])
        exports.append(title+'\n'+str(row['created_at'] or '')+' UTC\n\nOriginal comment:\n'+(row['question'] or '[Comment unavailable]')+'\n\nSaved response:\n'+row['note'])
    st.download_button('Download these saved responses', '\n\n---\n\n'.join(exports),'saved_tutor_responses.txt','text/plain',key=f'tutor_export_{user_id}_{course_id}')
