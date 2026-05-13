"""
database.py — SQLite schema, migrations, and all DB helper functions.

Architecture (StudyForge v2):
  - Courses are GLOBAL / SHARED — not owned by individual users.
  - Questions and materials belong to a course, visible to all enrolled users.
  - Users ENROLL in courses; their progress (scores, answers, mistakes,
    material completion) is always private to them.
  - First registered user is automatically an admin and can create/edit
    courses and upload shared content.

New in this version:
  - courses.normalized_title           — duplicate-title detection
  - course_materials.normalized_title  — duplicate-title detection per course
  - course_materials.display_order     — custom ordering
  - course_materials.estimated_minutes — optional time estimate
  - questions.content_hash             — identical-content duplicate detection
"""

import sqlite3
import json
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE        = Path(__file__).resolve().parent
PROJECT_ROOT = _HERE.parent
DB_PATH      = PROJECT_ROOT / "data" / "lsat_app.db"


# ── Normalisation helpers (used for duplicate detection) ─────────────────────
def _normalize_title(title: str) -> str:
    """Lowercase + collapse whitespace.  'CFA  Level 1' == 'cfa level 1'."""
    return " ".join(title.strip().lower().split())


def _make_content_hash(stimulus: str, choice_a: str = "", choice_b: str = "",
                        choice_c: str = "", choice_d: str = "",
                        choice_e: str = "", correct_answer: str = "") -> str:
    """32-char SHA-256 fingerprint of question content."""
    parts = [stimulus, choice_a, choice_b, choice_c,
             choice_d, choice_e, correct_answer]
    blob = "|".join(p.strip().lower() for p in parts)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


# ── Connection helper ─────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ── Schema — CREATE IF NOT EXISTS (only runs on fresh installs) ───────────────
def init_database() -> None:
    """Create tables on fresh install, then run safe migrations."""
    conn = get_connection()
    conn.executescript("""
    -- ── Users ──────────────────────────────────────────────────────────── --
    CREATE TABLE IF NOT EXISTS users (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        username              TEXT    UNIQUE NOT NULL,
        password_hash         TEXT    NOT NULL,
        security_question     TEXT,
        security_answer_hash  TEXT,
        is_admin              INTEGER DEFAULT 0,
        created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── Courses  (GLOBAL — shared by all users) ─────────────────────────── --
    CREATE TABLE IF NOT EXISTS courses (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        created_by_user_id  INTEGER,
        title               TEXT NOT NULL,
        normalized_title    TEXT DEFAULT '',
        description         TEXT DEFAULT '',
        category            TEXT DEFAULT '',
        is_active           INTEGER DEFAULT 1,
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── Course enrollments  (user ↔ course, user-specific) ──────────────── --
    CREATE TABLE IF NOT EXISTS course_enrollments (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        course_id         INTEGER NOT NULL,
        enrollment_status TEXT    DEFAULT 'Active',
        enrolled_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, course_id),
        FOREIGN KEY (user_id)  REFERENCES users(id),
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );

    -- ── Questions  (shared — belong to course, not user) ────────────────── --
    CREATE TABLE IF NOT EXISTS questions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id       INTEGER,
        question_id     TEXT UNIQUE,
        section_type    TEXT,
        question_type   TEXT,
        difficulty      INTEGER DEFAULT 3,
        passage         TEXT,
        stimulus        TEXT NOT NULL,
        choice_a        TEXT,
        choice_b        TEXT,
        choice_c        TEXT,
        choice_d        TEXT,
        choice_e        TEXT,
        correct_answer  TEXT,
        explanation     TEXT,
        wrong_answer_a  TEXT,
        wrong_answer_b  TEXT,
        wrong_answer_c  TEXT,
        wrong_answer_d  TEXT,
        wrong_answer_e  TEXT,
        source          TEXT DEFAULT 'custom',
        tags            TEXT,
        content_hash    TEXT DEFAULT '',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );

    -- ── Exam attempts  (user-specific) ──────────────────────────────────── --
    CREATE TABLE IF NOT EXISTS exam_attempts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id             INTEGER NOT NULL,
        course_id           INTEGER,
        mode                TEXT,
        section_type        TEXT,
        started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at        TIMESTAMP,
        total_questions     INTEGER DEFAULT 0,
        correct_answers     INTEGER DEFAULT 0,
        raw_score           REAL    DEFAULT 0,
        percent_correct     REAL    DEFAULT 0,
        section_scores_json TEXT,
        settings_json       TEXT,
        is_hard_mode        INTEGER DEFAULT 0,
        FOREIGN KEY (user_id)   REFERENCES users(id),
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );

    -- ── Per-question answers  (user-specific) ───────────────────────────── --
    CREATE TABLE IF NOT EXISTS user_answers (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id          INTEGER NOT NULL,
        question_id         INTEGER NOT NULL,
        selected_answer     TEXT,
        is_correct          INTEGER DEFAULT 0,
        time_spent_seconds  REAL    DEFAULT 0,
        is_flagged          INTEGER DEFAULT 0,
        section_number      INTEGER DEFAULT 1,
        FOREIGN KEY (attempt_id)  REFERENCES exam_attempts(id),
        FOREIGN KEY (question_id) REFERENCES questions(id)
    );

    -- ── Per-user settings ────────────────────────────────────────────────── --
    CREATE TABLE IF NOT EXISTS settings (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        key     TEXT    NOT NULL,
        value   TEXT,
        UNIQUE(user_id, key),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    -- App-wide settings for admin-managed integrations.
    CREATE TABLE IF NOT EXISTS app_settings (
        key        TEXT PRIMARY KEY,
        value      TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── Mistake journal  (user-specific) ────────────────────────────────── --
    CREATE TABLE IF NOT EXISTS mistake_journal (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        attempt_id  INTEGER,
        note        TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id)     REFERENCES users(id),
        FOREIGN KEY (question_id) REFERENCES questions(id)
    );

    -- ── Course materials  (shared — belong to course, not user) ─────────── --
    CREATE TABLE IF NOT EXISTS course_materials (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id           INTEGER NOT NULL,
        created_by_user_id  INTEGER,
        title               TEXT NOT NULL,
        normalized_title    TEXT DEFAULT '',
        material_type       TEXT DEFAULT 'Reading',
        content_text        TEXT DEFAULT '',
        external_url        TEXT DEFAULT '',
        notes               TEXT DEFAULT '',
        material_section    TEXT DEFAULT 'Module',
        module_name         TEXT DEFAULT '',
        display_order       INTEGER DEFAULT 0,
        estimated_minutes   INTEGER DEFAULT 0,
        is_active           INTEGER DEFAULT 1,
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );

    -- ── Material progress  (user-specific) ──────────────────────────────── --
    CREATE TABLE IF NOT EXISTS course_modules (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id        INTEGER NOT NULL,
        name             TEXT NOT NULL,
        normalized_name  TEXT DEFAULT '',
        display_order    INTEGER DEFAULT 0,
        is_active        INTEGER DEFAULT 1,
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS material_progress (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        material_id INTEGER NOT NULL,
        course_id   INTEGER NOT NULL,
        status      TEXT DEFAULT 'Not Started',
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, material_id),
        FOREIGN KEY (user_id)     REFERENCES users(id),
        FOREIGN KEY (material_id) REFERENCES course_materials(id)
    );

    -- ── User sessions (persistent login — token stored in browser cookie) ── --
    CREATE TABLE IF NOT EXISTS user_sessions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        token      TEXT    UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_user_sessions_token
        ON user_sessions(token);
    """)
    conn.commit()
    conn.close()
    _migrate_database()
    # Responsive Layout Manager tables (lazy-init, safe to call here)
    try:
        from src.responsive_layout import init_responsive_tables
        init_responsive_tables()
    except Exception:
        pass


