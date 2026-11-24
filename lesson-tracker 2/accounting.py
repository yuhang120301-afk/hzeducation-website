"""Owner permissions and business-date lesson reconciliation."""
import calendar
import datetime as dt
from decimal import Decimal, InvalidOperation
from teaching import AccessError, now_local, TIMEZONE

def schema(c,demo=False):
    columns={r['name'] for r in c.execute('PRAGMA table_info(users)')}
    if 'active' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
    c.execute('CREATE TABLE IF NOT EXISTS organization_owners(user_id INTEGER PRIMARY KEY REFERENCES users(id))')
    c.execute('''CREATE TABLE IF NOT EXISTS cash_entries (
        ledger_id INTEGER PRIMARY KEY REFERENCES ledger(id),
        cash_delta INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'AUD' CHECK(currency='AUD'),
        payment_method TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '',
        recorded_by INTEGER NOT NULL REFERENCES users(id),
        recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS payment_methods (
        code TEXT PRIMARY KEY, label TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0,
        system INTEGER NOT NULL DEFAULT 0
    )''')
    cash_cols={r['name'] for r in c.execute('PRAGMA table_info(cash_entries)')}
    if 'received_by' not in cash_cols:
        c.execute('ALTER TABLE cash_entries ADD COLUMN received_by INTEGER REFERENCES users(id)')
    if 'handed_over' not in cash_cols:
        c.execute('ALTER TABLE cash_entries ADD COLUMN handed_over INTEGER NOT NULL DEFAULT 1')
    if 'handed_over_on' not in cash_cols:
        c.execute('ALTER TABLE cash_entries ADD COLUMN handed_over_on TEXT')
    for code,label,active,sort_order,system in (
        ('bank','银行转账',1,10,1),('card','刷卡',1,20,1),('alipay','支付宝',1,30,0),
        ('wechat','微信',1,40,0),('cash','现金',1,50,1),('gift','赠课 / 无收款',1,90,1)):
        c.execute('INSERT OR IGNORE INTO payment_methods(code,label,active,sort_order,system) VALUES(?,?,?,?,?)',(code,label,active,sort_order,system))
    if demo:
        c.execute("INSERT OR IGNORE INTO organization_owners SELECT id FROM users WHERE phone='0400000000' AND role='admin'")

def require_owner(user):
    if user['role']!='owner':
        raise AccessError('此功能仅限老板账号。')

def administrators(c,user):
    require_owner(user)
    return [dict(r) for r in c.execute("SELECT u.id,u.name,u.phone,u.active FROM users u LEFT JOIN organization_owners o ON o.user_id=u.id WHERE u.role='admin' AND o.user_id IS NULL ORDER BY u.id")]

def add_administrator(c,user,data,phone_value,password_hash,text_value):
    require_owner(user)
    name=text_value(data.get('name'),'管理员姓名',40)
    phone=phone_value(data.get('phone'))
    password=str(data.get('password',''))
    if not 10<=len(password)<=128:
        raise ValueError('初始密码需为 10–128 位。')
    if c.execute('SELECT 1 FROM users WHERE phone=?',(phone,)).fetchone():
        raise ValueError('该手机号已有账号，请使用独立的管理员手机号。')
    uid=c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",(phone,name,password_hash(password))).lastrowid
    c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)',(uid,'数学'))
    return {'ok':True,'admin_id':uid}

def set_active(c,user,data):
    require_owner(user)
    uid=int(data.get('admin_id',0))
    admin=c.execute("SELECT u.id FROM users u LEFT JOIN organization_owners o ON o.user_id=u.id WHERE u.id=? AND u.role='admin' AND o.user_id IS NULL",(uid,)).fetchone()
    if not admin:
        raise ValueError('请选择有效的管理员，老板账号不能在这里停用。')
    active=data.get('active')
    if type(active) is not bool:
        raise ValueError('账号状态无效。')
    c.execute('UPDATE users SET active=? WHERE id=?',(int(active),uid))
    c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
    return {'ok':True}

