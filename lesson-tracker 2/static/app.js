const $ = (s) => document.querySelector(s);
const escapeHTML = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const userHTML = v => v===null||v===undefined||v===''?'':`<span data-user-content>${escapeHTML(v)}</span>`;
const fmt = v => Number(v / 100).toLocaleString(window.uiLocale==='en'?'en-AU':'zh-CN', {maximumFractionDigits:2});
const today = () => {if(state.today)return state.today;const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
const icons = {
 grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 book:'<path d="M4 4h12a3 3 0 0 1 3 3v14H7a3 3 0 0 1-3-3V4zM4 17h15M8 8h7M8 12h5"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 users:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M17 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 5"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>'
};
const icon = k => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[k]||icons.book}</svg>`;
const brand = () => `<div class="brand"><img src="/logo.jpg" alt=""><div>${escapeHTML(state.organization || 'HZ Education Melbourne')}<small>课时管理</small></div></div>`;
let state = {}, view = 'home', selected = '', search = '', studentStatus = 'all', studyFilter = 'studying', lastFocus, toastTimer;
async function api(path, data) {
 let r;
 try {r=await fetch('/api/'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf||''},body:JSON.stringify(data)});} catch {throw new Error('网络连接失败，请稍后重试。');}
 let result;try{result=await r.json();}catch{throw new Error('服务暂时不可用，请稍后重试。');}
 if(!r.ok) throw new Error(result.error||'操作未完成。');
 return result;
}
function toast(message){$('#toast').textContent=message;$('#toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').style.display='none',3800);}
async function refresh(){state=await api('state'+(typeof weekStart!=='undefined'&&weekStart?'?through='+encodeURIComponent(datePlus(weekStart,6)):''));render();}
const placeKey='hz-scroll-place';
let placeHold=null, placeTimer=0, placeObserver=null, usedReloadPlace=false;
function placeText(value){return String(value||'').replace(/\s+/g,' ').trim();}
function placeDetailsKey(el){
 const summary=placeText(el.querySelector(':scope > summary')?.innerText).slice(0,60);
 const card=el.previousElementSibling;
 const who=card&&card.classList&&card.classList.contains('pay-card')?placeText(card.querySelector('h2')?.innerText).slice(0,40):'';
 const outer=el.parentElement&&el.parentElement.closest('details');
 const outerLabel=outer?placeText(outer.querySelector(':scope > summary')?.innerText).slice(0,40):'';
 return [who, outerLabel, summary].filter(Boolean).join(' / ');
}
function placeScrollKey(el){
 if(el.id) return '#'+el.id;
 const cls=[...el.classList].slice(0,2).join('.');
 if(!cls) return '';
 return cls+':'+[...document.querySelectorAll('.'+cls)].indexOf(el);
}
function capturePlace(){
 const open=[];
 document.querySelectorAll('details').forEach(el=>{
  if(!el.open||el.closest('#modal')) return;
  const key=placeDetailsKey(el);
  if(key) open.push(key);
 });
 const scrolls=[];
 document.querySelectorAll('main, .content, .gcal-scroll, .time-calendar, .table-wrap, .sidebar').forEach(el=>{
  if(el.closest('#modal')) return;
  if((el.scrollTop||0)<1 && (el.scrollLeft||0)<1) return;
  const key=placeScrollKey(el);
  if(key) scrolls.push({key, top:el.scrollTop, left:el.scrollLeft});
 });
 const place={view:typeof view!=='undefined'?view:'', window:window.scrollY||document.documentElement.scrollTop||0, open, scrolls};
 try{sessionStorage.setItem(placeKey, JSON.stringify({...place, path:location.pathname}));}catch(error){}
 return place;
}
function restorePlace(place){
 if(!place) return;
 document.querySelectorAll('details').forEach(el=>{
  if(el.closest('#modal')) return;
  const key=placeDetailsKey(el);
  if(key && place.open.includes(key)) el.open=true;
 });
 for(const item of place.scrolls||[]){
  const el=item.key.startsWith('#')?document.getElementById(item.key.slice(1)):[...document.querySelectorAll('.'+item.key.split(':')[0])][Number(item.key.split(':')[1])];
  if(el){el.scrollTop=item.top; el.scrollLeft=item.left;}
 }
 window.scrollTo(0, place.window||0);
}
function armPlace(place){
 placeHold=place;
 const kick=()=>{if(placeHold) restorePlace(placeHold);};
 kick();
 requestAnimationFrame(kick);
 clearTimeout(placeTimer);
 placeTimer=setTimeout(()=>{placeHold=null;}, 700);
 if(!placeObserver && document.getElementById('app')){
  placeObserver=new MutationObserver(()=>{if(placeHold) restorePlace(placeHold);});
  placeObserver.observe(document.getElementById('app'), {childList:true, subtree:true});
 }
}
function reloadPlace(){
 try{
  const nav=performance.getEntriesByType('navigation')[0];
  if(!nav || nav.type!=='reload') return null;
  const saved=JSON.parse(sessionStorage.getItem(placeKey)||'null');
  if(!saved || saved.path!==location.pathname) return null;
  return saved;
 }catch(error){return null;}
}
function render(){
 if(!state.user)return login();
 const shell=document.querySelector('.shell');
 let place=shell?capturePlace():null;
 if(!place && !usedReloadPlace){
  usedReloadPlace=true;
  place=reloadPlace();
  if(place && place.view) view=place.view;
 }
 dashboard();
 if(place) armPlace(place);
}
function contactCard(){
 const info=state.contact||{};
 const email=info.email||'helenzeducation@gmail.com';
 return `<section class="login-contact"><h3>忘记密码或需要帮助</h3><p>账号由老师开通，不能在这里自己找回。请发邮件，我们帮你重设密码。</p><p><a href="mailto:${escapeHTML(email)}">${escapeHTML(email)}</a></p></section>`;
}
function login(){
 $('#app').innerHTML=`<main class="login-layout"><section class="login-story">${brand()}<p class="login-tagline">每一节，都有记录</p><div class="story-body"><div class="eyebrow" style="color:inherit">每一节，都有记录</div><h1>探索学习的乐趣，<br>见证每一步成长。</h1><p>查看课程安排、学习内容与今日作业，<br>让每一次进步都有记录。</p><div class="learning-values" aria-label="学习理念"><div class="learning-value"><strong>Habits</strong><span>培养良好习惯</span></div><div class="learning-value"><strong>Methods</strong><span>掌握学习方法</span></div><div class="learning-value"><strong>Success</strong><span>成就每一步成长</span></div></div></div><div class="login-foot">课程安排 · 今日作业 · 课后反馈</div></section><section class="login-side"><div class="login-box"><h2>登录学习中心</h2><p>使用老师为你开通的手机号和密码登录。</p><form id="login-form"><label class="field">手机号<input name="phone" type="tel" autocomplete="username" placeholder="例如 +61 412 345 678" required maxlength="24"></label><label class="field">密码<input name="password" type="password" autocomplete="current-password" placeholder="请输入密码" required maxlength="128"></label><div class="error" id="login-error" role="alert"></div><button class="btn primary full" type="submit">登录 ${icon('arrow')}</button></form>${contactCard()}${state.demo?'<div class="demo-login"><p>当前是本机演示版，仅含虚构学生，可体验完整流程。</p><div class="demo-buttons"><button class="btn" data-demo="owner">Helen校长端</button><button class="btn" data-demo="admin">管理员</button><button class="btn" data-demo="teacher">任课老师</button><button class="btn" data-demo="parent">家长端</button></div></div>':''}</div></section></main>`;
 $('#login-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.currentTarget.querySelector('button');b.disabled=true;$('#login-error').textContent='';try{await api('login',Object.fromEntries(new FormData(e.currentTarget)));view='home';selected='';search='';await refresh();}catch(err){$('#login-error').textContent=err.message;b.disabled=false;}});
 document.querySelectorAll('[data-demo]').forEach(b=>b.addEventListener('click',()=>{const creds={owner:['0400000000','TeacherDemo2026!'],admin:['0400000004','AdminDemo2026!'],teacher:['0400000003','TutorDemo2026!'],parent:['0400000001','ParentDemo2026!']}[b.dataset.demo];$('#login-form [name=phone]').value=creds[0];$('#login-form [name=password]').value=creds[1];$('#login-form').requestSubmit();}));
}
function nameInitial(name){const text=String(name||'').trim();return text?text.slice(0,1).toLocaleUpperCase('en'):'?';}
function sameSubjectCovered(account, group){const subject=account.subject_name||account.course;return (group||[]).some(other=>other!==account && (other.subject_name||other.course)===subject && other.balance>0);}
function entryMoney(entry){const cents=entry.cash_delta||entry.pack_cents;if(cents) return typeof cashFmt==='function'?cashFmt(cents):'$'+(cents/100).toFixed(2);if(entry.cash_delta===0) return typeof cashFmt==='function'?cashFmt(0):'$0.00';return fmt(Math.abs(entry.delta))+' '+unitFor(entry);}
function studyTag(person){const graduated=(person.study_status||'studying')==='graduated';return `<span class="study-tag${graduated?' is-graduated':''}">${graduated?'已毕业':'在读'}</span>`;}
function shownLevel(account){return account?.level_label||'';}
function studyLevelSelect(current){const chosen=current||'';return `<label class="field">学习年级（选填）<select name="study_level"><option value="">不指定，按今年年级</option>${yearLevels().map(level=>`<option value="${level}" ${chosen===level?'selected':''}>${level}</option>`).join('')}</select><small>只有高于今年年级时，才显示这个年级并用它定价。低于今年的会忽略。今年年级每年 1 月 1 日自动升一级。</small></label>`;}
function bookableStudents(extra){const ids=new Set((extra||[]).map(id=>String(id)));return (state.students||[]).filter(s=>ids.has(String(s.id))||(!s.no_course && (s.study_status||'studying')!=='graduated'));}
function parentCards(){return `<section class="child-cards">${state.students.length?studentGroups().map(group=>{const s=group[0];const empty=group.every(account=>account.no_course);return `<article class="child-card"><div class="child-top"><span class="student-icon">${userHTML(nameInitial(s.name))}</span><div><h2>${userHTML(s.name)} ${studyTag(s)}</h2><p>${userHTML(shownLevel(s)||s.grade||'')} · ${empty?'未选课 / 请添加课程':'各科余额独立计算'}</p></div></div>${empty?'<p class="muted">还没有在读的课。</p>':group.map(account=>`<section class="child-course"><h3>${userHTML(shownLevel(account))} ${userHTML(account.subject_name||account.course)} ${typeof typeBadge==='function'?typeBadge(account.course_type_name):''}</h3><div class="child-balance"><div><strong>${(account.billing_unit||'lesson')==='hour'?`剩余 ${fmt(regularHours(account))} 小时`:`剩余 ${fmt(regularHours(account))} 节`}</strong><span class="credit-split">赠送${unitFor(account)} ${fmt(account.gift_balance||0)}</span></div><span class="badge ${needsRenewal(account)?'low':''}">${needsRenewal(account)?'请续费':'余额充足'}</span></div><button class="action" data-child="${account.id}" style="margin-top:16px">查看余额明细 →</button></section>`).join('')}</article>`;}).join(''):'<div class="panel empty">还没有关联的学生，请联系老师。</div>'}</section>`;}
function studentGroups(){
 const groups=new Map();
 state.students.forEach(s=>{const key=s.profile_id||s.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(s);});
 return [...groups.values()];
}
function studentToneName(name){
 if(typeof teacherTone==='function') return teacherTone(name);
 const n=(name||'').toLowerCase();
 if(n.includes('helen')) return 'helen';
 if(n.includes('vincent')) return 'vincent';
 if(n.includes('angela')) return 'angela';
 if(n.includes('kelsey')) return 'kelsey';
 if(n.includes('ethan')) return 'ethan';
 if(n.includes('christina')) return 'christina';
 return 'other';
}
function teacherForAccounts(accounts){
 const ids=new Set(accounts.map(account=>String(account.id)));
 const lesson=(state.lessons||[]).find(item=>(item.students||[]).some(student=>ids.has(String(student.id))) && item.status!=='cancelled');
 return lesson?.teacher_name||'待定';
}
function accountStatus(account, group){
 if((account.balance||0)<=0 && !sameSubjectCovered(account, group||[])) return '欠费';
 if(needsRenewal(account)) return '该续费';
 return '正常';
}
function legacyMark(group){
 const names=[];
 group.forEach(account=>{
  const listed=Array.isArray(account.legacy_subjects)?account.legacy_subjects:(account.legacy?[account.subject_name||account.course]:[]);
  listed.forEach(name=>{if(name && !names.includes(name)) names.push(name);});
 });
 return names.length?`<span class="legacy-badge">老学员 · ${names.map(userHTML).join('、')}</span>`:'';
}
function studentFold(group, admin){
 const person=group[0];
 const ids=new Set(group.map(account=>String(account.id)));
 const lessons=(state.lessons||[]).filter(lesson=>(lesson.students||[]).some(student=>ids.has(String(student.id)))).sort((a,b)=>b.starts_at.localeCompare(a.starts_at));
 const payments=(state.entries||[]).filter(entry=>ids.has(String(entry.student_id)) && ['credit','refund'].includes(entry.kind));
 const money=cents=>typeof cashFmt==='function'?cashFmt(cents):'$'+((cents||0)/100).toFixed(2);
 const methods=typeof paymentNames==='object'?paymentNames:{};
 const empty=group.every(account=>account.no_course);
 const actions=admin?`<div class="profile-actions"><button class="btn" data-profile="${person.id}" type="button">编辑资料</button><button class="btn" data-guardian="${person.id}" type="button">家长账号</button><button class="btn" data-add-course="${person.id}" type="button">添加课程</button>${state.user.role==='owner'?`<button class="btn refund-action" data-delete-student="${person.id}" type="button">删除并归档</button>`:''}</div>`:'';
 const enrolments=group.map(account=>{
  const packs=(account.credit_batches||[]).map(batch=>packLine(batch, money)).join('')||'<li>还没有课时包。</li>';
  const subjectLabel=account.subject_name||account.course||'本科目';
  const price=state.user.role==='owner'&&account.course_type_name?`<form class="legacy-price" data-legacy-form="${account.id}"><p class="footnote">${account.legacy?`<span class="legacy-badge">老学员 · ${userHTML(subjectLabel)}</span> `:''}2027 价目 ${account.list_hourly_cents==null?'还没有':'$'+(account.list_hourly_cents/100).toFixed(2)+' / 小时'}。留空并保存，这一科就改回价目。</p><label class="field">${userHTML(subjectLabel)} 每小时价格 AUD<input name="hourly" inputmode="decimal" value="${account.custom_hourly_cents==null?'':(account.custom_hourly_cents/100).toFixed(2)}" placeholder="用 2027 价目"></label><button class="btn" type="submit">保存价格</button></form>`:'';
  return `<article class="trow"><div class="grow"><b>${userHTML(shownLevel(account))} ${userHTML(account.subject_name||account.course)}</b> ${typeof typeBadge==='function'?typeBadge(account.course_type_name):''}<small>剩余 ${fmt(regularHours(account))} ${unitFor(account)} · 赠送 ${fmt(account.gift_balance||0)}</small></div><div class="num">${accountStatus(account, group)}</div></article>${price}<ul class="pack-list">${packs}</ul>${admin?`<p class="profile-actions"><button class="btn" data-credit="${account.id}" type="button">充值</button><button class="btn" data-refund="${account.id}" type="button">退课退款</button><button class="btn" data-lesson="${account.id}" type="button">排课</button><button class="btn" data-study-level="${account.id}" type="button">学习年级</button><button class="btn" data-relink-course="${account.id}" type="button">把已停课的以后课移过来</button>${state.user.role==='owner'?`<button class="btn refund-action" data-stop-course="${account.id}" type="button">停课/删除这门课</button>`:''}</p>`:''}`;
 }).join('');
 const stopped=(state.archived_students||[]).filter(account=>account.profile_id===person.profile_id);
 const stoppedHtml=stopped.length?`<h3>已停的课</h3>${stopped.map(account=>`<article class="trow"><div class="grow"><b>${userHTML(account.subject_name||account.course)}</b><small>已停课${account.balance?` · 还剩 ${fmt(account.balance)} ${unitFor(account)}`:''}</small></div><button class="btn" data-restore-course="${account.id}" type="button">恢复这门课</button></article>`).join('')}`:'';
 const history=lessons.slice(0,12).map(lesson=>`<article class="trow t-${studentToneName(lesson.teacher_name)}"><div class="grow">${escapeHTML(lesson.starts_at.replace('T',' '))} ${typeof typeBadge==='function'?typeBadge(lesson.course_type_name):''}<small>${userHTML(lesson.subject_name||lesson.title)} · ${userHTML(lesson.teacher_name)}</small></div><div class="num">${lesson.status==='completed'?'已上了':lesson.status==='cancelled'?'已取消':'待上课'}</div></article>`).join('')||'<p class="muted">还没有课。</p>';
 const pays=payments.slice(0,12).map(entry=>`<article class="trow"><div class="grow">${escapeHTML(entry.lesson_date)} · ${entry.kind==='credit'?'收款':'退款'}<small>${userHTML(entry.note||entry.course||'')}</small></div><div class="num">${entryMoney(entry)}<small>${escapeHTML(methods[entry.payment_method]||'')}</small></div></article>`).join('')||'<p class="muted">还没有收款或退款。</p>';
 const recent=(state.entries||[]).filter(entry=>ids.has(String(entry.student_id)) && entry.kind==='lesson').slice(0,8).map(entry=>`<article class="trow"><div class="grow">${escapeHTML(entry.lesson_date)} · ${userHTML(entry.student_name)}<small>${userHTML(entry.subject_name||entry.course||'')}</small></div><div class="num">${entry.delta>0?'+':'−'}${fmt(Math.abs(entry.delta))} ${unitFor(entry)}</div></article>`).join('')||'<p class="muted">还没有这名学生的课时记录。</p>';
 return `<p class="muted">${userHTML(person.parent_name||'未填家长')} · ${userHTML(person.contact_phone||person.phone||'')}${person.birthday?' · '+escapeHTML(person.birthday):''} ${studyTag(person)}</p>${actions}<h3>报名与课时包</h3>${empty?'<p>未选课 / 请添加课程</p>':enrolments}${stoppedHtml}<h3>最近课时记录</h3>${recent}<h3>上课记录</h3>${history}<h3>收款</h3>${pays}<h3>备注</h3><p>${person.notes?userHTML(person.notes):'没有备注。'}</p><p><button class="action" data-history="${person.id}" type="button">全部余额明细 →</button> ${state.user.role==='owner'?`<button class="action" data-vouchers="${person.id}" type="button">单据 →</button>`:''}</p>`;
}
function renderStudents(){
 const admin=['owner','admin'].includes(state.user.role);
 const groups=studentGroups().filter(group=>studyFilter==='all'||(group[0].study_status||'studying')===studyFilter).map(group=>group.filter(s=>s.no_course||!admin||studentStatus==='all'||(studentStatus==='renewal'?needsRenewal(s):!needsRenewal(s)))).filter(group=>group.length&&group.some(s=>`${s.name} ${s.course} ${s.subject_name||''} ${s.phone} ${s.grade||''}`.toLowerCase().includes(search.toLowerCase())));
 $('#student-list').innerHTML=groups.length?groups.map(group=>{
  const person=group[0];
  const teacher=teacherForAccounts(group);
  const tone=studentToneName(teacher);
  const empty=group.every(account=>account.no_course);
  const subjects=empty?'未选课 / 请添加课程':group.map(account=>[shownLevel(account), account.subject_name||account.course, account.course_type_name].filter(Boolean).join(' · ')).join('，');
  const balance=empty?'—':group.map(account=>`${fmt(regularHours(account))} ${unitFor(account)}`).join(' · ');
  const health=String(person.health_notes||'').trim();
  const legacy=legacyMark(group);
  const pack=group.flatMap(account=>account.credit_batches||[]).filter(batch=>batch.pack_label).slice(-1)[0];
  return `<article class="pay-card t-${tone}"><div class="avatar">${userHTML(nameInitial(person.name))}</div><div style="flex:1"><h2>${userHTML(person.name)} ${studyTag(person)}${legacy?` ${legacy}`:''}${health?' <span class="health-badge">健康备注</span>':''}</h2><p class="muted">${userHTML(subjects)}</p><p class="muted">${userHTML(teacher)}</p>${pack&&!empty?`<p class="pack-now">${escapeHTML(pack.pack_label)}</p>`:''}</div><div><div class="muted">${empty?'课程':'剩余课时'}</div><strong>${balance}</strong></div><div><div class="muted">状态</div><strong>${empty?'未选课':group.some(account=>accountStatus(account, group)==='欠费')?'欠费':group.some(needsRenewal)?'该续费':'正常'}</strong></div>${admin?(empty?`<button class="btn" data-add-course="${person.id}" type="button">添加课程</button>`:`<button class="btn" data-credit="${person.id}" type="button">充值</button>`):''}</article><details class="pay-fold"><summary>查看档案</summary>${studentFold(group, admin)}</details>`;
 }).join(''):`<div class="panel empty">${search||studentStatus!=='all'?'没有匹配的学生。':'还没有学生，点击「添加学生」开始。'}</div>`;
 if(state.user.role==='owner'){
  const archived=state.archived_students||[];
  $('#student-list').insertAdjacentHTML('beforeend',`<details class="panel" style="margin-top:20px;padding:20px"><summary>已停的课（${archived.length}）</summary>${archived.map(account=>`<div class="profile-heading" style="padding:16px 0"><div><strong>${userHTML(account.name)}</strong><div>${userHTML(account.subject_name||account.course)}${balanceSplit(account)}</div></div><button class="btn" data-restore-course="${account.id}">恢复这门课</button></div>`).join('')||'<p>暂无已停的课。</p>'}</details>`);
 }
 document.querySelectorAll('#student-list .pay-card').forEach(card=>card.onclick=()=>{const fold=card.nextElementSibling; if(fold&&fold.tagName==='DETAILS') fold.open=!fold.open;});
 document.querySelectorAll('[data-delete-student]').forEach(b=>b.onclick=event=>{event.stopPropagation(); deleteProfileModal('student',state.students.find(s=>s.id==b.dataset.deleteStudent));});
 document.querySelectorAll('[data-profile]').forEach(b=>b.onclick=event=>{event.stopPropagation(); profileModal(b.dataset.profile);});
 document.querySelectorAll('[data-guardian]').forEach(b=>b.onclick=event=>{event.stopPropagation(); guardianModal(b.dataset.guardian);});
 document.querySelectorAll('[data-add-course]').forEach(b=>b.onclick=event=>{event.stopPropagation(); addCourseModal(b.dataset.addCourse);});
 document.querySelectorAll('[data-study-level]').forEach(b=>b.onclick=event=>{event.stopPropagation(); const account=state.students.find(s=>s.id==b.dataset.studyLevel); if(!account) return; modal('学习年级',`<div class="form-context">${userHTML(account.name)} · ${userHTML(account.subject_name||account.course)}<br>今年显示 ${userHTML(account.level_label||'还没有年级')}。低于今年的学习年级不会使用。</div>${studyLevelSelect(account.study_level)}`,'保存',async data=>{await api('students/course/level',{student_id:account.id,study_level:data.study_level||''}); toast('学习年级已保存。');});});
 document.querySelectorAll('[data-lesson]').forEach(b=>b.onclick=event=>{event.stopPropagation(); scheduleModal(null,b.dataset.lesson);});
 document.querySelectorAll('[data-relink-course]').forEach(b=>b.onclick=async event=>{event.stopPropagation(); try{const result=await api('students/course/relink',{student_id:Number(b.dataset.relinkCourse)}); toast(result.moved?`已把 ${result.moved} 节以后的课移到这门课。`:'没有可以移动的以后的课。'); if(result.moved) await refresh();}catch(error){toast(error.message);}});
 document.querySelectorAll('[data-refund]').forEach(b=>b.onclick=event=>{event.stopPropagation(); refundModal(b.dataset.refund);});
 document.querySelectorAll('[data-credit]').forEach(b=>b.onclick=event=>{event.stopPropagation(); entryModal('credit',b.dataset.credit);});
 document.querySelectorAll('[data-stop-course]').forEach(b=>b.onclick=event=>{event.stopPropagation(); stopCourseModal(b.dataset.stopCourse);});
 document.querySelectorAll('[data-restore-course]').forEach(b=>b.onclick=event=>{event.stopPropagation(); const account=(state.archived_students||[]).find(s=>s.id==b.dataset.restoreCourse); modal('恢复这门课',`<div class="form-context">${userHTML(account.name)} · ${userHTML(account.subject_name||account.course)}<br>恢复后可以再排课和充值。已上的课和账目都还在。</div>`,'确认恢复',async()=>{await api('profiles/restore',{id:account.id});toast('这门课已恢复。');});});
 document.querySelectorAll('[data-legacy-form]').forEach(form=>form.onsubmit=async event=>{
  event.preventDefault();
  event.stopPropagation();
  const hourly=new FormData(form).get('hourly');
  try{await api('prices/legacy',{student_id:Number(form.dataset.legacyForm),hourly,clear:!String(hourly||'').trim()}); toast(String(hourly||'').trim()?'价格已保存。':'已改回 2027 价目。'); await refresh();}catch(error){toast(error.message);}
 });
 document.querySelectorAll('[data-history]').forEach(b=>b.onclick=event=>{event.stopPropagation(); selected=b.dataset.history;view='records';render();});
 document.querySelectorAll('[data-vouchers]').forEach(b=>b.onclick=event=>{event.stopPropagation(); voucherStudent=b.dataset.vouchers; view='vouchers'; render();});
}
function stopCourseModal(id){
 const account=state.students.find(s=>s.id==id);
 if(!account) return;
 const left=account.balance||0;
 const warn=left>0?`<p class="error">这门课还剩 ${fmt(left)} ${unitFor(account)}。可以先退费（退款金额可以填 0），也可以直接停课。余额会留在这门已停的课上。</p>`:'';
 modal('停课/删除这门课',`<div class="form-context">${userHTML(account.name)} · ${userHTML(account.subject_name||account.course)}<br>同一学生的其他科目不受影响。已上的课、课后记录和账目保留，以后还没上的课会取消。没有任何记录的课会直接删除。</div>${warn}`,'确认停课',async()=>{const result=await api('students/course/stop',{student_id:account.id}); toast(result.deleted?'这门课已删除。':'这门课已停，历史记录还在。');},true);
}
function addCourseModal(id){
 const s=state.students.find(s=>s.id==id),existing=state.students.filter(x=>x.profile_id===s.profile_id).map(x=>x.course);
 const choices=(state.subjects||[]).filter(o=>o.active&&!existing.includes(o.name));
 if(!choices.length){toast('没有可添加的科目。停用的科目可以在设置里重新打开。');return;}
 modal('添加学生科目',`<div class="form-context">${userHTML(s.name)} · 目前只使用数学和英语。新科目从 0 ${unitFor(s)}开始。如果以前停过同一科目，以后还没上的课会自动改挂到这门新课。</div><label class="field">科目<select name="subject_id" required><option value="">请选择科目</option>${choices.map(o=>`<option value="${o.id}">${escapeHTML(o.name)}</option>`).join('')}</select></label><label class="field">课型${catalogSelect(state.course_types,'course_type_id','','请选择课型')}</label>${studyLevelSelect('')}`,'添加科目',async data=>{const result=await api('students/course',{...data,student_id:s.id});toast(result.moved?`新科目已添加，${result.moved} 节以后的课已改挂过来。`:'新科目已添加，可单独充值课时。');});
}
function renderRecords(){
 let rows=state.entries.filter(e=>!selected||String(e.student_id)===selected);if(view==='overview')rows=rows.slice(0,5);
 const admin=['owner','admin'].includes(state.user.role);
 $('#records-list').innerHTML=rows.length?`<div class="panel table-wrap"><table><thead><tr><th>日期 / 学生</th><th>类型</th><th>余额变动</th><th>备注</th><th>${admin?'登记人 / 操作':'登记人'}</th></tr></thead><tbody>${rows.map(e=>`<tr><td>${escapeHTML(e.lesson_date)}<div class="muted" style="font-size:12px;margin-top:6px">${userHTML(e.student_name)} · ${userHTML(e.course)}</div></td><td><span class="badge ${e.kind==='lesson'?'low':''}">${{lesson:'上课扣除',credit:'充值'+unitFor(e),refund:'退课退款',reversal:'撤销返还 / 扣回'}[e.kind]}</span>${e.reversed_by?'<div class="muted" style="font-size:12px;margin-top:6px">已撤销</div>':''}</td><td class="${e.delta>0?'positive':'negative'}">${e.delta>0?'+':'−'}${fmt(Math.abs(e.delta))} ${unitFor(e)}</td><td class="note-cell">${userHTML(e.note)||'—'}${creditBreakdown(e)}</td><td>${userHTML(e.actor_name)}${state.user.role==='owner'?`<button class="action" data-edit-entry="${e.id}">编辑单据</button>`:''}${admin&&e.kind!=='reversal'&&!e.reversed_by?`<button class="action" data-reverse="${e.id}">撤销</button>`:''}</td></tr>`).join('')}</tbody></table></div>`:'<div class="panel empty">暂无课时变动记录。</div>';
 document.querySelectorAll('[data-edit-entry]').forEach(b=>b.onclick=()=>editEntryModal(state.entries.find(e=>e.id==b.dataset.editEntry)));
 document.querySelectorAll('[data-reverse]').forEach(b=>b.onclick=()=>reverseModal(b.dataset.reverse));
}
function modal(title, body, submit, onsubmit, danger=false){
 lastFocus=document.activeElement;$('#modal').classList.remove('wide');
 $('#modal-body').innerHTML=`<form id="modal-form" class="modal-inner"><div class="modal-head"><h2 id="modal-title">${title}</h2><button type="button" class="close" aria-label="关闭">×</button></div>${body}<div id="modal-error" class="error" role="alert"></div><div class="modal-footer"><button type="button" class="btn cancel">取消</button><button type="submit" class="btn ${danger?'danger':'primary'}">${submit}</button></div></form>`;
 const close=()=>$('#modal').close();$('.close').onclick=close;$('.cancel').onclick=close;
 $('#modal-form').onsubmit=async e=>{e.preventDefault();const button=e.currentTarget.querySelector('[type=submit]');e.currentTarget.querySelectorAll('button').forEach(b=>b.disabled=true);$('#modal-error').textContent='';try{await onsubmit(Object.fromEntries(new FormData(e.currentTarget)));$('#modal').close();await refresh();}catch(err){$('#modal-error').textContent=err.message;$('#modal-form').querySelectorAll('button').forEach(b=>b.disabled=false);}};
 $('#modal').showModal();
}
$('#modal').addEventListener('close',()=>lastFocus?.isConnected&&lastFocus.focus({preventScroll:true}));
function entryModal(kind,id){
 if(!state.students.length){toast('请先添加学生。');return studentModal();}
 const isLesson=kind==='lesson', request_id=crypto.randomUUID();
 modal(isLesson?'登记上课':'充值课时',`<label class="field">学生<select name="student_id" id="entry-student">${state.students.filter(s=>!s.no_course).map(s=>`<option data-user-content value="${s.id}" ${id==s.id?'selected':''}>${escapeHTML(s.name)} · ${escapeHTML(s.subject_name||s.course)} · ${escapeHTML(s.level_label||s.grade||'')}</option>`).join('')}</select></label><div class="form-context" id="balance-context"></div>${isLesson?'':`<div id="package-presets" class="package-presets"></div><input type="hidden" name="product"><input type="hidden" name="lesson_minutes"><input type="hidden" name="terms">`}<div class="two-cols"><label class="field"><span id="entry-unit-label"></span><input name="amount" id="amount" type="number" min="${isLesson?'0.01':'0'}" max="10000" step="0.01" value="${isLesson?'1':'10'}" required></label><label class="field">${isLesson?'上课日期':'充值日期'}<input name="date" type="date" value="${today()}" max="${today()}" required></label></div>${isLesson?`<div class="quick">${[0.5,1,1.5,2].map(n=>`<button type="button" data-amount="${n}">${n} 课时</button>`).join('')}</div>`:`<label class="field"><span id="entry-gift-label"></span><input name="gift_amount" id="gift-amount" type="number" min="0" max="10000" step="0.01" value="0" required></label><div class="form-context" id="entry-unit-help"></div>${paymentFields()}`}<label class="field">备注（选填）<textarea name="note" id="entry-note" maxlength="300" placeholder="${isLesson?'例如：补录历史课时':'自定义金额留给旧价学生'}"></textarea></label>`,isLesson?'确认扣除':'确认充值',async data=>{await api('entries',{...data,kind,request_id});toast(isLesson?'上课已登记，课时已扣除。':'课时已充值。');});
 const update=()=>{const s=state.students.find(s=>s.id==$('#entry-student').value),amount=Math.round(Number($('#amount').value||0)*100),gift=Math.round(Number($('#gift-amount')?.value||0)*100),paid=regularHours(s),gifts=s.gift_balance||0;const afterPaid=isLesson?Math.max(0,paid-amount):paid+amount,afterGift=isLesson?gifts-Math.max(0,amount-paid):gifts+gift;$('#modal-title').textContent=isLesson?'登记上课':'充值'+unitFor(s);$('#entry-unit-label').textContent=(isLesson?'扣除':'充值')+unitFor(s);if($('#entry-gift-label'))$('#entry-gift-label').textContent='赠送'+unitFor(s);if($('#entry-unit-help'))$('#entry-unit-help').textContent=unitFor(s)+'用完后再使用赠送'+unitFor(s)+'，不足 3 '+unitFor(s)+'时提醒续费。';document.querySelectorAll('[data-amount]').forEach(b=>b.textContent=b.dataset.amount+' '+unitFor(s));$('#balance-context').innerHTML=`当前：${unitFor(s)} <strong>${fmt(paid)}</strong> · 赠送${unitFor(s)} <strong>${fmt(gifts)}</strong><br>${isLesson?'扣除':'充值'}后：${unitFor(s)} <strong>${fmt(afterPaid)}</strong> · 赠送${unitFor(s)} <strong>${fmt(afterGift)}</strong>`;};
 async function loadPresets(){
 const host=$('#package-presets');
 if(!host||isLesson) return;
 const studentId=$('#entry-student').value;
 host.innerHTML='正在带出这个年级的课时包…';
 try{
  const day=document.querySelector('#modal-form [name=date]')?.value||'';
  const offer=await api('prices/presets?student_id='+encodeURIComponent(studentId)+(day?'&date='+encodeURIComponent(day):''));
  if(!offer.packages?.length){host.innerHTML=`<p>${escapeHTML(offer.reason||'可以自己填节数。')}</p><button type="button" class="btn" id="custom-pack">自定义金额</button>`; $('#custom-pack').onclick=()=>{$('#amount').focus();}; return;}
  host.innerHTML=`<p><b>${escapeHTML(offer.level)} · ${escapeHTML(offer.course_type)}</b>${offer.source==='custom'?' · 老学员锁定价':''}</p><div class="pack-cards">${offer.packages.map((item,index)=>`<button type="button" class="pack-card" data-pack="${index}"><strong>${escapeHTML(item.label)}</strong><small>${escapeHTML(item.validity||'')}${item.gift_lessons?` · 赠 ${item.gift_lessons} 节，付费课用完后才能用`:''}</small></button>`).join('')}</div><p class="footnote" id="pack-chosen">点一个课时包，再确认充值。</p>`;
  host.querySelectorAll('[data-pack]').forEach(button=>button.onclick=()=>{
   const item=offer.packages[Number(button.dataset.pack)];
   host.querySelectorAll('.pack-card').forEach(card=>card.classList.remove('selected'));
   button.classList.add('selected');
   $('#amount').value=item.paid_lessons;
   if($('#gift-amount')) $('#gift-amount').value=item.gift_lessons;
   const cash=document.querySelector('[name=cash_amount]');
   if(cash) cash.value=(item.total_cents/100).toFixed(2);
   const note=$('#entry-note');
   if(note) note.value=`${offer.level} · ${offer.course_type} · ${item.label}`;
   const product=document.querySelector('[name=product]');
   if(product) product.value=item.product;
   const minutes=document.querySelector('[name=lesson_minutes]');
   if(minutes) minutes.value=item.lesson_minutes;
   const terms=document.querySelector('[name=terms]');
   if(terms) terms.value=(item.terms||[]).join(',');
   const chosen=$('#pack-chosen');
   if(chosen) chosen.textContent=`增加 ${item.paid_lessons} 节付费${item.gift_lessons?` + ${item.gift_lessons} 节赠送`:''}，学费 ${moneyAud(item.total_cents)}。确认充值即可。`;
   update();
  });
 }catch(error){host.textContent=error.message;}
}
$('#entry-student').onchange=()=>{update(); loadPresets();};const dateBox=document.querySelector('#modal-form [name=date]'); if(dateBox) dateBox.onchange=()=>{update(); loadPresets();};$('#amount').oninput=update;if($('#gift-amount'))$('#gift-amount').oninput=update;document.querySelectorAll('[data-amount]').forEach(b=>b.onclick=()=>{$('#amount').value=b.dataset.amount;update();});update(); loadPresets();
}
function studentModal(){modal('添加学生',`<label class="field">学生姓名<input name="name" required maxlength="40" placeholder="例如：陈一诺"></label>${profileFields()}${billingField()}<div class="profile-group"><label class="field">科目${catalogSelect(state.subjects,'subject_id','','请选择科目')}</label><label class="field">课型${catalogSelect(state.course_types,'course_type_id','','请选择课型')}</label><div class="form-context" id="offer-preview">选择年级和课型后，这里显示这个年级的课时包。科目不改变价格。</div><label class="field">家长初始密码（新手机号才需要）<input name="password" type="password" minlength="10" maxlength="128" autocomplete="new-password" placeholder="至少 10 位"><small>不填手机号也可以先建档，以后再补家长账号。</small></label></div>`,'创建学生',async data=>{await api('students',data);toast('学生已添加。');}); bindProfileFields(); const refreshOffer=()=>{const level=$('#year-level')?.value, type=document.querySelector('[name=course_type_id]')?.value; if(level&&type) showOffer('level='+encodeURIComponent(level)+'&course_type_id='+encodeURIComponent(type), $('#offer-preview'));}; $('#year-level').onchange=refreshOffer; document.querySelector('[name=course_type_id]').onchange=refreshOffer;}
function reverseModal(id){const e=state.entries.find(e=>e.id==id),request_id=crypto.randomUUID();modal('撤销这笔记录？',`<div class="form-context">${userHTML(e.student_name)} · ${escapeHTML(e.lesson_date)}<br>原记录：${e.kind==='refund'?'退课退款':e.delta>0?'充值':'扣除'} ${fmt(Math.abs(e.delta))} ${unitFor(e)}。<br>撤销后会${e.delta>0?'扣回':'返还'}相应课时，原记录仍会保留。涉及金额时会产生记账纠错，不代表实际收款或退款。${creditBreakdown(e)}</div><label class="field">撤销原因<textarea name="note" required maxlength="250" placeholder="例如：重复登记，返还课时"></textarea></label>`,'确认撤销',async data=>{await api('reverse',{...data,entry_id:id,request_id});toast('已撤销，课时余额已更新。');},true);}
function passwordModal(){modal('修改密码',`<label class="field">当前密码<input name="old" type="password" autocomplete="current-password" required maxlength="128"></label><label class="field">新密码<input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" required><small>至少 10 位，修改成功后需重新登录。</small></label>`,'保存新密码',async data=>{await api('password',data);toast('密码已修改，请重新登录。');});}

