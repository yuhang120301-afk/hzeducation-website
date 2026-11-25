"""Who changed what, and a one-step undo.

Each saved action compares the business rows before and after. Undo puts those
rows back, and only if nobody has changed them since. The undo is logged too.
"""
import json

from teaching import AccessError

# Higher rank is removed first when an insert is undone, so child rows go before parents.
RANK = {
    'payment_methods': 10,
    'price_tables': 20,
    'lesson_series': 30,
    'price_rows': 40,
    'student_prices': 40,
    'student_subject_prices': 40,
    'pay_rules': 40,
    'partner_share_rules': 40,
    'cost_schedules': 40,
    'cost_entries': 40,
    'students': 50,
    'profile_parents': 45,
    'lessons': 60,
    'ledger': 70,
    'credit_batches': 80,
    'vouchers': 85,
    'lesson_students': 80,
    'arrears': 80,
    'lesson_reports': 90,
    'credit_movements': 95,
    'cash_entries': 95,
    'voucher_events': 96,
    'profile_events': 97,
}
PRIMARY = {
    'students': ('id',),
    'profile_parents': ('profile_id', 'user_id'),
    'ledger': ('id',),
    'credit_batches': ('id',),
    'vouchers': ('id',),
    'credit_movements': ('ledger_id', 'batch_id'),
    'cash_entries': ('ledger_id',),
    'voucher_events': ('id',),
    'profile_events': ('id',),
    'lessons': ('id',),
    'lesson_students': ('lesson_id', 'student_id'),
    'lesson_reports': ('lesson_id', 'student_id'),
    'lesson_series': ('id',),
    'pay_rules': ('id',),
    'partner_share_rules': ('id',),
    'cost_entries': ('id',),
    'cost_schedules': ('id',),
    'price_tables': ('id',),
    'price_rows': ('id',),
    'student_prices': ('id',),
    'student_subject_prices': ('id',),
    'payment_methods': ('code',),
    'arrears': ('id',),
}


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY,
        actor_id INTEGER NOT NULL REFERENCES users(id),
        action TEXT NOT NULL,
        summary TEXT NOT NULL,
        ops_json TEXT NOT NULL,
        undone_by INTEGER,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS audit_actor ON audit_log(actor_id, id)')


# sqlite3.Connection has no instance dictionary, so the before-image cannot live on it.
_PENDING = []


def _slot(c):
    alive = []
    found = None
    for item in _PENDING:
        conn, data = item
        if conn is c:
            found = data
            alive.append(item)
            continue
        try:
            conn.execute('SELECT 1')
        except Exception:
            continue
        alive.append(item)
    _PENDING[:] = alive
    if found is None:
        found = {'before': None, 'hint': ''}
        _PENDING.append([c, found])
    return found


def hint(c, text):
    _slot(c)['hint'] = str(text or '')[:200]


def _key(row, columns):
    return tuple(row[column] for column in columns)


def _plain(row):
    return {key: row[key] for key in row.keys()}