def bounds(period,day):
    day=dt.date.fromisoformat(day)
    if period=='day':start=end=day
    elif period=='week':
        start=day-dt.timedelta(days=day.weekday());end=start+dt.timedelta(days=6)
    elif period=='month':
        start=day.replace(day=1);end=day.replace(day=calendar.monthrange(day.year,day.month)[1])
    elif period=='fortnight':
        monday=day-dt.timedelta(days=day.weekday())
        anchor=dt.date(2024,1,1)
        if ((monday-anchor).days//7)%2:
            monday-=dt.timedelta(days=7)
        start,end=monday,monday+dt.timedelta(days=13)
    else:raise ValueError('请选择日、周、双周或月。')
    return start,end

def blank_totals():
    return {'gift_void_units':0,'paid_credit_units':0,'gift_credit_units':0,'credit_units':0,'lesson_units':0,'refund_units':0,'reversed_credit_units':0,'returned_lesson_units':0,'returned_refund_units':0,'net_units':0,'count':0,'receipts_cents':0,'refunds_cents':0,'corrections_cents':0,'net_cash_cents':0,'missing_cash_count':0}

def add_row(t,row):
    t['count']+=1;t['net_units']+=row['delta']
    if row['kind']=='credit':
        t['credit_units']+=row['delta']
        t['paid_credit_units']+=row['paid_delta'] if row['split_known'] else row['delta']
        t['gift_credit_units']+=row['gift_delta'] if row['split_known'] else 0
    elif row['kind']=='lesson':t['lesson_units']-=row['delta']
    elif row['kind']=='refund':
        t['refund_units']-=row['paid_delta'] if row['split_known'] else row['delta']
        t['gift_void_units']+=row['gift_void']
    elif row['original_kind']=='credit':t['reversed_credit_units']-=row['delta']
    elif row['original_kind']=='lesson':t['returned_lesson_units']+=row['delta']
    elif row['original_kind']=='refund':t['returned_refund_units']+=row['delta']
    if row['cash_delta'] is not None:
        t['net_cash_cents']+=row['cash_delta']
        if row['kind']=='credit':t['receipts_cents']+=row['cash_delta']
        elif row['kind']=='refund':t['refunds_cents']-=row['cash_delta']
        else:t['corrections_cents']+=row['cash_delta']
    elif row['kind'] in ('credit','refund') or row['original_kind'] in ('credit','refund'):
        t['missing_cash_count']+=1

def reconciliation(c,user,period,day):
    require_owner(user)
    start,end=bounds(period,day)
    rows=[dict(r) for r in c.execute('''SELECT l.*,s.name student_name,s.course,s.billing_unit,u.name actor_name,
        original.kind original_kind, original.lesson_date original_date,original.id original_id,
        reversal.id reversed_by,cash.cash_delta,cash.payment_method,cash.reference,cash.handed_over,cash.received_by,
        recv.name receiver_name, l.created_at recorded_at FROM ledger l JOIN students s ON l.student_id=s.id
        JOIN users u ON l.actor_id=u.id LEFT JOIN ledger original ON l.reversal_of=original.id
        LEFT JOIN ledger reversal ON reversal.reversal_of=l.id
        LEFT JOIN cash_entries cash ON cash.ledger_id=l.id
        LEFT JOIN users recv ON recv.id=cash.received_by
        WHERE l.lesson_date>=? AND l.lesson_date<=? ORDER BY l.lesson_date DESC,l.id DESC''',(start.isoformat(),end.isoformat()))]
    totals=blank_totals();daily={}
    day_value=start
    while day_value<=end:
        daily[day_value.isoformat()]={'date':day_value.isoformat(),**blank_totals()}
        day_value+=dt.timedelta(days=1)
    for row in rows:
        add_row(totals,row);add_row(daily[row['lesson_date']],row)
    by_unit={u:blank_totals() for u in ('lesson','hour')}
    for d in daily.values():d['by_unit']={u:blank_totals() for u in ('lesson','hour')}
    for row in rows:
        unit=row['billing_unit'];add_row(by_unit[unit],row);add_row(daily[row['lesson_date']]['by_unit'][unit],row)
    totals['by_unit']=by_unit
    cash=cash_breakdown(c,start,end)
    unit_balances=[]
    for unit in ('lesson','hour'):
        opening_unit=c.execute('SELECT COALESCE(SUM(l.delta),0) FROM ledger l JOIN students s ON s.id=l.student_id WHERE l.lesson_date<? AND s.billing_unit=?',(start.isoformat(),unit)).fetchone()[0]
        unit_balances.append({'unit':unit,'opening':opening_unit,'closing':opening_unit+by_unit[unit]['net_units'],'totals':by_unit[unit]})
    opening=c.execute('SELECT COALESCE(SUM(delta),0) FROM ledger WHERE lesson_date<?',(start.isoformat(),)).fetchone()[0]
    mismatches=c.execute('SELECT COUNT(*) FROM students s WHERE s.balance!=COALESCE((SELECT SUM(l.delta) FROM ledger l WHERE l.student_id=s.id),0)').fetchone()[0]
    return {'period':period,'start':start.isoformat(),'end':end.isoformat(),'timezone':TIMEZONE,
        'unit_balances':unit_balances,'opening_units':opening,'closing_units':opening+totals['net_units'],
        'totals':totals,'daily':list(daily.values()),'rows':rows,'balance_check':mismatches==0,
        'by_method':cash['by_method'],'by_receiver':cash['by_receiver'],'unhanded':cash['unhanded'],
        'arrears': __import__('finance').arrears_rows(c),
        'generated_at':now_local().isoformat(timespec='seconds')}

def money(raw):
    try:
        value=Decimal(str(raw))
        if not value.is_finite() or value<0 or value>1000000 or value*100!=(value*100).to_integral_value():
            raise ValueError()
        return int(value*100)
    except (InvalidOperation,ValueError):
        raise ValueError('请输入有效的澳元金额，最多两位小数，且不超过 1,000,000。')

def cash_details(data, c=None):
    cents=money(data.get('cash_amount'))
    method=str(data.get('payment_method','')).strip()
    reference=str(data.get('reference','')).strip()
    legacy=('bank','cash','card','other','gift')
    if c is not None:
        row=c.execute('SELECT active FROM payment_methods WHERE code=?',(method,)).fetchone()
        if row is None and method not in legacy:
            raise ValueError('请选择收付款方式。')
        if row is not None and not row['active'] and method!='gift':
            raise ValueError('这种收款方式已停用。')
    elif method not in legacy:
        raise ValueError('请选择收付款方式。')
    if len(reference)>100:
        raise ValueError('凭证号或转账备注最多 100 个字。')
    return cents,method,reference

def record_cash(c,ledger_id,cents,method,reference,actor,received_by=None,handed_over=None,handed_over_on=None):
    if received_by is None:
        received_by=actor
    if handed_over is None:
        handed_over=1
    c.execute('''INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by,received_by,handed_over,handed_over_on)
        VALUES(?,?,?,?,?,?,?,?)''',(ledger_id,cents,method,reference,actor,received_by,int(bool(handed_over)),handed_over_on or None))

def is_owner_user(c, uid):
    return c.execute('SELECT 1 FROM organization_owners WHERE user_id=?',(uid,)).fetchone() is not None

def resolve_receiver(c, raw, actor):
    if raw in (None,'',0,'0'):
        return actor['id']
    uid=int(raw)
    row=c.execute('''SELECT u.id FROM users u
        LEFT JOIN teachers t ON t.user_id=u.id
        LEFT JOIN organization_owners o ON o.user_id=u.id
        WHERE u.id=? AND u.active=1 AND (u.role='admin' OR t.id IS NOT NULL OR o.user_id IS NOT NULL)''',(uid,)).fetchone()
    if not row:
        raise ValueError('请选择收款人。')
    return uid

def receipt_meta(c, user, data, when):
    received=resolve_receiver(c, data.get('received_by'), user)
    if 'handed_over' in data and data.get('handed_over') not in (None,''):
        handed=data.get('handed_over') in (True,1,'1','true','on','yes')
    else:
        handed=is_owner_user(c, received)
    return {'received_by':received,'handed_over':1 if handed else 0,'handed_over_on':when if handed else None}

def method_label(c, code):
    row=c.execute('SELECT label FROM payment_methods WHERE code=?',(code,)).fetchone()
    return row['label'] if row else (code or '')

def cash_breakdown(c, start, end):
    rows=c.execute('''SELECT cash.*, u.name receiver_name, l.lesson_date, l.kind, l.student_id, s.name student_name, s.course
        FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id
        LEFT JOIN users u ON u.id=cash.received_by
        LEFT JOIN students s ON s.id=l.student_id
        WHERE l.lesson_date>=? AND l.lesson_date<=?
          AND NOT EXISTS (SELECT 1 FROM ledger rev WHERE rev.reversal_of=l.id)''',(start.isoformat(),end.isoformat())).fetchall()
    by_method, by_receiver = {}, {}
    received=refunded=0
    for row in rows:
        if row['cash_delta']>0:
            received+=row['cash_delta']
        elif row['cash_delta']<0:
            refunded-=row['cash_delta']
        if row['cash_delta']<=0:
            continue
        bucket=by_method.setdefault(row['payment_method'], {'code':row['payment_method'],'label':method_label(c,row['payment_method']),'cents':0})
        bucket['cents']+=row['cash_delta']
        key=row['received_by'] or 0
        person=by_receiver.setdefault(key, {'user_id':row['received_by'],'name':row['receiver_name'] or '未填写','cents':0,'unhanded_cents':0})
        person['cents']+=row['cash_delta']
        if not row['handed_over']:
            person['unhanded_cents']+=row['cash_delta']
    outstanding=[dict(r) for r in c.execute('''SELECT cash.ledger_id, cash.cash_delta, cash.payment_method, cash.reference,
        cash.received_by, u.name receiver_name, l.lesson_date, s.name student_name, s.course
        FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id
        LEFT JOIN users u ON u.id=cash.received_by LEFT JOIN students s ON s.id=l.student_id
        WHERE cash.handed_over=0 AND cash.cash_delta>0
          AND NOT EXISTS (SELECT 1 FROM ledger rev WHERE rev.reversal_of=l.id)
        ORDER BY l.lesson_date, cash.ledger_id''')]
    for item in outstanding:
        item['method_label']=method_label(c, item['payment_method'])
    return {'received_cents':received,'refunded_cents':refunded,'by_method':list(by_method.values()),
        'by_receiver':list(by_receiver.values()),'unhanded':outstanding}

def payment_method_list(c):
    return [dict(r) for r in c.execute('SELECT * FROM payment_methods ORDER BY sort_order, code')]

def save_payment_method(c, user, data):
    require_owner(user)
    code=str(data.get('code') or '').strip().lower()
    label=str(data.get('label') or '').strip()
    if not code or not __import__('re').fullmatch(r'[a-z0-9_-]{1,20}', code):
        raise ValueError('方式代码只能用小写英文、数字、下划线或短横线。')
    if not label or len(label)>40:
        raise ValueError('方式名称不能为空，且不能超过 40 个字。')
    if code=='gift' and data.get('active') is False:
        raise ValueError('赠课方式要留着，纯赠课才有地方记。')
    active=1 if data.get('active', True) else 0
    existing=c.execute('SELECT * FROM payment_methods WHERE code=?',(code,)).fetchone()
    if existing:
        c.execute('UPDATE payment_methods SET label=?, active=? WHERE code=?',(label, active, code))
    else:
        sort=c.execute('SELECT COALESCE(MAX(sort_order),0)+10 FROM payment_methods').fetchone()[0]
        c.execute('INSERT INTO payment_methods(code,label,active,sort_order,system) VALUES(?,?,?,?,0)',(code,label,active,sort))
    return {'ok':True}

def mark_handover(c, user, data):
    require_owner(user)
    raw=data.get('ledger_ids')
    if not isinstance(raw, list) or not raw:
        raise ValueError('请选择要上交的收款。')
    ids=[int(x) for x in raw]
    handed=data.get('handed_over')
    if type(handed) is not bool:
        raise ValueError('请选择已上交或取消上交。')
    when=str(data.get('date') or now_local().date().isoformat())
    dt.date.fromisoformat(when)
    marks=','.join('?' for _ in ids)
    found=c.execute(f'SELECT COUNT(*) FROM cash_entries WHERE ledger_id IN ({marks})', ids).fetchone()[0]
    if found!=len(set(ids)):
        raise ValueError('有收款记录不存在。')
    c.execute(f'UPDATE cash_entries SET handed_over=?, handed_over_on=? WHERE ledger_id IN ({marks})',
        [int(handed), when if handed else None, *ids])
    return {'ok':True}

def supplement_cash(c,user,data):
    require_owner(user)
    entry=c.execute("SELECT * FROM ledger WHERE id=? AND kind IN ('credit','refund')",(int(data.get('entry_id',0)),)).fetchone()
    if not entry:raise ValueError('只能补录充值或退款记录的金额。')
    if c.execute('SELECT 1 FROM cash_entries WHERE ledger_id=?',(entry['id'],)).fetchone():
        raise ValueError('这笔记录已经登记金额，不能重复补录。')
    cents,method,reference=cash_details(data)
    if entry['kind']=='refund':cents=-cents
    record_cash(c,entry['id'],cents,method,reference,user['id'])
    reversed_entry=c.execute('SELECT id FROM ledger WHERE reversal_of=?',(entry['id'],)).fetchone()
    if reversed_entry:
        record_cash(c,reversed_entry['id'],-cents,method,'原记录补录后同步纠错',user['id'])
    return {'ok':True}


def edit_administrator(c,user,data,phone_value,password_hash,text_value):
    require_owner(user)
    uid=int(data.get('admin_id',0))
    admin=c.execute("SELECT u.* FROM users u LEFT JOIN organization_owners o ON o.user_id=u.id WHERE u.id=? AND u.role='admin' AND o.user_id IS NULL",(uid,)).fetchone()
    if not admin:
        raise ValueError('请选择有效的管理员。')
    name=text_value(data.get('name'),'管理员姓名',40)
    phone=phone_value(data.get('phone'))
    password=str(data.get('password',''))
    if password and not 10<=len(password)<=128:
        raise ValueError('新密码需为 10–128 位。')
    if c.execute('SELECT 1 FROM users WHERE phone=? AND id!=?',(phone,uid)).fetchone():
        raise ValueError('该手机号已有账号，请使用独立的管理员手机号。')
    c.execute('UPDATE users SET name=?,phone=? WHERE id=?',(name,phone,uid))
    if password:
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),uid))
    if password or phone!=admin['phone']:
        c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
    return {'ok':True}
