"""Start StudyForge quietly for desktop and home Wi-Fi use."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.mobile_access import PORT, phone_links


def is_running():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_stcore/health", timeout=2) as response:
            return response.read() == b"ok"
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not is_running():
        log_dir = ROOT / "output"
        log_dir.mkdir(exist_ok=True)
        with (log_dir / "mobile_server.log").open("ab") as log:
            subprocess.Popen(
                [str(ROOT / ".venv/Scripts/python.exe"), "-m", "streamlit", "run",
                 str(ROOT / "app.py"), "--server.address=0.0.0.0",
                 f"--server.port={PORT}", "--server.headless=true"],
                cwd=ROOT, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        for _ in range(30):
            if is_running():
                break
            time.sleep(1)
        else:
            raise RuntimeError("StudyForge did not start. See output/mobile_server.log.")
    if not args.no_browser:
        webbrowser.open(f"http://localhost:{PORT}")
    if sys.stdout:
        print(phone_links()[0] or phone_links()[1])


if __name__ == "__main__":
    main()
