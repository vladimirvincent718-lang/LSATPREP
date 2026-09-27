"""Course, module and chapter assignment for private audio recordings."""
import streamlit as st
from src import database, audio_study

LEVELS = ['Course overview', 'Modules', 'Chapters']


def catalog(user_id):
    courses = database.get_enrolled_courses(user_id)
    with audio_study.connection() as conn:
        names={c['id']:c['title'] for c in courses}
        modules=([dict(r,course_title=names[r['course_id']]) for r in conn.execute('SELECT * FROM course_module_blueprints ORDER BY display_order,id') if r['course_id'] in names]
                 if conn.execute("SELECT 1 FROM sqlite_master WHERE name='course_module_blueprints'").fetchone() else [])
        chapters = ([dict(r) for r in conn.execute('SELECT * FROM course_chapters')]
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='course_chapters'").fetchone() else [])
    ids = {c['id'] for c in courses}
    return courses, modules, [ch for ch in chapters if ch['course_id'] in ids]


def assignment_picker(user_id, course_id, key, current=None):
    courses, modules, chapters = catalog(user_id)
    current = current or [{'course_id':course_id,'module_id':0,'chapter_id':0}]
    initial = 'Chapters' if any(t.get('chapter_id') for t in current) else 'Modules' if any(t.get('module_id') for t in current) else 'Course overview'
    level = st.radio('Recording coverage', LEVELS, index=LEVELS.index(initial), horizontal=True, key=key+'_level')
    ids = [c['id'] for c in courses]
    names = {c['id']:c['title'] for c in courses}
    selected_courses = st.multiselect('Courses covered', ids, default=[cid for cid in ids if cid in {t['course_id'] for t in current}],
                                       format_func=names.get, key=key+'_courses')
    if level == 'Course overview':
        st.caption('An aggregate overview of the selected course(s). It does not belong to just one module.')
        return [{'course_id':cid,'module_id':0,'chapter_id':0} for cid in selected_courses]
    available = {m['id']:m for m in modules if m['course_id'] in selected_courses}
    mids = st.multiselect('Modules covered', list(available), default=[mid for mid in available if mid in {t.get('module_id') for t in current}],
        format_func=lambda mid:f"{available[mid]['course_title']} / {available[mid]['name']}",key=key+'_modules')
    if level == 'Modules':
        return [{'course_id':available[mid]['course_id'],'module_id':mid,'chapter_id':0} for mid in mids]
    available_chapters = {ch['id']:ch for ch in chapters if ch['module_id'] in mids and ch['course_id'] in selected_courses}
    chosen = st.multiselect('Chapters covered',list(available_chapters),default=[cid for cid in available_chapters if cid in {t.get('chapter_id') for t in current}],
        format_func=lambda cid:f"{available[available_chapters[cid]['module_id']]['name']} / {available_chapters[cid]['name']}",key=key+'_chapters')
    if not available_chapters:
        st.caption('Select modules with chapters, or use module-level coverage.')
    return [{'course_id':available_chapters[cid]['course_id'],'module_id':available_chapters[cid]['module_id'],'chapter_id':cid} for cid in chosen]


def coverage_label(selected, courses, modules, chapters):
    c = {r['id']:r['title'] for r in courses}
    m = {r['id']:r['name'] for r in modules}
    ch = {r['id']:r['name'] for r in chapters}
    return '; '.join(c.get(t['course_id'],'Course') +
        (f" / {m.get(t['module_id'],'Module')}" if t.get('module_id') else ' · Course overview') +
        (f" / {ch.get(t['chapter_id'],'Chapter')}" if t.get('chapter_id') else '') for t in selected)


def render_assignment_editor(user_id, course_id, recordings):
    key=f'audio_assign_{user_id}_{course_id}'
    if key+'_notice' in st.session_state:st.success(st.session_state.pop(key+'_notice'))
    with st.expander('Assign or change coverage for existing recordings'):
        ids=[r['id'] for r in recordings]
        names={r['id']:r['title'] for r in recordings}
        chosen=st.multiselect('Recordings to assign',ids,format_func=names.get,key=key+'_recordings')
        if not chosen:
            st.caption('Choose one recording, or select several to assign them together. Existing files and notes are kept.')
            return
        current=audio_study.targets(user_id,course_id,chosen[0])
        if len(chosen)>1:st.caption('The coverage selected below will replace the assignments for all selected recordings.')
        selected=assignment_picker(user_id,course_id,key+'_'+str(chosen[0]),current)
        if st.button('Save coverage',key=key+'_save'):
            try:
                audio_study.set_targets(user_id,course_id,chosen,selected)
                st.session_state[key+'_notice']='Coverage saved. Recordings appear in the courses you selected.'
                st.rerun()
            except ValueError as exc:st.error(str(exc))
