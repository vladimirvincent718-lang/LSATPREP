"""
scoring.py — All scoring logic.
"""

from __future__ import annotations


def compute_score(answers: list[dict]) -> dict:
    if not answers:
        return _empty_report()

    total   = len(answers)
    correct = sum(1 for a in answers if a.get("is_correct"))
    pct     = round(correct / total * 100, 1) if total else 0
    scaled  = estimate_scaled_score(correct, total)

    section_map: dict[int, dict] = {}
    for a in answers:
        sec = a.get("section_number", 1)
        if sec not in section_map:
            section_map[sec] = {
                "section_number": sec,
                "section_type": a.get("section_type", ""),
                "total": 0, "correct": 0,
            }
        section_map[sec]["total"]   += 1
        section_map[sec]["correct"] += int(bool(a.get("is_correct")))
    for s in section_map.values():
        s["percent"] = round(s["correct"] / s["total"] * 100, 1) if s["total"] else 0

    by_type: dict[str, dict] = {}
    for a in answers:
        t = a.get("section_type") or "Unknown"
        if t not in by_type:
            by_type[t] = {"total": 0, "correct": 0}
        by_type[t]["total"]   += 1
        by_type[t]["correct"] += int(bool(a.get("is_correct")))
    for t in by_type.values():
        t["percent"] = round(t["correct"] / t["total"] * 100, 1) if t["total"] else 0

    by_qtype: dict[str, dict] = {}
    for a in answers:
        qt = a.get("question_type") or "Unknown"
        if qt not in by_qtype:
            by_qtype[qt] = {"total": 0, "correct": 0}
        by_qtype[qt]["total"]   += 1
        by_qtype[qt]["correct"] += int(bool(a.get("is_correct")))
    for qt in by_qtype.values():
        qt["percent"] = round(qt["correct"] / qt["total"] * 100, 1) if qt["total"] else 0

    by_diff: dict[int, dict] = {}
    for a in answers:
        d = a.get("difficulty", 3)
        try:
            d = int(d)
        except (TypeError, ValueError):
            d = 3
        if d not in by_diff:
            by_diff[d] = {"total": 0, "correct": 0}
        by_diff[d]["total"]   += 1
        by_diff[d]["correct"] += int(bool(a.get("is_correct")))
    for d in by_diff.values():
        d["percent"] = round(d["correct"] / d["total"] * 100, 1) if d["total"] else 0

    times    = [a.get("time_spent_seconds", 0) or 0 for a in answers]
    avg_time = round(sum(times) / len(times), 1) if times else 0

    flagged  = [a for a in answers if a.get("is_flagged")]
    flag_pct = (
        round(sum(1 for a in flagged if a["is_correct"]) / len(flagged) * 100, 1)
        if flagged else None
    )

    return {
        "total":            total,
        "correct":          correct,
        "raw_score":        correct,
        "percent_correct":  pct,
        "scaled_score":     scaled,
        "sections":         list(section_map.values()),
        "by_section_type":  by_type,
        "by_question_type": by_qtype,
        "by_difficulty":    by_diff,
        "avg_time_seconds": avg_time,
        "flagged_count":    len(flagged),
        "flagged_accuracy": flag_pct,
    }


def _empty_report() -> dict:
    return {
        "total": 0, "correct": 0, "raw_score": 0,
        "percent_correct": 0, "scaled_score": None,
        "sections": [], "by_section_type": {},
        "by_question_type": {}, "by_difficulty": {},
        "avg_time_seconds": 0, "flagged_count": 0,
        "flagged_accuracy": None,
    }


def estimate_scaled_score(raw: int, total: int) -> str | None:
    if total == 0:
        return None
    pct = raw / total
    if pct >= 0.98: return "~178–180"
    if pct >= 0.95: return "~173–177"
    if pct >= 0.90: return "~168–172"
    if pct >= 0.83: return "~163–167"
    if pct >= 0.75: return "~158–162"
    if pct >= 0.66: return "~153–157"
    if pct >= 0.57: return "~148–152"
    if pct >= 0.47: return "~143–147"
    if pct >= 0.38: return "~138–142"
    if pct >= 0.28: return "~133–137"
    return "~120–132"


def get_weak_areas(answers: list[dict], top_n: int = 3) -> list[dict]:
    tally: dict[str, dict] = {}
    for a in answers:
        qt = a.get("question_type") or "Unknown"
        if qt not in tally:
            tally[qt] = {"total": 0, "correct": 0}
        tally[qt]["total"]   += 1
        tally[qt]["correct"] += int(bool(a.get("is_correct")))
    ranked = []
    for qt, v in tally.items():
        if v["total"] >= 3:
            pct = round(v["correct"] / v["total"] * 100, 1)
            ranked.append({"question_type": qt, "percent": pct, **v})
    ranked.sort(key=lambda x: x["percent"])
    return ranked[:top_n]
