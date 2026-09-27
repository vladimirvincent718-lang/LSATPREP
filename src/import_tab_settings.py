"""Course-scoped, reversible removal of import tabs without deleting course data."""
from src import database


def review_tab_groups(user_id, course_id, catalog):
    """Map each user's review plan to this course's actual import module IDs."""
    if user_id is None:
        return []
    from src.mock_review import get_mock_schedule, get_mock_review_items, get_review_module_plan

    normalize = lambda value: ' '.join(str(value or '').casefold().split())
    items = get_mock_review_items(user_id, status='all')
    groups = []
    for mock in get_mock_schedule(user_id):
        plan = get_review_module_plan(user_id, mock['id'])
        selected = plan['selection_items'] if plan['configured'] else [
            item for item in items if item['mock_schedule_id'] == mock['id']]
        keys = {normalize(item.get('match_topic_key') or item['topic_name'])
                for item in selected if item['course_id'] == course_id}
        groups.append({
            'id': str(mock['id']),
            'name': f"Mock exam review {mock['mock_label'].removeprefix('Mock ')} · {mock['scheduled_date']}",
            'ids': [str(module['id']) for module in catalog if normalize(module['name']) in keys],
        })
    return groups


def _connection():
    conn = database.get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS hidden_import_tabs (
        course_id INTEGER NOT NULL, module_id INTEGER NOT NULL,
        PRIMARY KEY(course_id, module_id))''')
    conn.commit()
    return conn


def hidden_tab_ids(course_id):
    conn = _connection()
    try:
        return {row[0] for row in conn.execute('SELECT module_id FROM hidden_import_tabs WHERE course_id=?', (course_id,))}
    finally:
        conn.close()


def set_tabs_removed(course_id, module_ids, removed=True):
    ids = set(module_ids)
    conn = _connection()
    try:
        with conn:
            valid = {row[0] for row in conn.execute('SELECT id FROM course_module_blueprints WHERE course_id=?', (course_id,))}
            if not ids <= valid:
                raise ValueError('One or more tabs do not belong to this course.')
            if removed:
                conn.executemany('INSERT OR IGNORE INTO hidden_import_tabs VALUES (?,?)', [(course_id, mid) for mid in ids])
            else:
                conn.executemany('DELETE FROM hidden_import_tabs WHERE course_id=? AND module_id=?', [(course_id, mid) for mid in ids])
        return len(ids)
    finally:
        conn.close()
