"""Authenticated activity domain; one shared service per Streamlit process.

No browser-supplied identity is trusted. All mutations, including autosaves,
check membership, pause, pacing, revision and sharing on the server.
"""
from __future__ import annotations
import base64
import copy
import csv
import io
import json
import math
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from functools import wraps

TABLES = ('act_lessons', 'act_rooms', 'act_answers', 'act_history', 'act_boards', 'act_assets')
TYPES = ('text', 'choice', 'graph', 'cards', 'table', 'drawing', 'pdf')
SCOPES = ('private', 'group', 'class')

def uid(): return uuid.uuid4().hex

def clone(value): return copy.deepcopy(value)

def stamp(): return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

class ActivityError(ValueError): pass

class Conflict(ActivityError): pass

def locked(fn):
    @wraps(fn)
    def wrapped(self, *a, **k):
        with self.lock:
            return fn(self, *a, **k)
    return wrapped

def limited(value, size=12000):
    value = str(value or '')
    if len(value) > size: raise ActivityError(f'입력이 너무 깁니다. {size}자 이내로 줄여 주세요.')
    return value


def screen_template(kind='text', title='새 활동'):
    return {'id': uid(), 'type': kind, 'title': title, 'prompt': '', 'hint': '',
            'options': ['선택 1', '선택 2'], 'cards': ['y=x', 'y=2x', 'y=x²'],
            'categories': ['일차함수', '이차함수'], 'expression': 'y=a*x+b',
            'params': {'a': 1, 'b': 0, 'c': 1}, 'table': [['0', '0'], ['1', '1'], ['2', '2']],
            'assets': [], 'group_work': False, 'rubric': '',
            'check': {'kind': 'manual', 'answer': '', 'tolerance': 0.001,
                      'success': '조건을 만족했어요. 왜 그런지 설명해볼까요?',
                      'retry': '조건을 다시 살펴보고 수정해보세요.'},
            'next_correct': '', 'next_incorrect': ''}


def sample_lesson():
    s1 = screen_template('choice', '01 · 먼저 예상해요')
    s1.update(prompt='y=ax+b에서 a가 커지면 그래프는 어떻게 달라질까요?',
              options=['항상 위로 평행이동한다', '기울기가 달라진다', '항상 원이 된다'],
              hint='x가 1만큼 늘 때 y가 얼마나 변하는지 생각해보세요.')
    s1['check'].update(kind='choice', answer='1')
    s2 = screen_template('graph', '02 · 움직이며 확인해요')
    s2.update(prompt='a와 b를 바꾸어 보고, 기울기와 절편의 역할을 설명하세요.',
              rubric='a와 기울기, b와 y절편의 관계를 자신의 말로 설명한다.')
    s3 = screen_template('cards', '03 · 같은 성질끼리 묶어요')
    s3.update(prompt='함수식을 알맞은 상자에 분류하고 근거를 적으세요.',
              cards=['y=2x+1', 'y=-x', 'y=x²', 'y=3x²+2'])
    s3['check'].update(kind='cards', answer={'0': '일차함수','1': '일차함수','2': '이차함수','3': '이차함수'})
    s4 = screen_template('drawing', '04 · 모둠의 생각을 모아요')
    s4.update(prompt='기울기가 같은 두 직선을 그리고, 두 직선의 관계를 함께 설명하세요.',group_work=True)
    s5 = screen_template('text', '05 · 나의 생각을 돌아봐요')
    s5.update(prompt='처음 생각과 달라진 점, 아직 궁금한 점을 각각 한 문장으로 적으세요.')
    return {'title':'함수, 움직이며 발견하기','subject':'공통수학2','screens':[s1,s2,s3,s4,s5]}


