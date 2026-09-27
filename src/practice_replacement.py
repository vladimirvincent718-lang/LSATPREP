"""Find the closest unused replacement before widening curriculum scope."""

from src.practice_allocation import module_label, practice_questions
from src.question_ordering import references_previous_question
from src.practice_session_edit import refers_to_numbered_question


def replacement_pool(current, enrolled_course_ids):
    from src.database import get_all_curriculums, get_curriculum_courses

    course_id = current.get("course_id")
    allowed = set(enrolled_course_ids)
    course_ids = {course_id} if course_id in allowed else set()
    for curriculum in get_all_curriculums():
        members = {c["id"] for c in get_curriculum_courses(curriculum["id"])}
        if course_id in members:
            course_ids.update(members & allowed)
    return practice_questions(sorted(course_ids))


def closest_replacements(current, pool, used_ids):
    """Return candidates and the first available scope; difficulty breaks ties."""
    candidates = [q for q in pool if q.get("id") is not None
                  and q["id"] not in used_ids and not q.get("is_archived")
                  and not references_previous_question(q)
                  and not refers_to_numbered_question(q)]
    same_course = [q for q in candidates if q.get("course_id") == current.get("course_id")]
    if current.get("chapter_id") is not None:
        same_module = [q for q in same_course if q.get("chapter_id") == current["chapter_id"]]
    else:
        label = module_label(current)
        same_module = [q for q in same_course if label and module_label(q) == label]
    for scope, matches in (("same chapter/module", same_module),
                           ("same course", same_course), ("same curriculum", candidates)):
        if matches:
            same_difficulty = [q for q in matches if q.get("difficulty") == current.get("difficulty")]
            return same_difficulty or matches, scope
    return [], ""
