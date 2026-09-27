"""Send PDF exams and process authorized replies from a dedicated IMAP inbox."""
import hashlib
import imaplib
import json
import os
import re
import secrets
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.utils import parseaddr

from src import database
from src.email_notifications import _load_smtp_settings, _missing_smtp_message, _send_message
from src.offline_exams import _connect, get_offline_exam, inspect_submission, submit_pdf
from src.pdf_export import display_exam_number

IMAP_KEYS = ['exam_imap_host', 'exam_imap_port', 'exam_imap_username', 'exam_imap_password', 'exam_reply_address']


def mailbox_settings():
    saved = database.get_app_settings(IMAP_KEYS)
    return {key: os.getenv('STUDYFORGE_' + key.upper(), saved.get(key, '')).strip() for key in IMAP_KEYS}


def valid_email(value):
    return bool(re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value))


def exam_subject(record, purpose='Exam PDF'):
    questions = json.loads(record['questions_json'])
    ids = sorted({q.get('course_id') for q in questions if q.get('course_id') is not None})
    conn = database.get_connection()
    try:
        titles = [row[0] for row in conn.execute(
            'SELECT title FROM courses WHERE id IN (' + ','.join('?' for _ in ids) + ') ORDER BY title', ids)] if ids else []
    finally:
        conn.close()
    course = ', '.join(titles) or record['title']
    course = ' '.join(course.split())[:160]
    return f"[StudyForge] {course} | {display_exam_number(record['serial'])} | {purpose}"


def _mail_connection():
    conn = _connect()
    conn.execute('''CREATE TABLE IF NOT EXISTS offline_email_tokens (
        token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, serial TEXT NOT NULL,
        recipient TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS offline_email_receipts (
        message_hash TEXT PRIMARY KEY, recipient TEXT NOT NULL, subject TEXT NOT NULL,
        body TEXT NOT NULL, reply_sent INTEGER DEFAULT 0)''')
    conn.commit()
    return conn


def send_exam(user_id, serial, recipient):
    recipient = recipient.strip().lower()
    if not valid_email(recipient):
        raise ValueError('Enter a valid recipient email address.')
    record = get_offline_exam(user_id, serial)
    smtp = _load_smtp_settings()
    missing = _missing_smtp_message(smtp)
    if missing:
        raise ValueError(missing)
    mailbox = mailbox_settings()
    reply = mailbox['exam_reply_address']
    token = secrets.token_hex(24)
    conn = _mail_connection()
    try:
        with conn:
            conn.execute('INSERT INTO offline_email_tokens (token,user_id,serial,recipient) VALUES (?,?,?,?)', (token,user_id,serial,recipient))
    finally:
        conn.close()
    msg = EmailMessage()
    msg['From'], msg['To'] = smtp['from_email'], recipient
    msg['Subject'] = f'{exam_subject(record)} [SF-REPLY:{token}]'
    if valid_email(reply):
        msg['Reply-To'] = reply
    instructions = ('Reply from this same email address with exactly one completed PDF attached. Keep the subject unchanged. '
                    'The mail processor will grade it and email the result. Written responses require self-grading in the app.') if valid_email(reply) else 'Email submissions are not configured yet. Upload the completed PDF in Practice Mode.'
    visible_number = display_exam_number(serial)
    msg.set_content(f"{record['title']}\nExam number: {visible_number}\n\nFill the PDF and save the editable file with your answers.\n{instructions}")
    from src.offline_exams import progress_pdf
    msg.add_attachment(progress_pdf(user_id, serial), maintype='application', subtype='pdf', filename=f'{visible_number}.pdf')
    _send_message(msg, smtp)


