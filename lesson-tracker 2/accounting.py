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
    else:raise ValueError('请选择日、周或月。')
    return start,end

def blank_totals():
    return {'credit_units':0,'lesson_units':0,'refund_units':0,'reversed_credit_units':0,'returned_lesson_units':0,'returned_refund_units':0,'net_units':0,'count':0,'receipts_cents':0,'refunds_cents':0,'corrections_cents':0,'net_cash_cents':0,'missing_cash_count':0}

def add_row(t,row):
    t['count']+=1;t['net_units']+=row['delta']
    if row['kind']=='credit':t['credit_units']+=row['delta']
    elif row['kind']=='lesson':t['lesson_units']-=row['delta']
    elif row['kind']=='refund':t['refund_units']-=row['delta']
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
    rows=[dict(r) for r in c.execute('''SELECT l.*,s.name student_name,s.course,u.name actor_name,
        original.kind original_kind, original.lesson_date original_date,original.id original_id,
        reversal.id reversed_by,cash.cash_delta,cash.payment_method,cash.reference FROM ledger l JOIN students s ON l.student_id=s.id
        JOIN users u ON l.actor_id=u.id LEFT JOIN ledger original ON l.reversal_of=original.id
        LEFT JOIN ledger reversal ON reversal.reversal_of=l.id
        LEFT JOIN cash_entries cash ON cash.ledger_id=l.id
        WHERE l.lesson_date>=? AND l.lesson_date<=? ORDER BY l.lesson_date DESC,l.id DESC''',(start.isoformat(),end.isoformat()))]
    totals=blank_totals();daily={}
    day_value=start
    while day_value<=end:
        daily[day_value.isoformat()]={'date':day_value.isoformat(),**blank_totals()}
        day_value+=dt.timedelta(days=1)
    for row in rows:
        add_row(totals,row);add_row(daily[row['lesson_date']],row)
    opening=c.execute('SELECT COALESCE(SUM(delta),0) FROM ledger WHERE lesson_date<?',(start.isoformat(),)).fetchone()[0]
    mismatches=c.execute('SELECT COUNT(*) FROM students s WHERE s.balance!=COALESCE((SELECT SUM(l.delta) FROM ledger l WHERE l.student_id=s.id),0)').fetchone()[0]
    return {'period':period,'start':start.isoformat(),'end':end.isoformat(),'timezone':TIMEZONE,
        'opening_units':opening,'closing_units':opening+totals['net_units'],
        'totals':totals,'daily':list(daily.values()),'rows':rows,'balance_check':mismatches==0,
        'generated_at':now_local().isoformat(timespec='seconds')}

def money(raw):
    try:
        value=Decimal(str(raw))
        if not value.is_finite() or value<0 or value>1000000 or value*100!=(value*100).to_integral_value():
            raise ValueError()
        return int(value*100)
    except (InvalidOperation,ValueError):
        raise ValueError('请输入有效的澳元金额，最多两位小数，且不超过 1,000,000。')

def cash_details(data):
    cents=money(data.get('cash_amount'))
    method=str(data.get('payment_method','')).strip()
    reference=str(data.get('reference','')).strip()
    if method not in ('bank','cash','card','other','gift'):
        raise ValueError('请选择收付款方式。')
    if len(reference)>100:
        raise ValueError('凭证号或转账备注最多 100 个字。')
    return cents,method,reference

def record_cash(c,ledger_id,cents,method,reference,actor):
    c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,?)',(ledger_id,cents,method,reference,actor))

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
