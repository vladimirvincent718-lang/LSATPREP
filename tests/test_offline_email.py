from email.message import EmailMessage
from io import BytesIO
from unittest.mock import patch

import pytest
from pypdf import PdfReader
from test_offline_exams import exam, fill
from src import offline_email, offline_exams, database
from src.offline_pdf_scoring import scoring_pdf, calculation_script
from src.pdf_export import display_exam_number


SMTP = {'host':'example.test','port':'587','from_email':'exams@example.test'}


def sent_exam(exam):
    _, serial, _, _ = exam
    with patch.object(offline_email,'_load_smtp_settings',return_value=SMTP), patch.object(offline_email,'_send_message') as send:
        offline_email.send_exam(1, serial, 'learner@any-provider.test')
        return send.call_args.args[0]


def response(sent, pdf, sender='learner@any-provider.test'):
    msg = EmailMessage()
    msg['From'],msg['To'],msg['Subject'] = sender,'exams@example.test','Re: '+str(sent['Subject'])
    msg.set_content('Completed exam attached.')
    msg.add_attachment(pdf, maintype='application', subtype='pdf', filename='completed.pdf')
    return msg.as_bytes()


def test_email_subject_and_auto_grade_retry(exam):
    _,serial,pdf,_ = exam
    sent = sent_exam(exam)
    visible = display_exam_number(serial)
    assert str(sent['Subject']).startswith(f'[StudyForge] Offline test | {visible} | Exam PDF')
    raw = response(sent,fill(pdf,{'q_001_answer':'/B'}))
    with patch.object(offline_email,'_load_smtp_settings',return_value=SMTP), patch.object(offline_email,'_send_message',side_effect=OSError('offline')):
        with pytest.raises(OSError):
            offline_email.process_message(raw)
    with patch.object(offline_email,'_load_smtp_settings',return_value=SMTP), patch.object(offline_email,'_send_message') as send:
        assert offline_email.process_message(raw)
        assert offline_email.process_message(raw)
        assert send.call_count == 1
        assert '100.0%' in send.call_args.args[0].get_content()
        assert str(send.call_args.args[0]['Subject']) == f'[StudyForge] Offline test | {visible} | Grading result'


def test_unknown_sender_and_blank_do_not_grade(exam):
    _,serial,pdf,_ = exam
    sent = sent_exam(exam)
    with patch.object(offline_email,'_load_smtp_settings',return_value=SMTP), patch.object(offline_email,'_send_message') as send:
        assert not offline_email.process_message(response(sent,pdf,'someone@else.test'))
        assert send.call_count == 0
        assert offline_email.process_message(response(sent,pdf))
        assert 'No saved answers' in send.call_args.args[0].get_content()
    assert offline_exams.get_offline_exam(1,serial)['submitted_at'] is None


def test_pdf_calculation_and_import_are_independent(exam):
    _,serial,_,_ = exam
    pdf = scoring_pdf(offline_exams.get_offline_exam(1,serial))
    reader = PdfReader(BytesIO(pdf))
    fields = reader.get_fields()
    assert fields['exam_serial']['/V'] == serial
    assert reader.trailer['/Root']['/AcroForm']['/CO']
    assert '/JavaScript' == fields['offline_live_score']['/AA']['/C']['/S']
    filled = fill(pdf,{'q_001_answer':'/B','offline_live_score':'999/999'})
    assert offline_exams.inspect_submission(1,serial,filled)['correct'] == 1


def test_self_assessment_exclusion_and_persistence(exam):
    _,serial,_,_ = exam
    assert offline_exams.assessment_score([{'Include':True,'Correct':True},{'Include':False,'Correct':True},{'Include':True,'Correct':False}]) == (1,2,50)
    rows = [{'Question':1,'Include':True,'Correct':True}]
    offline_exams.save_self_assessment(1,serial,rows)
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('from src.offline_exams import render_offline_exams\nrender_offline_exams(1)').run()
    app.radio(key=f'offline_grading_mode_{serial}').set_value('Self-grade with checkboxes').run()
    assert not app.exception
    assert app.metric[0].value == '1/1 (100.0%)'
    with pytest.raises(ValueError):
        offline_exams.save_self_assessment(2,serial,rows)


def test_checkbox_edits_update_live_metric(exam):
    from streamlit.testing.v1 import AppTest
    _,serial,_,_ = exam
    app = AppTest.from_string('from src.offline_exams import render_offline_exams\nrender_offline_exams(1)').run()
    app.radio(key=f'offline_grading_mode_{serial}').set_value('Self-grade with checkboxes').run()
    assert app.metric[0].value == '0/1 (0.0%)'
    app.session_state[f'offline_assessment_editor_{serial}'] = {
        'edited_rows':{0:{'Correct':True}},'added_rows':[],'deleted_rows':[]}
    app.run()
    assert not app.exception
    assert app.metric[0].value == '1/1 (100.0%)'
    app.session_state[f'offline_assessment_editor_{serial}'] = {
        'edited_rows':{0:{'Correct':True,'Include':False}},'added_rows':[],'deleted_rows':[]}
    app.run()
    assert app.metric[0].value == '0/0 (0%)'


def test_remove_ten_of_fifty():
    rows = [{'Include':i>=10,'Correct':True} for i in range(50)]
    assert offline_exams.assessment_score(rows) == (40,40,100)
