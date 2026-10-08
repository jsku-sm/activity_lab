"""Activity authoring, orchestration, and live student workspace."""
from __future__ import annotations
import base64
import copy
import csv
import io
import json
import zipfile
from pathlib import Path
import pandas as pd
import streamlit as st
import auth
import storage as db
from config import CLASSES, SUBJECTS, ai_settings
from activity_lab.core import ActivityService, ActivityError, TYPES, screen_template, sample_lesson, uid
from activity_lab.ai import FeedbackAI
from activity_lab.component import workspace
from activity_lab.media import pdf_pages, render_strokes

TYPE_LABELS={'text':'서술형·성찰','choice':'선택형','graph':'그래프 탐구','cards':'카드 분류','table':'표·좌표 탐구','drawing':'그림·필기','pdf':'PDF 학습지 필기'}
CHECK_LABELS={'manual':'교사 확인','exact':'텍스트 일치','number':'수치 비교','choice':'선택지 확인','cards':'카드 분류 확인'}

@st.cache_resource(show_spinner=False)
def service():
    return ActivityService(db.get_backend(),FeedbackAI(ai_settings()))

def run(action):
    try: return action()
    except ActivityError as e: st.error(str(e)); return None


def page(user):
    st.title('수학 액티비티 Lab')
    st.caption('생각을 쓰고, 함께 살펴보고, 다시 발견하는 수학 시간')
    try:
        svc=service()
        if user['role']=='teacher':
            section=st.radio('활동 메뉴',['수업 만들기','수업 운영','발표 화면','학습 기록'],horizontal=True,key='act_section')
            if section=='수업 만들기': author(user,svc)
            elif section=='수업 운영': operate(user,svc)
            elif section=='발표 화면': presentation(user,svc)
            else: records(user,svc)
        else: student(user,svc)
    except ActivityError as e: st.error(str(e))


