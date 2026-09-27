from __future__ import annotations

from collections.abc import Callable

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
        return "✓"
    if status == "wrong":
        return "×"
    return ""


def render_question_map(
    *,
    total: int,
    current_idx: int,
    state_for_index: Callable[[int], QuestionState],
    key_prefix: str,
    columns: int = 4,
) -> int | None:
    """Render a legible, numbered question map and return the clicked index."""

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
div[class*="_qmap_state_"] {
  margin-bottom: 0.3rem;
}
div[class*="_qmap_state_"] .stButton button {
  border: 2px solid transparent;
  border-radius: 0.5rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.18);
  font-weight: 800;
  height: 2.4rem;
  line-height: 1;
  min-height: 2.4rem;
  padding: 0.25rem;
}
div[class*="_qmap_state_"] .stButton button:hover {
  filter: brightness(1.06);
  transform: translateY(-1px);
}
div[class*="_qmap_state_"] .stButton button p {
  font-size: 0.95rem;
  font-weight: 800;
}
div[class*="_qmap_state_correct"] .stButton button,
div[class*="_qmap_state_answered"] .stButton button {
  background: #16a34a;
  border-color: #16a34a;
  color: #ffffff !important;
}
div[class*="_qmap_state_correct"] .stButton button p,
div[class*="_qmap_state_answered"] .stButton button p,
div[class*="_qmap_state_wrong"] .stButton button p {
  color: #ffffff !important;
}
div[class*="_qmap_state_wrong"] .stButton button {
  background: #dc2626;
  border-color: #dc2626;
  color: #ffffff !important;
}
div[class*="_qmap_state_unanswered"] .stButton button,
div[class*="_qmap_state_skipped"] .stButton button {
  background: #f8fafc;
  border-color: #f8fafc;
  color: #0f172a !important;
}
div[class*="_qmap_flagged"] .stButton button {
  border-color: #f59e0b;
}
div[class*="_qmap_current"] .stButton button {
  outline: 3px solid #38bdf8;
  outline-offset: 1px;
}
</style>
        """,
        unsafe_allow_html=True,
    )

    clicked_idx = None
    for row_start in range(0, total, columns):
        row_columns = st.columns(columns, gap="small")
        for column_offset, i in enumerate(range(row_start, min(row_start + columns, total))):
            state = state_for_index(i)
            status = _state_class(state)
            flagged = bool(state.get("flagged"))
            mark = _status_mark(status, flagged)
            # A native Streamlit button keeps the click in the current app view.
            # The state words in the container key also provide stable CSS hooks.
            state_key = f"{key_prefix}_qmap_state_{status}"
            if flagged:
                state_key += "_qmap_flagged"
            if i == current_idx:
                state_key += "_qmap_current"
            state_key += f"_{i}"
            label = f"{i + 1} {mark}" if mark else str(i + 1)
            with row_columns[column_offset]:
                with st.container(key=state_key):
                    if st.button(
                        label,
                        key=f"{key_prefix}_qmap_button_{i}",
                        help=str(state.get("help") or f"Go to question {i + 1}"),
                        use_container_width=True,
                    ):
                        clicked_idx = i

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
