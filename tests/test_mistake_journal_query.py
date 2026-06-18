import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import database


class MistakeJournalQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "mistakes.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY, question_id TEXT, course_id INTEGER,
                stimulus TEXT, section_type TEXT, question_type TEXT,
                difficulty INTEGER, correct_answer TEXT, explanation TEXT,
                passage TEXT, choice_a TEXT, choice_b TEXT, choice_c TEXT,
                choice_d TEXT, choice_e TEXT, is_archived INTEGER DEFAULT 0
            );
            CREATE TABLE mistake_journal (
                id INTEGER PRIMARY KEY, user_id INTEGER, question_id INTEGER,
                attempt_id INTEGER, note TEXT, created_at TEXT,
                is_completed INTEGER DEFAULT 0, completed_at TEXT,
                review_order INTEGER
            );
            CREATE TABLE user_answers (
                id INTEGER PRIMARY KEY, attempt_id INTEGER, question_id INTEGER,
                selected_answer TEXT
            );
            INSERT INTO courses VALUES (1, 'Course');
            INSERT INTO questions
                (id, question_id, course_id, stimulus, section_type, question_type)
                VALUES (10, 'Q-10', 1, 'Question', 'Module', 'Multiple Choice');
            INSERT INTO questions
                (id, question_id, course_id, stimulus, section_type, question_type)
                VALUES (11, 'Q-11', 1, 'Question 2', 'Module', 'Multiple Choice');
            INSERT INTO mistake_journal
                (id, user_id, question_id, attempt_id, created_at)
                VALUES (167, 1, 10, 88, '2026-06-10 05:56:11');
            INSERT INTO mistake_journal
                (id, user_id, question_id, attempt_id, created_at)
                VALUES (168, 1, 11, 89, '2026-06-10 06:00:00');
            INSERT INTO user_answers VALUES (1, 88, 10, 'A');
            INSERT INTO user_answers VALUES (2, 88, 10, 'B');
            """
        )
        conn.commit()
        conn.close()

        def get_connection():
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            return connection

        self.connection_patch = patch.object(database, "get_connection", get_connection)
        self.connection_patch.start()

    def tearDown(self):
        self.connection_patch.stop()
        self.temp_dir.cleanup()

    def test_duplicate_legacy_answers_render_one_mistake(self):
        journal = database.get_mistake_journal(1, course_id=1)
        first_question_entries = [entry for entry in journal if entry["question_id"] == 10]

        self.assertEqual(len(first_question_entries), 1)
        self.assertEqual(first_question_entries[0]["id"], 167)
        self.assertEqual(first_question_entries[0]["selected_answer"], "B")

    def test_custom_review_order_is_persisted(self):
        database.set_mistake_journal_order(1, [167, 168])

        journal = database.get_mistake_journal(1, course_id=1)

        self.assertEqual([entry["id"] for entry in journal], [167, 168])

    def test_custom_review_order_rejects_another_users_entry(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO mistake_journal
               (id, user_id, question_id, attempt_id, created_at)
               VALUES (169, 2, 11, 90, '2026-06-10 06:05:00')"""
        )
        conn.commit()
        conn.close()

        with self.assertRaises(ValueError):
            database.set_mistake_journal_order(1, [167, 169])

    def test_review_query_self_heals_missing_order_column(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("ALTER TABLE mistake_journal RENAME TO mistake_journal_old")
        conn.execute(
            """CREATE TABLE mistake_journal (
                   id INTEGER PRIMARY KEY, user_id INTEGER, question_id INTEGER,
                   attempt_id INTEGER, note TEXT, created_at TEXT,
                   is_completed INTEGER DEFAULT 0, completed_at TEXT
               )"""
        )
        conn.execute(
            """INSERT INTO mistake_journal
               SELECT id, user_id, question_id, attempt_id, note, created_at,
                      is_completed, completed_at
               FROM mistake_journal_old"""
        )
        conn.execute("DROP TABLE mistake_journal_old")
        conn.commit()
        conn.close()

        journal = database.get_mistake_journal(1, course_id=1)

        self.assertEqual(len(journal), 2)
        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mistake_journal)")}
        conn.close()
        self.assertIn("review_order", columns)


if __name__ == "__main__":
    unittest.main()