def author(user,svc):
    a,b=st.columns([2,1])
    with a,st.form('act_new'):
        title=st.text_input('새 수업 제목',placeholder='예: 함수, 움직이며 발견하기')
        sample=st.checkbox('함수 탐구 예제 5개 화면으로 시작',value=True)
        create=st.form_submit_button('새 수업 만들기',type='primary')
    if create:
        payload=sample_lesson() if sample else {'title':title,'subject':'공통수학2','screens':[screen_template()]}
        if title.strip(): payload['title']=title.strip()
        lesson=run(lambda:svc.save_lesson(user,payload))
        if lesson: st.session_state['act_lesson']=lesson['id'];st.rerun()
    lessons=svc.lessons(user)
    if not lessons: st.info('새 수업을 만들면 화면별 질문과 활동을 편집할 수 있어요.');return
    mapping={l['id']:l for l in lessons}
    if st.session_state.get('act_lesson') not in mapping: st.session_state['act_lesson']=lessons[-1]['id']
    lid=st.selectbox('편집할 수업',list(mapping),format_func=lambda k:mapping[k]['title'],key='act_lesson')
    lesson=copy.deepcopy(mapping[lid]);version=lesson['version']
    c1,c2=st.columns([4,1])
    with c1,st.form(f'act_meta_{lid}_{version}'):
        title=st.text_input('수업 제목',value=lesson['title'])
        subject=st.selectbox('과목',SUBJECTS,index=SUBJECTS.index(lesson['subject']) if lesson['subject'] in SUBJECTS else 0)
        if st.form_submit_button('제목·과목 저장'):
            lesson.update(title=title,subject=subject)
            if run(lambda:svc.save_lesson(user,lesson,version)): st.rerun()
    with c2:
        st.write('')
        if st.button('수업 복제',key=f'clone_{lid}'):
            lesson.pop('id');lesson['title']+=' (사본)';new=svc.save_lesson(user,lesson)
            st.session_state['act_choose_next']=new['id'];st.success('사본을 만들었어요. 위 목록에서 선택해 주세요.');st.rerun()
    screens=lesson['screens'];screen_map={s['id']:s for s in screens}
    sid=st.selectbox('활동 화면',list(screen_map),format_func=lambda k:f"{list(screen_map).index(k)+1}. {screen_map[k]['title']}",key=f'act_screen_{lid}')
    screen=copy.deepcopy(screen_map[sid]);idx=list(screen_map).index(sid)
    cols=st.columns(4)
    if cols[0].button('＋ 화면 추가',key=f'add_{lid}'):
        lesson['screens'].append(screen_template(title=f'{len(screens)+1:02} · 새 활동'))
        svc.save_lesson(user,lesson,version);st.rerun()
    if cols[1].button('↑ 위로',disabled=idx==0,key=f'up_{sid}'):
        screens[idx-1],screens[idx]=screens[idx],screens[idx-1];svc.save_lesson(user,lesson,version);st.rerun()
    if cols[2].button('↓ 아래로',disabled=idx==len(screens)-1,key=f'down_{sid}'):
        screens[idx+1],screens[idx]=screens[idx],screens[idx+1];svc.save_lesson(user,lesson,version);st.rerun()
    if cols[3].button('이 화면 삭제',disabled=len(screens)==1,key=f'del_{sid}'):
        lesson['screens']=[s for s in screens if s['id']!=sid]
        for s in lesson['screens']:
            for k in ('next_correct','next_incorrect'):
                if s.get(k)==sid: s[k]=''
        svc.save_lesson(user,lesson,version);st.rerun()
    kind=st.selectbox('활동 종류',TYPES,index=TYPES.index(screen['type']),format_func=TYPE_LABELS.get,key=f'kind_{sid}_{version}')
    with st.form(f'act_edit_{sid}_{version}_{kind}'):
        screen['type']=kind
        screen['title']=st.text_input('화면 제목',value=screen['title'])
        screen['prompt']=st.text_area('질문·수업 내용',value=screen['prompt'],height=120)
        screen['hint']=st.text_area('학생이 열어볼 힌트',value=screen['hint'])
        screen['group_work']=st.checkbox('이 화면에 모둠 공동 보드 열기',value=screen.get('group_work',False))
        if kind=='choice':
            options=st.text_area('선택지 (한 줄에 하나)',value='\n'.join(screen.get('options',[])))
            screen['options']=[s.strip() for s in options.splitlines() if s.strip()]
        if kind=='cards':
            cards=st.text_area('분류할 카드 (한 줄에 하나)',value='\n'.join(screen.get('cards',[])))
            cats=st.text_input('분류 상자 (쉼표로 구분)',value=', '.join(screen.get('categories',[])))
            screen['cards']=[s.strip() for s in cards.splitlines() if s.strip()]
            screen['categories']=[s.strip() for s in cats.split(',') if s.strip()]
        if kind in ('graph','table'):
            screen['expression']=st.text_input('처음 보여줄 식',value=screen.get('expression','y=a*x+b'),help='y=a*x+b, y=a*x^2+b, x^2+y^2=c^2 등을 지원합니다.')
            pc=st.columns(3);screen['params']={k:pc[i].number_input(f'{k} 초기값',-10.,10.,float(screen.get('params',{}).get(k,0)),.1) for i,k in enumerate(('a','b','c'))}
            table_text=st.text_area('좌표표 초깃값 (한 줄에 x,y)',value='\n'.join(','.join(map(str,r)) for r in screen.get('table',[])))
            screen['table']=[r.split(',')[:2] for r in table_text.splitlines() if ',' in r][:30]
        st.markdown('**피드백과 수준별 다음 활동**')
        check=copy.deepcopy(screen.get('check',{}))
        methods=['manual','exact','number']+(['choice'] if kind=='choice' else [])+(['cards'] if kind=='cards' else [])
        ck=check.get('kind','manual');ck=ck if ck in methods else 'manual'
        check['kind']=st.selectbox('답안 확인 방법',methods,index=methods.index(ck),format_func=CHECK_LABELS.get)
        old=check.get('answer','')
        answer_text=st.text_input('기준 답 (선택형은 1부터 센 번호 / 카드형은 아래 안내)',value=(str(int(old)+1) if ck=='choice' and str(old).isdigit() else json.dumps(old,ensure_ascii=False) if isinstance(old,dict) else str(old)))
        st.caption('카드 기준 답 예: {"0":"일차함수","1":"이차함수"} — 카드 번호는 0부터입니다. 수식의 수학적 동치는 자동 판정하지 않으므로 교사 확인을 선택하세요.')
        check['tolerance']=st.number_input('수치 비교 허용 오차',min_value=0.,value=float(check.get('tolerance',.001)),format='%.4f')
        check['success']=st.text_input('조건 충족 시 피드백',value=check.get('success','조건을 만족했어요.'))
        check['retry']=st.text_input('다시 생각할 때 피드백',value=check.get('retry','조건을 다시 확인해보세요.'))
        branch_ids=['']+list(screen_map)
        screen['next_correct']=st.selectbox('조건 충족 후 활동',branch_ids,index=branch_ids.index(screen.get('next_correct','')),format_func=lambda k:'학생이 순서대로 진행' if not k else screen_map[k]['title'])
        screen['next_incorrect']=st.selectbox('보충 활동',branch_ids,index=branch_ids.index(screen.get('next_incorrect','')),format_func=lambda k:'학생이 순서대로 진행' if not k else screen_map[k]['title'])
        screen['rubric']=st.text_area('교사·AI 참고 기준',value=screen.get('rubric',''),help='학생 화면에는 보이지 않는 평가·피드백 기준입니다.')
        save=st.form_submit_button('이 화면 저장',type='primary')
    if save:
        try:
            if check['kind']=='cards': check['answer']=json.loads(answer_text)
            elif check['kind']=='choice':
                index=int(answer_text)-1
                if not 0<=index<len(screen.get('options',[])): raise ActivityError('기준 답을 선택지 번호로 입력해 주세요.')
                check['answer']=str(index)
            elif check['kind']=='number': check['answer']=str(float(answer_text))
            else: check['answer']=answer_text
            screen['check']=check;lesson['screens'][idx]=screen
            svc.save_lesson(user,lesson,version);st.success('저장했어요.');st.rerun()
        except (ValueError,ActivityError) as e: st.error(f'기준 답이나 입력값을 확인해 주세요: {e}')
    with st.expander('이미지·PDF 학습지 넣기'):
        st.caption('PDF는 쪽마다 필기 가능한 활동 화면으로 추가됩니다. 현재 화면의 글은 먼저 저장하세요.')
        upload=st.file_uploader('학습지 PDF 또는 이미지',type=['pdf','png','jpg','jpeg','webp'],key=f'lesson_file_{lid}')
        if upload and st.button('자료를 활동에 추가',key=f'upload_{lid}'):
            try:
                raw=upload.getvalue()
                if upload.name.lower().endswith('.pdf'):
                    images=pdf_pages(raw)
                    if len(screens)+len(images)>40: raise ActivityError('전체 화면이 40개를 넘어요. PDF 쪽 수를 줄여 주세요.')
                    for i,image in enumerate(images):
                        a=svc.add_asset(user,image,f'{Path(upload.name).stem}_{i+1}.png','image/png')
                        page=screen_template('pdf',f'{Path(upload.name).stem} · {i+1}쪽')
                        page['assets']=[a['id']];page['prompt']='학습지 위에 풀이를 쓰고, 생각한 과정을 설명해 주세요.';screens.append(page)
                else:
                    a=svc.add_asset(user,raw,upload.name,upload.type or 'image/png')
                    lesson['screens'][idx]['assets']=[a['id']]
                svc.save_lesson(user,lesson,version);st.rerun()
            except ActivityError as e: st.error(str(e))
        if screen.get('assets') and st.button('이 화면 배경 자료 빼기',key=f'remove_bg_{sid}'):
            lesson['screens'][idx]['assets']=[];svc.save_lesson(user,lesson,version);st.rerun()
    st.caption('이미 배포한 수업에는 당시 버전이 유지됩니다. 편집 내용을 적용하려면 새 수업으로 배포하세요.')
    with st.expander('학생 화면 미리보기',expanded=False):
        preview_lesson=copy.deepcopy(mapping[lid]);s=preview_lesson['screens'][idx]
        preview={'id':'preview','class':'미리보기','role':'student','user_id':user['id'],'name':'미리보기','lesson':preview_lesson,
                 'paused':False,'global_locked':False,'status':'open','start':idx,'end':idx,'sync':False,'current':idx,
                 'anonymous':True,'gallery':False,'ai_enabled':False,'ai_available':False,'group':'','answers':[],
                 'boards':[],'shared':[],'snapshots':[],'version':version,'preview':True,
                 'assets':{aid:svc._asset_public(svc.data['act_assets'][aid]) for aid in s.get('assets',[])}}
        workspace(preview,key=f'preview_{lid}_{sid}_{version}')


