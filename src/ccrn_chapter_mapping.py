"""Translate source-book references using explicit, section-scoped topic rules.

Existing valid chapter edits always win. Unknown topics remain reviewable errors.
No clinical question content or answer is rewritten.
"""
import re

RULES = {
    "Cardiovascular": [
        (r"tamponade|pneumopericard", "Cardiac tamponade"),
        (r"arrhyth|tachycard|heart block|electrocardio|adenosine", "Dysrhythmias"),
        (r"ecmo|extracorporeal", "Cardiovascular surgery"),
        (r"cardiothoracic|cardiomegaly|cardiac physiology|myocardial compliance|stroke volume", "Acquired cardiac conditions"),
        (r"milrinone|digoxin|hypertroph|septal hypertrophy", "Heart failure"),
        (r"dopamine|dobutamine|epinephrine|inotrop|vasopressor|vasoactive|hypotension|shock|catheter|umbilical arter|resuscitation", "Hemodynamic instability"),
        (r"fetal circulation|transition|ductus arteriosus|nitric oxide|pphn|pulmonary hypertension", "Transition to extrauterine life: PDA, PFO, PPHN"),
        (r"coarctation|tetralogy|transposition|hypoplastic|hyperoxia|cchd|congenital heart|ventricular septal|pulmonary venous|tricuspid|truncus|murmur|ebstein|ductal.dependent|duct.dependent|22q11|turner|atrioventricular septal|pulmonary stenosis|prostaglandin", "Congenital heart defects"),
    ],
    "Respiratory": [
        (r"pulmonary hemorrhage", "Pulmonary hemorrhage"),
        (r"surfactant|\brds\b|respiratory distress syndrome", "Respiratory distress syndrome"),
        (r"pneumonia|infection", "Respiratory infections"),
        (r"nitric oxide|pphn|pulmonary hypertension|methemoglob", "Pulmonary hypertension / PPHN"),
        (r"pneumothorax|thoracostomy|pneumopericard", "Pleural-space abnormalities"),
        (r"bronchopulmonary|\bbpd\b|interstitial emphysema|\bpie\b", "Chronic lung disease / BPD / PIE"),
        (r"meconium|aspiration", "Aspiration"),
        (r"tachypnea|retained lung fluid|\bttn\b", "Transient tachypnea of the newborn"),
        (r"apnea|breathing|doxapram", "Apnea of prematurity"),
        (r"diaphragmatic|hypoplasia|congenital|choanal", "Congenital respiratory anomalies"),
        (r"ventilat|hypercapnia|nasal cannula|ecmo|oxygenation index|blood gas|oxyhemoglobin|intubat|endotracheal|respiratory support|retraction score|suction", "Acute respiratory distress / failure"),
    ],
    "Endocrine": [
        (r"adrenal|ambiguous genitalia|salt.wast", "Adrenal disorders"),
        (r"thyroid|graves|thyrotox", "Thyroid disorders"),
        (r"calcium|calcemia|phosphate|magnesium|parathyroid", "Calcium homeostasis disorders"),
        (r"glycemia|glucose|\bgir\b|insulin|diabetes mellitus|glucagon", "Hypoglycemia / hyperglycemia"),
        (r"hemolytic|coombs", "Hemolytic disease of the newborn"),
        (r"coagulation|\bdic\b", "Coagulopathies"),
        (r"anemia|polycythemia|thrombocytopenia|neutrophil|leukocyte|hematology", "Blood-cell disorders"),
        (r"spontaneous intestinal perforation|\bsip\b", "Congenital/acquired GI abnormalities"),
        (r"necrotizing|\bnec\b", "Necrotizing enterocolitis"),
        (r"volvulus|duodenal|atresia|gastrointestinal|esophag|tracheoesoph|hirschsprung|gastroschisis|omphalocele|abdominal wall", "Congenital/acquired GI abnormalities"),
        (r"prune belly|polycystic|potter|urethral valve", "Congenital renal/GU conditions"),
        (r"kidney|renal|kalemia|natremia|siadh|diabetes insipidus", "Acquired renal/GU conditions"),
        (r"tewl|barrier maturity|integumentary maturity", "Gestational-age-related skin conditions"),
        (r"aplasia cutis|epidermolysis|mechanobullous|incontinentia", "Congenital skin abnormalities"),
        (r"scalded skin", "Skin infections"),
        (r"skin|marsi|fat necrosis", "Neonatal skin complications"),
        (r"acid.base|anion gap|hypopituitar|septo.optic|diabetes in pregnancy", "Metabolic disorders"),
    ],
    "Musculoskeletal": [
        (r"human factors|just culture|system vulnerabilities", "Care systems and patient safety"),
        (r"hemorrhag|hematoma|cranial birth trauma|extracranial", "Intracranial / extracranial hemorrhage"),
        (r"hypoxic|\bhie\b|sarnat|leukomalacia|\bpvl\b", "Ischemic injury: stroke, PVL, HIE"),
        (r"seizure|phenobarbital", "Seizures"),
        (r"meningitis|lumbar puncture", "Neurological infections"),
        (r"plexus|peripheral nerve|facial nerve|cranial nerve|erb|klumpke", "Acquired peripheral nerve injuries"),
        (r"fracture|bone disease|osteopenia|plagiocephaly", "Acquired musculoskeletal conditions"),
        (r"hip|skeletal|clubfoot|arthrogryposis|osteogenesis|torticollis|vacterl", "Congenital musculoskeletal conditions"),
        (r"neural tube|myelomeningocele|holoprosencephaly|trisom|muscular atrophy|fetal alcohol|primitive reflex", "Congenital neurological abnormalities"),
        (r"ballard|neuromuscular maturity|gestational age assessment", "Congenital neurological abnormalities"),
        (r"grief|crisis|palliative|vulnerable child", "Families in crisis"),
        (r"family.centered|attachment", "Alterations in family systems"),
        (r"pain|pipp|fentanyl|opioid|sucrose|synactive|development|position|abstinence|nows|sleep|sedat|light|noise|kangaroo|neuromuscular block|central apnea", "State dysregulation: stress, pain, agitation"),
    ],
    "Multisystem": [
        (r"shock", "Shock states"),
        (r"hypothermia|ecmo", "Advanced therapies: ECMO, CRRT, dialysis, hypothermia"),
        (r"hydrops", "Hydrops fetalis"),
        (r"transport|altitude|boyle", "Transport and multisystem stabilization"),
        (r"cold stress|thermogen|hyperthermia|thermoregulat", "Thermoregulation"),
        (r"urea cycle|hyperammon|galactosemia|maple syrup|metabolism|organic acid", "Genetic/metabolic conditions"),
        (r"beckwith|genetic syndrome", "Genetic syndromes"),
        (r"trisomy|edwards|patau|down syndrome", "Trisomies"),
        (r"ssri|substance|cocaine|methamphetamine|alcohol|withdrawal|abstinence|eat, sleep|extravasation", "Toxin / drug exposure and withdrawal"),
        (r"cmv|cytomegalo|torch|syphilis|toxoplas|rubella|lupus|myasthenia|maternal|antenatal|parvovirus|polycythem|hyperviscos", "Maternal/fetal complications"),
        (r"sepsis|hsv|herpes|dic|coagulation|neutrophil", "Sepsis"),
        (r"asphyxi|end.organ|organ dysfunc|liver disease|advanced nec", "Multi-organ failure"),
        (r"bilirubin", "Hyperbilirubinemia"),
        (r"diabetic mother", "Infant of a diabetic mother"),
        (r"charge", "Congenital sequences"),
        (r"electrolyte", "Acid-base and fluid/electrolyte imbalance"),
        (r"root cause|catheter|pericardial", "Healthcare-acquired conditions"),
        (r"golden hour|resuscitation|nrp|cord clamp|delivery room", "Resuscitation and initial stabilization"),
    ],
    "Professional": [
        (r"cultur", "Response to Diversity"),
        (r"disclosure|consent|legal|ethical|ethics|moral|adolescent|advocacy", "Advocacy / Moral Agency"),
        (r"handoff|i.pass|sbar|communication|coordination", "Collaboration"),
        (r"transport|flight physiology|altitude|boyle", "Systems Thinking"),
        (r"second victim|grief|bereave|palliative|end.of.life|crisis|vulnerable child|sibling|memento", "Caring Practices"),
        (r"education|teach.back|health literacy|safe sleep|early intervention|purple crying|developmental", "Facilitation of Learning"),
        (r"family.centered|kangaroo|parental|synactive|environment", "Caring Practices"),
        (r"discharge|transition.to.home|rooming.in|car seat", "Facilitation of Learning"),
        (r"safety|just culture|root cause|fmea|reliability|information tech|workaround|fatigue|staffing|medication|alarm|guardrail|pump|abbreviation|extubation|nicu design|human factor|infection control", "Systems Thinking"),
    ],
}


