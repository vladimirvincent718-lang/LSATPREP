"""Preview and atomically commit choice permutations without changing answers."""
import hashlib
import json
import random
import re
from collections import Counter, defaultdict

from src import database

LETTERS = 'ABCDE'
CHOICES = [f'choice_{c.lower()}' for c in LETTERS]
WRONG = [f'wrong_answer_{c.lower()}' for c in LETTERS]


def load_questions(course_ids, conn=None):
    owned = conn is None
    conn = conn or database.get_connection()
    try:
        if not course_ids:
            return []
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM questions WHERE course_id IN ({','.join('?' for _ in course_ids)}) AND COALESCE(is_archived,0)=0 ORDER BY id", course_ids)]
    finally:
        if owned:
            conn.close()


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def counts(rows):
    values = Counter(str(q.get('correct_answer') or '').strip().upper() for q in rows)
    return {c: values[c] for c in LETTERS}


def distribution_health(rows, tolerance=5.0, minimum=20):
    """Check percentage-point deviation within each available-choice group.

    Invalid/written keys are excluded; position-dependent choices still count
    because they affect the bank even when they cannot safely be shuffled.
    """
    groups = defaultdict(list)
    for q in rows:
        available = ''.join(c for c in LETTERS if str(q.get(f'choice_{c.lower()}') or '').strip())
        written = str(q.get('question_type') or '').lower() in {
            'open-ended', 'open ended', 'open_ended', 'written response', 'free response'}
        if not written and len(available) >= 2 and q.get('correct_answer') in list(available):
            groups[available].append(q)
    details, breaches = [], []
    for available, questions in sorted(groups.items()):
        total = len(questions)
        target = 100 / len(available)
        current = counts(questions)
        for letter in available:
            share = 100 * current[letter] / total
            item = {'Choices': available, 'Questions': total, 'Answer': letter,
                    'Current %': share, 'Target %': target,
                    'Deviation (pp)': abs(share - target)}
            details.append(item)
            if total >= minimum and abs(share - target) > tolerance + 1e-9:
                breaches.append(item)
    return {'details': details, 'breaches': breaches,
            'checked': sum(len(qs) for qs in groups.values() if len(qs) >= minimum),
            'excluded': len(rows) - sum(map(len, groups.values()))}


def remap_references(text, mapping):
    """Remap explicit choice references and distractor headings, never bare letters."""
    # Headings must have punctuation; ordinary prose beginning with "A" is untouched.
    pattern = r'(?P<prefix>\b(?:[Oo]ption|[Cc]hoice|[Aa]nswer)\s+\**)(?P<letter>[A-E])\b|(?P<head>^[ \t*\-]*)(?P<label>[A-E])(?=\**\s*[:.)])'
    return re.sub(pattern, lambda m: (m['prefix'] or m['head'] or '') + mapping.get(m['letter'] or m['label'], m['letter'] or m['label']), text or '', flags=re.M)


def make_preview(rows, course_ids, balanced=False, rng=None):
    rng = rng or random.SystemRandom()
    groups, skipped = defaultdict(list), []
    for q in rows:
        available = ''.join(c for c in LETTERS if str(q.get(f'choice_{c.lower()}') or '').strip())
        reason = ''
        if str(q.get('question_type') or '').lower() in {'open-ended','open ended','open_ended','written response','free response'}:
            reason = 'Written-response question'
        elif len(available) < 2 or q.get('correct_answer') not in list(available):
            reason = 'Not a valid multiple-choice answer key'
        elif re.search(r'\b(?:all|none|both)\b.{0,30}\b(?:above|below)\b|\b[A-E]\s+(?:and|or)\s+[A-E]\b|\b(?:option|choice|answer)\s+[A-E]\b', ' '.join(str(q.get(k) or '') for k in CHOICES), re.I):
            reason = 'Choice text depends on positions or other answer letters'
        if reason:
            skipped.append({'Question': q.get('question_id',q['id']), 'Reason': reason})
        else:
            groups[available].append(q)
    edits = []
    for available, questions in groups.items():
        eligible_ids = {q['id'] for q in questions}
        fixed = Counter(q.get('correct_answer') for q in rows if q['id'] not in eligible_ids
                        and ''.join(c for c in LETTERS if str(q.get(f'choice_{c.lower()}') or '').strip()) == available)
        targets = []
        for _ in questions:
            lowest = min(fixed[c] for c in available)
            target = rng.choice([c for c in available if fixed[c] == lowest])
            targets.append(target)
            fixed[target] += 1
        rng.shuffle(targets)
        for q, target in zip(questions, targets):
            old_order = list(available)
            rng.shuffle(old_order)
            if balanced:
                index = old_order.index(q['correct_answer'])
                target_index = available.index(target)
                old_order[index], old_order[target_index] = old_order[target_index], old_order[index]
            mapping = dict(zip(old_order, available))
            after = dict(q)
            for old, new in mapping.items():
                after[f'choice_{new.lower()}'] = q[f'choice_{old.lower()}']
                if f'wrong_answer_{old.lower()}' in q:
                    after[f'wrong_answer_{new.lower()}'] = remap_references(q[f'wrong_answer_{old.lower()}'], mapping)
            after['correct_answer'] = mapping[q['correct_answer']]
            after['explanation'] = remap_references(q.get('explanation'), mapping)
            edits.append({'before':q, 'after':after, 'mapping':mapping})
    changed = {e['before']['id']:e['after'] for e in edits}
    return {'course_ids':list(course_ids), 'method':'Evenly balanced' if balanced else 'Random shuffle', 'fingerprint':fingerprint(rows), 'edits':edits,
            'skipped':skipped, 'before':counts(rows), 'after':counts([changed.get(q['id'],q) for q in rows]), 'total':len(rows)}


def commit_preview(preview, user_id):
    if not database.is_admin(user_id):
        raise ValueError('Only an administrator can commit answer-key changes.')
    conn = database.get_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = load_questions(preview['course_ids'], conn)
            if fingerprint(rows) != preview['fingerprint']:
                raise ValueError('The question bank changed after this preview. Generate a new preview.')
            # Saved/live sessions contain their original option order. Finish them first.
            ids = set(q['id'] for q in rows)
            for draft in conn.execute('SELECT state_json FROM exam_drafts'):
                state = json.loads(draft['state_json'])
                if any(q.get('id') in ids for q in state.get('exam_questions', []) if isinstance(q,dict)):
                    raise ValueError('Finish or discard the saved practice/exam sessions using these questions before committing.')
            conn.execute('CREATE TABLE IF NOT EXISTS answer_key_changes (id INTEGER PRIMARY KEY, user_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, preview_json TEXT NOT NULL)')
            conn.execute('INSERT INTO answer_key_changes(user_id,preview_json) VALUES (?,?)', (user_id,json.dumps(preview)))
            for edit in preview['edits']:
                q, mapping = edit['after'], edit['mapping']
                fields = CHOICES + [k for k in WRONG if k in q] + ['correct_answer','explanation']
                # Keep the import fingerprint: shuffling is the same imported content.
                conn.execute(f"UPDATE questions SET {','.join(k+'=?' for k in fields)} WHERE id=?", [q.get(k) for k in fields]+[q['id']])
                cases = ' '.join('WHEN ? THEN ?' for _ in mapping)
                params = [v for pair in mapping.items() for v in pair]
                for table in ('user_answers','question_issue_reports'):
                    conn.execute(f'UPDATE {table} SET selected_answer=CASE selected_answer {cases} ELSE selected_answer END WHERE question_id=?',params+[q['id']])
        return len(preview['edits'])
    finally:
        conn.close()
