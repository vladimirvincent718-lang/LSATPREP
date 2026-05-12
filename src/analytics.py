"""
analytics.py — Higher-level analytics built on top of DB raw data.
All functions accept an optional course_id for course-scoped stats.
"""

from __future__ import annotations
import pandas as pd

from src.database import get_attempts, get_answer_stats
from src.scoring  import get_weak_areas


# ── Dashboard stats ───────────────────────────────────────────────────────────
def get_dashboard_stats(user_id: int,
                         course_id: int | None = None) -> dict:
    """Return a summary dict for the Dashboard page."""
    attempts = get_attempts(user_id, limit=100, course_id=course_id)
    answers  = get_answer_stats(user_id, course_id=course_id)

    empty = {
        "total_attempts":   0,
        "total_questions":  0,
        "avg_percent":      None,
        "latest_percent":   None,
        "latest_scaled":    None,
        "best_percent":     None,
        "weak_areas":       [],
        "score_trend":      pd.DataFrame(),
        "accuracy_by_type": {},
        "accuracy_by_diff": {},
        "improvement_trend": None,
    }

    if not attempts:
        return empty

    df_a = pd.DataFrame(attempts)
    df_a["completed_at"] = pd.to_datetime(df_a["completed_at"])
    score_trend = df_a[["completed_at", "percent_correct", "mode"]].copy()
    score_trend = score_trend.sort_values("completed_at")

    weak_areas = get_weak_areas(answers, top_n=3)

    # Accuracy by question type
    acc_type: dict[str, dict] = {}
    for a in answers:
        qt = a.get("question_type") or "Unknown"
        if qt not in acc_type:
            acc_type[qt] = {"total": 0, "correct": 0}
        acc_type[qt]["total"]   += 1
        acc_type[qt]["correct"] += int(bool(a.get("is_correct")))
    for v in acc_type.values():
        v["pct"] = round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0

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
        "total_attempts":    len(attempts),
        "total_questions":   int(df_a["total_questions"].sum()),
        "avg_percent":       round(df_a["percent_correct"].mean(), 1),
        "latest_percent":    round(latest["percent_correct"], 1),
        "latest_scaled":     None,
        "best_percent":      round(df_a["percent_correct"].max(), 1),
        "weak_areas":        weak_areas,
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
def get_weakness_weighted_questions(
    user_id: int,
    all_questions: list[dict],
    n: int = 25,
    weakness_ratio: float = 0.6,
    course_id: int | None = None,
) -> list[dict]:
    """Return n questions biased toward the user's weak question types."""
    import random
    answers    = get_answer_stats(user_id, course_id=course_id)
    weak_areas = get_weak_areas(answers, top_n=5)
    weak_types = {w["question_type"] for w in weak_areas}

    weak_pool  = [q for q in all_questions if q.get("question_type") in weak_types]
    other_pool = [q for q in all_questions if q.get("question_type") not in weak_types]

    n_weak  = min(int(n * weakness_ratio), len(weak_pool))
    n_other = min(n - n_weak, len(other_pool))

    chosen = random.sample(weak_pool, n_weak) + random.sample(other_pool, n_other)
    random.shuffle(chosen)
    return chosen[:n]
