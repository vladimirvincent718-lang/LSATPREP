"""One local CPU worker per database, with durable jobs and speech word timings."""
import io
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path):
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def transcribe(model, content):
    segments, _ = model.transcribe(io.BytesIO(content), word_timestamps=True, vad_filter=True, beam_size=5)
    words = []
    passages = []
    for index, segment in enumerate(segments):
        if segment.text.strip():
            passages.append(segment.text.strip())
        for word in segment.words or []:
            if word.word.strip() and word.end > word.start:
                words.append(dict(text=word.word.strip(), start=max(0, word.start), end=word.end, cue=index))
    return '\n\n'.join(passages), words


def process_job(path, job, model):
    from src import audio_study as store, database
    database.DB_PATH = Path(path)
    content = store.audio_bytes(job['user_id'], job['course_id'], job['audio_id'])
    text, words = transcribe(model, content)
    with connect(path) as conn:
        if not conn.execute('SELECT 1 FROM study_audio WHERE id=?', (job['audio_id'],)).fetchone():
            conn.execute('DELETE FROM audio_transcription_jobs WHERE audio_id=?', (job['audio_id'],))
            return
        if text:
            conn.execute('INSERT OR IGNORE INTO audio_transcripts(audio_id,text) VALUES (?,?)', (job['audio_id'], text))
        conn.execute('UPDATE audio_transcription_jobs SET status=?,words=?,generated_text=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE audio_id=?',
                     ('ready' if text else 'empty', json.dumps(words), text,
                      '' if text else 'No speech was detected in this recording.', job['audio_id']))


def main(path):
    # A filesystem lock prevents parallel models, including across app restarts.
    lock = open(Path(path).with_suffix('.transcription.lock'), 'a+b')
    lock.seek(0)
    if os.name == 'nt':
        import msvcrt
        if lock.read(1) == b'':
            lock.write(b'0');lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock.close();return
    else:
        import fcntl
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close();return
    try:
        with connect(path) as conn:
            conn.execute("UPDATE audio_transcription_jobs SET status='queued' WHERE status='running'")
        model = None
        idle = 0
        while idle < 30:
            with connect(path) as conn:
                job = conn.execute("SELECT j.audio_id,a.user_id,a.course_id FROM audio_transcription_jobs j JOIN study_audio a ON a.id=j.audio_id WHERE j.status='queued' ORDER BY j.audio_id LIMIT 1").fetchone()
                if job:
                    conn.execute("UPDATE audio_transcription_jobs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE audio_id=?", (job['audio_id'],))
            if not job:
                idle += 1;time.sleep(1);continue
            idle = 0
            stop = threading.Event()
            def heartbeat(audio_id=job['audio_id']):
                while not stop.wait(10):
                    with connect(path) as conn:
                        conn.execute("UPDATE audio_transcription_jobs SET updated_at=CURRENT_TIMESTAMP WHERE audio_id=? AND status='running'", (audio_id,))
            thread = threading.Thread(target=heartbeat, daemon=True);thread.start()
            try:
                if model is None:
                    from faster_whisper import WhisperModel
                    model = WhisperModel('base', device='cpu', compute_type='int8', cpu_threads=4,
                                         download_root=str(Path(path).parent / 'speech_models'))
                process_job(path, job, model)
            except Exception as exc:
                # Keep private file paths and provider details out of the product UI.
                message = 'Automatic transcription could not finish. Retry from Transcript options.'
                if isinstance(exc, ImportError):
                    message = 'The local transcription dependencies are not installed.'
                with connect(path) as conn:
                    conn.execute("UPDATE audio_transcription_jobs SET status='error',error=?,updated_at=CURRENT_TIMESTAMP WHERE audio_id=?", (message, job['audio_id']))
            finally:
                stop.set();thread.join()
    finally:
        lock.close()


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
