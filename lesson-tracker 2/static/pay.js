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
 $('#surface').innerHTML=`<div class="accounting-controls"><div class="period-switch" role="group" aria-label="工资周期">${[['week','每周'],['month','每月'],['custom','自定义']].map(([value,label])=>`<button type="button" class="${value===payPeriod?'selected':''}" data-pay-period="${value}">${label}</button>`).join('')}</div>${payPeriod==='custom'?`<label>开始<input id="pay-start" type="date" value="${payStart}"></label><label>结束<input id="pay-end" type="date" value="${payEnd}"></label>`:`<label>选择日期<input id="pay-date" type="date" value="${payDate}"></label>`}<button class="btn" id="pay-export">导出本期 CSV</button></div><div id="pay-result"><div class="panel empty">正在计算工资…</div></div>`;
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
function paintPay(data){
 const partner=data.partner;
 const profiles=new Map();
 data.students.filter(student=>!student.archived).forEach(student=>{if(!profiles.has(student.profile_id)) profiles.set(student.profile_id, student);});
 const counts={new:0, original:0};
 profiles.forEach(student=>{counts[student.is_new?'new':'original']++;});
 $('#pay-result').innerHTML=`<div class="accounting-range"><strong>${data.start}${data.start===data.end?'':' — '+data.end}</strong><span>只统计已确认并扣过课时、且没有撤销的课程。一节课的价值 = 课时包总价 ÷（付费节数 + 赠送节数）。纯赠课、没有付款的，仍是 0。</span></div><section class="stats cash-stats"><div class="stat featured"><div class="stat-label">老师上课工资</div><div class="stat-value">${cashFmt(data.teachers.reduce((sum,teacher)=>sum+teacher.total_pay_cents,0))}</div><div class="stat-note">与下面的新学生分成分开计算</div></div><div class="stat"><div class="stat-label">新学生课酬</div><div class="stat-value">${cashFmt(partner.revenue_cents)}</div><div class="stat-note">新学生 ${counts.new} 位 · 原有学生 ${counts.original} 位</div></div><div class="stat"><div class="stat-label">新学生分成</div><div class="stat-value">${cashFmt(partner.share_cents)}</div><div class="stat-note">${partner.teacher_name?userHTML(partner.teacher_name)+' · '+(partner.percent_bp/100).toLocaleString('zh-CN',{maximumFractionDigits:2})+'%':'尚未设置合伙人'}</div></div></section>${data.teachers.filter(teacher=>teacher.rule).map(teacher=>`<article class="pay-card t-${(teacher.name||'').toLowerCase().includes('helen')?'helen':(teacher.name||'').toLowerCase().includes('vincent')?'vincent':(teacher.name||'').toLowerCase().includes('angela')?'angela':(teacher.name||'').toLowerCase().includes('kelsey')?'kelsey':(teacher.name||'').toLowerCase().includes('ethan')?'ethan':(teacher.name||'').toLowerCase().includes('christina')?'christina':'other'}"><div class="avatar">${userHTML((teacher.name||'?').slice(0,1))}</div><div style="flex:1"><h2 style="margin:0">${userHTML(teacher.name)}</h2><p class="muted">${ruleLabel(teacher.rule)}</p><p class="muted">${teacher.lessons.length} 节 · ${(teacher.total_minutes/60).toFixed(1)} 小时</p></div><div><div class="muted">课酬基数</div><strong>${cashFmt(teacher.total_fee_cents)}</strong></div><div><div class="muted">应付</div><strong>${cashFmt(teacher.total_pay_cents)}</strong></div></article><section class="accounting-section panel pay-teacher" hidden><div class="section-head"><div><h2>${userHTML(teacher.name)}</h2><p class="muted">${ruleLabel(teacher.rule)}${teacher.rules_in_period?' · 本期内规则有变化，每节课按上课当天的规则':''}</p></div><button class="btn" data-pay-export="${teacher.teacher_id}">导出这位老师</button></div><div class="hours-reconcile"><div><span>课时</span><strong>${teacher.lessons.length}</strong></div><div><span>授课小时</span><strong>${(teacher.total_minutes/60).toFixed(2)}</strong></div><div><span>课酬基数</span><strong>${cashFmt(teacher.total_fee_cents)}</strong></div><div class="ending"><span>上课工资</span><strong>${cashFmt(teacher.total_pay_cents)}</strong></div></div>${teacher.unknown_fee_count?`<div class="accounting-warning">${teacher.unknown_fee_count} 条还没有澳元单价。可以按课时包补上收款，或直接填写这节课的课酬。</div>`:''}${teacher.lessons.length?`<div class="table-wrap"><table><thead><tr><th>日期</th><th>学生</th><th>时长</th><th>课酬</th><th>本节工资</th><th>算法</th></tr></thead><tbody>${teacher.lessons.map(lesson=>lesson.lines.map((line,index)=>`<tr><td>${index?'':escapeHTML(lesson.date)+'<small class="row-meta">'+escapeHTML(lesson.starts_at.slice(11,16)+'–'+lesson.ends_at.slice(11,16))+'</small>'}</td><td>${userHTML(line.student_name)}<small class="row-meta">${userHTML(line.course)} · ${line.is_new?'新学生':'原有学生'}</small></td><td>${index?'':(lesson.minutes/60).toFixed(2)+' 小时'}</td><td>${line.fee_known?cashFmt(line.fee_cents):'<span class="missing-cash">未定价</span>'}${line.fee_overridden?'<small class="row-meta">已手改</small>':''}<button class="action" data-fee-lesson="${lesson.lesson_id}" data-fee-student="${line.student_id}" data-fee-value="${line.fee_known?line.fee_cents/100:''}">改课酬</button></td><td>${index?'':cashFmt(lesson.pay_cents)}</td><td>${index?'':payBasis(lesson.pay_basis)}</td></tr>`).join('')).join('')}</tbody></table></div>`:'<p class="empty">这个周期没有已确认的课程。</p>'}</section>`).join('')}<section class="accounting-section panel pay-partner"><div class="section-head"><h2>新学生分成</h2></div><div class="form-context">${partner.teacher_name?`${userHTML(partner.teacher_name)} 拿剩余金额的 ${(partner.percent_bp/100).toLocaleString('zh-CN',{maximumFractionDigits:2})}%。剩余 = 新学生课酬 − 共同成本。原有学生的课酬不进这里。${userHTML(partner.teacher_name)} 自己上课的工资是另一行，不会从剩余里再扣一次。`:'还没有设置分成对象。'}<br>上课工资（另计）：<strong>${cashFmt(partner.teaching_pay_cents)}</strong>${partner.changed_during_period?'<br>这个周期里分成比例有变动，本次按结束日生效的比例计算整段。':''}${partner.unknown_fee_count?`<br>有 ${partner.unknown_fee_count} 条新学生课程还没有单价，没有算进课酬。`:''}</div><div class="hours-reconcile"><div><span>新学生课酬</span><strong>${cashFmt(partner.revenue_cents)}</strong></div><div><span>减：共同成本</span><strong>${cashFmt(partner.shared_cost_cents)}</strong></div><div><span>剩余</span><strong>${cashFmt(partner.remainder_cents)}</strong></div><div class="ending"><span>分成</span><strong>${cashFmt(partner.share_cents)}</strong></div></div>${partner.remainder_cents<0?'<p class="footnote">剩余是负数，所以这笔分成是 0。</p>':''}${partner.costs.length?`<ul class="pay-cost-list">${partner.costs.map(cost=>`<li><span>${userHTML(cost.label)}</span><strong>${cashFmt(cost.amount_cents)}</strong></li>`).join('')}</ul>`:'<p class="muted">这个周期没有标成「共同成本」的支出。不勾选的成本不会参与分成。</p>'}</section>${paySettings(data)}`;
 document.querySelectorAll('[data-pay-export]').forEach(button=>button.onclick=async()=>{try{await downloadCsv('/api/pay.csv?'+payQuery()+'&teacher_id='+button.dataset.payExport,'teacher-pay.csv');}catch(error){toast(error.message);}});
 document.querySelectorAll('[data-fee-lesson]').forEach(button=>button.onclick=()=>feeModal(button));
 bindPaySettings();
}
let profileIdSafe=()=>typeof profileId!=='undefined'?profileId:'';
function renderProfile(){
 const sid=profileIdSafe();
 const student=(state.students||[]).find(item=>String(item.id)===String(sid));
 if(!student){$('#surface').innerHTML='<div class="panel empty">请从学生列表点开一位学生。</div>';return;}
 const lessons=(state.lessons||[]).filter(lesson=>lesson.students.some(item=>String(item.id)===String(sid))).sort((a,b)=>b.starts_at.localeCompare(a.starts_at));
 const reports=lessons.flatMap(lesson=>(lesson.reports||[]).filter(report=>String(report.student_id)===String(sid)).map(report=>({...report,when:lesson.starts_at}))).sort((a,b)=>b.when.localeCompare(a.when));
 $('#surface').innerHTML=`<p><button class="btn" id="back-students" type="button">返回学生</button></p><article class="pay-card"><div class="avatar">${userHTML(student.name.slice(0,1))}</div><div><h2 style="margin:0">${userHTML(student.name)}</h2><p class="muted">${userHTML(student.grade||'')} · ${userHTML(student.course)} · 剩余 ${fmt(regularHours(student))} 节</p></div></article><section class="panel"><h2>课程</h2>${lessons.map(lesson=>`<p>${escapeHTML(lesson.starts_at.replace('T',' '))} · ${userHTML(lesson.teacher_name)} · ${userHTML(lesson.title)} · ${lesson.status==='completed'?'已上了':'待上课'}</p>`).join('')||'<p>还没有课。</p>'}</section><section class="panel"><h2>课后记录</h2>${reports.map(report=>`<p>${escapeHTML(report.when.replace('T',' '))} · ${userHTML(report.content||'')} · 作业 ${userHTML(report.homework||'')}</p>`).join('')||'<p>还没有课后记录。</p>'}</section>`;
 $('#back-students').onclick=()=>{view='overview';render();};
}
async function renderAudit(){
 $('#surface').innerHTML='<div class="panel empty">正在读取操作日志…</div>';
 try{
  const data=await api('audit');
  if(view!=='audit') return;
  const rows=data.entries||[];
  $('#surface').innerHTML=`<label class="calendar-search"><input id="audit-search" type="search" placeholder="搜索操作" aria-label="搜索操作"></label><section class="panel" id="audit-list">${rows.map(row=>`<p data-audit-text="${escapeHTML(row.summary||'')}">${escapeHTML((row.created_at||'').slice(0,16))} · ${userHTML(row.actor_name||'')} · ${escapeHTML(row.summary||row.action||'')}</p>`).join('')||'<p>还没有操作记录。</p>'}</section>`;
  $('#audit-search').oninput=event=>{const q=event.target.value.trim().toLowerCase();document.querySelectorAll('#audit-list p').forEach(line=>{line.hidden=q && !(line.dataset.auditText||'').toLowerCase().includes(q);});};
 }catch(error){if(view==='audit') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
async function renderFinance(){
 $('#surface').innerHTML='<div class="panel empty">正在汇总财务报表…</div>';
 try{
  const data=await api('finance?period=month&date='+encodeURIComponent(state.today));
  if(view!=='finance') return;
  const money=cents=>cashFmt(cents||0);
  $('#surface').innerHTML=`<section class="stats"><div class="stat featured"><div class="stat-label">营业额</div><div class="stat-value">${money(data.turnover_cents)}</div><div class="stat-note">${escapeHTML(data.start)} – ${escapeHTML(data.end)}</div></div><div class="stat"><div class="stat-label">成本</div><div class="stat-value">${money(data.operating_cost_cents)}</div></div><div class="stat"><div class="stat-label">机构利润</div><div class="stat-value">${money(data.organisation_profit_cents)}</div></div><div class="stat"><div class="stat-label">Helen 净利润</div><div class="stat-value">${money(data.helen_net_cents)}</div><div class="stat-note">已扣 Vincent 分成 ${money((data.partner||{}).share_cents)}</div></div></section><div class="head-actions" style="margin-bottom:12px"><button class="btn" id="finance-xlsx" type="button">导出 Excel</button><button class="btn" id="finance-pdf" type="button">导出 PDF</button></div><section class="panel"><h2>按老师</h2>${(data.teachers||[]).map(teacher=>`<p>${userHTML(teacher.name)} · 课酬 ${money(teacher.fee_cents)} · 应付 ${money(teacher.pay_cents)}</p>`).join('')||'<p>这个月还没有已确认的课。</p>'}</section><p class="footnote">数字来自已扣课的记录。导出 Excel 和 PDF 使用同一套汇总。</p>`;
  const query='period=month&date='+encodeURIComponent(state.today);
  $('#finance-xlsx').onclick=async()=>{try{await downloadCsv('/api/finance.xlsx?'+query,'HZ-Education-Melbourne-finance.xlsx');}catch(error){toast(error.message);}};
  $('#finance-pdf').onclick=async()=>{try{await downloadCsv('/api/finance.pdf?'+query,'HZ-Education-Melbourne-finance.pdf');}catch(error){toast(error.message);}};
 }catch(error){if(view==='finance') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
function feeModal(button){
 modal('修改这节课的课酬',`<p class="footnote">留空并选择恢复，会重新按课时包价格 ÷ 付费课时计算。赠课仍是 0。</p><label class="field">课酬 AUD<input name="fee_amount" inputmode="decimal" value="${escapeHTML(button.dataset.feeValue)}" required></label>`,'保存手改金额',async data=>{await api('pay/fee',{lesson_id:Number(button.dataset.feeLesson),student_id:Number(button.dataset.feeStudent),fee_amount:data.fee_amount});toast('课酬已更新。');});
 const reset=document.createElement('button');
 reset.type='button';reset.className='btn';reset.textContent='恢复课时包单价';
 $('.modal-footer').prepend(reset);
 reset.onclick=async()=>{try{await api('pay/fee',{lesson_id:Number(button.dataset.feeLesson),student_id:Number(button.dataset.feeStudent),reset:true});$('#modal').close();toast('已恢复为课时包单价。');await refresh();}catch(error){toast(error.message);}};
}
function paySettings(data){
 const teachers=state.teachers.map(teacher=>`<option value="${teacher.id}">${escapeHTML(teacher.name)}</option>`).join('');
 const people=[...new Map(data.students.filter(student=>!student.archived).map(student=>[student.profile_id,student])).values()];
 return `<details class="panel pay-settings" open><summary>规则、原有学生和成本</summary><div class="pay-settings-body"><section><h3>Helen 的原有学生</h3><p class="footnote">新添加的学生都算新学生，包括原有学生的兄弟姐妹。只有老板能看到和勾选这份固定名单。勾上的学生不进入分成。</p><div class="table-wrap"><table><thead><tr><th>学生</th><th>Helen 的原有学生</th></tr></thead><tbody>${people.map(student=>`<tr><td>${userHTML(student.name)}</td><td><label class="report-choice"><input type="checkbox" data-original="${student.profile_id}" ${student.helen_original?'checked':''}>原有学生</label></td></tr>`).join('')}</tbody></table></div></section><section><h3>老师工资规则</h3><form id="pay-rule-form" class="pay-form"><label class="field">老师<select name="teacher_id" required>${teachers}</select></label><label class="field">方式<select name="rule_type"><option value="percent">课酬百分比</option><option value="hourly">时薪</option></select></label><label class="field">百分比<input name="percent" inputmode="decimal" placeholder="40"></label><label class="field">保底时薪 AUD（选填）<input name="hourly_floor" inputmode="decimal" placeholder="35"></label><label class="field">时薪 AUD<input name="hourly_rate" inputmode="decimal" placeholder="0.00"></label><label class="field">生效日期<input name="effective_from" type="date" value="${state.today}" required></label><button class="btn primary" type="submit">保存规则</button></form><ul class="pay-rule-list">${data.rules.map(rule=>`<li>${userHTML(state.teachers.find(teacher=>teacher.id===rule.teacher_id)?.name||'老师')} · 自 ${escapeHTML(rule.effective_from)} · ${ruleLabel(rule)}</li>`).join('')||'<li>还没有规则。</li>'}</ul></section><section><h3>分成对象</h3><form id="pay-partner-form" class="pay-form"><label class="field">谁拿分成<select name="teacher_id"><option value="">不设置</option>${teachers}</select></label><label class="field">剩余的百分比<input name="percent" inputmode="decimal" value="30" required></label><label class="field">生效日期<input name="effective_from" type="date" value="${state.today}" required></label><button class="btn primary" type="submit">保存分成</button></form></section><section><h3>成本</h3><p class="footnote">勾选「共同成本」才会从新学生课酬里扣除。不勾选的只是记录，不参与分成。</p><form id="pay-cost-form" class="pay-form"><label class="field">名称<input name="label" maxlength="80" required placeholder="例如：房租"></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" required></label><label class="field">日期<input name="cost_date" type="date" value="${state.today}" required></label><label class="report-choice"><input type="checkbox" name="shared">这是共同成本</label><button class="btn primary" type="submit">添加一笔</button></form><ul class="pay-rule-list">${data.cost_entries.map(entry=>`<li class="${entry.voided?'muted':''}">${escapeHTML(entry.cost_date)} · ${userHTML(entry.label)} · ${cashFmt(entry.amount_cents)} · ${entry.shared?'共同成本':'不参与分成'} ${entry.voided?'（已作废）':''}<button type="button" class="action" data-cost-void="${entry.id}" data-voided="${entry.voided?0:1}">${entry.voided?'恢复':'作废'}</button></li>`).join('')||'<li>还没有单笔成本。</li>'}</ul><form id="pay-schedule-form" class="pay-form"><label class="field">固定成本名称<input name="label" maxlength="80" required></label><label class="field">金额 AUD<input name="amount" inputmode="decimal" required></label><label class="field">周期<select name="cadence"><option value="month">每月</option><option value="week">每周</option><option value="day">每天</option></select></label><label class="field">从<input name="effective_from" type="date" value="${state.today}" required></label><label class="report-choice"><input type="checkbox" name="shared" checked>这是共同成本</label><button class="btn primary" type="submit">添加固定成本</button></form><ul class="pay-rule-list">${data.cost_schedules.map(item=>`<li>${userHTML(item.label)} · ${cashFmt(item.amount_cents)} / ${{day:'天',week:'周',month:'月'}[item.cadence]} · ${item.shared?'共同成本':'不参与分成'} · ${escapeHTML(item.effective_from)}${item.effective_to?' 至 '+escapeHTML(item.effective_to):''}${item.active?`<button type="button" class="action" data-schedule-stop="${item.id}">从今天起停止</button>`:'（已停止）'}</li>`).join('')||'<li>还没有固定成本。</li>'}</ul></section></div></details>`;
}
function bindPaySettings(){
 const send=(id, path, build)=>{$('#'+id).onsubmit=async event=>{event.preventDefault();const form=event.currentTarget, button=form.querySelector('[type=submit]');button.disabled=true;try{await api(path, build(form, Object.fromEntries(new FormData(form))));toast('已保存。');await refresh();}catch(error){toast(error.message);button.disabled=false;}};};
 send('pay-rule-form','pay/rules',(_,data)=>({teacher_id:Number(data.teacher_id),rule_type:data.rule_type,percent:data.percent,hourly_floor:data.hourly_floor,hourly_rate:data.hourly_rate,effective_from:data.effective_from}));
 send('pay-partner-form','pay/partner',(_,data)=>({teacher_id:Number(data.teacher_id||0),percent:data.teacher_id?data.percent:0,effective_from:data.effective_from}));
 send('pay-cost-form','pay/costs',(form,data)=>({...data,shared:form.querySelector('[name=shared]').checked}));
 send('pay-schedule-form','pay/schedules',(form,data)=>({...data,shared:form.querySelector('[name=shared]').checked}));
 document.querySelectorAll('[data-original]').forEach(box=>box.onchange=async()=>{try{await api('pay/students',{profile_ids:[Number(box.dataset.original)],helen_original:box.checked});toast(box.checked?'已标为 Helen 的原有学生。':'已改回新学生。');await refresh();}catch(error){toast(error.message);box.checked=!box.checked;}});
 document.querySelectorAll('[data-cost-void]').forEach(button=>button.onclick=async()=>{try{await api('pay/costs/void',{id:Number(button.dataset.costVoid),voided:button.dataset.voided==='1'});await refresh();}catch(error){toast(error.message);}});
 document.querySelectorAll('[data-schedule-stop]').forEach(button=>button.onclick=async()=>{try{await api('pay/schedules/stop',{id:Number(button.dataset.scheduleStop)});await refresh();}catch(error){toast(error.message);}});
}
