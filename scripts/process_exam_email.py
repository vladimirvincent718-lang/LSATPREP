"""Run only on the app host with its configured dedicated mailbox."""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.offline_email import poll_mailbox

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        try:
            print(f'Processed {poll_mailbox()} exam submissions.', flush=True)
        except Exception:
            print('Mailbox processing failed; verify IMAP and SMTP configuration. No credentials are logged.', flush=True)
            if not args.watch:
                sys.exit(1)
        if not args.watch:
            break
        time.sleep(30)
