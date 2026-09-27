"""Import the supplied September 2026 CCRN batches without altering their content.

Run with the application's Python from the repository root. Original attachments
are retained alongside this deterministic mapping; conversational footers are
not question content. Re-running skips already imported batch names/content.
"""
from pathlib import Path
import json
import re
import sqlite3
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import database
from src.neonatal_ccrn import get_batch_history, get_course_id, import_questions

DATA = ROOT / "data" / "ccrn_supplied"
ENDOCRINE = "Endocrine / Hematology-Immunology / GI / Renal-GU / Integumentary"
NEUROLOGICAL = "Musculoskeletal / Neurological / Behavioral-Psychosocial"
PROFESSIONAL = "Professional Caring & Ethical Practice"
FILES = {
    "Respiratory": "respiratory.txt", "Cardiovascular": "cardiovascular.txt",
    ENDOCRINE: "endocrine_hematology_gi_renal_skin.txt",
    NEUROLOGICAL: "musculoskeletal_neurological_behavioral.txt",
    "Multisystem": "multisystem.txt", PROFESSIONAL: "professional_caring.txt",
}

# Keep each supplied Section, then map its clinical focus to the existing chapter.
CHAPTERS = {
    "Respiratory": [
        "Respiratory distress syndrome", "Transient tachypnea of the newborn", "Aspiration",
        "Pulmonary hypertension / PPHN", "Chronic lung disease / BPD / PIE",
        "Chronic lung disease / BPD / PIE", "Pleural-space abnormalities",
        "Congenital respiratory anomalies", "Apnea of prematurity",
        "Acute respiratory distress / failure", "Chronic lung disease / BPD / PIE",
        "Respiratory distress syndrome", "Acute respiratory distress / failure",
        "Respiratory transition to extrauterine life", "Pulmonary hemorrhage",
        "Respiratory infections", "Acute respiratory distress / failure",
        "Acute respiratory distress / failure", "Respiratory infections",
        "Congenital respiratory anomalies", "Congenital respiratory anomalies",
        "Acute respiratory distress / failure", "Respiratory distress syndrome",
        "Acute respiratory distress / failure", "Acute respiratory distress / failure",
    ],
    "Cardiovascular": [
        "Transition to extrauterine life: PDA, PFO, PPHN",
        "Transition to extrauterine life: PDA, PFO, PPHN",
        "Congenital heart defects", "Congenital heart defects",
        "Transition to extrauterine life: PDA, PFO, PPHN",
        "Congenital heart defects", "Congenital heart defects", "Congenital heart defects",
        "Hemodynamic instability", "Heart failure", "Congenital heart defects",
        "Dysrhythmias", "Hemodynamic instability", "Congenital heart defects",
        "Congenital heart defects", "Congenital heart defects", "Dysrhythmias",
        "Cardiovascular surgery", "Cardiovascular surgery", "Cardiac tamponade",
        "Congenital heart defects", "Hemodynamic instability", "Congenital heart defects",
        "Congenital heart defects", "Congenital heart defects",
    ],
    ENDOCRINE: [
        "Hypoglycemia / hyperglycemia", "Adrenal disorders", "Thyroid disorders",
        "Hypoglycemia / hyperglycemia", "Calcium homeostasis disorders", "Blood-cell disorders",
        "Hyperbilirubinemia", "Blood-cell disorders", "Hemolytic disease of the newborn",
        "Blood-cell disorders", "Invasive fungal infections", "Necrotizing enterocolitis",
        "Congenital/acquired GI abnormalities", "Congenital/acquired GI abnormalities",
        "Congenital/acquired GI abnormalities", "Congenital/acquired GI abnormalities",
        "Hepatic failure", "Acquired renal/GU conditions", "Acquired renal/GU conditions",
        "Congenital renal/GU conditions", "Acquired renal/GU conditions",
        "Gestational-age-related skin conditions", "Skin infections",
        "IV infiltration / extravasation", "Neonatal skin complications",
    ],
    NEUROLOGICAL: [
        "Intracranial / extracranial hemorrhage", "Ischemic injury: stroke, PVL, HIE",
        "Seizures", "Congenital neurological abnormalities", "Acquired musculoskeletal conditions",
        "Intracranial / extracranial hemorrhage", "Intracranial / extracranial hemorrhage",
        "Acquired peripheral nerve injuries", "Congenital musculoskeletal conditions",
        "Acquired musculoskeletal conditions", "Acquired musculoskeletal conditions",
        "Congenital musculoskeletal conditions", "Congenital musculoskeletal conditions",
        "Acquired musculoskeletal conditions", "State dysregulation: stress, pain, agitation",
        "State dysregulation: stress, pain, agitation", "State dysregulation: stress, pain, agitation",
        "State dysregulation: stress, pain, agitation", "State dysregulation: stress, pain, agitation",
        "State dysregulation: stress, pain, agitation", "Acquired musculoskeletal conditions",
        "Families in crisis", "State dysregulation: stress, pain, agitation",
        "State dysregulation: stress, pain, agitation", "Families in crisis",
    ],
    "Multisystem": [
        "Shock states", "Resuscitation and initial stabilization",
        "Advanced therapies: ECMO, CRRT, dialysis, hypothermia",
        "Advanced therapies: ECMO, CRRT, dialysis, hypothermia", "Thermoregulation", "Sepsis",
        "Transport and multisystem stabilization", "Genetic/metabolic conditions",
        "Maternal/fetal complications", "Resuscitation and initial stabilization",
        "Toxin / drug exposure and withdrawal", "Toxin / drug exposure and withdrawal",
        "Sepsis", "Acid-base and fluid/electrolyte imbalance", "Transport and multisystem stabilization",
        "Trisomies", "Infant of a diabetic mother", "Birth trauma", "Toxin / drug exposure and withdrawal",
        "Sensory impairment", "Advanced therapies: ECMO, CRRT, dialysis, hypothermia",
        "Sepsis", "Multi-organ failure", "Discharge planning and care coordination",
        "Healthcare-acquired conditions",
    ],
    PROFESSIONAL: [
        "Systems Thinking", "Advocacy / Moral Agency", "Caring Practices", "Advocacy / Moral Agency",
        "Advocacy / Moral Agency", "Systems Thinking", "Collaboration", "Response to Diversity",
        "Advocacy / Moral Agency", "Systems Thinking", "Caring Practices", "Collaboration",
        "Caring Practices", "Advocacy / Moral Agency", "Caring Practices", "Facilitation of Learning",
        "Advocacy / Moral Agency", "Advocacy / Moral Agency", "Systems Thinking",
        "Collaboration", "Advocacy / Moral Agency", "Advocacy / Moral Agency", "Systems Thinking",
        "Clinical Inquiry", "Collaboration",
    ],
}


