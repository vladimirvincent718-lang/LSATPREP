# Offline PDF exams

Start an exam, then open **Practice Mode > Offline exams: download, email, submit, and review**.
Each newly generated PDF is saved with a database-unique exam number, the exact question order,
and a frozen answer key. You can download that same file again after restarting the app.

New PDFs use a phone-first half-letter page. The first page holds exam information; each regular
question then starts on its own page. Multiple-choice answers are presented once as large cards,
with a 24-point selection box beside the complete answer text. The former small A/B/C/D answer
strip is removed. Written answers and issue controls are enlarged as well. Exceptionally long
passages may continue onto another page rather than shrinking into unreadable text.

The default queue shows Outstanding exams only. A submitted PDF (uploaded manually or received
by email), or a linked attempt completed in the app, moves to Closed / submitted exams.
An active Practice Mode session checks completion on rerun so a remotely submitted attempt
does not stay open in that browser. A closed online attempt links to Score History.

Closed exams have a Delete this exam and its score control. Score History also offers deletion
for sessions without PDFs. Deleting removes the selected attempt's answers, score, study time,
PDF, self-assessment, and reply authorization. Question-bank content remains. Affected review
statistics are replayed from remaining answers with their original timestamps; a mistake shared
with another attempt remains associated with that other attempt. Deletion requires selecting
the particular exam and checking its permanent-deletion checkbox.

1. Download the PDF. If leaving an active online session, use Save and Exit to stop its timer.
2. Fill its answer fields offline and save the changed file. Do not print to PDF or flatten it.
3. Return to Offline exams, select the matching exam number, and upload the saved PDF.
4. Review the extracted answers, self-grade any written responses, and submit for grading.

Unanswered scored questions count as incorrect. Results and issue notes are saved; results also
appear in score history, and answered mistakes go to the mistake journal. Offline durations
are recorded as zero because time spent outside the app cannot be measured.

Practice PDF drafts do not expire at midnight. Take-home exams also receive saved attempts.
Practice, timed-section, and curriculum PDFs submit to the original attempt. A whole full-exam
PDF spans online section attempts and therefore receives a separate offline attempt when
submitted; experimental sections do not count toward its score.

The importer rejects missing or mismatched exam numbers, missing answer widgets, invalid choices,
and another account's exam. Completed online scores cannot be overwritten. Repeated offline
submissions return the original result. Database writes are transactional.

Older PDFs without exam numbers, scans, and flattened copies cannot be imported. Generate a
new PDF for this workflow. The identifier prevents accidental mismatches; it is not a digital
signature or a proctored-exam security mechanism.

Scores are practice accuracy, not validated predictions of licensing-exam results.

## Self-grading

Choose **Self-grade with checkboxes**. Each Correct checkbox updates the displayed score.
Uncheck Include in score to exclude specific questions; removing ten out of fifty changes the
denominator to forty. Save self-assessment preserves your choices for later. This is a separate
self-assessment and does not overwrite an automatic result or change official answer history.
The old result grid is now a read-only table with explicit Correct / Incorrect / Unanswered labels.
An entirely blank upload is stopped before the UI or email processor submits it.

## Offline calculations in the PDF

Expand **PDF with offline automatic scoring** to prepare an optional scoring copy. It includes
the answer key and an Acrobat calculation field on page one. In a reader that supports Acrobat
JavaScript with calculations enabled, the score updates when answers change. Written responses
and experimental questions are not included. The default field text says JavaScript is required
so an unsupported reader does not misleadingly display a calculated zero. Server grading ignores
the PDF's score field and checks the frozen answer key independently.

## Email delivery and incoming submissions

Enter any valid recipient address and click Save email address, or Email this exam (which also
saves the address after successful delivery). The profile address is reused for future exams.
Subjects use `[StudyForge] Course | EX-serial | Exam PDF`; grading replies use the same course
and serial with `Grading result`. Exam messages also include a private reply token in the subject.
Keep that token when replying and do not forward it to others.

Configure outgoing SMTP in **Settings > Email Delivery**. Port 465 uses implicit TLS; other ports
can use STARTTLS. Receiving email requires a dedicated mailbox configured under **Settings >
Incoming exam submissions**: IMAP host, port (normally 993), username, password/app password,
and submission email address. Provider authentication policies still apply; recipient addresses
are not limited to the sending/receiving mailbox's provider.

On the app host, run `python scripts/process_exam_email.py --watch` to check for replies every
30 seconds. Keep that process and the host running to grade while the browser is closed.
Settings also offers Check exam inbox now. Configuring a mailbox does not install or start a
background service. Environment overrides use `STUDYFORGE_EXAM_IMAP_HOST`,
`STUDYFORGE_EXAM_IMAP_PORT`, `STUDYFORGE_EXAM_IMAP_USERNAME`,
`STUDYFORGE_EXAM_IMAP_PASSWORD`, and `STUDYFORGE_EXAM_REPLY_ADDRESS`.

Saving a recipient does not configure the sending account. Missing SMTP host, port, or From email
is shown before sending, and Email this exam is disabled until those required fields are configured.

Reply from the original recipient address with exactly one completed PDF. The processor checks
the private reply token, sender, ownership, PDF serial, and fields, then submits once and emails
the practice score. Written responses require self-grading in the app. Failed result-email
delivery is retried without regrading; as with SMTP generally, a connection loss after delivery
can lead to a duplicate notification. Unrecognized messages are not graded or replied to.

Validation: `python -m pytest tests/test_offline_exams.py tests/test_offline_email.py tests/test_pdf_export.py tests/test_exam_draft_resume.py tests/test_submission_idempotency.py tests/test_practice_dashboard_toggle_regression.py tests/test_mock_exam_combinations.py -q`
