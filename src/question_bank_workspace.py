"""Subject-scoped bank planning and paste imports for ordinary courses."""

import io
import json
from collections import Counter

import pandas as pd
import streamlit as st

from src import database
from src.mock_exam_combinations import non_overlapping_mock_exams
from src.question_loader import load_csv, process_upload


def ensure_subject_catalog(course_id, course_title):
    """Reuse the durable batch pipeline with a separate catalog for each course."""
    from src.neonatal_ccrn import ensure_schema_and_catalog, get_catalog
    ensure_schema_and_catalog()
    plan = get_plan(course_id)
    names = list(dict.fromkeys(
        [m['name'] for m in database.get_course_modules(course_id)]
        + [q['section_type'] for q in database.get_all_questions(course_id=course_id) if q.get('section_type')]
        + list(plan['targets']))) or [course_title]
    existing = {m['name'] for m in get_catalog(course_id)}
    for name in names:
        if name not in existing:
            add_catalog_entry(course_id, name, 'General')
    return get_catalog(course_id)


def add_catalog_entry(course_id, module, chapter):
    module, chapter = module.strip(), chapter.strip()
    if not module or not chapter:
        raise ValueError('Module and chapter names are required.')
    conn = database.get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO course_areas(course_id,name) VALUES (?, 'Question Bank')", (course_id,))
        area = conn.execute("SELECT id FROM course_areas WHERE course_id=? AND name='Question Bank'", (course_id,)).fetchone()[0]
        conn.execute('INSERT OR IGNORE INTO course_module_blueprints(course_id,area_id,name) VALUES (?,?,?)', (course_id,area,module))
        mid = conn.execute('SELECT id FROM course_module_blueprints WHERE course_id=? AND name=?', (course_id,module)).fetchone()[0]
        conn.execute('INSERT OR IGNORE INTO course_chapters(course_id,module_id,name) VALUES (?,?,?)', (course_id,mid,chapter))
        conn.commit()
    finally:
        conn.close()


def render_catalog_editor(course_id, catalog):
    st.subheader('Import modules and chapters')
    st.caption('These names become the paste tabs and chapter choices in the review pipeline. Add a chapter here when your source uses a new chapter name.')
    with st.form(f'bank_catalog_{course_id}'):
        module = st.text_input('Module name', value=catalog[0]['name'] if catalog else '')
        chapter = st.text_input('Chapter name', value='General')
        if st.form_submit_button('Add module / chapter'):
            try:
                add_catalog_entry(course_id, module, chapter)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun()


def render_ccrn_targets(course_id, catalog):
    plan = get_plan(course_id)
    st.subheader('Edit coverage targets')
    st.caption('Edit each module target and save. The bank target is their sum; exam allocations stay unchanged.')
    with st.form(f'bank_targets_{course_id}'):
        values = {m['name']: st.number_input(m['name'], min_value=0,
                  value=int(plan['targets'].get(m['name'], m['target_questions'])),
                  key=f"bank_target_{course_id}_{m['id']}") for m in catalog}
        if st.form_submit_button('Save coverage targets'):
            save_plan(course_id, values, plan['mock_size'])
            st.rerun()


