"""Portable dashboard snapshot shared by previews, PDF emails, and scheduled runs."""
import calendar
import json
from datetime import date, datetime, timedelta
from html import escape
from io import BytesIO

from src import database as db
from src.analytics import get_dashboard_stats, get_module_attempt_history
from src.practice_calendar import (ZONE, accuracy_color, calendar_html, duration,
                                   load_days, percent, send_report, totals, utc_boundary)

SCHEDULE_KEY = 'dashboard_email_schedule_v1'


def score_percent(value):
    return f'{value:.1f}%' if value is not None else '—'


def report_config(scope, course_ids, time_context, sections, metric, *, mode='Curriculum', curriculum_id=None):
    return {'scope': scope, 'course_ids': list(course_ids), 'time': dict(time_context),
            'sections': sorted(sections), 'metric': metric, 'mode': mode, 'curriculum_id': curriculum_id}


def scheduled_time(context, day):
    """Re-evaluate relative dashboard date filters at the report's closing date."""
    label = context.get('label', 'All time').split(':', 1)[0]
    start, end = None, day
    if label.startswith('Last ') and label.endswith(' days'):
        start = day - timedelta(days=int(label.split()[1]) - 1)
    elif label == 'This month':
        start = day.replace(day=1)
    elif label == 'Last month':
        end = day.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif label == 'Year to date':
        start = day.replace(month=1, day=1)
    elif label in ('Custom range', 'Specific month'):
        result = dict(context)
        cutoff = utc_boundary(day + timedelta(days=1))
        result['completed_to'] = min(result.get('completed_to') or cutoff, cutoff)
        return result
    return {**context, 'completed_from': utc_boundary(start) if start else None,
            'completed_to': utc_boundary(end + timedelta(days=1)),
            'label': f'{label} through {end.isoformat()}'}


