import json
from pathlib import Path

import pytest

from src import database
from src.ccrn_import_queue import (add_draft, add_section_draft, convert_text, list_drafts,
                                   save_draft, process_drafts, pending_question_counts, delete_drafts)
from src.neonatal_ccrn import (ensure_schema_and_catalog, get_batch_history, get_catalog,
                               get_questions, import_questions)


@pytest.fixture
def course(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "queue.db")
    database.init_database()
    return ensure_schema_and_catalog()


def sample(number=1):
    return f"""### **Question {number}**
**Question Stem:** Sample question {number}?
A. First choice
continued over two lines
B. Second choice
C. Third choice
D. Fourth choice
**Correct Answer:** B
**Rationale:** Supplied explanation.
* **Distractor Analysis:**
  * **A:** Supplied distractor explanation.
**Difficulty:** Stretch
**Section:** Respiratory
**Chapter:** Respiratory distress syndrome
"""


def test_bulk_delete_preserves_imported_questions_and_history(course):
    module = get_catalog(course)[1]
    partial = add_section_draft(course, module['id'], sample(1) + '\n' + sample(2))
    complete = add_section_draft(course, module['id'], sample(3))
    raw = add_section_draft(course, module['id'], 'Unwanted saved text')
    process_drafts(course, [partial])
    draft = next(d for d in list_drafts(course) if d['id'] == partial)
    rows = json.loads(draft['rows_json'])
    rows[1]['_include_in_next_step'] = False
    save_draft(course, partial, draft['raw_text'], rows)
    process_drafts(course, [partial, complete], import_ready=True)
    questions = get_questions(course)
    history = get_batch_history(course)
    assert len(questions) == 2
    assert delete_drafts(course + 1000, [partial, raw]) == 0
    assert delete_drafts(course, [partial, partial, raw, complete, -1]) == 2
    assert [d['id'] for d in list_drafts(course)] == [complete]
    assert get_questions(course) == questions
    assert get_batch_history(course) == history
    assert delete_drafts(course, [partial, raw]) == 0


def test_bulk_delete_ui_select_all_and_persistence(course):
    from streamlit.testing.v1 import AppTest
    module = get_catalog(course)[1]
    add_section_draft(course, module['id'], sample())
    add_section_draft(course, module['id'], 'Unwanted saved text')
    at = AppTest.from_string(
        'from src.ccrn_import_ui import _render_bulk_delete\n'
        f'_render_bulk_delete({course})', default_timeout=30,
    ).run()
    assert not at.exception
    delete = lambda: next(b for b in at.button if b.label == 'Delete selected saved batches')
    assert delete().disabled
    next(b for b in at.button if b.label == 'Select all batches to delete').click().run()
    assert any('2 batches · 1 remaining questions' in c.value for c in at.caption)
    assert delete().disabled
    next(b for b in at.button if b.label == 'Clear deletion selection').click().run()
    assert any('0 batches · 0 remaining questions' in c.value for c in at.caption)
    next(b for b in at.button if b.label == 'Select all batches to delete').click().run()
    at.checkbox[0].check().run()
    assert not delete().disabled
    delete().click().run()
    assert not at.exception
    assert not list_drafts(course)
    assert any('Deleted 2 saved batches' in s.value for s in at.success)
    at.run()
    assert not at.exception
    assert not list_drafts(course)


