from io import BytesIO
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter
from src import database, offline_exams, exam_engine
from src.pdf_export import display_exam_number


@pytest.fixture
def exam(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'offline.db')
    database.init_database()
    conn = database.get_connection()
    conn.execute("INSERT INTO users (id,username,password_hash) VALUES (1,'offline','hash')")
    conn.execute("INSERT INTO questions (id,question_id,section_type,stimulus,choice_a,choice_b,correct_answer) VALUES (999,'OFF-1','Test','Pick B','One','Two','B')")
    conn.commit()
    conn.close()
    aid = database.create_attempt(1, 'practice', 'Test', {})
    questions = [dict(id=999, section_type='Test', stimulus='Pick B', choice_a='One', choice_b='Two', correct_answer='B')]
    pdf = offline_exams.export_offline_exam(user_id=1, attempt_id=aid, questions=questions, title='Offline test', include_answer_key=False)
    serial = offline_exams.list_offline_exams(1)[0]['serial']
    return aid, serial, pdf, questions


def fill(pdf, values):
    writer = PdfWriter(clone_from=BytesIO(pdf))
    writer.update_page_form_field_values(None, values, auto_regenerate=False)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_saved_document_identity_and_snapshot(exam):
    aid, serial, pdf, questions = exam
    assert PdfReader(BytesIO(pdf)).get_fields()['exam_serial']['/V'] == serial
    assert serial in PdfReader(BytesIO(pdf)).pages[0].extract_text()
    assert offline_exams.export_offline_exam(user_id=1, attempt_id=aid, questions=[], title='changed') == pdf
    questions[0]['correct_answer'] = 'A'
    result = offline_exams.inspect_submission(1, serial, fill(pdf, {'q_001_answer':'/B'}))
    assert result['correct'] == 1


def test_changed_questions_get_new_pdf_and_keep_original_separate(exam):
    aid, serial, original, questions = exam
    updated = [*questions, {**questions[0], 'id': 123, 'stimulus': 'Replacement question'}]
    database.save_exam_draft(1, aid, 'practice', None, {
        'exam_questions': updated, 'exam_answers': {'0': 'B'},
    })
    pdf = offline_exams.export_offline_exam(
        user_id=1, attempt_id=aid, questions=updated, title='Practice',
        replace_changed_questions=True,
    )
    linked = offline_exams.exam_for_attempt(1, aid)
    assert linked['serial'] != serial
    old = offline_exams.get_offline_exam(1, serial)
    assert old['attempt_id'] is None
    assert bytes(old['pdf']) == original
    assert 'Replacement question' in ''.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    result = offline_exams.inspect_submission(1, linked['serial'], offline_exams.progress_pdf(1, linked['serial']))
    assert [r['selected'] for r in result['rows']] == ['B', '']
    with pytest.raises(ValueError, match='mismatch'):
        offline_exams.save_pdf_progress(1, linked['serial'], original)
    with pytest.raises(ValueError, match='resumable'):
        offline_exams.save_pdf_progress(1, serial, original)
    assert offline_exams.export_offline_exam(
        user_id=1, attempt_id=aid, questions=updated, title='Practice',
        replace_changed_questions=True,
    ) == pdf


def test_changed_pdf_generation_failure_preserves_original_link(exam, monkeypatch):
    aid, serial, original, questions = exam
    def fail(**kwargs):
        raise RuntimeError('PDF generation failed')
    monkeypatch.setattr(offline_exams, 'generate_exam_pdf', fail)
    with pytest.raises(RuntimeError, match='generation failed'):
        offline_exams.export_offline_exam(
            user_id=1, attempt_id=aid, questions=[{**questions[0], 'id': 123}],
            title='Practice', replace_changed_questions=True,
        )
    assert offline_exams.exam_for_attempt(1, aid)['serial'] == serial
    assert offline_exams.get_offline_exam(1, serial)['pdf'] == original


def test_exam_numbers_and_queue_labels_are_short_and_specific(exam):
    _, serial, _, _ = exam
    record = offline_exams.get_offline_exam(1, serial)
    label = offline_exams._exam_option_label(record)

    assert serial == display_exam_number(serial)
    assert len(serial) == 12
    assert '1 question' in label
    assert 'Offline test' in label
    assert serial in label