def build_snapshot(user_id, config, day=None, *, scheduled=False, rows=None):
    from src.exam_planning import get_exam_plan, exam_countdown
    from src.mock_review import get_next_mock_summary
    day = day or datetime.now(ZONE).date()
    context = scheduled_time(config['time'], day) if scheduled else config['time']
    bounds = {k: context.get(k) for k in ('completed_from', 'completed_to')}
    ids = config['course_ids']
    stats = get_dashboard_stats(user_id, course_ids=ids, **bounds)
    courses = []
    from src.dashboard_layout import load_expansion
    expansion = load_expansion(user_id, config.get('mode', 'Curriculum'))
    course_details = []
    for cid in ids:
        course = db.get_course(cid)
        if not course:
            continue
        data = get_dashboard_stats(user_id, course_id=cid, **bounds)
        avg = data['avg_percent']
        status = 'Not started' if avg is None else 'Focus' if avg < 60 else 'Developing' if avg < 75 else 'On track'
        courses.append([course['title'], status, score_percent(avg), score_percent(data['latest_percent']),
                        str(data['total_attempts']), str(data['total_questions']), str(db.get_course_question_count(cid)),
                        f"{data['improvement_trend']:+.1f}%" if data['improvement_trend'] is not None else '—'])
        if expansion.get(f'course_{cid}', False):
            from src.utils import format_module_label, module_sort_key, DIFFICULTY_LABELS
            bank = db.get_course_module_question_counts(cid)
            difficulty_bank = db.get_course_module_difficulty_question_counts(cid)
            module_records = []
            for module in sorted(set(bank) | set(data['accuracy_by_module']), key=module_sort_key):
                result = data['accuracy_by_module'].get(module, {})
                total, correct = result.get('total', 0), result.get('correct', 0)
                module_records.append([format_module_label(module), score_percent(result.get('pct') if total else None), str(total), str(total-correct), str(bank.get(module, 0))])
                if expansion.get(f'module_{cid}_{module}', False):
                    for level, label in sorted(DIFFICULTY_LABELS.items()):
                        value = data['accuracy_by_module_difficulty'].get(module, {}).get(level, {})
                        n, c = value.get('total', 0), value.get('correct', 0)
                        module_records.append(['    ' + label, score_percent(value.get('pct') if n else None), str(n), str(n-c), str(difficulty_bank.get(module, {}).get(level, 0))])
            course_details.append({'course_index': len(courses)-1, 'key': 'Course dashboard cards', 'title': course['title'] + ' · Modules',
                                   'headers': ['Module / expanded difficulty', 'Accuracy', 'Answered', 'Missed', 'Bank'], 'rows': module_records})
    kpis = [('Questions in bank', str(sum(int(r[6]) for r in courses))),
            ('Sessions completed', str(stats['total_attempts'])), ('Total Qs answered', str(stats['total_questions'])),
            ('Latest score', score_percent(stats['latest_percent'])), ('Best score', score_percent(stats['best_percent'])),
            ('Average score', score_percent(stats['avg_percent']))]
    sections = set(config.get('sections', []))
    from src.dashboard_layout import load_layout, visible_order
    layout = visible_order(load_layout(user_id, config.get('mode', 'Curriculum'), sections))
    blocks = []
    def block(title, headers, records):
        key = title
        if title in ('Accuracy by question type', 'Accuracy by difficulty'):
            key = 'Question type and difficulty' if 'Question type and difficulty' in sections else 'Performance overview'
        elif title == 'Score trend analysis' and 'Performance overview' in sections:
            key = 'Performance overview'
        elif title == 'Weakest courses' and 'Weakest courses' not in sections:
            key = 'Performance overview'
        elif title == 'Materials progress':
            key = 'Dashboard summary'
        blocks.append({'title': title, 'headers': headers, 'rows': records, 'key': key})
    def accuracy_block(title, data):
        block(title, [title.removeprefix('Accuracy by '), 'Answered', 'Correct', 'Accuracy'],
              [[str(k), str(v['total']), str(v['correct']), percent(v['pct'])] for k, v in data.items()])
    trend = stats['score_trend']
    if sections & {'Performance overview', 'Score trend analysis'}:
        block('Score trend analysis', ['Completed (UTC)', 'Session', 'Mode', 'Questions', 'Correct', 'Score'],
              [[str(r.completed_at), str(r.attempt_id), str(r.mode), str(r.total_questions), str(r.correct_answers), percent(r.percent_correct)]
               for r in trend.itertuples()] if not trend.empty else [])
    if 'Performance overview' in sections:
        accuracy_block('Accuracy by difficulty', stats['accuracy_by_diff'])
    if 'Daily activity' in sections:
        answers = db.get_answer_stats(user_id, course_ids=ids, **bounds)
        grouped = {}
        for a in answers:
            key = str(a['completed_at'])[:10]
            v = grouped.setdefault(key, [0, 0])
            v[0] += 1
            v[1] += int(bool(a['is_correct']))
        block('Daily activity', ['Completion date (UTC)', 'Answered', 'Correct', 'Accuracy'],
              [[k, str(v[0]), str(v[1]), percent(v[1] / v[0] * 100)] for k, v in sorted(grouped.items())])
    for option, key in [('Accuracy by course', 'accuracy_by_course'), ('Accuracy by module', 'accuracy_by_module')]:
        if option in sections:
            accuracy_block(option, stats[key])
    if 'Question type and difficulty' in sections:
        accuracy_block('Accuracy by question type', stats['accuracy_by_type'])
        if 'Performance overview' not in sections:
            accuracy_block('Accuracy by difficulty', stats['accuracy_by_diff'])
    if sections & {'Weakest courses', 'Performance overview'}:
        block('Weakest courses', ['Course', 'Answered', 'Accuracy'],
              [[r['course'], str(r['total']), percent(r['pct'])] for r in stats['weak_courses']])
    if 'Module attempt report' in sections:
        data = get_module_attempt_history(user_id, course_ids=ids, **bounds)
        fields = ['Course', 'Module', 'Date', 'Mode', 'Questions', 'Correct', '% Correct', 'Attempt #']
        block('Module attempt report', fields, [[str(r[f]) for f in fields] for r in data.to_dict('records')])
    if 'Materials progress' in sections:
        material_rows = []
        for cid in ids:
            course = db.get_course(cid)
            if course:
                progress = db.get_material_progress(user_id, cid)
                materials = db.get_materials(cid)
                complete = sum(1 for m in materials if progress.get(m['id']) == 'Completed')
                material_rows.append([course['title'], str(complete), str(len(materials))])
        block('Materials progress', ['Course', 'Completed', 'Total'], material_rows)
    if 'Review activity' in sections:
        reviews = db.get_review_activity(user_id, course_ids=ids, reviewed_from=bounds['completed_from'], reviewed_to=bounds['completed_to'])
        block('Review activity', ['Completed (UTC)', 'Course', 'Module', 'Question'],
              [[str(r.get(k) or '—') for k in ('completed_at', 'course_title', 'section_type', 'question_id')] for r in reviews])
    if 'Question reports' in sections:
        reports = db.get_question_issue_reports(course_ids=ids)
        block('Question reports', ['Question', 'Status', 'Reported', 'Description'],
              [[str(r.get(k) or '—') for k in ('question_id', 'status', 'created_at', 'note')] for r in reports])
    if 'Current mock review' in layout:
        from src.mock_review_analytics import current_review_analytics, table_rows, HEADERS
        review = current_review_analytics(user_id, day=day)
        if expansion.get('mock_review_analytics', True):
            blocks.append({'key': 'Current mock review', 'title': review['title'], 'headers': HEADERS,
                           'rows': table_rows(review), 'note': review['note']})
        else:
            blocks.append({'key': 'Current mock review', 'title': review['title'], 'collapsed': True})
    if 'Course & module progress' in layout:
        if expansion.get('progress', False):
            from src.study_progress import load_progress, status, COLORS
            from src.practice_allocation import practice_questions, module_label
            progress = load_progress(user_id)
            if scheduled:
                cutoff = utc_boundary(day + timedelta(days=1))
                for group in ('courses', 'modules'):
                    progress[group] = {k: [r for r in v if str(r['completed_at']) < cutoff] for k, v in progress[group].items()}
            records = []
            for cid in ids:
                title = (db.get_course(cid) or {}).get('title', 'Course')
                for module in [None, *sorted({module_label(q) for q in practice_questions([cid]) if module_label(q)})]:
                    value = status(progress, [cid], module)
                    records.append([title + (' / ' + module if module else ''), COLORS[value['color']][1], score_percent(value['score']), str(value['questions']), str(value['sessions'])])
            block('Course & module progress', ['Course / module', 'Status', 'Score', 'Questions', 'Sessions'], records)
        else:
            blocks.append({'key': 'Course & module progress', 'title': 'Course & module progress', 'collapsed': True})
    if 'Curriculum reference materials' in layout:
        from src.curriculum_materials import get_curriculum_materials
        curriculum_id = config.get('curriculum_id')
        if curriculum_id is None:
            curriculum_id = next((c['id'] for c in db.get_all_curriculums() if c['title'] == config['scope']), None)
        refs = get_curriculum_materials(user_id, curriculum_id) if curriculum_id else []
        if expansion.get('references', True):
            block('Curriculum reference materials', ['Reference', 'Notes'], [[r['title'], r.get('notes', '')] for r in refs])
            for ref in refs:
                if expansion.get(f'reference_{ref["id"]}', False):
                    from src.material_review_ui import material_file
                    from src.flashcards import extract_text
                    path = material_file(ref)
                    text = extract_text(path.name, path.read_bytes()) if path else 'Reference document unavailable.'
                    blocks.append({'key': 'Curriculum reference materials', 'title': ref['title'], 'text': text})
        else:
            blocks.append({'key': 'Curriculum reference materials', 'title': 'Curriculum reference materials', 'collapsed': True})
    exam_days, exam_note = exam_countdown(get_exam_plan(user_id), day)
    mock = get_next_mock_summary(user_id, today=day)
    return {'day': day, 'scope': config['scope'], 'period': context.get('label', 'Selected period'),
            'metric': config.get('metric', 'accuracy'), 'days': rows if rows is not None else load_days(user_id, day),
            'kpis': kpis, 'courses': courses, 'blocks': blocks, 'exam_days': exam_days, 'exam_note': exam_note,
            'mock': mock, 'scheduled': scheduled, 'layout': layout, 'course_details': course_details}


