from src import database
from src.study_progress import preferences, summarize, load_progress, status


def rows(attempt, day, correct, total):
    return [{"attempt_id": attempt, "completed_at": day, "is_correct": int(i < correct)} for i in range(total)]


def test_recent_weighted_latest_all_and_incomplete():
    history = rows(1, "2026-09-01", 0, 100) + rows(2, "2026-09-02", 6, 10) + rows(3, "2026-09-03", 7, 10) + rows(4, "2026-09-04", 1, 1)
    history += [{"attempt_id": 5, "completed_at": None, "is_correct": 0}]
    recent = summarize(history, preferences({}))
    assert recent["score"] == 100 * 14 / 21
    assert recent["color"] == "yellow"
    assert summarize(history, preferences({"progress_method": "latest"}))["score"] == 100
    assert summarize(history, preferences({"progress_method": "all"}))["color"] == "red"


def test_window_is_independent_and_end_exclusive():
    prefs = preferences({})
    history = rows(1, "2026-09-04 09:00:00", 0, 10)
    assert summarize(history, prefs, ("2026-09-04", "2026-09-16"))["practiced"]
    assert not summarize(history, prefs, ("2026-09-01", "2026-09-04"))["practiced"]
    assert summarize(history, prefs, ("2026-09-04", None))["color"] == "red"
    assert summarize([], prefs)["color"] == "gray"
    assert summarize(rows(1, "2026-09-04", 6, 10), prefs)["color"] == "yellow"
    assert summarize(rows(1, "2026-09-04", 8, 10), prefs)["color"] == "green"


def test_user_course_question_isolation_and_old_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "progress.db")
    database.init_database()
    conn = database.get_connection()
    users = [conn.execute("INSERT INTO users(username,password_hash) VALUES (?, 'x')", (name,)).lastrowid for name in ["one", "two"]]
    courses = [conn.execute("INSERT INTO courses(title) VALUES (?)", (name,)).lastrowid for name in ["one", "two"]]
    questions = [conn.execute("INSERT INTO questions(course_id,question_id,section_type,stimulus,correct_answer) VALUES (?,?,'Same title','Question','A')", (cid,str(cid))).lastrowid for cid in courses]
    for uid, cid, qid, correct in [(users[0], courses[0], questions[0], 1), (users[0], courses[1], questions[1], 0), (users[1], courses[0], questions[0], 0)]:
        aid = conn.execute("INSERT INTO exam_attempts(user_id,course_id,completed_at) VALUES (?,?,'2026-09-04')",(uid,cid)).lastrowid
        conn.execute("INSERT INTO user_answers(attempt_id,question_id,is_correct) VALUES (?,?,?)",(aid,qid,correct))
    conn.commit()
    conn.close()
    progress = load_progress(users[0])
    assert status(progress,[courses[0]],"Same title")["score"] == 100
    assert status(progress,[courses[1]],"Same title")["score"] == 0
    filtered = load_progress(users[0], question_ids={questions[1]})
    assert status(filtered,[courses[0]])["score"] is None
    assert status(filtered,[courses[1]])["score"] == 0


def test_starting_mock_does_not_mark_review_done():
    history = rows(1, "2026-09-04", 8, 10)
    for row in history:
        row["mode"] = "mock_exam"
    result = summarize(history, preferences({}), ("2026-09-04", "2026-09-16"))
    assert result["color"] == "green"
    assert not result["practiced"]
    history += rows(2, "2026-09-05", 0, 1)
    assert summarize(history, preferences({}), ("2026-09-04", "2026-09-16"))["practiced"]


