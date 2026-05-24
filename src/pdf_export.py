"""PDF export helpers for generated practice and exam question sets."""

from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


CHOICE_LETTERS = ("A", "B", "C", "D", "E")


def make_pdf_filename(label: str) -> str:
    """Return a browser-friendly file name for an exported exam PDF."""
    safe_label = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower()
    safe_label = safe_label or "practice_test"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{safe_label}_{stamp}.pdf"


def generate_exam_pdf(
    questions: list[dict],
    title: str,
    subtitle: str = "",
    distribution: list[dict] | None = None,
) -> bytes:
    """Build a workbook-style PDF with a clean one-answer-per-line answer key."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=title,
    )

    styles = _styles()
    story: list = []

    story.append(Paragraph(escape(title), styles["Title"]))
    if subtitle:
        story.append(Paragraph(escape(subtitle), styles["Meta"]))
    story.append(
        Paragraph(
            f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            styles["Meta"],
        )
    )
    story.append(Spacer(1, 0.18 * inch))

    if distribution:
        story.append(Paragraph("Exam Composition", styles["Section"]))
        rows = [["Course", "Questions"]]
        for item in distribution:
            rows.append([
                str(item.get("course") or "Course"),
                str(item.get("q_count") or 0),
            ])
        story.append(_composition_table(rows))
        story.append(Spacer(1, 0.12 * inch))

    current_section = None
    for index, question in enumerate(questions, start=1):
        section = str(question.get("section_type") or "Questions").strip() or "Questions"
        if section != current_section:
            current_section = section
            story.append(Paragraph(escape(section), styles["Section"]))

        meta_bits = [
            bit
            for bit in [
                str(question.get("question_type") or "").strip(),
                _difficulty_label(question.get("difficulty")),
            ]
            if bit
        ]
        meta = f"Q{index}"
        if meta_bits:
            meta += " | " + " | ".join(meta_bits)
        story.append(Paragraph(escape(meta), styles["QuestionMeta"]))

        passage = _clean_text(question.get("passage"))
        if passage:
            story.append(Paragraph("<b>Passage</b>", styles["SmallHeading"]))
            story.append(Paragraph(escape(passage), styles["Body"]))

        stimulus = _clean_text(question.get("stimulus"))
        if stimulus:
            story.append(Paragraph(escape(stimulus), styles["Question"]))

        choices = _choices(question)
        for choice_letter, text in choices:
            story.append(Paragraph(f"<b>{choice_letter}.</b> {escape(text)}", styles["Choice"]))

        story.append(Spacer(1, 0.08 * inch))

    story.append(PageBreak())
    story.append(Paragraph("Answer Key", styles["Section"]))
    story.append(
        Paragraph(
            "Each answer appears on its own line for clean review and printing.",
            styles["Meta"],
        )
    )
    story.append(Spacer(1, 0.08 * inch))
    story.append(_answer_key_table(questions, styles))

    doc.build(story)
    return buffer.getvalue()


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4b5563"),
    ))
    styles.add(ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        spaceBefore=12,
        spaceAfter=7,
        textColor=colors.HexColor("#111827"),
    ))
    styles.add(ParagraphStyle(
        "QuestionMeta",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#374151"),
        spaceBefore=4,
        spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        "SmallHeading",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        spaceBefore=3,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "Question",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        "Choice",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=13,
        leftIndent=12,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "Answer",
        parent=styles["Normal"],
        fontSize=9.3,
        leading=12.5,
    ))
    return styles


def _composition_table(rows: list[list[str]]) -> Table:
    table = Table(rows, colWidths=[4.9 * inch, 1.2 * inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _answer_key_table(questions: list[dict], styles) -> Table:
    rows = [[Paragraph("<b>Question</b>", styles["Answer"]), Paragraph("<b>Answer</b>", styles["Answer"])]]
    for index, question in enumerate(questions, start=1):
        section = str(question.get("section_type") or "").strip()
        label = f"{section} Q{index}" if section else f"Q{index}"
        rows.append([
            Paragraph(escape(label), styles["Answer"]),
            Paragraph(escape(_answer_text(question)), styles["Answer"]),
        ])

    table = Table(rows, colWidths=[1.65 * inch, 4.8 * inch], hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _choices(question: dict) -> list[tuple[str, str]]:
    choices = []
    for letter in CHOICE_LETTERS:
        text = _clean_text(question.get(f"choice_{letter.lower()}"))
        if text:
            choices.append((letter, text))
    return choices


def _answer_text(question: dict) -> str:
    answer = _clean_text(question.get("correct_answer"))
    if not answer:
        return "No answer provided"

    letter = answer.upper()
    if letter in CHOICE_LETTERS:
        choice = _clean_text(question.get(f"choice_{letter.lower()}"))
        return f"{letter}. {choice}" if choice else letter
    return answer


def _clean_text(value) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def _difficulty_label(value) -> str:
    if value in (None, ""):
        return ""
    return f"Difficulty: {value}"