class ActivityService:
    def __init__(self, backend, ai=None, global_lock=None, clock=time.time):
        self.backend, self.ai = backend, ai
        self.clock = clock
        self.global_lock = global_lock or (lambda cls: False)
        self.lock = threading.RLock()
        self.data = {t: {} for t in TABLES}
        self.presence, self.receipts, self.rate = {}, {}, {}
        self.asset_cache = OrderedDict()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='activity-ai')
        for t in TABLES:
            for row in backend.read(t):
                try: self.data[t][row['id']] = json.loads(row['payload'])
                except (ValueError, KeyError): raise ActivityError(f'{t} 기록을 읽지 못했습니다. 데이터 파일을 확인해 주세요.')
        for a in self.data['act_answers'].values():
            if a.get('ai', {}).get('status') == 'pending':
                a['ai'] = {'status':'error','text':'서버가 재시작되어 분석이 중단됐어요. 다시 요청해 주세요.'}
                self._save('act_answers', a)

    def _save(self, table, item):
        row = {'id': item['id'], 'room_id': item.get('room', item['id'] if table=='act_rooms' else ''), 'payload': json.dumps(item, ensure_ascii=False, allow_nan=False)}
        if item['id'] in self.data[table]: self.backend.update(table, item['id'], row)
        else: self.backend.append(table, row)
        self.data[table][item['id']] = clone(item)

    def _teacher(self, u):
        if u.get('role') != 'teacher': raise ActivityError('교사만 사용할 수 있어요.')

    def _owned(self, u, table, key):
        self._teacher(u)
        obj = self.data[table].get(key)
        if not obj or obj['owner'] != u['id']: raise ActivityError('접근할 수 없는 자료예요.')
        return clone(obj)

    def _room(self, u, rid):
        r = self.data['act_rooms'].get(rid)
        if not r: raise ActivityError('수업을 찾을 수 없어요.')
        if u.get('role') == 'teacher':
            if u['id'] != r['owner']: raise ActivityError('담당 교사만 열 수 있어요.')
        elif u.get('role') != 'student' or u.get('class') != r['class'] or u['id'] not in r['members']:
            raise ActivityError('이 수업에 참여할 권한이 없어요.')
        return clone(r)

    def _screen(self, r, sid):
        for i, s in enumerate(r['lesson']['screens']):
            if s['id'] == sid: return i, s
        raise ActivityError('활동 화면을 찾을 수 없어요.')

    def _writable(self, u, r, sid=None):
        if u.get('role') != 'student': raise ActivityError('학생 답안 기능이에요.')
        if r['status'] != 'open': raise ActivityError('마감된 수업이에요.')
        if r['paused'] or self.global_lock(r['class']): raise ActivityError('선생님 설명 시간이에요. 잠금이 풀리면 다시 저장해 주세요.')
        if sid is not None:
            i, _ = self._screen(r, sid)
            if not r['start'] <= i <= r['end'] or (r['sync'] and i != r['current']):
                raise ActivityError('선생님이 열어 둔 화면에서 활동해 주세요.')

    def _history(self, r, u, sid, kind, content):
        e = {'id':uid(),'room':r['id'],'student':u['id'],'screen':sid,
             'kind':kind,'at':stamp(),'content':clone(content)}
        self._save('act_history',e)

    @locked
    def lessons(self, u):
        self._teacher(u)
        return [clone(x) for x in self.data['act_lessons'].values() if x['owner']==u['id']]

    @locked
    def save_lesson(self, u, lesson, expected=None):
        self._teacher(u)
        x = clone(lesson)
        if x.get('id'):
            old = self._owned(u,'act_lessons',x['id'])
            if expected != old['version']: raise Conflict('다른 창에서 수업이 변경됐어요. 다시 불러와 주세요.')
        else: old = {'version':0}; x['id']=uid()
        x['title'] = limited(x.get('title'),120).strip()
        if not x['title']: raise ActivityError('수업 제목을 입력해 주세요.')
        x['subject'] = limited(x.get('subject'),100)
        screens = x.get('screens',[])
        if not 1 <= len(screens) <= 40: raise ActivityError('활동 화면은 1~40개로 구성해 주세요.')
        ids=set()
        for s in screens:
            if s.get('type') not in TYPES: raise ActivityError('지원하지 않는 활동 종류예요.')
            if not s.get('id') or s['id'] in ids: raise ActivityError('화면 ID가 중복됐어요.')
            ids.add(s['id'])
            for k in ('title','prompt','hint','rubric'): s[k]=limited(s.get(k))
            if s.get('check',{}).get('kind') not in ('manual','exact','number','choice','cards'):
                raise ActivityError('정답 확인 방법이 잘못됐어요.')
            for aid in s.get('assets',[]):
                a=self.data['act_assets'].get(aid)
                if not a or a['owner']!=u['id'] or a.get('purpose')!='lesson': raise ActivityError('사용할 수 없는 첨부 자료예요.')
            if len(s.get('cards',[]))>30 or len(s.get('options',[]))>12: raise ActivityError('카드 30개, 선택지 12개 이내로 입력해 주세요.')
        for s in screens:
            for k in ('next_correct','next_incorrect'):
                if s.get(k) and s[k] not in ids: raise ActivityError('수준별 다음 화면을 다시 지정해 주세요.')
        if len(json.dumps(x))>500000: raise ActivityError('수업 내용이 너무 커요.')
        x.update(owner=u['id'],version=old['version']+1,updated=stamp())
        self._save('act_lessons',x)
        return clone(x)

    @locked
    def create_room(self, u, lesson_id, cls, ai_enabled=False):
        lesson=self._owned(u,'act_lessons',lesson_id)
        if cls not in [f'1-{i}' for i in range(1,8)]: raise ActivityError('학급을 확인해 주세요.')
        codes={r['code'] for r in self.data['act_rooms'].values()}
        code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
        while code in codes: code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
        r={'id':uid(),'owner':u['id'],'class':cls,'code':code,'lesson':lesson,'status':'open',
           'paused':False,'start':0,'end':len(lesson['screens'])-1,'sync':False,'current':0,
           'anonymous':True,'gallery':False,'ai_enabled':bool(ai_enabled),'members':{},
           'groups':{},'snapshots':[],'created':stamp(),'version':1}
        self._save('act_rooms',r)
        return clone(r)

    @locked
    def rooms(self, u):
        return [self._room_summary(r) for r in self.data['act_rooms'].values()
                if (u.get('role')=='teacher' and r['owner']==u['id']) or
                   (u.get('role')=='student' and u['id'] in r['members'] and u.get('class')==r['class'])]

    def _room_summary(self,r):
        return {k:r[k] for k in ('id','class','code','status','created')} | {'title':r['lesson']['title']}

    @locked
    def join(self,u,code):
        if u.get('role')!='student': raise ActivityError('학생 계정으로 참여해 주세요.')
        r=next((clone(r) for r in self.data['act_rooms'].values() if r['code']==str(code).strip().upper()),None)
        if not r or r['class']!=u.get('class'): raise ActivityError('참여 코드 또는 소속 학급을 확인해 주세요.')
        if r['status']!='open' and u['id'] not in r['members']: raise ActivityError('마감된 수업이에요.')
        if u['id'] not in r['members']:
            r['members'][u['id']]={'name':u['name'],'joined':stamp()}
            self._save('act_rooms',r)
        return r['id']

    @locked
    def control(self,u,rid,**changes):
        r=self._owned(u,'act_rooms',rid)
        allowed={'paused','start','end','sync','current','anonymous','gallery','ai_enabled','status','groups'}
        if set(changes)-allowed: raise ActivityError('지원하지 않는 수업 설정이에요.')
        r.update(clone(changes))
        n=len(r['lesson']['screens'])
        if not 0<=r['start']<=r['current']<=r['end']<n: raise ActivityError('진행 범위와 현재 화면을 확인해 주세요.')
        if r['status'] not in ('open','closed'): raise ActivityError('수업 상태를 확인해 주세요.')
        for k in ('paused','sync','anonymous','gallery','ai_enabled'):
            if not isinstance(r[k],bool): raise ActivityError('설정 형식이 잘못됐어요.')
        if set(r['groups'])-set(r['members']): raise ActivityError('참여한 학생만 모둠에 배정할 수 있어요.')
        r['groups']={k:limited(v,30) for k,v in r['groups'].items()}
        r['version']+=1
        self._save('act_rooms',r)
        return clone(r)

    def _answer_id(self,rid,sid,student): return f'{rid}:{sid}:{student}'

    def _empty_answer(self,u,r,sid):
        return {'id':self._answer_id(r['id'],sid,u['id']),'room':r['id'],'screen':sid,'student':u['id'],
                'name':u['name'],'response':{},'version':0,'submitted':False,'scope':'private',
                'understanding':'','help':False,'teacher_feedback':'','ai':{},'check':{},'updated':''}

    def _validate_response(self,res):
        if not isinstance(res,dict): raise ActivityError('답안 형식이 잘못됐어요.')
        allowed={'text','choice','placements','expression','params','table','strokes','point','reflection'}
        if set(res)-allowed: raise ActivityError('허용하지 않는 답안 항목이에요.')
        try: size=len(json.dumps(res,allow_nan=False))
        except (TypeError,ValueError): raise ActivityError('답안에 잘못된 값이 있어요.')
        if size>350000: raise ActivityError('풀이가 너무 커요. 화면을 나누어 작성해 주세요.')
        for k in ('text','reflection','expression'):
            if k in res and not isinstance(res[k],str): raise ActivityError('문자 입력 형식을 확인해 주세요.')
        for k in ('placements','params'):
            if k in res and not isinstance(res[k],dict): raise ActivityError('값 형식을 확인해 주세요.')
        if 'table' in res:
            if not isinstance(res['table'],list) or len(res['table'])>30 or any(not isinstance(row,list) or len(row)!=2 for row in res['table']):
                raise ActivityError('좌표표는 x, y 두 열과 30행 이내로 작성해 주세요.')
        strokes=res.get('strokes',[])
        if not isinstance(strokes,list) or len(strokes)>600: raise ActivityError('필기 획 수가 많거나 형식이 잘못됐어요.')
        import re
        for stroke in strokes:
            if not isinstance(stroke,dict) or not isinstance(stroke.get('points'),list) or len(stroke['points'])>5000:
                raise ActivityError('필기 형식이 잘못됐어요.')
            if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(stroke.get('color','#20334b'))): raise ActivityError('필기 색상을 확인해 주세요.')
            if not isinstance(stroke.get('width',3),(float,int)) or not 1<=stroke.get('width',3)<=12: raise ActivityError('펜 굵기를 확인해 주세요.')
            for point in stroke['points']:
                if not isinstance(point,list) or len(point)!=2 or any(not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<=n<=1 for n in point):
                    raise ActivityError('필기 좌표를 확인해 주세요.')
        return clone(res)

    def _check(self,s,res):
        c=s.get('check',{}); mode=c.get('kind','manual'); target=c.get('answer',''); result=None
        if mode=='choice': result=str(res.get('choice',''))==str(target)
        elif mode=='exact': result=str(res.get('text','')).strip()==str(target).strip()
        elif mode=='number':
            try:
                value=float(str(res.get('text','')).strip())
                result=math.isfinite(value) and math.isclose(value,float(target),rel_tol=0,abs_tol=float(c.get('tolerance',.001)))
            except (ValueError,TypeError): result=False
        elif mode=='cards': result=res.get('placements',{})==target
        return {'correct':result,'text':('선생님이 풀이를 확인할 예정이에요.' if result is None else c.get('success' if result else 'retry','')),
                'next':s.get('next_correct' if result else 'next_incorrect','') if result is not None else ''}

    @locked
    def save_answer(self,u,rid,sid,response,expected,submit=False,scope=None):
        r=self._room(u,rid); self._writable(u,r,sid); _,s=self._screen(r,sid)
        key=self._answer_id(rid,sid,u['id']); a=clone(self.data['act_answers'].get(key) or self._empty_answer(u,r,sid))
        if expected!=a['version']: raise Conflict('다른 창에서 수정한 답안이 있어요. 최신 답안을 불러온 뒤 다시 저장해 주세요.')
        clean=self._validate_response(response)
        if scope is not None:
            if scope not in SCOPES: raise ActivityError('공유 범위를 확인해 주세요.')
            if scope=='group' and not r['groups'].get(u['id']): raise ActivityError('모둠에 배정된 뒤 모둠 공유를 선택해 주세요.')
            a['scope']=scope
        if not a['version']: self._history(r,u,sid,'first',clean)
        changed=a['response']!=clean
        if changed:
            a['ai']={}; a['check']={}; a['submitted']=False
        a.update(response=clean,version=a['version']+1,updated=stamp())
        if submit:
            a.update(submitted=True,check=self._check(s,clean))
            self._history(r,u,sid,'submit',{'response':clean,'check':a['check'],'version':a['version']})
        self._save('act_answers',a)
        return clone(a)

    @locked
    def signal(self,u,rid,sid,help_value=None,understanding=None):
        r=self._room(u,rid); self._writable(u,r,sid)
        key=self._answer_id(rid,sid,u['id']); a=clone(self.data['act_answers'].get(key) or self._empty_answer(u,r,sid))
        if help_value is not None: a['help']=bool(help_value)
        if understanding is not None:
            if understanding not in ('이해했어요','헷갈려요','다시 설명해주세요',''): raise ActivityError('이해도 선택을 확인해 주세요.')
            a['understanding']=understanding
        self._save('act_answers',a)

    @locked
    def feedback(self,u,rid,answer_id,text,reviewed=False,correct=None):
        r=self._owned(u,'act_rooms',rid)
        a=clone(self.data['act_answers'].get(answer_id))
        if not a or a['room']!=rid: raise ActivityError('답안을 찾을 수 없어요.')
        a['teacher_feedback']=limited(text,4000); a['help']=False
        if a.get('ai'): a['ai']['reviewed']=bool(reviewed)
        if correct is not None:
            _,s=self._screen(r,a['screen'])
            a['check']={'correct':bool(correct),'text':'교사가 확인한 결과예요.',
                        'next':s.get('next_correct' if correct else 'next_incorrect','')}
        self._save('act_answers',a)
        self._history(r,{'id':a['student']},a['screen'],'teacher_feedback',{'text':a['teacher_feedback'],'check':a['check']})

    def _shared_response(self,a):
        return {k:clone(a.get(k)) for k in ('screen','response','submitted','updated')}

    @locked
    def snapshot_add(self,u,rid,answer_id):
        r=self._owned(u,'act_rooms',rid); a=self.data['act_answers'].get(answer_id)
        if not a or a['room']!=rid: raise ActivityError('답안을 찾을 수 없어요.')
        if a['scope']!='class': raise ActivityError('학생이 공유 범위를 학급으로 설정한 답안만 전체에 공유할 수 있어요.')
        r['snapshots'].append({'id':uid(),'answer_id':answer_id,'student':a['student'],'name':a['name'],
                               'captured':stamp(),**self._shared_response(a)})
        r['version']+=1; self._save('act_rooms',r)

    @locked
    def snapshots_set(self,u,rid,ids):
        r=self._owned(u,'act_rooms',rid); old={x['id']:x for x in r['snapshots']}
        if len(ids)!=len(set(ids)) or set(ids)-set(old): raise ActivityError('공유 목록을 확인해 주세요.')
        r['snapshots']=[old[i] for i in ids]; r['version']+=1; self._save('act_rooms',r)

    @locked
    def board_patch(self,u,rid,sid,operation):
        r=self._room(u,rid); self._writable(u,r,sid); _,s=self._screen(r,sid)
        group=r['groups'].get(u['id'])
        if not group or not s.get('group_work'): raise ActivityError('모둠 공동 활동 화면에서 사용할 수 있어요.')
        key=f'{rid}:{sid}:{group}'; b=clone(self.data['act_boards'].get(key) or {'id':key,'room':rid,'screen':sid,'group':group,'items':{},'version':0})
        op=operation.get('op'); item_id=limited(operation.get('id'),80)
        if not item_id: raise ActivityError('공동 작업 항목 ID가 필요해요.')
        if op=='add':
            if item_id in b['items']: return clone(b)
            value=self._validate_response(operation.get('value',{}))
            if len(b['items'])>=300: raise ActivityError('공동 보드가 가득 찼어요. 새 화면을 사용해 주세요.')
            b['items'][item_id]={'id':item_id,'author':u['id'],'name':u['name'],'value':value,'at':stamp()}
        elif op=='remove':
            item=b['items'].get(item_id)
            if item and item['author']!=u['id']: raise ActivityError('자신이 작성한 항목만 지울 수 있어요.')
            b['items'].pop(item_id,None)
        else: raise ActivityError('알 수 없는 공동 작업이에요.')
        b['version']+=1; self._save('act_boards',b)
        self._history(r,u,sid,'group_'+op,{'id':item_id,'group':group})
        return clone(b)

    @locked
    def touch(self,u,rid,sid=None):
        r=self._room(u,rid)
        if u.get('role')=='student':
            if sid: self._screen(r,sid)
            prev=self.presence.get((rid,u['id']),{})
            active=sid or prev.get('screen') or r['lesson']['screens'][r['start']]['id']
            index,_=self._screen(r,active)
            if r['status']=='open' and r['sync']: active=r['lesson']['screens'][r['current']]['id']
            elif r['status']=='open' and (index<r['start'] or index>r['end']): active=r['lesson']['screens'][r['start']]['id']
            self.presence[(rid,u['id'])]={'time':self.clock(),'screen':active}

    def _public_lesson(self,r):
        l=clone(r['lesson'])
        l.pop('owner',None)
        for s in l['screens']:
            for key in ('check','rubric','next_correct','next_incorrect'): s.pop(key,None)
        return l

    @locked
    def state(self,u,rid,screen_id=None,asset_student=None,include_assets=True):
        r=self._room(u,rid); teacher=u.get('role')=='teacher'
        all_answers=[a for a in self.data['act_answers'].values() if a['room']==rid]
        out={k:clone(r[k]) for k in ('id','class','code','status','paused','start','end','sync','current','anonymous','gallery','ai_enabled','version')}
        out.update(role=u['role'],user_id=u['id'],name=u['name'],lesson=clone(r['lesson']) if teacher else self._public_lesson(r),
                   ai_available=bool(self.ai and self.ai.available),global_locked=bool(self.global_lock(r['class'])),server_time=self.clock())
        out['answers']=clone(all_answers if teacher else [a for a in all_answers if a['student']==u['id']])
        out['group']=r['groups'].get(u['id'],'')
        if teacher:
            out['members']=[{'id':sid,**m,'group':r['groups'].get(sid,''),
                             'online':self.clock()-self.presence.get((rid,sid),{}).get('time',0)<15,
                             'screen':self.presence.get((rid,sid),{}).get('screen','')} for sid,m in r['members'].items()]
        out['boards']=[clone(b) for b in self.data['act_boards'].values() if b['room']==rid and (teacher or (out['group'] and b['group']==out['group']))]
        out['shared']=[]
        if r['gallery']:
            for a in all_answers:
                same_group=bool(out['group']) and r['groups'].get(a['student'])==out['group']
                if a['scope']=='class' or (a['scope']=='group' and same_group):
                    out['shared'].append(self._shared_response(a)|{'name':'익명' if r['anonymous'] else a['name']})
        out['snapshots']=[]
        for sn in r['snapshots']:
            current=self.data['act_answers'].get(sn['answer_id'])
            if not current or current['scope']!='class': continue
            out['snapshots'].append({k:clone(sn[k]) for k in ('id','screen','response','captured')}|{'name':'익명' if r['anonymous'] else sn['name']})
        # Only lesson assets and the viewer's own/teacher-authorized attachments leave the server.
        active_screen=screen_id or (r['lesson']['screens'][r['current']]['id'] if r['sync'] and r['status']=='open' else self.presence.get((rid,u['id']),{}).get('screen')) or r['lesson']['screens'][r['start']]['id']
        asset_ids={a for s in r['lesson']['screens'] if s['id']==active_screen for a in s.get('assets',[])} if include_assets else set()
        if include_assets:
            shared_screen_ids={x['screen'] for x in out['snapshots']}
            for screen in r['lesson']['screens']:
                if screen['id'] in shared_screen_ids: asset_ids.update(screen.get('assets',[]))
            for a in out['answers']:
                if a['screen']==active_screen and a['student']==(asset_student or u['id']): asset_ids.update(a.get('attachments',[]))
        out['assets']={aid:self._asset_public(self.data['act_assets'][aid]) for aid in asset_ids if aid in self.data['act_assets']}
        return out

    def _asset_public(self,a):
        if a['id'] in self.asset_cache:
            self.asset_cache.move_to_end(a['id']); return clone(self.asset_cache[a['id']])
        raw=self.backend.load_file(a['file_id'])
        if raw is None: return {'id':a['id'],'name':a['name'],'mime':a['mime'],'error':'파일을 불러오지 못했어요.'}
        result={'id':a['id'],'name':a['name'],'mime':a['mime'],'width':a.get('width',1000),'height':a.get('height',700),'data':'data:'+a['mime']+';base64,'+base64.b64encode(raw).decode()}
        self.asset_cache[a['id']]=result
        while sum(len(x.get('data','')) for x in self.asset_cache.values())>48*1024*1024:
            self.asset_cache.popitem(last=False)
        return clone(result)

    @locked
    def add_asset(self,u,raw,name,mime,purpose='lesson',rid=None,sid=None):
        if purpose=='lesson': self._teacher(u)
        else:
            r=self._room(u,rid); self._writable(u,r,sid)
            if purpose!='answer': raise ActivityError('첨부 용도를 확인해 주세요.')
        if purpose=='answer':
            existing=self.data['act_answers'].get(self._answer_id(rid,sid,u['id']),{})
            if len(existing.get('attachments',[]))>=5: raise ActivityError('한 화면에 첨부는 5개까지 가능해요.')
        from .media import normalize_upload
        raw,mime,name=normalize_upload(raw,mime,name)
        fid,_=self.backend.save_file(raw,name,mime,False)
        a={'id':uid(),'owner':u['id'],'purpose':purpose,'room':rid,'screen':sid,'name':name,'mime':mime,'file_id':fid}
        if mime.startswith('image/'):
            from PIL import Image
            image=Image.open(io.BytesIO(raw));a['width'],a['height']=image.size
        self._save('act_assets',a)
        if purpose=='answer':
            key=self._answer_id(rid,sid,u['id']); ans=clone(self.data['act_answers'].get(key) or self._empty_answer(u,r,sid))
            attachments=ans.setdefault('attachments',[])
            if len(attachments)>=5: raise ActivityError('한 화면에 첨부는 5개까지 가능해요.')
            attachments.append(a['id']); ans['version']+=1; ans['ai']={}; ans['updated']=stamp()
            self._save('act_answers',ans)
        return clone(a)

    @locked
    def ai_request(self,u,rid,sid,consent=False):
        r=self._room(u,rid); self._writable(u,r,sid)
        if not r['ai_enabled'] or not self.ai or not self.ai.available: raise ActivityError('AI 연결이 준비되지 않았어요. 선생님 피드백을 이용해 주세요.')
        if not consent: raise ActivityError('선택한 풀이 자료를 AI에 보내는 데 동의해 주세요.')
        key=self._answer_id(rid,sid,u['id']); a=clone(self.data['act_answers'].get(key))
        if not a or (not a['response'] and not a.get('attachments')): raise ActivityError('풀이를 먼저 저장해 주세요.')
        if a.get('ai',{}).get('status')=='pending': raise ActivityError('이미 분석 중이에요.')
        now=self.clock(); recent=[t for t in self.rate.get(u['id'],[]) if now-t<60]
        if len(recent)>=3: raise ActivityError('잠시 후 다시 요청해 주세요. 1분에 3회까지 가능해요.')
        self.rate[u['id']]=recent+[now]
        _,s=self._screen(r,sid); job=uid(); a['ai']={'status':'pending','job':job,'reviewed':False,'version':a['version']}
        self._save('act_answers',a)
        self.pool.submit(self._ai_job,key,job,clone(s),clone(a))

    def _ai_job(self,key,job,s,a):
        try:
            attachments=[]
            with self.lock:
                student_assets=[clone(self.data['act_assets'][aid]) for aid in a.get('attachments',[])]
                lesson_assets=[clone(self.data['act_assets'][aid]) for aid in s.get('assets',[])]
            for asset in student_assets:
                raw=self.backend.load_file(asset['file_id'])
                if raw: attachments.append({'bytes':raw,'mime':asset['mime'],'name':asset['name']})
            for asset in lesson_assets:
                raw=self.backend.load_file(asset['file_id'])
                if raw and asset['mime'].startswith('image/'):
                    attachments.append({'bytes':raw,'mime':asset['mime'],'name':'문제 배경','context':True})
            result=self.ai.analyze(s,a['response'],attachments)
            result.update(status='done',reviewed=False,version=a['version'])
        except Exception:
            result={'status':'error','text':'AI 분석을 완료하지 못했어요. 연결·한도·모델 설정을 확인하거나 선생님께 도움을 요청해 주세요.','reviewed':False}
        with self.lock:
            current=clone(self.data['act_answers'].get(key))
            if current and current.get('ai',{}).get('job')==job and current['response']==a['response'] and current.get('attachments',[])==a.get('attachments',[]):
                result['version']=current['version']
                current['ai']=result
                if result.get('needs_teacher'): current['help']=True
                self._save('act_answers',current)

    @locked
    def history(self,u,rid,student=None):
        self._room(u,rid)
        if u['role']!='teacher': student=u['id']
        return [clone(e) for e in self.data['act_history'].values() if e['room']==rid and (not student or e['student']==student)]

    @locked
    def export(self,u,rid):
        r=self._owned(u,'act_rooms',rid)
        return {'exported':stamp(),'room':r,'answers':[clone(a) for a in self.data['act_answers'].values() if a['room']==rid],
                'history':self.history(u,rid),'boards':[clone(b) for b in self.data['act_boards'].values() if b['room']==rid]}

    def handle(self,u,rid,event):
        """Exactly-once within process, client-generated event IDs are receipts only."""
        if not isinstance(event,dict): raise ActivityError('요청 형식이 잘못됐어요.')
        eid=limited(event.get('id'),100)
        if not eid: raise ActivityError('요청 ID가 필요해요.')
        receipt_key=(u['id'],rid,eid)
        with self.lock:
            if receipt_key in self.receipts: return clone(self.receipts[receipt_key])
            kind=event.get('kind'); sid=event.get('screen')
            try:
                if kind=='answer':
                    a=self.save_answer(u,rid,sid,event.get('response',{}),event.get('version'),bool(event.get('submit')),event.get('scope'))
                    result={'answer':a}
                elif kind=='signal': self.signal(u,rid,sid,event.get('help'),event.get('understanding')); result={}
                elif kind=='navigate':
                    r=self._room(u,rid)
                    if r['status']=='open': self._writable(u,r,sid)
                    self.touch(u,rid,sid); result={}
                elif kind=='board': result={'board':self.board_patch(u,rid,sid,event.get('operation',{}))}
                elif kind=='asset':
                    try: raw=base64.b64decode(event.get('base64',''),validate=True)
                    except (ValueError,TypeError): raise ActivityError('첨부파일을 읽지 못했어요.')
                    result={'asset':self.add_asset(u,raw,event.get('name','파일'),event.get('mime',''),purpose='answer',rid=rid,sid=sid)}
                elif kind=='ai': self.ai_request(u,rid,sid,event.get('consent') is True); result={}
                else: raise ActivityError('지원하지 않는 요청이에요.')
                result={'id':eid,'ok':True,**result}
            except (ActivityError,ValueError) as e:
                result={'id':eid,'ok':False,'error':str(e),'conflict':isinstance(e,Conflict)}
            self.receipts[receipt_key]=clone(result)
            if len(self.receipts)>2500: self.receipts.pop(next(iter(self.receipts)))
            return result
