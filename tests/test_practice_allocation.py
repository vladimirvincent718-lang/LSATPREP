from pathlib import Path

import pytest

from src.practice_allocation import allocation_plan, percentage_counts


def test_rounding_preserves_total_and_zero_weights():
    assert percentage_counts({'a': 50, 'b': 50, 'c': 0}, 7) == {'a': 4, 'b': 3, 'c': 0}
    with pytest.raises(ValueError, match='100%'):
        percentage_counts({'a': 70}, 10)


def test_joint_allocation_reassigns_flexible_group_for_scarce_difficulty():
    questions = [dict(course_id=c, section_type='chapter', difficulty=d)
                 for c, d in [(1, 1), (1, 5), (2, 1)]]
    plan = allocation_plan(questions, {(1, 'chapter'): 1, (2, 'chapter'): 1}, {1: 1, 5: 1})
    assert plan[(1, 'chapter'), 5] == 1
    assert plan[(2, 'chapter'), 1] == 1
    with pytest.raises(ValueError, match='Only'):
        allocation_plan(questions, {(1, 'chapter'): 1, (2, 'chapter'): 1}, {5: 2})


def test_practice_setup_curriculum_difficulty_and_allocation(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from src import auth, database, utils

    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'practice.db')
    database.init_database()
    database.init_curriculum_tables()
    conn = database.get_connection()
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('student','x')").lastrowid
    ids = []
    for title, difficulty in [('CFA Test', 1), ('CCRN Test', 5)]:
        cid = conn.execute('INSERT INTO courses(title) VALUES (?)', (title,)).lastrowid
        ids.append(cid)
        conn.execute('INSERT INTO course_enrollments(user_id,course_id) VALUES (?,?)', (uid,cid))
        for i in range(4):
            conn.execute("INSERT INTO questions(course_id,question_id,section_type,difficulty,stimulus,choice_a,choice_b,correct_answer) VALUES (?,?,?,?,?,?,?,?)",
                         (cid,f'{cid}-{i}','Chapter One',difficulty,f'Question {i}','Yes','No','A'))
    curriculum = conn.execute("INSERT INTO curriculums(title) VALUES ('Combined')").lastrowid
    for cid in ids:
        conn.execute('INSERT INTO curriculum_courses(curriculum_id,course_id) VALUES (?,?)', (curriculum,cid))
    area = conn.execute("INSERT INTO course_areas(course_id,name) VALUES (?,'Clinical')", (ids[1],)).lastrowid
    module = conn.execute("INSERT INTO course_module_blueprints(course_id,area_id,name) VALUES (?,?,'Cardiac')", (ids[1],area)).lastrowid
    chapter = conn.execute("INSERT INTO course_chapters(course_id,module_id,name) VALUES (?,?,'Cardiac Assessment')", (ids[1],module)).lastrowid
    conn.execute('UPDATE questions SET chapter_id=? WHERE course_id=?', (chapter,ids[1]))
    conn.commit()
    conn.close()
    monkeypatch.setattr(auth, 'require_login', lambda: uid)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *a: None)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'pages/5_Practice_Mode.py'), default_timeout=30).run()
    assert not app.exception
    app.multiselect(key='practice_course_ids').set_value([ids[1]]).run()
    assert not app.exception
    assert [x.key for x in app.number_input if str(x.key).startswith('practice_difficulty_count_')] == ['practice_difficulty_count_5']
    assert app.multiselect(key='practice_module_filters').options == ['Chapter One / Cardiac Assessment']
    assert [x.label for x in app.selectbox if x.label.startswith('Level ')] == ['Level 5']
    assert not any('take-home exam PDF' in x.label or 'Enable per-question timer' in x.label for x in app.checkbox)
    app.number_input(key='practice_difficulty_count_5').set_value(2).run()
    next(x for x in app.radio if x.label == 'Choose exam content by').set_value('Curriculum').run()
    assert app.multiselect(key='practice_course_ids').value == ids
    app.number_input(key='practice_difficulty_count_1').set_value(2).run()
    next(x for x in app.toggle if x.label.startswith('Allocate questions')).set_value(True).run()
    assert not app.exception
    assert not app.warning
    next(x for x in app.button if x.label == 'Start Practice Exam').click().run()
    assert not app.exception
    questions = app.session_state['exam_questions']
    assert len(questions) == 4
    assert sum(q['course_id'] == ids[0] for q in questions) == 2
    assert sum(q['difficulty'] == 5 for q in questions) == 2


def test_practice_uses_shared_lenses_and_starts_only_matching_questions(monkeypatch, tmp_path):
    import json
    from streamlit.testing.v1 import AppTest
    from src import auth, database, utils
    from src.question_lenses import get_lenses, save_lens, question_lens
    from src.professional_specialty import normalize_specialty, specialty_label
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'shared_practice.db')
    database.init_database()
    database.init_curriculum_tables()
    conn = database.get_connection()
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('lens_student','x')").lastrowid
    cid = conn.execute("INSERT INTO courses(title) VALUES ('CFA Lens Test')").lastrowid
    conn.execute('INSERT INTO course_enrollments(user_id,course_id) VALUES (?,?)', (uid,cid))
    for i, lens in enumerate(['standard', 'hip_hop', 'hip_hop']):
        conn.execute('INSERT INTO questions(course_id,question_id,section_type,difficulty,stimulus,choice_a,choice_b,correct_answer,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)',
                     (cid,f'L-{i}','Chapter One',1,f'Question {i}','Yes','No','A',json.dumps({'lens':lens})))
    conn.commit()
    conn.close()
    custom = save_lens('Music Business')
    monkeypatch.setattr(auth, 'require_login', lambda: uid)
    monkeypatch.setattr(utils, 'sidebar_nav', lambda *args: None)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'pages/5_Practice_Mode.py'), default_timeout=30).run()
    assert not app.exception
    assert not [s for s in app.selectbox if s.label == 'Professional Specialty']
    assert app.selectbox(key='practice_question_lens').options == ['All lenses', *get_lenses().values()]
    save_lens('Music Industry', custom)
    app.run()
    assert 'Music Industry' in app.selectbox(key='practice_question_lens').options
    assert normalize_specialty(custom) == custom
    assert specialty_label(custom) == 'Music Industry'
    app.multiselect(key='practice_course_ids').set_value([cid]).run()
    app.selectbox(key='practice_question_lens').set_value('hip_hop').run()
    assert not app.exception
    app.number_input(key='practice_difficulty_count_1').set_value(1).run()
    next(b for b in app.button if b.label == 'Start Practice Exam').click().run()
    assert not app.exception
    assert len(app.session_state['exam_questions']) == 1
    assert question_lens(app.session_state['exam_questions'][0]) == 'hip_hop'
    assert app.session_state['practice_professional_specialty'] == 'hip_hop'
    assert any('Hip Hop' in item.value for item in app.info)
