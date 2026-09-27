"""Durable, user-owned PDF exam snapshots and validated submissions."""
from __future__ import annotations

import json
import uuid
from io import BytesIO

from pypdf import PdfReader
from src import database
from src.pdf_export import display_exam_number, generate_exam_pdf, _choices


def _connect():
    conn = database.get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS offline_exams (
        serial TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        attempt_id INTEGER, title TEXT NOT NULL, questions_json TEXT NOT NULL,
        pdf BLOB NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        submitted_at TEXT, result_json TEXT,
        UNIQUE(attempt_id)
    )""")
    conn.commit()
    return conn


def is_closed(record):
    return bool(record.get('submitted_at') or record.get('result_json') or record.get('completed_at'))


def delete_offline_exam(user_id, serial):
    from src.exam_lifecycle import delete_attempt_rows
    conn = _connect()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT attempt_id FROM offline_exams WHERE user_id=? AND serial=?', (user_id,serial)).fetchone()
            if not row:
                raise ValueError('This exam is not available for this account.')
            for table in ('offline_self_assessments','offline_email_tokens'):
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (table,)).fetchone():
                    conn.execute(f'DELETE FROM {table} WHERE user_id=? AND serial=?', (user_id,serial))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='offline_email_receipts' AND type='table'").fetchone():
                conn.execute('DELETE FROM offline_email_receipts WHERE instr(subject,?)>0', (serial,))
            conn.execute('DELETE FROM offline_exams WHERE user_id=? AND serial=?', (user_id,serial))
            if row['attempt_id']:
                delete_attempt_rows(conn,user_id,[row['attempt_id']])
    finally:
        conn.close()


def reconcile_active_exam(user_id):
    import streamlit as st
    aid = st.session_state.get('exam_attempt_id')
    if not aid or not st.session_state.get('exam_active'):
        return
    conn = database.get_connection()
    try:
        attempt = conn.execute('SELECT completed_at FROM exam_attempts WHERE id=? AND user_id=?', (aid,user_id)).fetchone()
    finally:
        conn.close()
    if not attempt or attempt['completed_at']:
        from src.exam_engine import clear_quiz
        clear_quiz(delete_draft=False)
        st.info('This exam was completed or deleted elsewhere. Its active session has been closed.')


def export_offline_exam(*, user_id, attempt_id=None, replace_changed_questions=False, **kwargs):
    """Reserve a unique serial and store the exact downloadable document."""
    conn = _connect()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if attempt_id is not None:
                owner = conn.execute("SELECT user_id FROM exam_attempts WHERE id=?", (attempt_id,)).fetchone()
                if not owner or owner[0] != user_id:
                    raise ValueError("Exam is not available for this account.")
                existing = conn.execute("SELECT * FROM offline_exams WHERE attempt_id=? AND user_id=?", (attempt_id, user_id)).fetchone()
                if existing:
                    old_questions = json.loads(existing['questions_json'])
                    changed = [q.get('id') for q in old_questions] != [q.get('id') for q in kwargs['questions']]
                    if not replace_changed_questions or not changed:
                        return bytes(existing['pdf'])
                    attempt = conn.execute('SELECT completed_at FROM exam_attempts WHERE id=?', (attempt_id,)).fetchone()
                    if is_closed(dict(existing)) or attempt['completed_at']:
                        raise ValueError('Completed exams keep their original PDF.')
                    # Keep downloaded copies valid, but never let their answers
                    # flow back into the practice attempt with different questions.
                    conn.execute('UPDATE offline_exams SET attempt_id=NULL WHERE serial=?', (existing['serial'],))
                    kwargs['title'] = existing['title']
                    old_pdf = PdfReader(BytesIO(existing['pdf']))
                    kwargs['include_answer_key'] = any('Answer Key' in (page.extract_text() or '') for page in old_pdf.pages)
            token = uuid.uuid4().hex[:8].upper()
            serial = f"EX-{token[:4]}-{token[4:]}"
            while conn.execute("SELECT 1 FROM offline_exams WHERE serial=?", (serial,)).fetchone():
                token = uuid.uuid4().hex[:8].upper()
                serial = f"EX-{token[:4]}-{token[4:]}"
            pdf = generate_exam_pdf(**kwargs, exam_serial=serial)
            conn.execute("""INSERT INTO offline_exams
                (serial,user_id,attempt_id,title,questions_json,pdf) VALUES (?,?,?,?,?,?)""",
                (serial, user_id, attempt_id, kwargs['title'], json.dumps(kwargs['questions']), pdf))
        return pdf
    finally:
        conn.close()


def list_offline_exams(user_id):
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute("""SELECT o.serial,o.title,o.created_at,
            o.submitted_at,o.result_json,o.attempt_id,a.completed_at,o.questions_json
            FROM offline_exams o LEFT JOIN exam_attempts a ON a.id=o.attempt_id
            WHERE o.user_id=? ORDER BY o.created_at DESC, o.serial""", (user_id,))]
    finally:
        conn.close()


def get_offline_exam(user_id, serial):
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM offline_exams WHERE user_id=? AND serial=?", (user_id, serial)).fetchone()
        if not row:
            raise ValueError("This exam is not available for this account.")
        return dict(row)
    finally:
        conn.close()


def refresh_offline_pdf_layout(user_id, serial):
    """Rebuild an outstanding saved PDF without changing its serial or questions."""
    record = get_offline_exam(user_id, serial)
    if record.get('submitted_at') or record.get('result_json'):
        raise ValueError('Submitted exams keep the exact PDF that was graded.')
    conn = database.get_connection()
    try:
        if record.get('attempt_id'):
            attempt = conn.execute('SELECT completed_at FROM exam_attempts WHERE id=? AND user_id=?',
                                   (record['attempt_id'], user_id)).fetchone()
            if not attempt or attempt['completed_at']:
                raise ValueError('Completed exams keep their original PDF.')
    finally:
        conn.close()
    old_reader = PdfReader(BytesIO(record['pdf']))
    include_answer_key = any('Answer Key' in (page.extract_text() or '') for page in old_reader.pages)
    questions = json.loads(record['questions_json'])
    pdf = generate_exam_pdf(
        questions,
        record['title'],
        subtitle='Phone-friendly offline practice test',
        include_answer_key=include_answer_key,
        exam_serial=serial,
    )
    conn = _connect()
    try:
        with conn:
            updated = conn.execute('UPDATE offline_exams SET pdf=? WHERE user_id=? AND serial=? AND submitted_at IS NULL',
                                   (pdf, user_id, serial))
            if not updated.rowcount:
                raise ValueError('This exam is no longer available to update.')
    finally:
        conn.close()
    return pdf


def inspect_submission(user_id, serial, pdf_bytes):
    record = get_offline_exam(user_id, serial)
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise ValueError("Please upload a PDF smaller than 20 MB.")
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        fields = reader.get_fields() or {}
    except Exception as exc:
        raise ValueError("Cannot read this PDF. Save a filled copy of the original PDF and try again.") from exc
    identity = str(fields.get('exam_serial', {}).get('/V', ''))
    if identity != serial:
        raise ValueError("Exam number mismatch or missing. Upload the original filled PDF for the selected exam.")
    questions = json.loads(record['questions_json'])
    expected = {f'q_{i:03d}_{"answer" if _choices(q) else "written_answer"}' for i, q in enumerate(questions, 1)}
    actual = {name for name in fields if name.startswith('q_') and name.endswith(('_answer', '_written_answer'))}
    if actual != expected:
        raise ValueError("The PDF answer fields do not match this exam. Scanned or flattened PDFs cannot be graded.")
    visible_fields = set()
    for page in reader.pages:
        for ref in page.get('/Annots', []):
            widget = ref.get_object()
            if widget.get('/Subtype') != '/Widget':
                continue
            field = widget.get('/Parent', widget).get_object()
            visible_fields.add(str(field.get('/T', '')))
    if not expected.issubset(visible_fields):
        raise ValueError('Some answer pages or form widgets are missing. Upload the complete editable PDF.')
    rows = []
    for i, q in enumerate(questions, 1):
        prefix = f'q_{i:03d}'
        choices = _choices(q)
        field = prefix + ('_answer' if choices else '_written_answer')
        raw = str(fields[field].get('/V', '') or '')
        selected = raw.lstrip('/') if choices else raw.strip()
        if choices and selected == 'Off':
            selected = ''
        if choices and selected and selected not in dict(choices):
            raise ValueError(f"Question {i} has an invalid answer.")
        gradeable = bool(choices) and str(q.get('correct_answer', '')).upper() in dict(choices)
        rows.append(dict(number=i, question_id=q.get('id'), selected=selected,
                         correct=gradeable and bool(selected) and selected == str(q.get('correct_answer', '')).upper(),
                         gradeable=gradeable,
                         scored=q.get('_offline_scored', True),
                         section=int(q.get('_offline_section', 1)),
                         issue=str(fields.get(prefix+'_report_issue', {}).get('/V', '/Off')) not in ('/Off', '', 'None'),
                         note=str(fields.get(prefix+'_issue_note', {}).get('/V', '') or '')))
    total = sum(r['gradeable'] and r['scored'] for r in rows)
    correct = sum(r['correct'] and r['scored'] for r in rows)
    return dict(serial=serial, rows=rows, total=total, correct=correct,
                percent=round(100*correct/total, 1) if total else None,
                unanswered=sum(not r['selected'] for r in rows),
                manual_review=sum(not r['gradeable'] and r['scored'] for r in rows))


def exam_for_attempt(user_id, attempt_id):
    return next((r for r in list_offline_exams(user_id) if r['attempt_id'] == attempt_id), None)


def _progress_state(user_id, record):
    draft = database.get_exam_draft(user_id, record['attempt_id']) if record['attempt_id'] else None
    state = (draft or {}).get('state') or {}
    questions = json.loads(record['questions_json'])
    saved_questions = state.get('exam_questions', questions)
    if [q.get('id') for q in saved_questions] != [q.get('id') for q in questions]:
        raise ValueError('The app question set has changed since this PDF was created. Progress cannot be copied between different question sets.')
    return draft, state, questions


def progress_pdf(user_id, serial, source_pdf=None):
    """Download an editable copy containing the latest durable app answers."""
    from pypdf import PdfWriter
    from pypdf.generic import NameObject
    record = get_offline_exam(user_id, serial)
    if is_closed(record):
        return bytes(record['pdf'])
    _, state, questions = _progress_state(user_id, record)
    answers = state.get('exam_answers') or {}
    writer = PdfWriter(clone_from=BytesIO(source_pdf if source_pdf is not None else record['pdf']))
    values = {}
    for idx, question in enumerate(questions):
        answer = str(answers.get(str(idx), answers.get(idx, '')) or '')
        name = f'q_{idx+1:03d}_'
        values[name + ('answer' if _choices(question) else 'written_answer')] = (
            NameObject('/' + (answer or 'Off')) if _choices(question) else answer)
    writer.update_page_form_field_values(None, values, auto_regenerate=False)
    # pypdf writes per-widget /V values for radio groups. Let every widget
    # inherit the canonical group value instead; /AS controls its appearance.
    for page in writer.pages:
        for ref in page.get('/Annots', []):
            widget = ref.get_object()
            if widget.get('/Parent'):
                widget.pop(NameObject('/V'), None)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def save_pdf_progress(user_id, serial, pdf_bytes):
    """Merge nonblank PDF answers into a draft without completing the exam."""
    result = inspect_submission(user_id, serial, pdf_bytes)
    conn = _connect()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            record = dict(conn.execute('SELECT * FROM offline_exams WHERE serial=? AND user_id=?', (serial,user_id)).fetchone())
            if is_closed(record):
                raise ValueError('This exam is already closed.')
            aid = record['attempt_id']
            row = conn.execute('SELECT d.state_json,a.completed_at FROM exam_drafts d JOIN exam_attempts a ON a.id=d.attempt_id WHERE d.attempt_id=? AND d.user_id=?', (aid,user_id)).fetchone()
            if not row or row['completed_at']:
                raise ValueError('A resumable app session is required to save partial PDF progress.')
            state = json.loads(row['state_json'])
            questions = json.loads(record['questions_json'])
            if [q.get('id') for q in state.get('exam_questions', [])] != [q.get('id') for q in questions]:
                raise ValueError('The app question set has changed since this PDF was created.')
            answers = state.setdefault('exam_answers', {})
            count = 0
            for answer in result['rows']:
                if not answer['selected']:
                    continue
                idx = answer['number'] - 1
                answers[str(idx)] = answer['selected']
                state.pop(f'q_radio_{idx}', None)
                state.pop(f'q_open_ended_{idx}', None)
                # A changed written response needs a fresh self-grade.
                state.get('exam_self_grades', {}).pop(str(idx), None)
                count += 1
            state['exam_offline_pending'] = True
            state['exam_current_idx'] = next((i for i in range(len(questions)) if not answers.get(str(i))), max(0,len(questions)-1))
            conn.execute('UPDATE exam_drafts SET state_json=?,updated_at=CURRENT_TIMESTAMP WHERE attempt_id=? AND user_id=?', (json.dumps(state),aid,user_id))
        return count
    finally:
        conn.close()


def submit_pdf(user_id, serial, pdf_bytes, self_grades=None):
    result = inspect_submission(user_id, serial, pdf_bytes)
    if result['manual_review']:
        self_grades = self_grades or {}
        for row in result['rows']:
            if not row['gradeable'] and row['scored']:
                if type(self_grades.get(row['number'])) is not bool:
                    raise ValueError('Please self-grade each written response before submitting.')
                row['correct'] = bool(row['selected']) and self_grades[row['number']]
                row['self_graded'] = True
        result['total'] = sum(r['scored'] for r in result['rows'])
        result['correct'] = sum(r['correct'] and r['scored'] for r in result['rows'])
        result['percent'] = round(100*result['correct']/result['total'], 1) if result['total'] else 0
    conn = _connect()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            record = conn.execute('SELECT * FROM offline_exams WHERE user_id=? AND serial=?', (user_id, serial)).fetchone()
            if record['submitted_at']:
                return json.loads(record['result_json'])
            aid = record['attempt_id']
            if aid:
                attempt = conn.execute('SELECT completed_at FROM exam_attempts WHERE id=? AND user_id=?', (aid, user_id)).fetchone()
                if not attempt or attempt[0]:
                    raise ValueError('This exam was already completed online. Its score cannot be overwritten.')
            else:
                # Whole-exam PDF exports can span several online section attempts.
                aid = conn.execute("""INSERT INTO exam_attempts (user_id,mode,section_type,settings_json)
                    VALUES (?,'practice',?,?)""", (user_id, record['title'], json.dumps({'offline_serial':serial}))).lastrowid
            database._ensure_user_answer_submitted_at(conn)
            prior_answers = {(row[0], row[1]) for row in conn.execute(
                'SELECT question_id,section_number FROM user_answers WHERE attempt_id=?', (aid,))}
            # A practice question may have been replaced online after export.
            # Final history must describe exactly the frozen PDF question set.
            conn.execute('DELETE FROM user_answers WHERE attempt_id=?', (aid,))
            for r in result['rows']:
                if not r['scored']:
                    continue
                existed = (r['question_id'], r['section']) in prior_answers
                conn.execute("""INSERT INTO user_answers
                    (attempt_id,question_id,selected_answer,is_correct,time_spent_seconds,is_flagged,section_number,submitted_at)
                    VALUES (?,?,?,?,0,?,?,CURRENT_TIMESTAMP)
                    ON CONFLICT(attempt_id,question_id,section_number) DO UPDATE SET
                    selected_answer=excluded.selected_answer,is_correct=excluded.is_correct,
                    is_flagged=excluded.is_flagged,time_spent_seconds=0,submitted_at=CURRENT_TIMESTAMP""",
                    (aid,r['question_id'],r['selected'],int(r['correct']),int(r['issue']),r['section']))
                if not existed:
                    database._update_question_review_state(conn, aid, r['question_id'], r['correct'])
                if r['selected'] and not r['correct']:
                    prior = conn.execute('SELECT id FROM mistake_journal WHERE user_id=? AND question_id=? AND COALESCE(is_completed,0)=0', (user_id,r['question_id'])).fetchone()
                    if prior:
                        conn.execute('UPDATE mistake_journal SET attempt_id=? WHERE id=?', (aid,prior[0]))
                    else:
                        conn.execute('INSERT INTO mistake_journal (user_id,question_id,attempt_id) VALUES (?,?,?)', (user_id,r['question_id'],aid))
                if r['issue'] or r['note']:
                    conn.execute("""INSERT INTO question_issue_reports
                        (user_id,question_id,attempt_id,note,selected_answer,mode)
                        VALUES (?,?,?,?,?,'offline_pdf')""", (user_id,r['question_id'],aid,r['note'],r['selected']))
            conn.execute("""UPDATE exam_attempts SET completed_at=CURRENT_TIMESTAMP,
                total_questions=?,correct_answers=?,raw_score=?,percent_correct=?,section_scores_json=? WHERE id=?""",
                (result['total'],result['correct'],result['correct'],result['percent'],json.dumps({'offline_pdf':result}),aid))
            conn.execute('DELETE FROM exam_drafts WHERE attempt_id=?', (aid,))
            conn.execute("""UPDATE offline_exams SET submitted_at=CURRENT_TIMESTAMP,result_json=?,attempt_id=?
                WHERE serial=? AND user_id=?""", (json.dumps(result),aid,serial,user_id))
        return result
    finally:
        conn.close()


def save_self_assessment(user_id, serial, rows):
    record = get_offline_exam(user_id, serial)
    count = len(json.loads(record['questions_json']))
    if len(rows) != count or [r['Question'] for r in rows] != list(range(1, count+1)):
        raise ValueError('The self-assessment does not match the exam.')
    conn = _connect()
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS offline_self_assessments (user_id INTEGER, serial TEXT, rows_json TEXT, PRIMARY KEY(user_id,serial))")
            conn.execute("INSERT INTO offline_self_assessments VALUES (?,?,?) ON CONFLICT(user_id,serial) DO UPDATE SET rows_json=excluded.rows_json", (user_id,serial,json.dumps(rows)))
    finally:
        conn.close()


def assessment_score(rows):
    total = sum(bool(r['Include']) for r in rows)
    correct = sum(bool(r['Include']) and bool(r['Correct']) for r in rows)
    return correct, total, round(100*correct/total,1) if total else 0


def render_self_assessment(user_id, record):
    import streamlit as st
    import pandas as pd
    serial = record['serial']
    questions = json.loads(record['questions_json'])
    conn = _connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS offline_self_assessments (user_id INTEGER, serial TEXT, rows_json TEXT, PRIMARY KEY(user_id,serial))")
        saved = conn.execute('SELECT rows_json FROM offline_self_assessments WHERE user_id=? AND serial=?', (user_id,serial)).fetchone()
    finally:
        conn.close()
    initial_key = f'offline_assessment_initial_{serial}'
    if initial_key not in st.session_state:
        st.session_state[initial_key] = json.loads(saved[0]) if saved else [
            {'Question':i, 'Include':q.get('_offline_scored',True), 'Correct':False}
            for i,q in enumerate(questions,1)]
    st.caption('Check Correct as you review your paper or PDF. Uncheck Include to remove specific questions from this self-assessment. Changes update the score immediately; Save keeps your assessment for next time. This does not overwrite an automatically graded result.')
    score_area = st.empty()
    edited = st.data_editor(pd.DataFrame(st.session_state[initial_key]), hide_index=True,
        disabled=['Question'], key=f'offline_assessment_editor_{serial}',
        column_config={'Include':st.column_config.CheckboxColumn('Include in score', required=True),
                       'Correct':st.column_config.CheckboxColumn('Correct', required=True)})
    rows = edited.to_dict('records')
    correct,total,percent = assessment_score(rows)
    score_area.metric('Live self-assessed score', f'{correct}/{total} ({percent}%)', help='Correct included questions divided by all included questions.')
    st.caption(f'{len(rows)-total} questions excluded. ' + ('Include at least one question to calculate a meaningful score.' if not total else ''))
    if st.button('Save self-assessment',key=f'save_assessment_{serial}'):
        save_self_assessment(user_id,serial,rows)
        st.success('Self-assessment saved.')
    with st.expander('Reference answers'):
        from src.pdf_export import _answer_text
        st.dataframe([{'Question':i,'Reference answer':_answer_text(q)} for i,q in enumerate(questions,1)], hide_index=True)


def grading_details(record, result, self_grades=None):
    """Use frozen question content for both provisional and saved grading."""
    from src.pdf_export import _answer_text
    questions = json.loads(record['questions_json'])
    details = []
    for row in result['rows']:
        question = questions[row['number']-1]
        selected = str(row.get('selected') or '')
        chosen_text = question.get(f'choice_{selected.lower()}') if selected in 'ABCDE' and selected else None
        answer = f'{selected}. {chosen_text}' if chosen_text else selected or 'No saved answer'
        pending = not row.get('gradeable', True) and not row.get('self_graded', False)
        correct = bool(row.get('correct'))
        if self_grades is not None and row['number'] in self_grades:
            pending = False
            correct = bool(selected.strip()) and self_grades[row['number']]
        if not row.get('scored', True):
            status, points = 'Excluded', '0 / 0'
        elif pending:
            status, points = 'Needs self-grading', 'Pending / 1'
        else:
            status = 'Correct' if correct else 'Incorrect' if selected or row.get('self_graded') else 'Unanswered'
            points = '1 / 1' if correct else '0 / 1'
        rationale = str(question.get('explanation') or question.get('rationale') or '').strip()
        details.append({
            'Question': f"Q{row['number']}: {question.get('stimulus') or 'Question text unavailable'}",
            'Your answer': answer,
            'Correct answer': _answer_text(question),
            'Result': status,
            'Rationale': rationale or 'No rationale was saved with this exam.',
            'Points': points,
        })
    return details


def render_grading_details(record, result, *, provisional=False, self_grades=None):
    import streamlit as st
    details = grading_details(record,result,self_grades)
    earned = sum(row['Points']=='1 / 1' for row in details)
    possible = sum(row['Points']!='0 / 0' for row in details)
    pending = sum(row['Result']=='Needs self-grading' for row in details)
    label = 'Provisional points' if provisional else 'Points awarded'
    st.metric(label, f'{earned} / {possible}')
    st.caption('1 point per correct included question; 0 for incorrect or unanswered questions. Excluded questions are worth 0 points.' +
        (f' {pending} question(s) still need self-grading.' if pending else '') +
        (' Preview only: submit to save this score and close the exam.' if provisional else ''))
    st.dataframe(details, hide_index=True, use_container_width=True, row_height=80,
        column_config={
            'Question':st.column_config.TextColumn(width='large'),
            'Your answer':st.column_config.TextColumn(width='medium'),
            'Correct answer':st.column_config.TextColumn(width='medium'),
            'Result':st.column_config.TextColumn(width='small'),
            'Rationale':st.column_config.TextColumn(width='large'),
            'Points':st.column_config.TextColumn('Points earned / possible',width='small'),
        })
    with st.expander('Read full question and rationale'):
        number = st.selectbox('Question to review', range(1,len(details)+1),
            key=f"offline_detail_question_{record['serial']}_{provisional}")
        if number:
            detail = details[number-1]
            st.write(detail['Question'])
            st.write('Your answer:', detail['Your answer'])
            st.write('Correct answer:', detail['Correct answer'])
            st.write('Result:', detail['Result'], '| Points:', detail['Points'])
            st.write('Rationale:', detail['Rationale'])


def _record_course_summary(record):
    questions = json.loads(record.get('questions_json') or '[]')
    titles = sorted({
        str(q.get('course_title') or '').strip()
        for q in questions
        if str(q.get('course_title') or '').strip()
    })
    course = titles[0] if len(titles) == 1 else f'{len(titles)} courses' if titles else record.get('title', 'Practice exam')
    return course, len(questions), {q.get('course_id') for q in questions}


def _exam_option_label(record):
    course, question_count, _ = _record_course_summary(record)
    status = 'Submitted' if record.get('result_json') else 'Completed online' if record.get('completed_at') else 'Outstanding'
    noun = 'question' if question_count == 1 else 'questions'
    return f"{course} · {question_count} {noun} · {display_exam_number(record['serial'])} · {status}"


def render_offline_exams(user_id, preferred_course_id=None):
    import streamlit as st
    from src.offline_email import send_exam, valid_email
    from src.email_notifications import USER_EMAIL_KEY, _load_smtp_settings, _missing_smtp_message
    reconcile_active_exam(user_id)
    if st.session_state.get('offline_progress_notice'):
        st.success(st.session_state.pop('offline_progress_notice'))
    with st.expander('Offline exams: download, email, submit, and review'):
        st.caption('Fill the PDF offline and save its editable form. Return here to upload it, or reply to an exam email when email submissions are configured. Scans and flattened copies cannot be imported.')
        records = list_offline_exams(user_id)
        if not records:
            st.info('Start a practice exam to create a saved PDF exam.')
            return
        current_attempt = st.session_state.get('exam_attempt_id') if st.session_state.get('exam_active') else None
        if current_attempt and st.session_state.get('offline_linked_attempt') != current_attempt:
            st.session_state['offline_exam_section'] = 'Outstanding exams'
        st.session_state['offline_linked_attempt'] = current_attempt
        section = st.radio('Exam list', ['Outstanding exams','Closed / submitted exams'], key='offline_exam_section', horizontal=True)
        records = [r for r in records if is_closed(r) == (section == 'Closed / submitted exams')]
        if not records:
            st.info('No exams in this section.')
            return
        if preferred_course_id is not None:
            records.sort(key=lambda r: preferred_course_id not in _record_course_summary(r)[2])
        options = {r['serial']:r for r in records}
        picker_key = 'offline_exam_picker_v2'
        active = next((r for r in records if st.session_state.get('exam_active') and r['attempt_id'] == st.session_state.get('exam_attempt_id')), None)
        if st.session_state.get(picker_key) not in options:
            st.session_state.pop(picker_key,None)
        if active:
            serial = active['serial']
            st.write('PDF for your current practice session')
            from src.exam_engine import persist_current_exam
            persist_current_exam(user_id)
        else:
            serial = st.selectbox('Saved PDF exam', options, format_func=lambda s: _exam_option_label(options[s]), key=picker_key)
        record = get_offline_exam(user_id, serial)
        course, question_count, course_ids = _record_course_summary(record)
        st.caption(f"Selected: {course} · {question_count} questions · Exam {display_exam_number(serial)}")
        if preferred_course_id is not None and preferred_course_id not in course_ids:
            st.warning(f'This saved exam contains {course} material, which differs from the active course. Choose the matching exam above before downloading.')
        if section == 'Closed / submitted exams':
            with st.expander('Delete this exam and its score'):
                st.caption('Permanently removes this exam, its answers, saved PDF, self-assessment, and score. Review statistics are rebuilt from your remaining attempts. The question bank is kept.')
                confirm = st.checkbox('Delete this selected exam permanently',key=f'delete_confirm_{serial}')
                if st.button('Delete exam',disabled=not confirm,key=f'delete_exam_{serial}'):
                    delete_offline_exam(user_id,serial)
                    st.session_state.pop(picker_key,None)
                    reconcile_active_exam(user_id)
                    st.rerun()
        try:
            download_pdf = progress_pdf(user_id, serial)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.download_button('Download / print PDF with saved answers', download_pdf, file_name=f'{display_exam_number(serial)}.pdf', mime='application/pdf', key=f'offline_saved_download_{serial}')
        recipient = st.text_input('Recipient email address', value=database.get_setting(user_id,USER_EMAIL_KEY), key='offline_recipient_email')
        save_email, send_email = st.columns(2)
        email_setup = _missing_smtp_message(_load_smtp_settings())
        if email_setup:
            st.warning('Email sending is not configured. Your recipient address can still be saved. ' + email_setup)
            if st.button('Configure sending account in Settings > Email Delivery'):
                st.switch_page('pages/10_Settings.py')
        if save_email.button('Save email address'):
            if valid_email(recipient.strip()):
                database.set_setting(user_id,USER_EMAIL_KEY,recipient.strip())
                st.success('Email address saved for your account.')
            else:
                st.error('Enter a valid email address.')
        if send_email.button('Email this exam',disabled=bool(email_setup)):
            try:
                send_exam(user_id,serial,recipient)
                database.set_setting(user_id,USER_EMAIL_KEY,recipient.strip())
                st.success('Exam emailed. Recipient address saved for next time.')
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error('Email could not be sent. Check the SMTP settings in Settings > Email Delivery.')
        with st.expander('PDF with offline automatic scoring'):
            st.caption('This optional copy contains the answer key and a calculated score for multiple-choice questions. Use Acrobat with PDF JavaScript enabled. If your reader does not run calculations, upload the completed PDF for grading instead. The server recalculates the score independently.')
            if st.button('Prepare offline scoring PDF', key=f'prepare_live_{serial}'):
                from src.offline_pdf_scoring import scoring_pdf
                st.session_state[f'offline_live_{serial}'] = progress_pdf(user_id, serial, scoring_pdf(record))
            if f'offline_live_{serial}' in st.session_state:
                st.download_button('Download offline scoring PDF',st.session_state[f'offline_live_{serial}'],file_name=f'{display_exam_number(serial)}_scoring.pdf',mime='application/pdf')
        mode = st.radio('Grading mode',['Automatically grade PDF','Self-grade with checkboxes'], key=f'offline_grading_mode_{serial}', horizontal=True)
        if mode == 'Self-grade with checkboxes':
            render_self_assessment(user_id,record)
            return
        if record['result_json']:
            result = json.loads(record['result_json'])
            st.success(f"Practice accuracy: {result['correct']}/{result['total']} ({result['percent']}%)")
            if result.get('unanswered') == len(result['rows']):
                st.warning('No saved answers were found in this submission. This zero reflects blank answers, not an assessment of your knowledge. You can use Self-grade with checkboxes to record your paper results separately.')
            st.caption('Saved automatic result. These rows are read-only; use Self-grade with checkboxes for an editable self-assessment.')
            render_grading_details(record,result)
            return
        if options[serial].get('completed_at'):
            st.info('Completed in the app. This exam is closed to further submissions.')
            answers = database.get_attempt_answers(record['attempt_id'])
            frozen = {q['id']:q for q in json.loads(record['questions_json']) if q.get('id') is not None}
            online_questions = [frozen.get(a['question_id'],a) for a in answers]
            online_rows = [dict(number=i, selected=a.get('selected_answer') or '',
                                correct=bool(a.get('is_correct')),scored=True,gradeable=True)
                           for i,a in enumerate(answers,1)]
            if online_rows:
                render_grading_details({**record,'questions_json':json.dumps(online_questions)}, {'rows':online_rows})
            if st.button('Open Score History'):
                st.switch_page('pages/9_Score_History.py')
            return
        upload = st.file_uploader('Upload PDF progress or completed exam', type=['pdf'], key=f'offline_upload_{serial}')
        if upload is not None:
            try:
                result = inspect_submission(user_id, serial, upload.getvalue())
                empty_upload = result['unanswered'] == len(result['rows'])
                st.caption('Save progress copies nonblank PDF answers into the app and keeps the exam open. Blank PDF answers keep existing app answers. Changed nonblank answers replace the corresponding app answers.')
                if st.button('Save PDF progress and keep exam open', key=f'offline_progress_{serial}', disabled=empty_upload):
                    saved_count = save_pdf_progress(user_id, serial, upload.getvalue())
                    if st.session_state.get('exam_attempt_id') == record['attempt_id']:
                        from src.exam_engine import clear_quiz, restore_exam_draft
                        for idx in range(len(result['rows'])):
                            st.session_state.pop(f'q_radio_{idx}', None)
                            st.session_state.pop(f'q_open_ended_{idx}', None)
                        clear_quiz(delete_draft=False)
                        restore_exam_draft(user_id, attempt_id=record['attempt_id'])
                    st.session_state['offline_progress_notice'] = f'Saved {saved_count} PDF answers. The exam remains open; resume in the app or download an updated PDF.'
                    st.rerun()
                if empty_upload:
                    st.warning('No saved answers found. Fill the PDF and save the changed editable copy before uploading. To grade a paper copy yourself, choose Self-grade with checkboxes.')
                st.info(f"Matched exam. {len(result['rows'])-result['unanswered']} answers found; {result['unanswered']} unanswered. Unanswered multiple-choice questions count as incorrect.")
                self_grades = {}
                if result['manual_review']:
                    from src.pdf_export import _answer_text
                    questions = json.loads(record['questions_json'])
                    st.warning('Review the reference answers and self-grade the written responses below.')
                    for row in result['rows']:
                        if not row['gradeable'] and row['scored']:
                            st.write(f"Q{row['number']} reference: {_answer_text(questions[row['number']-1])}")
                            grade = st.selectbox(f"Q{row['number']} self-grade", ['Select a grade', 'Incorrect', 'Correct'], key=f"offline_grade_{serial}_{row['number']}")
                            if grade != 'Select a grade':
                                self_grades[row['number']] = grade == 'Correct'
                render_grading_details(record,result,provisional=True,self_grades=self_grades)
                if st.button('Finish exam and submit PDF for grading', key=f'offline_submit_{serial}',disabled=empty_upload):
                    submit_pdf(user_id, serial, upload.getvalue(), self_grades)
                    if st.session_state.get('exam_attempt_id') == record['attempt_id']:
                        from src.exam_engine import clear_quiz
                        clear_quiz(delete_draft=False)
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))
