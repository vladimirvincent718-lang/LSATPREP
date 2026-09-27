from types import SimpleNamespace

import pytest

from src import audio_study as audio, audio_transcription as jobs, database
from src.audio_transcription_worker import process_job, transcribe


@pytest.fixture
def recording(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'audio.db')
    database.init_database()
    audio.init_audio()
    with audio.connection() as conn:
        conn.execute("INSERT INTO users(id,username,password_hash) VALUES (1,'owner','x')")
        conn.execute("INSERT INTO courses(id,title) VALUES (101,'Audio')")
        conn.execute("INSERT INTO course_enrollments(user_id,course_id,enrollment_status) VALUES (1,101,'Active')")
    return audio.save_audio(1, 101, 'Speech', '', 'speech.wav', b'content')


class SpeechModel:
    def transcribe(self, content, **options):
        assert content.read() == b'content'
        assert options['word_timestamps'] is True
        words = [SimpleNamespace(word=' Hello', start=2.0, end=2.4),
                 SimpleNamespace(word=' world.', start=2.7, end=3.1)]
        return iter([SimpleNamespace(text=' Hello world.', words=words)]), None


def test_queue_is_private_and_idempotent(recording, monkeypatch):
    starts = []
    monkeypatch.setattr(jobs, 'launch_worker', lambda: starts.append(True))
    with pytest.raises(ValueError):
        jobs.queue_transcription(2, 101, recording)
    jobs.queue_transcription(1, 101, recording)
    jobs.queue_transcription(1, 101, recording)
    assert starts == [True]
    assert jobs.transcription_state(1, 101, recording)['status'] == 'queued'


def test_recognized_words_persist_and_manual_changes_invalidate_timings(recording, monkeypatch):
    monkeypatch.setattr(jobs, 'launch_worker', lambda: None)
    jobs.queue_transcription(1, 101, recording)
    process_job(database.DB_PATH, {'audio_id': recording, 'user_id': 1, 'course_id': 101}, SpeechModel())
    assert audio.transcript(1, 101, recording) == 'Hello world.'
    state = jobs.transcription_state(1, 101, recording)
    assert state['status'] == 'ready'
    assert [(word['start'], word['end']) for word in state['words']] == [(2, 2.4), (2.7, 3.1)]
    audio.save_transcript(1, 101, recording, 'Corrected words')
    assert jobs.transcription_state(1, 101, recording)['words'] == []
    jobs.queue_transcription(1, 101, recording, retry=True)
    assert audio.transcript(1, 101, recording) == 'Corrected words'


def test_existing_transcript_is_preserved_even_during_job(recording, monkeypatch):
    monkeypatch.setattr(jobs, 'launch_worker', lambda: None)
    jobs.queue_transcription(1, 101, recording)
    audio.save_transcript(1, 101, recording, 'Existing text')
    process_job(database.DB_PATH, {'audio_id': recording, 'user_id': 1, 'course_id': 101}, SpeechModel())
    assert audio.transcript(1, 101, recording) == 'Existing text'
    assert jobs.transcription_state(1, 101, recording)['words'] == []


def test_silence_finishes_without_inventing_words(recording, monkeypatch):
    monkeypatch.setattr(jobs, 'launch_worker', lambda: None)
    jobs.queue_transcription(1, 101, recording)
    model = SimpleNamespace(transcribe=lambda *args, **kwargs: (iter([]), None))
    assert transcribe(model, b'content') == ('', [])
    process_job(database.DB_PATH, {'audio_id': recording, 'user_id': 1, 'course_id': 101}, model)
    assert jobs.transcription_state(1, 101, recording)['status'] == 'empty'
    assert audio.transcript(1, 101, recording) == ''
    starts = []
    monkeypatch.setattr(jobs, 'launch_worker', lambda: starts.append(True))
    jobs.queue_transcription(1, 101, recording)
    assert not starts
    jobs.queue_transcription(1, 101, recording, retry=True)
    assert starts == [True]
