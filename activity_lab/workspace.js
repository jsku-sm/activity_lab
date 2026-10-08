/* No external scripts, analytics, eval, or client credentials. */
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy = value => JSON.parse(JSON.stringify(value));
const makeId = () => globalThis.crypto?.randomUUID?.() || Date.now().toString(36)+Math.random().toString(36).slice(2);

// Small, bounded mathematical parser. Supports explicit and implicit equations.
export function mathExpr(source) {
  let str=String(source).replaceAll('π','pi').replaceAll('²','^2').replaceAll('³','^3').replaceAll('×','*').replaceAll('÷','/');
  if(str.length>250) throw Error('식은 250자 이내로 적어 주세요.');
  const tokens=[];let p=0;
  while(p<str.length){if(/\s/.test(str[p])){p++;continue;}const m=str.slice(p).match(/^(?:\d*\.\d+|\d+\.?\d*)(?:[eE][+-]?\d+)?|^[a-zA-Z]+|^[+\-*/^()]/);if(!m)throw Error('허용하지 않는 기호예요.');tokens.push(m[0]);p+=m[0].length;}
  const ts=[];const fn={sin:Math.sin,cos:Math.cos,tan:Math.tan,sqrt:Math.sqrt,abs:Math.abs,log:Math.log,exp:Math.exp};
  for(let i=0;i<tokens.length;i++){const a=tokens[i-1],b=tokens[i];if(i&&(/^[\d.]|^[xyabc]$|^pi$|^e$|^\)$/.test(a))&&(/^[a-zA-Z(]/.test(b)||(/^\d/.test(b)&&a===')')))ts.push('*');ts.push(b);}
  let k=0,depth=0;
  function atom(){if(++depth>40)throw Error('식이 너무 복잡해요.');let t=ts[k++],f;
    if(t==='('){f=add();if(ts[k++]!==')')throw Error('괄호를 확인해 주세요.');}
    else if(fn[t]){if(ts[k++]!=='(')throw Error('함수 뒤에 괄호를 써 주세요.');const a=add();if(ts[k++]!==')')throw Error('괄호를 확인해 주세요.');f=v=>fn[t](a(v));}
    else if(t==='pi')f=()=>Math.PI;else if(t==='e')f=()=>Math.E;
    else if(/^[xyabc]$/.test(t||''))f=v=>Number(v[t]??0);
    else if(t!==undefined&&Number.isFinite(Number(t)))f=()=>Number(t);
    else throw Error('식과 변수 x, y, a, b, c를 확인해 주세요.');depth--;return f;}
  function power(){let a=atom();if(ts[k]==='^'){k++;const b=unary();return v=>a(v)**b(v);}return a;}
  function unary(){if(ts[k]==='-'){k++;const a=unary();return v=>-a(v);}if(ts[k]==='+'){k++;return unary();}return power();}
  function mul(){let a=unary();while(['*','/'].includes(ts[k])){let op=ts[k++],b=unary(),left=a;a=op==='*'?v=>left(v)*b(v):v=>left(v)/b(v);}return a;}
  function add(){let a=mul();while(['+','-'].includes(ts[k])){let op=ts[k++],b=mul(),left=a;a=op==='+'?v=>left(v)+b(v):v=>left(v)-b(v);}return a;}
  const out=add();if(k!==ts.length)throw Error('식의 형식을 확인해 주세요.');return out;
}

