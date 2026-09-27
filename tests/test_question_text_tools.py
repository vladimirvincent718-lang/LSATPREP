from src.utils import _question_text_card_html


def test_question_card_has_text_screenshot_and_play_controls():
    html = _question_text_card_html("What is the implied return?", "question-card-1")

    assert ">Copy Text</button>" in html
    assert ">Copy Screenshot</button>" in html
    assert "data-sf-copy-screenshot=\"question-card-1\"" in html
    assert "Play</button>" in html


def test_question_card_cleans_notebooklm_text_and_keeps_tools_in_header():
    html = _question_text_card_html(
        r"**Question:** A \$2,000,000 write-down < inventory", "card", compact_tools=True
    )
    assert "Question: A $2,000,000 write-down &lt; inventory" in html
    assert "<details" not in html
    assert "Text tools" not in html
    assert html.index("Copy Screenshot") < html.index("<textarea")
