"""Optional Acrobat calculation field; the server never trusts this score."""
import json
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject
from src.pdf_export import generate_exam_pdf, _choices


def calculation_script(questions):
    keys = {f'q_{i:03d}_answer': str(q.get('correct_answer', '')).upper()
            for i, q in enumerate(questions, 1)
            if q.get('_offline_scored', True) and str(q.get('correct_answer', '')).upper() in dict(_choices(q))}
    return ('var keys = ' + json.dumps(keys) + '; var correct = 0, total = 0, answered = 0;'
            'for (var name in keys) { if (keys.hasOwnProperty(name)) {'
            'total++; var field = this.getField(name); var value = field ? String(field.value) : "Off";'
            'if (value && value !== "Off") answered++; if (value === keys[name]) correct++; }}'
            'event.value = total ? correct + "/" + total + " (" + Math.round(1000*correct/total)/10 + "%); " + answered + " answered" : "No automatically graded questions";')


def scoring_pdf(record):
    questions = json.loads(record['questions_json'])
    pdf = generate_exam_pdf(questions, record['title'], exam_serial=record['serial'],
        subtitle='Offline scoring copy: contains the answer key. Open in Acrobat with PDF JavaScript enabled. Only keyed multiple-choice questions are scored.',
        include_answer_key=True, live_score=True)
    writer = PdfWriter(clone_from=BytesIO(pdf))
    root = writer.root_object['/AcroForm']
    score = writer.get_fields()['offline_live_score'].indirect_reference
    score.get_object()[NameObject('/AA')] = DictionaryObject({NameObject('/C'): DictionaryObject({
        NameObject('/S'): NameObject('/JavaScript'), NameObject('/JS'): TextStringObject(calculation_script(questions))})})
    root[NameObject('/CO')] = ArrayObject([score])
    writer.add_js('this.calculateNow();')
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
