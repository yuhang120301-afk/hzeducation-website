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
const brand = () => `<div class="brand"><img src="/logo.jpg" alt="HELEN’S MATH SECRETS"><div>${escapeHTML(state.organization || 'HELEN’S MATH SECRETS')}<small>课时管理</small></div></div>`;
let state = {}, view = 'home', selected = '', search = '', studentStatus = 'all', lastFocus, toastTimer;
async function api(path, data) {
 let r;
 try {r=await fetch('/api/'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf||''},body:JSON.stringify(data)});} catch {throw new Error('网络连接失败，请稍后重试。');}
 let result;try{result=await r.json();}catch{throw new Error('服务暂时不可用，请稍后重试。');}
 if(!r.ok) throw new Error(result.error||'操作未完成。');
 return result;
}
function toast(message){$('#toast').textContent=message;$('#toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').style.display='none',3800);}
async function refresh(){state=await api('state');render();}
function render(){if(!state.user)return login();dashboard();}
function login(){
 $('#app').innerHTML=`<main class="login-layout"><section class="login-story">${brand()}<div class="story-body"><div class="eyebrow" style="color:inherit">每一节，都有记录</div><h1>探索学习的乐趣，<br>见证每一步成长。</h1><p>查看课程安排、学习内容与今日作业，<br>让每一次进步都有记录。</p><div class="learning-values" aria-label="学习理念"><div class="learning-value"><strong>Habits</strong><span>培养良好习惯</span></div><div class="learning-value"><strong>Methods</strong><span>掌握学习方法</span></div><div class="learning-value"><strong>Success</strong><span>成就每一步成长</span></div></div></div><div class="login-foot">课程安排 · 今日作业 · 课后反馈</div></section><section class="login-side"><div class="login-box"><h2>登录学习中心</h2><p>使用老师为你开通的手机号和密码登录。</p><form id="login-form"><label class="field">手机号<input name="phone" type="tel" autocomplete="username" placeholder="例如 +61 412 345 678" required maxlength="24"></label><label class="field">密码<input name="password" type="password" autocomplete="current-password" placeholder="请输入密码" required maxlength="128"></label><div class="error" id="login-error" role="alert"></div><button class="btn primary full" type="submit">登录 ${icon('arrow')}</button></form><p class="login-help">首次登录或忘记密码，请联系老师。<br>手机号格式请与老师开通账号时保持一致。</p>${state.demo?'<div class="demo-login"><p>当前是本机演示版，仅含虚构学生，可体验完整流程。</p><div class="demo-buttons"><button class="btn" data-demo="owner">老板</button><button class="btn" data-demo="admin">管理员</button><button class="btn" data-demo="teacher">任课老师</button><button class="btn" data-demo="parent">家长端</button></div></div>':''}</div></section></main>`;
 $('#login-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.currentTarget.querySelector('button');b.disabled=true;$('#login-error').textContent='';try{await api('login',Object.fromEntries(new FormData(e.currentTarget)));view='home';selected='';search='';await refresh();}catch(err){$('#login-error').textContent=err.message;b.disabled=false;}});
 document.querySelectorAll('[data-demo]').forEach(b=>b.addEventListener('click',()=>{const creds={owner:['0400000000','TeacherDemo2026!'],admin:['0400000004','AdminDemo2026!'],teacher:['0400000003','TutorDemo2026!'],parent:['0400000001','ParentDemo2026!']}[b.dataset.demo];$('#login-form [name=phone]').value=creds[0];$('#login-form [name=password]').value=creds[1];$('#login-form').requestSubmit();}));
}
function parentCards(){return `<section class="child-cards">${state.students.length?studentGroups().map(group=>{const s=group[0];return `<article class="child-card"><div class="child-top"><span class="student-icon">${userHTML(s.name.slice(-1))}</span><div><h2>${userHTML(s.name)}</h2><p>${userHTML(s.grade||'')} · 各科课时独立计算</p></div></div>${group.map(account=>`<section class="child-course"><h3>${userHTML(account.course)}</h3><div class="child-balance"><div><small>剩余</small><strong>${fmt(regularHours(account))}</strong><small>课时</small><span class="credit-split">赠送课时 ${fmt(account.gift_balance||0)}</span></div><span class="badge ${needsRenewal(account)?'low':''}">${needsRenewal(account)?'请续费':'余额充足'}</span></div><button class="action" data-child="${account.id}" style="margin-top:16px">查看课时明细 →</button></section>`).join('')}</article>`;}).join(''):'<div class="panel empty">还没有关联的学生，请联系老师。</div>'}</section>`;}
function studentGroups(){
 const groups=new Map();
 state.students.forEach(s=>{const key=s.profile_id||s.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(s);});
 return [...groups.values()];
}
function renderStudents(){
 const admin=['owner','admin'].includes(state.user.role);
 const groups=studentGroups().map(group=>group.filter(s=>!admin||studentStatus==='all'||(studentStatus==='renewal'?needsRenewal(s):!needsRenewal(s)))).filter(group=>group.some(s=>`${s.name} ${s.course} ${s.phone} ${s.grade||''}`.toLowerCase().includes(search.toLowerCase())));
 $('#student-list').innerHTML=groups.length?`<div class="student-profile-list">${groups.map(group=>{const s=group[0];return `<article class="panel student-profile"><div class="profile-heading"><div class="student-cell"><span class="student-icon">${userHTML(s.name.slice(-1))}</span><div><h3>${userHTML(s.name)}</h3><small>${userHTML(s.grade||'年级未填写')}${s.birthday?' · '+escapeHTML(s.birthday):''}</small><small>${userHTML(s.parent_name)} · ${userHTML(s.contact_phone||s.phone)}</small></div></div>${admin?`<div class="profile-actions"><button class="btn" data-profile="${s.id}">编辑档案</button>${state.user.role==='owner'?`<button class="btn refund-action" data-delete-student="${s.id}">删除并归档</button>`:''}<button class="btn" data-guardian="${s.id}">家长账号</button><button class="btn primary" data-add-course="${s.id}">添加科目</button></div>`:''}</div><div class="table-wrap"><table><thead><tr><th>课程</th><th>剩余课时</th><th>状态</th><th>操作</th></tr></thead><tbody>${group.map(account=>`<tr><td>${userHTML(account.course)}</td><td class="balance">${fmt(regularHours(account))}<small>课时</small><span class="credit-split">赠送课时 ${fmt(account.gift_balance||0)}</span></td><td><span class="badge ${needsRenewal(account)?'low':''}">${needsRenewal(account)?'请续费':'正常'}</span></td><td><div class="table-actions">${admin?`<button class="action" data-lesson="${account.id}">排课</button><button class="action" data-credit="${account.id}">充值</button><button class="action refund-action" data-refund="${account.id}">退课退款</button>`:''}<button class="action muted" data-history="${account.id}">明细</button></div></td></tr>`).join('')}</tbody></table></div></article>`;}).join('')}</div>`:`<div class="panel empty">${search||studentStatus!=='all'?'没有匹配的学生。':'还没有学生，点击「添加学生」开始。'}</div>`;
 if(state.user.role==='owner'){
  const archived=Object.values((state.archived_students||[]).reduce((groups,s)=>{(groups[s.profile_id]??=[]).push(s);return groups;},{}));
  $('#student-list').insertAdjacentHTML('beforeend',`<details class="panel" style="margin-top:20px;padding:20px"><summary>已归档学生（${archived.length}）</summary>${archived.map(group=>`<div class="profile-heading" style="padding:16px 0"><div><strong>${userHTML(group[0].name)}</strong>${group.map(s=>`<div>${userHTML(s.course)}${balanceSplit(s)}</div>`).join('')}</div><button class="btn" data-restore-student="${group[0].id}">恢复档案</button></div>`).join('')||'<p>暂无已归档学生。</p>'}</details>`);
  document.querySelectorAll('[data-restore-student]').forEach(b=>b.onclick=()=>{const s=state.archived_students.find(s=>s.id==b.dataset.restoreStudent);modal('恢复学生档案',`<div class="form-context">${userHTML(s.name)}<br>恢复后重新显示在学生列表中，可以排课和充值；原余额及记录保留。</div>`,'确认恢复',async()=>{await api('profiles/restore',{id:s.id});toast('学生档案已恢复。');});});
 }
 document.querySelectorAll('[data-delete-student]').forEach(b=>b.onclick=()=>deleteProfileModal('student',state.students.find(s=>s.id==b.dataset.deleteStudent)));
 document.querySelectorAll('[data-profile]').forEach(b=>b.onclick=()=>profileModal(b.dataset.profile));
 document.querySelectorAll('[data-guardian]').forEach(b=>b.onclick=()=>guardianModal(b.dataset.guardian));
 document.querySelectorAll('[data-add-course]').forEach(b=>b.onclick=()=>addCourseModal(b.dataset.addCourse));
 document.querySelectorAll('[data-lesson]').forEach(b=>b.onclick=()=>scheduleModal(null,b.dataset.lesson));
 document.querySelectorAll('[data-refund]').forEach(b=>b.onclick=()=>refundModal(b.dataset.refund));
 document.querySelectorAll('[data-credit]').forEach(b=>b.onclick=()=>entryModal('credit',b.dataset.credit));
 document.querySelectorAll('[data-history]').forEach(b=>b.onclick=()=>{selected=b.dataset.history;view='records';render();});
}
function addCourseModal(id){
 const s=state.students.find(s=>s.id==id),existing=state.students.filter(x=>x.profile_id===s.profile_id).map(x=>x.course);
 const choices=state.schedule_options.filter(o=>o.kind==='course'&&o.active&&!existing.includes(o.name));
 if(!choices.length){toast('没有可添加的科目，请先在课程与地点设置中添加课程。');return;}
 modal('添加学生科目',`<div class="form-context">${userHTML(s.name)} · 新科目从 0 课时开始，充值与扣课独立计算。</div><label class="field">课程名称<select name="course" required><option value="">请选择课程</option>${choices.map(o=>`<option data-user-content value="${escapeHTML(o.name)}">${escapeHTML(o.name)}</option>`).join('')}</select></label>`,'添加科目',async data=>{await api('students/course',{...data,student_id:s.id});toast('新科目已添加，可单独充值课时。');});
}
function renderRecords(){
 let rows=state.entries.filter(e=>!selected||String(e.student_id)===selected);if(view==='overview')rows=rows.slice(0,5);
 const admin=['owner','admin'].includes(state.user.role);
 $('#records-list').innerHTML=rows.length?`<div class="panel table-wrap"><table><thead><tr><th>日期 / 学生</th><th>类型</th><th>课时变动</th><th>备注</th><th>${admin?'登记人 / 操作':'登记人'}</th></tr></thead><tbody>${rows.map(e=>`<tr><td>${escapeHTML(e.lesson_date)}<div class="muted" style="font-size:12px;margin-top:6px">${userHTML(e.student_name)} · ${userHTML(e.course)}</div></td><td><span class="badge ${e.kind==='lesson'?'low':''}">${{lesson:'上课扣除',credit:'课时充值',refund:'退课退款',reversal:'撤销返还 / 扣回'}[e.kind]}</span>${e.reversed_by?'<div class="muted" style="font-size:12px;margin-top:6px">已撤销</div>':''}</td><td class="${e.delta>0?'positive':'negative'}">${e.delta>0?'+':'−'}${fmt(Math.abs(e.delta))}</td><td class="note-cell">${userHTML(e.note)||'—'}${creditBreakdown(e)}</td><td>${userHTML(e.actor_name)}${admin&&e.kind!=='reversal'&&!e.reversed_by?`<button class="action" data-reverse="${e.id}">撤销</button>`:''}</td></tr>`).join('')}</tbody></table></div>`:'<div class="panel empty">暂无课时变动记录。</div>';
 document.querySelectorAll('[data-reverse]').forEach(b=>b.onclick=()=>reverseModal(b.dataset.reverse));
}
function modal(title, body, submit, onsubmit, danger=false){
 lastFocus=document.activeElement;$('#modal').classList.remove('wide');
 $('#modal-body').innerHTML=`<form id="modal-form" class="modal-inner"><div class="modal-head"><h2 id="modal-title">${title}</h2><button type="button" class="close" aria-label="关闭">×</button></div>${body}<div id="modal-error" class="error" role="alert"></div><div class="modal-footer"><button type="button" class="btn cancel">取消</button><button type="submit" class="btn ${danger?'danger':'primary'}">${submit}</button></div></form>`;
 const close=()=>$('#modal').close();$('.close').onclick=close;$('.cancel').onclick=close;
 $('#modal-form').onsubmit=async e=>{e.preventDefault();const button=e.currentTarget.querySelector('[type=submit]');e.currentTarget.querySelectorAll('button').forEach(b=>b.disabled=true);$('#modal-error').textContent='';try{await onsubmit(Object.fromEntries(new FormData(e.currentTarget)));$('#modal').close();await refresh();}catch(err){$('#modal-error').textContent=err.message;$('#modal-form').querySelectorAll('button').forEach(b=>b.disabled=false);}};
 $('#modal').showModal();
}
$('#modal').addEventListener('close',()=>lastFocus?.isConnected&&lastFocus.focus());
function entryModal(kind,id){
 if(!state.students.length){toast('请先添加学生。');return studentModal();}
 const isLesson=kind==='lesson', request_id=crypto.randomUUID();
 modal(isLesson?'登记上课':'充值课时',`<label class="field">学生<select name="student_id" id="entry-student">${state.students.map(s=>`<option data-user-content value="${s.id}" ${id==s.id?'selected':''}>${escapeHTML(s.name)} · ${escapeHTML(s.course)}</option>`).join('')}</select></label><div class="form-context" id="balance-context"></div><div class="two-cols"><label class="field">${isLesson?'扣除课时':'课时'}<input name="amount" id="amount" type="number" min="${isLesson?'0.01':'0'}" max="10000" step="0.01" value="${isLesson?'1':'10'}" required></label><label class="field">${isLesson?'上课日期':'充值日期'}<input name="date" type="date" value="${today()}" max="${today()}" required></label></div><div class="quick">${(isLesson?[0.5,1,1.5,2]:[5,10,20,30]).map(n=>`<button type="button" data-amount="${n}">${n} 课时</button>`).join('')}</div>${isLesson?'':`<label class="field">赠送课时<input name="gift_amount" id="gift-amount" type="number" min="0" max="10000" step="0.01" value="0" required></label><div class="form-context">课时用完后再使用赠送课时。课时不足 3 节时提醒续费。</div>${paymentFields()}`}<label class="field">备注（选填）<textarea name="note" maxlength="300" placeholder="${isLesson?'例如：补录历史课时':'例如：新学期购买 10 课时'}"></textarea></label>`,isLesson?'确认扣除':'确认充值',async data=>{await api('entries',{...data,kind,request_id});toast(isLesson?'上课已登记，课时已扣除。':'课时已充值。');});
 const update=()=>{const s=state.students.find(s=>s.id==$('#entry-student').value),amount=Math.round(Number($('#amount').value||0)*100),gift=Math.round(Number($('#gift-amount')?.value||0)*100),paid=regularHours(s),gifts=s.gift_balance||0;const afterPaid=isLesson?Math.max(0,paid-amount):paid+amount,afterGift=isLesson?gifts-Math.max(0,amount-paid):gifts+gift;$('#balance-context').innerHTML=`当前：课时 <strong>${fmt(paid)}</strong> · 赠送课时 <strong>${fmt(gifts)}</strong><br>${isLesson?'扣除':'充值'}后：课时 <strong>${fmt(afterPaid)}</strong> · 赠送课时 <strong>${fmt(afterGift)}</strong>`;};
 $('#entry-student').onchange=update;$('#amount').oninput=update;if($('#gift-amount'))$('#gift-amount').oninput=update;document.querySelectorAll('[data-amount]').forEach(b=>b.onclick=()=>{$('#amount').value=b.dataset.amount;update();});update();
}
function studentModal(){modal('添加学生',`<label class="field">学生姓名<input name="name" required maxlength="40" placeholder="例如：陈一诺"></label>${profileFields()}<label class="field">课程名称<select name="course" required>${scheduleOptions("course","")}</select></label><label class="field">家长姓名<input name="parent_name" maxlength="40" placeholder="选填"></label><label class="field">家长手机号<input name="phone" type="tel" required maxlength="24" placeholder="例如 +61 412 345 678"><small>同一手机号可关联多个孩子。已有账号会直接关联。</small></label><label class="field">家长初始密码<input name="password" type="password" minlength="10" maxlength="128" autocomplete="new-password" placeholder="新账号需至少 10 位"><small>已有家长账号可留空，其原密码保持不变。请单独告知家长登录信息。</small></label>`,'创建学生',async data=>{await api('students',data);toast('学生已添加，可在列表中充值课时。');});}
function reverseModal(id){const e=state.entries.find(e=>e.id==id),request_id=crypto.randomUUID();modal('撤销这笔记录？',`<div class="form-context">${userHTML(e.student_name)} · ${escapeHTML(e.lesson_date)}<br>原记录：${e.kind==='refund'?'退课退款':e.delta>0?'充值':'扣除'} ${fmt(Math.abs(e.delta))} 课时。<br>撤销后会${e.delta>0?'扣回':'返还'}相应课时，原记录仍会保留。涉及金额时会产生记账纠错，不代表实际收款或退款。${creditBreakdown(e)}</div><label class="field">撤销原因<textarea name="note" required maxlength="250" placeholder="例如：重复登记，返还课时"></textarea></label>`,'确认撤销',async data=>{await api('reverse',{...data,entry_id:id,request_id});toast('已撤销，课时余额已更新。');},true);}
function passwordModal(){modal('修改密码',`<label class="field">当前密码<input name="old" type="password" autocomplete="current-password" required maxlength="128"></label><label class="field">新密码<input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" required><small>至少 10 位，修改成功后需重新登录。</small></label>`,'保存新密码',async data=>{await api('password',data);toast('密码已修改，请重新登录。');});}

function profileFields(s={}){return `<div class="two-cols"><label class="field">生日<input type="date" name="birthday" max="${state.today}" value="${escapeHTML(s.birthday||'')}"></label><label class="field">年级<input name="grade" maxlength="40" value="${escapeHTML(s.grade||'')}" placeholder="例如：Year 8"></label></div><label class="field">内部备注<textarea name="notes" maxlength="2000" placeholder="仅老板和管理员可查看">${escapeHTML(s.notes||'')}</textarea></label>`;}
function profileModal(id){
 const s=state.students.find(s=>s.id==id);
 modal('编辑学生档案',`<label class="field">学生姓名<input name="name" required maxlength="40" value="${escapeHTML(s.name)}"></label>${profileFields(s)}`,'保存档案',async data=>{await api('students/profile',{...data,student_id:s.id});toast('学生档案已更新。');});
}
function guardianModal(id){
 const s=state.students.find(s=>s.id==id),children=studentGroups().map(g=>g[0]).filter(x=>x.parent_id===s.parent_id);
 modal('编辑家长账号',`<div class="form-context">此账号关联：${children.map(x=>userHTML(x.name)).join('、')}。修改将对这些孩子共用的家长账号生效。</div><label class="field">家长姓名<input name="parent_name" required maxlength="40" value="${escapeHTML(s.parent_name)}"></label><label class="field">登录手机号<input type="tel" name="phone" required maxlength="24" value="${escapeHTML(s.phone)}"></label><label class="field">联系手机号（选填）<input type="tel" name="contact_phone" maxlength="24" value="${escapeHTML(s.contact_phone||'')}"></label><label class="field">重置密码（选填）<input name="password" type="password" minlength="10" maxlength="128" autocomplete="new-password"><small>留空则保留原密码。修改登录手机号或重置密码后，家长需重新登录。</small></label>`,'保存家长账号',async data=>{await api('students/guardian',{...data,student_id:s.id});toast('家长账号已更新。');});
}

function regularHours(s){return s.paid_balance??s.balance;}
function needsRenewal(s){return regularHours(s)<300;}
function balanceSplit(s){return `<span class="credit-split">课时 ${fmt(regularHours(s))} · 赠送课时 ${fmt(s.gift_balance||0)}</span>`;}
function creditBreakdown(e){if(!e.split_known)return '';return `<small class="credit-split">课时 ${signedUnits(e.paid_delta)} · 赠送课时 ${signedUnits(e.gift_delta)}${e.gift_void?` · ${e.gift_void>0?'作废赠课':'恢复赠课'} ${fmt(Math.abs(e.gift_void))}`:''}</small>`;}

function deleteProfileModal(kind,item){
 if(state.user.role!=='owner')return;
 if(kind==='student'){modal('删除并归档学生',`<div class="form-context"><strong>${userHTML(item.name)}</strong><br>归档后从日常学生列表和新排课选项中移除。所有科目的课时、赠送课时和历史记录保留，已有排课不会自动取消。<br>老板可在已归档学生中恢复。</div>`,'确认归档',async()=>{await api('profiles/delete',{kind,id:item.id});toast('学生已归档，可在已归档学生中恢复。');},true);return;}
 const type={student:'学生',teacher:'老师',admin:'管理员'}[kind];
 modal('删除'+type+'档案',`<div class="form-context"><strong>${userHTML(item.name)}</strong><br>仅可删除没有课时余额、课程或业务记录的档案。${kind==='student'?'会删除这位学生名下所有空白科目，家长账号保留。':'删除后该账号无法登录。'}<br>删除后无法恢复，请确认不是仍需使用的档案。</div>`,'确认删除',async()=>{await api('profiles/delete',{kind,id:item.id});toast('档案已删除。');},true);
}
