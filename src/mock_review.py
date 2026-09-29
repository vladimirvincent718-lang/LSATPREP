"""Automated mock-exam scheduling and review reconciliation.

The planner deliberately derives its state from StudyForge's existing exam and
answer history.  Users maintain only the mock dates (plus optional status/notes
overrides); deadlines and practice matches are reproducible derived data.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

from src.database import get_connection
from src.exam_planning import get_exam_plan


AUTO_STATUS = ("Pending", "In Progress", "Complete")
MOCK_MODES = ("mock_exam", "full_exam", "neonatal_mock")


def _date_value(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def _topic_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def ensure_mock_review_schema() -> None:
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mock_exam_schedule (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                  INTEGER NOT NULL,
            sequence_number          INTEGER NOT NULL,
            scheduled_date           TEXT NOT NULL,
            completed_at             TIMESTAMP,
            matched_attempt_ids_json TEXT DEFAULT '[]',
            is_active                INTEGER DEFAULT 1,
            created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, sequence_number),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS mock_review_items (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                    INTEGER NOT NULL,
            mock_schedule_id           INTEGER NOT NULL,
            course_id                  INTEGER,
            topic_key                  TEXT NOT NULL,
            topic_name                 TEXT NOT NULL,
            match_topic_key            TEXT,
            review_deadline            TEXT,
            days_allocated             INTEGER DEFAULT 0,
            auto_status                TEXT DEFAULT 'Pending',
            status_override            TEXT,
            date_reviewed              TEXT,
            matched_practice_attempt_id INTEGER,
            retest_score               REAL,
            notes                      TEXT DEFAULT '',
            created_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mock_schedule_id, course_id, topic_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (mock_schedule_id) REFERENCES mock_exam_schedule(id),
            FOREIGN KEY (course_id) REFERENCES courses(id),
            FOREIGN KEY (matched_practice_attempt_id) REFERENCES exam_attempts(id)
        );

        CREATE TABLE IF NOT EXISTS mock_review_plan_config (
            mock_schedule_id INTEGER PRIMARY KEY,
            user_id           INTEGER NOT NULL,
            curriculum_id     INTEGER NOT NULL,
            configured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (mock_schedule_id) REFERENCES mock_exam_schedule(id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (curriculum_id) REFERENCES curriculums(id)
        );

        CREATE TABLE IF NOT EXISTS mock_review_module_selections (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL,
            mock_schedule_id INTEGER NOT NULL,
            course_id        INTEGER NOT NULL,
            topic_key        TEXT NOT NULL,
            topic_name       TEXT NOT NULL,
            match_topic_key  TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mock_schedule_id, course_id, topic_key),
            FOREIGN KEY (mock_schedule_id) REFERENCES mock_exam_schedule(id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS mock_review_course_priority (
            user_id INTEGER NOT NULL,
            mock_schedule_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (user_id, mock_schedule_id, course_id),
            FOREIGN KEY (mock_schedule_id) REFERENCES mock_exam_schedule(id)
        );

        CREATE INDEX IF NOT EXISTS idx_mock_schedule_user_date
            ON mock_exam_schedule(user_id, scheduled_date);
        CREATE INDEX IF NOT EXISTS idx_mock_review_user_status
            ON mock_review_items(user_id, auto_status, status_override);
        """
    )
    schedule_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(mock_exam_schedule)")
    }
    for name, sql_type in (("manual_score", "REAL"), ("score_provider", "TEXT DEFAULT ''")):
        if name not in schedule_columns:
            conn.execute(f"ALTER TABLE mock_exam_schedule ADD COLUMN {name} {sql_type}")
    review_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(mock_review_items)").fetchall()
    }
    if "match_topic_key" not in review_columns:
        conn.execute("ALTER TABLE mock_review_items ADD COLUMN match_topic_key TEXT")
    selection_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(mock_review_module_selections)").fetchall()
    }
    if "match_topic_key" not in selection_columns:
        conn.execute("ALTER TABLE mock_review_module_selections ADD COLUMN match_topic_key TEXT")
    conn.execute(
        "UPDATE mock_review_items SET match_topic_key = topic_key WHERE match_topic_key IS NULL"
    )
    conn.execute(
        """UPDATE mock_review_module_selections
           SET match_topic_key = topic_key WHERE match_topic_key IS NULL"""
    )
    conn.commit()
    conn.close()


