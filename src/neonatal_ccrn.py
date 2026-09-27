"""Neonatal CCRN course catalog, coverage, imports, and exam selection.

The feature is intentionally additive: existing StudyForge questions continue to
use ``section_type`` while CCRN questions also receive normalized area/module/
chapter foreign keys for richer navigation and reporting.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime
from typing import Iterable


COURSE_TITLE = "Neonatal CCRN"
COURSE_TARGET = 3000
NEXT_BATCH_DEFAULT = 150

CATALOG = (
    {
        "area": "Clinical Judgment",
        "target": 2400,
        "modules": (
            ("Cardiovascular", 308, 15, None, (
                "Acquired cardiac conditions", "Transition to extrauterine life: PDA, PFO, PPHN",
                "Cardiac tamponade", "Congenital heart defects", "Dysrhythmias", "Heart failure",
                "Hemodynamic instability", "Cardiovascular surgery",
            )),
            ("Respiratory", 462, 23, None, (
                "Acute respiratory distress / failure", "Respiratory transition to extrauterine life",
                "Apnea of prematurity", "Aspiration", "Chronic lung disease / BPD / PIE",
                "Congenital respiratory anomalies", "Respiratory infections", "Pleural-space abnormalities",
                "Pulmonary hemorrhage", "Pulmonary hypertension / PPHN", "Respiratory distress syndrome",
                "Respiratory surgery", "Transient tachypnea of the newborn",
            )),
            ("Endocrine / Hematology-Immunology / GI / Renal-GU / Integumentary", 615, 31, (
                ("Endocrine", ("Adrenal disorders", "Calcium homeostasis disorders", "Hypoglycemia / hyperglycemia", "Metabolic disorders", "Thyroid disorders")),
                ("Hematology & Immunology", ("Blood-cell disorders", "Coagulopathies", "Hemolytic disease of the newborn", "Hyperbilirubinemia", "Invasive fungal infections")),
                ("Gastrointestinal", ("Congenital/acquired GI abnormalities", "Gastroesophageal reflux", "Hepatic failure", "Necrotizing enterocolitis", "Feeding intolerance", "Malabsorption", "GI surgery")),
                ("Renal & Genitourinary", ("Congenital renal/GU conditions", "Acquired renal/GU conditions", "Renal/GU infections", "Renal/GU surgery")),
                ("Integumentary", ("Neonatal skin complications", "Congenital skin abnormalities", "Diaper dermatitis", "Skin infections", "IV infiltration / extravasation", "Gestational-age-related skin conditions", "Surgical and nonsurgical wounds")),
            ), ()),
            ("Musculoskeletal / Neurological / Behavioral-Psychosocial", 400, 20, (
                ("Musculoskeletal", ("Acquired musculoskeletal conditions", "Congenital musculoskeletal conditions")),
                ("Neurological", ("Congenital neurological abnormalities", "Intracranial / extracranial hemorrhage", "Neurological infections", "Ischemic injury: stroke, PVL, HIE", "Seizures", "State dysregulation: stress, pain, agitation", "Neurological surgery", "Acquired peripheral nerve injuries")),
                ("Behavioral / Psychosocial", ("Alterations in family systems", "Abuse / neglect / maltreatment", "Families in crisis", "Culture, communication and language", "Care systems and patient safety")),
            ), ()),
            ("Multisystem", 615, 31, None, (
                "Acid-base and fluid/electrolyte imbalance", "Birth trauma", "Advanced therapies: ECMO, CRRT, dialysis, hypothermia",
                "Growth and developmental delays", "Genetic/metabolic conditions", "Genetic syndromes", "Trisomies",
                "Healthcare-acquired conditions", "Hydrops fetalis", "Hyperbilirubinemia", "Infant of a diabetic mother",
                "Maternal/fetal complications", "Multi-organ failure", "Sensory impairment", "Sepsis", "Congenital sequences",
                "Shock states", "Terminal conditions / palliative care", "Thermoregulation", "Toxin / drug exposure and withdrawal",
                "Resuscitation and initial stabilization", "Transport and multisystem stabilization", "Discharge planning and care coordination",
            )),
        ),
    },
    {
        "area": "Professional Caring & Ethical Practice",
        "target": 600,
        "modules": (("Professional Caring & Ethical Practice", 600, 30, None, (
            "Advocacy / Moral Agency", "Caring Practices", "Clinical Inquiry", "Collaboration",
            "Facilitation of Learning", "Response to Diversity", "Systems Thinking",
        )),),
    },
)


def _db():
    from src import database
    return database


def ensure_schema_and_catalog() -> int:
    """Create CCRN tables/columns and idempotently seed the empty catalog."""
    db = _db()
    conn = db.get_connection()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS course_areas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL,
        name TEXT NOT NULL, target_questions INTEGER NOT NULL DEFAULT 0,
        display_order INTEGER NOT NULL DEFAULT 0, UNIQUE(course_id, name),
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );
    CREATE TABLE IF NOT EXISTS course_module_blueprints (
        id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL,
        area_id INTEGER NOT NULL, name TEXT NOT NULL, target_questions INTEGER NOT NULL DEFAULT 0,
        mock_questions INTEGER NOT NULL DEFAULT 0, display_order INTEGER NOT NULL DEFAULT 0,
        UNIQUE(course_id, name), FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(area_id) REFERENCES course_areas(id)
    );
    CREATE TABLE IF NOT EXISTS course_chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL,
        module_id INTEGER NOT NULL, subgroup TEXT DEFAULT '', name TEXT NOT NULL,
        display_order INTEGER NOT NULL DEFAULT 0, UNIQUE(module_id, name),
        FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(module_id) REFERENCES course_module_blueprints(id)
    );
    CREATE TABLE IF NOT EXISTS question_import_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL,
        name TEXT NOT NULL, imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        questions_imported INTEGER NOT NULL DEFAULT 0,
        UNIQUE(course_id, name), FOREIGN KEY(course_id) REFERENCES courses(id)
    );
    CREATE TABLE IF NOT EXISTS question_import_batch_modules (
        batch_id INTEGER NOT NULL, module_id INTEGER NOT NULL,
        before_count INTEGER NOT NULL DEFAULT 0, added_count INTEGER NOT NULL DEFAULT 0,
        after_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(batch_id, module_id),
        FOREIGN KEY(batch_id) REFERENCES question_import_batches(id),
        FOREIGN KEY(module_id) REFERENCES course_module_blueprints(id)
    );
    CREATE TABLE IF NOT EXISTS ccrn_import_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL,
        name TEXT NOT NULL, raw_text TEXT NOT NULL,
        rows_json TEXT NOT NULL DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        imported_batch_id INTEGER,
        UNIQUE(course_id, name),
        FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(imported_batch_id) REFERENCES question_import_batches(id)
    );
    """)
    for table in ('ccrn_import_queue', 'question_import_batches'):
        columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
        if 'lens' not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN lens TEXT NOT NULL DEFAULT 'standard'")
    queue_columns = {row["name"] for row in conn.execute("PRAGMA table_info(ccrn_import_queue)")}
    for name in ("module_id", "batch_number"):
        if name not in queue_columns:
            conn.execute(f"ALTER TABLE ccrn_import_queue ADD COLUMN {name} INTEGER")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ccrn_queue_module_number ON ccrn_import_queue(course_id,module_id,batch_number)")
    question_columns = {row["name"] for row in conn.execute("PRAGMA table_info(questions)")}
    additions = {
        "area_id": "INTEGER", "module_id": "INTEGER", "chapter_id": "INTEGER",
        "import_batch_id": "INTEGER", "source_page": "TEXT DEFAULT ''",
        "metadata_json": "TEXT DEFAULT '{}'", "quality_status": "TEXT DEFAULT ''",
    }
    for name, declaration in additions.items():
        if name not in question_columns:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {name} {declaration}")

    normalized = db._normalize_title(COURSE_TITLE)
    course = conn.execute("SELECT id FROM courses WHERE normalized_title = ?", (normalized,)).fetchone()
    if course:
        course_id = int(course["id"])
        conn.execute("UPDATE courses SET is_active = 1 WHERE id = ?", (course_id,))
    else:
        course_id = int(conn.execute(
            """INSERT INTO courses (title, normalized_title, description, category)
               VALUES (?, ?, ?, ?)""",
            (COURSE_TITLE, normalized, "AACN Neonatal CCRN certification exam preparation", "CCRN Neonatal"),
        ).lastrowid)
    conn.execute(
        """INSERT OR IGNORE INTO course_enrollments (user_id, course_id, enrollment_status)
           SELECT id, ?, 'Active' FROM users""", (course_id,)
    )
    module_order = 0
    for area_order, area_spec in enumerate(CATALOG):
        conn.execute(
            """INSERT INTO course_areas (course_id, name, target_questions, display_order)
               VALUES (?, ?, ?, ?) ON CONFLICT(course_id, name) DO UPDATE SET
               target_questions=excluded.target_questions, display_order=excluded.display_order""",
            (course_id, area_spec["area"], area_spec["target"], area_order),
        )
        area_id = int(conn.execute(
            "SELECT id FROM course_areas WHERE course_id=? AND name=?", (course_id, area_spec["area"])
        ).fetchone()["id"])
        for module_name, target, mock_count, grouped, chapters in area_spec["modules"]:
            conn.execute(
                """INSERT INTO course_module_blueprints
                   (course_id, area_id, name, target_questions, mock_questions, display_order)
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(course_id, name) DO UPDATE SET
                   area_id=excluded.area_id, target_questions=excluded.target_questions,
                   mock_questions=excluded.mock_questions, display_order=excluded.display_order""",
                (course_id, area_id, module_name, target, mock_count, module_order),
            )
            module_id = int(conn.execute(
                "SELECT id FROM course_module_blueprints WHERE course_id=? AND name=?", (course_id, module_name)
            ).fetchone()["id"])
            chapter_order = 0
            chapter_groups = grouped or (("", chapters),)
            for subgroup, names in chapter_groups:
                for chapter_name in names:
                    conn.execute(
                        """INSERT INTO course_chapters (course_id, module_id, subgroup, name, display_order)
                           VALUES (?, ?, ?, ?, ?) ON CONFLICT(module_id, name) DO UPDATE SET
                           subgroup=excluded.subgroup, display_order=excluded.display_order""",
                        (course_id, module_id, subgroup, chapter_name, chapter_order),
                    )
                    chapter_order += 1
            module_order += 1
    conn.commit()
    conn.close()
    return course_id


