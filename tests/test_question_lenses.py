import json

import pytest

from src import database
from src.ccrn_import_queue import add_section_draft, process_drafts, list_drafts
from src.neonatal_ccrn import ensure_schema_and_catalog, get_catalog, get_questions, get_batch_history
from src.question_lenses import question_lens, set_batch_lens


@pytest.fixture
def bank(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'lenses.db')
    database.init_database()
    course = ensure_schema_and_catalog()
    return course, get_catalog(course)[0]


def paste(module):
    return f"Question 1\nChapter: {module['chapters'][0]['name']}\nQuestion Stem: A lens test?\nA. One\nB. Two\nC. Three\nD. Four\nAnswer: A\nRationale: Explanation."


def test_batch_lens_survives_conversion_import_and_reload(bank):
    course, module = bank
    draft = add_section_draft(course, module['id'], paste(module), lens='hip_hop')
    process_drafts(course, [draft])
    assert list_drafts(course)[0]['lens'] == 'hip_hop'
    process_drafts(course, [draft], import_ready=True)
    assert question_lens(get_questions(course)[0]) == 'hip_hop'
    assert get_questions(course)[0]['difficulty'] == 3
    assert get_batch_history(course)[0]['lens'] == 'hip_hop'
    ensure_schema_and_catalog()
    assert question_lens(database.get_all_questions(course_id=course)[0]) == 'hip_hop'


def test_review_and_historical_corrections_are_scoped_and_preserve_content(bank):
    course, module = bank
    draft = add_section_draft(course, module['id'], paste(module))
    set_batch_lens(course, draft, 'hip_hop')
    process_drafts(course, [draft], import_ready=True)
    before = get_questions(course)[0]
    batch = get_batch_history(course)[0]['id']
    with pytest.raises(ValueError):
        set_batch_lens(course + 1000, batch, 'standard', imported=True)
    assert set_batch_lens(course, batch, 'standard', imported=True) == 1
    after = get_questions(course)[0]
    assert question_lens(after) == 'standard'
    assert {k:v for k,v in after.items() if k != 'metadata_json'} == {k:v for k,v in before.items() if k != 'metadata_json'}
    assert len(get_questions(course)) == 1


def test_legacy_questions_default_to_unassigned():
    assert question_lens({}) == 'standard'
    assert question_lens({'metadata_json': json.dumps({'source_chapter': 'Old'})}) == 'standard'


def test_lens_selector_and_review_controls(bank, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from src import auth, utils
    course, module = bank
    monkeypatch.setattr(auth, 'require_login', lambda: 1)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *args: None)
    monkeypatch.setattr(database, 'is_admin', lambda *args: True)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'pages/4_Question_Bank_Manager.py'), default_timeout=30)
    app.session_state['qbm_course_id'] = course
    app.run()
    assert not app.exception
    app.selectbox(key='b_lens').set_value('hip_hop').run()
    app.text_area(key=f"ccrn_section_{module['id']}_paste").set_value(paste(module))
    next(b for b in app.button if b.label == 'Add all filled sections & convert').click().run()
    assert not app.exception
    draft = list_drafts(course)[0]
    assert draft['lens'] == 'hip_hop'
    assert not [w for w in app.selectbox if w.key == f"ccrn_draft_{draft['id']}_lens"]
    assert not [w for w in app.selectbox if w.key == f"bank_new_lens_{course}"]
    app.selectbox(key='b_lens').set_value('movement').run()
    assert list_drafts(course)[0]['lens'] == 'hip_hop'
    next(b for b in app.button if b.label == 'Apply selected lens to this batch').click().run()
    assert not app.exception
    assert list_drafts(course)[0]['lens'] == 'movement' 


def test_custom_lens_and_manual_question_assignment(bank):
    from src.question_lenses import get_lenses, save_lens, set_question_lenses
    course, module = bank
    draft = add_section_draft(course, module['id'], paste(module))
    process_drafts(course, [draft], import_ready=True)
    question = get_questions(course)[0]
    assert get_lenses()['movement'] == 'Movement'
    lens_id = save_lens('Dance & Motion')
    assert set_question_lenses(course, [question['id']], lens_id) == 1
    assert question_lens(get_questions(course)[0]) == lens_id
    save_lens('Movement and Dance', lens_id)
    assert get_lenses()[lens_id] == 'Movement and Dance'
    assert question_lens(get_questions(course)[0]) == lens_id
    with pytest.raises(ValueError):
        set_question_lenses(course + 1, [question['id']], 'movement')
    assert get_questions(course)[0]['stimulus'] == question['stimulus']


def test_manual_assignment_in_manager_ignores_stale_course_selection(bank, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from src import auth, utils
    course, module = bank
    draft = add_section_draft(course, module['id'], paste(module))
    process_drafts(course, [draft], import_ready=True)
    question = get_questions(course)[0]
    monkeypatch.setattr(auth, 'require_login', lambda: 1)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *args: None)
    monkeypatch.setattr(database, 'is_admin', lambda *args: True)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'pages/4_Question_Bank_Manager.py'), default_timeout=30)
    app.session_state['qbm_course_id'] = course
    app.session_state['qbm_browse_courses'] = [99999]
    app.session_state['active_course_id'] = 99999
    app.run()
    assert not app.exception
    assert not [m for m in app.multiselect if m.label == 'Active Courses']
    app.multiselect(key=f'lens_assign_ids_{course}').set_value([question['id']]).run()
    app.selectbox(key='b_lens').set_value('movement').run()
    app.button(key=f'lens_assign_save_{course}').click().run()
    assert not app.exception
    assert question_lens(get_questions(course)[0]) == 'movement'
    app.selectbox(key='b_lens').set_value('movement').run()
    assert any('1 questions match the selected filters and lens' in c.value for c in app.caption)


@pytest.mark.parametrize("difficulty,expected", [(None, 3), ("", 3), ("Intermediate", 3), ("5", 5)])
def test_lens_import_difficulty(bank, difficulty, expected):
    from src.ccrn_import_queue import convert_text, save_draft
    course, module = bank
    raw = paste(module)
    if difficulty is not None:
        raw += "\nDifficulty: " + difficulty
    draft = add_section_draft(course, module['id'], raw, lens='hip_hop')
    rows = convert_text(raw, get_catalog(course), module['name'], lens='hip_hop')['rows']
    save_draft(course, draft, raw, rows)
    result = process_drafts(course, [draft], import_ready=True)
    assert not result[0]['errors']
    assert get_questions(course)[0]['difficulty'] == expected
