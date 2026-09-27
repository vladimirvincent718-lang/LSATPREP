import pytest
from src import database
from src.provider_import import parse_kaplan, import_kaplan, next_reminder, valid_provider_url


def page(score='66.67%', time='12:01 AM', title='Reading 1 QBank'):
    return f'{title}\nJune 28, 2026 - {time}\n3 Questions\n00:10:00\ntime spent 00hours 10minutes 00seconds\n{score}\n'


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    conn = database.get_connection()
    conn.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY); INSERT INTO users VALUES(1); INSERT INTO users VALUES(2); CREATE TABLE settings(user_id INTEGER, key TEXT, value TEXT, UNIQUE(user_id,key));')
    conn.close()


def test_parser_rounding_and_unfinished():
    parsed = parse_kaplan(page() + page('IN PROGRESS', '1:02 PM'))
    assert parsed['skipped'] == 1
    assert parsed['quizzes'][0]['correct_count'] == 2
    assert parsed['quizzes'][0]['started_at'] == '2026-06-28T00:01:00'
    assert parse_kaplan(page('0%'))['quizzes'][0]['correct_count'] == 0


def test_reject_partial_and_invalid():
    with pytest.raises(ValueError):
        parse_kaplan(page() + 'Other quiz\n4 Questions\n')
    with pytest.raises(ValueError):
        parse_kaplan(page('50%'))


def test_repeat_and_overlapping_imports(db):
    assert import_kaplan(1, page())['added'] == 1
    assert import_kaplan(1, page())['added'] == 0
    assert import_kaplan(1, page(time='1:00 PM'))['added'] == 1
    row = database.get_external_practice_entries(1)[0]
    assert (row['correct_count'], row['incorrect_count']) == (4, 2)
    assert database.get_external_practice_entries(2) == []
    import_kaplan(1, page('100%'))
    assert database.get_external_practice_entries(1)[0]['correct_count'] == 5


def test_manual_conflict_is_atomic_and_explicit(db):
    database.save_external_practice_entry(1, '2026-06-28', 'Kaplan', 20, 10)
    database.save_external_practice_entry(1, '2026-06-28', 'Quizlet', 9, 1)
    with pytest.raises(ValueError):
        import_kaplan(1, page())
    assert database.get_external_practice_entries(1)[0]['correct_count'] == 20
    assert import_kaplan(1, page(), True)['added'] == 1
    assert database.get_external_practice_entries(1)[1]['correct_count'] == 9
    database.save_external_practice_entry(1, '2026-06-28', 'Kaplan', 8, 2)
    with pytest.raises(ValueError):
        import_kaplan(1, page())


def test_reminders_and_links(db):
    database.set_setting(1, 'kaplan_last_import', '2026-09-17')
    assert next_reminder(1).isoformat() == '2026-09-24'
    database.set_setting(1, 'kaplan_reminder_days', '0')
    assert next_reminder(1) is None
    assert valid_provider_url('https://example.com/quizzes')
    assert not valid_provider_url('javascript:alert(1)')
    assert not valid_provider_url('https://user:password@example.com')


def test_import_ui(db):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('from src.provider_import_ui import render_provider_import\nrender_provider_import(1)').run()
    assert not app.exception
    app.text_area[0].set_value(page()).run()
    assert not app.exception
    next(b for b in app.button if b.label == 'Import Kaplan results').click().run()
    assert not app.exception
    assert database.get_external_practice_entries(1)[0]['correct_count'] == 2
