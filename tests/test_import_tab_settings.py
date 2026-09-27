from pathlib import Path
import json

import pytest
from streamlit.testing.v1 import AppTest

from src import auth, database, utils
from src.neonatal_ccrn import ensure_schema_and_catalog, get_catalog
from src.ccrn_import_queue import add_section_draft, list_drafts
from src.import_tab_settings import hidden_tab_ids, set_tabs_removed


def test_review_groups_match_course_and_canonical_module_names(monkeypatch):
    from src import mock_review
    from src.import_tab_settings import review_tab_groups
    monkeypatch.setattr(mock_review, 'get_mock_schedule', lambda user: [
        {'id': 1, 'mock_label': 'Mock 1/2', 'scheduled_date': '2026-09-01'},
        {'id': 2, 'mock_label': 'Mock 2/2', 'scheduled_date': '2026-10-01'}])
    monkeypatch.setattr(mock_review, 'get_mock_review_items', lambda user, status: [
        {'mock_schedule_id': 1, 'course_id': 7, 'topic_name': 'Unselected'},
        {'mock_schedule_id': 2, 'course_id': 7, 'topic_name': 'Finished module'},
        {'mock_schedule_id': 2, 'course_id': 8, 'topic_name': 'Unselected'}])
    monkeypatch.setattr(mock_review, 'get_review_module_plan', lambda user, mid: {
        'configured': mid == 1, 'selection_items': [
            {'course_id': 7, 'topic_name': 'Display title', 'match_topic_key': '  actual   MODULE '},
            {'course_id': 8, 'topic_name': 'Unselected'}]})
    catalog = [{'id': 10, 'name': 'Actual Module'}, {'id': 11, 'name': 'Finished module'},
               {'id': 12, 'name': 'Unselected'}]
    groups = review_tab_groups(3, 7, catalog)
    assert groups[0]['ids'] == ['10']
    assert groups[1]['ids'] == ['11']
    assert review_tab_groups(None, 7, catalog) == []


@pytest.fixture
def bank(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'tabs.db')
    database.init_database()
    course = ensure_schema_and_catalog()
    monkeypatch.setattr(auth, 'require_login', lambda: 1)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *args: None)
    monkeypatch.setattr(database, 'is_admin', lambda *args: True)
    return course, get_catalog(course)


def app_for(course):
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'pages/4_Question_Bank_Manager.py'), default_timeout=30)
    app.session_state['qbm_course_id'] = course
    return app.run()


def test_bulk_removal_persists_without_deleting_data(bank):
    course, catalog = bank
    ids = [m['id'] for m in catalog[:2]]
    draft = add_section_draft(course, ids[0], 'Question 1\nQuestion Stem: Saved text')
    set_tabs_removed(course, ids)
    ensure_schema_and_catalog()
    assert hidden_tab_ids(course) == set(ids)
    assert len(get_catalog(course)) == len(catalog)
    assert list_drafts(course)[0]['id'] == draft
    assert hidden_tab_ids(course + 1000) == set()
    with pytest.raises(ValueError):
        set_tabs_removed(course, [ids[0], 999999])
    set_tabs_removed(course, ids, removed=False)
    assert hidden_tab_ids(course) == set()


def test_delete_multiple_all_and_restore_tabs(bank):
    course, catalog = bank
    app = app_for(course)
    assert not app.exception
    ids = [m['id'] for m in catalog]
    app.text_input(key=f'import_tab_delete_ids_{course}').set_value(json.dumps({'action':'delete', 'ids':ids}))
    app.button(key=f'import_tab_delete_submit_{course}').click().run()
    assert not app.exception
    assert hidden_tab_ids(course) == set(ids)
    # AppTest retains stale form nodes after st.rerun removes the whole form.
    # Verify the persisted removal in a fresh page tree before restoring.
    app = app_for(course)
    assert not app.exception
    assert not [a for a in app.text_area if a.key.startswith('ccrn_section_')]
    next(m for m in app.multiselect if m.label == 'Tabs to restore').set_value(ids[:2])
    next(b for b in app.button if b.label == 'Restore selected tabs').click().run()
    assert not app.exception
    assert len([a for a in app.text_area if a.key.startswith('ccrn_section_')]) == 2


def test_single_delete_preserves_pasted_text_for_restore(bank):
    course, catalog = bank
    mid = catalog[0]['id']
    app = app_for(course)
    app.text_area(key=f'ccrn_section_{mid}_paste').set_value('Unfinished question text')
    app.text_input(key=f'import_tab_delete_ids_{course}').set_value(json.dumps({'action':'delete', 'ids':[mid]}))
    app.button(key=f'import_tab_delete_submit_{course}').click().run()
    assert not app.exception
    assert mid in hidden_tab_ids(course)
    app.text_input(key=f'import_tab_delete_ids_{course}').set_value(json.dumps({'action':'restore', 'ids':[mid]}))
    app.button(key=f'import_tab_delete_submit_{course}').click().run()
    assert not app.exception
    assert app.text_area(key=f'ccrn_section_{mid}_paste').value == 'Unfinished question text'
