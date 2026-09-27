"""Native sidebar controls and synchronized course selection on reruns."""
from src.utils import _SIDEBAR_JS, _SIDEBAR_CSS


def test_native_sidebar_controls_are_not_hidden():
    assert 'display: none' not in _SIDEBAR_CSS
    assert "classList.remove('sf-sb-collapsed')" in _SIDEBAR_JS
    assert 'disconnect()' in _SIDEBAR_JS
    assert 'el.remove()' in _SIDEBAR_JS
    assert '[aria-expanded="true"]' in _SIDEBAR_CSS


def test_main_and_sidebar_course_selection_stay_in_sync(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import database,study_progress
    monkeypatch.setattr(database,'get_enrolled_courses',lambda uid:[
        {'id':1,'title':'Alternative Investments'},{'id':2,'title':'Financial Statement Analysis'}])
    monkeypatch.setattr(study_progress,'load_progress',lambda uid:{'window':None})
    monkeypatch.setattr(study_progress,'status',lambda *a:'')
    monkeypatch.setattr(study_progress,'label',lambda title,*a:title)
    app=AppTest.from_string('''import streamlit as st
from src.utils import require_course
course=require_course(1,main=True)
st.write(f'Materials for course {course}')
st.button('Unrelated rerun')
''').run()
    assert not app.exception
    app.selectbox(key='main_course_selector').set_value(2).run()
    assert not app.exception
    assert app.session_state['active_course_id']==2
    assert app.selectbox(key='sidebar_course_selector').value==2
    app.button[0].click().run()
    assert app.selectbox(key='main_course_selector').value==2
    app.selectbox(key='sidebar_course_selector').set_value(1).run()
    assert app.selectbox(key='main_course_selector').value==1
    assert app.session_state['active_course_id']==1
