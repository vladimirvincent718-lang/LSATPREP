"""Import the user's local NotebookLM slide PDFs, safely and without duplicates.

Run: python scripts/import_cfa_slides.py --source-dir <Downloads>
Missing subjects are reported, never replaced with fabricated slides.
"""
import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import database, material_reviews

SOURCES = {
    'Ethics': '2025_CFA_Ethics Cheat Sheet.pdf',
    'Alternative Investments': 'CFA_Alternative_Investments Cheat Sheet.pdf',
    'Corporate Issuers': 'Corporate_Issuers Cheat Sheet.pdf',
    'Derivatives': 'Derivatives Cheat Sheet.pdf',
    'Economics': 'CFA_L1_Economics_Dashboard.pdf',
    'Equity': 'Equity Cheat Sheet.pdf',
    'Financial Statement Analysis': 'FSA cheat sheet.pdf',
    'Fixed Income': 'Fixed_Income Cheat Sheet.pdf',
    'Portfolio Management': 'Portfolio Management Cheat Sheet.pdf',
    'Quantitative Methods': 'Quantitative methods Cheat Sheet.pdf',
}


def import_slides(source_dir):
    material_reviews.init_reviews()
    with material_reviews.connection() as conn:
        courses = [dict(r) for r in conn.execute('SELECT id,title FROM courses WHERE is_active=1')]
    report = []
    for subject, filename in SOURCES.items():
        source = Path(source_dir) / filename
        matches = [c for c in courses if 'cfa' in c['title'].lower() and subject.lower() in c['title'].lower()]
        if not source.is_file():
            report.append(f'MISSING: {subject}')
            continue
        if len(matches) != 1:
            raise ValueError(f'Expected one active CFA course for {subject}; found {len(matches)}')
        from pypdf import PdfReader
        count = len(PdfReader(source).pages)
        target = ROOT / 'data/material_files' / ('cfa-slides-' + subject.lower().replace(' ', '-') + '.pdf')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError(f'A different document already exists at {target}')
        if not target.exists():
            shutil.copy2(source, target)
        relative = target.relative_to(ROOT).as_posix()
        cid = matches[0]['id']
        existing = next((m for m in database.get_materials(cid) if m['stored_file_path'] == relative), None)
        if existing:
            mid = existing['id']
        else:
            mid, error = database.create_material(cid, f'{subject} - NotebookLM-generated slides',
                'PDF/Document Link', stored_file_path=relative, material_section='Syllabus',
                notes=f'Original NotebookLM slide deck: {filename}. {count} slides.', estimated_minutes=15)
            if error:
                raise ValueError(error)
        material_reviews.register_cheat_sheet(mid, filename)
        report.append(f'ATTACHED: {subject} ({count} slides)')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    args = parser.parse_args()
    print('\n'.join(import_slides(args.source_dir)))
