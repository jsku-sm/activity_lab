import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(process.env.ACTIVITY_QA_NODE ? process.env.ACTIVITY_QA_NODE+'/package.json' : new URL('./package.json',import.meta.url));
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(new URL('../activity_lab/workspace.js',import.meta.url),'utf8');
const {default:mount,mathExpr}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
let tests=0;
function test(name,fn){fn();tests++;console.log('PASS',name);}
const dom=new JSDOM('<!doctype html><div id="host"><div id="activity-root"></div></div>',{url:'https://classroom.test/'});
const {window}=dom;globalThis.window=window;globalThis.document=window.document;
Object.defineProperty(globalThis,'navigator',{value:window.navigator,configurable:true});
window.HTMLCanvasElement.prototype.getContext=()=>new Proxy({}, {get:(t,k)=>t[k]||(()=>{}),set:(t,k,v)=>(t[k]=v,true)});
window.HTMLElement.prototype.setPointerCapture=()=>{};
const screen=(id,type)=>({id,type,title:'활동 '+id,prompt:'왜 그런가요?',hint:'근거를 찾아봐요.',options:['A','B'],cards:['y=x','y=x²'],categories:['직선','곡선'],expression:'y=a*x+b',params:{a:1,b:0,c:1},table:[['0','0'],['1','1']],assets:[],group_work:false});
const screens=['text','choice','graph','cards','table','drawing','pdf'].map((t,i)=>screen(String(i),t));
function state(){return {id:'r',class:'1-1',role:'student',user_id:'10101',name:'학생',lesson:{title:'함수 탐구',version:1,screens:structuredClone(screens)},paused:false,global_locked:false,status:'open',start:0,end:6,sync:false,current:0,anonymous:true,gallery:false,ai_enabled:false,ai_available:false,group:'',answers:[],boards:[],shared:[],snapshots:[],assets:{},version:1};}
let sent=[],data=state();const host=document.querySelector('#host'),root=document.querySelector('#activity-root');
const trigger=(key,value)=>sent.push(value);function update(){mount({parentElement:host,data:structuredClone(data),setTriggerValue:trigger});}
update();
test('safe math parser supports powers, implicit multiplication and unary',()=>{
 assert.equal(mathExpr('2x+3')({x:4}),11);assert.equal(mathExpr('-x^2')({x:3}),-9);assert.equal(mathExpr('2^3^2')({}),512);assert.equal(mathExpr('sqrt(9)+abs(-2)')({}),5);assert.equal(mathExpr('(x+1)(x-1)')({x:3}),8);assert.equal(mathExpr('2pi')({}),Math.PI*2);
 assert.throws(()=>mathExpr('globalThis.process.exit()'));assert.throws(()=>mathExpr('x;alert(1)'));
});
test('all seven activity types render with accessible input',()=>{
 for(const s of screens){root._lab.sid=s.id;root._lab.renderKey='';update();assert(root.querySelector('#explain'));if(['drawing','pdf'].includes(s.type))assert(root.querySelector('#ink'));if(['graph','table'].includes(s.type))assert(root.querySelector('#graph'));}
});
test('untrusted prompt and answers are rendered as text',()=>{
 data.lesson.screens[0].prompt='<img src=x onerror="alert(1)">';root._lab.sid='0';root._lab.renderKey='';update();assert(!root.querySelector('img[onerror]'));assert(root.textContent.includes('<img src=x'));
});
test('text autosave event carries response, not identity',()=>{
 const ui=root._lab;const input=root.querySelector('#explain');input.value='내가 발견한 규칙';input.dispatchEvent(new window.Event('input'));ui.save(false);assert.equal(sent.at(-1).kind,'answer');assert.equal(sent.at(-1).response.text,'내가 발견한 규칙');assert.equal(sent.at(-1).version,0);assert.equal(sent.at(-1).student,undefined);
});
test('server acknowledgement advances revision without losing newer typing',()=>{
 const e=sent.at(-1);root.querySelector('#explain').value='더 수정한 생각';root.querySelector('#explain').dispatchEvent(new window.Event('input'));
 data.answers=[{id:'a',screen:'0',student:'10101',version:1,response:{text:'내가 발견한 규칙'},scope:'private',ai:{},check:{}}];data.receipt={id:e.id,ok:true,answer:data.answers[0]};update();assert.equal(root.querySelector('#explain').value,'더 수정한 생각');root._lab.save(true);assert.equal(sent.at(-1).version,1);assert.equal(sent.at(-1).submit,true);
});
test('pause locks all response controls but retains local draft',()=>{
 data.paused=true;update();assert(root.querySelector('#explain').disabled);assert(root.querySelector('.lock'));assert.equal(root._lab.local['0'].text,'더 수정한 생각');
});
test('pacing and sync switch to the teacher screen',()=>{
 data.paused=false;data.sync=true;data.start=1;data.end=3;data.current=2;update();assert.equal(root._lab.sid,'2');assert(root.querySelector('#graph'));const buttons=[...root.querySelectorAll('#pages button')];assert.equal(buttons.filter(b=>!b.disabled).length,1);
});
test('card changes update draft and permit touch dropdown interaction',()=>{
 data.sync=false;data.start=0;data.end=6;root._lab.sid='3';root._lab.renderKey='';update();const sel=root.querySelector('.sort-card select');sel.value='직선';sel.dispatchEvent(new window.Event('change'));assert.equal(root._lab.res.placements['0'],'직선');
});
test('teacher review never exposes editable controls',()=>{
 data.role='teacher';data.current=0;data.start=0;data.end=0;root._lab.sid='0';root._lab.renderKey='';update();assert(root.querySelector('#explain').disabled);assert(!root.querySelector('#record-button'));
});
test('teacher receives changed graph and ink data on polling',()=>{
 const host2=document.createElement('div');host2.innerHTML='<div id="activity-root"></div>';document.body.append(host2);const d=state();d.role='teacher';d.start=2;d.end=2;d.current=2;d.sync=true;d.answers=[{screen:'2',version:1,response:{expression:'y=x',params:{a:1,b:0,c:1},table:[]}}];
 const render=()=>mount({parentElement:host2,data:structuredClone(d),setTriggerValue:()=>{}});render();assert.equal(host2.querySelector('#expr').value,'y=x');d.answers[0].response.expression='y=2*x';d.answers[0].version=2;render();assert.equal(host2.querySelector('#expr').value,'y=2*x');host2.remove();
});
test('conflicts expose explicit recovery instead of silent overwrite',()=>{
 data.role='student';data.end=6;data.receipt={id:root._lab.pending.id,ok:false,conflict:true,error:'다른 창에서 수정됨'};update();assert(root.textContent.includes('최신 답안 불러오기'));assert(root.textContent.includes('내 입력 복사'));
});
test('presentation screen contains no roster or private feedback controls',()=>{
 data.presentation=true;data.snapshots=[{id:'shot',screen:'0',name:'익명',response:{text:'다른 생각도 살펴봐요.'}}];update();assert(root.textContent.includes('다른 생각도 살펴봐요.'));assert(!root.querySelector('#explain'));assert(!root.querySelector('#scope'));assert(!root.querySelector('#ai-tools'));
});
clearTimeout(root._lab.saveTimer);console.log(`${tests} DOM/math checks passed`);
