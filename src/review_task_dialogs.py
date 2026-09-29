"""Popup selection and setup, keeping course queues compact."""
from collections import Counter
from datetime import date
import hashlib
import json

import pandas as pd
import streamlit as st
from streamlit_sortables import sort_items

from src import review_tasks as store, review_practice
from src.utils import DIFFICULTY_LABELS
from src.practice_review_focus import topic_key


def dismiss_dialog():
    st.session_state.pop('review_queue_dialog',None)


def close_dialog():
    dismiss_dialog()
    st.rerun(scope='app')


def open_dialog(kind,user_id,mock_id,course_id,**options):
    st.session_state['review_queue_dialog'] = dict(kind=kind,user_id=user_id,mock_id=mock_id,course_id=course_id,**options)


def render_dialog(user_id,mock_id,course_id):
    state = st.session_state.get('review_queue_dialog')
    if not state or (state['user_id'],state['mock_id'],state['course_id'])!=(user_id,mock_id,course_id):
        return
    if state['kind']=='material':
        material_dialog(user_id,mock_id,course_id,state['category'])
    elif state['kind']=='practice':
        practice_dialog(user_id,mock_id,course_id,state.get('task_id'))
    elif state['kind']=='arrange':
        arrange_dialog(user_id,mock_id,course_id)
    else:
        details_dialog(user_id,mock_id,state['task_id'])


def category(source):
    return source.get('category') or {
        'PDF/Document Link':'Documents','Reading':'Readings','Video':'Video',
        'Link':'Links','Notes':'Notes','Other':'Other materials',
    }.get(source['kind'],source['kind'])


def _due(items,course_id):
    dates = [str(r['review_deadline']) for r in items if r['course_id']==course_id and r.get('review_deadline')]
    return date.fromisoformat(min(dates)) if dates else date.today()


@st.dialog('Add material to this course queue',width='large',on_dismiss=dismiss_dialog)
def material_dialog(user_id,mock_id,course_id,kind):
    st.subheader(kind)
    existing = {r['source_key'] for r in store.tasks(user_id,mock_id) if r['course_id']==course_id}
    matches = [s for s in store.catalog(user_id,course_id,mock_id) if category(s)==kind]
    available = {s['key']:s for s in matches if s['key'] not in existing}
    st.caption('Only material matching this course’s topics in the selected review window is shown. Audio includes relevant course overviews.')
    key = f'add_resource_{mock_id}_{course_id}_{kind}'
    if available:
        selected = st.multiselect('Select material',list(available),
                                  default=list(available) if len(available)==1 else [],
                                  format_func=lambda k:available[k]['title'],key=key)
        due = st.date_input('Due date',_due(store.review_scope(user_id,mock_id),course_id),key=key+'_due')
        if st.button('Add to queue',type='primary',disabled=not selected,key=key+'_save'):
            try:
                for source_key in selected:
                    store.add_task(user_id,mock_id,course_id,available[source_key],due)
                close_dialog()
            except ValueError as exc:
                st.error(str(exc))
    elif matches:
        st.info('All matching material of this type is already in this course queue.')
    else:
        st.info('No matching material of this type is available for this review yet.')
    if st.button('Cancel',key=key+'_cancel'):
        close_dialog()


