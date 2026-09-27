from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
import pytest
from src import database
from src import provider_reminders as reminders
from src.provider_import import import_kaplan
from tests.test_provider_import import page, db


def test_coverage_is_explicit_atomic_and_monotonic(db):
    import_kaplan(1, page())
    assert reminders.requested_range(1, date(2026, 9, 22)) == (None, date(2026, 9, 21))
    import_kaplan(1, page(), complete_through='2026-09-01')
    assert reminders.requested_range(1, date(2026, 9, 22))[0] == date(2026, 9, 2)
    import_kaplan(1, page(), complete_through='2026-08-01')
    assert database.get_setting(1, 'kaplan_complete_through') == '2026-09-01'
    with pytest.raises(ValueError):
        import_kaplan(1, page() + page('IN PROGRESS', '1:02 PM'), complete_through='2026-09-10')
    assert database.get_setting(1, 'kaplan_complete_through') == '2026-09-01'
    assert database.get_setting(2, 'kaplan_complete_through') == ''


def configure():
    for k, v in {'kaplan_email_enabled':'true', 'kaplan_reminder_days':'7', 'profile_email':'student@example.com', 'kaplan_app_url':'https://study.example.com', 'kaplan_complete_through':'2026-09-01'}.items():
        database.set_setting(1, k, v)


def test_message_and_interval(db, monkeypatch):
    configure()
    sent = []
    monkeypatch.setattr(reminders, '_load_smtp_settings', lambda: {'from_email':'app@example.com'})
    monkeypatch.setattr(reminders, '_missing_smtp_message', lambda smtp: '')
    monkeypatch.setattr(reminders, '_send_message', lambda msg, smtp: sent.append(msg))
    now = datetime(2026, 9, 22, 0, 5, tzinfo=reminders.ZONE)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: reminders.run_due_requests(now), range(2)))
    assert len(sent) == 1
    assert 'September 02, 2026 through September 21, 2026' in sent[0].get_content()
    assert 'https://study.example.com/Kaplan_Update' in sent[0].get_content()
    assert reminders.run_due_requests(now.replace(day=28)) == []
    assert reminders.run_due_requests(now.replace(day=29)) == [(1, 'sent')]
    database.set_setting(1, 'kaplan_email_enabled', 'false')
    assert reminders.run_due_requests(now.replace(month=10)) == []


def test_no_practice_and_link_validation(db):
    import_kaplan(1, page(), complete_through='2026-09-01')
    before = database.get_external_practice_entries(1)
    reminders.confirm_no_new_quizzes(1, '2026-09-10')
    assert database.get_external_practice_entries(1) == before
    assert reminders.requested_range(1, date(2026, 9, 22))[0] == date(2026, 9, 11)
    with pytest.raises(ValueError):
        reminders.confirm_no_new_quizzes(1, '2026-09-01')
    with pytest.raises(ValueError):
        reminders.submission_url('javascript:alert(1)')
    assert reminders.submission_url('https://example.com/study/') == 'https://example.com/study/Kaplan_Update'


def test_uncertain_delivery_not_retried(db, monkeypatch):
    configure()
    monkeypatch.setattr(reminders, 'build_request', lambda *args: (None, None))
    def fail(*args):
        raise OSError('uncertain SMTP result')
    monkeypatch.setattr(reminders, '_send_message', fail)
    now = datetime(2026, 9, 22, 0, 5, tzinfo=reminders.ZONE)
    assert reminders.run_due_requests(now) == [(1, 'delivery_unconfirmed')]
    assert reminders.run_due_requests(now) == []

def test_caught_up_and_invalid_setup_do_not_send(db, monkeypatch):
    configure()
    now = datetime(2026, 9, 22, 0, 5, tzinfo=reminders.ZONE)
    database.set_setting(1, 'kaplan_complete_through', '2026-09-21')
    assert reminders.run_due_requests(now) == []
    database.set_setting(1, 'kaplan_complete_through', '2026-09-01')
    database.set_setting(1, 'kaplan_app_url', '')
    assert reminders.run_due_requests(now) == [(1, 'Kaplan request configuration needs review')]
    conn = database.get_connection()
    assert conn.execute('SELECT COUNT(*) FROM kaplan_request_deliveries').fetchone()[0] == 0
    conn.close()


def test_ui_confirms_coverage_and_shows_following_day(db):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('from src.provider_import_ui import render_provider_import\nrender_provider_import(1)').run()
    app.text_area[0].set_value(page()).run()
    app.date_input[0].set_value(date(2026, 9, 1))
    next(c for c in app.checkbox if c.label.startswith('This includes')).check()
    next(b for b in app.button if b.label == 'Import Kaplan results').click().run()
    assert not app.exception
    assert database.get_setting(1, 'kaplan_complete_through') == '2026-09-01'
    assert 'September 02, 2026' in app.info[0].value
