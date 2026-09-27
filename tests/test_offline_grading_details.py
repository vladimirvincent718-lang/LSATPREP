import json
from test_offline_exams import exam, fill
from src import offline_exams, database


def test_preview_and_closed_details_match(exam):
    _,serial,pdf,_=exam
    record=offline_exams.get_offline_exam(1,serial)
    completed=fill(pdf,{'q_001_answer':'/B'})
    preview=offline_exams.inspect_submission(1,serial,completed)
    before=offline_exams.grading_details(record,preview)
    assert list(before[0]) == ['Question','Your answer','Correct answer','Result','Rationale','Points']
    assert before[0]['Your answer']=='B. Two'
    assert before[0]['Correct answer']=='B. Two'
    assert before[0]['Points']=='1 / 1'
    assert not database.get_attempts(1)
    saved=offline_exams.submit_pdf(1,serial,completed)
    assert offline_exams.grading_details(record,saved)==before


def test_points_rationale_and_pending():
    question={'stimulus':'Explain this.','correct_answer':'A','choice_a':'Reference','explanation':'Saved reasoning.'}
    record={'questions_json':json.dumps([question]*5)}
    result={'rows':[
        {'number':1,'selected':'A','correct':True,'scored':True},
        {'number':2,'selected':'B','correct':False,'scored':True},
        {'number':3,'selected':'','correct':False,'scored':True},
        {'number':4,'selected':'A','correct':True,'scored':False},
        {'number':5,'selected':'Written response','correct':False,'scored':True,'gradeable':False},
    ]}
    rows=offline_exams.grading_details(record,result)
    assert [r['Points'] for r in rows]==['1 / 1','0 / 1','0 / 1','0 / 0','Pending / 1']
    assert rows[2]['Result']=='Unanswered'
    assert rows[3]['Result']=='Excluded'
    assert all(r['Rationale']=='Saved reasoning.' for r in rows)
    assert offline_exams.grading_details(record,result,{5:True})[4]['Points']=='1 / 1'


def test_preview_renderer_shows_points_and_all_columns(exam):
    from streamlit.testing.v1 import AppTest
    _,serial,_,_=exam
    app=AppTest.from_string(f'''from src.offline_exams import get_offline_exam, inspect_submission, render_grading_details
record=get_offline_exam(1,{serial!r})
result=inspect_submission(1,{serial!r},record['pdf'])
render_grading_details(record,result,provisional=True)
''').run()
    assert not app.exception
    assert app.metric[0].label=='Provisional points'
    assert app.metric[0].value=='0 / 1'
    assert list(app.dataframe[0].value.columns)==['Question','Your answer','Correct answer','Result','Rationale','Points']
    assert not database.get_attempts(1)
