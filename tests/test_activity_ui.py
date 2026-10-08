import json
import pytest
from streamlit.testing.v1 import AppTest
import streamlit as st
import storage as db
import classroom_ui as activities
from activity_lab.component import renderer
from activity_lab.core import sample_lesson

TEACHER={'id':'teacher','role':'teacher','name':'교사','class':'','must_change':'0'}
STUDENT={'id':'10101','role':'student','name':'학생1','class':'1-1','must_change':'0'}

@pytest.fixture
def appenv(tmp_path,monkeypatch):
    backend=db.LocalBackend(str(tmp_path/'data'))
    monkeypatch.setattr(db,'get_backend',lambda:backend)
    db._cache.clear();activities.service.clear()
    for u in [TEACHER,STUDENT]:backend.append('users',u)
    yield backend
    activities.service.clear();db._cache.clear()

def no_error(at):assert not list(at.exception),[e.message for e in at.exception]

def teacher_app():
    return AppTest.from_string("from classroom_ui import page\npage("+repr(TEACHER)+")").run(timeout=15)

def test_author_deploy_and_operating_controls(appenv):
    a=teacher_app();no_error(a)
    next(x for x in a.text_input if x.label=='새 수업 제목').input('실제 작동 시험')
    next(x for x in a.button if x.label=='새 수업 만들기').click().run();no_error(a)
    assert any(x.label=='화면 제목' for x in a.text_input)
    a.radio[0].set_value('수업 운영').run();no_error(a)
    next(x for x in a.button if x.label=='수업 배포 · 참여 코드 만들기').click().run();no_error(a)
    s=activities.service();r=s.rooms(TEACHER)[0]
    next(x for x in a.button if x.label=='⏸ 전체 일시정지').click().run();no_error(a)
    assert s.state(TEACHER,r['id'])['paused']
    next(x for x in a.button if x.label=='▶ 활동 재개').click().run();no_error(a)
    assert not s.state(TEACHER,r['id'])['paused']
    a.radio[0].set_value('학습 기록').run();no_error(a)

def test_student_join_and_component_registration(appenv):
    s=activities.service();l=s.save_lesson(TEACHER,sample_lesson());r=s.create_room(TEACHER,l['id'],'1-1')
    a=AppTest.from_string("from classroom_ui import page\npage("+repr(STUDENT)+")").run(timeout=15);no_error(a)
    next(x for x in a.text_input if x.label=='수업 참여 코드').input(r['code'])
    next(x for x in a.button if x.label=='수업 참여').click().run();no_error(a)
    assert len(s.rooms(STUDENT))==1
    assert any(n.type=='bidi_component' for n in a.main)

def test_teacher_feedback_and_records_render(appenv):
    s=activities.service();l=s.save_lesson(TEACHER,sample_lesson());r=s.create_room(TEACHER,l['id'],'1-1');s.join(STUDENT,r['code'])
    sid=l['screens'][0]['id'];s.save_answer(STUDENT,r['id'],sid,{'choice':'1','text':'생각했어요'},0,True,'class')
    a=teacher_app();a.radio[0].set_value('수업 운영').run();no_error(a)
    next(x for x in a.text_area if x.label=='학생에게 남길 피드백').input('근거를 한 줄 더 써보세요.')
    next(x for x in a.button if x.label=='피드백 보내기').click().run();no_error(a)
    assert s.state(STUDENT,r['id'])['answers'][0]['teacher_feedback']=='근거를 한 줄 더 써보세요.'
    next(x for x in a.button if x.label=='이 답안을 전체 공유 목록에 추가').click().run();no_error(a)
    assert len(s.state(STUDENT,r['id'])['snapshots'])==1
    a.radio[0].set_value('학습 기록').run();no_error(a)


def test_presentation_screen_renders(appenv):
    s=activities.service();l=s.save_lesson(TEACHER,sample_lesson());r=s.create_room(TEACHER,l['id'],'1-1')
    a=teacher_app();a.radio[0].set_value('발표 화면').run();no_error(a)
    assert not any(x.label=='학생에게 남길 피드백' for x in a.text_area)
    assert any(n.type=='bidi_component' for n in a.main)
