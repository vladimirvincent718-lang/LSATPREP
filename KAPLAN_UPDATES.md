# Kaplan update requests

Open **Kaplan Update** in StudyForge (or Practice Mode → External practice).

1. Paste My Quizzes history and import it. Overlapping quizzes are merged without duplicating daily counts.
2. Select **History complete through** and confirm that the paste includes every completed quiz through that date. Only full days through yesterday can be confirmed. The next request begins the following day. Existing imports without this confirmation do not prove complete coverage; confirm coverage with the first update.
3. When there are no new quizzes, use **Confirm no new quizzes**. Existing counts remain unchanged.
4. Save the StudyForge app base address, email checkbox, and reminder interval. The email recipient and SMTP configuration come from Settings. A saved interval of 0 disables requests.

The existing `scripts/send_dashboard_reports.py` nightly runner now processes Kaplan requests as well as dashboard PDFs. The existing local StudyForge nightly automation runs it at 12:05 a.m. America/New_York. Delivery requires that runner and the computer to be available. No new scheduler is required. Each user must enable Kaplan emails in the app; changing code alone does not enable them.

The request links directly to `/Kaplan_Update`; sign-in happens on that page when needed. Links contain no credentials or user IDs. Request dates are computed when sending, and the submission page shows the current outstanding range even if an older email is opened.

Unfinished quizzes are skipped by the importer. A paste containing unfinished quizzes cannot advance confirmed coverage; import completed results without the coverage checkbox and include unfinished quizzes in a later update after completion. Dashboard dates remain the quiz timestamps displayed by Kaplan.

Requests recur every configured N days after the latest import or email attempt. Claims in `kaplan_request_deliveries` prevent simultaneous or repeated runs from sending duplicate requests. An uncertain SMTP outcome is recorded as `delivery_unconfirmed` and is not retried that day. The scheduler reports configuration or delivery failures without logging addresses or credentials.
