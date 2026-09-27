import pytest

from src.practice_allocation_editor import allocation_counts, default_weights


def config():
    return {'total': 7, 'courses': [
        {'id': '2', 'title': 'CCRN', 'weight': 50,
         'modules': [{'id': 'a', 'weight': 75}, {'id': 'b', 'weight': 25}]},
        {'id': '1', 'title': 'CFA', 'weight': 50,
         'modules': [{'id': 'c', 'weight': 100}]},
    ]}


def test_editor_rounds_nested_counts_in_course_selection_order():
    data = config()
    assert allocation_counts(data, default_weights(data)) == {(2, 'a'): 3, (2, 'b'): 1, (1, 'c'): 3}


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -1, 101, True, '50'])
def test_editor_rejects_invalid_browser_values(value):
    data = config()
    weights = default_weights(data)
    weights['courses']['2'] = value
    with pytest.raises(ValueError, match='every allocation field'):
        allocation_counts(data, weights)


def test_editor_validates_module_total_even_when_course_rounds_to_zero_questions():
    data = config()
    data['total'] = 1
    weights = default_weights(data)
    weights['modules']['1']['c'] = 80
    with pytest.raises(ValueError, match='CFA:.*100%'):
        allocation_counts(data, weights)


def test_hundredth_percent_difference_is_not_balanced():
    data = config()
    weights = default_weights(data)
    weights['courses']['2'] = 49.99
    with pytest.raises(ValueError, match='100%'):
        allocation_counts(data, weights)
