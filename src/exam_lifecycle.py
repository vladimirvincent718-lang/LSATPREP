"""Delete owned exam attempts and rebuild derived review statistics atomically."""
from src import database


def delete_attempt_rows(conn, user_id, attempt_ids):
    ids = sorted(set(attempt_ids))
    if not ids:
        return
    placeholders = ','.join('?' for _ in ids)
    owned = conn.execute(f'SELECT id FROM exam_attempts WHERE user_id=? AND id IN ({placeholders})', [user_id,*ids]).fetchall()
    if {r[0] for r in owned} != set(ids):
        raise ValueError('One or more exams are not available for this account.')
    questions = [r[0] for r in conn.execute(f'SELECT DISTINCT question_id FROM user_answers WHERE attempt_id IN ({placeholders})', ids)]
    # Preserve a journal item if another remaining attempt also missed that question.
    for row in conn.execute(f'SELECT id,question_id FROM mistake_journal WHERE user_id=? AND attempt_id IN ({placeholders})', [user_id,*ids]).fetchall():
        prior = conn.execute(f'''SELECT ua.attempt_id FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
            WHERE ea.user_id=? AND ua.question_id=? AND ua.is_correct=0 AND ua.selected_answer!=''
            AND ua.attempt_id NOT IN ({placeholders}) ORDER BY ua.submitted_at DESC,ua.id DESC LIMIT 1''', [user_id,row['question_id'],*ids]).fetchone()
        if prior:
            conn.execute('UPDATE mistake_journal SET attempt_id=? WHERE id=?', (prior[0],row['id']))
    for table in ('user_answers','exam_drafts','study_time_entries','question_issue_reports','mistake_journal'):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            conn.execute(f'DELETE FROM {table} WHERE attempt_id IN ({placeholders})', ids)
    conn.execute(f'DELETE FROM exam_attempts WHERE id IN ({placeholders})', ids)
    for qid in questions:
        conn.execute('DELETE FROM user_question_review WHERE user_id=? AND question_id=?', (user_id,qid))
        remaining = conn.execute('''SELECT ua.attempt_id,ua.is_correct,ua.submitted_at FROM user_answers ua
            JOIN exam_attempts ea ON ea.id=ua.attempt_id WHERE ea.user_id=? AND ua.question_id=?
            ORDER BY COALESCE(ua.submitted_at,ea.started_at),ua.id''', (user_id,qid)).fetchall()
        for row in remaining:
            database._update_question_review_state(conn,row['attempt_id'],qid,bool(row['is_correct']), answered_at=row['submitted_at'])


def delete_exam_attempt(user_id, attempt_id):
    from src.offline_exams import _connect, delete_offline_exam
    conn = _connect()
    try:
        linked = conn.execute('SELECT serial FROM offline_exams WHERE user_id=? AND attempt_id=?', (user_id,attempt_id)).fetchone()
        if linked:
            conn.close()
            delete_offline_exam(user_id,linked[0])
            return
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            delete_attempt_rows(conn,user_id,[attempt_id])
    finally:
        conn.close()