def test_settings_save_validation_and_persistence(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from src import auth, utils
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "settings.db")
    database.init_database()
    conn = database.get_connection()
    uid = conn.execute("INSERT INTO users(username,password_hash) VALUES ('student','x')").lastrowid
    conn.commit()
    conn.close()
    monkeypatch.setattr(auth, "require_login", lambda: uid)
    monkeypatch.setattr(utils, "sidebar_nav", lambda *args: None)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/10_Settings.py"), default_timeout=30).run()
    assert not app.exception
    next(s for s in app.selectbox if s.label == "Score used for colors").set_value("latest")
    next(n for n in app.number_input if n.label == "Yellow starts at (%)").set_value(65)
    next(n for n in app.number_input if n.label == "Green starts at (%)").set_value(85)
    next(b for b in app.button if b.label == "Save Progress Colors").click().run()
    assert not app.exception
    assert preferences(database.get_all_settings(uid)) == {"method": "latest", "yellow": 65, "green": 85}
    next(n for n in app.number_input if n.label == "Yellow starts at (%)").set_value(90)
    next(b for b in app.button if b.label == "Save Progress Colors").click().run()
    assert any("Green must start above yellow" in e.value for e in app.error)
    assert database.get_setting(uid, "progress_yellow") == "65"


def test_placeholder_chapters_match_history_without_merging_real_chapters():
    from src.study_progress import progress_module_key
    assert progress_module_key("Learning Module 03: Market Efficiency / General") == progress_module_key("Learning Module 3: Market Efficiency")
    assert progress_module_key("Cardiac / Assessment") != progress_module_key("Cardiac / Heart Failure")
    progress = {"prefs": preferences({}), "window": ("2026-09-04", "2026-09-16"),
                "modules": {(12, progress_module_key("Learning Module 3: Market Efficiency")): rows(1,"2026-09-05",7,10)}}
    assert status(progress,[12],"Learning Module 3: Market Efficiency / General")["practiced"]
    assert status(progress,[12],"Learning Module 3: Market Efficiency / General")["score"] == 70
    assert not status(progress,[14],"Learning Module 3: Market Efficiency / General")["practiced"]


def test_vertical_selector_select_clear_and_toggle():
    from streamlit.testing.v1 import AppTest
    from src.practice_module_selector import row_key
    app = AppTest.from_string("""
import streamlit as st
from src.practice_module_selector import render_module_selector
from src.study_progress import preferences, summarize
options = ['Module A', 'Module B']
if 'modules' not in st.session_state:
    st.session_state['modules'] = options[:]
p = {'prefs':preferences({}), 'window':None}
v = {m:summarize([],p['prefs']) for m in options}
result = render_module_selector(options, {m:m for m in options},v,p,key='modules')
st.session_state['result'] = result
""").run()
    assert not app.exception
    assert not app.multiselect
    app.checkbox(key=row_key('modules','Module A')).uncheck().run()
    assert app.session_state['result'] == ['Module B']
    app.button(key='modules_none').click().run()
    assert app.session_state['result'] == []
    assert all(not c.value for c in app.checkbox)
    app.button(key='modules_all').click().run()
    assert app.session_state['result'] == ['Module A','Module B']
    assert all(c.value for c in app.checkbox)


def test_color_filters_limit_rows_and_exam_selection():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string("""
import streamlit as st
from src.practice_module_selector import render_module_selector
from src.study_progress import preferences, summarize
options = ['Red module', 'Yellow module', 'Green module', 'New module']
if 'modules' not in st.session_state:
    st.session_state['modules'] = options[:]
p = {'prefs':preferences({}), 'window':None}
v = {m:dict(summarize([],p['prefs']),color=c) for m,c in zip(options,['red','yellow','green','gray'])}
result = render_module_selector(options,{m:m for m in options},v,p,key='modules')
st.session_state['result'] = result
""").run()
    colors = lambda: app.get('button_group')[0]
    colors().set_value(['red']).run()
    assert not app.exception
    assert app.session_state['result'] == ['Red module']
    assert len(app.checkbox) == 1
    colors().set_value(['red','yellow']).run()
    assert app.session_state['result'] == ['Red module','Yellow module']
    colors().set_value(['green']).run()
    assert app.session_state['result'] == ['Green module']
    colors().set_value(['gray']).run()
    assert app.session_state['result'] == ['New module']
    app.button(key='modules_none').click().run()
    assert app.session_state['result'] == []
    app.button(key='modules_all').click().run()
    assert app.session_state['result'] == ['New module']
    colors().set_value([]).run()
    assert len(app.checkbox) == 4
    assert app.session_state['result'] == ['New module']
    app.button(key='modules_all').click().run()
    assert len(app.session_state['result']) == 4