def room_choice(user,svc,key):
    rooms=svc.rooms(user)
    if not rooms: st.info('아직 배포한 수업이 없어요.');return None
    mapping={r['id']:r for r in reversed(rooms)}
    return st.selectbox('수업 선택',list(mapping),format_func=lambda k:f"{mapping[k]['class']} · {mapping[k]['title']} · {mapping[k]['code']} ({'진행 중' if mapping[k]['status']=='open' else '마감'})",key=key)


def operate(user,svc):
    lessons=svc.lessons(user)
    if not lessons: st.info('먼저 수업을 만들어 주세요.');return
    with st.expander('반별로 새 수업 배포',expanded=not bool(svc.rooms(user))):
        with st.form('act_deploy'):
            lm={l['id']:l for l in lessons};lid=st.selectbox('배포할 수업',list(lm),format_func=lambda k:lm[k]['title'])
            cls=st.selectbox('대상 학급',CLASSES)
            ai=st.checkbox('이 수업에서 AI 피드백 허용',disabled=not svc.ai.available)
            if not svc.ai.available: st.caption('API 키를 설정하면 AI 피드백을 열 수 있어요. 기본 활동은 연결 없이 작동합니다.')
            if st.form_submit_button('수업 배포 · 참여 코드 만들기',type='primary'):
                room=svc.create_room(user,lid,cls,ai);st.success(f"참여 코드: {room['code']}");st.rerun()
    rid=room_choice(user,svc,'act_operate_room')
    if not rid:return
    state=svc.state(user,rid)
    st.info(f"학생 안내: 수학 액티비티 Lab → 참여 코드 **{state['code']}** 입력 · 소속 반 학생만 참여할 수 있어요.")
    cols=st.columns(4)
    if cols[0].button('▶ 활동 재개' if state['paused'] else '⏸ 전체 일시정지',type='primary',key=f'pause_{rid}'):
        svc.control(user,rid,paused=not state['paused']);st.rerun()
    if cols[1].button('자유 이동으로 전환' if state['sync'] else '현재 화면으로 모으기',key=f'sync_{rid}'):
        svc.control(user,rid,sync=not state['sync']);st.rerun()
    if cols[2].button('실명으로 공유' if state['anonymous'] else '익명으로 공유',key=f'anon_{rid}'):
        svc.control(user,rid,anonymous=not state['anonymous']);st.rerun()
    if cols[3].button('수업 다시 열기' if state['status']=='closed' else '수업 마감',key=f'close_{rid}'):
        svc.control(user,rid,status='open' if state['status']=='closed' else 'closed');db.flush_now();st.rerun()
    screens=state['lesson']['screens'];numbers=list(range(len(screens)));fmt=lambda i:f'{i+1}. {screens[i]["title"]}'
    with st.form(f'pace_{rid}_{state["version"]}'):
        cc=st.columns(3)
        start=cc[0].selectbox('열어둘 첫 화면',numbers,index=state['start'],format_func=fmt)
        end=cc[1].selectbox('열어둘 마지막 화면',numbers,index=state['end'],format_func=fmt)
        current=cc[2].selectbox('교사의 현재 화면',numbers,index=state['current'],format_func=fmt)
        gallery=st.checkbox('학생이 공개한 답안 갤러리 열기',value=state['gallery'])
        ai_enabled=st.checkbox('AI 피드백 열기',value=state['ai_enabled'],disabled=not svc.ai.available)
        if st.form_submit_button('화면 범위·공유 설정 적용'):
            if run(lambda:svc.control(user,rid,start=start,end=end,current=current,gallery=gallery,ai_enabled=ai_enabled)):st.rerun()
    with st.expander('모둠 배정'):
        members=state['members']
        if not members: st.caption('학생이 참여하면 모둠을 배정할 수 있어요.')
        else:
            groups=pd.DataFrame([{'학번':m['id'],'이름':m['name'],'모둠':m['group']} for m in members])
            edited=st.data_editor(groups,disabled=['학번','이름'],hide_index=True,key=f'groups_{rid}')
            c1,c2=st.columns(2)
            if c1.button('모둠 저장',key=f'save_groups_{rid}'):
                svc.control(user,rid,groups={str(r['학번']):str(r['모둠']).strip() for r in edited.to_dict('records')});st.rerun()
            size=c2.number_input('자동 배정 모둠 인원',2,8,4,key=f'group_size_{rid}')
            if c2.button('학번 순으로 자동 배정',key=f'auto_groups_{rid}'):
                svc.control(user,rid,groups={m['id']:f'{i//size+1}모둠' for i,m in enumerate(sorted(members,key=lambda m:m['id']))});st.rerun()
    live_monitor(user,rid)
    with st.expander('학생 답안 자세히 보기 · 피드백 · 공유',expanded=True):
        answer_review(user,svc,rid)
    snapshots=svc._room(user,rid)['snapshots']
    if snapshots:
        with st.expander('교사가 선택한 답안 · 발표 순서'):
            for i,sn in enumerate(snapshots):
                cols=st.columns([6,1,1,1]);cols[0].write(f"{i+1}. {sn['name']} · {sn['captured']}")
                if cols[1].button('↑',key=f'snup_{sn["id"]}',disabled=i==0):
                    ids=[x['id'] for x in snapshots];ids[i-1],ids[i]=ids[i],ids[i-1];svc.snapshots_set(user,rid,ids);st.rerun()
                if cols[2].button('↓',key=f'sndown_{sn["id"]}',disabled=i==len(snapshots)-1):
                    ids=[x['id'] for x in snapshots];ids[i+1],ids[i]=ids[i],ids[i+1];svc.snapshots_set(user,rid,ids);st.rerun()
                if cols[3].button('삭제',key=f'sndel_{sn["id"]}'):
                    svc.snapshots_set(user,rid,[x['id'] for x in snapshots if x['id']!=sn['id']]);st.rerun()
    st.caption(db.backend_status())


