from datetime import date
from email import policy
from email.parser import BytesParser

import pytest

from src import practice_calendar as calendar


def test_local_dates_weighted_accuracy_and_padding():
    rows = calendar.aggregate_days(date(2026, 9, 17), [
        {'mode': 'practice', 'completed_at': '2026-09-17 03:59:59', 'is_correct': 1},
        {'mode': 'practice', 'completed_at': '2026-09-17 04:00:00', 'is_correct': 0},
        {'mode': 'full_exam', 'completed_at': '2026-09-17 12:00:00', 'is_correct': 1},
    ], [{'entry_date': '2026-09-17', 'correct_count': 8, 'incorrect_count': 1}],
       [{'activity_date': '2026-09-17', 'active_seconds': 120}])
    assert len(rows) == 30
    assert rows[0]['date'] == date(2026, 8, 19)
    assert rows[0]['accuracy'] is None
    assert rows[-2]['total'] == 1
    assert rows[-1]['total'] == 10
    assert rows[-1]['accuracy'] == 80
    assert rows[-1]['rolling'] == pytest.approx(9 / 11 * 100)
    assert calendar.totals(rows) == (11, 120, pytest.approx(9 / 11 * 100))
    html = calendar.calendar_html(rows)
    assert html.index('Mon') < html.index('Sun') < html.index('Week total')
    assert html.count('Partial week') == 2


def test_rolling_uses_days_before_visible_window_and_dst():
    rows = calendar.aggregate_days(date(2026, 9, 17), [], [
        {'entry_date': '2026-08-18', 'correct_count': 1, 'incorrect_count': 0},
    ], [])
    assert rows[0]['total'] == 0
    assert rows[0]['rolling'] == 100
    assert rows[6]['rolling'] is None
    assert calendar.utc_boundary(date(2026, 3, 8)) == '2026-03-08 05:00:00'
    assert calendar.utc_boundary(date(2026, 3, 9)) == '2026-03-09 04:00:00'


def test_course_scores_and_report_escape():
    stats = calendar.course_summary([
        {'course_title': '<Course>', 'attempt_id': 1, 'completed_at': '2026-09-16', 'is_correct': 1},
        {'course_title': '<Course>', 'attempt_id': 2, 'completed_at': '2026-09-17', 'is_correct': 0},
        {'course_title': '<Course>', 'attempt_id': 2, 'completed_at': '2026-09-17', 'is_correct': 1},
    ])
    assert stats['<Course>']['average'] == 75
    assert stats['<Course>']['latest'] == 50
    assert stats['<Course>']['pct'] == pytest.approx(200 / 3)
    plain, html = calendar.report_content([], 'accuracy', 'Course performance', '<Scope>', stats, 'All time')
    assert '&lt;Course&gt;' in html and '<Course>' not in html
    assert '<Course>' in plain


def test_send_uses_profile_and_existing_transport(monkeypatch):
    from src import email_notifications as email
    monkeypatch.setattr(calendar.database, 'get_setting', lambda *args: 'learner@example.com')
    monkeypatch.setattr(email, '_load_smtp_settings', lambda: {'host': 'test', 'port': '587', 'from_email': 'app@example.com'})
    sent = []
    monkeypatch.setattr(email, '_send_message', lambda msg, smtp: sent.append(msg))
    assert calendar.send_report(7, 'Progress', 'Plain report', '<p>HTML report</p>') == 'learner@example.com'
    message = BytesParser(policy=policy.default).parsebytes(sent[0].as_bytes())
    assert message['To'] == 'learner@example.com'
    assert message.get_body(preferencelist=('plain',)).get_content().strip() == 'Plain report'
    assert '<p>HTML report</p>' in message.get_body(preferencelist=('html',)).get_content()
    monkeypatch.setattr(calendar.database, 'get_setting', lambda *args: '')
    with pytest.raises(ValueError, match='valid email'):
        calendar.send_report(7, 'Progress', '', '')
    assert len(sent) == 1
