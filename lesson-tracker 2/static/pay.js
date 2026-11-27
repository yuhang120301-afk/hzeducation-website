let payPeriod='week', payDate='', payStart='', payEnd='', payRequest=0;

function ruleLabel(rule){
 if(!rule) return '未设置工资规则';
 if(rule.rule_type==='hourly') return `时薪 ${cashFmt(rule.hourly_rate_cents||0)} / 小时`;
 const percent=(rule.percent_bp/100).toLocaleString('zh-CN',{maximumFractionDigits:2})+'%';
 return rule.hourly_floor_cents?`课酬的 ${percent}，保底 ${cashFmt(rule.hourly_floor_cents)} / 小时`:`课酬的 ${percent}`;
}
function payBasis(basis){return {percent:'按课酬比例',floor:'按时薪保底',hourly:'按时薪','missing-rule':'未设置规则'}[basis]||basis;}
function payQuery(){
 if(payPeriod==='custom') return `period=custom&start=${encodeURIComponent(payStart)}&end=${encodeURIComponent(payEnd)}`;
 return `period=${payPeriod}&date=${encodeURIComponent(payDate)}`;
}
async function downloadCsv(path, filename){
 const response=await fetch(path);
 if(!response.ok){let message='导出失败';try{message=(await response.json()).error||message;}catch{} throw new Error(message);}
 const blob=await response.blob();
 const link=document.createElement('a');
 link.href=URL.createObjectURL(blob);
 link.download=filename;
 link.click();
 URL.revokeObjectURL(link.href);
}
async function renderPay(){
 if(!payDate) payDate=state.today;
 if(!payStart) payStart=state.today;
 if(!payEnd) payEnd=state.today;
 const request=++payRequest;
 const teacherPay=state.user.role==='teacher';
 const periods=teacherPay?[['day','每天'],['week','每周'],['fortnight','双周'],['month','每月']]:[['day','每天'],['week','每周'],['month','每月'],['custom','自定义']];
 if(teacherPay && !periods.some(([value])=>value===payPeriod)) payPeriod='week';
 $('#surface').innerHTML=`${typeof payTeacherId!=='undefined'&&payTeacherId?'<p class="page-back"><button type="button" class="btn" id="page-back">返回</button></p>':''}<div class="accounting-controls"><div class="period-switch" role="group" aria-label="工资周期">${periods.map(([value,label])=>`<button type="button" class="${value===payPeriod?'selected':''}" data-pay-period="${value}">${label}</button>`).join('')}</div>${!teacherPay&&payPeriod==='custom'?`<label>开始<input id="pay-start" type="date" value="${payStart}"></label><label>结束<input id="pay-end" type="date" value="${payEnd}"></label>`:`<label>选择日期<input id="pay-date" type="date" value="${payDate}"></label>`}<button class="btn" id="pay-export">导出本期 CSV</button></div><div id="pay-result"><div class="panel empty">正在计算工资…</div></div>`;
 if($('#page-back')&&typeof goBack==='function') $('#page-back').onclick=()=>goBack('/?view=pay');
 document.querySelectorAll('[data-pay-period]').forEach(button=>button.onclick=()=>{payPeriod=button.dataset.payPeriod;renderPay();});
 if($('#pay-date')) $('#pay-date').onchange=event=>{if(event.target.value){payDate=event.target.value;renderPay();}};
 if($('#pay-start')) $('#pay-start').onchange=event=>{payStart=event.target.value;if(payStart&&payEnd)renderPay();};
 if($('#pay-end')) $('#pay-end').onchange=event=>{payEnd=event.target.value;if(payStart&&payEnd)renderPay();};
 $('#pay-export').onclick=async()=>{try{await downloadCsv('/api/pay.csv?'+payQuery(),'teacher-pay.csv');}catch(error){toast(error.message);}};
 try{
  const data=await api('pay?'+payQuery());
  if(view!=='pay'||request!==payRequest) return;
  paintPay(data);
 }catch(error){if(view==='pay'&&request===payRequest) $('#pay-result').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
function moneyPlain(cents){return '$'+((cents||0)/100).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2});}
function payLessonTable(teacher){
 const rows=teacher.lessons.flatMap(lesson=>lesson.lines.map((line,index)=>({lesson,line,index})));
 const body=rows.map(({lesson,line,index})=>`<tr><td>${index?'':escapeHTML(lesson.date)+' '+escapeHTML(lesson.starts_at.slice(11,16)+'–'+lesson.ends_at.slice(11,16))}</td><td>${userHTML(line.student_name)}</td><td>${typeBadge(lesson.course_type_name)} ${userHTML(lesson.subject_name||'')}</td><td>${index?'':(lesson.minutes/60).toFixed(2)}</td><td>${line.fee_known?moneyPlain(line.fee_cents):'未定价'}</td><td>${index?'':(lesson.share_bp==null?'—':(lesson.share_bp/100)+'%')}</td><td>${index?'':moneyPlain(lesson.percent_cents)}</td><td>${index&&!lesson.top_up_cents?'':(lesson.top_up_cents?moneyPlain(lesson.top_up_cents)+' 保底补足':'—')}</td><td>${index?'':moneyPlain(lesson.pay_cents)}</td></tr>`).join('');
 return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>学生</th><th>类型</th><th>小时</th><th>课酬</th><th>分成</th><th>比例工资</th><th>保底补足</th><th>应付</th></tr></thead><tbody>${body||'<tr><td colspan="9">这个周期没有已确认的课。</td></tr>'}</tbody><tfoot><tr><td>合计</td><td></td><td></td><td>${(teacher.total_minutes/60).toFixed(2)}</td><td>${moneyPlain(teacher.total_fee_cents)}</td><td></td><td></td><td>${moneyPlain(teacher.total_top_up_cents||0)}</td><td>${moneyPlain(teacher.total_pay_cents)}</td></tr></tfoot></table></div><p><button class="btn" data-pay-export="${teacher.teacher_id}" type="button">导出这位老师 CSV</button></p>`;
}
function payWageNote(data){
 if(!data||!data.partner||!state.user||state.user.role==='teacher') return '全部上课工资';
 const total=(data.teachers||[]).reduce((sum,teacher)=>sum+(teacher.total_pay_cents||0),0);
 const institution=data.partner.institution_wage_cents||0;
 return `其中 ${cashFmt(institution)} 已计入机构成本，${cashFmt(total-institution)} 是我的学生的老师工资。`;
}
function hmsPayCard(data){
 const hms=data&&data.hms;
 if(!hms||!hms.fee_cents||!state.user||state.user.role==='teacher') return '';
 const pct=(hms.percent_bp||4000)/100;
 return `<article class="pay-card t-helen"><div class="avatar">H</div><div style="flex:1"><h2 style="margin:0">Helen工作室</h2><p class="muted">工资 ${pct}%（不另付）</p><p class="muted">Helen 亲自上的原有学生课</p></div><div><div class="muted">课酬基数</div><strong>${cashFmt(hms.fee_cents)}</strong></div><div><div class="muted">不另付</div><strong>${cashFmt(hms.wage_cents||0)}</strong></div></article>`;
}
function hmsSplitCards(wage, dividend, percent){
 const pct=percent?` ${percent/100}%`:'';
 return `<div class="sums"><div class="card"><div class="k">Helen工作室 工资${pct}（不另付）</div><div class="n">${cashFmt(wage||0)}</div></div><div class="card"><div class="k">Helen工作室 分红</div><div class="n">${cashFmt(dividend||0)}</div></div></div>`;
}
function paintPay(data){
 $('#pay-result').innerHTML=`<div class="accounting-range"><strong>${data.start}${data.start===data.end?'':' — '+data.end}</strong><span>只统计已确认并扣过课时、且没有撤销的课程。一节课的价值 = 课时包总价 ÷（付费节数 + 赠送节数）。纯赠课、没有付款的，仍是 0。</span></div><section class="stats cash-stats"><div class="stat featured"><div class="stat-label">老师上课工资</div><div class="stat-value">${cashFmt(data.teachers.reduce((sum,teacher)=>sum+teacher.total_pay_cents,0))}</div><div class="stat-note">${payWageNote(data)}</div></div></section>${data.teachers.filter(teacher=>typeof payTeacherId!=='undefined'&&payTeacherId?String(teacher.teacher_id)===String(payTeacherId):(state.user.role==='teacher'||teacher.rule)).map(teacher=>`<article data-teacher="${teacher.teacher_id}" class="pay-card t-${(teacher.name||'').toLowerCase().includes('helen')?'helen':(teacher.name||'').toLowerCase().includes('vincent')?'vincent':(teacher.name||'').toLowerCase().includes('angela')?'angela':(teacher.name||'').toLowerCase().includes('kelsey')?'kelsey':(teacher.name||'').toLowerCase().includes('ethan')?'ethan':(teacher.name||'').toLowerCase().includes('christina')?'christina':'other'}"><div class="avatar">${userHTML((teacher.name||'?').slice(0,1))}</div><div style="flex:1"><h2 style="margin:0">${userHTML(teacher.name)}</h2><p class="muted">${ruleLabel(teacher.rule)}</p><p class="muted">${teacher.lessons.length} 节 · ${(teacher.total_minutes/60).toFixed(1)} 小时</p></div><div><div class="muted">课酬基数</div><strong>${cashFmt(teacher.total_fee_cents)}</strong></div><div><div class="muted">应付</div><strong>${cashFmt(teacher.total_pay_cents)}</strong></div></article><section class="accounting-section panel pay-teacher" hidden><div class="section-head"><div><h2>${userHTML(teacher.name)}</h2><p class="muted">${ruleLabel(teacher.rule)}${teacher.rules_in_period?' · 本期内规则有变化，每节课按上课当天的规则':''}</p></div><button class="btn" data-pay-export="${teacher.teacher_id}">导出这位老师</button></div><div class="hours-reconcile"><div><span>课时</span><strong>${teacher.lessons.length}</strong></div><div><span>授课小时</span><strong>${(teacher.total_minutes/60).toFixed(2)}</strong></div><div><span>课酬基数</span><strong>${cashFmt(teacher.total_fee_cents)}</strong></div><div class="ending"><span>上课工资</span><strong>${cashFmt(teacher.total_pay_cents)}</strong></div></div>${teacher.unknown_fee_count?`<div class="accounting-warning">${teacher.unknown_fee_count} 条还没有澳元单价。可以按课时包补上收款，或直接填写这节课的课酬。</div>`:''}${teacher.lessons.length?`<div class="table-wrap"><table><thead><tr><th>日期</th><th>学生</th><th>时长</th><th>课酬</th><th>本节工资</th><th>算法</th></tr></thead><tbody>${teacher.lessons.map(lesson=>lesson.lines.map((line,index)=>`<tr><td>${index?'':escapeHTML(lesson.date)+'<small class="row-meta">'+escapeHTML(lesson.starts_at.slice(11,16)+'–'+lesson.ends_at.slice(11,16))+'</small>'}</td><td>${userHTML(line.student_name)}<small class="row-meta">${userHTML(line.course)}${state.user.role==='teacher'?'':` · ${line.is_new?'新学生':'原有学生'}`}</small></td><td>${index?'':(lesson.minutes/60).toFixed(2)+' 小时'}</td><td>${line.fee_known?cashFmt(line.fee_cents):'<span class="missing-cash">未定价</span>'}${line.fee_overridden?'<small class="row-meta">已手改</small>':''}<button class="action" data-fee-lesson="${lesson.lesson_id}" data-fee-student="${line.student_id}" data-fee-value="${line.fee_known?line.fee_cents/100:''}">改课酬</button></td><td>${index?'':cashFmt(lesson.pay_cents)}</td><td>${index?'':payBasis(lesson.pay_basis)}</td></tr>`).join('')).join('')}</tbody></table></div>`:'<p class="empty">这个周期没有已确认的课程。</p>'}</section>`).join('')}${hmsPayCard(data)}${teacherShareSection(data)}${state.user.role==='teacher'?'':paySettings(data)}`;
 document.querySelectorAll('.pay-card').forEach(card=>card.onclick=()=>{if(typeof openDetail==='function') openDetail('/teachers/'+card.dataset.teacher+'/pay');});
 if(typeof payTeacherId!=='undefined'&&payTeacherId){document.querySelectorAll('#pay-result .pay-card, #pay-result .pay-fold, #pay-result .cash-stats').forEach(el=>el.remove()); document.querySelectorAll('#pay-result .pay-teacher').forEach(el=>{el.hidden=false;});}
 document.querySelectorAll('[data-pay-export]').forEach(button=>button.onclick=async event=>{event.stopPropagation(); try{await downloadCsv('/api/pay.csv?'+payQuery()+'&teacher_id='+button.dataset.payExport,'teacher-pay.csv');}catch(error){toast(error.message);}});
 document.querySelectorAll('[data-fee-lesson]').forEach(button=>button.onclick=()=>feeModal(button));
 if(state.user.role!=='teacher') bindPaySettings();
 document.querySelectorAll('#surface details.pay-settings').forEach(panel=>{panel.open=false;});
 if(state.user.role==='teacher'){
  document.querySelectorAll('[data-fee-lesson]').forEach(button=>button.remove());
  document.querySelectorAll('#pay-result .pay-teacher').forEach(el=>{el.hidden=false;});
 }
}
let profileIdSafe=()=>typeof profileId!=='undefined'?profileId:'';
function renderProfile(){
 const routeId=profileIdSafe();
 const group=typeof studentGroupById==='function'?studentGroupById(routeId):null;
 const student=group?(group.find(item=>String(item.id)===String(routeId))||group[0]):(state.students||[]).find(item=>String(item.id)===String(routeId));
 if(!student){$('#surface').innerHTML='<div class="panel empty">请从学生列表点开一位学生。</div>';return;}
 const sid=student.id;
 const ids=new Set((state.students||[]).concat(state.archived_students||[]).filter(item=>student.profile_id&&item.profile_id===student.profile_id).map(item=>String(item.id)));
 if(!ids.size) ids.add(String(sid));
 const lessons=(state.lessons||[]).filter(lesson=>(lesson.students||[]).some(item=>ids.has(String(item.id))) && !(typeof lessonIsCancelled==='function' && lessonIsCancelled(lesson)));
 const reports=lessons.flatMap(lesson=>(lesson.reports||[]).filter(report=>ids.has(String(report.student_id))).map(report=>({...report,when:lesson.starts_at}))).sort((a,b)=>b.when.localeCompare(a.when));
 const lessonBody=lesson=>`<span class="pill">${userHTML(lesson.teacher_name)}</span><div class="grow">${escapeHTML(lesson.starts_at.replace('T',' '))} ${typeBadge(lesson.course_type_name)}<small>${userHTML(lesson.subject_name||lesson.title)}</small></div><div class="num">${lesson.status==='completed'?'已上了':lesson.status==='cancelled'?'已取消':'待上课'}</div>`;
 const lessonRow=lesson=>`<article class="trow t-${toneClass(lesson.teacher_name)}">${lessonBody(lesson)}</article>`;
 const attendedRow=lesson=>`<button type="button" class="trow trow-link t-${toneClass(lesson.teacher_name)}" data-open-lesson="${lesson.id}">${lessonBody(lesson)}</button>`;
 const reportRow=report=>`<article class="feedback-card"><h3>${escapeHTML(report.when.replace('T',' '))}</h3><p>${userHTML(report.content||'没有学习内容。')}</p><p class="footnote">作业 ${userHTML(report.homework||'无')}</p></article>`;
 const teacherView=state.user && state.user.role==='teacher';
 const parentView=state.user && state.user.role==='parent';
 const parentLine=teacherView?(typeof studyTag==='function'?studyTag(student):''):`${userHTML(student.parent_name||'未填家长')}${parentView?'':` · ${userHTML(student.contact_phone||student.phone||'')}`} ${typeof studyTag==='function'?studyTag(student):''}`;
 $('#surface').innerHTML=`<p><button class="btn" id="back-students" type="button">返回学生</button></p><article class="staff t-${toneClass(lessons[0]?.teacher_name||'')}"><div class="avatar">${userHTML(typeof nameInitial==='function'?nameInitial(student.name):student.name.slice(0,1).toUpperCase())}</div><div class="mid"><h3>${userHTML(student.name)}</h3><p class="muted">${parentLine}</p><div class="meta">${userHTML(displayLevel(student.level_label||student.grade||''))} · ${userHTML(student.subject_name||student.course)} ${typeBadge(student.course_type_name)}<br>剩余课时 ${fmt(regularHours(student))} ${typeof unitFor==='function'?unitFor(student):'课时'}<br>剩余赠送课时 ${fmt(student.gift_balance||0)} ${typeof unitFor==='function'?unitFor(student):'课时'}</div>${student.course_note&&student.course_note!==student.course?`<p class="footnote">原课程名称：${userHTML(student.course_note)}</p>`:''}</div></article>${profileSection('profile-lessons','上课记录',lessonTimeline(lessons, lessonRow, attendedRow),true)}${profileSection('profile-reports','课后记录',previewList(reports, reportRow, '还没有课后记录。'),true)}`;
 $('#back-students').onclick=()=>{if(typeof backToStudents==='function') backToStudents(); else if(typeof showView==='function') showView('overview'); else {view='overview'; render();}};
 bindProfileSections();
 document.querySelectorAll('[data-open-lesson]').forEach(button=>button.onclick=()=>{if(typeof openDetail==='function') openDetail('/students/'+sid+'/lessons/'+button.dataset.openLesson);});
}
async function renderAudit(){
 $('#surface').innerHTML='<div class="panel empty">正在读取操作日志…</div>';
 try{
  const data=await api('audit');
  if(view!=='audit') return;
  const rows=Array.isArray(data.entries)?data.entries:[];
  $('#surface').innerHTML=`<label class="calendar-search"><input id="audit-search" type="search" placeholder="搜索操作" aria-label="搜索操作"></label><section class="panel" id="audit-list">${rows.map(row=>`<p data-audit-text="${escapeHTML(row.summary||'')}">${escapeHTML((row.created_at||'').slice(0,16))} · ${userHTML(row.actor_name||'')} · ${escapeHTML(row.summary||row.action||'')}</p>`).join('')||'<p>还没有操作记录。</p>'}</section>`;
  $('#audit-search').oninput=event=>{const q=event.target.value.trim().toLowerCase();document.querySelectorAll('#audit-list p').forEach(line=>{line.hidden=q && !(line.dataset.auditText||'').toLowerCase().includes(q);});};
 }catch(error){if(view==='audit') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
let financePeriod='month', financeDate='', financeStart='', financeEnd='', financeReady=false;
function loadFinanceChoice(){
 if(financeReady) return;
 financeReady=true;
 try{
  const saved=JSON.parse(localStorage.getItem('hz-finance-range')||'{}');
  if(['day','week','month','last_month','year','custom'].includes(saved.period)) financePeriod=saved.period;
  if(saved.start) financeStart=saved.start;
  if(saved.end) financeEnd=saved.end;
 }catch(error){}
}
function saveFinanceChoice(){
 try{localStorage.setItem('hz-finance-range', JSON.stringify({period:financePeriod,start:financeStart,end:financeEnd}));}catch(error){}
}
function financeQuery(){
 if(financePeriod==='custom') return `period=custom&start=${encodeURIComponent(financeStart)}&end=${encodeURIComponent(financeEnd)}`;
 return `period=${financePeriod}&date=${encodeURIComponent(financeDate)}`;
}
function financeMonth(anchor, selected, which){
 const start=anchor.slice(0,8)+'01';
 const endDay=new Date(Date.UTC(Number(start.slice(0,4)), Number(start.slice(5,7)), 0)).getUTCDate();
 const lead=(new Date(start+'T12:00:00Z').getUTCDay()+6)%7;
 const cells=Array.from({length:lead},()=>'<td></td>').concat(Array.from({length:endDay},(_,i)=>{
  const day=start.slice(0,8)+String(i+1).padStart(2,'0');
  return `<td><button type="button" class="mini-day ${day===state.today?'is-today':''} ${day===selected?'selected':''}" data-fin-day="${day}" data-fin-which="${which}">${i+1}</button></td>`;
 }));
 let rows='';
 for(let i=0;i<cells.length;i+=7) rows+=`<tr>${cells.slice(i,i+7).join('')}</tr>`;
 return `<div class="mini-head"><button type="button" data-fin-move="-1" data-fin-which="${which}" aria-label="上个月">‹</button><strong>${start.slice(0,4)}年${Number(start.slice(5,7))}月</strong><button type="button" data-fin-move="1" data-fin-which="${which}" aria-label="下个月">›</button></div><table><thead><tr>${['一','二','三','四','五','六','日'].map(d=>`<th>${d}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`;
}
function toneClass(name){
 const n=(name||'').toLowerCase();
 if(n.includes('helen')) return 'helen';
 if(n.includes('vincent')) return 'vincent';
 if(n.includes('angela')) return 'angela';
 if(n.includes('kelsey')) return 'kelsey';
 if(n.includes('ethan')) return 'ethan';
 if(n.includes('christina')) return 'christina';
 return 'other';
}
let financeAnchor={start:'',end:''};
function bindFinanceCalendar(which, selected){
 const button=$('#fin-'+which), panel=$('#fin-'+which+'-cal');
 if(!button||!panel) return;
 if(!financeAnchor[which]) financeAnchor[which]=selected;
 const paint=()=>{
  panel.innerHTML=financeMonth(financeAnchor[which], which==='start'?financeStart:financeEnd, which);
  panel.querySelectorAll('[data-fin-move]').forEach(item=>item.onclick=event=>{
   event.stopPropagation();
   const month=financeAnchor[which].slice(0,8)+'01';
   const shifted=item.dataset.finMove==='1'?datePlus(month,32):datePlus(month,-1);
   financeAnchor[which]=shifted.slice(0,8)+'01';
   paint();
   panel.hidden=false;
  });
  panel.querySelectorAll('[data-fin-day]').forEach(item=>item.onclick=()=>{
   if(which==='start') financeStart=item.dataset.finDay; else financeEnd=item.dataset.finDay;
   if(financeEnd<financeStart){const swap=financeStart; financeStart=financeEnd; financeEnd=swap;}
   saveFinanceChoice();
   renderFinance();
  });
 };
 paint();
 button.onclick=()=>{const open=panel.hidden; panel.hidden=!open; button.setAttribute('aria-expanded', String(open));};
}
async function renderPrices(){
 $('#surface').innerHTML='<div class="panel empty">正在读取价目…</div>';
 try{
  const prices=await api('prices');
  if(view!=='prices') return;
  const money=moneyPlain;
  const table=(prices.tables||[]).find(item=>item.effective_from==='2027-01-01')||(prices.tables||[])[0]||{rows:[], validity_note:''};
  const labels={one_to_one:'一对一', one_to_two:'一对二', term:'小班课'};
  const rows=(table.rows||[]).filter(row=>row.product!=='helen');
  const packNote=row=>{
   const hour=row.hourly_cents/100;
   if(row.product==='term'){
    const session=hour*row.lesson_minutes/60;
    const counts={T1:8,T2:10,T3:9,T4:10};
    return Object.entries(counts).map(([term,n])=>`${term} $${(session*n).toFixed(2)}`).join(' · ');
   }
   return `20×1小时 $${(hour*20).toFixed(2)} · 20×1.5小时 $${(hour*30).toFixed(2)} · 另赠 1 节`;
  };
  $('#surface').innerHTML=`<p class="mock-sub">2027 价目，不含 GST。价格按年级和课程类型锁定。一对一、一对二买 20 节赠 1 节；小班课按学期，不赠课。Prep 到 Year 6 的小班课是数学 + 英语，每节 2.5 小时，$45 / 小时。有效期可以先空着。</p><label class="field">课时包有效期（未定可留空）<input id="price-validity" maxlength="80" value="${escapeHTML(table.validity_note||'')}" placeholder="Helen 还没定"></label><button class="btn" id="save-validity" type="button">保存有效期</button>${rows.map(row=>`<article class="trow"><span class="pill">${labels[row.product]||row.product}</span><div class="grow">${escapeHTML(displayLevel(row.level_from))}–${escapeHTML(displayLevel(row.level_to))} · $${(row.hourly_cents/100).toFixed(2)} / 小时<small>${packNote(row)}</small></div><button class="btn" data-price-row="${row.id}" data-hourly="${row.hourly_cents/100}" type="button">改这一档</button></article>`).join('')}`;
  $('#save-validity').onclick=async()=>{try{await api('prices/validity',{validity_note:$('#price-validity').value}); toast('有效期已保存。');}catch(error){toast(error.message);}};
  document.querySelectorAll('[data-price-row]').forEach(button=>button.onclick=()=>modal('修改这一档的时薪',`<p class="footnote">只改这一年级、这一课型。不含 GST。学生充值会按改后的价自动带出课时包。</p><label class="field">每小时 AUD<input name="hourly" type="number" min="0" step="0.01" value="${escapeHTML(button.dataset.hourly)}" required></label>`,'保存',async form=>{await api('prices/row',{id:Number(button.dataset.priceRow),hourly:form.hourly}); toast('这一档已保存。'); renderPrices();}));
 }catch(error){if(view==='prices') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
let expenseMonth='';
function shiftExpenseMonth(month, delta){
 const [year, mon]=month.split('-').map(Number);
 const next=new Date(Date.UTC(year, mon-1+delta, 1));
 return next.getUTCFullYear()+'-'+String(next.getUTCMonth()+1).padStart(2,'0');
}
async function renderExpenses(){
 const month=expenseMonth||(state.today||'').slice(0,7);
 $('#surface').innerHTML='<div class="panel empty">正在读取成本…</div>';
 let data;
 try{ data=await api('expenses?month='+encodeURIComponent(month)); }
 catch(error){ if(view==='expenses') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`; return; }
 if(view!=='expenses') return;
 expenseMonth=data.month;
 const money=cents=>typeof cashFmt==='function'?cashFmt(cents):'$'+((cents||0)/100).toFixed(2);
 const categories=data.categories||[];
 const options=categories.map(item=>`<option value="${item.id}">${escapeHTML(item.name)}</option>`).join('');
 const cards=(data.by_category||[]).map(item=>`<div class="card"><div class="k">${userHTML(item.name)}</div><div class="n">${money(item.amount_cents)}</div></div>`).join('');
 const rows=(data.entries||[]).map(entry=>`<article class="trow ${entry.voided?'muted':''}"><div class="grow"><b>${escapeHTML(entry.cost_date)} · ${userHTML(entry.category_name||entry.label)}</b><small>${userHTML(entry.note||'')} ${entry.monthly_id?'· 每月固定':''} ${entry.voided?'· 已作废':''}</small></div><div class="num">${money(entry.amount_cents)}</div>${entry.voided?'':`<button class="btn" type="button" data-expense-edit="${entry.id}">修改</button><button class="btn" type="button" data-expense-void="${entry.id}">作废</button>`}</article>`).join('');
 const fixed=(data.monthly||[]).map(item=>`<article class="trow ${item.active?'':'muted'}"><div class="grow"><b>${userHTML(item.name)}</b><small>${userHTML(item.category_name||'')} · 每月 ${item.day_of_month} 日 · ${money(item.amount_cents)} · ${escapeHTML(item.start_month)}${item.end_month?' 至 '+escapeHTML(item.end_month):' 起一直记'}${item.active?'':' · 已停止'}</small></div>${item.active?`<button class="btn" type="button" data-monthly-edit="${item.id}">修改</button><button class="btn" type="button" data-monthly-stop="${item.id}">停到本月</button>`:'<span class="muted">已停止</span>'}</article>`).join('');
 const defaultDay=expenseMonth===(state.today||'').slice(0,7)?state.today:expenseMonth+'-01';
 $('#surface').innerHTML=`<div class="calendar-toolbar"><div class="week-switch"><button class="btn icon-button" id="expense-prev" type="button" aria-label="上个月">‹</button><strong>${escapeHTML(expenseMonth)}</strong><button class="btn icon-button" id="expense-next" type="button" aria-label="下个月">›</button><button class="btn" id="expense-this" type="button">本月</button></div></div><p class="footnote">这些是机构开支，不含老师工资。每一笔都算共同成本：Vincent 的分成仍是新学生课酬减去共同成本，剩余大于 0 才按原来的比例。作废后记在操作日志里，可以用「撤销上一步」恢复。</p><div class="sums">${cards}<div class="card focus"><div class="k">本月合计</div><div class="n">${money(data.total_cents)}</div></div></div><section class="panel" style="margin-top:18px;padding:18px"><h2>记一笔</h2><form id="expense-form" class="pay-form"><label class="field">日期<input name="cost_date" type="date" value="${escapeHTML(defaultDay)}" required></label><label class="field">类别<select name="category_id" required>${options}</select></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" required placeholder="120.00"></label><label class="field">备注<input name="note" maxlength="200" placeholder="例如：白板"></label><button class="btn primary" type="submit">记一笔</button></form></section><section class="panel" style="margin-top:18px;padding:18px"><h2>${escapeHTML(expenseMonth)} 的开支</h2>${rows||'<p class="muted">这个月还没有成本。</p>'}</section><section class="panel" style="margin-top:18px;padding:18px"><h2>每月固定成本</h2><p class="footnote">到了那个月会自动记一笔，只记一次。已经记入的可以单独修改；改模板不会改写已经记入的金额。</p><form id="expense-monthly-form" class="pay-form"><label class="field">名称<input name="name" maxlength="80" required placeholder="例如：教室房租"></label><label class="field">类别<select name="category_id" required>${options}</select></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" required></label><label class="field">每月几号<input name="day_of_month" type="number" min="1" max="31" value="1" required></label><label class="field">开始月份<input name="start_month" type="month" value="${escapeHTML(expenseMonth)}" required></label><label class="field">结束月份（可空）<input name="end_month" type="month"></label><button class="btn primary" type="submit">添加固定成本</button></form>${fixed||'<p class="muted">还没有每月固定成本。</p>'}</section><section class="panel" style="margin-top:18px;padding:18px"><h2>自己的类别</h2><form id="expense-category-form" class="pay-form"><label class="field">新类别<input name="name" maxlength="40" required placeholder="例如：保险"></label><button class="btn" type="submit">添加类别</button></form></section>`;
 const send=(id, path)=>{const form=$('#'+id); if(!form) return; form.onsubmit=async event=>{event.preventDefault(); const button=event.currentTarget.querySelector('[type=submit]'); if(button) button.disabled=true; try{await api(path, Object.fromEntries(new FormData(form))); toast('已保存。'); await renderExpenses();}catch(error){toast(error.message); if(button) button.disabled=false;}};};
 send('expense-form','expenses');
 send('expense-monthly-form','expenses/monthly');
 send('expense-category-form','expenses/categories');
 $('#expense-prev').onclick=()=>{expenseMonth=shiftExpenseMonth(expenseMonth,-1); renderExpenses();};
 $('#expense-next').onclick=()=>{expenseMonth=shiftExpenseMonth(expenseMonth,1); renderExpenses();};
 $('#expense-this').onclick=()=>{expenseMonth=(state.today||'').slice(0,7); renderExpenses();};
 document.querySelectorAll('[data-expense-void]').forEach(button=>button.onclick=async()=>{try{await api('expenses/void',{id:Number(button.dataset.expenseVoid)}); toast('已作废。可以在操作日志里撤销。'); await renderExpenses();}catch(error){toast(error.message);}});
 document.querySelectorAll('[data-expense-edit]').forEach(button=>button.onclick=()=>{
  const row=(data.entries||[]).find(item=>String(item.id)===button.dataset.expenseEdit);
  if(!row) return;
  modal('修改这笔成本',`<label class="field">日期<input name="cost_date" type="date" value="${escapeHTML(row.cost_date)}" required></label><label class="field">类别<select name="category_id" required>${categories.map(item=>`<option value="${item.id}" ${Number(item.id)===Number(row.category_id)?'selected':''}>${escapeHTML(item.name)}</option>`).join('')}</select></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" value="${(row.amount_cents/100).toFixed(2)}" required></label><label class="field">备注<input name="note" maxlength="200" value="${escapeHTML(row.note||'')}"></label>`,'保存',async form=>{await api('expenses/edit',{id:row.id,...form}); toast('已修改。');});
 });
 document.querySelectorAll('[data-monthly-stop]').forEach(button=>button.onclick=async()=>{try{await api('expenses/monthly/stop',{id:Number(button.dataset.monthlyStop)}); toast('已停到本月。已经记入的还在。'); await renderExpenses();}catch(error){toast(error.message);}});
 document.querySelectorAll('[data-monthly-edit]').forEach(button=>button.onclick=()=>{
  const row=(data.monthly||[]).find(item=>String(item.id)===button.dataset.monthlyEdit);
  if(!row) return;
  modal('修改每月固定成本',`<label class="field">名称<input name="name" maxlength="80" value="${escapeHTML(row.name)}" required></label><label class="field">类别<select name="category_id" required>${categories.map(item=>`<option value="${item.id}" ${Number(item.id)===Number(row.category_id)?'selected':''}>${escapeHTML(item.name)}</option>`).join('')}</select></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" value="${(row.amount_cents/100).toFixed(2)}" required></label><label class="field">每月几号<input name="day_of_month" type="number" min="1" max="31" value="${row.day_of_month}" required></label><label class="field">开始月份<input name="start_month" type="month" value="${escapeHTML(row.start_month)}" required></label><label class="field">结束月份（可空）<input name="end_month" type="month" value="${escapeHTML(row.end_month||'')}"></label>`,'保存',async form=>{await api('expenses/monthly/edit',{id:row.id,...form}); toast('已修改。已经记入的金额不变。');});
 });
}
async function renderMonth(){
 const month=(state.today||'').slice(0,7);
 $('#surface').innerHTML='<div class="panel empty">正在读取月度对账…</div>';
 let data;
 try{ data=await api('reports/monthly?month='+encodeURIComponent(month)); }
 catch(error){ if(view==='month') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`; return; }
 if(view!=='month') return;
 const money=cents=>typeof cashFmt==='function'?cashFmt(cents):'$'+((cents||0)/100).toFixed(2);
 const lines=[
  ['收到的钱', money(data.money_received_cents)],
  ['退款', money(data.money_refunded_cents)],
  ['机构学生上过的课', money(data.institution_lessons_cents||0)],
  ['我的学生上过的课', money(data.own_lessons_cents||0)],
  [`Helen工作室 工资${data.hms_percent_bp?` ${data.hms_percent_bp/100}%`:''}（不另付）`, money(data.hms_wage_cents||0)],
  ['Helen工作室 分红', money(data.hms_dividend_cents||0)],
  ['上过的课合计', money((data.institution_lessons_cents||0)+(data.own_lessons_cents||0))],
  ['还剩的课时', ((data.outstanding_units||0)/100).toFixed(2)+' · '+money(data.outstanding_value_cents)],
  ['老师工资', money(data.teacher_pay_cents)],
  ['机构成本', money(data.cost_cents)],
  ['作废余额', ((data.forfeit_units||0)/100).toFixed(2)+' 课时'],
  ['挂账应收', money(data.receivable_cents)],
 ];
 const problems=(data.exceptions||[]).map(item=>`<li>${escapeHTML(item)}</li>`).join('');
 $('#surface').innerHTML=`${backBar()}<div class="mock-top"><div><h1 class="mock-title">月度对账</h1><p class="mock-sub">${escapeHTML(data.month||month)}</p></div></div><div class="sums">${lines.map(([name,value])=>`<div class="card"><div class="k">${name}</div><div class="n">${value}</div></div>`).join('')}</div><p class="footnote">机构成本与分红、财务报表是同一个数，含机构课的老师工资。上面的老师工资是全部上课工资。Helen工作室 工资和 Helen工作室 分红两张卡加起来是我的学生收入，工资那一笔不另付。</p><section class="panel" style="margin-top:18px;padding:18px"><h2>对不上的</h2>${problems?`<ul>${problems}</ul>`:'<p class="muted">这个月对得上。</p>'}</section>`;
 bindBack('/?view=finance');
}
async function renderReceivable(){
 $('#surface').innerHTML='<div class="panel empty">正在读取挂账…</div>';
 let data;
 try{ data=await api('receivables'); }
 catch(error){ if(view==='receivable') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`; return; }
 if(view!=='receivable') return;
 const money=cents=>typeof cashFmt==='function'?cashFmt(cents):'$'+((cents||0)/100).toFixed(2);
 const rows=data.rows||[];
 $('#surface').innerHTML=`${backBar()}<div class="mock-top"><div><h1 class="mock-title">挂账 / 欠款</h1><p class="mock-sub">还欠 ${money(data.owed_cents)}。课时已经可以用，这里的钱不是收入。</p></div></div>${rows.length?rows.map(row=>`<article class="trow"><div class="grow"><b>${userHTML(row.student_name)}</b> ${userHTML(row.course)}<small>${escapeHTML(row.pack_label)} · 从 ${escapeHTML(row.since||'')} 挂账</small></div><div class="num">还欠 ${money(row.owed_cents)}<small>总额 ${money(row.total_cents)} · 已收 ${money(row.paid_cents)}</small></div><button class="btn" type="button" data-collect-pack="${row.batch_id}" data-collect-student="${row.student_id}">收款</button></article>`).join(''):'<div class="panel empty">现在没有挂账。</div>'}`;
 document.querySelectorAll('[data-collect-pack]').forEach(button=>button.onclick=()=>{ if(typeof collectPackModal==='function') collectPackModal(button.dataset.collectStudent, button.dataset.collectPack); });
 bindBack('/?view=finance');
}
function teacherShareSection(data){
 const share=data&&data.profit_share;
 if(!share||!state.user||state.user.role!=='teacher') return '';
 const pct=(share.percent_bp||0)/100;
 const lines=(share.lines||[]).map(line=>`<tr><td>${escapeHTML(line.date)}</td><td>${userHTML(line.student_name)}</td><td>${userHTML(line.lesson||'')}</td><td>${line.fee_known?cashFmt(line.revenue_cents):'未定价'}</td><td>${cashFmt(line.share_cents||0)}</td></tr>`).join('');
 const costs=(share.costs||[]).map(cost=>`<article class="trow"><div class="grow">${escapeHTML(cost.date)} · ${userHTML(cost.label)}</div><div class="num">${cashFmt(cost.amount_cents||0)}</div></article>`).join('');
 const loss=(share.share_cents||0)<0;
 const shown=loss?'-'+cashFmt(Math.abs(share.share_cents)):cashFmt(share.share_cents||0);
 return `<section class="panel pay-share"><div class="section-head"><div><h2>分红</h2><p class="muted">${loss?`本期分红 ${shown}（机构亏损，按 ${pct}% 分摊）`:`分红 = (收入 − 成本) × ${pct}%`}</p></div><strong>${shown}</strong></div><p class="footnote">分红 = (${cashFmt(share.revenue_cents||0)} − ${cashFmt(share.cost_cents||0)}) × ${pct}% = ${shown}。${loss?'机构亏损按比例分摊。':''}机构课的老师工资已经算在成本里。</p><details class="pay-settings"><summary>明细</summary><div class="pay-settings-body"><div class="table-wrap"><table><thead><tr><th>日期</th><th>学生</th><th>课程</th><th>收入</th><th>分红</th></tr></thead><tbody>${lines||'<tr><td colspan="5">这个周期没有计入分红的课。</td></tr>'}</tbody></table></div><h3>本期成本 ${cashFmt(share.cost_cents||0)}</h3>${costs||'<p class="muted">这个周期没有机构成本。</p>'}</div></details></section>`;
}
let financeDash='';
function lessonMoneyRows(lines){
 return `<div class="table-wrap"><table><thead><tr><th>日期</th><th>学生</th><th>课程</th><th>收入</th></tr></thead><tbody>${(lines||[]).map(line=>`<tr><td>${escapeHTML(line.date)}</td><td>${userHTML(line.student_name)}</td><td>${userHTML(line.lesson||'')}</td><td>${line.fee_known?cashFmt(line.revenue_cents):'未定价'}</td></tr>`).join('')||'<tr><td colspan="4">这个周期没有课。</td></tr>'}</tbody></table></div>`;
}
function financeDetail(board, key){
 if(key==='own'){
  const rows=(board.own_lines||[]).map(line=>`<tr><td>${escapeHTML(line.date)}</td><td>${userHTML(line.student_name)}</td><td>${userHTML(line.lesson||'')}</td><td>${userHTML(line.teacher_name||'')}</td><td>${line.fee_known?cashFmt(line.fee_cents):'未定价'}</td><td>${cashFmt(line.teacher_pay_cents||0)}</td><td>${line.net_cents==null?'未定价':cashFmt(line.net_cents)}</td></tr>`).join('');
  return `<h2>我的学生收入 ${cashFmt(board.own_revenue_cents||0)}</h2>${hmsSplitCards(board.hms_wage_cents, board.hms_dividend_cents, board.hms_percent_bp)}<p class="dash-formula">Helen工作室 工资 ${cashFmt(board.hms_wage_cents||0)} + Helen工作室 分红 ${cashFmt(board.hms_dividend_cents||0)} = 我的学生收入 ${cashFmt(board.own_revenue_cents||0)}。工资按 Helen 亲自上课的课酬的 ${((board.hms_percent_bp||4000)/100)}% 列出，不另付。其他老师的工资已经从分红里扣除。</p><div class="table-wrap"><table><thead><tr><th>日期</th><th>学生</th><th>课程</th><th>老师</th><th>课酬</th><th>扣除老师工资</th><th>计入我的收入</th></tr></thead><tbody>${rows||'<tr><td colspan="7">这个周期没有原有学生的课。</td></tr>'}</tbody></table></div>`;
 }
 if(key==='revenue') return `<h2>机构收入</h2>${lessonMoneyRows(board.lines)}`;
 if(key==='cost'){
  const rows=(board.costs||[]).map(cost=>`<article class="trow"><div class="grow">${cost.label==='免费课老师工资'||cost.label==='老师工资'?`${escapeHTML(cost.date)} · ${userHTML(cost.label)} · ${userHTML(cost.student_name||'')} · ${userHTML(cost.teacher_name||'')}`:`${escapeHTML(cost.date)} · ${userHTML(cost.label)}`}</div><div class="num">${cashFmt(cost.amount_cents||0)}</div></article>`).join('');
  return `<h2>机构成本</h2>${rows||'<p class="muted">这个周期没有机构成本。</p>'}`;
 }
 if(key==='profit') return `<h2>机构利润</h2><p class="dash-formula">机构利润 = 机构收入 ${cashFmt(board.revenue_cents||0)} − 机构成本 ${cashFmt(board.cost_cents||0)} = ${cashFmt(board.profit_cents||0)}</p><p class="footnote">机构成本包含机构课的老师工资，以及房租和其他共同成本。亏损也按同样的比例分。</p>`;
 if(key==='vincent') return `<h2>Vincent 分红（30%）</h2><p class="dash-formula">分红 = (机构收入 ${cashFmt(board.revenue_cents||0)} − 机构成本 ${cashFmt(board.cost_cents||0)}) × 30% = ${cashFmt(board.vincent_cents||0)}</p><div class="table-wrap"><table><thead><tr><th>日期</th><th>学生</th><th>课程</th><th>收入</th><th>分红</th></tr></thead><tbody>${(board.lines||[]).map(line=>`<tr><td>${escapeHTML(line.date)}</td><td>${userHTML(line.student_name)}</td><td>${userHTML(line.lesson||'')}</td><td>${line.fee_known?cashFmt(line.revenue_cents):'未定价'}</td><td>${cashFmt(line.share_cents||0)}</td></tr>`).join('')||'<tr><td colspan="5">这个周期没有计入分红的课。</td></tr>'}</tbody></table></div>`;
 if(key==='helen') return `<h2>我的机构分成（70%）</h2><p class="dash-formula">我的机构分成 = 机构利润 ${cashFmt(board.profit_cents||0)} × 70% = ${cashFmt(board.helen_share_cents||0)}</p>`;
 return '';
}
function financeCards(board){
 const cards=[
  ['own','我的学生收入',board.own_revenue_cents,'原有学生的课'],
  ['revenue','机构收入',board.revenue_cents,'机构的课'],
  ['cost','机构成本',board.cost_cents,'机构课的老师工资，加上共同成本'],
  ['profit','机构利润',board.profit_cents,'机构收入 − 机构成本'],
  ['vincent','Vincent 分红（30%）',board.vincent_cents,'亏损也按 30% 分摊'],
  ['helen','我的机构分成（70%）',board.helen_share_cents,'机构利润 × 70%'],
 ];
 const missing=board.unpriced||[];
 const warning=missing.length?`<div class="accounting-warning"><strong>有 ${missing.length} 节课没有价格，请补上</strong><ul>${missing.map(row=>`<li>${escapeHTML(row.date)} · ${userHTML(row.student_name)} · ${userHTML(row.course||'')} · ${userHTML(row.teacher_name)} <button type="button" class="action" data-fee-lesson="${row.lesson_id}" data-fee-student="${row.student_id}" data-fee-value="">补上价格</button></li>`).join('')}</ul></div>`:'';
 return `${warning}<div class="dash-grid">${cards.map(([key,label,cents,note])=>`<button type="button" class="dash-card${financeDash===key?' on':''}" data-dash="${key}"><span>${label}</span><strong>${cashFmt(cents||0)}</strong><small>${note}</small></button>`).join('')}</div>${hmsSplitCards(board.hms_wage_cents, board.hms_dividend_cents, board.hms_percent_bp)}<p class="dash-formula">Helen工作室 工资 ${cashFmt(board.hms_wage_cents||0)} + Helen工作室 分红 ${cashFmt(board.hms_dividend_cents||0)} = 我的学生收入 ${cashFmt(board.own_revenue_cents||0)}</p>${financeDash?`<section class="panel dash-detail">${financeDetail(board, financeDash)}</section>`:''}<section class="dash-total"><p>本月我的总收入</p><strong>${cashFmt(board.total_cents||0)}</strong><p class="dash-formula">本月我的总收入 = 我的学生收入 ${cashFmt(board.own_revenue_cents||0)} + 我的机构分成 ${cashFmt(board.helen_share_cents||0)} + 我教机构课的工资 ${cashFmt(board.helen_institution_wage_cents||0)}</p></section>`;
}
async function renderFinance(){
 loadFinanceChoice();
 if(!financeDate) financeDate=state.today;
 if(!financeStart) financeStart=state.today.slice(0,8)+'01';
 if(!financeEnd) financeEnd=state.today;
 $('#surface').innerHTML='<div class="panel empty">正在汇总财务报表…</div>';
 try{
  const query=financeQuery();
  const data=await api('finance?'+query);
  if(view!=='finance') return;
  const paint=()=>{
   const board=data.dashboard||{};
   $('#surface').innerHTML=`<div class="mock-top"><div><h1 class="mock-title">财务报表</h1><p class="mock-sub">${escapeHTML(data.start)} – ${escapeHTML(data.end)}</p></div><div class="exports"><button class="btn" id="finance-xlsx" type="button">导出 Excel</button><button class="btn primary" id="finance-pdf" type="button">导出 PDF</button></div></div><div class="period"><div class="seg">${[['day','今天'],['week','本周'],['month','本月'],['last_month','上月'],['year','今年'],['custom','自定义']].map(([value,label])=>`<button type="button" class="${value===financePeriod?'on':''}" data-fin-period="${value}">${label}</button>`).join('')}</div>${financePeriod==='custom'?`<div class="mini-wrap"><button type="button" class="btn" id="fin-start" aria-expanded="false">开始 ${escapeHTML(financeStart)}</button><div id="fin-start-cal" class="mini-cal" hidden></div></div><div class="mini-wrap"><button type="button" class="btn" id="fin-end" aria-expanded="false">结束 ${escapeHTML(financeEnd)}</button><div id="fin-end-cal" class="mini-cal" hidden></div></div>`:''}</div>${financeCards(board)}<section class="section" id="price-types"><h2>课程类型价目</h2><div class="panel empty">正在读取价目…</div></section>`;
   document.querySelectorAll('[data-fin-period]').forEach(button=>button.onclick=()=>{financePeriod=button.dataset.finPeriod;saveFinanceChoice();renderFinance();});
   bindFinanceCalendar('start', financeStart);
   bindFinanceCalendar('end', financeEnd);
   $('#finance-xlsx').onclick=async()=>{try{await downloadCsv('/api/finance.xlsx?'+query,'HZ-Education-Melbourne-finance.xlsx');}catch(error){toast(error.message);}};
   $('#finance-pdf').onclick=async()=>{try{await downloadCsv('/api/finance.pdf?'+query,'HZ-Education-Melbourne-finance.pdf');}catch(error){toast(error.message);}};
   document.querySelectorAll('[data-dash]').forEach(button=>button.onclick=()=>{financeDash=financeDash===button.dataset.dash?'':button.dataset.dash; paint();});
   document.querySelectorAll('[data-fee-lesson]').forEach(button=>button.onclick=()=>feeModal(button));
  };
  paint();
  try{
   const prices=await api('prices');
   const host=$('#price-types');
   if(host&&view==='finance') host.querySelector('.panel')?.remove(), host.insertAdjacentHTML('beforeend', (prices.by_type||[]).map(kind=>`<article class="trow"><span class="pill">${typeBadge(kind.name)}</span><div class="grow">${kind.placeholder?'暂定':'已填写'}<small>${(kind.rows[0]&&kind.rows[0].hourly_cents)?cashFmt(kind.rows[0].hourly_cents)+' / 小时':'还没有数字'}</small></div><button class="btn" data-price-type="${kind.id}" type="button">改价格</button></article>`).join(''));
   document.querySelectorAll('[data-price-type]').forEach(button=>button.onclick=()=>modal('填写价格',`<p class="footnote">这是暂定数字，保存后就按你填的价目。不含 GST。</p><label class="field">每小时 AUD<input name="hourly" type="number" min="0" step="0.01" required></label>`,'保存',async form=>{await api('prices/save',{course_type_id:Number(button.dataset.priceType),hourly:form.hourly,effective_from:state.today});toast('价目已保存。');renderFinance();}));
  }catch(error){/* prices stay marked as unread */}
 }catch(error){if(view==='finance') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
function feeModal(button){
 modal('修改这节课的课酬',`<p class="footnote">留空并选择恢复，会重新按课时包价格 ÷ 付费课时计算。赠课仍是 0。</p><label class="field">课酬 AUD<input name="fee_amount" inputmode="decimal" value="${escapeHTML(button.dataset.feeValue)}" required></label>`,'保存手改金额',async data=>{await api('pay/fee',{lesson_id:Number(button.dataset.feeLesson),student_id:Number(button.dataset.feeStudent),fee_amount:data.fee_amount});toast('课酬已更新。'); if(view==='finance') renderFinance(); else if(view==='pay') renderPay();});
 const reset=document.createElement('button');
 reset.type='button';reset.className='btn';reset.textContent='恢复课时包单价';
 $('.modal-footer').prepend(reset);
 reset.onclick=async()=>{try{await api('pay/fee',{lesson_id:Number(button.dataset.feeLesson),student_id:Number(button.dataset.feeStudent),reset:true});$('#modal').close();toast('已恢复为课时包单价。');await refresh();}catch(error){toast(error.message);}};
}
function paySettings(data){
 const teachers=state.teachers.map(teacher=>`<option value="${teacher.id}">${escapeHTML(teacher.name)}</option>`).join('');
 const people=[...new Map(data.students.filter(student=>!student.archived).map(student=>[student.profile_id,student])).values()];
 return `<details class="panel pay-settings"><summary>工资规则和成本</summary><div class="pay-settings-body"><section><h3>老师工资规则</h3><form id="pay-rule-form" class="pay-form"><label class="field">老师<select name="teacher_id" required>${teachers}</select></label><label class="field">方式<select name="rule_type"><option value="percent">课酬百分比</option><option value="hourly">时薪</option></select></label><label class="field">百分比<input name="percent" inputmode="decimal" placeholder="40"></label><label class="field">保底时薪 AUD（选填）<input name="hourly_floor" inputmode="decimal" placeholder="35"></label><label class="field">时薪 AUD<input name="hourly_rate" inputmode="decimal" placeholder="0.00"></label><label class="field">生效日期<input name="effective_from" type="date" value="${state.today}" required></label><button class="btn primary" type="submit">保存规则</button></form><ul class="pay-rule-list">${data.rules.map(rule=>`<li>${userHTML(state.teachers.find(teacher=>teacher.id===rule.teacher_id)?.name||'老师')} · 自 ${escapeHTML(rule.effective_from)} · ${ruleLabel(rule)}</li>`).join('')||'<li>还没有规则。</li>'}</ul></section><section><h3>成本</h3><p class="footnote">房租、教材、广告这些开支请到「成本」页。这里勾选「共同成本」才会从新学生课酬里扣除。不勾选的只是记录，不参与分成。</p><form id="pay-cost-form" class="pay-form"><label class="field">名称<input name="label" maxlength="80" required placeholder="例如：房租"></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" required></label><label class="field">日期<input name="cost_date" type="date" value="${state.today}" required></label><label class="report-choice"><input type="checkbox" name="shared">这是共同成本</label><button class="btn primary" type="submit">添加一笔</button></form><ul class="pay-rule-list">${data.cost_entries.map(entry=>`<li class="${entry.voided?'muted':''}">${escapeHTML(entry.cost_date)} · ${userHTML(entry.label)} · ${cashFmt(entry.amount_cents)} · ${entry.shared?'共同成本':'不参与分成'} ${entry.voided?'（已作废）':''}<button type="button" class="action" data-cost-void="${entry.id}" data-voided="${entry.voided?0:1}">${entry.voided?'恢复':'作废'}</button></li>`).join('')||'<li>还没有单笔成本。</li>'}</ul><form id="pay-schedule-form" class="pay-form"><label class="field">固定成本名称<input name="label" maxlength="80" required></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" required></label><label class="field">周期<select name="cadence"><option value="month">每月</option><option value="week">每周</option><option value="day">每天</option></select></label><label class="field">从<input name="effective_from" type="date" value="${state.today}" required></label><label class="report-choice"><input type="checkbox" name="shared" checked>这是共同成本</label><button class="btn primary" type="submit">添加固定成本</button></form><ul class="pay-rule-list">${data.cost_schedules.map(item=>`<li>${userHTML(item.label)} · ${cashFmt(item.amount_cents)} / ${{day:'天',week:'周',month:'月'}[item.cadence]} · ${item.shared?'共同成本':'不参与分成'} · ${escapeHTML(item.effective_from)}${item.effective_to?' 至 '+escapeHTML(item.effective_to):''}${item.active?`<button type="button" class="action" data-schedule-stop="${item.id}">从今天起停止</button>`:'（已停止）'}</li>`).join('')||'<li>还没有固定成本。</li>'}</ul></section></div></details>`;
}
function bindPaySettings(){
 const send=(id, path, build)=>{const form=$('#'+id); if(!form) return; form.onsubmit=async event=>{event.preventDefault();const button=event.currentTarget.querySelector('[type=submit]'); if(button) button.disabled=true; try{await api(path, build(form, Object.fromEntries(new FormData(form))));toast('已保存。');await refresh();}catch(error){toast(error.message); if(button) button.disabled=false;}};};
 send('pay-rule-form','pay/rules',(_,data)=>({teacher_id:Number(data.teacher_id),rule_type:data.rule_type,percent:data.percent,hourly_floor:data.hourly_floor,hourly_rate:data.hourly_rate,effective_from:data.effective_from}));
  send('pay-cost-form','pay/costs',(form,data)=>({...data,shared:form.querySelector('[name=shared]').checked}));
 send('pay-schedule-form','pay/schedules',(form,data)=>({...data,shared:form.querySelector('[name=shared]').checked}));
 document.querySelectorAll('[data-original]').forEach(box=>box.onchange=async()=>{try{await api('pay/students',{profile_ids:[Number(box.dataset.original)],helen_original:box.checked});toast(box.checked?'已标为 Helen 的原有学生。':'已改回新学生。');await refresh();}catch(error){toast(error.message);box.checked=!box.checked;}});
 document.querySelectorAll('[data-cost-void]').forEach(button=>button.onclick=async()=>{try{await api('pay/costs/void',{id:Number(button.dataset.costVoid),voided:button.dataset.voided==='1'});await refresh();}catch(error){toast(error.message);}});
 document.querySelectorAll('[data-schedule-stop]').forEach(button=>button.onclick=async()=>{try{await api('pay/schedules/stop',{id:Number(button.dataset.scheduleStop)});await refresh();}catch(error){toast(error.message);}});
}

let sharePeriod='month', shareDate='', shareStart='', shareEnd='', shareReady=false, shareAnchor={start:'',end:''};
function loadShareChoice(){
 if(shareReady) return;
 shareReady=true;
 try{
  const saved=JSON.parse(localStorage.getItem('hz-share-range')||'{}');
  if(['day','week','month','last_month','year','custom'].includes(saved.period)) sharePeriod=saved.period;
  if(saved.start) shareStart=saved.start;
  if(saved.end) shareEnd=saved.end;
 }catch(error){}
}
function saveShareChoice(){
 try{localStorage.setItem('hz-share-range', JSON.stringify({period:sharePeriod,start:shareStart,end:shareEnd}));}catch(error){}
}
function shareQuery(){
 if(sharePeriod==='custom') return `period=custom&start=${encodeURIComponent(shareStart)}&end=${encodeURIComponent(shareEnd)}`;
 return `period=${sharePeriod}&date=${encodeURIComponent(shareDate)}`;
}
function bindShareCalendar(which, selected){
 const button=$('#share-'+which), panel=$('#share-'+which+'-cal');
 if(!button||!panel) return;
 if(!shareAnchor[which]) shareAnchor[which]=selected;
 const paint=()=>{
  panel.innerHTML=financeMonth(shareAnchor[which], which==='start'?shareStart:shareEnd, which).replaceAll('data-fin-','data-share-');
  panel.querySelectorAll('[data-share-move]').forEach(item=>item.onclick=event=>{
   event.stopPropagation();
   const month=shareAnchor[which].slice(0,8)+'01';
   shareAnchor[which]=(item.dataset.shareMove==='1'?datePlus(month,32):datePlus(month,-1)).slice(0,8)+'01';
   paint(); panel.hidden=false;
  });
  panel.querySelectorAll('[data-share-day]').forEach(item=>item.onclick=()=>{
   if(which==='start') shareStart=item.dataset.shareDay; else shareEnd=item.dataset.shareDay;
   if(shareEnd<shareStart){const swap=shareStart; shareStart=shareEnd; shareEnd=swap;}
   saveShareChoice(); renderShare();
  });
 };
 paint();
 button.onclick=()=>{const open=panel.hidden; panel.hidden=!open; button.setAttribute('aria-expanded', String(open));};
}
async function renderShare(){
 loadShareChoice();
 if(!shareDate) shareDate=state.today;
 if(!shareStart) shareStart=state.today.slice(0,8)+'01';
 if(!shareEnd) shareEnd=state.today;
 $('#surface').innerHTML='<div class="panel empty">正在计算分红…</div>';
 try{
  const data=await api('share?'+shareQuery());
  if(view!=='share') return;
  const money=cents=>cashFmt(cents||0);
  const people=[...new Map((data.roster||[]).filter(student=>!student.archived).map(student=>[student.profile_id, student])).values()];
  const lines=(data.lines||[]).map(line=>`<tr><td>${escapeHTML(line.date)}</td><td>${userHTML(line.student_name)}</td><td>${userHTML(line.lesson||'')}</td><td>${line.fee_known?money(line.revenue_cents):'未定价'}</td><td>${money(line.share_cents||0)}</td></tr>`).join('');
  const costs=(data.costs||[]).map(cost=>`<article class="trow"><div class="grow">${escapeHTML(cost.date)} · ${userHTML(cost.label)}</div><div class="num">${money(cost.amount_cents)}</div></article>`).join('');
  $('#surface').innerHTML=`<div class="mock-top"><div><h1 class="mock-title">分红</h1><p class="mock-sub">${escapeHTML(data.start)} – ${escapeHTML(data.end)}</p></div><button class="btn" id="share-export" type="button">导出 CSV</button></div><div class="period"><div class="seg">${[['day','今天'],['week','本周'],['month','本月'],['last_month','上月'],['year','今年'],['custom','自定义']].map(([value,label])=>`<button type="button" class="${value===sharePeriod?'on':''}" data-share-period="${value}">${label}</button>`).join('')}</div>${sharePeriod==='custom'?`<div class="mini-wrap"><button type="button" class="btn" id="share-start">开始 ${escapeHTML(shareStart)}</button><div id="share-start-cal" class="mini-cal" hidden></div></div><div class="mini-wrap"><button type="button" class="btn" id="share-end">结束 ${escapeHTML(shareEnd)}</button><div id="share-end-cal" class="mini-cal" hidden></div></div>`:''}</div><div class="dash-grid"><div class="dash-card"><span>机构收入</span><strong>${money(data.revenue_cents)}</strong><small>机构的课</small></div><div class="dash-card"><span>机构成本</span><strong>${money(data.cost_cents)}</strong><small>机构课的老师工资，加上共同成本</small></div><div class="dash-card"><span>机构利润</span><strong>${money(data.profit_cents)}</strong><small>机构收入 − 机构成本</small></div><div class="dash-card"><span>Vincent 分红（30%）</span><strong>${money(data.share_cents)}</strong><small>亏损也按 30% 分摊</small></div><div class="dash-card"><span>我的机构分成（70%）</span><strong>${money(data.helen_share_cents)}</strong><small>机构利润 × 70%</small></div></div><p class="dash-formula">分红 = (机构收入 ${money(data.revenue_cents)} − 机构成本 ${money(data.cost_cents)}) × 30% = ${money(data.share_cents)}。机构课的老师工资已经算进机构成本。</p><details class="panel pay-settings" open><summary>计入分红的课</summary><div class="pay-settings-body"><div class="table-wrap"><table><thead><tr><th>日期</th><th>学生</th><th>课程</th><th>收入</th><th>分红</th></tr></thead><tbody>${lines||'<tr><td colspan="5">这个周期没有计入分红的课。</td></tr>'}</tbody></table></div><h3>机构成本</h3>${costs||'<p class="muted">这个周期没有机构成本。</p>'}</div></details><details class="panel pay-settings"><summary>标记原有学生</summary><div class="pay-settings-body"><p class="footnote">勾上的学生，只有数学课不算机构的课。科学、英语等其他课仍进入机构收入和分红。</p><div class="table-wrap"><table><tbody>${people.map(student=>`<tr><td>${userHTML(student.name)}</td><td><label class="report-choice"><input type="checkbox" data-original="${student.profile_id}" ${student.helen_original?'checked':''}>原有学生</label>${student.helen_original?`<small class="row-meta">${student.origin_since==='2000-01-01'?'自一开始':('自 '+escapeHTML(student.origin_since||''))}</small>`:''}</td></tr>`).join('')}</tbody></table></div><h3>数学课</h3><p class="footnote">按课程名称先勾上，可以改。只有勾上的课，原有学生才算 Helen 自己的课。</p><div class="table-wrap"><table><tbody>${[...(state.subjects||[])].sort((a,b)=>Number(b.active)-Number(a.active)||String(a.name).localeCompare(String(b.name),'zh')).map(subject=>`<tr><td>${userHTML(subject.name)}${subject.active?'':' <small class="row-meta">已停用</small>'}</td><td><label class="report-choice"><input type="checkbox" data-maths-subject="${subject.id}" ${subject.is_maths?'checked':''}>数学课</label></td></tr>`).join('')}</tbody></table></div></div></details><details class="panel pay-settings"><summary>分红比例</summary><div class="pay-settings-body"><form id="share-partner-form" class="pay-form"><label class="field">谁拿机构利润的分成<select name="teacher_id">${(state.teachers||[]).map(teacher=>`<option value="${teacher.id}">${escapeHTML(teacher.name)}</option>`).join('')}</select></label><label class="field">百分比<input name="percent" inputmode="decimal" value="${(data.percent_bp||3000)/100}" required></label><label class="field">生效日期<input name="effective_from" type="date" value="${state.today}" required></label><button class="btn primary" type="submit">保存</button></form></div></details>`;
  document.querySelectorAll('#surface details.pay-settings').forEach(panel=>{if(!panel.open && panel.querySelector('summary')?.textContent!=='计入分红的课') panel.open=false;});
  document.querySelectorAll('[data-share-period]').forEach(button=>button.onclick=()=>{sharePeriod=button.dataset.sharePeriod; saveShareChoice(); renderShare();});
  bindShareCalendar('start', shareStart);
  bindShareCalendar('end', shareEnd);
  $('#share-export').onclick=async()=>{try{await downloadCsv('/api/share.csv?'+shareQuery(),'partner-share.csv');}catch(error){toast(error.message);}};
  const form=$('#share-partner-form');
  if(form) form.onsubmit=async event=>{event.preventDefault(); const body=Object.fromEntries(new FormData(form)); try{await api('pay/partner',{teacher_id:Number(body.teacher_id||0),percent:body.percent,effective_from:body.effective_from}); toast('已保存。'); renderShare();}catch(error){toast(error.message);}};
  document.querySelectorAll('[data-original]').forEach(box=>box.onchange=async()=>{try{await api('pay/students',{profile_ids:[Number(box.dataset.original)],helen_original:box.checked}); toast(box.checked?'已标为原有学生。':'已改回机构学生。'); renderShare();}catch(error){toast(error.message); box.checked=!box.checked;}});
  document.querySelectorAll('[data-maths-subject]').forEach(box=>box.onchange=async()=>{const subject=(state.subjects||[]).find(item=>String(item.id)===box.dataset.mathsSubject); try{await api('subjects',{id:subject.id,name:subject.name,active:!!subject.active,is_maths:box.checked}); toast('已保存。'); await refresh();}catch(error){toast(error.message); box.checked=!box.checked;}});
 }catch(error){if(view==='share') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
