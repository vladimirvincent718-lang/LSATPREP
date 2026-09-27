"""Automatic local speech transcription, queued once per recording."""
import json
import subprocess
import sys
from pathlib import Path

from src import audio_study as store, database


def launch_worker():
    root = Path(__file__).resolve().parent.parent
    bundled = root / '.venv' / 'Scripts' / 'python.exe'
    python = str(bundled) if bundled.exists() else sys.executable
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    subprocess.Popen([python, '-m', 'src.audio_transcription_worker', str(database.DB_PATH.resolve())],
                     cwd=root, creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def queue_transcription(user_id, course_id, audio_id, retry=False):
    """Recheck access; existing transcripts and completed jobs are never replaced."""
    launch = False
    with store.connection() as conn:
        store._accessible(conn, user_id, course_id, audio_id)
        if conn.execute('SELECT 1 FROM audio_transcripts WHERE audio_id=?', (audio_id,)).fetchone():
            return
        job = conn.execute('SELECT *, (julianday("now")-julianday(updated_at))*86400 AS age FROM audio_transcription_jobs WHERE audio_id=?', (audio_id,)).fetchone()
        if job is None:
            conn.execute('INSERT INTO audio_transcription_jobs(audio_id) VALUES (?)', (audio_id,))
            launch = True
        elif retry and job['status'] in ('error', 'empty'):
            conn.execute("UPDATE audio_transcription_jobs SET status='queued',error='',updated_at=CURRENT_TIMESTAMP WHERE audio_id=?", (audio_id,))
            launch = True
        elif job['status'] in ('queued', 'running') and job['age'] > 30:
            conn.execute('UPDATE audio_transcription_jobs SET updated_at=CURRENT_TIMESTAMP WHERE audio_id=?', (audio_id,))
            launch = True
    if launch:
        try:
            launch_worker()
        except OSError:
            with store.connection() as conn:
                conn.execute("UPDATE audio_transcription_jobs SET status='error',error='The transcription service could not start.' WHERE audio_id=?", (audio_id,))


def transcription_state(user_id, course_id, audio_id):
    with store.connection() as conn:
        store._accessible(conn, user_id, course_id, audio_id)
        job = conn.execute('SELECT * FROM audio_transcription_jobs WHERE audio_id=?', (audio_id,)).fetchone()
        text = conn.execute('SELECT text FROM audio_transcripts WHERE audio_id=?', (audio_id,)).fetchone()
    if not job:
        return {'status': 'missing', 'words': []}
    return {'status': job['status'], 'error': job['error'],
            'words': json.loads(job['words']) if text and text['text'] == job['generated_text'] else []}
