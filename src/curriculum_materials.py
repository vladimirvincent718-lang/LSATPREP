"""Shared references that belong to a curriculum rather than an individual course."""
from src.material_reviews import connection


def init_curriculum_materials():
    with connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS curriculum_materials (
            id INTEGER PRIMARY KEY, curriculum_id INTEGER NOT NULL,
            title TEXT NOT NULL, stored_file_path TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
            UNIQUE(curriculum_id, stored_file_path))''')


def move_shared_document(curriculum_id, stored_file_path):
    """Keep old records and personal progress, but show one curriculum reference."""
    init_curriculum_materials()
    with connection() as conn:
        rows = conn.execute('''SELECT m.* FROM course_materials m
            JOIN curriculum_courses cc ON cc.course_id=m.course_id
            WHERE cc.curriculum_id=? AND m.stored_file_path=? ORDER BY m.id''',
            (curriculum_id, stored_file_path)).fetchall()
        if not rows:
            raise ValueError('No matching document was found in this curriculum.')
        first = rows[0]
        conn.execute('''INSERT OR IGNORE INTO curriculum_materials
            (curriculum_id,title,stored_file_path,notes) VALUES (?,?,?,?)''',
            (curriculum_id, first['title'], stored_file_path, first['notes'] or ''))
        conn.executemany('UPDATE course_materials SET is_active=0 WHERE id=?',
                         [(r['id'],) for r in rows])
    return len(rows)


def get_curriculum_materials(user_id, curriculum_id):
    init_curriculum_materials()
    with connection() as conn:
        return [dict(r) for r in conn.execute('''SELECT m.* FROM curriculum_materials m
            WHERE m.curriculum_id=? AND EXISTS (
                SELECT 1 FROM curriculum_courses cc
                JOIN course_enrollments e ON e.course_id=cc.course_id
                JOIN courses c ON c.id=cc.course_id
                WHERE cc.curriculum_id=m.curriculum_id AND e.user_id=?
                AND e.enrollment_status='Active' AND c.is_active=1)
            ORDER BY m.title''', (curriculum_id, user_id))]


def has_curriculum_source(course_id, filename):
    """Preserve flashcard seeding when its source moves out of course materials."""
    from pathlib import Path
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='curriculum_materials'").fetchone():
            return False
        return any(Path(r['stored_file_path']).name == filename for r in conn.execute('''
            SELECT m.stored_file_path FROM curriculum_materials m
            JOIN curriculum_courses cc ON cc.curriculum_id=m.curriculum_id
            WHERE cc.course_id=?''', (course_id,)))


def render_curriculum_materials(user_id, curriculum_id, *, dashboard_mode=None):
    import streamlit as st
    from src.material_review_ui import material_file
    rows = get_curriculum_materials(user_id, curriculum_id)
    if not rows:
        return
    from src.dashboard_layout import tracked_expander
    panel = (tracked_expander('📖 Curriculum reference materials', user_id, dashboard_mode, 'references', default=True)
             if dashboard_mode else st.expander('📖 Curriculum reference materials', expanded=True))
    with panel:
        st.caption('References covering the whole curriculum.')
        for row in rows:
            st.markdown(f"**{row['title']}** · Word document")
            path = material_file(row)
            if path:
                text_panel = (tracked_expander('Read reference text', user_id, dashboard_mode, f'reference_{row["id"]}')
                              if dashboard_mode else st.expander('Read reference text'))
                with text_panel:
                    from src.flashcards import extract_text
                    try:
                        st.text(extract_text(path.name, path.read_bytes()))
                    except ValueError:
                        st.info('Text preview is unavailable for this document.')
                st.download_button('Save Word document', path.read_bytes(), file_name=path.name,
                    key=f"curriculum_material_{row['id']}")
            else:
                st.warning('The reference document could not be found.')
