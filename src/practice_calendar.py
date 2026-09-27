"""Thirty-day all-practice calendar and email-ready dashboard summaries."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from zoneinfo import ZoneInfo

from src import database

ZONE = ZoneInfo("America/New_York")


def utc_boundary(day):
    return datetime.combine(day, datetime.min.time(), tzinfo=ZONE).astimezone(
        timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def aggregate_days(today, answers, external, timers):
    # Six extra days make the first visible day's trailing average complete.
    start = today - timedelta(days=35)
    days = {start + timedelta(days=i): {"date": start + timedelta(days=i),
            "total": 0, "correct": 0, "seconds": 0.0} for i in range(36)}
    for answer in answers:
        if answer.get("mode") != "practice" or not answer.get("completed_at"):
            continue
        stamp = datetime.fromisoformat(str(answer["completed_at"]).replace("Z", "+00:00"))
        day = (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(ZONE).date()
        if day in days:
            days[day]["total"] += 1
            days[day]["correct"] += int(bool(answer.get("is_correct")))
    for entry in external:
        day = datetime.fromisoformat(entry["entry_date"]).date()
        if day in days:
            days[day]["correct"] += int(entry["correct_count"])
            days[day]["total"] += int(entry["correct_count"]) + int(entry["incorrect_count"])
    for entry in timers:
        day = datetime.fromisoformat(entry["activity_date"]).date()
        if day in days:
            days[day]["seconds"] += float(entry["active_seconds"])
    for day, row in days.items():
        row["accuracy"] = row["correct"] / row["total"] * 100 if row["total"] else None
        window = [days[d] for d in days if day - timedelta(days=6) <= d <= day]
        total = sum(r["total"] for r in window)
        row["rolling"] = sum(r["correct"] for r in window) / total * 100 if total else None
    return [r for d, r in days.items() if d >= today - timedelta(days=29)]


def load_days(user_id, today):
    start, end = today - timedelta(days=35), today + timedelta(days=1)
    answers = database.get_answer_stats(user_id, completed_from=utc_boundary(start),
        completed_to=utc_boundary(end), include_in_progress_practice=True)
    external = database.get_external_practice_entries(user_id, entry_from=start.isoformat(), entry_to=end.isoformat())
    timers = database.get_study_time_entries(user_id, entry_from=start.isoformat(), entry_to=end.isoformat(), mode="practice")
    return aggregate_days(today, answers, external, timers)


def percent(value):
    return f"{value:.0f}%" if value is not None else "—"


def duration(seconds):
    if 0 < seconds < 60:
        return "<1m"
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def totals(rows):
    total = sum(r["total"] for r in rows)
    return total, sum(r["seconds"] for r in rows), (sum(r["correct"] for r in rows) / total * 100 if total else None)


def accuracy_color(value):
    """Continuous red / yellow / green scale; missing observations stay neutral."""
    if value is None:
        return '#f1f5f9'
    value = max(0, min(100, value))
    stops = ((190, 45, 50), (255, 231, 139), (45, 153, 88))
    left, right = (stops[0], stops[1]) if value <= 50 else (stops[1], stops[2])
    t = value / 50 if value <= 50 else (value - 50) / 50
    return '#' + ''.join(f'{round(a + (b-a)*t):02x}' for a, b in zip(left, right))


def calendar_html(rows, metric="accuracy", *, interactive=False):
    by_day = {r["date"]: r for r in rows}
    first = rows[0]["date"] - timedelta(days=rows[0]["date"].weekday())
    last = rows[-1]["date"] + timedelta(days=6 - rows[-1]["date"].weekday())
    out = ['<div style="overflow-x:auto"><table style="width:100%;min-width:720px;border-collapse:separate;border-spacing:5px"><thead><tr>']
    out.extend(f'<th style="text-align:left;padding:6px">{d}</th>' for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Week total"))
    out.append('</tr></thead><tbody>')
    day = first
    while day <= last:
        out.append('<tr>')
        week = []
        for _ in range(7):
            row = by_day.get(day)
            if row is None:
                out.append('<td style="opacity:.3;padding:10px">—</td>')
            else:
                week.append(row)
                value = row[metric]
                color = accuracy_color(value)
                ink = '#ffffff' if value is not None and value < 20 else '#172033'
                border = "2px solid #2563eb" if day == rows[-1]["date"] else "1px solid #cbd5e1"
                label = "Accuracy" if metric == "accuracy" else "7-day avg"
                content = (
                    f'<strong>{day:%b} {day.day}</strong><br><span>{row["total"]:,} questions</span><br>'
                    f'<span>{duration(row["seconds"])} active</span><br><strong>{percent(value)}</strong> <small>{label}</small>')
                if interactive:
                    content = (f'<a href="Practice_Day?date={day.isoformat()}&metric={metric}" target="_blank" rel="noopener noreferrer" '
                               f'aria-label="Explore practice on {day:%B %d, %Y} (opens a new tab)" '
                               f'style="display:block;padding:10px;color:{ink};text-decoration:none">{content}</a>')
                padding = '0' if interactive else '10px'
                out.append(f'<td style="padding:{padding};border:{border};border-radius:8px;background:{color};color:{ink};vertical-align:top">{content}</td>')
            day += timedelta(days=1)
        count, seconds, accuracy = totals(week)
        out.append(f'<td style="padding:10px;vertical-align:top"><strong>{count:,} questions</strong><br>{duration(seconds)} active<br>{percent(accuracy)} accuracy'
                   + ('<br><small>Partial week</small>' if len(week) < 7 else '') + '</td></tr>')
    return ''.join(out) + '</tbody></table></div>'


def report_content(rows, metric, kind, scope, stats, period):
    parts = ['<h1>StudyForge progress report</h1>']
    plain = ['StudyForge progress report']
    if kind != "Course performance":
        title = f'All practice · {rows[0]["date"]:%b %d, %Y} – {rows[-1]["date"]:%b %d, %Y}'
        count, seconds, accuracy = totals(rows)
        summary = f'{count:,} questions · {duration(seconds)} active · {percent(accuracy)} practice accuracy'
        note = ('America/New_York. All courses and external practice totals; timed exams excluded. '
                'Active time is recorded practice timer time, excluding pauses. Accuracy is correct / answered; '
                '7-day averages include the six days before each date. Blank accuracy means no answers. '
                'Older answers without a submission timestamp use session completion date. '
                'Practice accuracy is not a CFA exam score prediction.')
        parts.extend([f'<h2>{escape(title)}</h2><p>{summary}</p>', calendar_html(rows, metric), f'<p>{note}</p>'])
        plain.extend([title, summary, note])
        plain.extend(f'{r["date"]}: {r["total"]} questions, {duration(r["seconds"])} active, {percent(r[metric])} '
                     + ('accuracy' if metric == 'accuracy' else '7-day accuracy') for r in rows)
    if kind != "30-day practice":
        title = f'Course performance · {scope} · {period}'
        parts.append(f'<h2>{escape(title)}</h2><p>Completed sessions only. Average and latest are session percentages.</p>')
        plain.append(title)
        parts.append('<table style="width:100%;text-align:left"><tr><th>Course</th><th>Questions</th><th>Accuracy</th><th>Sessions</th><th>Average</th><th>Latest</th></tr>')
        for name, data in stats.items():
            values = [name, str(data['total']), percent(data['pct']), str(data['attempts']), percent(data['average']), percent(data['latest'])]
            parts.append('<tr>' + ''.join(f'<td>{escape(v)}</td>' for v in values) + '</tr>')
            plain.append(' | '.join(values))
        if not stats:
            parts.append('<tr><td colspan="6">No completed sessions in this scope and period.</td></tr>')
            plain.append('No completed sessions in this scope and period.')
        parts.append('</table>')
    return '\n'.join(plain), ''.join(parts)


def course_summary(answers):
    groups = {}
    for a in answers:
        name = a.get('course_title') or 'Unassigned'
        sessions = groups.setdefault(name, {})
        session = sessions.setdefault(a['attempt_id'], {'total': 0, 'correct': 0, 'date': a['completed_at']})
        session['total'] += 1
        session['correct'] += int(bool(a['is_correct']))
    result = {}
    for name, sessions in sorted(groups.items()):
        values = list(sessions.values())
        total = sum(v['total'] for v in values)
        latest = max(sessions.items(), key=lambda pair: (pair[1]['date'], pair[0]))[1]
        result[name] = {'total': total, 'pct': sum(v['correct'] for v in values) / total * 100,
                        'attempts': len(values), 'average': sum(v['correct'] / v['total'] * 100 for v in values) / len(values),
                        'latest': latest['correct'] / latest['total'] * 100}
    return result


def send_report(user_id, subject, plain, html, pdf=None, filename='studyforge-dashboard.pdf'):
    from src.email_notifications import USER_EMAIL_KEY, _load_smtp_settings, _missing_smtp_message, _send_message
    from src.offline_email import valid_email
    recipient = database.get_setting(user_id, USER_EMAIL_KEY).strip()
    if not valid_email(recipient):
        raise ValueError('Add a valid email address in Settings first.')
    smtp = _load_smtp_settings()
    missing = _missing_smtp_message(smtp)
    if missing:
        raise ValueError(missing)
    message = EmailMessage()
    message['Subject'], message['From'], message['To'] = subject, smtp['from_email'], recipient
    message.set_content(plain)
    message.add_alternative(html, subtype='html')
    if pdf is not None:
        message.add_attachment(pdf, maintype='application', subtype='pdf', filename=filename)
    _send_message(message, smtp)
    return recipient


def render_practice_calendar(user_id, scope, course_ids, time_context, sections=(), *, rows=None, show_summary=True):
    import streamlit as st
    from src.email_notifications import USER_EMAIL_KEY
    today = datetime.now(ZONE).date()
    rows = rows if rows is not None else load_days(user_id, today)
    st.markdown('### All practice · Last 30 days')
    st.caption(f'{rows[0]["date"]:%b %d} – {today:%b %d, %Y} · America/New_York · All courses + external practice · Independent of dashboard filters')
    count, seconds, accuracy = totals(rows)
    if show_summary:
        cols = st.columns(3)
        cols[0].metric('Total questions', f'{count:,}')
        cols[1].metric('Active time', duration(seconds))
        cols[2].metric('Practice accuracy', percent(accuracy))
    choice = st.radio('Calendar accuracy metric', ['Daily practice accuracy', 'Trailing 7-day accuracy'], horizontal=True, key='practice_calendar_metric')
    metric = 'accuracy' if choice == 'Daily practice accuracy' else 'rolling'
    st.markdown(calendar_html(rows, metric, interactive=True), unsafe_allow_html=True)
    st.caption('Click a day to explore its metrics and records in a new tab. Your dashboard stays open here.')
    st.caption('Accuracy = correct ÷ answered. Color scale: 0% red → 50% yellow → 100% green; no data is gray. Colors are not passing thresholds. '
               'Weekly totals include only visible dates. Active time excludes pauses; external time is not recorded. '
               'Older answers without submission timestamps use session completion date. Timed exams are excluded.')
    st.caption('The 7-day view smooths daily swings using question-weighted accuracy. Practice accuracy is not a CFA exam score prediction.')
