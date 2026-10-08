"""Independent Streamlit entrypoint: python -m streamlit run app.py."""
import streamlit as st
st.set_page_config(page_title='수학 액티비티 Lab',page_icon='🧩',layout='wide')

import auth
import storage as db
from config import APP_TITLE,CLASSES,lab_settings,DEFAULT_TEACHER_PASSWORD,DEFAULT_STUDENT_PASSWORD,section
from bootstrap import initialize

st.markdown('''<style>
.block-container{max-width:1440px;padding-top:2rem}
.lab-hero{background:linear-gradient(120deg,#eef4ff,#f1faf6);border:1px solid #dbe7ef;border-radius:22px;padding:30px;margin-bottom:22px;color:#20334b}
.lab-hero h1{font-size:2rem;margin:4px 0 10px}.lab-hero p{color:#546a7e;font-size:1.05rem}.lab-tag{letter-spacing:.06em;font-size:.8rem;color:#376e86}
</style>''',unsafe_allow_html=True)

config=lab_settings()
try:initialize()
except Exception as e:
    st.title(APP_TITLE)
    st.error('테스트 앱 설정을 확인해 주세요.')
    st.write(str(e))
    st.info('설정 없이 시작하려면 Secrets의 [lab] storage를 "local"로 설정하세요. 실행 파일은 app.py입니다.')
    st.stop()


def login_page():
    st.markdown('''<div class="lab-hero"><div class="lab-tag">CLASSROOM ACTIVITY · TEST SPACE</div><h1>수학 액티비티 Lab</h1><p>학생의 생각을 보고, 함께 나누고, 수업의 흐름을 조절하세요.</p></div>''',unsafe_allow_html=True)
    left,right=st.columns([1.05,1],gap='large')
    with left:
        st.subheader('독립 테스트 앱')
        st.write('수업 만들기 · 실시간 답안 · 화면 제어 · 모둠 협업 · 익명 공유 · 과정 기록')
        if config.get('test_mode'):
            st.info('가상 계정으로 기능을 시험하는 공간입니다. 실제 학생 개인정보를 입력하지 마세요.')
            with st.expander('테스트 계정 확인',expanded=True):
                tid=str(config.get('teacher_id','teacher'))
                st.write(f'**교사 아이디:** {tid}')
                teacher=auth.get_user(tid)
                if teacher and auth.check_pw(DEFAULT_TEACHER_PASSWORD,teacher['pw_hash']):
                    st.code(DEFAULT_TEACHER_PASSWORD,language=None)
                else:st.caption('교사 비밀번호: 직접 설정한 비밀번호를 사용하세요.')
                st.write('**학생 아이디:** student01 ~ student25')
                st.code(DEFAULT_STUDENT_PASSWORD,language=None)
                st.caption('모든 테스트 학생은 1-1반입니다. 비밀번호를 변경한 계정은 변경한 값을 사용하세요.')
        st.caption('교사 창과 학생 창을 다른 브라우저 또는 시크릿 창으로 열면 실시간 수업을 확인할 수 있어요.')
    with right,st.container(border=True):
        st.subheader('로그인')
        with st.form('login'):
            user_id=st.text_input('아이디',placeholder='teacher 또는 student01')
            password=st.text_input('비밀번호',type='password')
            submit=st.form_submit_button('들어가기',type='primary',width='stretch')
        if submit:
            try:
                user=auth.login(user_id,password)
                if user:st.session_state['lab_user']=user;st.rerun()
                else:st.error('아이디 또는 비밀번호를 확인해 주세요.')
            except auth.AccountError as e:st.error(str(e))
        if db.get_backend().is_local:
            st.caption('임시 테스트 저장: Cloud 재배포나 절전 복구로 기록이 초기화될 수 있습니다.')


def password_page(user,force=False):
    st.title('비밀번호 변경')
    if force:st.info('처음 로그인한 계정입니다. 새 비밀번호를 설정해 주세요.')
    with st.form('change_pw'):
        old=st.text_input('현재 비밀번호',type='password')
        new=st.text_input('새 비밀번호 (8자 이상)',type='password')
        confirm=st.text_input('새 비밀번호 확인',type='password')
        submit=st.form_submit_button('비밀번호 변경',type='primary')
    if submit:
        try:
            if new!=confirm:raise auth.AccountError('새 비밀번호 두 칸이 서로 달라요.')
            auth.change_password(user,old,new)
            st.session_state['lab_user']=auth.public_user(auth.get_user(user['id']))
            st.success('비밀번호를 변경했어요.')
            if force:st.rerun()
        except auth.AccountError as e:st.error(str(e))


