"""Email notifications for StudyForge exam launches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
import os
import smtplib
from ssl import create_default_context

from src.database import get_app_settings, get_connection, get_setting


USER_EMAIL_KEY = "profile_email"
EMAIL_NOTIFICATIONS_KEY = "exam_email_notifications"
TEST_START_COUNT_KEY = "test_start_count"

SMTP_SETTING_KEYS = [
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_password",
    "smtp_from_email",
    "smtp_use_tls",
]

REQUIRED_SMTP_FIELDS = {
    "host": "SMTP host",
    "port": "SMTP port",
    "from_email": "From email",
}


@dataclass
class NotificationResult:
    sent: bool
    test_count: int
    message: str


def record_exam_start(user_id: int) -> int:
    """Increment and return this user's exam/test launch counter."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM settings WHERE user_id = ? AND key = ?",
            (user_id, TEST_START_COUNT_KEY),
        ).fetchone()
        try:
            current = int(row["value"]) if row else 0
        except (TypeError, ValueError):
            current = 0
        next_count = current + 1
        conn.execute(
            "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, TEST_START_COUNT_KEY, str(next_count)),
        )
        conn.commit()
        return next_count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def notify_exam_started(
    user_id: int,
    *,
    course_name: str,
    module_name: str,
    exam_label: str,
    pdf_bytes: bytes | None = None,
    pdf_filename: str | None = None,
    question_count: int | None = None,
) -> NotificationResult:
    """Record a launch and send the configured exam-start email when enabled."""
    test_count = record_exam_start(user_id)
    enabled = get_setting(user_id, EMAIL_NOTIFICATIONS_KEY) == "true"
    if not enabled:
        return NotificationResult(False, test_count, "Email notifications are off.")

    recipient = get_setting(user_id, USER_EMAIL_KEY).strip()
    if not recipient:
        return NotificationResult(False, test_count, "Add an email address in Settings to receive exam notifications.")

    smtp = _load_smtp_settings()
    missing_message = _missing_smtp_message(smtp)
    if missing_message:
        return NotificationResult(False, test_count, missing_message)

    subject = build_exam_subject(course_name, module_name, test_count)
    body = _build_exam_body(
        course_name=course_name,
        module_name=module_name,
        exam_label=exam_label,
        test_count=test_count,
        question_count=question_count,
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp["from_email"]
    msg["To"] = recipient
    msg.set_content(body)

    if pdf_bytes:
        filename = pdf_filename or f"studyforge_test_{test_count}.pdf"
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=filename,
        )

    try:
        _send_message(msg, smtp)
    except Exception as exc:
        return NotificationResult(False, test_count, f"Email notification could not be sent: {exc}")

    return NotificationResult(True, test_count, f"Email notification sent to {recipient}.")


def send_take_home_exam_pdf(
    user_id: int,
    *,
    course_name: str,
    module_name: str,
    exam_label: str,
    pdf_bytes: bytes,
    pdf_filename: str,
    question_count: int | None = None,
) -> NotificationResult:
    """Email a generated take-home exam PDF to the user's email on file."""
    test_count = record_exam_start(user_id)
    recipient = get_setting(user_id, USER_EMAIL_KEY).strip()
    if not recipient:
        return NotificationResult(False, test_count, "Add an email address in Settings to receive take-home exams.")

    smtp = _load_smtp_settings()
    missing_message = _missing_smtp_message(smtp)
    if missing_message:
        return NotificationResult(False, test_count, f"{missing_message} Your PDF is ready to download instead.")

    msg = EmailMessage()
    msg["Subject"] = build_take_home_subject(course_name, module_name, test_count)
    msg["From"] = smtp["from_email"]
    msg["To"] = recipient
    msg.set_content(_build_take_home_body(
        course_name=course_name,
        module_name=module_name,
        exam_label=exam_label,
        test_count=test_count,
        question_count=question_count,
    ))
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_filename,
    )

    try:
        _send_message(msg, smtp)
    except Exception as exc:
        return NotificationResult(False, test_count, f"Take-home exam email could not be sent: {exc}")

    return NotificationResult(True, test_count, f"Take-home exam PDF sent to {recipient}.")


