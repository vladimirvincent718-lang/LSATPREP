"""Compact course checklists with popup material selection and exam setup."""
from datetime import date
import json

import streamlit as st

from src import database as db
from src import review_tasks as store


def _start(user_id, task):
    st.session_state['active_course_id'] = task['course_id']
    if task['kind'] == 'Practice':
        if task['attempt_id']:
            from src.mock_review_ui import open_attempt
            open_attempt(user_id,task['attempt_id'])
            return
        from src.exam_engine import start_quiz, suspend_current_exam
        questions = store.prepare_practice(user_id,task['id'],10)
        suspend_current_exam(user_id)
        # Preserve the suspended draft, but do not carry its per-question state
        # or exported PDF into a newly generated queue session.
        for key in list(st.session_state):
            if key.startswith(('practice_timer_', 'q_radio_', 'q_open_ended_', 'q_self_grade_')) or key in (
                'practice_pdf', 'practice_pdf_name', 'practice_confirm_finish',
                'practice_expanded_answer_idxs', 'practice_timed_out_questions',
                'practice_skipped_questions', 'practice_swipe_drafts',
                'practice_reached_questions', 'practice_timeout_notice', 'practice_skipped_notice'):
                st.session_state.pop(key,None)
        st.session_state['practice_question_pool'] = questions
        st.session_state['practice_session_label'] = task['title']
        settings = json.loads(task.get('settings_json') or '{}')
        timer_seconds = int(settings.get('timer_seconds',120))
        st.session_state['practice_timer_enabled'] = timer_seconds > 0
        st.session_state['practice_timer_seconds'] = timer_seconds or 120
        attempt = start_quiz(user_id,'practice',questions,task['topic'] or 'Review practice',
                             course_id=task['course_id'],time_limit_seconds=timer_seconds)
        store.link_attempt(user_id,task['id'],attempt)
        st.switch_page('pages/5_Practice_Mode.py')
    elif task['kind'] == 'Audio':
        sources = store.catalog(user_id,task['course_id'])
        if not any(s['key']==task['source_key'] for s in sources):
            raise ValueError('This recording is no longer available.')
        st.session_state[f"recording_{user_id}_{task['course_id']}"] = task['source_id']
        st.switch_page('pages/3c_Audio_Study.py')
    elif task['kind']=='Flashcards':
        from src.flashcards import list_decks
        if not any(d['id']==task['source_id'] for d in list_decks(user_id,task['course_id'])):
            raise ValueError('This flashcard set is no longer available.')
        st.session_state[f"fc_{user_id}_{task['course_id']}selected"] = task['source_id']
        st.session_state[f"fc_{user_id}_{task['course_id']}search"] = ''
        st.switch_page('pages/3a_Flashcards.py')
    else:
        st.session_state['review_task_material'] = task['source_id']
        st.switch_page('pages/3_Course_Materials.py')


