"""
src/curriculum_allocation.py — Centralised allocation logic for Curriculum Exams.

All four allocation strategies live here so the exam page just calls helpers:

  equal_allocation(courses, total_q)
      → Even split across all courses, rounding-adjusted.

  preset_allocation(courses, preset_weights, total_q)
      → Uses saved % weights, normalises to selected courses, validates.

  manual_allocation(courses, weight_inputs, total_q)
      → Uses user-entered % weights, validates total = 100.

  random_allocation(courses, total_q, balanced=True)
      → Randomly assigns questions across courses with floor guarantees.

Each function returns an AllocationResult with:
  .rows          list of dicts  {course_id, course_title, pct, requested, available, final}
  .final_total   int            sum of .final across rows
  .method        str            "equal" | "preset" | "manual" | "random"
  .warnings      list[str]      human-readable warnings (shortages, rounding, etc.)
  .errors        list[str]      blocking errors (weights ≠ 100%, etc.)
  .valid         bool           True if exam can proceed
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Any


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class AllocationResult:
    method:      str
    rows:        list[dict]       = field(default_factory=list)
    final_total: int              = 0
    warnings:    list[str]        = field(default_factory=list)
    errors:      list[str]        = field(default_factory=list)
    valid:       bool             = True

    def as_dist(self) -> list[dict]:
        """Convert to the format expected by _launch_exam / score history."""
        return [
            {
                "course":    r["course_title"],
                "weight":    round(r["pct"], 2),
                "q_count":   r["final"],
                "method":    self.method,
            }
            for r in self.rows
        ]

    def method_label(self) -> str:
        return {
            "equal":  "Equal Weighting",
            "preset": "Preset Weighting",
            "manual": "Manual Weighting",
            "random": "Random Mix",
        }.get(self.method, self.method.title())


# ── Shared rounding helper ────────────────────────────────────────────────────

def _distribute_with_rounding(
    courses: list[dict],
    raw_counts: dict[int, float],
    total_q: int,
    avail_map: dict[int, int],
) -> tuple[dict[int, int], list[str]]:
    """
    Given raw (float) question counts, floor them then distribute remainder by
    largest fraction.  Caps each course at its available question count.
    Returns (final_counts, shortage_warnings).
    """
    floored  = {c["id"]: math.floor(raw_counts[c["id"]]) for c in courses}
    deficit  = total_q - sum(floored.values())
    fracs    = sorted(
        [(c["id"], raw_counts[c["id"]] - floored[c["id"]]) for c in courses],
        key=lambda x: x[1],
        reverse=True,
    )
    for i, (cid, _) in enumerate(fracs):
        if i < deficit:
            floored[cid] += 1

    final = {}
    warnings: list[str] = []
    for c in courses:
        cid     = c["id"]
        need    = floored[cid]
        avail   = avail_map[cid]
        f       = min(need, avail)
        final[cid] = f
        if f < need:
            warnings.append(
                f"**{c['title']}** needs {need} but only {avail} available "
                f"(short by {need - f})."
            )
    return final, warnings


# ── Equal allocation ──────────────────────────────────────────────────────────

def equal_allocation(
    courses: list[dict],
    total_q: int,
    avail_map: dict[int, int],
) -> AllocationResult:
    """
    Distribute `total_q` evenly across all courses.
    """
    n   = len(courses)
    pct = 100.0 / n if n else 0.0
    raw = {c["id"]: (pct / 100.0) * total_q for c in courses}
    final, warns = _distribute_with_rounding(courses, raw, total_q, avail_map)

    rows = [
        {
            "course_id":    c["id"],
            "course_title": c["title"],
            "pct":          pct,
            "requested":    math.floor(raw[c["id"]]),
            "available":    avail_map[c["id"]],
            "final":        final[c["id"]],
        }
        for c in courses
    ]
    result = AllocationResult(method="equal", rows=rows, warnings=warns)
    result.final_total = sum(r["final"] for r in rows)
    result.valid = result.final_total > 0
    if result.final_total == 0:
        result.errors.append("No questions are available in the selected courses.")
    return result


# ── Preset allocation ─────────────────────────────────────────────────────────

def preset_allocation(
    courses: list[dict],
    preset_weights: dict[Any, float],  # keys may be str or int course IDs
    total_q: int,
    avail_map: dict[int, int],
    normalize: bool = True,
) -> AllocationResult:
    """
    Distribute questions according to saved preset percentages.
    If `normalize` is True, re-scales the preset weights so they sum to 100%
    across only the *selected* courses (ignoring any preset entries whose
    course isn't in `courses`).
    """
    # Normalise preset key types to int
    pw: dict[int, float] = {}
    for k, v in preset_weights.items():
        try:
            pw[int(k)] = float(v)
        except (ValueError, TypeError):
            pass

    selected_ids = {c["id"] for c in courses}

    # Pull only weights that match selected courses
    partial_weights = {cid: pw.get(cid, 0.0) for cid in selected_ids}
    total_partial   = sum(partial_weights.values())

    warnings: list[str] = []
    errors:   list[str] = []

    # Warn about preset courses not selected
    preset_only_ids = set(pw.keys()) - selected_ids
    if preset_only_ids:
        warnings.append(
            f"{len(preset_only_ids)} preset course(s) are not selected and will be ignored."
        )

    # Warn about selected courses with 0 preset weight
    zero_weight_courses = [c["title"] for c in courses if partial_weights[c["id"]] == 0.0]
    if zero_weight_courses:
        warnings.append(
            "These selected courses have 0% in the preset: "
            + ", ".join(f"**{t}**" for t in zero_weight_courses)
            + ".  They will receive 0 questions unless you adjust."
        )

    if total_partial == 0.0:
        errors.append("No preset weights found for the selected courses.")
        result = AllocationResult(method="preset", errors=errors, valid=False)
        return result

    # Normalise so selected courses sum to 100
    if normalize and abs(total_partial - 100.0) > 0.05:
        factor = 100.0 / total_partial
        partial_weights = {cid: v * factor for cid, v in partial_weights.items()}
        warnings.append(
            f"Preset weights for selected courses summed to {total_partial:.1f}%. "
            "They have been normalised to 100% across the selected courses."
        )
    elif not normalize and abs(total_partial - 100.0) > 0.5:
        errors.append(
            f"Preset weights for selected courses sum to {total_partial:.1f}%, not 100%. "
            "Enable normalisation or adjust the preset."
        )
        result = AllocationResult(method="preset", errors=errors, valid=False)
        return result

    raw = {c["id"]: (partial_weights[c["id"]] / 100.0) * total_q for c in courses}
    final, shortage_warns = _distribute_with_rounding(courses, raw, total_q, avail_map)
    warnings.extend(shortage_warns)

    rows = [
        {
            "course_id":    c["id"],
            "course_title": c["title"],
            "pct":          partial_weights[c["id"]],
            "requested":    math.floor(raw[c["id"]]),
            "available":    avail_map[c["id"]],
            "final":        final[c["id"]],
        }
        for c in courses
    ]
    result = AllocationResult(method="preset", rows=rows, warnings=warnings, errors=errors)
    result.final_total = sum(r["final"] for r in rows)
    result.valid = not errors and result.final_total > 0
    return result


# ── Manual allocation ─────────────────────────────────────────────────────────

def manual_allocation(
    courses: list[dict],
    weight_inputs: dict[int, float],   # course_id → pct (0–100)
    total_q: int,
    avail_map: dict[int, int],
) -> AllocationResult:
    """
    Validate that weights sum to 100, then distribute questions.
    """
    total_w = sum(weight_inputs.get(c["id"], 0.0) for c in courses)
    errors:   list[str] = []
    warnings: list[str] = []

    if abs(total_w - 100.0) > 0.5:
        direction = "exceeds" if total_w > 100 else "is below"
        errors.append(
            f"Current total: {total_w:.1f}%. "
            f"Weights {direction} 100% — please adjust before generating."
        )
        result = AllocationResult(method="manual", errors=errors, valid=False)
        result.rows = [
            {
                "course_id":    c["id"],
                "course_title": c["title"],
                "pct":          weight_inputs.get(c["id"], 0.0),
                "requested":    0,
                "available":    avail_map[c["id"]],
                "final":        0,
            }
            for c in courses
        ]
        return result

    raw = {c["id"]: (weight_inputs.get(c["id"], 0.0) / 100.0) * total_q for c in courses}
    final, shortage_warns = _distribute_with_rounding(courses, raw, total_q, avail_map)
    warnings.extend(shortage_warns)

    rows = [
        {
            "course_id":    c["id"],
            "course_title": c["title"],
            "pct":          weight_inputs.get(c["id"], 0.0),
            "requested":    math.floor(raw[c["id"]]),
            "available":    avail_map[c["id"]],
            "final":        final[c["id"]],
        }
        for c in courses
    ]
    result = AllocationResult(method="manual", rows=rows, warnings=warnings)
    result.final_total = sum(r["final"] for r in rows)
    result.valid = result.final_total > 0
    return result


# ── Random allocation ─────────────────────────────────────────────────────────

_BALANCED_MAX_SINGLE_PCT = 40.0   # No single course takes more than this in balanced mode


def random_allocation(
    courses: list[dict],
    total_q: int,
    avail_map: dict[int, int],
    balanced: bool = True,
    seed: int | None = None,
) -> AllocationResult:
    """
    Randomly assign questions across courses.

    balanced=True  → each course gets at least 1 question and no single
                     course takes more than _BALANCED_MAX_SINGLE_PCT %.
    balanced=False → fully random (Dirichlet-like) — one course may dominate.

    Always guarantees total == total_q if possible.
    """
    rng      = random.Random(seed)
    n        = len(courses)
    warnings: list[str] = []
    errors:   list[str] = []

    if n == 0:
        e = AllocationResult(method="random", valid=False)
        e.errors.append("No courses selected.")
        return e

    if total_q < n:
        warnings.append(
            f"You have {n} courses but only {total_q} questions requested. "
            "Some courses will receive 0 questions."
        )

    # Generate random weights
    if balanced:
        max_pct = min(_BALANCED_MAX_SINGLE_PCT, 100.0 / n * 2.5)
        for _attempt in range(200):
            raw_pcts = [rng.uniform(1.0, max_pct) for _ in range(n)]
            total_p  = sum(raw_pcts)
            normed   = [p / total_p * 100.0 for p in raw_pcts]
            if all(p <= _BALANCED_MAX_SINGLE_PCT + 0.1 for p in normed):
                break
        else:
            # fallback: equal weights
            normed = [100.0 / n] * n
    else:
        # Dirichlet-like (exponential trick)
        raw_pcts = [-math.log(rng.random()) for _ in range(n)]
        total_p  = sum(raw_pcts)
        normed   = [p / total_p * 100.0 for p in raw_pcts]

    # Map to courses
    pct_map = {c["id"]: normed[i] for i, c in enumerate(courses)}
    raw_map = {c["id"]: (pct_map[c["id"]] / 100.0) * total_q for c in courses}

    # Ensure at least 1 per course if total_q >= n
    floored = {c["id"]: max(1, math.floor(raw_map[c["id"]])) for c in courses} \
              if total_q >= n \
              else {c["id"]: math.floor(raw_map[c["id"]]) for c in courses}

    # Fix total after floor/ceiling adjustments
    current_total = sum(floored.values())
    deficit = total_q - current_total

    if deficit > 0:
        # Add to courses with largest fractional parts
        fracs = sorted(
            [(c["id"], raw_map[c["id"]] - math.floor(raw_map[c["id"]])) for c in courses],
            key=lambda x: x[1], reverse=True,
        )
        for i, (cid, _) in enumerate(fracs):
            if i >= deficit:
                break
            floored[cid] += 1
    elif deficit < 0:
        # Remove from smallest courses
        sorted_by_count = sorted(courses, key=lambda c: floored[c["id"]], reverse=True)
        excess = -deficit
        for c in sorted_by_count:
            if excess <= 0:
                break
            reduction = min(excess, floored[c["id"]] - (1 if total_q >= n else 0))
            if reduction > 0:
                floored[c["id"]] -= reduction
                excess -= reduction

    # Cap at available
    final: dict[int, int] = {}
    for c in courses:
        cid   = c["id"]
        need  = floored.get(cid, 0)
        avail = avail_map[cid]
        f     = min(need, avail)
        final[cid] = f
        if f < need:
            warnings.append(
                f"**{c['title']}** needed {need} but only {avail} available."
            )

    rows = [
        {
            "course_id":    c["id"],
            "course_title": c["title"],
            "pct":          pct_map[c["id"]],
            "requested":    floored[c["id"]],
            "available":    avail_map[c["id"]],
            "final":        final[c["id"]],
        }
        for c in courses
    ]
    result = AllocationResult(method="random", rows=rows, warnings=warnings, errors=errors)
    result.final_total = sum(r["final"] for r in rows)
    result.valid = result.final_total > 0
    return result
