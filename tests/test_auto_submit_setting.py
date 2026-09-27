from src import database


def test_auto_submit_setting_defaults_off_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "auto_submit.db")
    conn = database.get_connection()
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            UNIQUE(user_id, key)
        );
        INSERT INTO users (id, username) VALUES (1, 'student');
        """
    )
    conn.commit()
    conn.close()

    assert database.get_setting(1, "auto_submit_answers") == "false"

    database.set_setting(1, "auto_submit_answers", "true")

    assert database.get_setting(1, "auto_submit_answers") == "true"
    assert database.get_all_settings(1)["auto_submit_answers"] == "true"

