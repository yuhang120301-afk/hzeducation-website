"""Boss-only operating costs. Teacher pay is not an expense here.

A monthly fixed cost becomes one cost_entries row per month, once.
Voiding and edits go through the audit log, so they can be undone.
New rows are shared costs: Vincent's share still subtracts them from
new-student fees and applies his existing percentage. It does not
change that formula, and it does not touch a row marked shared=0.
"""
import calendar
import datetime as dt

import accounting
import auditlog
from teaching import now_local

DEFAULT_CATEGORIES = ('房租', '教材打印', '广告', '软件', '设备/文具', '其他')
MONTH_CAP = 240


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS expense_categories (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        builtin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS monthly_costs (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
        day_of_month INTEGER NOT NULL CHECK(day_of_month BETWEEN 1 AND 31),
        start_month TEXT NOT NULL,
        end_month TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        shared INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )''')
    cols = {row['name'] for row in c.execute('PRAGMA table_info(cost_entries)')}
    if 'category_id' not in cols:
        c.execute('ALTER TABLE cost_entries ADD COLUMN category_id INTEGER')
    if 'monthly_id' not in cols:
        c.execute('ALTER TABLE cost_entries ADD COLUMN monthly_id INTEGER')
    if 'source_month' not in cols:
        c.execute('ALTER TABLE cost_entries ADD COLUMN source_month TEXT')
    c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS expense_month_once
        ON cost_entries(monthly_id, source_month) WHERE monthly_id IS NOT NULL''')
    for name in DEFAULT_CATEGORIES:
        c.execute('INSERT OR IGNORE INTO expense_categories(name, builtin) VALUES(?,1)', (name,))


def require_owner(user):
    accounting.require_owner(user)


def _parse_month(text, label):
    raw = str(text or '').strip()
    try:
        if len(raw) != 7 or raw[4] != '-':
            raise ValueError
        year, month = int(raw[:4]), int(raw[5:7])
        if year < 2000 or year > 2100 or not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        raise ValueError(label)
    return year, month


def _month_key(year, month):
    return f'{year:04d}-{month:02d}'


def _next_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1


def entry_date(year, month, day):
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(int(day), last))


def _today(today):
    return today or now_local().date()


def _category(c, category_id):
    row = c.execute('SELECT * FROM expense_categories WHERE id=?', (int(category_id or 0),)).fetchone()
    if not row:
        raise ValueError('请选择类别。')
    return row


def _name(raw, label, limit):
    text = str(raw or '').strip()
    if not text or len(text) > limit or '\n' in text or '\r' in text:
        raise ValueError(label)
    return text


def _note(raw):
    text = str(raw or '').strip()
    if len(text) > 200:
        raise ValueError('备注最多 200 个字。')
    return text


def _aud(cents):
    return f'${int(cents) / 100:.2f}'


def _existing_months(c):
    found = {}
    for row in c.execute('SELECT monthly_id, source_month FROM cost_entries WHERE monthly_id IS NOT NULL'):
        found.setdefault(row['monthly_id'], set()).add(row['source_month'])
    return found


def _last_month(row, today_key):
    if not row['active']:
        return row['end_month'] or ''
    last = today_key
    if row['end_month'] and row['end_month'] < last:
        last = row['end_month']
    return last


def _ensure_schedule(c, row, today, seen):
    today_key = _month_key(today.year, today.month)
    last = _last_month(row, today_key)
    if not last or row['start_month'] > last:
        return
    year, month = _parse_month(row['start_month'], '开始月份无效。')
    have = seen.setdefault(row['id'], set())
    for _ in range(MONTH_CAP):
        key = _month_key(year, month)
        if key > last:
            return
        if key not in have:
            when = entry_date(year, month, row['day_of_month'])
            c.execute('''INSERT INTO cost_entries(cost_date,label,amount_cents,note,voided,shared,created_by,category_id,monthly_id,source_month)
                VALUES(?,?,?,'',0,?,?,?,?,?)''',
                (when.isoformat(), row['name'], row['amount_cents'], row['shared'], row['created_by'],
                 row['category_id'], row['id'], key))
            have.add(key)
        year, month = _next_month(year, month)


