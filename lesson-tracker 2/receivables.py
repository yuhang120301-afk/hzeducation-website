"""A 挂账 pack can be used before the money arrives. The money is a receivable until it is paid."""
import uuid

import accounting
import auditlog
import timeline
from teaching import AccessError


def schema(c):
    cols = {row['name'] for row in c.execute('PRAGMA table_info(credit_batches)')}
    if 'payment_status' not in cols:
        c.execute("ALTER TABLE credit_batches ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'paid'")
    if 'receivable_cents' not in cols:
        c.execute('ALTER TABLE credit_batches ADD COLUMN receivable_cents INTEGER NOT NULL DEFAULT 0')
    if 'paid_cents' not in cols:
        c.execute('ALTER TABLE credit_batches ADD COLUMN paid_cents INTEGER NOT NULL DEFAULT 0')
    c.execute('''CREATE TABLE IF NOT EXISTS pack_payments (
        id INTEGER PRIMARY KEY,
        batch_id INTEGER NOT NULL REFERENCES credit_batches(id),
        ledger_id INTEGER UNIQUE REFERENCES ledger(id),
        amount_cents INTEGER NOT NULL,
        paid_on TEXT NOT NULL,
        method TEXT NOT NULL DEFAULT '',
        voided INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )''')
    if c.execute("SELECT 1 FROM app_meta WHERE key='receivable_paid_v1'").fetchone():
        return
    c.execute('''UPDATE credit_batches
        SET payment_status='paid',
            receivable_cents=COALESCE(total_cents,0),
            paid_cents=COALESCE(total_cents,0)
        WHERE IFNULL(payment_status,'paid')!='unpaid' ''')
    c.execute("INSERT INTO app_meta(key,value) VALUES('receivable_paid_v1','1')")


def owed_cents(batch):
    if not batch or (batch['payment_status'] if 'payment_status' in batch.keys() else 'paid') != 'unpaid':
        return 0
    total = int(batch['receivable_cents'] or 0) if 'receivable_cents' in batch.keys() else 0
    paid = int(batch['paid_cents'] or 0) if 'paid_cents' in batch.keys() else 0
    return max(0, total - paid)


def open_on_ledger(c, ledger_id):
    """The new pack's price is owed. Hours are already on the pack. No cash is written here."""
    schema(c)
    batch = c.execute('SELECT * FROM credit_batches WHERE ledger_id=?', (ledger_id,)).fetchone()
    if not batch:
        raise ValueError('没有找到这次充值的课时包。')
    total = batch['total_cents']
    if total is None:
        raise ValueError('挂账需要有金额。')
    total = int(total)
    if total < 0:
        raise ValueError('挂账金额不能是负数。')
    c.execute('''UPDATE credit_batches SET payment_status='unpaid', receivable_cents=?, paid_cents=0 WHERE id=?''',
        (total, batch['id']))
    return batch['id']


def _owner(user):
    if not user or user.get('role') != 'owner':
        raise AccessError('只有老板可以登记挂账收款。')


def collect(c, user, data):
    """Record one payment against a 挂账 pack. A partial payment leaves the rest unpaid."""
    _owner(user)
    schema(c)
    batch = c.execute('SELECT * FROM credit_batches WHERE id=?', (int(data.get('batch_id') or 0),)).fetchone()
    if not batch:
        raise ValueError('这个课时包不存在。')
    remaining = owed_cents(batch)
    if remaining <= 0:
        raise ValueError('这个课时包没有挂账。')
    amount = accounting.money(data.get('amount'))
    if amount <= 0 or amount > remaining:
        raise ValueError('收款金额要大于 0，并且不能超过还欠的钱。')
    day = str(data.get('date') or '')
    import datetime as dt
    from teaching import now_local
    day = dt.date.fromisoformat(day).isoformat()
    if day > now_local().date().isoformat():
        raise ValueError('不能登记还没到的收款日期。')
    cents, method, reference = accounting.cash_details({'cash_amount': amount / 100, 'payment_method': data.get('payment_method'), 'reference': data.get('reference') or ''}, c)
    if cents != amount:
        raise ValueError('收款金额无效。')
    auditlog.begin(c)
    note = f"挂账收款 {batch['pack_label'] or '课时包'}"
    lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
        VALUES(?,0,'receipt',?,?,?,?)''', (batch['student_id'], day, note, user['id'], uuid.uuid4().hex)).lastrowid
    accounting.record_cash(c, lid, amount, method, reference, user['id'])
    c.execute('''INSERT INTO pack_payments(batch_id,ledger_id,amount_cents,paid_on,method,created_by)
        VALUES(?,?,?,?,?,?)''', (batch['id'], lid, amount, day, method, user['id']))
    paid = int(batch['paid_cents'] or 0) + amount
    status = 'paid' if paid >= int(batch['receivable_cents'] or 0) else 'unpaid'
    c.execute('UPDATE credit_batches SET paid_cents=?, payment_status=? WHERE id=?', (paid, status, batch['id']))
    import vouchers
    vouchers.issue_ledger(c, user, lid)
    timeline.record(c, user, batch['student_id'], 'receipt', f"挂账收款 {amount / 100:.2f}")
    auditlog.hint(c, f"挂账收款 ${amount / 100:.2f}")
    auditlog.finish(c, user)
    return {'ok': True, 'ledger_id': lid, 'paid_cents': paid, 'owed_cents': max(0, int(batch['receivable_cents'] or 0) - paid), 'payment_status': status}


def reverse_receipt(c, ledger_id):
    """A voided 挂账收款 puts the amount back on the pack. Hours are not touched."""
    schema(c)
    payment = c.execute('SELECT * FROM pack_payments WHERE ledger_id=? AND voided=0', (ledger_id,)).fetchone()
    if not payment:
        return
    batch = c.execute('SELECT * FROM credit_batches WHERE id=?', (payment['batch_id'],)).fetchone()
    c.execute('UPDATE pack_payments SET voided=1 WHERE id=?', (payment['id'],))
    if not batch:
        return
    paid = max(0, int(batch['paid_cents'] or 0) - int(payment['amount_cents'] or 0))
    total = int(batch['receivable_cents'] or 0)
    status = 'unpaid' if total and paid < total else batch['payment_status']
    c.execute('UPDATE credit_batches SET paid_cents=?, payment_status=? WHERE id=?', (paid, status, batch['id']))


def outstanding(c):
    schema(c)
    import switches
    switches.schema(c)
    rows = []
    for row in c.execute('''SELECT b.*, s.name student_name, s.course, s.profile_id
        FROM credit_batches b JOIN students s ON s.id=b.student_id
        WHERE b.payment_status='unpaid' AND IFNULL(b.status,'active')!='voided' AND IFNULL(s.voided,0)=0
        ORDER BY b.credited_on, b.id'''):
        owed = owed_cents(row)
        if owed <= 0:
            continue
        rows.append({
            'batch_id': row['id'], 'student_id': row['student_id'], 'profile_id': row['profile_id'],
            'student_name': row['student_name'], 'course': row['course'],
            'pack_label': row['pack_label'] or '课时包',
            'total_cents': int(row['receivable_cents'] or 0),
            'paid_cents': int(row['paid_cents'] or 0),
            'owed_cents': owed,
            'since': row['credited_on'] or '',
        })
    return rows


def total_owed(c):
    return sum(row['owed_cents'] for row in outstanding(c))
