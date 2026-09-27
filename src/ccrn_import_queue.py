"""Durable pasted drafts and conservative NotebookLM text conversion.

Pasted content is data only. Conversion never generates answers or clinical facts.
"""
import json
import re
import sqlite3

from src import database
from src.ccrn_chapter_mapping import map_chapters
from src.import_math_text import normalize_math_row


FIELDS = ["source_question_number", "module", "chapter", "question_text",
          "choice_a", "choice_b", "choice_c", "choice_d", "choice_e",
          "correct_answer", "rationale", "difficulty", "source", "source_page",
          "subtopic", "tags", "quality_status", "source_chapter"]
ROW_SELECTION_FIELD = "_include_in_next_step"
LABELS = {
    "question stem": "question_text", "question text": "question_text",
    "correct answer": "correct_answer", "answer": "correct_answer",
    "section": "module", "module": "module", "chapter": "chapter",
    "rationale": "rationale", "explanation": "rationale", "difficulty": "difficulty",
    "source": "source", "sources": "source", "source page": "source_page",
    "subtopic": "subtopic", "tags": "tags", "quality status": "quality_status",
}


def _plain(line):
    line = re.sub(r"^\s*(?:#{1,6}\s+|[-*•]\s+)", "", line)
    return line.replace("**", "").strip()


def _question_starts(text):
    """Share question-boundary detection between conversion and queue badges."""
    lines = text.replace("\r\n", "\n").splitlines()
    header = re.compile(r"^(?:Question\s+|Q\s*)(\d+)\s*(?:[.):\-–—]\s*(.*))?$", re.I)
    numbered = re.compile(r"^(\d+)[.)]\s+(.+)$")
    starts = [(i, m) for i, line in enumerate(lines) if (m := header.match(_plain(line)))]
    if not starts:
        unnumbered = re.compile(r"^(Question(?: Stem| Text)?)\s*:\s*(.*)$", re.I)
        starts = [(i, m) for i, line in enumerate(lines) if (m := unnumbered.match(_plain(line)))]
    if not starts:
        starts = [(i, m) for i, line in enumerate(lines) if (m := numbered.match(_plain(line)))]
    return lines, starts


def draft_question_count(draft):
    rows = json.loads(draft["rows_json"])
    return len(rows) if rows else len(_question_starts(draft["raw_text"])[1])


def pending_question_counts(drafts):
    """Count saved pending questions, including drafts not yet converted."""
    counts = {}
    for draft in drafts:
        if draft["imported_batch_id"] is None:
            module_id = draft["module_id"]
            counts[module_id] = counts.get(module_id, 0) + draft_question_count(draft)
    return counts


def row_selected(row):
    """Rows are included by default; an explicit false value holds one back."""
    value = row.get(ROW_SELECTION_FIELD, True)
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def resolve_module(label, catalog):
    """Accept exact names or unambiguous subsets of a combined module's names."""
    def parts(value):
        return {" ".join(part.casefold().split()) for part in value.split("/") if part.strip()}
    exact = next((m for m in catalog if m["name"].casefold() == label.strip().casefold()), None)
    if exact:
        return exact
    requested = parts(label)
    candidates = [m for m in catalog if requested and requested < parts(m["name"])]
    return candidates[0] if len(candidates) == 1 else None


