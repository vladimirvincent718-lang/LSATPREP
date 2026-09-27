"""Regression coverage for the Streamlit dashboard-toggle crash."""

from pathlib import Path


PRACTICE_PAGE = Path(__file__).resolve().parents[1] / "pages" / "5_Practice_Mode.py"


def test_legacy_button_state_is_removed_before_rendering_new_toggle():
    source = PRACTICE_PAGE.read_text(encoding="utf-8")
    cleanup = 'st.session_state.pop("practice_dashboard_toggle", None)'
    new_widget = 'key="practice_dashboard_toggle_button_v2"'
    assert cleanup in source
    assert new_widget in source
    assert source.index(cleanup) < source.index(new_widget)

