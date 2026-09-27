from __future__ import annotations

from contextlib import nullcontext

import src.question_map as question_map
from streamlit.testing.v1 import AppTest


class _FakeStreamlit:
    def __init__(self, clicked_key: str | None = None):
        self.clicked_key = clicked_key
        self.button_calls: list[dict[str, object]] = []
        self.container_keys: list[str] = []
        self.markdown_calls: list[str] = []

    def markdown(self, body, **_kwargs):
        self.markdown_calls.append(body)
        return None

    def columns(self, count, **_kwargs):
        return [nullcontext() for _ in range(count)]

    def container(self, *, key):
        self.container_keys.append(key)
        return nullcontext()

    def button(self, label, **kwargs):
        self.button_calls.append({"label": label, **kwargs})
        return kwargs["key"] == self.clicked_key


def test_question_map_uses_in_app_buttons_and_returns_clicked_index(monkeypatch):
    fake_st = _FakeStreamlit(clicked_key="map_qmap_button_2")
    monkeypatch.setattr(question_map, "st", fake_st)

    selected = question_map.render_question_map(
        total=4,
        current_idx=1,
        state_for_index=lambda i: {
            "status": ("wrong", "correct", "unanswered", "answered")[i],
            "flagged": i == 3,
        },
        key_prefix="map",
    )

    assert selected == 2
    assert [call["key"] for call in fake_st.button_calls] == [
        "map_qmap_button_0",
        "map_qmap_button_1",
        "map_qmap_button_2",
        "map_qmap_button_3",
    ]
    assert [call["label"] for call in fake_st.button_calls] == [
        "1 ×",
        "2 ✓",
        "3",
        "4 F",
    ]
    assert any("_qmap_current" in key for key in fake_st.container_keys)
    assert any("_qmap_flagged" in key for key in fake_st.container_keys)
    assert ".stButton button" in fake_st.markdown_calls[0]
    assert ".stButton > button" not in fake_st.markdown_calls[0]


def test_question_map_returns_none_without_a_click(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(question_map, "st", fake_st)

    selected = question_map.render_question_map(
        total=2,
        current_idx=0,
        state_for_index=lambda _i: {"status": "unanswered"},
        key_prefix="timed",
    )

    assert selected is None


def test_question_map_click_stays_inside_streamlit_app():
    app = AppTest.from_string(
        """
import streamlit as st
from src.question_map import render_question_map

selected = render_question_map(
    total=4,
    current_idx=0,
    state_for_index=lambda i: {"status": "correct" if i == 0 else "unanswered"},
    key_prefix="probe",
)
if selected is not None:
    st.session_state["selected_question"] = selected
"""
    ).run()

    assert [button.label for button in app.button] == ["1 ✓", "2", "3", "4"]
    app.button[2].click().run()
    assert app.session_state["selected_question"] == 2
