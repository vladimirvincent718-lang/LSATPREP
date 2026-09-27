"""PDF export helpers for generated practice and exam question sets."""

from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
import re

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


CHOICE_LETTERS = ("A", "B", "C", "D", "E")
MOBILE_PAGE_SIZE = (5.5 * inch, 8.5 * inch)


def display_exam_number(serial: str) -> str:
    """Return a short, readable label while preserving the stored identity."""
    serial = str(serial or "").strip().upper()
    token = re.sub(r"[^A-Z0-9]", "", serial[3:] if serial.startswith("EX-") else serial)
    if len(token) >= 8:
        return f"EX-{token[:4]}-{token[4:8]}"
    return serial


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
    exam_serial: str | None = None,
    live_score: bool = False,
) -> bytes:
    """Build a workbook-style PDF with fillable answer and issue fields."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=MOBILE_PAGE_SIZE,
        rightMargin=0.38 * inch,
        leftMargin=0.38 * inch,
        topMargin=0.38 * inch,
        bottomMargin=0.48 * inch,
        title=title,
    )

    styles = _styles()
    visible_exam_number = display_exam_number(exam_serial) if exam_serial else ""
    for name in ("QuestionMeta", "Question", "Choice"):
        styles[name].keepWithNext = True
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
    if exam_serial:
        story.append(Paragraph(f"Exam number: {escape(visible_exam_number)}", styles["Meta"]))
        story.append(Paragraph(
            "Offline use: fill in your answers and save a copy with your changes. "
            "Return to Practice Mode &gt; Offline exams to upload the saved PDF. "
            "Do not print to PDF or flatten the form. Keep this exam number intact.",
            styles["Meta"],
        ))
        story.append(Spacer(1, 0.12 * inch))

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

    if questions:
        story.append(PageBreak())

    for index, question in enumerate(questions, start=1):
        if index > 1:
            story.append(PageBreak())
        question_page = []
        section = str(question.get("section_type") or "Questions").strip() or "Questions"
        question_page.append(Paragraph(escape(section), styles["Section"]))

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
        question_page.append(Paragraph(escape(meta), styles["QuestionMeta"]))

        passage = _clean_text(question.get("passage"))
        if passage:
            question_page.append(Paragraph("<b>Passage</b>", styles["SmallHeading"]))
            question_page.append(Paragraph(escape(passage), styles["Body"]))

        stimulus = _clean_text(question.get("stimulus"))
        if stimulus:
            question_page.append(Paragraph(escape(stimulus), styles["Question"]))

        choices = _choices(question)
        for choice_letter, text in choices:
            question_page.append(_SelectableChoice(index, choice_letter, text, styles["Choice"]))

        question_page.append(_QuestionResponseFields(index, choices))
        question_page.append(Spacer(1, 0.08 * inch))
        story.append(KeepTogether(question_page))

    if include_answer_key:
        story.append(PageBreak())
        story.append(Paragraph("Answer Key", styles["Section"]))
        story.append(
            Paragraph(
                "Each row shows the correct answer and its rationale.",
                styles["Meta"],
            )
        )
        story.append(Spacer(1, 0.08 * inch))
        story.append(_answer_key_table(questions, styles))
        written_references = _written_answer_references(questions, styles)
        if written_references:
            story.append(Spacer(1, 0.1 * inch))
            story.extend(written_references)

    def identity(canvas, document):
        if exam_serial:
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.drawRightString(document.pagesize[0] - document.rightMargin, 16, f"Page {document.page}")
            canvas.drawString(document.leftMargin, 16, visible_exam_number)
            if document.page == 1:
                if live_score:
                    canvas.acroForm.textfield(name="offline_live_score",
                        value="Offline score: requires PDF JavaScript", x=document.leftMargin,
                        y=29, width=300, height=12, fontSize=8, fieldFlags="readOnly", borderWidth=0)
                canvas.acroForm.textfield(name="exam_serial", value=exam_serial,
                    x=document.leftMargin, y=14, width=265, height=11,
                    fontSize=7, fieldFlags="readOnly", annotationFlags="hidden",
                    borderWidth=0, fillColor=colors.white)
            canvas.restoreState()

    doc.build(story, onFirstPage=identity, onLaterPages=identity)
    return buffer.getvalue()


class _SelectableChoice(Flowable):
    """A large, readable answer row with its selection control beside the text."""

    def __init__(self, question_number: int, letter_value: str, text: str, style):
        super().__init__()
        self.question_number = question_number
        self.letter_value = letter_value
        self.paragraph = Paragraph(f"<b>{letter_value}.</b> {escape(text)}", style)
        self.width = 0
        self.height = 0
        self._paragraph_height = 0

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        _, self._paragraph_height = self.paragraph.wrap(max(1, availWidth - 50), availHeight)
        self.height = max(48, self._paragraph_height + 18)
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(colors.HexColor("#f8fafc"))
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        canvas.roundRect(0, 0, self.width, self.height, 7, stroke=1, fill=1)
        size = 24
        y = (self.height - size) / 2
        canvas.acroForm.radioRelative(
            name=f"q_{self.question_number:03d}_answer",
            value=self.letter_value,
            selected=False,
            x=10,
            y=y,
            size=size,
            buttonStyle="check",
            shape="square",
            borderColor=colors.HexColor("#475569"),
            fillColor=colors.white,
            textColor=colors.HexColor("#0f172a"),
            borderWidth=1,
            fieldFlags="radio",
            tooltip=f"Question {self.question_number}: select {self.letter_value}. {self.paragraph.getPlainText()}",
        )
        self.paragraph.drawOn(canvas, 45, (self.height - self._paragraph_height) / 2)


class _QuestionResponseFields(Flowable):
    """Issue reporting plus a large written-response field when needed."""

    def __init__(self, question_number: int, choices: list[tuple[str, str]]):
        super().__init__()
        self.question_number = question_number
        self.choice_letters = [letter for letter, _ in choices]
        self.width = 4.74 * inch
        self.height = 0.74 * inch if self.choice_letters else 1.72 * inch

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
        if not self.choice_letters:
            canvas.drawString(10, self.height - 18, "Your written answer")
            form.textfieldRelative(
                name=f"{field_prefix}_written_answer",
                x=10,
                y=48,
                width=self.width - 20,
                height=self.height - 72,
                borderColor=border,
                fillColor=fill,
                textColor=ink,
                fieldFlags="multiline",
                tooltip=f"Question {q_num} written answer",
            )

        issue_y = 15
        form.checkboxRelative(
            name=f"{field_prefix}_report_issue",
            x=10,
            y=issue_y,
            size=18,
            buttonStyle="check",
            borderColor=border,
            fillColor=fill,
            textColor=ink,
            tooltip=f"Question {q_num} report issue",
        )
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(34, issue_y + 4, "Report issue")
        canvas.drawString(107, issue_y + 4, "Note")
        form.textfieldRelative(
            name=f"{field_prefix}_issue_note",
            x=136,
            y=issue_y - 3,
            width=self.width - 146,
            height=24,
            borderColor=border,
            fillColor=fill,
            textColor=ink,
            tooltip=f"Question {q_num} issue note",
        )


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10.5,
        leading=14,
        spaceAfter=5,
    ))
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
        fontSize=12,
        leading=15,
        spaceBefore=0,
        spaceAfter=5,
        textColor=colors.HexColor("#111827"),
    ))
    styles.add(ParagraphStyle(
        "QuestionMeta",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
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
        fontSize=11,
        leading=15,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "Choice",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        leftIndent=0,
        rightIndent=0,
        spaceAfter=0,
    ))
    styles.add(ParagraphStyle(
        "Answer",
        parent=styles["Normal"],
        fontSize=9.3,
        leading=12.5,
    ))
    styles.add(ParagraphStyle(
        "KeyCell",
        parent=styles["Normal"],
        fontSize=7.2,
        leading=8.6,
    ))
    return styles


def _composition_table(rows: list[list[str]]) -> Table:
    table = Table(rows, colWidths=[3.75 * inch, 0.8 * inch], hAlign="LEFT")
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
    key_style = styles["KeyCell"]
    rows = [[
        Paragraph("<b>Question</b>", key_style),
        Paragraph("<b>Answer</b>", key_style),
        Paragraph("<b>Rationale</b>", key_style),
    ]]
    for index, question in enumerate(questions, start=1):
        rationale = _rationale_text(question) or "No rationale provided."
        rows.append([
            Paragraph(f"<b>Q{index}</b>", key_style),
            Paragraph(escape(_compact_answer_value(question)), key_style),
            Paragraph(escape(rationale), key_style),
        ])

    table = Table(
        rows,
        colWidths=[0.52 * inch, 0.62 * inch, 3.60 * inch],
        hAlign="LEFT",
        repeatRows=1,
        splitByRow=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _compact_answer_value(question: dict) -> str:
    answer = _clean_text(question.get("correct_answer"))
    if not answer:
        return "-"
    if answer.upper() in CHOICE_LETTERS and _choices(question):
        return answer.upper()
    return "Written*"


def _rationale_text(question: dict) -> str:
    rationale = _clean_text(question.get("explanation"))
    return rationale.replace("*", "").replace("__", "")


def _written_answer_references(questions: list[dict], styles) -> list:
    references = []
    for index, question in enumerate(questions, start=1):
        if _compact_answer_value(question) != "Written*":
            continue
        references.append(Paragraph(
            f"<b>Q{index} written response:</b> {escape(_answer_text(question))}",
            styles["Answer"],
        ))
    if not references:
        return []
    return [Paragraph("Written response references", styles["SmallHeading"]), *references]


def _choices(question: dict) -> list[tuple[str, str]]:
    if question.get("_force_open_ended"):
        return []
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
