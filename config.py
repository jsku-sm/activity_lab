"""Independent app configuration. Does not read dashboard [app]/[github] settings."""
from zoneinfo import ZoneInfo
import streamlit as st
TZ=ZoneInfo('Asia/Seoul')
APP_TITLE='수학 액티비티 Lab'
CLASSES=[f'1-{i}' for i in range(1,8)]
SUBJECTS=['공통수학1','공통수학2']
DEFAULT_SETTINGS={}
LAB_PREFIX='activity-lab/'
DEFAULT_TEACHER_PASSWORD='TeacherTest!2026'
DEFAULT_STUDENT_PASSWORD='StudentTest!2026'

def section(name):
    try:return dict(st.secrets.get(name,{}))
    except (FileNotFoundError,KeyError):return {}

def lab_settings():
    config=section('lab')
    return {'test_mode':True,'storage':'local','teacher_id':'teacher',**config}

def ai_settings():
    cfg=section('openai');lab=lab_settings()
    # The publicly documented demo teacher password must not unlock a paid API key.
    if not lab.get('teacher_password') or lab.get('teacher_password')==DEFAULT_TEACHER_PASSWORD:
        return {}
    import auth
    user=auth.get_user(str(lab.get('teacher_id','teacher')))
    if not user or auth.check_pw(DEFAULT_TEACHER_PASSWORD,user['pw_hash']):
        return {}
    return cfg