def test_needs_fixing_tabs_identify_block_and_disappear_after_repair(course, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import auth, utils
    from src.ccrn_import_ui import _workflow_snapshot
    module = get_catalog(course)[1]
    good_rows = convert_text(sample(), get_catalog(course))["rows"]
    bad = add_section_draft(course, module['id'], sample())
    save_draft(course, bad, sample(), [{**good_rows[0], 'correct_answer': ''}])
    malformed = add_section_draft(course, module['id'], 'No question headings')
    queued, stages, _ = _workflow_snapshot(course)
    assert stages[bad]['boundary'] == 'Step 2 → Step 3: validation blocked'
    assert stages[malformed]['boundary'] == 'Step 2 → Step 3: conversion blocked'
    monkeypatch.setattr(auth, 'require_login', lambda: 1)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *a: None)
    monkeypatch.setattr(database, 'is_admin', lambda *a: True)
    path = Path(__file__).resolve().parents[1] / 'pages' / '4_Question_Bank_Manager.py'
    at = AppTest.from_file(str(path), default_timeout=30)
    at.session_state["qbm_course_id"] = course
    at.run()
    assert not at.exception
    assert len([tab for tab in at.tabs if tab.label.startswith('⚠')]) == 2
    workflow = {exp.label: exp for exp in at.expander if exp.label[:1] in '1234'}
    assert len(workflow) == 4
    assert all(not exp.proto.expanded for exp in workflow.values())
    conversion = workflow['2 · Convert saved questions']
    review = workflow['3 · Review & import']
    assert any('conversion blocked' in e.value for e in conversion.get('error'))
    assert not any('validation blocked' in e.value for e in conversion.get('error'))
    assert any('validation blocked' in e.value for e in review.get('error'))
    assert not any('conversion blocked' in e.value for e in review.get('error'))
    for stage in workflow.values():
        assert any(e.label == 'Delete saved batches' for e in stage.get('expander'))
        assert any('sf-workflow-jump' in md.value for md in stage.get('markdown'))
    assert not at.get('file_uploader')
    assert any('validation blocked' in error.value for error in at.error)
    save_draft(course, bad, sample(), good_rows)
    save_draft(course, malformed, sample(2), convert_text(sample(2), get_catalog(course))['rows'])
    at.run()
    assert not at.exception
    assert not [tab for tab in at.tabs if tab.label.startswith('⚠')]
    assert not any('href="#ccrn-fixes"' in md.value for md in at.markdown)


def test_math_conversion_and_existing_queue_import(course):
    raw = sample().replace("Sample question 1?", r"An infant weighing $4.2\text{ kg}$?")
    raw = raw.replace("Second choice", r"Give \(2\text{ mL/kg}\)")
    raw = raw.replace("Supplied explanation.", r"Lower \(PaCO_2\).")
    rows = convert_text(raw, get_catalog(course))["rows"]
    assert rows[0]["question_text"] == "An infant weighing 4.2 kg?"
    assert rows[0]["choice_b"] == "Give 2 mL/kg"
    assert "Lower PaCO₂." in rows[0]["rationale"]
    draft_id = add_draft(course, "Math batch", raw)
    rows[0]["question_text"] = r"Edited infant weighing $4.2\text{ kg}$?"
    save_draft(course, draft_id, raw, rows)
    result = process_drafts(course, [draft_id], import_ready=True)
    assert result[0]["inserted"] == 1
    assert list_drafts(course)[0]["raw_text"] == raw
    assert get_questions(course)[0]["stimulus"] == "Edited infant weighing 4.2 kg?"


def test_math_duplicate_matches_legacy_import(course):
    rows = convert_text(sample(), get_catalog(course))["rows"]
    assert import_questions("Original", rows, course)["inserted"] == 1
    conn = database.get_connection()
    with conn:
        conn.execute("UPDATE questions SET stimulus=? WHERE course_id=?",
                     (r"Infant $4.2\text{ kg}$", course))
    conn.close()
    rows[0]["question_text"] = "Infant 4.2 kg"
    result = import_questions("Repeat with readable math", rows, course)
    assert result["inserted"] == 0
    assert result["skipped_content"] == 1


def test_saved_bank_math_repair_is_backed_up_and_idempotent(course):
    from scripts.repair_ccrn_math import repair
    import sqlite3

    rows = convert_text(sample(), get_catalog(course))["rows"]
    import_questions("Existing bank", rows, course)
    raw = r"An infant at \\(34.2^\circ\text{C}\\) with \\(PaCO_2\\)."
    conn = database.get_connection()
    with conn:
        conn.execute("UPDATE questions SET stimulus=? WHERE course_id=?", (raw, course))
    conn.close()
    before = dict(get_questions(course)[0])
    draft_id = add_draft(course, "Pending math", raw)
    rows[0]["question_text"] = raw
    save_draft(course, draft_id, raw, rows)
    preview = repair(database.DB_PATH)
    assert preview["questions_changed"] == 1
    assert get_questions(course)[0]["stimulus"] == raw
    result = repair(database.DB_PATH, apply=True)
    assert result["remaining_math"] == []
    with sqlite3.connect(result["backup"]) as backup:
        assert backup.execute("SELECT stimulus FROM questions WHERE course_id=?", (course,)).fetchone()[0] == raw
    after = dict(get_questions(course)[0])
    assert after["stimulus"] == "An infant at 34.2°C with PaCO₂."
    for key in before:
        if key not in ("stimulus", "content_hash"):
            assert before[key] == after[key]
    assert list_drafts(course)[0]["raw_text"] == raw
    assert result["pending_batches_changed"] == 1
    assert repair(database.DB_PATH)["questions_changed"] == 0
    assert repair(database.DB_PATH)["pending_batches_changed"] == 0


