"""Publishing must be local, source-only, and update the existing branch."""

from pathlib import Path
import subprocess

import pytest

from src import desktop_publisher as publisher


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_publish_button_is_desktop_loopback_only():
    assert publisher.is_local_publish_session({"Host": "localhost:8510"}, platform="win32")
    assert publisher.is_local_publish_session({"host": "127.0.0.1:8510"}, platform="win32")
    assert not publisher.is_local_publish_session({"Host": "192.168.1.5:8510"}, platform="win32")
    assert not publisher.is_local_publish_session({"Host": "localhost:8510", "X-Forwarded-Host": "example.com"}, platform="win32")
    assert not publisher.is_local_publish_session({"Host": "localhost:8510"}, platform="linux")


def test_publish_copies_only_source_and_preserves_remote_database(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    local = tmp_path / "desktop"
    result = tmp_path / "result"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    _git(tmp_path, "clone", str(remote), str(seed))
    for folder in ("src", "pages", "scripts", "assets", "data", ".streamlit"):
        (seed / folder).mkdir()
    (seed / "app.py").write_text("print('old')\n", encoding="utf-8")
    (seed / "requirements.txt").write_text("streamlit\n", encoding="utf-8")
    (seed / "src" / "old.py").write_text("old = True\n", encoding="utf-8")
    (seed / "data" / "lsat_app.db").write_bytes(b"REMOTE_DATABASE")
    (seed / ".streamlit" / "config.toml").write_text('[theme]\nprimaryColor = "#111111"\n', encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "seed")
    _git(seed, "push", "origin", "main")

    for folder in ("src", "pages", "scripts", "assets", "data", ".streamlit"):
        (local / folder).mkdir(parents=True)
    (local / "app.py").write_text("print('new')\n", encoding="utf-8")
    (local / "requirements.txt").write_text("streamlit>=1.57\n", encoding="utf-8")
    (local / "src" / "new.py").write_text("new = True\n", encoding="utf-8")
    (local / "data" / "lsat_app.db").write_bytes(b"PRIVATE_DATABASE")
    (local / ".streamlit" / "config.toml").write_text(
        '[server]\naddress = "0.0.0.0"\nport = 8510\n[theme]\nprimaryColor = "#222222"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(publisher, "github_connected", lambda: True)
    commit, count = publisher.publish_update(root=local, repository_url=str(remote))
    assert len(commit) == 40
    assert count >= 3
    _git(tmp_path, "clone", str(remote), str(result))
    assert (result / "app.py").read_text(encoding="utf-8") == "print('new')\n"
    assert (result / "src" / "new.py").exists()
    assert not (result / "src" / "old.py").exists()
    assert (result / "data" / "lsat_app.db").read_bytes() == b"REMOTE_DATABASE"
    config = (result / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "primaryColor" in config
    assert "[server]" not in config


def test_invalid_python_blocks_publish(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "app.py").write_text("def invalid(:\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("streamlit\n", encoding="utf-8")
    with pytest.raises(publisher.PublishError, match="Fix Python syntax"):
        publisher._safe_source_files(tmp_path)