def map_chapters(rows, catalog):
    result, notes = [], []
    for original in rows:
        row = dict(original)
        module = next((m for m in catalog if m['name'] == row.get('module')), None)
        if module:
            chapters = {ch['name'].casefold(): ch['name'] for ch in module['chapters']}
            current = str(row.get('chapter') or '')
            if module.get('area_name') == 'Question Bank':
                if not current and 'general' in chapters:
                    row['chapter'] = chapters['general']
                elif current.casefold() in chapters:
                    row['chapter'] = chapters[current.casefold()]
                result.append(row)
                continue

            if current.casefold() in chapters:
                row['chapter'] = chapters[current.casefold()]
            else:
                # NotebookLM commonly returns the source book's chapter heading,
                # while the CCRN blueprint expects a section-specific category.
                # Match against the question's clinical topic and retain the book
                # heading separately for traceability.
                topic = ' '.join(str(row.get(field) or '') for field in
                                 ('subtopic', 'question_text', 'rationale', 'chapter'))
                group = next((key for key in RULES if module['name'].startswith(key)), '')
                candidate = next((name for pattern, name in RULES.get(group, []) if re.search(pattern, topic, re.I)), None)
                if candidate and candidate.casefold() in chapters:
                    row['source_chapter'] = row.get('source_chapter') or current
                    row['chapter'] = candidate
                    notes.append(f"Question {row.get('source_question_number', '?')}: mapped to {candidate}; original chapter reference retained.")
        result.append(row)
    return result, notes