def get_course_id() -> int:
    return ensure_schema_and_catalog()


def get_catalog(course_id: int | None = None) -> list[dict]:
    course_id = course_id or get_course_id()
    conn = _db().get_connection()
    rows = conn.execute(
        """SELECT m.id, m.name, m.target_questions, m.mock_questions, m.display_order,
                  a.id AS area_id, a.name AS area_name, a.target_questions AS area_target
           FROM course_module_blueprints m JOIN course_areas a ON a.id=m.area_id
           WHERE m.course_id=? ORDER BY m.display_order""", (course_id,)
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["chapters"] = [dict(ch) for ch in conn.execute(
            "SELECT id, name, subgroup, display_order FROM course_chapters WHERE module_id=? ORDER BY display_order",
            (row["id"],),
        ).fetchall()]
        result.append(item)
    conn.close()
    return result


def get_coverage(course_id: int | None = None, user_id: int | None = None) -> dict:
    course_id = course_id or get_course_id()
    conn = _db().get_connection()
    modules = conn.execute(
        """SELECT m.id, m.name, m.target_questions, m.mock_questions, m.display_order,
                  a.name AS area_name, COUNT(q.id) AS actual
           FROM course_module_blueprints m JOIN course_areas a ON a.id=m.area_id
           LEFT JOIN questions q ON q.module_id=m.id AND COALESCE(q.is_archived,0)=0
           WHERE m.course_id=? GROUP BY m.id ORDER BY m.display_order""", (course_id,)
    ).fetchall()
    from src.question_bank_workspace import get_plan
    targets = get_plan(course_id)["targets"]
    rows = []
    for module in modules:
        target, actual = int(targets.get(module["name"], module["target_questions"])), int(module["actual"])
        rows.append({**dict(module), "target_questions": target, "variance": actual-target, "remaining": max(target-actual, 0),
                     "completion": (actual/target*100 if target else 0.0)})
    chapters = []
    if user_id is not None:
        chapter_rows = conn.execute(
            """SELECT ch.id, ch.module_id, ch.name, ch.subgroup, COUNT(DISTINCT q.id) AS actual,
                      (SELECT COUNT(*) FROM user_answers ua
                       JOIN exam_attempts ea ON ea.id=ua.attempt_id JOIN questions uq ON uq.id=ua.question_id
                       WHERE ea.user_id=? AND uq.chapter_id=ch.id) AS attempted,
                      (SELECT COALESCE(SUM(ua.is_correct),0) FROM user_answers ua
                       JOIN exam_attempts ea ON ea.id=ua.attempt_id JOIN questions uq ON uq.id=ua.question_id
                       WHERE ea.user_id=? AND uq.chapter_id=ch.id) AS correct,
                      (SELECT MAX(ua.submitted_at) FROM user_answers ua
                       JOIN exam_attempts ea ON ea.id=ua.attempt_id JOIN questions uq ON uq.id=ua.question_id
                       WHERE ea.user_id=? AND uq.chapter_id=ch.id) AS last_practiced
               FROM course_chapters ch
               LEFT JOIN questions q ON q.chapter_id=ch.id AND COALESCE(q.is_archived,0)=0
               WHERE ch.course_id=? GROUP BY ch.id ORDER BY ch.module_id, ch.display_order""",
            (user_id, user_id, user_id, course_id)
        ).fetchall()
    else:
        chapter_rows = conn.execute(
            """SELECT ch.id, ch.module_id, ch.name, ch.subgroup, COUNT(q.id) AS actual,
                      0 AS attempted, 0 AS correct, NULL AS last_practiced
               FROM course_chapters ch LEFT JOIN questions q ON q.chapter_id=ch.id AND COALESCE(q.is_archived,0)=0
               WHERE ch.course_id=? GROUP BY ch.id ORDER BY ch.module_id, ch.display_order""", (course_id,)
        ).fetchall()
    module_actual = {row["id"]: row["actual"] for row in rows}
    for row in chapter_rows:
        item = dict(row)
        attempted = int(item["attempted"] or 0)
        item["module_share"] = (int(item["actual"])/module_actual.get(item["module_id"], 1)*100
                                if module_actual.get(item["module_id"], 0) else 0.0)
        item["accuracy"] = (int(item["correct"] or 0)/attempted*100 if attempted else None)
        chapters.append(item)
    conn.close()
    actual_total = sum(row["actual"] for row in rows)
    target_total = sum(row["target_questions"] for row in rows)
    return {"target": target_total, "actual": actual_total, "remaining": max(target_total-actual_total, 0),
            "variance": actual_total-target_total, "completion": actual_total/target_total*100 if target_total else 0.0,
            "modules": rows, "chapters": chapters}


def recommend_next_batch(batch_size: int = NEXT_BATCH_DEFAULT, course_id: int | None = None) -> list[dict]:
    """Allocate exactly ``batch_size`` toward the projected bank trajectory.

    Comparing the *post-batch* bank with its desired proportional size prevents
    an already overrepresented module from receiving more questions merely
    because it has not reached its eventual absolute target yet.
    """
    if batch_size < 1:
        raise ValueError("Batch size must be positive.")
    coverage = get_coverage(course_id)
    modules = coverage["modules"]
    if not modules or not coverage["target"]:
        return []
    projected_total = coverage["actual"] + batch_size
    trajectory_targets = [projected_total * int(m["target_questions"]) / coverage["target"] for m in modules]
    deficits = [max(trajectory_targets[i]-int(m["actual"]), 0.0) for i, m in enumerate(modules)]
    weights = deficits if sum(deficits) else [int(m["target_questions"]) for m in modules]
    total_weight = sum(weights)
    raw = [batch_size*w/total_weight for w in weights]
    allocation = [math.floor(value) for value in raw]
    order = sorted(range(len(modules)), key=lambda i: (raw[i]-allocation[i], weights[i], -i), reverse=True)
    for i in order[:batch_size-sum(allocation)]:
        allocation[i] += 1
    return [{**module, "trajectory_target": trajectory_targets[i], "recommended": allocation[i]}
            for i, module in enumerate(modules)]


def _content_hash(row: dict) -> str:
    parts = [row.get("question_text") or row.get("stimulus") or ""]
    parts.extend(str(row.get(f"choice_{letter}", "")) for letter in "abcde")
    parts.append(str(row.get("correct_answer", "")))
    return hashlib.sha256("|".join(str(v).strip().lower() for v in parts).encode()).hexdigest()[:32]


def import_questions(batch_name: str, rows: Iterable[dict], course_id: int | None = None,
                     *, validate_only=False, queue_id=None, remaining_rows=None, lens="standard") -> dict:
    """Validate and atomically import a named CCRN batch."""
    course_id = course_id or get_course_id()
    batch_name = " ".join(str(batch_name or "").split())
    if not batch_name:
        raise ValueError("Batch name is required.")
    from src.question_lenses import validate_lens, get_lenses
    validate_lens(lens)
    lens_options = get_lenses()
    # The saved batch lens is authoritative, including during validation.
    if queue_id is not None:
        from contextlib import closing
        with closing(_db().get_connection()) as lens_conn:
            saved = lens_conn.execute(
                "SELECT lens FROM ccrn_import_queue WHERE id=? AND course_id=?",
                (queue_id, course_id),
            ).fetchone()
        if saved:
            lens = validate_lens(saved["lens"])
    catalog = get_catalog(course_id)
    modules = {m["name"].casefold(): m for m in catalog}
    chapters = {(m["name"].casefold(), ch["name"].casefold()): ch for m in catalog for ch in m["chapters"]}
    from src.ccrn_chapter_mapping import map_chapters
    from src.import_math_text import normalize_math_row
    rows, _ = map_chapters(rows, catalog)
    prepared, errors = [], []
    for index, source_row in enumerate(rows, 2):
        row = {str(k).strip().lower().replace(" ", "_"): ("" if v is None else v) for k, v in dict(source_row).items()}
        row = normalize_math_row(row)
        module_name = str(row.get("module") or row.get("section_type") or "").strip()
        chapter_name = str(row.get("chapter") or "").strip()
        stimulus = str(row.get("question_text") or row.get("stimulus") or "").strip()
        module = modules.get(module_name.casefold())
        chapter = chapters.get((module_name.casefold(), chapter_name.casefold()))
        if not module: errors.append(f"Row {index}: unknown module '{module_name}'."); continue
        if not chapter: errors.append(f"Row {index}: chapter '{chapter_name}' is not in {module_name}."); continue
        if not stimulus: errors.append(f"Row {index}: question text is required."); continue
        answer = str(row.get("correct_answer") or "").strip().upper()
        if answer not in {"A", "B", "C", "D", "E"}: errors.append(f"Row {index}: correct_answer must be A-E."); continue
        # This importer serves CFA and other courses too: three to five
        # populated options are valid, including gaps in the A-E labels.
        choices = [letter for letter in "abcde" if str(row.get(f"choice_{letter}") or "").strip()]
        if len(choices) < 3:
            errors.append(f"Row {index}: at least three answer choices are required."); continue
        if not str(row.get(f"choice_{answer.lower()}") or "").strip():
            errors.append(f"Row {index}: correct_answer references an empty choice."); continue
        difficulty_raw = str(row.get("difficulty") or "").strip() or ("3" if lens != "standard" else "5")
        if difficulty_raw.casefold() in {"stretch", "stretch problems"}:
            difficulty_raw = "5"
        if difficulty_raw.casefold() in {"intermediate", "intermediate calculations"}:
            difficulty_raw = "3"
        try: difficulty = int(difficulty_raw)
        except ValueError: difficulty = 0
        if difficulty not in range(1, 6): errors.append(f"Row {index}: difficulty must be 1-5."); continue
        metadata_fields = ("clinical_condition", "question_type_detail", "cognitive_skill", "signs_symptoms", "diagnostics",
                           "laboratory_interpretation", "blood_gas_interpretation", "medication", "intervention",
                           "prioritization", "patient_scenario", "confidence", "subtopic", "source_question_number", "source_chapter")
        metadata = {key: row.get(key) for key in metadata_fields if str(row.get(key) or "").strip()}
        prepared.append({**row, "stimulus": stimulus, "module": module, "chapter_record": chapter,
                         "difficulty": difficulty, "correct_answer": answer, "metadata_json": json.dumps(metadata),
                         "content_hash": _content_hash({**row, "stimulus": stimulus, "correct_answer": answer})})
    if not prepared and not errors:
        errors.append("This batch contains no questions.")
    if errors or validate_only:
        return {"inserted": 0, "skipped_content": 0, "errors": errors, "batch_id": None, "distribution": {}}

    db = _db(); conn = db.get_connection()
    conn.execute("BEGIN IMMEDIATE")
    if queue_id is not None:
        queued = conn.execute(
            "SELECT * FROM ccrn_import_queue WHERE id=? AND course_id=?", (queue_id, course_id)
        ).fetchone()
        if not queued or queued["imported_batch_id"] is not None or queued["name"] != batch_name:
            conn.close(); raise ValueError("This queued batch is unavailable or already imported.")
        if queued["module_id"] is not None and any(row["module"]["id"] != queued["module_id"] for row in prepared):
            conn.close(); raise ValueError("Every question must belong to this queue's section.")
    if queue_id is not None:
        lens = queued['lens']
        if lens not in lens_options:
            conn.close()
            raise ValueError('Choose a supported question lens.')
    import_batch_name = batch_name
    if queue_id is not None and remaining_rows:
        part = 1
        while conn.execute(
            "SELECT 1 FROM question_import_batches WHERE course_id=? AND name=?",
            (course_id, f"{batch_name} — Part {part}"),
        ).fetchone():
            part += 1
        import_batch_name = f"{batch_name} — Part {part}"
    if conn.execute("SELECT 1 FROM question_import_batches WHERE course_id=? AND name=?", (course_id, import_batch_name)).fetchone():
        conn.close(); raise ValueError("A batch with this name already exists.")
    before = {m["id"]: int(conn.execute(
        "SELECT COUNT(*) FROM questions WHERE module_id=? AND COALESCE(is_archived,0)=0", (m["id"],)
    ).fetchone()[0]) for m in catalog}
    batch_id = int(conn.execute(
        "INSERT INTO question_import_batches (course_id, name, lens) VALUES (?, ?, ?)", (course_id, import_batch_name, lens)
    ).lastrowid)
    course = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    prefix = db._course_abbreviation(course)
    next_number = db._next_question_number_for_course(conn, course_id, prefix)
    inserted = skipped = 0; added = defaultdict(int)
    # Older imports can contain raw LaTeX. Compare their readable content too,
    # so re-pasting a batch after this formatting update cannot duplicate it.
    existing_hashes = {_content_hash(normalize_math_row(dict(existing))) for existing in conn.execute(
        "SELECT stimulus, choice_a, choice_b, choice_c, choice_d, choice_e, correct_answer FROM questions WHERE course_id=?",
        (course_id,))}
    for row in prepared:
        if row["content_hash"] in existing_hashes:
            skipped += 1; continue
        module, chapter = row["module"], row["chapter_record"]
        metadata = json.loads(row['metadata_json'])
        metadata['lens'] = lens
        row['metadata_json'] = json.dumps(metadata)

        conn.execute(
            """INSERT INTO questions
               (course_id, question_id, section_type, question_type, difficulty, passage, stimulus,
                choice_a, choice_b, choice_c, choice_d, choice_e, correct_answer, explanation, source, tags,
                content_hash, area_id, module_id, chapter_id, import_batch_id, source_page, metadata_json, quality_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (course_id, f"{prefix}-{next_number:04d}", module["name"], str(row.get("question_type") or "Multiple Choice"),
             row["difficulty"], str(row.get("passage") or ""), row["stimulus"],
             *(str(row.get(f"choice_{letter}") or "").strip() for letter in "abcde"), row["correct_answer"],
             str(row.get("rationale") or row.get("explanation") or ""), str(row.get("source") or "custom"),
             str(row.get("tags") or ""), row["content_hash"], module["area_id"], module["id"], chapter["id"],
             batch_id, str(row.get("source_page") or ""), row["metadata_json"], str(row.get("quality_status") or "")),
        )
        existing_hashes.add(row["content_hash"])
        next_number += 1; inserted += 1; added[module["id"]] += 1
    conn.execute("UPDATE question_import_batches SET questions_imported=? WHERE id=?", (inserted, batch_id))
    for module in catalog:
        module_added = added[module["id"]]
        conn.execute(
            """INSERT INTO question_import_batch_modules
               (batch_id,module_id,before_count,added_count,after_count) VALUES (?,?,?,?,?)""",
            (batch_id, module["id"], before[module["id"]], module_added, before[module["id"]]+module_added),
        )
    if queue_id is not None:
        if remaining_rows:
            conn.execute(
                "UPDATE ccrn_import_queue SET rows_json=? WHERE id=?",
                (json.dumps(list(remaining_rows), ensure_ascii=False), queue_id),
            )
        else:
            conn.execute("UPDATE ccrn_import_queue SET imported_batch_id=? WHERE id=?", (batch_id, queue_id))
    conn.commit(); conn.close()
    return {"inserted": inserted, "skipped_content": skipped, "errors": [], "batch_id": batch_id,
            "distribution": {m["name"]: added[m["id"]] for m in catalog}}


def get_batch_history(course_id: int | None = None) -> list[dict]:
    course_id = course_id or get_course_id(); conn = _db().get_connection()
    batches = [dict(row) for row in conn.execute(
        """SELECT b.*, (SELECT COUNT(*) FROM questions q WHERE q.course_id=b.course_id
                         AND q.created_at <= b.imported_at) AS cumulative_questions
           FROM question_import_batches b WHERE b.course_id=? ORDER BY b.imported_at, b.id""", (course_id,)
    ).fetchall()]
    for batch in batches:
        batch["modules"] = [dict(row) for row in conn.execute(
            """SELECT m.name, m.target_questions, bm.before_count, bm.added_count, bm.after_count,
                      bm.after_count-m.target_questions AS variance
               FROM question_import_batch_modules bm JOIN course_module_blueprints m ON m.id=bm.module_id
               WHERE bm.batch_id=? ORDER BY m.display_order""", (batch["id"],)
        ).fetchall()]
    conn.close(); return batches


def get_questions(course_id: int | None = None, *, area_id=None, module_id=None, chapter_id=None,
                  batch_id=None, tag="", difficulty=None, search="", question_id="") -> list[dict]:
    course_id = course_id or get_course_id(); conn = _db().get_connection()
    query = """SELECT q.*, a.name AS area_name, m.name AS module_name, ch.name AS chapter_name,
                      b.name AS batch_name FROM questions q
               LEFT JOIN course_areas a ON a.id=q.area_id LEFT JOIN course_module_blueprints m ON m.id=q.module_id
               LEFT JOIN course_chapters ch ON ch.id=q.chapter_id LEFT JOIN question_import_batches b ON b.id=q.import_batch_id
               WHERE q.course_id=? AND COALESCE(q.is_archived,0)=0"""
    params: list = [course_id]
    for column, value in (("q.area_id", area_id), ("q.module_id", module_id), ("q.chapter_id", chapter_id),
                          ("q.import_batch_id", batch_id), ("q.difficulty", difficulty)):
        if value not in (None, "", "All"): query += f" AND {column}=?"; params.append(value)
    if tag: query += " AND q.tags LIKE ?"; params.append(f"%{tag}%")
    if question_id: query += " AND q.question_id LIKE ?"; params.append(f"%{question_id}%")
    if search:
        query += " AND (q.stimulus LIKE ? OR q.explanation LIKE ? OR q.source LIKE ?)"; params.extend([f"%{search}%"]*3)
    query += " ORDER BY q.id DESC"
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]; conn.close(); return rows


def select_mock_questions(user_id: int, mode: str = "Standard Mock", course_id: int | None = None,
                          rng: random.Random | None = None, *, difficulty: int | None = None) -> dict:
    """Return the exact configured mock allocation or explicit shortages."""
    if difficulty is not None and difficulty not in range(1, 6):
        raise ValueError("Difficulty must be 1-5 or None for all levels.")
    course_id = course_id or get_course_id(); rng = rng or random.Random(); conn = _db().get_connection()
    catalog = get_catalog(course_id); shortages = []; selected = []
    for module in catalog:
        pool = [dict(row) for row in conn.execute(
            """SELECT q.*,
                      (SELECT COUNT(*) FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                       WHERE ua.question_id=q.id AND ea.user_id=?) AS exposures,
                      (SELECT COALESCE(SUM(ua.is_correct),0) FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                       WHERE ua.question_id=q.id AND ea.user_id=?) AS correct_attempts,
                      (SELECT COUNT(*) FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                       WHERE ua.question_id=q.id AND ea.user_id=? AND ua.is_correct=0) AS incorrect_attempts,
                      (SELECT MIN(ua.submitted_at) FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                       WHERE ua.question_id=q.id AND ea.user_id=?) AS first_seen,
                      (SELECT MAX(ua.submitted_at) FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                       WHERE ua.question_id=q.id AND ea.user_id=?) AS last_seen
               FROM questions q WHERE q.module_id=? AND COALESCE(q.is_archived,0)=0""",
            (user_id, user_id, user_id, user_id, user_id, module["id"])
        ).fetchall()]
        if difficulty is not None:
            pool = [q for q in pool if q["difficulty"] == difficulty]
        need = int(module["mock_questions"])
        if len(pool) < need:
            shortages.append({"module": module["name"], "required": need, "available": len(pool), "shortage": need-len(pool)})
            continue
        rng.shuffle(pool)
        if mode == "Random Mock": pass
        elif mode == "Previously Incorrect": pool.sort(key=lambda q: (int(q["incorrect_attempts"] or 0)==0, -int(q["incorrect_attempts"] or 0), q["last_seen"] or ""))
        elif mode == "Weak Areas": pool.sort(key=lambda q: ((int(q["correct_attempts"] or 0)/int(q["exposures"])) if q["exposures"] else 1.0, q["last_seen"] or ""))
        elif mode == "Mostly New Questions": pool.sort(key=lambda q: (int(q["exposures"] or 0)>0, q["last_seen"] or ""))
        else: pool.sort(key=lambda q: (int(q["exposures"] or 0)>0, q["last_seen"] or "", -int(q["incorrect_attempts"] or 0)))
        selected.extend(pool[:need])
    conn.close()
    if shortages: return {"questions": [], "shortages": shortages}
    rng.shuffle(selected)
    return {"questions": selected, "shortages": []}


def get_performance(user_id: int, course_id: int | None = None) -> dict:
    course_id = course_id or get_course_id(); conn = _db().get_connection()
    overall = conn.execute(
        """SELECT COUNT(ua.id) attempted, COALESCE(SUM(ua.is_correct),0) correct
           FROM user_answers ua JOIN questions q ON q.id=ua.question_id
           JOIN exam_attempts ea ON ea.id=ua.attempt_id WHERE ea.user_id=? AND q.course_id=?""", (user_id, course_id)
    ).fetchone()
    mocks = conn.execute(
        """SELECT COUNT(*) completed, AVG(percent_correct) average_score,
                  (SELECT percent_correct FROM exam_attempts WHERE user_id=? AND course_id=? AND mode='neonatal_mock'
                   AND completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1) latest_score
           FROM exam_attempts WHERE user_id=? AND course_id=? AND mode='neonatal_mock' AND completed_at IS NOT NULL""",
        (user_id, course_id, user_id, course_id),
    ).fetchone()
    module_rows = conn.execute(
        """SELECT m.name,
                  (SELECT COUNT(*) FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                   JOIN questions q ON q.id=ua.question_id WHERE ea.user_id=? AND q.module_id=m.id) attempted,
                  (SELECT AVG(ua.is_correct)*100 FROM user_answers ua JOIN exam_attempts ea ON ea.id=ua.attempt_id
                   JOIN questions q ON q.id=ua.question_id WHERE ea.user_id=? AND q.module_id=m.id) accuracy
           FROM course_module_blueprints m WHERE m.course_id=?""", (user_id, user_id, course_id)
    ).fetchall(); conn.close()
    ranked = sorted((dict(row) for row in module_rows if int(row["attempted"] or 0) > 0), key=lambda row: row["accuracy"])
    attempted = int(overall["attempted"] or 0)
    return {"attempted": attempted, "accuracy": int(overall["correct"] or 0)/attempted*100 if attempted else None,
            "mocks_completed": int(mocks["completed"] or 0), "average_mock": mocks["average_score"], "latest_mock": mocks["latest_score"],
            "weakest_module": ranked[0]["name"] if ranked else None, "strongest_module": ranked[-1]["name"] if ranked else None}
