"""
question_loader.py — Parse and validate question CSV uploads.
Works for ANY course type, not just LSAT.

New in this version:
  - content_hash is computed for every row (duplicate content detection)
  - process_upload() returns a rich dict instead of a 3-tuple
"""

import hashlib
import pandas as pd
import io
from src.database import insert_questions

# Columns that MUST be in the CSV
REQUIRED_COLS = {
    "question_id", "stimulus", "choice_a", "choice_b", "choice_c",
    "choice_d", "choice_e", "correct_answer",
}

# All recognised columns (optional ones get empty string if missing)
ALL_COLS = [
    "question_id", "section_type", "question_type", "difficulty",
    "passage", "stimulus",
    "choice_a", "choice_b", "choice_c", "choice_d", "choice_e",
    "correct_answer", "explanation",
    "wrong_answer_a", "wrong_answer_b", "wrong_answer_c",
    "wrong_answer_d", "wrong_answer_e",
    "source", "tags",
]

VALID_ANSWERS = {"A", "B", "C", "D", "E"}


# ── Content hash (identical-question detection) ───────────────────────────────
def _content_hash(stimulus: str, choice_a: str = "", choice_b: str = "",
                   choice_c: str = "", choice_d: str = "",
                   choice_e: str = "", correct_answer: str = "") -> str:
    parts = [stimulus, choice_a, choice_b, choice_c,
             choice_d, choice_e, correct_answer]
    blob = "|".join(p.strip().lower() for p in parts)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def load_csv(file_obj) -> tuple:
    """
    Parse an uploaded file object.
    Returns (rows, errors, rows_read).
      rows      — list of valid row dicts (with content_hash added)
      errors    — list of human-readable error strings
      rows_read — total data rows seen in the file (before validation)
    """
    errors: list = []

    try:
        df = pd.read_csv(file_obj, dtype=str).fillna("")
    except Exception as e:
        return [], [f"Could not parse CSV: {e}"], 0

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        return [], [f"Missing required columns: {', '.join(sorted(missing))}"], 0

    for col in ALL_COLS:
        if col not in df.columns:
            df[col] = ""

    rows_read = len(df)
    rows: list = []

    for idx, row in df.iterrows():
        line = idx + 2
        r    = {col: str(row.get(col, "")).strip() for col in ALL_COLS}

        # Validate correct_answer
        if r["correct_answer"].upper() not in VALID_ANSWERS:
            errors.append(
                f"Row {line}: invalid correct_answer '{r['correct_answer']}'. "
                "Must be A, B, C, D, or E."
            )
            continue

        # Validate / default difficulty
        if r["difficulty"] == "":
            r["difficulty"] = 3
        else:
            try:
                diff = int(r["difficulty"])
                if diff < 1 or diff > 5:
                    raise ValueError
                r["difficulty"] = diff
            except (ValueError, TypeError):
                errors.append(
                    f"Row {line}: difficulty must be 1–5, "
                    f"got '{r['difficulty']}'. Defaulting to 3."
                )
                r["difficulty"] = 3

        r["correct_answer"] = r["correct_answer"].upper()

        # Auto-generate question_id if blank
        if not r["question_id"]:
            prefix = "Q"
            if r.get("section_type"):
                prefix = r["section_type"][:2].upper()
            r["question_id"] = f"{prefix}_{line:04d}"

        # Compute content_hash for duplicate detection
        r["content_hash"] = _content_hash(
            r["stimulus"],
            r["choice_a"], r["choice_b"], r["choice_c"],
            r["choice_d"], r["choice_e"], r["correct_answer"],
        )

        rows.append(r)

    return rows, errors, rows_read


def process_upload(file_obj, course_id=None) -> dict:
    """
    Full pipeline: parse CSV → validate → insert.

    Returns a dict:
      rows_read        — total data rows in the file
      valid_rows       — rows that passed validation
      inserted         — new questions added to the database
      skipped_id       — rows skipped because question_id already exists
      skipped_content  — rows skipped because identical content already exists
      invalid          — rows that failed validation (wrong answer, bad difficulty…)
      errors           — list of validation error strings
    """
    rows, errors, rows_read = load_csv(file_obj)
    invalid = rows_read - len(rows) if rows_read > len(rows) else len(errors)

    if not rows:
        return {
            "rows_read": rows_read,
            "valid_rows": 0,
            "inserted": 0,
            "skipped_id": 0,
            "skipped_content": 0,
            "invalid": invalid,
            "errors": errors,
        }

    inserted, skipped_id, skipped_content = insert_questions(rows, course_id=course_id)

    return {
        "rows_read": rows_read,
        "valid_rows": len(rows),
        "inserted": inserted,
        "skipped_id": skipped_id,
        "skipped_content": skipped_content,
        "invalid": invalid,
        "errors": errors,
    }


def make_template_csv() -> str:
    """Return a CSV string with headers and two example rows."""
    sample = pd.DataFrame([
        {
            "question_id":   "LR_001",
            "section_type":  "Logical Reasoning",
            "question_type": "Weaken",
            "difficulty":    3,
            "passage":       "",
            "stimulus": (
                "All professional athletes train daily. Maria trains daily. "
                "Therefore, Maria is a professional athlete."
            ),
            "choice_a":      "Maria has been training for less than a year.",
            "choice_b":      "Many non-athletes also train daily.",
            "choice_c":      "Professional athletes are highly disciplined.",
            "choice_d":      "Maria competes in regional tournaments.",
            "choice_e":      "Daily training improves athletic performance.",
            "correct_answer": "B",
            "explanation": (
                "Choice B weakens the argument by showing that training daily "
                "is not sufficient to conclude someone is a professional athlete."
            ),
            "wrong_answer_a": "Irrelevant to the conclusion about professional status.",
            "wrong_answer_b": "",
            "wrong_answer_c": "Strengthens rather than weakens.",
            "wrong_answer_d": "Competing regionally doesn't refute the logic.",
            "wrong_answer_e": "This supports the premise, doesn't attack it.",
            "source": "custom",
            "tags":   "causal reasoning, sufficient condition",
        },
        {
            "question_id":   "PY_001",
            "section_type":  "Python Basics",
            "question_type": "Multiple Choice",
            "difficulty":    2,
            "passage":       "",
            "stimulus":      "What is the output of: print(type(3.14))?",
            "choice_a":      "<class 'int'>",
            "choice_b":      "<class 'float'>",
            "choice_c":      "<class 'str'>",
            "choice_d":      "<class 'double'>",
            "choice_e":      "<class 'number'>",
            "correct_answer": "B",
            "explanation":   "3.14 is a floating-point literal — Python represents it as float.",
            "wrong_answer_a": "int is for whole numbers like 3 or -5.",
            "wrong_answer_b": "",
            "wrong_answer_c": "str is for text strings.",
            "wrong_answer_d": "Python has no 'double' type.",
            "wrong_answer_e": "Python has no 'number' type.",
            "source": "custom",
            "tags":   "types, floats",
        },
    ])
    return sample.to_csv(index=False)
