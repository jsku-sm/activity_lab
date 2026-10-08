"""Standalone teacher/student accounts, isolated from the previous dashboard."""
import hashlib
import hmac
import os
import re
import threading
import time
import streamlit as st
import storage as db
from config import lab_settings,DEFAULT_TEACHER_PASSWORD,DEFAULT_STUDENT_PASSWORD,CLASSES

class AccountError(ValueError):pass

def hash_pw(password):
    salt=os.urandom(16)
    h=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,260000)
    return f'{salt.hex()}${h.hex()}'

def check_pw(password,stored):
    try:
        salt,digest=stored.split('$')
        return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex(),digest)
    except (ValueError,TypeError,AttributeError):return False

@st.cache_resource(show_spinner=False)
def state():return {'lock':threading.RLock(),'failed':{}}

def get_user(user_id):
    return next((dict(u) for u in db.get_backend().read('users') if u['id']==user_id),None)

def public_user(u):return {k:u.get(k,'') for k in ('id','name','class','role','must_change')}

def validate_password(password):
    if not isinstance(password,str) or len(password)<8:raise AccountError('비밀번호는 8자 이상 입력해 주세요.')
    if len(password)>128:raise AccountError('비밀번호는 128자 이하로 입력해 주세요.')

def bootstrap():
    config=lab_settings();tid=str(config.get('teacher_id','teacher')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,40}',tid):raise AccountError('교사 아이디는 영문·숫자·밑줄·하이픈 3~40자로 정해 주세요.')
    with state()['lock']:
        if not any(u['role']=='teacher' for u in db.get_backend().read('users')):
            if not config.get('test_mode') and not config.get('teacher_password'):
                raise AccountError('test_mode=false에서는 [lab] teacher_password를 먼저 설정해 주세요.')
            password=str(config.get('teacher_password') or DEFAULT_TEACHER_PASSWORD);validate_password(password)
            db.append('users',{'id':tid,'name':'테스트 교사' if config.get('test_mode') else '선생님','class':'','role':'teacher',
                     'pw_hash':hash_pw(password),'must_change':'0','created_at':db.now_str()})
        if config.get('test_mode') and not db.get_setting('demo_accounts_ready'):
            for i in range(1,26):
                sid=f'student{i:02}'
                if not get_user(sid):
                    db.append('users',{'id':sid,'name':f'테스트 학생 {i:02}','class':'1-1','role':'student',
                        'pw_hash':hash_pw(DEFAULT_STUDENT_PASSWORD),'must_change':'0','created_at':db.now_str()})
            db.set_setting('demo_accounts_ready','1')
    return get_user(tid) or next(u for u in db.get_backend().read('users') if u['role']=='teacher')

def login(user_id,password):
    user_id=str(user_id).strip();now=time.time()
    with state()['lock']:
        previous=[t for t in state()['failed'].get(user_id,[]) if now-t<120]
        if len(previous)>=8:raise AccountError('로그인 실패가 반복되어 2분 동안 잠시 기다려 주세요.')
        user=get_user(user_id)
        if user and check_pw(password,user['pw_hash']):
            state()['failed'].pop(user_id,None);return public_user(user)
        state()['failed'][user_id]=previous+[now]
        return None

def require_teacher(actor):
    current=get_user(actor.get('id'))
    if not current or current['role']!='teacher':raise AccountError('교사 계정에서만 사용할 수 있어요.')
    return current

def add_student(actor,user_id,name,cls,password,must_change=True):
    require_teacher(actor);validate_password(password)
    user_id=str(user_id).strip();name=str(name).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,40}',user_id):raise AccountError('학생 아이디는 영문·숫자·밑줄·하이픈 3~40자로 입력해 주세요.')
    if not name or len(name)>50:raise AccountError('이름을 1~50자로 입력해 주세요.')
    if cls not in CLASSES:raise AccountError('학급을 확인해 주세요.')
    with state()['lock']:
        if get_user(user_id):raise AccountError('이미 등록된 아이디예요.')
        db.append('users',{'id':user_id,'name':name,'class':cls,'role':'student','pw_hash':hash_pw(password),
            'must_change':'1' if must_change else '0','created_at':db.now_str()})

def reset_password(actor,user_id,password):
    require_teacher(actor);validate_password(password);user=get_user(user_id)
    if not user or user['role']!='student':raise AccountError('등록된 학생 계정을 선택해 주세요.')
    db.update('users',user_id,{'pw_hash':hash_pw(password),'must_change':'1'})

def change_password(actor,current_password,new_password):
    user=get_user(actor['id'])
    if not user or not check_pw(current_password,user['pw_hash']):raise AccountError('현재 비밀번호를 확인해 주세요.')
    validate_password(new_password)
    db.update('users',user['id'],{'pw_hash':hash_pw(new_password),'must_change':'0'})
