"""Admin paste, queue, and review workflow for Neonatal CCRN."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from src import database
from src.question_lenses import get_lenses, set_batch_lens
from src.ccrn_chapter_mapping import map_chapters
from src.import_math_text import normalize_math_row

from src.ccrn_import_queue import (FIELDS, add_section_draft, convert_text, list_drafts,
                                   save_draft, process_drafts, draft_question_count,
                                   ROW_SELECTION_FIELD, row_selected, delete_drafts)
from src.neonatal_ccrn import get_batch_history, get_catalog, import_questions

WORKFLOW_SECTIONS = (
    ("ccrn-paste", "1 · Paste & save"),
    ("ccrn-queue", "2 · Convert saved questions"),
    ("ccrn-review", "3 · Review & import"),
    ("ccrn-imported", "4 · Imported questions"),
)


def _workflow_heading(index):
    anchor, title = WORKFLOW_SECTIONS[index]
    st.markdown(f'<span id="{anchor}"></span>', unsafe_allow_html=True)
    links = [f'<a class="sf-workflow-jump" href="#{target}" target="_self">{label}</a>'
             for target, label in WORKFLOW_SECTIONS]
    st.markdown('Go to: ' + ' · '.join(links), unsafe_allow_html=True)


def _queue_breakdown(totals):
    total = sum(totals[code] for code in ("convert", "fix", "ready"))
    return (f"{total:,} questions in the saved queue = "
            f"{totals['convert']:,} waiting to convert + {totals['fix']:,} needing fixes + "
            f"{totals['ready']:,} ready to review. Each question is counted once.")


def _draft_stage(course_id, draft):
    """Return the durable stage of one queued batch and its next action."""
    rows = json.loads(draft["rows_json"])
    questions = draft_question_count(draft)
    if not rows:
        catalog = get_catalog(course_id)
        module = next((m for m in catalog if m['id'] == draft['module_id']), None)
        preview = convert_text(draft['raw_text'], catalog, module['name'] if module else '', lens=draft['lens'])
        errors = preview['errors']
        if module and any(row.get('module') != module['name'] for row in preview['rows']):
            errors = errors + ["The pasted Section labels do not match this batch's section."]
        if errors:
            return {"code": "fix", "questions": questions, "label": "Needs fixes",
                    "issues": len(errors), "errors": errors, "boundary": "Step 2 → Step 3: conversion blocked",
                    "action": "Correct the original paste in Needs fixing, then convert again"}
        return {"code": "convert", "questions": questions,
                "label": "Waiting to convert", "issues": 0,
                "action": "Run Convert selected batches"}
    included = [row for row in rows if row_selected(row)]
    if not included:
        return {"code": "ready", "questions": questions,
                "label": "Selection needed", "issues": 0,
                "action": "Select one or more question rows for the next step"}
    errors = import_questions(draft["name"], included, course_id, validate_only=True)["errors"]
    if errors:
        return {"code": "fix", "questions": questions,
                "label": "Needs fixes", "issues": len(errors),
                "errors": errors, "boundary": "Step 2 → Step 3: validation blocked",
                "action": "Correct the listed fields or leave those questions unchecked, then save review changes"}
    return {"code": "ready", "questions": questions,
            "label": "Ready to review", "issues": 0,
            "action": "Select the reviewed rows to include, then import"}


def _batch_selection_frame(rows, key, selection_label):
    """Render a checkbox-per-batch grid with durable select-all/clear behavior."""
    revision = int(st.session_state.get(key + "_revision", 0))
    selected_default = bool(st.session_state.get(key + "_default", True))
    frame = pd.DataFrame([{selection_label: selected_default, **row} for row in rows])
    return st.data_editor(
        frame, hide_index=True, num_rows="fixed", use_container_width=True,
        disabled=[column for column in frame.columns if column != selection_label],
        column_config={selection_label: st.column_config.CheckboxColumn(selection_label, width="small"),
                       "_id": None},
        key=f"{key}_editor_{revision}",
    )


def _reset_batch_selection(key, selected):
    st.session_state[key + "_default"] = selected
    st.session_state[key + "_revision"] = int(st.session_state.get(key + "_revision", 0)) + 1


def _workflow_snapshot(course_id, drafts=None):
    drafts = drafts if drafts is not None else list_drafts(course_id)
    queued = [draft for draft in drafts if draft["imported_batch_id"] is None]
    stages = {draft["id"]: _draft_stage(course_id, draft) for draft in queued}
    totals = {code: sum(stage["questions"] for stage in stages.values() if stage["code"] == code)
              for code in ("convert", "fix", "ready")}
    conn = database.get_connection()
    try:
        totals["imported"] = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE course_id=? AND COALESCE(is_archived,0)=0",
            (course_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    return queued, stages, totals


def render_import_workflow_overview(course_id):
    """Show a live map of the paste-to-bank pipeline at the top of the import tab."""
    queued, stages, totals = _workflow_snapshot(course_id)
    st.markdown("""
    <style>
    .sf-import-flow {display:flex; align-items:stretch; gap:.45rem; margin:.35rem 0 .6rem;}
    .sf-import-step {flex:1; min-width:0; padding:.8rem .9rem; background:#fff;
        display:block; text-decoration:none !important;
        border:1px solid #dbe3ec; border-top:4px solid #0f766e; border-radius:8px;
        box-shadow:0 1px 2px rgba(15,23,42,.04);}
    .sf-import-step strong {display:block; color:#0f172a; margin-bottom:.2rem;}
    .sf-import-step:hover,.sf-import-step:focus-visible {background:#f0fdfa; outline:2px solid #0f766e;}
    .sf-import-step.sf-import-broken {background:#fef2f2; border:2px solid #dc2626; margin:.6rem 0;}
    .sf-import-broken strong,.sf-import-broken .sf-import-count,.sf-import-broken .sf-import-note {color:#991b1b;}
    [data-testid="stTabs"] [role="tab"].sf-ccrn-broken-tab {
        background:#fee2e2 !important; color:#991b1b !important; border:2px solid #dc2626 !important;
    }
    [id^="ccrn-"] {scroll-margin-top:5rem;}
    .sf-import-count {font-size:1.35rem; font-weight:750; color:#0f766e;}
    .sf-import-note {font-size:.78rem; color:#64748b; line-height:1.3;}
    .sf-import-arrow {display:flex; align-items:center; color:#64748b; font-size:1.35rem;}
    @media(max-width:850px){.sf-import-flow{flex-direction:column}.sf-import-arrow{display:none}}
    </style>
    """, unsafe_allow_html=True)
    st.subheader("Question import workflow")
    from html import escape
    counts = ["Add questions", f"{totals['convert']:,} to convert",
              f"{totals['ready']:,} ready to review", f"{totals['imported']:,} in the bank"]
    notes = ["Paste new text here, then save it to the queue.",
             "Turn saved text into question rows. Blocked batches appear in Needs fixing.",
             "Part of the saved queue above. Review, correct, then import.",
             "Already imported; separate from the saved queue."]
    cards = [f'<a class="sf-import-step" href="#{anchor}" target="_self">'
             f'<strong>{escape(title)}</strong><span class="sf-import-count">{count}</span>'
             f'<div class="sf-import-note">{note}</div></a>'
             for (anchor, title), count, note in zip(WORKFLOW_SECTIONS, counts, notes)]
    st.markdown('<nav class="sf-import-flow" aria-label="Question import workflow">' +
                '<span class="sf-import-arrow" aria-hidden="true">→</span>'.join(cards) + '</nav>',
                unsafe_allow_html=True)
    st.info(_queue_breakdown(totals))
    st.caption("Click a box to open the section with the same name. Each section can be collapsed. The review count is a subset of the saved queue, not additional questions. Text still in the paste boxes is not included until saved.")


def _run_bulk(course_id, selected, import_ready=False):
    results = process_drafts(course_id, selected, import_ready=import_ready)
    st.session_state["ccrn_bulk_import_results" if import_ready else "ccrn_bulk_results"] = results
    for result in results:
        if result["converted"]:
            key = f"ccrn_draft_{result['id']}revision"
            st.session_state[key] = st.session_state.get(key, 0) + 1
    if any(result["inserted"] for result in results):
        st.session_state.pop("ccrn_mock_shortages", None)


def _render_bulk_actions(course_id):
    notice = st.session_state.pop("ccrn_bulk_notice", None)
    if notice:
        st.info(notice)
    queued, stages, totals = _workflow_snapshot(course_id)
    st.info(_queue_breakdown(totals))
    pending = {d["id"]: d for d in queued if stages[d['id']]['code'] == 'convert'}
    queue_rows = []
    for draft in pending.values():
        stage = stages[draft["id"]]
        queue_rows.append({"Queued batch": draft["name"], "Questions": draft_question_count(draft),
                           "Stage": stage["label"], "Validation issues": stage["issues"] or "—",
                           "Next action": stage["action"]})

    st.caption("Only batches waiting to convert are listed here. Conversion moves them to Review & import or Needs fixing.")
    results = [r for r in st.session_state.get("ccrn_bulk_results", [])
               if r['id'] in stages]
    if results:
        failed = [r for r in results if r["errors"]]
        if failed:
            st.info(f"{len(failed)} batches need attention. Conversion errors appear below; review errors appear in Review & import.")
        else:
            ready = sum(r['status'] == 'Ready for review' for r in results)
            if ready:
                st.success(f"{ready} batches converted and ready to import. Review them, then choose Import selected reviewed batches. Pending counts clear after import.")
            else:
                st.success(f"Processed {len(results)} batches: {sum(r['inserted'] for r in results)} imported, {sum(r['duplicates'] for r in results)} duplicates skipped.")
        st.dataframe(pd.DataFrame([{"Batch": r["batch"], "Result": r["status"], "Questions": r["questions"],
                                    "Imported": r["inserted"], "Duplicates skipped": r["duplicates"]} for r in results]),
                     hide_index=True, use_container_width=True)
        with st.expander("Bulk results: validation details and conversion notes", expanded=bool(failed)):
            for result in results:
                if result["errors"] or result["warnings"]:
                    st.write(result["batch"])
                    for message in result["warnings"]:
                        st.write(message)
    if not pending:
        st.info("No batches waiting to convert. Continue to Needs fixing if shown, or Review & import.")
        return
    st.markdown("**Choose batches to convert**")
    st.caption("Every batch has its own checkbox. All are selected by default; unchecked batches stay in the queue.")
    with st.form("ccrn_bulk_actions"):
        table_rows = [{"_id": draft["id"], **row} for draft, row in zip(pending.values(), queue_rows)]
        selection = _batch_selection_frame(table_rows, "ccrn_convert_batches", "Convert")
        st.caption("Run this after adding new pasted sections. Existing converted edits are preserved. The result table will identify anything that needs correction.")
        select_all = st.form_submit_button("Select all batches")
        clear_all = st.form_submit_button("Clear all batches")
        convert = st.form_submit_button("Convert selected batches", type="primary")
    if select_all or clear_all:
        _reset_batch_selection("ccrn_convert_batches", select_all)
        st.rerun()
    if convert:
        selected = [int(row["_id"]) for _, row in selection.iterrows() if bool(row["Convert"])]
        if not selected:
            st.warning("Select at least one batch.")
        else:
            _run_bulk(course_id, selected)
            st.rerun()


def _render_bulk_import(course_id):
    queued, stages, totals = _workflow_snapshot(course_id)
    ready = {d['id']: d for d in queued if stages[d['id']]['code'] == 'ready'}
    results = st.session_state.get("ccrn_bulk_import_results", [])
    if results:
        failed = [result for result in results if result["errors"]]
        imported = sum(result["inserted"] for result in results)
        remaining = sum(result.get("remaining", 0) for result in results)
        if failed:
            st.error(f"{len(failed)} selected batches need attention. {failed[0]['errors'][0]}")
        else:
            message = f"Imported {imported:,} selected questions."
            if remaining:
                message += f" {remaining:,} unchecked questions remain in their batches."
            st.success(message)
        st.dataframe(pd.DataFrame([{
            "Batch": result["batch"], "Result": result["status"],
            "Imported": result["inserted"], "Left in queue": result.get("remaining", 0),
            "Duplicates skipped": result["duplicates"],
        } for result in results]), hide_index=True, use_container_width=True)
    if not ready:
        st.info("No batches are ready to import yet. Convert saved text in section 2, then resolve any validation issues here.")
        return
    st.markdown(f"**Import after review — {totals['ready']:,} questions eligible**")
    st.caption("Select batches for this import pass. Within each batch, only question rows checked in the review grid will advance.")
    with st.form("ccrn_bulk_import"):
        rows = [{"_id": draft["id"], "Batch": draft["name"],
                 "Questions remaining": draft_question_count(draft)} for draft in ready.values()]
        selection = _batch_selection_frame(rows, "ccrn_import_batches", "Import")
        select_all = st.form_submit_button("Select all reviewed batches")
        clear_all = st.form_submit_button("Clear all reviewed batches")
        commit = st.form_submit_button("Import selected reviewed batches")
    if select_all or clear_all:
        _reset_batch_selection("ccrn_import_batches", select_all)
        st.rerun()
    if commit:
        selected = [int(row["_id"]) for _, row in selection.iterrows() if bool(row["Import"])]
        if not selected:
            st.warning("Select at least one reviewed batch.")
        else:
            _run_bulk(course_id, selected, import_ready=True)
            st.rerun()


def _render_bulk_delete(course_id, scope="review"):
    notice_key = f"ccrn_delete_notice_{scope}"
    notice = st.session_state.pop(notice_key, None)
    if notice:
        st.success(notice)
    queued, stages, _ = _workflow_snapshot(course_id)
    if not queued:
        return
    with st.expander("Delete saved batches"):
        st.caption("Permanently remove unwanted batches and their remaining questions from the saved queue, including questions held back from import. Already imported questions and import history are kept. This cannot be undone.")
        key = f"ccrn_delete_batches_{course_id}_{scope}"
        st.session_state.setdefault(key + "_default", False)
        if st.button("Select all batches to delete", key=key + "_all"):
            _reset_batch_selection(key, True)
            st.rerun()
        if st.button("Clear deletion selection", key=key + "_clear"):
            _reset_batch_selection(key, False)
            st.rerun()
        # Changing queue membership creates a fresh editor; stale row indices must
        # never select a different batch after an import or deletion.
        membership = "_".join(str(d["id"]) for d in queued)
        editor_key = key + "_" + membership
        st.session_state[editor_key + "_default"] = st.session_state[key + "_default"]
        st.session_state[editor_key + "_revision"] = st.session_state.get(key + "_revision", 0)
        selection = _batch_selection_frame([
            {"_id": d["id"], "Batch": d["name"],
             "Questions remaining": draft_question_count(d), "Stage": stages[d["id"]]["label"]}
            for d in queued
        ], editor_key, "Delete")
        selected = [int(row["_id"]) for _, row in selection.iterrows() if bool(row["Delete"])]
        count = sum(draft_question_count(d) for d in queued if d["id"] in selected)
        st.caption(f"Selected for deletion: {len(selected)} batches · {count} remaining questions")
        confirmed = st.checkbox("I understand these saved batches will be permanently deleted.",
                                key=key + f"_confirm_{st.session_state.get(key + '_revision', 0)}_" + "_".join(map(str, selected)))
        if st.button("Delete selected saved batches", key=key + "_delete", disabled=not selected or not confirmed):
            deleted = delete_drafts(course_id, selected)
            _reset_batch_selection(key, False)
            st.session_state[notice_key] = f"Deleted {deleted} saved batches from the queue."
            st.session_state.pop("ccrn_bulk_import_results", None)
            st.rerun()


def _render_needs_fixing(course_id, catalog, phase=None):
    queued, stages, _ = _workflow_snapshot(course_id)
    broken = [d for d in queued if stages[d['id']]['code'] == 'fix'
              and (phase is None or ('review' if json.loads(d['rows_json']) else 'convert') == phase)]
    if not broken:
        return set()
    st.subheader("⚠ Needs fixing", anchor="ccrn-fixes" if phase != "review" else "ccrn-review-fixes")
    st.error("These batches are blocked. Choose a batch tab to see the exact question/field errors and edit it directly below. This section disappears when all blocks are resolved.")
    tabs = st.tabs([f"⚠ {d['name']} · {stages[d['id']]['issues']} issues" for d in broken])
    for tab, draft in zip(tabs, broken):
        with tab:
            stage = stages[draft['id']]
            st.error(stage['boundary'])
            st.caption(f"{stage['questions']} questions held in this batch; {stage['issues']} validation messages. The whole batch waits even if only one question has an error.")
            for error in stage['errors']:
                # Import validation uses spreadsheet row numbers (header is row 1).
                import re
                message = re.sub(r'^Row (\d+):', lambda m: f"Question {int(m[1]) - 1}:", error)
                st.write(message)
            st.info("Next action: " + stage['action'])
            module = next((m for m in catalog if m['id'] == draft['module_id']), None)
            _render_section_queue(course_id, catalog, module, only_id=draft['id'])
    return {d['id'] for d in broken}


def render_paste_queue(course_id, catalog, user_id=None, render_file_import=None):
    LENSES = get_lenses()
    with st.expander(WORKFLOW_SECTIONS[0][1], expanded=False):
        _workflow_heading(0)
        labels = _render_paste_stage(course_id, catalog, user_id)
        _render_bulk_delete(course_id, "paste")
    with st.expander(WORKFLOW_SECTIONS[1][1], expanded=False):
        _workflow_heading(1)
        _render_bulk_actions(course_id)
        conversion_ids = _render_needs_fixing(course_id, catalog, phase="convert")
        _render_bulk_delete(course_id, "convert")
    history = get_batch_history(course_id)
    with st.expander(WORKFLOW_SECTIONS[2][1], expanded=False):
        _workflow_heading(2)
        review_ids = _render_needs_fixing(course_id, catalog, phase="review")
        _render_review_stage(course_id, catalog, labels, history, conversion_ids | review_ids)
        if render_file_import is not None:
            render_file_import()
        _render_bulk_delete(course_id, "review")
    with st.expander(WORKFLOW_SECTIONS[3][1], expanded=False):
        _workflow_heading(3)
        _render_imported_stage(course_id, history)
        if history:
            with st.expander("Assign or correct an imported batch's lens"):
                batch_by_id = {b['id']: b for b in history}
                batch_id = st.selectbox("Imported batch", list(batch_by_id),
                    format_func=lambda bid: f"{batch_by_id[bid]['name']} · {batch_by_id[bid]['questions_imported']} questions · {LENSES.get(batch_by_id[bid].get('lens'), 'Standard / no lens')}",
                    key=f"bank_lens_batch_{course_id}")
                with st.form(f"bank_imported_lens_{course_id}_{batch_id}"):
                    chosen = st.session_state.get('b_lens', 'all')
                    st.caption('Use the Question lens selection at the top of the page.')
                    if st.form_submit_button("Apply selected lens to this imported batch", disabled=chosen not in LENSES):
                        count = set_batch_lens(course_id, batch_id, chosen, imported=True)
                        st.session_state[f"bank_lens_notice_{course_id}"] = f"Updated {count} questions to {LENSES[chosen]}."
                        st.rerun()
                notice = st.session_state.pop(f"bank_lens_notice_{course_id}", None)
                if notice:
                    st.success(notice)

        _render_bulk_delete(course_id, "imported")


def _render_paste_stage(course_id, catalog, user_id):
    from src.import_tab_settings import hidden_tab_ids, set_tabs_removed, review_tab_groups
    hidden = hidden_tab_ids(course_id)
    visible = [m for m in catalog if m['id'] not in hidden]
    LENSES = get_lenses()
    notice = st.session_state.pop("ccrn_paste_notice", None)
    if notice:
        st.success(notice)
    if not visible:
      with st.popover('Delete'):
        removed_modules = {m['id']: m['name'] for m in catalog if m['id'] in hidden}
        if removed_modules:
            with st.form(f'restore_import_tabs_{course_id}'):
                restore = st.multiselect('Tabs to restore', list(removed_modules), format_func=removed_modules.get)
                if st.form_submit_button('Restore selected tabs', disabled=not removed_modules):
                    set_tabs_removed(course_id, restore, removed=False)
                    st.session_state['ccrn_paste_notice'] = f'Restored {len(restore)} tabs.'
                    st.rerun()
        else:
            st.caption('No deleted tabs for this course.')
    for error in st.session_state.pop("ccrn_paste_errors", []):
        st.error(error)
    st.caption("Paste new NotebookLM output below, then choose Add all filled sections to queue. The tab badges describe previously saved batches, not the text currently in these paste boxes.")
    st.markdown('''<style>
    [data-testid="stTabs"] [role="tab"].sf-ccrn-pending-tab {
        background: #fef08a !important; color: #713f12 !important;
        border: 1px solid #eab308 !important;
    }
    .sf-ccrn-mark-unread {
        background: white; color: #713f12; border: 1px solid #d1d5db;
        border-radius: 6px; padding: 5px 12px; margin: 8px 0; cursor: pointer;
        font: inherit; font-size: 0.875rem;
    }
    .sf-ccrn-mark-unread:disabled { opacity: 0.5; cursor: default; }
    </style>''', unsafe_allow_html=True)
    st.caption("Choose a section below and paste its questions. Section names, batch numbers, question counts, and final question IDs are filled in automatically.")
    short_labels = [module["name"] for module in catalog]
    drafts = list_drafts(course_id)
    queued, stages, _ = _workflow_snapshot(course_id, drafts)
    labels = []
    for short_label, module in zip(short_labels, catalog):
        section_stages = [stages[draft["id"]] for draft in queued if draft["module_id"] == module["id"]]
        parts = []
        for code, suffix in (("convert", "to convert"), ("fix", "need fixes"), ("ready", "ready to review")):
            count = sum(stage["questions"] for stage in section_stages if stage["code"] == code)
            if count:
                parts.append(f"{count} {suffix}")
        labels.append(f"{short_label} · {' · '.join(parts) if parts else 'clear'}")
    st.caption("Each tab shows its current import stage. Clear means that section has no questions waiting in the queue.")
    st.caption("Yellow = unread. Opening or editing a section marks it read. Mark unread turns it yellow again. New queued batches mark their section unread. Read status is remembered in this browser.")
    config = {"user": user_id, "course": course_id, "sections": [
        {"id": str(module["id"]), "label": label,
         "batches": sorted(d["id"] for d in drafts if d["module_id"] == module["id"] and d["imported_batch_id"] is None)}
        for module, label in zip(catalog, labels)
    ]}
    script = Path(__file__).with_name("ccrn_tab_read_state.js").read_text(encoding="utf-8")
    components.html("<script>" + script.replace("__CCRN_TAB_CONFIG__", json.dumps(config).replace("<", "\\u003c")) + "</script>", height=0)
    for module in catalog:
        scope = f"ccrn_section_{module['id']}"
        preserved = f"bank_tab_text_{course_id}_{module['id']}"
        if module['id'] not in hidden and scope + '_paste' not in st.session_state and preserved in st.session_state:
            st.session_state[scope + '_paste'] = st.session_state.pop(preserved)
        if st.session_state.pop(scope + "_clear", False):
            st.session_state[scope + "_paste"] = ""
    lens = st.session_state.get('b_lens', 'all')
    lens = lens if lens in LENSES else 'standard'
    st.caption(f"New batches use the lens selected at the top: {LENSES[lens]}.")
    if not visible:
        st.info('All import tabs have been deleted for this course. Use Restore deleted tabs above to bring them back.')
        return labels
    toolbar_config = {'course': course_id, 'removed': [{'id': str(m['id']), 'name': m['name']} for m in catalog if m['id'] in hidden], 'sections': [
        {'id': str(m['id']), 'name': m['name'], 'label': label}
        for m, label in zip(catalog, labels) if m['id'] not in hidden]}
    toolbar_config['reviews'] = review_tab_groups(user_id, course_id, catalog)
    toolbar_config['user'] = user_id
    toolbar_script = Path(__file__).with_name('import_tab_toolbar.js').read_text(encoding='utf-8')
    components.html('<script>' + toolbar_script.replace('__IMPORT_TAB_CONFIG__', json.dumps(toolbar_config).replace('<', '\\u003c')) + '</script>', height=0)
    st.markdown('''<style>
    .st-key-import_tab_delete_bridge { display: none; }
    .sf-import-tab-action { background: white; color: #713f12; border: 1px solid #d1d5db;
        border-radius: 6px; padding: 5px 12px; margin: 8px 0 8px 8px; cursor: pointer;
        font: inherit; font-size: .875rem; }
    [data-testid="stTabs"] [role="tab"].sf-import-tab-selected {
        background: #fef08a !important; color: #713f12 !important;
        border: 1px solid #eab308 !important;
        box-shadow: inset 0 0 0 2px #eab308; border-radius: 5px;
    }
    .sf-import-bulk-menu { background: white; color: #172033; padding: 12px; border: 1px solid #d1d5db;
        border-radius: 8px; margin: 0 0 12px; max-width: 650px; }
    .sf-import-bulk-list { max-height: 300px; overflow: auto; }
    .sf-import-bulk-list label { display: flex; align-items: start; gap: 8px; padding: 7px; }
    .sf-import-review-filter { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
    .sf-import-review-filter select { font: inherit; color: inherit; background: white; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px; max-width: 100%; }
    .sf-import-review-count { font-size: .875rem; color: #64748b; }
    </style>''', unsafe_allow_html=True)
    st.caption('Choose a review, then show only modules in it or outside it. Select outside review hides the review modules and selects the others. Invert selection toggles the shown tabs. Use Delete for bulk deletion or restore.')
    with st.form("ccrn_all_sections_paste"):
        with st.container(key='import_tab_delete_bridge'):
            delete_payload = st.text_input('Import tab deletion selection', key=f'import_tab_delete_ids_{course_id}')
            delete_selected = st.form_submit_button('Apply import tab deletion', key=f'import_tab_delete_submit_{course_id}')
        visible_labels = [label for module, label in zip(catalog, labels) if module['id'] not in hidden]
        paste_tabs = st.tabs(visible_labels)
        pasted, individual = {}, {}
        for tab, module in zip(paste_tabs, visible):
            with tab:
                st.markdown(f"**{module['name']}**")
                pasted[module["id"]] = st.text_area("Paste NotebookLM questions", height=320,
                    key=f"ccrn_section_{module['id']}_paste",
                    placeholder="Paste this section's questions, choices, answers, and rationales here.")
                individual[module["id"]] = st.form_submit_button("Add to import queue", key=f"ccrn_add_{module['id']}")
        st.caption("Fill any or all section tabs above, then save them together. Blank sections are skipped.")
        add_all = st.form_submit_button("Add all filled sections to queue", type="primary")
        add_convert = st.form_submit_button("Add all filled sections & convert")
    removed_ids = []
    if delete_selected:
        try:
            request = json.loads(delete_payload)
            action = request.get('action')
            requested_ids = request.get('ids')
            if not isinstance(requested_ids, list):
                raise ValueError('Invalid selection')
            requested_ids = {int(mid) for mid in requested_ids}
            if action == 'restore':
                if not requested_ids <= hidden:
                    raise ValueError('Invalid selection')
                set_tabs_removed(course_id, requested_ids, removed=False)
                st.session_state['ccrn_paste_notice'] = f'Restored {len(requested_ids)} tabs.'
                st.rerun()
            if action != 'delete':
                raise ValueError('Invalid action')
            if not requested_ids <= {m['id'] for m in visible}:
                raise ValueError('Invalid selection')
            removed_ids = sorted(requested_ids)
        except (ValueError, TypeError, AttributeError):
            st.error('The tab selection has changed. Select the tabs again.')
    if removed_ids:
        for mid in removed_ids:
            st.session_state[f'bank_tab_text_{course_id}_{mid}'] = pasted[mid]
        set_tabs_removed(course_id, removed_ids)
        st.session_state['ccrn_paste_notice'] = f'Deleted {len(removed_ids)} import tabs. Questions and saved batches are kept. Restore deleted tabs can bring them back.'
        st.rerun()
    elif delete_selected:
        st.warning('Select at least one tab to delete.')
    requested = [m for m in visible if (add_all or add_convert) and pasted[m["id"]].strip() or individual[m["id"]]]
    if requested:
        saved, errors = [], []
        for module in requested:
            try:
                draft_id = add_section_draft(course_id, module["id"], pasted[module["id"]], lens=lens)
            except ValueError as exc:
                errors.append(f"{module['name']}: {exc}")
            else:
                saved.append(draft_id)
                scope = f"ccrn_section_{module['id']}"
                st.session_state[scope + "_clear"] = True
                st.session_state[scope + "_selected"] = draft_id
        st.session_state["ccrn_paste_notice"] = f"Saved {len(saved)} batches."
        st.session_state["ccrn_paste_errors"] = errors
        if add_convert and saved:
            _run_bulk(course_id, saved)
        st.rerun()
    elif add_all or add_convert:
        st.warning("Paste questions into at least one section first.")
    return labels


def _render_review_stage(course_id, catalog, labels, history, broken_ids):
    from src.import_tab_settings import hidden_tab_ids
    hidden = hidden_tab_ids(course_id)
    st.info(_queue_breakdown(_workflow_snapshot(course_id)[2]))
    st.caption("These are the same saved batches shown in section 2. Open a section to inspect its batches; ready to review means conversion and validation have passed, not that review is finished. Import controls are below the editors.")
    visible_pairs = [(module, label) for module, label in zip(catalog, labels) if module['id'] not in hidden]
    section_tabs = st.tabs([label for _, label in visible_pairs]) if visible_pairs else []
    for tab, (module, _) in zip(section_tabs, visible_pairs):
        with tab:
            st.subheader(module["name"])
            _render_section_queue(course_id, catalog, module, exclude_ids=broken_ids)
            with st.expander("Section import history"):
                records = []
                for batch in history:
                    part = next((m for m in batch["modules"] if m["name"] == module["name"] and m["added_count"] > 0), None)
                    if part:
                        records.append({"Batch": batch["name"], "Questions imported": part["added_count"], "Section total after batch": part["after_count"], "Imported": batch["imported_at"]})
                if records:
                    st.dataframe(pd.DataFrame(records), hide_index=True, use_container_width=True)
                else:
                    st.caption("No questions imported into this section yet.")
    pending_modules = {d['module_id'] for d in list_drafts(course_id) if d['imported_batch_id'] is None}
    for module in catalog:
        if module['id'] in hidden and module['id'] in pending_modules:
            with st.expander(f"Saved batches from deleted tab: {module['name']}"):
                _render_section_queue(course_id, catalog, module, exclude_ids=broken_ids)
    if None in pending_modules:
        with st.expander("Earlier saved batches"):
            _render_section_queue(course_id, catalog, exclude_ids=broken_ids)
    _render_bulk_import(course_id)


def _render_imported_stage(course_id, history):
    st.metric("Questions currently in the bank", _workflow_snapshot(course_id)[2]['imported'])
    st.caption("These questions have completed import and are no longer in the saved queue.")
    with st.expander("All import batch history"):
        if history:
            st.dataframe(pd.DataFrame([{"Batch": b['name'], "Questions imported": b['questions_imported'],
                                        "Imported": b['imported_at']} for b in history]),
                         hide_index=True, use_container_width=True)
            for batch in history:
                with st.expander(batch['name']):
                    st.dataframe(pd.DataFrame(batch['modules']).rename(columns={
                        'name': 'Module', 'before_count': 'Before import',
                        'added_count': 'Added', 'after_count': 'After import'}),
                        hide_index=True, use_container_width=True)
        else:
            st.info("No batches imported yet.")


def _render_section_queue(course_id, catalog, section=None, only_id=None, exclude_ids=()):
    LENSES = get_lenses()
    scope = f"ccrn_section_{section['id']}" if section else "ccrn_legacy"
    if only_id is not None:
        scope += f"_fix_{only_id}"
    notice_key = scope + "_notice"
    selected_key = scope + "_selected"
    st.caption("Inspect saved batches for this section here. Edit the converted rows, save your changes, then import after review.")
    notice = st.session_state.pop(notice_key, None)
    if notice:
        st.success(notice)
    drafts = [d for d in list_drafts(course_id) if d["module_id"] == (section["id"] if section else None)]
    completed = sum(d['imported_batch_id'] is not None for d in drafts)
    pending = [d for d in drafts if d["imported_batch_id"] is None
               and (only_id is None or d['id'] == only_id) and d['id'] not in exclude_ids]
    section_stages = {d['id']: _draft_stage(course_id, d) for d in pending}
    totals = {code: sum(s['questions'] for s in section_stages.values() if s['code'] == code)
              for code in ('convert', 'fix', 'ready')}
    st.markdown("**Saved batches in this section**")
    st.caption(_queue_breakdown(totals) + f" {completed} batches previously imported.")
    if not pending:
        st.info("No batches to review here. Any blocked batches are in Needs fixing above.")
        return
    by_id = {d["id"]: d for d in pending}
    if st.session_state.get(selected_key) not in by_id:
        st.session_state[selected_key] = pending[0]["id"]
    selected = st.selectbox("Batch to review", list(by_id), key=selected_key,
                            format_func=lambda key: f"{by_id[key]['name']} · {section_stages[key]['label']}")
    draft = by_id[selected]
    prefix = f"ccrn_draft_{selected}"
    st.caption(f"Saved question lens: {LENSES.get(draft.get('lens'), LENSES['standard'])}")
    with st.form(prefix + "_lens_form"):
        chosen_lens = st.session_state.get('b_lens', 'all')
        st.caption('To change this saved batch, choose a lens at the top and apply it here.')
        if st.form_submit_button("Apply selected lens to this batch", disabled=chosen_lens not in LENSES):
            set_batch_lens(course_id, selected, chosen_lens)
            st.rerun()

    rows, _ = map_chapters(json.loads(draft["rows_json"]), catalog)
    rows = [normalize_math_row(row) for row in rows]
    with st.expander("Original paste & conversion", expanded=not rows):
        st.download_button("Download saved text", draft["raw_text"], f"ccrn_batch_{selected}.txt", "text/plain", key=prefix+"download")
        st.caption("Recognizes Question 1 / 1. headings or unnumbered Question: / Question Stem: labels, A–E choices, and Answer / Rationale labels, including NotebookLM bold formatting. Unmatched chapters stay blank for review.")
        with st.form(prefix + "source_form"):
            edited_text = st.text_area("Batch text", draft["raw_text"], height=360, key=prefix+"raw")
            source_saved = st.form_submit_button("Save text changes")
        if source_saved:
            save_draft(course_id, selected, edited_text, [] if edited_text != draft["raw_text"] else rows)
            st.session_state[notice_key] = "Text saved. Convert again if you changed the text."
            st.rerun()
        default_module = section["name"] if section else st.selectbox("Default module (if absent from text)", ["", *[m["name"] for m in catalog]], key=prefix+"module")
        module = next((m for m in catalog if m["name"] == default_module), None)
        default_chapter = st.selectbox("Default chapter (only for a batch covering one chapter)",
                                       ["", *[ch["name"] for ch in module["chapters"]]] if module else [""], key=prefix+"chapter")
        st.caption("Save text changes before converting. Converting again replaces the saved structured draft.")
        if st.button("Convert saved text for review", key=prefix+"convert"):
            result = convert_text(draft["raw_text"], catalog, default_module, default_chapter, lens=draft["lens"])
            if section:
                for row in result["rows"]:
                    if row["module"] != section["name"]:
                        result["errors"].append(f"Question {row['source_question_number']} names {row['module']}; this queue is for {section['name']}. Correct its Section label in the saved text.")
            if result["errors"]:
                for error in result["errors"]:
                    st.error(error)
            else:
                save_draft(course_id, selected, draft["raw_text"], result["rows"])
                st.session_state[notice_key] = f"Converted {len(result['rows'])} questions. " + " ".join(result["warnings"])
                # A new editor key prevents stale edits from being replayed after conversion.
                st.session_state[prefix+"revision"] = st.session_state.get(prefix+"revision", 0) + 1
                st.rerun()
    if not rows:
        return
    st.markdown(f"**Review {len(rows):,} converted questions**")
    st.caption("Common NotebookLM formulas and units are shown as readable text, including subscripts and symbols. The original paste is available above; unsupported formulas retain their source notation for review.")
    st.caption("Question numbers and counts are automatic; permanent question IDs are assigned on import. Edit cells to correct fields. Scroll right for answers, rationales, and sources. Module and chapter must match the course catalog. Blank difficulty uses 3 (Intermediate) for lens batches and 5 (Stretch) for Standard / no lens.")
    with st.expander("Module and chapter reference"):
        st.dataframe(pd.DataFrame([{"Module": m["name"], "Chapter": ch["name"]} for m in catalog for ch in m["chapters"]]), hide_index=True)
    revision = st.session_state.get(prefix+"revision", 0)
    review_frame = pd.DataFrame(rows, columns=FIELDS).fillna("")
    review_frame.insert(0, "question_number", range(1, len(rows) + 1))
    review_frame.insert(0, "include_in_next_step", [row_selected(row) for row in rows])
    with st.form(prefix+f"review_{revision}"):
        frame = st.data_editor(review_frame, hide_index=True,
                               disabled=["question_number", "source_question_number", *(["module"] if section else [])],
                               use_container_width=True, height=420, num_rows="fixed", key=prefix+f"editor_{revision}",
                               column_config={"include_in_next_step": st.column_config.CheckboxColumn("Include", help="Checked questions advance; unchecked questions remain in this batch."),
                                              "question_number": st.column_config.NumberColumn("Question #"), "source_question_number": None, "module": st.column_config.SelectboxColumn("Module", options=[m["name"] for m in catalog]),
                                              "chapter": st.column_config.SelectboxColumn("Chapter", options=sorted({ch["name"] for m in catalog for ch in m["chapters"]})),
                                              "question_text": st.column_config.TextColumn("Question", width="large"),
                                              "rationale": st.column_config.TextColumn("Rationale", width="large")})
        select_all = st.form_submit_button("Select all questions")
        clear_all = st.form_submit_button("Clear all questions")
        save = st.form_submit_button("Save review changes")
        commit = st.form_submit_button("Import selected questions", type="primary")
    selected_flags = [bool(value) for value in frame["include_in_next_step"]]
    current_rows = frame.drop(columns=["include_in_next_step", "question_number"]).fillna("").to_dict("records")
    for row, included in zip(current_rows, selected_flags):
        row[ROW_SELECTION_FIELD] = included
    if select_all or clear_all:
        for row in current_rows:
            row[ROW_SELECTION_FIELD] = bool(select_all)
        save_draft(course_id, selected, draft["raw_text"], current_rows)
        st.session_state[prefix+"revision"] = revision + 1
        st.session_state[notice_key] = "All questions selected." if select_all else "All questions held back."
        st.rerun()
    if save or commit:
        save_draft(course_id, selected, draft["raw_text"], current_rows)
        if save:
            st.session_state[notice_key] = "Review changes saved."
            st.rerun()
    included_rows = [row for row in current_rows if row_selected(row)]
    remaining_rows = [row for row in current_rows if not row_selected(row)]
    st.caption(f"{len(included_rows)} selected for the next step · {len(remaining_rows)} staying in this batch")
    validation = import_questions(draft["name"], included_rows, course_id, validate_only=True)
    if validation["errors"]:
        st.warning(f"{len(validation['errors'])} validation issues to resolve before importing. Row 2 is the first question.")
        with st.expander("Validation details", expanded=True):
            for error in validation["errors"]:
                st.write(error)
    elif save:
        st.success("Review changes saved. All required fields pass validation.")
    if commit:
        if not included_rows:
            st.warning("Select at least one question to import. Your edits have been saved.")
        elif not validation["errors"]:
            try:
                result = import_questions(
                    draft["name"], included_rows, course_id, queue_id=selected,
                    remaining_rows=remaining_rows,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                if result["errors"]:
                    st.error("Nothing was imported. " + " ".join(result["errors"]))
                else:
                    ending = (f"{len(remaining_rows)} unchecked questions remain in this batch."
                              if remaining_rows else "Batch complete.")
                    st.session_state[notice_key] = f"Imported {result['inserted']} questions; skipped {result['skipped_content']} duplicates. {ending}"
                    st.session_state.pop("ccrn_mock_shortages", None)
                    st.session_state[prefix+"revision"] = revision + 1
                    st.rerun()
