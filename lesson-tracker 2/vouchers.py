"""Receipts for money and course events.

A new receipt starts as 待审核 and the balance has already changed. Approving
it does not move money again. Voiding it reverses the ledger entry.
"""
import datetime as dt

from teaching import AccessError, now_local

PREFIX = {'credit': 'CZ', 'refund': 'TF', 'stop': 'TK', 'adjust': 'TZ'}
STATUS = {'pending': '待审核', 'approved': '已审核', 'void': '已作废'}
BACKFILL_KEY = 'voucher_backfill_v1'


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers (
        id INTEGER PRIMARY KEY,
        number TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        student_id INTEGER,
        student_name TEXT NOT NULL DEFAULT '',
        course TEXT NOT NULL DEFAULT '',
        ledger_id INTEGER UNIQUE,
        reversal_ledger_id INTEGER,
        lesson_date TEXT NOT NULL,
        pack_label TEXT NOT NULL DEFAULT '',
        paid_units INTEGER NOT NULL DEFAULT 0,
        gift_units INTEGER NOT NULL DEFAULT 0,
        amount_cents INTEGER,
        payment_method TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        approved_by INTEGER,
        approved_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS voucher_events (
        id INTEGER PRIMARY KEY,
        voucher_id INTEGER NOT NULL REFERENCES vouchers(id),
        actor_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS voucher_seq (
        kind TEXT NOT NULL, year INTEGER NOT NULL, n INTEGER NOT NULL,
        PRIMARY KEY(kind, year)
    )''')
    backfill(c)


def hide_sql(c, alias):
    """Drop a voided receipt and its reversal from finance, wages and the share."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vouchers'").fetchone():
        return ''
    return (
        f" AND NOT EXISTS (SELECT 1 FROM vouchers v WHERE v.status='void'"
        f" AND (v.ledger_id={alias}.id OR v.reversal_ledger_id={alias}.id))"
    )


def _owner(user):
    if user['role'] != 'owner':
        raise AccessError('单据只对老板开放。')


def _year(day):
    text = str(day or '')
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else now_local().year


def _number(c, kind, year):
    row = c.execute('SELECT n FROM voucher_seq WHERE kind=? AND year=?', (kind, year)).fetchone()
    n = (row['n'] if row else 0) + 1
    if row:
        c.execute('UPDATE voucher_seq SET n=? WHERE kind=? AND year=?', (n, kind, year))
    else:
        c.execute('INSERT INTO voucher_seq(kind,year,n) VALUES(?,?,?)', (kind, year, n))
    return f"{PREFIX[kind]}-{year}-{n:04d}"


def _event(c, voucher_id, user, action, detail=''):
    c.execute('INSERT INTO voucher_events(voucher_id,actor_id,action,detail) VALUES(?,?,?,?)',
        (voucher_id, user['id'], action, str(detail or '')[:500]))


def _pack(c, ledger_id):
    row = c.execute('SELECT pack_label FROM credit_batches WHERE ledger_id=? AND pack_label!=\'\'', (ledger_id,)).fetchone()
    if row:
        return row['pack_label']
    row = c.execute('''SELECT b.pack_label FROM credit_movements m
        JOIN credit_batches b ON b.id=m.batch_id
        WHERE m.ledger_id=? AND b.pack_label!='' LIMIT 1''', (ledger_id,)).fetchone()
    return row['pack_label'] if row else ''


def _amounts(entry, cash):
    paid = abs(entry['paid_delta']) if entry['split_known'] else abs(entry['delta'])
    gift = abs(entry['gift_delta']) if entry['split_known'] else 0
    if entry['kind'] == 'refund' and entry['split_known']:
        paid = abs(entry['paid_delta'])
    amount = abs(cash['cash_delta']) if cash is not None else None
    method = cash['payment_method'] if cash is not None else ''
    return paid, gift, amount, method


def issue_ledger(c, user, ledger_id, approved=False):
    if c.execute('SELECT 1 FROM vouchers WHERE ledger_id=?', (ledger_id,)).fetchone():
        return None
    entry = c.execute('SELECT * FROM ledger WHERE id=?', (ledger_id,)).fetchone()
    if not entry or entry['kind'] not in ('credit', 'refund') or entry['reversal_of']:
        return None
    student = c.execute('SELECT name, course FROM students WHERE id=?', (entry['student_id'],)).fetchone()
    cash = c.execute('SELECT cash_delta, payment_method FROM cash_entries WHERE ledger_id=?', (ledger_id,)).fetchone()
    paid, gift, amount, method = _amounts(entry, cash)
    year = _year(entry['lesson_date'])
    number = _number(c, entry['kind'], year)
    status = 'approved' if approved else 'pending'
    vid = c.execute('''INSERT INTO vouchers(number,kind,status,student_id,student_name,course,ledger_id,lesson_date,
        pack_label,paid_units,gift_units,amount_cents,payment_method,note,created_by,approved_by,approved_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
        number, entry['kind'], status, entry['student_id'],
        student['name'] if student else '', student['course'] if student else '',
        ledger_id, entry['lesson_date'], _pack(c, ledger_id), paid, gift, amount, method,
        entry['note'], entry['actor_id'], entry['actor_id'] if approved else None,
        entry['created_at'] if approved else None)).lastrowid
    _event(c, vid, {'id': entry['actor_id']}, '历史补记' if approved else '开单', number)
    return vid


def issue_stop(c, user, student, deleted):
    """A stopped course. The balance is not moved; the receipt only records the decision."""
    name = student['name'] if not isinstance(student, dict) else student.get('name', '')
    course = student['course'] if not isinstance(student, dict) else student.get('course', '')
    sid = student['id'] if not isinstance(student, dict) else student.get('id')
    day = now_local().date().isoformat()
    note = '删除没有记录的课程' if deleted else '停课，历史记录保留'
    number = _number(c, 'stop', _year(day))
    vid = c.execute('''INSERT INTO vouchers(number,kind,status,student_id,student_name,course,lesson_date,
        note,created_by,paid_units,gift_units) VALUES(?,?,?,?,?,?,?,?,?,0,0)''',
        (number, 'stop', 'pending', sid, name, course, day, note, user['id'])).lastrowid
    _event(c, vid, user, '开单', note)
    return vid


def backfill(c):
    if c.execute('SELECT 1 FROM app_meta WHERE key=?', (BACKFILL_KEY,)).fetchone():
        return
    rows = c.execute("""SELECT id FROM ledger WHERE kind IN ('credit','refund') AND reversal_of IS NULL ORDER BY id""")
    for row in rows:
        issue_ledger(c, {'id': 0}, row['id'], approved=True)
    c.execute('INSERT OR IGNORE INTO app_meta(key,value) VALUES(?,?)', (BACKFILL_KEY, '1'))


def guard_edit(c, ledger_id):
    row = c.execute('SELECT status, number FROM vouchers WHERE ledger_id=?', (ledger_id,)).fetchone()
    if not row:
        return
    if row['status'] == 'void':
        raise ValueError(f'{row["number"]} 已作废，不能再改。')
    if row['status'] == 'approved':
        raise ValueError(f'{row["number"]} 已审核。请先撤销审核，再修改。')


def sync_from_ledger(c, user, ledger_id):
    row = c.execute('SELECT * FROM vouchers WHERE ledger_id=?', (ledger_id,)).fetchone()
    if not row or row['status'] != 'pending':
        return
    entry = c.execute('SELECT * FROM ledger WHERE id=?', (ledger_id,)).fetchone()
    if not entry:
        return
    cash = c.execute('SELECT cash_delta, payment_method FROM cash_entries WHERE ledger_id=?', (ledger_id,)).fetchone()
    paid, gift, amount, method = _amounts(entry, cash)
    c.execute('''UPDATE vouchers SET lesson_date=?, note=?, paid_units=?, gift_units=?, amount_cents=?, payment_method=?, pack_label=?
        WHERE id=?''', (entry['lesson_date'], entry['note'], paid, gift, amount, method, _pack(c, ledger_id) or row['pack_label'], row['id']))
    _event(c, row['id'], user, '修改', f'{row["number"]} 已按账本更新')


def _load(c, voucher_id):
    row = c.execute('SELECT * FROM vouchers WHERE id=?', (int(voucher_id),)).fetchone()
    if not row:
        raise ValueError('找不到这张单据。')
    return row


def approve(c, user, voucher_id):
    _owner(user)
    row = _load(c, voucher_id)
    if row['status'] == 'void':
        raise ValueError('已作废的单据不能审核。')
    if row['status'] == 'approved':
        return {'ok': True}
    c.execute("UPDATE vouchers SET status='approved', approved_by=?, approved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (user['id'], row['id']))
    _event(c, row['id'], user, '审核', row['number'])
    return {'ok': True}


def unapprove(c, user, voucher_id):
    _owner(user)
    row = _load(c, voucher_id)
    if row['status'] != 'approved':
        raise ValueError('只有已审核的单据可以撤销审核。')
    c.execute("UPDATE vouchers SET status='pending', approved_by=NULL, approved_at=NULL WHERE id=?", (row['id'],))
    _event(c, row['id'], user, '撤销审核', row['number'])
    return {'ok': True}


def edit(c, user, data, units, text_value):
    _owner(user)
    row = _load(c, data.get('id'))
    if row['status'] != 'pending':
        raise ValueError('请先撤销审核，再修改。')
    if row['ledger_id']:
        import record_edits
        entry = c.execute('SELECT * FROM ledger WHERE id=?', (row['ledger_id'],)).fetchone()
        payload = {
            'entry_id': entry['id'], 'version': entry['version'],
            'reason': '修改单据 ' + row['number'],
            'date': data.get('date') or entry['lesson_date'],
            'note': data.get('note', entry['note']),
            'amount': data.get('amount'),
            'cash_amount': data.get('cash_amount', ''),
            'payment_method': data.get('payment_method') or row['payment_method'] or 'bank',
            'reference': data.get('reference') or '',
        }
        if row['kind'] == 'credit':
            payload['gift_amount'] = data.get('gift_amount', 0)
        record_edits.edit(c, user, payload, units, text_value)
        return {'ok': True}
    note = str(data.get('note', row['note'])).strip()
    day = str(data.get('date') or row['lesson_date'])
    dt.date.fromisoformat(day)
    c.execute('UPDATE vouchers SET note=?, lesson_date=? WHERE id=?', (note[:300], day, row['id']))
    _event(c, row['id'], user, '修改', note[:120])
    return {'ok': True}


def void(c, user, voucher_id, units):
    _owner(user)
    row = _load(c, voucher_id)
    if row['status'] == 'void':
        raise ValueError('这张单据已经作废。')
    if row['kind'] == 'stop' or not row['ledger_id']:
        student = c.execute('SELECT * FROM students WHERE id=?', (row['student_id'],)).fetchone() if row['student_id'] else None
        if student and student['archived']:
            c.execute('UPDATE students SET archived=0 WHERE id=?', (student['id'],))
        c.execute("UPDATE vouchers SET status='void' WHERE id=?", (row['id'],))
        _event(c, row['id'], user, '作废', '停课单据作废' + ('，课程已恢复' if student and student['archived'] else ''))
        return {'ok': True}
    original = c.execute('SELECT * FROM ledger WHERE id=?', (row['ledger_id'],)).fetchone()
    if not original:
        raise ValueError('原账目不在了。')
    if c.execute('SELECT 1 FROM ledger WHERE reversal_of=?', (original['id'],)).fetchone():
        raise ValueError('这笔账已经撤销过。')
    student = c.execute('SELECT * FROM students WHERE id=?', (original['student_id'],)).fetchone()
    if student and student['balance'] - original['delta'] < 0:
        raise ValueError('剩余课时不够冲回这张单据。')
    import secrets
    import accounting
    import credit_batches
    day = now_local().date().isoformat()
    note = '作废单据 ' + row['number']
    lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of)
        VALUES(?,?,'reversal',?,?,?,?,?)''',
        (original['student_id'], -original['delta'], day, note, user['id'], 'void-' + secrets.token_hex(16), original['id'])).lastrowid
    credit_batches.apply(c, lid, 'reversal', {}, units, original)
    cash = c.execute('SELECT * FROM cash_entries WHERE ledger_id=?', (original['id'],)).fetchone()
    if cash:
        accounting.record_cash(c, lid, -cash['cash_delta'], cash['payment_method'], note, user['id'])
    c.execute("UPDATE vouchers SET status='void', reversal_ledger_id=? WHERE id=?", (lid, row['id']))
    _event(c, row['id'], user, '作废', note)
    return {'ok': True, 'reversal_id': lid}


def attach_reversal(c, user, ledger_id, reversal_id):
    """The old undo button already reversed the ledger. Mark the receipt void too."""
    row = c.execute('SELECT * FROM vouchers WHERE ledger_id=? AND status!=\'void\'', (ledger_id,)).fetchone()
    if not row:
        return
    c.execute("UPDATE vouchers SET status='void', reversal_ledger_id=? WHERE id=?", (reversal_id, row['id']))
    _event(c, row['id'], user, '作废', '从账本撤销')


def _public(row, actor):
    item = dict(row)
    item['status_label'] = STATUS.get(row['status'], row['status'])
    item['kind_label'] = {'credit': '充值', 'refund': '退费', 'stop': '退课', 'adjust': '调整'}.get(row['kind'], row['kind'])
    item['actor_name'] = actor or ''
    return item


def search(c, user, student_id=None, kind=None, status=None, start=None, end=None, query=None):
    _owner(user)
    sql = '''SELECT v.*, u.name actor_name FROM vouchers v
        LEFT JOIN users u ON u.id=v.created_by WHERE 1=1'''
    args = []
    if student_id:
        sql += ' AND v.student_id=?'
        args.append(int(student_id))
    if kind in PREFIX:
        sql += ' AND v.kind=?'
        args.append(kind)
    if status in STATUS:
        sql += ' AND v.status=?'
        args.append(status)
    if start:
        sql += ' AND v.lesson_date>=?'
        args.append(str(start))
    if end:
        sql += ' AND v.lesson_date<=?'
        args.append(str(end))
    if query:
        sql += ' AND (v.number LIKE ? OR v.student_name LIKE ? OR v.course LIKE ? OR v.note LIKE ? OR v.pack_label LIKE ?)'
        like = f'%{str(query).strip()}%'
        args.extend([like, like, like, like, like])
    sql += ' ORDER BY v.lesson_date DESC, v.id DESC'
    rows = [_public(row, row['actor_name']) for row in c.execute(sql, args)]
    credit = sum(row['amount_cents'] or 0 for row in rows if row['kind'] == 'credit' and row['status'] != 'void')
    refund = sum(row['amount_cents'] or 0 for row in rows if row['kind'] == 'refund' and row['status'] != 'void')
    return {'vouchers': rows, 'totals': {
        'count': len(rows), 'open_count': sum(1 for row in rows if row['status'] != 'void'),
        'credit_cents': credit, 'refund_cents': refund, 'net_cents': credit - refund,
    }}


def events(c, user, voucher_id):
    _owner(user)
    _load(c, voucher_id)
    return [dict(row) for row in c.execute('''SELECT e.*, u.name actor_name FROM voucher_events e
        LEFT JOIN users u ON u.id=e.actor_id WHERE e.voucher_id=? ORDER BY e.id''', (int(voucher_id),))]
