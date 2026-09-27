"""Exercise the real video card without running the unrelated page sections."""
import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import database


def test_video_completion_checkbox_persists_and_is_private(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'video.db')
    database.init_database()
    conn = database.get_connection()
    conn.execute("INSERT INTO users(id,username,password_hash) VALUES (1,'viewer','x'),(2,'other-viewer','x')")
    conn.execute("INSERT INTO courses(id,title) VALUES (101,'Video course')")
    conn.execute("INSERT INTO course_enrollments(user_id,course_id,enrollment_status) VALUES (1,101,'Active'),(2,101,'Active')")
    conn.commit();conn.close()
    mid, error = database.create_material(101, 'Lesson video', 'Video', external_url='https://example.com/lesson')
    assert not error
    source = (Path(__file__).resolve().parents[1] / 'pages/3_Course_Materials.py').read_text(encoding='utf-8')
    helpers = {'_stored_material_file', '_extract_display_title', '_is_document_content',
               '_material_section', '_module_name', '_render_mat_card'}
    pieces = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in helpers:
            pieces.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
                                                {'TYPE_META', 'PROGRESS_OPTIONS', 'STATUS_ICONS'} for target in node.targets):
            pieces.append(ast.get_source_segment(source, node))
    script = '''import html, re, mimetypes
from pathlib import Path
import streamlit as st
from src.database import get_materials, get_material_progress, set_material_progress, MATERIAL_SECTIONS
''' + '\n\n'.join(pieces) + f'''
mat=get_materials(101)[0]
_render_mat_card(mat,get_material_progress(1,101).get({mid},'Not Started'),1,101,False)
'''
    app = AppTest.from_string(script).run()
    assert not app.exception
    checkbox = app.checkbox[0]
    assert checkbox.label == 'Incomplete'
    checkbox.check().run()
    assert not app.exception
    assert app.checkbox[0].label == 'Complete'
    assert database.get_material_progress(1,101)[mid] == 'Completed'
    assert database.get_material_progress(2,101) == {}
    reopened = AppTest.from_string(script).run()
    assert reopened.checkbox[0].value is True
    reopened.checkbox[0].uncheck().run()
    assert not reopened.exception
    assert reopened.checkbox[0].label == 'Incomplete'
    assert database.get_material_progress(1,101)[mid] == 'Not Started'