@st.fragment(run_every=1.5)
def live_monitor(user,rid):
    svc=service();state=svc.state(user,rid,include_assets=False);members=state['members'];answers=state['answers'];current=state['lesson']['screens'][state['current']]['id']
    cols=st.columns(4)
    cols[0].metric('수업 참여',f'{len(members)}명');cols[1].metric('최근 연결',f'{sum(m["online"] for m in members)}명')
    cols[2].metric('현재 화면 제출',f'{sum(a["submitted"] and a["screen"]==current for a in answers)}명')
    cols[3].metric('도움 요청',f'{len({a["student"] for a in answers if a["help"]})}명')
    screen_titles={s['id']:f'{i+1}. {s["title"]}' for i,s in enumerate(state['lesson']['screens'])}
    rows=[]
    for m in members:
        mine=[a for a in answers if a['student']==m['id']];active=next((a for a in mine if a['screen']==m['screen']),{})
        rows.append({'학생':f"{m['id']} {m['name']}",'연결':'접속 중' if m['online'] else '연결 확인 필요',
                     '현재 화면':screen_titles.get(m['screen'],'입장'),'제출':sum(a['submitted'] for a in mine),
                     '도움':'🙋' if any(a['help'] for a in mine) else '', '이해도':active.get('understanding',''),
                     '최근 반응':response_summary(active,state['lesson']['screens']),'모둠':m['group']})
    if rows: st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
    else: st.info('학생 참여를 기다리고 있어요.')
    counts={k:sum(a['screen']==current and a.get('understanding')==k for a in answers) for k in ('이해했어요','헷갈려요','다시 설명해주세요')}
    current_screen=next(s for s in state['lesson']['screens'] if s['id']==current)
    if current_screen['type']=='choice':
        votes={str(i):sum(a['screen']==current and str(a.get('response',{}).get('choice',''))==str(i) for a in answers) for i in range(len(current_screen.get('options',[])))}
        st.caption('선택 반응: '+' · '.join(f'{i+1}번 {votes[str(i)]}명' for i in range(len(votes))))
    st.caption('현재 화면 이해도: '+' · '.join(f'{k} {v}명' for k,v in counts.items())+' · 약 1.5초 간격으로 확인')


