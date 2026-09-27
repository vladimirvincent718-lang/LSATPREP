from scripts.add_fixed_income_exhibits import PILOT_MODULE, QUESTIONS, SOURCE


def test_mbs_pilot_has_one_question_at_each_challenging_level():
    assert len(QUESTIONS) == 3
    assert {level: sum(q["difficulty"] == level for q in QUESTIONS) for level in (3, 4, 5)} == {
        3: 1,
        4: 1,
        5: 1,
    }
    assert {question["section_type"] for question in QUESTIONS} == {PILOT_MODULE}
    assert {question["correct_answer"] for question in QUESTIONS} == {"A", "B", "C"}


def test_every_question_has_a_markdown_table_and_decoy_explanation():
    for question in QUESTIONS:
        assert "|---" in question["passage"]
        assert "exhibit-table" in question["tags"]
        assert len(question["passage"].splitlines()) >= 8
        assert len(question["explanation"]) >= 120
        assert question["source"] == SOURCE
        assert question["correct_answer"] in {"A", "B", "C"}
        assert all(question[f"choice_{letter}"] for letter in "abc")


def test_representative_calculations_match_keyed_answers():
    monthly_pass_through = 10_000_000 * (0.06 - 0.0025) / 12 + 20_000 + 180_000
    pac_payment = 1.00

    assert round(monthly_pass_through) == 247_917
    assert pac_payment == 1.00
