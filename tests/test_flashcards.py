from pathlib import Path
import io
from zipfile import ZipFile

import pytest
from src import database, flashcards as fc


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'cards.db')
    fc.init_flashcards()


def test_private_progress_and_edit_retention(store):
    cards = [{'front': 'Yield', 'back': 'Annual coupon / price'}, {'front': 'NPV', 'back': 'PV minus investment'}]
    deck = fc.save_deck(1, 2, 'Chapter', 'Notes', cards)
    first = fc.get_cards(1, 2, deck)[0]
    fc.mark_card(2, 2, first['id'], 'known', True)
    assert not fc.get_cards(1, 2, deck)[0]['known']
    assert not fc.get_cards(1, 3, deck)
    assert not fc.list_decks(2, 2)
    with pytest.raises(ValueError):
        fc.save_deck(2, 2, 'Stolen', '', cards, deck_id=deck)
    fc.mark_card(1, 2, first['id'], 'known', True)
    fc.mark_card(1, 2, first['id'], 'starred', True)
    cards[1]['back'] = 'Changed answer'
    fc.save_deck(1, 2, 'Revised', 'Notes', cards, deck_id=deck)
    revised = fc.get_cards(1, 2, deck)
    assert revised[0]['known'] == revised[0]['starred'] == 1
    assert revised[1]['known'] == 0
    with pytest.raises(ValueError):
        fc.save_deck(1, 2, 'Empty', '', [{'front': 'Incomplete', 'back': ''}], deck_id=deck)
    assert len(fc.get_cards(1, 2, deck)) == 2


def test_source_conversion_and_scans():
    cards = fc.draft_cards('# Bonds\nYield: Annual coupon / price\nYield: Annual coupon / price\nNPV\tPV less cost')
    assert len(cards) == 2
    assert cards[1] == {'front': 'NPV', 'back': 'PV less cost'}
    assert fc.draft_cards('CV = s / mean')[0]['back'] == 'CV = s / mean'
    assert fc.extract_text('chapter.txt', b'Term: Definition') == 'Term: Definition'
    buf = io.BytesIO()
    with ZipFile(buf, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>')
    with pytest.raises(ValueError, match='no readable text'):
        fc.extract_text('scan.docx', buf.getvalue())
    source = fc.ROOT / 'data/material_files' / fc.starter_data()['source']
    if source.exists():
        assert len(fc.draft_cards(fc.extract_text(source.name, source.read_bytes()))) == 128


def test_seed_is_idempotent_and_course_scoped(store, monkeypatch):
    monkeypatch.setattr(database, 'get_materials', lambda cid: [{'stored_file_path': fc.starter_data()['source']}] if cid == 2 else [])
    fc.seed_cfa(1, 2)
    fc.seed_cfa(1, 2)
    fc.seed_cfa(1, 3)
    assert len(fc.list_decks(1, 2)) == 10
    assert sum(d['total'] for d in fc.list_decks(1, 2)) == 128
    assert not fc.list_decks(1, 3)


def test_fsa_upgrade_preserves_edits_progress_and_removals(store, monkeypatch):
    data = fc.starter_data()
    chapter = next(c for c in data['chapters'] if c['title'] == 'Financial Statement Analysis')
    old_cards = [dict(c) for c in chapter['cards'] if c.get('seed_revision', 1) == 1]
    assert len(old_cards) == 8
    old_cards[0]['back'] = 'My custom answer'
    old_cards.pop(1)  # A learner removed one of the original cards.
    deck_id = fc.save_deck(1, 2, 'My FSA title', data['source'], old_cards,
                           seed_key='cfa-v1:Financial Statement Analysis')
    first = fc.get_cards(1, 2, deck_id)[0]
    fc.mark_card(1, 2, first['id'], 'known', True)
    fc.mark_card(1, 2, first['id'], 'starred', True)
    private_id = fc.save_deck(2, 2, 'Other learner', '', old_cards,
                              seed_key='cfa-v1:Financial Statement Analysis')
    monkeypatch.setattr(database, 'get_materials', lambda cid: [{'stored_file_path': data['source']}])
    fc.seed_cfa(1, 2)
    cards = fc.get_cards(1, 2, deck_id)
    assert len(cards) == 66
    assert cards[0] == {**first, 'known': 1, 'starred': 1}
    assert next(d for d in fc.list_decks(1, 2) if d['id'] == deck_id)['title'] == 'My FSA title'
    assert len(fc.get_cards(2, 2, private_id)) == 7
    # A later removal of an added card must not be undone by reopening the page.
    fc.save_deck(1, 2, 'My FSA title', data['source'], cards[:-1], deck_id=deck_id)
    fc.seed_cfa(1, 2)
    fc.seed_cfa(1, 2)
    assert len(fc.get_cards(1, 2, deck_id)) == 65


def test_fsa_source_coverage():
    chapter = next(c for c in fc.starter_data()['chapters'] if c['title'] == 'Financial Statement Analysis')
    assert len(chapter['cards']) == 67
    fronts = {c['front'] for c in chapter['cards']}
    assert {'Cash ratio', 'Defensive interval', 'Inventory turnover', 'Fixed charge coverage',
            'Expanded five-factor DuPont analysis', 'Deferred tax asset',
            'Finance lease: lessor reporting', 'Share-based compensation',
            'Sales-based pro forma model'} <= fronts
    assert all(c['source_page'] in (2, 3) for c in chapter['cards'])
    assert 'obscures' in chapter['coverage_note']


def test_study_and_create_flow(store, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    from src import auth, utils
    # Standalone AppTest does not register multipage navigation destinations.
    monkeypatch.setattr(st, 'page_link', lambda *a, **kw: None)
    monkeypatch.setattr(auth, 'require_login', lambda: 1)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *a: None)
    monkeypatch.setattr(utils, 'require_course', lambda *a: 2)
    monkeypatch.setattr(database, 'get_course', lambda cid: {'title': 'CFA Level I'})
    monkeypatch.setattr(database, 'get_materials', lambda cid: [{'title': 'CFA cheatsheet', 'stored_file_path': fc.starter_data()['source']}])
    app = AppTest.from_file(str(fc.ROOT / 'pages/3a_Flashcards.py'), default_timeout=30).run()
    assert not app.exception
    def click(label):
        next(b for b in app.button if b.label == label).click().run()
        assert not app.exception
    click('Flip card ↻')
    click('☆ Star')
    click('✓ Got it')
    deck = fc.list_decks(1, 2)[0]
    assert deck['known'] == 1
    next(r for r in app.radio if r.label == 'Study mode').set_value('Starred').run()
    assert not app.exception
    click('⤨ Shuffle')
    click('Next →')
    next(r for r in app.radio if r.label == 'Start with').set_value('Paste notes').run()
    next(t for t in app.text_area if t.label == 'Chapter notes').set_value('NPV: Discounted cash flows less initial cost').run()
    click('Generate draft cards')
    click('Save study set')
    assert len(fc.list_decks(1, 2)) == 11
    assert fc.list_decks(1, 2)[-1]['total'] == 1
    app = AppTest.from_file(str(fc.ROOT / 'pages/3a_Flashcards.py'), default_timeout=30).run()
    assert not app.exception
    click('Save changes')
