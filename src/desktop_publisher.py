"""Publish desktop StudyForge source to its existing Streamlit Cloud repository.

This module is deliberately usable only by the local desktop UI. GitHub
credentials stay with Git Credential Manager; no token enters Streamlit state.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping

import toml

from src.mobile_access import PUBLIC_APP_URL


ROOT = Path(__file__).resolve().parents[1]
GITHUB_OWNER = "vladimirvincent718-lang"
REPOSITORY_URL = f"https://github.com/{GITHUB_OWNER}/LSATPREP.git"
SOURCE_FOLDERS = ("src", "pages", "scripts", "assets")
SOURCE_SUFFIXES = frozenset({".py", ".js", ".css", ".html"})
MAX_SOURCE_FILES = 500
MAX_SOURCE_BYTES = 2_000_000
_PUBLISH_LOCK = threading.Lock()


class PublishError(RuntimeError):
    """An actionable publishing failure suitable for the desktop UI."""


def is_local_publish_session(headers: Mapping[str, str], *, platform: str | None = None) -> bool:
    """Only an actual loopback browser session on Windows can publish."""
    if (platform or sys.platform) != "win32":
        return False
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    host = normalized.get("host", "").lower()
    if not re.fullmatch(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?", host):
        return False
    return not any(key.startswith("x-forwarded-") for key in normalized)


def _command(args: list[str], *, cwd: Path = ROOT, timeout: int = 60) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Publishing must use the already-connected account. The dedicated Connect
    # action is the only place where an interactive GitHub login is allowed.
    env["GCM_INTERACTIVE"] = "never"
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError("Git could not finish. Check your connection and try again.") from exc
    if result.returncode:
        if "non-fast-forward" in result.stderr or "fetch first" in result.stderr:
            raise PublishError("The online repository changed while publishing. Click Publish update again.")
        raise PublishError("GitHub did not accept this update. Reconnect GitHub, then try again.")
    return result.stdout.strip()


def github_connected() -> bool:
    """Check the GCM account list without retrieving or exposing credentials."""
    try:
        output = _command(["git", "credential-manager", "github", "list"], timeout=8)
    except PublishError:
        return False
    return GITHUB_OWNER.lower() in output.lower()


def connect_github() -> None:
    """Open Git Credential Manager's browser login once on the desktop."""
    try:
        result = subprocess.run(
            ["git", "credential-manager", "github", "login", "--username", GITHUB_OWNER, "--browser"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError("GitHub sign-in did not finish. Try Connect GitHub again.") from exc
    if result.returncode or not github_connected():
        raise PublishError("GitHub sign-in did not finish for the publishing account.")


def _safe_source_files(root: Path) -> dict[str, Path]:
    """Select code paths only; exclude the local database, media and secrets."""
    selected: dict[str, Path] = {}
    root = root.resolve()
    for folder in SOURCE_FOLDERS:
        base = root / folder
        if not base.is_dir() or base.is_symlink():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise PublishError("A source link points outside this project. Remove it before publishing.")
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise PublishError(f"Source file is too large to publish: {path.relative_to(root)}")
            selected[path.relative_to(root).as_posix()] = path
    for name in ("app.py", "requirements.txt"):
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise PublishError(f"Required source file is missing: {name}")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise PublishError(f"Source file is too large to publish: {name}")
        selected[name] = path
    if len(selected) > MAX_SOURCE_FILES:
        raise PublishError("Too many source files to publish safely.")
    for name, path in selected.items():
        if name.endswith(".py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=name)
            except (UnicodeError, SyntaxError) as exc:
                raise PublishError(f"Fix Python syntax before publishing: {name}") from exc
    return selected


def _copy_source(root: Path, checkout: Path) -> list[str]:
    selected = _safe_source_files(root)
    for folder in SOURCE_FOLDERS:
        base = checkout / folder
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
                    relative = path.relative_to(checkout).as_posix()
                    if relative not in selected:
                        path.unlink()
    for relative, source in selected.items():
        destination = checkout / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = source.read_text(encoding="utf-8").replace("\r\n", "\n")
        except UnicodeError as exc:
            raise PublishError(f"Source file is not UTF-8 text: {relative}") from exc
        normalized = content.encode("utf-8")
        if destination.is_file() and destination.read_bytes().replace(b"\r\n", b"\n") == normalized:
            continue
        destination.write_bytes(normalized)

    # Desktop networking options would break Streamlit Cloud. Publish the
    # visual/client settings while omitting the desktop-only server section.
    local_config = root / ".streamlit" / "config.toml"
    if local_config.is_file() and not local_config.is_symlink():
        try:
            config = toml.loads(local_config.read_text(encoding="utf-8"))
        except (UnicodeError, toml.TomlDecodeError) as exc:
            raise PublishError("Fix the desktop .streamlit/config.toml before publishing.") from exc
        config.pop("server", None)
        destination = checkout / ".streamlit" / "config.toml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(toml.dumps(config), encoding="utf-8")
    return list(selected)


def publish_update(*, root: Path = ROOT, repository_url: str = REPOSITORY_URL) -> tuple[str, int]:
    """Upload current desktop code to main; Streamlit Cloud deploys that push."""
    if not _PUBLISH_LOCK.acquire(blocking=False):
        raise PublishError("An update is already publishing. Wait for it to finish.")
    try:
        return _publish_update_locked(root=root, repository_url=repository_url)
    finally:
        _PUBLISH_LOCK.release()


def _publish_update_locked(*, root: Path, repository_url: str) -> tuple[str, int]:
    root = root.resolve()
    if not github_connected():
        raise PublishError("Connect GitHub on this computer before publishing.")
    with tempfile.TemporaryDirectory(prefix="studyforge-publish-") as temporary:
        checkout = Path(temporary) / "checkout"
        _command(["git", "clone", "--quiet", "--depth", "1", "--branch", "main", repository_url, str(checkout)], timeout=120)
        _copy_source(root, checkout)
        _command(["git", "add", "-A"], cwd=checkout)
        changes = _command(["git", "diff", "--cached", "--name-only"], cwd=checkout).splitlines()
        allowed_roots = tuple(folder + "/" for folder in SOURCE_FOLDERS)
        if any(
            name not in {"app.py", "requirements.txt", ".streamlit/config.toml"}
            and not (name.startswith(allowed_roots) and Path(name).suffix.lower() in SOURCE_SUFFIXES)
            for name in changes
        ):
            raise PublishError("The update contains an unexpected file. Nothing was uploaded.")
        if not changes:
            return "", 0
        _command(
            ["git", "-c", f"user.name={GITHUB_OWNER}", "-c", "user.email=vladimir.vincent718@gmail.com",
             "commit", "--quiet", "-m", "Publish StudyForge desktop update"],
            cwd=checkout,
        )
        commit = _command(["git", "rev-parse", "HEAD"], cwd=checkout)
        _command(["git", "push", "--quiet", "origin", "HEAD:refs/heads/main"], cwd=checkout, timeout=180)
        remote = _command(["git", "ls-remote", "origin", "refs/heads/main"], cwd=checkout, timeout=30)
        if not remote.startswith(commit + "\t"):
            raise PublishError("GitHub did not confirm the new version. Check the repository before retrying.")
        return commit, len(changes)


def render_publish_controls() -> None:
    """Render the local-only admin controls within the Settings page."""
    import streamlit as st

    st.markdown("#### Publish app updates")
    st.caption("Upload the latest app code from this computer to your existing phone link. This uses no AI tokens. Your study database, uploads, and passwords stay on this computer.")
    connected = github_connected()
    if not connected:
        st.info("Connect GitHub once on this computer, then publish updates whenever you change the app.")
        if st.button("Connect GitHub", key="studyforge_connect_github"):
            try:
                with st.spinner("Finish signing in to GitHub in the browser window..."):
                    connect_github()
                st.success("GitHub connected. You can publish updates now.")
                st.rerun()
            except PublishError as exc:
                st.error(str(exc))
    else:
        st.success(f"GitHub connected as {GITHUB_OWNER}.")
    publish_column, unpublish_column = st.columns(2)
    with publish_column:
        publish_clicked = st.button("Publish update", key="studyforge_publish_update", type="primary", disabled=not connected)
    with unpublish_column:
        with st.popover("Unpublish online app", width="stretch"):
            st.markdown("**Take the Streamlit app off the internet**")
            st.write("Streamlit calls this **Delete app**. Complete the removal in your Streamlit account; opening these controls does not take the app offline.")
            st.warning("Removing the hosted app deletes its cloud uploads, progress and settings. Save anything you need from the online app first. Your desktop app, local files and GitHub repository are kept.")
            st.markdown("1. Open your Streamlit apps below and sign in.\n2. Find **LSATPREP · main · app.py**, open its **⋮** menu and choose **Delete**.\n3. Enter Streamlit's confirmation text and select **Delete** to take the link offline.")
            st.link_button("Open Streamlit removal controls", f"https://share.streamlit.io/?workspaceName={GITHUB_OWNER}", type="primary")
            st.caption("To put it online again, deploy LSATPREP / main / app.py in Streamlit. Publish update only updates the code; it does not recreate a deleted deployment.")
    if publish_clicked:
        try:
            with st.spinner("Checking and uploading the latest app code..."):
                commit, changed = publish_update()
            if changed:
                st.success(f"Uploaded {changed} changed source files (version {commit[:7]}). Streamlit is rebuilding the same link; refresh it in a minute or two.")
            else:
                st.info("The online app already has the same source files.")
        except PublishError as exc:
            st.error(str(exc))
    st.link_button("Open the live app", PUBLIC_APP_URL)
