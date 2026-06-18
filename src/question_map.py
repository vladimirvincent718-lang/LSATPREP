from __future__ import annotations

from collections.abc import Callable
from html import escape

import streamlit as st


QuestionState = dict[str, object]


def _state_class(state: QuestionState) -> str:
    status = str(state.get("status") or "unanswered").lower()
    allowed = {"answered", "correct", "wrong", "unanswered", "skipped"}
    return status if status in allowed else "unanswered"


def _status_mark(status: str, flagged: bool) -> str:
    if flagged:
        return "F"
    if status in {"answered", "correct"}:
        return "&check;"
    if status == "wrong":
        return "&times;"
    return ""


def _consume_clicked_index(param_name: str, total: int) -> int | None:
    raw_value = st.query_params.get(param_name)
    if isinstance(raw_value, list):
        raw_value = raw_value[0] if raw_value else None
    try:
        clicked_idx = int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        clicked_idx = None

    if raw_value is not None:
        try:
            del st.query_params[param_name]
        except Exception:
            st.query_params.clear()

    if clicked_idx is None or not (0 <= clicked_idx < total):
        return None
    return clicked_idx


def render_question_map(
    *,
    total: int,
    current_idx: int,
    state_for_index: Callable[[int], QuestionState],
    key_prefix: str,
    columns: int = 4,
) -> int | None:
    """Render a legible, numbered question map and return the clicked index."""

    param_name = f"{key_prefix}_goto"
    clicked_idx = _consume_clicked_index(param_name, total)

    st.markdown(
        """
<style>
.sf-qmap-legend {
  display: grid;
  gap: 0.35rem;
  margin: 0.35rem 0 0.75rem;
  color: rgba(226, 232, 240, 0.86);
  font-size: 0.82rem;
}
.sf-qmap-legend-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.75rem;
}
.sf-qmap-key {
  align-items: center;
  display: inline-flex;
  gap: 0.28rem;
  white-space: nowrap;
}
.sf-qmap-swatch {
  border: 1px solid rgba(15, 23, 42, 0.24);
  border-radius: 0.35rem;
  display: inline-block;
  height: 0.8rem;
  width: 0.8rem;
}
.sf-qmap-swatch.answered,
.sf-qmap-swatch.correct { background: #16a34a; }
.sf-qmap-swatch.wrong { background: #dc2626; }
.sf-qmap-swatch.unanswered,
.sf-qmap-swatch.skipped { background: #f8fafc; }
.sf-qmap-swatch.flagged {
  background: linear-gradient(135deg, #f59e0b 0 50%, #f8fafc 50% 100%);
}
.sf-qmap-grid {
  display: grid;
  gap: 0.62rem;
  margin-top: 0.85rem;
}
.sf-qmap-tile {
  align-items: center;
  border: 2px solid transparent;
  border-radius: 0.5rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.18);
  display: flex;
  font-weight: 800;
  height: 2.4rem;
  justify-content: center;
  line-height: 1;
  min-width: 0;
  position: relative;
  text-decoration: none !important;
}
.sf-qmap-tile:hover {
  filter: brightness(1.06);
  transform: translateY(-1px);
}
.sf-qmap-number {
  font-size: 0.95rem;
}
.sf-qmap-mark {
  bottom: 0.18rem;
  font-size: 0.72rem;
  position: absolute;
  right: 0.24rem;
}
.sf-qmap-tile.correct,
.sf-qmap-tile.answered {
  background: #16a34a;
  color: #ffffff !important;
}
.sf-qmap-tile.wrong {
  background: #dc2626;
  color: #ffffff !important;
}
.sf-qmap-tile.unanswered,
.sf-qmap-tile.skipped {
  background: #f8fafc;
  color: #0f172a !important;
}
.sf-qmap-tile.flagged {
  border-color: #f59e0b;
}
.sf-qmap-tile.current {
  outline: 3px solid #38bdf8;
  outline-offset: 1px;
}
</style>
        """,
        unsafe_allow_html=True,
    )

    tiles = []
    for i in range(total):
        state = state_for_index(i)
        status = _state_class(state)
        flagged = bool(state.get("flagged"))
        classes = [
            "sf-qmap-tile",
            status,
            "flagged" if flagged else "",
            "current" if i == current_idx else "",
        ]
        mark = _status_mark(status, flagged)
        help_text = escape(str(state.get("help") or f"Go to question {i + 1}"))
        tiles.append(
            (
                f'<a class="{" ".join(c for c in classes if c)}" '
                f'href="?{param_name}={i}" title="{help_text}">'
                f'<span class="sf-qmap-number">{i + 1}</span>'
                f'<span class="sf-qmap-mark">{mark}</span>'
                '</a>'
            )
        )

    st.markdown(
        (
            f'<div class="sf-qmap-grid" '
            f'style="grid-template-columns: repeat({columns}, minmax(0, 1fr));">'
            + "".join(tiles)
            + "</div>"
        ),
        unsafe_allow_html=True,
    )
    return clicked_idx


def render_question_map_legend(*, scored: bool) -> None:
    if scored:
        legend = """
<div class="sf-qmap-legend">
  <div class="sf-qmap-legend-row">
    <span class="sf-qmap-key"><span class="sf-qmap-swatch correct"></span>Correct</span>
    <span class="sf-qmap-key"><span class="sf-qmap-swatch wrong"></span>Wrong</span>
  </div>
  <div class="sf-qmap-legend-row">
    <span class="sf-qmap-key"><span class="sf-qmap-swatch unanswered"></span>Unanswered</span>
    <span class="sf-qmap-key"><span class="sf-qmap-swatch flagged"></span>F = Flagged</span>
  </div>
</div>
        """
    else:
        legend = """
<div class="sf-qmap-legend">
  <div class="sf-qmap-legend-row">
    <span class="sf-qmap-key"><span class="sf-qmap-swatch answered"></span>Answered</span>
    <span class="sf-qmap-key"><span class="sf-qmap-swatch unanswered"></span>Unanswered</span>
  </div>
  <div class="sf-qmap-legend-row">
    <span class="sf-qmap-key"><span class="sf-qmap-swatch flagged"></span>F = Flagged</span>
  </div>
</div>
        """
    st.markdown(legend, unsafe_allow_html=True)
