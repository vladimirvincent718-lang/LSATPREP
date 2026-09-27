import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import database


class SubmissionIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "submission.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE exam_attempts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER DEFAULT 7,
                course_id INTEGER,
                mode TEXT DEFAULT 'practice',
                section_type TEXT DEFAULT 'Mixed',
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                total_questions INTEGER DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                raw_score REAL DEFAULT 0,
                percent_correct REAL DEFAULT 0,
                section_scores_json TEXT
            );
            CREATE TABLE user_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                selected_answer TEXT,
                is_correct INTEGER DEFAULT 0,
                time_spent_seconds REAL DEFAULT 0,
                is_flagged INTEGER DEFAULT 0,
                section_number INTEGER DEFAULT 1
            );
            CREATE UNIQUE INDEX idx_user_answers_attempt_question_section
                ON user_answers(attempt_id, question_id, section_number);
            CREATE TABLE exam_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                attempt_id INTEGER NOT NULL UNIQUE,
                mode TEXT,
                course_id INTEGER,
                state_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY,
                course_id INTEGER,
                section_type TEXT,
                question_type TEXT,
                difficulty INTEGER
            );
            INSERT INTO courses (id, title) VALUES (5, 'Test Course');
            INSERT INTO questions
                (id, course_id, section_type, question_type, difficulty)
                VALUES (101, 5, 'Logical Reasoning', 'Test', 2);
            INSERT INTO exam_attempts (id, course_id) VALUES (1, 5);
            """
        )
        conn.commit()
        conn.close()

        def get_connection():
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            return connection

        self.connection_patch = patch.object(database, "get_connection", get_connection)
        self.review_patch = patch.object(database, "_update_question_review_state")
        self.mock_review = self.review_patch.start()
        self.connection_patch.start()

    def tearDown(self):
        self.connection_patch.stop()
        self.review_patch.stop()
        self.temp_dir.cleanup()

    def test_repeated_answer_save_updates_one_row(self):
        inserted = database.save_answer(1, 101, "A", False, 1.0, False, 1)
        updated = database.save_answer(1, 101, "B", True, 2.0, True, 1)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """SELECT COUNT(*), selected_answer, is_correct, is_flagged
               FROM user_answers
               WHERE attempt_id = 1 AND question_id = 101"""
        ).fetchone()
        conn.close()

        self.assertEqual(row, (1, "B", 1, 1))
        self.assertTrue(inserted)
        self.assertFalse(updated)
        self.mock_review.assert_called_once()

        conn = sqlite3.connect(self.db_path)
        submitted_at = conn.execute(
            "SELECT submitted_at FROM user_answers WHERE attempt_id = 1"
        ).fetchone()[0]
        conn.close()
        self.assertIsNotNone(submitted_at)

    def test_completed_attempt_cannot_be_saved_as_draft(self):
        self.assertTrue(
            database.save_exam_draft(7, 1, "practice", None, {"exam_active": True})
        )
        database.complete_attempt(1, 1, 1, {"1": {}})

        self.assertFalse(
            database.save_exam_draft(7, 1, "practice", None, {"exam_active": True})
        )

    def test_rollover_can_stamp_answer_and_completion_at_day_end(self):
        cutoff = "2026-09-05 03:59:59"
        database.save_answer(
            1, 101, "B", True, 2.0, False, 1, submitted_at=cutoff
        )
        database.complete_attempt(
            1, 1, 1, {"1": {}}, completed_at=cutoff
        )

        conn = sqlite3.connect(self.db_path)
        answer_time = conn.execute(
            "SELECT submitted_at FROM user_answers WHERE attempt_id = 1"
        ).fetchone()[0]
        completion_time = conn.execute(
            "SELECT completed_at FROM exam_attempts WHERE id = 1"
        ).fetchone()[0]
        conn.close()

        self.assertEqual(answer_time, cutoff)
        self.assertEqual(completion_time, cutoff)

    def test_active_practice_answer_can_be_included_in_daily_stats(self):
        database.save_answer(1, 101, "B", True, 2.0, False, 1)

        self.assertEqual(database.get_answer_stats(7), [])
        rows = database.get_answer_stats(7, include_in_progress_practice=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempt_id"], 1)
        self.assertEqual(rows[0]["is_correct"], 1)
        self.assertIsNotNone(rows[0]["completed_at"])

    def test_practice_report_details_use_the_same_date_and_owner_scope(self):
        database.save_answer(1, 101, "B", True, 2.0, False, 1,
                             submitted_at="2026-09-14 01:00:00")
        scope = dict(course_ids=[5], completed_from="2026-09-13 04:00:00",
                     completed_to="2026-09-14 04:00:00",
                     include_in_progress_practice=True)
        summary = database.get_answer_stats(7, **scope)
        details = database.get_answer_stats(7, **scope, include_answer_details=True)
        self.assertEqual(len(summary), len(details))
        self.assertEqual(details[0]["question_id"], 101)
        self.assertEqual(details[0]["selected_answer"], "B")
        self.assertIsNotNone(details[0]["answer_id"])
        self.assertEqual(database.get_answer_stats(8, **scope, include_answer_details=True), [])
        scope["completed_to"] = "2026-09-14 00:00:00"
        self.assertEqual(database.get_answer_stats(7, **scope, include_answer_details=True), [])

    def test_multiple_exam_drafts_can_be_listed_and_selected(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO exam_attempts (id, user_id, mode, course_id) VALUES (2, 7, 'curriculum_exam', 5)"
        )
        conn.commit()
        conn.close()

        self.assertTrue(
            database.save_exam_draft(
                7, 1, "curriculum_exam", 5, {"ceb_exam_source": "Exam One"}
            )
        )
        self.assertTrue(
            database.save_exam_draft(
                7, 2, "curriculum_exam", 5, {"ceb_exam_source": "Exam Two"}
            )
        )

        drafts = database.get_exam_drafts(7, modes={"curriculum_exam"})
        self.assertEqual({draft["attempt_id"] for draft in drafts}, {1, 2})
        selected = database.get_exam_draft(7, 1)
        self.assertEqual(selected["state"]["ceb_exam_source"], "Exam One")
        self.assertIsNone(database.get_exam_draft(99, 1))


if __name__ == "__main__":
    unittest.main()