def test_conversion_retains_multiline_content_and_does_not_guess(course):
    catalog = get_catalog(course)
    result = convert_text(sample(), catalog)
    assert not result["errors"]
    row = result["rows"][0]
    assert row["question_text"] == "Sample question 1?"
    assert row["choice_a"] == "First choice\ncontinued over two lines"
    assert "Supplied distractor explanation" in row["rationale"]
    assert row["correct_answer"] == "B"
    assert not import_questions("Preview", [row], course, validate_only=True)["errors"]
    assert not get_questions(course)
    missing = convert_text(sample().replace("**Chapter:** Respiratory distress syndrome", ""), catalog)
    assert missing["rows"][0]["chapter"] == ""
    assert import_questions("Invalid", missing["rows"], course, validate_only=True)["errors"]
    assert convert_text("Unstructured paste", catalog)["errors"]


def test_queue_persistence_atomic_import_and_repeat_guard(course):
    text = sample()
    draft_id = add_draft(course, "Queued batch", text)
    assert list_drafts(course)[0]["raw_text"] == text
    with pytest.raises(ValueError):
        add_draft(course, "Queued batch", text)
    rows = convert_text(text, get_catalog(course))["rows"]
    save_draft(course, draft_id, text, rows)
    assert json.loads(list_drafts(course)[0]["rows_json"]) == rows
    invalid = [{**rows[0], "correct_answer": ""}]
    assert import_questions("Queued batch", invalid, course, queue_id=draft_id)["errors"]
    assert list_drafts(course)[0]["imported_batch_id"] is None
    assert not get_questions(course)
    result = import_questions("Queued batch", rows, course, queue_id=draft_id)
    assert result["inserted"] == 1
    assert list_drafts(course)[0]["imported_batch_id"] == result["batch_id"]
    with pytest.raises(ValueError):
        import_questions("Queued batch", rows, course, queue_id=draft_id)
    with pytest.raises(ValueError):
        save_draft(course, draft_id, "overwrite", [])
    second = add_draft(course, "Duplicate content", text)
    assert import_questions("Duplicate content", rows, course, queue_id=second)["skipped_content"] == 1
    assert len(get_questions(course)) == 1


def test_large_paste_and_real_notebooklm_batches(course):
    catalog = get_catalog(course)
    result = convert_text("\n".join(sample(n) for n in range(1, 1151)), catalog)
    assert len(result["rows"]) == 1150
    assert not result["errors"]
    assert result["rows"][-1]["question_text"] == "Sample question 1150?"
    root = Path(__file__).resolve().parents[1]
    for path in (root / "data" / "ccrn_supplied").glob("*.txt"):
        result = convert_text(path.read_text(encoding="utf-8-sig"), catalog)
        assert len(result["rows"]) == 25, path.name
        assert not result["errors"], (path.name, result["errors"])
        assert all(row["choice_d"] and row["rationale"] and row["correct_answer"] in "ABCDE" for row in result["rows"])


def test_numbered_prose_and_incomplete_batches(course):
    result = convert_text("1. Sample?\nA) One\nB) Two\nC) Three\nD) Four\nAnswer: A\nRationale: Explanation.", get_catalog(course))
    assert result["rows"][0]["question_text"] == "Sample?"
    assert result["rows"][0]["correct_answer"] == "A"
    assert import_questions("Empty", [], course)["errors"]


def test_section_numbers_include_history_and_keep_sections_separate(course):
    catalog = get_catalog(course)
    cardio, respiratory = catalog[:2]
    rows = convert_text(sample(), catalog)["rows"]
    import_questions("Earlier respiratory batch", rows, course)
    first = add_section_draft(course, respiratory["id"], sample(2))
    second = add_section_draft(course, respiratory["id"], sample(3))
    other = add_section_draft(course, cardio["id"], sample())
    drafts = {d["id"]: d for d in list_drafts(course)}
    assert drafts[first]["name"] == "Respiratory — Batch 002"
    assert drafts[second]["batch_number"] == 3
    assert drafts[other]["batch_number"] == 1
    with pytest.raises(ValueError, match="section"):
        import_questions(drafts[other]["name"], rows, course, queue_id=other)
    assert len(get_questions(course)) == 1
    assert list_drafts(course)[-1]["imported_batch_id"] is None
    ensure_schema_and_catalog()
    assert len(list_drafts(course)) == 3


