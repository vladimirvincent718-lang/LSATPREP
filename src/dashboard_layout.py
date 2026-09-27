"""Persistent ordering and visibility for dashboard widgets."""
import json
import hashlib
from src.database import get_setting, set_setting

BASE = ['Days till exam', 'Next mock exam', 'Current mock review', 'Practice summary', 'Practice calendar',
        'Dashboard summary', 'Course dashboard cards', 'Course & module progress',
        'Curriculum reference materials']
LABELS = {'Course dashboard cards': 'Course performance'}


def load_expansion(user_id, mode):
    try:
        value = json.loads(get_setting(user_id, 'dashboard_expansion_v1_' + mode) or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def save_expanded(user_id, mode, name, expanded):
    state = load_expansion(user_id, mode)
    state[name] = bool(expanded)
    set_setting(user_id, 'dashboard_expansion_v1_' + mode, json.dumps(state))


def tracked_expander(label, user_id, mode, name, *, default=False):
    import streamlit as st
    key = f'dashboard_expansion_{mode}_{name}'
    if key not in st.session_state:
        st.session_state[key] = bool(load_expansion(user_id, mode).get(name, default))
    def changed():
        save_expanded(user_id, mode, name, st.session_state[key])
    return st.expander(label, expanded=default, key=key, on_change=changed)


def load_layout(user_id, mode, sections):
    available = list(dict.fromkeys(BASE + sorted(set(sections) - {'Materials progress'})))
    if mode == 'Course':
        available.remove('Curriculum reference materials')
    if 'Performance overview' in sections and 'Score trend analysis' in available:
        available.remove('Score trend analysis')
    try:
        saved = json.loads(get_setting(user_id, 'dashboard_layout_v1_' + mode) or '{}')
    except (ValueError, TypeError):
        saved = {}
    order = list(dict.fromkeys([k for k in saved.get('order', []) if k in available] + available))
    hidden = [k for k in saved.get('hidden', []) if k in available]
    return {'order': order, 'hidden': hidden}


def save_layout(user_id, mode, layout):
    set_setting(user_id, 'dashboard_layout_v1_' + mode, json.dumps(layout))


def visible_order(layout):
    return [k for k in layout['order'] if k not in layout['hidden']]


def set_widget_hidden(user_id, mode, sections, key, hidden):
    layout = load_layout(user_id, mode, sections)
    layout['hidden'] = [k for k in layout['hidden'] if k != key]
    if hidden:
        layout['hidden'].append(key)
    save_layout(user_id, mode, layout)


def render_layout_editor(user_id, mode, sections):
    import streamlit as st
    from streamlit_sortables import sort_items
    layout = load_layout(user_id, mode, sections)
    with st.popover('Arrange & restore', use_container_width=True):
        st.caption('Drag section names into the order you want. Use × on a dashboard section to hide it. Changes are saved automatically for this view and used in reports.')
        shown = visible_order(layout)
        labels = {LABELS.get(k, k): k for k in shown}
        revision = hashlib.sha256(json.dumps(shown).encode()).hexdigest()[:12]
        reordered = sort_items(list(labels), direction='vertical', key='dashboard_order_' + mode + revision)
        if reordered and set(reordered) == set(labels) and reordered != list(labels):
            layout['order'] = [labels[k] for k in reordered] + layout['hidden']
            save_layout(user_id, mode, layout)
            st.rerun()
        if layout['hidden']:
            restore = st.selectbox('Hidden sections', layout['hidden'], format_func=lambda k: LABELS.get(k, k), key='dashboard_restore_' + mode)
            st.button('Restore section', key='dashboard_restore_button_' + mode,
                      on_click=set_widget_hidden, args=(user_id, mode, sections, restore, False))
        else:
            st.caption('All available sections are visible.')
        if st.button('Reset layout', key='dashboard_reset_' + mode):
            save_layout(user_id, mode, {'order': [], 'hidden': []})
            st.rerun()


def create_slots(user_id, mode, sections):
    import streamlit as st
    layout = load_layout(user_id, mode, sections)
    slots = {}
    for key in visible_order(layout):
        slot = st.container(border=True, key='dashboard_widget_' + mode + '_' + key.replace(' ', '_'))
        with slot:
            title, close = st.columns([30, 1])
            title.caption(LABELS.get(key, key))
            close.button('×', key='dashboard_hide_' + mode + '_' + key, help='Hide ' + LABELS.get(key, key),
                         on_click=set_widget_hidden, args=(user_id, mode, sections, key, True))
        slots[key] = slot
    return slots
