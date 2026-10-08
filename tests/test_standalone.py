import copy
from pathlib import Path
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
import auth
import bootstrap
import config
import storage as db
import classroom_ui
from activity_lab.component import renderer

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    backend=db.LocalBackend(str(tmp_path/'independent'))
    monkeypatch.setattr(db,'get_backend',lambda:backend)
    monkeypatch.setattr(config,'section',lambda name:{})
    db._cache.clear();auth.state.clear();bootstrap.initialize.clear();classroom_ui.service.clear()
    yield backend
    db._cache.clear();auth.state.clear();bootstrap.initialize.clear();classroom_ui.service.clear()

def no_error(app):assert not list(app.exception),[x.message for x in app.exception]

def enter(app,user,password):
    next(x for x in app.text_input if x.label=='아이디').input(user)
    next(x for x in app.text_input if x.label=='비밀번호').input(password)
    next(x for x in app.button if x.label=='들어가기').click().run(timeout=30)
    no_error(app)

def test_no_secrets_boot_opens_login_and_seeds_25_students(isolated):
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py').run(timeout=30);no_error(app)
    assert any(x.label=='아이디' for x in app.text_input)
    users=db.get_backend().read('users')
    assert sum(x['role']=='student' for x in users)==25
    assert auth.login('teacher',config.DEFAULT_TEACHER_PASSWORD)['role']=='teacher'
    assert len(classroom_ui.service().rooms(auth.get_user('student01')))==1
    bootstrap.initialize.clear();bootstrap.initialize()
    assert len(db.get_backend().read('users'))==26
    assert len(classroom_ui.service().rooms(auth.get_user('teacher')))==1

def test_teacher_login_controls_and_student_separate_sessions(isolated):
    teacher=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py').run(timeout=30)
    enter(teacher,'teacher',config.DEFAULT_TEACHER_PASSWORD)
    next(x for x in teacher.radio if x.label=='활동 메뉴').set_value('수업 운영').run();no_error(teacher)
    student=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py').run(timeout=30)
    enter(student,'student01',config.DEFAULT_STUDENT_PASSWORD)
    assert '학생 계정' not in next(x for x in student.radio if x.label=='메뉴').options
    assert any(x.type=='bidi_component' for x in student.main)
    next(x for x in teacher.button if x.label=='⏸ 전체 일시정지').click().run();no_error(teacher)
    user=auth.get_user('student01');svc=classroom_ui.service();room=svc.rooms(user)[0]
    assert svc.state(user,room['id'])['paused']
    student.run();no_error(student)
    next(x for x in teacher.button if x.label=='▶ 활동 재개').click().run();no_error(teacher)
    assert not svc.state(user,room['id'])['paused']

def test_student_account_create_reset_and_forced_password_change(isolated):
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py').run(timeout=30);enter(app,'teacher',config.DEFAULT_TEACHER_PASSWORD)
    next(x for x in app.radio if x.label=='메뉴').set_value('학생 계정').run();no_error(app)
    next(x for x in app.text_input if x.label=='학생 아이디').input('test999')
    next(x for x in app.text_input if x.label=='학생 이름').input('테스트999')
    next(x for x in app.text_input if x.label=='초기 비밀번호 (8자 이상)').input('NewTest!2026')
    next(x for x in app.button if x.label=='학생 계정 만들기').click().run();no_error(app)
    user=auth.login('test999','NewTest!2026');assert user['must_change']=='1'
    student=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py').run(timeout=30);enter(student,'test999','NewTest!2026')
    next(x for x in student.text_input if x.label=='현재 비밀번호').input('NewTest!2026')
    next(x for x in student.text_input if x.label=='새 비밀번호 (8자 이상)').input('Changed!2026')
    next(x for x in student.text_input if x.label=='새 비밀번호 확인').input('Changed!2026')
    next(x for x in student.button if x.label=='비밀번호 변경').click().run();no_error(student)
    assert auth.login('test999','Changed!2026')['must_change']=='0'
    assert auth.login('test999','NewTest!2026') is None
    with pytest.raises(auth.AccountError):auth.reset_password(user,'student01','Denied!2026')

def test_old_dashboard_configuration_and_files_are_not_loaded(tmp_path,monkeypatch):
    # Explicitly provided old settings must never select the old GitHub repo.
    old={'app':{'storage':'github'},'github':{'repo':'old/dashboard','token':'do-not-use'}}
    monkeypatch.setattr(config,'section',lambda name:copy.deepcopy(old.get(name,{})))
    monkeypatch.setattr(db,'section',lambda name:copy.deepcopy(old.get(name,{})))
    target=tmp_path/'lab';monkeypatch.setenv('ACTIVITY_LAB_DATA_DIR',str(target))
    db.get_backend.clear();db._cache.clear()
    backend=db.get_backend();assert backend.is_local and Path(backend.root)==target
    legacy=tmp_path/'data';legacy.mkdir();old_file=legacy/'users.csv';old_file.write_text('id,name,role\nold,Original,teacher\n')
    before=old_file.read_bytes();assert backend.read('users')==[]
    assert old_file.read_bytes()==before
    db.get_backend.clear();db._cache.clear()

def test_namespace_covers_github_tables_uploads_and_reader(tmp_path):
    class Response:
        status_code=200
        def __init__(self,data):self.data=data
        def json(self):return self.data
        def raise_for_status(self):pass
    b=object.__new__(db.GitHubBackend);b.repo='test/repo';b.rows={t:[] for t in db.SCHEMAS};requested=[]
    b._head=lambda:'head'
    b._req=lambda *a,**k:Response({'tree':[
        {'type':'blob','path':'data/users.csv','sha':'old'},
        {'type':'blob','path':'activity-lab/data/users.csv','sha':'new'}]})
    def blob(sha):requested.append(sha);return b'id,name,role\ntest,Test,teacher\n'
    b._blob=blob;b._load_all()
    assert requested==['new'] and b.rows['users'][0]['id']=='test'
    assert db.GitHubBackend._path('users',{'id':'x'})=='activity-lab/data/users.csv'
    assert db.GitHubBackend._path('act_answers',{'id':'x','room_id':'r'})=='activity-lab/data/act_answers/r.csv'
    assert 'materials' not in db.SCHEMAS and 'emotions' not in db.SCHEMAS

def test_default_demo_password_cannot_enable_ai(isolated,monkeypatch):
    auth.bootstrap()
    cfg={'lab':{'teacher_password':'CustomSecure!2026'},'openai':{'api_key':'not-a-real-key'}}
    monkeypatch.setattr(config,'section',lambda name:copy.deepcopy(cfg.get(name,{})))
    assert config.ai_settings()=={}
    actor=auth.get_user('teacher');auth.change_password(actor,config.DEFAULT_TEACHER_PASSWORD,'CustomSecure!2026')
    assert config.ai_settings()['api_key']=='not-a-real-key'

def test_non_demo_requires_explicit_teacher_password(isolated,monkeypatch):
    monkeypatch.setattr(config,'section',lambda name:{'test_mode':False} if name=='lab' else {})
    with pytest.raises(auth.AccountError):auth.bootstrap()
    assert not db.get_backend().read('users')

def test_clean_package_has_no_dashboard_dependency():
    text=Path('app.py').read_text()+Path('classroom_ui.py').read_text()
    assert 'from views' not in text and 'import realtime' not in text and 'import ui' not in text
    assert not Path('views').exists()
