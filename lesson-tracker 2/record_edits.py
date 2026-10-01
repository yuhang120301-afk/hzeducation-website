"""Owner-only corrections, with transactional balance rebuilding and private audit."""
import json
import datetime as dt


def schema(c):
    cols={r['name'] for r in c.execute('PRAGMA table_info(ledger)')}
    if 'version' not in cols:c.execute('ALTER TABLE ledger ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
    c.execute("""CREATE TABLE IF NOT EXISTS ledger_edits (
        id INTEGER PRIMARY KEY,ledger_id INTEGER NOT NULL REFERENCES ledger(id),
        actor_id INTEGER NOT NULL REFERENCES users(id),reason TEXT NOT NULL,
        before_json TEXT NOT NULL,after_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")


def rebuild(c,sid,units):
    import credit_batches as cb
    rows=[dict(r) for r in c.execute('SELECT * FROM ledger WHERE student_id=? ORDER BY id',(sid,))]
    batches={r['id']:dict(r) for r in c.execute('SELECT * FROM credit_batches WHERE student_id=?',(sid,))}
    refunds={r['id']:[m['batch_id'] for m in c.execute('SELECT batch_id FROM credit_movements WHERE ledger_id=?',(r['id'],))] for r in rows if r['kind']=='refund'}
    c.execute('DELETE FROM credit_movements WHERE ledger_id IN (SELECT id FROM ledger WHERE student_id=?)',(sid,))
    c.execute('UPDATE credit_batches SET paid_left=0,gift_left=0 WHERE student_id=?',(sid,))
    c.execute('UPDATE students SET balance=0 WHERE id=?',(sid,))
    for row in rows:
        lid=row['id'];kind=row['kind']
        try:
            if kind=='credit':
                paid=row['paid_delta'] if row['split_known'] else row['delta'];gift=row['gift_delta'] if row['split_known'] else 0
                existing=c.execute('SELECT id FROM credit_batches WHERE ledger_id=?',(lid,)).fetchone()
                if existing:bid=existing['id'];c.execute('UPDATE credit_batches SET purchased=?,gifted=?,credited_on=? WHERE id=?',(paid,gift,row['lesson_date'],bid))
                else:bid=c.execute('INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on) VALUES(?,?,?,?,0,0,?)',(sid,lid,paid,gift,row['lesson_date'])).lastrowid
                cb.move(c,lid,bid,paid,gift);cb.finish(c,lid)
            elif kind=='lesson':cb.apply(c,lid,'lesson',{},units)
            elif kind=='refund':
                amount=-row['paid_delta'] if row['split_known'] else -row['delta']
                targets=refunds[lid]
                if len(targets)==1 and batches[targets[0]]['ledger_id'] is not None:
                    cb.apply(c,lid,'refund',{'batch_id':targets[0],'amount':str(amount/100)},units)
                else:
                    # Original pre-batch refunds have no uniquely attributable purchase.
                    cb.consume(c,lid,sid,amount,paid_only=True);cb.finish(c,lid)
            elif kind=='reversal':
                original=c.execute('SELECT * FROM ledger WHERE id=?',(row['reversal_of'],)).fetchone()
                if not original:raise ValueError('原记录不存在。')
                c.execute('UPDATE ledger SET delta=? WHERE id=?',(-original['delta'],lid))
                cb.apply(c,lid,'reversal',{},units,original)
            else:raise ValueError('此记录类型不支持调整数量。')
        except ValueError as e:raise ValueError('修改会影响后续单据 #'+str(lid)+'：'+str(e)+' 本次修改未保存。') from e
    # Updated allocation and reversal amounts are reflected in all optimistic versions.
    c.execute('UPDATE ledger SET version=version+1 WHERE student_id=?',(sid,))


def edit(c,user,data,units,text_value):
    import accounting,credit_batches as cb
    accounting.require_owner(user)
    entry=c.execute('SELECT * FROM ledger WHERE id=?',(int(data.get('entry_id',0)),)).fetchone()
    if not entry:raise ValueError('单据不存在。')
    if int(data.get('version',0))!=entry['version']:raise ValueError('单据已更新，请刷新后重新编辑。')
    reason=text_value(data.get('reason'),'修改原因',250)
    date=dt.date.fromisoformat(str(data.get('date',entry['lesson_date']))).isoformat()
    if date>accounting.now_local().date().isoformat():raise ValueError('单据日期不能在未来。')
    note=str(data.get('note',entry['note'])).strip()
    if len(note)>300:raise ValueError('备注不能超过 300 字。')
    cash=c.execute('SELECT * FROM cash_entries WHERE ledger_id=?',(entry['id'],)).fetchone()
    before={'entry':dict(entry),'cash':dict(cash) if cash else None}
    reversed_by=c.execute('SELECT id FROM ledger WHERE reversal_of=?',(entry['id'],)).fetchone()
    kind=entry['kind'];quantity_changed=False
    if kind=='credit':
        oldpaid=entry['paid_delta'] if entry['split_known'] else entry['delta'];oldgift=entry['gift_delta'] if entry['split_known'] else 0
        paid=cb.zero_units(data.get('amount',str(oldpaid/100)),units);gift=cb.zero_units(data.get('gift_amount',str(oldgift/100)),units)
        if paid+gift<=0:raise ValueError('充值和赠送数量至少填写一项。')
        quantity_changed=(paid,gift)!=(oldpaid,oldgift)
        if quantity_changed:c.execute('UPDATE ledger SET delta=?,paid_delta=?,gift_delta=?,split_known=1 WHERE id=?',(paid+gift,paid,gift,entry['id']))
    elif kind in ('lesson','refund'):
        old=-entry['paid_delta'] if kind=='refund' and entry['split_known'] else -entry['delta']
        amount=units(data.get('amount',str(old/100)));quantity_changed=amount!=old
        if quantity_changed:
            if kind=='lesson':c.execute('UPDATE ledger SET delta=? WHERE id=?',(-amount,entry['id']))
            else:c.execute('UPDATE ledger SET paid_delta=?,delta=?,split_known=1 WHERE id=?',(-amount,-amount+entry['gift_delta'],entry['id']))
    if quantity_changed and (kind=='reversal' or reversed_by):raise ValueError('已撤销单据的数量不再生效，请编辑正确的有效单据。')
    c.execute('UPDATE ledger SET lesson_date=?,note=?,version=version+1 WHERE id=?',(date,note,entry['id']))
    if 'cash_amount' in data and data['cash_amount']!='':
        if kind not in ('credit','refund'):raise ValueError('此单据没有独立的收退款金额，请编辑原单据。')
        cents,method,reference=accounting.cash_details(data)
        if kind=='refund' and cents<=0:raise ValueError('退款金额必须大于 0。')
        if kind=='credit' and method=='gift' and paid>0:raise ValueError('纯赠送的充值数量必须为 0。')
        signed=cents if kind=='credit' else -cents
        c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,?) ON CONFLICT(ledger_id) DO UPDATE SET cash_delta=excluded.cash_delta,payment_method=excluded.payment_method,reference=excluded.reference,recorded_by=excluded.recorded_by',(entry['id'],signed,method,reference,user['id']))
        if reversed_by:
            c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,?) ON CONFLICT(ledger_id) DO UPDATE SET cash_delta=excluded.cash_delta,payment_method=excluded.payment_method',(reversed_by['id'],-signed,method,'原单据金额更新后同步',user['id']))
    if kind=='credit':c.execute('UPDATE credit_batches SET credited_on=? WHERE ledger_id=?',(date,entry['id']))
    if quantity_changed:rebuild(c,entry['student_id'],units)
    # A published report and its charge must always agree.
    if kind=='lesson':
        c.execute('UPDATE lesson_reports SET amount=?,updated_by=? WHERE ledger_id=?',(-c.execute('SELECT delta FROM ledger WHERE id=?',(entry['id'],)).fetchone()[0],user['id'],entry['id']))
        c.execute('UPDATE lessons SET version=version+1 WHERE id IN (SELECT lesson_id FROM lesson_reports WHERE ledger_id=?)',(entry['id'],))
    after={'entry':dict(c.execute('SELECT * FROM ledger WHERE id=?',(entry['id'],)).fetchone()),'cash':dict(c.execute('SELECT * FROM cash_entries WHERE ledger_id=?',(entry['id'],)).fetchone() or {})}
    c.execute('INSERT INTO ledger_edits(ledger_id,actor_id,reason,before_json,after_json) VALUES(?,?,?,?,?)',(entry['id'],user['id'],reason,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False)))
    return {'ok':True}
