"""One-time cleanup for the CFA Level I Corporate Issuers question bank."""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "lsat_app.db"
BACKUP_DIR = Path.home() / "AppData" / "Local" / "Temp"

V2_SOURCES = (
    "LM1CORPISS25V2",
    "LM2CORPISS25V2",
    "LM3CORPISS25V2",
    "LM4CORPISS25V2",
    "LM5CORPISS25V2",
)
ORIGINAL_SOURCES = (
    "CFA25MOD1QM",
    "CFA25MOD2QM",
    "CFA25MOD3QM",
    "CFA25MOD4WL",
    "CFA25MOD5CI",
)
MALFORMED_IDS = (1083, 1087, 1167, 1175, 1177, 1202)


def content_hash(question: dict[str, str]) -> str:
    fields = (
        "section_type",
        "question_type",
        "passage",
        "stimulus",
        "choice_a",
        "choice_b",
        "choice_c",
        "choice_d",
        "choice_e",
    )
    raw = "||".join(str(question.get(field, "") or "").strip() for field in fields)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


REPAIRS = {
    1008: {
        "stimulus": (
            "Which partnership structure has at least one general partner with "
            "unlimited liability and one or more limited partners whose liability "
            "is generally limited to their investment?"
        ),
        "choice_a": "General partnership",
        "choice_b": "Limited partnership",
        "choice_c": "Limited liability partnership",
        "choice_d": "Sole proprietorship",
        "choice_e": "Corporation",
        "correct_answer": "B",
        "explanation": (
            "A limited partnership has at least one general partner with unlimited "
            "liability and one or more limited partners with limited liability."
        ),
        "wrong_answer_a": (
            "In a general partnership, the partners generally have unlimited liability."
        ),
        "wrong_answer_b": "Correct.",
        "wrong_answer_c": (
            "A limited liability partnership generally provides liability protection "
            "to all partners."
        ),
        "wrong_answer_d": "A sole proprietorship has one owner and is not a partnership.",
        "wrong_answer_e": "A corporation is a separate legal entity, not a partnership.",
    },
    1010: {
        "stimulus": (
            "For a taxable corporation that distributes after-tax earnings as "
            "dividends, what is the principal tax disadvantage?"
        ),
        "choice_a": "The corporation cannot retain earnings",
        "choice_b": "Distributed earnings may be taxed at both corporate and shareholder levels",
        "choice_c": "Shareholders have unlimited liability",
        "choice_d": "The corporation cannot issue equity",
        "choice_e": "All corporate losses pass directly to shareholders",
        "correct_answer": "B",
        "explanation": (
            "A taxable corporation pays tax on its earnings, and shareholders may "
            "also pay tax when after-tax earnings are distributed as dividends. "
            "This is commonly called double taxation."
        ),
        "wrong_answer_a": "Corporations may retain earnings.",
        "wrong_answer_b": "Correct.",
        "wrong_answer_c": "Corporate shareholders generally have limited liability.",
        "wrong_answer_d": "Corporations can issue equity.",
        "wrong_answer_e": (
            "Loss pass-through is associated with pass-through structures, not a "
            "taxable corporation."
        ),
    },
    1017: {
        "stimulus": (
            "A corporation earns $100 million in pre-tax income. If the corporate "
            "tax rate is 21%, what is the corporate tax paid in millions?"
        ),
        "choice_a": "19",
        "choice_b": "20",
        "choice_c": "21",
        "choice_d": "79",
        "choice_e": "121",
        "correct_answer": "C",
        "explanation": (
            "Corporate tax paid = $100 million x 21% = $21 million."
        ),
        "wrong_answer_a": "This understates $100 million x 21%.",
        "wrong_answer_b": "This uses a 20% tax rate rather than 21%.",
        "wrong_answer_c": "Correct.",
        "wrong_answer_d": "This is after-tax income, not tax paid.",
        "wrong_answer_e": "This adds tax to pre-tax income.",
    },
    1229: {
        "stimulus": (
            "A firm faces an effective tax rate of 22%. It earns 8830 in operating "
            "profit. Average long-term debt is 25475. If the firm's ROIC is exactly "
            "9.50%, what is the average equity capital, rounded to the nearest whole number?"
        ),
        "choice_a": "42332",
        "choice_b": "37628",
        "choice_c": "47024",
        "choice_d": "51739",
        "choice_e": "58794",
        "correct_answer": "C",
        "explanation": (
            "After-tax operating profit is 8830 x (1 - 22%) = 6887.4. "
            "Total invested capital is 6887.4 / 9.50% = 72498.95. "
            "Average equity capital is 72498.95 - 25475 = 47023.95, or 47024."
        ),
        "wrong_answer_a": "This understates the equity capital implied by the target ROIC.",
        "wrong_answer_b": "This understates the equity capital implied by the target ROIC.",
        "wrong_answer_c": "Correct.",
        "wrong_answer_d": "This overstates the equity capital implied by the target ROIC.",
        "wrong_answer_e": "This overstates the equity capital implied by the target ROIC.",
    },
}


