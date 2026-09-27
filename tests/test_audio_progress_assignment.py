import pytest
from src import audio_study as audio, database


@pytest.fixture
def store(monkeypatch,tmp_path):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'study.db')
    database.init_database()
    audio.init_audio()
    with audio.connection() as c:
        c.execute("INSERT INTO users(id,username,password_hash) VALUES (1,'audio-owner','x')")
        for cid in (101,102):
            c.execute('INSERT INTO courses(id,title) VALUES (?,?)',(cid,f'Course {cid}'))
            c.execute("INSERT INTO course_enrollments(user_id,course_id,enrollment_status) VALUES (1,?,'Active')",(cid,))
        c.execute("INSERT INTO course_areas(id,course_id,name) VALUES (9001,101,'Area A'),(9002,102,'Area B')")
        c.execute("INSERT INTO course_module_blueprints(id,course_id,area_id,name) VALUES (301,101,9001,'Module A'),(302,101,9001,'Module B'),(303,102,9002,'Module C')")
        c.execute('''CREATE TABLE IF NOT EXISTS course_chapters(id INTEGER PRIMARY KEY,course_id INTEGER,module_id INTEGER,name TEXT,subgroup TEXT DEFAULT '',display_order INTEGER DEFAULT 0)''')
        c.execute("INSERT INTO course_chapters(id,course_id,module_id,name) VALUES (401,101,301,'Chapter A'),(402,101,302,'Chapter B')")
    return audio.save_audio(1,101,'Overview','', 'overview.mp3', b'audio')


def event(sequence,position,processed,seconds=0,ranges=None):
    return dict(session='player',sequence=sequence,duration=100,seconds=seconds,ranges=ranges or [],position=position,processed_until=processed)


def test_seek_progress_resume_and_duplicate_delivery(store):
    first=event(0,60,60)
    audio.record_event(1,101,store,first)
    assert audio.progress(1,101,store)==dict(position=60,processed_until=60,duration=100)
    stats=audio.analytics(1,101,store)
    assert stats['processed_percent']==60 and stats['seconds']==0 and stats['percent']==0
    audio.record_event(1,101,store,event(2,20,60))
    audio.record_event(1,101,store,first)
    audio.record_event(1,101,store,event(1,70,70))
    audio.init_audio()
    assert audio.progress(1,101,store)['position']==20
    assert audio.progress(1,101,store)['processed_until']==70
    with pytest.raises(ValueError):audio.progress(2,101,store)
    with pytest.raises(ValueError):audio.record_event(1,101,store,event(3,101,101))


def test_comment_submission_is_idempotent_and_private(store):
    audio.record_event(1,101,store,event(0,12,12))
    args=(1,101,store,10,12,'Remember this explanation','Red')
    first=audio.save_mark(*args,submission_id='comment-1')
    assert audio.save_mark(*args,submission_id='comment-1')==first
    assert len(audio.marks(1,101,store))==1
    with pytest.raises(ValueError):audio.save_mark(2,101,store,10,12,'Not mine','Green',submission_id='comment-1')


def test_overview_multiple_modules_chapters_and_reassignment(store):
    assert audio.targets(1,101,store)==[dict(course_id=101,module_id=0,chapter_id=0)]
    audio.set_targets(1,101,[store],[dict(course_id=101),dict(course_id=102)])
    assert audio.library(1,102)[0]['id']==store
    assert not audio.library(2,102)
    assert audio.audio_bytes(1,102,store)==b'audio'
    audio.set_targets(1,101,[store],[dict(course_id=101,module_id=301),dict(course_id=101,module_id=302)])
    assert len(audio.targets(1,101,store))==2 and not audio.library(1,102)
    audio.set_targets(1,101,[store],[dict(course_id=101,module_id=301,chapter_id=401),dict(course_id=101,module_id=302,chapter_id=402)])
    assert {t['chapter_id'] for t in audio.targets(1,101,store)}=={401,402}
    with pytest.raises(ValueError):audio.set_targets(1,101,[store],[dict(course_id=101,module_id=303)])
    with pytest.raises(ValueError):audio.set_targets(1,101,[store],[dict(course_id=101,module_id=301,chapter_id=402)])
    with pytest.raises(ValueError):audio.set_targets(1,101,[store],[dict(course_id=999)])
    assert len(audio.targets(1,101,store))==2


def test_batch_assignment_preserves_original_files_and_notes(store):
    second=audio.save_audio(1,101,'Part II','', 'part2.mp3', b'second audio')
    audio.record_event(1,101,store,event(0,10,10))
    audio.save_mark(1,101,store,5,7,'My note','Neutral')
    audio.set_targets(1,101,[store,second],[dict(course_id=102,module_id=303)])
    assert not audio.library(1,101)
    assert {r['id'] for r in audio.library(1,102)}=={store,second}
    assert audio.marks(1,102,store)[0]['note']=='My note'
    assert audio.progress(1,102,store)['processed_until']==10
    assert audio.audio_bytes(1,102,second)==b'second audio'