# ── Migration — safe, idempotent, runs on every startup ───────────────────────
def _migrate_database() -> None:
    """
    Incremental migration that is always safe to re-run.

    New steps in this version:
    - Add courses.normalized_title and back-fill it.
    - Add course_materials.normalized_title, display_order, estimated_minutes.
    - Add questions.content_hash and back-fill it.
    - Create app_settings for shared integration credentials.
    - All existing migration steps are preserved.
    """
    conn = get_connection()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS app_settings (
               key        TEXT PRIMARY KEY,
               value      TEXT DEFAULT '',
               updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS course_modules (
               id               INTEGER PRIMARY KEY AUTOINCREMENT,
               course_id        INTEGER NOT NULL,
               name             TEXT NOT NULL,
               normalized_name  TEXT DEFAULT '',
               display_order    INTEGER DEFAULT 0,
               is_active        INTEGER DEFAULT 1,
               created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               FOREIGN KEY (course_id) REFERENCES courses(id)
           )"""
    )

    def cols(table: str) -> set:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    # ── 1. users columns ──────────────────────────────────────────────────────
    u_cols = cols("users")
    for col, ddl in [
        ("security_question",   "ALTER TABLE users ADD COLUMN security_question TEXT"),
        ("security_answer_hash","ALTER TABLE users ADD COLUMN security_answer_hash TEXT"),
        ("is_admin",            "ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0"),
    ]:
        if col not in u_cols:
            conn.execute(ddl)

    # ── 2. Legacy column additions ────────────────────────────────────────────
    q_cols  = cols("questions")
    ea_cols = cols("exam_attempts")
    if "course_id" not in q_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN course_id INTEGER")
    if "course_id" not in ea_cols:
        conn.execute("ALTER TABLE exam_attempts ADD COLUMN course_id INTEGER")

    # ── 3. courses: add created_by_user_id if missing ─────────────────────────
    c_cols = cols("courses")
    if "created_by_user_id" not in c_cols:
        conn.execute("ALTER TABLE courses ADD COLUMN created_by_user_id INTEGER")
        if "user_id" in c_cols:
            conn.execute("UPDATE courses SET created_by_user_id = user_id "
                         "WHERE created_by_user_id IS NULL")

    # ── 4a. courses.normalized_title ──────────────────────────────────────────
    c_cols = cols("courses")
    if "normalized_title" not in c_cols:
        conn.execute("ALTER TABLE courses ADD COLUMN normalized_title TEXT DEFAULT ''")
    # Back-fill any courses that have an empty normalized_title
    empty_nt = conn.execute(
        "SELECT id, title FROM courses WHERE normalized_title IS NULL OR normalized_title = ''"
    ).fetchall()
    for row in empty_nt:
        conn.execute(
            "UPDATE courses SET normalized_title = ? WHERE id = ?",
            (_normalize_title(row["title"]), row["id"]),
        )
    conn.commit()

    # ── 4b. course_materials columns ──────────────────────────────────────────
    m_cols = cols("course_materials")
    for col_name, ddl in [
        ("created_by_user_id", "ALTER TABLE course_materials ADD COLUMN created_by_user_id INTEGER"),
        ("is_active",          "ALTER TABLE course_materials ADD COLUMN is_active INTEGER DEFAULT 1"),
        ("normalized_title",   "ALTER TABLE course_materials ADD COLUMN normalized_title TEXT DEFAULT ''"),
        ("material_section",   "ALTER TABLE course_materials ADD COLUMN material_section TEXT DEFAULT 'Module'"),
        ("module_name",        "ALTER TABLE course_materials ADD COLUMN module_name TEXT DEFAULT ''"),
        ("display_order",      "ALTER TABLE course_materials ADD COLUMN display_order INTEGER DEFAULT 0"),
        ("estimated_minutes",  "ALTER TABLE course_materials ADD COLUMN estimated_minutes INTEGER DEFAULT 0"),
    ]:
        if col_name not in m_cols:
            conn.execute(ddl)
            if col_name == "created_by_user_id" and "user_id" in m_cols:
                conn.execute(
                    "UPDATE course_materials SET created_by_user_id = user_id "
                    "WHERE created_by_user_id IS NULL"
                )

    # Back-fill materials normalized_title
    empty_mnt = conn.execute(
        "SELECT id, title FROM course_materials "
        "WHERE normalized_title IS NULL OR normalized_title = ''"
    ).fetchall()
    for row in empty_mnt:
        conn.execute(
            "UPDATE course_materials SET normalized_title = ? WHERE id = ?",
            (_normalize_title(row["title"]), row["id"]),
        )
    conn.execute(
        """UPDATE course_materials
           SET material_section = 'Syllabus'
           WHERE (material_section IS NULL OR material_section = '' OR material_section = 'Module')
             AND (
                LOWER(title) LIKE '%syllabus%'
                OR LOWER(notes) LIKE '%syllabus%'
                OR LOWER(material_type) = 'syllabus'
             )"""
    )
    conn.execute(
        """UPDATE course_materials
           SET material_section = 'Module'
           WHERE material_section IS NULL OR material_section = ''"""
    )
    conn.commit()

    # ── 4c. questions.content_hash ────────────────────────────────────────────
    q_cols = cols("questions")
    if "content_hash" not in q_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN content_hash TEXT DEFAULT ''")

    # Back-fill content_hash for existing questions
    empty_ch = conn.execute(
        "SELECT id, stimulus, choice_a, choice_b, choice_c, "
        "       choice_d, choice_e, correct_answer "
        "FROM questions WHERE content_hash IS NULL OR content_hash = ''"
    ).fetchall()
    for row in empty_ch:
        ch = _make_content_hash(
            row["stimulus"] or "",
            row["choice_a"] or "", row["choice_b"] or "",
            row["choice_c"] or "", row["choice_d"] or "",
            row["choice_e"] or "", row["correct_answer"] or "",
        )
        conn.execute(
            "UPDATE questions SET content_hash = ? WHERE id = ?", (ch, row["id"])
        )
    if empty_ch:
        conn.commit()

    # ── 5. course_enrollments table ───────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS course_enrollments (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL,
            course_id         INTEGER NOT NULL,
            enrollment_status TEXT    DEFAULT 'Active',
            enrolled_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, course_id),
            FOREIGN KEY (user_id)   REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    """)
    conn.commit()

    # ── 6. Ensure one canonical shared "LSAT Prep" course ────────────────────
    all_lsat = conn.execute(
        "SELECT id FROM courses WHERE title = 'LSAT Prep' AND is_active = 1 "
        "ORDER BY id ASC"
    ).fetchall()

    if not all_lsat:
        first_user = conn.execute(
            "SELECT id FROM users ORDER BY id ASC LIMIT 1"
        ).fetchone()
        creator_id = first_user["id"] if first_user else None
        conn.execute(
            """INSERT INTO courses
               (created_by_user_id, title, normalized_title, description, category)
               VALUES (?, 'LSAT Prep', 'lsat prep',
                       'Shared LSAT preparation course.',
                       'LSAT')""",
            (creator_id,),
        )
        conn.commit()
        all_lsat = conn.execute(
            "SELECT id FROM courses WHERE title = 'LSAT Prep' ORDER BY id ASC"
        ).fetchall()

    canonical_id = all_lsat[0]["id"]

    # ── 7. Deduplicate per-user LSAT Prep copies ──────────────────────────────
    duplicates = [r["id"] for r in all_lsat[1:]]
    for dup_id in duplicates:
        conn.execute(
            "UPDATE questions SET course_id = ? WHERE course_id = ?",
            (canonical_id, dup_id),
        )
        conn.execute(
            "UPDATE exam_attempts SET course_id = ? WHERE course_id = ?",
            (canonical_id, dup_id),
        )
        conn.execute(
            "UPDATE course_materials SET course_id = ? WHERE course_id = ?",
            (canonical_id, dup_id),
        )
        conn.execute(
            "UPDATE material_progress SET course_id = ? WHERE course_id = ?",
            (canonical_id, dup_id),
        )
        conn.execute(
            "UPDATE courses SET is_active = 0 WHERE id = ?", (dup_id,)
        )
    conn.commit()

    conn.execute(
        "UPDATE questions SET course_id = ? WHERE course_id IS NULL",
        (canonical_id,),
    )
    conn.commit()

    # ── 8. Auto-enroll all existing users in LSAT Prep ───────────────────────
    users = conn.execute("SELECT id FROM users ORDER BY id").fetchall()
    for u in users:
        conn.execute(
            """INSERT OR IGNORE INTO course_enrollments
               (user_id, course_id, enrollment_status)
               VALUES (?, ?, 'Active')""",
            (u["id"], canonical_id),
        )
    conn.commit()

    conn.execute(
        "UPDATE exam_attempts SET course_id = ? WHERE course_id IS NULL",
        (canonical_id,),
    )
    conn.commit()

    # ── 9. Set first user as admin if none exists ─────────────────────────────
    admin_exists = conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin = 1"
    ).fetchone()[0]
    if not admin_exists and users:
        conn.execute(
            "UPDATE users SET is_admin = 1 WHERE id = ?", (users[0]["id"],)
        )
        conn.commit()

    # ── 10. user_sessions table (persistent login) ────────────────────────────
    try:
        conn.execute("SELECT 1 FROM user_sessions LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_user_sessions_token
            ON user_sessions(token);
        """)
        conn.commit()

    conn.close()

    # Purge any expired sessions on every startup (housekeeping)
    cleanup_expired_sessions()


# ── User helpers ──────────────────────────────────────────────────────────────
def create_user(username: str, password_hash: str) -> bool:
    """Register a new user. Auto-enrolls them in all active courses."""
    try:
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username.strip().lower(), password_hash),
        )
        conn.commit()
        conn.close()

        user = get_user_by_username(username)
        if user:
            _auto_enroll_new_user(user["id"])
        return True
    except sqlite3.IntegrityError:
        return False


def _auto_enroll_new_user(user_id: int) -> None:
    """Enroll a newly registered user in all currently active courses."""
    conn = get_connection()
    active_courses = conn.execute(
        "SELECT id FROM courses WHERE is_active = 1"
    ).fetchall()
    for c in active_courses:
        conn.execute(
            """INSERT OR IGNORE INTO course_enrollments
               (user_id, course_id, enrollment_status)
               VALUES (?, ?, 'Active')""",
            (user_id, c["id"]),
        )
    conn.commit()
    conn.close()


def get_user_by_username(username: str):
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        (username.strip().lower(),),
    ).fetchone()
    conn.close()
    return row


def is_admin(user_id: int) -> bool:
    conn = get_connection()
    row  = conn.execute(
        "SELECT is_admin FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return bool(row["is_admin"]) if row else False


def set_admin(user_id: int, admin: bool) -> None:
    conn = get_connection()
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?",
                 (int(admin), user_id))
    conn.commit()
    conn.close()


# ── Persistent session token helpers (cookie-based login) ────────────────────

#: How long a session token lives before expiring.  Adjust freely.
SESSION_TOKEN_DAYS = 30


def create_session_token(user_id: int,
                         days: int = SESSION_TOKEN_DAYS) -> str:
    """
    Generate a cryptographically-random session token, persist it in the DB,
    and return the token string so the caller can store it in a browser cookie.

    The cookie stores ONLY this opaque token — no passwords, no user data.
    """
    token      = secrets.token_urlsafe(48)          # 64-char URL-safe string
    expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
    conn = get_connection()
    conn.execute(
        "INSERT INTO user_sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at),
    )
    conn.commit()
    conn.close()
    return token


def validate_session_token(token: str) -> dict | None:
    """
    Look up a session token.  Returns a dict with ``id``, ``username``, and
    ``is_admin`` if the token exists AND has not expired; otherwise ``None``.
    An expired-but-present token is left in the DB for cleanup_expired_sessions().
    """
    if not token:
        return None
    conn = get_connection()
    row  = conn.execute(
        """
        SELECT u.id, u.username, u.is_admin
        FROM   user_sessions s
        JOIN   users u ON u.id = s.user_id
        WHERE  s.token = ?
          AND  datetime(s.expires_at) > datetime('now')
        """,
        (token,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session_token(token: str) -> None:
    """Remove a single session token (called on explicit logout)."""
    if not token:
        return
    conn = get_connection()
    conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def delete_all_sessions_for_user(user_id: int) -> None:
    """Invalidate every active session for a user (e.g. password change)."""
    conn = get_connection()
    conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def cleanup_expired_sessions() -> None:
    """Delete all expired rows from user_sessions.  Safe to call at any time."""
    try:
        conn = get_connection()
        conn.execute(
            "DELETE FROM user_sessions WHERE datetime(expires_at) <= datetime('now')"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Never let housekeeping crash the app


# ── Course helpers (global / shared) ─────────────────────────────────────────
def create_course(created_by_user_id: int, title: str,
                  description: str = "",
                  category: str = "") -> tuple:
    """
    Create a shared global course.
    Returns (course_id, None) on success.
    Returns (None, error_message) if a course with the same title already exists.
    After creation, auto-enrolls ALL existing users.
    """
    nt = _normalize_title(title)
    if not nt:
        return None, "Course title cannot be empty."

    conn = get_connection()
    # Check for active duplicate
    existing = conn.execute(
        "SELECT id, title FROM courses WHERE normalized_title = ? AND is_active = 1",
        (nt,),
    ).fetchone()
    if existing:
        conn.close()
        return None, (
            f'A course named **"{existing["title"]}"** already exists. '
            "Duplicate course titles are not allowed (comparison ignores "
            "capitalisation and extra spaces)."
        )

    cur = conn.execute(
        """INSERT INTO courses
           (created_by_user_id, title, normalized_title, description, category)
           VALUES (?, ?, ?, ?, ?)""",
        (created_by_user_id, title.strip(), nt,
         description.strip(), category.strip()),
    )
    cid = cur.lastrowid
    conn.commit()

    users = conn.execute("SELECT id FROM users").fetchall()
    for u in users:
        conn.execute(
            """INSERT OR IGNORE INTO course_enrollments
               (user_id, course_id, enrollment_status)
               VALUES (?, ?, 'Active')""",
            (u["id"], cid),
        )
    conn.commit()
    conn.close()
    return cid, None


def get_all_courses() -> list:
    """Return all active shared courses (global — not filtered by user)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM courses WHERE is_active = 1 ORDER BY title"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_courses_including_archived() -> list:
    """Return ALL courses — active and archived — for admin use."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM courses ORDER BY title").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_courses(user_id=None) -> list:
    """Backwards-compat alias — returns all active courses."""
    return get_all_courses()


def get_course(course_id: int):
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM courses WHERE id = ?", (course_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_course(course_id: int, title: str,
                  description: str, category: str) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE courses
           SET title = ?, normalized_title = ?, description = ?, category = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (title.strip(), _normalize_title(title),
         description.strip(), category.strip(), course_id),
    )
    conn.commit()
    conn.close()


def archive_course(course_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE courses SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?", (course_id,)
    )
    conn.commit()
    conn.close()


def restore_course(course_id: int) -> None:
    """Re-activate an archived course."""
    conn = get_connection()
    conn.execute(
        "UPDATE courses SET is_active = 1, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?", (course_id,)
    )
    conn.commit()
    conn.close()


def delete_course_if_safe(course_id: int) -> tuple:
    """
    Delete a course only if it has NO questions, materials, attempts, or enrollments.
    Returns (True, None) on success, (False, reason) if blocked.
    """
    conn = get_connection()
    q = conn.execute("SELECT COUNT(*) FROM questions WHERE course_id = ?",
                     (course_id,)).fetchone()[0]
    m = conn.execute("SELECT COUNT(*) FROM course_materials WHERE course_id = ?",
                     (course_id,)).fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM exam_attempts WHERE course_id = ?",
                     (course_id,)).fetchone()[0]
    e = conn.execute("SELECT COUNT(*) FROM course_enrollments WHERE course_id = ?",
                     (course_id,)).fetchone()[0]
    conn.close()
    if q or m or a or e:
        reasons = []
        if q: reasons.append(f"{q} question(s)")
        if m: reasons.append(f"{m} material(s)")
        if a: reasons.append(f"{a} attempt(s)")
        if e: reasons.append(f"{e} enrollment(s)")
        return False, "Cannot delete — course still has: " + ", ".join(reasons) + "."
    conn = get_connection()
    conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    conn.commit()
    conn.close()
    return True, None


def get_course_question_count(course_id: int) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE course_id = ?", (course_id,)
    ).fetchone()[0]
    conn.close()
    return n


# ── Duplicate-course detection and cleanup ────────────────────────────────────
def get_duplicate_course_groups() -> list:
    """
    Return a list of groups.  Each group is a list of course dicts that share
    the same normalized_title and are currently active.
    Only groups with 2+ courses are returned.
    """
    conn = get_connection()
    dup_nts = conn.execute(
        """SELECT normalized_title
           FROM courses
           WHERE is_active = 1 AND (normalized_title IS NOT NULL AND normalized_title != '')
           GROUP BY normalized_title
           HAVING COUNT(*) > 1"""
    ).fetchall()
    groups = []
    for row in dup_nts:
        courses = conn.execute(
            "SELECT * FROM courses WHERE normalized_title = ? AND is_active = 1 ORDER BY id",
            (row["normalized_title"],),
        ).fetchall()
        groups.append([dict(c) for c in courses])
    conn.close()
    return groups


def merge_into_course(keep_id: int, archive_ids: list) -> dict:
    """
    Move all questions / materials / attempts / enrollments from archive_ids
    to keep_id, then archive the duplicate courses.

    Materials with a normalized_title that already exists in keep_id are left
    in the duplicate (they disappear when it is archived) to avoid creating
    duplicates in the target course.

    Returns a summary dict.
    """
    conn = get_connection()
    summary = {"questions_moved": 0, "materials_moved": 0,
               "materials_skipped": 0, "attempts_moved": 0, "archived": 0}

    for dup_id in archive_ids:
        # questions
        q = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE course_id = ?", (dup_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE questions SET course_id = ? WHERE course_id = ?",
            (keep_id, dup_id),
        )
        summary["questions_moved"] += q

        # attempts
        a = conn.execute(
            "SELECT COUNT(*) FROM exam_attempts WHERE course_id = ?", (dup_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE exam_attempts SET course_id = ? WHERE course_id = ?",
            (keep_id, dup_id),
        )
        summary["attempts_moved"] += a

        # materials — only move if no title conflict
        mats = conn.execute(
            "SELECT * FROM course_materials WHERE course_id = ?", (dup_id,)
        ).fetchall()
        for mat in mats:
            nt = _normalize_title(mat["title"])
            conflict = conn.execute(
                "SELECT id FROM course_materials WHERE course_id = ? AND normalized_title = ?",
                (keep_id, nt),
            ).fetchone()
            if conflict:
                summary["materials_skipped"] += 1
            else:
                conn.execute(
                    "UPDATE course_materials SET course_id = ? WHERE id = ?",
                    (keep_id, mat["id"]),
                )
                summary["materials_moved"] += 1

        # material_progress
        conn.execute(
            "UPDATE material_progress SET course_id = ? WHERE course_id = ?",
            (keep_id, dup_id),
        )

        # archive
        conn.execute(
            "UPDATE courses SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?", (dup_id,)
        )
        summary["archived"] += 1

    conn.commit()
    conn.close()
    return summary


# ── Enrollment helpers ────────────────────────────────────────────────────────
ENROLLMENT_STATUSES = ["Active", "Completed", "Archived"]


def enroll_user(user_id: int, course_id: int) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO course_enrollments
           (user_id, course_id, enrollment_status, updated_at)
           VALUES (?, ?, 'Active', CURRENT_TIMESTAMP)
           ON CONFLICT(user_id, course_id)
           DO UPDATE SET enrollment_status = 'Active',
                         updated_at = CURRENT_TIMESTAMP""",
        (user_id, course_id),
    )
    conn.commit()
    conn.close()


