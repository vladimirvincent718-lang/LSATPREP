import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from src import audio_study as audio, audio_tutors as tutors, database, tutor_providers as providers
from src import audio_tutor_worker as worker


@pytest.fixture
def recording(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'audio.db')
    audio.init_audio()
    with audio.connection() as c:
        c.execute("INSERT INTO study_audio(id,user_id,course_id,title,filename,mime,duration) VALUES (1,1,2,'Lecture','x.wav','audio/wav',3600)")
    monkeypatch.setattr(providers, 'has_key', lambda *args: True)
    monkeypatch.setattr(tutors, 'now', lambda: 1_000_000.0)
    tutors.save_settings(1, {**tutors.DEFAULTS, 'enabled': True})
    return 1


def comment(text='What does this mean?', parent=None, submission=None):
    return audio.save_mark(1,2,1,120,125,text,'Neutral',parent_id=parent,submission_id=submission)


def jobs():
    with audio.connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM audio_tutor_jobs ORDER BY id')]


def thread(root):
    with audio.connection() as c:
        return dict(c.execute('SELECT * FROM audio_tutor_threads WHERE root_id=?',(root,)).fetchone())


def finish(job, text='Explanation at [2:00].', followup=True):
    tutors.finish_job(job, dict(needs_followup=followup, reply=text))


def test_comment_is_flag_and_duplicate_submission_is_not_new_work(recording):
    root=comment(submission='same')
    assert comment(submission='same')==root
    assert thread(root)['state']=='open'
    assert thread(root)['revision']==1
    assert len(jobs())==2
    assert jobs()[1]['due_at']==1_086_400
    assert tutors.settings(9)['enabled'] is False


def test_only_one_reply_and_one_review_no_ai_loop(recording):
    root=comment()
    first=tutors.claim_job()
    assert first['provider']=='gemini'
    assert tutors.claim_job() is None
    finish(first);finish(first)  # Provider completion replay is harmless.
    assert tutors.claim_job() is None
    review=tutors.claim_job(1_086_401)
    assert review['provider']=='openai'
    assert review['context']['conversation'][-1]['author']=='AI Tutor · Gemini'
    finish(review,'A clarification at [2:00].')
    assert tutors.claim_job(9_000_000) is None
    assert len(jobs())==2 and thread(root)['revision']==1
    marks=audio.marks(1,2,1)
    assert len(marks)==3
    assert [m['author'] for m in marks[1:]]==['AI Tutor · Gemini','AI Tutor · ChatGPT']
    assert all(m['unread'] for m in marks[1:])
    tutors.read_replies(1,2,1,root)
    assert not any(m['unread'] for m in audio.marks(1,2,1))


def test_quiet_review_does_not_post_or_notify(recording):
    comment();finish(tutors.claim_job())
    finish(tutors.claim_job(1_086_401),'',False)
    assert len(audio.marks(1,2,1))==2
    assert jobs()[1]['status']=='quiet'
    tutors.save_settings(1,tutors.settings(1))
    assert tutors.claim_job(9_000_000) is None


def test_closing_during_generation_discards_output_and_human_reopens(recording):
    root=comment();job=tutors.claim_job()
    tutors.set_help(1,2,1,root,False)
    finish(job)
    assert len(audio.marks(1,2,1))==1
    assert all(j['status']=='cancelled' for j in jobs())
    assert tutors.claim_job(9_000_000) is None
    comment('I have another question',parent=root)
    assert thread(root)['state']=='open'
    assert tutors.claim_job()['revision']!=job['revision']


def test_new_comment_invalidates_running_answer_and_resets_review(recording,monkeypatch):
    root=comment();old=tutors.claim_job()
    monkeypatch.setattr(tutors,'now',lambda:1_000_600.0)
    comment('More context',parent=root)
    finish(old)
    assert len(audio.marks(1,2,1))==2
    fresh=tutors.claim_job()
    assert fresh['context']['conversation'][-1]['text']=='More context'
    assert jobs()[-1]['due_at']==1_087_000


