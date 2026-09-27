from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import auth, database, utils
from src.neonatal_ccrn import ensure_schema_and_catalog
from src.question_bank_workspace import coverage_rows, get_plan, plan_batch, save_plan


@pytest.fixture
def banks(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "banks.db")
    database.init_database()
    ccrn = ensure_schema_and_catalog()
    conn = database.get_connection()
    cfa = conn.execute("INSERT INTO courses(title, normalized_title) VALUES ('CFA Level 1', 'cfa level 1')").lastrowid
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('bank_admin','hash')").lastrowid
    conn.commit()
    conn.close()
    monkeypatch.setattr(auth, "require_login", lambda: uid)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *args: None)
    monkeypatch.setattr(database, "is_admin", lambda *args: True)
    return ccrn, cfa, uid


def test_targets_and_batch_plan_are_subject_scoped(banks):
    ccrn, cfa, _ = banks
    save_plan(cfa, {"Ethics": 10, "Economics": 20}, 90)
    assert get_plan(cfa) == {"targets": {"Ethics": 10, "Economics": 20}, "mock_size": 90}
    assert get_plan(ccrn)["targets"] == {}
    rows = coverage_rows([{"section_type": "Ethics"}] * 12, [], get_plan(cfa)["targets"])
    batch = plan_batch(rows, 7)
    assert sum(row["Next Questions"] for row in batch) == 7
    assert next(row for row in batch if row["Module"] == "Ethics")["Next Questions"] == 0
    assert sum(row["Next Questions"] for row in plan_batch(rows, 150)) == 20


def _app(course_id):
    page = Path(__file__).resolve().parents[1] / "pages/4_Question_Bank_Manager.py"
    app = AppTest.from_file(str(page), default_timeout=30)
    app.session_state["qbm_course_id"] = course_id
    return app.run()


def test_switch_subject_and_import_without_crossing_banks(banks):
    ccrn, cfa, _ = banks
    app = _app(ccrn)
    assert not app.exception
    assert "Exam Preparation" in [tab.label for tab in app.tabs]
    app.selectbox(key="qbm_course_id").set_value(cfa).run()
    assert not app.exception
    assert "Exam Preparation" not in [tab.label for tab in app.tabs]
    assert not [m for m in app.multiselect if m.label == "Active Courses"]
    assert next(m for m in app.metric if m.label == "Target").value == "Not set"
    from src.neonatal_ccrn import get_catalog
    from src.ccrn_import_queue import list_drafts
    module = get_catalog(cfa)[0]
    payload = """Question 1
Question Stem: What is a fiduciary duty?
A. Act for the client
B. Act for the broker
C. Ignore conflicts
D. Ignore client needs
Answer: A
Rationale: The duty protects the client.
"""
    app.text_area(key=f"ccrn_section_{module['id']}_paste").set_value(payload)
    next(b for b in app.button if b.label == "Add all filled sections & convert").click().run()
    assert not app.exception
    assert len(list_drafts(cfa)) == 1
    next(b for b in app.button if b.label == "Import selected questions").click().run()
    assert not app.exception
    assert database.get_course_question_count(cfa) == 1
    assert database.get_course_question_count(ccrn) == 0
    # Reload after the import's rerun: AppTest retains removed checkbox nodes.
    app = _app(cfa)
    app.selectbox(key="qbm_course_id").set_value(ccrn).run()
    assert not app.exception
    assert app.selectbox(key="qbm_course_id").value == ccrn


def test_user_view_hides_import_and_target_mutations(banks, monkeypatch):
    _, cfa, uid = banks
    conn = database.get_connection()
    conn.execute("INSERT INTO course_enrollments(user_id,course_id) VALUES (?,?)", (uid,cfa))
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "is_admin", lambda *args: False)
    app = _app(cfa)
    assert not app.exception
    assert "Upload Files" not in [tab.label for tab in app.tabs]
    assert not [b for b in app.button if b.label == "Save bank targets"]
    assert not app.text_area


