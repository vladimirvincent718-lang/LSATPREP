"""Read the records behind a calendar day using the calendar's exact scope."""
from datetime import date, timedelta

from src import database
from src.practice_calendar import utc_boundary


def parse_day(value, today):
    try:
        day = date.fromisoformat(value)
    except (ValueError, TypeError):
        return today
    return min(day, today)


def load_day_records(user_id, day, *, days=1):
    start, end = day - timedelta(days=days - 1), day + timedelta(days=1)
    answers = [r for r in database.get_answer_stats(
        user_id, completed_from=utc_boundary(start), completed_to=utc_boundary(end),
        include_in_progress_practice=True, include_answer_details=True,
    ) if r.get('mode') == 'practice']
    external = database.get_external_practice_entries(user_id, entry_from=start.isoformat(), entry_to=end.isoformat())
    timers = database.get_study_time_entries(user_id, entry_from=start.isoformat(), entry_to=end.isoformat(), mode='practice')
    return answers, external, timers
