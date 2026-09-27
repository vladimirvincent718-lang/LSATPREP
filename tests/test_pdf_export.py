from io import BytesIO

from pypdf import PdfReader
from src.pdf_export import display_exam_number, generate_exam_pdf


def test_generate_exam_pdf_handles_passage_body_style():
    pdf_bytes = generate_exam_pdf(
        questions=[
            {
                "section_type": "Chapter 4: Location, Location, Location",
                "question_type": "Open-Ended",
                "difficulty": 1,
                "passage": "Learning objectives and source context.",
                "stimulus": "Explain why utilities should be verified before signing a lease.",
                "correct_answer": "Major utility upgrades can be costly.",
            }
        ],
        title="Restaurant Finance",
        subtitle="Chapter 4",
        include_answer_key=True,
    )

    assert pdf_bytes.startswith(b"%PDF")


def test_mobile_pdf_uses_one_question_per_page_and_large_inline_choices():
    questions = [
        {
            "id": index,
            "section_type": "Mobile Practice",
            "stimulus": f"Question {index}",
            "choice_a": "First option",
            "choice_b": "Second option",
            "choice_c": "Third option",
            "choice_d": "Fourth option",
            "correct_answer": "B",
        }
        for index in range(1, 4)
    ]
    pdf = generate_exam_pdf(
        questions,
        "Phone Practice",
        include_answer_key=False,
        exam_serial="EX-MOBILE",
    )
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 4  # cover plus one page for each question
    assert reader.pages[1].mediabox.width == 396
    for page_number, page in enumerate(reader.pages[1:], start=1):
        assert f"Question {page_number}" in page.extract_text()
        assert f"Question {page_number + 1}" not in page.extract_text()
        widgets = []
        for annotation in page.get("/Annots", []):
            widget = annotation.get_object()
            parent = widget.get("/Parent", widget).get_object()
            if str(parent.get("/T", "")) == f"q_{page_number:03d}_answer":
                widgets.append(widget)
        assert len(widgets) == 4
        assert all(float(widget["/Rect"][2] - widget["/Rect"][0]) >= 24 for widget in widgets)


def test_answer_key_is_compact_and_preserves_written_references():
    questions = [
        {
            "section_type": "Mobile Practice",
            "stimulus": f"Question {index}",
            "choice_a": "First option",
            "choice_b": "Second option",
            "choice_c": "Third option",
            "choice_d": "Fourth option",
            "correct_answer": "B" if index % 2 else "D",
        }
        for index in range(1, 101)
    ]
    questions.append({
        "section_type": "Written Practice",
        "stimulus": "Explain the governing rule.",
        "correct_answer": "The reference explanation remains available in full.",
        "_force_open_ended": True,
    })
    questions[0]["explanation"] = "**Rule:** The second option follows the governing rule."

    pdf = generate_exam_pdf(questions, "Compact Key", include_answer_key=True)
    reader = PdfReader(BytesIO(pdf))

    # Cover + one page per question + a compact three-column answer key.
    assert len(reader.pages) <= len(questions) + 5
    key_text = "\n".join(page.extract_text() or "" for page in reader.pages[len(questions) + 1:])
    assert "Answer Key" in key_text
    assert "Q1" in key_text
    assert "Q100" in key_text
    assert "Rationale" in key_text
    assert "Rule: The second option follows the governing rule." in key_text
    assert "**Rule:**" not in key_text
    assert "Written*" in key_text
    assert "Q101 written response:" in key_text
    assert "The reference explanation remains available in full." in key_text


def test_legacy_exam_number_is_short_on_page_but_full_in_hidden_identity():
    serial = "EX-F059F31E0B8A45D58A71BBC7425226EE"
    pdf = generate_exam_pdf([], "Identity", include_answer_key=False, exam_serial=serial)
    reader = PdfReader(BytesIO(pdf))

    assert display_exam_number(serial) == "EX-F059-F31E"
    assert "EX-F059-F31E" in reader.pages[0].extract_text()
    assert serial not in reader.pages[0].extract_text()
    assert reader.get_fields()["exam_serial"]["/V"] == serial