function yearLevels(){return ['Prep','Y1','Y2','Y3','Y4','Y5','Y6','Y7','Y8','Y9','Y10','Y11','Y12'];}
function ageText(birthday){
 if(!birthday||!state.today) return '';
 const born=new Date(birthday+'T12:00:00Z'), now=new Date(state.today+'T12:00:00Z');
 let years=now.getUTCFullYear()-born.getUTCFullYear();
 const month=now.getUTCMonth()-born.getUTCMonth();
 if(month<0||(month===0&&now.getUTCDate()<born.getUTCDate())) years--;
 return years>=0?`（${years} 岁）`:'';
}
function profileFields(s={}){
 const current=s.level_code||s.grade||'';
 const extra=current&&!yearLevels().includes(current)?`<option value="${escapeHTML(current)}" selected>${escapeHTML(current)}</option>`:'';
 const phone=String(s.phone||'').startsWith('pending-')?'':(s.phone||'');
 const checked=name=>s[name]?'checked':'';
 return `<label class="field year-level">2027 年级<select name="grade" id="year-level" required><option value="">请选择年级</option>${extra}${yearLevels().map(level=>`<option value="${level}" ${current===level?'selected':''}>${level}</option>`).join('')}</select><small>这里填的是 2027 年级。卡片显示今年年级，每年 1 月 1 日自动升一级。${s.level_label?`今年是 ${escapeHTML(s.level_label)}。`:''}充值按充值日期那一年的年级计价；某一科可以另填更高的学习年级。</small></label>
<details class="profile-group" open><summary>学生</summary><label class="field">出生日期<input type="date" name="birthday" max="${state.today}" value="${escapeHTML(s.birthday||'')}" data-birthday><small id="age-note">${ageText(s.birthday)}</small></label><label class="field">学校<input name="school" maxlength="80" value="${escapeHTML(s.school||'')}"></label></details>
<details class="profile-group"><summary>家长</summary><label class="field">家长姓名<input name="parent_name" maxlength="40" value="${escapeHTML(s.parent_name||'')}"></label><label class="field">电话<input name="phone" type="tel" maxlength="24" value="${escapeHTML(phone)}"></label><label class="field">邮箱<input name="parent_email" type="email" maxlength="80" value="${escapeHTML(s.parent_email||'')}"></label></details>
<details class="profile-group"><summary>紧急联系人（不是家长）</summary><label class="field">姓名<input name="emergency_name" maxlength="40" value="${escapeHTML(s.emergency_name||'')}"></label><label class="field">关系<input name="emergency_relation" maxlength="40" value="${escapeHTML(s.emergency_relation||'')}"></label><label class="field">电话<input name="emergency_phone" type="tel" maxlength="24" value="${escapeHTML(s.emergency_phone||'')}"></label></details>
<details class="profile-group"><summary>健康</summary><label class="field">过敏、疾病、需要老师注意的事项<textarea name="health_notes" maxlength="2000">${escapeHTML(s.health_notes||'')}</textarea></label></details>
<details class="profile-group"${s.id?' open':''}><summary>${s.id?'入学档案':'报读'}</summary>${s.id&&state.user?.role==='owner'?`<fieldset class="student-picker"><legend>在读状态</legend><label><input type="radio" name="study_status" value="studying" ${(s.study_status||'studying')!=='graduated'?'checked':''}> 在读</label><label><input type="radio" name="study_status" value="graduated" ${(s.study_status||'studying')==='graduated'?'checked':''}> 已毕业</label></fieldset><p class="footnote">已毕业的学生仍留在档案和历史里，排课名单里不再出现。学生列表默认只显示在读。</p>`:''}<p class="footnote">课型只用一对一、一对二、小班课。科目目前只用数学和英语。</p></details>
<details class="profile-group"><summary>拍照 / 视频同意</summary><label class="report-choice"><input type="checkbox" name="photo_homework" ${checked('photo_homework')}>① 作业试卷（隐去姓名）用于宣传</label><label class="report-choice"><input type="checkbox" name="photo_class" ${checked('photo_class')}>② 上课照片 / 视频（不露脸）</label><label class="report-choice"><input type="checkbox" name="photo_face" ${checked('photo_face')}>③ 露脸照片 / 视频</label><label class="report-choice"><input type="checkbox" name="photo_none" ${checked('photo_none')}>④ 均不同意</label><div class="two-cols"><label class="field">同意日期<input type="date" name="consent_on" value="${escapeHTML(s.consent_on||'')}"></label><label class="field">撤回日期<input type="date" name="consent_withdrawn_on" value="${escapeHTML(s.consent_withdrawn_on||'')}"></label></div></details>
<details class="profile-group"><summary>确认</summary><label class="report-choice"><input type="checkbox" name="handbook_read" ${checked('handbook_read')}>已阅读家长须知</label><label class="field">签字日期<input type="date" name="signed_on" value="${escapeHTML(s.signed_on||'')}"></label></details>
<details class="profile-group"><summary>更多报名资料</summary><p class="footnote">其他报名项以后加在这里。</p><label class="field">内部备注<textarea name="notes" maxlength="2000">${escapeHTML(s.notes||'')}</textarea></label></details>`;
}
function bindProfileFields(){
 const box=document.querySelector('[data-birthday]');
 if(box) box.oninput=()=>{const note=document.querySelector('#age-note'); if(note) note.textContent=ageText(box.value);};
 const none=document.querySelector('[name=photo_none]');
 if(!none) return;
 none.onchange=()=>{if(none.checked) document.querySelectorAll('[name=photo_homework],[name=photo_class],[name=photo_face]').forEach(box=>{box.checked=false;});};
 document.querySelectorAll('[name=photo_homework],[name=photo_class],[name=photo_face]').forEach(box=>box.onchange=()=>{if(box.checked) none.checked=false;});
}
function packLine(batch, money){
 const used=((batch.purchased||0)+(batch.gifted||0))-((batch.paid_left||0)+(batch.gift_left||0));
 const price=batch.total_cents!=null?` · 总额 ${money(batch.total_cents)}`:'';
 return `<li>${batch.pack_label?escapeHTML(batch.pack_label):(batch.legacy?'原有课时':escapeHTML(batch.credited_on||'课时包'))}${price} · 购买 ${fmt(batch.purchased||0)} · 赠送 ${fmt(batch.gifted||0)} · 已用 ${fmt(used)} · 还剩 ${fmt((batch.paid_left||0)+(batch.gift_left||0))}</li>`;
}
function moneyAud(cents){return '$'+((cents||0)/100).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2});}
async function showOffer(query, host){
 if(!host) return;
 host.innerHTML='正在按年级和课型取价…';
 try{
  const offer=await api('prices/presets?'+query);
  if(!offer.packages?.length){host.innerHTML=escapeHTML(offer.reason||'还没有匹配的课时包。'); return;}
  host.innerHTML=`<b>${escapeHTML(offer.level)} · ${escapeHTML(offer.course_type)}</b> 已锁定 $${((offer.hourly_cents||0)/100).toFixed(2)} / 小时${offer.source==='custom'?'（这位学生有单独旧价）':''}<br>${offer.packages.map(item=>`${escapeHTML(item.label)} ${moneyAud(item.total_cents)}${item.gift_lessons?` + 赠 ${item.gift_lessons} 节`:''}`).join('<br>')}<br><span class="muted">${escapeHTML(offer.packages[0].validity||'')}</span>`;
 }catch(error){host.textContent=error.message;}
}
function profileModal(id){
 const s=state.students.find(s=>s.id==id);
 modal('编辑资料',`<label class="field">学生姓名<input name="name" required maxlength="40" value="${escapeHTML(s.name)}"></label>${profileFields(s)}${billingField(s)}<p class="footnote">价格只看年级和课型。科目不改变价格。</p>`,'保存档案',async data=>{await api('students/profile',{...data,student_id:s.id});toast('学生档案已更新。');}); bindProfileFields();
}
function guardianModal(id){
 const s=state.students.find(s=>s.id==id),children=studentGroups().map(g=>g[0]).filter(x=>x.parent_id===s.parent_id);
 modal('编辑家长账号',`<div class="form-context">此账号关联：${children.map(x=>userHTML(x.name)).join('、')}。修改将对这些孩子共用的家长账号生效。</div><label class="field">家长姓名<input name="parent_name" required maxlength="40" value="${escapeHTML(s.parent_name)}"></label><label class="field">登录手机号<input type="tel" name="phone" required maxlength="24" value="${escapeHTML(s.phone)}"></label><label class="field">联系手机号（选填）<input type="tel" name="contact_phone" maxlength="24" value="${escapeHTML(s.contact_phone||'')}"></label><label class="field">重置密码（选填）<input name="password" type="password" minlength="10" maxlength="128" autocomplete="new-password"><small>留空则保留原密码。修改登录手机号或重置密码后，家长需重新登录。</small></label>`,'保存家长账号',async data=>{await api('students/guardian',{...data,student_id:s.id});toast('家长账号已更新。');});
}

