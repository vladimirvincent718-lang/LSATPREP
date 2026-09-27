# Audio Study

Open **Course Materials → Audio Study**. Recordings are private unless the owner grants access to an existing StudyForge listener. Listening history and recall results remain personal.

## Upload and review

- Upload one or more MP3, WAV, M4A or OGG recordings (up to 200 MB per file). Each title defaults to the original filename and can be edited before saving. A batch saves together; validation failures preserve the selection and titles.
- Click or drag on the waveform to seek. Dragging also selects a range. **Add note at selection** immediately opens and focuses a bordered comment box within the player. **Save comment** shows a confirmation and adds the note to the list.
- Save a timestamped note with Neutral, Red, Yellow or Green status. Notes appear when playback reaches them, and clicking a saved note seeks to it.
- Edit notes and statuses under **Edit saved notes and statuses**.
- **Comment replay** on the right reveals comments and replies at their recording timestamps and keeps earlier comments visible. Seeking forward reveals comments up to that point; rewinding hides later comments until you reach them again. Use the arrow to collapse it against the right edge or reopen it. On phones it starts collapsed and opens as a right-side drawer. The browser remembers the panel preference.
- Click the time display beside the playback controls to cycle through elapsed time, time remaining, percent completed and percent remaining. Percentages use the current playback position divided by the track duration, shown to one decimal place. Rewinding updates all four views. The browser remembers the selected view, and switching it does not interrupt playback.
- Progress saves automatically every two seconds during playback, immediately on pause and after seeking. Green ends at the current position, moving backward as well as forward. Historical listening and furthest reach are retained separately. The saved position is restored when the recording is reopened. The player shows an explicit saving/saved indicator; no manual save button is needed. An abrupt browser shutdown can lose the last unsaved two-second batch.
- **Reply** below any comment opens a focused reply editor. Replies retain the original timestamp, show author and date, and can have further replies. Removing a parent preserves its replies. Listeners can edit their own comments; the recording owner can moderate the thread.
- **Invite a listener to this recording** grants access to an existing username enrolled in a covered course. Owners can remove access. Shared recordings appear in the listener’s Audio Library. This does not send email invitations.
- Each recording displays a total play count across its listeners. Actual playback in a new player visit or restarting from the beginning counts once; pausing/resuming, opening, seeking and retrying an event do not inflate it. Historical sessions with measured listening count once because older versions did not track individual starts. Analytics also shows your plays in the selected period.
- Listening Analytics separates processed progress (including seeking) from actual listening minutes and unique playback coverage. A complete listen covers at least 95% through actual playback within one session. Filter by the app's current review window or custom dates (UTC).

## Complete and incomplete

Each recording has a private, saved **Complete / Incomplete** marker and one-click **Mark complete / Mark incomplete** controls. Listening to at least 95% of its unique audio across visits completes it automatically; seeking alone does not. Existing listening history is included. A manual choice overrides automatic completion and stays saved during replay, rewinding and future visits. Marking complete does not create listening minutes, change the playback position or inflate measured coverage.

The recording chooser identifies completed items, and the library shows the completed count and percentage. Analytics includes completion status alongside measured listening. Shared recordings have separate completion states for each listener. Video cards in Course Materials offer a completion checkbox that updates the existing course-material progress totals; videos opened on external sites are marked manually because this app cannot observe their playback.

## Transcripts

The app generates transcripts automatically on this computer for newly uploaded recordings and existing recordings when opened. A background worker uses Faster Whisper's CPU model, downloads the model on first use, and saves recognized text and word timestamps in SQLite. Playback remains available while processing. Jobs are serialized to limit memory use, persist across app restarts, and never replace an attached transcript. Silence and transcription failures show a clear status with **Retry transcription** in **Transcript options**. Speech recognition can contain mistakes.

One transcript panel sits beside comment replay, beneath the compact waveform. **Navigate** seeks when you click a word, keeping the play/pause state. **Follow playback** scrolls to the current word in this mode. **Highlight** lets you drag across words, Shift-click the last word, or use Shift + arrow keys to select a passage without seeking. **Save highlight** persists a private yellow highlight; **My highlights** lets you revisit or remove it. **Comment on passage** uses the same selection and opens the comment editor; **Comment on selection** also works from Highlight mode. Comments show the selected words directly below their timestamp and keep the full quote when saved. Long quotes have a compact preview in the editor.

