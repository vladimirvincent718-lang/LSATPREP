"""Module trends for the active mock review window, using its existing matching rules."""
from datetime import datetime

from src.mock_review import get_current_review_mock, get_mock_review_items, get_review_window_practice_sessions
from src.practice_calendar import ZONE

HEADERS = ['Course / module', 'Submitted', 'Latest', '2nd latest', '3rd latest', 'Average', 'Trend', 'Focus']


def summarize_modules(items, sessions):
    rows, seen = [], set()
    for item in items:
        topic = item.get('match_topic_key') or item['topic_key']
        key = (item['course_id'], topic)
        if key in seen:
            continue
        seen.add(key)
        matched = {}
        for session in sessions:
            if (session.get('completed_at') and session.get('questions', 0) > 0
                    and session.get('course_id') == item['course_id']
                    and ' '.join(session['module_name'].casefold().split()) == topic):
                matched[session['attempt_id']] = session
        ordered = sorted(matched.values(), key=lambda r: (r['completed_at'], r['attempt_id']), reverse=True)
        scores = [100 * r['correct'] / r['questions'] for r in ordered]
        latest = scores[0] if scores else None
        average = sum(scores) / len(scores) if scores else None
        trend = scores[0] - scores[min(2, len(scores)-1)] if len(scores) >= 2 else None
        focus = 'Not practiced' if latest is None else 'Focus' if latest < 60 else 'Developing' if latest < 75 else 'On track'
        rows.append({'label': f"{item.get('course_title') or 'Course'} / {item['topic_name']}",
                     'item_id': item['id'], 'count': len(scores), 'latest': latest, 'scores': scores[:3],
                     'average': average, 'trend': trend, 'focus': focus, 'sessions': ordered})
    # Unpracticed and weaker modules come first; averages break ties.
    rows.sort(key=lambda r: (r['latest'] is not None, r['latest'] or 0, r['average'] or 0, r['label']))
    return rows


def current_review_analytics(user_id, *, day=None):
    day = day or datetime.now(ZONE).date()
    current = get_current_review_mock(user_id, today=day)
    if not current:
        return {'title': 'Current mock review', 'note': 'No active mock review window for this date.', 'rows': [], 'submitted': 0}
    items = [r for r in get_mock_review_items(user_id, status='all') if r['mock_schedule_id'] == current['id']]
    # Follow the same completion-date window and mode rules as Mock Review.
    sessions = [r for r in get_review_window_practice_sessions(user_id, current['id'])
                if r.get('completed_at') and str(r['completed_at'])[:10] <= day.isoformat()]
    rows = summarize_modules(items, sessions)
    submitted = len({s['attempt_id'] for r in rows for s in r['sessions']})
    title = f"Current mock review · {current['mock_label']}"
    note = (f"{current['window_start']} to {current['window_end']} (end exclusive), through {day}. "
            f"{len(rows)} planned modules · {submitted} distinct submitted sessions. "
            'Latest scores are newest first. Average gives each completed session equal weight. '
            'Trend compares latest with third latest, or previous when only two exist, in percentage points. '
            'A session covering several modules counts once in each module and once in the overall count. '
            'Uses the Mock Review completion-date window; drafts, mock exams, and unassigned external totals are excluded. '
            'Focus <60%; Developing 60–<75%; On track ≥75% are study indicators, not pass predictions.')
    return {'title': title, 'note': note, 'rows': rows, 'submitted': submitted}


def table_rows(analytics):
    def pct(v):
        return f'{v:.1f}%' if v is not None else '—'
    return [[r['label'], str(r['count']), *[pct((r['scores']+[None]*3)[i]) for i in range(3)],
             pct(r['average']), f"{r['trend']:+.1f} pp" if r['trend'] is not None else '—', r['focus']]
            for r in analytics['rows']]


def render_current_review(user_id, mode):
    import streamlit as st
    from src.dashboard_layout import tracked_expander
    data = current_review_analytics(user_id)
    with tracked_expander(data['title'], user_id, mode, 'mock_review_analytics', default=True):
        st.caption(data['note'])
        cols = st.columns(3)
        cols[0].metric('Modules in this review', len(data['rows']))
        cols[1].metric('Submitted sessions', data['submitted'])
        cols[2].metric('Modules to focus on', sum(r['focus'] in ('Not practiced', 'Focus') for r in data['rows']))
        if data['rows']:
            st.dataframe([dict(zip(HEADERS, row)) for row in table_rows(data)], hide_index=True, width='stretch')
            st.markdown('View session evidence in [Mock Review](a_Mock_Review).')
        else:
            st.info('No modules are assigned to this review window yet.' if 'No active' not in data['note'] else data['note'])
