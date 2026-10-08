"""Create only synthetic examples inside the independent test namespace."""
import streamlit as st
import auth
import storage as db
from config import lab_settings
from activity_lab.core import sample_lesson

@st.cache_resource(show_spinner='테스트 계정과 예제 수업을 준비하는 중...')
def initialize():
    teacher=auth.bootstrap()
    if lab_settings().get('test_mode'):
        import classroom_ui
        svc=classroom_ui.service()
        with auth.state()['lock']:
            lesson_id=db.get_setting('demo_lesson_id')
            lesson=next((x for x in svc.lessons(teacher) if x['id']==lesson_id),None)
            if not lesson:
                template=sample_lesson();template['title']='[테스트] 함수, 움직이며 발견하기'
                lesson=svc.save_lesson(teacher,template);db.set_setting('demo_lesson_id',lesson['id'])
            room_id=db.get_setting('demo_room_id')
            room=next((r for r in svc.rooms(teacher) if r['id']==room_id),None)
            if not room:
                room=svc.create_room(teacher,lesson['id'],'1-1');db.set_setting('demo_room_id',room['id'])
                members=[auth.get_user(f'student{i:02}') for i in range(1,26)]
                for u in members:
                    if u:svc.join(u,room['code'])
                svc.control(teacher,room['id'],groups={u['id']:f'{i//4+1}모둠' for i,u in enumerate(members) if u})
    return True
