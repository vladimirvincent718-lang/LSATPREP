"""Guided recall, answer review and non-musical delayed tests."""
import time
import uuid
import base64
from pathlib import Path
from datetime import datetime,timedelta
import pandas as pd
import streamlit as st
import streamlit.components.v2 as components
from src import karaoke_recall as recall
from src import audio_study

_KARAOKE_JS=Path(__file__).with_name('karaoke_player.js').read_text(encoding='utf-8')


def trial(user_id,course_id,deck,concept,level,key,experiment_id=None,phase='practice',delay_days=None,method='Music'):
    state=st.session_state.get(key)
    if not state:
        if st.button('Start recall',key=key+'_start'):
            st.session_state[key]={'id':uuid.uuid4().hex,'started':time.monotonic()}
            st.rerun()
        return
    if state.get('saved'):
        st.success('Saved. Your concept review schedule and history are updated.')
        if st.button('Another attempt',key=key+'_again'):
            del st.session_state[key];st.rerun()
        return
    if phase!='test' and method=='Music' and level<5:
        lyrics=recall.masked_lyrics(deck['lyrics'],concept['keywords'],level)
        if deck['audio_id']:
            cache_key=f"karaoke_src_{user_id}_{course_id}_{deck['audio_id']}"
            if cache_key not in st.session_state:
                recording=next(r for r in audio_study.library(user_id,course_id) if r['id']==deck['audio_id'])
                st.session_state[cache_key]='data:'+recording['mime']+';base64,'+base64.b64encode(audio_study.audio_bytes(user_id,course_id,deck['audio_id'])).decode()
            player=components.component('karaoke_lyrics_player',js=_KARAOKE_JS)
            player(key=key+'_player',data={'src':st.session_state[cache_key],'lyrics':lyrics})
            st.caption('Timed LRC lyrics follow the recording. With plain lyrics, click a line to highlight it.')
        else:st.text(lyrics)
        if level==4:st.caption('Use an instrumental recording for a practice round without sung lyrics.')
    if phase=='training' and method=='Standard' and not state.get('studied'):
        st.info(concept['answer'])
        if st.button('Hide answer and begin recall',key=key+'_hide'):
            state.update(studied=True,started=time.monotonic());st.rerun()
        return
    st.write(concept['prompt'])
    if 'response' not in state:
        with st.form(key+'_response'):
            response=st.text_area('Recall in your own words',key=key+'_answer')
            if st.form_submit_button('Check recall'):
                if not response.strip():st.error('Write your response first.')
                else:
                    state.update(response=response,seconds=time.monotonic()-state['started']);st.rerun()
    else:
        st.write('Your response: '+state['response'])
        st.info('Reference answer: '+concept['answer'])
        suggestion=recall.suggest_score(state['response'],concept['keywords'])
        st.caption('Keyword coverage is a guide, not an AI judgment. Check meaning, relationships, signs and formulas against the reference before confirming your score.')
        if suggestion['missing']:st.write('Check these concepts: '+', '.join(suggestion['missing']))
        score=st.slider('Concepts correctly recalled (%)',0,100,round(suggestion['score']*100),key=key+'_score')
        if st.button('Save recall result',type='primary',key=key+'_save'):
            try:
                recall.record_attempt(user_id,course_id,deck['id'],concept['id'],state['id'],level,state['response'],score/100,state['seconds'],experiment_id,phase,delay_days)
                state['saved']=True;st.rerun()
            except ValueError as exc:st.error(str(exc))


