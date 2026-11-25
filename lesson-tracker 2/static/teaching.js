let weekStart='', teacherFilter='', scheduleStatus='all', profileId='', lessonRecordId='', payTeacherId='', recordTeacher='', recordQuery='';
const statusName={scheduled:'待上课',completed:'已完成',cancelled:'已取消'};
function lessonIsAbsent(lesson){return !!Number(lesson&&lesson.absent);}
const datePlus=(day,n)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);};
const monday=day=>{const n=new Date(day+'T12:00:00Z').getUTCDay();return datePlus(day,-((n+6)%7));};
const lessonById=id=>state.lessons.find(l=>l.id==id);
const isStaff=()=>state.user.role!=='parent';
const formatDate=day=>day.slice(5).replace('-',' / ');
const lessonStatus=l=>lessonIsAbsent(l)?'请假':l.status==='cancelled'?statusName.cancelled:(typeof lessonDone==='function'&&lessonDone(l)?'已完成':l.status==='scheduled'&&l.ends_at<state.now?'待写课后记录':statusName[l.status]);
function navigationItems(){
 const role=state.user.role;
 if(role==='owner') return [
  ['',[['today','今天','clock'],['schedule','课表','grid'],['overview','学生','users'],['pay','工资','book'],['finance','财务','book'],['vouchers','单据','book'],['share','分红','book']]],
  ['更多',[['feedback','课后记录','check'],['accounting','收款与欠费','grid'],['prices','价格表','book'],['audit','操作日志','book'],['setup','设置','users']]]
 ];
 if(role==='teacher') return [['',[['schedule','我的课程','clock'],['feedback','课后记录','book'],['overview','我的学生','users'],['pay','我的工资','book']]]];
 if(role==='parent') return [['',[['schedule','孩子的课表','clock'],['feedback','课后记录','book'],['overview','剩余课时','grid'],['records','付款记录','book']]]];
 const items=[['schedule','排课日历','clock'],['feedback','课后记录','book'],['overview','学生与课时','grid'],['records','余额明细','book'],['teachers','老师管理','users'],['settings','课程与地点设置','grid']];
 return [['',items]];
}
function flatNavigation(){
 const items=navigationItems().flatMap(group=>group[1]);
 if(state.user.role==='owner'){
  if(view==='teachers') items.push(['teachers','老师','users']);
  if(view==='settings') items.push(['settings','课程与地点','grid']);
  if(view==='administrators') items.push(['administrators','管理员','users']);
  if(view==='profile') items.push(['profile','学生档案','users']);
  if(view==='records') items.push(['records','余额明细','book']);
  if(view==='receipt') items.push(['receipt','单据','book']);
 }
 if(view==='profile' && !items.some(item=>item[0]==='profile')) items.push(['profile','学生档案','users']);
 if(view==='lesson-record' && !items.some(item=>item[0]==='lesson-record')) items.push(['lesson-record','课时记录','book']);
 return items;
}
function headerActions(){
 const role=state.user.role;
 if(!['owner','admin'].includes(role)) return '';
 const schedule=`<button class="btn primary" id="add-schedule">${icon('plus')}新增排课</button>`;
 const student=`<button class="btn" id="add-student">${icon('plus')}添加学生</button>`;
 if(view==='teachers') return `<div class="head-actions"><button class="btn primary" id="add-teacher">${icon('plus')}添加老师</button></div>`;
 if(view==='administrators') return `<div class="head-actions"><button class="btn primary" id="add-admin">${icon('plus')}添加管理员</button></div>`;
 if(view==='today' && role==='owner') return `<div class="head-actions"><span class="today-who">Helen校长端</span></div>`;
 if(view==='overview') return `<div class="head-actions">${student}${schedule}</div>`;
 if(view==='schedule' || (role==='admin' && !['settings','accounting'].includes(view))) return `<div class="head-actions">${schedule}</div>`;
 return '';
}
async function downloadDatabaseBackup(){
 try{
  const response=await fetch('/api/backup',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf||''},body:'{}'});
  if(!response.ok){let message='备份没有下载。'; try{message=(await response.json()).error||message;}catch{} throw new Error(message);}
  const blob=await response.blob();
  const link=document.createElement('a');
  link.href=URL.createObjectURL(blob);
  link.download='lessons-backup.sqlite3';
  link.click();
  URL.revokeObjectURL(link.href);
  toast('备份已下载。请把它存到电脑上的私人位置。');
 }catch(error){toast(error.message);}
}
function renderSetup(){
 $('#surface').innerHTML=`<div class="feedback-grid"><button class="feedback-card setup-card" data-view="teachers"><h2>老师</h2><p>开通账号、科目和在职状态。</p></button><button class="feedback-card setup-card" data-view="settings"><h2>课程与地点</h2><p>排课时可选的名称和上课地点。</p></button><button class="feedback-card setup-card" data-view="administrators"><h2>管理员</h2><p>协助处理学生、排课和收款的账号。</p></button></div><p class="footnote">日常先看今天、课表和确认课时。老师、课程和管理员放在这里，不占每天的菜单。</p><p><button class="btn" id="download-backup" type="button">下载数据库备份</button></p><p class="footnote">这是整份数据库的副本，含学生姓名和余额。请保存到自己的电脑，不要留在聊天或邮箱里。下载不会改动正在使用的数据。</p>`;
 document.querySelectorAll('#surface [data-view]').forEach(button=>button.onclick=()=>{document.querySelector('.shell')?.classList.remove('nav-open'); showView(button.dataset.view);});
 $('#download-backup').onclick=downloadDatabaseBackup;
}
function dashboard(){
 if(!weekStart)weekStart=monday(state.today);
 const role=state.user.role, admin=['owner','admin'].includes(role), staff=isStaff();
 const nav=navigationItems(), flat=flatNavigation(), current=flat.find(item=>item[0]===view)||flat[0];
 view=current[0];
 const center=role==='owner'?'Helen校长端':admin?'机构管理':staff?'老师中心':'家长中心';
 const shown={teachers:'setup',settings:'setup',administrators:'setup',profile:'overview','lesson-record':'overview',receipt:'vouchers'}[view]||view;
 const todayLine=`${typeof weekdayName==='function'?weekdayName(state.today):''} ${Number(state.today.slice(5,7))}月${Number(state.today.slice(8))}日 · 墨尔本时间`;
 const subtitles={today:todayLine,schedule:role==='owner'?'点击或拖选时间即可排课。点到的位置就是上课时间。':role==='teacher'?'只显示自己的课，不能改时间。':`按机构时间显示 · ${state.timezone}`,feedback:role==='owner'?'课程结束后确认。也可以只点「这节课已上」，作业以后再补。':staff?'记录学习内容、今日作业和课后反馈。':'查看孩子每节课的学习内容、作业与老师反馈。',overview:role==='owner'?'每张卡是一位学生。左边的颜色是任课老师。':role==='teacher'?'只显示自己课上的学生。点开可以看上课记录并写课后反馈。':role==='parent'?'只显示自己的孩子。点开可以看课时、课时包和付款。':'剩余余额与学习记录，随时查看。',records:role==='parent'?'只显示自己付给机构的款和退款。':'查看充值、上课扣除和退款记录。',teachers:'为任课老师开通独立账号，并安排课程。',settings:'管理排课时可选择的课程名称和上课地点。',administrators:'由老板开通管理员账号，分工管理机构日常事务。',accounting:'核对每天收到的家长付款，以及还没上交的代收。',pay:role==='teacher'?'只显示自己的上课工资。可以按天、周、双周或月查看。':'按已经上完、扣过课时的课计算。数字供核对，不会自动打款。',finance:'营业额、成本、机构利润和 Helen 净利润。',share:'新学生利润的分红。上课工资只在工资页，不记在这里。',audit:'可以查看并撤销还没有被别人改过的操作。',profile:role==='teacher'?'上课记录和课后反馈。':'课程和课后记录按日期排列。','lesson-record':'这节课的课时和课后记录。',setup:'老师、课程名称、管理员和每日备份。',prices:'每种课程各自的价和课时包。暂定的数字可以改。'};
 const navHtml=nav.map(([label,items])=>`${label==='更多'?'<p class="nav-more">更多</p>':label?`<p class="nav-label">${label}</p>`:''}${items.map(item=>`<button class="nav-item ${shown===item[0]?'active':''}" data-view="${item[0]}">${icon(item[2])}${item[1]}</button>`).join('')}`).join('');
 $('#app').innerHTML=`<div class="shell"><aside class="sidebar ${role==='owner'?'a2':''}">${brand()}<nav>${navHtml}</nav><div class="side-foot"><strong>HZ Education Melbourne</strong>把每一次进步，认真记下来。</div></aside><button type="button" class="nav-backdrop" id="nav-backdrop" aria-label="关闭菜单"></button><main class="main">${state.demo?'<div class="demo-banner">本机演示版 · 虚构数据 · 可分别体验Helen校长端、管理员、任课老师和家长账号</div>':''}<header class="topbar"><button type="button" class="nav-toggle" id="nav-toggle" aria-label="打开菜单"><span></span><span></span><span></span></button><div class="breadcrumb">${center}<span>/　${current[1]}</span></div><div class="account"><span class="avatar">${userHTML(state.user.name.slice(0,1))}</span><span>${userHTML(state.user.name)}</span><span class="role-label">${role==='owner'?'Helen校长端':admin?'管理员':staff?'任课老师':'家长'}</span>${role==='owner'?'<button class="text-btn" id="undo-last" type="button">撤销上一步</button>':''}<button class="text-btn" id="password">修改密码</button><button class="text-btn logout" id="logout">退出</button></div></header><div class="content"><div class="page-head ${role==='owner'?'a2-head':''}"><div><h1>${current[1]}</h1><p>${escapeHTML(subtitles[view]||'')}</p></div>${headerActions()}</div><div id="surface"></div></div></main></div>`;
 const closeNav=()=>document.querySelector('.shell')?.classList.remove('nav-open');
 document.querySelectorAll('.sidebar [data-view]').forEach(button=>button.onclick=()=>{view=button.dataset.view;selected='';payTeacherId='';closeNav();const next='/?view='+encodeURIComponent(view);if(location.pathname+location.search!==next)history.pushState({hz:1},'',next);render();});
 $('#nav-toggle').onclick=()=>document.querySelector('.shell').classList.toggle('nav-open');
 $('#nav-backdrop').onclick=closeNav;
 if($('#undo-last')) $('#undo-last').onclick=()=>{if(typeof undoLast==='function') undoLast();};
 $('#password').onclick=passwordModal;
 $('#logout').onclick=async()=>{try{await api('logout',{});state={demo:state.demo,organization:state.organization};weekStart='';teacherFilter='';scheduleStatus='all';studentStatus='all';studyFilter='studying';search='';view='home';render();}catch(error){toast(error.message);}};
 if($('#add-schedule'))$('#add-schedule').onclick=()=>scheduleModal();
 if($('#add-student'))$('#add-student').onclick=studentModal;
 if($('#add-admin'))$('#add-admin').onclick=administratorModal;
 if($('#add-teacher'))$('#add-teacher').onclick=teacherModal;
 if(view==='today')renderToday();
 if(view==='accounting')renderAccounting();
 if(view==='pay')renderPay();
 if(view==='finance')renderFinance();
 if(view==='vouchers')renderVouchers();
 if(view==='receipt')renderReceipt();
 if(view==='share')renderShare();
 if(view==='prices')renderPrices();
 if(view==='audit')renderAudit();
 if(view==='profile')renderStudentProfile();
 if(view==='lesson-record')renderLessonRecord();
 if(view==='setup')renderSetup();
 if(view==='administrators')renderAdministrators();
 if(view==='settings')renderScheduleSettings();
 if(view==='schedule')renderSchedule();
 if(view==='feedback')renderFeedback();
 if(view==='teachers')renderTeachers();
 if(view==='overview')renderOverview();
 if(view==='records'){
  $('#surface').innerHTML=`<div class="section-head"><h2>${state.user.role==='parent'?'付款记录':'余额变动记录'}</h2>${studentFilter()}</div><div id="records-list"></div><p class="footnote">${state.user.role==='parent'?'只显示自己的付款和退款。':'已排课不会提前扣除余额；撤销和修改历史仅后台保留。'}</p>`;
  $('#student-filter').onchange=event=>{selected=event.target.value;renderRecords();};renderRecords();
 }
 if(state.user.role==='owner' && ['teachers','settings','administrators','records'].includes(view)){
  $('#surface').insertAdjacentHTML('afterbegin', typeof backBar==='function'?backBar():'<p class="page-back"><button type="button" class="btn" id="page-back">返回</button></p>');
  const backTo=view==='records'?'overview':'setup';
  $('#page-back').onclick=()=>showView(backTo);
 }
}
function studentFilter(){return `<select id="student-filter" class="select-filter" aria-label="按学生筛选"><option value="">全部学生</option>${state.students.map(s=>`<option data-user-content value="${s.id}" ${selected==s.id?'selected':''}>${escapeHTML(s.name)}${s.no_course?'':` · ${escapeHTML(s.course)}`}</option>`).join('')}</select>`;}
function renderOverview(){
 if(typeof restoreStudentList!=='undefined' && restoreStudentList){restoreStudentList=false; loadListPlace();}
 const students=state.students,total=students.reduce((n,s)=>n+regularHours(s),0),staff=isStaff();
 const teacherHome=state.user.role==='teacher';
 $('#surface').innerHTML=`<section class="stats"><div class="stat featured"><div class="stat-label">${teacherHome?'我的学生':staff?'学生剩余余额':'孩子剩余余额'}${icon('clock')}</div><div class="stat-value">${teacherHome?studentGroups().length:balanceSummary(students)}</div><div class="stat-note">${teacherHome?'只看自己课上的学生':`赠送 ${balanceSummary(students,true)}`}</div></div><div class="stat"><div class="stat-label">${staff?'关联学生':'关联孩子'}${icon('users')}</div><div class="stat-value">${studentGroups().length}<small>位</small></div><div class="stat-note">${staff?'可在课表中查看课程安排':'仅显示自己孩子的信息'}</div></div>${teacherHome?'':`<div class="stat"><div class="stat-label">需要续费</div><div class="stat-value">${studentGroups().filter(g=>g.some(s=>!s.no_course&&needsRenewal(s)&&(s.study_status||'studying')!=='graduated')).length}<small>位</small></div><div class="stat-note">至少一个科目的余额不足 3 课时／小时，请续费</div></div>`}</section>${staff?`<div class="section-head"><h2>${teacherHome?'我的学生':'学生课时'}</h2><input id="search" class="search" type="search" placeholder="${teacherHome?'搜索学生或课程':'搜索学生、课程或手机号'}" aria-label="搜索学生"></div><div id="student-list"></div>`:parentCards()}${teacherHome?'':`<section class="recent"><div class="section-head"><h2>${staff?'全校最近变动':'最近付款'}</h2><button class="action" id="all-records">${staff?'全部记录 →':'全部付款记录 →'}</button></div><div id="records-list"></div></section>`}`;
 if(staff){if(['owner','admin'].includes(state.user.role)){const studyChoices=[['studying','在读'],['withdrawn','退学'],['graduated','已毕业'],['all','全部']];$('#search').insertAdjacentHTML('afterend',`<div class="course-tabs" id="study-filter" role="tablist" aria-label="按在读状态筛选">${studyChoices.map(([value,label])=>`<button type="button" role="tab" data-study="${value}" class="${studyFilter===value?'on':''}" aria-selected="${studyFilter===value?'true':'false'}">${label}</button>`).join('')}</div><select id="student-status-filter" class="select-filter" aria-label="按学生课时状态筛选"><option value="all">全部状态</option><option value="normal">正常（余额不少于 3）</option><option value="renewal">需续费（余额不足 3）</option></select>`);document.querySelectorAll('#study-filter [data-study]').forEach(button=>button.onclick=()=>{studyFilter=button.dataset.study;renderStudents();document.querySelectorAll('#study-filter [data-study]').forEach(item=>{const on=item.dataset.study===studyFilter;item.classList.toggle('on',on);item.setAttribute('aria-selected',on?'true':'false');});});$('#student-status-filter').value=studentStatus;$('#student-status-filter').onchange=e=>{studentStatus=e.target.value;renderStudents();};}$('#search').value=search;$('#search').oninput=e=>{search=e.target.value;renderStudents();};renderStudents();}
 document.querySelectorAll('.child-card[data-open-student]').forEach(card=>card.onclick=event=>{if(event.target.closest('button')) return; if(typeof openDetail==='function') openDetail('/students/'+card.dataset.openStudent);});
 document.querySelectorAll('[data-child]').forEach(b=>b.onclick=()=>{selected=b.dataset.child; showView('records');});
 if($('#all-records')){$('#all-records').onclick=()=>{selected=''; showView('records');};renderRecords();}
}
function renderListSchedule(){
 const admin=['owner','admin'].includes(state.user.role),end=datePlus(weekStart,7);
 const week=state.lessons.filter(l=>l.status!=='cancelled'&&l.starts_at>=weekStart&&l.starts_at<end&&(state.user.role!=='teacher'||l.teacher_id==state.user.teacher_id)&&(!admin||!teacherFilter||l.teacher_id==teacherFilter));
 const rows=week.filter(l=>scheduleStatus==='all'||l.status===scheduleStatus);
 const done=week.filter(l=>l.status==='completed');
 const duration=done.reduce((n,l)=>n+(new Date(l.ends_at+'Z')-new Date(l.starts_at+'Z'))/3600000,0);
 $('#surface').innerHTML=`<label class="calendar-search"><input id="calendar-search" type="search" placeholder="搜索学生或老师" aria-label="搜索学生或老师" value="${escapeHTML(calendarSearch||'')}"></label><section class="stats teaching-stats"><div class="stat featured"><div class="stat-label">本周课程${icon('clock')}</div><div class="stat-value">${week.filter(l=>l.status!=='cancelled').length}<small>节</small></div><div class="stat-note">已安排 · 不含取消课程</div></div><div class="stat"><div class="stat-label">已完成</div><div class="stat-value">${done.length}<small>节</small></div><div class="stat-note">课后记录已发布</div></div><div class="stat"><div class="stat-label">${isStaff()?'已授课时长':'已完成课程时长'}</div><div class="stat-value">${Number(duration.toFixed(2))}<small>小时</small></div><div class="stat-note">按实际课程时段统计，与扣课单位分开</div></div></section><div class="calendar-toolbar"><div class="week-switch"><button class="btn icon-button" id="prev-week" aria-label="上一周">‹</button><strong>${formatDate(weekStart)} — ${formatDate(datePlus(weekStart,6))}<small>${weekStart.slice(0,4)}</small></strong><button class="btn icon-button" id="next-week" aria-label="下一周">›</button><button class="btn" id="this-week">本周</button></div><div class="calendar-filters">${admin?`<select id="teacher-filter" aria-label="按老师筛选"><option value="">全部老师</option>${state.teachers.map(t=>`<option data-user-content value="${t.id}" ${teacherFilter==t.id?'selected':''}>${escapeHTML(t.name)}</option>`).join('')}</select>`:''}<select id="status-filter" aria-label="按课程状态筛选">${[['all','全部状态'],['scheduled','待上课 / 待记录'],['completed','已完成']].map(([v,t])=>`<option value="${v}" ${v===scheduleStatus?'selected':''}>${t}</option>`).join('')}</select></div></div>${state.user.role==='owner'?'<p class="footnote">拖动课程卡片到其他日期可调整排课；点击空白处可新增当天课程。</p>':''}${state.user.role==='admin'?timeCalendar(rows):parentCalendar(rows)}<p class="footnote">时间以 ${escapeHTML(state.timezone)} 为准。排课不扣课时；完成课程并发布记录后才扣除。</p>`;
 bindWeekButton('prev-week', ()=>changeScheduleWeek(datePlus(weekStart,-7)));bindWeekButton('next-week', ()=>changeScheduleWeek(datePlus(weekStart,7)));bindWeekButton('this-week', ()=>changeScheduleWeek(monday(state.today)));
 if($('#teacher-filter'))$('#teacher-filter').onchange=e=>{teacherFilter=e.target.value;renderSchedule();};
 $('#status-filter').onchange=e=>{scheduleStatus=e.target.value;renderSchedule();};
 const calendarSearchBox=$('#calendar-search');
 if(calendarSearchBox && typeof applyCalendarSearch==='function'){calendarSearchBox.oninput=event=>{calendarSearch=event.target.value;applyCalendarSearch();};applyCalendarSearch();}
 bindLessons();
 initCalendarDragging();
 const listBanner=typeof recurrenceBanner==='function'?recurrenceBanner():'';
 if(listBanner)$('#surface').insertAdjacentHTML('afterbegin',listBanner);
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
 const first=Math.min(7,...(hours.length?hours:[7])),last=Math.max(21,...(hours.length?hours:[21]));
 return `<div class="time-calendar"><table class="time-table"><thead><tr><th class="time-axis">时间</th>${days.map((day,i)=>`<th class="${day===state.today?'calendar-today':''}"><span>${['周一','周二','周三','周四','周五','周六','周日'][i]}</span><strong>${day.slice(5).replace('-',' / ')}</strong></th>`).join('')}</tr></thead><tbody>${Array.from({length:last-first+1},(_,i)=>{
 const hour=String(first+i).padStart(2,'0')+':00';
 return `<tr><th class="time-axis">${hour}</th>${days.map(day=>{
 const slot=day+'T'+hour,list=rows.filter(l=>l.starts_at.slice(0,13)===slot.slice(0,13));
 return `<td class="${day===state.today?'calendar-today':''}">${list.map(lessonCard).join('')}${['owner','admin'].includes(state.user.role)?`<button class="calendar-slot ${list.length?'slot-add':''}" data-slot="${slot}" aria-label="${day} ${hour} · 新增排课">${list.length?'+':'<span>暂无课程</span><small>＋ 排课</small>'}</button>`:''}</td>`;
 }).join('')}</tr>`;
 }).join('')}</tbody></table></div>`;
}
const lessonColors=[['green','绿色'],['blue','蓝色'],['purple','紫色'],['pink','粉色'],['orange','橙色'],['yellow','黄色'],['gray','灰色']];
function lessonCard(l){
 const owner=state.user.role==='owner',color=lessonColors.some(([v])=>v===l.color)?l.color:'green',names=l.students.map(s=>s.name),students=names.map(userHTML).join(' · ');
 const subject=l.subject_name && !names.includes(l.subject_name)?l.subject_name:'';
 return `<button class="lesson-card ${l.status}${lessonIsAbsent(l)?' absent':''}${typeof lessonDone==='function'&&lessonDone(l)?' completed':''} ${owner?'owner-lesson color-'+color:''}" data-lesson-detail="${l.id}" ${owner&&l.status==='scheduled'&&!lessonIsAbsent(l)?'draggable="true" title="拖动到其他日期可调整课程"':''}>${owner?`<strong class="lesson-students">${students||'还没有学生'}</strong>`:''}<div class="lesson-time">${l.starts_at.slice(11)}–${l.ends_at.slice(11)} ${typeBadge(l.course_type_name)}</div><strong class="lesson-subject">${userHTML(subject||l.course_type_name||'')}</strong>${lessonIsAbsent(l)?'<em class="absence-tag">请假</em>':''}<span>${userHTML(l.teacher_name)}</span>${owner?'':`<span class="lesson-students">${students}</span>`}<div class="lesson-card-foot"><span class="lesson-state">${lessonStatus(l)}</span><span>${lessonIsAbsent(l)?(Number(l.absent_charge)?'已扣课时':'未扣课时'):lessonChargeLabel(l)}</span></div></button>`;
}
function lessonColorPicker(l){return `<fieldset class="lesson-color-picker"><legend>课程颜色</legend>${lessonColors.map(([v,label])=>`<label class="color-choice color-${v}" title="${label}"><input type="radio" name="color" value="${v}" ${(l?.color||'green')===v?'checked':''}><span>${label}</span></label>`).join('')}</fieldset>`;}

