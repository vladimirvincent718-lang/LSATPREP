import pytest
from src import audio_study as a, database, drive_audio as d

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'test.db')
    a.init_audio()
    blobs={}
    monkeypatch.setattr(d,'configured',lambda u:True)
    def upload(u,n,m,b):
        fid=str(len(blobs)+1);blobs[fid]=(u,b);return fid
    def download(u,f):
        assert blobs[f][0]==u
        return blobs[f][1]
    monkeypatch.setattr(d,'upload',upload)
    monkeypatch.setattr(d,'download',download)
    monkeypatch.setattr(d,'delete',lambda u,f:blobs.pop(f))
    return tmp_path,blobs

def test_drive_privacy_playback_and_no_disk_copy(setup):
    root,blobs=setup;a.enable_drive(1)
    aid=a.save_audio(1,2,'a','','a.mp3',b'audio')
    assert not (root/'study_audio').exists()
    assert a.audio_bytes(1,2,aid)==b'audio'
    with pytest.raises(ValueError):a.audio_bytes(3,2,aid)
    with a.connection() as c:c.execute('INSERT INTO audio_listeners VALUES (?,?)',(aid,3))
    assert a.audio_bytes(3,2,aid)==b'audio'

def test_failed_batch_cleans_up(setup,monkeypatch):
    root,blobs=setup;a.enable_drive(1)
    original=d.upload
    def fail(*args):
        if blobs:raise d.DriveError('quota')
        return original(*args)
    monkeypatch.setattr(d,'upload',fail)
    with pytest.raises(ValueError,match='quota'):
        a.save_audio_batch(1,2,[dict(title='a',topic='',filename='a.mp3',content=b'x')]*2)
    assert not blobs and not a.library(1,2)

def test_migration_keeps_original_metadata_and_is_idempotent(setup):
    root,blobs=setup
    aid=a.save_audio(1,2,'Title','Topic','a.mp3',b'original')
    a.save_transcript(1,2,aid,'Words')
    name=a.library(1,2)[0]['filename']
    a.migrate_to_drive(1,2,aid);a.migrate_to_drive(1,2,aid)
    assert (root/'study_audio'/name).read_bytes()==b'original'
    assert a.audio_bytes(1,2,aid)==b'original'
    assert a.transcript(1,2,aid)=='Words' and len(blobs)==1

def test_auth_failure_no_local_fallback(setup,monkeypatch):
    root,blobs=setup;a.enable_drive(1)
    def fail(*args):raise d.DriveError('Reconnect')
    monkeypatch.setattr(d,'upload',fail)
    with pytest.raises(ValueError,match='Reconnect'):a.save_audio(1,2,'a','','a.mp3',b'x')
    assert not a.library(1,2) and not (root/'study_audio').exists()