def materialize(c, today=None, only_id=None):
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monthly_costs'").fetchone() is None:
        return
    today = _today(today)
    seen = _existing_months(c)
    sql = 'SELECT * FROM monthly_costs'
    params = ()
    if only_id:
        sql += ' WHERE id=?'
        params = (only_id,)
    for row in c.execute(sql, params):
        _ensure_schedule(c, row, today, seen)


def _log(c, user, hint):
    auditlog.hint(c, hint)
    auditlog.finish(c, user)


def add_entry(c, user, data):
    require_owner(user)
    materialize(c)
    category = _category(c, data.get('category_id'))
    note = _note(data.get('note'))
    day = __import__('payroll').day_value(data.get('cost_date'), '请选择日期。').isoformat()
    amount = accounting.money(data.get('amount'))
    auditlog.begin(c)
    c.execute('''INSERT INTO cost_entries(cost_date,label,amount_cents,note,voided,shared,created_by,category_id)
        VALUES(?,?,?,?,0,1,?,?)''', (day, category['name'], amount, note, user['id'], category['id']))
    extra = f' {note}' if note else ''
    _log(c, user, f"记一笔成本：{category['name']}{extra} {_aud(amount)}")
    return {'ok': True}


def edit_entry(c, user, data):
    require_owner(user)
    materialize(c)
    row = c.execute('SELECT * FROM cost_entries WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not row:
        raise ValueError('找不到这条成本。')
    if row['voided']:
        raise ValueError('这条成本已经作废，不能修改。')
    category = _category(c, data.get('category_id'))
    note = _note(data.get('note'))
    day = __import__('payroll').day_value(data.get('cost_date'), '请选择日期。').isoformat()
    amount = accounting.money(data.get('amount'))
    auditlog.begin(c)
    c.execute('''UPDATE cost_entries SET cost_date=?, label=?, amount_cents=?, note=?, category_id=? WHERE id=?''',
        (day, category['name'], amount, note, category['id'], row['id']))
    _log(c, user, f"修改成本：{category['name']} {_aud(amount)}")
    return {'ok': True}


def void_entry(c, user, data):
    require_owner(user)
    materialize(c)
    row = c.execute('SELECT * FROM cost_entries WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not row:
        raise ValueError('找不到这条成本。')
    if row['voided']:
        raise ValueError('这条成本已经作废。')
    auditlog.begin(c)
    c.execute('UPDATE cost_entries SET voided=1 WHERE id=?', (row['id'],))
    extra = f" {row['note']}" if row['note'] else ''
    _log(c, user, f"作废成本：{row['label']}{extra} {_aud(row['amount_cents'])}")
    return {'ok': True}


def add_category(c, user, data):
    require_owner(user)
    name = _name(data.get('name'), '类别名称不能为空，且不能超过 40 个字。', 40)
    if c.execute('SELECT 1 FROM expense_categories WHERE name=?', (name,)).fetchone():
        raise ValueError('这个类别已经有了。')
    auditlog.begin(c)
    c.execute('INSERT INTO expense_categories(name, builtin) VALUES(?,0)', (name,))
    _log(c, user, f'新增成本类别：{name}')
    return {'ok': True}


def _month_fields(data):
    name = _name(data.get('name'), '名称不能为空，且不能超过 80 个字。', 80)
    try:
        day = int(str(data.get('day_of_month') or '').strip())
    except ValueError:
        day = 0
    if not 1 <= day <= 31:
        raise ValueError('请填写每月几号，1 到 31。')
    start_year, start_month = _parse_month(data.get('start_month'), '请选择开始月份。')
    start = _month_key(start_year, start_month)
    end_raw = str(data.get('end_month') or '').strip()
    end = None
    if end_raw:
        end_year, end_month = _parse_month(end_raw, '结束月份无效。')
        end = _month_key(end_year, end_month)
        if end < start:
            raise ValueError('结束月份不能早于开始月份。')
    return name, day, start, end


def add_monthly(c, user, data):
    require_owner(user)
    materialize(c)
    category = _category(c, data.get('category_id'))
    name, day, start, end = _month_fields(data)
    amount = accounting.money(data.get('amount'))
    auditlog.begin(c)
    new_id = c.execute('''INSERT INTO monthly_costs(name,category_id,amount_cents,day_of_month,start_month,end_month,active,shared,created_by)
        VALUES(?,?,?,?,?,?,1,1,?)''', (name, category['id'], amount, day, start, end, user['id'])).lastrowid
    materialize(c, only_id=new_id)
    _log(c, user, f'新增每月固定成本：{name} {_aud(amount)}')
    return {'ok': True}


def edit_monthly(c, user, data):
    require_owner(user)
    materialize(c)
    row = c.execute('SELECT * FROM monthly_costs WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not row:
        raise ValueError('找不到这项每月固定成本。')
    category = _category(c, data.get('category_id'))
    name, day, start, end = _month_fields(data)
    amount = accounting.money(data.get('amount'))
    auditlog.begin(c)
    c.execute('''UPDATE monthly_costs SET name=?, category_id=?, amount_cents=?, day_of_month=?, start_month=?, end_month=?, active=1
        WHERE id=?''', (name, category['id'], amount, day, start, end, row['id']))
    materialize(c, only_id=row['id'])
    _log(c, user, f'修改每月固定成本：{name} {_aud(amount)}')
    return {'ok': True}


def stop_monthly(c, user, data):
    require_owner(user)
    materialize(c)
    row = c.execute('SELECT * FROM monthly_costs WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not row:
        raise ValueError('找不到这项每月固定成本。')
    if not row['active']:
        raise ValueError('这项每月固定成本已经停止。')
    today_key = _month_key(now_local().year, now_local().month)
    end = row['end_month']
    if not end or end > today_key:
        end = today_key
    auditlog.begin(c)
    c.execute('UPDATE monthly_costs SET active=0, end_month=? WHERE id=?', (end, row['id']))
    _log(c, user, f"停止每月固定成本：{row['name']}")
    return {'ok': True}


def _month_bounds(month):
    if not str(month or '').strip():
        today = now_local().date()
        year, mon = today.year, today.month
    else:
        year, mon = _parse_month(month, '请选择月份。')
    start = dt.date(year, mon, 1)
    end = dt.date(year, mon, calendar.monthrange(year, mon)[1])
    return _month_key(year, mon), start, end


def page(c, user, month):
    require_owner(user)
    schema(c)
    key, start, end = _month_bounds(month)
    materialize(c)
    categories = [dict(row) for row in c.execute('SELECT id, name, builtin FROM expense_categories ORDER BY builtin DESC, id')]
    entries = []
    buckets = {}
    total = 0
    for row in c.execute('''SELECT e.*, cat.name category_name
            FROM cost_entries e LEFT JOIN expense_categories cat ON cat.id=e.category_id
            WHERE e.cost_date>=? AND e.cost_date<=? ORDER BY e.cost_date, e.id''', (start.isoformat(), end.isoformat())):
        item = dict(row)
        item['category_name'] = item.get('category_name') or item['label']
        entries.append(item)
        if item['voided']:
            continue
        label = item['category_name'] or '未分类'
        buckets[label] = buckets.get(label, 0) + item['amount_cents']
        total += item['amount_cents']
    monthly = []
    for row in c.execute('''SELECT m.*, cat.name category_name FROM monthly_costs m
            LEFT JOIN expense_categories cat ON cat.id=m.category_id ORDER BY m.active DESC, m.id'''):
        monthly.append(dict(row))
    by_category = [{'name': name, 'amount_cents': amount} for name, amount in sorted(buckets.items(), key=lambda item: (-item[1], item[0]))]
    return {'month': key, 'categories': categories, 'entries': entries, 'monthly': monthly,
        'by_category': by_category, 'total_cents': total}


def handle_post(c, user, path, data):
    if path == '/api/expenses':
        return add_entry(c, user, data)
    if path == '/api/expenses/edit':
        return edit_entry(c, user, data)
    if path == '/api/expenses/void':
        return void_entry(c, user, data)
    if path == '/api/expenses/categories':
        return add_category(c, user, data)
    if path == '/api/expenses/monthly':
        return add_monthly(c, user, data)
    if path == '/api/expenses/monthly/edit':
        return edit_monthly(c, user, data)
    if path == '/api/expenses/monthly/stop':
        return stop_monthly(c, user, data)
    raise ValueError('接口不存在。')
