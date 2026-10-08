import base64
import copy
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from activity_lab.core import ActivityService, ActivityError, Conflict, sample_lesson, screen_template, uid
from activity_lab.media import pdf_pages

TEACHER={'id':'teacher','role':'teacher','name':'교사','class':''}
OTHER_TEACHER={'id':'other','role':'teacher','name':'다른 교사','class':''}
def student(i=1,cls='1-1'):return {'id':f'101{i:02}','role':'student','name':f'학생{i}','class':cls}

class MemoryBackend:
    def __init__(self):self.rows={};self.files={}
    def read(self,t):return copy.deepcopy(list(self.rows.get(t,{}).values()))
    def append(self,t,r):self.rows.setdefault(t,{})[r['id']]=copy.deepcopy(r)
    def update(self,t,k,r):self.rows[t][k].update(copy.deepcopy(r));return True
    def save_file(self,data,name,mime,public):
        k=uid();self.files[k]=data;return k,''
    def load_file(self,k):return self.files.get(k)

@pytest.fixture
def env():
    b=MemoryBackend();s=ActivityService(b);l=s.save_lesson(TEACHER,sample_lesson());r=s.create_room(TEACHER,l['id'],'1-1')
    s.join(student(),r['code']);return s,l,r,b

def test_author_version_and_deploy_snapshot(env):
    s,l,r,b=env;l['title']='새 제목';s.save_lesson(TEACHER,l,l['version'])
    assert s.state(student(),r['id'])['lesson']['title']!='새 제목'
    with pytest.raises(Conflict):s.save_lesson(TEACHER,l,l['version'])
    with pytest.raises(ActivityError):s.save_lesson(student(),l)
    with pytest.raises(ActivityError):s.create_room(OTHER_TEACHER,l['id'],'1-1')

def test_class_membership_and_private_answers(env):
    s,l,r,b=env
    with pytest.raises(ActivityError):s.join(student(2,'1-2'),r['code'])
    with pytest.raises(ActivityError):s.state(student(2),r['id'])
    sid=l['screens'][0]['id'];s.save_answer(student(),r['id'],sid,{'choice':'1','text':'이유'},0)
    s.join(student(2),r['code']);out=s.state(student(2),r['id'])
    assert out['answers']==[] and out['shared']==[]
    assert all('check' not in x and 'rubric' not in x for x in out['lesson']['screens'])
    with pytest.raises(ActivityError):s.control(student(),r['id'],paused=True)
    with pytest.raises(ActivityError):s.state(OTHER_TEACHER,r['id'])

def test_pause_pace_sync_close_are_server_enforced(env):
    s,l,r,b=env;sid=l['screens'][0]['id'];rid=r['id']
    s.control(TEACHER,rid,paused=True)
    for f in (lambda:s.save_answer(student(),rid,sid,{},0),lambda:s.signal(student(),rid,sid,True)):
        with pytest.raises(ActivityError):f()
    s.control(TEACHER,rid,paused=False,start=1,end=2,current=1)
    with pytest.raises(ActivityError):s.save_answer(student(),rid,sid,{},0)
    s.control(TEACHER,rid,sync=True)
    with pytest.raises(ActivityError):s.save_answer(student(),rid,l['screens'][2]['id'],{},0)
    s.save_answer(student(),rid,l['screens'][1]['id'],{'text':'허용'},0)
    s.control(TEACHER,rid,status='closed')
    with pytest.raises(ActivityError):s.save_answer(student(),rid,l['screens'][1]['id'],{},1)
    assert len(s.state(student(),rid)['answers'])==1

def test_global_lock_applies_to_stale_clients(env):
    s,l,r,b=env;s.global_lock=lambda c:True
    with pytest.raises(ActivityError):s.save_answer(student(),r['id'],l['screens'][0]['id'],{},0)

def test_revision_conflict_and_idempotent_retry(env):
    s,l,r,b=env;sid=l['screens'][0]['id']
    event={'id':uid(),'kind':'answer','screen':sid,'response':{'choice':'1'},'version':0,'submit':True}
    one=s.handle(student(),r['id'],event);two=s.handle(student(),r['id'],event)
    assert one==two and one['answer']['version']==1
    assert one['answer']['check']['correct'] is True
    with pytest.raises(Conflict):s.save_answer(student(),r['id'],sid,{'choice':'0'},0)
    s.save_answer(student(),r['id'],sid,{'choice':'0'},1,True)
    h=s.history(student(),r['id']);assert [x['kind'] for x in h]==['first','submit','submit']
    assert h[0]['content']['choice']=='1'