def render_tasks(user_id, mock_id, review_items, *, course_id=None, overview_only=False):
    if course_id is None:
        st.subheader('Your to-do plan')
    if mock_id is None:
        st.info('Choose one mock above to open its to-do plan.')
        return
    store.init_tasks()
    review_items = store.review_scope(user_id,mock_id)
    course_ids = {r['course_id'] for r in review_items}
    courses = {c['id']:c['title'] for c in db.get_enrolled_courses(user_id) if c['id'] in course_ids}
    if not courses:
        st.info('Choose review modules for this mock to add work to its plan.')
        return
    rows = store.scoped_tasks(user_id,mock_id)
    today = date.today().isoformat()
    if course_id is None:
        st.caption('Build once, then work through the list. Choose a material type inside a course to select and set up its next task.')
        if st.button('Build / refresh plan from review topics',key=f'build_tasks_{mock_id}',
                     help='Adds a practice task and matching materials for each saved review topic. Existing work and deadlines stay saved.'):
            try:
                store.build_plan(user_id,mock_id,review_items)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        pending = [r for r in rows if not r['completed']]
        a,b,c,d = st.columns(4)
        a.metric('Tasks left',len(pending))
        b.metric('Due today / overdue',sum(r['due_date']<=today for r in pending))
        c.metric('Finished tasks',len(rows)-len(pending))
        d.metric('Planned minutes left',sum(r['estimated_minutes'] for r in pending))
        completed = len(rows)-len(pending)
        fraction = completed/len(rows) if rows else 0
        st.progress(fraction, text=f'Overall review plan · {fraction:.0%} complete · {completed} of {len(rows)} tasks')
        st.caption('Progress counts completed tasks in this mock’s plan. Each task counts equally; the overall percentage includes all subjects, regardless of the filters below.')
        if rows:
            with st.expander('Subject statistics'):
                overview = []
                for cid, title in courses.items():
                    subject = [r for r in rows if r['course_id']==cid]
                    left = [r for r in subject if not r['completed']]
                    if subject:
                        overview.append({'Subject':title,'Completed (%)':round(100*(len(subject)-len(left))/len(subject),1),
                                         'Left':len(left),'Complete':len(subject)-len(left),
                                         'Due now':sum(r['due_date']<=today for r in left),
                                         'Next deadline':min((r['due_date'] for r in left),default='—')})
                st.dataframe(overview,hide_index=True,use_container_width=True)
        if overview_only:
            return rows
        if st.session_state.get(f'task_subject_{mock_id}') not in courses:
            st.session_state.pop(f'task_subject_{mock_id}',None)
        course_id = st.selectbox('Subject',list(courses),format_func=courses.get,key=f'task_subject_{mock_id}')
    else:
        if course_id not in courses:
            st.info('This course is outside the selected review plan.')
            return
        st.markdown(f"**{courses[course_id]} queue**")
        if st.button('Build / refresh this course queue',key=f'build_course_tasks_{mock_id}_{course_id}'):
            store.build_plan(user_id,mock_id,[r for r in review_items if r['course_id']==course_id])
            st.rerun()
    current = [r for r in rows if r['course_id']==course_id]
    sources = store.catalog(user_id,course_id,mock_id)
    st.caption(f"{sum(not r['completed'] for r in current)} tasks left for {courses[course_id]}")
    from src.review_task_dialogs import category, open_dialog, render_dialog
    st.markdown('**Add to this course queue**')
    categories = ['Practice exam','Audio','Cheat sheets','Flashcards']
    categories += sorted({category(source) for source in sources}-set(categories))
    for offset in range(0,len(categories),4):
        for column,kind in zip(st.columns(4),categories[offset:offset+4]):
            if column.button(kind,key=f'queue_type_{mock_id}_{course_id}_{kind}',use_container_width=True):
                if kind=='Practice exam':
                    open_dialog('practice',user_id,mock_id,course_id)
                else:
                    open_dialog('material',user_id,mock_id,course_id,category=kind)
    if current and st.button('Arrange queue',key=f'arrange_queue_{mock_id}_{course_id}'):
        open_dialog('arrange',user_id,mock_id,course_id)
    show = st.radio('Task view',['To do','Due now','Completed','All'],horizontal=True,key=f'task_filter_{mock_id}_{course_id}')
    visible = [r for r in current if show=='All' or (show=='Completed' and r['completed']) or
               (show in ('To do','Due now') and not r['completed'] and (show!='Due now' or r['due_date']<=today))]
    if not visible:
        st.info('Nothing in this view. Add work above or choose another task view.')
    for index, task in enumerate(visible):
        tid = task['id']
        with st.container(border=True):
            check,body,action = st.columns([1,8,2],vertical_alignment='center')
            done = check.checkbox('Done',value=bool(task['completed']),key=f'task_done_{tid}_{task["completed"]}',label_visibility='collapsed')
            if done != bool(task['completed']):
                store.update_task(user_id,tid,completed=done)
                st.rerun()
            body.markdown(f"**{task['title']}**")
            due_label = 'Overdue' if task['due_date']<today else 'Due today' if task['due_date']==today else 'Due'
            body.caption(f"{due_label} {task['due_date']} · {task['estimated_minutes']} min planned · {'Complete' if task['completed'] else 'Next up' if index==0 else 'To do'}")
            prepared = bool(json.loads(task['question_ids']))
            start_label = ('Set up exam' if not prepared else 'Resume' if task['attempt_id'] else 'Start practice') if task['kind']=='Practice' else 'Open'
            if action.button(start_label,key=f'start_task_{tid}'):
                try:
                    if task['kind']=='Practice' and not prepared and not task['attempt_id']:
                        open_dialog('practice',user_id,mock_id,course_id,task_id=tid)
                    else:
                        _start(user_id,task)
                except ValueError as exc:
                    st.error(str(exc))
            if action.button('Details',key=f'details_task_{tid}'):
                open_dialog('details',user_id,mock_id,course_id,task_id=tid)
            if task['kind']=='Practice' and prepared and not task['attempt_id'] and not task['completed']:
                if body.button('Edit exam setup',key=f'edit_exam_{tid}'):
                    open_dialog('practice',user_id,mock_id,course_id,task_id=tid)
    _time_summary(user_id,mock_id,current,course_id,sources)
    render_dialog(user_id,mock_id,course_id)


def _time_summary(user_id,mock_id,rows,course_id,sources):
    from src import audio_study
    from src.study_progress import review_window
    window = review_window(user_id,mock_id)
    practice_seconds = 0
    with store.connection() as c:
        for task in rows:
            if task['attempt_id']:
                practice_seconds += c.execute('SELECT COALESCE(SUM(active_seconds),0) FROM study_time_entries WHERE user_id=? AND attempt_id=?',
                                               (user_id,task['attempt_id'])).fetchone()[0]
    audio_seconds = 0
    for task in sources if window else []:
        if task['kind']=='Audio':
            try:
                audio_seconds += audio_study.analytics(user_id,course_id,task['source_id'],window)['seconds']
            except ValueError:
                pass
    st.caption('Time for this subject: practice uses linked exams; audio includes repeat listening to matching recordings and course overviews during this review window; reading/video time is logged above. Task completion does not change your exam score.')
    a,b,c = st.columns(3)
    a.metric('Practice minutes',round(practice_seconds/60,1))
    b.metric('Audio minutes',round(audio_seconds/60,1))
    c.metric('Material review minutes',round(sum(r['minutes'] for r in rows),1))
