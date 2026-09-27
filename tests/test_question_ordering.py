from src.question_ordering import arrange_question_dependencies, references_previous_question


def _q(number, stimulus="Standalone question", course_id=1):
    return {
        "id": number,
        "course_id": course_id,
        "question_id": f"CC-{number:04d}",
        "stimulus": stimulus,
        "passage": "",
    }


def test_detects_common_previous_question_cues():
    assert references_previous_question(
        _q(2, "Using the data from the previous question, solve this.")
    )
    assert references_previous_question(
        _q(2, "Based on the question immediately above, solve this.")
    )
    assert not references_previous_question(_q(2, "Solve this self-contained question."))


def test_adds_missing_predecessor_and_keeps_requested_count():
    pool = [_q(1), _q(2, "Using the previous question, calculate the return."), _q(8)]
    result = arrange_question_dependencies([pool[1], pool[2]], pool, target_count=2)

    assert [question["id"] for question in result] == [1, 2]


def test_moves_existing_predecessor_directly_before_dependent():
    questions = [_q(8), _q(2, "Using the prior question, calculate the return."), _q(1)]
    result = arrange_question_dependencies(questions, questions)

    assert [question["id"] for question in result] == [8, 1, 2]


def test_preserves_multi_question_dependency_chain():
    pool = [
        _q(1),
        _q(2, "Use the previous question."),
        _q(3, "Based on the preceding question."),
        _q(9),
    ]
    result = arrange_question_dependencies([pool[2], pool[3], pool[0]], pool, target_count=3)

    assert [question["id"] for question in result] == [1, 2, 3]


def test_drops_broken_dependency_and_fills_with_safe_question():
    broken = _q(5, "Use the previous question.")
    safe = _q(9)
    result = arrange_question_dependencies([broken], [broken, safe], target_count=1)

    assert [question["id"] for question in result] == [9]


def test_never_links_across_courses():
    predecessor_elsewhere = _q(1, course_id=2)
    dependent = _q(2, "Use the previous question.", course_id=1)
    safe = _q(9, course_id=1)
    result = arrange_question_dependencies(
        [dependent], [dependent, predecessor_elsewhere, safe], target_count=1
    )

    assert [question["id"] for question in result] == [9]
