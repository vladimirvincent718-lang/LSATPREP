from pathlib import Path
import pytest
from src import database, notebook as nb


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'notebook.db')
    nb.init_notebook()


def test_persistence_scope_search_and_validation(store):
    body = '| Rule | Value |\n| --- | --- |\n| Inventory | MIN(cost, NRV) |\n\n$$x = 1$$'
    nid = nb.save_note(1, 2, 'Inventory', body, 'FSA', 'ChatGPT')
    nb.init_notebook()
    assert nb.list_notes(1, 2, 'nrv', 'FSA')[0]['body'] == body
    assert not nb.list_notes(2, 2)
    assert not nb.list_notes(1, 3)
    with pytest.raises(ValueError):
        nb.save_note(2, 2, 'Stolen', 'Body', note_id=nid)
    with pytest.raises(ValueError):
        nb.save_note(1, 3, 'Wrong course', 'Body', note_id=nid)
    nb.delete_note(2, 2, nid)
    nb.delete_note(1, 3, nid)
    assert len(nb.list_notes(1, 2)) == 1
    with pytest.raises(ValueError):
        nb.save_note(1, 2, ' ', body, note_id=nid)
    nb.save_note(1, 2, 'Revised', body, 'Inventories', pinned=True, note_id=nid)
    nb.save_note(1, 2, 'Newer', 'Unpinned')
    assert nb.list_notes(1, 2)[0]['id'] == nid
    assert not nb.list_notes(1, 2, chapter='FSA')
    nb.delete_note(1, 2, nid)
    assert len(nb.list_notes(1, 2)) == 1


def test_notebook_flow(store, monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    # AppTest does not populate multipage URL metadata.
    monkeypatch.setattr(st, 'page_link', lambda *a, **kw: None)
    from src import auth, utils
    monkeypatch.setattr(auth, 'require_login', lambda: 1)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *a: None)
    monkeypatch.setattr(utils, 'require_course', lambda *a: 2)
    monkeypatch.setattr(database, 'get_course', lambda cid: {'title': 'CFA Level I'})
    monkeypatch.setattr(database, 'get_course_modules', lambda cid: [{'name': 'FSA'}])
    path = str(Path(__file__).resolve().parents[1] / 'pages/3b_Notebook.py')
    app = AppTest.from_file(path, default_timeout=30).run()
    assert not app.exception
    def click(label):
        next(b for b in app.button if b.label == label).click().run()
        assert not app.exception
    click('Use FSA example: inventory MIN / MAX')
    assert 'MEDIAN' in app.text_area[0].value
    click('Save note')
    app = AppTest.from_file(path, default_timeout=30).run()
    assert not app.exception
    assert nb.list_notes(1, 2)[0]['chapter'] == 'FSA'
    click('Pin')
    assert nb.list_notes(1, 2)[0]['pinned'] == 1
    click('Edit note')
    app.text_input[0].set_value('My inventory shortcut').run()
    math_note = r'Answer: \(\boxed{$8,000}\)'
    rendered_note = r'Answer: $\boxed{\$8,000}$'
    app.text_area[0].set_value(math_note).run()
    assert any(m.value == rendered_note for m in app.markdown)
    click('Save note')
    app = AppTest.from_file(path, default_timeout=30).run()
    assert not app.exception
    assert any(m.value == rendered_note for m in app.markdown)
    app = AppTest.from_file(path, default_timeout=30).run()
    assert 'My inventory shortcut' in app.expander[0].label
    next(t for t in app.text_input if t.label == 'Search notes').set_value('missing').run()
    assert not app.expander
    next(t for t in app.text_input if t.label == 'Search notes').set_value('').run()
    click('Delete permanently')
    assert not nb.list_notes(1, 2)
    app.session_state['notebook_open_2'] = 'FSA'
    app.run()
    click('＋ New note')
    assert app.selectbox[0].value == 'FSA'
    app.text_input[0].set_value('Draft').run()
    click('Discard changes')
    assert not nb.list_notes(1, 2)
