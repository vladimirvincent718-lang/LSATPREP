import sqlite3

from src.app_status import (
    DeploymentStatus,
    backup_receipt,
    create_database_backup,
    deployment_caption,
)


def test_create_database_backup_is_consistent_and_dated(tmp_path):
    db_path = tmp_path / "source.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, created_at TEXT)"
    )
    connection.execute(
        "INSERT INTO events (created_at) VALUES ('2026-07-10 17:45:12')"
    )
    connection.commit()
    connection.close()

    backup = create_database_backup(db_path)

    backup_path = tmp_path / backup.database_filename
    backup_path.write_bytes(backup.data)
    restored = sqlite3.connect(backup_path)
    assert restored.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    restored.close()
    assert backup.database_filename.startswith("studyforge_backup_")
    assert backup.database_filename.endswith(".db")
    assert len(backup.sha256) == 64
    assert backup.latest_activity_at is not None

    receipt = backup_receipt(
        backup,
        DeploymentStatus(commit="1234567890abcdef", committed_at=None),
    )
    assert backup.database_filename in receipt
    assert backup.sha256 in receipt
    assert "1234567890abcdef" in receipt


def test_deployment_caption_and_receipt_show_auditable_version():
    status = DeploymentStatus(
        commit="1234567890abcdef",
        committed_at=None,
        has_local_changes=True,
    )
    caption = deployment_caption(status)
    assert "version 1234567" in caption
    assert "local changes pending" in caption
