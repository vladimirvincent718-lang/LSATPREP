from src import database
from src.utils import question_course_title


def test_get_all_questions_includes_course_title(monkeypatch, tmp_path):
    db_path = tmp_path / "question_metadata.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_database()

    conn = database.get_connection()
    course_id = conn.execute(
        "INSERT INTO courses (title) VALUES (?)",
        ("CFA Level 1 Quantitative Methods",),
    ).lastrowid
    conn.execute(
        """INSERT INTO questions
           (question_id, course_id, section_type, question_type, difficulty, stimulus)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "CC-0209",
            course_id,
            "Learning Module 5: Portfolio Mathematics",
            "Multiple Choice",
            3,
            "What is annualized volatility?",
        ),
    )
    conn.commit()
    conn.close()

    questions = database.get_all_questions(course_id=course_id)

    assert len(questions) == 1
    assert questions[0]["course_title"] == "CFA Level 1 Quantitative Methods"
    assert question_course_title(questions[0]) == "CFA Level 1 Quantitative Methods"

    # Older saved sessions predate the joined course_title field. The UI still
    # resolves their course name from course_id when rendering the question.
    assert question_course_title({"course_id": course_id}) == "CFA Level 1 Quantitative Methods"
