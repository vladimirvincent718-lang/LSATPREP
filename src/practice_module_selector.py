"""Readable native checkbox rows combining module selection and progress."""
import hashlib

import streamlit as st
from src.study_progress import COLORS, METHODS, label


def row_key(key, module):
    return key + "_row_" + hashlib.sha256(module.encode()).hexdigest()[:16]


def render_module_selector(options, titles, values, progress, *, key):
    selected = set(st.session_state.get(key, []))

    def toggle(module):
        current = set(st.session_state.get(key, []))
        if st.session_state[row_key(key, module)]:
            current.add(module)
        else:
            current.discard(module)
        st.session_state[key] = [m for m in options if m in current]

    def select_all(include):
        st.session_state[key] = list(visible_options) if include else []

    st.markdown("#### Modules / Chapters")
    st.caption("Check the modules to include. Progress includes all question lenses; your selected lens only filters exam questions.")
    prefs = progress["prefs"]
    color_labels = {
        "red": f"🔴 Red · Below {prefs['yellow']}%",
        "yellow": f"🟡 Yellow · {prefs['yellow']}–<{prefs['green']}%",
        "green": f"🟢 Green · {prefs['green']}%+",
        "gray": "⚪ Unpracticed",
    }
    active_colors = st.pills("Filter by progress color", list(color_labels),
        format_func=color_labels.get, selection_mode="multi", key=key + "_colors",
        help="Select one or more colors. With no colors selected, all modules are shown.")
    visible_options = [m for m in options if not active_colors or values[m]["color"] in active_colors]
    included = [m for m in visible_options if m in selected]
    st.caption(f"{METHODS[prefs['method']]}, weighted by questions. No color selected = show all. Only checked modules matching the color filter are included in the exam.")
    if progress["window"]:
        start, end = progress["window"]
        st.caption(f"Review window: {start} to {end + ' (exclusive)' if end else 'next scheduled mock'}. ✓ Practiced = a completed practice or section session in this window.")
    left, right, count = st.columns([1, 1, 3])
    left.button("Select all", key=key + "_all", on_click=select_all, args=(True,), use_container_width=True)
    right.button("Clear all", key=key + "_none", on_click=select_all, args=(False,), use_container_width=True)
    count.caption(f"{len(included)} of {len(visible_options)} shown modules selected · {len(options)} total")
    rules = []
    with st.container(height=440, border=True):
        for module in visible_options:
            value = values[module]
            widget_key = row_key(key, module)
            card_key = widget_key + "_card"
            _, name, bg, fg = COLORS[value["color"]]
            rules.append(f".st-key-{card_key} {{background:{bg};border:1px solid {fg};border-radius:8px;padding:10px 12px;}} .st-key-{card_key} p {{color:{fg};white-space:normal;overflow-wrap:anywhere;}}")
            st.session_state[widget_key] = module in selected
            with st.container(key=card_key):
                st.checkbox(label(titles[module], value, progress["window"]), key=widget_key,
                            on_change=toggle, args=(module,))
                st.caption(f"{name} · {value['questions']} scored questions in {value['sessions']} session(s) · Last completed: {value['last'] or 'Never'}")
        if not visible_options:
            st.info("No modules match these colors. Deselect the color filters to show all modules.")
    st.markdown("<style>" + "\n".join(rules) + "</style>", unsafe_allow_html=True)
    if visible_options and not included:
        st.info("Select at least one module to include questions in your exam.")
    return included