def _review_course_order(conn, user_id, mock_schedule_id):
    rows = conn.execute(
        """SELECT course_id FROM mock_review_items
           WHERE user_id = ? AND mock_schedule_id = ?
           ORDER BY review_deadline, topic_name, id""",
        (user_id, mock_schedule_id),
    ).fetchall()
    baseline = list(dict.fromkeys(row["course_id"] for row in rows))
    saved = conn.execute(
        """SELECT course_id FROM mock_review_course_priority
           WHERE user_id = ? AND mock_schedule_id = ? ORDER BY position""",
        (user_id, mock_schedule_id),
    ).fetchall()
    ordered = [row["course_id"] for row in saved if row["course_id"] in baseline]
    return ordered + [course_id for course_id in baseline if course_id not in ordered]


def get_review_course_order(user_id: int, mock_schedule_id: int) -> list:
    """Return saved course priorities, appending newly added courses."""
    ensure_mock_review_schema()
    conn = get_connection()
    try:
        return _review_course_order(conn, user_id, mock_schedule_id)
    finally:
        conn.close()


def move_review_course(user_id: int, mock_schedule_id: int,
                       course_id: int, neighbor_id: int) -> None:
    """Swap visible neighbors while preserving courses hidden by status filters."""
    ensure_mock_review_schema()
    conn = get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            owned = conn.execute(
                "SELECT id FROM mock_exam_schedule WHERE id = ? AND user_id = ?",
                (mock_schedule_id, user_id),
            ).fetchone()
            order = _review_course_order(conn, user_id, mock_schedule_id)
            if (not owned or course_id is None or neighbor_id is None
                    or course_id == neighbor_id
                    or course_id not in order or neighbor_id not in order):
                raise ValueError("Choose two courses from this mock's review queue.")
            left, right = order.index(course_id), order.index(neighbor_id)
            order[left], order[right] = order[right], order[left]
            conn.executemany(
                """INSERT INTO mock_review_course_priority
                   (user_id, mock_schedule_id, course_id, position) VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, mock_schedule_id, course_id)
                   DO UPDATE SET position = excluded.position""",
                [(user_id, mock_schedule_id, cid, position)
                 for position, cid in enumerate(order) if cid is not None],
            )
    finally:
        conn.close()


def get_review_module_plan(user_id: int, mock_schedule_id: int) -> dict:
    """Return the saved curriculum and module choices for one scheduled mock."""
    ensure_mock_review_schema()
    conn = get_connection()
    config = conn.execute(
        """SELECT curriculum_id FROM mock_review_plan_config
           WHERE user_id = ? AND mock_schedule_id = ?""",
        (int(user_id), int(mock_schedule_id)),
    ).fetchone()
    rows = conn.execute(
        """SELECT course_id, topic_name, match_topic_key
           FROM mock_review_module_selections
           WHERE user_id = ? AND mock_schedule_id = ?
           ORDER BY course_id, topic_name COLLATE NOCASE""",
        (int(user_id), int(mock_schedule_id)),
    ).fetchall()
    conn.close()
    selections: dict[int, list[str]] = {}
    selection_items = []
    for row in rows:
        selections.setdefault(int(row["course_id"]), []).append(row["topic_name"])
        selection_items.append({
            "course_id": int(row["course_id"]),
            "topic_name": row["topic_name"],
            "match_topic_key": row["match_topic_key"] or _topic_key(row["topic_name"]),
        })
    return {
        "configured": config is not None,
        "curriculum_id": int(config["curriculum_id"]) if config else None,
        "selections": selections,
        "selection_items": selection_items,
    }


