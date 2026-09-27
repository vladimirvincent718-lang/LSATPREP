from datetime import date, timedelta

import pytest

from src import database, material_reviews as reviews


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'reviews.db')
    database.init_database()
    reviews.init_reviews()
    with reviews.connection() as conn:
        users = [conn.execute("INSERT INTO users(username,password_hash) VALUES (?, 'x')", (n,)).lastrowid for n in ('one', 'two')]
        cid = conn.execute("INSERT INTO courses(title) VALUES ('CFA FSA')").lastrowid
    for uid in users:
        database.enroll_user(uid, cid)
    mid, error = database.create_material(cid, 'FSA slides', 'Notes', content_text='Original material')
    assert not error
    reviews.register_cheat_sheet(mid, 'FSA.pdf')
    return users, cid, mid


def test_spacing_persists_resets_and_duplicate_submission(store):
    users, cid, mid = store
    today = date(2026, 9, 17)
    assert reviews.list_reviews(users[0], cid, today)[0]['is_due']
    for interval in (1, 3, 7, 14, 30, 60, 60):
        due = reviews.record_review(users[0], mid, 'good', 'Recreated ratios', today)
        assert due == (today + timedelta(days=interval)).isoformat()
        # Double click or another open tab cannot advance the schedule twice.
        assert reviews.record_review(users[0], mid, 'good', today=today) == due
        reviews.init_reviews()
        assert not reviews.list_reviews(users[0], cid, today)[0]['is_due']
        today = date.fromisoformat(due)
    assert reviews.record_review(users[0], mid, 'again', today=today) == (today + timedelta(days=1)).isoformat()
    today += timedelta(days=1)
    assert reviews.record_review(users[0], mid, 'good', today=today) == (today + timedelta(days=1)).isoformat()
    assert reviews.list_reviews(users[1], cid, today)[0]['last_review'] is None
    assert reviews.review_history(users[1], mid) == []
    assert any(h['recall'] == 'Recreated ratios' for h in reviews.review_history(users[0], mid))


def test_pause_archive_enrollment_scope_and_generic_material(store):
    users, cid, mid = store
    uid = users[0]
    other, _ = database.create_material(cid, 'A reading', 'Reading')
    assert not next(r for r in reviews.list_reviews(uid) if r['id'] == other)['review_enabled']
    reviews.set_enabled(uid, other, True)
    assert next(r for r in reviews.list_reviews(uid) if r['id'] == other)['is_due']
    reviews.set_enabled(uid, mid, False)
    assert not next(r for r in reviews.list_reviews(uid) if r['id'] == mid)['is_due']
    reviews.set_enabled(uid, mid, True)
    assert next(r for r in reviews.list_reviews(uid) if r['id'] == mid)['is_due']
    assert reviews.list_reviews(uid, cid + 100) == []
    with pytest.raises(ValueError):
        reviews.record_review(uid, mid, 'invalid')
    with reviews.connection() as conn:
        conn.execute('UPDATE course_materials SET is_active=0 WHERE id=?', (mid,))
        conn.execute("UPDATE course_enrollments SET enrollment_status='Inactive' WHERE user_id=?", (uid,))
    assert reviews.list_reviews(uid) == []
    with pytest.raises(ValueError):
        reviews.record_review(uid, other, 'good')
    with pytest.raises(ValueError):
        reviews.set_enabled(users[1], mid, True)


def test_some_gaps_shortens_interval(store):
    users, _, mid = store
    today = date(2026, 9, 17)
    for _ in range(4):
        today = date.fromisoformat(reviews.record_review(users[0], mid, 'good', today=today))
    assert reviews.record_review(users[0], mid, 'hard', today=today) == (today + timedelta(days=7)).isoformat()


