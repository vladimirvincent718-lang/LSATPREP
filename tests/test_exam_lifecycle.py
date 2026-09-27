from unittest.mock import patch
import pytest
from test_offline_exams import exam, fill
from src import database, offline_exams
from src.exam_lifecycle import delete_exam_attempt


def test_all_completion_paths_close_queue(exam):
    aid,serial,pdf,_ = exam
    assert not offline_exams.is_closed(offline_exams.list_offline_exams(1)[0])
    database.complete_attempt(aid,1,1,{})
    assert offline_exams.is_closed(offline_exams.list_offline_exams(1)[0])


def test_pdf_completion_and_delete_remove_score_and_reviews(exam):
    aid,serial,pdf,_ = exam
    offline_exams.submit_pdf(1,serial,fill(pdf,{'q_001_answer':'/A'}))
    assert offline_exams.is_closed(offline_exams.list_offline_exams(1)[0])
    assert database.get_attempts(1)
    offline_exams.delete_offline_exam(1,serial)
    assert not database.get_attempts(1)
    assert not offline_exams.list_offline_exams(1)
    conn=database.get_connection()
    for table in ['user_answers','mistake_journal','user_question_review']:
        assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    conn.close()


def test_delete_preserves_other_attempt_and_rebuilds_reviews(exam):
    aid,serial,pdf,_ = exam
    previous = database.create_attempt(1,'practice','Test',{})
    database.save_answer(previous,999,'A',False,1,False,1,submitted_at='2025-01-01 10:00:00')
    database.complete_attempt(previous,1,0,{})
    offline_exams.submit_pdf(1,serial,fill(pdf,{'q_001_answer':'/A'}))
    delete_exam_attempt(1,aid)
    assert len(database.get_attempts(1)) == 1
    conn=database.get_connection()
    state=conn.execute('SELECT * FROM user_question_review WHERE user_id=1 AND question_id=999').fetchone()
    assert state['times_seen'] == 1
    assert state['misses'] == 1
    assert state['last_answered_at'].startswith('2025-01-01')
    assert conn.execute('SELECT attempt_id FROM mistake_journal').fetchone()[0] == previous
    conn.close()


def test_delete_checks_owner_and_rolls_back(exam):
    aid,serial,pdf,_ = exam
    offline_exams.submit_pdf(1,serial,fill(pdf,{'q_001_answer':'/B'}))
    with pytest.raises(ValueError):
        delete_exam_attempt(2,aid)
    with patch('src.exam_lifecycle.delete_attempt_rows',side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            offline_exams.delete_offline_exam(1,serial)
    assert offline_exams.get_offline_exam(1,serial)
    assert database.get_attempts(1)


def test_remote_completion_closes_live_session(exam):
    aid,serial,pdf,_ = exam
    offline_exams.submit_pdf(1,serial,fill(pdf,{'q_001_answer':'/B'}))
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('from src.offline_exams import render_offline_exams\nrender_offline_exams(1)')
    app.session_state['exam_active']=True
    app.session_state['exam_attempt_id']=aid
    app.run()
    assert not app.exception
    assert 'exam_active' not in app.session_state
    assert not app.selectbox
    app.radio(key='offline_exam_section').set_value('Closed / submitted exams').run()
    assert app.selectbox[0].value == serial


def test_delete_button_removes_closed_exam(exam):
    aid,serial,pdf,_=exam
    offline_exams.submit_pdf(1,serial,fill(pdf,{'q_001_answer':'/B'}))
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('from src.offline_exams import render_offline_exams\nrender_offline_exams(1)').run()
    app.radio(key='offline_exam_section').set_value('Closed / submitted exams').run()
    app.checkbox(key=f'delete_confirm_{serial}').check().run()
    app.button(key=f'delete_exam_{serial}').click().run()
    assert not app.exception
    assert not offline_exams.list_offline_exams(1)
    assert not database.get_attempts(1)
