"""Exact course/chapter and difficulty quotas for practice exams."""

from collections import Counter, defaultdict, deque
import math


def percentage_counts(weights, total):
    """Largest-remainder rounding, preserving zero weights and the total."""
    if not weights or any(not math.isfinite(v) or v < 0 for v in weights.values()):
        raise ValueError("Enter nonnegative allocation percentages.")
    if round(sum(weights.values()), 2) != 100:
        raise ValueError("Allocation percentages must total 100%.")
    raw = {key: total * value / sum(weights.values()) for key, value in weights.items()}
    counts = {key: math.floor(value) for key, value in raw.items()}
    for key in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[:total - sum(counts.values())]:
        counts[key] += 1
    return counts


def question_group(question):
    return question['course_id'], module_label(question)


def module_label(question):
    return question.get('practice_module_label') or question.get('section_type') or ''


def practice_questions(course_ids):
    """Expose CCRN's actual chapters alongside ordinary course modules."""
    from src.database import get_all_questions, get_connection
    conn = get_connection()
    try:
        has_chapters = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='course_chapters'").fetchone()
        chapters = {row['id']: row['name'] for row in conn.execute('SELECT id, name FROM course_chapters')} if has_chapters else {}
    finally:
        conn.close()
    questions = [q for cid in course_ids for q in get_all_questions(course_id=cid)]
    for question in questions:
        chapter = chapters.get(question.get('chapter_id'))
        if chapter:
            question['practice_module_label'] = f"{question.get('section_type') or 'Chapters'} / {chapter}"
    return questions


def allocation_plan(questions, group_counts, difficulty_counts):
    """Match both sets of quotas using integral bipartite max flow.

    Return counts by (course/chapter group, difficulty), or a blocking error.
    Residual edges allow reassignment when a scarce difficulty needs a group.
    """
    capacity = Counter((question_group(q), int(q['difficulty'])) for q in questions)
    residual = defaultdict(dict)
    source, sink = ('source',), ('sink',)

    def edge(a, b, count):
        residual[a][b] = count
        residual[b][a] = 0

    if sum(group_counts.values()) != sum(difficulty_counts.values()):
        raise ValueError("Course and difficulty question totals must match.")
    for group, count in group_counts.items():
        edge(source, ('group', group), count)
        for difficulty in difficulty_counts:
            edge(('group', group), ('difficulty', difficulty), capacity[group, difficulty])
    for difficulty, count in difficulty_counts.items():
        edge(('difficulty', difficulty), sink, count)
    flow = 0
    while True:
        parents = {source: None}
        queue = deque([source])
        while queue and sink not in parents:
            node = queue.popleft()
            for neighbor, count in residual[node].items():
                if count > 0 and neighbor not in parents:
                    parents[neighbor] = node
                    queue.append(neighbor)
        if sink not in parents:
            break
        node, amount = sink, float('inf')
        while parents[node] is not None:
            parent = parents[node]
            amount = min(amount, residual[parent][node])
            node = parent
        node = sink
        while parents[node] is not None:
            parent = parents[node]
            residual[parent][node] -= amount
            residual[node][parent] += amount
            node = parent
        flow += amount
    if flow != sum(group_counts.values()):
        raise ValueError(
            f"Only {flow} of {sum(group_counts.values())} questions can fit both the "
            "allocation and difficulty counts. Adjust the percentages, difficulty counts, "
            "or module/chapter filters."
        )
    return {(group, difficulty): residual[('difficulty', difficulty)][('group', group)]
            for group in group_counts for difficulty in difficulty_counts}