def test_outstanding_exam_can_refresh_to_mobile_layout(exam):
    aid, serial, original, _ = exam
    refreshed = offline_exams.refresh_offline_pdf_layout(1, serial)
    reader = PdfReader(BytesIO(refreshed))
    assert refreshed != original
    assert reader.get_fields()['exam_serial']['/V'] == serial
    assert reader.pages[0].mediabox.width == 396
    assert len(reader.pages) == 2
    assert offline_exams.inspect_submission(1, serial, fill(refreshed, {'q_001_answer':'/B'}))['correct'] == 1


def test_submitted_exam_cannot_refresh_layout(exam):
    _, serial, pdf, _ = exam
    offline_exams.submit_pdf(1, serial, fill(pdf, {'q_001_answer':'/B'}))
    with pytest.raises(ValueError, match='Submitted'):
        offline_exams.refresh_offline_pdf_layout(1, serial)


def test_submit_atomic_and_idempotent(exam):
    aid, serial, pdf, _ = exam
    completed = fill(pdf, {'q_001_answer':'/B', 'q_001_report_issue':'/Yes', 'q_001_issue_note':'Check wording'})
    result = offline_exams.submit_pdf(1, serial, completed)
    assert result['percent'] == 100
    assert offline_exams.submit_pdf(1, serial, fill(pdf, {'q_001_answer':'/A'})) == result
    conn = database.get_connection()
    assert conn.execute('SELECT count(*) FROM user_answers WHERE attempt_id=?', (aid,)).fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM question_issue_reports WHERE attempt_id=?', (aid,)).fetchone()[0] == 1
    assert conn.execute('SELECT correct_answers FROM exam_attempts WHERE id=?', (aid,)).fetchone()[0] == 1
    conn.close()


def test_reject_wrong_exam_account_and_broken_pdf(exam):
    aid, serial, pdf, questions = exam
    another = offline_exams.export_offline_exam(user_id=1, questions=questions, title='Another')
    for bad in (another, b'not a pdf', fill(pdf, {'exam_serial':'WRONG'})):
        with pytest.raises(ValueError):
            offline_exams.submit_pdf(1, serial, bad)
    with pytest.raises(ValueError):
        offline_exams.inspect_submission(2, serial, pdf)
    with pytest.raises(ValueError):
        offline_exams.export_offline_exam(user_id=2, attempt_id=aid, questions=questions, title='Bad')


def test_blanks_and_completed_online(exam):
    aid, serial, pdf, _ = exam
    result = offline_exams.inspect_submission(1, serial, pdf)
    assert result['unanswered'] == 1
    assert result['correct'] == 0
    database.complete_attempt(aid, 1, 1, {})
    with pytest.raises(ValueError, match='already completed'):
        offline_exams.submit_pdf(1, serial, pdf)


def test_offline_draft_survives_midnight():
    draft = {'attempt_id':1,'state':{'exam_offline_pending':True,'exam_saved_at':0}}
    with patch.object(exam_engine, 'get_exam_drafts', return_value=[draft]), patch.object(exam_engine,'delete_exam_draft') as delete:
        assert exam_engine.finalize_stale_practice_drafts(1) == []
        delete.assert_not_called()


def test_written_responses_require_explicit_self_grade(exam):
    _, _, _, questions = exam
    questions[0]['_force_open_ended'] = True
    pdf = offline_exams.export_offline_exam(user_id=1, questions=questions, title='Written')
    serial = str(PdfReader(BytesIO(pdf)).get_fields()['exam_serial']['/V'])
    filled = fill(pdf, {'q_001_written_answer':'Two'})
    with pytest.raises(ValueError, match='self-grade'):
        offline_exams.submit_pdf(1, serial, filled)
    result = offline_exams.submit_pdf(1, serial, filled, {1:True})
    assert result['correct'] == 1
    assert result['rows'][0]['self_graded']


def test_missing_widgets_rejected(exam):
    _, serial, pdf, _ = exam
    writer = PdfWriter(clone_from=BytesIO(pdf))
    writer.remove_annotations(subtypes='/Widget')
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError):
        offline_exams.inspect_submission(1, serial, buffer.getvalue())


def test_experimental_section_excluded_and_repeat_question_preserved(exam):
    _, _, _, questions = exam
    questions = [{**questions[0], '_offline_section':i, '_offline_scored':i != 3} for i in range(1,4)]
    pdf = offline_exams.export_offline_exam(user_id=1, questions=questions, title='Full exam')
    serial = str(PdfReader(BytesIO(pdf)).get_fields()['exam_serial']['/V'])
    filled = fill(pdf, {'q_001_answer':'/B','q_002_answer':'/A','q_003_answer':'/B'})
    result = offline_exams.submit_pdf(1, serial, filled)
    assert (result['correct'], result['total'], result['percent']) == (1, 2, 50)
    aid = offline_exams.get_offline_exam(1, serial)['attempt_id']
    conn = database.get_connection()
    assert conn.execute('SELECT count(*) FROM user_answers WHERE attempt_id=?', (aid,)).fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM mistake_journal WHERE attempt_id=?', (aid,)).fetchone()[0] == 1
    conn.close()