@st.dialog('Set up practice exam',width='large',on_dismiss=dismiss_dialog)
def practice_dialog(user_id,mock_id,course_id,task_id=None):
    task = next((r for r in store.tasks(user_id,mock_id) if r['id']==task_id and r['course_id']==course_id),None)
    if task_id is not None and (not task or task['attempt_id'] or task['completed']):
        st.info('This practice exam has already started or is no longer available.')
        return
    settings = json.loads(task.get('settings_json') or '{}') if task else {}
    items = store.review_scope(user_id,mock_id)
    topics = {r.get('match_topic_key') or r['topic_name']:r['topic_name'] for r in items if r['course_id']==course_id}
    defaults = settings.get('topics') or ([task['topic']] if task else list(topics))
    key = f'practice_popup_{mock_id}_{course_id}_{task_id or "new"}'
    st.caption('Configure now; the chosen questions and settings stay saved until you start. Topics are limited to this review window.')
    title = st.text_input('Exam name',task['title'] if task else 'Practice exam',key=key+'_title')
    selected_topics = st.multiselect('Review topics',list(topics),default=[t for t in topics if topic_key(t) in {topic_key(d) for d in defaults}],
                                     format_func=topics.get,key=key+'_topics')
    try:
        pool = review_practice.question_pool(user_id,mock_id,course_id,selected_topics) if selected_topics else []
    except ValueError as exc:
        st.error(str(exc))
        pool=[]
    types = sorted({q.get('question_type') or 'Unspecified' for q in pool})
    chosen_types = st.multiselect('Question types',types,default=types,key=key+'_types_'+str(selected_topics))
    capacity = Counter((q.get('question_type') or 'Unspecified',int(q.get('difficulty') or 3)) for q in pool
                       if (q.get('question_type') or 'Unspecified') in chosen_types)
    saved = {(r['type'],int(r['difficulty'])):r['count'] for r in settings.get('quotas',[])}
    signature = hashlib.sha256(json.dumps([selected_topics,sorted(capacity.items())]).encode()).hexdigest()[:12]
    records = [{'Question type':kind,'Level':level,'Difficulty':DIFFICULTY_LABELS.get(level,str(level)),
                'Available':count,'Count':min(count,saved.get((kind,level),0))}
               for (kind,level),count in sorted(capacity.items())]
    quotas=[]
    if records:
        st.markdown('**Questions by type and difficulty**')
        edited = st.data_editor(pd.DataFrame(records),hide_index=True,width='stretch',
            disabled=['Question type','Level','Difficulty','Available'],
            column_config={'Count':st.column_config.NumberColumn('Count',min_value=0,step=1,required=True),
                           'Level':None},key=key+'_counts_'+signature)
        quotas=[dict(type=r['Question type'],difficulty=int(r['Level']),count=r['Count']) for r in edited.to_dict('records')]
        st.caption(f"Total selected: {sum(r['count'] for r in quotas)} of {sum(capacity.values())} available questions")
    else:
        st.info('No questions match these topics and types. Choose another review topic or add questions to the bank.')
    left,right = st.columns(2)
    order = left.radio('Question order',['Random','By difficulty'],index=int(settings.get('order')=='By difficulty'),key=key+'_order')
    smart = right.checkbox('Smart Review Queue — prioritize due weak areas',value=settings.get('smart_review',False),key=key+'_smart')
    levels = sorted({level for _,level in capacity})
    open_ended = st.multiselect('Open-ended challenge by difficulty',levels,
        default=[int(d) for d in settings.get('open_ended_levels',[]) if int(d) in levels],
        format_func=lambda d:f'{d} — {DIFFICULTY_LABELS.get(d,d)}',key=key+'_modes',
        help='Hide answer choices for these levels. Other levels stay multiple choice.')
    timer = st.checkbox('Use a question timer',value=settings.get('timer_seconds',120)>0,key=key+'_timer')
    seconds = st.number_input('Seconds per question',15,600,max(15,settings.get('timer_seconds',120)),key=key+'_seconds') if timer else 0
    if not timer:
        st.caption('Untimed exams do not contribute to the existing timer-based practice-minute total.')
    due = st.date_input('Due date',date.fromisoformat(task['due_date']) if task else _due(items,course_id),key=key+'_due')
    if st.button('Save practice exam to queue',type='primary',disabled=not quotas,key=key+'_save'):
        try:
            review_practice.save_exam(user_id,mock_id,course_id,title=title,topics=selected_topics,quotas=quotas,
                due_date=due,order=order,smart_review=smart,timer_seconds=seconds,open_ended_levels=open_ended,task_id=task_id)
            close_dialog()
        except (ValueError,TypeError) as exc:
            st.error(str(exc))
    if st.button('Cancel',key=key+'_cancel'):
        close_dialog()


@st.dialog('Arrange course queue',width='large',on_dismiss=dismiss_dialog)
def arrange_dialog(user_id,mock_id,course_id):
    rows = [r for r in store.scoped_tasks(user_id,mock_id) if r['course_id']==course_id]
    labels = {f"{r['title']} [#{r['id']}]":r['id'] for r in rows}
    st.caption('Drag tasks into the order you want to do them, then save.')
    ordered = sort_items(list(labels),direction='vertical',key=f'queue_order_{mock_id}_{course_id}_{list(labels.values())}')
    if st.button('Save order',type='primary'):
        try:
            store.reorder(user_id,mock_id,course_id,[labels[label] for label in ordered])
            close_dialog()
        except ValueError as exc:
            st.error(str(exc))
    if st.button('Cancel'):
        close_dialog()


@st.dialog('Task details',width='large',on_dismiss=dismiss_dialog)
def details_dialog(user_id,mock_id,task_id):
    task = next((r for r in store.scoped_tasks(user_id,mock_id) if r['id']==task_id),None)
    if not task:
        st.info('This task is no longer available in this review.')
        return
    st.subheader(task['title'])
    with st.form(f'task_details_{task_id}'):
        due = st.date_input('Deadline',date.fromisoformat(task['due_date']))
        minutes = 0
        if task['kind'] not in ('Practice','Audio'):
            st.caption(f"{task['minutes']:g} review minutes recorded")
            minutes = st.number_input('Add review minutes',0,1440,0)
        elif task['kind']=='Practice':
            st.caption(f"{len(json.loads(task['question_ids']))} questions prepared · practice time is recorded by the question timer")
        else:
            st.caption('Audio listening time is recorded automatically, including repeat listens.')
        if st.form_submit_button('Save changes',type='primary'):
            store.update_task(user_id,task_id,due_date=due,minutes=minutes or None)
            close_dialog()
    if st.button('Cancel'):
        close_dialog()