def unenroll_user(user_id: int, course_id: int) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE course_enrollments
           SET enrollment_status = 'Archived', updated_at = CURRENT_TIMESTAMP
           WHERE user_id = ? AND course_id = ?""",
        (user_id, course_id),
    )
    conn.commit()
    conn.close()


def force_unenroll_all_from_course(course_id: int) -> tuple:
    """
    Admin-only: permanently delete ALL enrollment records for a course,
    regardless of status (Active, Archived, Completed, etc.).
    This clears ghost/stale records that block deletion.
    Returns (rows_deleted, None) on success, (0, error_message) on failure.
    """
    try:
        conn = get_connection()
        cur  = conn.execute(
            "DELETE FROM course_enrollments WHERE course_id = ?",
            (course_id,),
        )
        rows = cur.rowcount
        conn.commit()
        conn.close()
        return rows, None
    except Exception as exc:
        return 0, str(exc)


def get_course_enrollment_records(course_id: int) -> list:
    """
    Admin-only: return every enrollment row for a course (all statuses),
    joined with the username from users.
    Each dict has: enrollment_id, user_id, username, enrollment_status, enrolled_at.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT e.id   AS enrollment_id,
                  e.user_id,
                  u.username,
                  e.enrollment_status,
                  e.enrolled_at
           FROM course_enrollments e
           JOIN users u ON u.id = e.user_id
           WHERE e.course_id = ?
           ORDER BY e.enrollment_status, u.username""",
        (course_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def force_unenroll_users_from_course(course_id: int, user_ids: list) -> tuple:
    """
    Admin-only: permanently delete enrollment records for specific users.
    Returns (rows_deleted, None) on success, (0, error_message) on failure.
    """
    if not user_ids:
        return 0, None
    try:
        conn = get_connection()
        placeholders = ",".join("?" * len(user_ids))
        cur = conn.execute(
            f"DELETE FROM course_enrollments WHERE course_id = ? AND user_id IN ({placeholders})",
            [course_id, *user_ids],
        )
        rows = cur.rowcount
        conn.commit()
        conn.close()
        return rows, None
    except Exception as exc:
        return 0, str(exc)


def is_enrolled(user_id: int, course_id: int) -> bool:
    conn = get_connection()
    row  = conn.execute(
        """SELECT id FROM course_enrollments
           WHERE user_id = ? AND course_id = ? AND enrollment_status = 'Active'""",
        (user_id, course_id),
    ).fetchone()
    conn.close()
    return row is not None


def get_enrolled_courses(user_id: int) -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT c.* FROM courses c
           JOIN course_enrollments e ON c.id = e.course_id
           WHERE e.user_id = ? AND e.enrollment_status = 'Active'
             AND c.is_active = 1
           ORDER BY c.title""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_enrollment_stats(course_id: int) -> dict:
    conn = get_connection()
    total  = conn.execute(
        "SELECT COUNT(*) FROM course_enrollments WHERE course_id = ?",
        (course_id,),
    ).fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM course_enrollments "
        "WHERE course_id = ? AND enrollment_status = 'Active'",
        (course_id,),
    ).fetchone()[0]
    conn.close()
    return {"total_enrolled": total, "active_learners": active}


# ── Question helpers ──────────────────────────────────────────────────────────
def insert_questions(rows: list,
                     course_id=None) -> tuple:
    """
    Bulk-insert shared questions.

    Duplicate detection (in order):
    1. question_id UNIQUE constraint → skipped_id
    2. content_hash duplicate within same course → skipped_content

    Returns (inserted, skipped_id, skipped_content).
    """
    conn     = get_connection()
    inserted = skipped_id = skipped_content = 0

    for row in rows:
        r = dict(row)
        if course_id is not None:
            r["course_id"] = course_id
        elif "course_id" not in r:
            r["course_id"] = None

        # Ensure content_hash is present
        if not r.get("content_hash"):
            r["content_hash"] = _make_content_hash(
                r.get("stimulus", ""),
                r.get("choice_a", ""), r.get("choice_b", ""),
                r.get("choice_c", ""), r.get("choice_d", ""),
                r.get("choice_e", ""), r.get("correct_answer", ""),
            )

        # Check content_hash duplicate within this course
        if r["content_hash"] and r["course_id"] is not None:
            existing = conn.execute(
                "SELECT id FROM questions WHERE content_hash = ? AND course_id = ?",
                (r["content_hash"], r["course_id"]),
            ).fetchone()
            if existing:
                skipped_content += 1
                continue

        try:
            conn.execute(
                """INSERT INTO questions
                   (course_id, question_id, section_type, question_type, difficulty,
                    passage, stimulus, choice_a, choice_b, choice_c, choice_d, choice_e,
                    correct_answer, explanation,
                    wrong_answer_a, wrong_answer_b, wrong_answer_c,
                    wrong_answer_d, wrong_answer_e, source, tags, content_hash)
                   VALUES
                   (:course_id,:question_id,:section_type,:question_type,:difficulty,
                    :passage,:stimulus,:choice_a,:choice_b,:choice_c,:choice_d,:choice_e,
                    :correct_answer,:explanation,
                    :wrong_answer_a,:wrong_answer_b,:wrong_answer_c,
                    :wrong_answer_d,:wrong_answer_e,:source,:tags,:content_hash)""",
                r,
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped_id += 1

    conn.commit()
    conn.close()
    return inserted, skipped_id, skipped_content


def get_all_questions(
    section_type=None,
    question_type=None,
    min_difficulty: int = 1,
    max_difficulty: int = 5,
    course_id=None,
) -> list:
    conn   = get_connection()
    query  = "SELECT * FROM questions WHERE difficulty BETWEEN ? AND ?"
    params = [min_difficulty, max_difficulty]
    if course_id is not None:
        query += " AND course_id = ?"
        params.append(course_id)
    if section_type and section_type != "All":
        query += " AND section_type = ?"
        params.append(section_type)
    if question_type and question_type != "All":
        query += " AND question_type = ?"
        params.append(question_type)
    query += " ORDER BY RANDOM()"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_question_by_id(qid: int):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_question_count() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    return n


def _safe_delete_questions(conn: sqlite3.Connection, ids: list) -> None:
    """
    Internal helper: remove child rows that reference the given question IDs,
    then delete the questions themselves.

    Safety policy:
      - exam_attempts (aggregate score history) are PRESERVED — the attempt row
        keeps its totals so Score History is never broken.
      - user_answers rows referencing these questions are deleted (they are the
        per-question detail rows; the parent attempt row is untouched).
      - mistake_journal entries are deleted (they are review notes, not scores).
    """
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM user_answers    WHERE question_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM mistake_journal WHERE question_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM questions       WHERE id          IN ({placeholders})", ids)


def delete_question(qid: int) -> None:
    """Delete a single question and its child rows safely."""
    conn = get_connection()
    _safe_delete_questions(conn, [qid])
    conn.commit()
    conn.close()


def bulk_delete_questions(ids: list) -> int:
    """
    Delete a list of question IDs in one transaction.
    Returns the number of questions actually deleted.
    Also cleans up user_answers and mistake_journal child rows so that
    foreign-key constraints are satisfied and no orphaned data is left.
    exam_attempts are preserved — aggregate scores are unaffected.
    """
    if not ids:
        return 0
    # Only count IDs that actually exist before we delete them
    conn = get_connection()
    placeholders = ",".join("?" * len(ids))
    existing = conn.execute(
        f"SELECT COUNT(*) FROM questions WHERE id IN ({placeholders})", ids
    ).fetchone()[0]
    _safe_delete_questions(conn, ids)
    conn.commit()
    conn.close()
    return existing


def get_distinct_values(column: str, course_id=None) -> list:
    allowed = {"section_type", "question_type", "difficulty", "source"}
    if column not in allowed:
        return []
    conn   = get_connection()
    query  = (f"SELECT DISTINCT {column} FROM questions "
               f"WHERE {column} IS NOT NULL")
    params = []
    if course_id is not None:
        query += " AND course_id = ?"
        params.append(course_id)
    query += f" ORDER BY {column}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [str(r[0]) for r in rows]


# ── Exam attempt helpers ──────────────────────────────────────────────────────
def create_attempt(user_id: int, mode: str, section_type: str,
                   settings_snapshot: dict, is_hard_mode: bool = False,
                   course_id=None) -> int:
    conn = get_connection()
    cur  = conn.execute(
        """INSERT INTO exam_attempts
           (user_id, course_id, mode, section_type, settings_json, is_hard_mode)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, course_id, mode, section_type,
         json.dumps(settings_snapshot), int(is_hard_mode)),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def complete_attempt(attempt_id: int, total: int, correct: int,
                     section_scores: dict) -> None:
    pct  = round(correct / total * 100, 1) if total else 0
    conn = get_connection()
    conn.execute(
        """UPDATE exam_attempts
           SET completed_at = CURRENT_TIMESTAMP,
               total_questions = ?, correct_answers = ?,
               raw_score = ?, percent_correct = ?,
               section_scores_json = ?
           WHERE id = ?""",
        (total, correct, correct, pct, json.dumps(section_scores), attempt_id),
    )
    conn.commit()
    conn.close()


