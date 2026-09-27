from src.utils import format_module_label, module_sort_key


def test_single_digit_module_numbers_are_zero_padded_for_display():
    assert (
        format_module_label("Learning Module 1: Introduction")
        == "Learning Module 01: Introduction"
    )
    assert format_module_label("Module #9 Review") == "Module #09 Review"


def test_existing_multi_digit_module_numbers_are_unchanged():
    assert format_module_label("Learning Module 10: Reporting Quality") == (
        "Learning Module 10: Reporting Quality"
    )


def test_module_sort_key_orders_numbers_naturally():
    labels = ["Learning Module 10", "Learning Module 2", "Learning Module 1"]
    assert sorted(labels, key=module_sort_key) == [
        "Learning Module 1",
        "Learning Module 2",
        "Learning Module 10",
    ]