function regularHours(s){return s.paid_balance??s.balance;}
function needsRenewal(s){return regularHours(s)<300;}
function balanceSplit(s){return `<span class="credit-split">${unitFor(s)} ${fmt(regularHours(s))} · 赠送${unitFor(s)} ${fmt(s.gift_balance||0)}</span>`;}
function creditBreakdown(e){if(!e.split_known)return '';return `<small class="credit-split">${unitFor(e)} ${signedUnits(e.paid_delta)} · 赠送${unitFor(e)} ${signedUnits(e.gift_delta)}${e.gift_void?` · ${e.gift_void>0?'作废赠课':'恢复赠课'} ${fmt(Math.abs(e.gift_void))}`:''}</small>`;}

function deleteProfileModal(kind,item){
 if(state.user.role!=='owner')return;
 if(kind==='student'){modal('删除并归档学生',`<div class="form-context"><strong>${userHTML(item.name)}</strong><br>归档后从日常学生列表和新排课选项中移除。所有科目的课时、赠送课时和历史记录保留，已有排课不会自动取消。<br>老板可在已归档学生中恢复。</div>`,'确认归档',async()=>{await api('profiles/delete',{kind,id:item.id});toast('学生已归档，可在已归档学生中恢复。');},true);return;}
 const type={student:'学生',teacher:'老师',admin:'管理员'}[kind];
 modal('删除'+type+'档案',`<div class="form-context"><strong>${userHTML(item.name)}</strong><br>仅可删除没有课时余额、课程或业务记录的档案。${kind==='student'?'会删除这位学生名下所有空白科目，家长账号保留。':'删除后该账号无法登录。'}<br>删除后无法恢复，请确认不是仍需使用的档案。</div>`,'确认删除',async()=>{await api('profiles/delete',{kind,id:item.id});toast('档案已删除。');},true);
}