def convert_text(text, catalog, default_module="", default_chapter="", *, lens="standard"):
    """Recognize question fields without generating answers or guessing chapters."""
    lines, starts = _question_starts(text)
    if not starts:
        return {"rows": [], "errors": ["No question headings found. Use Question 1 or 1. before each question."], "warnings": []}
    rows, errors, warnings = [], [], []
    if any(_plain(line).strip("- ") for line in lines[:starts[0][0]]):
        warnings.append("Introductory text before the first question was kept in the original paste only.")
    for pos, (start, match) in enumerate(starts):
        row = dict.fromkeys(FIELDS, "")
        row.update(source_question_number=match[1] if match[1].isdigit() else str(pos + 1), question_text=match[2] or "",
                   module=default_module, chapter=default_chapter, difficulty="3" if lens != "standard" else "5",
                   source="NotebookLM", quality_status="Needs review")
        active = "question_text"
        seen = set()
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        for line_index in range(start + 1, end):
            original = lines[line_index]
            if original.strip() == "***":
                if any(line.strip() for line in lines[line_index + 1:end]):
                    warnings.append(f"Text after the closing *** separator for question {match[1]} was kept in the original paste only.")
                break
            line = _plain(original)
            if not line or re.fullmatch(r"[-_*]{3,}", line):
                continue
            field = re.match(r"^([^:]+):\s*(.*)$", line)
            key = LABELS.get(field[1].casefold()) if field else None
            option = re.match(r"^\(?([A-E])\s*[.):]\s*(.+)$", line)
            if key:
                if key in seen:
                    # NotebookLM sometimes uses "Section" once as a topic label
                    # and again for the actual CCRN module. Prefer the value that
                    # resolves to a catalog module and keep the topic as subtopic.
                    if key == "module":
                        existing, incoming = row[key], field[2]
                        existing_module = resolve_module(existing, catalog)
                        incoming_module = resolve_module(incoming, catalog)
                        if incoming_module and not existing_module:
                            if not row["subtopic"]:
                                row["subtopic"] = existing
                            row[key] = incoming
                            active = key
                            continue
                        if existing_module and not incoming_module:
                            if not row["subtopic"]:
                                row["subtopic"] = incoming
                            active = key
                            continue
                    errors.append(f"Question {match[1]}: repeated {field[1]} field; check the source text.")
                seen.add(key)
                active = key
                row[key] = field[2]
            elif option and active not in ("rationale", "source"):
                active = "choice_" + option[1].lower()
                if active in seen:
                    errors.append(f"Question {match[1]}: repeated option {option[1]}.")
                seen.add(active)
                row[active] = option[2]
            else:
                row[active] = (row[active] + "\n" + original.strip()).strip()
        answer = re.fullmatch(r"([A-Ea-e])(?:[.):\-]\s*[^\n]+)?", row["correct_answer"].strip())
        if answer:
            row["correct_answer"] = answer[1].upper()
        source_module = row["module"]
        module = resolve_module(source_module, catalog)
        if module:
            row["module"] = module["name"]
            if source_module.strip().casefold() != module["name"].casefold():
                warnings.append(f"Question {row['source_question_number']}: section '{source_module}' standardized to '{module['name']}'.")
        if "chapter" not in seen and row["module"].casefold() != default_module.casefold():
            row["chapter"] = ""
        if module:
            row["module"] = module["name"]
            chapters = {ch["name"].casefold(): ch["name"] for ch in module["chapters"]}
            candidate = row["chapter"] or row["subtopic"]
            row["chapter"] = chapters.get(candidate.casefold(), row["chapter"])
        row["tags"] = row["tags"] or row["subtopic"]
        rows.append(normalize_math_row(row))
    if any(not row["rationale"] for row in rows):
        warnings.append("Some questions have no labeled rationale. Review the original paste before importing.")
    rows, mapping_notes = map_chapters(rows, catalog)
    return {"rows": rows, "errors": errors, "warnings": warnings + mapping_notes}


def add_draft(course_id, name, raw_text):
    name = " ".join(name.split())
    if not name or not raw_text.strip():
        raise ValueError("Enter a batch name and paste the questions first.")
    conn = database.get_connection()
    try:
        with conn:
            if conn.execute("SELECT 1 FROM question_import_batches WHERE course_id=? AND name=?", (course_id, name)).fetchone():
                raise ValueError("This batch name has already been imported. Choose a new name.")
            return conn.execute("INSERT INTO ccrn_import_queue (course_id,name,raw_text) VALUES (?,?,?)",
                                (course_id, name, raw_text)).lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError("A queued batch already has this name. Choose a different name.") from exc
    finally:
        conn.close()


def add_section_draft(course_id, module_id, raw_text, lens="standard"):
    """Reserve the next section batch number under a database write lock."""
    from src.question_lenses import validate_lens
    validate_lens(lens)
    if not raw_text.strip():
        raise ValueError("Paste the questions first.")
    conn = database.get_connection()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            module = conn.execute("SELECT name FROM course_module_blueprints WHERE id=? AND course_id=?",
                                  (module_id, course_id)).fetchone()
            if not module:
                raise ValueError("Unknown course section.")
            imported = conn.execute("SELECT COUNT(*) FROM question_import_batch_modules bm JOIN question_import_batches b ON b.id=bm.batch_id WHERE b.course_id=? AND bm.module_id=? AND bm.added_count>0",
                                    (course_id, module_id)).fetchone()[0]
            pending, last = conn.execute("SELECT SUM(CASE WHEN imported_batch_id IS NULL THEN 1 ELSE 0 END), MAX(batch_number) FROM ccrn_import_queue WHERE course_id=? AND module_id=?",
                                        (course_id, module_id)).fetchone()
            number = max(imported + (pending or 0), last or 0) + 1
            while True:
                name = f"{module['name']} — Batch {number:03d}"
                exists = conn.execute("SELECT 1 FROM ccrn_import_queue WHERE course_id=? AND name=? UNION ALL SELECT 1 FROM question_import_batches WHERE course_id=? AND name=?",
                                      (course_id, name, course_id, name)).fetchone()
                if not exists:
                    break
                number += 1
            return conn.execute("INSERT INTO ccrn_import_queue (course_id,module_id,batch_number,name,raw_text,lens) VALUES (?,?,?,?,?,?)",
                                (course_id, module_id, number, name, raw_text, lens)).lastrowid
    finally:
        conn.close()