def snapshot(c):
    found = {}
    existing = {r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, columns in PRIMARY.items():
        if table not in existing:
            found[table] = {}
            continue
        rows = {}
        for row in c.execute(f'SELECT * FROM {table}'):
            item = _plain(row)
            rows[_key(item, columns)] = item
        found[table] = rows
    return found


def begin(c):
    _slot(c)['before'] = snapshot(c)


def _summary(ops, hint_text):
    if hint_text:
        return hint_text
    if not ops:
        return '保存'
    verbs = {'insert': '新增', 'update': '修改', 'delete': '删除'}
    first = ops[0]
    label = f"{verbs.get(first['op'], '修改')} {first['table']}"
    if len(ops) > 1:
        label += f' 等 {len(ops)} 处'
    return label


def _action(ops):
    kinds = {op['op'] for op in ops}
    if kinds == {'insert'}:
        return 'create'
    if kinds == {'delete'}:
        return 'delete'
    if kinds == {'update'}:
        return 'update'
    return 'update'


def finish(c, user):
    slot = _slot(c)
    before = slot.get('before')
    hint_text = slot.get('hint', '')
    slot['before'] = None
    slot['hint'] = ''
    if not user or before is None:
        return None
    after = snapshot(c)
    ops = []
    for table, columns in PRIMARY.items():
        old, new = before.get(table, {}), after.get(table, {})
        for key in old.keys() - new.keys():
            ops.append({'op': 'delete', 'table': table, 'pk': list(zip(columns, key)), 'before': old[key], 'after': None, 'rank': RANK[table]})
        for key in new.keys() - old.keys():
            ops.append({'op': 'insert', 'table': table, 'pk': list(zip(columns, key)), 'before': None, 'after': new[key], 'rank': RANK[table]})
        for key in old.keys() & new.keys():
            if old[key] != new[key]:
                ops.append({'op': 'update', 'table': table, 'pk': list(zip(columns, key)), 'before': old[key], 'after': new[key], 'rank': RANK[table]})
    if not ops:
        return None
    summary = _summary(ops, hint_text)
    return c.execute('INSERT INTO audit_log(actor_id,action,summary,ops_json) VALUES(?,?,?,?)',
        (user['id'], _action(ops), summary, json.dumps(ops, ensure_ascii=False, default=str))).lastrowid


def _where(pk):
    clause = ' AND '.join(f'{column}=?' for column, _value in pk)
    values = [value for _column, value in pk]
    return clause, values


def _current(c, table, pk):
    clause, values = _where(pk)
    row = c.execute(f'SELECT * FROM {table} WHERE {clause}', values).fetchone()
    return _plain(row) if row else None


def _same(left, right):
    if left is None or right is None:
        return left is right
    return {key: left.get(key) for key in right.keys()} == right or left == right


def _write(c, table, columns, row):
    names = list(columns)
    marks = ','.join('?' for _ in names)
    c.execute(f'INSERT INTO {table}({",".join(names)}) VALUES({marks})', [row.get(name) for name in names])


def undo(c, user, audit_id):
    row = c.execute('SELECT * FROM audit_log WHERE id=?', (int(audit_id),)).fetchone()
    if not row:
        raise ValueError('找不到这条操作记录。')
    if user['role'] != 'owner' and row['actor_id'] != user['id']:
        raise AccessError('只能撤回自己的操作。全部记录仅老板可看。')
    if row['undone_by']:
        raise ValueError('这条操作已经撤回。')
    ops = json.loads(row['ops_json'])
    for op in ops:
        current = _current(c, op['table'], op['pk'])
        if op['op'] == 'insert':
            if not _same(current, op['after']):
                raise ValueError('之后又有修改，请从最新的操作开始撤回。')
        elif op['op'] == 'update':
            if not _same(current, op['after']):
                raise ValueError('之后又有修改，请从最新的操作开始撤回。')
        elif current is not None:
            raise ValueError('之后又有修改，请从最新的操作开始撤回。')
    for op in sorted((item for item in ops if item['op'] == 'insert'), key=lambda item: -item['rank']):
        clause, values = _where(op['pk'])
        c.execute(f'DELETE FROM {op["table"]} WHERE {clause}', values)
    for op in (item for item in ops if item['op'] == 'update'):
        columns = [key for key in op['before'].keys()]
        assignments = ','.join(f'{column}=?' for column in columns)
        clause, pk_values = _where(op['pk'])
        c.execute(f'UPDATE {op["table"]} SET {assignments} WHERE {clause}', [op['before'].get(column) for column in columns] + pk_values)
    for op in sorted((item for item in ops if item['op'] == 'delete'), key=lambda item: item['rank']):
        _write(c, op['table'], op['before'].keys(), op['before'])
    return {'ok': True, 'undone': row['id']}


def last_for(c, user):
    if user['role'] != 'owner':
        raise AccessError('只有老板可以撤销上一步。')
    row = c.execute('''SELECT * FROM audit_log WHERE actor_id=? AND undone_by IS NULL
        ORDER BY id DESC LIMIT 1''', (user['id'],)).fetchone()
    if not row:
        return {'entry': None}
    ops = json.loads(row['ops_json'] or '[]')
    money = any(op.get('table') in ('ledger', 'cash_entries') for op in ops)
    return {'entry': {'id': row['id'], 'summary': row['summary'], 'money': money}}


def mark_undone(c, audit_id, undone_by):
    c.execute('UPDATE audit_log SET undone_by=? WHERE id=? AND undone_by IS NULL', (undone_by, audit_id))


def search(c, user, actor_id, start, end):
    if user['role'] != 'owner':
        raise AccessError('操作日志仅老板可查看。')
    sql = '''SELECT a.*, u.name actor_name FROM audit_log a JOIN users u ON u.id=a.actor_id WHERE 1=1'''
    params = []
    if actor_id:
        sql += ' AND a.actor_id=?'
        params.append(int(actor_id))
    if start:
        sql += ' AND substr(a.created_at,1,10)>=?'
        params.append(str(start))
    if end:
        sql += ' AND substr(a.created_at,1,10)<=?'
        params.append(str(end))
    sql += ' ORDER BY a.id DESC LIMIT 300'
    rows = []
    for item in c.execute(sql, params):
        row = dict(item)
        ops = json.loads(row.pop('ops_json'))
        row['changes'] = [{
            'op': op['op'], 'table': op['table'],
            'before': op.get('before'), 'after': op.get('after'),
        } for op in ops[:12]]
        row['change_count'] = len(ops)
        rows.append(row)
    people = [dict(r) for r in c.execute('''SELECT DISTINCT u.id, u.name FROM audit_log a JOIN users u ON u.id=a.actor_id ORDER BY u.name''')]
    return {'entries': rows, 'people': people}
