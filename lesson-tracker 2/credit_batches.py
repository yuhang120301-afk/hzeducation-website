"""Per-course paid and gift balances. Call mutations inside a DB transaction."""
from decimal import Decimal, InvalidOperation

def zero_units(raw, units):
    try:
        n=Decimal(str(raw))
        if n==0:return 0
    except InvalidOperation:pass
    return units(raw)

def schema(c):
    cols={r['name'] for r in c.execute('PRAGMA table_info(ledger)')}
    for name in ('paid_delta','gift_delta','gift_void','split_known'):
        if name not in cols:c.execute('ALTER TABLE ledger ADD COLUMN '+name+' INTEGER NOT NULL DEFAULT 0')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS credit_batches (
        id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id),
        ledger_id INTEGER UNIQUE REFERENCES ledger(id), purchased INTEGER NOT NULL, gifted INTEGER NOT NULL,
        paid_left INTEGER NOT NULL CHECK(paid_left>=0), gift_left INTEGER NOT NULL CHECK(gift_left>=0),
        credited_on TEXT NOT NULL, legacy INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS credit_movements (
        ledger_id INTEGER NOT NULL REFERENCES ledger(id), batch_id INTEGER NOT NULL REFERENCES credit_batches(id),
        paid INTEGER NOT NULL, gift INTEGER NOT NULL, voided INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(ledger_id,batch_id)
    );
    ''')
    if not c.execute("SELECT 1 FROM app_meta WHERE key='credit_batches_v1'").fetchone():
        for s in c.execute('SELECT id,balance FROM students').fetchall():
            c.execute("INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,legacy) VALUES(?,?,0,?,0,'',1)",(s['id'],s['balance'],s['balance']))
        c.execute("INSERT INTO app_meta VALUES('credit_batches_v1','1')")

def enrich(c,students):
    for s in students:
        batches=[dict(r) for r in c.execute('SELECT * FROM credit_batches WHERE student_id=? ORDER BY id',(s['id'],))]
        s['credit_batches']=batches
        s['paid_balance']=sum(b['paid_left'] for b in batches)
        s['gift_balance']=sum(b['gift_left'] for b in batches)
        s['legacy_balance']=sum(b['paid_left'] for b in batches if b['legacy'])

def move(c,lid,bid,paid,gift,voided=0):
    b=c.execute('SELECT * FROM credit_batches WHERE id=?',(bid,)).fetchone()
    if b['paid_left']+paid<0 or b['gift_left']+gift<0:
        raise ValueError('该批次课时已使用或退费，请先撤销关联操作。')
    c.execute('UPDATE credit_batches SET paid_left=paid_left+?,gift_left=gift_left+? WHERE id=?',(paid,gift,bid))
    c.execute('INSERT INTO credit_movements VALUES(?,?,?,?,?) ON CONFLICT(ledger_id,batch_id) DO UPDATE SET paid=paid+excluded.paid,gift=gift+excluded.gift,voided=voided+excluded.voided',(lid,bid,paid,gift,voided))

def finish(c,lid):
    sums=c.execute('SELECT COALESCE(SUM(paid),0),COALESCE(SUM(gift),0),COALESCE(SUM(voided),0) FROM credit_movements WHERE ledger_id=?',(lid,)).fetchone()
    sid=c.execute('SELECT student_id FROM ledger WHERE id=?',(lid,)).fetchone()[0]
    delta=sums[0]+sums[1]
    c.execute('UPDATE ledger SET delta=?,paid_delta=?,gift_delta=?,gift_void=?,split_known=1 WHERE id=?',(delta,*sums,lid))
    c.execute('UPDATE students SET balance=balance+? WHERE id=?',(delta,sid))
    return {'paid_delta':sums[0],'gift_delta':sums[1],'gift_void':sums[2]}

def consume(c,lid,sid,amount,paid_only=False):
    remaining=amount
    for column in (['paid_left'] if paid_only else ['paid_left','gift_left']):
        for b in c.execute('SELECT * FROM credit_batches WHERE student_id=? AND '+column+'>0 ORDER BY id',(sid,)).fetchall():
            take=min(remaining,b[column])
            if take:move(c,lid,b['id'],-take if column=='paid_left' else 0,-take if column=='gift_left' else 0)
            remaining-=take
            if not remaining:break
        if not remaining:break
    if remaining:raise ValueError('可用课时不足，无法完成此次操作。')

def outstanding_refunds(c,bid,exclude):
    return c.execute("SELECT 1 FROM credit_movements m JOIN ledger l ON l.id=m.ledger_id WHERE m.batch_id=? AND l.kind='refund' AND l.id!=? AND NOT EXISTS(SELECT 1 FROM ledger r WHERE r.reversal_of=l.id)",(bid,exclude)).fetchone()

def apply(c,lid,kind,data,units,original=None):
    entry=c.execute('SELECT * FROM ledger WHERE id=?',(lid,)).fetchone();sid=entry['student_id']
    if kind=='credit':
        paid=zero_units(data.get('amount'),units);gift=zero_units(data.get('gift_amount',0),units)
        if paid+gift<=0:raise ValueError('付费课时和赠送课时至少填写一项。')
        bid=c.execute('INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on) VALUES(?,?,?,?,0,0,?)',(sid,lid,paid,gift,entry['lesson_date'])).lastrowid
        move(c,lid,bid,paid,gift)
    elif kind=='lesson':consume(c,lid,sid,-entry['delta'])
    elif kind=='refund':
        bid=int(data.get('batch_id') or 0)
        if not bid:
            eligible=c.execute('SELECT id FROM credit_batches WHERE student_id=? AND paid_left>0',(sid,)).fetchall()
            if len(eligible)!=1:raise ValueError('请选择要退费的充值批次。')
            bid=eligible[0]['id']
        b=c.execute('SELECT * FROM credit_batches WHERE id=? AND student_id=?',(bid,sid)).fetchone()
        amount=units(data.get('amount'))
        if not b or amount>b['paid_left']:raise ValueError('退款课时不能超过该批次剩余付费课时，赠送课时不可退款。')
        move(c,lid,bid,-amount,-b['gift_left'],b['gift_left'])
    elif kind=='reversal':
        movements=c.execute('SELECT * FROM credit_movements WHERE ledger_id=?',(original['id'],)).fetchall()
        if movements:
            for m in movements:
                if m['gift']<0 and outstanding_refunds(c,m['batch_id'],original['id']):
                    raise ValueError('该批次赠课已因退费作废，请先撤销该批次的其他退费记录。')
                move(c,lid,m['batch_id'],-m['paid'],-m['gift'],-m['voided'])
        elif entry['delta']<0:consume(c,lid,sid,-entry['delta'],paid_only=True)
        else:
            bid=c.execute("INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,legacy) VALUES(?,?,0,0,0,'',1)",(sid,entry['delta'])).lastrowid
            move(c,lid,bid,entry['delta'],0)
    return finish(c,lid)
