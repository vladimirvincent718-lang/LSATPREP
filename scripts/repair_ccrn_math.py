"""Repair saved CCRN math; preview by default, back up before --apply."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from src.import_math_text import TEXT_FIELDS, _MATH, normalize_math_row
from src.neonatal_ccrn import _content_hash


def repair(db_path, *, apply=False):
    db_path = Path(db_path).resolve()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    report = {"questions_changed": 0, "pending_batches_changed": 0, "remaining_math": []}
    try:
        course = conn.execute("SELECT id FROM courses WHERE title=?", ("Neonatal CCRN",)).fetchone()
        if not course:
            raise ValueError("Neonatal CCRN course not found")
        if apply:
            backup_path = db_path.with_name(f"{db_path.stem}-before-math-repair-{datetime.now():%Y%m%d-%H%M%S-%f}.db")
            with sqlite3.connect(backup_path) as backup:
                conn.backup(backup)
            report["backup"] = str(backup_path)
            conn.execute("BEGIN IMMEDIATE")
        for saved in conn.execute("SELECT * FROM questions WHERE course_id=?", (course["id"],)).fetchall():
            old = dict(saved)
            new = normalize_math_row(old)
            changed = [key for key in TEXT_FIELDS if key in old and old[key] != new[key]]
            for key in TEXT_FIELDS:
                for span in _MATH.finditer(new.get(key) or ""):
                    report["remaining_math"].append({"question": old["question_id"], "field": key, "text": span[0]})
            if changed:
                report["questions_changed"] += 1
                if apply:
                    assignments = ", ".join(f"{key}=?" for key in changed)
                    conn.execute(f"UPDATE questions SET {assignments}, content_hash=? WHERE id=?",
                                 [new[key] for key in changed] + [_content_hash(new), old["id"]])
        for draft in conn.execute("SELECT id, rows_json FROM ccrn_import_queue WHERE course_id=? AND imported_batch_id IS NULL", (course["id"],)).fetchall():
            old = json.loads(draft["rows_json"])
            new = [normalize_math_row(row) for row in old]
            if new != old:
                report["pending_batches_changed"] += 1
                if apply:
                    conn.execute("UPDATE ccrn_import_queue SET rows_json=? WHERE id=?",
                                 (json.dumps(new, ensure_ascii=False), draft["id"]))
        if apply:
            conn.commit()
        report["applied"] = apply
        return report
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/lsat_app.db")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(repair(args.db, apply=args.apply), indent=2))