def build_exam_subject(course_name: str, module_name: str, test_count: int) -> str:
    course = _clean_label(course_name, "Course")
    module = _clean_label(module_name, "Exam")
    return f"[StudyForge] {course} | {module} | Test #{test_count} Started"


def build_take_home_subject(course_name: str, module_name: str, test_count: int) -> str:
    course = _clean_label(course_name, "Course")
    module = _clean_label(module_name, "Exam")
    return f"[StudyForge] Take-Home Exam #{test_count}: {course} | {module}"


def _build_exam_body(
    *,
    course_name: str,
    module_name: str,
    exam_label: str,
    test_count: int,
    question_count: int | None,
) -> str:
    started_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    lines = [
        "Your StudyForge exam has started.",
        "",
        f"Test count: #{test_count}",
        f"Course: {_clean_label(course_name, 'Course')}",
        f"Module: {_clean_label(module_name, 'Exam')}",
        f"Exam: {_clean_label(exam_label, 'Exam')}",
        f"Started: {started_at}",
    ]
    if question_count is not None:
        lines.append(f"Questions: {question_count}")
    lines.extend(["", "The exam PDF is attached when available."])
    return "\n".join(lines)


def _build_take_home_body(
    *,
    course_name: str,
    module_name: str,
    exam_label: str,
    test_count: int,
    question_count: int | None,
) -> str:
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    lines = [
        "Your StudyForge take-home exam PDF is attached.",
        "",
        f"Take-home exam: #{test_count}",
        f"Course: {_clean_label(course_name, 'Course')}",
        f"Module: {_clean_label(module_name, 'Exam')}",
        f"Exam: {_clean_label(exam_label, 'Exam')}",
        f"Generated: {generated_at}",
    ]
    if question_count is not None:
        lines.append(f"Questions: {question_count}")
    lines.extend(["", "Print it or open it on your mobile device when you are ready to take it."])
    return "\n".join(lines)


def _load_smtp_settings() -> dict:
    db_settings = get_app_settings(SMTP_SETTING_KEYS)
    return {
        "host": os.getenv("STUDYFORGE_SMTP_HOST") or db_settings.get("smtp_host", "").strip(),
        "port": os.getenv("STUDYFORGE_SMTP_PORT") or db_settings.get("smtp_port", "").strip(),
        "username": os.getenv("STUDYFORGE_SMTP_USERNAME") or db_settings.get("smtp_username", "").strip(),
        "password": os.getenv("STUDYFORGE_SMTP_PASSWORD") or db_settings.get("smtp_password", "").strip(),
        "from_email": os.getenv("STUDYFORGE_SMTP_FROM_EMAIL") or db_settings.get("smtp_from_email", "").strip(),
        "use_tls": (os.getenv("STUDYFORGE_SMTP_USE_TLS") or db_settings.get("smtp_use_tls", "true")).lower() == "true",
    }


def _missing_smtp_message(smtp: dict) -> str:
    missing = [
        label
        for key, label in REQUIRED_SMTP_FIELDS.items()
        if not str(smtp.get(key) or "").strip()
    ]
    if not missing:
        return ""
    return f"SMTP email settings are missing: {', '.join(missing)}."


def _send_message(msg: EmailMessage, smtp: dict) -> None:
    port = int(smtp["port"])
    context = create_default_context()
    with smtplib.SMTP(smtp["host"], port, timeout=20) as server:
        if smtp.get("use_tls", True):
            server.starttls(context=context)
        if smtp.get("username") or smtp.get("password"):
            server.login(smtp.get("username", ""), smtp.get("password", ""))
        server.send_message(msg)


def _clean_label(value: str | None, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    return text or fallback
