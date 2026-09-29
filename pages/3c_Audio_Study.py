"""Audio review and musical active recall, private to each enrolled learner."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pandas as pd
import streamlit as st
from src.auth import require_login
from src.utils import sidebar_nav,require_course,page_header
from src.course_material_nav import course_material_nav
from src import audio_study as audio
from src.audio_player import render_player
from src.audio_music import render_music_library
from src.audio_upload import render_audio_upload
from src.audio_course_setup import render_course_setup
from src.drive_audio_ui import render_drive_settings
from src.audio_assignment import catalog,coverage_label,render_assignment_editor
from src.audio_sharing import render_sharing
from src.audio_transcript import render_transcript
from src.audio_tutor_ui import render_tutor_profiles, render_saved_responses
from src.karaoke_ui import render_recall
from src.study_progress import review_window

st.set_page_config(page_title='Audio Study · StudyForge',page_icon='🎧',layout='wide')
user_id=require_login()
sidebar_nav(st.session_state.get('username',''))
page_header('Audio Study','Listen actively. Mark the hard parts. Recall what matters.')
render_course_setup(user_id)
course_id=require_course(user_id, main=True)
audio.init_audio()
course_material_nav('audio')
library,recall,analytics,responses=st.tabs(['Audio Library','Karaoke Recall','Listening Analytics','Tutor responses'])
with responses:
    render_saved_responses(user_id,course_id)
with library:
    render_tutor_profiles(user_id)
    render_drive_settings(user_id,course_id)
    render_audio_upload(user_id,course_id)
recordings=audio.library(user_id,course_id)
with library:
    if not recordings:st.info('Upload an audio overview, lecture or study song to begin.')
    else:
        completed_count=sum(r['completion']['completed'] for r in recordings)
        st.progress(completed_count/len(recordings),text=f'{completed_count} of {len(recordings)} recordings complete ({completed_count/len(recordings):.0%})')
        owned_recordings=[r for r in recordings if r['user_id']==user_id]
        if owned_recordings:render_assignment_editor(user_id,course_id,owned_recordings)
        by_id={r['id']:r for r in recordings}
        recording_key=f'recording_{user_id}_{course_id}'
        if isinstance(st.session_state.get(recording_key),dict):
            st.session_state[recording_key]=st.session_state[recording_key]['id']
        selected_id=st.selectbox('Recording',list(by_id),format_func=lambda aid:f"{'✓ Complete' if by_id[aid]['completion']['completed'] else '○ Incomplete'} · {by_id[aid]['title']} · {by_id[aid]['play_count']} plays",key=recording_key)
        recording=by_id[selected_id]
        st.caption('Coverage: '+coverage_label(audio.targets(user_id,course_id,recording['id']),*catalog(user_id)))
        st.caption('Green waveform · current playback position. Bottom-edge review flags: Red · needs review / Yellow · learning / Green · comfortable.')
        music_tracks=render_music_library(user_id)
        render_player(user_id,course_id,recording,music_tracks)
        render_transcript(user_id,course_id,recording)
        render_sharing(user_id,course_id,recording)
with recall:render_recall(user_id,course_id,[r for r in recordings if r['user_id']==user_id])
with analytics:
    active_window=review_window(user_id)
    period=st.radio('Listening period',['All time','Current review window','Custom dates'],horizontal=True)
    window=None
    if period=='Current review window':
        window=active_window
        if not window:st.info('No active review window is scheduled. Showing all-time listening.')
        else:st.caption(f"{window[0]} to {window[1] or 'next scheduled review'} (end excluded)")
    elif period=='Custom dates':
        from datetime import date,timedelta
        start=st.date_input('From',date.today()-timedelta(days=7))
        end=st.date_input('Through',date.today())
        if start>end:st.error('The end date must follow the start date.');st.stop()
        window=(start.isoformat(),(end+timedelta(days=1)).isoformat())
    st.button('Refresh listening totals')
    totals=[];segments=[]
    for recording in recordings:
        stats=audio.analytics(user_id,course_id,recording['id'],window)
        totals.append({'Recording':recording['title'],'Completion':'Complete' if recording['completion']['completed'] else 'Incomplete','Topic':coverage_label(audio.targets(user_id,course_id,recording['id']),*catalog(user_id)),
                       'Total plays':audio.play_count(user_id,course_id,recording['id']),'Your plays (selected period)':stats['plays'],'Opens':stats['opens'],'Complete listens':stats['complete'],
                       'Partial listens':stats['partial'],'Minutes':round(stats['seconds']/60,2),'Reviewed (%)':round(stats['percent'],1),'Last listened':stats['last_listened']})
        totals[-1]['Furthest reached (%)']=round(stats['processed_percent'],1)
        segments.extend({'Recording':recording['title'],'Note':s['note'],'Status':s['status'],'Start':s['start'],'End':s['end'],
                         'Visits':s['visits'],'Replays':max(0,s['visits']-1),'Seconds reviewed':round(s['listening_seconds'],1),'Last listened':s['last_listened']} for s in stats['segments'])
    if totals:
        frame=pd.DataFrame(totals).sort_values('Minutes',ascending=False)
        st.dataframe(frame,hide_index=True,width='stretch')
        st.bar_chart(frame.groupby('Topic')['Minutes'].sum())
        st.caption('The green waveform follows your current position; these analytics retain your listening history when you rewind. Total plays includes invited listeners across all time. Other metrics are your own activity for the selected period. Earlier listening sessions count once; detailed replay counts start with this update. A complete listen covers at least 95% within one player session. Dates use UTC.')
        if segments:
            st.subheader('Flagged segments')
            st.dataframe(pd.DataFrame(segments).sort_values('Replays',ascending=False),hide_index=True,width='stretch')
            gaps=[s for s in segments if s['Status']=='Red' and s['Visits']==0]
            if gaps:
                st.warning(f'{len(gaps)} weak segments have not been revisited in this period.')
                st.dataframe(pd.DataFrame(gaps),hide_index=True,width='stretch')
        st.download_button('Download listening totals',frame.to_csv(index=False),'audio_listening.csv','text/csv')
    else:st.info('Listening activity will appear here after you upload a recording.')