function unitFor(s={}){const account=(state.students||[]).concat(state.archived_students||[]).find(x=>x.id==(s.student_id||s.id));return (s.billing_unit||account?.billing_unit)==='hour'?'小时':'课时';}
function billingField(){return `<input type="hidden" name="billing_unit" value="lesson">`;}
function balanceSummary(students,gift=false){return ['lesson','hour'].map(unit=>{const rows=students.filter(s=>(s.billing_unit||'lesson')===unit);return rows.length?`${fmt(rows.reduce((n,s)=>n+(gift?s.gift_balance||0:regularHours(s)),0))} <small>${unit==='hour'?'小时':'课时'}</small>`:'';}).filter(Boolean).join(' / ')||'0';}
function editEntryModal(e){
 if(state.user.role!=='owner')return;
 const unit=unitFor(e),locked=e.kind==='reversal'||!!e.reversed_by,paid=e.kind==='credit'?(e.split_known?e.paid_delta:e.delta):e.kind==='refund'&&e.split_known?-e.paid_delta:Math.abs(e.delta);
 modal('编辑历史单据',`<div class="form-context">${userHTML(e.student_name)} · ${userHTML(e.course)} · #${e.id}<br>修改会更新余额和相关记录，修改原因仅后台保留。${locked?'<br>已撤销单据可修改日期和备注；请在有效单据中更正数量。':''}</div><label class="field">业务日期<input name="date" type="date" value="${e.lesson_date}" max="${today()}" required></label>${e.kind!=='reversal'?`<label class="field">${e.kind==='credit'?'充值':e.kind==='refund'?'退款':'扣除'}${unit}<input name="amount" type="number" min="${e.kind==='credit'?0:0.01}" max="10000" step="0.01" value="${paid/100}" ${locked?'readonly':''} required></label>`:''}${e.kind==='credit'?`<label class="field">赠送${unit}<input name="gift_amount" type="number" min="0" max="10000" step="0.01" value="${(e.gift_delta||0)/100}" ${locked?'readonly':''} required></label>`:''}${['credit','refund'].includes(e.kind)?paymentFields(e.kind==='refund'):''}<label class="field">单据备注<textarea name="note" maxlength="300">${escapeHTML(e.note)}</textarea></label><label class="field">修改原因（仅后台）<textarea name="reason" required maxlength="250"></textarea></label>`,'保存修改',async data=>{await api('entries/edit',{...data,entry_id:e.id,version:e.version});toast('单据和余额已更新。');});
 const history=document.createElement('details');history.className='form-context';history.innerHTML='<summary>后台修改记录（仅老板）</summary><div class="edit-history-content"></div>';$('#modal-form').insertBefore(history,$('.modal-footer'));history.ontoggle=async()=>{if(!history.open||history.dataset.loaded)return;try{const result=await api('entries/history?id='+e.id);history.querySelector('.edit-history-content').innerHTML=result.edits.map(item=>{const before=JSON.parse(item.before_json),after=JSON.parse(item.after_json);return `<p>${escapeHTML(item.created_at)} · ${userHTML(item.actor_name)}<br>${userHTML(item.reason)}<br>数量：${fmt(Math.abs(before.entry.delta))} → ${fmt(Math.abs(after.entry.delta))} ${unit}<br>金额：${before.cash?cashFmt(before.cash.cash_delta):'未登记'} → ${after.cash?.cash_delta!=null?cashFmt(after.cash.cash_delta):'未登记'}</p>`;}).join('')||'<p>暂无修改记录。</p>';history.dataset.loaded='1';}catch(err){history.querySelector('.edit-history-content').textContent=err.message;}};
 if($('[name=cash_amount]')){$('[name=cash_amount]').required=false;$('[name=cash_amount]').value=e.cash_delta==null?'':Math.abs(e.cash_delta)/100;$('[name=cash_amount]').placeholder='未登记金额可留空';$('[name=payment_method]').value=e.payment_method||'bank';$('[name=reference]').value=e.reference||'';}
}