def answer_review(user,svc,rid):
    state=svc.state(user,rid)
    sid=st.selectbox('살펴볼 화면',[s['id'] for s in state['lesson']['screens']],format_func=lambda k:next(s['title'] for s in state['lesson']['screens'] if s['id']==k),key=f'review_screen_{rid}')
    members={m['id']:m for m in state['members']}
    student_ids=list(members)
    if not student_ids: return
    student_id=st.selectbox('학생',student_ids,format_func=lambda k:f"{k} · {members[k]['name']}",key=f'review_student_{rid}')
    answer=next((a for a in state['answers'] if a['student']==student_id and a['screen']==sid),None)
    if not answer: st.caption('이 화면에 아직 답안이 없어요.');return
    answer_preview(user,rid,sid,student_id)
    with st.form(f'fb_{answer["id"]}'):
        text=st.text_area('학생에게 남길 피드백',value=answer['teacher_feedback'])
        reviewed=st.checkbox('AI 제안을 교사가 확인함',value=answer.get('ai',{}).get('reviewed',False),disabled=not bool(answer.get('ai')))
        judgement=st.selectbox('교사 확인 결과',['판정 유지','조건 충족','보충 필요'])
        if st.form_submit_button('피드백 보내기',type='primary'):
            svc.feedback(user,rid,answer['id'],text,reviewed,None if judgement=='판정 유지' else judgement=='조건 충족');st.success('학생에게 전달했어요.')
    if st.button('이 답안을 전체 공유 목록에 추가',key=f'capture_{answer["id"]}',disabled=answer['scope']!='class'):
        svc.snapshot_add(user,rid,answer['id']);st.success('공유 목록에 추가했어요.');st.rerun()
    if answer['scope']!='class':st.caption('학생이 답안 공개 범위를 ‘우리 학급’으로 선택하면 전체 공유할 수 있어요.')


