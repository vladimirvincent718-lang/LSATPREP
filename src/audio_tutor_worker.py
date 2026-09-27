"""One detached scheduler per database; no automatic retries or AI reply loops."""
import os
import sys
import time
from pathlib import Path

from src import audio_tutors as tutors, database
from src.tutor_providers import generate, TutorError


def process_once():
    job = tutors.claim_job()
    if not job:
        return False
    try:
        tutors.finish_job(job, generate(job))
    except TutorError as exc:
        tutors.fail_job(job, str(exc))
    except Exception:
        tutors.fail_job(job, 'The tutor could not finish. Reopen help to request a new attempt.')
    return True


def main(path):
    database.DB_PATH = Path(path)
    lock = open(Path(path).with_suffix('.tutors.lock'), 'a+b')
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
        with tutors.store.connection() as c:
            # A crash may have happened after billing. Never replay uncertain requests.
            c.execute("UPDATE audio_tutor_jobs SET status='error',error='The worker stopped during this request. Reopen help to retry.' WHERE status='running'")
        while True:
            with tutors.store.connection() as c:
                c.execute('INSERT OR REPLACE INTO audio_tutor_worker_state VALUES (1,?)', (tutors.now(),))
                active = any(tutors.settings(r['user_id'], c)['enabled'] for r in c.execute('''
                  SELECT DISTINCT t.user_id FROM audio_tutor_threads t JOIN audio_tutor_jobs j ON j.root_id=t.root_id
                  WHERE t.state='open' AND j.status IN ('queued','blocked')'''))
            if not active:
                break
            if not process_once():
                time.sleep(10)
    finally:
        with tutors.store.connection() as c:
            c.execute('DELETE FROM audio_tutor_worker_state WHERE id=1')
        lock.close()


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