def save_review_module_plan(
    user_id: int,
    mock_schedule_id: int,
    curriculum_id: int,
    selections: dict[int, list[str | dict]],
) -> None:
    """Make the selected curriculum modules authoritative for one review window."""
    ensure_mock_review_schema()
    conn = get_connection()
    owned_mock = conn.execute(
        """SELECT id FROM mock_exam_schedule
           WHERE id = ? AND user_id = ? AND is_active = 1""",
        (int(mock_schedule_id), int(user_id)),
    ).fetchone()
    if not owned_mock:
        conn.close()
        raise ValueError("The selected mock is not part of your active schedule.")

    course_rows = conn.execute(
        "SELECT course_id FROM curriculum_courses WHERE curriculum_id = ?",
        (int(curriculum_id),),
    ).fetchall()
    valid_course_ids = {int(row["course_id"]) for row in course_rows}
    normalized: dict[tuple[int, str], dict[str, str]] = {}
    for course_id, topic_entries in selections.items():
        course_id = int(course_id)
        if course_id not in valid_course_ids:
            conn.close()
            raise ValueError("Every selected course must belong to the chosen curriculum.")
        for entry in topic_entries:
            if isinstance(entry, dict):
                topic_name = entry.get("topic_name") or entry.get("name")
                match_topic = entry.get("match_topic") or entry.get("match_topic_key") or topic_name
            else:
                topic_name = entry
                match_topic = entry
            clean_name = " ".join(str(topic_name or "").strip().split())
            if clean_name:
                normalized[(course_id, _topic_key(clean_name))] = {
                    "topic_name": clean_name,
                    "match_topic_key": _topic_key(match_topic),
                }

    conn.execute(
        """INSERT INTO mock_review_plan_config
           (mock_schedule_id, user_id, curriculum_id)
           VALUES (?, ?, ?)
           ON CONFLICT(mock_schedule_id) DO UPDATE SET
               user_id = excluded.user_id,
               curriculum_id = excluded.curriculum_id,
               updated_at = CURRENT_TIMESTAMP""",
        (int(mock_schedule_id), int(user_id), int(curriculum_id)),
    )
    conn.execute(
        "DELETE FROM mock_review_module_selections WHERE mock_schedule_id = ? AND user_id = ?",
        (int(mock_schedule_id), int(user_id)),
    )
    for (course_id, topic_key), topic in normalized.items():
        conn.execute(
            """INSERT INTO mock_review_module_selections
               (user_id, mock_schedule_id, course_id, topic_key, topic_name, match_topic_key)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                int(user_id), int(mock_schedule_id), course_id, topic_key,
                topic["topic_name"], topic["match_topic_key"],
            ),
        )

    # Removing a selection removes only unfinished work. Completed records stay
    # available as history even if the plan is later edited.
    selected_pairs = set(normalized)
    existing_items = conn.execute(
        """SELECT id, course_id, topic_key,
                  COALESCE(status_override, auto_status) AS effective_status
           FROM mock_review_items
           WHERE user_id = ? AND mock_schedule_id = ?""",
        (int(user_id), int(mock_schedule_id)),
    ).fetchall()
    for item in existing_items:
        pair = (int(item["course_id"]), item["topic_key"]) if item["course_id"] is not None else None
        if pair not in selected_pairs and item["effective_status"] != "Complete":
            conn.execute("DELETE FROM mock_review_items WHERE id = ?", (item["id"],))

    for (course_id, topic_key), topic in normalized.items():
        existing = conn.execute(
            """SELECT id FROM mock_review_items
               WHERE mock_schedule_id = ? AND course_id = ? AND topic_key = ?""",
            (int(mock_schedule_id), course_id, topic_key),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE mock_review_items
                   SET topic_name = ?, match_topic_key = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (topic["topic_name"], topic["match_topic_key"], existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO mock_review_items
                   (user_id, mock_schedule_id, course_id, topic_key, topic_name, match_topic_key)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    int(user_id), int(mock_schedule_id), course_id, topic_key,
                    topic["topic_name"], topic["match_topic_key"],
                ),
            )
    conn.commit()
    conn.close()


def save_mock_schedule(user_id: int, scheduled_dates: list[date | str]) -> None:
    """Replace the active plan while preserving review history for removed rows."""
    ensure_mock_review_schema()
    cleaned = sorted({d for d in (_date_value(value) for value in scheduled_dates) if d})
    plan = get_exam_plan(user_id)
    if plan and any(d >= date.fromisoformat(plan['exam_date']) for d in cleaned):
        raise ValueError("Mock exams must be scheduled before your actual exam date.")
    conn = get_connection()
    existing_rows = conn.execute(
        """SELECT id, scheduled_date FROM mock_exam_schedule
           WHERE user_id = ? AND is_active = 1
           ORDER BY scheduled_date, sequence_number""",
        (int(user_id),),
    ).fetchall()
    exact_rows = {row["scheduled_date"]: row for row in existing_rows}
    new_date_strings = {scheduled.isoformat() for scheduled in cleaned}
    reusable_rows = iter([
        row for row in existing_rows if row["scheduled_date"] not in new_date_strings
    ])
    conn.execute(
        """UPDATE mock_exam_schedule
           SET is_active = 0, sequence_number = -id, updated_at = CURRENT_TIMESTAMP
           WHERE user_id = ?""",
        (int(user_id),),
    )
    for sequence, scheduled in enumerate(cleaned, start=1):
        # Prefer the existing row for this exact date so inserting an earlier mock
        # does not detach already-created review history from its exam. If a date
        # was edited, reuse the unmatched row so its historical identity remains.
        existing = exact_rows.get(scheduled.isoformat()) or next(reusable_rows, None)
        if existing:
            conn.execute(
                """UPDATE mock_exam_schedule
                   SET sequence_number = ?, scheduled_date = ?, is_active = 1,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (sequence, scheduled.isoformat(), existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO mock_exam_schedule
                   (user_id, sequence_number, scheduled_date, is_active)
                   VALUES (?, ?, ?, 1)""",
                (int(user_id), sequence, scheduled.isoformat()),
            )
    conn.commit()
    conn.close()


def get_mock_schedule(user_id: int, *, include_inactive: bool = False) -> list[dict]:
    ensure_mock_review_schema()
    conn = get_connection()
    query = "SELECT * FROM mock_exam_schedule WHERE user_id = ?"
    if not include_inactive:
        query += " AND is_active = 1"
    query += " ORDER BY scheduled_date, sequence_number"
    rows = [dict(row) for row in conn.execute(query, (int(user_id),)).fetchall()]
    conn.close()
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        row["mock_label"] = f"Mock {index}/{total}"
    return rows


def save_mock_scores(user_id: int, scores: list[dict]) -> None:
    """Save external percentages atomically, scoped to the owner's active mocks."""
    ensure_mock_review_schema()
    normalized = []
    for row in scores:
        score = row.get("manual_score")
        if score is not None:
            score = float(score)
            if not math.isfinite(score) or not 0 <= score <= 100:
                raise ValueError("Mock scores must be between 0 and 100 percent.")
        normalized.append((score, str(row.get("score_provider") or "").strip(),
                           int(row["id"]), int(user_id)))
    conn = get_connection()
    try:
        with conn:
            for values in normalized:
                result = conn.execute(
                    """UPDATE mock_exam_schedule
                       SET manual_score = ?, score_provider = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND user_id = ? AND is_active = 1""", values,
                )
                if result.rowcount != 1:
                    raise ValueError("The selected mock is not part of your active schedule.")
    finally:
        conn.close()


def get_review_schedule(user_id):
    """Append the real exam solely as a review boundary, never as a mock."""
    rows = get_mock_schedule(user_id)
    plan = get_exam_plan(user_id)
    if plan:
        rows = [row for row in rows if row['scheduled_date'] < plan['exam_date']]
        rows.append({'id': None, 'scheduled_date': plan['exam_date'],
                     'mock_label': 'Actual exam', 'is_actual_exam': True})
    return rows


def _completed_mock_groups(user_id: int) -> list[dict]:
    conn = get_connection()
    placeholders = ",".join("?" for _ in MOCK_MODES)
    rows = conn.execute(
        f"""SELECT ea.id, ea.mode, ea.completed_at
            FROM exam_attempts ea
            WHERE ea.user_id = ? AND ea.completed_at IS NOT NULL
              AND ea.mode IN ({placeholders})
            ORDER BY ea.completed_at, ea.id""",
        [int(user_id), *MOCK_MODES],
    ).fetchall()
    conn.close()
    groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        completed = _date_value(row["completed_at"])
        if not completed:
            continue
        # Full-exam sections on one calendar date are one mock. Other modes are
        # one DB attempt per mock and therefore retain their attempt identity.
        discriminator = "full" if row["mode"] == "full_exam" else str(row["id"])
        key = (completed.isoformat(), discriminator)
        group = groups.setdefault(
            key,
            {"date": completed, "attempt_ids": [], "completed_at": row["completed_at"]},
        )
        group["attempt_ids"].append(int(row["id"]))
    return list(groups.values())


def _match_completed_mocks(user_id: int, schedule: list[dict]) -> None:
    candidates = _completed_mock_groups(user_id)
    claimed = {
        attempt_id
        for row in schedule
        for attempt_id in json.loads(row.get("matched_attempt_ids_json") or "[]")
    }
    today = date.today()
    conn = get_connection()
    for index, row in enumerate(schedule):
        if row.get("completed_at"):
            continue
        scheduled = _date_value(row["scheduled_date"])
        if not scheduled or scheduled > today:
            continue
        previous_date = _date_value(schedule[index - 1]["scheduled_date"]) if index else None
        next_date = _date_value(schedule[index + 1]["scheduled_date"]) if index + 1 < len(schedule) else None
        eligible = []
        for candidate in candidates:
            if any(aid in claimed for aid in candidate["attempt_ids"]):
                continue
            candidate_date = candidate["date"]
            if previous_date and candidate_date <= previous_date:
                continue
            if next_date and candidate_date >= next_date:
                continue
            # A small early-completion allowance, with unrestricted late matching
            # until the next scheduled mock.
            if candidate_date < scheduled - timedelta(days=3):
                continue
            eligible.append(candidate)
        if not eligible:
            continue
        eligible.sort(key=lambda item: (abs((item["date"] - scheduled).days), item["date"]))
        match = eligible[0]
        claimed.update(match["attempt_ids"])
        conn.execute(
            """UPDATE mock_exam_schedule
               SET completed_at = ?, matched_attempt_ids_json = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND user_id = ?""",
            (match["completed_at"], json.dumps(match["attempt_ids"]), row["id"], int(user_id)),
        )
    conn.commit()
    conn.close()


def _create_weakness_items(user_id: int, schedule_row: dict) -> None:
    conn = get_connection()
    configured = conn.execute(
        """SELECT 1 FROM mock_review_plan_config
           WHERE user_id = ? AND mock_schedule_id = ?""",
        (int(user_id), schedule_row["id"]),
    ).fetchone()
    conn.close()
    if configured:
        # Once the learner saves a module plan, those choices are authoritative
        # for this mock instead of the automatically inferred missed modules.
        return
    attempt_ids = json.loads(schedule_row.get("matched_attempt_ids_json") or "[]")
    if not attempt_ids:
        return
    placeholders = ",".join("?" for _ in attempt_ids)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT q.course_id,
                   COALESCE(NULLIF(TRIM(q.section_type), ''),
                            NULLIF(TRIM(q.question_type), ''), 'General Review') AS topic_name,
                   SUM(CASE WHEN COALESCE(ua.is_correct, 0) = 0 THEN 1 ELSE 0 END) AS misses
            FROM user_answers ua
            JOIN questions q ON q.id = ua.question_id
            WHERE ua.attempt_id IN ({placeholders})
            GROUP BY q.course_id, topic_name
            HAVING misses > 0
            ORDER BY q.course_id, topic_name COLLATE NOCASE""",
        attempt_ids,
    ).fetchall()
    for row in rows:
        topic_name = str(row["topic_name"]).strip()
        topic_key = _topic_key(topic_name)
        existing = conn.execute(
            """SELECT id FROM mock_review_items
               WHERE mock_schedule_id = ? AND course_id IS ? AND topic_key = ?""",
            (schedule_row["id"], row["course_id"], topic_key),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE mock_review_items
                   SET topic_name = ?, match_topic_key = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (topic_name, topic_key, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO mock_review_items
                   (user_id, mock_schedule_id, course_id, topic_key, topic_name, match_topic_key)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    int(user_id), schedule_row["id"], row["course_id"],
                    topic_key, topic_name, topic_key,
                ),
            )
    conn.commit()
    conn.close()


def allocate_review_days(total_days: int, item_count: int) -> list[int]:
    """Return deterministic, near-equal allocations such as 10/4 -> 3,3,2,2."""
    if item_count <= 0:
        return []
    days = max(0, int(total_days))
    base, remainder = divmod(days, item_count)
    return [base + (1 if index < remainder else 0) for index in range(item_count)]


def _allocate_deadlines(user_id: int, schedule: list[dict]) -> None:
    conn = get_connection()
    for index, row in enumerate(schedule[:-1]):
        window_start = _date_value(row.get("completed_at") or row["scheduled_date"])
        window_end = _date_value(schedule[index + 1]["scheduled_date"])
        if not window_start or not window_end or window_start > date.today():
            continue
        items = conn.execute(
            """SELECT id FROM mock_review_items
               WHERE user_id = ? AND mock_schedule_id = ?
               ORDER BY course_id, topic_name COLLATE NOCASE, id""",
            (int(user_id), row["id"]),
        ).fetchall()
        allocations = allocate_review_days((window_end - window_start).days, len(items))
        # Anchor the final item to the day before the next mock, then work
        # backward by the allocations that follow each item.
        for item_index, (item, allocated) in enumerate(zip(items, allocations)):
            later_days = sum(allocations[item_index + 1:])
            deadline = window_end - timedelta(days=later_days + 1)
            deadline = max(deadline, window_start)
            if window_end > window_start:
                deadline = min(deadline, window_end - timedelta(days=1))
            conn.execute(
                """UPDATE mock_review_items
                   SET days_allocated = ?, review_deadline = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (allocated, deadline.isoformat(), item["id"]),
            )
    conn.commit()
    conn.close()


def _practice_match(user_id: int, item: dict, start: date, end: date) -> dict | None:
    """Find the first qualifying practice session, preferring completed work."""
    conn = get_connection()
    params = [
        int(user_id), item.get("course_id"),
        item.get("match_topic_key") or item["topic_key"],
        start.isoformat(), end.isoformat(),
    ]
    rows = conn.execute(
        """SELECT ea.id AS attempt_id, ea.completed_at,
                  MIN(ua.submitted_at) AS first_activity,
                  COUNT(*) AS questions,
                  SUM(CASE WHEN ua.is_correct = 1 THEN 1 ELSE 0 END) AS correct
           FROM user_answers ua
           JOIN exam_attempts ea ON ea.id = ua.attempt_id
           JOIN questions q ON q.id = ua.question_id
           WHERE ea.user_id = ?
             AND q.course_id IS ?
             AND LOWER(TRIM(COALESCE(NULLIF(q.section_type, ''),
                                     NULLIF(q.question_type, ''), 'General Review'))) = ?
             AND ea.mode NOT IN ('mock_exam', 'full_exam', 'neonatal_mock')
             AND date(COALESCE(ea.completed_at, ua.submitted_at)) >= date(?)
             AND date(COALESCE(ea.completed_at, ua.submitted_at)) < date(?)
           GROUP BY ea.id, ea.completed_at
           ORDER BY CASE WHEN ea.completed_at IS NOT NULL THEN 0 ELSE 1 END,
                    datetime(COALESCE(ea.completed_at, first_activity)), ea.id""",
        params,
    ).fetchall()
    conn.close()
    if not rows:
        return None
    return dict(rows[0])


def _reconcile_practice(user_id: int, schedule: list[dict]) -> None:
    conn = get_connection()
    items = [dict(row) for row in conn.execute(
        """SELECT mri.*,
                  COALESCE(mes.completed_at, mes.scheduled_date) AS review_start,
                  (SELECT scheduled_date FROM mock_exam_schedule next_mock
                   WHERE next_mock.user_id = mes.user_id
                     AND next_mock.is_active = 1
                     AND next_mock.scheduled_date > mes.scheduled_date
                   ORDER BY next_mock.scheduled_date LIMIT 1) AS next_mock_date
           FROM mock_review_items mri
           JOIN mock_exam_schedule mes ON mes.id = mri.mock_schedule_id
           WHERE mri.user_id = ?""",
        (int(user_id),),
    ).fetchall()]
    conn.close()
    for item in items:
        start = _date_value(item.get("review_start"))
        plan = get_exam_plan(user_id)
        end = _date_value(item.get("next_mock_date")) or (_date_value(plan['exam_date']) if plan else None)
        if not start or not end or start > date.today():
            continue
        match = _practice_match(user_id, item, start, end)
        conn = get_connection()
        if not match:
            conn.execute(
                """UPDATE mock_review_items
                   SET auto_status = 'Pending', date_reviewed = NULL,
                       matched_practice_attempt_id = NULL, retest_score = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (item["id"],),
            )
        elif match.get("completed_at"):
            score = round(100 * int(match["correct"]) / int(match["questions"]), 1) if match["questions"] else None
            conn.execute(
                """UPDATE mock_review_items
                   SET auto_status = 'Complete', date_reviewed = ?,
                       matched_practice_attempt_id = ?, retest_score = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (_date_value(match["completed_at"]).isoformat(), match["attempt_id"], score, item["id"]),
            )
        else:
            conn.execute(
                """UPDATE mock_review_items
                   SET auto_status = 'In Progress', date_reviewed = NULL,
                       matched_practice_attempt_id = ?, retest_score = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (match["attempt_id"], item["id"]),
            )
        conn.commit()
        conn.close()


def sync_mock_reviews(user_id: int) -> None:
    """Idempotently reconcile schedules, mock weaknesses, deadlines and practice."""
    ensure_mock_review_schema()
    schedule = get_mock_schedule(user_id)
    _match_completed_mocks(user_id, schedule)
    schedule = get_mock_schedule(user_id)
    for row in schedule:
        _create_weakness_items(user_id, row)
    _allocate_deadlines(user_id, get_review_schedule(user_id))
    _reconcile_practice(user_id, schedule)


def get_mock_review_items(user_id: int, status: str = "unfinished") -> list[dict]:
    ensure_mock_review_schema()
    conn = get_connection()
    query = """SELECT mri.*, mes.scheduled_date, mes.completed_at AS mock_completed_at,
                      c.title AS course_title
               FROM mock_review_items mri
               JOIN mock_exam_schedule mes ON mes.id = mri.mock_schedule_id
               LEFT JOIN courses c ON c.id = mri.course_id
               WHERE mri.user_id = ?"""
    if status == "unfinished":
        query += " AND COALESCE(mri.status_override, mri.auto_status) <> 'Complete'"
    elif status == "complete":
        query += " AND COALESCE(mri.status_override, mri.auto_status) = 'Complete'"
    query += " ORDER BY mes.scheduled_date DESC, mri.review_deadline, mri.topic_name"
    rows = [dict(row) for row in conn.execute(query, (int(user_id),)).fetchall()]
    conn.close()
    schedule = get_mock_schedule(user_id, include_inactive=True)
    ordered = sorted(schedule, key=lambda row: (row["scheduled_date"], row["id"]))
    total = len(ordered)
    labels = {row["id"]: f"Mock {index}/{total}" for index, row in enumerate(ordered, start=1)}
    for row in rows:
        row["mock_label"] = labels.get(row["mock_schedule_id"], "Mock")
        row["review_status"] = row.get("status_override") or row.get("auto_status") or "Pending"
        course = str(row.get("course_title") or "").strip()
        row["topic_display"] = f"{course} — {row['topic_name']}" if course else row["topic_name"]
    return rows


def update_review_item(user_id: int, item_id: int, *, status_override: str | None, notes: str) -> bool:
    ensure_mock_review_schema()
    override = status_override if status_override in AUTO_STATUS else None
    conn = get_connection()
    result = conn.execute(
        """UPDATE mock_review_items
           SET status_override = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ? AND user_id = ?""",
        (override, str(notes or ""), int(item_id), int(user_id)),
    )
    conn.commit()
    conn.close()
    return bool(result.rowcount)


def get_next_mock_summary(user_id: int, *, today: date | None = None) -> dict | None:
    ensure_mock_review_schema()
    today = today or date.today()
    schedule = get_mock_schedule(user_id)
    upcoming = [
        row for row in schedule
        if not row.get("completed_at")
        and (_date_value(row["scheduled_date"]) or date.min) >= today
    ]
    if not upcoming:
        return None
    next_mock = upcoming[0]
    next_index = next(
        index for index, row in enumerate(schedule) if row["id"] == next_mock["id"]
    )
    review_mock_id = schedule[next_index - 1]["id"] if next_index > 0 else None
    conn = get_connection()
    counts = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN COALESCE(status_override, auto_status) = 'Complete'
                           THEN 1 ELSE 0 END) AS complete
           FROM mock_review_items
           WHERE user_id = ? AND mock_schedule_id IS ?""",
        (int(user_id), review_mock_id),
    ).fetchone()
    conn.close()
    scheduled = _date_value(next_mock["scheduled_date"])
    total = int(counts["total"] or 0)
    complete = int(counts["complete"] or 0)
    return {
        "label": next_mock["mock_label"],
        "scheduled_date": scheduled,
        "days_remaining": (scheduled - today).days,
        "review_items_total": total,
        "review_items_complete": complete,
        "review_items_remaining": max(0, total - complete),
        "review_progress_label": (
            f"{complete} reviewed of {total}" if total else "No modules selected"
        ),
        # Kept explicit so notification thresholds can be added without a schema rewrite.
        "reminder_offsets": [14, 7, 3, 1],
    }


def get_current_review_mock(user_id: int, *, today: date | None = None) -> dict | None:
    """Return the mock whose review window currently contains today."""
    today = today or date.today()
    schedule = get_review_schedule(user_id)
    for index, row in enumerate(schedule[:-1]):
        start = _date_value(row.get("completed_at") or row["scheduled_date"])
        end = _date_value(schedule[index + 1]["scheduled_date"])
        if start and end and start <= today < end:
            current = dict(row)
            current["window_start"] = start
            current["window_end"] = end
            return current
    return None


def get_review_window_practice_sessions(user_id: int, mock_schedule_id: int, *, include_exams: bool = False) -> list[dict]:
    """Return practice modules delivered inside one mock's exact review window."""
    ensure_mock_review_schema()
    conn = get_connection()
    mock = conn.execute(
        """SELECT * FROM mock_exam_schedule
           WHERE id = ? AND user_id = ? AND is_active = 1""",
        (int(mock_schedule_id), int(user_id)),
    ).fetchone()
    if not mock:
        conn.close()
        return []
    next_mock = conn.execute(
        """SELECT scheduled_date FROM mock_exam_schedule
           WHERE user_id = ? AND is_active = 1 AND scheduled_date > ?
           ORDER BY scheduled_date LIMIT 1""",
        (int(user_id), mock["scheduled_date"]),
    ).fetchone()
    start = _date_value(mock["completed_at"] or mock["scheduled_date"])
    plan = get_exam_plan(user_id)
    end = _date_value(next_mock["scheduled_date"]) if next_mock else (_date_value(plan["exam_date"]) if plan else None)
    if not start or not end:
        conn.close()
        return []
    rows = conn.execute(
        """SELECT ea.id AS attempt_id, ea.mode, ea.completed_at,
                  MIN(ua.submitted_at) AS first_activity,
                  q.course_id, c.title AS course_title,
                  COALESCE(NULLIF(TRIM(q.section_type), ''),
                           NULLIF(TRIM(q.question_type), ''), 'General Review') AS module_name,
                  COUNT(*) AS questions,
                  SUM(CASE WHEN ua.is_correct = 1 THEN 1 ELSE 0 END) AS correct
           FROM user_answers ua
           JOIN exam_attempts ea ON ea.id = ua.attempt_id
           JOIN questions q ON q.id = ua.question_id
           LEFT JOIN courses c ON c.id = q.course_id
           WHERE ea.user_id = ?
             AND (? OR ea.mode NOT IN ('mock_exam', 'full_exam', 'neonatal_mock'))
             AND date(COALESCE(ea.completed_at, ua.submitted_at)) >= date(?)
             AND date(COALESCE(ea.completed_at, ua.submitted_at)) < date(?)
           GROUP BY ea.id, ea.mode, ea.completed_at, q.course_id, c.title, module_name
           ORDER BY datetime(COALESCE(ea.completed_at, first_activity)), ea.id""",
        (int(user_id), int(include_exams), start.isoformat(), end.isoformat()),
    ).fetchall()
    conn.close()
    output = []
    for row in rows:
        item = dict(row)
        activity = _date_value(item.get("completed_at") or item.get("first_activity"))
        item["activity_date"] = activity.isoformat() if activity else None
        item["status"] = "Complete" if item.get("completed_at") else "In Progress"
        item["score"] = (
            round(100 * int(item["correct"]) / int(item["questions"]), 1)
            if item.get("questions") else None
        )
        output.append(item)
    return output


def get_window_summary(user_id: int) -> list[dict]:
    schedule = get_review_schedule(user_id)
    conn = get_connection()
    output = []
    for index, row in enumerate(schedule[:-1]):
        start = _date_value(row.get("completed_at") or row["scheduled_date"])
        end = _date_value(schedule[index + 1]["scheduled_date"])
        if not start or start > date.today():
            continue
        allocated = conn.execute(
            "SELECT COALESCE(SUM(days_allocated), 0) FROM mock_review_items WHERE mock_schedule_id = ?",
            (row["id"],),
        ).fetchone()[0]
        total_days = max(0, (end - start).days) if start and end else 0
        output.append({
            "mock_label": row["mock_label"],
            "days_until_next_mock": total_days,
            "days_allocated": int(allocated),
            "unallocated_buffer": max(0, total_days - int(allocated)),
        })
    conn.close()
    return output
