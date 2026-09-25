let weekStart='', teacherFilter='', scheduleStatus='all';
const statusName={scheduled:'待上课',completed:'已完成',cancelled:'已取消'};
const datePlus=(day,n)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);};
const monday=day=>{const n=new Date(day+'T12:00:00Z').getUTCDay();return datePlus(day,-((n+6)%7));};
const lessonById=id=>state.lessons.find(l=>l.id==id);
const isStaff=()=>state.user.role!=='parent';
const formatDate=day=>day.slice(5).replace('-',' / ');
const lessonStatus=l=>l.status==='scheduled'&&l.ends_at<state.now?'待写课后记录':statusName[l.status];
function navigationItems(){
 const role=state.user.role;
 return [...(role==='owner'?[['accounting','账目总结','grid'],['administrators','管理员','users']]:[]),['schedule',['owner','admin'].includes(role)?'排课日历':role==='teacher'?'我的课程':'孩子的课表','clock'],['feedback','课后记录','book'],['overview',['owner','admin'].includes(role)?'学生与课时':role==='teacher'?'我的学生':'剩余课时','grid'],['records','课时明细','book'],...(['owner','admin'].includes(role)?[['teachers','老师管理','users'],['settings','课程与地点设置','grid']]:[])];
}
function dashboard(){
 if(!weekStart)weekStart=monday(state.today);
 const admin=['owner','admin'].includes(state.user.role),staff=isStaff(),nav=navigationItems(),current=nav.find(n=>n[0]===view)||nav[0];view=current[0];
 const subtitles={settings:'管理排课时可选择的课程名称和上课地点。',accounting:'核对收款、退款与课时变动，每笔数字都有明细。',administrators:'由老板开通管理员账号，分工管理机构日常事务。',schedule:`按机构时间显示 · ${state.timezone}`,feedback:staff?'记录学习内容、今日作业和课后反馈。':'查看孩子每节课的学习内容、作业与老师反馈。',overview:staff?'查看学生余额，管理每一笔课时。':'剩余课时与学习记录，随时查看。',records:'每一笔课时变动，均有记录可查。',teachers:'为任课老师开通独立账号，并安排课程。'};
 $('#app').innerHTML=`<div class="shell"><aside class="sidebar">${brand()}<nav><p class="nav-label">${admin?'机构管理':staff?'老师中心':'家长中心'}</p>${nav.map(n=>`<button class="nav-item ${view===n[0]?'active':''}" data-view="${n[0]}">${icon(n[2])}${n[1]}</button>`).join('')}</nav><div class="side-foot"><strong>HELEN’S MATH SECRETS</strong>把每一次进步，认真记下来。</div></aside><main class="main">${state.demo?'<div class="demo-banner">本机演示版 · 虚构数据 · 可分别体验老板、管理员、任课老师和家长账号</div>':''}<header class="topbar"><div class="breadcrumb">${admin?'机构管理':staff?'老师中心':'家长中心'}<span>/　${current[1]}</span></div><div class="account"><span class="avatar">${userHTML(state.user.name.slice(0,1))}</span><span>${userHTML(state.user.name)}</span><span class="role-label">${state.user.role==='owner'?'老板':admin?'管理员':staff?'任课老师':'家长'}</span><button class="text-btn" id="password">修改密码</button><button class="text-btn logout" id="logout">退出</button></div></header><div class="content"><div class="page-head"><div><h1>${current[1]}</h1><p>${escapeHTML(subtitles[view])}</p></div>${admin?`<div class="head-actions">${['accounting','settings'].includes(view)?'':view==='administrators'?'<button class="btn primary" id="add-admin">'+icon('plus')+'添加管理员</button>':view==='teachers'?'<button class="btn primary" id="add-teacher">'+icon('plus')+'添加老师</button>':`${view==='overview'?'<button class="btn" id="add-student">'+icon('plus')+'添加学生</button>':''}<button class="btn primary" id="add-schedule">${icon('plus')}新增排课</button>`}</div>`:''}</div><div id="surface"></div></div></main></div>`;
 document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;selected='';render();});
 $('#password').onclick=passwordModal;
 $('#logout').onclick=async()=>{try{await api('logout',{});state={demo:state.demo,organization:state.organization};weekStart='';teacherFilter='';scheduleStatus='all';studentStatus='all';search='';render();}catch(e){toast(e.message);}};
 if($('#add-schedule'))$('#add-schedule').onclick=()=>scheduleModal();
 if($('#add-student'))$('#add-student').onclick=studentModal;
 if($('#add-admin'))$('#add-admin').onclick=administratorModal;
 if(view==='accounting')renderAccounting();
 if(view==='administrators')renderAdministrators();
 if($('#add-teacher'))$('#add-teacher').onclick=teacherModal;
 if(view==='settings')renderScheduleSettings();
 if(view==='schedule')renderSchedule();
 if(view==='feedback')renderFeedback();
 if(view==='teachers')renderTeachers();
 if(view==='overview')renderOverview();
 if(view==='records'){
  $('#surface').innerHTML=`<div class="section-head"><h2>课时变动记录</h2>${studentFilter()}</div><div id="records-list"></div><p class="footnote">已排课不会提前扣课时。完成课程后才扣除；撤销会保留原记录。</p>`;
  $('#student-filter').onchange=e=>{selected=e.target.value;renderRecords();};renderRecords();
 }
}
function studentFilter(){return `<select id="student-filter" class="select-filter" aria-label="按学生筛选"><option value="">全部学生</option>${state.students.map(s=>`<option data-user-content value="${s.id}" ${selected==s.id?'selected':''}>${escapeHTML(s.name)} · ${escapeHTML(s.course)}</option>`).join('')}</select>`;}
function renderOverview(){
 const students=state.students,total=students.reduce((n,s)=>n+regularHours(s),0),staff=isStaff();
 $('#surface').innerHTML=`<section class="stats"><div class="stat featured"><div class="stat-label">${staff?'学生剩余课时合计':'孩子剩余课时合计'}${icon('clock')}</div><div class="stat-value">${fmt(total)}<small>课时</small></div><div class="stat-note">赠送课时 ${fmt(students.reduce((n,s)=>n+(s.gift_balance||0),0))}</div></div><div class="stat"><div class="stat-label">${staff?'关联学生':'关联孩子'}${icon('users')}</div><div class="stat-value">${studentGroups().length}<small>位</small></div><div class="stat-note">${staff?'可在课表中查看课程安排':'仅显示自己孩子的信息'}</div></div><div class="stat"><div class="stat-label">需要续费</div><div class="stat-value">${studentGroups().filter(g=>g.some(s=>needsRenewal(s))).length}<small>位</small></div><div class="stat-note">至少一个科目的课时不足 3 节，请续费</div></div></section>${staff?'<div class="section-head"><h2>学生课时</h2><input id="search" class="search" type="search" placeholder="搜索学生、课程或手机号" aria-label="搜索学生"></div><div id="student-list"></div>':parentCards()}<section class="recent"><div class="section-head"><h2>最近课时记录</h2><button class="action" id="all-records">全部记录 →</button></div><div id="records-list"></div></section>`;
 if(staff){if(['owner','admin'].includes(state.user.role)){$('#search').insertAdjacentHTML('afterend',`<select id="student-status-filter" class="select-filter" aria-label="按学生课时状态筛选"><option value="all">全部状态</option><option value="normal">正常（课时不少于 3 节）</option><option value="renewal">需续费（课时不足 3 节）</option></select>`);$('#student-status-filter').value=studentStatus;$('#student-status-filter').onchange=e=>{studentStatus=e.target.value;renderStudents();};}$('#search').value=search;$('#search').oninput=e=>{search=e.target.value;renderStudents();};renderStudents();}
 document.querySelectorAll('[data-child]').forEach(b=>b.onclick=()=>{view='records';selected=b.dataset.child;render();});
 $('#all-records').onclick=()=>{view='records';selected='';render();};renderRecords();
}
function renderSchedule(){
 const admin=['owner','admin'].includes(state.user.role),end=datePlus(weekStart,7);
 const week=state.lessons.filter(l=>l.status!=='cancelled'&&l.starts_at>=weekStart&&l.starts_at<end&&(state.user.role!=='teacher'||l.teacher_id==state.user.teacher_id)&&(!admin||!teacherFilter||l.teacher_id==teacherFilter));
 const rows=week.filter(l=>scheduleStatus==='all'||l.status===scheduleStatus);
 const done=week.filter(l=>l.status==='completed');
 const duration=done.reduce((n,l)=>n+(new Date(l.ends_at+'Z')-new Date(l.starts_at+'Z'))/3600000,0);
 $('#surface').innerHTML=`<section class="stats teaching-stats"><div class="stat featured"><div class="stat-label">本周课程${icon('clock')}</div><div class="stat-value">${week.filter(l=>l.status!=='cancelled').length}<small>节</small></div><div class="stat-note">已安排 · 不含取消课程</div></div><div class="stat"><div class="stat-label">已完成</div><div class="stat-value">${done.length}<small>节</small></div><div class="stat-note">课后记录已发布</div></div><div class="stat"><div class="stat-label">${isStaff()?'已授课时长':'已完成课程时长'}</div><div class="stat-value">${Number(duration.toFixed(2))}<small>小时</small></div><div class="stat-note">按实际课程时段统计，与扣课单位分开</div></div></section><div class="calendar-toolbar"><div class="week-switch"><button class="btn icon-button" id="prev-week" aria-label="上一周">‹</button><strong>${formatDate(weekStart)} — ${formatDate(datePlus(weekStart,6))}<small>${weekStart.slice(0,4)}</small></strong><button class="btn icon-button" id="next-week" aria-label="下一周">›</button><button class="btn" id="this-week">本周</button></div><div class="calendar-filters">${admin?`<select id="teacher-filter" aria-label="按老师筛选"><option value="">全部老师</option>${state.teachers.map(t=>`<option data-user-content value="${t.id}" ${teacherFilter==t.id?'selected':''}>${escapeHTML(t.name)}</option>`).join('')}</select>`:''}<select id="status-filter" aria-label="按课程状态筛选">${[['all','全部状态'],['scheduled','待上课 / 待记录'],['completed','已完成']].map(([v,t])=>`<option value="${v}" ${v===scheduleStatus?'selected':''}>${t}</option>`).join('')}</select></div></div>${state.user.role==='owner'?'<p class="footnote">拖动课程卡片到其他日期可调整排课；点击空白处可新增当天课程。</p>':''}${state.user.role==='admin'?timeCalendar(rows):parentCalendar(rows)}<p class="footnote">时间以 ${escapeHTML(state.timezone)} 为准。排课不扣课时；完成课程并发布记录后才扣除。</p>`;
 $('#prev-week').onclick=()=>changeScheduleWeek(datePlus(weekStart,-7));$('#next-week').onclick=()=>changeScheduleWeek(datePlus(weekStart,7));$('#this-week').onclick=()=>changeScheduleWeek(monday(state.today));
 if($('#teacher-filter'))$('#teacher-filter').onchange=e=>{teacherFilter=e.target.value;renderSchedule();};
 $('#status-filter').onchange=e=>{scheduleStatus=e.target.value;renderSchedule();};bindLessons();
 initCalendarDragging();
 if(state.recurrence_warnings?.length)$('#surface').insertAdjacentHTML('afterbegin',`<div class="form-context" role="alert"><strong>重复排课需要处理</strong>${state.recurrence_warnings.map(w=>`<p>${escapeHTML(w)}</p>`).join('')}<p>发生冲突后的课程暂未继续生成，请调整时间或处理冲突课程。</p></div>`);
 document.querySelectorAll('[data-slot]').forEach(b=>b.onclick=()=>{if(Date.now()>calendarClickSuppressedUntil)scheduleModal(null,'',b.dataset.slot);});
 document.querySelectorAll('[data-add-day]').forEach(area=>area.onclick=e=>{if(Date.now()>calendarClickSuppressedUntil&&!e.target.closest('button'))scheduleModal(null,'',area.dataset.addDay+'T16:00');});
}
function parentCalendar(rows){
 const days=Array.from({length:7},(_,i)=>datePlus(weekStart,i));
 return `<div class="week-grid parent-week-grid ${state.user.role==='owner'?'owner-week-grid':''}">${days.map((day,i)=>{
 const lessons=rows.filter(l=>l.starts_at.slice(0,10)===day).sort((a,b)=>a.starts_at.localeCompare(b.starts_at));
 return `<section class="day-column ${day===state.today?'is-today':''}"><header class="day-title"><span>${['周一','周二','周三','周四','周五','周六','周日'][i]}</span><strong>${Number(day.slice(8))}${day===state.today?'<small>今天</small>':''}</strong></header><div class="day-lessons" ${state.user.role==='owner'?`data-add-day="${day}"`:''}>${lessons.map(lessonCard).join('')}${state.user.role==='owner'?`<button class="day-add-lesson" data-slot="${day}T16:00" aria-label="${day} · 新增排课"><span aria-hidden="true">＋</span></button>`:''}</div></section>`;
 }).join('')}</div>`;
}
function timeCalendar(rows){
 const days=Array.from({length:7},(_,i)=>datePlus(weekStart,i));
 const hours=rows.map(l=>Number(l.starts_at.slice(11,13)));
 const first=Math.min(8,...hours),last=Math.max(20,...hours);
 return `<div class="time-calendar"><table class="time-table"><thead><tr><th class="time-axis">时间</th>${days.map((day,i)=>`<th class="${day===state.today?'calendar-today':''}"><span>${['周一','周二','周三','周四','周五','周六','周日'][i]}</span><strong>${day.slice(5).replace('-',' / ')}</strong></th>`).join('')}</tr></thead><tbody>${Array.from({length:last-first+1},(_,i)=>{
 const hour=String(first+i).padStart(2,'0')+':00';
 return `<tr><th class="time-axis">${hour}</th>${days.map(day=>{
 const slot=day+'T'+hour,list=rows.filter(l=>l.starts_at.slice(0,13)===slot.slice(0,13));
 return `<td class="${day===state.today?'calendar-today':''}">${list.map(lessonCard).join('')}${isStaff()?`<button class="calendar-slot ${list.length?'slot-add':''}" data-slot="${slot}" aria-label="${day} ${hour} · 新增排课">${list.length?'+':'<span>暂无课程</span><small>＋ 排课</small>'}</button>`:''}</td>`;
 }).join('')}</tr>`;
 }).join('')}</tbody></table></div>`;
}
const lessonColors=[['green','绿色'],['blue','蓝色'],['purple','紫色'],['pink','粉色'],['orange','橙色'],['yellow','黄色'],['gray','灰色']];
function lessonCard(l){
 const owner=state.user.role==='owner',color=lessonColors.some(([v])=>v===l.color)?l.color:'green',students=l.students.map(s=>userHTML(s.name)).join('、');
 return `<button class="lesson-card ${l.status} ${owner?'owner-lesson color-'+color:''}" data-lesson-detail="${l.id}" ${owner&&l.status==='scheduled'?'draggable="true" title="拖动到其他日期可调整课程"':''}>${owner?`<strong class="lesson-students">${students}</strong>`:''}<div class="lesson-time">${l.starts_at.slice(11)}–${l.ends_at.slice(11)}</div><strong class="lesson-subject">${userHTML(l.title)}</strong><span>${userHTML(l.teacher_name)}</span>${owner?'':`<span class="lesson-students">${students}</span>`}<div class="lesson-card-foot"><span class="lesson-state">${lessonStatus(l)}</span><span>${fmt(l.planned_units)} 课时/人</span></div></button>`;
}
function lessonColorPicker(l){return `<fieldset class="lesson-color-picker"><legend>课程颜色</legend>${lessonColors.map(([v,label])=>`<label class="color-choice color-${v}" title="${label}"><input type="radio" name="color" value="${v}" ${(l?.color||'green')===v?'checked':''}><span>${label}</span></label>`).join('')}</fieldset>`;}