COURSE_HEADERS = ['Course', 'Status', 'Average', 'Latest', 'Sessions', 'Answered', 'Bank', 'Trend']


def course_blocks(s):
    """Keep expanded details directly below their parent course, in display order."""
    details = {b['course_index']: b for b in s.get('course_details', [])}
    result, pending = [], []
    for index, row in enumerate(s['courses']):
        pending.append(row)
        if index in details:
            result.append({'title': 'Course performance' if not result else 'Course performance (continued)', 'key': 'Course dashboard cards', 'headers': COURSE_HEADERS, 'rows': pending})
            result.append(details[index])
            pending = []
    if pending or not result:
        result.append({'title': 'Course performance' if not result else 'Course performance (continued)', 'key': 'Course dashboard cards', 'headers': COURSE_HEADERS, 'rows': pending})
    return result


def report_order(s):
    return s.get('layout', ['Days till exam', 'Next mock exam', 'Practice summary', 'Practice calendar',
                           'Dashboard summary', 'Course dashboard cards', *dict.fromkeys(b.get('key', b['title']) for b in s['blocks'])])


def snapshot_html(s):
    def cards(values):
        return '<table style="width:100%;border-spacing:8px"><tr>' + ''.join(
            f'<td style="padding:16px;background:#eef2ff;border:1px solid #cbd5e1;border-radius:8px;color:#172033"><small>{escape(k)}</small><br><strong style="font-size:24px">{escape(v)}</strong></td>' for k, v in values) + '</tr></table>'
    count, seconds, accuracy = totals(s['days'])
    widgets = {
        'Days till exam': cards([('Days till exam', s['exam_days'])]) + f'<p>{escape(s["exam_note"])}</p>',
        'Practice summary': '<h2>All practice · Last 30 days</h2>' + cards([('Total questions', f'{count:,}'), ('Active time', duration(seconds)), ('Practice accuracy', percent(accuracy))]),
        'Practice calendar': '<h2>Practice calendar</h2>' + calendar_html(s['days'], s['metric']) + '<p>Red 0% → yellow 50% → green 100%. Gray = no data. Colors are not passing thresholds.</p>',
        'Dashboard summary': '<h2>Dashboard summary</h2>' + cards(s['kpis']) + f'<p>{escape(s["period"])}</p>',
    }
    if s['mock']:
        m = s['mock']
        widgets['Next mock exam'] = f'<h2>Next mock exam: {escape(m["label"])}</h2>' + cards([('Date', str(m['scheduled_date'])), ('Days remaining', str(m['days_remaining'])), ('Review items remaining', str(m['review_items_remaining']))])
    else:
        widgets['Next mock exam'] = '<h2>Next mock exam</h2><p>No upcoming mock exam scheduled.</p>'
    for b in [*course_blocks(s), *s['blocks']]:
        if b.get('collapsed') or 'text' in b:
            part = f'<h2>{escape(b["title"])}</h2><p>{escape(b.get("text", "Collapsed on dashboard."))}</p>'
            widgets[b['key']] = widgets.get(b['key'], '') + part
            continue
        part = [f'<h2>{escape(b["title"])}</h2>' + (f'<p>{escape(b["note"])}</p>' if b.get('note') else '') + '<table style="border-collapse:collapse;width:100%;text-align:left"><tr>']
        part.extend(f'<th style="padding:6px;border-bottom:1px solid #cbd5e1">{escape(h)}</th>' for h in b['headers'])
        part.append('</tr>')
        for row in b['rows']:
            part.append('<tr>' + ''.join(f'<td style="padding:6px;border-bottom:1px solid #e2e8f0">{escape(str(v))}</td>' for v in row) + '</tr>')
        part.append('</table>' if b['rows'] else '</table><p>No records in this scope and period.</p>')
        key = b.get('key', b['title'])
        widgets[key] = widgets.get(key, '') + ''.join(part)
    return f'<h1>StudyForge dashboard report</h1><p>{escape(s["scope"])} · Through {s["day"]} · America/New_York</p>' + ''.join(widgets.get(k, '') for k in report_order(s))