function drawGraph(canvas,res,screen,errorElement) {
  const ctx=canvas.getContext('2d'),w=900,h=520;canvas.width=w;canvas.height=h;
  ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);
  const X=x=>(x+10)*w/20,Y=y=>(7-y)*h/14;
  ctx.strokeStyle='#e5edf6';ctx.lineWidth=1;
  for(let i=-10;i<=10;i++){ctx.beginPath();ctx.moveTo(X(i),0);ctx.lineTo(X(i),h);ctx.stroke();}
  for(let i=-7;i<=7;i++){ctx.beginPath();ctx.moveTo(0,Y(i));ctx.lineTo(w,Y(i));ctx.stroke();}
  ctx.strokeStyle='#7b8fa8';ctx.lineWidth=1.8;ctx.beginPath();ctx.moveTo(X(0),0);ctx.lineTo(X(0),h);ctx.moveTo(0,Y(0));ctx.lineTo(w,Y(0));ctx.stroke();
  ctx.fillStyle='#617892';ctx.font='14px sans-serif';for(let i=-10;i<=10;i+=2)ctx.fillText(i,X(i)+3,Y(0)+16);ctx.fillText('x',w-15,Y(0)-8);ctx.fillText('y',X(0)+8,15);
  const expr=String(res.expression??screen.expression??'y=a*x+b');const vars={a:1,b:0,c:1,...screen.params,...res.params};
  try {
    if(expr.trim()){
      const eq=expr.split('=');if(eq.length>2)throw Error('등호는 한 개만 써 주세요.');
      ctx.strokeStyle='#3375c0';ctx.lineWidth=3;
      if(eq.length===1 || eq[0].trim()==='y'){
        const f=mathExpr(eq.at(-1));ctx.beginPath();let prev=null;
        for(let px=0;px<=w;px+=2){const x=px*20/w-10,y=f({...vars,x}),py=Y(y);if(!Number.isFinite(y)||Math.abs(py)>h*10){prev=null;continue;}if(prev===null||Math.abs(py-prev)>h)ctx.moveTo(px,py);else ctx.lineTo(px,py);prev=py;}ctx.stroke();
      }else{
        const l=mathExpr(eq[0]),r=mathExpr(eq[1]),f=(x,y)=>l({...vars,x,y})-r({...vars,x,y});
        // Marching squares with interpolated zero crossings.
        const dx=20/110,dy=14/77;
        for(let xi=0;xi<110;xi++)for(let yi=0;yi<77;yi++){
          const x=-10+xi*dx,y=-7+yi*dy,ps=[[x,y],[x+dx,y],[x+dx,y+dy],[x,y+dy]],vs=ps.map(p=>f(...p)),hits=[];
          if(vs.some(v=>!Number.isFinite(v)))continue;
          for(let e=0;e<4;e++){const j=(e+1)%4;if((vs[e]<=0&&vs[j]>0)||(vs[e]>0&&vs[j]<=0)){const t=vs[e]/(vs[e]-vs[j]);hits.push([ps[e][0]+t*(ps[j][0]-ps[e][0]),ps[e][1]+t*(ps[j][1]-ps[e][1])]);}}
          for(let j=0;j+1<hits.length;j+=2){ctx.beginPath();ctx.moveTo(X(hits[j][0]),Y(hits[j][1]));ctx.lineTo(X(hits[j+1][0]),Y(hits[j+1][1]));ctx.stroke();}
        }
      }
    }
    if(errorElement)errorElement.textContent='';
  }catch(e){if(errorElement)errorElement.textContent=e.message;}
  ctx.fillStyle='#d77a4b';
  for(const row of res.table||screen.table||[]){if(row.length<2||row.some(v=>String(v).trim()===''))continue;const [x,y]=row.map(Number);if(!Number.isFinite(x)||!Number.isFinite(y))continue;ctx.beginPath();ctx.arc(X(x),Y(y),5,0,Math.PI*2);ctx.fill();}
  const point=res.point||[1,1];ctx.fillStyle='#a44881';ctx.beginPath();ctx.arc(X(point[0]),Y(point[1]),8,0,Math.PI*2);ctx.fill();ctx.fillText(`P (${point[0]}, ${point[1]})`,X(point[0])+12,Y(point[1])-10);
}

function drawInk(canvas,strokes){
  canvas.width=1000;canvas.height=Math.round(1000/Number(canvas.dataset.ratio||10/7));const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
  for(const s of strokes||[]){if(!s.points?.length)continue;ctx.strokeStyle=s.color||'#20334b';ctx.lineWidth=s.width||3;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath();s.points.forEach((p,i)=>i?ctx.lineTo(p[0]*1000,p[1]*canvas.height):ctx.moveTo(p[0]*1000,p[1]*canvas.height));if(s.points.length===1)ctx.lineTo(s.points[0][0]*1000+.3,s.points[0][1]*canvas.height+.3);ctx.stroke();}
}