def test_ui_review_notes_pause_and_due_filter(store):
    from streamlit.testing.v1 import AppTest
    users, cid, mid = store
    app = AppTest.from_string(f'from src.material_review_ui import render_course_reviews\nrender_course_reviews({users[0]}, {cid})').run()
    assert not app.exception
    app.text_area(key=f'material_recall_{users[0]}_{mid}').input('Recall: balance sheet').run()
    app.button(key=f'review_rate_{mid}_good').click().run()
    assert not app.exception
    assert reviews.review_history(users[0], mid)[0]['recall'] == 'Recall: balance sheet'
    app.checkbox(key=f'material_due_only_{cid}').check().run()
    assert not app.exception
    assert any('caught up' in message.value for message in app.success)
    app.checkbox(key=f'material_due_only_{cid}').uncheck().run()
    app.button(key=f'review_toggle_{mid}').click().run()
    assert not reviews.list_reviews(users[0], cid)[0]['review_enabled']


def test_managed_file_boundary(tmp_path):
    from src.material_review_ui import material_file
    outside = tmp_path / 'secret.pdf'
    outside.write_bytes(b'x')
    assert material_file({'stored_file_path': str(outside)}) is None


def test_slide_navigation_without_download(tmp_path):
    import fitz
    from streamlit.testing.v1 import AppTest
    path = tmp_path / 'slides.pdf'
    with fitz.open() as doc:
        for text in ('First slide', 'Second slide', 'Third slide'):
            doc.new_page().insert_text((50, 50), text)
        doc.save(path)
    app = AppTest.from_string(
        'from pathlib import Path\nfrom src.material_review_ui import render_slide_viewer\n'
        f'render_slide_viewer(Path({str(path)!r}), "test")'
    ).run()
    assert not app.exception
    assert app.button(key='test_previous').disabled
    assert app.number_input(key='test_slide').value == 1
    assert app.radio(key='test_size').value == 'Fit whole slide'
    assert any('object-fit:contain' in m.value and '65vh' in m.value for m in app.markdown)
    app.button(key='test_next').click().run()
    assert not app.exception
    assert app.number_input(key='test_slide').value == 2
    app.number_input(key='test_slide').set_value(3).run()
    assert app.button(key='test_next').disabled
    app.button(key='test_previous').click().run()
    assert app.number_input(key='test_slide').value == 2
    app.button(key='test_next_bottom').click().run()
    assert app.number_input(key='test_slide').value == 3
    app.radio(key='test_size').set_value('Larger text').run()
    assert not app.exception
    assert app.number_input(key='test_slide').value == 3
    app.radio(key='test_size').set_value('Fit whole slide').run()
    app.button(key='test_previous_bottom').click().run()
    assert app.number_input(key='test_slide').value == 2


def test_slide_views_persist_with_private_daily_breakdown(store):
    users, cid, mid = store
    first, second = date(2026, 9, 21), date(2026, 9, 22)
    for _ in range(5):
        reviews.record_slide_view(users[0], mid, 5, first)
    for _ in range(10):
        reviews.record_slide_view(users[0], mid, 5, second)
    reviews.record_slide_view(users[0], mid, 2, second)
    reviews.record_slide_view(users[1], mid, 5, second)
    reviews.init_reviews()
    assert reviews.slide_view_history(users[0], mid) == [
        {'slide_number': 2, 'viewed_on': '2026-09-22', 'views': 1},
        {'slide_number': 5, 'viewed_on': '2026-09-22', 'views': 10},
        {'slide_number': 5, 'viewed_on': '2026-09-21', 'views': 5},
    ]
    assert sum(r['views'] for r in reviews.slide_view_history(users[1], mid)) == 1
    other, _ = database.create_material(cid, 'Other slides', 'Notes')
    assert reviews.slide_view_history(users[0], other) == []
    assert reviews.review_history(users[0], mid) == []
    assert reviews.list_reviews(users[0], cid)[0]['last_review'] is None
    with pytest.raises(ValueError):
        reviews.record_slide_view(users[0], mid, 0)
    with reviews.connection() as conn:
        conn.execute("UPDATE course_enrollments SET enrollment_status='Inactive' WHERE user_id=?", (users[1],))
    with pytest.raises(ValueError):
        reviews.record_slide_view(users[1], mid, 5)
    with pytest.raises(ValueError):
        reviews.slide_view_history(users[1], mid)


