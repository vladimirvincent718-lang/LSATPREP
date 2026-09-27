import json
import random
import pytest
from streamlit.testing.v1 import AppTest
from src import database
from src.answer_key import load_questions, counts, make_preview, commit_preview, remap_references, distribution_health


@pytest.fixture
def bank(monkeypatch,tmp_path):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'bank.db')
    database.init_database()
    conn=database.get_connection()
    user=conn.execute("INSERT INTO users(username,password_hash,is_admin) VALUES ('owner','x',1)").lastrowid
    course=conn.execute("INSERT INTO courses(title) VALUES ('Test bank')").lastrowid
    for n in range(20):
        conn.execute('''INSERT INTO questions(course_id,question_id,stimulus,choice_a,choice_b,choice_c,choice_d,correct_answer,explanation,wrong_answer_b,content_hash)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                     (course,str(n),f'Question {n}','Correct content','Wrong B','Wrong C','Wrong D','A','Answer A is correct.\n* **B:** Wrong B reason.','Choice B is incorrect.',f'hash{n}'))
    conn.commit();conn.close()
    return course,user


def test_preview_balances_and_preserves_content(bank):
    course,_=bank
    rows=load_questions([course]); p=make_preview(rows,[course],True,random.Random(5))
    assert p['after']==dict(A=5,B=5,C=5,D=5,E=0)
    assert load_questions([course])==rows
    assert p != make_preview(rows,[course],True,random.Random(9))
    for e in p['edits']:
        before,after=e['before'],e['after']
        assert after['choice_'+after['correct_answer'].lower()]=='Correct content'
        assert sorted(after['choice_'+c] for c in 'abcd')==sorted(before['choice_'+c] for c in 'abcd')
        assert 'Answer '+after['correct_answer']+' is correct.' in after['explanation']
        wrong=e['mapping']['B']
        assert f'**{wrong}:** Wrong B reason.' in after['explanation']
        assert after['wrong_answer_'+wrong.lower()]==f'Choice {wrong} is incorrect.'


def test_commit_remaps_history_and_rejects_stale_preview(bank):
    course,user=bank; rows=load_questions([course]);p=make_preview(rows,[course],True,random.Random(5))
    conn=database.get_connection()
    attempt=conn.execute('INSERT INTO exam_attempts(user_id,course_id) VALUES (?,?)',(user,course)).lastrowid
    conn.execute('INSERT INTO user_answers(attempt_id,question_id,selected_answer,is_correct) VALUES (?,?,?,1)',(attempt,rows[0]['id'],'A'))
    conn.commit();conn.close()
    assert commit_preview(p,user)==20
    assert counts(load_questions([course]))==p['after']
    conn=database.get_connection()
    history=conn.execute('SELECT selected_answer,is_correct FROM user_answers').fetchone()
    assert history['selected_answer']==p['edits'][0]['mapping']['A'] and history['is_correct']==1
    assert conn.execute('SELECT COUNT(*) FROM answer_key_changes').fetchone()[0]==1
    assert conn.execute('SELECT content_hash FROM questions ORDER BY id').fetchone()[0]=='hash0'
    conn.close()
    with pytest.raises(ValueError,match='changed'):
        commit_preview(p,user)


def test_invalid_and_position_dependent_choices_are_explicitly_skipped(bank):
    course,_=bank;rows=load_questions([course])
    rows[0]['choice_d']='All of the above'
    rows[1]['correct_answer']=None
    p=make_preview(rows,[course])
    assert len(p['skipped'])==2 and len(p['edits'])==18


def test_saved_exam_and_non_admin_block_commit(bank):
    course,user=bank;rows=load_questions([course]);p=make_preview(rows,[course])
    with pytest.raises(ValueError,match='administrator'):
        commit_preview(p,-1)
    conn=database.get_connection()
    attempt=conn.execute('INSERT INTO exam_attempts(user_id,course_id) VALUES (?,?)',(user,course)).lastrowid
    conn.execute('INSERT INTO exam_drafts(user_id,attempt_id,course_id,state_json) VALUES (?,?,?,?)',(user,attempt,course,json.dumps({'exam_questions':rows})))
    conn.commit();conn.close()
    with pytest.raises(ValueError,match='saved practice'):
        commit_preview(p,user)
    assert load_questions([course])==rows


def test_ui_preview_retry_discard_and_commit(bank):
    course,user=bank
    code=f'from src.answer_key_ui import render_answer_key\nrender_answer_key([{course}],{user})'
    at=AppTest.from_string(code).run()
    before=load_questions([course])
    at.radio[0].set_value('Evenly balanced')
    at.button(key='answer_key_generate').click().run()
    assert not at.exception
    assert load_questions([course])==before
    at.button(key='answer_key_generate').click().run()
    assert load_questions([course])==before
    at.button(key='answer_key_discard').click().run()
    assert load_questions([course])==before
    at.button(key='answer_key_generate').click().run()
    at.button(key='answer_key_commit').click().run()
    assert not at.exception
    assert counts(load_questions([course]))==dict(A=5,B=5,C=5,D=5,E=0)
    assert at.success


def test_prose_is_not_mistaken_for_answer_labels():
    assert remap_references('A newborn has type B blood.', {'A':'D','B':'C'})=='A newborn has type B blood.'


def test_five_choices_duplicate_text_and_written_responses(bank):
    course,_=bank
    rows=load_questions([course])
    for row in rows:
        row['choice_e']='Wrong E'
        row['choice_b']=row['choice_a']  # Identity, not matching text, determines correctness.
    p=make_preview(rows,[course],True,random.Random(1))
    assert p['after']==dict(A=4,B=4,C=4,D=4,E=4)
    for edit in p['edits']:
        assert edit['after']['correct_answer']==edit['mapping']['A']
        assert edit['after']['choice_e']
    rows[0]['question_type']='open-ended'
    assert len(make_preview(rows,[course])['skipped'])==1


def test_tolerance_uses_available_choices_and_inclusive_boundary(bank):
    course, _ = bank
    rows = load_questions([course])
    for row, letter in zip(rows, 'AAAAAABBBBBCCCCCDDDD'):
        row['correct_answer'] = letter
    health = distribution_health(rows, 5)
    assert not health['breaches']  # 30/25/25/20 is inside the inclusive 20–30 range.
    assert {item['Answer'] for item in health['details']} == set('ABCD')
    assert distribution_health(rows, 4)['breaches']
    five = [dict(row, id=row['id'] + 100, choice_e='Fifth', correct_answer='ABCDE'[i % 5])
            for i, row in enumerate(rows)]
    assert not distribution_health(rows + five, 5)['breaches']
    assert not distribution_health(rows[:19], 0)['breaches']
    rows[0]['correct_answer'] = None
    rows[1]['question_type'] = 'open-ended'
    assert distribution_health(rows)['excluded'] == 2


def test_auto_preview_is_stable_dismissible_and_rechecks_bank_changes(bank):
    course, user = bank
    code = f'from src.answer_key_ui import render_answer_key\nrender_answer_key([{course}],{user})'
    before = load_questions([course])
    at = AppTest.from_string(code).run()
    assert not at.exception
    assert at.warning
    preview = at.session_state['answer_key_preview']
    assert preview['method'] == 'Evenly balanced'
    assert preview['after'] == dict(A=5, B=5, C=5, D=5, E=0)
    at.run()
    assert at.session_state['answer_key_preview'] == preview
    assert load_questions([course]) == before
    at.button(key='answer_key_discard').click().run()
    assert 'answer_key_preview' not in at.session_state
    at.run()
    assert 'answer_key_preview' not in at.session_state
    conn = database.get_connection()
    conn.execute('UPDATE questions SET stimulus=? WHERE id=?', ('Updated question', before[0]['id']))
    conn.commit()
    conn.close()
    at.run()
    assert at.session_state['answer_key_preview']['fingerprint'] != preview['fingerprint']
    at.button(key='answer_key_commit').click().run()
    assert not at.exception
    assert not at.warning
    assert 'answer_key_preview' not in at.session_state


def test_tolerance_persists_for_new_visit(bank):
    course, user = bank
    code = f'from src.answer_key_ui import render_answer_key\nrender_answer_key([{course}],{user})'
    at = AppTest.from_string(code).run()
    at.number_input(key='answer_key_tolerance').set_value(9.0).run()
    assert database.get_setting(user, 'answer_key_tolerance_pp') == '9.0'
    fresh = AppTest.from_string(code).run()
    assert not fresh.exception
    assert fresh.number_input(key='answer_key_tolerance').value == 9.0
