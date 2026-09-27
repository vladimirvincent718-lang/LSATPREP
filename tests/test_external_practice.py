from src import database


def _external_practice_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "external_practice.db")
    conn = database.get_connection()
    conn.execute(
        """CREATE TABLE users (
               id INTEGER PRIMARY KEY,
               username TEXT UNIQUE NOT NULL,
               password_hash TEXT NOT NULL
           )"""
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'learner', 'hash')"
    )
    conn.commit()
    conn.close()


def test_external_practice_upserts_daily_source_totals(monkeypatch, tmp_path):
    _external_practice_database(monkeypatch, tmp_path)

    database.save_external_practice_entry(1, "2026-08-22", "kaplan schweser", 4, 6)
    database.save_external_practice_entry(1, "2026-08-22", "Kaplan", 7, 3)

    entries = database.get_external_practice_entries(
        1,
        entry_from="2026-08-22",
        entry_to="2026-08-23",
    )
    assert entries == [
        {
            "id": entries[0]["id"],
            "entry_date": "2026-08-22",
            "source": "Kaplan",
            "correct_count": 7,
            "incorrect_count": 3,
            "total_count": 10,
            "updated_at": entries[0]["updated_at"],
        }
    ]
    assert database.get_external_practice_sources(1) == ["Kaplan"]


def test_external_practice_preserves_other_recurring_sources(monkeypatch, tmp_path):
    _external_practice_database(monkeypatch, tmp_path)

    database.save_external_practice_entry(1, "2026-08-22", "  CFA Institute  ", 2, 1)

    assert database.get_external_practice_sources(1) == ["Kaplan", "CFA Institute"]


def test_external_practice_entry_can_be_updated_and_deleted(monkeypatch, tmp_path):
    _external_practice_database(monkeypatch, tmp_path)
    database.save_external_practice_entry(1, "2026-08-23", "Quizlet", 112, 6)
    entry_id = database.get_external_practice_entries(1)[0]["id"]

    assert database.update_external_practice_entry(
        1, entry_id, "2026-08-22", "Quizlet", 110, 8
    )
    updated = database.get_external_practice_entries(1)[0]
    assert updated["entry_date"] == "2026-08-22"
    assert updated["correct_count"] == 110
    assert updated["incorrect_count"] == 8

    assert database.delete_external_practice_entry(1, entry_id)
    assert database.get_external_practice_entries(1) == []


def test_external_practice_edits_require_ownership(monkeypatch, tmp_path):
    _external_practice_database(monkeypatch, tmp_path)
    database.save_external_practice_entry(1, "2026-08-23", "Quizlet", 112, 6)
    entry_id = database.get_external_practice_entries(1)[0]["id"]

    assert not database.update_external_practice_entry(
        2, entry_id, "2026-08-22", "Quizlet", 112, 6
    )
    assert not database.delete_external_practice_entry(2, entry_id)
    assert database.get_external_practice_entries(1)[0]["entry_date"] == "2026-08-23"