def test_assignment_picker_can_choose_multiple_modules_and_chapters(store):
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('''from src.audio_assignment import assignment_picker
import streamlit as st
selected=assignment_picker(1,101,'test')
st.session_state['picked']=selected
''').run()
    assert not app.exception
    app.radio[0].set_value('Modules').run()
    next(m for m in app.multiselect if m.label=='Modules covered').set_value([301,302]).run()
    assert len(app.session_state['picked'])==2
    app.radio[0].set_value('Chapters').run()
    next(m for m in app.multiselect if m.label=='Chapters covered').set_value([401,402]).run()
    assert {t['chapter_id'] for t in app.session_state['picked']}=={401,402}


def invite_listener(store):
    with audio.connection() as c:
        c.execute("INSERT INTO users(id,username,password_hash) VALUES (2,'listener','x')")
        c.execute("INSERT INTO course_enrollments(user_id,course_id,enrollment_status) VALUES (2,101,'Active')")
    audio.share_audio(1,101,store,'listener')


def test_shared_recording_highlights_are_private_and_revocable(store):
    audio.record_event(1,101,store,event(0,0,0))
    invite_listener(store)
    audio.save_highlight(1,101,store,10,12,'Owner words','owner-highlight')
    audio.save_highlight(2,101,store,20,24,'Listener words','listener-highlight')
    assert [h['id'] for h in audio.highlights(1,101,store)]==['owner-highlight']
    assert [h['id'] for h in audio.highlights(2,101,store)]==['listener-highlight']
    with pytest.raises(ValueError):audio.delete_highlight(2,101,store,'owner-highlight')
    audio.init_audio()
    assert audio.highlights(2,101,store)[0]['quote']=='Listener words'
    audio.unshare_audio(1,101,store,2)
    with pytest.raises(ValueError):audio.highlights(2,101,store)
    with pytest.raises(ValueError):audio.save_highlight(2,101,store,20,24,'Revoked','revoked')


def test_thread_replies_authorship_permissions_and_revocation(store):
    audio.record_event(1,101,store,event(0,12,12))
    root=audio.save_mark(1,101,store,10,12,'First thought','Red')
    invite_listener(store)
    reply=audio.save_mark(2,101,store,0,0,'My reply','Green',parent_id=root)
    nested=audio.save_mark(1,101,store,0,0,'Follow-up','Neutral',parent_id=reply)
    notes={m['id']:m for m in audio.marks(2,101,store)}
    assert notes[reply]['start']==10 and notes[reply]['end']==12
    assert notes[reply]['author']=='listener' and notes[reply]['can_edit']
    assert not notes[root]['can_edit'] and notes[nested]['parent_id']==reply
    with pytest.raises(ValueError):audio.save_mark(2,101,store,10,12,'Changed','Red',mark_id=root)
    with pytest.raises(ValueError):audio.save_mark(2,101,store,0,0,'Wrong parent','Neutral',parent_id=99999)
    audio.delete_mark(1,101,store,root)
    assert audio.marks(1,101,store)[0]['is_deleted']==1
    assert len(audio.marks(1,101,store))==3
    assert audio.library(2,101)[0]['id']==store
    audio.unshare_audio(1,101,store,2)
    assert not audio.library(2,101)
    with pytest.raises(ValueError):audio.audio_bytes(2,101,store)
    with pytest.raises(ValueError):audio.save_mark(2,101,store,0,0,'Revoked','Neutral',parent_id=reply)


def test_play_counts_retries_restarts_and_personal_progress(store):
    audio.record_event(1,101,store,event(0,60,60))
    assert audio.play_count(1,101,store)==0
    first=dict(event(1,62,62,2,[[60,62]]),play_id='first-play')
    audio.record_event(1,101,store,first)
    audio.record_event(1,101,store,dict(first,play_id='retry-must-not-count'))
    audio.record_event(1,101,store,dict(event(2,64,64,2,[[62,64]]),play_id='first-play'))
    assert audio.play_count(1,101,store)==1
    audio.record_event(1,101,store,dict(event(3,2,2,2,[[0,2]]),play_id='restarted-play'))
    audio.init_audio()
    assert audio.play_count(1,101,store)==2
    assert audio.progress(1,101,store)['position']==2
    assert audio.progress(1,101,store)['processed_until']==64
    invite_listener(store)
    listener=dict(event(0,10,10,10,[[0,10]]),session='listener-session',play_id='listener-play')
    audio.record_event(2,101,store,listener)
    assert audio.play_count(1,101,store)==3
    assert audio.library(2,101)[0]['play_count']==3
    assert audio.progress(2,101,store)['position']==10
    assert audio.progress(1,101,store)['position']==2
    assert audio.analytics(2,101,store)['plays']==1
    assert audio.analytics(1,101,store)['plays']==2
    with pytest.raises(ValueError):audio.record_event(2,101,store,dict(listener,session='player',sequence=4))