function bindLessons(){document.querySelectorAll('[data-lesson-detail]').forEach(b=>b.onclick=()=>lessonDetail(b.dataset.lessonDetail));}
function renderTeachers(){
 $('#surface').innerHTML=`<section class="teacher-grid">${state.teachers.map(t=>{const upcoming=state.lessons.filter(l=>l.teacher_id===t.id&&l.status==='scheduled').length,managed=t.account_role!=='teacher',canEdit=!managed||state.user.role==='owner';return `<article class="teacher-card"><div class="child-top"><span class="student-icon">${userHTML(t.name.slice(0,1))}</span><div><h2>${userHTML(t.name)}</h2><p>${userHTML(t.subjects.join('、'))}</p><p>${managed?'管理员 / 任课老师':'任课老师'} · ${t.active?'在职':'已离职 / 停用'}</p></div></div><p class="teacher-phone">${userHTML(t.phone)}</p>${!t.active&&upcoming?'<p class="error">仍有未完成课程，请查看课表并调整任课老师。</p>':''}<div class="profile-actions">${canEdit?`<button class="btn" data-teacher-edit="${t.id}">${managed?'编辑教学科目':'编辑老师'}</button>`:''}${!managed?`${state.user.role==='owner'?`<button class="btn refund-action" data-delete-teacher="${t.id}">删除档案</button>`:''}<button class="btn" data-teacher-status="${t.id}">${t.active?'离职 / 停用':'恢复在职'}</button>`:''}</div><div class="teacher-bottom"><span>待完成 <strong>${upcoming}</strong> 节</span><button class="action" data-teacher-calendar="${t.id}">查看课表 →</button></div></article>`;}).join('')}</section><p class="footnote">离职停用后无法登录或接受新排课，历史课程和课后记录保留。</p>`;
 document.querySelectorAll('[data-teacher-calendar]').forEach(b=>b.onclick=()=>{teacherFilter=b.dataset.teacherCalendar;view='schedule';render();});
 document.querySelectorAll('[data-delete-teacher]').forEach(b=>b.onclick=()=>deleteProfileModal('teacher',state.teachers.find(t=>t.id==b.dataset.deleteTeacher)));
 document.querySelectorAll('[data-teacher-edit]').forEach(b=>b.onclick=()=>teacherModal(state.teachers.find(t=>t.id==b.dataset.teacherEdit)));
 document.querySelectorAll('[data-teacher-status]').forEach(b=>b.onclick=()=>{const t=state.teachers.find(t=>t.id==b.dataset.teacherStatus);modal(t.active?'离职 / 停用':'恢复在职',`<div class="form-context">${userHTML(t.name)}<br>${t.active?'停用后无法登录或接受新排课。已有课程保留，请另行调整未完成课程。':'恢复后可使用原账号登录并接受排课。'}</div>`,'确认',async()=>{await api('teachers/status',{teacher_id:t.id,active:!t.active});toast('老师状态已更新。');},!!t.active);});
}
function teacherModal(existing=null){
 const t=existing&&existing.id?existing:null,managed=t&&t.account_role!=='teacher',selected=t?.subjects||[];
 const choices=[...new Set([...selected,...(state.schedule_options||[]).filter(o=>o.kind==='course'&&o.active).map(o=>o.name)])];
 modal(t?'编辑老师':'添加任课老师',`${managed?'<div class="form-context">此账号兼任管理职务，这里仅修改教学科目。</div>':`<label class="field">老师姓名<input name="name" required maxlength="40" value="${escapeHTML(t?.name||'')}"></label><label class="field">登录手机号<input name="phone" type="tel" required maxlength="24" value="${escapeHTML(t?.phone||'')}"></label><label class="field">${t?'重置密码（选填）':'初始密码'}<input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" ${t?'':'required'}><small>${t?'留空保留原密码；修改手机号或密码后需重新登录。':'至少 10 位，请单独告知老师。'}</small></label>`}<fieldset class="student-picker"><legend>教学科目 · 可多选</legend>${choices.map(name=>`<label><input type="checkbox" name="subjects" value="${escapeHTML(name)}" ${selected.includes(name)?'checked':''}>${userHTML(name)}</label>`).join('')}</fieldset><p class="footnote">更多科目可在课程与地点设置中添加。</p>`,'保存老师',async data=>{data.subjects=[...document.querySelectorAll('[name=subjects]:checked')].map(e=>e.value);delete data.subject;await api(t?'teachers/edit':'teachers',{...data,teacher_id:t?.id});toast('老师资料已保存。');});
}
function scheduleModal(existing=null,studentId='',slot=''){
 if(!state.students.length){toast('请先添加学生，再安排课程。');if(['owner','admin'].includes(state.user.role))return studentModal();return;}
 const l=existing,request_id=crypto.randomUUID(),day=slot?slot.slice(0,10):state.today,initialStart=slot||day+'T16:00',initialEnd=shiftScheduleTime(initialStart,60);
 modal(l?'调整课程':'新增排课',`<div class="form-context">${escapeHTML(state.timezone)} · 排课不会提前扣课时</div>${state.user.role==='owner'?lessonColorPicker(l):''}<label class="field">课程名称<select name="title" required>${scheduleOptions("course",l?.title||state.students.find(s=>s.id==studentId)?.course||"")}</select></label><label class="field">任课老师<select name="teacher_id">${state.teachers.filter(t=>t.active||t.id===l?.teacher_id).map(t=>`<option data-user-content ${t.active?'':'disabled'} value="${t.id}" ${(l?.teacher_id||teacherFilter||state.user.teacher_id)==t.id?'selected':''}>${escapeHTML(t.name)} · ${escapeHTML(t.subject)}</option>`).join('')}</select></label><div class="two-cols schedule-time-fields">${scheduleTimeField("starts_at","开始时间",l?.starts_at||initialStart)}${scheduleTimeField("ends_at","结束时间",l?.ends_at||initialEnd)}</div><p class="footnote">结束时间默认往后一小时，可手动调整。手动调整时长后，更改开始时间会保留该时长。</p><div class="two-cols"><label class="field">预计扣课（每位学生）<input name="amount" type="number" min="0.01" max="10000" step="0.01" value="${l?l.planned_units/100:1}" required></label><label class="field">上课地点（选填）<select name="location">${scheduleOptions("location",l?.location||"")}</select></label></div>${l?repeatScopeFields(l):'<div class="two-cols"><label class="field">重复安排<select name="repeat"><option value="none">不重复</option><option value="weekly">每周重复</option><option value="fortnightly">每两周重复</option></select></label><label class="field" id="repeat-end-field" hidden>结束方式<select name="repeat_end" disabled><option value="count">指定次数</option><option value="forever">永久重复</option></select></label><label class="field" id="repeat-count-field" hidden>总课次数（包含本次）<input name="repeat_count" type="number" min="2" max="52" step="1" value="10" disabled required></label></div><p id="repeat-help" class="form-context" hidden>按机构当地时间重复。可指定 2–52 次，或选择永久重复。永久课程会自动延续，也可随时调整或取消本次及后续课程。</p>'}<label class="field">搜索学生<input id="schedule-student-search" type="search" placeholder="输入学生姓名、课程或家长手机号" autocomplete="off"></label><div id="schedule-selected" class="schedule-selected" aria-live="polite"></div><fieldset class="student-picker" id="schedule-student-picker"><legend>选择学生及扣课科目 · 同一学生只选一个科目</legend><p id="schedule-search-empty" hidden>没有找到匹配的学生。</p>${state.students.map(s=>`<label><input type="checkbox" name="student_ids" value="${s.id}" ${(l?.students.some(x=>x.id===s.id)||studentId==s.id)?'checked':''}><span>${userHTML(s.name)}<small>${userHTML(s.course)} · 剩余 ${fmt(s.balance)} 课时</small></span></label>`).join('')}</fieldset>`,'保存排课',async data=>{data.student_ids=[...document.querySelectorAll('[name=student_ids]:checked')].map(x=>Number(x.value));const result=await api('lessons',{...data,request_id,lesson_id:l?.id,version:l?.version,series_version:l?.series_version});weekStart=monday(data.starts_at.slice(0,10));view='schedule';toast(l?'课程已更新。':data.repeat_end==='forever'?'永久重复排课已保存，将自动延续。':result.created_count?`已安排 ${result.created_count} 次课程，课时暂不扣除。`:'排课已保存，课时暂不扣除。');});
 $('#modal').classList.add('wide');
 initScheduleStudentSearch();
 initScheduleTimes();
 if(!l){const repeat=$('[name=repeat]'),ending=$('[name=repeat_end]');const updateRepeat=()=>{const enabled=repeat.value!=='none',count=enabled&&ending.value==='count';$('#repeat-end-field').hidden=!enabled;ending.disabled=!enabled;$('#repeat-count-field').hidden=!count;$('[name=repeat_count]').disabled=!count;$('#repeat-help').hidden=!enabled;};repeat.onchange=updateRepeat;ending.onchange=updateRepeat;}
}
function lessonDetail(id){
 if(Date.now()<calendarClickSuppressedUntil)return;
 const l=lessonById(id),admin=['owner','admin'].includes(state.user.role),staff=isStaff();lastFocus=document.activeElement;$('#modal').classList.add('wide');
 $('#modal-body').innerHTML=`<div class="modal-inner"><div class="modal-head"><h2 id="modal-title">${userHTML(l.title)}</h2><button type="button" class="close" aria-label="关闭">×</button></div><div class="lesson-detail-meta"><span class="badge ${l.status==='scheduled'?'low':''}">${lessonStatus(l)}</span><p>${escapeHTML(l.starts_at.replace('T',' '))} — ${l.ends_at.slice(11)}<br>${userHTML(l.teacher_name)} · ${escapeHTML(l.location||'地点未填写')}</p><p>${l.students.map(s=>userHTML(s.name)).join('、')} · 预计每人 ${fmt(l.planned_units)} 课时</p></div>${l.status==='cancelled'?`<div class="form-context">取消原因：${userHTML(l.cancel_reason)}<br>本次课程未扣课时。</div>`:l.status==='completed'?l.reports.map(r=>reportCard(l,r,false)).join(''):`<div class="form-context">${staff?(l.reports.length?'已保存课后记录草稿，家长暂不可见。':'完成课程后，填写学习内容、作业和反馈，再确认扣课。'):'课程结束后，老师会在这里发布学习内容、作业与反馈。'}</div>`}<div class="detail-actions">${admin&&l.status==='scheduled'?'<button class="btn" id="edit-schedule">调整排课</button><button class="btn" id="cancel-schedule">取消课程</button>':''}${staff&&l.status!=='cancelled'?`<button class="btn primary" id="write-report">${l.status==='completed'?'修改课后记录':'填写课后记录'}</button>`:''}<button class="btn" id="close-detail">关闭</button></div></div>`;
 const close=()=>$('#modal').close();$('.close').onclick=close;$('#close-detail').onclick=close;
 if($('#edit-schedule'))$('#edit-schedule').onclick=()=>{close();scheduleModal(l);};
 if($('#cancel-schedule'))$('#cancel-schedule').onclick=()=>{close();cancelModal(l);};
 if($('#write-report'))$('#write-report').onclick=()=>{close();reportModal(l);};
 $('#modal').showModal();
}
function cancelModal(l){modal('取消这节课',`<div class="form-context">${userHTML(l.title)}<br>${escapeHTML(l.starts_at.replace('T',' '))} · ${userHTML(l.teacher_name)}<br>取消后保留课程记录，不扣课时。</div>${repeatScopeFields(l)}<label class="field">取消原因<textarea name="reason" required maxlength="250" placeholder="例如：学生请假，另约时间"></textarea></label>`,'确认取消课程',async data=>{await api('lessons/cancel',{...data,lesson_id:l.id,version:l.version,series_version:l.series_version});toast('课程已取消，没有扣课时。');},true);}
function reportFields(l){return l.students.map((s,i)=>{
 const r=l.reports.find(r=>r.student_id===s.id),completed=l.status==='completed';
 return `<fieldset class="report-student" data-student="${s.id}"><legend>${userHTML(s.name)} <span>${userHTML(s.course)}</span></legend><label class="field">本次扣除课时<input name="amount_${i}" type="number" min="0.01" max="10000" step="0.01" value="${(r?.amount??l.planned_units)/100}" ${completed?'readonly':''} required><small>${completed?'已完成课程的课时不可在此修改；本次保存不会再次扣课。':`当前剩余 ${fmt(s.balance)} 课时，支持 0.5 或自定义数值。`}</small></label><label class="field">学习内容<textarea name="content_${i}" maxlength="2000" required placeholder="例如：分数加减法，通分与约分的应用。">${escapeHTML(r?.content||'')}</textarea></label><label class="field">今日作业<textarea name="homework_${i}" maxlength="2000" required placeholder="例如：完成练习册第 12 页 1–6 题；没有作业请写“今日无作业”。">${escapeHTML(r?.homework||'')}</textarea></label><label class="field">课后反馈<textarea name="feedback_${i}" maxlength="2000" required placeholder="记录掌握情况、课堂表现，以及下次课需要加强的内容。">${escapeHTML(r?.feedback||'')}</textarea></label></fieldset>`;
 }).join('');}
function reportModal(l){
 const completed=l.status==='completed';
 const payload=()=>({lesson_id:l.id,version:l.version,reports:l.students.map((s,i)=>({student_id:s.id,amount:$(`[name=amount_${i}]`).value,content:$(`[name=content_${i}]`).value,homework:$(`[name=homework_${i}]`).value,feedback:$(`[name=feedback_${i}]`).value}))});
 modal(completed?'修改课后记录':'填写课后记录',`<div class="form-context">${userHTML(l.title)} · ${userHTML(l.teacher_name)}<br>${escapeHTML(l.starts_at.replace('T',' '))}<br>${completed?'保存后更新家长端，课时不会再次扣除。':'保存草稿不会扣课，也不会向家长展示。确认完成后将扣除课时并发布给家长。'}</div>${reportFields(l)}`,completed?'保存修改':'确认完成并扣课',async()=>{await api(completed?'reports/edit':'reports/complete',payload());toast(completed?'课后记录已更新，没有重复扣课。':'课程已完成，课时已扣除，家长可以查看课后记录。');});
 $('#modal').classList.add('wide');
 if(!completed){
  const b=document.createElement('button');b.type='button';b.className='btn';b.textContent='保存草稿';$('.modal-footer').prepend(b);
  b.onclick=async()=>{const buttons=[...$('#modal-form').querySelectorAll('button')];buttons.forEach(x=>x.disabled=true);try{await api('reports/draft',payload());$('#modal').close();await refresh();toast('草稿已保存，未扣课时。');}catch(e){$('#modal-error').textContent=e.message;buttons.forEach(x=>x.disabled=false);}};
 }
}
function reportCard(l,r,withAction=true){return `<article class="feedback-card"><div class="feedback-head"><div><h3>${userHTML(r.student_name)} <span>${userHTML(l.title)}</span></h3><p>${l.starts_at.slice(0,10)} · ${userHTML(l.teacher_name)}</p></div><span class="badge ${r.reversed_by?'low':''}">${r.reversed_by?'该笔课时已撤销':`已扣 ${fmt(r.amount)} 课时`}</span></div><div class="report-block"><h4>学习内容</h4><p>${userHTML(r.content)}</p></div><div class="report-block homework-block"><h4>今日作业</h4><p>${userHTML(r.homework)}</p></div><div class="report-block"><h4>课后反馈</h4><p>${userHTML(r.feedback)}</p></div><div class="feedback-footer"><span>更新于 ${escapeHTML(new Intl.DateTimeFormat(window.uiLocale==='en'?'en-AU':'zh-CN',{timeZone:state.timezone,dateStyle:'short',timeStyle:'short'}).format(new Date(r.updated_at)))}</span>${withAction&&isStaff()?`<button class="action" data-edit-report="${l.id}">修改记录</button>`:''}</div></article>`;}
function renderFeedback(){
 const published=state.lessons.filter(l=>l.status==='completed').sort((a,b)=>b.starts_at.localeCompare(a.starts_at)),rows=published.flatMap(l=>l.reports.filter(r=>!selected||r.student_id==selected).map(r=>({l,r})));
 const waiting=isStaff()?state.lessons.filter(l=>l.status==='scheduled'&&l.ends_at<=state.now):[];
 $('#surface').innerHTML=`${waiting.length?`<section class="pending-lessons"><h2>待完成记录 <span class="count">${waiting.length}</span></h2>${waiting.map(l=>`<button class="pending-row" data-lesson-detail="${l.id}"><span><strong>${userHTML(l.title)}</strong><small>${l.starts_at.replace('T',' ')} · ${userHTML(l.teacher_name)} · ${l.students.map(s=>userHTML(s.name)).join('、')}</small></span><span>${l.reports.length?'继续草稿':'填写记录'} →</span></button>`).join('')}</section>`:''}<div class="section-head"><h2>已发布记录 <span class="count">${rows.length}</span></h2>${studentFilter()}</div><section class="feedback-grid">${rows.length?rows.map(({l,r})=>reportCard(l,r)).join(''):'<div class="panel empty">还没有发布的课后记录。<br>老师完成课程后，学习内容、作业和反馈会出现在这里。</div>'}</section>`;
 $('#student-filter').onchange=e=>{selected=e.target.value;renderFeedback();};bindLessons();document.querySelectorAll('[data-edit-report]').forEach(b=>b.onclick=()=>reportModal(lessonById(b.dataset.editReport)));
}

function scheduleOptions(kind,current){
 const options=(state.schedule_options||[]).filter(o=>o.kind===kind&&o.active).map(o=>o.name);
 if(current&&!options.includes(current))options.unshift(current);
 return `<option value="">${kind==='course'?'请选择课程':'不指定地点'}</option>`+options.map(name=>`<option data-user-content value="${escapeHTML(name)}" ${name===current?'selected':''}>${escapeHTML(name)}</option>`).join('');
}
function renderScheduleSettings(){
 $('#surface').innerHTML=`<p class="form-context">添加后即可在排课时选择。修改或停用选项不会更改已排课程的名称和地点。</p><div class="feedback-grid">${[['course','课程名称','添加课程'],['location','上课地点','添加地点']].map(([kind,title,add])=>`<section class="feedback-card"><div class="section-head"><h2>${title}</h2><button class="btn primary" data-option-add="${kind}">${add}</button></div>${(state.schedule_options||[]).filter(o=>o.kind===kind).map(o=>`<div class="option-row"><div>${userHTML(o.name)}<small>${o.active?'使用中':'已停用'}</small></div><div class="option-actions"><button class="btn" data-option-edit="${o.id}">编辑</button><button class="btn" data-option-toggle="${o.id}">${o.active?'停用':'启用'}</button></div></div>`).join('')||'<p class="muted">尚未设置，请点击添加。</p>'}</section>`).join('')}</div>`;
 document.querySelectorAll('[data-option-add]').forEach(b=>b.onclick=()=>optionModal(b.dataset.optionAdd));
 document.querySelectorAll('[data-option-edit]').forEach(b=>b.onclick=()=>{const o=state.schedule_options.find(o=>o.id==b.dataset.optionEdit);optionModal(o.kind,o);});
 document.querySelectorAll('[data-option-toggle]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const o=state.schedule_options.find(o=>o.id==b.dataset.optionToggle);await api('schedule-options',{...o,active:!o.active});await refresh();toast('选项已更新。');}catch(e){b.disabled=false;toast(e.message);}});
}
function optionModal(kind,option=null){
 modal(option?'编辑选项':kind==='course'?'添加课程':'添加地点',`<label class="field">${kind==='course'?'课程名称':'上课地点'}<input name="name" required maxlength="${kind==='course'?80:150}" value="${escapeHTML(option?.name||'')}" placeholder="${kind==='course'?'例如：物理、化学、数学小班':'例如：教室 A、线上 Zoom'}"></label>`,'保存选项',async data=>{await api('schedule-options',{...data,kind,id:option?.id,active:option?!!option.active:true});toast('选项已保存。');});
}

function initScheduleStudentSearch(){
 const searchInput=$('#schedule-student-search'),picker=$('#schedule-student-picker'),selected=$('#schedule-selected');
 const boxes=[...picker.querySelectorAll('[name=student_ids]')],accounts=new Map(state.students.map(s=>[String(s.id),s]));
 const refresh=()=>{
  const query=searchInput.value.trim().toLocaleLowerCase();let matches=0;
  for(const box of boxes){const s=accounts.get(box.value),text=[s.name,s.course,s.phone,s.contact_phone].filter(Boolean).join(' ').toLocaleLowerCase();const match=!query||text.includes(query);box.closest('label').hidden=!match;if(match)matches++;}
  $('#schedule-search-empty').hidden=matches>0;
  const checked=boxes.filter(b=>b.checked);
  selected.innerHTML=`<span>已选学生：${checked.length} / 30</span>${checked.map(b=>{const s=accounts.get(b.value);return `<button type="button" class="btn" data-unselect-student="${s.id}" aria-label="${escapeHTML('取消选择 '+s.name+' '+s.course)}">${userHTML(s.name)} · ${userHTML(s.course)} ×</button>`;}).join('')}`;
  selected.querySelectorAll('[data-unselect-student]').forEach(b=>b.onclick=()=>{boxes.find(x=>x.value===b.dataset.unselectStudent).checked=false;refresh();});
 };
 searchInput.oninput=refresh;
 searchInput.onkeydown=e=>{if(e.key==='Enter')e.preventDefault();};
 boxes.forEach(box=>box.onchange=()=>{if(box.checked){const s=accounts.get(box.value);boxes.forEach(other=>{if(other!==box&&accounts.get(other.value).profile_id===s.profile_id)other.checked=false;});}refresh();});
 refresh();
}

let calendarClickSuppressedUntil=0;
async function changeScheduleWeek(day){
 try{const next=await api('state?through='+encodeURIComponent(datePlus(day,6)));state=next;weekStart=day;renderSchedule();}catch(e){toast(e.message);}
}
function repeatScopeFields(l){return l?.series_id?`<fieldset class="repeat-scope"><legend>应用范围</legend><label><input type="radio" name="scope" value="single" checked>仅本次课程</label><label><input type="radio" name="scope" value="future">本次及后续所有课程</label><small>已完成和已取消的课程保持不变。</small></fieldset>`:'';}
function moveCalendarLesson(l,day){
 if(!l||l.status!=='scheduled'||day===l.starts_at.slice(0,10))return;
 const delta=Math.round((new Date(day+'T00:00:00Z')-new Date(l.starts_at.slice(0,10)+'T00:00:00Z'))/86400000);
 const starts_at=day+'T'+l.starts_at.slice(11),ends_at=datePlus(l.ends_at.slice(0,10),delta)+'T'+l.ends_at.slice(11);
 modal('移动课程',`<div class="form-context"><strong>${l.students.map(s=>userHTML(s.name)).join('、')}</strong><p>${userHTML(l.title)}</p><p>${escapeHTML(l.starts_at.replace('T',' '))} → <strong>${escapeHTML(starts_at.replace('T',' '))}</strong></p><small>上课时间和时长保持不变，仅移动日期。</small></div>${repeatScopeFields(l)}`,'确认移动',async data=>{
  await api('lessons',{...data,lesson_id:l.id,version:l.version,series_version:l.series_version,title:l.title,teacher_id:l.teacher_id,starts_at,ends_at,amount:l.planned_units/100,location:l.location,color:l.color||'green',student_ids:l.students.map(s=>s.id)});
  weekStart=monday(day);toast(data.scope==='future'?'本次及后续课程已移动。':'课程已移动。');
 });
}
function initCalendarDragging(){
 if(state.user.role!=='owner')return;
 let dragged=null;
 const clear=()=>document.querySelectorAll('.calendar-drop-target,.calendar-dragging').forEach(el=>el.classList.remove('calendar-drop-target','calendar-dragging'));
 document.querySelectorAll('.owner-week-grid [data-add-day]').forEach(area=>{
  area.ondragover=e=>{if(dragged){e.preventDefault();e.dataTransfer.dropEffect='move';clear();area.classList.add('calendar-drop-target');}};
  area.ondragleave=e=>{if(!area.contains(e.relatedTarget))area.classList.remove('calendar-drop-target');};
  area.ondrop=e=>{e.preventDefault();const l=dragged;dragged=null;clear();calendarClickSuppressedUntil=Date.now()+500;if(l)moveCalendarLesson(l,area.dataset.addDay);};
 });
 document.querySelectorAll('.owner-week-grid [draggable=true]').forEach(card=>{
  const l=lessonById(card.dataset.lessonDetail);
  card.ondragstart=e=>{dragged=l;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',String(l.id));card.classList.add('calendar-dragging');};
  card.ondragend=()=>{dragged=null;clear();calendarClickSuppressedUntil=Date.now()+500;};
  card.onkeydown=e=>{if(e.altKey&&(e.key==='ArrowLeft'||e.key==='ArrowRight')){e.preventDefault();moveCalendarLesson(l,datePlus(l.starts_at.slice(0,10),e.key==='ArrowLeft'?-1:1));}};
  let timer=null,touch=null;
  card.onpointerdown=e=>{if(e.pointerType!=='touch')return;touch={x:e.clientX,y:e.clientY,active:false};timer=setTimeout(()=>{if(touch){touch.active=true;card.setPointerCapture(e.pointerId);card.classList.add('calendar-dragging');}},350);};
  card.onpointermove=e=>{if(!touch)return;if(!touch.active){if(Math.hypot(e.clientX-touch.x,e.clientY-touch.y)>10){clearTimeout(timer);touch=null;}return;}e.preventDefault();clear();card.classList.add('calendar-dragging');document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-add-day]')?.classList.add('calendar-drop-target');};
  card.onpointerup=e=>{clearTimeout(timer);if(touch?.active){calendarClickSuppressedUntil=Date.now()+500;const area=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-add-day]');clear();if(area)moveCalendarLesson(l,area.dataset.addDay);}touch=null;};
  card.onpointercancel=()=>{clearTimeout(timer);touch=null;clear();};
 });
}

function shiftScheduleTime(value,minutes){return new Date(Date.parse(value+'Z')+minutes*60000).toISOString().slice(0,16);}
function scheduleTimeField(name,label,value){
 const hour=value.slice(11,13),minute=value.slice(14,16),minutes=[...new Set(['00','15','30','45',minute])].sort();
 return `<fieldset class="schedule-time-field" data-time-field="${name}"><legend>${label}</legend><input type="hidden" name="${name}" value="${escapeHTML(value)}"><input type="date" data-time-part="date" aria-label="${label}日期" value="${value.slice(0,10)}" required><div class="schedule-clock"><select data-time-part="hour" aria-label="${label}小时">${Array.from({length:24},(_,i)=>String(i).padStart(2,'0')).map(h=>`<option value="${h}" ${h===hour?'selected':''}>${h}</option>`).join('')}</select><span aria-hidden="true">:</span><select data-time-part="minute" aria-label="${label}分钟">${minutes.map(m=>`<option value="${m}" ${m===minute?'selected':''}>${m}</option>`).join('')}</select></div></fieldset>`;
}
function initScheduleTimes(){
 const fields=['starts_at','ends_at'].map(name=>{const box=document.querySelector(`[data-time-field="${name}"]`);return {box,value:box.querySelector('input[type=hidden]'),date:box.querySelector('[data-time-part=date]'),hour:box.querySelector('[data-time-part=hour]'),minute:box.querySelector('[data-time-part=minute]')};});
 const [start,end]=fields;
 let duration=(Date.parse(end.value.value+'Z')-Date.parse(start.value.value+'Z'))/60000;
 if(!(duration>0))duration=60;
 const write=(f,value)=>{f.value.value=value;f.date.value=value.slice(0,10);f.hour.value=value.slice(11,13);const minute=value.slice(14,16);if(![...f.minute.options].some(o=>o.value===minute))f.minute.add(new Option(minute,minute));f.minute.value=minute;};
 fields.forEach(f=>[f.date,f.hour,f.minute].forEach(input=>input.onchange=()=>{
  if(!f.date.value){f.value.value='';return;}
  f.value.value=f.date.value+'T'+f.hour.value+':'+f.minute.value;
  if(f===start)write(end,shiftScheduleTime(start.value.value,duration));
  else if(start.value.value){const chosen=(Date.parse(end.value.value+'Z')-Date.parse(start.value.value+'Z'))/60000;if(chosen>0)duration=chosen;}
 }));
}
