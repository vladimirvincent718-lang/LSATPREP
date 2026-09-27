"""Keep question-bank items that depend on earlier items together and in order."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable


_DEPENDENCY_CUE = re.compile(
    r"\b(?:the\s+)?(?:previous|preceding|prior)\s+question\b|"
    r"\bquestion\s+(?:immediately\s+)?above\b",
    re.IGNORECASE,
)
_SEQUENCE_ID = re.compile(r"^(.*?)(\d+)$")


def references_previous_question(question: dict) -> bool:
    """Return whether the learner-facing text explicitly relies on an earlier item."""
    text = " ".join(
        str(question.get(field) or "") for field in ("passage", "stimulus")
    )
    return bool(_DEPENDENCY_CUE.search(text))


def _identity(question: dict) -> tuple:
    if question.get("id") is not None:
        return ("id", question["id"])
    return (
        "question_id",
        question.get("course_id"),
        str(question.get("question_id") or ""),
    )


def _sequence_key(question: dict) -> tuple | None:
    question_id = str(question.get("question_id") or "").strip()
    match = _SEQUENCE_ID.match(question_id)
    if not match:
        return None
    return question.get("course_id"), match.group(1).casefold(), int(match.group(2))


def arrange_question_dependencies(
    questions: Iterable[dict],
    available_questions: Iterable[dict] | None = None,
    target_count: int | None = None,
) -> list[dict]:
    """Return a session where explicit "previous question" chains are intact.

    The numeric suffix of ``question_id`` identifies the preceding bank item. If
    a selected dependent item is missing its prerequisite, the prerequisite is
    brought in from ``available_questions`` and an unrelated item is removed so
    the requested session size stays constant. A dependent item whose prerequisite
    cannot be found is omitted instead of presenting a broken question.
    """
    selected = list(questions)
    if not selected:
        return []
    if target_count is None:
        target_count = len(selected)
    target_count = max(0, int(target_count))

    available = (
        list(available_questions)
        if available_questions is not None
        else list(selected)
    )
    combined: list[dict] = []
    seen: set[tuple] = set()
    for question in [*available, *selected]:
        key = _identity(question)
        if key not in seen:
            combined.append(question)
            seen.add(key)

    by_identity = {_identity(question): question for question in combined}
    by_sequence = {
        key: question
        for question in combined
        if (key := _sequence_key(question)) is not None
    }

    def parent_of(question: dict) -> dict | None:
        if not references_previous_question(question):
            return None
        key = _sequence_key(question)
        if key is None or key[2] <= 0:
            return None
        return by_sequence.get((key[0], key[1], key[2] - 1))

    def chain_for(question: dict) -> list[dict] | None:
        chain: list[dict] = []
        chain_seen: set[tuple] = set()
        current = question
        while True:
            key = _identity(current)
            if key in chain_seen:
                return None
            chain_seen.add(key)
            chain.append(current)
            if not references_previous_question(current):
                break
            parent = parent_of(current)
            if parent is None:
                return None
            current = parent
        chain.reverse()
        return chain

    kept: dict[tuple, dict] = {}
    selected_rank = {_identity(question): rank for rank, question in enumerate(selected)}
    desired_course_counts = Counter(question.get("course_id") for question in selected)
    for question in selected:
        chain = chain_for(question)
        if chain is not None:
            for item in chain:
                kept[_identity(item)] = item

    def required_parent_keys() -> set[tuple]:
        required: set[tuple] = set()
        for item in kept.values():
            parent = parent_of(item)
            if parent is not None and _identity(parent) in kept:
                required.add(_identity(parent))
        return required

    while len(kept) > target_count:
        required = required_parent_keys()
        removable = [key for key in kept if key not in required]
        current_course_counts = Counter(
            item.get("course_id") for item in kept.values()
        )
        overrepresented_courses = {
            course_id
            for course_id, count in current_course_counts.items()
            if count > desired_course_counts.get(course_id, 0)
        }
        same_course_removable = [
            key
            for key in removable
            if kept[key].get("course_id") in overrepresented_courses
        ]
        if same_course_removable:
            removable = same_course_removable
        if not removable:
            break
        # Preserve dependency chains preferentially; discard unrelated selections first.
        removable.sort(
            key=lambda key: (
                parent_of(kept[key]) is None,
                selected_rank.get(key, -1),
            ),
            reverse=True,
        )
        del kept[removable[0]]

    # Fill gaps left by malformed dependencies without exceeding the requested size.
    selected_courses = {
        question.get("course_id")
        for question in selected
        if question.get("course_id") is not None
    }
    for candidate in available:
        if len(kept) >= target_count:
            break
        if selected_courses and candidate.get("course_id") not in selected_courses:
            continue
        chain = chain_for(candidate)
        if chain is None:
            continue
        missing = [item for item in chain if _identity(item) not in kept]
        projected_course_counts = Counter(
            item.get("course_id") for item in kept.values()
        )
        projected_course_counts.update(item.get("course_id") for item in missing)
        if any(
            count > desired_course_counts.get(course_id, 0)
            for course_id, count in projected_course_counts.items()
        ):
            continue
        if missing and len(kept) + len(missing) <= target_count:
            for item in missing:
                kept[_identity(item)] = item

    if not kept:
        return []

    # Build contiguous chains. Their position follows the selected random order,
    # while each prerequisite is guaranteed to appear immediately before its child.
    children: dict[tuple, list[tuple]] = {}
    parent_keys: dict[tuple, tuple] = {}
    for key, item in kept.items():
        parent = parent_of(item)
        if parent is None:
            continue
        parent_key = _identity(parent)
        if parent_key in kept:
            parent_keys[key] = parent_key
            children.setdefault(parent_key, []).append(key)

    roots = [key for key in kept if key not in parent_keys]
    available_rank = {_identity(question): rank for rank, question in enumerate(available)}

    def group_rank(root: tuple) -> int:
        stack = [root]
        ranks: list[int] = []
        while stack:
            key = stack.pop()
            if key in selected_rank:
                ranks.append(selected_rank[key])
            stack.extend(children.get(key, []))
        return min(ranks) if ranks else available_rank.get(root, len(available_rank))

    roots.sort(key=group_rank)
    ordered: list[dict] = []

    def append_chain(key: tuple) -> None:
        ordered.append(by_identity[key])
        child_keys = children.get(key, [])
        child_keys.sort(
            key=lambda child: (
                _sequence_key(by_identity[child]) or (None, "", 0)
            )[2]
        )
        for child in child_keys:
            append_chain(child)

    for root in roots:
        append_chain(root)
    return ordered[:target_count]