function bindLessons(){document.querySelectorAll('[data-lesson-detail]').forEach(b=>b.onclick=()=>lessonDetail(b.dataset.lessonDetail));}
function renderTeachers(){
 $('#surface').innerHTML=`<section class="teacher-grid">${state.teachers.map(t=>{const upcoming=state.lessons.filter(l=>l.teacher_id===t.id&&l.status==='scheduled'&&!lessonIsAbsent(l)&&!(typeof lessonDone==='function'&&lessonDone(l))).length,managed=t.account_role!=='teacher',canEdit=!managed||state.user.role==='owner';const dutyLabel=String(t.duty||'').trim();return `<article class="teacher-card"><div class="child-top"><span class="student-icon">${userHTML(t.name.slice(0,1))}</span><div><h2>${userHTML(t.name)}</h2><p>${userHTML(t.subjects.join('、'))}</p><p>${userHTML(dutyLabel||(managed?'管理员 / 任课老师':'任课老师'))} · ${t.active?'在职':'已离职 / 停用'}</p></div></div><p class="teacher-phone">${userHTML(t.phone)}</p>${!t.active&&upcoming?'<p class="error">仍有未完成课程，请查看课表并调整任课老师。</p>':''}<div class="profile-actions">${canEdit?`<button class="btn" data-teacher-edit="${t.id}">${managed?'编辑教学科目':'编辑老师'}</button>`:''}${!managed?`${state.user.role==='owner'?`<button class="btn refund-action" data-delete-teacher="${t.id}">删除档案</button>`:''}<button class="btn" data-teacher-status="${t.id}">${t.active?'离职 / 停用':'恢复在职'}</button>`:''}</div><div class="teacher-bottom"><span>待完成 <strong>${upcoming}</strong> 节</span><button class="action" data-teacher-calendar="${t.id}">查看课表 →</button></div></article>`;}).join('')}</section><p class="footnote">离职停用后无法登录或接受新排课，历史课程和课后记录保留。</p>`;
 document.querySelectorAll('[data-teacher-calendar]').forEach(b=>b.onclick=()=>{teacherFilter=b.dataset.teacherCalendar; showView('schedule');});
 document.querySelectorAll('[data-delete-teacher]').forEach(b=>b.onclick=()=>deleteProfileModal('teacher',state.teachers.find(t=>t.id==b.dataset.deleteTeacher)));
 document.querySelectorAll('[data-teacher-edit]').forEach(b=>b.onclick=()=>teacherModal(state.teachers.find(t=>t.id==b.dataset.teacherEdit)));
 document.querySelectorAll('[data-teacher-status]').forEach(b=>b.onclick=()=>{const t=state.teachers.find(t=>t.id==b.dataset.teacherStatus);modal(t.active?'离职 / 停用':'恢复在职',`<div class="form-context">${userHTML(t.name)}<br>${t.active?'停用后无法登录或接受新排课。已有课程保留，请另行调整未完成课程。':'恢复后可使用原账号登录并接受排课。'}</div>`,'确认',async()=>{await api('teachers/status',{teacher_id:t.id,active:!t.active});toast('老师状态已更新。');},!!t.active);});
}
var offeredSubjects=['数学','英语','VCE 中数','VCE 低数','VCE 高数','新加坡数学'];
function canonicalTeacherSubject(name){
 const text=String(name||'').trim();
 if(!text) return '';
 const key=text.toLocaleLowerCase();
 const vce=[['mathematical methods','VCE 中数'],['specialist mathematics','VCE 高数'],['general mathematics','VCE 低数'],['maths methods','VCE 中数'],['math methods','VCE 中数'],['vce 中数','VCE 中数'],['vce 低数','VCE 低数'],['vce 高数','VCE 高数']];
 for(const [alias,label] of vce){if(key===alias || key.startsWith(alias+' ') || key.startsWith(alias+'·') || key.startsWith(alias+' ·')) return label;}
 const aliases={数学:'数学',maths:'数学',math:'数学',mathematics:'数学',英语:'英语',english:'英语',科学:'科学',science:'科学',物理:'物理',化学:'化学',中文:'中文',写作:'写作',writing:'写作',高数:'高数',中数:'中数','新加坡数学':'新加坡数学','singapore maths':'新加坡数学','singapore math':'新加坡数学','singapore mathematics':'新加坡数学'};
 return aliases[key]||aliases[text]||text;
}
function teacherSubjectChoices(teacher){
 const current=(teacher?.subjects||[]).map(canonicalTeacherSubject).filter(Boolean);
 const choices=[];
 const catalog=(state.subjects||[]).filter(item=>item.active).map(item=>item.name);
 [...catalog,...current].forEach(name=>{if(name && !choices.includes(name)) choices.push(name);});
 return choices;
}
function teacherModal(existing=null){
 const t=existing&&existing.id?existing:null,managed=t&&t.account_role!=='teacher',selected=(t?.subjects||[]).map(canonicalTeacherSubject);
 const choices=teacherSubjectChoices(t);
 const dutyField=`<label class="field">职责（选填）<input name="duty" maxlength="60" value="${escapeHTML(t?.duty||'')}" placeholder="如：联合校长"></label>`;
 modal(t?'编辑老师':'添加任课老师',`${managed?'<div class="form-context">此账号兼任管理职务，这里修改教学科目和职责。</div>':`<label class="field">老师姓名<input name="name" required maxlength="40" value="${escapeHTML(t?.name||'')}"></label><label class="field">登录手机号<input name="phone" type="tel" required maxlength="24" value="${escapeHTML(t?.phone||'')}"></label><label class="field">${t?'重置密码（选填）':'初始密码'}<input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" ${t?'':'required'}><small>${t?'留空保留原密码；修改手机号或密码后需重新登录。':'至少 10 位，请单独告知老师。'}</small></label>`}${dutyField}<fieldset class="student-picker"><legend>教学科目 · 可多选</legend>${choices.map(name=>`<label><input type="checkbox" name="subjects" value="${escapeHTML(name)}" ${selected.includes(name)?'checked':''}>${userHTML(name)}</label>`).join('')}</fieldset><label class="field">其他科目<input name="extra_subjects" maxlength="80" placeholder="用逗号或顿号分隔，如：化学、高数"></label><p class="footnote">已有科目默认勾选。只有取消勾选才会去掉。新科目写在「其他科目」。</p>`,'保存老师',async data=>{
  const extra=String(data.extra_subjects||'').split(/[,、，]/).map(canonicalTeacherSubject).filter(Boolean);
  const checked=[...document.querySelectorAll('#modal [name=subjects]:checked')].map(box=>canonicalTeacherSubject(box.value)).filter(Boolean);
  const subjects=[];
  [...checked,...extra].forEach(name=>{if(!subjects.includes(name)) subjects.push(name);});
  data.subjects=subjects;
  delete data.subject;
  delete data.extra_subjects;
  await api(t?'teachers/edit':'teachers',{...data,teacher_id:t?.id});
  toast('老师资料已保存。');
 });
}
function scheduleModal(existing=null,studentId='',slot='',slotEnd=''){
 if(!['owner','admin'].includes(state.user?.role)){toast('只有老板或管理员可以排课或调整课程。');return;}
 if(!bookableStudents().length){toast('请先添加学生，再安排课程。');if(['owner','admin'].includes(state.user.role)&&!state.students.length)return studentModal();return;}
 const l=existing,request_id=crypto.randomUUID(),day=slot?slot.slice(0,10):state.today,initialStart=slot||day+'T16:00',initialEnd=slotEnd||shiftScheduleTime(initialStart,60);
 modal(l?'调整课程':'新增排课',`<div class="form-context">${escapeHTML(state.timezone)} · 排课不会提前扣课时。先选学生，再选这名学生的课程，科目和课型跟着课程。</div>${state.user.role==='owner'?lessonColorPicker(l):''}<div class="two-cols"><label class="field">科目${catalogSelect(state.subjects,'subject_id',l?.subject_id,'请选择科目')}</label><label class="field">课程类型${catalogSelect(state.course_types,'course_type_id',l?.course_type_id,'请选择课程类型')}</label></div><label class="field">任课老师<select name="teacher_id" required>${state.teachers.filter(t=>t.active||t.id===l?.teacher_id).map(t=>`<option data-user-content ${t.active?'':'disabled data-inactive="1"'} value="${t.id}" ${(l?.teacher_id||teacherFilter||state.user.teacher_id)==t.id?'selected':''}>${escapeHTML(t.name)} · ${escapeHTML(t.subject)}</option>`).join('')}</select></label><div class="two-cols schedule-time-fields">${scheduleTimeField("starts_at","开始时间",l?.starts_at||initialStart)}${scheduleTimeField("ends_at","结束时间",l?.ends_at||initialEnd)}</div><p class="footnote">结束时间默认往后一小时，可手动调整。手动调整时长后，更改开始时间会保留该时长。</p><div class="two-cols"><label class="field">按课时学生：预计每人扣除课时<input name="amount" type="number" min="0.01" max="10000" step="0.01" value="${l?l.planned_units/100:1}" required></label><label class="field">上课地点（选填）<select name="location">${scheduleOptions("location",l?.location||"")}</select></label></div>${l?(l.status!=='scheduled'?'<p class="form-context">编辑时间和课程信息不会自动改动已扣余额；如需更正数量，请编辑单据或课后记录。</p>':repeatScopeFields(l)):'<div class="two-cols"><label class="field">重复安排<select name="repeat"><option value="none">不重复</option><option value="weekly">每周重复</option><option value="fortnightly">每两周重复</option></select></label><label class="field" id="repeat-end-field" hidden>结束方式<select name="repeat_end" disabled><option value="count">指定次数</option><option value="forever">永久重复</option></select></label><label class="field" id="repeat-count-field" hidden>总课次数（包含本次）<input name="repeat_count" type="number" min="2" max="52" step="1" value="10" disabled required></label></div><p id="repeat-help" class="form-context" hidden>按机构当地时间重复。可指定 2–52 次，或选择永久重复。永久课程会自动延续，也可随时调整或取消本次及后续课程。</p>'}<label class="field">搜索学生<input id="schedule-student-search" type="search" placeholder="输入姓名，中文或英文都可以" autocomplete="off"></label><div id="schedule-selected" class="schedule-selected" aria-live="polite"></div><fieldset class="student-picker" id="schedule-student-picker"><legend>选择学生及扣课科目 · 同一学生只选一个科目</legend><p id="schedule-search-empty" hidden>没有找到匹配的学生。</p>${bookableStudents((l?.students||[]).map(s=>s.id).concat(studentId?[studentId]:[])).map(s=>{const hint=typeof lessonStudentHint==='function'?lessonStudentHint(s):'';return `<label><input type="checkbox" name="student_ids" value="${s.id}" data-subject-id="${s.subject_id||''}" data-type-id="${s.course_type_id||''}" ${s.no_course?'disabled':''} ${(l?.students.some(x=>x.id===s.id)||studentId==s.id)?'checked':''}><span>${userHTML(s.name)}<small>${userHTML(s.no_course?'未选课':(s.subject_name||s.course))}${hint?` · ${hint}`:''}${s.no_course?'':` · 剩余 ${fmt(s.balance)} ${unitFor(s)}`}</small></span></label>`;}).join('')}</fieldset>`,'保存排课',async data=>{data.student_ids=[...document.querySelectorAll('[name=student_ids]:checked')].map(x=>Number(x.value));syncScheduleCourse();const subjectName=document.querySelector('[name=subject_id] option:checked')?.textContent||'';const typeName=document.querySelector('[name=course_type_id] option:checked')?.textContent||'';data.title=`${subjectName} · ${typeName}`;data.course_type_id=Number(data.course_type_id);data.subject_id=Number(data.subject_id);if(l?.series_id){const chosen=document.querySelector('#modal-form [name=scope]:checked');if(!chosen) throw new Error('请选择这次改动应用到仅本次，还是本次及以后。');data.scope=chosen.value;}if(![...document.querySelectorAll('#modal-form [name=student_ids]:checked')].length) throw new Error('每节课请选择 1–30 位学生。');const teacherLabel=(document.querySelector('#modal-form [name=teacher_id] option:checked')?.textContent||'').split('·')[0].trim();const result=await api('lessons',{...data,request_id,lesson_id:l?.id,version:l?.version,series_version:l?.series_version});weekStart=monday(data.starts_at.slice(0,10));view='schedule';toast(l?(data.scope==='future'?`本次及以后的课已保存${teacherLabel?'，任课老师：'+teacherLabel:''}。`:`课程已更新${teacherLabel?'，任课老师：'+teacherLabel:''}。`):data.repeat_end==='forever'?'永久重复排课已保存，将自动延续。':result.created_count?`已安排 ${result.created_count} 次课程，课时暂不扣除。`:'排课已保存，课时暂不扣除。');});
 $('#modal').classList.add('wide');
 initScheduleStudentSearch();
 initScheduleTimes();
 document.querySelectorAll('#modal [name=student_ids]').forEach(box=>box.onchange=syncScheduleCourse);
 syncScheduleCourse();
 limitSingaporeChoices();
 if(!l){const repeat=$('[name=repeat]'),ending=$('[name=repeat_end]');const updateRepeat=()=>{const enabled=repeat.value!=='none',count=enabled&&ending.value==='count';$('#repeat-end-field').hidden=!enabled;ending.disabled=!enabled;$('#repeat-count-field').hidden=!count;$('[name=repeat_count]').disabled=!count;$('#repeat-help').hidden=!enabled;};repeat.onchange=updateRepeat;ending.onchange=updateRepeat;}
}
function syncScheduleCourse(){
 const checked=[...document.querySelectorAll('#modal [name=student_ids]:checked')];
 const subjects=[...new Set(checked.map(box=>box.dataset.subjectId).filter(Boolean))];
 const subjectBox=document.querySelector('#modal [name=subject_id]');
 if(subjects.length===1 && subjectBox) subjectBox.value=subjects[0];
 const student=(state.students||[]).find(item=>String(item.id)===String(checked[0]?.value));
 if(typeof syncPrimaryClass==='function') syncPrimaryClass(student?.level_code||student?.level_calendar||'');
 if(typeof limitSingaporeChoices==='function') limitSingaporeChoices();
}
function askAbsenceCharge(){
 return new Promise(resolve=>{
  let settled=false;
  const finish=value=>{if(settled) return; settled=true; resolve(value); if($('#modal').open) $('#modal').close();};
  $('#modal').classList.remove('wide');
  $('#modal-body').innerHTML=`<div class="modal-inner scope-dialog"><div class="modal-head"><h2 id="modal-title">请假</h2><button type="button" class="close" aria-label="关闭">×</button></div><p>请选择这节课是否扣课时。只影响这一次。</p><div class="scope-actions"><button type="button" class="btn primary" id="absence-charge">扣课时</button><button type="button" class="btn" id="absence-free">不扣课时</button><button type="button" class="btn" id="absence-cancel">取消</button></div></div>`;
  $('.close').onclick=()=>finish(null);
  $('#absence-charge').onclick=()=>finish(true);
  $('#absence-free').onclick=()=>finish(false);
  $('#absence-cancel').onclick=()=>finish(null);
  $('#modal').addEventListener('close', ()=>finish(null), {once:true});
  $('#modal').showModal();
 });
}
async function markAbsent(lesson, reopen){
 const charge=await askAbsenceCharge();
 if(charge==null){if(reopen) lessonDetail(lesson.id); return;}
 try{
  await api('lessons/absent',{lesson_id:lesson.id,version:lesson.version,charge});
  if($('#modal')?.open) $('#modal').close();
  await refresh();
  toast(charge?'已标记请假，并扣除课时。':'已标记请假，未扣课时。');
 }catch(error){
  toast(error.message);
  if(reopen) lessonDetail(lesson.id);
 }
}
async function undoAbsent(lesson){
 await api('lessons/absent/undo',{lesson_id:lesson.id,version:lesson.version});
 if($('#modal')?.open) $('#modal').close();
 await refresh();
 toast(Number(lesson.absent_charge)?'已取消请假，课时已退回。':'已取消请假。');
}
function lessonDetail(id){
 if(Date.now()<calendarClickSuppressedUntil)return;
 const l=lessonById(id),absent=lessonIsAbsent(l),admin=['owner','admin'].includes(state.user.role),staff=isStaff();lastFocus=document.activeElement;$('#modal').classList.add('wide');
 $('#modal-body').innerHTML=`<div class="modal-inner"><div class="modal-head"><h2 id="modal-title">${userHTML(l.subject_name||l.title)} ${typeBadge(l.course_type_name)}</h2><button type="button" class="close" aria-label="关闭">×</button></div><div class="lesson-detail-meta"><span class="badge ${absent?'absent':l.status==='scheduled'?'low':''}">${lessonStatus(l)}</span><p>${escapeHTML(l.starts_at.replace('T',' '))} — ${l.ends_at.slice(11)}<br>${userHTML(l.teacher_name)} · ${escapeHTML(l.location||'地点未填写')}</p><p>${l.students.map(s=>userHTML(s.name)).join('、')} · 预计 ${lessonChargeLabel(l)}</p>${l.title_note&&l.title_note!==l.title?`<p class="footnote">原名称：${userHTML(l.title_note)}</p>`:''}</div>${absent?`<div class="form-context">${Number(l.absent_charge)?'这节课已请假。已扣课时。不需要填写课后记录。':'这节课已请假。未扣课时。不需要填写课后记录。'}</div>`:l.status==='cancelled'?`<div class="form-context">取消原因：${userHTML(l.cancel_reason)}<br>本次课程未扣课时。</div>`:l.status==='completed'?l.reports.map(r=>reportCard(l,r,false)).join(''):`<div class="form-context">${staff?(l.reports.length?'已保存课后记录草稿，家长暂不可见。':'完成课程后，填写学习内容、作业和反馈，再确认扣课。'):'课程结束后，老师会在这里发布学习内容、作业与反馈。'}</div>`}<div class="detail-actions">${admin&&!absent&&(l.status==='scheduled'||state.user.role==='owner')?'<button class="btn" id="edit-schedule">调整排课</button>':''}${admin&&l.status==='scheduled'&&!absent?'<button class="btn" id="cancel-schedule">取消课程</button><button class="btn" id="mark-absent">请假</button>':''}${admin&&absent?'<button class="btn" id="undo-absent">取消请假</button>':''}${admin&&l.status==='scheduled'&&!absent&&l.ends_at<=state.now?'<button class="btn primary" id="quick-close">这节课已上</button>':''}${staff&&l.status!=='cancelled'&&!absent?`<button class="btn" id="write-report">${l.status==='completed'?'修改课后记录':'填写作业和反馈'}</button>`:''}<button class="btn" id="close-detail">关闭</button></div></div>`;
 const close=()=>$('#modal').close();$('.close').onclick=close;$('#close-detail').onclick=close;
 if($('#edit-schedule'))$('#edit-schedule').onclick=()=>{close();scheduleModal(l);};
 if($('#cancel-schedule'))$('#cancel-schedule').onclick=()=>{close();cancelModal(l);};
 if($('#mark-absent'))$('#mark-absent').onclick=()=>markAbsent(l,true);
 if($('#undo-absent'))$('#undo-absent').onclick=()=>undoAbsent(l).catch(error=>toast(error.message));
 if($('#quick-close'))$('#quick-close').onclick=()=>{close();quickCloseModal(l);};
 if($('#write-report'))$('#write-report').onclick=()=>{close();reportModal(l);};
 $('#modal').showModal();
}
function within48Hours(lesson){
 const start=Date.parse(String(lesson.starts_at||''));
 const now=Date.parse(String(state.now||''));
 if(!Number.isFinite(start)||!Number.isFinite(now)) return false;
 const gap=start-now;
 return gap>0 && gap<=48*3600*1000;
}
async function cancelModal(l){
 const scope=await askSeriesScope(l);
 if(!scope) return;
 let charge=false;
 if(scope==='single' && within48Hours(l)){
  charge=await askAbsenceCharge();
  if(charge==null) return;
 }
 modal('取消这节课',`<div class="form-context">${userHTML(l.title)}<br>${escapeHTML(l.starts_at.replace('T',' '))} · ${userHTML(l.teacher_name)}<br>${scope==='future'?'将取消本次及以后所有未上的课。':'只取消这一次。'} ${charge?'这一次会扣课时，老师没有课酬。':'不扣课时。'}</div><label class="field">取消原因（选填）<span class="quick"><button type="button" data-cancel-reason="学生请假">学生请假</button><button type="button" data-cancel-reason="老师请假">老师请假</button><button type="button" data-cancel-reason="改期">改期</button><button type="button" data-cancel-reason="临时停课">临时停课</button></span><textarea name="reason" maxlength="250" placeholder="可以留空"></textarea></label>`,'确认取消课程',async data=>{await api('lessons/cancel',{...data,charge,scope,lesson_id:l.id,version:l.version,series_version:l.series_version});toast(charge?'课程已取消，并扣除课时。老师没有这节课的工资。':'课程已取消，没有扣课时。');},true);
 document.querySelectorAll('[data-cancel-reason]').forEach(button=>button.onclick=()=>{$('[name=reason]').value=button.dataset.cancelReason;});
}
function expectedUnits(l,s){return unitFor(s)==='小时'?Math.round((Date.parse(l.ends_at+'Z')-Date.parse(l.starts_at+'Z'))/36000):l.planned_units;}
function lessonChargeLabel(l){const units=[...new Set(l.students.map(s=>`${fmt(expectedUnits(l,s))} ${unitFor(s)}`))];return units.length===1?units[0]+'/人':'按学生计费方式扣除';}
function reportFields(l){
 const first=l.reports[0]||{},shared=l.students.length>1,completed=l.status==='completed';
 const field=(name,label,value,required=true)=>`<label class="field">${label}<textarea name="${name}" maxlength="2000" ${required?'required':''}>${escapeHTML(value||'')}</textarea></label>`;
 const canEditHours=['owner','admin'].includes(state.user.role);
 return `${shared?`<section class="form-context"><h3>全班共用内容</h3>${field('shared_content','学习内容',first.content)}${field('shared_homework','今日作业',first.homework)}${field('shared_feedback','统一反馈',first.feedback)}</section>`:''}`+l.students.map((s,i)=>{
 const r=l.reports.find(r=>r.student_id===s.id)||{},special=shared&&!!r.feedback&&r.feedback!==first.feedback,custom=shared&&((!!r.content&&r.content!==first.content)||(!!r.homework&&r.homework!==first.homework));
 return `<fieldset class="report-student"><legend>${userHTML(s.name)} · ${unitFor(s)}</legend><label class="field">本次扣除${unitFor(s)}<input name="amount_${i}" type="number" min="0.01" max="10000" step="0.01" value="${(r.amount??expectedUnits(l,s))/100}" ${canEditHours&&!(completed&&state.user.role!=='owner')?'':'readonly'} required><small>${canEditHours?(completed?(state.user.role==='owner'?'老板调整数量会同步校正余额。':'本次只修改内容，不再次扣费。'):`当前剩余 ${fmt(s.balance)} ${unitFor(s)}${unitFor(s)==='小时'?'，默认按实际课程时长':''}`):'按排课时的数量记录，不能改时长。'}</small></label>${shared?`<label class="report-choice"><input type="checkbox" data-report-toggle="feedback_${i}" ${special?'checked':''}>此学生需要单独反馈</label><div id="report-feedback_${i}" ${special?'':'hidden'}>${field('feedback_'+i,'单独反馈',r.feedback||first.feedback,special)}</div><label class="report-choice"><input type="checkbox" data-report-toggle="content_${i}" ${custom?'checked':''}>此学生的内容或作业不同</label><div id="report-content_${i}" ${custom?'':'hidden'}>${field('content_'+i,'单独学习内容',r.content||first.content,custom)}${field('homework_'+i,'单独作业',r.homework||first.homework,custom)}</div>`:field('content_'+i,'学习内容',r.content)+field('homework_'+i,'今日作业',r.homework)+field('feedback_'+i,'课后反馈',r.feedback)}</fieldset>`;
 }).join('');
}
function reportPayload(l){return {lesson_id:l.id,version:l.version,reports:l.students.map((s,i)=>{
 const shared=l.students.length>1,custom=shared&&$(`[data-report-toggle="content_${i}"]`).checked,special=shared&&$(`[data-report-toggle="feedback_${i}"]`).checked;
 return {student_id:s.id,amount:$(`[name=amount_${i}]`).value,content:$(`[name=${shared&&!custom?'shared_content':'content_'+i}]`).value,homework:$(`[name=${shared&&!custom?'shared_homework':'homework_'+i}]`).value,feedback:$(`[name=${shared&&!special?'shared_feedback':'feedback_'+i}]`).value};
 })};}
