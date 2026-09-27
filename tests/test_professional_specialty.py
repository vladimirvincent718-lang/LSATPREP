from src import database
import pytest


@pytest.fixture(autouse=True)
def isolated_lens_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'lens_registry.db')
from src.professional_specialty import (
    DEFAULT_SPECIALTY,
    normalize_specialty,
    professional_context_cue,
    specialty_label,
)


def test_specialty_values_are_normalized_and_labeled():
    assert normalize_specialty("restaurant_hospitality") == "restaurant_hospitality"
    assert normalize_specialty("not-a-specialty") == DEFAULT_SPECIALTY
    assert specialty_label("fitness_wellness") == "Fitness & Wellness"


def test_context_cue_is_professional_and_module_aware():
    cue = professional_context_cue(
        "restaurant_hospitality",
        "Financial Statement Analysis",
    )
    assert "restaurant" in cue.lower()
    assert "financial statements" in cue.lower()
    assert professional_context_cue(DEFAULT_SPECIALTY, "Economics") == ""


def test_professional_specialty_setting_defaults_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "specialty.db")
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

    assert database.get_setting(1, "professional_specialty") == DEFAULT_SPECIALTY
    database.set_setting(1, "professional_specialty", "technology_saas")
    assert database.get_all_settings(1)["professional_specialty"] == "technology_saas"
