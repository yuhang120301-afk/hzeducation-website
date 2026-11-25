"""Receipts for money and course events.

A new receipt starts as 待审核 and the balance has already changed. Approving
it does not move money again. Voiding it reverses the ledger entry.
"""
import datetime as dt

from teaching import AccessError, now_local

PREFIX = {'credit': 'CZ', 'refund': 'TF', 'stop': 'TK', 'adjust': 'TZ', 'receipt': 'SK'}
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
    if not entry or entry['kind'] not in ('credit', 'refund', 'receipt') or entry['reversal_of']:
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


def _mark_approved(c, user, row):
    """The only write single and bulk approve share. Approval does not move the balance."""
    c.execute("UPDATE vouchers SET status='approved', approved_by=?, approved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (user['id'], row['id']))
    _event(c, row['id'], user, '审核', row['number'])


def approve(c, user, voucher_id):
    _owner(user)
    row = _load(c, voucher_id)
    if row['status'] == 'void':
        raise ValueError('已作废的单据不能审核。')
    if row['status'] == 'approved':
        return {'ok': True}
    _mark_approved(c, user, row)
    return {'ok': True}


def _voucher_ids(raw):
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise ValueError('请选择要审核的单据。')
    if not raw:
        raise ValueError('请选择要审核的单据。')
    if len(raw) > 500:
        raise ValueError('一次最多审核 500 张单据。')
    ids = []
    seen = set()
    for item in raw:
        if isinstance(item, bool):
            raise ValueError('单据编号无效。')
        if isinstance(item, int):
            vid = item
        elif isinstance(item, str) and item.isdigit():
            vid = int(item)
        else:
            raise ValueError('单据编号无效。')
        if vid < 1:
            raise ValueError('单据编号无效。')
        if vid in seen:
            continue
        seen.add(vid)
        ids.append(vid)
    return ids


def approve_many(c, user, ids):
    """Approve each pending receipt with the single-approve write. Does not commit."""
    _owner(user)
    chosen = _voucher_ids(ids)
    approved_ids = []
    skipped = []
    for vid in chosen:
        row = c.execute('SELECT * FROM vouchers WHERE id=?', (vid,)).fetchone()
        if not row or row['status'] != 'pending':
            skipped.append({
                'id': vid,
                'number': row['number'] if row else '',
                'status': row['status'] if row else 'missing',
            })
            continue
        _mark_approved(c, user, row)
        approved_ids.append(vid)
    return {'ok': True, 'approved': len(approved_ids), 'approved_ids': approved_ids, 'skipped': skipped}


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


def _chain_tail(c, original):
    """The ledger row that still carries this receipt, after any void and un-void."""
    current = original
    while True:
        nxt = c.execute('SELECT * FROM ledger WHERE reversal_of=? ORDER BY id DESC LIMIT 1', (current['id'],)).fetchone()
        if not nxt:
            return current
        current = nxt


def _pack_schema(c):
    cols = {row['name'] for row in c.execute('PRAGMA table_info(credit_batches)')}
    if 'status' in cols and 'payment_status' in cols:
        return
    # executescript commits an open transaction, so this only runs before any write.
    import switches
    switches.schema(c)


def _park_credit_pack(c, ledger_id):
    """A voided top-up no longer looks like a live pack, and a 挂账 drops out of what is owed."""
    _pack_schema(c)
    for batch in c.execute('SELECT * FROM credit_batches WHERE ledger_id=?', (ledger_id,)):
        status = batch['status'] if 'status' in batch.keys() else 'active'
        if status not in ('active', '', None):
            continue
        if int(batch['paid_left'] or 0) or int(batch['gift_left'] or 0):
            continue
        payment = batch['payment_status'] if 'payment_status' in batch.keys() else 'paid'
        if payment == 'unpaid':
            c.execute("UPDATE credit_batches SET status='voided', payment_status='voided' WHERE id=?", (batch['id'],))
        else:
            c.execute("UPDATE credit_batches SET status='voided' WHERE id=?", (batch['id'],))


def _reopen_credit_pack(c, ledger_id):
    """Put the pack back. Hours are already restored. A parked 挂账 becomes owed again."""
    _pack_schema(c)
    for batch in c.execute('SELECT * FROM credit_batches WHERE ledger_id=?', (ledger_id,)):
        status = batch['status'] if 'status' in batch.keys() else 'active'
        payment = batch['payment_status'] if 'payment_status' in batch.keys() else 'paid'
        if status == 'switched':
            continue
        receivable = int(batch['receivable_cents'] or 0) if 'receivable_cents' in batch.keys() else 0
        total = int(batch['total_cents'] or 0) if 'total_cents' in batch.keys() else 0
        if payment in ('voided', 'unpaid'):
            if not receivable and total:
                receivable = total
            c.execute('''UPDATE credit_batches SET status='active', payment_status='unpaid', receivable_cents=?
                WHERE id=?''', (receivable, batch['id']))
        else:
            c.execute("UPDATE credit_batches SET status='active' WHERE id=?", (batch['id'],))


def _status_before_void(c, voucher_id):
    """The status this receipt had when it was voided, including an earlier un-void."""
    status = 'pending'
    before = 'pending'
    for event in c.execute('SELECT action FROM voucher_events WHERE voucher_id=? ORDER BY id', (voucher_id,)):
        action = event['action']
        if action in ('审核', '历史补记'):
            status = 'approved'
        elif action == '撤销审核':
            status = 'pending'
        elif action == '作废':
            before = status
            status = 'void'
        elif action == '取消作废':
            status = before
    return before if status == 'void' else status


def _replacement_number(c, row):
    event = c.execute('''SELECT created_at FROM voucher_events
        WHERE voucher_id=? AND action='作废' ORDER BY id DESC LIMIT 1''', (row['id'],)).fetchone()
    if not event or not row['student_id']:
        return ''
    other = c.execute('''SELECT number FROM vouchers
        WHERE student_id=? AND kind=? AND id!=? AND status!='void' AND created_at>?
        ORDER BY id LIMIT 1''', (row['student_id'], row['kind'], row['id'], event['created_at'])).fetchone()
    return other['number'] if other else ''


def _restore_receipt(c, ledger_id):
    """Put a voided 挂账收款 back onto its pack."""
    import receivables
    receivables.schema(c)
    payment = c.execute('SELECT * FROM pack_payments WHERE ledger_id=? AND voided=1', (ledger_id,)).fetchone()
    if not payment:
        return
    batch = c.execute('SELECT * FROM credit_batches WHERE id=?', (payment['batch_id'],)).fetchone()
    if not batch:
        raise ValueError('这个课时包不在了，不能取消作废。')
    c.execute('UPDATE pack_payments SET voided=0 WHERE id=?', (payment['id'],))
    paid = int(batch['paid_cents'] or 0) + int(payment['amount_cents'] or 0)
    total = int(batch['receivable_cents'] or 0)
    if total and paid >= total:
        status = 'paid'
    elif total:
        status = 'unpaid'
    else:
        status = batch['payment_status']
    c.execute('UPDATE credit_batches SET paid_cents=?, payment_status=? WHERE id=?', (paid, status, batch['id']))


def _packs_and_ledger(c, student_id):
    balance = int(c.execute('SELECT balance FROM students WHERE id=?', (student_id,)).fetchone()['balance'] or 0)
    packs = int(c.execute('SELECT COALESCE(SUM(paid_left+gift_left),0) n FROM credit_batches WHERE student_id=?',
        (student_id,)).fetchone()['n'] or 0)
    ledger = int(c.execute('SELECT COALESCE(SUM(delta),0) n FROM ledger WHERE student_id=?', (student_id,)).fetchone()['n'] or 0)
    return balance, packs, ledger


def _mistake_course(student):
    if not student or 'voided' not in student.keys():
        return False
    reason = str(student['void_reason'] or '') if 'void_reason' in student.keys() else ''
    return int(student['voided'] or 0) == 1 or reason == '加错了'


def _restore_course_row(c, student):
    """Clear 加错了 markers so the course is enrolled again."""
    import deletion
    deletion.schema(c)
    try:
        c.execute("UPDATE students SET archived=0, voided=0, void_reason='' WHERE id=?", (student['id'],))
    except Exception as exc:
        if 'UNIQUE' in str(exc).upper():
            raise ValueError('这门课已经有另一条在读记录，不能同时恢复。')
        raise


def unvoid(c, user, voucher_id, units, restore_course=False):
    """Put back exactly what a void took away. A new ledger row reverses the reversal."""
    _owner(user)
    import auditlog
    import deletion
    deletion.schema(c)
    row = _load(c, voucher_id)
    if row['status'] != 'void':
        raise ValueError('这张单据没有作废，不用取消作废。')
    student = None
    if row['student_id']:
        student = c.execute('SELECT * FROM students WHERE id=?', (row['student_id'],)).fetchone()
        if not student:
            raise ValueError('这门课已经不在了，不能取消作废。')
    replacement = _replacement_number(c, row)
    if replacement:
        raise ValueError(f'已经另开了单据 {replacement}，不能再取消作废。')
    status = _status_before_void(c, row['id'])
    if status not in ('pending', 'approved'):
        status = 'pending'
    restoring = bool(restore_course and _mistake_course(student))
    auditlog.begin(c)
    try:
        if row['ledger_id']:
            _repost(c, user, row, units)
        elif student:
            detail = c.execute('''SELECT detail FROM voucher_events
                WHERE voucher_id=? AND action='作废' ORDER BY id DESC LIMIT 1''', (row['id'],)).fetchone()
            if detail and '课程已恢复' in (detail['detail'] or '') and not student['archived']:
                c.execute('UPDATE students SET archived=1 WHERE id=?', (student['id'],))
        if restoring:
            _restore_course_row(c, student)
        if status == 'approved':
            c.execute("UPDATE vouchers SET status='approved' WHERE id=?", (row['id'],))
            if not row['approved_by']:
                c.execute('''UPDATE vouchers SET approved_by=?, approved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE id=?''', (user['id'], row['id']))
        else:
            c.execute("UPDATE vouchers SET status='pending', approved_by=NULL, approved_at=NULL WHERE id=?", (row['id'],))
        _event(c, row['id'], user, '取消作废', row['number'])
        import timeline
        if row['student_id']:
            summary = f"取消作废 {row['number']}"
            if restoring:
                summary += '，并恢复课程'
            timeline.record(c, user, row['student_id'], 'unvoid', summary)
        hint = f"取消作废 {row['number']}"
        if restoring:
            hint += '，并恢复课程'
        auditlog.hint(c, hint)
        auditlog.finish(c, user)
    except Exception:
        slot = auditlog._slot(c)
        slot['before'] = None
        slot['hint'] = ''
        raise
    return {'ok': True, 'status': status, 'course_restored': restoring}


def _repost(c, user, row, units):
    original = c.execute('SELECT * FROM ledger WHERE id=?', (row['ledger_id'],)).fetchone()
    if not original:
        raise ValueError('原账目不在了，不能取消作废。')
    reversal = None
    if row['reversal_ledger_id']:
        reversal = c.execute('SELECT * FROM ledger WHERE id=?', (row['reversal_ledger_id'],)).fetchone()
    if not reversal:
        reversal = c.execute('SELECT * FROM ledger WHERE reversal_of=? ORDER BY id DESC LIMIT 1', (original['id'],)).fetchone()
    if not reversal:
        raise ValueError('作废账目不在了，不能取消作废。')
    if c.execute('SELECT 1 FROM ledger WHERE reversal_of=?', (reversal['id'],)).fetchone():
        raise ValueError('这张作废已经冲回过，不能再取消作废。')
    import secrets
    import accounting
    import credit_batches
    before_balance, before_packs, _before_ledger = _packs_and_ledger(c, original['student_id'])
    note = '取消作废 ' + row['number']
    lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of)
        VALUES(?,?,'reversal',?,?,?,?,?)''', (
        original['student_id'], -int(reversal['delta'] or 0), original['lesson_date'], note,
        user['id'], 'unvoid-' + secrets.token_hex(16), reversal['id'])).lastrowid
    if original['kind'] == 'receipt':
        _restore_receipt(c, original['id'])
    else:
        movements = list(c.execute('SELECT batch_id FROM credit_movements WHERE ledger_id=?', (reversal['id'],)))
        for movement in movements:
            if not c.execute('SELECT 1 FROM credit_batches WHERE id=?', (movement['batch_id'],)).fetchone():
                raise ValueError('这个课时包不在了，不能取消作废。')
        try:
            credit_batches.apply(c, lid, 'reversal', {}, units, reversal)
        except (ValueError, TypeError) as exc:
            text = str(exc)
            if isinstance(exc, TypeError) or '课时' in text or '批次' in text:
                raise ValueError('取消作废会和已经用掉或退掉的课时冲突，请先处理那些记录。')
            raise
        if original['kind'] == 'credit':
            _reopen_credit_pack(c, original['id'])
    cash = c.execute('SELECT * FROM cash_entries WHERE ledger_id=?', (reversal['id'],)).fetchone()
    if cash and int(cash['cash_delta'] or 0):
        accounting.record_cash(c, lid, -int(cash['cash_delta']), cash['payment_method'], note, user['id'],
            cash['received_by'] if 'received_by' in cash.keys() else user['id'],
            cash['handed_over'] if 'handed_over' in cash.keys() else 1,
            cash['handed_over_on'] if 'handed_over_on' in cash.keys() else None)
    balance, packs, ledger = _packs_and_ledger(c, original['student_id'])
    if balance - before_balance != packs - before_packs:
        raise ValueError('取消作废后余额和课时包对不上，已停下。')
    if balance != ledger:
        raise ValueError('取消作废后余额和账本对不上，已停下。')


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
        import timeline
        if row['student_id']:
            timeline.record(c, user, row['student_id'], 'void', f"作废单据 {row['number']}")
        return {'ok': True}
    original = c.execute('SELECT * FROM ledger WHERE id=?', (row['ledger_id'],)).fetchone()
    if not original:
        raise ValueError('原账目不在了。')
    source = _chain_tail(c, original)
    student = c.execute('SELECT * FROM students WHERE id=?', (source['student_id'],)).fetchone()
    if student and student['balance'] - source['delta'] < 0:
        raise ValueError('剩余课时不够冲回这张单据。')
    import secrets
    import accounting
    import credit_batches
    day = now_local().date().isoformat()
    note = '作废单据 ' + row['number']
    lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of)
        VALUES(?,?,'reversal',?,?,?,?,?)''',
        (source['student_id'], -source['delta'], day, note, user['id'], 'void-' + secrets.token_hex(16), source['id'])).lastrowid
    if original['kind'] == 'receipt':
        credit_batches.apply(c, lid, 'reversal', {}, units, original)
    else:
        credit_batches.apply(c, lid, 'reversal', {}, units, source)
        if original['kind'] == 'credit':
            _park_credit_pack(c, original['id'])
    cash = c.execute('SELECT * FROM cash_entries WHERE ledger_id=?', (source['id'],)).fetchone()
    if cash:
        accounting.record_cash(c, lid, -cash['cash_delta'], cash['payment_method'], note, user['id'])
    c.execute("UPDATE vouchers SET status='void', reversal_ledger_id=? WHERE id=?", (lid, row['id']))
    _event(c, row['id'], user, '作废', note)
    import timeline
    timeline.record(c, user, original['student_id'], 'void', f"作废单据 {row['number']}")
    return {'ok': True, 'reversal_id': lid}