def test_unnumbered_questions_get_numbers_and_inherit_section(course):
    text = sample().replace("### **Question 1**\n", "").replace("**Section:** Respiratory\n", "")
    result = convert_text(text + "\n" + text, get_catalog(course), "Respiratory")
    assert not result["errors"]
    assert [r["source_question_number"] for r in result["rows"]] == ["1", "2"]
    assert all(r["module"] == "Respiratory" for r in result["rows"])


def test_admin_paste_convert_review_import_ui(course, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import auth, utils
    monkeypatch.setattr(auth, "require_login", lambda: 1)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *a: None)
    monkeypatch.setattr(database, "is_admin", lambda *a: True)
    path = Path(__file__).resolve().parents[1] / "pages" / "4_Question_Bank_Manager.py"
    at = AppTest.from_file(str(path), default_timeout=30)
    at.session_state["qbm_course_id"] = course
    at.run()
    assert not at.exception
    respiratory = get_catalog(course)[1]
    at.text_area(key=f"ccrn_section_{respiratory['id']}_paste").set_value(sample().replace("**Section:** Respiratory\n", ""))
    [b for b in at.button if b.label == "Add to import queue"][1].click().run()
    assert not at.exception
    assert len(list_drafts(course)) == 1
    next(b for b in at.button if b.label == "Convert saved text for review").click().run()
    assert not at.exception
    assert json.loads(list_drafts(course)[0]["rows_json"])[0]["correct_answer"] == "B"
    next(b for b in at.button if b.label == "Clear all questions").click().run()
    assert json.loads(list_drafts(course)[0]["rows_json"])[0]["_include_in_next_step"] is False
    select_buttons = [b for b in at.button if b.label == "Select all questions"]
    select_buttons[-1].click().run()
    assert json.loads(list_drafts(course)[0]["rows_json"])[0]["_include_in_next_step"] is True
    [b for b in at.button if b.label == "Import selected questions"][-1].click().run()
    assert not at.exception
    assert len(get_questions(course)) == 1
    assert list_drafts(course)[0]["imported_batch_id"] is not None


def test_bulk_conversion_preserves_edits_and_import_leaves_errors_queued(course):
    respiratory = get_catalog(course)[1]
    good = add_section_draft(course, respiratory["id"], sample())
    bad = add_section_draft(course, respiratory["id"], sample(2).replace("**Correct Answer:** B", "**Correct Answer:**"))
    malformed = add_section_draft(course, respiratory["id"], "Unrecognized text")
    result = process_drafts(course, [good, bad, malformed])
    assert [r["status"] for r in result] == ["Ready for review", "Needs attention", "Needs attention"]
    drafts = {d["id"]: d for d in list_drafts(course)}
    rows = json.loads(drafts[good]["rows_json"])
    rows[0]["rationale"] = "Saved review correction"
    save_draft(course, good, sample(), rows)
    process_drafts(course, [good])
    assert json.loads(list_drafts(course)[0]["rows_json"])[0]["rationale"] == "Saved review correction"
    result = process_drafts(course, [good, bad, malformed], import_ready=True)
    assert [r["status"] for r in result] == ["Imported", "Needs attention", "Needs attention"]
    assert len(get_questions(course)) == 1
    assert get_questions(course)[0]["explanation"] == "Saved review correction"
    assert sum(d["imported_batch_id"] is None for d in list_drafts(course)) == 2
    assert process_drafts(course, [good], import_ready=True)[0]["status"] == "Already imported / unavailable"


def test_source_book_chapter_is_mapped_from_question_topic(course):
    catalog = get_catalog(course)
    text = sample().replace(
        "**Chapter:** Respiratory distress syndrome",
        "**Chapter:** Chapter 26: Assisted Ventilation",
    )
    result = convert_text(text, catalog, "Respiratory")
    assert not result["errors"]
    assert result["rows"][0]["chapter"] == "Acute respiratory distress / failure"
    assert result["rows"][0]["source_chapter"] == "Chapter 26: Assisted Ventilation"