def save_answer(attempt_id: int, question_id: int, selected: str,
                is_correct: bool, time_spent: float,
                is_flagged: bool, section_num: int) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO user_answers
           (attempt_id, question_id, selected_answer, is_correct,
            time_spent_seconds, is_flagged, section_number)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (attempt_id, question_id, selected, int(is_correct),
         round(time_spent, 2), int(is_flagged), section_num),
    )
    conn.commit()
    conn.close()


def get_attempts(user_id: int, limit: int = 50,
                 course_id=None) -> list:
    conn   = get_connection()
    query  = ("SELECT * FROM exam_attempts "
               "WHERE user_id = ? AND completed_at IS NOT NULL")
    params = [user_id]
    if course_id is not None:
        query += " AND course_id = ?"
        params.append(course_id)
    query += " ORDER BY completed_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_attempt_answers(attempt_id: int) -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT ua.*, q.stimulus, q.choice_a, q.choice_b, q.choice_c,
                  q.choice_d, q.choice_e, q.correct_answer, q.explanation,
                  q.section_type, q.question_type, q.difficulty, q.passage,
                  q.wrong_answer_a, q.wrong_answer_b, q.wrong_answer_c,
                  q.wrong_answer_d, q.wrong_answer_e
           FROM user_answers ua
           JOIN questions q ON ua.question_id = q.id
           WHERE ua.attempt_id = ?
           ORDER BY ua.id""",
        (attempt_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Settings helpers ──────────────────────────────────────────────────────────
_DEFAULTS = {
    "hard_mode":              "false",
    "section_time_minutes":   "35",
    "hard_mode_time_minutes": "30",
    "min_difficulty":         "1",
    "max_difficulty":         "5",
    "show_explanations":      "always",
    "question_mix":           "balanced",
}


def get_setting(user_id: int, key: str) -> str:
    conn = get_connection()
    row  = conn.execute(
        "SELECT value FROM settings WHERE user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    conn.close()
    return row["value"] if row else _DEFAULTS.get(key, "")


def set_setting(user_id: int, key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
        (user_id, key, str(value)),
    )
    conn.commit()
    conn.close()


def get_all_settings(user_id: int) -> dict:
    result = dict(_DEFAULTS)
    conn   = get_connection()
    rows   = conn.execute(
        "SELECT key, value FROM settings WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    for r in rows:
        result[r["key"]] = r["value"]
    return result


def get_app_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_app_setting(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO app_settings (key, value, updated_at)
           VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(key) DO UPDATE SET
             value = excluded.value,
             updated_at = CURRENT_TIMESTAMP""",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_app_settings(keys: list[str] | None = None) -> dict:
    conn = get_connection()
    if keys:
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
    else:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    conn.close()
    found = {r["key"]: r["value"] for r in rows}
    if keys:
        return {key: found.get(key, "") for key in keys}
    return found