def test_concurrent_25_students_no_lost_updates(env):
    s,l,r,b=env;sid=l['screens'][0]['id'];rid=r['id']
    for i in range(2,26):s.join(student(i),r['code'])
    def act(i):
        a=s.save_answer(student(i),rid,sid,{'text':f'처음{i}','choice':'0'},0)
        return s.save_answer(student(i),rid,sid,{'text':f'수정{i}','choice':'1'},a['version'],True)
    with ThreadPoolExecutor(max_workers=25) as pool:answers=list(pool.map(act,range(1,26)))
    assert len(s.state(TEACHER,rid)['answers'])==25
    assert all(a['version']==2 and a['submitted'] and a['check']['correct'] for a in answers)
    assert len(s.history(TEACHER,rid))==50

def test_group_merge_ownership_and_visibility(env):
    s,l,r,b=env;rid=r['id'];sid=l['screens'][3]['id']
    for i in [2,3]:s.join(student(i),r['code'])
    s.control(TEACHER,rid,groups={student()['id']:'A',student(2)['id']:'A',student(3)['id']:'B'})
    def post(i):return s.board_patch(student(i),rid,sid,{'op':'add','id':f'n{i}','value':{'text':str(i)}})
    with ThreadPoolExecutor(2) as pool:list(pool.map(post,[1,2]))
    a=s.state(student(),rid)['boards'];assert len(a)==1 and len(a[0]['items'])==2
    assert not s.state(student(3),rid)['boards']
    with pytest.raises(ActivityError):s.board_patch(student(2),rid,sid,{'op':'remove','id':'n1'})
    s.board_patch(student(),rid,sid,{'op':'remove','id':'n1'})
    assert len(s.state(student(2),rid)['boards'][0]['items'])==1

def test_snapshot_consent_anonymity_revocation_and_order(env):
    s,l,r,b=env;sid=l['screens'][0]['id'];rid=r['id']
    a=s.save_answer(student(),rid,sid,{'text':'이 생각'},0)
    with pytest.raises(ActivityError):s.snapshot_add(TEACHER,rid,a['id'])
    a=s.save_answer(student(),rid,sid,{'text':'이 생각'},1,scope='class')
    s.snapshot_add(TEACHER,rid,a['id']);s.snapshot_add(TEACHER,rid,a['id'])
    assert s.state(student(),rid)['snapshots'][0]['name']=='익명'
    assert 'student' not in s.state(student(),rid)['snapshots'][0]
    ids=[x['id'] for x in s._room(TEACHER,rid)['snapshots']][::-1];s.snapshots_set(TEACHER,rid,ids)
    assert [x['id'] for x in s.state(student(),rid)['snapshots']]==ids
    s.save_answer(student(),rid,sid,{'text':'비공개'},2,scope='private')
    assert not s.state(student(),rid)['snapshots']

def test_feedback_and_branching(env):
    s,l,r,b=env;sid=l['screens'][0]['id'];l['screens'][0]['next_correct']=l['screens'][1]['id'];l=s.save_lesson(TEACHER,l,l['version']);r=s.create_room(TEACHER,l['id'],'1-1');s.join(student(),r['code'])
    a=s.save_answer(student(),r['id'],sid,{'choice':'1'},0,True)
    assert a['check']['next']==l['screens'][1]['id']
    s.signal(student(),r['id'],sid,True,'헷갈려요');s.feedback(TEACHER,r['id'],a['id'],'이유도 써보세요.',correct=False)
    out=s.state(student(),r['id'])['answers'][0];assert out['teacher_feedback'] and not out['help']

def test_upload_private_and_invalid_types(env):
    s,l,r,b=env;sid=l['screens'][3]['id'];rid=r['id']
    image=io.BytesIO();Image.new('RGB',(40,40),'red').save(image,'PNG')
    a=s.add_asset(student(),image.getvalue(),'풀이.png','image/png','answer',rid,sid)
    s.join(student(2),r['code']);s.touch(student(),rid,sid)
    assert a['id'] in s.state(student(),rid)['assets']
    assert a['id'] not in s.state(student(2),rid,screen_id=sid)['assets']
    assert a['id'] in s.state(TEACHER,rid,screen_id=sid,asset_student=student()['id'])['assets']
    with pytest.raises(ActivityError):s.add_asset(student(),b'<script>evil</script>','x.svg','image/svg+xml','answer',rid,sid)
    with pytest.raises(ActivityError):s.add_asset(student(),b'anything','x.jpg','image/jpeg','lesson')

def test_restart_preserves_records_and_large_drawing(tmp_path):
    from storage import LocalBackend
    b=LocalBackend(str(tmp_path));s=ActivityService(b);l=s.save_lesson(TEACHER,sample_lesson());r=s.create_room(TEACHER,l['id'],'1-1');s.join(student(),r['code']);sid=l['screens'][3]['id']
    res={'text':'첫 답','strokes':[{'points':[[.12345,.54321]]*4000,'color':'#000000','width':3} for _ in range(3)]}
    s.save_answer(student(),r['id'],sid,res,0,True);s.control(TEACHER,r['id'],paused=True)
    restored=ActivityService(LocalBackend(str(tmp_path)))
    out=restored.state(student(),r['id']);assert out['paused'] and out['answers'][0]['response']==res

