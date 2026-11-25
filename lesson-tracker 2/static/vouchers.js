let voucherStudent='', voucherKind='', voucherStatus='', voucherStart='', voucherEnd='', voucherQuery='', receiptId='';
const voucherKindName={credit:'充值',refund:'退费',stop:'退课',adjust:'调整'};
const voucherStatusName={pending:'待审核',approved:'已审核',void:'已作废'};
function voucherMoney(cents){return cents==null?'—':(typeof cashFmt==='function'?cashFmt(cents):'$'+(cents/100).toFixed(2));}
function voucherUnits(row){
 const unit=(row.course||'').includes('小时')?'小时':'课时';
 return `付费 ${fmt(row.paid_units||0)} ${unit} · 赠送 ${fmt(row.gift_units||0)}`;
}
async function renderVouchers(){
 const params=new URLSearchParams();
 if(voucherStudent) params.set('student', voucherStudent);
 if(voucherKind) params.set('kind', voucherKind);
 if(voucherStatus) params.set('status', voucherStatus);
 if(voucherStart) params.set('start', voucherStart);
 if(voucherEnd) params.set('end', voucherEnd);
 if(voucherQuery) params.set('q', voucherQuery);
 $('#surface').innerHTML='<div class="panel empty">正在读取单据…</div>';
 let data;
 try{ data=await api('vouchers?'+params.toString()); }
 catch(error){ if(view==='vouchers') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`; return; }
 if(view!=='vouchers') return;
 const totals=data.totals||{};
 const students=state.students.concat(state.archived_students||[]);
 $('#surface').innerHTML=`<div class="mock-top voucher-tools"><div><h1 class="mock-title">单据</h1><p class="mock-sub">新单据先是待审核，课时和金额已经入账。审核不再动余额。</p></div><button class="btn primary" id="voucher-bulk" type="button" disabled>批量审核</button></div>
 <div class="pay-sums voucher-tools"><div class="card"><div class="k">张数</div><div class="n">${totals.open_count||0}</div><div class="s">不含已作废</div></div><div class="card"><div class="k">充值</div><div class="n">${voucherMoney(totals.credit_cents||0)}</div></div><div class="card"><div class="k">退费</div><div class="n">${voucherMoney(totals.refund_cents||0)}</div></div><div class="card"><div class="k">净额</div><div class="n">${voucherMoney(totals.net_cents||0)}</div></div></div>
 <div class="pay-tools voucher-tools"><label class="field">学生<select id="voucher-student"><option value="">全部学生</option>${students.map(s=>`<option value="${s.id}" ${String(voucherStudent)===String(s.id)?'selected':''}>${escapeHTML(s.name)} · ${escapeHTML(s.subject_name||s.course)}</option>`).join('')}</select></label>
 <label class="field">类型<select id="voucher-kind"><option value="">全部</option>${Object.entries(voucherKindName).map(([k,v])=>`<option value="${k}" ${voucherKind===k?'selected':''}>${v}</option>`).join('')}</select></label>
 <label class="field">状态<select id="voucher-status"><option value="">全部</option>${Object.entries(voucherStatusName).map(([k,v])=>`<option value="${k}" ${voucherStatus===k?'selected':''}>${v}</option>`).join('')}</select></label>
 <label class="field">从<input id="voucher-start" type="date" value="${escapeHTML(voucherStart)}"></label>
 <label class="field">到<input id="voucher-end" type="date" value="${escapeHTML(voucherEnd)}"></label>
 <label class="search">搜索<input id="voucher-q" value="${escapeHTML(voucherQuery)}" placeholder="单号、学生、备注"></label></div>
 <div class="panel table-wrap voucher-tools"><table><thead><tr><th class="voucher-check"><label><input id="voucher-all" type="checkbox" aria-label="全选"> 全选</label></th><th>单号</th><th>日期</th><th>学生 / 科目</th><th>类型</th><th>课时</th><th>金额</th><th>状态</th></tr></thead><tbody>${(data.vouchers||[]).map(row=>`<tr class="${row.status==='void'?'voucher-void':''}" data-voucher="${row.id}"><td class="voucher-check">${row.status==='pending'?`<input class="voucher-pick" type="checkbox" value="${row.id}" aria-label="选择 ${escapeHTML(row.number)}">`:''}</td><td>${escapeHTML(row.number)}</td><td>${escapeHTML(row.lesson_date)}</td><td>${userHTML(row.student_name)}<div class="muted">${userHTML(row.course)}</div></td><td>${escapeHTML(row.kind_label)}</td><td>${escapeHTML(voucherUnits(row))}</td><td>${voucherMoney(row.amount_cents)}</td><td>${escapeHTML(row.status_label)}</td></tr>`).join('')||'<tr><td colspan="8">没有单据。</td></tr>'}</tbody></table></div>`;
 const reload=()=>{voucherStudent=$('#voucher-student').value; voucherKind=$('#voucher-kind').value; voucherStatus=$('#voucher-status').value; voucherStart=$('#voucher-start').value; voucherEnd=$('#voucher-end').value; voucherQuery=$('#voucher-q').value; renderVouchers();};
 $('#voucher-student').onchange=reload; $('#voucher-kind').onchange=reload; $('#voucher-status').onchange=reload;
 $('#voucher-start').onchange=reload; $('#voucher-end').onchange=reload;
 $('#voucher-q').onchange=reload;
 document.querySelectorAll('[data-voucher]').forEach(row=>row.onclick=event=>{if(event.target.closest('.voucher-check')) return; if(typeof openDetail==='function') openDetail('/receipts/'+row.dataset.voucher);});
 bindVoucherBulk();
}
function bindVoucherBulk(){
 const picks=()=>[...document.querySelectorAll('.voucher-pick')];
 const sync=()=>{
  const boxes=picks(), chosen=boxes.filter(box=>box.checked).length, all=$('#voucher-all'), button=$('#voucher-bulk');
  if(all){all.disabled=!boxes.length; all.checked=!!boxes.length&&chosen===boxes.length; all.indeterminate=chosen>0&&chosen<boxes.length;}
  if(button) button.disabled=!chosen;
 };
 const all=$('#voucher-all');
 if(all) all.onclick=()=>{picks().forEach(box=>{box.checked=all.checked;}); sync();};
 picks().forEach(box=>box.onchange=sync);
 const button=$('#voucher-bulk');
 if(button) button.onclick=()=>{
  const ids=picks().filter(box=>box.checked).map(box=>Number(box.value));
  if(!ids.length) return;
  modal(`确定审核选中的 ${ids.length} 张单据？`,`<div class="form-context">余额不会再变动。已经不是待审核的会跳过。</div>`,'确认审核',async()=>{
   const result=await api('vouchers/approve-bulk',{ids});
   const skipped=(result.skipped||[]).length;
   toast(skipped?`已审核 ${result.approved} 张单据。${skipped} 张已跳过。`:`已审核 ${result.approved} 张单据。`);
  });
 };
 sync();
}
async function renderReceipt(){
 const id=receiptId;
 const showMissing=()=>{$('#surface').innerHTML=`${typeof backBar==='function'?backBar():'<p class="page-back"><button type="button" class="btn" id="page-back">返回</button></p>'}<div class="panel empty">找不到这张单据。</div>`; if(typeof bindBack==='function') bindBack('/?view=vouchers');};
 $('#surface').innerHTML='<div class="panel empty">正在读取单据…</div>';
 let data;
 try{ data=await api('vouchers?id='+encodeURIComponent(id)); }
 catch(error){ if(view==='receipt') $('#surface').innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`; return; }
 if(view!=='receipt') return;
 const row=(data.vouchers||[]).find(item=>String(item.id)===String(id));
 if(!row){ showMissing(); return; }
 $('#surface').innerHTML=`${typeof backBar==='function'?backBar():'<p class="page-back"><button type="button" class="btn" id="page-back">返回</button></p>'}${voucherSheet(row)}`;
 if(typeof bindBack==='function') bindBack('/?view=vouchers');
 bindVoucher(row);
}
function voucherSheet(row){
 const method=(typeof paymentNames==='object'&&paymentNames[row.payment_method])||row.payment_method||'—';
 return `<article class="panel voucher-sheet ${row.status==='void'?'voucher-void':''}"><header><p>HZ Education Melbourne</p><h2>${escapeHTML(row.number)}</h2><p>${escapeHTML(row.status_label)} · ${escapeHTML(row.kind_label)}</p></header>
 <dl><div><dt>日期</dt><dd>${escapeHTML(row.lesson_date)}</dd></div><div><dt>学生</dt><dd>${userHTML(row.student_name)} · ${userHTML(row.course)}</dd></div><div><dt>课时包</dt><dd>${row.pack_label?escapeHTML(row.pack_label):'—'}</dd></div><div><dt>课时</dt><dd>${escapeHTML(voucherUnits(row))}</dd></div><div><dt>金额</dt><dd>${voucherMoney(row.amount_cents)}</dd></div><div><dt>方式</dt><dd>${escapeHTML(method)}</dd></div><div><dt>经办</dt><dd>${userHTML(row.actor_name||'')}</dd></div></dl>
 <p>${row.note?userHTML(row.note):'没有备注。'}</p>
 <div class="voucher-actions"><button class="btn" id="voucher-print" type="button">打印</button>
 ${row.status==='pending'?`<button class="btn primary" id="voucher-approve" type="button">审核</button><button class="btn" id="voucher-edit" type="button">修改</button>`:''}
 ${row.status==='approved'?`<button class="btn" id="voucher-unapprove" type="button">撤销审核</button>`:''}
 ${row.status!=='void'?`<button class="btn refund-action" id="voucher-void" type="button">作废</button>`:''}</div>
 <div id="voucher-log" class="footnote">正在读取修改记录…</div></article>`;
}
function bindVoucher(row){
 $('#voucher-print').onclick=()=>window.print();
 if($('#voucher-approve')) $('#voucher-approve').onclick=async()=>{await api('vouchers/approve',{id:row.id}); toast('已审核。余额没有再变动。'); renderReceipt();};
 if($('#voucher-unapprove')) $('#voucher-unapprove').onclick=async()=>{await api('vouchers/unapprove',{id:row.id}); toast('已改回待审核。'); renderReceipt();};
 if($('#voucher-void')) $('#voucher-void').onclick=()=>modal('作废这张单据？',`<div class="form-context">${escapeHTML(row.number)}<br>作废会冲回这张单据的课时和金额，单据本身仍保留。</div>`,'确认作废',async()=>{await api('vouchers/void',{id:row.id}); toast('单据已作废。');},true);
 if($('#voucher-edit')) $('#voucher-edit').onclick=()=>voucherEdit(row);
 api('vouchers?id='+row.id).then(data=>{
  const host=$('#voucher-log'); if(!host) return;
  host.innerHTML=(data.events||[]).map(event=>`${escapeHTML(event.created_at.slice(0,16).replace('T',' '))} ${userHTML(event.actor_name||'')} ${escapeHTML(event.action)} ${escapeHTML(event.detail||'')}`).join('<br>')||'还没有修改记录。';
 }).catch(()=>{});
}
function voucherEdit(row){
 const methods=typeof paymentNames==='object'?paymentNames:{bank:'银行转账'};
 modal('修改单据',`<div class="form-context">${escapeHTML(row.number)} · 只有待审核可以改。保存后余额和财务会重算。</div>
 <label class="field">日期<input name="date" type="date" value="${escapeHTML(row.lesson_date)}" required></label>
 <div class="two-cols"><label class="field">付费课时<input name="amount" type="number" min="0" step="0.01" value="${((row.paid_units||0)/100)}"></label><label class="field">赠送课时<input name="gift_amount" type="number" min="0" step="0.01" value="${((row.gift_units||0)/100)}"></label></div>
 <label class="field">金额 AUD<input name="cash_amount" type="number" min="0" step="0.01" value="${row.amount_cents==null?'':(row.amount_cents/100)}"></label>
 <label class="field">方式<select name="payment_method">${Object.entries(methods).filter(([k])=>k!=='gift'||row.kind==='credit').map(([k,v])=>`<option value="${k}" ${row.payment_method===k?'selected':''}>${v}</option>`).join('')}</select></label>
 <label class="field">备注<textarea name="note" maxlength="300">${escapeHTML(row.note||'')}</textarea></label>`,'保存修改',async data=>{await api('vouchers/edit',{...data,id:row.id}); toast('单据已修改，余额已重算。');});
}
