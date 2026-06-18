"""
analytics.py — Higher-level analytics built on top of DB raw data.
All functions accept an optional course_id for course-scoped stats.
"""

from __future__ import annotations
from datetime import datetime
import pandas as pd

from src.database import get_attempts, get_answer_stats, get_review_states
from src.scoring  import get_weak_areas


def _accuracy_breakdown(answers: list[dict], field: str, unknown: str) -> dict:
    """Group answer accuracy by one answer field."""
    grouped: dict[str, dict] = {}
    for answer in answers:
        key = str(answer.get(field) or unknown).strip() or unknown
        if key not in grouped:
            grouped[key] = {"total": 0, "correct": 0}
        grouped[key]["total"] += 1
        grouped[key]["correct"] += int(bool(answer.get("is_correct")))

    for value in grouped.values():
        value["pct"] = (
            round(value["correct"] / value["total"] * 100, 1)
            if value["total"]
            else 0
        )
    return grouped


def _course_breakdown(answers: list[dict]) -> dict:
    grouped: dict[str, dict] = {}
    for answer in answers:
        course_id = answer.get("question_course_id")
        title = str(answer.get("course_title") or "Unknown Course").strip() or "Unknown Course"
        key = f"{course_id}:{title}" if course_id is not None else title
        if key not in grouped:
            grouped[key] = {"course_id": course_id, "total": 0, "correct": 0}
        grouped[key]["total"] += 1
        grouped[key]["correct"] += int(bool(answer.get("is_correct")))

    for value in grouped.values():
        value["pct"] = (
            round(value["correct"] / value["total"] * 100, 1)
            if value["total"]
            else 0
        )
    return {
        key.split(":", 1)[1] if ":" in key else key: value
        for key, value in grouped.items()
    }