def test_pausing_or_deleting_during_call_prevents_publication(recording):
    root=comment();job=tutors.claim_job()
    tutors.save_settings(1,{**tutors.settings(1),'enabled':False})
    finish(job)
    assert len(audio.marks(1,2,1))==1
    assert tutors.claim_job(9_000_000) is None
    tutors.save_settings(1,{**tutors.settings(1),'enabled':True})
    tutors.set_help(1,2,1,root,False);tutors.set_help(1,2,1,root,True)
    job=tutors.claim_job()
    audio.delete_mark(1,2,1,root)
    finish(job)
    assert not audio.marks(1,2,1)


def test_unauthorized_controls_and_access_revocation(recording):
    root=comment()
    with pytest.raises(ValueError):tutors.set_help(2,2,1,root,False)
    with pytest.raises(ValueError):tutors.read_replies(2,2,1,root)
    job=tutors.claim_job()
    with audio.connection() as c:c.execute('UPDATE study_audio SET user_id=3 WHERE id=1')
    finish(job)
    with audio.connection() as c:
        assert c.execute('SELECT COUNT(*) FROM audio_marks').fetchone()[0]==1
    assert jobs()[0]['status']=='cancelled'


def test_call_limit_counts_failures_and_simultaneous_claims(recording):
    tutors.save_settings(1,{**tutors.settings(1),'call_limit':1})
    comment();comment('Another question')
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed=list(pool.map(lambda _:tutors.claim_job(),range(2)))
    assert sum(j is not None for j in claimed)==1
    job=next(j for j in claimed if j)
    tutors.fail_job(job,'Provider unavailable')
    assert tutors.claim_job() is None
    assert tutors.claim_job(1_086_402) is not None
    assert next(j for j in jobs() if j['id']==job['id'])['status']=='error'


def test_settings_adjust_unstarted_cadence_and_disable_review(recording):
    root=comment()
    tutors.save_settings(1,{**tutors.settings(1),'reply_minutes':15,'review_hours':2})
    assert [j['due_at'] for j in jobs()]==[1_000_900,1_007_200]
    assert tutors.claim_job() is None
    tutors.save_settings(1,{**tutors.settings(1),'reviewer':'none'})
    assert jobs()[1]['status']=='cancelled'
    for value in [float('nan'),-1,200]:
        with pytest.raises(ValueError):tutors.save_settings(1,{**tutors.settings(1),'review_hours':value})


def test_no_key_blocks_without_consuming_call(recording,monkeypatch):
    root=comment()
    monkeypatch.setattr(providers,'has_key',lambda *args:False)
    assert tutors.claim_job() is None
    assert jobs()[0]['status']=='blocked' and jobs()[0]['started_at'] is None
    monkeypatch.setattr(providers,'has_key',lambda *args:True)
    assert tutors.claim_job() is not None


def test_worker_failure_is_terminal_not_retried(recording,monkeypatch):
    comment()
    def failed(job):raise providers.TutorError('Rate limit reached')
    monkeypatch.setattr(worker,'generate',failed)
    assert worker.process_once() is True
    assert worker.process_once() is False
    assert jobs()[0]['status']=='error'


def test_transcript_context_and_export_respect_actual_timings(recording):
    words=[dict(text='Early',start=0,end=1,cue=0),dict(text='Relevant',start=120,end=121,cue=1),dict(text='words.',start=121,end=122,cue=1),dict(text='Late',start=3000,end=3001,cue=2)]
    text='Early Relevant words. Late'
    audio.save_transcript(1,2,1,text)
    with audio.connection() as c:c.execute('INSERT INTO audio_transcription_jobs(audio_id,words,generated_text) VALUES (?,?,?)',(1,json.dumps(words),text))
    comment();job=tutors.claim_job()
    assert job['context']['transcript']=='[2:00] Relevant words.'
    assert tutors.transcript_export(text,words,True)=='[0:00] Early\n\n[2:00] Relevant words.\n\n[50:00] Late'
    assert '[2:00]' not in tutors.transcript_export(text,words,False)
    assert tutors.transcript_export('WEBVTT\n\n00:02.000 --> 00:04.000\nHello',[],False)=='Hello'
    audio.save_transcript(1,2,1,'Corrected plain text')
    with audio.connection() as c:context=tutors.build_context(c,job)
    assert context['transcript']=='Corrected plain text'
    assert context['transcript_has_real_timestamps'] is False
    context,timed=tutors.transcript_context('[0:00] Early\n[2:00] Relevant\n[50:00] Late',[],120,125)
    assert 'Relevant' in context and 'Late' not in context and timed
