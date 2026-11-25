"""Teacher pay. Bosses see everyone. A teacher sees only their own pay.

A confirmed lesson is worth the package price divided by the paid lessons in
that package. Gift lessons are worth nothing. Helen can type over that number.
Vincent's teaching pay (his own percentage) is separate from his share of what
is left after shared costs are taken out of new students' fees.

An absence is not taught time. absence_pay_clause is the only place that
decides whether one is paid. Charging the student's balance does not pay
the teacher.
"""
import calendar
import csv
import datetime as dt
import io
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import accounting
from teaching import SINGAPORE_SUBJECT, AccessError, now_local

SEED_KEY = 'pay_seed_v1'
HELEN_PAY_KEY = 'helen_pay_40_v1'
# Name fragment, rule type, percent in basis points, hourly floor cents or None.
SEED_RULES = (
    ('helen', 'percent', 4000, None),
    ('angela', 'percent', 4000, 3500),
    ('kelsey', 'percent', 4000, None),
    ('ethan', 'percent', 4000, None),
    ('christina', 'percent', 4000, None),
    ('vincent', 'percent', 4000, None),
)


def schema(c):
    cols = {r['name'] for r in c.execute('PRAGMA table_info(students)')}
    if 'helen_original' not in cols:
        c.execute('ALTER TABLE students ADD COLUMN helen_original INTEGER NOT NULL DEFAULT 0')
    report_cols = {r['name'] for r in c.execute('PRAGMA table_info(lesson_reports)')}
    if 'fee_cents' not in report_cols:
        c.execute('ALTER TABLE lesson_reports ADD COLUMN fee_cents INTEGER')
    if 'fee_overridden' not in report_cols:
        c.execute('ALTER TABLE lesson_reports ADD COLUMN fee_overridden INTEGER NOT NULL DEFAULT 0')
    if 'fee_millis' not in report_cols:
        c.execute('ALTER TABLE lesson_reports ADD COLUMN fee_millis INTEGER')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS pay_rules (
        id INTEGER PRIMARY KEY,
        teacher_id INTEGER NOT NULL REFERENCES teachers(id),
        rule_type TEXT NOT NULL CHECK(rule_type IN ('percent','hourly')),
        percent_bp INTEGER,
        hourly_floor_cents INTEGER,
        hourly_rate_cents INTEGER,
        effective_from TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX IF NOT EXISTS pay_rules_lookup ON pay_rules(teacher_id, effective_from);
    CREATE TABLE IF NOT EXISTS partner_share_rules (
        id INTEGER PRIMARY KEY,
        teacher_id INTEGER REFERENCES teachers(id),
        percent_bp INTEGER NOT NULL,
        effective_from TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE IF NOT EXISTS cost_schedules (
        id INTEGER PRIMARY KEY,
        label TEXT NOT NULL,
        amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
        cadence TEXT NOT NULL CHECK(cadence IN ('day','week','month')),
        effective_from TEXT NOT NULL,
        effective_to TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        shared INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE IF NOT EXISTS cost_entries (
        id INTEGER PRIMARY KEY,
        cost_date TEXT NOT NULL,
        label TEXT NOT NULL,
        amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
        note TEXT NOT NULL DEFAULT '',
        voided INTEGER NOT NULL DEFAULT 0,
        shared INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    ''')
    for table in ('cost_entries', 'cost_schedules'):
        if 'shared' not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}:
            c.execute(f'ALTER TABLE {table} ADD COLUMN shared INTEGER NOT NULL DEFAULT 0')
    seed_if_needed(c)
    apply_helen_percent(c)
    import expenses
    expenses.schema(c)


def seed_if_needed(c):
    if c.execute('SELECT 1 FROM app_meta WHERE key=?', (SEED_KEY,)).fetchone():
        return
    actor = c.execute('SELECT user_id FROM organization_owners ORDER BY user_id LIMIT 1').fetchone()
    actor_id = actor['user_id'] if actor else (c.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone() or {'id': None})['id']
    teachers = [dict(r) for r in c.execute('SELECT t.id, u.name FROM teachers t JOIN users u ON u.id=t.user_id ORDER BY t.id')]
    if actor_id and teachers:
        vincent = None
        for teacher in teachers:
            folded = teacher['name'].casefold()
            for fragment, kind, bp, floor in SEED_RULES:
                if fragment in folded:
                    c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,note,created_by)
                        VALUES(?,?,?,?,?,?,?,?)''', (teacher['id'], kind, bp, floor, None, '2000-01-01', '初始规则', actor_id))
                    if fragment == 'vincent' and vincent is None:
                        vincent = teacher['id']
        if vincent is not None:
            c.execute('''INSERT INTO partner_share_rules(teacher_id,percent_bp,effective_from,note,created_by)
                VALUES(?,?,?,?,?)''', (vincent, 3000, '2000-01-01', '新学生课酬减去共同成本后的分成', actor_id))
    c.execute('INSERT INTO app_meta(key,value) VALUES(?,?)', (SEED_KEY, '1'))


def apply_helen_percent(c):
    """One-time: Helen's existing 0% rule becomes 40%. A later edit is left alone."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'").fetchone():
        return
    if c.execute('SELECT 1 FROM app_meta WHERE key=?', (HELEN_PAY_KEY,)).fetchone():
        return
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pay_rules'").fetchone():
        rows = c.execute('''SELECT r.id FROM pay_rules r
            JOIN teachers t ON t.id=r.teacher_id
            JOIN users u ON u.id=t.user_id
            WHERE r.rule_type='percent' AND IFNULL(r.percent_bp, 0)=0
              AND instr(lower(u.name), 'helen')>0''').fetchall()
        for row in rows:
            c.execute('UPDATE pay_rules SET percent_bp=4000 WHERE id=?', (row['id'],))
    c.execute('INSERT INTO app_meta(key,value) VALUES(?,?)', (HELEN_PAY_KEY, '1'))


def require_owner(user):
    accounting.require_owner(user)


def percent_bp(raw):
    try:
        value = Decimal(str(raw).strip().rstrip('%'))
        if not value.is_finite() or value < 0 or value > 100:
            raise ValueError()
        scaled = (value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        if scaled != value * 100:
            raise ValueError()
        return int(scaled)
    except (InvalidOperation, ValueError):
        raise ValueError('比例需在 0 到 100 之间，最多两位小数。')


def optional_money(raw):
    if raw is None or str(raw).strip() == '':
        return None
    cents = accounting.money(raw)
    return cents or None


def day_value(raw, label):
    try:
        return dt.date.fromisoformat(str(raw))
    except ValueError:
        raise ValueError(label)


def period_bounds(period, day, start, end):
    if period == 'custom':
        start, end = day_value(start, '请选择开始日期。'), day_value(end, '请选择结束日期。')
        if end < start:
            raise ValueError('结束日期不能早于开始日期。')
        if (end - start).days > 366:
            raise ValueError('一次最多查询 366 天。')
        return start, end
    return accounting.bounds(period, day or now_local().date().isoformat())


def rule_on(rules, day):
    chosen = None
    for rule in rules:
        if rule['effective_from'] <= day and (chosen is None or rule['effective_from'] >= chosen['effective_from']):
            chosen = rule
    return chosen


def minutes_between(starts, ends):
    start = dt.datetime.fromisoformat(starts)
    end = dt.datetime.fromisoformat(ends)
    return max(0, int((end - start).total_seconds() // 60))


def mul_div(value, numerator, denominator):
    if denominator <= 0:
        return 0
    return (value * numerator + denominator // 2) // denominator


def indexed_fee_millis(c, ledger_id):
    """Per-lesson price stored on the package. Gift lessons are included and still paid to the teacher."""
    import json
    moves = c.execute('''SELECT m.paid, m.gift, m.batch_id, b.unit_fees
        FROM credit_movements m JOIN credit_batches b ON b.id=m.batch_id
        WHERE m.ledger_id=?''', (ledger_id,)).fetchall()
    total = 0
    used = False
    for move in moves:
        raw = move['unit_fees'] if 'unit_fees' in move.keys() else ''
        if not raw:
            continue
        try:
            fees = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not fees:
            continue
        before = c.execute('''SELECT COALESCE(SUM(-paid - gift),0) FROM credit_movements
            WHERE batch_id=? AND ledger_id<? AND (paid<0 OR gift<0)''', (move['batch_id'], ledger_id)).fetchone()[0]
        index = int(before) // 100
        taken = ((-move['paid'] if move['paid'] < 0 else 0) + (-move['gift'] if move['gift'] < 0 else 0)) // 100
        if taken <= 0:
            continue
        used = True
        for step in range(taken):
            slot = index + step
            if 0 <= slot < len(fees):
                total += int(fees[slot])
    return total if used else None


def fee_for_ledger(c, ledger_id, amount):
    """Return (fee cents or None if the price is unknown, paid units, gift units)."""
    indexed = indexed_fee_millis(c, ledger_id)
    moves = c.execute('''SELECT m.paid, m.gift, b.purchased, b.gifted, cash.cash_delta
        FROM credit_movements m JOIN credit_batches b ON b.id=m.batch_id
        LEFT JOIN cash_entries cash ON cash.ledger_id=b.ledger_id
        WHERE m.ledger_id=?''', (ledger_id,)).fetchall()
    if not moves:
        return (None, 0, 0) if amount else (0, 0, 0)
    fee = 0
    known = True
    paid_units = gift_units = 0
    for move in moves:
        paid = -move['paid'] if move['paid'] < 0 else 0
        gift = -move['gift'] if move['gift'] < 0 else 0
        paid_units += paid
        gift_units += gift
        taken = paid + gift
        if taken <= 0:
            continue
        pool = (move['purchased'] or 0) + (move['gifted'] or 0)
        cash = move['cash_delta']
        # A paid package splits its cash across paid and gift lessons. A pure gift, with no cash, stays 0.
        if cash is None or pool <= 0:
            if (move['purchased'] or 0) <= 0 and (move['gifted'] or 0) > 0 and cash is None:
                continue
            known = False
            continue
        fee += mul_div(taken, cash, pool)
    if indexed is not None:
        return (indexed + 5) // 10, paid_units, gift_units
    return (fee if known else None), paid_units, gift_units


def lesson_pay(rule, minutes, known_fee_cents):
    """Percent uses the known fee total. An hourly floor can raise that amount."""
    if not rule:
        return 0, 'missing-rule'
    if rule['rule_type'] == 'hourly':
        return mul_div(rule['hourly_rate_cents'] or 0, minutes, 60), 'hourly'
    percent = mul_div(known_fee_cents, rule['percent_bp'] or 0, 10000)
    floor = mul_div(rule['hourly_floor_cents'], minutes, 60) if rule['hourly_floor_cents'] else 0
    if floor > percent:
        return floor, 'floor'
    return percent, 'percent'


def student_is_new(helen_original):
    """Unticked students are new. Only a boss-set flag marks Helen's original list."""
    return not helen_original


def absence_pay_clause():
    """SQL AND-fragment for teacher pay. This is the only pay decision for 请假.

    Absences are not taught hours and are not paid, whether or not the
    student's balance was charged. Pay rules that pay an attended lesson do
    not apply to an absence. To pay a charged absence the same way as an
    attended lesson, return:
        " AND (COALESCE(l.absent,0)=0 OR COALESCE(l.absent_charge,0)=1)"
    Uncharged absences stay unpaid with that change too, unless the fragment
    is widened further. A charged absence has no lesson report, so it still
    produces no pay line until this query is also given one.
    """
    return ' AND COALESCE(l.absent, 0)=0'


def confirmed_rows(c, start, end):
    return c.execute('''SELECT l.id lesson_id, l.teacher_id, l.title, l.starts_at, l.ends_at, l.course_type_id,
        (SELECT name FROM course_types WHERE id=l.course_type_id) course_type_name,
        (SELECT name FROM subjects WHERE id=l.subject_id) subject_name,
        r.student_id, r.amount, r.ledger_id, r.fee_cents, r.fee_millis, r.fee_overridden,
        s.name student_name, s.course, s.billing_unit, s.profile_id, s.helen_original,
        u.name teacher_name
        FROM lessons l
        JOIN teachers t ON t.id=l.teacher_id JOIN users u ON u.id=t.user_id
        JOIN lesson_reports r ON r.lesson_id=l.id
        JOIN students s ON s.id=r.student_id
        JOIN ledger led ON led.id=r.ledger_id
        WHERE l.status!='cancelled' AND substr(l.starts_at,1,10)>=? AND substr(l.starts_at,1,10)<=?
          AND NOT EXISTS (SELECT 1 FROM ledger rev WHERE rev.reversal_of=r.ledger_id)'''
        + absence_pay_clause()
        + __import__('vouchers').hide_sql(c, 'led') + ' ORDER BY l.starts_at, l.id, s.name''', (start.isoformat(), end.isoformat())).fetchall()


def resolved_fee(c, row):
    computed, paid_units, gift_units = fee_for_ledger(c, row['ledger_id'], row['amount'])
    if row['fee_cents'] is not None:
        return row['fee_cents'], True, paid_units, gift_units, bool(row['fee_overridden'])
    return computed, computed is not None, paid_units, gift_units, False


def build_lessons(c, rows, rules_by_teacher):
    grouped = []
    index = {}
    owner_teachers = {row['id'] for row in c.execute(
        'SELECT t.id FROM teachers t JOIN organization_owners o ON o.user_id=t.user_id')}
    for row in rows:
        key = row['lesson_id']
        if key not in index:
            minutes = minutes_between(row['starts_at'], row['ends_at'])
            item = {'lesson_id': key, 'teacher_id': row['teacher_id'], 'teacher_name': row['teacher_name'],
                'title': row['title'], 'date': row['starts_at'][:10], 'starts_at': row['starts_at'], 'ends_at': row['ends_at'],
                'minutes': minutes, 'course_type_name': row['course_type_name'] or '', 'subject_name': row['subject_name'] or '',
                'lines': []}
            index[key] = item
            grouped.append(item)
        fee, known, paid_units, gift_units, overridden = resolved_fee(c, row)
        millis = row['fee_millis'] if row['fee_millis'] is not None else (None if fee is None else fee * 10)
        index[key]['lines'].append({'student_id': row['student_id'], 'student_name': row['student_name'],
            'course': row['course'], 'billing_unit': row['billing_unit'], 'profile_id': row['profile_id'],
            'is_new': student_is_new(row['helen_original']),
            'units': row['amount'], 'paid_units': paid_units, 'gift_units': gift_units,
            'fee_cents': fee, 'fee_millis': millis, 'fee_known': known, 'fee_overridden': overridden, 'ledger_id': row['ledger_id']})
    for item in grouped:
        rule = rule_on(rules_by_teacher.get(item['teacher_id'], []), item['date'])
        known = [line['fee_cents'] for line in item['lines'] if line['fee_known']]
        item['fee_known'] = all(line['fee_known'] for line in item['lines'])
        item['fee_cents'] = sum(known)
        item['unknown_fee_count'] = sum(1 for line in item['lines'] if not line['fee_known'])
        item['rule'] = public_rule(rule)
        floor_cents = mul_div(rule['hourly_floor_cents'], item['minutes'], 60) if rule and rule['hourly_floor_cents'] else 0
        warnings = [line['student_name'] for line in item['lines'] if not line['fee_known']]
        item['warnings'] = warnings
        percent_bp = int(rule['percent_bp'] or 0) if rule and rule['rule_type'] == 'percent' else 0
        if item['course_type_name'] == '小班课' and rule and rule['rule_type'] == 'percent':
            percent_cents = 0
            for line in item['lines']:
                if not line['fee_known']:
                    continue
                millis = line['fee_millis'] if line['fee_millis'] is not None else (line['fee_cents'] or 0) * 10
                percent_cents += (int(millis) * percent_bp + 50000) // 100000
            if floor_cents > percent_cents:
                pay, basis = floor_cents, 'floor'
            else:
                pay, basis = percent_cents, 'percent'
        else:
            known_fee = sum(line['fee_cents'] or 0 for line in item['lines'] if line['fee_known'])
            pay, basis = lesson_pay(rule, item['minutes'], known_fee)
            percent_cents = mul_div(known_fee, percent_bp, 10000) if rule and rule['rule_type'] == 'percent' else 0
        item['pay_cents'] = pay
        item['pay_basis'] = basis
        item['share_bp'] = rule['percent_bp'] if rule and rule['rule_type'] == 'percent' else None
        item['percent_cents'] = percent_cents
        item['floor_cents'] = floor_cents
        item['top_up_cents'] = max(0, pay - percent_cents) if basis == 'floor' else 0
        allocate_line_pay(item)
    return grouped


def allocate_line_pay(item):
    lines = item['lines']
    if not lines:
        return
    hourly = item['rule'] and item['rule']['rule_type'] == 'hourly'
    if hourly or any(not line['fee_known'] for line in lines):
        weights = [1] * len(lines)
    else:
        weights = [line['fee_cents'] or 0 for line in lines]
        if sum(weights) <= 0:
            weights = [1] * len(lines)
    total = sum(weights)
    allocated = 0
    for i, line in enumerate(lines):
        if i == len(lines) - 1:
            line['pay_cents'] = item['pay_cents'] - allocated
        else:
            line['pay_cents'] = mul_div(item['pay_cents'], weights[i], total)
            allocated += line['pay_cents']


def public_rule(rule):
    if not rule:
        return None
    return {'id': rule['id'], 'teacher_id': rule['teacher_id'], 'rule_type': rule['rule_type'],
        'percent_bp': rule['percent_bp'], 'hourly_floor_cents': rule['hourly_floor_cents'],
        'hourly_rate_cents': rule['hourly_rate_cents'], 'effective_from': rule['effective_from'], 'note': rule['note']}


def schedule_cost(amount, cadence, eff_from, eff_to, start, end):
    window_start = max(start, eff_from)
    window_end = end if not eff_to else min(end, eff_to)
    if window_end < window_start:
        return 0
    if cadence == 'day':
        return amount * ((window_end - window_start).days + 1)
    if cadence == 'week':
        days = (window_end - window_start).days + 1
        return mul_div(amount, days, 7)
    total = 0
    cursor = window_start
    while cursor <= window_end:
        month_end = cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1])
        seg_end = min(window_end, month_end)
        dim = calendar.monthrange(cursor.year, cursor.month)[1]
        days = (seg_end - cursor).days + 1
        total += mul_div(amount, days, dim)
        cursor = month_end + dt.timedelta(days=1)
    return total


def costs_for(c, start, end, shared_only=False):
    import expenses
    expenses.materialize(c)
    details = []
    total = 0
    shared_sql = ' AND shared=1' if shared_only else ''
    for row in c.execute('SELECT * FROM cost_entries WHERE voided=0 AND cost_date>=? AND cost_date<=?'+shared_sql+' ORDER BY cost_date,id', (start.isoformat(), end.isoformat())):
        details.append({'kind': 'entry', 'id': row['id'], 'date': row['cost_date'], 'label': row['label'],
            'amount_cents': row['amount_cents'], 'note': row['note'], 'shared': row['shared']})
        total += row['amount_cents']
    for row in c.execute('SELECT * FROM cost_schedules WHERE 1=1'+shared_sql+' ORDER BY id'):
        eff_to = dt.date.fromisoformat(row['effective_to']) if row['effective_to'] else None
        amount = schedule_cost(row['amount_cents'], row['cadence'], dt.date.fromisoformat(row['effective_from']), eff_to, start, end)
        if amount:
            details.append({'kind': 'schedule', 'id': row['id'], 'date': row['effective_from'], 'label': row['label'],
                'amount_cents': amount, 'cadence': row['cadence'], 'rate_cents': row['amount_cents'], 'shared': row['shared']})
            total += amount
    return total, details


def partner_section(c, lessons, teachers, start, end):
    """30% of (new-student fees − shared costs). Teaching pay is not deducted again."""
    rules = [dict(r) for r in c.execute('''SELECT p.*, u.name teacher_name FROM partner_share_rules p
        LEFT JOIN teachers t ON t.id=p.teacher_id LEFT JOIN users u ON u.id=t.user_id ORDER BY p.effective_from, p.id''')]
    chosen = rule_on(rules, end.isoformat())
    lines = []
    revenue = unknown = 0
    for lesson in lessons:
        for line in lesson['lines']:
            if not line['is_new']:
                continue
            if line['fee_known']:
                revenue += line['fee_cents'] or 0
            else:
                unknown += 1
            lines.append({'date': lesson['date'], 'starts_at': lesson['starts_at'], 'ends_at': lesson['ends_at'],
                'minutes': lesson['minutes'], 'lesson_id': lesson['lesson_id'], 'title': lesson['title'],
                'teacher_id': lesson['teacher_id'], 'teacher_name': lesson['teacher_name'],
                'student_id': line['student_id'], 'student_name': line['student_name'], 'course': line['course'],
                'fee_cents': line['fee_cents'], 'fee_known': line['fee_known'], 'pay_cents': line['pay_cents']})
    shared_total, shared_details = costs_for(c, start, end, shared_only=True)
    remainder = revenue - shared_total
    percent = chosen['percent_bp'] if chosen and chosen['teacher_id'] else 0
    share = mul_div(remainder, percent, 10000) if remainder > 0 and percent else 0
    teaching = next((teacher for teacher in teachers if chosen and teacher['teacher_id'] == chosen['teacher_id']), None)
    return {'teacher_id': chosen['teacher_id'] if chosen else None,
        'teacher_name': chosen.get('teacher_name') if chosen else None,
        'percent_bp': percent, 'effective_from': chosen['effective_from'] if chosen else None,
        'changed_during_period': any(start.isoformat() < r['effective_from'] <= end.isoformat() for r in rules),
        'revenue_cents': revenue, 'shared_cost_cents': shared_total, 'remainder_cents': remainder,
        'share_cents': share, 'teaching_pay_cents': teaching['total_pay_cents'] if teaching else 0,
        'unknown_fee_count': unknown, 'lines': lines, 'costs': shared_details,
        'rules': [{k: r[k] for k in ('id','teacher_id','teacher_name','percent_bp','effective_from','note')} for r in rules]}


def report(c, user, period, day, start, end):
    own_teacher = None
    if user['role'] == 'teacher':
        if period not in ('day', 'week', 'fortnight', 'month'):
            raise ValueError('请选择今天、本周、双周或本月。')
        own_teacher = c.execute('SELECT id FROM teachers WHERE user_id=?', (user['id'],)).fetchone()
        if not own_teacher:
            raise AccessError('无法查看工资。')
    else:
        require_owner(user)
    start, end = period_bounds(period, day, start, end)
    rules = [dict(r) for r in c.execute('SELECT * FROM pay_rules ORDER BY teacher_id, effective_from, id')]
    by_teacher = {}
    for rule in rules:
        by_teacher.setdefault(rule['teacher_id'], []).append(rule)
    lessons = build_lessons(c, confirmed_rows(c, start, end), by_teacher)
    teachers = []
    for teacher in c.execute('''SELECT t.id, u.name, u.active FROM teachers t JOIN users u ON u.id=t.user_id ORDER BY u.name, t.id'''):
        own = [lesson for lesson in lessons if lesson['teacher_id'] == teacher['id']]
        applicable = [rule_on(by_teacher.get(teacher['id'], []), lesson['date']) for lesson in own]
        teachers.append({'teacher_id': teacher['id'], 'name': teacher['name'], 'active': teacher['active'],
            'rule': public_rule(rule_on(by_teacher.get(teacher['id'], []), end.isoformat())),
            'rules_in_period': len({id(r) for r in applicable if r}) > 1,
            'lessons': own, 'total_minutes': sum(lesson['minutes'] for lesson in own),
            'total_fee_cents': sum(lesson['fee_cents'] for lesson in own),
            'total_pay_cents': sum(lesson['pay_cents'] for lesson in own),
            'total_top_up_cents': sum(lesson['top_up_cents'] for lesson in own),
            'unknown_fee_count': sum(lesson['unknown_fee_count'] for lesson in own)})
    students = []
    for row in c.execute('''SELECT id, profile_id, name, course, helen_original, archived
        FROM students ORDER BY helen_original DESC, name, course, id'''):
        item = dict(row)
        item['is_new'] = student_is_new(row['helen_original'])
        students.append(item)
    if own_teacher:
        teachers = [teacher for teacher in teachers if teacher['teacher_id'] == own_teacher['id']]
        return {'period': period, 'start': start.isoformat(), 'end': end.isoformat(),
            'teachers': teachers, 'partner': None, 'rules': [], 'cost_entries': [], 'cost_schedules': [],
            'students': [], 'generated_at': now_local().isoformat(timespec='seconds')}
    return {'period': period, 'start': start.isoformat(), 'end': end.isoformat(),
        'teachers': teachers, 'partner': partner_section(c, lessons, teachers, start, end),
        'rules': [public_rule(r) for r in rules],
        'cost_entries': [dict(r) for r in c.execute('SELECT * FROM cost_entries ORDER BY cost_date DESC, id DESC')],
        'cost_schedules': [dict(r) for r in c.execute('SELECT * FROM cost_schedules ORDER BY active DESC, id DESC')],
        'students': students,
        'generated_at': now_local().isoformat(timespec='seconds')}


def save_rule(c, user, data):
    require_owner(user)
    teacher_id = int(data.get('teacher_id') or 0)
    if not c.execute('SELECT 1 FROM teachers WHERE id=?', (teacher_id,)).fetchone():
        raise ValueError('请选择老师。')
    kind = data.get('rule_type')
    if kind not in ('percent', 'hourly'):
        raise ValueError('请选择工资方式：按课酬比例，或按小时。')
    start = day_value(data.get('effective_from'), '请选择生效日期。').isoformat()
    note = str(data.get('note') or '').strip()
    if len(note) > 200:
        raise ValueError('备注最多 200 个字。')
    if kind == 'percent':
        bp, floor, rate = percent_bp(data.get('percent')), optional_money(data.get('hourly_floor')), None
    else:
        bp, floor, rate = None, None, accounting.money(data.get('hourly_rate'))
    existing = c.execute('SELECT id FROM pay_rules WHERE teacher_id=? AND effective_from=?', (teacher_id, start)).fetchone()
    if existing:
        c.execute('''UPDATE pay_rules SET rule_type=?,percent_bp=?,hourly_floor_cents=?,hourly_rate_cents=?,note=? WHERE id=?''',
            (kind, bp, floor, rate, note, existing['id']))
    else:
        c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,note,created_by)
            VALUES(?,?,?,?,?,?,?,?)''', (teacher_id, kind, bp, floor, rate, start, note, user['id']))
    return {'ok': True}


def save_partner(c, user, data):
    require_owner(user)
    teacher_id = int(data.get('teacher_id') or 0) or None
    if teacher_id and not c.execute('SELECT 1 FROM teachers WHERE id=?', (teacher_id,)).fetchone():
        raise ValueError('请选择合伙人对应的老师账号。')
    start = day_value(data.get('effective_from'), '请选择生效日期。').isoformat()
    bp = percent_bp(data.get('percent') if teacher_id else 0)
    note = str(data.get('note') or '').strip()
    if len(note) > 200:
        raise ValueError('备注最多 200 个字。')
    existing = c.execute('SELECT id FROM partner_share_rules WHERE effective_from=? AND ifnull(teacher_id,0)=?', (start, teacher_id or 0)).fetchone()
    if existing:
        c.execute('UPDATE partner_share_rules SET teacher_id=?,percent_bp=?,note=? WHERE id=?', (teacher_id, bp, note, existing['id']))
    else:
        c.execute('INSERT INTO partner_share_rules(teacher_id,percent_bp,effective_from,note,created_by) VALUES(?,?,?,?,?)',
            (teacher_id, bp, start, note, user['id']))
    return {'ok': True}


def reject_original_flag(user, data):
    """The original-student list is boss-only, including on unrelated forms."""
    if any(key in data for key in ('helen_original', 'origin_override', 'cutoff', 'student_origin_cutoff')):
        require_owner(user)
        raise ValueError('原有学生标记请在工资页面修改。')


def set_original(c, user, data):
    require_owner(user)
    flag = data.get('helen_original')
    if type(flag) is not bool:
        raise ValueError('请选择是否为 Helen 的原有学生。')
    raw = data.get('profile_ids')
    if not isinstance(raw, list) or not raw:
        raise ValueError('请选择学生。')
    ids = sorted({int(x) for x in raw})
    marks = ','.join('?' for _ in ids)
    found = c.execute(f'SELECT COUNT(DISTINCT profile_id) FROM students WHERE profile_id IN ({marks})', ids).fetchone()[0]
    if found != len(ids):
        raise ValueError('有学生不存在，请刷新后重试。')
    c.execute(f'UPDATE students SET helen_original=? WHERE profile_id IN ({marks})', [int(flag), *ids])
    return {'ok': True}


def set_fee(c, user, data):
    require_owner(user)
    lesson_id, student_id = int(data.get('lesson_id') or 0), int(data.get('student_id') or 0)
    row = c.execute('SELECT * FROM lesson_reports WHERE lesson_id=? AND student_id=?', (lesson_id, student_id)).fetchone()
    if not row or not row['ledger_id']:
        raise ValueError('只能修改已经确认扣课的课程金额。')
    if data.get('reset') is True:
        c.execute('UPDATE lesson_reports SET fee_cents=NULL, fee_overridden=0 WHERE lesson_id=? AND student_id=?', (lesson_id, student_id))
        return {'ok': True}
    c.execute('UPDATE lesson_reports SET fee_cents=?, fee_overridden=1 WHERE lesson_id=? AND student_id=?',
        (accounting.money(data.get('fee_amount')), lesson_id, student_id))
    return {'ok': True}


def add_cost_entry(c, user, data):
    require_owner(user)
    label = str(data.get('label') or '').strip()
    if not label or len(label) > 80:
        raise ValueError('成本名称不能为空，且不能超过 80 个字。')
    note = str(data.get('note') or '').strip()
    if len(note) > 200:
        raise ValueError('备注最多 200 个字。')
    day = day_value(data.get('cost_date'), '请选择成本日期。').isoformat()
    c.execute('INSERT INTO cost_entries(cost_date,label,amount_cents,note,shared,created_by) VALUES(?,?,?,?,?,?)',
        (day, label, accounting.money(data.get('amount')), note, int(data.get('shared') is True), user['id']))
    return {'ok': True}


def void_cost_entry(c, user, data):
    require_owner(user)
    row = c.execute('SELECT id FROM cost_entries WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not row:
        raise ValueError('找不到这条成本。')
    voided = data.get('voided')
    if type(voided) is not bool:
        raise ValueError('请选择作废或恢复。')
    c.execute('UPDATE cost_entries SET voided=? WHERE id=?', (int(voided), row['id']))
    return {'ok': True}


def add_cost_schedule(c, user, data):
    require_owner(user)
    label = str(data.get('label') or '').strip()
    if not label or len(label) > 80:
        raise ValueError('成本名称不能为空，且不能超过 80 个字。')
    cadence = data.get('cadence')
    if cadence not in ('day', 'week', 'month'):
        raise ValueError('请选择按日、按周或按月。')
    start = day_value(data.get('effective_from'), '请选择生效日期。').isoformat()
    end = str(data.get('effective_to') or '').strip()
    end = day_value(end, '结束日期无效。').isoformat() if end else None
    if end and end < start:
        raise ValueError('结束日期不能早于开始日期。')
    c.execute('''INSERT INTO cost_schedules(label,amount_cents,cadence,effective_from,effective_to,shared,created_by)
        VALUES(?,?,?,?,?,?,?)''', (label, accounting.money(data.get('amount')), cadence, start, end, int(data.get('shared') is True), user['id']))
    return {'ok': True}


def stop_cost_schedule(c, user, data):
    require_owner(user)
    row = c.execute('SELECT * FROM cost_schedules WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not row:
        raise ValueError('找不到这项固定成本。')
    yesterday = (now_local().date() - dt.timedelta(days=1)).isoformat()
    end = yesterday if yesterday >= row['effective_from'] else row['effective_from']
    c.execute('UPDATE cost_schedules SET active=0, effective_to=? WHERE id=?', (end, row['id']))
    return {'ok': True}


def handle_post(c, user, path, data):
    if path == '/api/pay/rules':
        return save_rule(c, user, data)
    if path == '/api/pay/partner':
        return save_partner(c, user, data)
    if path == '/api/pay/students':
        return set_original(c, user, data)
    if path == '/api/pay/fee':
        return set_fee(c, user, data)
    if path == '/api/pay/costs':
        return add_cost_entry(c, user, data)
    if path == '/api/pay/costs/void':
        return void_cost_entry(c, user, data)
    if path == '/api/pay/schedules':
        return add_cost_schedule(c, user, data)
    if path == '/api/pay/schedules/stop':
        return stop_cost_schedule(c, user, data)
    raise ValueError('接口不存在。')


def aud(cents):
    if cents is None:
        return ''
    sign = '-' if cents < 0 else ''
    cents = abs(int(cents))
    return f'{sign}{cents // 100}.{cents % 100:02d}'


def hours(minutes):
    return f'{minutes / 60:.2f}'


def csv_bytes(data, teacher_id=None):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    teachers = data['teachers']
    if teacher_id:
        teachers = [t for t in teachers if t['teacher_id'] == teacher_id]
        if not teachers:
            raise ValueError('找不到这位老师。')
    writer.writerow(['老师工资', data['start'], data['end']])
    writer.writerow(['老师', '日期', '开始', '结束', '时长（小时）', '学生', '科目', '课程类型', '扣除数量', '课酬基数（AUD）', '分成比例', '比例工资（AUD）', '保底补足（AUD）', '本节应付（AUD）', '计算方式', '备注'])
    basis_name = {'percent': '课酬比例', 'floor': '时薪保底', 'hourly': '时薪', 'missing-rule': '未设置规则'}
    for teacher in teachers:
        if not teacher['lessons']:
            writer.writerow([teacher['name'], '', '', '', '0.00', '', '', '', '', '0.00', '0.00', '', '本期没有已确认课程'])
        for lesson in teacher['lessons']:
            for index, line in enumerate(lesson['lines']):
                writer.writerow([
                    teacher['name'], lesson['date'], lesson['starts_at'][11:16], lesson['ends_at'][11:16],
                    hours(lesson['minutes']) if index == 0 else '', line['student_name'],
                    lesson.get('subject_name') or line['course'], lesson.get('course_type_name') or '',
                    f'{line["units"] / 100:.2f}', aud(line['fee_cents']) if line['fee_known'] else '未定价',
                    f"{(lesson.get('share_bp') or 0) / 100:.2f}%" if index == 0 and lesson.get('share_bp') is not None else '',
                    aud(lesson.get('percent_cents') or 0) if index == 0 else '',
                    aud(lesson.get('top_up_cents') or 0) if index == 0 else '',
                    aud(lesson['pay_cents']) if index == 0 else '',
                    basis_name.get(lesson['pay_basis'], lesson['pay_basis']) if index == 0 else '',
                    '' if line['fee_known'] else '充值批次没有可计算的澳元单价'])
        writer.writerow([teacher['name'], '合计', '', '', hours(teacher['total_minutes']), '', '', '', '',
            aud(teacher['total_fee_cents']), '', '', aud(teacher.get('total_top_up_cents') or 0),
            aud(teacher['total_pay_cents']), '',
            f'未定价 {teacher["unknown_fee_count"]} 节' if teacher['unknown_fee_count'] else ''])
    if not teacher_id:
        partner = data['partner']
        writer.writerow([])
        writer.writerow(['新学生分成', partner.get('teacher_name') or '未设置', f'{(partner.get("percent_bp") or 0) / 100:.2f}%'])
        writer.writerow(['新学生课酬', aud(partner['revenue_cents'])])
        writer.writerow(['减：共同成本', aud(partner['shared_cost_cents'])])
        writer.writerow(['剩余', aud(partner['remainder_cents'])])
        writer.writerow(['分成金额（剩余为负时为 0）', aud(partner['share_cents'])])
        writer.writerow(['上课工资（另计，不从剩余里扣除）', aud(partner['teaching_pay_cents'])])
        writer.writerow(['日期', '学生', '老师', '课酬基数（AUD）', '分摊老师课酬（AUD）'])
        for line in partner['lines']:
            writer.writerow([line['date'], line['student_name'], line['teacher_name'],
                aud(line['fee_cents']) if line['fee_known'] else '未定价', aud(line['pay_cents'])])
        writer.writerow(['成本', '金额（AUD）', '说明'])
        for cost in partner['costs']:
            writer.writerow([cost['label'], aud(cost['amount_cents']), cost.get('date', '')])
    return b'\xef\xbb\xbf' + buffer.getvalue().encode('utf-8')


def accounting_csv(data):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    totals = data['totals']
    writer.writerow(['账目总结', data['start'], data['end'], data['timezone']])
    writer.writerow(['本期收款（AUD）', aud(totals['receipts_cents'])])
    writer.writerow(['本期退款（AUD）', aud(totals['refunds_cents'])])
    writer.writerow(['金额纠错（AUD）', aud(totals['corrections_cents'])])
    writer.writerow(['本期净收款（AUD）', aud(totals['net_cash_cents'])])
    writer.writerow([])
    writer.writerow(['日期', '充值课时', '耗课时', '退课时', '收款（AUD）', '退款（AUD）', '金额纠错（AUD）', '净收款（AUD）'])
    for day in data['daily']:
        writer.writerow([day['date'], day['credit_units'] / 100, day['lesson_units'] / 100, day['refund_units'] / 100,
            aud(day['receipts_cents']), aud(day['refunds_cents']), aud(day['corrections_cents']), aud(day['net_cash_cents'])])
    writer.writerow([])
    writer.writerow(['业务日期', '编号', '学生', '课程', '类型', '课时变动', '金额（AUD）', '方式', '备注'])
    for row in data['rows']:
        kind = row['kind'] if row['kind'] != 'reversal' else (row.get('original_kind') or '') + '纠错'
        writer.writerow([row['lesson_date'], row['id'], row['student_name'], row['course'], kind,
            row['delta'] / 100, aud(row['cash_delta']) if row['cash_delta'] is not None else '未登记',
            row.get('payment_method') or '', row.get('note') or ''])
    return b'\xef\xbb\xbf' + buffer.getvalue().encode('utf-8')
