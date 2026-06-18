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
            INSERT INTO exam_attempts (id) VALUES (1);
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
        database.save_answer(1, 101, "A", False, 1.0, False, 1)
        database.save_answer(1, 101, "B", True, 2.0, True, 1)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """SELECT COUNT(*), selected_answer, is_correct, is_flagged
               FROM user_answers
               WHERE attempt_id = 1 AND question_id = 101"""
        ).fetchone()
        conn.close()

        self.assertEqual(row, (1, "B", 1, 1))
        self.mock_review.assert_called_once()

    def test_completed_attempt_cannot_be_saved_as_draft(self):
        self.assertTrue(
            database.save_exam_draft(7, 1, "practice", None, {"exam_active": True})
        )
        database.complete_attempt(1, 1, 1, {"1": {}})

        self.assertFalse(
            database.save_exam_draft(7, 1, "practice", None, {"exam_active": True})
        )


if __name__ == "__main__":
    unittest.main()