def test_pdf_multi_page_and_limit():
    import fitz
    d=fitz.open();d.new_page();d.new_page();assert len(pdf_pages(d.tobytes()))==2
    for _ in range(19):d.new_page()
    with pytest.raises(ActivityError):pdf_pages(d.tobytes())

def test_ai_disabled_and_fresh_results(env):
    s,l,r,b=env;sid=l['screens'][0]['id'];rid=r['id']
    s.save_answer(student(),rid,sid,{'text':'풀이'},0)
    with pytest.raises(ActivityError):s.ai_request(student(),rid,sid,True)
    class FakeAI:
        available=True
        def analyze(self,*a):return {'text':'근거를 확인해보세요.','needs_teacher':True}
    s.ai=FakeAI();s.control(TEACHER,rid,ai_enabled=True)
    with pytest.raises(ActivityError):s.ai_request(student(),rid,sid,False)
    s.ai_request(student(),rid,sid,True)
    for _ in range(100):
        a=s.state(student(),rid)['answers'][0]
        if a['ai'].get('status')=='done':break
        time.sleep(.01)
    assert a['ai']['status']=='done' and a['help'] and not a['ai']['reviewed']
    s.feedback(TEACHER,rid,a['id'],'교사 검토',True)
    assert s.state(student(),rid)['answers'][0]['ai']['reviewed']

def test_ai_old_result_does_not_replace_new_answer(env):
    s,l,r,b=env;sid=l['screens'][0]['id'];rid=r['id'];gate=threading.Event()
    class SlowAI:
        available=True
        def analyze(self,*a):gate.wait(2);return {'text':'old result','needs_teacher':False}
    s.ai=SlowAI();s.control(TEACHER,rid,ai_enabled=True);s.save_answer(student(),rid,sid,{'text':'처음'},0)
    s.ai_request(student(),rid,sid,True);s.save_answer(student(),rid,sid,{'text':'수정'},1);gate.set();time.sleep(.04)
    assert s.state(student(),rid)['answers'][0]['ai']=={}

def test_git_partition_and_csv_round_trip():
    from storage import GitHubBackend
    assert GitHubBackend._path('act_history',{'id':'h','room_id':'room123'})=='activity-lab/data/act_history/room123.csv'
    assert GitHubBackend._path('users',{'id':'10101'})=='activity-lab/data/users.csv'

def test_ai_metadata_save_does_not_leave_pending_forever(env):
    s,l,r,b=env;sid=l['screens'][0]['id'];rid=r['id'];gate=threading.Event()
    class SlowAI:
        available=True
        def analyze(self,*a):gate.wait(2);return {'text':'metadata-safe','needs_teacher':False}
    s.ai=SlowAI();s.control(TEACHER,rid,ai_enabled=True);s.save_answer(student(),rid,sid,{'text':'풀이'},0)
    s.ai_request(student(),rid,sid,True)
    s.save_answer(student(),rid,sid,{'text':'풀이'},1,scope='class')
    gate.set()
    for _ in range(100):
        a=s.state(student(),rid)['answers'][0]
        if a['ai'].get('status')=='done':break
        time.sleep(.01)
    assert a['ai']['status']=='done' and a['ai']['version']==2

def test_portrait_pdf_export_preserves_aspect():
    from activity_lab.media import render_strokes
    bg=io.BytesIO();Image.new('RGB',(400,600),'white').save(bg,'PNG')
    result=Image.open(io.BytesIO(render_strokes({'strokes':[{'points':[[0,0],[1,1]],'color':'#000000','width':3}]},bg.getvalue())))
    assert result.size==(400,600)

def test_invalid_strokes_are_rejected(env):
    s,l,r,b=env;sid=l['screens'][3]['id']
    for bad in [{'strokes':'not-a-list'},{'strokes':[{'points':[[float('nan'),0]]}]},{'strokes':[{'points':[[0,0]],'color':'url(evil)'}]}]:
        with pytest.raises(ActivityError):s.save_answer(student(),r['id'],sid,bad,0)

def test_closed_activity_allows_review_outside_old_pacing(env):
    s,l,r,b=env;rid=r['id'];sid=l['screens'][4]['id']
    s.control(TEACHER,rid,start=0,end=0,current=0,sync=True,status='closed')
    reply=s.handle(student(),rid,{'id':uid(),'kind':'navigate','screen':sid})
    assert reply['ok']
    assert s.state(TEACHER,rid)['members'][0]['screen']==sid