function reportModal(l){
 const completed=l.status==='completed';
 modal(completed?'修改课后记录':'填写课后记录',`<div class="form-context">${userHTML(l.title)} · ${userHTML(l.teacher_name)}<br>${escapeHTML(l.starts_at.replace('T',' '))}<br>${completed?'保存后家长看到更新后的记录。':'共用内容会分别保存给每位学生；单独反馈仅对应家长可见。'}</div>${reportFields(l)}`,completed?'保存修改':'确认完成并扣除',async()=>{await api(completed?'reports/edit':'reports/complete',reportPayload(l));toast('课后记录已保存。');});
 $('#modal').classList.add('wide');
 document.querySelectorAll('[data-report-toggle]').forEach(box=>box.onchange=()=>{const area=$('#report-'+box.dataset.reportToggle);area.hidden=!box.checked;area.querySelectorAll('textarea').forEach(t=>t.required=box.checked);});
 if(!completed){const b=document.createElement('button');b.type='button';b.className='btn';b.textContent='保存草稿';$('.modal-footer').prepend(b);b.onclick=async()=>{const buttons=[...$('#modal-form').querySelectorAll('button')];buttons.forEach(x=>x.disabled=true);try{await api('reports/draft',reportPayload(l));$('#modal').close();await refresh();toast('草稿已保存，未扣除余额。');}catch(e){$('#modal-error').textContent=e.message;buttons.forEach(x=>x.disabled=false);}};}
}
function reportCard(l,r,withAction=true){return `<article class="feedback-card"><div class="feedback-head"><div><h3>${userHTML(r.student_name)} <span>${userHTML(l.title)}</span></h3><p>${l.starts_at.slice(0,10)} · ${userHTML(l.teacher_name)}</p></div><span class="badge ${r.reversed_by?'low':''}">${r.reversed_by?'该笔课时已撤销':`已扣 ${fmt(r.amount)} ${unitFor(r)}`}</span></div><div class="report-block"><h4>学习内容</h4><p>${userHTML(r.content)}</p></div><div class="report-block homework-block"><h4>今日作业</h4><p>${userHTML(r.homework)}</p></div><div class="report-block"><h4>课后反馈</h4><p>${userHTML(r.feedback)}</p></div><div class="feedback-footer"><span>更新于 ${escapeHTML(new Intl.DateTimeFormat(window.uiLocale==='en'?'en-AU':'zh-CN',{timeZone:state.timezone,dateStyle:'short',timeStyle:'short'}).format(new Date(r.updated_at)))}</span>${withAction&&isStaff()?`<button class="action" data-edit-report="${l.id}">修改记录</button>`:''}</div></article>`;}
function recordMatches(lesson, report){
 if(recordTeacher && String(lesson.teacher_id)!==String(recordTeacher)) return false;
 const query=recordQuery.trim().toLowerCase();
 if(!query) return true;
 const names=(lesson.students||[]).map(student=>student.name);
 const blob=[report?.student_name, report?.content, report?.homework, report?.feedback, lesson.title, lesson.teacher_name, ...names].join(' ').toLowerCase();
 return blob.includes(query);
}
function renderFeedback(){
 const done=lesson=>typeof lessonDone==='function'&&lessonDone(lesson);
 const published=state.lessons.filter(done).sort((a,b)=>b.starts_at.localeCompare(a.starts_at));
 const rows=published.flatMap(lesson=>lesson.reports.filter(report=>(!selected||report.student_id==selected)&&recordMatches(lesson, report)).map(report=>({l:lesson,r:report})));
 const waiting=isStaff()?state.lessons.filter(lesson=>!lessonIsAbsent(lesson)&&lesson.status!=='cancelled'&&!done(lesson)&&lesson.ends_at<=state.now&&recordMatches(lesson)):[];
 const teacherPick=['owner','admin'].includes(state.user.role)?`<select id="record-teacher" class="select-filter" aria-label="按老师筛选"><option value="">全部老师</option>${(state.teachers||[]).map(teacher=>`<option value="${teacher.id}" ${String(recordTeacher)===String(teacher.id)?'selected':''}>${escapeHTML(teacher.name)}</option>`).join('')}</select>`:'';
 $('#surface').innerHTML=`${waiting.length?`<section class="pending-lessons"><h2>待填写记录 <span class="count">${waiting.length}</span></h2>${waiting.map(l=>`<button class="pending-row" data-lesson-detail="${l.id}"><span><strong>${userHTML(l.title)}</strong><small>${l.starts_at.replace('T',' ')} · ${userHTML(l.teacher_name)} · ${l.students.map(s=>userHTML(s.name)).join('、')}</small></span><span>填写记录 →</span></button>`).join('')}</section>`:''}<div class="section-head record-tools"><h2>已发布记录 <span class="count">${rows.length}</span></h2><label class="calendar-search"><input id="record-search" type="search" placeholder="搜索学生或记录" aria-label="搜索学生或记录" value="${escapeHTML(recordQuery)}"></label>${teacherPick}${studentFilter()}</div><section class="feedback-grid">${rows.length?rows.map(({l,r})=>reportCard(l,r)).join(''):'<div class="panel empty">没有匹配的课后记录。</div>'}</section>`;
 if($('#record-teacher')) $('#record-teacher').onchange=event=>{recordTeacher=event.target.value;renderFeedback();};
 const search=$('#record-search');
 if(search) search.oninput=event=>{const caret=event.target.selectionStart; recordQuery=event.target.value; renderFeedback(); const box=$('#record-search'); if(box){box.focus(); if(caret!=null) box.setSelectionRange(caret, caret);}};
 $('#student-filter').onchange=e=>{selected=e.target.value;renderFeedback();};bindLessons();document.querySelectorAll('[data-edit-report]').forEach(b=>b.onclick=()=>reportModal(lessonById(b.dataset.editReport)));
}