def test_slide_visits_ignore_reruns_and_hidden_tabs(store, tmp_path):
    import fitz
    from streamlit.testing.v1 import AppTest
    users, cid, mid = store
    other, _ = database.create_material(cid, 'Other slides', 'Notes')
    path = tmp_path / 'viewed_slides.pdf'
    with fitz.open() as doc:
        for _ in range(3):
            doc.new_page()
        doc.save(path)
    app = AppTest.from_string(
        'import streamlit as st\nfrom pathlib import Path\n'
        'from src.material_review_ui import render_slide_viewer\n'
        'st.session_state["tabs"] = st.radio("Section", ["Review", "Other"], key="section")\n'
        'review, other_tab = st.tabs(["Review", "Other"], key="tabs", on_change="rerun")\n'
        'if not review.open:\n'
        '    st.session_state.pop("_material_slide_visit", None)\n'
        'with review:\n'
        f'    mid = st.selectbox("Material", [{mid}, {other}], key="material")\n'
        f'    render_slide_viewer(Path({str(path)!r}), f"review_{{mid}}", {users[0]} if review.open else None, mid)\n'
    ).run()

    def counts():
        assert not app.exception
        assert not app.warning
        return {r['slide_number']: r['views'] for r in reviews.slide_view_history(users[0], mid)}

    prefix = f'review_{mid}'
    assert counts() == {1: 1}
    app.run()
    app.radio(key=f'{prefix}_size').set_value('Larger text').run()
    assert counts() == {1: 1}
    assert any(p.proto.popover.label == 'Slide 1 · 1 view' for p in app.get('popover'))
    assert any(df.value.to_dict('records') == [{'Date': date.today().isoformat(), 'Views': 1}]
               for df in app.dataframe)
    app.button(key=f'{prefix}_next').click().run()
    app.button(key=f'{prefix}_previous_bottom').click().run()
    assert counts() == {1: 2, 2: 1}
    app.number_input(key=f'{prefix}_slide').set_value(3).run()
    assert counts() == {1: 2, 2: 1, 3: 1}
    app.radio(key='section').set_value('Other').run()
    app.run()
    assert counts() == {1: 2, 2: 1, 3: 1}
    app.radio(key='section').set_value('Review').run()
    assert counts() == {1: 2, 2: 1, 3: 2}
    app.selectbox(key='material').select(other).run()
    app.selectbox(key='material').select(mid).run()
    assert counts() == {1: 3, 2: 1, 3: 2}
    assert reviews.slide_view_history(users[0], other)[0]['views'] == 1


def test_move_shared_word_to_curriculum_preserves_flashcard_source(store):
    from src import curriculum_materials as cm
    users, cid, _ = store
    database.init_curriculum_tables()
    with reviews.connection() as conn:
        curid = conn.execute("INSERT INTO curriculums(title) VALUES ('CFA curriculum')").lastrowid
        conn.execute('INSERT INTO curriculum_courses(curriculum_id,course_id) VALUES (?,?)', (curid, cid))
    source = 'data/material_files/cfa-level-i-november-2026-cheat-sheet.docx'
    mid, _ = database.create_material(cid, 'Whole CFA cheat sheet', 'PDF/Document Link', stored_file_path=source)
    database.set_material_progress(users[0], mid, cid, 'Completed')
    cm.move_shared_document(curid, source)
    cm.move_shared_document(curid, source)
    assert len(cm.get_curriculum_materials(users[0], curid)) == 1
    assert not cm.get_curriculum_materials(9999, curid)
    assert mid not in [m['id'] for m in database.get_materials(cid)]
    assert mid not in [m['id'] for m in reviews.list_reviews(users[0], cid)]
    assert database.get_material_progress(users[0], cid)[mid] == 'Completed'
    assert cm.has_curriculum_source(cid, 'cfa-level-i-november-2026-cheat-sheet.docx')
    assert not cm.has_curriculum_source(cid + 100, 'cfa-level-i-november-2026-cheat-sheet.docx')