def test_failure_rolls_back_grading(exam):
    aid, serial, pdf, _ = exam
    with patch.object(database, '_update_question_review_state', side_effect=RuntimeError('test failure')):
        with pytest.raises(RuntimeError):
            offline_exams.submit_pdf(1, serial, fill(pdf, {'q_001_answer':'/A'}))
    assert offline_exams.get_offline_exam(1, serial)['submitted_at'] is None
    conn = database.get_connection()
    assert conn.execute('SELECT count(*) FROM user_answers WHERE attempt_id=?', (aid,)).fetchone()[0] == 0
    conn.close()


def test_offline_panel_renders_saved_exam_and_result(exam):
    from streamlit.testing.v1 import AppTest
    _, serial, pdf, _ = exam
    app = AppTest.from_string('from src.offline_exams import render_offline_exams\nrender_offline_exams(1)')
    app.run()
    assert not app.exception
    assert app.selectbox[0].value == serial
    offline_exams.submit_pdf(1, serial, fill(pdf, {'q_001_answer':'/B'}))
    app.radio(key='offline_exam_section').set_value('Closed / submitted exams').run()
    assert not app.exception
    assert '100.0%' in app.success[0].value


def test_partial_pdf_round_trip_keeps_attempt_open(exam):
    aid, serial, pdf, questions = exam
    database.save_exam_draft(1, aid, 'practice', None, {
        'exam_questions': questions, 'exam_answers': {'0': 'A'},
        'exam_attempt_id': aid, 'exam_active': True, 'exam_mode': 'practice',
    })
    exported = offline_exams.progress_pdf(1, serial)
    assert offline_exams.inspect_submission(1, serial, exported)['rows'][0]['selected'] == 'A'
    assert offline_exams.save_pdf_progress(1, serial, fill(exported, {'q_001_answer': '/B'})) == 1
    assert database.get_exam_draft(1, aid)['state']['exam_answers']['0'] == 'B'
    assert offline_exams.get_offline_exam(1, serial)['submitted_at'] is None
    assert offline_exams.inspect_submission(1, serial, offline_exams.progress_pdf(1, serial))['correct'] == 1
    # Uploading an older blank copy must not wipe the saved answer.
    offline_exams.save_pdf_progress(1, serial, pdf)
    assert database.get_exam_draft(1, aid)['state']['exam_answers']['0'] == 'B'
    conn = database.get_connection()
    assert conn.execute('SELECT completed_at FROM exam_attempts WHERE id=?', (aid,)).fetchone()[0] is None
    assert conn.execute('SELECT COUNT(*) FROM user_answers WHERE attempt_id=?', (aid,)).fetchone()[0] == 0
    conn.close()


def test_active_exam_uses_linked_pdf_without_picker(exam):
    from streamlit.testing.v1 import AppTest
    aid, serial, _, questions = exam
    app = AppTest.from_string(f'''import streamlit as st
from src.offline_exams import render_offline_exams
st.session_state['exam_active'] = True
st.session_state['exam_attempt_id'] = {aid}
st.session_state['exam_questions'] = {questions!r}
st.session_state['exam_mode'] = 'practice'
render_offline_exams(1)
''').run()
    assert not app.exception
    assert not any(s.label == 'Saved PDF exam' for s in app.selectbox)
    assert not any(b.label == 'Update saved PDF to phone-friendly layout' for b in app.button)


def test_partial_pdf_rejects_closed_or_changed_exam(exam):
    aid, serial, pdf, questions = exam
    database.save_exam_draft(1, aid, 'practice', None, {
        'exam_questions': [{**questions[0], 'id': 123}], 'exam_answers': {},
    })
    with pytest.raises(ValueError, match='question set'):
        offline_exams.save_pdf_progress(1, serial, pdf)
    with pytest.raises(ValueError, match='question set'):
        offline_exams.progress_pdf(1, serial)
    with pytest.raises(ValueError):
        offline_exams.save_pdf_progress(2, serial, pdf)
    offline_exams.submit_pdf(1, serial, fill(pdf, {'q_001_answer': '/B'}))
    with pytest.raises(ValueError, match='closed'):
        offline_exams.save_pdf_progress(1, serial, pdf)