def attach_reversal(c, user, ledger_id, reversal_id):
    """The old undo button already reversed the ledger. Mark the receipt void too."""
    row = c.execute('SELECT * FROM vouchers WHERE ledger_id=? AND status!=\'void\'', (ledger_id,)).fetchone()
    if not row:
        return
    c.execute("UPDATE vouchers SET status='void', reversal_ledger_id=? WHERE id=?", (reversal_id, row['id']))
    _event(c, row['id'], user, '作废', '从账本撤销')
    import timeline
    if row['student_id']:
        timeline.record(c, user, row['student_id'], 'void', f"作废单据 {row['number']}")


def _public(row, actor):
    item = dict(row)
    item['status_label'] = STATUS.get(row['status'], row['status'])
    item['kind_label'] = {'credit': '充值', 'refund': '退费', 'stop': '退课', 'adjust': '调整', 'receipt': '挂账收款'}.get(row['kind'], row['kind'])
    item['actor_name'] = actor or ''
    return item


def search(c, user, student_id=None, kind=None, status=None, start=None, end=None, query=None):
    _owner(user)
    student_cols = {row['name'] for row in c.execute('PRAGMA table_info(students)')}
    if 'voided' not in student_cols or 'void_reason' not in student_cols:
        import deletion
        deletion.schema(c)
    sql = '''SELECT v.*, u.name actor_name, IFNULL(s.voided,0) course_voided,
        IFNULL(s.void_reason,'') course_void_reason
        FROM vouchers v
        LEFT JOIN users u ON u.id=v.created_by
        LEFT JOIN students s ON s.id=v.student_id WHERE 1=1'''
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
