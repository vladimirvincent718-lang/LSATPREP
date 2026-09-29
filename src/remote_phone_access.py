"""A protected public link to the desktop StudyForge server.

The ngrok agent forwards requests to the *running desktop app*. No database or
uploads are copied to Streamlit Cloud or GitHub.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

from src.mobile_access import PORT


PRIVATE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "StudyForge" / "phone-access"
POLICY_PATH = PRIVATE_DIR / "ngrok-policy.json"
CREDENTIAL_PATH = PRIVATE_DIR / "phone-credential.json"
LOG_PATH = PRIVATE_DIR / "ngrok.log"
AUTOSTART_PATH = PRIVATE_DIR / "start-with-studyforge"
PID_PATH = PRIVATE_DIR / "ngrok.pid"
AGENT_API_PORTS = range(4040, 4051)


class PhoneAccessError(RuntimeError):
    """A message that can be shown in the local Settings page."""


def _ngrok() -> str:
    executable = shutil.which("ngrok")
    if not executable:
        raise PhoneAccessError("Install the ngrok app on this computer before starting live phone access.")
    return executable


def ngrok_is_configured() -> bool:
    """Check the agent's configuration without displaying its account token."""
    try:
        result = subprocess.run(
            [_ngrok(), "config", "check"], capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (PhoneAccessError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def connect_ngrok(token: str) -> None:
    """Save the user's agent token with the official ngrok CLI."""
    token = token.strip()
    if not token or any(character.isspace() for character in token):
        raise PhoneAccessError("Paste the complete ngrok authtoken from your dashboard.")
    try:
        result = subprocess.run(
            [_ngrok(), "config", "add-authtoken", token],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhoneAccessError("ngrok could not save the account connection.") from exc
    if result.returncode or not ngrok_is_configured():
        raise PhoneAccessError("ngrok did not accept that authtoken. Copy it again from the dashboard.")


def _agent_tunnels() -> list[dict]:
    tunnels = []
    for port in AGENT_API_PORTS:
        api = f"http://127.0.0.1:{port}/api/tunnels"
        try:
            with urllib.request.urlopen(api, timeout=0.2) as response:
                payload = json.load(response)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            for tunnel in payload.get("tunnels", []):
                tunnels.append({**tunnel, "_agent_api": api})
    return tunnels


def live_phone_url() -> str:
    """Return only an HTTPS endpoint forwarding to this app's local port."""
    for tunnel in _agent_tunnels():
        target = str((tunnel.get("config") or {}).get("addr", ""))
        url = str(tunnel.get("public_url", ""))
        if url.startswith("https://") and target.rstrip("/").endswith(f":{PORT}"):
            return url
    return ""


def phone_access_password() -> str:
    try:
        record = json.loads(CREDENTIAL_PATH.read_text(encoding="utf-8"))
        return str(record.get("password", ""))
    except (OSError, ValueError):
        return ""


def _ensure_policy() -> None:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    password = phone_access_password()
    if not password:
        password = secrets.token_urlsafe(30)
        CREDENTIAL_PATH.write_text(
            json.dumps({"username": "studyforge", "password": password}), encoding="utf-8"
        )
    policy = {
        "on_http_request": [{"actions": [{"type": "basic-auth", "config": {
            "realm": "StudyForge phone access",
            "credentials": [f"studyforge:{password}"],
            "enforce": True,
        }}]}]
    }
    POLICY_PATH.write_text(json.dumps(policy), encoding="utf-8")


def _desktop_is_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_stcore/health", timeout=2) as response:
            return response.read() == b"ok"
    except OSError:
        return False


def start_live_phone_access() -> str:
    """Start one protected tunnel and return its public HTTPS URL."""
    existing = live_phone_url()
    if existing:
        AUTOSTART_PATH.touch()
        return existing
    if not _desktop_is_running():
        raise PhoneAccessError("Start StudyForge on this computer first.")
    if not ngrok_is_configured():
        raise PhoneAccessError("Connect your ngrok account first.")
    _ensure_policy()
    with LOG_PATH.open("ab") as log:
        process = subprocess.Popen(
            [_ngrok(), "http", str(PORT), "--traffic-policy-file", str(POLICY_PATH),
             "--inspect=false"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    PID_PATH.write_text(str(process.pid), encoding="ascii")
    for _ in range(40):
        url = live_phone_url()
        if url:
            AUTOSTART_PATH.touch()
            return url
        if process.poll() is not None:
            break
        time.sleep(0.5)
    raise PhoneAccessError(
        "The secure phone link did not start. Check that your ngrok account is active and try again."
    )


def stop_live_phone_access() -> None:
    """Remove this app's endpoint through ngrok's local agent API."""
    AUTOSTART_PATH.unlink(missing_ok=True)
    for tunnel in _agent_tunnels():
        target = str((tunnel.get("config") or {}).get("addr", ""))
        name = str(tunnel.get("name", ""))
        if not name or not target.rstrip("/").endswith(f":{PORT}"):
            continue
        request = urllib.request.Request(f"{tunnel['_agent_api']}/{name}", method="DELETE")
        try:
            urllib.request.urlopen(request, timeout=5).close()
        except urllib.error.URLError as exc:
            raise PhoneAccessError("Could not turn off the phone link. Try again.") from exc
    _stop_managed_agent()


def _stop_managed_agent() -> None:
    try:
        pid = int(PID_PATH.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return
    PID_PATH.unlink(missing_ok=True)
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        command = result.stdout.strip().lower()
        if result.returncode == 0 and "ngrok" in command and str(POLICY_PATH).lower() in command:
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.TimeoutExpired):
        pass


def should_start_with_studyforge() -> bool:
    """Remember the user's choice to enable the link on future app starts."""
    return AUTOSTART_PATH.is_file() and CREDENTIAL_PATH.is_file()
