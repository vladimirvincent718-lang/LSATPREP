"""Send due saved dashboard PDFs once; no credentials or addresses are logged."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dashboard_report_schedule import run_due_reports
from src.provider_reminders import run_due_requests

if __name__ == '__main__':
    results = run_due_reports() + run_due_requests()
    for user_id, status in results:
        print(f'User {user_id}: {status}', flush=True)
    if not results:
        print('No dashboard reports due.')
    sys.exit(1 if any(status != 'sent' for _, status in results) else 0)
