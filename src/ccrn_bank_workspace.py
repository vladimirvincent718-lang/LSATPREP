"""CCRN dashboard, coverage, imports and existing exam tools inside Question Bank Manager."""

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.ccrn_import_ui import render_import_workflow_overview, render_paste_queue
from src.exam_engine import (
    _st, clear_quiz, current_question, is_active, next_question, prev_question,
    record_answer, start_quiz, submit_section,
)
from src.neonatal_ccrn import (
    get_batch_history, get_catalog,
    get_coverage, get_performance, get_questions, import_questions,
    recommend_next_batch, select_mock_questions,
)
from src.mock_exam_combinations import (
    compact_combination_count, metric_drilldown_script,
    non_overlapping_mock_exams, possible_mock_exams,
)
from src.utils import DIFFICULTY_LABELS, render_question



def render_ccrn_workspace(course_id, user_id, admin, tabs):
    catalog = get_catalog(course_id)
    def _fmt_pct(value):
        return "—" if value is None else f"{float(value):.1f}%"


    def _difficulty_label(value):
        return "All difficulties" if value is None else f"{value} - {DIFFICULTY_LABELS[value]}"


    @st.dialog("Possible mock exam settings")
    def _mock_estimate_settings(actual_question_count):
        st.caption(f"The live question bank currently contains {actual_question_count:,} active questions.")
        estimated_default = max(int(st.session_state.get("ccrn_mock_estimated_bank_size", actual_question_count)), 1)
        mock_default = int(st.session_state.get("ccrn_mock_combination_size", min(150, max(estimated_default, 1))))
        if "ccrn_mock_estimated_bank_size" not in st.session_state:
            st.session_state["ccrn_mock_estimated_bank_size_input"] = estimated_default
        else:
            st.session_state.setdefault("ccrn_mock_estimated_bank_size_input", estimated_default)
        st.session_state.setdefault("ccrn_mock_combination_size_input", mock_default)
        with st.form("ccrn_mock_estimate_settings_form"):
            estimated_count = int(st.number_input(
                "Estimated total questions in bank", min_value=1, step=1,
                key="ccrn_mock_estimated_bank_size_input",
                help="Defaults to the current live question count. Change it to project future bank growth.",
            ))
            mock_size = int(st.number_input(
                "Questions in each mock", min_value=1, step=1,
                key="ccrn_mock_combination_size_input",
            ))
            save = st.form_submit_button("Update estimate", type="primary", use_container_width=True)
        report_possible = possible_mock_exams(estimated_count, mock_size)
        report_non_overlapping = non_overlapping_mock_exams(estimated_count, mock_size)
        st.divider()
        st.subheader("Estimate report")
        report_left, report_right = st.columns(2)
        report_left.metric("Mocks without reusing questions", f"{report_non_overlapping:,}")
        report_right.metric("All unique question combinations", compact_combination_count(report_possible))
        if report_possible >= 1_000_000_000_000:
            st.caption(
                f"The full combination total contains {len(str(report_possible))} digits. "
                "This counts different question sets; rearranging the same set does not create another mock."
            )
        else:
            st.caption(
                f"There are {report_possible:,} unique question sets. Rearranging the same set does not create another mock."
            )
        with st.expander("Show exact combination count"):
            st.code(f"{report_possible:,}")
        if save:
            if mock_size > estimated_count:
                st.error("Questions in each mock cannot exceed the estimated question count.")
            else:
                st.session_state["ccrn_mock_estimated_bank_size"] = estimated_count
                st.session_state["ccrn_mock_combination_size"] = mock_size
                st.rerun()
        if st.button("Reset question count to live bank", use_container_width=True):
            st.session_state.pop("ccrn_mock_estimated_bank_size", None)
            st.session_state["ccrn_mock_estimated_bank_size_input"] = actual_question_count
            if int(st.session_state.get("ccrn_mock_combination_size", 150)) > actual_question_count:
                st.session_state["ccrn_mock_combination_size"] = min(150, max(actual_question_count, 1))
                st.session_state["ccrn_mock_combination_size_input"] = st.session_state["ccrn_mock_combination_size"]
            st.rerun()


    def _start_questions(questions, mode, label, minutes=0, settings=None):
        start_quiz(
            user_id=user_id,
            questions=questions,
            mode=mode,
            section_type=label,
            time_limit_seconds=minutes * 60,
            hard_mode=False,
            course_id=course_id,
        )
        st.session_state["ccrn_session_kind"] = mode
        st.session_state.pop("ccrn_completed_report", None)
        st.rerun()


    def _render_active_session():
        questions = _st("questions") or []
        idx = int(_st("current_idx") or 0)
        answers = _st("answers") or {}
        mode = _st("mode") or "practice"
        label = "150-Question Full Mock" if mode == "neonatal_mock" else (_st("section_num") or "Practice")
        st.subheader(label)
        st.progress(len(answers) / len(questions) if questions else 0, text=f"{len(answers)}/{len(questions)} answered")
        left, middle, right = st.columns([1, 5, 1])
        with left:
            if st.button("◀ Previous", disabled=idx == 0, use_container_width=True):
                prev_question(); st.rerun()
        with middle:
            jump = st.selectbox("Question", range(len(questions)), index=idx,
                                format_func=lambda value: f"Question {value + 1}", label_visibility="collapsed")
            if jump != idx:
                st.session_state["exam_current_idx"] = jump; st.rerun()
        with right:
            if st.button("Next ▶", disabled=idx >= len(questions)-1, use_container_width=True):
                next_question(); st.rerun()
        q = current_question()
        if q:
            picked = render_question(q=q, idx=idx, total=len(questions), selected=answers.get(idx, ""), show_answer=False)
            if picked and picked != answers.get(idx, ""):
                record_answer(idx, picked)
            if st.button("Record & continue", type="primary", use_container_width=True):
                if not picked:
                    st.warning("Select an answer first.")
                else:
                    record_answer(idx, picked)
                    if idx < len(questions)-1: next_question()
                    st.rerun()
        st.divider()
        finish, quit_col = st.columns(2)
        if finish.button("Submit session", type="primary", use_container_width=True):
            report = submit_section(user_id)
            st.session_state["ccrn_completed_report"] = report
            clear_quiz()
            st.rerun()
        if quit_col.button("Quit session", use_container_width=True):
            clear_quiz(); st.rerun()


    if is_active() and _st("course_id") == course_id:
        _render_active_session()
        st.stop()

    completed = st.session_state.pop("ccrn_completed_report", None)
    if completed:
        st.success(f"Session complete: {completed['correct']} / {completed['total']} correct ({completed['percent_correct']}%).")

    coverage = get_coverage(course_id, user_id)
    performance = get_performance(user_id, course_id)
    from src.question_lenses import question_lens
    selected_lens = st.session_state.get('b_lens', 'all')
    dashboard_coverage = dict(coverage)
    if selected_lens != 'all':
        actual = sum(question_lens(q) == selected_lens for q in get_questions(course_id))
        dashboard_coverage.update(actual=actual, remaining=max(coverage['target']-actual, 0),
                                  completion=actual/coverage['target']*100 if coverage['target'] else 0)




    with tabs[0]:
        st.subheader("Question Bank")
        estimated_question_count = int(st.session_state.get("ccrn_mock_estimated_bank_size", dashboard_coverage["actual"]))
        questions_per_mock = int(st.session_state.get("ccrn_mock_combination_size", min(150, max(estimated_question_count, 1))))
        if questions_per_mock > estimated_question_count:
            questions_per_mock = min(150, max(estimated_question_count, 1))
            st.session_state["ccrn_mock_combination_size"] = questions_per_mock
        non_overlapping_count = non_overlapping_mock_exams(estimated_question_count, questions_per_mock)
        st.markdown("""<style>
        [data-testid="stColumn"]:has(#sf-mock-estimate-anchor) [data-testid="stButton"] { display: none !important; }
        [data-testid="stColumn"]:has(#sf-mock-estimate-anchor) [data-testid="stMetric"] { cursor: pointer; }
        </style>""", unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Actual Questions", f"{dashboard_coverage['actual']:,}")
        c2.metric("Target", f"{dashboard_coverage['target']:,}")
        c3.metric("Completion", f"{dashboard_coverage['completion']:.1f}%")
        c4.metric("Remaining", f"{dashboard_coverage['remaining']:,}")
        with c5:
            st.metric(f"{questions_per_mock}-Question Mock Capacity", f"{non_overlapping_count:,} without repeats",
                      help=f"Based on {estimated_question_count:,} estimated questions. Double-click for the complete combinations report and both estimate settings.")
            st.markdown('<span id="sf-mock-estimate-anchor"></span>', unsafe_allow_html=True)
            open_mock_settings = st.button("Open mock estimate settings", key="ccrn_open_mock_estimate_settings")
        components.html(metric_drilldown_script(), height=0, scrolling=False)
        if open_mock_settings:
            _mock_estimate_settings(int(dashboard_coverage["actual"]))
        st.progress(min(dashboard_coverage["completion"] / 100, 1.0), text=f"{dashboard_coverage['actual']:,} / {dashboard_coverage['target']:,}")

        st.subheader("Performance")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Questions Attempted", f"{performance['attempted']:,}")
        p2.metric("Overall Accuracy", _fmt_pct(performance["accuracy"]))
        p3.metric("Mocks Completed", performance["mocks_completed"])
        p4.metric("Average Mock Score", _fmt_pct(performance["average_mock"]))
        p5, p6, p7 = st.columns(3)
        p5.metric("Latest Mock Score", _fmt_pct(performance["latest_mock"]))
        p6.metric("Strongest Module", performance["strongest_module"] or "—")
        p7.metric("Weakest Module", performance["weakest_module"] or "—")

        st.subheader("Course Workspace")
        st.markdown(
            "Use **Exam Preparation** for a full mock, module or chapter practice. "
            "Use **Coverage** for live coverage and learner chapter statistics. "
            "Use **Paste & Batch Import** to import NotebookLM batches and inspect the dynamic **Next Questions Needed** plan."
        )

    with tabs[1]:
        exam_difficulty = st.selectbox(
            "Exam difficulty", [None, 1, 2, 3, 4, 5], index=5,
            format_func=_difficulty_label, key="ccrn_exam_difficulty",
            help="Applies to both full mocks and module/chapter practice. Stretch is level 5.",
            on_change=lambda: st.session_state.pop("ccrn_mock_shortages", None),
        )
        st.subheader("Full 150-question mock")
        mock_mode = st.selectbox("Mock type", ["Standard Mock", "Mostly New Questions", "Previously Incorrect", "Weak Areas", "Random Mock"])
        st.caption("Every type keeps the official 15 / 23 / 31 / 20 / 31 / 30 module allocation and never duplicates a question.")
        if st.button("Generate 150-question mock", type="primary", use_container_width=True):
            result = select_mock_questions(user_id, mock_mode, course_id, difficulty=exam_difficulty)
            if result["shortages"]:
                st.session_state["ccrn_mock_shortages"] = result["shortages"]
            else:
                _start_questions(result["questions"], "neonatal_mock", "Full 150-Question Mock", 180)
        shortages = st.session_state.get("ccrn_mock_shortages")
        if shortages:
            st.error(f"Mock exam cannot yet be generated at {_difficulty_label(exam_difficulty)} because these modules do not contain enough matching questions.")
            st.dataframe(pd.DataFrame(shortages).rename(columns={"module": "Module", "required": "Required", "available": "Available", "shortage": "Shortage"}),
                         hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("Module and chapter practice")
        module_by_id = {m["id"]: m for m in catalog}
        module_id = st.selectbox("Module", list(module_by_id), format_func=lambda value: module_by_id[value]["name"])
        chapter_options = {ch["id"]: ch for ch in module_by_id[module_id]["chapters"]}
        scope = st.radio("Scope", ["Entire module", "One chapter"], horizontal=True)
        chapter_id = None
        if scope == "One chapter":
            chapter_id = st.selectbox("Chapter", list(chapter_options), format_func=lambda value: chapter_options[value]["name"])
        available = get_questions(course_id, module_id=module_id, chapter_id=chapter_id, difficulty=exam_difficulty)
        st.caption(f"{len(available)} questions available · {_difficulty_label(exam_difficulty)}")
        requested = st.number_input("Questions", min_value=1, max_value=max(len(available), 1), value=min(10, max(len(available), 1)))
        if st.button("Start practice", use_container_width=True):
            if not available:
                st.warning("No questions match this module/chapter and difficulty. Choose another difficulty or import matching questions.")
            else:
                label = chapter_options[chapter_id]["name"] if chapter_id else module_by_id[module_id]["name"]
                _start_questions(available[:int(requested)], "practice", label, settings={"module_id": module_id, "chapter_id": chapter_id})

    with tabs[2]:
        if admin:
            from src.question_bank_workspace import render_ccrn_targets
            render_ccrn_targets(course_id, catalog)
        st.subheader("Question Bank Coverage")
        rows = [{"Module": m["name"], "Target": m["target_questions"], "Actual": m["actual"],
                 "Variance": m["variance"], "Remaining": m["remaining"], "Completion": f"{m['completion']:.1f}%"}
                for m in coverage["modules"]]
        rows.append({"Module": "TOTAL", "Target": coverage["target"], "Actual": coverage["actual"], "Variance": coverage["variance"],
                     "Remaining": coverage["remaining"], "Completion": f"{coverage['completion']:.1f}%"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        chapters_by_module = {}
        for chapter in coverage["chapters"]:
            chapters_by_module.setdefault(chapter["module_id"], []).append(chapter)
        for module in catalog:
            with st.expander(f"{module['name']} · {next((m['actual'] for m in coverage['modules'] if m['id']==module['id']), 0)} questions"):
                chapter_rows = []
                for ch in chapters_by_module.get(module["id"], []):
                    chapter_rows.append({"Group": ch["subgroup"] or "—", "Chapter": ch["name"], "Questions": ch["actual"],
                                         "% of Module": f"{ch['module_share']:.1f}%", "Attempted": ch["attempted"],
                                         "Correct": ch["correct"], "Accuracy": _fmt_pct(ch["accuracy"]),
                                         "Last Practiced": ch["last_practiced"] or "—"})
                st.dataframe(pd.DataFrame(chapter_rows), hide_index=True, use_container_width=True)

    with tabs[3]:
        if admin:
            render_import_workflow_overview(course_id)
        st.subheader("Next Questions Needed")
        batch_size = st.number_input("Planned batch size", min_value=1, value=150)
        recommendation = recommend_next_batch(int(batch_size), course_id)
        st.caption(f"Dynamic allocation based on current deficits. Recommendations total exactly {sum(r['recommended'] for r in recommendation)} questions.")
        st.dataframe(pd.DataFrame([{"Module": r["name"], "Current": r["actual"], "Target": r["target_questions"],
                                    "Desired After Batch": round(r["trajectory_target"], 1), "Current Deficit": r["remaining"],
                                    "Next Questions": r["recommended"]} for r in recommendation]),
                     hide_index=True, use_container_width=True)

        if admin:
            render_paste_queue(course_id, catalog, user_id)
        else:
            st.info("An administrator can import and manage CCRN question batches.")

    with tabs[4]:
        st.subheader("Question-bank filters")
        area_options = {m["area_id"]: m["area_name"] for m in catalog}
        f1, f2, f3, f4, f5 = st.columns(5)
        area_id = f1.selectbox("Area", [None, *area_options], format_func=lambda value: "All" if value is None else area_options[value])
        filtered_modules = [m for m in catalog if area_id is None or m["area_id"] == area_id]
        module_options = {m["id"]: m for m in filtered_modules}
        selected_module = f2.selectbox("Module", [None, *module_options], format_func=lambda value: "All" if value is None else module_options[value]["name"])
        chapter_options = {ch["id"]: ch for m in filtered_modules if selected_module in (None, m["id"]) for ch in m["chapters"]}
        selected_chapter = f3.selectbox("Chapter", [None, *chapter_options], format_func=lambda value: "All" if value is None else chapter_options[value]["name"])
        difficulty = f4.selectbox("Difficulty", [None, 1, 2, 3, 4, 5], format_func=_difficulty_label)
        batch_options = {batch["id"]: batch["name"] for batch in get_batch_history(course_id)}
        selected_batch = f5.selectbox("Batch", [None, *batch_options], format_func=lambda value: "All" if value is None else batch_options[value])
        s1, s2, s3 = st.columns(3)
        text_search = s1.text_input("Text / source")
        tag_search = s2.text_input("Tag")
        id_search = s3.text_input("Question ID")
        matching = get_questions(course_id, area_id=area_id, module_id=selected_module, chapter_id=selected_chapter,
                                 batch_id=selected_batch, difficulty=difficulty, search=text_search, tag=tag_search, question_id=id_search)
        st.metric("Matching Questions", len(matching))
        if matching:
            st.dataframe(pd.DataFrame([{"ID": q["question_id"], "Area": q["area_name"], "Module": q["module_name"],
                "Chapter": q["chapter_name"], "Difficulty": q["difficulty"], "Batch": q["batch_name"] or "—",
                "Question": q["stimulus"], "Tags": q["tags"]} for q in matching]), hide_index=True, use_container_width=True)
        else:
            st.info("No questions match these filters. Use Paste & Batch Import to add questions.")
