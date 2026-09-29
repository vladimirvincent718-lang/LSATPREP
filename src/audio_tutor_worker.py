"""Compatibility entry point for retired tutor workers. Never schedules or calls APIs."""
import sys
from pathlib import Path
from src import audio_tutors as tutors, database


def process_once():
    return False


def main(path):
    database.DB_PATH = Path(path)
    with tutors.store.connection() as c:
        tutors.disable_automation(c)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