def test_repeated_section_topic_uses_recognized_module(course):
    catalog = get_catalog(course)
    text = sample().replace(
        "**Section:** Respiratory",
        "Section: Caffeine Citrate Mechanism of Action\n**Section:** Respiratory",
    )
    result = convert_text(text, catalog, "Respiratory")
    assert not result["errors"]
    assert result["rows"][0]["module"] == "Respiratory"
    assert result["rows"][0]["subtopic"] == "Caffeine Citrate Mechanism of Action"


def test_bulk_ui_pastes_all_sections_with_one_submit(course, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import auth, utils
    monkeypatch.setattr(auth, "require_login", lambda: 1)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *a: None)
    monkeypatch.setattr(database, "is_admin", lambda *a: True)
    path = Path(__file__).resolve().parents[1] / "pages" / "4_Question_Bank_Manager.py"
    at = AppTest.from_file(str(path), default_timeout=30)
    at.session_state["qbm_course_id"] = course
    at.run()
    for module in get_catalog(course):
        text = sample(module["id"]).replace("**Section:** Respiratory", f"**Section:** {module['name']}").replace(
            "**Chapter:** Respiratory distress syndrome", f"**Chapter:** {module['chapters'][0]['name']}")
        at.text_area(key=f"ccrn_section_{module['id']}_paste").set_value(text)
    next(b for b in at.button if b.label == "Add all filled sections & convert").click().run()
    assert not at.exception
    drafts = list_drafts(course)
    assert len(drafts) == 6
    assert all(len(json.loads(d["rows_json"])) == 1 for d in drafts)
    assert len([tab for tab in at.tabs if "· 1 ready to review" in tab.label]) == 12
    assert any(subheader.value == "Question import workflow" for subheader in at.subheader)
    from src.ccrn_import_ui import WORKFLOW_SECTIONS
    rendered = "\n".join(markdown.value for markdown in at.markdown)
    for anchor, title in WORKFLOW_SECTIONS:
        assert f'href="#{anchor}"' in rendered
        assert any(expander.label == title for expander in at.expander)
    assert "6 questions in the saved queue = 0 waiting to convert + 0 needing fixes + 6 ready to review" in "\n".join(info.value for info in at.info)
    assert not get_questions(course)
    assert all(not at.text_area(key=f"ccrn_section_{m['id']}_paste").value for m in get_catalog(course))
    next(b for b in at.button if b.label == "Clear all reviewed batches").click().run()
    next(b for b in at.button if b.label == "Import selected reviewed batches").click().run()
    assert not get_questions(course)
    next(b for b in at.button if b.label == "Select all reviewed batches").click().run()
    next(b for b in at.button if b.label == "Import selected reviewed batches").click().run()
    assert not at.exception
    assert len(get_questions(course)) == 6
    assert all(d["imported_batch_id"] for d in list_drafts(course))
    assert len([tab for tab in at.tabs if "· clear" in tab.label]) == 12


def test_pending_counts_include_unconverted_batches_and_drop_on_import(course):
    module = get_catalog(course)[1]
    first = add_section_draft(course, module["id"], sample())
    add_section_draft(course, module["id"], sample(2) + "\n" + sample(3))
    assert pending_question_counts(list_drafts(course)) == {module["id"]: 3}
    process_drafts(course, [first])
    assert pending_question_counts(list_drafts(course)) == {module["id"]: 3}
    process_drafts(course, [first], import_ready=True)
    assert pending_question_counts(list_drafts(course)) == {module["id"]: 2}


