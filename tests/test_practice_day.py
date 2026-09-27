from datetime import date

from src import practice_day
from src.practice_calendar import aggregate_days, calendar_html


def test_calendar_links_each_real_day_only_and_exports_stay_portable():
    rows = aggregate_days(date(2026, 9, 17), [], [], [])
    html = calendar_html(rows, 'rolling', interactive=True)
    assert html.count('href="Practice_Day?date=') == 30
    assert 'date=2026-09-17&metric=rolling' in html
    assert 'date=2026-08-18' not in html
    assert html.count('target="_blank"') == 30
    assert 'Practice_Day' not in calendar_html(rows)


def test_date_validation():
    today = date(2026, 9, 17)
    assert practice_day.parse_day('2026-09-10', today) == date(2026, 9, 10)
    assert practice_day.parse_day('2026-10-01', today) == today
    for invalid in (None, '', 'bad', '2026-02-30'):
        assert practice_day.parse_day(invalid, today) == today


def test_records_use_same_user_local_window_and_practice_scope(monkeypatch):
    calls = []
    def answers(uid, **kwargs):
        calls.append((uid, kwargs))
        return [{'mode': 'practice'}, {'mode': 'full_exam'}]
    monkeypatch.setattr(practice_day.database, 'get_answer_stats', answers)
    monkeypatch.setattr(practice_day.database, 'get_external_practice_entries', lambda uid, **kw: calls.append((uid, kw)) or [])
    monkeypatch.setattr(practice_day.database, 'get_study_time_entries', lambda uid, **kw: calls.append((uid, kw)) or [])
    result = practice_day.load_day_records(42, date(2026, 3, 8))
    assert result[0] == [{'mode': 'practice'}]
    assert all(uid == 42 for uid, _ in calls)
    assert calls[0][1]['completed_from'] == '2026-03-08 05:00:00'
    assert calls[0][1]['completed_to'] == '2026-03-09 04:00:00'
    assert calls[0][1]['include_answer_details'] is True
    assert calls[1][1] == {'entry_from': '2026-03-08', 'entry_to': '2026-03-09'}
    assert calls[2][1]['mode'] == 'practice'
    calls.clear()
    practice_day.load_day_records(42, date(2026, 3, 8), days=7)
    assert calls[0][1]['completed_from'] == '2026-03-02 05:00:00'
