from pathlib import Path
from types import SimpleNamespace

import pytest

from src import audio_study, database


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'audio.db')
    from src import audio_transcription
    monkeypatch.setattr(audio_transcription, 'launch_worker', lambda: None)
    database.init_database()
    with audio_study.connection() as conn:
        conn.execute("INSERT INTO users(id,username,password_hash) VALUES (1,'upload-test','x')")
        conn.execute("INSERT OR IGNORE INTO courses(id,title) VALUES (2,'Test course')")
        conn.execute("INSERT INTO course_enrollments(user_id,course_id,enrollment_status) VALUES (1,2,'Active')")
    audio_study.init_audio()
    return tmp_path


def tracks():
    return [dict(title=name, topic='Equity', filename=name, content=b'audio')
            for name in ('FULL_OVERVIEW.m4a', 'PART_IV.m4a')]


def test_batch_saves_every_title_and_validates_before_writing(store):
    recordings = tracks()
    recordings[1]['title'] = 'My fourth section'
    ids = audio_study.save_audio_batch(1, 2, recordings)
    assert len(ids) == 2
    assert {r['title'] for r in audio_study.library(1, 2)} == {'FULL_OVERVIEW.m4a', 'My fourth section'}
    before = set((store / 'study_audio').iterdir())
    recordings[1]['title'] = ' '
    with pytest.raises(ValueError, match='Add a title'):
        audio_study.save_audio_batch(1, 2, recordings)
    assert len(audio_study.library(1, 2)) == 2
    assert set((store / 'study_audio').iterdir()) == before


def test_batch_rolls_back_on_disk_failure(store, monkeypatch):
    original = Path.write_bytes
    writes = 0

    def fail_second(path, content):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError('Disk write failed')
        return original(path, content)

    monkeypatch.setattr(Path, 'write_bytes', fail_second)
    with pytest.raises(OSError, match='Disk write failed'):
        audio_study.save_audio_batch(1, 2, tracks())
    assert not audio_study.library(1, 2)
    assert not list((store / 'study_audio').iterdir())


def test_filename_defaults_preserve_edits_and_save_all_tracks(store, monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    uploads = [SimpleNamespace(name=r['filename'], file_id=str(i), getvalue=lambda: b'audio')
               for i, r in enumerate(tracks())]

    def uploader(*args, **kwargs):
        assert kwargs['accept_multiple_files'] is True
        assert kwargs['max_upload_size'] == audio_study.MAX_AUDIO_UPLOAD_MB == 200
        assert '200 MB per file' in args[0]
        return uploads

    monkeypatch.setattr(st, 'file_uploader', uploader)
    app = AppTest.from_string('from src.audio_upload import render_audio_upload\nrender_audio_upload(1, 2)').run()
    assert not app.exception
    assert app.text_input[1].value == 'FULL_OVERVIEW.m4a'
    assert app.text_input[2].value == 'PART_IV.m4a'
    app.text_input[2].set_value('My custom title').run()
    assert app.text_input[2].value == 'My custom title'
    app.button[0].click().run()
    assert not app.exception
    assert {r['title'] for r in audio_study.library(1, 2)} == {'FULL_OVERVIEW.m4a', 'My custom title'}