def list_drafts(course_id):
    conn = database.get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM ccrn_import_queue WHERE course_id=? ORDER BY id", (course_id,))]
    finally:
        conn.close()


def delete_drafts(course_id, draft_ids):
    """Permanently delete queued drafts, preserving imported questions and history."""
    conn = database.get_connection()
    try:
        with conn:
            deleted = 0
            for draft_id in dict.fromkeys(draft_ids):
                deleted += conn.execute(
                    "DELETE FROM ccrn_import_queue WHERE id=? AND course_id=? AND imported_batch_id IS NULL",
                    (draft_id, course_id),
                ).rowcount
            return deleted
    finally:
        conn.close()


def save_draft(course_id, draft_id, raw_text, rows):
    conn = database.get_connection()
    try:
        with conn:
            result = conn.execute(
                "UPDATE ccrn_import_queue SET raw_text=?, rows_json=? WHERE id=? AND course_id=? AND imported_batch_id IS NULL",
                (raw_text, json.dumps(rows, ensure_ascii=False), draft_id, course_id))
            if result.rowcount != 1:
                raise ValueError("This batch has already been imported or is unavailable.")
    finally:
        conn.close()


def process_drafts(course_id, draft_ids, *, import_ready=False):
    """Process saved batches independently; failures remain queued and are reported."""
    from src.neonatal_ccrn import get_catalog, import_questions
    catalog = get_catalog(course_id)
    modules = {m["id"]: m for m in catalog}
    drafts = {d["id"]: d for d in list_drafts(course_id)}
    results = []
    for draft_id in dict.fromkeys(draft_ids):
        draft = drafts.get(draft_id)
        result = {"id": draft_id, "batch": draft["name"] if draft else str(draft_id),
                  "status": "Needs attention", "questions": 0, "inserted": 0,
                  "duplicates": 0, "remaining": 0, "errors": [], "warnings": [], "converted": False}
        results.append(result)
        if not draft or draft["imported_batch_id"] is not None:
            result["status"] = "Already imported / unavailable"
            continue
        try:
            rows = json.loads(draft["rows_json"])
            module = modules.get(draft["module_id"])
            if not rows:
                conversion = convert_text(draft["raw_text"], catalog, module["name"] if module else "", lens=draft["lens"])
                result["warnings"] = conversion["warnings"]
                if conversion["errors"]:
                    result["errors"] = conversion["errors"]
                    continue
                rows = conversion["rows"]
                if module and any(row["module"] != module["name"] for row in rows):
                    result["errors"] = ["The pasted Section labels do not match this queue's section."]
                    continue
                save_draft(course_id, draft_id, draft["raw_text"], rows)
                result["converted"] = True
            mapped, notes = map_chapters([normalize_math_row(row) for row in rows], catalog)
            if mapped != rows:
                rows = mapped
                save_draft(course_id, draft_id, draft["raw_text"], rows)
                result["converted"] = True
                result["warnings"].extend(notes)
            result["questions"] = len(rows)
            included = [row for row in rows if row_selected(row)]
            remaining = [row for row in rows if not row_selected(row)]
            validation = import_questions(draft["name"], included, course_id, validate_only=True, lens=draft["lens"])
            result["errors"] = validation["errors"]
            if module and any(row.get("module") != module["name"] for row in rows):
                result["errors"].append("Every question must belong to this queue's section.")
            if result["errors"]:
                continue
            result["status"] = "Ready for review"
            if import_ready:
                imported = import_questions(
                    draft["name"], included, course_id, queue_id=draft_id,
                    remaining_rows=remaining,
                )
                result["errors"] = imported["errors"]
                result["status"] = ("Needs attention" if imported["errors"] else
                                    "Partially imported" if remaining else "Imported")
                result["inserted"] = imported["inserted"]
                result["duplicates"] = imported["skipped_content"]
                result["remaining"] = len(remaining)
        except (ValueError, sqlite3.Error) as exc:
            result["errors"] = [str(exc)]
    return results
