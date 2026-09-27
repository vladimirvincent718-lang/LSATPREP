"""Browser-local allocation feedback with isolated Streamlit state updates."""

import hashlib
import json
import re
from pathlib import Path

import streamlit as st
import streamlit.components.v2 as components

from src.practice_allocation import allocation_plan, module_label, percentage_counts


_ASSETS = Path(__file__).parent
_JS = (_ASSETS / 'practice_allocation_editor.js').read_text(encoding='utf-8')
_CSS = (_ASSETS / 'practice_allocation_editor.css').read_text(encoding='utf-8')


def editor_config(course_ids, course_titles, questions, total):
    """Stable identities preserve edits on ordinary page reruns."""
    courses = []
    signature = '_'.join(map(str, course_ids))
    for index, cid in enumerate(course_ids):
        modules = sorted(
            {module_label(q) for q in questions if q['course_id'] == cid},
            key=lambda value: [int(part) if part.isdigit() else part.lower()
                               for part in re.split(r'(\d+)', value)],
        )
        courses.append({
            'id': str(cid), 'title': course_titles[cid],
            'weight': st.session_state.get(
                f'practice_course_weight_{signature}_{cid}',
                100 // len(course_ids) + (index == 0) * (100 % len(course_ids)),
            ),
            'modules': [
                {'id': name, 'title': name or 'Unassigned',
                 'weight': st.session_state.get(
                     f'practice_module_weight_{cid}_{repr(modules)}_{name}',
                     100 // len(modules) + (i == 0) * (100 % len(modules)),
                 )}
                for i, name in enumerate(modules)
            ],
        })
    identity = [(c['id'], [m['id'] for m in c['modules']]) for c in courses]
    signature = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
    return {'courses': courses, 'total': total, 'signature': signature}


def default_weights(config):
    return {
        'courses': {c['id']: c['weight'] for c in config['courses']},
        'modules': {c['id']: {m['id']: m['weight'] for m in c['modules']} for c in config['courses']},
    }


def allocation_counts(config, values):
    """Validate browser values independently before starting an exam."""
    def weights(items, values):
        result = {}
        for item in items:
            value = values.get(item['id'])
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 <= value <= 100:
                raise ValueError('Enter a percentage from 0 to 100 in every allocation field.')
            result[item['id']] = value
        return result

    course_weights = weights(config['courses'], values.get('courses', {}))
    targets = percentage_counts(course_weights, config['total'])
    groups = {}
    for course in config['courses']:
        cid = course['id']
        module_weights = weights(course['modules'], values.get('modules', {}).get(cid, {}))
        if course_weights[cid] > 0:
            try:
                counts = percentage_counts(module_weights, targets[cid])
            except ValueError as exc:
                raise ValueError(f"{course['title']}: {exc}") from exc
            groups.update({(int(cid), module): count for module, count in counts.items()})
    return groups


@st.fragment
def render_allocation_editor(config, questions, difficulty_counts):
    """Percentage edits rerun only this small fragment, with no database work."""
    editor = components.component('practice_allocation_editor', js=_JS, css=_CSS)
    key = f"practice_allocation_{config['signature']}"
    current = st.session_state.get(key, {}).get('weights', default_weights(config))
    data = {**config, 'courses': [
        {**c, 'weight': current['courses'].get(c['id'], c['weight']),
         'modules': [{**m, 'weight': current['modules'].get(c['id'], {}).get(m['id'], m['weight'])}
                     for m in c['modules']]}
        for c in config['courses']
    ]}
    result = editor(
        key=key, data=data,
        default={'weights': default_weights(config)},
        on_weights_change=lambda: None,
    )
    try:
        counts = allocation_counts(config, result.weights)
        allocation_plan(questions, counts, difficulty_counts)
    except ValueError as exc:
        # Numeric totals and over/under feedback are painted immediately in JS.
        # Capacity constraints are checked here and again when the exam starts.
        if str(exc).startswith('Only '):
            st.warning(str(exc))
        return {}, str(exc)
    return counts, None
