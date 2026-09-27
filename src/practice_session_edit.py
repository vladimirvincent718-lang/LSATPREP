"""Edit a practice session without recycling questions or mixing slot state."""
import re

from src.practice_allocation import module_label
from src.question_ordering import references_previous_question

HISTORY_KEY = 'practice_used_question_ids'
SCOPE_KEY = 'practice_session_modules'
EDIT_ATTEMPT_KEY = 'practice_edit_attempt_id'
INDEX_SETS = ('exam_flagged', 'practice_expanded_answer_idxs',
              'practice_timed_out_questions', 'practice_skipped_questions',
              'practice_reached_questions')
WIDGET_PREFIXES = ('q_radio_', 'q_open_ended_', 'q_self_grade_')


def module_key(question):
    return (question.get('course_id'), question.get('chapter_id'),
            '' if question.get('chapter_id') is not None else module_label(question))


def initialize_edit_state(state):
    questions = state.get('exam_questions') or []
    if state.get(EDIT_ATTEMPT_KEY) != state.get('exam_attempt_id'):
        state[HISTORY_KEY] = set()
        state[SCOPE_KEY] = list(dict.fromkeys(module_key(q) for q in questions))
        state[EDIT_ATTEMPT_KEY] = state.get('exam_attempt_id')
    state[HISTORY_KEY] = set(state.get(HISTORY_KEY) or []) | {
        q['id'] for q in questions if q.get('id') is not None
    }


def refers_to_numbered_question(question):
    text = ' '.join(str(question.get(k) or '') for k in ('passage', 'stimulus'))
    return bool(re.search(r'\bquestion\s+#?\d+\b', text, re.I))


def addition_candidates(state, pool, difficulty):
    scopes = {tuple(key) for key in state[SCOPE_KEY]}
    used = set(state[HISTORY_KEY])
    unique = {}
    for q in pool:
        if (q.get('id') is not None and q['id'] not in used
                and not q.get('is_archived') and module_key(q) in scopes
                and q.get('difficulty') == difficulty
                and not references_previous_question(q)
                and not refers_to_numbered_question(q)):
            unique[q['id']] = q
    return list(unique.values())


def removal_error(questions, idx):
    if not 0 <= idx < len(questions):
        return 'Choose a question to remove.'
    if len(questions) == 1:
        return 'Keep at least one question in the session. Add questions first, or finish this session.'
    if idx + 1 < len(questions) and references_previous_question(questions[idx + 1]):
        return 'The next question uses this question’s information. Remove the dependent question first.'
    return ''


def remove_question_state(state, idx):
    questions = list(state['exam_questions'])
    error = removal_error(questions, idx)
    if error:
        raise ValueError(error)
    initialize_edit_state(state)
    questions.pop(idx)
    state['exam_questions'] = questions
    for key in ('exam_answers', 'exam_self_grades'):
        state[key] = {int(i) - (int(i) > idx): value
                      for i, value in (state.get(key) or {}).items() if int(i) != idx}
    for key in INDEX_SETS:
        state[key] = {int(i) - (int(i) > idx) for i in (state.get(key) or []) if int(i) != idx}
    # Retain unfinished written/radio responses as their slots move.
    for prefix in WIDGET_PREFIXES:
        saved = {}
        for key in list(state):
            suffix = str(key)[len(prefix):]
            if str(key).startswith(prefix) and suffix.isdigit():
                i = int(suffix)
                if i != idx:
                    saved[f'{prefix}{i - (i > idx)}'] = state[key]
                del state[key]
        state.update(saved)
    state['exam_current_idx'] = min(idx, len(questions) - 1)
    for key in ('practice_timeout_notice', 'practice_skipped_notice', 'practice_confirm_finish'):
        state.pop(key, None)


def remove_saved_answer(user_id, attempt_id, question_id):
    """Remove this session's score for an edited-out question, retaining other attempts."""
    from src import database
    conn = database.get_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            attempt = conn.execute('SELECT user_id,completed_at FROM exam_attempts WHERE id=?', (attempt_id,)).fetchone()
            if not attempt or attempt['user_id'] != user_id or attempt['completed_at']:
                raise ValueError('Only your active practice session can be edited.')
            deleted = conn.execute('DELETE FROM user_answers WHERE attempt_id=? AND question_id=?', (attempt_id, question_id))
            if not deleted.rowcount:
                return
            prior = conn.execute('''SELECT ua.attempt_id FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                WHERE ea.user_id=? AND ua.question_id=? AND ua.is_correct=0 AND ua.selected_answer!=''
                ORDER BY ua.submitted_at DESC,ua.id DESC LIMIT 1''', (user_id, question_id)).fetchone()
            if prior:
                conn.execute('UPDATE mistake_journal SET attempt_id=? WHERE user_id=? AND attempt_id=? AND question_id=?',
                             (prior[0], user_id, attempt_id, question_id))
            else:
                conn.execute('DELETE FROM mistake_journal WHERE user_id=? AND attempt_id=? AND question_id=?',
                             (user_id, attempt_id, question_id))
            conn.execute('DELETE FROM user_question_review WHERE user_id=? AND question_id=?', (user_id, question_id))
            remaining = conn.execute('''SELECT ua.attempt_id,ua.is_correct,ua.submitted_at FROM user_answers ua
                JOIN exam_attempts ea ON ea.id=ua.attempt_id WHERE ea.user_id=? AND ua.question_id=?
                ORDER BY COALESCE(ua.submitted_at,ea.started_at),ua.id''', (user_id, question_id)).fetchall()
            for row in remaining:
                database._update_question_review_state(conn, row['attempt_id'], question_id,
                    bool(row['is_correct']), answered_at=row['submitted_at'])
    finally:
        conn.close()