def test_legacy_play_count_backfilled_once(store):
    audio.record_event(1,101,store,event(0,5,5,5,[[0,5]]))
    audio.init_audio()
    audio.init_audio()
    assert audio.play_count(1,101,store)==1


def test_transcript_export_sharing_and_owner_edits(store):
    assert audio.transcript(1,101,store)==''
    original='Price and yield move inversely.\nCoupon: café — 5%.'
    audio.save_transcript(1,101,store,original)
    audio.init_audio()
    assert audio.transcript(1,101,store)==original
    with pytest.raises(ValueError):audio.transcript(2,101,store)
    invite_listener(store)
    assert audio.transcript(2,101,store)==original
    with pytest.raises(ValueError):audio.save_transcript(2,101,store,'Changed')
    with pytest.raises(ValueError):audio.save_transcript(1,101,store,'  ')
    audio.save_transcript(1,101,store,'Corrected transcript')
    assert audio.transcript(1,101,store)=='Corrected transcript'
    audio.unshare_audio(1,101,store,2)
    with pytest.raises(ValueError):audio.transcript(2,101,store)


def test_transcript_options_and_editor(store):
    from streamlit.testing.v1 import AppTest
    from src.audio_transcript import transcript_filename
    assert transcript_filename('Lecture.m4a')=='Lecture_transcript.txt'
    app=AppTest.from_string('''from src import audio_study
from src.audio_transcript import render_transcript
render_transcript(1,101,audio_study.library(1,101)[0])
''').run()
    assert not app.exception
    assert len(app.text_area)==0
    assert len(app.code)==0
    assert len(app.expander)==1
    assert app.expander[0].label=='Transcript options'
    assert app.expander[0].proto.expanded is False
    audio.save_transcript(1,101,store,'A transcript ready for ChatGPT.')
    app.run()
    assert not app.exception
    assert len(app.text_area)==0


def test_completion_manual_override_does_not_fake_listening(store):
    assert not audio.completion(1,101,store)['completed']
    audio.set_completion(1,101,store,True)
    assert audio.completion(1,101,store)=={'completed':True,'source':'manual'}
    assert audio.library(1,101)[0]['completion']['completed']
    assert audio.analytics(1,101,store)['seconds']==0
    assert audio.analytics(1,101,store)['percent']==0
    audio.set_completion(1,101,store,False)
    audio.record_event(1,101,store,event(0,100,100,100,[[0,100]]))
    assert audio.completion(1,101,store)=={'completed':False,'source':'manual'}
    audio.init_audio()
    assert not audio.completion(1,101,store)['completed']
    with pytest.raises(ValueError):audio.set_completion(2,101,store,True)
    with pytest.raises(ValueError):audio.set_completion(1,101,store,'true')


def test_automatic_completion_uses_coverage_across_visits_not_seeking(store):
    audio.record_event(1,101,store,event(0,100,100))
    assert not audio.completion(1,101,store)['completed']
    audio.record_event(1,101,store,event(1,50,100,50,[[0,50]]))
    assert not audio.completion(1,101,store)['completed']
    next_visit=event(0,95,95,45,[[50,95]])
    next_visit['session']='second-visit'
    audio.record_event(1,101,store,next_visit)
    assert audio.completion(1,101,store)=={'completed':True,'source':'automatic'}
    audio.record_event(1,101,store,event(2,0,100))
    assert audio.completion(1,101,store)['completed']
    # Older history is recognized even without a saved completion record.
    with audio.connection() as conn:conn.execute('DELETE FROM audio_completion')
    assert audio.completion(1,101,store)['completed']
    audio.set_completion(1,101,store,False)
    audio.record_event(1,101,store,event(3,100,100,50,[[50,100]]))
    assert not audio.completion(1,101,store)['completed']


def test_shared_recording_completion_is_per_listener(store):
    with audio.connection() as conn:
        conn.execute("INSERT INTO users(id,username,password_hash) VALUES (2,'completion-listener','x')")
        conn.execute("INSERT INTO course_enrollments(user_id,course_id,enrollment_status) VALUES (2,101,'Active')")
    audio.share_audio(1,101,store,'completion-listener')
    audio.set_completion(2,101,store,True)
    assert audio.completion(2,101,store)['completed']
    assert not audio.completion(1,101,store)['completed']
    audio.unshare_audio(1,101,store,2)
    with pytest.raises(ValueError):audio.completion(2,101,store)
    with pytest.raises(ValueError):audio.set_completion(2,101,store,False)