def test_empty_browse_selection_does_not_hide_imports(banks):
    _, cfa, _ = banks
    app = _app(cfa)
    app.session_state["qbm_browse_courses"] = [999999]
    app.run()
    assert not app.exception
    assert app.text_area
    assert len(app.get("file_uploader")) == 0
    assert "Imports" not in [t.label for t in app.tabs]
    assert "Paste & Batch Import" in [t.label for t in app.tabs]


def test_ccrn_targets_survive_catalog_refresh_and_preserve_exams(banks):
    from src.neonatal_ccrn import get_catalog, get_coverage, recommend_next_batch
    ccrn, _, uid = banks
    catalog = get_catalog(ccrn)
    targets = {m['name']: 100 for m in catalog}
    save_plan(ccrn, targets, 150)
    ensure_schema_and_catalog()
    coverage = get_coverage(ccrn, uid)
    assert coverage['target'] == 600
    assert all(m['target_questions'] == 100 for m in coverage['modules'])
    assert sum(m['mock_questions'] for m in get_catalog(ccrn)) == 150
    assert sum(m['recommended'] for m in recommend_next_batch(150, ccrn)) == 150
    app = _app(ccrn)
    assert not app.exception
    assert next(m for m in app.metric if m.label == 'Target').value == '600'
    app.number_input(key=f"bank_target_{ccrn}_{catalog[0]['id']}").set_value(200)
    next(b for b in app.button if b.label == 'Save coverage targets').click().run()
    assert get_coverage(ccrn)['target'] == 700


def test_pipeline_handles_more_than_six_modules_and_named_chapters(banks):
    from src.question_bank_workspace import add_catalog_entry, ensure_subject_catalog
    from src.ccrn_import_queue import convert_text
    from src.neonatal_ccrn import import_questions
    _, cfa, _ = banks
    save_plan(cfa, {f'Module {i}': 20 for i in range(8)}, 90)
    ensure_subject_catalog(cfa, 'CFA Level 1')
    add_catalog_entry(cfa, 'Module 7', 'Income Taxes')
    catalog = ensure_subject_catalog(cfa, 'CFA Level 1')
    app = _app(cfa)
    assert not app.exception
    assert len([a for a in app.text_area if a.key.startswith('ccrn_section_')]) == 8
    result = convert_text('Question 1\nQuestion Stem: Tax question?\nChapter: Income Taxes\nA. One\nB. Two\nC. Three\nD. Four\nAnswer: A', catalog, 'Module 7')
    assert not result['errors']
    assert result['rows'][0]['chapter'] == 'Income Taxes'
    assert import_questions('Tax batch', result['rows'], cfa)['inserted'] == 1


def test_dashboard_and_browse_share_lens_filter(banks):
    from src.question_bank_workspace import ensure_subject_catalog
    from src.neonatal_ccrn import import_questions
    _, cfa, _ = banks
    module = ensure_subject_catalog(cfa, 'CFA Level 1')[0]
    row = {'module': module['name'], 'chapter': 'General', 'question_text': 'Standard question?',
           'choice_a': 'A', 'choice_b': 'B', 'choice_c': 'C', 'choice_d': 'D', 'correct_answer': 'A'}
    import_questions('Standard batch', [row], cfa)
    import_questions('Hip Hop batch', [{**row, 'question_text': 'Record label question?'}], cfa, lens='hip_hop')
    app = _app(cfa)
    app.selectbox(key='b_lens').set_value('hip_hop').run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == 'Actual Questions').value == '1'
    assert next(m for m in app.metric if m.label.endswith('· Hip Hop')).value == '1'
    app.selectbox(key='b_lens').set_value('standard').run()
    assert next(m for m in app.metric if m.label == 'Actual Questions').value == '1'
    app.selectbox(key='b_lens').set_value('all').run()
    assert next(m for m in app.metric if m.label == 'Actual Questions').value == '2'
