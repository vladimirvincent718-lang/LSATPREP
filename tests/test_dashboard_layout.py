import json
from src import dashboard_layout as layout


def test_saved_order_hidden_and_new_sections(monkeypatch):
    monkeypatch.setattr(layout, 'get_setting', lambda *args: json.dumps({
        'order': ['Practice calendar', 'Days till exam', 'unknown', 'Days till exam'],
        'hidden': ['Days till exam', 'unknown']}))
    result = layout.load_layout(7, 'Curriculum', {'Accuracy by module'})
    assert result['order'][:2] == ['Practice calendar', 'Days till exam']
    assert result['hidden'] == ['Days till exam']
    assert 'Accuracy by module' in result['order']
    assert 'Days till exam' not in layout.visible_order(result)
    assert len(result['order']) == len(set(result['order']))


def test_layout_is_scoped_to_user_and_view(monkeypatch):
    calls = []
    monkeypatch.setattr(layout, 'get_setting', lambda *args: calls.append(args) or '{}')
    assert 'Curriculum reference materials' not in layout.load_layout(3, 'Course', [])['order']
    assert calls == [(3, 'dashboard_layout_v1_Course')]
    monkeypatch.setattr(layout, 'set_setting', lambda *args: calls.append(args))
    layout.save_layout(3, 'Course', {'order': [], 'hidden': []})
    assert calls[-1][:2] == (3, 'dashboard_layout_v1_Course')


def test_expansion_persists_independently_per_user_and_view(monkeypatch):
    saved = {}
    monkeypatch.setattr(layout, 'get_setting', lambda uid, key: saved.get((uid, key), ''))
    monkeypatch.setattr(layout, 'set_setting', lambda uid, key, value: saved.update({(uid, key): value}))
    layout.save_expanded(1, 'Curriculum', 'course_9', True)
    layout.save_expanded(1, 'Curriculum', 'module_9_Ethics', True)
    assert layout.load_expansion(1, 'Curriculum') == {'course_9': True, 'module_9_Ethics': True}
    assert layout.load_expansion(2, 'Curriculum') == {}
    assert layout.load_expansion(1, 'Course') == {}
    layout.save_expanded(1, 'Curriculum', 'course_9', False)
    assert layout.load_expansion(1, 'Curriculum')['course_9'] is False