def _settings_connection():
    conn = database.get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS question_bank_plans (
        course_id INTEGER PRIMARY KEY REFERENCES courses(id),
        module_targets TEXT NOT NULL DEFAULT '{}',
        mock_size INTEGER NOT NULL DEFAULT 150
    )""")
    conn.commit()
    return conn


def get_plan(course_id):
    conn = _settings_connection()
    try:
        row = conn.execute("SELECT * FROM question_bank_plans WHERE course_id=?", (course_id,)).fetchone()
        return {"targets": json.loads(row["module_targets"]), "mock_size": row["mock_size"]} if row else {
            "targets": {}, "mock_size": 150,
        }
    finally:
        conn.close()


def save_plan(course_id, targets, mock_size):
    if int(mock_size) < 1 or any(int(value) < 0 for value in targets.values()):
        raise ValueError("Targets must be nonnegative and mock size must be positive.")
    conn = _settings_connection()
    try:
        conn.execute("""INSERT INTO question_bank_plans(course_id, module_targets, mock_size)
            VALUES (?, ?, ?) ON CONFLICT(course_id) DO UPDATE SET
            module_targets=excluded.module_targets, mock_size=excluded.mock_size""",
                     (course_id, json.dumps({name: int(value) for name, value in targets.items()}), int(mock_size)))
        conn.commit()
    finally:
        conn.close()


def coverage_rows(questions, modules, targets):
    counts = Counter(str(q.get("section_type") or "").strip() or "Unassigned" for q in questions)
    names = list(dict.fromkeys([m["name"] for m in modules] + list(counts) + list(targets)))
    return [{"Module": name, "Actual": counts[name], "Target": targets.get(name, 0),
             "Remaining": max(targets.get(name, 0) - counts[name], 0)} for name in names]


def plan_batch(rows, batch_size):
    """Allocate no more than the remaining targets; rounding conserves the batch."""
    remaining = sum(row["Remaining"] for row in rows)
    amount = min(int(batch_size), remaining)
    if not remaining:
        return []
    shares = [amount * row["Remaining"] / remaining for row in rows]
    counts = [int(value) for value in shares]
    order = sorted(range(len(rows)), key=lambda i: shares[i] - counts[i], reverse=True)
    for i in order[:amount - sum(counts)]:
        counts[i] += 1
    return [{**row, "Next Questions": count} for row, count in zip(rows, counts)]


def render_subject_workspace(course_id, course_title, user_id, admin, dashboard, coverage, imports):
    prefix = f"qbm_subject_{course_id}"
    catalog = ensure_subject_catalog(course_id, course_title)
    plan = get_plan(course_id)
    questions = database.get_all_questions(course_id=course_id)
    from src.question_lenses import question_lens, get_lenses
    lens = st.session_state.get('b_lens', 'all')
    total_questions = len(questions)
    lens_counts = Counter(question_lens(q) for q in questions)
    if lens != 'all':
        questions = [q for q in questions if question_lens(q) == lens]
    rows = coverage_rows(questions, catalog, plan["targets"])
    actual = len(questions)
    target = sum(plan["targets"].values())
    with dashboard:
        st.subheader(f"{course_title} · Question Bank")
        lens_labels = get_lenses()
        st.caption("Bank by lens: " + " · ".join(f"{lens_labels.get(key, key)}: {count:,}" for key, count in sorted(lens_counts.items())))

        st.caption(f"{get_lenses().get(lens, 'All lenses')}: {actual:,} questions · All lenses: {total_questions:,}. Coverage targets apply to the whole subject.")
        metrics = st.columns(5)
        metrics[0].metric("Actual Questions", f"{actual:,}")
        metrics[1].metric("Target", f"{target:,}" if target else "Not set")
        metrics[2].metric("Completion", f"{actual / target * 100:.1f}%" if target else "—")
        metrics[3].metric("Remaining", f"{max(target - actual, 0):,}" if target else "—")
        metrics[4].metric(f"{plan['mock_size']}-Question Mock Capacity",
                          f"{non_overlapping_mock_exams(actual, plan['mock_size']):,} without repeats")
        st.caption("Mock capacity counts question sets by bank size; exam module and difficulty requirements may reduce availability.")
        if target:
            st.progress(min(actual / target, 1.0), text=f"{actual:,} / {target:,}")
        else:
            st.info("Set module targets in Coverage to track completion and plan the next import batch.")
        st.markdown("Use **Paste & Batch Import** to add questions and **Manage Questions** to browse and maintain this bank.")
        st.caption("Practice Mode remains available in the sidebar.")

    with coverage:
        st.subheader("Question Bank Coverage")
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.info("Add module names and targets below, or import questions to start this bank.")
        if admin:
            with st.expander("Bank targets and mock capacity settings", expanded=True):
                with st.form(prefix + "_plan"):
                    edited = st.data_editor(
                        pd.DataFrame([{"Module": r["Module"], "Target": r["Target"]} for r in rows],
                                     columns=["Module", "Target"]),
                        num_rows="dynamic", hide_index=True, key=prefix + "_targets",
                        column_config={"Target": st.column_config.NumberColumn(min_value=0, step=1, required=True),
                                       "Module": st.column_config.TextColumn(required=True)},
                    )
                    mock_size = st.number_input("Questions per mock (capacity estimate)", min_value=1,
                                                value=int(plan["mock_size"]), key=prefix + "_mock_size")
                    if st.form_submit_button("Save bank targets"):
                        try:
                            targets = {}
                            for row in edited.to_dict("records"):
                                name = str(row["Module"] or "").strip()
                                value = float(row["Target"])
                                if not name or name in targets or not value.is_integer():
                                    raise ValueError("Use unique module names and whole-number targets.")
                                targets[name] = int(value)
                            save_plan(course_id, targets, mock_size)
                        except (TypeError, ValueError) as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()

    with coverage:
        if admin:
            render_catalog_editor(course_id, catalog)

    with imports:
        if not admin:
            return
        st.subheader("Next Questions Needed")
        size = st.number_input("Planned batch size", min_value=1, value=150, key=prefix + "_batch")
        recommendations = plan_batch(rows, size)
        if recommendations:
            st.dataframe(pd.DataFrame(recommendations), hide_index=True, use_container_width=True)
            st.caption(f"Plan: {sum(r['Next Questions'] for r in recommendations):,} questions, capped at remaining module targets.")
        else:
            st.info("Set or increase module targets in Coverage to get a batch plan.")
        from src.ccrn_import_ui import render_import_workflow_overview, render_paste_queue
        render_import_workflow_overview(course_id)
        render_paste_queue(course_id, catalog, user_id)