Passage comments retain the first word's start and last word's end, sort alongside point comments by start time, and appear in replay at their start. Replay marks them active throughout their range, and rewinding before the start hides them again. Commented words are underlined. Deliberately seeking or selecting new words updates an open comment editor's target while preserving the draft. Saving consumes the old selection and closes the editor; a new comment then starts at the current playback position. Ordinary playback leaves a draft's chosen target fixed.

**Flatten transcript** combines timestamped passages into a compact paragraph and shortens both transcript and replay panels. **Collapse transcript** hides its content to reach the comments quickly. Both layout preferences are remembered in the browser. Automatically recognized words use speech timestamps; legacy plain text uses clearly labeled estimated timing. **Copy transcript** copies the entire transcript in one click. **Download transcript (.txt)** is tucked into collapsed **Transcript options** and appears once text is available.

The transport provides play/pause, rewind/forward ten seconds, stop, volume and speed. The waveform is the only progress slider and supports arrow keys, Home and End. Each comment the listener can manage has a direct **× Delete comment** button, including in replay; removing a parent preserves its replies. The separate saved-note editing section has been removed.

## AI tutor conversations

**AI tutors · connections and response timing** in Audio Library configures two distinct profiles, **AI Tutor · Gemini** and **AI Tutor · ChatGPT**. Gemini is the default first responder; ChatGPT is the default optional reviewer. Select either as first responder and the other as reviewer, or choose **No automatic review**. Enter provider API keys in the password fields; the app stores them in Windows Credential Manager under a database-instance and user-specific namespace. Keys are not stored in SQLite, player payloads or logs. Automatic tutoring starts disabled and requires saving a key and explicitly enabling it. Developer API billing and quotas are separate from consumer Gemini/ChatGPT subscriptions. No live API calls are made by regression tests.

A **new comment is the help flag**: it opens a help ticket and schedules one answer plus at most one review. Existing comments from before this feature use **Request tutor help** to opt in. **Resolved / stop tutoring** cancels pending work and suppresses any in-flight output. **Reopen tutor help** or a new comment from the original requester starts a new revision. Other invited listeners cannot enable charges against the requester's account. Only human activity creates work; tutor messages never schedule replies or reviews. Threads stay quiet after their allotted answer and review until human activity resumes them. Reviewers post only for a meaningful possible error, omission or unresolved question, and are instructed to state uncertainty and distinguish transcript claims from factual accuracy. They have no external research tools; review is not guaranteed fact verification.

Reply delay is adjustable from 0 to 1,440 minutes. Review delay is adjustable from 0.25 to 168 hours after the latest human activity and waits for the first answer. Changing settings updates unstarted work. These are scheduled ordinary API calls, not discounted provider batch jobs; the delay sets when work becomes eligible, rather than guaranteeing delivery time. A rolling 24-hour call limit, default 20 and configurable from 1 to 100, counts started calls including failures and reviews. Each request also has bounded input, output and timeout. Errors and interrupted requests are terminal, with no automatic retry; resolve and reopen to request another attempt. The call cap is not a dollar spending cap and does not track consumer subscription limits.

One detached worker per SQLite database processes requests sequentially. It remains alive for scheduled work while the computer is awake, including after the browser closes. After shutdown or interruption, opening Audio Study resumes queued work. A filesystem lock prevents duplicate workers, and each job can publish only one reply. Background API requests already sent cannot be unbilled or necessarily cancelled by resolving a thread; their results are discarded. Missing keys block work without API usage. Removing a saved key or disabling tutoring also prevents an in-flight reply from being published.

**Tutor inbox** lists persisted unread replies across accessible recordings in the active course. **Open conversation** selects the recording, scrolls to the thread, and marks its replies read; **Mark replies read** is also available on the thread. Notifications are in-app, with no unsolicited email or desktop push. Profile labels identify reply authors, and supported timestamp citations jump to the recording.

The model receives the original question, up to 23 recent thread messages, the selected quote, and a bounded nearby passage when actual word or imported passage timings are available. Plain text is explicitly marked as unaligned and may be truncated; estimated player word positions are never passed as real transcript timestamps. **Include timestamps in copy** and **Include timestamps in download** independently control exports while preserving saved timings. These controls cannot manufacture accurate timestamps for older plain-text transcripts.

Checks: `python -m pytest tests/test_audio_tutors.py tests/test_tutor_providers.py tests/test_audio_study.py tests/test_audio_transcription.py tests/test_audio_progress_assignment.py tests/test_audio_upload.py` and `node tests/js/audio_tutors.test.mjs`. An isolated Streamlit fixture in `work/audio_tutors_preview.py` and Playwright checks in `work/verify_audio_tutors_ui.cjs` exercise the real player callbacks without touching the user's database or API accounts.

