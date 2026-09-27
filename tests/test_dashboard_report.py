import json
from datetime import date, datetime
from io import BytesIO

from pypdf import PdfReader

from src import database as db
from src import dashboard_report as report
from src import dashboard_report_schedule as scheduler
from src.practice_calendar import ZONE, accuracy_color, aggregate_days


def test_heatmap_endpoints_and_no_data():
    assert accuracy_color(None) == '#f1f5f9'
    assert accuracy_color(0) == '#be2d32'
    assert accuracy_color(50) == '#ffe78b'
    assert accuracy_color(100) == '#2d9958'
    assert len({accuracy_color(v) for v in range(101)}) == 101


def test_pdf_contains_complete_dashboard_and_zero_courses():
    snapshot = {'day': date(2026, 9, 17), 'scope': 'CFA Level I Test', 'period': 'All time', 'metric': 'accuracy',
                'days': aggregate_days(date(2026, 9, 17), [], [], []), 'exam_days': '61', 'exam_note': 'Nov 17, 2026',
                'mock': None, 'kpis': [('Questions in bank', '4676'), ('Sessions completed', '58'),
                ('Total Qs answered', '957'), ('Latest score', '80%'), ('Best score', '100%'), ('Average score', '49%')],
                'courses': [['Financial Modeling', 'Not started', '—', '—', '0', '0', '24', '—']],
                'blocks': [{'title': 'Accuracy by module', 'headers': ['Module', 'Accuracy'], 'rows': [['Module <1>', '72%']]}]}
    pdf = report.snapshot_pdf(snapshot)
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) >= 3
    text = '\n'.join(p.extract_text() for p in reader.pages)
    for required in ['All practice', 'Dashboard summary', 'Course performance', 'Financial Modeling', 'Not started', 'Accuracy by module', '4676']:
        assert required in text
    assert 'material review(s) due' not in text
    assert '&lt;1&gt;' in report.snapshot_html(snapshot)
    snapshot['layout'] = ['Course dashboard cards', 'Practice summary']
    html = report.snapshot_html(snapshot)
    assert html.index('Course performance') < html.index('All practice')
    assert 'Days till exam' not in html and 'Accuracy by module' not in html
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(report.snapshot_pdf(snapshot))).pages)
    assert text.index('Course performance') < text.index('All practice')
    assert 'Days till exam' not in text and 'Accuracy by module' not in text


def test_overnight_relative_window_ends_at_previous_midnight():
    context = {'label': 'Last 30 days: 2026-08-19 to 2026-09-17'}
    result = report.scheduled_time(context, date(2026, 9, 18))
    assert result['completed_from'] == '2026-08-20 04:00:00'
    assert result['completed_to'] == '2026-09-19 04:00:00'


def schedule_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'schedule.db')
    with db.get_connection() as conn:
        conn.execute('CREATE TABLE settings (user_id INTEGER, key TEXT, value TEXT)')
        conn.execute('INSERT INTO settings VALUES (1, ?, ?)', (report.SCHEDULE_KEY, json.dumps({'frequency': 'Daily'})))


def test_delivery_previous_day_once_and_no_early_delivery(monkeypatch, tmp_path):
    schedule_db(monkeypatch, tmp_path)
    built, sent = [], []
    monkeypatch.setattr(scheduler, 'build_snapshot', lambda uid, config, day, **kw: built.append(day) or {'day': day})
    monkeypatch.setattr(scheduler, 'deliver_snapshot', lambda uid, snap: sent.append(snap))
    assert scheduler.run_due_reports(datetime(2026, 9, 18, 0, 4, tzinfo=ZONE)) == []
    now = datetime(2026, 9, 18, 0, 5, tzinfo=ZONE)
    assert scheduler.run_due_reports(now) == [(1, 'sent')]
    assert built == [date(2026, 9, 17)]
    assert scheduler.run_due_reports(now) == []
    assert len(sent) == 1


def test_uncertain_delivery_never_automatically_resends(monkeypatch, tmp_path):
    schedule_db(monkeypatch, tmp_path)
    monkeypatch.setattr(scheduler, 'build_snapshot', lambda *args, **kw: {})
    called = []
    def fail(*args):
        called.append(True)
        raise TimeoutError()
    monkeypatch.setattr(scheduler, 'deliver_snapshot', fail)
    now = datetime(2026, 9, 18, 0, 5, tzinfo=ZONE)
    assert scheduler.run_due_reports(now) == [(1, 'delivery_unconfirmed')]
    assert 'requires review' in scheduler.run_due_reports(now)[0][1]
    assert len(called) == 1


def test_frequency_days():
    monday = datetime(2026, 9, 21, 0, 5, tzinfo=ZONE)
    assert scheduler.is_due({'frequency': 'Weekly', 'weekday': 0}, monday)
    assert not scheduler.is_due({'frequency': 'Weekly', 'weekday': 1}, monday)
    assert not scheduler.is_due({'frequency': 'Off'}, monday)
    assert not scheduler.is_due({'frequency': 'Weekdays'}, datetime(2026, 9, 20, 0, 5, tzinfo=ZONE))


def test_expanded_course_details_follow_the_parent_row():
    detail = {'course_index': 0, 'title': 'Ethics modules', 'key': 'Course dashboard cards', 'headers': ['Module'], 'rows': [['Ethics 1']]}
    blocks = report.course_blocks({'courses': [['Ethics'], ['Equity']], 'course_details': [detail]})
    assert blocks[0]['rows'] == [['Ethics']]
    assert blocks[1] == detail
    assert blocks[2]['rows'] == [['Equity']]