def render_recall(user_id,course_id,recordings):
    recall.init_recall()
    study,create,compare,history=st.tabs(['Recall practice','Create song set','Retention comparison','Recall history'])
    with create:
        st.caption('Upload your music in Audio Library, then attach it here with your lyrics and concept prompts.')
        lyrics_file=st.file_uploader('Upload lyrics (optional)',type=['txt','lrc'],key=f'lyrics_file_{user_id}_{course_id}')
        uploaded_lyrics=lyrics_file.getvalue().decode('utf-8-sig',errors='replace') if lyrics_file else ''
        with st.form(f'recall_create_{user_id}_{course_id}'):
            title=st.text_input('Song set title')
            source=st.text_input('Source cheat sheet / chapter')
            song=st.selectbox('Song recording',[None]+[r['id'] for r in recordings],format_func=lambda v:'No recording yet' if v is None else next(r['title'] for r in recordings if r['id']==v))
            lyrics=st.text_area('Lyrics',value=uploaded_lyrics,height=180)
            st.caption('Define the concepts behind the lyrics. Separate required ideas with semicolons; use | between acceptable synonyms. Example: price; yield|interest rate; inverse|opposite.')
            rows=st.data_editor(pd.DataFrame([{'prompt':'','answer':'','keywords':''}]),num_rows='dynamic',hide_index=True,width='stretch',key=f'recall_concepts_{user_id}_{course_id}')
            if st.form_submit_button('Save song set'):
                try:
                    recall.save_set(user_id,course_id,title,lyrics,rows.fillna('').to_dict('records'),song,source)
                    st.success('Song set saved. Open Recall practice to begin.')
                except ValueError as exc:st.error(str(exc))
    decks=recall.sets(user_id,course_id)
    if not decks:
        with study:st.info('Create your first song set with lyrics and concept prompts.')
        return
    selected=st.selectbox('Song set',[d['id'] for d in decks],format_func=lambda v:next(d['title'] for d in decks if d['id']==v),key=f'recall_deck_{course_id}')
    deck=next(d for d in decks if d['id']==selected)
    with create:
        with st.expander('Edit selected song set'):
            with st.form(f'edit_song_{user_id}_{selected}'):
                title=st.text_input('Title',deck['title'])
                source=st.text_input('Cheat-sheet source',deck['source'])
                lyrics=st.text_area('Song lyrics',deck['lyrics'],height=180)
                ids=[None]+[r['id'] for r in recordings]
                song=st.selectbox('Attached recording',ids,index=ids.index(deck['audio_id']) if deck['audio_id'] in ids else 0,
                    format_func=lambda v:'No recording' if v is None else next(r['title'] for r in recordings if r['id']==v))
                if st.form_submit_button('Update song set'):
                    try:recall.update_set(user_id,course_id,selected,title,lyrics,song,source);st.rerun()
                    except ValueError as exc:st.error(str(exc))
    concepts=recall.concepts(user_id,course_id,selected)
    records=recall.attempts(user_id,course_id,selected)
    assignments=recall.experiment(user_id,course_id,selected)
    with study:
        due=[q for q in concepts if q['due_at']<=recall.now().isoformat(sep=' ')]
        st.caption(f'{len(due)} concepts due · Weak concepts return sooner; successful recall earns longer intervals.')
        if assignments:st.warning('Practicing these concepts outside the assigned method may affect your retention comparison. Use Retention comparison for controlled sessions.')
        due_only=st.toggle('Only concepts due',value=True,key=f'due_{selected}')
        pool=due if due_only else concepts
        if pool:
            concept=st.selectbox('Concept',pool,format_func=lambda q:q['prompt'],key=f'concept_{selected}')
            level=st.select_slider('Recall level',options=[1,2,3,4,5],format_func=lambda v:{1:'1 · Full lyrics',2:'2 · Hide keywords',3:'3 · Hide lines',4:'4 · Minimal prompts',5:'5 · No music or lyrics'}[v],key=f'level_{selected}')
            trial(user_id,course_id,deck,concept,level,f"recall_{user_id}_{selected}_{concept['id']}_{level}")
        else:st.success('Nothing due. Turn off the filter to practice ahead.')
    with compare:
        st.write('Compare music with standard active recall using the same non-musical prompts after 1, 7 and 14 days.')
        st.caption('Personal pilot: concepts are randomly assigned, scores are self-confirmed, and difficulty or exposure to other lyrics can affect results. Choose comparable concepts and interpret differences cautiously.')
        if not assignments:
            if st.button('Start randomized comparison',key=f'experiment_{selected}'):
                try:recall.start_experiment(user_id,course_id,selected);st.rerun()
                except ValueError as exc:st.error(str(exc))
        else:
            assignment=st.selectbox('Assigned concept',assignments,format_func=lambda a:f"{a['prompt']} · {a['method']}",key=f'assignment_{selected}')
            concept=next(q for q in concepts if q['id']==assignment['concept_id'])
            eid=assignment['experiment_id']
            if not assignment['trained_at']:
                st.write('Initial study method: '+assignment['method'])
                trial(user_id,course_id,deck,concept,1 if assignment['method']=='Music' else 5,f"train_{user_id}_{eid}_{concept['id']}",eid,'training',method=assignment['method'])
            else:
                completed={r['delay_days'] for r in records if r['phase']=='test' and r['concept_id']==concept['id']}
                for delay in (1,7,14):
                    due_at=datetime.fromisoformat(assignment['trained_at'])+timedelta(days=delay)
                    if delay in completed:st.write(f'Day {delay}: complete')
                    elif recall.now()<due_at:st.write(f'Day {delay}: due {due_at:%Y-%m-%d %H:%M} UTC')
                    else:
                        st.subheader(f'Day {delay} retention test')
                        trial(user_id,course_id,deck,concept,5,f"test_{user_id}_{eid}_{concept['id']}_{delay}",eid,'test',delay,assignment['method'])
                        break
            results=[r for r in records if r['phase']=='test']
            if results:
                frame=pd.DataFrame(results)
                frame['Accuracy (%)']=frame['score']*100
                st.dataframe(frame.groupby(['method','delay_days']).agg(Tests=('score','count'),Accuracy=('Accuracy (%)','mean'),Seconds=('seconds','mean')).reset_index(),hide_index=True)
                st.caption('Response time includes reading and typing. Actual test dates appear in Recall history; late tests are not necessarily exact 1-, 7- or 14-day intervals.')
            else:st.info('Delayed retention results will appear after the first tests become due.')
    with history:
        if records:
            frame=pd.DataFrame(records)
            st.metric('Recall attempts',len(records))
            mastery=frame.groupby('prompt').agg(Attempts=('score','count'),Average_recall=('score','mean'),Average_seconds=('seconds','mean'))
            st.dataframe(mastery,width='stretch')
            st.line_chart(frame.assign(Accuracy=frame['score']*100).set_index('created_at')[['Accuracy']])
            st.caption('Review schedule by concept')
            st.dataframe(pd.DataFrame(concepts)[['prompt','stage','due_at']],hide_index=True,width='stretch')
            st.dataframe(frame[['created_at','prompt','phase','method','delay_days','score','seconds']],hide_index=True,width='stretch')
            st.download_button('Download recall history',frame.to_csv(index=False),'recall_history.csv','text/csv')
        else:st.info('Your recall accuracy and response times will appear here after practice.')
