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
    Flowable,
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
    include_answer_key: bool = True,
) -> bytes:
    """Build a workbook-style PDF with fillable answer and issue fields."""
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

        story.append(_QuestionResponseFields(index, choices))
        story.append(Spacer(1, 0.08 * inch))

    if include_answer_key:
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


class _QuestionResponseFields(Flowable):
    """Small AcroForm block for answer selection and issue reporting."""

    def __init__(self, question_number: int, choices: list[tuple[str, str]]):
        super().__init__()
        self.question_number = question_number
        self.choice_letters = [letter for letter, _ in choices]
        self.width = 6.45 * inch
        self.height = 0.88 * inch if self.choice_letters else 1.08 * inch

    def wrap(self, availWidth, availHeight):
        return min(self.width, availWidth), self.height

    def draw(self):
        canvas = self.canv
        form = canvas.acroForm
        q_num = self.question_number
        field_prefix = f"q_{q_num:03d}"
        ink = colors.HexColor("#111827")
        muted = colors.HexColor("#4b5563")
        border = colors.HexColor("#9ca3af")
        fill = colors.HexColor("#ffffff")

        canvas.setStrokeColor(colors.HexColor("#e5e7eb"))
        canvas.roundRect(0, 0, self.width, self.height, 4, stroke=1, fill=0)

        canvas.setFillColor(ink)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(8, self.height - 15, "Your answer:")

        if self.choice_letters:
            radio_name = f"{field_prefix}_answer"
            x = 78
            y = self.height - 19
            for letter in self.choice_letters:
                form.radioRelative(
                    name=radio_name,
                    value=letter,
                    selected=False,
                    x=x,
                    y=y,
                    size=10,
                    buttonStyle="circle",
                    borderColor=border,
                    fillColor=fill,
                    textColor=ink,
                    fieldFlags="radio",
                    tooltip=f"Question {q_num} answer {letter}",
                )
                canvas.setFillColor(ink)
                canvas.setFont("Helvetica", 8.5)
                canvas.drawString(x + 14, y + 1, letter)
                x += 38
        else:
            form.textfieldRelative(
                name=f"{field_prefix}_written_answer",
                x=78,
                y=self.height - 42,
                width=self.width - 92,
                height=22,
                borderColor=border,
                fillColor=fill,
                textColor=ink,
                fieldFlags="multiline",
                tooltip=f"Question {q_num} written answer",
            )

        issue_y = 30
        form.checkboxRelative(
            name=f"{field_prefix}_report_issue",
            x=8,
            y=issue_y,
            size=10,
            buttonStyle="check",
            borderColor=border,
            fillColor=fill,
            textColor=ink,
            tooltip=f"Question {q_num} report issue",
        )
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(24, issue_y + 1, "Report issue")
        canvas.drawString(102, issue_y + 1, "Issue note:")
        form.textfieldRelative(
            name=f"{field_prefix}_issue_note",
            x=154,
            y=issue_y - 4,
            width=self.width - 164,
            height=18,
            borderColor=border,
            fillColor=fill,
            textColor=ink,
            tooltip=f"Question {q_num} issue note",
        )


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