def manage_students(user):
    auth.require_teacher(user)
    st.title('학생 계정')
    st.caption('이 독립 앱에만 등록되는 계정입니다.')
    with st.form('new_student'):
        sid=st.text_input('학생 아이디',placeholder='예: test101')
        name=st.text_input('학생 이름',placeholder='테스트 학생')
        cls=st.selectbox('학급',CLASSES)
        password=st.text_input('초기 비밀번호 (8자 이상)',type='password')
        if st.form_submit_button('학생 계정 만들기',type='primary'):
            try:auth.add_student(user,sid,name,cls,password);st.success('계정을 만들었어요. 첫 로그인에서 비밀번호를 바꾸게 됩니다.')
            except auth.AccountError as e:st.error(str(e))
    students=[auth.public_user(u) for u in db.get_backend().read('users') if u['role']=='student']
    if students:
        st.dataframe([{'아이디':u['id'],'이름':u['name'],'학급':u['class']} for u in students],hide_index=True,width='stretch')
        with st.expander('학생 비밀번호 초기화'):
            with st.form('reset_pw'):
                mapping={u['id']:u for u in students}
                selected=st.selectbox('학생 선택',list(mapping),format_func=lambda k:f"{k} · {mapping[k]['name']}")
                password=st.text_input('새 초기 비밀번호',type='password')
                if st.form_submit_button('선택한 학생의 비밀번호 초기화'):
                    try:auth.reset_password(user,selected,password);st.success('변경했어요. 학생에게 새 초기 비밀번호를 알려 주세요.')
                    except auth.AccountError as e:st.error(str(e))


def instructions():
    st.title('테스트 순서')
    st.markdown('''
1. **교사**로 로그인하고 활동 메뉴의 **수업 운영**을 엽니다.
2. **student01**로 다른 브라우저/시크릿 창에 로그인합니다. 예제 수업이 준비되어 있습니다.
3. 학생이 답을 입력하면 교사의 실시간 표와 답안 상세에 표시되는지 확인합니다.
4. 교사가 일시정지·진행 범위·같은 화면으로 모으기를 눌러 봅니다.
5. 학생 두 명으로 모둠 공동 보드에 메모·필기를 각각 올립니다.
6. 학생이 ‘우리 학급’ 공개를 선택한 답안을 교사가 선택해 **발표 화면**에서 봅니다.
7. **학습 기록**에서 파일을 내려받습니다.

새 수업은 **수업 만들기 → 수업 운영 → 반별로 새 수업 배포** 순서로 엽니다.
''')
    st.caption('AI 피드백은 선택 기능입니다. API 키와 직접 정한 교사 비밀번호를 설정한 뒤 수업 운영에서 사용을 열어 주세요.')
    st.code('[lab]\nteacher_password = "직접-정한-8자-이상-비밀번호"\n\n[openai]\napi_key = "실제-API-키"\nmodel = "gpt-4.1-mini"\ntranscribe_model = "gpt-4o-mini-transcribe"',language='toml')
    st.caption('교사 계정이 이미 생성된 경우 ‘내 비밀번호’에서도 같은 비밀번호로 변경하세요. 설정은 기존 계정을 자동 덮어쓰지 않습니다.')
    st.write(db.backend_status())

user=st.session_state.get('lab_user')
if not user:
    login_page();st.stop()
fresh=auth.get_user(user['id'])
if not fresh:
    st.session_state.clear();st.rerun()
user=auth.public_user(fresh);st.session_state['lab_user']=user
with st.sidebar:
    st.title('🧩 Activity Lab')
    st.caption('독립 테스트 공간' if config.get('test_mode') else '수업 활동 공간')
    st.write(f"**{user['name']}** · {'교사' if user['role']=='teacher' else user['class']}")
    options=['활동']+(['학생 계정'] if user['role']=='teacher' else [])+['내 비밀번호','실행 안내']
    menu=st.radio('메뉴',options,key='lab_nav')
    if st.button('로그아웃',width='stretch'):
        st.session_state.clear();st.rerun()
    st.divider()
    if user['role']=='teacher':st.caption(db.backend_status())
if user.get('must_change')=='1':
    password_page(user,True);st.stop()
if menu=='내 비밀번호':password_page(user)
elif menu=='학생 계정':manage_students(user)
elif menu=='실행 안내':instructions()
else:
    import classroom_ui
    classroom_ui.page(user)
