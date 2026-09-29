"""Validated comment files and private image/PDF previews."""
import base64
import binascii
import io
import re
import sqlite3
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image
from streamlit import runtime

MAX_FILES = 5
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
IMAGE_TYPES = {'.png': ('PNG', 'image/png'), '.jpg': ('JPEG', 'image/jpeg'),
               '.jpeg': ('JPEG', 'image/jpeg'), '.gif': ('GIF', 'image/gif'),
               '.webp': ('WEBP', 'image/webp')}


def validate_attachments(files):
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ValueError('Attach up to five files per comment.')
    result = []
    total = 0
    for file in files:
        if not isinstance(file, dict) or not isinstance(file.get('data'), str):
            raise ValueError('Choose a valid attachment.')
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(file.get('name', '')).replace('\\', '/').split('/')[-1]).strip(' .')[:180]
        suffix = Path(name).suffix.lower()
        encoded = file['data']
        if len(encoded) > (MAX_FILE_BYTES + 2) // 3 * 4:
            raise ValueError('Each attachment must be 10 MB or smaller.')
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('This attachment could not be read. Choose the file again.') from None
        if not content or len(content) > MAX_FILE_BYTES:
            raise ValueError('Each attachment must contain data and be 10 MB or smaller.')
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError('Attachments must total 25 MB or less per comment.')
        pages = 0
        try:
            if suffix in IMAGE_TYPES:
                expected, mime = IMAGE_TYPES[suffix]
                with Image.open(io.BytesIO(content)) as image:
                    if image.format != expected or image.width * image.height > 20_000_000:
                        raise ValueError('Use a valid picture with no more than 20 million pixels.')
                    image.verify()
            elif suffix == '.pdf':
                import fitz
                with fitz.open(stream=content, filetype='pdf') as document:
                    pages = len(document)
                    if document.needs_pass or not 1 <= pages <= 100:
                        raise ValueError('Use an unlocked PDF with 1–100 slides or pages.')
                mime = 'application/pdf'
            elif suffix == '.pptx':
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    names = set(archive.namelist())
                    if not {'[Content_Types].xml', 'ppt/presentation.xml'} <= names:
                        raise ValueError('Choose a valid PowerPoint presentation.')
                    if any(item.flag_bits & 1 for item in archive.infolist()) or sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                        raise ValueError('This PowerPoint file is too large or encrypted.')
                    pages = sum(bool(re.fullmatch(r'ppt/slides/slide\d+\.xml', name)) for name in names)
                    if not 1 <= pages <= 100:
                        raise ValueError('Use a PowerPoint presentation with 1–100 slides.')
                mime = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
            else:
                raise ValueError('Choose a PNG, JPG, GIF, WEBP, PDF, or PowerPoint (.pptx) file.')
        except ValueError:
            raise
        except Exception:
            raise ValueError(f'{name or "Attachment"} is damaged or is not a supported file.') from None
        result.append(dict(name=name, mime=mime, content=content, pages=pages))
    return result


@st.cache_data(show_spinner=False, max_entries=64)
def _content(db_path, attachment_id):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute('SELECT content FROM audio_comment_attachments WHERE id=?', (attachment_id,)).fetchone()
    if not row:
        raise ValueError('This attachment is no longer available.')
    return bytes(row[0])


@st.cache_data(show_spinner=False, max_entries=128)
def _pdf_preview(db_path, attachment_id, page):
    import fitz
    with fitz.open(stream=_content(db_path, attachment_id), filetype='pdf') as document:
        slide = document[page]
        scale = min(1.5, 1400 / max(slide.rect.width, slide.rect.height, 1))
        return slide.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')


def media_for_marks(user_id, course_id, audio_id, marks, pages):
    """Only ids belonging to currently authorized, nondeleted comments are served."""
    from src import audio_study as store, database
    with store.connection() as conn:
        store._accessible(conn, user_id, course_id, audio_id)
        allowed = {row['id'] for row in conn.execute('SELECT f.id FROM audio_comment_attachments f JOIN audio_marks m ON m.id=f.mark_id WHERE m.audio_id=? AND m.is_deleted=0', (audio_id,))}
    manager = runtime.get_instance().media_file_mgr
    db_path = str(database.DB_PATH.resolve())
    for mark in marks:
        mark['attachments'] = [item for item in mark.get('attachments', []) if item['id'] in allowed]
        for item in mark.get('attachments', []):
            content = _content(db_path, item['id'])
            item['url'] = manager.add(content, item['mime'], f"comment_attachment_{item['id']}",
                                      file_name=item['name'], is_for_static_download=True)
            if item['mime'].startswith('image/'):
                item['preview_url'] = manager.add(content, item['mime'], f"comment_image_{item['id']}")
            elif item['mime'] == 'application/pdf':
                page = max(0, min(item['pages'] - 1, pages.get(item['id'], 0)))
                item['preview_page'] = page
                try:
                    item['preview_url'] = manager.add(_pdf_preview(db_path, item['id'], page), 'image/png', f"comment_slide_{item['id']}_{page}")
                except Exception:
                    item['preview_error'] = 'Preview unavailable. Open or download the PDF to view it.'
    return marks
