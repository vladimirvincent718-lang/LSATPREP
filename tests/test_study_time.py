from src import database


def _study_time_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "study_time.db")
    conn = database.get_connection()
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE exam_attempts (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            course_id INTEGER,
            mode TEXT
        );
        INSERT INTO users (id, username) VALUES (1, 'student'), (2, 'other');
        INSERT INTO courses (id, title) VALUES (10, 'CSK'), (20, 'Ethics');
        INSERT INTO exam_attempts (id, user_id, course_id, mode)
        VALUES (100, 1, 10, 'practice'), (200, 1, 20, 'practice');
        """
    )
    conn.commit()
    conn.close()


def test_study_time_accumulates_by_attempt_course_and_date(monkeypatch, tmp_path):
    _study_time_database(monkeypatch, tmp_path)

    database.add_study_time(1, 100, 10, 30.25, activity_date="2026-09-04")
    total = database.add_study_time(
        1, 100, 10, 29.75, activity_date="2026-09-04"
    )
    database.add_study_time(1, 200, 20, 120, activity_date="2026-09-04")
    database.add_study_time(1, 100, 10, 45, activity_date="2026-09-03")

    assert total == 60.0
    assert database.get_study_time_total(
        1,
        entry_from="2026-09-04",
        entry_to="2026-09-05",
        mode="practice",
    ) == 180.0
    assert database.get_study_time_total(
        1,
        entry_from="2026-09-04",
        entry_to="2026-09-05",
        course_id=10,
    ) == 60.0


def test_study_time_returns_a_daily_course_trail(monkeypatch, tmp_path):
    _study_time_database(monkeypatch, tmp_path)
    database.add_study_time(1, 100, 10, 60, activity_date="2026-09-03")
    database.add_study_time(1, 100, 10, 90, activity_date="2026-09-04")
    database.add_study_time(1, 200, 20, 30, activity_date="2026-09-04")

    rows = database.get_study_time_entries(
        1,
        entry_from="2026-09-03",
        entry_to="2026-09-05",
        mode="practice",
    )

    assert [(row["activity_date"], row["course_title"], row["active_seconds"]) for row in rows] == [
        ("2026-09-04", "CSK", 90.0),
        ("2026-09-04", "Ethics", 30.0),
        ("2026-09-03", "CSK", 60.0),
    ]