REPORT_RESOLUTIONS = {
    24: "Corrected and restored: the answer is limited partnership.",
    25: "Corrected and restored: the tax disadvantage is double taxation.",
    26: "Confirmed ambiguous because multiple structures can be pass-through entities; kept archived.",
    27: "Confirmed invalid: 87% of $38 billion is $33.06 billion, which was absent; retired with V2 batch.",
    28: "Confirmed dependent on a missing prior question; kept archived.",
    29: "Confirmed invalid: $115 million - $24.2 million = $90.8 million, which was absent; retired with V2 batch.",
    30: "Duplicate report; confirmed invalid and retired with V2 batch.",
    31: "Corrected and restored: $100 million x 21% = $21 million.",
    32: "Confirmed explanation metadata failure; retired with V2 batch.",
}


def archive(conn: sqlite3.Connection, ids: list[int], reason: str) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(
        f"""
        UPDATE questions
        SET is_archived = 1,
            archived_at = CURRENT_TIMESTAMP,
            archive_reason = ?
        WHERE id IN ({placeholders}) AND COALESCE(is_archived, 0) = 0
        """,
        [reason, *ids],
    )
    return cursor.rowcount


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"lsat_app_before_corporate_issuers_cleanup_{stamp}.db"
    shutil.copy2(DB_PATH, backup)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        v2_placeholders = ",".join("?" for _ in V2_SOURCES)
        v2_ids = [
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM questions WHERE course_id = 9 AND source IN ({v2_placeholders})",
                V2_SOURCES,
            )
        ]
        archived_v2 = archive(
            conn,
            v2_ids,
            "Corporate Issuers audit: unreliable V2 transformed question batch",
        )

        original_placeholders = ",".join("?" for _ in ORIGINAL_SOURCES)
        dependency_ids = [
            row["id"]
            for row in conn.execute(
                f"""
                SELECT id, stimulus
                FROM questions
                WHERE course_id = 9 AND source IN ({original_placeholders})
                """,
                ORIGINAL_SOURCES,
            )
            if re.search(r"\bQuestion \d+\b|previous question", row["stimulus"] or "", re.I)
        ]
        archived_dependencies = archive(
            conn,
            dependency_ids,
            "Corporate Issuers audit: requires missing prior-question context",
        )
        archived_malformed = archive(
            conn,
            list(MALFORMED_IDS),
            "Corporate Issuers audit: truncated or underspecified question",
        )

        for question_id, fields in REPAIRS.items():
            current = dict(
                conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
            )
            updated = {**current, **fields}
            updated["content_hash"] = content_hash(updated)
            assignments = ", ".join(f"{field} = :{field}" for field in fields)
            conn.execute(
                f"""
                UPDATE questions
                SET {assignments},
                    content_hash = :content_hash,
                    is_archived = 0,
                    archived_at = NULL,
                    archive_reason = NULL
                WHERE id = :id
                """,
                {**fields, "content_hash": updated["content_hash"], "id": question_id},
            )

        for report_id, note in REPORT_RESOLUTIONS.items():
            conn.execute(
                """
                UPDATE question_issue_reports
                SET status = 'Resolved',
                    admin_notes = ?,
                    resolved_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (note, report_id),
            )

        conn.commit()
    finally:
        conn.close()

    print(f"Backup: {backup}")
    print(f"V2 questions newly archived: {archived_v2}")
    print(f"Dependent questions newly archived: {archived_dependencies}")
    print(f"Malformed questions newly archived: {archived_malformed}")
    print(f"Questions repaired and restored: {len(REPAIRS)}")
    print(f"Issue reports resolved: {len(REPORT_RESOLUTIONS)}")


if __name__ == "__main__":
    main()