# ── Mistake journal helpers ───────────────────────────────────────────────────
def add_to_journal(user_id: int, question_id: int,
                   attempt_id, note: str = "") -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO mistake_journal (user_id, question_id, attempt_id, note)
           VALUES (?, ?, ?, ?)""",
        (user_id, question_id, attempt_id, note),
    )
    conn.commit()
    conn.close()


def get_mistake_journal(user_id: int, course_id=None) -> list:
    conn   = get_connection()
    query  = """
        SELECT mj.*, q.stimulus, q.section_type, q.question_type,
               q.difficulty, q.correct_answer, q.explanation,
               q.choice_a, q.choice_b, q.choice_c, q.choice_d, q.choice_e,
               q.course_id as q_course_id
        FROM mistake_journal mj
        JOIN questions q ON mj.question_id = q.id
        WHERE mj.user_id = ?"""
    params = [user_id]
    if course_id is not None:
        query += " AND q.course_id = ?"
        params.append(course_id)
    query += " ORDER BY mj.created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_journal_entry(entry_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM mistake_journal WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()


# ── Analytics raw queries ─────────────────────────────────────────────────────
def get_answer_stats(user_id: int, course_id=None) -> list:
    conn   = get_connection()
    query  = """
        SELECT ua.is_correct, ua.time_spent_seconds, ua.is_flagged,
               q.section_type, q.question_type, q.difficulty,
               ea.mode, ea.completed_at, ea.course_id
        FROM user_answers ua
        JOIN exam_attempts ea ON ua.attempt_id = ea.id
        JOIN questions q      ON ua.question_id = q.id
        WHERE ea.user_id = ? AND ea.completed_at IS NOT NULL"""
    params = [user_id]
    if course_id is not None:
        query += " AND ea.course_id = ?"
        params.append(course_id)
    query += " ORDER BY ea.completed_at"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Course materials helpers (shared) ─────────────────────────────────────────
MATERIAL_TYPES = [
    "Reading",
    "Video",
    "Link",
    "Notes",
    "PDF/Document Link",
    "Other",
]

MATERIAL_SECTIONS = [
    "Syllabus",
    "Module",
]


def _ensure_material_modules(course_id: int, conn: sqlite3.Connection | None = None) -> None:
    """Seed module rows from existing material module names."""
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        module_count = conn.execute(
            "SELECT COUNT(*) FROM course_modules WHERE course_id = ?",
            (course_id,),
        ).fetchone()[0]
        if module_count:
            return
        existing = {
            r["normalized_name"]
            for r in conn.execute(
                """SELECT normalized_name FROM course_modules
                   WHERE course_id = ? AND (is_active IS NULL OR is_active = 1)""",
                (course_id,),
            ).fetchall()
        }
        max_order = conn.execute(
            "SELECT COALESCE(MAX(display_order), -1) FROM course_modules WHERE course_id = ?",
            (course_id,),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT DISTINCT module_name FROM course_materials
               WHERE course_id = ?
                 AND (is_active IS NULL OR is_active = 1)
                 AND COALESCE(material_section, 'Module') = 'Module'
                 AND TRIM(COALESCE(module_name, '')) <> ''
               ORDER BY module_name""",
            (course_id,),
        ).fetchall()
        for row in rows:
            name = (row["module_name"] or "").strip()
            nt = _normalize_title(name)
            if not nt or nt in existing:
                continue
            max_order += 1
            conn.execute(
                """INSERT INTO course_modules
                   (course_id, name, normalized_name, display_order, is_active)
                   VALUES (?, ?, ?, ?, 1)""",
                (course_id, name, nt, max_order),
            )
            existing.add(nt)
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def get_course_modules(course_id: int) -> list:
    _ensure_material_modules(course_id)
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM course_modules
           WHERE course_id = ? AND (is_active IS NULL OR is_active = 1)
           ORDER BY display_order ASC, created_at ASC, name ASC""",
        (course_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def replace_course_modules(course_id: int, module_names: list[str]) -> tuple:
    cleaned = []
    seen = set()
    for name in module_names:
        clean = " ".join(str(name or "").strip().split())
        nt = _normalize_title(clean)
        if not clean or nt in seen:
            continue
        cleaned.append((clean, nt))
        seen.add(nt)

    conn = get_connection()
    existing_rows = conn.execute(
        "SELECT id, normalized_name FROM course_modules WHERE course_id = ?",
        (course_id,),
    ).fetchall()
    existing = {r["normalized_name"]: r["id"] for r in existing_rows}

    for order, (name, nt) in enumerate(cleaned):
        if nt in existing:
            conn.execute(
                """UPDATE course_modules
                   SET name = ?, display_order = ?, is_active = 1,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (name, order, existing[nt]),
            )
        else:
            conn.execute(
                """INSERT INTO course_modules
                   (course_id, name, normalized_name, display_order, is_active)
                   VALUES (?, ?, ?, ?, 1)""",
                (course_id, name, nt, order),
            )

    if cleaned:
        placeholders = ",".join("?" for _ in cleaned)
        conn.execute(
            f"""UPDATE course_modules
                SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE course_id = ? AND normalized_name NOT IN ({placeholders})""",
            [course_id] + [nt for _, nt in cleaned],
        )
    else:
        conn.execute(
            """UPDATE course_modules
               SET is_active = 0, updated_at = CURRENT_TIMESTAMP
               WHERE course_id = ?""",
            (course_id,),
        )

    conn.commit()
    conn.close()
    return True, None