def snapshot_pdf(s):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from pathlib import Path
    font = 'Helvetica'
    font_path = Path('C:/Windows/Fonts/segoeui.ttf')
    if font_path.exists():
        if 'ReportUI' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('ReportUI', str(font_path)))
        font = 'ReportUI'
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    styles.add(ParagraphStyle('Cell', fontName=font, fontSize=8, leading=11, textColor=colors.HexColor('#172033')))
    styles.add(ParagraphStyle('Note', fontName=font, fontSize=8, leading=11, textColor=colors.HexColor('#475569')))
    styles['Heading1'].fontSize = 20
    styles['Heading2'].fontSize = 13
    styles['Heading1'].keepWithNext = True
    styles['Heading2'].keepWithNext = True
    def p(text, style='Cell'):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style])
    stream = BytesIO()
    width = landscape(A4)[0] - 64
    doc = SimpleDocTemplate(stream, pagesize=landscape(A4), rightMargin=32, leftMargin=32,
                            topMargin=26, bottomMargin=30, title='StudyForge dashboard report')
    def cards(values):
        style = ParagraphStyle('MetricValue', parent=styles['Cell'], fontSize=18, leading=23)
        cells = [[p(k, 'Note'), Paragraph(escape(v), style)] for k, v in values]
        table = Table([cells], colWidths=[width / len(values)] * len(values))
        table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef2ff')),
                                  ('BOX', (0, 0), (-1, -1), .5, colors.HexColor('#cbd5e1')),
                                  ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                  ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
        return table
    widgets = {'Days till exam': [cards([('Days till exam', s['exam_days'])]), p(s['exam_note'], 'Note')]}
    if s['mock']:
        m = s['mock']
        widgets['Next mock exam'] = [p('Next mock exam: ' + m['label'], 'Heading2'), cards([
            ('Date', str(m['scheduled_date'])), ('Days remaining', str(m['days_remaining'])),
            ('Review items remaining', str(m['review_items_remaining']))])]
    else:
        widgets['Next mock exam'] = [p('Next mock exam', 'Heading2'), p('No upcoming mock exam scheduled.')]
    count, seconds, accuracy = totals(s['days'])
    widgets['Practice summary'] = [p('All practice | Last 30 days', 'Heading2'), cards([
        ('Total questions', f'{count:,}'), ('Active time', duration(seconds)), ('Practice accuracy', percent(accuracy))])]
    story = [p('Practice calendar', 'Heading2')]
    lookup = {r['date']: r for r in s['days']}
    first = s['days'][0]['date']
    cursor = first - timedelta(days=first.weekday())
    table_rows = [[p(h) for h in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Week total']]]
    commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#cbd5e1')),
                ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0'))]
    while cursor <= s['day']:
        week, cells = [], []
        y = len(table_rows)
        for x in range(7):
            row = lookup.get(cursor)
            if row:
                week.append(row)
                value = row[s['metric']]
                label = 'accuracy' if s['metric'] == 'accuracy' else '7-day avg'
                style = ParagraphStyle('Calendar', parent=styles['Cell'], textColor=colors.white if value is not None and value < 20 else colors.HexColor('#172033'))
                cells.append(Paragraph(f'{cursor:%b %d}<br/>{row["total"]:,} questions<br/>{duration(row["seconds"])} active<br/>{percent(value)} {label}', style))
                commands.append(('BACKGROUND', (x, y), (x, y), colors.HexColor(accuracy_color(value))))
            else:
                cells.append(p(''))
            cursor += timedelta(days=1)
        n, sec, acc = totals(week)
        cells.append(p(f'{n:,} questions\n{duration(sec)} active\n{percent(acc)} accuracy' + ('\nPartial week' if len(week) < 7 else '')))
        table_rows.append(cells)
    table = Table(table_rows, colWidths=[width / 8] * 8)
    table.setStyle(TableStyle(commands))
    story.extend([table, Spacer(1, 6), p('Color scale: red 0% | yellow 50% | green 100% | gray: no data. Weekly totals cover visible dates only.', 'Note'),
                  p('Practice accuracy is correct / answered, including external practice. Active time excludes pauses and external study time. Timed exams are excluded. Colors are not passing thresholds. Older answers without submission dates use session completion dates.', 'Note'),
                  p('Trailing 7-day accuracy is question-weighted and includes the six days before each date.' if s['metric'] == 'rolling' else 'Calendar shows daily practice accuracy.', 'Note')])
    widgets['Practice calendar'] = story
    story = []
    story.extend([p('Dashboard summary', 'Heading1'), p(f'{s["scope"]} | {s["period"]}', 'Note'), Spacer(1, 10)])
    story.append(cards(s['kpis']))
    widgets['Dashboard summary'] = story
    blocks = [*course_blocks(s), *s['blocks']]
    for i, block in enumerate(blocks):
        story = []
        key = block.get('key', block['title'])
        widgets.setdefault(key, [])
        widgets[key].extend(story)
        story = widgets[key]
        story.append(p(block['title'], 'Heading2'))
        if block.get('note'):
            story.append(p(block['note'], 'Note'))
        if block.get('collapsed') or 'text' in block:
            story.extend(p(line) for line in block.get('text', 'Collapsed on dashboard.').splitlines() if line.strip())
            continue
        if not block['rows']:
            story.append(p('No records in this scope and period.'))
            continue
        n = len(block['headers'])
        widths = [width * .36] + [width * .64 / (n - 1)] * (n - 1)
        records = [[p(v) for v in block['headers']]] + [[p(v) for v in r] for r in block['rows']]
        t = Table(records, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0')),
                              ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
                              ('LINEBELOW', (0, 0), (-1, -1), .35, colors.HexColor('#cbd5e1')),
                              ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 7),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
        story.append(t)
        if i == 0:
            story.append(p('Average/latest/best are completed-session percentages. Trend compares the first and second halves of completed sessions. Status: Focus <60%, Developing 60-74%, On track 75%+. These are study indicators, not CFA pass predictions.', 'Note'))
    from reportlab.platypus import KeepTogether
    story = [p('StudyForge dashboard report', 'Heading1'), p(f'{s["scope"]} | Through {s["day"]} | America/New_York', 'Note'), Spacer(1, 10)]
    order = report_order(s)
    for index, key in enumerate(order):
        content = widgets.get(key, [])
        calendar_after_summary = key == 'Practice calendar' and index > 0 and order[index - 1] == 'Practice summary'
        summary_before_calendar = key == 'Practice summary' and index + 1 < len(order) and order[index + 1] == 'Practice calendar'
        course_after_summary = key == 'Course dashboard cards' and index > 0 and order[index - 1] == 'Dashboard summary'
        if (summary_before_calendar or key == 'Course dashboard cards' and not course_after_summary or key == 'Practice calendar' and not calendar_after_summary) and len(story) > 3:
            story.append(PageBreak())
        if key in ('Days till exam', 'Next mock exam', 'Practice summary', 'Dashboard summary'):
            story.append(KeepTogether(content))
        else:
            story.extend(content)
        if index < len(order) - 1:
            story.append(Spacer(1, 12))
    def footer(canvas, document):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(32, 15, f'StudyForge | Report through {s["day"]}')
        canvas.drawRightString(landscape(A4)[0] - 32, 15, f'Page {document.page}')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


def deliver_snapshot(user_id, snapshot):
    day = snapshot['day']
    pdf = snapshot_pdf(snapshot)
    plain = f'Your complete StudyForge dashboard report through {day} is attached as a PDF.\nScope: {snapshot["scope"]}\nIncludes your visible dashboard sections in their saved order.'
    return send_report(user_id, f'[StudyForge] Dashboard report · {day}', plain, snapshot_html(snapshot), pdf,
                       f'studyforge-dashboard-{day}.pdf')


def load_schedule(user_id):
    try:
        return json.loads(db.get_setting(user_id, SCHEDULE_KEY) or '{}')
    except (ValueError, TypeError):
        return {}


def render_report_controls(user_id, scope, course_ids, time_context, sections, metric, today, rows, *, mode='Curriculum', curriculum_id=None):
    import streamlit as st
    config = report_config(scope, course_ids, time_context, sections, metric, mode=mode, curriculum_id=curriculum_id)
    with st.expander('Email me a report'):
        recipient = db.get_setting(user_id, 'profile_email').strip()
        st.caption(f'To: {recipient}' if recipient else 'Add your email address in Settings before sending.')
        st.write('Your report follows the dashboard order, visibility, and expanded sections. Open a course or module to include its details; collapse it to keep the report summarized. These choices are saved automatically and used by scheduled emails. Preview below to check the result.')
        snapshot = build_snapshot(user_id, config, today, rows=rows)
        pdf = snapshot_pdf(snapshot)
        if st.checkbox('Preview full report', key='dashboard_email_preview'):
            preview_type = st.radio('Preview format', ['Email body', 'PDF attachment'], horizontal=True)
            if preview_type == 'Email body':
                with st.container(height=650):
                    st.markdown(snapshot_html(snapshot), unsafe_allow_html=True)
            else:
                import fitz
                with fitz.open(stream=pdf, filetype='pdf') as document:
                    page = st.selectbox('PDF page', range(1, len(document) + 1))
                    st.image(document[page - 1].get_pixmap(matrix=fitz.Matrix(1.4, 1.4)).tobytes('png'), width='stretch')
        st.download_button('Download full report (PDF)', pdf, file_name=f'studyforge-dashboard-{today}.pdf', mime='application/pdf')
        if st.button('Email full report to me', disabled=not recipient, key='dashboard_email_send'):
            try:
                deliver_snapshot(user_id, snapshot)
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error('Delivery could not be confirmed. Check Email Delivery settings before retrying.')
            else:
                st.success(f'Full dashboard PDF sent to {recipient}.')
        saved = load_schedule(user_id)
        frequencies = ['Off', 'Daily', 'Weekdays', 'Weekly']
        with st.form('dashboard_report_schedule'):
            frequency = st.selectbox('Email frequency', frequencies, index=frequencies.index(saved.get('frequency', 'Off')))
            weekday = st.selectbox('Weekly send day', list(calendar.day_name), index=saved.get('weekday', 0))
            st.caption('Scheduled for 12:05 a.m. America/New_York. Each PDF ends with the previous day. Daily counters roll over by date; no study records are cleared. Codex and this computer must be running. A late wake-up sends the latest completed day once.')
            if st.form_submit_button('Save report schedule'):
                if frequency != 'Off' and not recipient:
                    st.error('Add your email address in Settings first.')
                else:
                    db.set_setting(user_id, SCHEDULE_KEY, json.dumps({**config, 'frequency': frequency, 'weekday': list(calendar.day_name).index(weekday)}))
                    st.success('Schedule saved with the current dashboard scope, date filter, analysis sections, and calendar metric.')
        if saved.get('frequency', 'Off') != 'Off':
            st.caption(f'Saved schedule: {saved["frequency"]} at 12:05 a.m. Eastern · {saved.get("scope", scope)}. Save again to apply dashboard changes to scheduled reports.')
