from streamlit.testing.v1 import AppTest

from src.practice_report import report_rows, summarize


ANSWERS = [
    dict(answer_id=1, attempt_id=10, question_id=100, is_correct=True,
         course_title="Course A", section_type="Module A", difficulty=2,
         selected_answer="A", completed_at="2026-09-14 01:00:00"),
    dict(answer_id=2, attempt_id=10, question_id=101, is_correct=False,
         course_title="Course B", section_type="Module B", difficulty=3,
         selected_answer="B", completed_at="2026-09-14 01:01:00"),
]
EXTERNAL = [dict(id=3, source="Kaplan", correct_count=7, incorrect_count=3,
                 entry_date="2026-09-13")]


def test_source_totals_reconcile_without_expanding_external_answers():
    rows = report_rows(ANSWERS, EXTERNAL)
    assert len(rows) == 3
    groups = summarize(rows, "Source")
    assert sum(g["Total"] for g in groups) == 12
    assert sum(g["Correct"] for g in groups) == 8
    assert sum(g["Incorrect"] for g in groups) == 4
    assert rows[-1]["Question ID"] is None
    assert summarize(rows[:2], "Course")[1]["Course"] == "Course B"


def report_app():
    import streamlit as st
    import src.practice_report as report
    from tests.test_practice_report import ANSWERS, EXTERNAL
    from datetime import date
    from unittest.mock import patch

    for metric in report.METRICS:
        st.button(metric, on_click=report.open_report, args=(metric,))
    with patch.object(report, "get_question_by_id", side_effect=lambda qid: dict(stimulus=f"Question {qid}", correct_answer="A", explanation="Because A.")):
        report.render_report(ANSWERS, EXTERNAL, [], 30, date(2026, 9, 13))


def test_metric_to_source_to_answer_and_reset():
    app = AppTest.from_function(report_app).run()
    assert not app.exception
    app.button[2].click().run()
    assert app.selectbox[0].value == "Incorrect"
    assert app.metric[0].value == "4"
    app.selectbox[1].select("StudyForge").run()
    assert app.metric[0].value == "1"
    app.selectbox[2].select("Course B").run()
    app.selectbox[3].select("Module B").run()
    app.selectbox[4].select("3").run()
    app.selectbox[-1].select("Answer 2 · Session 10").run()
    assert not app.exception
    assert any("Question 101" in m.value for m in app.markdown)
    app.button[0].click().run()
    assert app.metric[0].value == "12"
    assert app.selectbox[1].value is None
    app.button[5].click().run()
    assert app.metric[0].value == "0 seconds"
    assert not app.exception


def test_empty_report():
    app = AppTest.from_string('''
from src.practice_report import render_report
from datetime import date
render_report([], [], [], 30, date(2026, 9, 13))
''').run()
    assert not app.exception
    assert app.metric[0].value == "0"
    assert app.info[0].value == "No matching practice records today."


def test_explanation_report_shows_new_submissions():
    app = AppTest.from_string('''
import streamlit as st
from src.practice_report import render_report
from datetime import date
st.session_state["drill_report_metric"] = "Explanations"
render_report([], [], [], 30, date(2026, 9, 17), explanations=[
    dict(question_id=10, explanation="My reasoning", created_at="2026-09-17 12:00:00")])
''').run()
    assert not app.exception
    assert app.metric[0].value == "1"
    assert app.dataframe[0].value.iloc[0]["Explanation"] == "My reasoning"


def test_empty_explanation_report():
    app = AppTest.from_function(report_app).run()
    app.button[6].click().run()
    assert not app.exception
    assert app.metric[0].value == "0"
    assert app.info[0].value == "No new explanations submitted today."