def create_material(course_id: int, title: str,
                    material_type: str, content_text: str = "",
                    external_url: str = "", notes: str = "",
                    created_by_user_id=None,
                    display_order: int = 0,
                    estimated_minutes: int = 0,
                    is_active: int = 1,
                    material_section: str = "Module",
                    module_name: str = "") -> tuple:
    """
    Create a shared course material.
    Returns (material_id, None) on success.
    Returns (None, error_message) if a duplicate title exists in this course.
    """
    nt = _normalize_title(title)
    if not nt:
        return None, "Material title cannot be empty."

    conn = get_connection()
    # Check for duplicate title in same course
    existing = conn.execute(
        """SELECT id, title FROM course_materials
           WHERE course_id = ? AND normalized_title = ?
             AND (is_active IS NULL OR is_active = 1)""",
        (course_id, nt),
    ).fetchone()
    if existing:
        conn.close()
        return None, (
            f'A material titled **"{existing["title"]}"** already exists '
            "in this course. Please use a different title."
        )

    cur = conn.execute(
        """INSERT INTO course_materials
           (course_id, created_by_user_id, title, normalized_title,
            material_type, content_text, external_url, notes,
            material_section, module_name,
            display_order, estimated_minutes, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (course_id, created_by_user_id, title.strip(), nt,
         material_type, content_text, external_url.strip(), notes,
         material_section if material_section in MATERIAL_SECTIONS else "Module",
         module_name.strip(),
         display_order, estimated_minutes, is_active),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid, None


def get_materials(course_id: int) -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM course_materials
           WHERE course_id = ? AND (is_active IS NULL OR is_active = 1)
           ORDER BY
             CASE COALESCE(material_section, 'Module')
               WHEN 'Syllabus' THEN 0
               WHEN 'Module' THEN 1
               ELSE 2
             END,
             COALESCE(module_name, '') ASC,
             display_order ASC,
             created_at ASC""",
        (course_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_material(material_id: int, title: str, material_type: str,
                    content_text: str, external_url: str, notes: str,
                    display_order: int = 0,
                    estimated_minutes: int = 0,
                    material_section: str = "Module",
                    module_name: str = "") -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE course_materials
           SET title = ?, normalized_title = ?, material_type = ?,
               content_text = ?, external_url = ?, notes = ?,
               material_section = ?, module_name = ?,
               display_order = ?, estimated_minutes = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (title.strip(), _normalize_title(title), material_type, content_text,
         external_url.strip(), notes,
         material_section if material_section in MATERIAL_SECTIONS else "Module",
         module_name.strip(), display_order, estimated_minutes, material_id),
    )
    conn.commit()
    conn.close()


def archive_material(material_id: int) -> None:
    """Soft-archive a material (hides it without deleting)."""
    conn = get_connection()
    conn.execute(
        "UPDATE course_materials SET is_active = 0, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (material_id,),
    )
    conn.commit()
    conn.close()


def delete_material(material_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM material_progress WHERE material_id = ?", (material_id,))
    conn.execute("DELETE FROM course_materials WHERE id = ?", (material_id,))
    conn.commit()
    conn.close()


def set_material_progress(user_id: int, material_id: int,
                           course_id: int, status: str) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO material_progress
           (user_id, material_id, course_id, status, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id, material_id)
           DO UPDATE SET status = excluded.status,
                         updated_at = CURRENT_TIMESTAMP""",
        (user_id, material_id, course_id, status),
    )
    conn.commit()
    conn.close()


def get_material_progress(user_id: int, course_id: int) -> dict:
    conn = get_connection()
    rows = conn.execute(
        """SELECT material_id, status FROM material_progress
           WHERE user_id = ? AND course_id = ?""",
        (user_id, course_id),
    ).fetchall()
    conn.close()
    return {r["material_id"]: r["status"] for r in rows}


# ── Security question helpers ─────────────────────────────────────────────────
def set_security_question(user_id: int, question: str,
                           answer_hash: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE users SET security_question = ?, security_answer_hash = ? "
        "WHERE id = ?",
        (question.strip(), answer_hash, user_id),
    )
    conn.commit()
    conn.close()


def get_security_question(username: str):
    conn = get_connection()
    row  = conn.execute(
        "SELECT security_question FROM users WHERE username = ?",
        (username.strip().lower(),),
    ).fetchone()
    conn.close()
    return row["security_question"] if row and row["security_question"] else None


def verify_security_answer(username: str, answer_hash: str) -> bool:
    conn = get_connection()
    row  = conn.execute(
        "SELECT security_answer_hash FROM users WHERE username = ?",
        (username.strip().lower(),),
    ).fetchone()
    conn.close()
    if not row or not row["security_answer_hash"]:
        return False
    return row["security_answer_hash"] == answer_hash


def reset_password(username: str, new_password_hash: str) -> bool:
    conn = get_connection()
    cur  = conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (new_password_hash, username.strip().lower()),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ═══════════════════════════════════════════════════════════════════════════════
# CURRICULUM SYSTEM — Added in StudyForge v3
# ═══════════════════════════════════════════════════════════════════════════════
# Tables:
#   curriculums              — top-level curriculum objects
#   curriculum_courses       — many-to-many: curriculum ↔ course
#   curriculum_weight_presets— saved weight distributions per curriculum
#
# Design principles:
#   - Courses remain global; adding to a curriculum does NOT move or hide them.
#   - A course cannot appear twice in the same curriculum (UNIQUE constraint).
#   - Presets are curriculum-scoped; one curriculum can have many presets.
# ═══════════════════════════════════════════════════════════════════════════════


def init_curriculum_tables() -> None:
    """Create curriculum-related tables if they don't exist. Safe to re-run."""
    conn = get_connection()
    conn.executescript("""
    -- ── Curriculums ──────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS curriculums (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        created_by_user_id  INTEGER,
        title               TEXT NOT NULL,
        normalized_title    TEXT DEFAULT '',
        description         TEXT DEFAULT '',
        is_active           INTEGER DEFAULT 1,
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── Curriculum ↔ Course junction ─────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS curriculum_courses (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        curriculum_id   INTEGER NOT NULL,
        course_id       INTEGER NOT NULL,
        display_order   INTEGER DEFAULT 0,
        added_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(curriculum_id, course_id),
        FOREIGN KEY (curriculum_id) REFERENCES curriculums(id),
        FOREIGN KEY (course_id)     REFERENCES courses(id)
    );

    -- ── Saved weighting presets ───────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS curriculum_weight_presets (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        curriculum_id   INTEGER NOT NULL,
        name            TEXT    NOT NULL,
        weights_json    TEXT    DEFAULT '{}',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (curriculum_id) REFERENCES curriculums(id)
    );
    """)
    conn.commit()
    conn.close()


# ── Curriculum CRUD ───────────────────────────────────────────────────────────

def create_curriculum(created_by_user_id: int, title: str,
                      description: str = "") -> tuple:
    """
    Create a new curriculum.
    Returns (curriculum_id, None) on success.
    Returns (None, error_message) if a curriculum with the same title exists.
    """
    init_curriculum_tables()
    nt = _normalize_title(title)
    if not nt:
        return None, "Curriculum title cannot be empty."

    conn = get_connection()
    existing = conn.execute(
        "SELECT id, title FROM curriculums WHERE normalized_title = ? AND is_active = 1",
        (nt,),
    ).fetchone()
    if existing:
        conn.close()
        return None, (
            f'A curriculum named **"{existing["title"]}"** already exists. '
            "Please choose a different name."
        )
    cur = conn.execute(
        """INSERT INTO curriculums
           (created_by_user_id, title, normalized_title, description)
           VALUES (?, ?, ?, ?)""",
        (created_by_user_id, title.strip(), nt, description.strip()),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid, None


def get_all_curriculums() -> list:
    """Return all active curriculums."""
    init_curriculum_tables()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM curriculums WHERE is_active = 1 ORDER BY title"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_curriculum(curriculum_id: int):
    """Return a single curriculum dict, or None if not found."""
    init_curriculum_tables()
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM curriculums WHERE id = ?", (curriculum_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_curriculum(curriculum_id: int, title: str, description: str) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE curriculums
           SET title = ?, normalized_title = ?, description = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (title.strip(), _normalize_title(title), description.strip(), curriculum_id),
    )
    conn.commit()
    conn.close()


def delete_curriculum(curriculum_id: int) -> tuple:
    """
    Permanently delete a curriculum and all its course associations and presets.
    Returns (True, None) on success.
    """
    init_curriculum_tables()
    conn = get_connection()
    conn.execute("DELETE FROM curriculum_courses WHERE curriculum_id = ?", (curriculum_id,))
    conn.execute("DELETE FROM curriculum_weight_presets WHERE curriculum_id = ?", (curriculum_id,))
    conn.execute("DELETE FROM curriculums WHERE id = ?", (curriculum_id,))
    conn.commit()
    conn.close()
    return True, None


def archive_curriculum(curriculum_id: int) -> None:
    """Soft-archive a curriculum (hides it without deleting)."""
    conn = get_connection()
    conn.execute(
        "UPDATE curriculums SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (curriculum_id,),
    )
    conn.commit()
    conn.close()


# ── Curriculum ↔ Course management ───────────────────────────────────────────

def add_course_to_curriculum(curriculum_id: int, course_id: int) -> tuple:
    """
    Add a course to a curriculum.
    Returns (True, None) on success.
    Returns (False, error_message) if course is already in this curriculum.
    """
    init_curriculum_tables()
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM curriculum_courses WHERE curriculum_id = ? AND course_id = ?",
        (curriculum_id, course_id),
    ).fetchone()
    if existing:
        conn.close()
        return False, "This course is already in the curriculum."
    # Get next display_order
    max_order = conn.execute(
        "SELECT COALESCE(MAX(display_order), -1) FROM curriculum_courses WHERE curriculum_id = ?",
        (curriculum_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO curriculum_courses (curriculum_id, course_id, display_order) VALUES (?, ?, ?)",
        (curriculum_id, course_id, max_order + 1),
    )
    conn.commit()
    conn.close()
    return True, None


def remove_course_from_curriculum(curriculum_id: int, course_id: int) -> None:
    """Remove a course from a curriculum."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM curriculum_courses WHERE curriculum_id = ? AND course_id = ?",
        (curriculum_id, course_id),
    )
    conn.commit()
    conn.close()


def get_curriculum_courses(curriculum_id: int) -> list:
    """Return full course dicts for all courses in a curriculum, in display order."""
    init_curriculum_tables()
    conn = get_connection()
    rows = conn.execute(
        """SELECT c.*, cc.display_order, cc.added_at as cc_added_at
           FROM curriculum_courses cc
           JOIN courses c ON cc.course_id = c.id
           WHERE cc.curriculum_id = ? AND c.is_active = 1
           ORDER BY cc.display_order ASC, cc.added_at ASC""",
        (curriculum_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_courses_not_in_curriculum(curriculum_id: int) -> list:
    """Return active courses that are NOT yet in the given curriculum."""
    init_curriculum_tables()
    conn = get_connection()
    rows = conn.execute(
        """SELECT c.* FROM courses c
           WHERE c.is_active = 1
             AND c.id NOT IN (
                 SELECT course_id FROM curriculum_courses WHERE curriculum_id = ?
             )
           ORDER BY c.title""",
        (curriculum_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reorder_curriculum_courses(curriculum_id: int, ordered_course_ids: list) -> None:
    """Update display_order for courses in a curriculum."""
    conn = get_connection()
    for i, cid in enumerate(ordered_course_ids):
        conn.execute(
            "UPDATE curriculum_courses SET display_order = ? WHERE curriculum_id = ? AND course_id = ?",
            (i, curriculum_id, cid),
        )
    conn.commit()
    conn.close()


# ── Weight preset CRUD ────────────────────────────────────────────────────────

def create_weight_preset(curriculum_id: int, name: str,
                          weights: dict) -> tuple:
    """
    Save a new weighting preset for a curriculum.
    weights: dict mapping course_id (int) → weight_pct (float).
    Returns (preset_id, None) or (None, error_message).
    """
    init_curriculum_tables()
    if not name.strip():
        return None, "Preset name cannot be empty."
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO curriculum_weight_presets (curriculum_id, name, weights_json)
           VALUES (?, ?, ?)""",
        (curriculum_id, name.strip(), json.dumps(weights)),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid, None


def get_weight_presets(curriculum_id: int) -> list:
    """Return all saved weight presets for a curriculum."""
    init_curriculum_tables()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM curriculum_weight_presets WHERE curriculum_id = ? ORDER BY name",
        (curriculum_id,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["weights"] = json.loads(d["weights_json"] or "{}")
        except Exception:
            d["weights"] = {}
        result.append(d)
    return result


def update_weight_preset(preset_id: int, name: str, weights: dict) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE curriculum_weight_presets
           SET name = ?, weights_json = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (name.strip(), json.dumps(weights), preset_id),
    )
    conn.commit()
    conn.close()


def delete_weight_preset(preset_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM curriculum_weight_presets WHERE id = ?", (preset_id,))
    conn.commit()
    conn.close()


# ── Multi-course question helpers for curriculum exams ────────────────────────

def get_questions_for_courses(course_ids: list,
                               min_difficulty: int = 1,
                               max_difficulty: int = 5) -> dict:
    """
    Return a dict mapping course_id → list of question dicts.
    Used by the curriculum exam builder to pull questions per course.
    """
    if not course_ids:
        return {}
    result = {}
    for cid in course_ids:
        result[cid] = get_all_questions(
            min_difficulty=min_difficulty,
            max_difficulty=max_difficulty,
            course_id=cid,
        )
    return result


def get_curriculum_question_counts(curriculum_id: int) -> dict:
    """
    Return a dict mapping course_id → question_count for all courses
    in the given curriculum.
    """
    init_curriculum_tables()
    courses = get_curriculum_courses(curriculum_id)
    return {c["id"]: get_course_question_count(c["id"]) for c in courses}



# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

def init_feedback_tables() -> None:
    """Create the feedback_items table if it does not exist. Safe to re-run."""
    conn = get_connection()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS feedback_items (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        feedback_type   TEXT    DEFAULT 'Other',
        title           TEXT    NOT NULL,
        description     TEXT    NOT NULL,
        area            TEXT    DEFAULT '',
        user_priority   TEXT    DEFAULT 'Medium',
        admin_priority  TEXT    DEFAULT 'Medium',
        status          TEXT    DEFAULT 'New',
        is_implemented  INTEGER DEFAULT 0,
        admin_notes     TEXT    DEFAULT '',
        implemented_at  TIMESTAMP,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)
    conn.commit()
    conn.close()


def create_feedback_item(
    user_id: int,
    feedback_type: str,
    title: str,
    description: str,
    area: str = "",
    user_priority: str = "Medium",
) -> tuple:
    """
    Insert a new feedback item.
    Returns (feedback_id, None) on success or (None, error_message) on failure.
    """
    init_feedback_tables()
    if not title.strip():
        return None, "Title cannot be empty."
    if not description.strip():
        return None, "Description cannot be empty."
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO feedback_items
               (user_id, feedback_type, title, description, area, user_priority)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, feedback_type, title.strip(), description.strip(),
             area.strip(), user_priority),
        )
        fid = cur.lastrowid
        conn.commit()
        return fid, None
    except Exception as exc:
        return None, str(exc)
    finally:
        conn.close()


def get_user_feedback(user_id: int) -> list:
    """Return all feedback items submitted by a specific user, newest first."""
    init_feedback_tables()
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM feedback_items
           WHERE user_id = ?
           ORDER BY created_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_feedback(
    status: str | None = None,
    feedback_type: str | None = None,
    priority: str | None = None,
    implemented: bool | None = None,
    search: str | None = None,
) -> list:
    """
    Return feedback items for admin review with optional filters.
    Joins with users table to include the submitter's username.
    """
    init_feedback_tables()
    conn = get_connection()

    query = """
        SELECT f.*, u.username
        FROM feedback_items f
        JOIN users u ON f.user_id = u.id
        WHERE 1=1
    """
    params: list = []

    if status:
        query += " AND f.status = ?"
        params.append(status)
    if feedback_type:
        query += " AND f.feedback_type = ?"
        params.append(feedback_type)
    if priority:
        query += " AND f.user_priority = ?"
        params.append(priority)
    if implemented is not None:
        query += " AND f.is_implemented = ?"
        params.append(1 if implemented else 0)
    if search:
        like = f"%{search}%"
        query += " AND (f.title LIKE ? OR f.description LIKE ? OR u.username LIKE ?)"
        params.extend([like, like, like])

    query += " ORDER BY f.created_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_feedback_item(
    feedback_id: int,
    status: str,
    admin_priority: str,
    is_implemented: bool,
    admin_notes: str,
    implemented_at: str | None = None,
) -> None:
    """
    Admin update: status, priority, implemented flag, notes, and optional date.
    If is_implemented is True and no implemented_at is provided, use now.
    """
    init_feedback_tables()
    conn = get_connection()

    # Auto-set implemented_at if marking as implemented and no date given
    if is_implemented and not implemented_at:
        from datetime import datetime
        implemented_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # If un-marking implemented, clear the date
    if not is_implemented:
        implemented_at = None

    conn.execute(
        """UPDATE feedback_items
           SET status          = ?,
               admin_priority  = ?,
               is_implemented  = ?,
               admin_notes     = ?,
               implemented_at  = ?,
               updated_at      = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (status, admin_priority, 1 if is_implemented else 0,
         admin_notes.strip(), implemented_at, feedback_id),
    )
    conn.commit()
    conn.close()


def get_feedback_metrics() -> dict:
    """Return aggregate counts for admin dashboard metrics."""
    init_feedback_tables()
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COUNT(*)                                                        AS total,
            COALESCE(SUM(CASE WHEN status = 'New'         THEN 1 ELSE 0 END), 0) AS new_count,
            COALESCE(SUM(CASE WHEN status IN ('In Progress','Planned')
                                                 THEN 1 ELSE 0 END), 0) AS active_count,
            COALESCE(SUM(CASE WHEN status = 'Implemented' THEN 1 ELSE 0 END), 0) AS implemented_count,
            COALESCE(SUM(CASE WHEN status IN ('Rejected','Duplicate')
                                                 THEN 1 ELSE 0 END), 0) AS closed_count
        FROM feedback_items
    """).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"total": 0, "new_count": 0, "active_count": 0,
            "implemented_count": 0, "closed_count": 0}
