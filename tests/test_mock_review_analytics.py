from datetime import date
import pytest
from src import mock_review_analytics as analytics


def test_recent_three_average_trend_and_submission_counts():
    items = [{'id': 1, 'course_id': 3, 'topic_key': 'ethics', 'topic_name': 'Ethics', 'course_title': 'CFA'},
             {'id': 2, 'course_id': 3, 'topic_key': 'equity', 'topic_name': 'Equity', 'course_title': 'CFA'}]
    sessions = [{'attempt_id': i, 'course_id': 3, 'module_name': 'Ethics', 'completed_at': f'2026-09-{10+i:02d}',
                 'questions': 10, 'correct': i+4} for i in range(1,5)]
    sessions += [dict(sessions[0]), {**sessions[0], 'attempt_id': 9, 'completed_at': None},
                 {**sessions[0], 'attempt_id': 10, 'course_id': 4}]
    rows = analytics.summarize_modules(items, sessions)
    assert rows[0]['focus'] == 'Not practiced'
    r = rows[1]
    assert r['count'] == 4
    assert r['scores'] == [80,70,60]
    assert r['average'] == 65
    assert r['trend'] == 20


def test_single_session_has_no_trend_and_average_is_session_weighted():
    item = {'id': 1, 'course_id': 1, 'topic_key': 'x', 'topic_name': 'X'}
    first = {'attempt_id':1,'course_id':1,'module_name':' X ','completed_at':'2026-09-10','questions':1,'correct':1}
    one = analytics.summarize_modules([item],[first])[0]
    assert one['trend'] is None and one['average'] == 100
    second = {**first,'attempt_id':2,'completed_at':'2026-09-11','questions':10,'correct':0}
    two = analytics.summarize_modules([item],[first,second])[0]
    assert two['average'] == 50 and two['trend'] == -100


def test_active_window_and_report_cutoff(monkeypatch):
    monkeypatch.setattr(analytics,'get_current_review_mock',lambda uid, **kw: {'id':7,'mock_label':'Mock 1/7','window_start':date(2026,9,1),'window_end':date(2026,9,19)})
    item={'id':1,'course_id':1,'topic_key':'x','topic_name':'X','mock_schedule_id':7}
    monkeypatch.setattr(analytics,'get_mock_review_items',lambda uid, **kw: [item,{**item,'id':2,'mock_schedule_id':8}])
    sessions=[{'attempt_id':1,'course_id':1,'module_name':'X','completed_at':'2026-09-17 12:00:00','questions':2,'correct':1},
              {'attempt_id':2,'course_id':1,'module_name':'X','completed_at':'2026-09-18 00:01:00','questions':2,'correct':2}]
    monkeypatch.setattr(analytics,'get_review_window_practice_sessions',lambda uid, mid: sessions)
    data=analytics.current_review_analytics(1,day=date(2026,9,17))
    assert data['submitted']==1 and len(data['rows'])==1
    assert data['rows'][0]['latest']==50
    monkeypatch.setattr(analytics,'get_current_review_mock',lambda *a,**kw: None)
    assert analytics.current_review_analytics(1)['rows']==[]