def process_message(raw):
    """Only possession of an emailed token plus its recipient can authorize grading.

    The token, not the spoofable From header alone, is the authorization secret.
    Unrecognized messages receive no reply and never reach the grading service.
    """
    if len(raw) > 30*1024*1024:
        return False
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    if msg.get('Auto-Submitted', 'no').lower() != 'no':
        return False
    match = re.search(r'\[SF-REPLY:([a-f0-9]{48})\]', str(msg.get('Subject', '')))
    if not match:
        return False
    conn = _mail_connection()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        authorization = conn.execute('SELECT * FROM offline_email_tokens WHERE token=?', (match[1],)).fetchone()
        if not authorization or parseaddr(str(msg.get('From', '')))[1].lower() != authorization['recipient']:
            return False
        receipt = conn.execute('SELECT * FROM offline_email_receipts WHERE message_hash=?', (digest,)).fetchone()
        if not receipt:
            attachments = [part.get_payload(decode=True) for part in msg.iter_attachments()
                           if (part.get_filename() or '').lower().endswith('.pdf')]
            try:
                if len(attachments) != 1 or not attachments[0]:
                    raise ValueError('Attach exactly one saved, editable PDF exam.')
                preview = inspect_submission(authorization['user_id'], authorization['serial'], attachments[0])
                if preview['manual_review']:
                    raise ValueError('Written responses need self-grading in Practice Mode. No score was submitted by email.')
                if preview['unanswered'] == len(preview['rows']):
                    raise ValueError('No saved answers were found. Save your answers in the editable PDF and reply again.')
                result = submit_pdf(authorization['user_id'], authorization['serial'], attachments[0])
                body = f"Exam {display_exam_number(authorization['serial'])}\nPractice accuracy: {result['correct']}/{result['total']} ({result['percent']}%).\nThis is practice accuracy, not a licensing-exam score prediction.\nReview details in Practice Mode."
            except ValueError as exc:
                body = str(exc)
            with conn:
                conn.execute('INSERT OR IGNORE INTO offline_email_receipts (message_hash,recipient,subject,body) VALUES (?,?,?,?)',
                    (digest,authorization['recipient'],exam_subject(get_offline_exam(authorization['user_id'],authorization['serial']), 'Grading result'),body))
            receipt = conn.execute('SELECT * FROM offline_email_receipts WHERE message_hash=?', (digest,)).fetchone()
        if not receipt['reply_sent']:
            smtp = _load_smtp_settings()
            if _missing_smtp_message(smtp):
                raise ValueError(_missing_smtp_message(smtp))
            reply = EmailMessage()
            reply['From'], reply['To'] = smtp['from_email'], receipt['recipient']
            reply['Subject'], reply['Auto-Submitted'] = receipt['subject'], 'auto-replied'
            reply.set_content(receipt['body'])
            _send_message(reply, smtp)
            with conn:
                conn.execute('UPDATE offline_email_receipts SET reply_sent=1 WHERE message_hash=?', (digest,))
        return True
    finally:
        conn.close()


def poll_mailbox():
    settings = mailbox_settings()
    if not all(settings[k] for k in ('exam_imap_host','exam_imap_username','exam_imap_password')):
        raise ValueError('Configure the incoming exam mailbox in Settings first.')
    processed = 0
    with imaplib.IMAP4_SSL(settings['exam_imap_host'], int(settings['exam_imap_port'] or 993), timeout=20) as mail:
        mail.login(settings['exam_imap_username'], settings['exam_imap_password'])
        status, _ = mail.select('INBOX')
        if status != 'OK':
            raise ValueError('Cannot open the exam inbox.')
        status, data = mail.uid('search', None, '(UNSEEN SUBJECT "SF-REPLY:")')
        if status != 'OK':
            raise ValueError('Cannot search the exam inbox.')
        for uid in (data[0] or b'').split()[:50]:
            status, size_data = mail.uid('fetch', uid, '(RFC822.SIZE)')
            sizes = re.findall(rb'RFC822.SIZE (\d+)', b' '.join(x for x in size_data if isinstance(x, bytes)))
            if status != 'OK' or not sizes or int(sizes[0]) > 30*1024*1024:
                continue
            status, parts = mail.uid('fetch', uid, '(BODY.PEEK[])')
            if status == 'OK':
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw and process_message(raw):
                    mail.uid('store', uid, '+FLAGS', '(\\Seen)')
                    processed += 1
    return processed


def render_mailbox_settings():
    import streamlit as st
    st.markdown('#### Incoming exam submissions')
    st.caption('Use a dedicated mailbox. The mail processor must be running to grade replies automatically, including while this browser is closed.')
    current = mailbox_settings()
    with st.form('offline_mailbox_settings'):
        values = {}
        for key, label in zip(IMAP_KEYS, ['IMAP host','IMAP port','Mailbox username','Mailbox password / app password','Submission email address']):
            values[key] = st.text_input(label, value=current[key] or ('993' if key=='exam_imap_port' else ''), type='password' if 'password' in key else 'default')
        if st.form_submit_button('Save incoming mailbox settings'):
            if not valid_email(values['exam_reply_address']):
                st.error('Enter a valid submission email address.')
            else:
                for key,value in values.items():
                    database.set_app_setting(key,value.strip())
                st.success('Mailbox settings saved. Start the mail processor to enable automatic grading.')
    st.code('python scripts/process_exam_email.py --watch', language='powershell')
    if st.button('Check exam inbox now'):
        try:
            st.success(f'Processed {poll_mailbox()} exam submissions.')
        except Exception:
            st.error('The inbox check failed. Verify IMAP and SMTP settings and mailbox access.')
