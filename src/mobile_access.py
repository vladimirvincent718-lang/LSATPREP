"""Home Wi-Fi links for the local StudyForge server."""
import socket

PUBLIC_APP_URL = "https://lsatprep-fppkbqtqmpdxg7jwlxvnho.streamlit.app/"
PORT = 8510


def phone_links() -> tuple[str, str]:
    """Return the current LAN address and a hostname fallback."""
    hostname_link = f"http://{socket.gethostname()}:{PORT}"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("192.0.2.1", 80))
            address = connection.getsockname()[0]
        return f"http://{address}:{PORT}", hostname_link
    except OSError:
        return "", hostname_link