class ActivityUI {
  constructor(root){this.root=root;this.sid='';this.local={};this.pending=null;this.queue=[];this.lastAck='';this.error='';this.renderKey='';this.dirty={};this.recorder=null;this.recordStream=null;this.latestTime=Date.now();}
  get screen(){return this.data.lesson.screens.find(s=>s.id===this.sid)||this.data.lesson.screens[0];}
  answer(sid=this.sid){return this.data.answers.find(a=>a.screen===sid)||{version:0,response:{},scope:'private',attachments:[]};}
  get res(){return this.local[this.sid]||(this.local[this.sid]=copy(this.answer().response||{}));}
  get blocked(){return this.data.role==='teacher'||this.data.paused||this.data.global_locked||this.data.status!=='open';}
  button(label,fn,cls=''){const b=document.createElement('button');b.textContent=label;b.className=cls;b.onclick=fn;return b;}
  q(sel){return this.root.querySelector(sel);}
  notice(text,error=false){const n=this.q('#notice');if(n){n.textContent=text;n.className='notice'+(error?' error':'');n.classList.toggle('hidden',!text);}}
  send(event){
    if(this.data.preview)return;
    const e={id:makeId(),screen:this.sid,...event};
    // Only unsent draft saves are coalesced; submissions and commands are kept.
    if(e.kind==='answer'&&!e.submit){const i=this.queue.findIndex(x=>x.kind==='answer'&&!x.submit&&x.screen===e.screen);if(i>=0)this.queue[i]=e;else this.queue.push(e);}else this.queue.push(e);
    this.pump();
  }
  pump(){if(this.pending||!this.queue.length)return;let e=this.queue.shift();if(e.kind==='answer')e.version=this.answer(e.screen).version;
    this.pending=e;this.trigger('event',e);this.saveStatus('서버에 저장 중…');}
  saveStatus(text){const el=this.q('#save-status');if(el)el.textContent=text;}
  changed(){this.dirty[this.sid]=true;this.saveStatus('수정 중…');clearTimeout(this.saveTimer);const sid=this.sid;this.saveTimer=setTimeout(()=>{if(this.root.isConnected&&this.sid===sid&&!this.blocked)this.save(false);},650);}
  save(submit){if(this.blocked)return;clearTimeout(this.saveTimer);this.send({kind:'answer',response:copy(this.res),scope:this.q('#scope')?.value||this.answer().scope||'private',submit});}
  navigate(sid){if(sid===this.sid)return;if(this.dirty[this.sid]&&!this.blocked)this.save(false);this.stopRecording();this.sid=sid;this.renderKey='';this.render();if(this.data.role==='student')this.send({kind:'navigate',screen:sid});}
  update(data,trigger){
    this.data=data;this.trigger=trigger;this.latestTime=Date.now();
    const ack=data.receipt;
    if(ack&&ack.id!==this.lastAck){
      this.lastAck=ack.id;
      if(this.pending?.id===ack.id){
        const pending=this.pending;this.pending=null;
        if(ack.ok){
          if(ack.answer){const i=data.answers.findIndex(a=>a.screen===ack.answer.screen);if(i>=0)data.answers[i]=ack.answer;else data.answers.push(ack.answer);
            if(JSON.stringify(this.local[ack.answer.screen])===JSON.stringify(ack.answer.response)){this.dirty[ack.answer.screen]=false;}}
          this.error='';this.saveStatus('서버에 저장됨');
        }else{
          this.error=ack.error;this.queue=this.queue.filter(e=>e.kind!=='answer'||e.screen!==pending.screen);
          this.saveStatus('저장되지 않음 · 아래 안내 확인');
          if(ack.conflict)this.conflict=pending.screen;
        }
      }
    }
    const screens=data.lesson.screens;let current=screens.findIndex(s=>s.id===this.sid);
    const target=data.status==='closed'?Math.max(0,current):(data.sync?data.current:Math.max(data.start,Math.min(data.end,current<0?data.start:current)));
    if(current!==target){this.sid=screens[target].id;this.renderKey='';}
    let remoteChanged=false;
    if(!this.dirty[this.sid]&&!this.pending&&!this.queue.some(e=>e.screen===this.sid)){const incoming=this.answer().response||{};remoteChanged=JSON.stringify(this.local[this.sid]||{})!==JSON.stringify(incoming);this.local[this.sid]=copy(incoming);}
    const key=JSON.stringify([this.sid,data.paused,data.global_locked,data.status,data.start,data.end,data.sync,data.group,data.role,data.lesson.version,Object.keys(data.assets||{}),data.presentation]);
    if(key!==this.renderKey){this.renderKey=key;this.render();}else {if(remoteChanged&&!data.presentation)this.renderInteraction();this.refresh();}
    this.pump();
  }
  render(){
    if(this.data.presentation){this.renderPresentation();return;}
    const d=this.data,s=this.screen;const read=d.role==='teacher';
    this.root.innerHTML=`<div class="bar between"><div><span class="badge">${esc(d.class)} · ${read?'답안 살펴보기':'참여형 수업'}</span><h2 style="margin-top:8px">${esc(d.lesson.title)}</h2></div><div class="muted"><span class="live-dot"></span>실시간 연결 · <span id="save-status">${this.dirty[this.sid]?'저장 대기':'서버 기록 불러옴'}</span></div></div>
      <div id="notice" class="notice hidden" role="status"></div><div class="pages" id="pages"></div>
      <div id="lock-box"></div><div class="layout"><main><div class="card"><span class="badge">${esc({text:'생각 쓰기',choice:'선택하기',graph:'그래프 탐구',cards:'카드 분류',table:'표와 그래프',drawing:'그림·필기',pdf:'학습지 필기'}[s.type])}</span>
      <h3 style="margin-top:12px">${esc(s.title)}</h3><p class="prompt">${esc(s.prompt)}</p><div id="media"></div><div id="interaction"></div>
      <label for="explain">${s.type==='text'?'나의 답과 생각':'나의 설명 · 그렇게 생각한 이유'}</label><textarea id="explain" maxlength="12000" placeholder="생각한 과정과 이유를 자신의 말로 적어 보세요."></textarea>
      <div class="bar between" style="margin-top:12px"><div class="bar" id="submit-buttons"></div><span class="toolbar-status">${read?'읽기 전용':'입력 후 잠시 멈추면 자동 저장됩니다.'}</span></div></div>
      <div id="group-panel"></div><div id="feedback-panel"></div><div id="sharing-panel"></div></main>
      <aside class="side"><div class="card"><h3>수업 도우미</h3><div id="hint-tools"></div><div id="signal-tools"></div></div>
      <div class="card"><h3>내 자료와 공유</h3><label for="scope">이 답안의 공개 범위</label><select id="scope"><option value="private">나와 선생님</option><option value="group">우리 모둠</option><option value="class">우리 학급 · 교사 선택 공유 허용</option></select><p class="muted">음성·첨부 원본은 본인과 교사만 볼 수 있어요.</p><div id="upload-tools"></div><div id="attachments"></div></div>
      <div class="card"><h3>AI 생각 도우미</h3><div id="ai-tools"></div><div id="ai-panel"></div></div></aside></div>`;
    const pages=this.q('#pages');d.lesson.screens.forEach((sc,i)=>{const b=this.button(`${i+1} · ${sc.title.replace(/^\d+\s*·\s*/,'')}`,()=>this.navigate(sc.id),sc.id===this.sid?'selected':'');b.disabled=!read&&d.status==='open'&&(i<d.start||i>d.end||d.sync&&i!==d.current);pages.append(b);});
    const response=this.res;const text=this.q('#explain');text.value=response.text||'';text.disabled=this.blocked;text.oninput=()=>{this.res.text=text.value;this.changed();};
    this.q('#scope').value=this.answer().scope||'private';this.q('#scope').disabled=this.blocked;
    this.q('#scope').onchange=()=>{this.dirty[this.sid]=true;this.save(false);};
    const buttons=this.q('#submit-buttons');if(!read){buttons.append(this.button('풀이 제출',()=>this.save(true),'primary'),this.button('지금 저장',()=>this.save(false)));for(const b of buttons.children)b.disabled=this.blocked;}
    const media=this.q('#media');if(!['pdf','drawing'].includes(s.type))for(const id of s.assets||[]){const a=d.assets[id];if(a?.data){const img=document.createElement('img');img.className='attachment';img.alt=a.name;img.src=a.data;media.append(img);}}
    this.renderInteraction();this.renderTools();this.refresh();
  }
  renderInteraction(){
    const s=this.screen,box=this.q('#interaction'),res=this.res;box.innerHTML='';
    if(s.type==='choice')s.options.forEach((value,i)=>{const label=document.createElement('label');label.className='option'+(String(res.choice)===String(i)?' active':'');label.innerHTML=`<input type="radio" name="option" value="${i}" ${String(res.choice)===String(i)?'checked':''} ${this.blocked?'disabled':''}><span>${esc(value)}</span>`;label.onchange=()=>{this.res.choice=String(i);this.changed();this.renderInteraction();};box.append(label);});
    if(s.type==='cards')this.renderCards(box);
    if(s.type==='graph'||s.type==='table')this.renderGraph(box);
    if(s.type==='drawing'||s.type==='pdf')this.renderDrawing(box);
  }
  renderCards(box){
    const s=this.screen;this.res.placements||={};const groups=['미분류',...(s.categories||[])];
    box.innerHTML='<p class="muted">카드를 끌어 옮기거나 카드 아래 선택 메뉴를 이용하세요.</p><div class="columns"></div>';
    groups.forEach(group=>{const bucket=document.createElement('div');bucket.className='bucket';bucket.innerHTML=`<h4>${esc(group)}</h4>`;
      bucket.ondragover=e=>{if(this.blocked)return;e.preventDefault();bucket.classList.add('over');};bucket.ondragleave=()=>bucket.classList.remove('over');
      bucket.ondrop=e=>{if(this.blocked)return;e.preventDefault();const id=e.dataTransfer.getData('text/plain');if(!/^\d+$/.test(id)||!s.cards[Number(id)])return;this.placeCard(id,group);};
      s.cards.forEach((card,i)=>{if((this.res.placements[String(i)]||'미분류')!==group)return;const el=document.createElement('div');el.className='sort-card';el.draggable=!this.blocked;el.ondragstart=e=>e.dataTransfer.setData('text/plain',String(i));el.innerHTML=`<div>${esc(card)}</div><select aria-label="${esc(card)} 분류">${groups.map(g=>`<option ${g===group?'selected':''}>${esc(g)}</option>`).join('')}</select>`;const select=el.querySelector('select');select.disabled=this.blocked;select.onchange=()=>this.placeCard(String(i),select.value);bucket.append(el);});
      box.querySelector('.columns').append(bucket);
    });
  }
  placeCard(id,group){if(group==='미분류')delete this.res.placements[id];else this.res.placements[id]=group;this.changed();this.renderInteraction();}
  renderGraph(box){
    const s=this.screen,res=this.res;res.expression??=s.type==='table'?'':s.expression||'y=a*x+b';res.params??=copy(s.params||{a:1,b:0,c:1});res.table??=copy(s.table||[['0','0'],['1','1']]);
    box.innerHTML=`<label>함수·도형의 식 <input id="expr" maxlength="250" placeholder="y=a*x+b 또는 x^2+y^2=c^2"></label><div class="graph-tools" id="params"></div><p class="muted">변수 a, b, c · sin, cos, tan, sqrt, abs, log, exp 지원. 그래프의 점 P를 움직여 좌표를 살펴보세요.</p><canvas id="graph" aria-label="조작 가능한 좌표평면"></canvas><div id="graph-error" class="muted" role="status"></div><details ${s.type==='table'?'open':''}><summary>좌표표 · 입력한 점을 그래프에 표시</summary><table><thead><tr><th>x</th><th>y</th><th></th></tr></thead><tbody id="table-body"></tbody></table><div id="add-row"></div></details>`;
    const expr=box.querySelector('#expr');expr.value=res.expression;expr.disabled=this.blocked;expr.oninput=()=>{res.expression=expr.value;this.changed();paint();};
    for(const p of ['a','b','c']){const label=document.createElement('label');label.innerHTML=`${p} = <span>${esc(res.params[p])}</span><input aria-label="${p}" type="range" min="-10" max="10" step="0.1" value="${Number(res.params[p]??0)}">`;const input=label.querySelector('input');input.disabled=this.blocked;input.oninput=()=>{res.params[p]=Number(input.value);label.querySelector('span').textContent=input.value;paint();this.changed();};box.querySelector('#params').append(label);}
    const canvas=box.querySelector('#graph'),paint=()=>drawGraph(canvas,res,s,box.querySelector('#graph-error'));
    const point=e=>{if(this.blocked)return;const rect=canvas.getBoundingClientRect();res.point=[Math.round(((e.clientX-rect.left)/rect.width*20-10)*10)/10,Math.round((7-(e.clientY-rect.top)/rect.height*14)*10)/10];paint();this.changed();};
    canvas.onpointerdown=e=>{if(this.blocked)return;canvas.setPointerCapture(e.pointerId);this.graphDrag=true;point(e);};canvas.onpointermove=e=>{if(this.graphDrag)point(e);};canvas.onpointerup=()=>this.graphDrag=false;canvas.onpointercancel=()=>this.graphDrag=false;
    const tbody=box.querySelector('#table-body');res.table.forEach((row,i)=>{const tr=document.createElement('tr');for(let j=0;j<2;j++){const td=document.createElement('td'),input=document.createElement('input');input.type='number';input.step='any';input.value=row[j];input.disabled=this.blocked;input.setAttribute('aria-label',`${i+1}행 ${j?'y':'x'}`);input.oninput=()=>{row[j]=input.value;paint();this.changed();};td.append(input);tr.append(td);}const td=document.createElement('td'),del=this.button('삭제',()=>{res.table.splice(i,1);this.changed();this.renderInteraction();});del.disabled=this.blocked;td.append(del);tr.append(td);tbody.append(tr);});
    const add=this.button('행 추가',()=>{if(res.table.length>=30)return;res.table.push(['','']);this.changed();this.renderInteraction();});add.disabled=this.blocked;box.querySelector('#add-row').append(add);paint();
  }
  renderDrawing(box){
    const s=this.screen,res=this.res;res.strokes||=[];
    const bg=this.data.assets[s.assets?.[0]];
    box.innerHTML=`<div class="bar draw-tools"><label>색 <input type="color" id="ink-color" value="${this.inkColor||'#20334b'}"></label><label>굵기 <input type="range" id="ink-width" min="1" max="10" value="${this.inkWidth||3}"></label><div id="ink-buttons" class="bar"></div></div><div class="draw-wrap" style="background:#fff;aspect-ratio:${bg?.width||1000}/${bg?.height||700}">${bg?.data?`<img src="${esc(bg.data)}" alt="${esc(bg.name)}">`:''}<canvas id="ink" aria-label="펜과 손가락으로 풀이를 쓰는 공간"></canvas></div><p class="muted">펜·손가락·마우스로 쓰세요. 필기는 화면 비율에 맞추어 보관됩니다.</p>`;
    const canvas=box.querySelector('#ink');canvas.dataset.ratio=String((bg?.width||1000)/(bg?.height||700));const paint=()=>drawInk(canvas,res.strokes);paint();
    box.querySelector('#ink-color').oninput=e=>this.inkColor=e.target.value;box.querySelector('#ink-width').oninput=e=>this.inkWidth=Number(e.target.value);
    const undo=this.button('한 획 지우기',()=>{res.strokes.pop();paint();this.changed();});undo.disabled=this.blocked;box.querySelector('#ink-buttons').append(undo);
    if(s.group_work&&this.data.group){const publish=this.button('이 필기를 모둠에 붙이기',()=>{this.send({kind:'board',operation:{op:'add',id:makeId(),value:{strokes:copy(res.strokes)}}});});publish.disabled=this.blocked;box.querySelector('#ink-buttons').append(publish);}
    const point=e=>{const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
    canvas.onpointerdown=e=>{if(this.blocked)return;e.preventDefault();canvas.setPointerCapture(e.pointerId);this.stroke={color:this.inkColor||'#20334b',width:this.inkWidth||3,points:[point(e)]};res.strokes.push(this.stroke);paint();};
    canvas.onpointermove=e=>{if(!this.stroke)return;e.preventDefault();if(this.stroke.points.length<3000)this.stroke.points.push(point(e));paint();};
    const finish=()=>{if(this.stroke){this.stroke=null;this.changed();}};canvas.onpointerup=finish;canvas.onpointercancel=finish;
  }
  renderTools(){
    const s=this.screen,d=this.data;const hint=this.q('#hint-tools');
    if(s.hint){const details=document.createElement('details');details.innerHTML=`<summary>힌트 열기</summary><div class="hint">${esc(s.hint)}</div>`;hint.append(details);}
    const signal=this.q('#signal-tools');const help=this.button('🙋 도움이 필요해요',()=>this.send({kind:'signal',help:true}));help.disabled=this.blocked;signal.append(help);
    const u=document.createElement('select');u.setAttribute('aria-label','나의 이해도');u.innerHTML='<option value="">지금 나의 이해도는?</option>'+['이해했어요','헷갈려요','다시 설명해주세요'].map(x=>`<option>${x}</option>`).join('');u.value=this.answer().understanding||'';u.disabled=this.blocked;u.onchange=()=>this.send({kind:'signal',understanding:u.value});signal.append(u);
    const tools=this.q('#upload-tools');if(d.role==='student'){
      tools.innerHTML='<label>풀이 사진·음성 첨부 (8MB 이하)<input id="attach" type="file" accept="image/png,image/jpeg,image/webp,audio/*"></label><div id="record-bar" class="bar"></div><p class="muted" id="record-status">마이크 녹음은 지원 브라우저·HTTPS에서 사용할 수 있어요.</p>';
      const input=tools.querySelector('#attach');input.disabled=this.blocked;input.onchange=()=>{if(input.files?.[0])this.upload(input.files[0]);input.value='';};
      const rec=this.button(this.recorder?.state==='recording'?'녹음 종료':'🎙 설명 녹음',()=>this.record(),this.recorder?.state==='recording'?'record-btn recording':'record-btn');rec.id='record-button';rec.disabled=this.blocked;tools.querySelector('#record-bar').append(rec);
    }
    const ai=this.q('#ai-tools');
    if(!d.ai_available||!d.ai_enabled)ai.innerHTML='<p class="muted">AI가 연결되어 있지 않거나 교사가 사용을 열지 않았어요. 도움 요청으로 교사에게 질문하세요.</p>';
    else if(d.role==='student'){
      ai.innerHTML='<label><input type="checkbox" id="ai-consent"> 이 화면의 풀이·이미지·음성을 AI에 보내 피드백 받기</label><p class="muted">학번과 이름은 전송 항목에서 제외합니다. 풀이 안에 직접 적은 개인정보는 포함될 수 있어요.</p><div id="ai-btn"></div>';
      const b=this.button('AI 힌트 요청',()=>{if(!this.q('#ai-consent').checked){this.notice('AI 전송 동의를 선택해 주세요.',true);return;}this.save(false);this.send({kind:'ai',consent:true});});b.disabled=this.blocked;ai.querySelector('#ai-btn').append(b);
    }
  }
  async upload(file){if(this.blocked)return;if(file.size>8*1024*1024){this.notice('파일은 8MB 이하로 올려 주세요.',true);return;}const reader=new FileReader();reader.onload=()=>{this.save(false);this.send({kind:'asset',name:file.name,mime:file.type,base64:reader.result.split(',')[1]});};reader.readAsDataURL(file);}
  async record(){
    if(this.recorder?.state==='recording'){this.stopRecording();return;}
    if(!navigator.mediaDevices?.getUserMedia||!globalThis.MediaRecorder){this.notice('이 브라우저에서는 녹음을 지원하지 않아요. 음성 파일을 첨부해 주세요.',true);return;}
    try{
      this.recordStream=await navigator.mediaDevices.getUserMedia({audio:true});const mime=['audio/webm','audio/mp4','audio/ogg'].find(t=>MediaRecorder.isTypeSupported(t));
      this.recorder=new MediaRecorder(this.recordStream,mime?{mimeType:mime}:undefined);const chunks=[];let size=0;
      this.recorder.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);size+=e.data.size;if(size>7*1024*1024)this.stopRecording();}};
      this.recorder.onstop=()=>{clearTimeout(this.recordTimer);this.recordStream?.getTracks().forEach(t=>t.stop());const type=this.recorder.mimeType.split(';')[0];const ext=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';const blob=new Blob(chunks,{type});if(blob.size&&this.root.isConnected&&!this.blocked)this.upload(new File([blob],`설명.${ext}`,{type}));this.recorder=null;this.renderKey='';this.render();};
      this.recorder.start(1000);this.recordTimer=setTimeout(()=>this.stopRecording(),120000);const btn=this.q('#record-button');btn.textContent='⏹ 녹음 종료';btn.classList.add('recording');this.q('#record-status').textContent='녹음 중 · 최대 2분 · 종료하면 첨부됩니다.';
    }catch(e){this.recordStream?.getTracks().forEach(t=>t.stop());this.notice('마이크를 사용할 수 없어요. 권한을 확인하거나 음성 파일을 첨부해 주세요.',true);}
  }
  stopRecording(){if(this.recorder?.state==='recording')this.recorder.stop();else this.recordStream?.getTracks().forEach(t=>t.stop());}
  showResponse(container,res,screen){
    if(res.choice!==undefined){const p=document.createElement('p');p.textContent='선택: '+(screen.options?.[Number(res.choice)]??res.choice);container.append(p);}
    if(res.placements){const p=document.createElement('p');p.textContent=Object.entries(res.placements).map(([i,c])=>`${screen.cards?.[Number(i)]||i} → ${c}`).join('\n');container.append(p);}
    if(res.expression||res.table){const c=document.createElement('canvas');container.append(c);drawGraph(c,res,screen);}
    if(res.strokes){const wrap=document.createElement('div');wrap.className='draw-wrap';const asset=this.data.assets[screen.assets?.[0]];if(asset?.data){const img=document.createElement('img');img.src=asset.data;img.alt=asset.name;wrap.append(img);}const c=document.createElement('canvas');c.dataset.ratio=String((asset?.width||1000)/(asset?.height||700));wrap.style.aspectRatio=c.dataset.ratio;wrap.append(c);container.append(wrap);drawInk(c,res.strokes);}
    if(res.text){const p=document.createElement('p');p.className='safe-text';p.textContent=res.text;container.append(p);}
  }
  refresh(){
    if(this.data.presentation){this.renderPresentation();return;}
    const d=this.data,a=this.answer(),s=this.screen;
    const input=this.q('#explain');
    if(input&&!this.dirty[this.sid]&&this.root.getRootNode().activeElement!==input&&input.value!==(this.res.text||''))input.value=this.res.text||'';
    this.notice(this.error,!!this.error);
    if(this.conflict===this.sid){const n=this.q('#notice');n.append(this.button('내 입력 복사',async()=>{try{await navigator.clipboard.writeText(JSON.stringify(this.res,null,2));this.notice('내 입력을 복사했어요.');}catch{this.notice(JSON.stringify(this.res),true);}}),this.button('최신 답안 불러오기',()=>{this.dirty[this.sid]=false;this.local[this.sid]=copy(this.answer().response);this.conflict=null;this.error='';this.render();}));}
    this.q('#lock-box').innerHTML=(d.paused||d.global_locked)?'<div class="lock"><h2>🔒 잠깐, 함께 생각해요</h2><p>지금은 선생님 설명 시간이에요. 잠금이 풀리면 다시 이어서 할 수 있어요.</p></div>':d.status==='closed'?'<div class="notice">수업이 마감되었어요. 답안과 피드백을 다시 볼 수 있습니다.</div>':'';
    if(this.blocked)this.stopRecording();
    const fb=this.q('#feedback-panel');fb.innerHTML='';
    if(a.check?.text){const p=document.createElement('div');p.className='feedback';p.textContent=a.check.text;fb.append(p);if(a.check.next){const i=d.lesson.screens.findIndex(sc=>sc.id===a.check.next);const b=this.button('수준별 다음 활동으로',()=>this.navigate(a.check.next));b.disabled=this.blocked||i<d.start||i>d.end||d.sync&&i!==d.current;fb.append(b);}}
    if(a.teacher_feedback){const c=document.createElement('div');c.className='card';c.innerHTML='<h3>선생님의 피드백</h3>';const p=document.createElement('p');p.className='safe-text';p.textContent=a.teacher_feedback;c.append(p);fb.append(c);}
    const ai=this.q('#ai-panel');ai.innerHTML='';
    if(a.ai?.status){const p=document.createElement('p');p.className='feedback';p.textContent=a.ai.status==='pending'?'풀이를 살펴보고 있어요…':a.ai.text||'';ai.append(p);
      if(a.ai.status==='done'){const label=document.createElement('span');label.className='badge';label.textContent=a.ai.reviewed?'교사 확인 완료':'AI 제안 · 교사 확인 전';ai.append(label);if(a.ai.needs_teacher){const t=document.createElement('p');t.textContent='확인이 필요한 부분이 있어 교사에게 도움 요청을 표시했어요.';ai.append(t);}if(a.ai.transcript){const det=document.createElement('details');det.innerHTML='<summary>음성 인식 결과 확인</summary>';const p=document.createElement('p');p.textContent=a.ai.transcript;det.append(p);ai.append(det);}}
    }
    const attach=this.q('#attachments');const attachmentKey=JSON.stringify(a.attachments||[]);if(attach.dataset.key!==attachmentKey){attach.dataset.key=attachmentKey;attach.innerHTML='';for(const id of a.attachments||[]){const asset=d.assets[id];if(!asset?.data)continue;const el=document.createElement(asset.mime.startsWith('audio/')?'audio':'img');el.src=asset.data;el.className='attachment';if(asset.mime.startsWith('audio/'))el.controls=true;else el.alt=asset.name;attach.append(el);}}
    this.refreshGroup();this.refreshSharing();
  }
  refreshGroup(){
    const panel=this.q('#group-panel'),s=this.screen;if(!s.group_work){panel.innerHTML='';return;}
    if(!this.data.group&&this.data.role==='student'){panel.innerHTML='<div class="card">선생님이 모둠을 배정하면 공동 보드가 열려요.</div>';return;}
    if(!panel.querySelector('#group-items')){
      panel.innerHTML='<div class="card"><h3>모둠 공동 보드</h3><p class="muted">각자의 메모와 필기를 붙여 함께 완성하세요. 다른 친구의 항목은 덮어쓰지 않습니다.</p><div id="group-items"></div><div id="group-compose"><label>모둠에 남길 생각<textarea id="group-note" maxlength="3000"></textarea></label><div id="group-send"></div></div></div>';
      const b=this.button('모둠에 메모 붙이기',()=>{const text=this.q('#group-note').value.trim();if(!text)return;this.send({kind:'board',operation:{op:'add',id:makeId(),value:{text}}});this.q('#group-note').value='';});b.disabled=this.blocked;panel.querySelector('#group-send').append(b);if(this.data.role==='teacher')panel.querySelector('#group-compose').classList.add('hidden');
    }
    const items=panel.querySelector('#group-items'),boards=this.data.boards.filter(b=>b.screen===this.sid);const key=JSON.stringify(boards);if(items.dataset.key===key)return;items.dataset.key=key;items.innerHTML='';
    for(const board of boards)for(const item of Object.values(board.items)){const card=document.createElement('div');card.className='group-item';const title=document.createElement('strong');title.textContent=`${board.group} · ${item.name}`;card.append(title);this.showResponse(card,item.value,s);if(item.author===this.data.user_id){const del=this.button('내 항목 삭제',()=>this.send({kind:'board',operation:{op:'remove',id:item.id}}));del.disabled=this.blocked;card.append(del);}items.append(card);}
  }
  renderPresentation(){
    const d=this.data,s=d.lesson.screens[d.current];
    this.sid=s.id;
    this.root.innerHTML=`<div class="bar between"><div><span class="badge">${esc(d.class)} · 함께 생각하기</span><h2 style="font-size:32px;margin-top:12px">${esc(d.lesson.title)}</h2></div><span class="badge">${d.anonymous?'익명 공유':'실명 공유'}</span></div><div class="card"><h3>${esc(s.title)}</h3><p class="prompt">${esc(s.prompt)}</p></div><div id="sharing-panel"></div>`;
    this.refreshSharing();
    if(!d.snapshots.length&&!d.shared.length){const msg=document.createElement('p');msg.className='muted';msg.textContent='수업 운영에서 학생 답안을 선택하면 이곳에 표시됩니다.';this.root.append(msg);}
  }
  refreshSharing(){
    const p=this.q('#sharing-panel');const shares=[...this.data.snapshots.map(s=>({...s,kind:'교사가 선택한 생각'})),...this.data.shared.filter(a=>a.screen===this.sid).map(a=>({...a,kind:'함께 보는 생각'}))];
    const key=JSON.stringify(shares);if(p.dataset.key===key)return;p.dataset.key=key;p.innerHTML='';if(!shares.length)return;
    const card=document.createElement('div');card.className='card';card.innerHTML='<h3>우리의 생각 나누기</h3>';
    shares.forEach(item=>{const sc=this.data.lesson.screens.find(s=>s.id===item.screen);if(!sc)return;const el=document.createElement('div');el.className='share-item';const title=document.createElement('h4');title.textContent=`${item.kind} · ${item.name} · ${sc.title}`;el.append(title);this.showResponse(el,item.response,sc);card.append(el);});p.append(card);
  }
}

export default function(component){
  const root=component.parentElement.querySelector('#activity-root');
  if(!root._lab)root._lab=new ActivityUI(root);
  root._lab.update(component.data,component.setTriggerValue);
  return ()=>{setTimeout(()=>{if(!root.isConnected){root._lab.stopRecording();clearTimeout(root._lab.saveTimer);}},50);};
}