@st.fragment(run_every=1.5)
def answer_preview(user,rid,sid,student_id):
    svc=service();state=svc.state(user,rid,screen_id=sid,asset_student=student_id);state['answers']=[a for a in state['answers'] if a['student']==student_id]
    i=next(i for i,s in enumerate(state['lesson']['screens']) if s['id']==sid)
    state.update(start=i,end=i,current=i,sync=True,group=next((m['group'] for m in state['members'] if m['id']==student_id),''))
    workspace(state,key=f'answer_view_{rid}_{sid}_{student_id}')


def student(user,svc):
    with st.form('join_activity'):
        code=st.text_input('수업 참여 코드',max_chars=6,placeholder='선생님이 알려준 6자리 코드')
        if st.form_submit_button('수업 참여',type='primary'):
            result=run(lambda:svc.join(user,code))
            if result:st.session_state['act_student_room']=result;st.rerun()
    rooms=svc.rooms(user)
    if not rooms:st.info('선생님의 참여 코드를 입력해 주세요.');return
    mapping={r['id']:r for r in reversed(rooms)}
    if st.session_state.get('act_student_room') not in mapping:st.session_state['act_student_room']=next(iter(mapping))
    rid=st.selectbox('나의 수업',list(mapping),format_func=lambda k:mapping[k]['title']+(' · 마감' if mapping[k]['status']=='closed' else ''),key='act_student_room')
    student_workspace(user,rid)
    with st.expander('나의 학습 과정 내려받기'):
        history=svc.history(user,rid)
        st.download_button('처음 생각·제출·교사 피드백 기록 JSON',json.dumps(history,ensure_ascii=False,indent=2).encode(),'my_learning_history.json','application/json')


@st.fragment(run_every=1.5)
def student_workspace(user,rid):
    svc=service();key=f'student_workspace_{rid}_{user["id"]}'
    # Resolve the identity from server-side accounts on every fragment and callback.
    current=auth.get_user(user['id'])
    if not current or current['role']!='student':st.error('로그인을 다시 해 주세요.');return
    svc.touch(current,rid)
    def on_event():
        fresh=auth.get_user(user['id'])
        if not fresh or fresh['role']!='student':return
        value=st.session_state.get(key,{})
        event=value.get('event')
        if event:
            try: result=svc.handle(fresh,rid,event)
            except Exception: result={'id':event.get('id'),'ok':False,'error':'처리하지 못했어요. 연결을 확인하고 다시 시도해 주세요.'}
            st.session_state[key+'_receipt']=result
    state=svc.state(current,rid)
    state['receipt']=st.session_state.get(key+'_receipt')
    workspace(state,key=key,on_event=on_event)