def _attempt_trend_from_answers(answers: list[dict]) -> pd.DataFrame:
    if not answers:
        return pd.DataFrame()

    grouped: dict[int, dict] = {}
    for answer in answers:
        attempt_id = answer.get("attempt_id")
        if attempt_id is None:
            continue
        row = grouped.setdefault(
            attempt_id,
            {
                "completed_at": answer.get("completed_at"),
                "mode": answer.get("mode"),
                "total": 0,
                "correct": 0,
            },
        )
        row["total"] += 1
        row["correct"] += int(bool(answer.get("is_correct")))

    rows = []
    for attempt_id, value in grouped.items():
        total = value["total"]
        rows.append({
            "attempt_id": attempt_id,
            "completed_at": value["completed_at"],
            "mode": value["mode"],
            "total_questions": total,
            "correct_answers": value["correct"],
            "percent_correct": round(value["correct"] / total * 100, 1) if total else 0,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["completed_at"] = pd.to_datetime(df["completed_at"])
    return df.sort_values("completed_at")


def _weakest_breakdown(
    grouped: dict,
    label_key: str,
    min_answers: int = 1,
    top_n: int = 5,
    max_percent: float | None = None,
) -> list[dict]:
    """Return the lowest-accuracy groups with enough attempts to be meaningful."""
    ranked = [
        {label_key: label, "percent": values["pct"], **values}
        for label, values in grouped.items()
        if values["total"] >= min_answers
        and (max_percent is None or values["pct"] < max_percent)
    ]
    ranked.sort(key=lambda item: (item["percent"], -item["total"], item[label_key]))
    return ranked[:top_n]


# ── Dashboard stats ───────────────────────────────────────────────────────────
def get_dashboard_stats(user_id: int,
                         course_id: int | None = None,
                         course_ids: list[int] | None = None,
                         completed_from=None,
                         completed_to=None) -> dict:
    """Return a summary dict for the Dashboard page."""
    answers = get_answer_stats(
        user_id,
        course_id=course_id,
        course_ids=course_ids,
        completed_from=completed_from,
        completed_to=completed_to,
    )

    empty = {
        "total_attempts":   0,
        "total_questions":  0,
        "avg_percent":      None,
        "latest_percent":   None,
        "latest_scaled":    None,
        "best_percent":     None,
        "weak_areas":       [],
        "weak_modules":     [],
        "weak_courses":     [],
        "accuracy_by_module": {},
        "accuracy_by_course": {},
        "score_trend":      pd.DataFrame(),
        "accuracy_by_type": {},
        "accuracy_by_diff": {},
        "improvement_trend": None,
    }

    if not answers:
        return empty

    df_a = _attempt_trend_from_answers(answers)
    if df_a.empty:
        return empty
    score_trend = df_a[
        [
            "attempt_id",
            "completed_at",
            "percent_correct",
            "mode",
            "total_questions",
            "correct_answers",
        ]
    ].copy()

    weak_areas = get_weak_areas(answers, top_n=3)

    acc_course = _course_breakdown(answers)
    weak_courses = _weakest_breakdown(
        acc_course,
        label_key="course",
        min_answers=1,
        top_n=5,
        max_percent=75,
    )

    # Accuracy by module / curriculum area. In this app, questions store their
    # module name in section_type.
    acc_module = _accuracy_breakdown(answers, "section_type", "Unknown Module")
    weak_modules = _weakest_breakdown(
        acc_module,
        label_key="module",
        min_answers=1,
        top_n=5,
        max_percent=75,
    )

    # Accuracy by question type
    acc_type = _accuracy_breakdown(answers, "question_type", "Unknown")

    # Accuracy by difficulty
    acc_diff: dict[int, dict] = {}
    for a in answers:
        d = int(a.get("difficulty") or 3)
        if d not in acc_diff:
            acc_diff[d] = {"total": 0, "correct": 0}
        acc_diff[d]["total"]   += 1
        acc_diff[d]["correct"] += int(bool(a.get("is_correct")))
    for v in acc_diff.values():
        v["pct"] = round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0

    # Improvement trend: compare first half vs second half of attempts
    improvement_trend = None
    if len(df_a) >= 4:
        half = len(df_a) // 2
        first_half_avg  = df_a.iloc[:half]["percent_correct"].mean()
        second_half_avg = df_a.iloc[half:]["percent_correct"].mean()
        improvement_trend = round(second_half_avg - first_half_avg, 1)

    latest = df_a.iloc[-1]
    return {
        "total_attempts":    len(df_a),
        "total_questions":   len(answers),
        "avg_percent":       round(df_a["percent_correct"].mean(), 1),
        "latest_percent":    round(latest["percent_correct"], 1),
        "latest_scaled":     None,
        "best_percent":      round(df_a["percent_correct"].max(), 1),
        "weak_areas":        weak_areas,
        "weak_modules":      weak_modules,
        "weak_courses":      weak_courses,
        "accuracy_by_module": acc_module,
        "accuracy_by_course": acc_course,
        "score_trend":       score_trend,
        "accuracy_by_type":  acc_type,
        "accuracy_by_diff":  acc_diff,
        "improvement_trend": improvement_trend,
    }


# ── Score history ─────────────────────────────────────────────────────────────
def get_score_history(user_id: int,
                       course_id: int | None = None) -> pd.DataFrame:
    attempts = get_attempts(user_id, limit=200, course_id=course_id)
    if not attempts:
        return pd.DataFrame()

    rows = []
    for a in attempts:
        rows.append({
            "Date":      a["completed_at"][:10] if a["completed_at"] else "",
            "Mode":      a["mode"],
            "Section":   a["section_type"],
            "Questions": a["total_questions"],
            "Correct":   a["correct_answers"],
            "% Correct": a["percent_correct"],
            "Hard Mode": "Yes" if a["is_hard_mode"] else "No",
            "attempt_id": a["id"],
        })

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date", ascending=False)


# ── Weakness-weighted question selection ──────────────────────────────────────
def get_module_attempt_history(
    user_id: int,
    course_id: int | None = None,
    course_ids: list[int] | None = None,
    completed_from=None,
    completed_to=None,
) -> pd.DataFrame:
    """Return one row per module per completed attempt."""
    answers = get_answer_stats(
        user_id,
        course_id=course_id,
        course_ids=course_ids,
        completed_from=completed_from,
        completed_to=completed_to,
    )
    if not answers:
        return pd.DataFrame()

    grouped: dict[tuple, dict] = {}
    for answer in answers:
        attempt_id = answer.get("attempt_id")
        if attempt_id is None:
            continue
        course_title = str(answer.get("course_title") or "Unknown Course").strip() or "Unknown Course"
        module = str(answer.get("section_type") or "Unknown Module").strip() or "Unknown Module"
        key = (course_title, module, attempt_id)
        row = grouped.setdefault(
            key,
            {
                "Course": course_title,
                "Module": module,
                "Date": answer.get("completed_at"),
                "Mode": answer.get("mode") or "",
                "Attempt ID": attempt_id,
                "Questions": 0,
                "Correct": 0,
            },
        )
        row["Questions"] += 1
        row["Correct"] += int(bool(answer.get("is_correct")))

    rows = []
    for row in grouped.values():
        total = row["Questions"]
        row["% Correct"] = round(row["Correct"] / total * 100, 1) if total else 0
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(["Course", "Module", "Date", "Attempt ID"])
    df["Attempt #"] = df.groupby(["Course", "Module"]).cumcount() + 1
    latest_attempt = df.groupby(["Course", "Module"])["Attempt #"].transform("max")
    df["Latest"] = df["Attempt #"].eq(latest_attempt)
    return df.sort_values(["Date", "Course", "Module"], ascending=[False, True, True])


def get_weakness_weighted_questions(
    user_id: int,
    all_questions: list[dict],
    n: int = 25,
    course_id: int | None = None,
) -> list[dict]:
    """Return n questions from the smart review queue.

    Backward-compatible wrapper for older imports. Selection is driven by
    per-question mastery state: due missed items come first, repeated correct
    answers push items farther into the future, and retired items only appear
    when the filtered pool is otherwise exhausted.
    """
    return get_smart_review_questions(user_id, all_questions, n=n, course_id=course_id)


def get_smart_review_questions(
    user_id: int,
    all_questions: list[dict],
    n: int = 25,
    course_id: int | None = None,
) -> list[dict]:
    """Return n questions prioritized by spaced-review readiness and weakness."""
    import random

    if not all_questions:
        return []

    answers = get_answer_stats(user_id, course_id=course_id)
    weak_areas = get_weak_areas(answers, top_n=5)
    weakness_by_type = {
        w["question_type"]: max(0.0, 100.0 - float(w["percent"]))
        for w in weak_areas
    }

    question_ids = [q["id"] for q in all_questions if q.get("id") is not None]
    states = {
        s["question_id"]: s
        for s in get_review_states(user_id, question_ids=question_ids, course_id=course_id)
    }
    now = datetime.now()

    def parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            try:
                return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None

    ranked = []
    for q in all_questions:
        state = states.get(q.get("id"))
        qtype = q.get("question_type") or "Unknown"
        type_bonus = weakness_by_type.get(qtype, 0.0)
        jitter = random.random()

        if state:
            mastery = int(state.get("mastery_level") or 0)
            misses = int(state.get("misses") or 0)
            retired = bool(state.get("retired"))
            due_at = parse_dt(state.get("next_review_at"))
            days_delta = ((now - due_at).total_seconds() / 86400.0) if due_at else 0.0

            if retired:
                priority = 5.0 + type_bonus * 0.05 + jitter
            elif due_at is None or due_at <= now:
                priority = (
                    1000.0
                    + max(days_delta, 0.0) * 12.0
                    + misses * 10.0
                    - mastery * 8.0
                    + type_bonus
                    + jitter
                )
            else:
                days_until_due = max(-days_delta, 0.0)
                priority = (
                    220.0
                    - days_until_due * 12.0
                    + misses * 6.0
                    - mastery * 10.0
                    + type_bonus * 0.5
                    + jitter
                )
        else:
            priority = 90.0 + type_bonus + jitter

        smart_review_state = None
        if state:
            smart_review_state = {
                "times_seen": int(state.get("times_seen") or 0),
                "misses": int(state.get("misses") or 0),
                "correct_streak": int(state.get("correct_streak") or 0),
                "mastery_level": int(state.get("mastery_level") or 0),
                "next_review_at": state.get("next_review_at"),
                "last_answered_at": state.get("last_answered_at"),
                "retired": bool(state.get("retired")),
            }

        item = dict(q)
        if smart_review_state and smart_review_state["times_seen"] > 0:
            item["_smart_review_state"] = smart_review_state
        ranked.append((priority, item))

    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen = [q for _, q in ranked[: min(n, len(ranked))]]
    random.shuffle(chosen)
    return chosen
