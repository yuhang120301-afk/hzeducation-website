/* Time grid for the people who schedule lessons. Times are read from the
   stored local clock text, so the click position cannot drift with timezones. */
const GCAL_PX = 64;
const GCAL_START = 9;
const GCAL_END = 21;
let gcalScroll = null;
let gcalDay = '';
let calendarMode = 'lessons';
let gcalNarrow = window.matchMedia('(max-width:760px)').matches;

let calendarSpan='week';
function gcalDays(){
 const days = Array.from({length:7}, (_,i)=>datePlus(weekStart, i));
 if(calendarSpan==='day' || window.matchMedia('(max-width:760px)').matches){
  if(!days.includes(gcalDay)) gcalDay = days.includes(state.today) ? state.today : days[0];
  return [gcalDay];
 }
 return days;
}
function teacherTone(name){
 const n=(name||'').toLowerCase();
 if(n.includes('helen')) return 'helen';
 if(n.includes('vincent')) return 'vincent';
 if(n.includes('angela')) return 'angela';
 if(n.includes('kelsey')) return 'kelsey';
 if(n.includes('ethan')) return 'ethan';
 if(n.includes('christina')) return 'christina';
 return 'other';
}
function weekdayName(day){
 return ['周一','周二','周三','周四','周五','周六','周日'][(new Date(day+'T12:00:00Z').getUTCDay()+6)%7];
}
function gcalMinutes(value){return Number(value.slice(11,13))*60+Number(value.slice(14,16));}
function gcalClock(minutes){
 const wrapped = ((minutes % (24*60)) + 24*60) % (24*60);
 return `${String(Math.floor(wrapped/60)).padStart(2,'0')}:${String(wrapped%60).padStart(2,'0')}`;
}
function gcalSlot(day, minutes){
 const extra = Math.floor(minutes/(24*60));
 return `${extra?datePlus(day, extra):day}T${gcalClock(minutes)}`;
}
function gcalSnap(y){
 const raw = GCAL_START*60 + (y / GCAL_PX) * 60;
 const snapped = Math.round(raw / 15) * 15;
 return Math.max(GCAL_START*60, Math.min(GCAL_END*60-15, snapped));
}
function gcalSpan(lesson){
 const start = gcalMinutes(lesson.starts_at);
 let end = gcalMinutes(lesson.ends_at);
 if(lesson.ends_at.slice(0,10)!==lesson.starts_at.slice(0,10)) end += 24*60;
 return {start, end:Math.max(start+15, end), duration:Math.max(15, end-start)};
}
function gcalLayout(lessons){
 const items = lessons.map(lesson=>({lesson, ...gcalSpan(lesson)})).sort((a,b)=>a.start-b.start||a.end-b.end);
 const clusters = [];
 for(const item of items){
  let cluster = clusters.find(group=>group.end>item.start);
  if(!cluster){cluster={end:item.end, items:[]};clusters.push(cluster);}
  const used = new Set(cluster.items.filter(other=>other.end>item.start).map(other=>other.col));
  let col = 0;
  while(used.has(col)) col++;
  item.col = col;
  cluster.items.push(item);
  cluster.end = Math.max(cluster.end, item.end);
 }
 for(const cluster of clusters){
  const cols = Math.max(...cluster.items.map(item=>item.col))+1;
  cluster.items.forEach(item=>{item.cols=cols;});
 }
 return items;
}
let calendarSearch='';
function lessonMatchesSearch(lesson, query){
 const blob=[lesson.teacher_name, lesson.title, ...(lesson.students||[]).map(student=>student.name)].join(' ').toLocaleLowerCase();
 return blob.includes(query);
}
function applyCalendarSearch(){
 const query=calendarSearch.trim().toLocaleLowerCase();
 document.querySelectorAll('.gcal-event,.lesson-card').forEach(el=>{
  const lesson=lessonById(el.dataset.lessonDetail);
  const hit=!query || (lesson && lessonMatchesSearch(lesson, query));
  el.classList.toggle('search-hit', !!query && hit);
  el.classList.toggle('search-dim', !!query && !hit);
 });
}
function gcalEvent(item){
 const lesson = item.lesson;
 const start = Math.max(item.start, GCAL_START*60);
 const end = Math.min(item.end, GCAL_END*60);
 if(end<=GCAL_START*60 || start>=GCAL_END*60) return '';
 const top = ((start-GCAL_START*60)/60)*GCAL_PX;
 const height = Math.max(22, ((end-start)/60)*GCAL_PX);
 const width = 100/item.cols, left = item.col*width;
 const names = lesson.students.map(student=>userHTML(student.name)).join('、');
 const year = (lesson.students[0]&&lesson.students[0].grade) || '';
 const kind = (lesson.title||'').includes('1:2') ? '1:2' : '1:1';
 const done = lesson.status==='completed';
 return `<button type="button" class="gcal-event ${lesson.status} t-${teacherTone(lesson.teacher_name)}" data-lesson-detail="${lesson.id}" style="top:${top}px;height:${height}px;left:calc(${left}% + 2px);width:calc(${width}% - 4px)"><strong>${names||userHTML(lesson.title)}</strong><span>${year?userHTML(year)+' · ':''}${kind}${done?' · 已上了':''}</span></button>`;
}
let calendarLayout='grid';
function renderSchedule(){
 if(!state.user || !['owner','admin'].includes(state.user.role) || calendarLayout==='cards'){
  renderListSchedule();
  if(state.user && ['owner','admin'].includes(state.user.role)) injectCalendarSwitch();
  return;
 }
 renderTimeGrid();
}
function injectCalendarSwitch(){
 const bar=document.querySelector('.calendar-filters');
 if(!bar || $('#layout-grid')) return;
 bar.insertAdjacentHTML('afterbegin', `<div class="period-switch" role="group" aria-label="课表样式"><button type="button" id="layout-grid" class="${calendarLayout==='grid'?'selected':''}">时间格</button><button type="button" id="layout-cards" class="${calendarLayout==='cards'?'selected':''}">按天</button></div>`);
 $('#layout-grid').onclick=()=>{calendarLayout='grid';renderSchedule();};
 $('#layout-cards').onclick=()=>{calendarLayout='cards';renderSchedule();};
}
function renderTimeGrid(){
 if(!['owner','admin'].includes(state.user.role)) return renderListSchedule();
 const end = datePlus(weekStart, 7);
 const week = state.lessons.filter(lesson=>lesson.status!=='cancelled' && lesson.starts_at>=weekStart && lesson.starts_at<end && (!teacherFilter || lesson.teacher_id==teacherFilter));
 const rows = week.filter(lesson=>scheduleStatus==='all' || lesson.status===scheduleStatus);
 const done = week.filter(lesson=>lesson.status==='completed');
 const duration = done.reduce((sum,lesson)=>sum+(gcalSpan(lesson).duration/60), 0);
 const days = gcalDays();
 const weekday = ['周一','周二','周三','周四','周五','周六','周日'];
 const nowMinutes = state.now ? gcalMinutes(state.now.length===16?state.now:state.now.slice(0,16)) : null;
 const columns = days.map(day=>{
  const items = gcalLayout(rows.filter(lesson=>lesson.starts_at.slice(0,10)===day));
  const now = day===state.today && nowMinutes!=null && nowMinutes>=GCAL_START*60 && nowMinutes<=GCAL_END*60 ? `<div class="gcal-now" style="top:${((nowMinutes-GCAL_START*60)/60)*GCAL_PX}px"><span>${gcalClock(nowMinutes)}</span></div>` : '';
  return `<div class="gcal-col ${day===state.today?'is-today':''}" data-day="${day}">${items.map(gcalEvent).join('')}${now}</div>`;
 }).join('');
 const mobileDays = window.matchMedia('(max-width:760px)').matches ? `<div class="gcal-daystrip">${Array.from({length:7},(_,i)=>datePlus(weekStart,i)).map(day=>`<button type="button" class="gcal-daybtn ${day===days[0]?'selected':''} ${day===state.today?'is-today':''}" data-gcal-day="${day}">${weekday[(new Date(day+'T12:00:00Z').getUTCDay()+6)%7]} ${Number(day.slice(8))}</button>`).join('')}</div>` : '';
 $('#surface').innerHTML = `<div class="calendar-toolbar"><label class="calendar-search"><input id="calendar-search" type="search" placeholder="搜索学生或老师" aria-label="搜索学生或老师" value="${escapeHTML(calendarSearch)}"></label><div class="week-switch"><button class="btn icon-button" id="prev-week" aria-label="上一周">‹</button><strong>${formatDate(weekStart)} — ${formatDate(datePlus(weekStart,6))}<small>${week.filter(lesson=>lesson.status!=='cancelled').length} 节 · 已完成 ${done.length} · ${Number(duration.toFixed(2))} 小时</small></strong><button class="btn icon-button" id="next-week" aria-label="下一周">›</button><button class="btn" id="this-week">本周</button></div><div class="calendar-filters"><div class="period-switch" role="group" aria-label="日周月"><button type="button" id="span-day" class="${calendarSpan==='day'?'selected':''}">日</button><button type="button" id="span-week" class="${calendarSpan==='week'?'selected':''}">周</button><button type="button" id="span-month" class="${calendarSpan==='month'?'selected':''}">月</button></div><div class="period-switch" role="group" aria-label="日历显示"><button type="button" id="mode-lessons" class="${calendarMode==='lessons'?'selected':''}">课程</button><button type="button" id="mode-availability" class="${calendarMode==='availability'?'selected':''}">空档</button></div><select id="teacher-filter" aria-label="按老师筛选"><option value="">全部老师</option>${state.teachers.map(teacher=>`<option data-user-content value="${teacher.id}" ${teacherFilter==teacher.id?'selected':''}>${escapeHTML(teacher.name)}</option>`).join('')}</select><select id="status-filter" aria-label="按课程状态筛选">${[['all','全部状态'],['scheduled','待上课 / 待记录'],['completed','已完成']].map(([value,label])=>`<option value="${value}" ${value===scheduleStatus?'selected':''}>${label}</option>`).join('')}</select></div></div>${mobileDays}<p class="gcal-hint">${calendarMode==='availability'?(teacherFilter?'空白是这位老师可以排课的时间，色块是已经占用的时段。':'空白是还没有课程的时间。选择一位老师后，只看这位老师的空档。'):'点击空白处排一小时，拖动可选更长的时间。拖动课程可改时间。'}</p><div class="gcal ${calendarMode==='availability'?'is-availability':''}" style="--days:${days.length}"><div class="gcal-head"><div class="gcal-corner">时间</div>${days.map(day=>`<div class="gcal-dayhead ${day===state.today?'is-today':''}"><span>${weekday[(new Date(day+'T12:00:00Z').getUTCDay()+6)%7]}</span><strong>${Number(day.slice(8))}${day===state.today?'<small>今天</small>':''}</strong></div>`).join('')}</div><div class="gcal-scroll" id="gcal-scroll"><div class="gcal-body"><div class="gcal-gutter">${Array.from({length:GCAL_END-GCAL_START},(_,i)=>`<div class="gcal-hour"><span>${String(GCAL_START+i).padStart(2,'0')}:00</span></div>`).join('')}</div>${columns}</div></div></div><p class="footnote">时间以 ${escapeHTML(state.timezone)} 为准。排课不扣课时；确认完成并发布记录后才扣除，并进入老师工资。</p>`;
 $('#prev-week').onclick=()=>changeScheduleWeek(datePlus(weekStart,-7));
 $('#next-week').onclick=()=>changeScheduleWeek(datePlus(weekStart,7));
 $('#this-week').onclick=()=>changeScheduleWeek(monday(state.today));
 $('#teacher-filter').onchange=e=>{teacherFilter=e.target.value;renderSchedule();};
 $('#status-filter').onchange=e=>{scheduleStatus=e.target.value;renderSchedule();};
 $('#mode-lessons').onclick=()=>{calendarMode='lessons';renderSchedule();};
 $('#mode-availability').onclick=()=>{calendarMode='availability';renderSchedule();};
 $('#span-day').onclick=()=>{calendarSpan='day';gcalDay=state.today;renderSchedule();};
 $('#span-week').onclick=()=>{calendarSpan='week';renderSchedule();};
 $('#span-month').onclick=()=>{calendarSpan='month';renderSchedule();};
 const calendarSearchBox=$('#calendar-search');
 if(calendarSearchBox){calendarSearchBox.oninput=event=>{calendarSearch=event.target.value;applyCalendarSearch();};applyCalendarSearch();}
 document.querySelectorAll('[data-gcal-day]').forEach(button=>button.onclick=()=>{gcalDay=button.dataset.gcalDay;renderSchedule();});
 const scroller = $('#gcal-scroll');
 if(gcalScroll==null){
  let hour = 8;
  if(state.today>=weekStart && state.today<end && state.now){
   const current = Number(state.now.slice(11,13))+Number(state.now.slice(14,16))/60;
   if(current>=8 && current<=21) hour = Math.max(7, current-1);
  }
  gcalScroll = hour*GCAL_PX;
 }
 const applyScroll=()=>{if(scroller) scroller.scrollTop=gcalScroll;};
 applyScroll();
 requestAnimationFrame(applyScroll);
 scroller.onscroll=()=>{gcalScroll=scroller.scrollTop;};
 initTimeGrid();
 if(state.recurrence_warnings?.length) $('#surface').insertAdjacentHTML('afterbegin', `<div class="form-context" role="alert"><strong>重复排课需要处理</strong>${state.recurrence_warnings.map(warning=>`<p>${escapeHTML(warning)}</p>`).join('')}<p>发生冲突后的课程暂未继续生成，请调整时间或处理冲突课程。</p></div>`);
}
function initTimeGrid(){
 const fine = window.matchMedia('(pointer:fine)').matches && !window.matchMedia('(max-width:760px)').matches;
 document.querySelectorAll('.gcal-event').forEach(button=>{
  const lesson = lessonById(button.dataset.lessonDetail);
  button.onclick = event=>{event.stopPropagation();if(Date.now()<calendarClickSuppressedUntil) return;lessonDetail(lesson.id);};
  if(!fine || lesson.status!=='scheduled') return;
  let drag=null;
  button.onpointerdown = event=>{
   if(event.button!==0) return;
   event.stopPropagation();
   drag={x:event.clientX,y:event.clientY,moved:false};
   button.setPointerCapture(event.pointerId);
  };
  button.onpointermove = event=>{
   if(!drag) return;
   if(Math.hypot(event.clientX-drag.x, event.clientY-drag.y)>6) drag.moved=true;
   if(!drag.moved) return;
   button.classList.add('gcal-ghost');
   const column = columnAt(event.clientX, event.clientY) || button.closest('.gcal-col');
   const span = gcalSpan(lesson);
   const delta = Math.round(((event.clientY-drag.y)/GCAL_PX)*60/15)*15;
   const start = Math.max(0, Math.min(24*60-Math.min(span.duration,24*60), span.start+delta));
   showPreview(column, start, start+span.duration);
  };
  button.onpointerup = event=>{
   if(!drag) return;
   const moved = drag.moved;
   drag=null;
   button.classList.remove('gcal-ghost');
   if(!moved){clearPreview();return;}
   const column = columnAt(event.clientX, event.clientY);
   clearPreview();
   calendarClickSuppressedUntil = Date.now()+500;
   if(!column) return;
   const span = gcalSpan(lesson);
   const delta = Math.round(((event.clientY-button.getBoundingClientRect().top)/GCAL_PX)*60/15)*15;
   const start = gcalSnap(event.clientY-column.getBoundingClientRect().top);
   const duration = span.duration;
   moveCalendarLesson(lesson, gcalSlot(column.dataset.day, start), gcalSlot(column.dataset.day, start+duration));
   void delta;
  };
 });
 document.querySelectorAll('.gcal-col').forEach(column=>{
  let drag=null;
  column.onpointerdown = event=>{
   if(event.target.closest('.gcal-event') || event.button!==0) return;
   const y = event.clientY-column.getBoundingClientRect().top;
   drag={y, x:event.clientX, start:gcalSnap(y), moved:false};
   if(fine) column.setPointerCapture(event.pointerId);
   showPreview(column, drag.start, drag.start+60);
  };
  column.onpointermove = event=>{
   if(!drag) return;
   const y = event.clientY-column.getBoundingClientRect().top;
   if(Math.hypot(event.clientX-drag.x, y-(drag.y))>8) drag.moved=true;
   if(!fine) return;
   const end = gcalSnap(y);
   const start = Math.min(drag.start, end), stop = Math.max(drag.start, end);
   showPreview(column, start, Math.max(start+15, stop));
  };
  column.onpointerup = event=>{
   if(!drag) return;
   const info = drag;
   drag=null;
   const moved = info.moved && Math.hypot(event.clientX-info.x, event.clientY-column.getBoundingClientRect().top-info.y)>8;
   clearPreview();
   if(!fine && Math.hypot(event.clientX-info.x, event.clientY-(info.y+column.getBoundingClientRect().top))>12) return;
   calendarClickSuppressedUntil = Date.now()+400;
   const y = event.clientY-column.getBoundingClientRect().top;
   const start = fine && moved ? Math.min(info.start, gcalSnap(y)) : info.start;
   const stop = fine && moved ? Math.max(start+15, Math.max(info.start, gcalSnap(y))) : start+60;
   scheduleModal(null, '', gcalSlot(column.dataset.day, start), gcalSlot(column.dataset.day, stop));
  };
  column.onpointercancel = ()=>{drag=null;clearPreview();};
 });
}
function columnAt(x,y){
 for(const element of document.elementsFromPoint(x,y)){
  const column = element.closest?.('.gcal-col');
  if(column) return column;
 }
 return null;
}
function showPreview(column, start, end){
 clearPreview();
 if(!column) return;
 const top = (start/60)*GCAL_PX, height = Math.max(18, ((end-start)/60)*GCAL_PX);
 const day = column.dataset.day;
 column.insertAdjacentHTML('beforeend', `<div class="gcal-preview" style="top:${((start-GCAL_START*60)/60)*GCAL_PX}px;height:${height}px"><em class="drag-tip">改到 ${weekdayName(day)} ${gcalClock(start)}</em></div>`);
}
function clearPreview(){document.querySelectorAll('.gcal-preview').forEach(node=>node.remove());}
async function renderToday(){
 const lessons=(state.lessons||[]).filter(lesson=>lesson.starts_at.slice(0,10)===state.today && lesson.status!=='cancelled').sort((a,b)=>a.starts_at.localeCompare(b.starts_at));
 const renew=studentGroups().filter(group=>group.some(needsRenewal));
 $('#surface').innerHTML=`<section class="stats"><div class="stat featured"><div class="stat-label">今天的课</div><div class="stat-value">${lessons.length}<small>节</small></div><div class="stat-note">${escapeHTML(state.today)} · ${escapeHTML(state.timezone)}</div></div><div class="stat"><div class="stat-label">需要续费</div><div class="stat-value">${renew.length}<small>位</small></div><div class="stat-note">剩余不超过 3 节</div></div><div class="stat" id="today-cash"><div class="stat-label">本周净收款</div><div class="stat-value">…</div><div class="stat-note">收款减退款，不是利润</div></div></section><section class="panel pending-lessons"><h2>今天</h2>${lessons.length?lessons.map(lesson=>`<button class="pending-row" data-lesson-detail="${lesson.id}"><span><strong>${lesson.students.map(student=>userHTML(student.name)).join('、')||userHTML(lesson.title)}</strong><small>${lesson.starts_at.slice(11,16)}–${lesson.ends_at.slice(11,16)} · ${userHTML(lesson.teacher_name)} · ${lessonStatus(lesson)}</small></span><span>${lesson.status==='completed'?'已扣课':'查看'} →</span></button>`).join(''):'<p class="empty">今天还没有课。</p>'}</section><section class="panel" style="margin-top:18px;padding:18px"><h2>余额不足 3 的学生</h2>${renew.length?renew.map(group=>`<p>${userHTML(group[0].name)} · ${group.filter(needsRenewal).map(account=>userHTML(account.course)+' '+fmt(regularHours(account))+' '+unitFor(account)).join('，')}</p>`).join(''):'<p class="muted">目前没有人低于 3。</p>'}</section>`;
 document.querySelectorAll('[data-lesson-detail]').forEach(button=>button.onclick=()=>lessonDetail(button.dataset.lessonDetail));
 try{
  const data=await api('reconciliation?period=week&date='+encodeURIComponent(state.today));
  if(view!=='today') return;
  $('#today-cash').innerHTML=`<div class="stat-label">本周净收款</div><div class="stat-value">${cashFmt(data.totals.net_cash_cents)}</div><div class="stat-note">收款 ${cashFmt(data.totals.receipts_cents)} · 退款 ${cashFmt(data.totals.refunds_cents)}</div>`;
 }catch(error){if(view==='today') $('#today-cash').querySelector('.stat-note').textContent=error.message;}
}
function quickCloseModal(lesson){
 const fields=lesson.students.map(student=>`<fieldset class="report-student"><legend>${userHTML(student.name)} · ${unitFor(student)}</legend><label class="field">本次扣除<input name="amount_${student.id}" type="number" min="0.01" max="10000" step="0.01" value="${(expectedUnits(lesson,student)/100)}" required></label><label class="field">这节课课酬 AUD<input name="fee_${student.id}" inputmode="decimal" placeholder="留空则按课时包单价，赠课为 0"></label></fieldset>`).join('');
 modal('这节课已上',`<div class="form-context">${userHTML(lesson.title)} · ${userHTML(lesson.teacher_name)}<br>${escapeHTML(lesson.starts_at.replace('T',' '))}<br>确认后就扣课时。作业和反馈可以之后再补。</div>${fields}<label class="field">备注（选填）<textarea name="note" maxlength="2000" placeholder="可以留空"></textarea></label>`,'确认扣课时',async data=>{
  await api('reports/close',{lesson_id:lesson.id,version:lesson.version,reports:lesson.students.map(student=>({student_id:student.id,amount:data['amount_'+student.id],fee_amount:data['fee_'+student.id]||'',content:'',homework:'',feedback:data.note||''}))});
  toast('已确认上课，课时已扣除。');
 });
}
addEventListener('resize', ()=>{
 const narrow = window.matchMedia('(max-width:760px)').matches;
 if(narrow===gcalNarrow) return;
 gcalNarrow = narrow;
 if(state.user && view==='schedule' && ['owner','admin'].includes(state.user.role)) renderSchedule();
});