def test_question_selection_imports_checked_rows_and_keeps_others_queued(course):
    from src.ccrn_import_queue import ROW_SELECTION_FIELD
    module = get_catalog(course)[1]
    draft_id = add_section_draft(course, module["id"], sample() + "\n" + sample(2))
    process_drafts(course, [draft_id])
    draft = list_drafts(course)[0]
    rows = json.loads(draft["rows_json"])
    rows[0][ROW_SELECTION_FIELD] = True
    rows[1][ROW_SELECTION_FIELD] = False
    save_draft(course, draft_id, draft["raw_text"], rows)

    result = process_drafts(course, [draft_id], import_ready=True)[0]
    assert result["status"] == "Partially imported"
    assert result["inserted"] == 1
    remaining_draft = list_drafts(course)[0]
    assert remaining_draft["imported_batch_id"] is None
    remaining = json.loads(remaining_draft["rows_json"])
    assert len(remaining) == 1 and remaining[0][ROW_SELECTION_FIELD] is False
    assert pending_question_counts([remaining_draft]) == {module["id"]: 1}

    remaining[0][ROW_SELECTION_FIELD] = True
    save_draft(course, draft_id, remaining_draft["raw_text"], remaining)
    result = process_drafts(course, [draft_id], import_ready=True)[0]
    assert result["status"] == "Imported"
    assert len(get_questions(course)) == 2
    assert list_drafts(course)[0]["imported_batch_id"] is not None
    assert [batch["name"] for batch in get_batch_history(course)] == [
        f"{module['name']} — Batch 001 — Part 1", f"{module['name']} — Batch 001"
    ]


def test_unchecked_invalid_question_does_not_block_selected_question(course):
    from src.ccrn_import_queue import ROW_SELECTION_FIELD
    module = get_catalog(course)[1]
    draft_id = add_section_draft(course, module["id"], sample() + "\n" + sample(2))
    process_drafts(course, [draft_id])
    draft = list_drafts(course)[0]
    rows = json.loads(draft["rows_json"])
    rows[1]["correct_answer"] = ""
    rows[1][ROW_SELECTION_FIELD] = False
    save_draft(course, draft_id, draft["raw_text"], rows)
    result = process_drafts(course, [draft_id], import_ready=True)[0]
    assert not result["errors"]
    assert result["inserted"] == 1 and result["remaining"] == 1


def test_question_24_short_section_resolves_without_changing_content(course):
    catalog = get_catalog(course)
    module = catalog[3]
    text = sample(24).replace("**Section:** Respiratory", "**Section:** Neurological / Behavioral-Psychosocial")
    result = convert_text(text, catalog, module["name"])
    row = result["rows"][0]
    assert row["module"] == module["name"]
    assert row["source_question_number"] == "24"
    assert row["question_text"] == "Sample question 24?"
    assert row["correct_answer"] == "B"
    assert row["chapter"] == "Respiratory distress syndrome"  # Never guess or rewrite chapters.
    assert any("standardized" in w for w in result["warnings"])
    unrelated = convert_text(sample(), catalog, module["name"])
    assert unrelated["rows"][0]["module"] == "Respiratory"
    ambiguous_catalog = [{"name": "Neurological / Behavioral-Psychosocial", "chapters": []},
                         {"name": "Neurological / Other", "chapters": []}]
    ambiguous = convert_text(sample().replace("**Section:** Respiratory", "**Section:** Neurological"), ambiguous_catalog)
    assert ambiguous["rows"][0]["module"] == "Neurological"


def test_source_chapter_repair_preserves_edits_and_live_total(course):
    from src.utils import _ccrn_pending_count
    module = get_catalog(course)[1]
    raw = sample().replace("Respiratory distress syndrome", "Chapter 29: Respiratory Disorders") + "\n**Subtopic:** Surfactant deficiency\n"
    draft = add_section_draft(course, module["id"], raw)
    rows = convert_text(raw, get_catalog(course))["rows"]
    assert rows[0]["chapter"] == "Respiratory distress syndrome"
    assert rows[0]["source_chapter"] == "Chapter 29: Respiratory Disorders"
    rows[0]["chapter"] = "Chapter 29: Respiratory Disorders"
    rows[0]["rationale"] = "Saved correction"
    save_draft(course, draft, raw, rows)
    assert _ccrn_pending_count() == 1
    result = process_drafts(course, [draft])
    assert result[0]["status"] == "Ready for review"
    assert _ccrn_pending_count() == 1
    result = process_drafts(course, [draft], import_ready=True)
    assert result[0]["inserted"] == 1
    assert get_questions(course)[0]["explanation"] == "Saved correction"
    assert _ccrn_pending_count() == 0


def test_bulk_import_converts_raw_saved_batches(course):
    module = get_catalog(course)[1]
    draft = add_section_draft(course, module["id"], sample())
    result = process_drafts(course, [draft], import_ready=True)
    assert result[0]["inserted"] == 1
    assert not pending_question_counts(list_drafts(course)).get(module["id"], 0)