def parse_supplied(section: str) -> list[dict]:
    text = (DATA / FILES[section]).read_text(encoding="utf-8-sig")
    starts = list(re.finditer(r"(?m)^(?:#{3,4} \*\*)?Question (\d+)(?:\*\*)?[ \t]*$", text))
    if [int(m[1]) for m in starts] != list(range(1, 26)):
        raise ValueError(f"Expected exactly questions 1-25 in {section}")
    rows = []
    for index, match in enumerate(starts):
        block = text[match.end():starts[index+1].start() if index+1 < len(starts) else len(text)]
        block = re.split(r"(?m)^\*\*\*\s*$", block)[0].strip()
        block = re.sub(r"\s*---\s*$", "", block)
        def field(name):
            pattern = rf"(?m)^[ \t]*(?:\*[ \t]+)?(?:\*\*)?{name}:(?:\*\*)?[ \t]*(.*)$"
            found = list(re.finditer(pattern, block))
            if len(found) != 1:
                raise ValueError(f"Missing {name}: {section} {index+1}")
            return found[0]
        answer, difficulty, module, subtopic, rationale = [field(name) for name in
            ("Correct Answer", "Difficulty", "Section", "Subtopic", "Rationale")]
        if module[1].strip() != section or difficulty[1].strip() != "Stretch":
            raise ValueError("Unexpected supplied section or difficulty")
        stem = field("Question Stem") if "**Question Stem:**" in block else None
        prompt = block[stem.end() if stem else 0:answer.start()].strip()
        options = list(re.finditer(r"(?m)^[ \t]*(?:\*[ \t]+)?([A-D])\.[ \t]+", prompt))
        if [m[1] for m in options] != list("ABCD"):
            raise ValueError("Expected four ordered options")
        row = {
            "module": section, "chapter": CHAPTERS[section][index],
            "question_text": prompt[:options[0].start()].strip(),
            "correct_answer": answer[1].strip()[0], "difficulty": 5,
            "rationale": block[rationale.start(1):].strip(),
            "source": f"User-supplied {section} batch — September 2026",
            "source_question_number": index+1, "subtopic": subtopic[1].strip(),
            "tags": subtopic[1].strip(), "quality_status": "User supplied",
        }
        for i, option in enumerate(options):
            row[f"choice_{option[1].lower()}"] = prompt[option.end():options[i+1].start() if i+1 < 4 else len(prompt)].strip()
        answer_text = answer[1].strip()
        if not re.fullmatch(r"[A-D](?:\. .+)?", answer_text):
            raise ValueError(f"Malformed answer: {section} {index+1}")
        if len(answer_text) > 1 and answer_text[3:] != row[f"choice_{answer_text[0].lower()}"]:
            raise ValueError(f"Answer text disagrees with its option: {section} {index+1}")
        rows.append(row)
    return rows


def main():
    batches = {section: parse_supplied(section) for section in CHAPTERS}
    backup = ROOT / "work" / f"ccrn_before_import_{datetime.now():%Y%m%d_%H%M%S}.db"
    backup.parent.mkdir(exist_ok=True)
    with sqlite3.connect(database.DB_PATH) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    course_id = get_course_id()
    history = {b["name"] for b in get_batch_history(course_id)}
    results = []
    for section, rows in batches.items():
        name = f"Supplied September 2026 — {section} — 25 Stretch"
        if name in history:
            results.append({"section": section, "already_imported": True})
            continue
        result = import_questions(name, rows, course_id)
        results.append({"section": section, **result})
        if result["errors"]:
            raise ValueError(result["errors"])
    print(json.dumps({"backup": str(backup), "results": results}, indent=2))


if __name__ == "__main__":
    main()