function typeBadge(name){
 const label=name||'';
 const kind=label==='一对一'?'one':label==='一对二'?'two':'small';
 return label?`<span class="type-badge type-${kind}">${escapeHTML(label)}</span>`:'';
}
function limitSingaporeChoices(){
 const subjectBox=document.querySelector('#modal [name=subject_id]');
 const typeBox=document.querySelector('#modal [name=course_type_id]');
 const teacherBox=document.querySelector('#modal [name=teacher_id]');
 if(!subjectBox) return;
 const apply=()=>{
  const selected=subjectBox.selectedOptions&&subjectBox.selectedOptions[0]?subjectBox.selectedOptions[0].textContent.trim():'';
  const singapore=selected==='新加坡数学';
  if(typeBox) [...typeBox.options].forEach(option=>{option.hidden=singapore&&option.textContent.trim()==='一对二'; option.disabled=option.hidden; if(option.hidden&&option.selected) typeBox.value='';});
  if(teacherBox) [...teacherBox.options].forEach(option=>{
   const teacher=(state.teachers||[]).find(item=>String(item.id)===option.value);
   const blocked=singapore&&!(teacher&&teacher.account_role==='owner');
   option.hidden=blocked;
   option.disabled=blocked||option.dataset.inactive==='1';
   if(option.disabled&&option.selected){const next=[...teacherBox.options].find(item=>!item.disabled&&item.value); teacherBox.value=next?next.value:'';}
  });
  let note=document.querySelector('#singapore-teacher-note');
  if(singapore){
   if(!note && teacherBox){
    note=document.createElement('p');
    note.id='singapore-teacher-note';
    note.className='footnote';
    note.textContent='新加坡数学只由 Helen 授课。其他老师不能选。';
    teacherBox.closest('label')?.insertAdjacentElement('afterend', note);
   }
  }else if(note) note.remove();
 };
 subjectBox.addEventListener('change', apply);
 apply();
}
function catalogSelect(list, field, current, placeholder){
 const rows=(list||[]).filter(item=>item.active || String(item.id)===String(current));
 return `<select name="${field}" required><option value="">${placeholder}</option>${rows.map(item=>`<option value="${item.id}" ${String(item.id)===String(current)?'selected':''}>${escapeHTML(item.name)}</option>`).join('')}</select>`;
}
function scheduleOptions(kind,current){
 const options=(state.schedule_options||[]).filter(o=>o.kind===kind&&o.active).map(o=>o.name);
 if(current&&kind!=='course'&&!options.includes(current))options.unshift(current);
 return `<option value="">${kind==='course'?'请选择课程':'不指定地点'}</option>`+options.map(name=>`<option data-user-content value="${escapeHTML(name)}" ${name===current?'selected':''}>${escapeHTML(name)}</option>`).join('');
}
function renderScheduleSettings(){
 $('#surface').innerHTML=`<p class="form-context">科目和课程类型从列表里选。停用后不能再选，已经排好的课不受影响。</p><div class="feedback-grid"><section class="feedback-card"><div class="section-head"><h2>课程类型</h2><button class="btn primary" id="add-course-type">添加类型</button></div>${(state.course_types||[]).map(o=>`<div class="option-row"><div>${userHTML(o.name)}<small>${o.active?'使用中':'已停用'}</small></div><div class="option-actions"><button class="btn" data-type-edit="${o.id}">编辑</button></div></div>`).join('')}</section><section class="feedback-card"><div class="section-head"><h2>科目</h2><button class="btn primary" id="add-subject">添加科目</button></div>${(state.subjects||[]).map(o=>`<div class="option-row"><div>${userHTML(o.name)}<small>${o.active?'使用中':'已停用'}</small></div><div class="option-actions"><button class="btn" data-subject-edit="${o.id}">编辑</button></div></div>`).join('')}</section><section class="feedback-card"><div class="section-head"><h2>上课地点</h2><button class="btn primary" data-option-add="location">添加地点</button></div>${(state.schedule_options||[]).filter(o=>o.kind==='location').map(o=>`<div class="option-row"><div>${userHTML(o.name)}<small>${o.active?'使用中':'已停用'}</small></div><div class="option-actions"><button class="btn" data-option-edit="${o.id}">编辑</button><button class="btn" data-option-toggle="${o.id}">${o.active?'停用':'启用'}</button></div></div>`).join('')||'<p class="muted">尚未设置，请点击添加。</p>'}</section></div>`;
 const editCatalog=(path,item)=>modal(item?'编辑':'添加',`<label class="field">名称<input name="name" required maxlength="40" value="${escapeHTML(item?.name||'')}"></label><label><input type="checkbox" name="active" ${!item||item.active?'checked':''}> 使用中</label>`,'保存',async data=>{data.active=!!document.querySelector('[name=active]').checked;await api(path,{...data,id:item?.id});toast('已保存。');});
 $('#add-course-type').onclick=()=>editCatalog('course-types');
 $('#add-subject').onclick=()=>editCatalog('subjects');
 document.querySelectorAll('[data-type-edit]').forEach(b=>b.onclick=()=>editCatalog('course-types',state.course_types.find(o=>o.id==b.dataset.typeEdit)));
 document.querySelectorAll('[data-subject-edit]').forEach(b=>b.onclick=()=>editCatalog('subjects',state.subjects.find(o=>o.id==b.dataset.subjectEdit)));
 document.querySelectorAll('[data-option-add]').forEach(b=>b.onclick=()=>optionModal(b.dataset.optionAdd));
 document.querySelectorAll('[data-option-edit]').forEach(b=>b.onclick=()=>{const o=state.schedule_options.find(o=>o.id==b.dataset.optionEdit);optionModal(o.kind,o);});
 document.querySelectorAll('[data-option-toggle]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const o=state.schedule_options.find(o=>o.id==b.dataset.optionToggle);await api('schedule-options',{...o,active:!o.active});await refresh();toast('选项已更新。');}catch(e){b.disabled=false;toast(e.message);}});
}
function optionModal(kind,option=null){
 modal(option?'编辑选项':kind==='course'?'添加课程':'添加地点',`<label class="field">${kind==='course'?'课程名称':'上课地点'}<input name="name" required maxlength="${kind==='course'?80:150}" value="${escapeHTML(option?.name||'')}" placeholder="${kind==='course'?'例如：物理、化学、数学小班':'例如：教室 A、线上 Zoom'}"></label>`,'保存选项',async data=>{await api('schedule-options',{...data,kind,id:option?.id,active:option?!!option.active:true});toast('选项已保存。');});
}

function initScheduleStudentSearch(){
 const searchInput=$('#schedule-student-search'),picker=$('#schedule-student-picker'),selected=$('#schedule-selected');
 const boxes=[...picker.querySelectorAll('[name=student_ids]')],accounts=new Map((state.students||[]).map(s=>[String(s.id),s]));
 const refresh=()=>{
  const query=searchInput.value.trim().toLocaleLowerCase();let matches=0;
  for(const box of boxes){const s=accounts.get(box.value)||{};const text=[s.name,s.course,s.subject_name,s.phone,s.contact_phone].filter(Boolean).join(' ').toLocaleLowerCase();const match=!query||text.includes(query);box.closest('label').hidden=!match;if(match)matches++;}
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
 const target=monday(day);
 weekStart=target;
 if(typeof calendarSpan==='undefined' || (calendarSpan!=='day' && calendarSpan!=='month')) gcalDay=target;
 renderSchedule();
 const through=calendarSpan==='month'?datePlus(monthStart(gcalDay||target), 41):datePlus(target, calendarSpan==='day'?0:6);
 try{const next=await api('state?through='+encodeURIComponent(through));state=next;weekStart=target;renderSchedule();}catch(e){toast(e.message);}
}
function askSeriesScope(lesson){
 if(!lesson?.series_id || lesson.status!=='scheduled') return Promise.resolve('single');
 return new Promise(resolve=>{
  let settled=false;
  const finish=value=>{if(settled) return; settled=true; resolve(value); if($('#modal').open) $('#modal').close();};
  $('#modal').classList.remove('wide');
  $('#modal-body').innerHTML=`<div class="modal-inner scope-dialog"><div class="modal-head"><h2 id="modal-title">重复课程</h2><button type="button" class="close" aria-label="关闭">×</button></div><p>这次改动要应用到哪里？</p><div id="modal-error" class="error" role="alert" hidden></div><div class="scope-actions"><button type="button" class="btn primary" id="scope-single">只改本次</button><button type="button" class="btn" id="scope-future">本次及以后所有</button><button type="button" class="btn" id="scope-cancel">取消</button></div></div>`;
  $('.close').onclick=()=>finish(null);
  $('#scope-single').onclick=()=>finish('single');
  $('#scope-future').onclick=()=>finish('future');
  $('#scope-cancel').onclick=()=>finish(null);
  $('#modal').addEventListener('cancel', event=>{event.preventDefault(); finish(null);}, {once:true});
  if(!$('#modal').open) $('#modal').showModal();
 });
}
function repeatScopeFields(l){return l?.series_id&&l.status==='scheduled'?`<fieldset class="repeat-scope"><legend>这次改动应用到</legend><label><input type="radio" name="scope" value="single" checked required>仅本次课程</label><label><input type="radio" name="scope" value="future">本次及后续所有课程</label><small>已完成和已取消的课程保持不变。保存后如果不能改，原因会显示在按钮上方。</small></fieldset>`:'';}
async function moveCalendarLesson(l,day,endsAt){
 if(!l||l.status!=='scheduled')return;
 let starts_at, ends_at;
 if(endsAt){
  starts_at=day; ends_at=endsAt;
  if(starts_at===l.starts_at && ends_at===l.ends_at) return;
  try{
   const scope=await askSeriesScope(l);
   if(!scope) return;
   await api('lessons',{lesson_id:l.id,version:l.version,series_version:l.series_version,scope,title:l.title,teacher_id:l.teacher_id,starts_at,ends_at,amount:l.planned_units/100,location:l.location,color:l.color||'green',student_ids:l.students.map(s=>s.id),course_type_id:l.course_type_id,subject_id:l.subject_id});
   weekStart=monday(starts_at.slice(0,10));
   toast(scope==='future'?'本次及以后都已改时间':'已改到 '+(typeof weekdayName==='function'?weekdayName(starts_at.slice(0,10))+' ':'')+starts_at.slice(11,16));
   await refresh();
  }catch(error){toast(error.message||'没能改时间，请重试。');}
  return;
 }else{
  if(day===l.starts_at.slice(0,10))return;
  const delta=Math.round((new Date(day+'T00:00:00Z')-new Date(l.starts_at.slice(0,10)+'T00:00:00Z'))/86400000);
  starts_at=day+'T'+l.starts_at.slice(11); ends_at=datePlus(l.ends_at.slice(0,10),delta)+'T'+l.ends_at.slice(11);
 }
 const label=`${typeof weekdayName==='function'?weekdayName(starts_at.slice(0,10)):''} ${starts_at.slice(11,16)}`;
 try{
  const scope=await askSeriesScope(l);
  if(!scope) return;
  await api('lessons',{lesson_id:l.id,version:l.version,series_version:l.series_version,scope,title:l.title,teacher_id:l.teacher_id,starts_at,ends_at,amount:l.planned_units/100,location:l.location,color:l.color||'green',student_ids:l.students.map(s=>s.id),course_type_id:l.course_type_id,subject_id:l.subject_id});
  weekStart=monday(starts_at.slice(0,10));
  toast('已改到 '+label);
  await refresh();
 }catch(error){toast(error.message||'没能改时间，请重试。');}
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
 const hours=[...new Set([hour, ...Array.from({length:17},(_,i)=>String(i+7).padStart(2,'0'))])].filter(Boolean).sort();
 return `<fieldset class="schedule-time-field" data-time-field="${name}"><legend>${label}</legend><input type="hidden" name="${name}" value="${escapeHTML(value)}"><input type="date" data-time-part="date" aria-label="${label}日期" value="${value.slice(0,10)}" required><div class="schedule-clock"><select data-time-part="hour" aria-label="${label}小时">${hours.map(h=>`<option value="${h}" ${h===hour?'selected':''}>${h}</option>`).join('')}</select><span aria-hidden="true">:</span><select data-time-part="minute" aria-label="${label}分钟">${minutes.map(m=>`<option value="${m}" ${m===minute?'selected':''}>${m}</option>`).join('')}</select></div></fieldset>`;
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
