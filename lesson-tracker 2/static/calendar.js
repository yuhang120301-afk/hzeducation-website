/* Time grid for the people who schedule lessons. Times are read from the
   stored local clock text, so the click position cannot drift with timezones. */
const GCAL_PX = 64;
const GCAL_START = 7;
const GCAL_END = 21;
let gcalScroll = null;
let gcalDay = '';
let calendarMode = 'lessons';
let gcalNarrow = window.matchMedia('(max-width:760px)').matches;

let calendarSpan='week';
function gcalDays(){
 const days = Array.from({length:7}, (_,i)=>datePlus(weekStart, i));
 if(calendarSpan==='day' || (window.matchMedia('(max-width:760px)').matches && calendarSpan!=='month')){
  if(!days.includes(gcalDay)) gcalDay = days.includes(state.today) ? state.today : days[0];
  return [gcalDay];
 }
 return days;
}
function monthStart(day){return (day||weekStart||state.today).slice(0,8)+'01';}
function monthEnd(day){
 const start=monthStart(day);
 const next=start.slice(5,7)==='12'?`${Number(start.slice(0,4))+1}-01-01`:`${start.slice(0,4)}-${String(Number(start.slice(5,7))+1).padStart(2,'0')}-01`;
 return datePlus(next,-1);
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
  if(cols>3){
   const start=Math.min(...cluster.items.map(item=>item.start));
   cluster.items.forEach((item,index)=>{item.stacked=true;item.stackIndex=index;item.stackCount=cluster.items.length;item.stackStart=start;item.stackEnd=cluster.end;});
  }else cluster.items.forEach(item=>{item.cols=cols;});
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
function lessonIsOpen(lesson){
 const blob=[lesson.title, lesson.title_note, lesson.teacher_name, lesson.subject_name].filter(Boolean).join(' ');
 return /待定|试听/.test(blob);
}
function lessonDone(lesson){
 const status=String(lesson.status||'').toLowerCase();
 if(['completed','attended','done','redeemed','已完成','已上了'].includes(status)) return true;
 if(lesson.recorded) return true;
 return (lesson.reports||[]).some(report=>report.ledger_id || [report.content,report.homework,report.feedback].some(text=>String(text||'').trim()));
}
function clockLabel(value, compact){
 const hour=Number(value.slice(0,2)), minute=Number(value.slice(3,5));
 const suffix=hour>=12?'pm':'am';
 const h=hour%12||12;
 if(compact && minute===0) return `${h}${suffix}`;
 return `${h}:${String(minute).padStart(2,'0')}${suffix}`;
}
function timeRange(lesson, compact){
 const start=lesson.starts_at.slice(11,16), end=lesson.ends_at.slice(11,16);
 if(compact) return clockLabel(start, true);
 const same=(Number(start.slice(0,2))<12)===(Number(end.slice(0,2))<12);
 const startText=clockLabel(start, false).replace(/(am|pm)$/, same?'':'$1');
 return `${startText} – ${clockLabel(end, false)}`;
}
function lessonKind(lesson){
 return lesson.course_type_name || ((lesson.title||'').includes('1:2')||(lesson.title||'').includes('一对二') ? '一对二' : (lesson.title||'').includes('小班')||(lesson.title||'').includes('班课') ? '小班课' : '一对一');
}
function lessonSubject(lesson){
 if(lesson.subject_name) return lesson.subject_name;
 const skip=/^(一对一|一对二|小班课|班课|1:1|1:2|试听|待定)$/;
 return (lesson.title||'').split('·').map(part=>part.trim()).find(part=>part && !skip.test(part))||'';
}
function cardHeadline(lesson){
 const kind=lessonKind(lesson);
 const subject=lessonSubject(lesson);
 const names=(lesson.students||[]).map(student=>student.name).filter(Boolean);
 const subjectBit=subject && !names.includes(subject) && subject!==kind ? subject : '';
 if(kind==='小班课') return [names.length?`小班课 · ${names.length}人`:'小班课 · 还没有学生', subjectBit].filter(Boolean).join(' · ');
 return [names.join('、')||'未选学生', subjectBit, kind].filter(Boolean).join(' · ');
}
function cardMarkup(lesson, compact, extra){
 const headline=escapeHTML(cardHeadline(lesson));
 const when=escapeHTML(timeRange(lesson, compact));
 if(compact) return `<strong>${headline}, ${when}</strong>${extra||''}`;
 return `<strong>${headline}</strong><span>${when}</span>${extra||''}`;
}
function gcalEvent(item){
 const lesson = item.lesson;
 const start = Math.max(item.start, GCAL_START*60);
 const end = Math.min(item.end, GCAL_END*60);
 if(end<=GCAL_START*60 || start>=GCAL_END*60) return '';
 let top = ((start-GCAL_START*60)/60)*GCAL_PX;
 let height = Math.max(22, ((end-start)/60)*GCAL_PX);
 let width = 100/(item.cols||1), left = (item.col||0)*width;
 if(item.stacked){
  const slice=(item.stackEnd-item.stackStart)/item.stackCount;
  top=((item.stackStart+item.stackIndex*slice-GCAL_START*60)/60)*GCAL_PX;
  height=Math.max(22, (slice/60)*GCAL_PX-2);
  width=100; left=0;
 }
 const compact=height<40;
 const hover=`${cardHeadline(lesson)}, ${timeRange(lesson, false)}`;
 const done=lessonDone(lesson);
 return `<button type="button" class="gcal-event ${compact?'is-compact':''} ${lesson.status}${done?' completed':''} t-${teacherTone(lesson.teacher_name)}${!done&&lessonIsOpen(lesson)?' is-open':''}" data-lesson-detail="${lesson.id}" title="${escapeHTML(hover)}" style="top:${top}px;height:${height}px;left:calc(${left}% + 2px);width:calc(${width}% - 4px)">${cardMarkup(lesson, compact, '<i class="gcal-resize" aria-hidden="true"></i>')}</button>`;
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
 if(calendarSpan==='month') return renderMonth();
 const end = datePlus(weekStart, 7);
 const week = state.lessons.filter(lesson=>lesson.status!=='cancelled' && lesson.starts_at>=weekStart && lesson.starts_at<end && (!teacherFilter || String(lesson.teacher_id)===String(teacherFilter)));
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
 $('#surface').innerHTML = `<div class="calendar-toolbar"><label class="calendar-search"><input id="calendar-search" type="search" placeholder="搜索学生或老师" aria-label="搜索学生或老师" value="${escapeHTML(calendarSearch)}"></label><div class="week-switch"><button class="btn icon-button" id="prev-week" aria-label="上一周">‹</button><strong>${formatDate(weekStart)} — ${formatDate(datePlus(weekStart,6))}<small>${week.filter(lesson=>lesson.status!=='cancelled').length} 节 · 已完成 ${done.length} · ${Number(duration.toFixed(2))} 小时</small></strong><button class="btn icon-button" id="next-week" aria-label="下一周">›</button><button class="btn" id="this-week">本周</button></div>${miniPickerButton()}<div class="calendar-filters"><div class="period-switch" role="group" aria-label="日周月"><button type="button" id="span-day" class="${calendarSpan==='day'?'selected':''}">日</button><button type="button" id="span-week" class="${calendarSpan==='week'?'selected':''}">周</button><button type="button" id="span-month" class="${calendarSpan==='month'?'selected':''}">月</button></div><div class="period-switch" role="group" aria-label="日历显示"><button type="button" id="mode-lessons" class="${calendarMode==='lessons'?'selected':''}">课程</button><button type="button" id="mode-availability" class="${calendarMode==='availability'?'selected':''}">空档</button></div><select id="teacher-filter" aria-label="按老师筛选"><option value="">全部老师</option>${state.teachers.map(teacher=>`<option data-user-content value="${teacher.id}" ${teacherFilter==teacher.id?'selected':''}>${escapeHTML(teacher.name)}</option>`).join('')}</select><select id="status-filter" aria-label="按课程状态筛选">${[['all','全部状态'],['scheduled','待上课 / 待记录'],['completed','已完成']].map(([value,label])=>`<option value="${value}" ${value===scheduleStatus?'selected':''}>${label}</option>`).join('')}</select></div></div>${mobileDays}<p class="gcal-hint">${calendarMode==='availability'?(teacherFilter?'空白是这位老师可以排课的时间，色块是已经占用的时段。':'空白是还没有课程的时间。选择一位老师后，只看这位老师的空档。'):'点击空白处排一小时，拖动可选更长的时间。拖动课程可改时间。'}</p><div class="gcal ${calendarMode==='availability'?'is-availability':''}" style="--days:${days.length};--gcal-span:${GCAL_END-GCAL_START}"><div class="gcal-head"><div class="gcal-corner">时间</div>${days.map(day=>`<div class="gcal-dayhead ${day===state.today?'is-today':''}"><span>${weekday[(new Date(day+'T12:00:00Z').getUTCDay()+6)%7]}</span><strong>${Number(day.slice(8))}${day===state.today?'<small>今天</small>':''}</strong></div>`).join('')}</div><div class="gcal-scroll" id="gcal-scroll"><div class="gcal-body"><div class="gcal-gutter">${Array.from({length:GCAL_END-GCAL_START},(_,i)=>`<div class="gcal-hour"><span>${String(GCAL_START+i).padStart(2,'0')}:00</span></div>`).join('')}</div>${columns}</div></div></div><p class="footnote">时间以 ${escapeHTML(state.timezone)} 为准。排课不扣课时；确认完成并发布记录后才扣除，并进入老师工资。</p>`;
 bindWeekButton('prev-week', ()=>stepCalendar(-1));
 bindWeekButton('next-week', ()=>stepCalendar(1));
 bindWeekButton('this-week', ()=>focusCalendar(state.today));
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
  let hour = GCAL_START;
  if(state.today>=weekStart && state.today<end && state.now){
   const current = Number(state.now.slice(11,13))+Number(state.now.slice(14,16))/60;
   if(current>=GCAL_START && current<=GCAL_END) hour = Math.max(GCAL_START, current-1);
  }
  gcalScroll = (hour-GCAL_START)*GCAL_PX;
 }
 const applyScroll=()=>{if(scroller) scroller.scrollTop=gcalScroll;};
 applyScroll();
 requestAnimationFrame(applyScroll);
 scroller.onscroll=()=>{gcalScroll=scroller.scrollTop;};
 initTimeGrid();
 bindMiniPicker();
 const banner=recurrenceBanner();
 if(banner) $('#surface').insertAdjacentHTML('afterbegin', banner);
}
function recurrenceBanner(){
 if(typeof visibleWarningRange!=='function') return '';
 const [start,end]=visibleWarningRange();
 const rows=(state.recurrence_warnings||[]).filter(item=>{
  const day=typeof item==='string'?String(item).slice(0,10):(item.date||'');
  return day && day>=start && day<=end;
 });
 if(!rows.length) return '';
 const lines=rows.map(item=>{
  if(typeof item==='string') return escapeHTML(item);
  const who=[item.teacher, ...(item.students||[])].filter(Boolean).join(' · ');
  return escapeHTML(`${item.date||''} ${item.time||''} ${who}：${item.message||''}`.replace(/\s+/g,' ').trim());
 });
 return `<div class="form-context" role="alert"><strong>重复排课需要处理</strong>${lines.map(line=>`<p>${line}</p>`).join('')}<p>只显示当前这段日期里的冲突。</p></div>`;
}
function visibleWarningRange(){
 if(typeof calendarSpan!=='undefined' && calendarSpan==='month'){
  const anchor=gcalDay||weekStart||state.today;
  return [monthStart(anchor), monthEnd(anchor)];
 }
 if(typeof calendarSpan!=='undefined' && calendarSpan==='day'){
  const day=gcalDay||weekStart||state.today;
  return [day, day];
 }
 return [weekStart, datePlus(weekStart,6)];
}
function bindWeekButton(id, action){
 const button=$(id.charAt(0)==='#'?id:'#'+id);
 if(!button) return;
 button.onpointerdown=event=>{if(event.button!==0) return; event.preventDefault(); action();};
}
function stepCalendar(direction){
 const anchor=gcalDay||weekStart||state.today;
 if(calendarSpan==='day') return focusCalendar(datePlus(anchor, direction));
 if(calendarSpan==='month') return focusCalendar(datePlus(monthStart(anchor), direction>0?32:-1).slice(0,8)+'01');
 return focusCalendar(datePlus(weekStart, direction*7));
}
function focusCalendar(day){
 gcalDay=day;
 changeScheduleWeek(monday(day));
}
function miniPickerButton(){
 return `<div class="mini-wrap"><button type="button" class="btn" id="mini-toggle" aria-expanded="false">跳到日期</button><div id="mini-cal" class="mini-cal" hidden></div></div>`;
}
function paintMini(anchor){
 const start=monthStart(anchor);
 const end=monthEnd(anchor);
 const lead=(new Date(start+'T12:00:00Z').getUTCDay()+6)%7;
 const cells=Array.from({length:lead},()=>'<td></td>').concat(Array.from({length:Number(end.slice(8))},(_,i)=>{
  const day=start.slice(0,8)+String(i+1).padStart(2,'0');
  return `<td><button type="button" class="mini-day ${day===state.today?'is-today':''} ${day===(gcalDay||'')?'selected':''}" data-mini-day="${day}">${i+1}</button></td>`;
 }));
 const rows=[];
 for(let i=0;i<cells.length;i+=7) rows.push(`<tr>${cells.slice(i,i+7).join('')}</tr>`);
 return `<div class="mini-head"><button type="button" data-mini-move="-1" aria-label="上个月">‹</button><strong>${start.slice(0,4)}年${Number(start.slice(5,7))}月</strong><button type="button" data-mini-move="1" aria-label="下个月">›</button></div><table><thead><tr>${['一','二','三','四','五','六','日'].map(d=>`<th>${d}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
}
let miniAnchor='';
function bindMiniPicker(){
 const toggle=$('#mini-toggle'), panel=$('#mini-cal');
 if(!toggle||!panel) return;
 miniAnchor=miniAnchor||gcalDay||weekStart||state.today;
 panel.innerHTML=paintMini(miniAnchor);
 toggle.onclick=()=>{const open=panel.hidden; panel.hidden=!open; toggle.setAttribute('aria-expanded', String(open)); if(open){miniAnchor=gcalDay||weekStart||state.today; panel.innerHTML=paintMini(miniAnchor); bindMiniPicker();}};
 panel.querySelectorAll('[data-mini-move]').forEach(button=>button.onclick=event=>{event.stopPropagation(); miniAnchor=datePlus(monthStart(miniAnchor), button.dataset.miniMove==='1'?32:-1).slice(0,8)+'01'; panel.innerHTML=paintMini(miniAnchor); bindMiniPicker(); panel.hidden=false;});
 panel.querySelectorAll('[data-mini-day]').forEach(button=>button.onclick=()=>{panel.hidden=true; toggle.setAttribute('aria-expanded','false'); focusCalendar(button.dataset.miniDay);});
}
function renderMonth(){
 const anchor=gcalDay||weekStart||state.today;
 const start=monthStart(anchor), end=monthEnd(anchor);
 const lead=(new Date(start+'T12:00:00Z').getUTCDay()+6)%7;
 const lessons=(state.lessons||[]).filter(lesson=>lesson.status!=='cancelled' && lesson.starts_at.slice(0,10)>=start && lesson.starts_at.slice(0,10)<=end && (!teacherFilter || String(lesson.teacher_id)===String(teacherFilter)));
 const cells=Array.from({length:lead},()=>'<div class="month-day is-empty"></div>');
 for(let n=1;n<=Number(end.slice(8));n++){
  const day=start.slice(0,8)+String(n).padStart(2,'0');
  const items=lessons.filter(lesson=>lesson.starts_at.slice(0,10)===day).sort((a,b)=>a.starts_at.localeCompare(b.starts_at));
  cells.push(`<div class="month-day ${day===state.today?'is-today':''}" data-month-day="${day}"><button type="button" class="month-num">${n}</button>${items.slice(0,3).map(lesson=>{const done=lessonDone(lesson);return `<button type="button" class="month-chip gcal-event is-compact t-${teacherTone(lesson.teacher_name)} ${lesson.status}${done?' completed':''}${!done&&lessonIsOpen(lesson)?' is-open':''}" data-lesson-detail="${lesson.id}" title="${escapeHTML(cardHeadline(lesson)+', '+timeRange(lesson, false))}">${cardMarkup(lesson, true)}</button>`;}).join('')}${items.length>3?`<span class="month-more">还有 ${items.length-3} 节</span>`:''}</div>`);
 }
 $('#surface').innerHTML=`<div class="calendar-toolbar"><label class="calendar-search"><input id="calendar-search" type="search" placeholder="搜索学生或老师" value="${escapeHTML(calendarSearch)}"></label><div class="week-switch"><button class="btn icon-button" id="prev-week" aria-label="上个月">‹</button><strong>${start.slice(0,4)}年${Number(start.slice(5,7))}月<small>${lessons.length} 节</small></strong><button class="btn icon-button" id="next-week" aria-label="下个月">›</button><button class="btn" id="this-week">本月</button></div>${miniPickerButton()}<div class="calendar-filters"><div class="period-switch" role="group" aria-label="日周月"><button type="button" id="span-day">日</button><button type="button" id="span-week">周</button><button type="button" id="span-month" class="selected">月</button></div><select id="teacher-filter" aria-label="按老师筛选"><option value="">全部老师</option>${state.teachers.map(teacher=>`<option value="${teacher.id}" ${teacherFilter==teacher.id?'selected':''}>${escapeHTML(teacher.name)}</option>`).join('')}</select></div></div><div class="month-grid"><div class="month-head">${['周一','周二','周三','周四','周五','周六','周日'].map(name=>`<span>${name}</span>`).join('')}</div><div class="month-days">${cells.join('')}</div></div>`;
 bindWeekButton('prev-week', ()=>stepCalendar(-1));
 bindWeekButton('next-week', ()=>stepCalendar(1));
 bindWeekButton('this-week', ()=>focusCalendar(state.today));
 const monthBanner=recurrenceBanner();
 if(monthBanner) $('#surface').insertAdjacentHTML('afterbegin', monthBanner);
 $('#span-day').onclick=()=>{calendarSpan='day';renderSchedule();};
 $('#span-week').onclick=()=>{calendarSpan='week';renderSchedule();};
 $('#span-month').onclick=()=>{calendarSpan='month';renderSchedule();};
 $('#teacher-filter').onchange=e=>{teacherFilter=e.target.value;renderSchedule();};
 document.querySelectorAll('[data-month-day]').forEach(cell=>cell.querySelector('.month-num').onclick=()=>{gcalDay=cell.dataset.monthDay;calendarSpan='day';weekStart=monday(gcalDay);renderSchedule();});
 document.querySelectorAll('[data-lesson-detail]').forEach(button=>button.onclick=event=>{event.stopPropagation();lessonDetail(button.dataset.lessonDetail);});
 bindMiniPicker();
 const box=$('#calendar-search');
 if(box) box.oninput=event=>{calendarSearch=event.target.value;applyCalendarSearch();};
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
   drag={x:event.clientX,y:event.clientY,moved:false,resize:!!event.target.closest('.gcal-resize')};
   button.dataset.resizing=drag.resize?'1':'0';
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
   const point = gcalSnap(event.clientY-column.getBoundingClientRect().top);
   const start = dragWasResize(button) ? span.start : point;
   const end = dragWasResize(button) ? Math.max(span.start+15, point) : point+span.duration;
   moveCalendarLesson(lesson, gcalSlot(column.dataset.day, start), gcalSlot(column.dataset.day, end));
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
function dragWasResize(button){return button.dataset.resizing==='1';}
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
function durationLabel(lesson){
 const [sh,sm]=lesson.starts_at.slice(11,16).split(':').map(Number);
 const [eh,em]=lesson.ends_at.slice(11,16).split(':').map(Number);
 const hours=Math.max(0,((eh*60+em)-(sh*60+sm))/60);
 const text=Number.isInteger(hours)?String(hours):String(Math.round(hours*10)/10);
 return `${text} 小时`;
}
function boardMoney(cents){
 const value=(cents||0)/100;
 return '$'+value.toLocaleString('en-AU',{minimumFractionDigits:value%1?2:0,maximumFractionDigits:2});
}
async function renderToday(){
 const lessons=(state.lessons||[]).filter(lesson=>lesson.starts_at.slice(0,10)===state.today && lesson.status!=='cancelled').sort((a,b)=>a.starts_at.localeCompare(b.starts_at));
 const methods={bank:'银行转账',cash:'现金',card:'刷卡',alipay:'支付宝',wechat:'微信',other:'其他'};
 $('#surface').innerHTML=`<div class="today-board"><label class="today-search"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3-3"/></svg><input id="today-search" type="search" placeholder="搜索老师或学生，直接打开他们的页面" aria-label="搜索老师或学生"></label><div id="today-hits" class="today-hits" hidden></div><div class="today-cards" id="today-cards"><div class="card"><div class="k">今日营业额</div><div class="n">…</div><div class="s">今天已上的课</div></div><div class="card good"><div class="k">今日利润</div><div class="n">…</div><div class="s">扣课酬和当天成本</div></div><div class="card"><div class="k">本月营业额</div><div class="n">…</div><div class="s">本月已上的课</div></div><div class="card good"><div class="k">本月利润</div><div class="n">…</div><div class="s">还没扣 Vincent 分成</div></div></div><div class="section"><h2>今天的课</h2>${lessons.map(lesson=>{
  const tone=teacherTone(lesson.teacher_name);
  const who=(lesson.students||[]).map(student=>[student.name,student.grade].filter(Boolean).join(' · ')).join(' · ')||lesson.title;
  const kind=lesson.course_type_name||'';
  const mine=(lesson.teacher_name||'').toLowerCase().includes('helen')?'本人 · ':'';
  const done=lessonDone(lesson);
  return `<article class="today-lesson ${done?'done':''} t-${tone}"><time>${lesson.starts_at.slice(11,16)}<small>${durationLabel(lesson)}</small></time><div class="who2"><span class="mark">${userHTML((lesson.teacher_name||'?').slice(0,1))}</span><div>${userHTML(who)}<span>${userHTML(lesson.teacher_name)} · ${mine}${userHTML(kind)}</span></div></div><div class="taps">${done?'<button type="button" class="go" disabled>已上了</button>':`<button type="button" class="go" data-today-done="${lesson.id}">上了</button><button type="button" data-today-leave="${lesson.id}">请假</button>`}</div></article>`;
 }).join('')||'<p class="muted">今天还没有课。</p>'}</div><div class="section"><h2>要处理</h2><div class="today-actions" id="today-actions"><div class="today-action"><h3>正在读取</h3></div></div></div></div>`;
 const box=$('#today-search'), hits=$('#today-hits');
 box.oninput=()=>{
  const query=box.value.trim().toLowerCase();
  if(!query){hits.hidden=true;hits.innerHTML='';return;}
  const students=studentGroups().map(group=>group[0]).filter(student=>student.name.toLowerCase().includes(query));
  const teachers=(state.teachers||[]).filter(teacher=>teacher.name.toLowerCase().includes(query));
  hits.hidden=false;
  hits.innerHTML=[...students.map(student=>`<button type="button" data-open-student="${student.id}">学生 · ${userHTML(student.name)}</button>`),...teachers.map(teacher=>`<button type="button" data-open-teacher="${teacher.id}">老师 · ${userHTML(teacher.name)}</button>`)].join('')||'<p>没有匹配的老师或学生。</p>';
  hits.querySelectorAll('[data-open-student]').forEach(button=>button.onclick=()=>{profileId=button.dataset.openStudent;view='profile';render();});
  hits.querySelectorAll('[data-open-teacher]').forEach(button=>button.onclick=()=>{teacherFilter=button.dataset.openTeacher;view='schedule';render();});
 };
 document.querySelectorAll('[data-today-done]').forEach(button=>button.onclick=()=>quickCloseModal(lessonById(button.dataset.todayDone)));
 document.querySelectorAll('[data-today-leave]').forEach(button=>button.onclick=async()=>{
  const lesson=lessonById(button.dataset.todayLeave);
  const scope=await askSeriesScope(lesson);
  if(!scope) return;
  try{await api('lessons/cancel',{lesson_id:lesson.id,version:lesson.version,series_version:lesson.series_version,scope,reason:'学生请假'});toast('已请假，没有扣课时。');}catch(error){toast(error.message);}
 });
 try{
  const data=await api('today?date='+encodeURIComponent(state.today));
  if(view!=='today') return;
  const cards=[['今日营业额',boardMoney(data.today.turnover_cents),'今天已上的课'],['今日利润',boardMoney(data.today.profit_cents),'扣课酬和当天成本'],['本月营业额',boardMoney(data.month.turnover_cents),'本月已上的课'],['本月利润',boardMoney(data.month.profit_cents),'还没扣 Vincent 分成']];
  $('#today-cards').innerHTML=cards.map((card,index)=>`<div class="card ${index%2?'good':''}"><div class="k">${card[0]}</div><div class="n">${card[1]}</div><div class="s">${card[2]}</div></div>`).join('');
  const low=(data.low_balance||[]).filter(row=>row.lessons_left<=3);
  const booked=data.arrears?.booked_without_credit||[];
  const debts=data.arrears?.debts||[];
  const unhanded=data.unhanded||[];
  const row=(name,meta,amount)=>`<div class="row"><div>${userHTML(name)}<small>${meta}</small></div><b>${amount}</b></div>`;
  $('#today-actions').innerHTML=`<div class="today-action"><h3>剩余不超过 3 节 <span class="count">${low.length}</span></h3>${low.map(item=>row(item.name,`${item.grade||''} · ${item.course}`,`${item.lessons_left} 节`)).join('')||'<p class="muted">没有人低于 3 节。</p>'}</div><div class="today-action"><h3>欠费或没课了还排着 <span class="count">${booked.length+debts.length}</span></h3>${booked.map(item=>row(item.student_name,`${item.subject_name||item.course||''} · 课时已用完 · 仍有课`,'去收款')).join('')}${debts.map(item=>row(item.student_name,`${item.subject_name||item.course||''} · ${item.reason||'欠费'}`,boardMoney(item.amount))).join('')|| (booked.length?'':'<p class="muted">没有欠费。</p>')}</div><div class="today-action"><h3>老师收款还没上交 <span class="count">${unhanded.length}</span></h3>${unhanded.map(item=>row(item.receiver_name||'',`${item.lesson_date||''} · ${methods[item.payment_method]||item.payment_method||''} · ${item.student_name||''}`,boardMoney(item.cash_delta))).join('')||'<p class="muted">没有未上交的代收。</p>'}</div>`;
 }catch(error){if(view==='today') $('#today-actions').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
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