def records(user,svc):
    rid=room_choice(user,svc,'act_records_room')
    if not rid:return
    export=svc.export(user,rid);answers=export['answers'];members=export['room']['members'];screens={s['id']:s for s in export['room']['lesson']['screens']}
    rows=[]
    for a in answers:
        first=next((h['content'] for h in export['history'] if h['kind']=='first' and h['student']==a['student'] and h['screen']==a['screen']),{})
        rows.append({'학번':a['student'],'이름':a['name'],'화면':screens[a['screen']]['title'],'처음 생각':first.get('text',''),
                     '현재 생각':a['response'].get('text',''),'제출':'제출' if a['submitted'] else '작성 중','수정 저장 횟수':a['version'],
                     '이해도':a['understanding'],'교사 피드백':a['teacher_feedback'],'AI 제안':a.get('ai',{}).get('text',''),
                     'AI 교사 확인':'확인' if a.get('ai',{}).get('reviewed') else '미확인','최종 저장(UTC)':a['updated']})
    if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
    else:st.info('학생 답안이 저장되면 기록이 나타나요.')
    data=json.dumps(export,ensure_ascii=False,indent=2).encode()
    c1,c2=st.columns(2)
    c1.download_button('전체 학습 기록 JSON',data,f'activity_{rid[:8]}.json','application/json')
    if rows:
        # Prevent spreadsheet formula injection in user-authored values.
        safe=[{k:("'"+str(v) if str(v).lstrip().startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()} for row in rows]
        csvbytes=pd.DataFrame(safe).to_csv(index=False).encode('utf-8-sig')
        c2.download_button('교사 검토용 기록 CSV',csvbytes,f'activity_{rid[:8]}.csv','text/csv')
    if st.button('필기·음성을 포함한 전체 기록 ZIP 만들기',key=f'export_zip_{rid}'):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('learning_records.json',data)
            ids={aid for s in screens.values() for aid in s.get('assets',[])}
            for a in answers:
                ids.update(a.get('attachments',[]))
                if a['response'].get('strokes'):
                    screen=screens[a['screen']];bg=None
                    if screen.get('assets'):
                        asset=svc.data['act_assets'][screen['assets'][0]];bg=svc.backend.load_file(asset['file_id'])
                    z.writestr(f"drawings/{a['student']}_{a['screen']}.png",render_strokes(a['response'],bg))
            for aid in ids:
                asset=svc.data['act_assets'].get(aid)
                if not asset:continue
                raw=svc.backend.load_file(asset['file_id'])
                if raw:z.writestr(f"attachments/{aid}_{asset['name']}",raw)
        st.session_state[f'export_zip_{rid}_bytes']=out.getvalue()
    if st.session_state.get(f'export_zip_{rid}_bytes'):
        st.download_button('완성된 기록 ZIP 다운로드',st.session_state[f'export_zip_{rid}_bytes'],f'activity_records_{rid[:8]}.zip','application/zip')
    st.caption('처음 답안·수정 후 제출·교사 피드백을 근거로 확인하는 기록입니다. 자동으로 생활기록부에 입력되지는 않습니다.')


def presentation(user,svc):
    rid=room_choice(user,svc,'act_present_room')
    if not rid:return
    st.caption('선택한 답안과 공개한 생각만 표시합니다. 학생 명단과 개인 피드백은 이 화면에 표시되지 않습니다.')
    present_live(user,rid)

@st.fragment(run_every=1.5)
def present_live(user,rid):
    state=service().state(user,rid)
    state.update(presentation=True,answers=[],boards=[],user_id='',name='')
    state.pop('members',None)
    workspace(state,key=f'presentation_{rid}')


def response_summary(answer,screens):
    res=answer.get('response',{})
    if res.get('text'):return res['text'][:100]
    screen=next((s for s in screens if s['id']==answer.get('screen')), {})
    if res.get('choice') is not None:
        try:return '선택: '+screen['options'][int(res['choice'])]
        except (KeyError,ValueError,IndexError):return '선택 중'
    if res.get('placements'):return f"카드 {len(res['placements'])}개 분류"
    if res.get('strokes'):return f"필기 {len(res['strokes'])}획 작성"
    if res.get('expression'):return '그래프: '+str(res['expression'])[:80]
    if res.get('table'):return f"좌표 {len(res['table'])}행"
    return ''
