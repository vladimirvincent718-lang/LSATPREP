import io
import wave
from datetime import datetime,timedelta
from pathlib import Path
import pytest
from src import database,audio_study as audio,karaoke_recall as recall


@pytest.fixture
def store(monkeypatch,tmp_path):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'audio.db')
    audio.init_audio();recall.init_recall()
    content=io.BytesIO()
    with wave.open(content,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\x00\x00'*8000)
    aid=audio.save_audio(1,2,'Lecture','Equity','../example.wav',content.getvalue())
    return aid


def event(session='one',seq=0,ranges=None,seconds=0):
    return dict(session=session,sequence=seq,duration=100,seconds=seconds,ranges=ranges or [])


def test_private_library_notes_and_validation(store):
    assert not audio.library(2,2)
    assert not audio.library(1,3)
    with pytest.raises(ValueError):audio.audio_bytes(2,2,store)
    assert audio.audio_bytes(1,2,store).startswith(b'RIFF')
    audio.record_event(1,2,store,event())
    note=audio.save_mark(1,2,store,12,20,'Check formula','Red')
    audio.save_mark(1,2,store,12,20,'Understood','Green',note)
    assert audio.marks(1,2,store)[0]['status']=='Green'
    with pytest.raises(ValueError):audio.save_mark(1,2,store,20,12,'Invalid','Red')
    with pytest.raises(ValueError):audio.save_mark(1,2,store,0,101,'Invalid','Red')
    with pytest.raises(ValueError):audio.delete_mark(2,2,store,note)
    audio.delete_mark(1,2,store,note)
    assert not audio.marks(1,2,store)


def test_listening_coverage_replay_and_idempotency(store):
    audio.record_event(1,2,store,event())
    audio.save_mark(1,2,store,10,20,'Weak','Red')
    first=event(seq=1,ranges=[[0,50]],seconds=50)
    audio.record_event(1,2,store,first);audio.record_event(1,2,store,first)
    stats=audio.analytics(1,2,store)
    assert stats['seconds']==50 and stats['percent']==50 and stats['partial']==1 and stats['complete']==0
    audio.record_event(1,2,store,event(seq=2,ranges=[[50,100]],seconds=50))
    audio.record_event(1,2,store,event(seq=3,ranges=[[10,20]],seconds=10))
    stats=audio.analytics(1,2,store)
    assert stats['seconds']==110 and stats['percent']==100 and stats['complete']==1
    assert stats['segments'][0]['visits']==2
    assert stats['segments'][0]['listening_seconds']==20
    assert audio.analytics(1,2,store,('2000-01-01','2000-02-01'))['percent']==0
    with pytest.raises(ValueError):audio.record_event(1,2,store,event(seq=4,ranges=[[0,100]],seconds=1))


def test_transcript_highlights_and_passage_comments(store):
    audio.record_event(1,2,store,event())
    audio.save_highlight(1,2,store,12,20,'Selected passage','highlight-one')
    audio.save_highlight(1,2,store,12,20,'Selected passage','highlight-one')
    assert len(audio.highlights(1,2,store))==1
    assert audio.highlights(1,2,store)[0]['quote']=='Selected passage'
    assert not audio.marks(1,2,store), 'Highlights do not create empty comments'
    with pytest.raises(ValueError):audio.highlights(2,2,store)
    for start,end in [(20,12),(0,101),(float('nan'),20),(12,12)]:
        with pytest.raises(ValueError):audio.save_highlight(1,2,store,start,end,'words','invalid')
    point=audio.save_mark(1,2,store,25,25,'Point comment','Neutral')
    passage=audio.save_mark(1,2,store,12,20,'Passage comment','Neutral',submission_id='passage-one',quote='Selected passage')
    assert audio.save_mark(1,2,store,12,20,'Passage comment','Neutral',submission_id='passage-one',quote='Selected passage')==passage
    items=audio.marks(1,2,store)
    assert [m['id'] for m in items]==[passage,point]
    assert items[0]['quote']=='Selected passage'
    reply=audio.save_mark(1,2,store,0,0,'Reply','Neutral',parent_id=passage,quote='ignored')
    assert next(m for m in audio.marks(1,2,store) if m['id']==reply)['quote']==''
    audio.delete_highlight(1,2,store,'highlight-one')
    assert not audio.highlights(1,2,store)
    assert len(audio.marks(1,2,store))==3


def create_set(store):
    return recall.save_set(1,2,'Recall song','Price and yield move in opposite directions.\nRemember the coupon.',
      [dict(prompt='Explain price and yield',answer='Price and yield move inversely.',keywords='price;yield|interest rate;inverse|opposite'),
       dict(prompt='What is a coupon?',answer='Periodic bond interest.',keywords='interest;periodic|regular')],store)


def test_recall_privacy_masking_scoring_and_schedule(store):
    sid=create_set(store)
    assert not recall.sets(2,2)
    with pytest.raises(ValueError):recall.concepts(2,2,sid)
    q=recall.concepts(1,2,sid)[0]
    assert recall.suggest_score('Price moves opposite to the interest rate',q['keywords'])['score']==1
    assert recall.suggest_score('surpriceless yielding',q['keywords'])['score']==0
    assert 'price' not in recall.masked_lyrics('Price and yield',q['keywords'],2).lower()
    assert recall.masked_lyrics('Do not show',q['keywords'],5)==''
    at=datetime(2026,9,21)
    recall.record_attempt(1,2,sid,q['id'],'attempt',5,'Price inversely follows yield',1,12,at=at)
    recall.record_attempt(1,2,sid,q['id'],'attempt',5,'Price inversely follows yield',1,12,at=at)
    assert len(recall.attempts(1,2,sid))==1
    updated=next(x for x in recall.concepts(1,2,sid) if x['id']==q['id'])
    assert updated['stage']==1 and updated['due_at'].startswith('2026-09-24')
    recall.record_attempt(1,2,sid,q['id'],'same-day',5,'Price inversely follows yield',1,9,at=at)
    assert next(x for x in recall.concepts(1,2,sid) if x['id']==q['id'])['stage']==1
    recall.record_attempt(1,2,sid,q['id'],'miss',5,'Forgot',0,20,at=at)
    updated=next(x for x in recall.concepts(1,2,sid) if x['id']==q['id'])
    assert updated['stage']==0 and updated['due_at'].startswith('2026-09-22')


def test_random_assignment_and_delayed_nonmusical_tests(store):
    sid=create_set(store);eid=recall.start_experiment(1,2,sid)
    assignments=recall.experiment(1,2,sid)
    assert {a['method'] for a in assignments}=={'Music','Standard'}
    with pytest.raises(ValueError):recall.start_experiment(1,2,sid)
    q=recall.concepts(1,2,sid)[0];at=datetime(2026,9,21)
    recall.record_attempt(1,2,sid,q['id'],'train',1,'Response',1,20,eid,'training',at=at)
    with pytest.raises(ValueError):recall.record_attempt(1,2,sid,q['id'],'early',5,'Response',1,10,eid,'test',1,at=at)
    with pytest.raises(ValueError):recall.record_attempt(1,2,sid,q['id'],'music',1,'Response',1,10,eid,'test',1,at=at+timedelta(days=1))
    recall.record_attempt(1,2,sid,q['id'],'day1',5,'Response',.5,10,eid,'test',1,at=at+timedelta(days=1))
    recall.record_attempt(1,2,sid,q['id'],'duplicate-day1',5,'Response',.5,10,eid,'test',1,at=at+timedelta(days=1))
    assert len(recall.attempts(1,2,sid))==2
    assert recall.attempts(1,2,sid)[-1]['phase']=='test'


def test_audio_page_and_recall_workflow(store,monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from src import auth,utils,study_progress,audio_player,audio_assignment,audio_sharing
    monkeypatch.setattr(audio_sharing,'render_sharing',lambda *a:None)
    monkeypatch.setattr(audio_assignment,'catalog',lambda uid:([{'id':2,'title':'Test course'}],[],[]))
    monkeypatch.setattr(auth,'require_login',lambda:1)
    monkeypatch.setattr(utils,'sidebar_nav',lambda *a:None)
    monkeypatch.setattr(utils,'require_course',lambda *a,**kw:2)
    monkeypatch.setattr(st,'page_link',lambda *a,**kw:None)
    monkeypatch.setattr(study_progress,'review_window',lambda *a:None)
    monkeypatch.setattr(audio_player,'render_player',lambda *a:None)
    sid=create_set(store)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/3c_Audio_Study.py'),default_timeout=30).run()
    assert not app.exception
    next(b for b in app.button if b.label=='Start recall').click().run()
    assert not app.exception
    next(t for t in app.text_area if t.label=='Recall in your own words').set_value('Price and yield move in opposite directions')
    next(b for b in app.button if b.label=='Check recall').click().run()
    assert not app.exception
    next(b for b in app.button if b.label=='Save recall result').click().run()
    assert not app.exception
    assert len(recall.attempts(1,2,sid))==1
    audio.set_completion(1,2,store,True)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/3c_Audio_Study.py'),default_timeout=30).run()
    assert not app.exception
    recording_selector=next(widget for widget in app.selectbox if widget.label=='Recording')
    assert any('✓ Complete' in option for option in recording_selector.options)
    assert any(progress.proto.text=='1 of 1 recordings complete (100%)' for progress in app.get('progress'))
    audio.set_completion(1,2,store,False)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/3c_Audio_Study.py'),default_timeout=30).run()
    assert any(progress.proto.text=='0 of 1 recordings complete (0%)' for progress in app.get('progress'))


def test_edit_song_and_audio_privacy(store):
    sid=create_set(store)
    recall.update_set(1,2,sid,'New title','New lyrics',store,'Chapter 2')
    assert recall.sets(1,2)[0]['title']=='New title'
    with pytest.raises(ValueError):recall.update_set(2,2,sid,'Stolen','Lyrics',store,'')
    with pytest.raises(ValueError):recall.save_set(2,2,'Other','Lyrics',[dict(prompt='P',answer='A',keywords='K')],store)