## Course coverage

Choose **Course overview**, **Modules**, or **Chapters** during upload. A course overview can cover one or several enrolled courses; module and chapter assignments accept multiple selections. The optional description does not determine assignment.

Use **Assign or change coverage for existing recordings** to update one recording or a batch. Files, comments and progress stay intact, and the same recording appears under every assigned course. Existing recordings initially become course overviews in their original course. Chapter selection uses the app's curriculum module and chapter catalog.

## Uploaded music and recall

The app does not generate music. Upload your own recording, then create a song set with lyrics and concept prompts, reference answers and keyword rubrics. Lyrics can be pasted or uploaded as TXT/LRC. LRC timestamps follow playback; plain lyrics support manual line highlighting.

Five levels provide full lyrics, masked keywords, masked lines, minimal prompts and recall without music. Scores concern concepts, not singing. Keyword coverage suggests a score using configured synonyms; learners confirm correctness against the reference answer, including formulas and relationships. This is not automated semantic grading.

Recall history persists responses, scores, durations, attempts and review dates. Weak concepts return sooner. Repeated successful attempts on the same day do not repeatedly advance the review stage.

Retention comparison randomly assigns concepts to music or standard study, then schedules the same non-musical prompts 1, 7 and 14 days after initial training. Tests stay unavailable until due and can be recorded only once per delay. This is a personal pilot, not proof of causality: self-grading, concept difficulty, late tests and exposure to other concepts in the song can affect results. Actual dates and responses are exportable.

## Storage and verification

New SQLite tables are additive and initialized when the page opens. Uploaded files are stored under `data/study_audio`; include that directory when backing up recordings in addition to the database. Automatic transcription requires `faster-whisper`; the first run downloads a speech model into `data/speech_models`. Audio recognition runs locally.

Regression checks: `python -m pytest tests/test_audio_study.py tests/test_material_reviews.py tests/test_notebook.py tests/test_flashcards.py tests/test_study_progress.py tests/test_sidebar_toggle.py`.

Player checks: `node tests/js/audio_player.test.mjs` with `jsdom` installed, or `JSDOM_PATH` pointing to an existing jsdom package. These cover playback sampling, seek exclusion, event acknowledgments, safe note text, lifecycle cleanup, timed lyric parsing and highlighting.

Future work from the feedback: cross-tool attention recommendations, automated semantic scoring, and deeper relearning analytics. Music generation is explicitly outside scope.

## Google Drive storage (local Windows installation)
Audio Library now includes Google Drive audio storage. New uploads switch to Drive after a successful connection; existing local recordings stay readable. Drive files remain private. Invited StudyForge listeners use the owner's server-side authorization, following the existing app permissions; no public Drive sharing links are created.

Enable Drive API in Google Cloud, configure Google Auth Platform, and create a Desktop app OAuth client. Upload the downloaded client JSON in Audio Library, save configuration, then Connect Google Drive. Open the app on the computer running Streamlit: consent opens on that computer with an ephemeral 127.0.0.1 callback, separate from Streamlit's port 8510. Remote hosting is not supported by this desktop OAuth implementation. Tokens and client configuration are stored in Windows Credential Manager, partitioned by database path and app user; no token files are written. Do not share the JSON in chat or commit it.

Only drive.file is requested. This gives StudyForge access to files it creates/uses, not all Drive files, and does not authorize ChatGPT Drive access. Google One provides storage quota; Google Cloud OAuth setup is still necessary. External apps in Testing can require renewed consent after seven days; reconnect when prompted or configure Production as appropriate in Google Cloud.

Private playback buffers one recording (maximum 200 MB) in server memory and uses the existing Streamlit media endpoint and waveform player. It is not direct Drive streaming. Browser and Streamlit memory copies are temporary; no new permanent local audio copy is created for Drive uploads. Existing study database metadata remains local and should be backed up. Migrating a selected recording checks size and MD5 before changing its storage reference, retaining the same recording ID, notes, transcript, assignments, sharing and progress. Local originals are deliberately retained; this feature does not delete them.

Disconnect revokes Google access but retains files and Drive storage preference. Reconnect to resume uploads/playback; there is no silent fallback to disk. Failed batches roll back database rows and attempt remote cleanup. If cleanup is unavailable, the app reports incomplete uploads remaining in Drive. Google API failures and revoked consent are handled without exposing tokens.
