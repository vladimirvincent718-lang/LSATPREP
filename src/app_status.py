"""Deployment and database-backup status helpers for StudyForge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISPLAY_TIMEZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DeploymentStatus:
    """Git identity and, on desktop, the latest local source edit."""

    commit: str
    committed_at: datetime | None
    has_local_changes: bool = False
    local_source_modified_at: datetime | None = None

    @property
    def short_commit(self) -> str:
        return self.commit[:7] if self.commit else "unknown"


@dataclass(frozen=True)
class DatabaseBackup:
    """A consistent SQLite snapshot plus an auditable receipt."""

    data: bytes
    created_at: datetime
    latest_activity_at: datetime | None
    sha256: str

    @property
    def timestamp_slug(self) -> str:
        return self.created_at.strftime("%Y-%m-%d_%H%M%S_%Z")

    @property
    def database_filename(self) -> str:
        return f"studyforge_backup_{self.timestamp_slug}.db"

    @property
    def receipt_filename(self) -> str:
        return f"studyforge_backup_{self.timestamp_slug}_receipt.txt"


def _run_git(*args: str, root: Path = PROJECT_ROOT) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        check=True,
        text=True,
        timeout=3,
    )
    return completed.stdout.strip()


def _parse_timestamp(value: str | None, *, assume_utc: bool = False) -> datetime | None:
    if not value:
        return None
    normalized = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc if assume_utc else DISPLAY_TIMEZONE)
    return parsed.astimezone(DISPLAY_TIMEZONE)


def _latest_local_source_edit(root: Path = PROJECT_ROOT) -> datetime | None:
    """Inspect the same source paths the desktop publish button considers."""
    suffixes = {".py", ".js", ".css", ".html"}
    candidates = [root / "app.py", root / "requirements.txt", root / ".streamlit" / "config.toml"]
    for folder in ("src", "pages", "scripts", "assets"):
        base = root / folder
        if base.is_dir():
            candidates.extend(path for path in base.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)
    modified = [path.stat().st_mtime for path in candidates if path.is_file() and not path.is_symlink()]
    if not modified:
        return None
    return datetime.fromtimestamp(max(modified), tz=timezone.utc).astimezone(DISPLAY_TIMEZONE)


def get_deployment_status() -> DeploymentStatus:
    """Return Git revision, plus current source edit time on the desktop."""
    commit = (
        os.environ.get("STREAMLIT_GIT_COMMIT")
        or os.environ.get("GITHUB_SHA")
        or os.environ.get("COMMIT_SHA")
        or ""
    )
    committed_at = None
    has_local_changes = False
    local_source_modified_at = _latest_local_source_edit() if os.name == "nt" else None

    try:
        if not commit:
            commit = _run_git("rev-parse", "HEAD")
        committed_at = _parse_timestamp(
            _run_git("show", "-s", "--format=%cI", commit)
        )
        has_local_changes = bool(
            _run_git("status", "--porcelain", "--untracked-files=no")
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        committed_at = _parse_timestamp(os.environ.get("APP_DEPLOYED_AT"))

    return DeploymentStatus(
        commit=commit,
        committed_at=committed_at,
        has_local_changes=has_local_changes,
        local_source_modified_at=local_source_modified_at,
    )


def format_local_timestamp(value: datetime | None, *, include_seconds: bool = False) -> str:
    if value is None:
        return "Unknown"
    local = value.astimezone(DISPLAY_TIMEZONE)
    pattern = "%b %d, %Y at %I:%M:%S %p %Z" if include_seconds else "%b %d, %Y at %I:%M %p %Z"
    return local.strftime(pattern).replace(" 0", " ")


def deployment_caption(status: DeploymentStatus | None = None) -> str:
    status = status or get_deployment_status()
    if status.local_source_modified_at is not None:
        when = format_local_timestamp(status.local_source_modified_at)
        return f"Desktop source last edited {when} · Git baseline {status.short_commit}"
    when = format_local_timestamp(status.committed_at)
    caption = f"Online code published {when} · version {status.short_commit}"
    if status.has_local_changes:
        caption += " · local changes pending"
    return caption


def _latest_database_activity(connection: sqlite3.Connection) -> datetime | None:
    latest: datetime | None = None
    table_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (table_name,) in table_rows:
        columns = {
            row[1]
            for row in connection.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()
        }
        for column in ("updated_at", "completed_at", "created_at", "started_at"):
            if column not in columns:
                continue
            row = connection.execute(
                f'SELECT MAX("{column}") FROM "{table_name}"'
            ).fetchone()
            candidate = _parse_timestamp(row[0] if row else None, assume_utc=True)
            if candidate is not None and (latest is None or candidate > latest):
                latest = candidate
    return latest


def create_database_backup(db_path: str | Path) -> DatabaseBackup:
    """Create a transactionally consistent SQLite backup and checksum."""
    source_path = Path(db_path)
    created_at = datetime.now(timezone.utc).astimezone(DISPLAY_TIMEZONE)
    temporary_path: Path | None = None

    source = sqlite3.connect(str(source_path))
    try:
        latest_activity_at = _latest_database_activity(source)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        target = sqlite3.connect(str(temporary_path))
        try:
            source.backup(target)
        finally:
            target.close()
        data = temporary_path.read_bytes()
    finally:
        source.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return DatabaseBackup(
        data=data,
        created_at=created_at,
        latest_activity_at=latest_activity_at,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def backup_receipt(
    backup: DatabaseBackup,
    status: DeploymentStatus | None = None,
) -> str:
    status = status or get_deployment_status()
    committed_at = (
        status.committed_at.isoformat() if status.committed_at else "Unknown"
    )
    latest_activity = (
        backup.latest_activity_at.isoformat()
        if backup.latest_activity_at
        else "Unknown"
    )
    return "\n".join(
        [
            "StudyForge database backup receipt",
            f"Backup created: {backup.created_at.isoformat()}",
            f"Latest database activity: {latest_activity}",
            f"Code commit: {status.commit or 'Unknown'}",
            f"Code commit time: {committed_at}",
            f"Database filename: {backup.database_filename}",
            f"Database bytes: {len(backup.data)}",
            f"SHA-256: {backup.sha256}",
            "",
            "The SHA-256 value can be used to verify that the database file has not changed.",
        ]
    )
