"""Boss-only statement: what the lessons were worth, what was collected, and what is left."""
import datetime as dt

import accounting
import payroll
from teaching import now_local


def _headlines(statement):
    turnover = statement['turnover_cents']
    teacher_pay = statement['teacher_pay_cents']
    gross = turnover - teacher_pay
    margin = None if not turnover else int((gross * 10000 + turnover // 2) // turnover) / 100
    return {
        'turnover_cents': turnover,
        'cash_cents': statement['cash_received_cents'],
        'teacher_pay_cents': teacher_pay,
        'cost_cents': statement['operating_cost_cents'],
        'gross_profit_cents': gross,
        'gross_margin_percent': margin,
        'profit_cents': statement['organisation_profit_cents'],
        'helen_net_cents': statement['helen_net_cents'],
    }


def unhanded(c):
    return [dict(r) for r in c.execute('''SELECT cash.ledger_id, cash.cash_delta, cash.payment_method, cash.reference,
        cash.received_by, cash.handed_over_on, u.name receiver_name, l.lesson_date, s.name student_name, s.course
        FROM cash_entries cash
        JOIN ledger l ON l.id=cash.ledger_id
        JOIN students s ON s.id=l.student_id
        LEFT JOIN users u ON u.id=cash.received_by
        WHERE cash.handed_over=0 AND cash.cash_delta>0
          AND NOT EXISTS (SELECT 1 FROM ledger rev WHERE rev.reversal_of=l.id)'''
        + __import__('vouchers').hide_sql(c, 'l') + ' ORDER BY l.lesson_date, cash.ledger_id''')]


def arrears_rows(c):
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='arrears'").fetchone():
        owed = [dict(r) for r in c.execute('''SELECT a.*, s.name student_name, s.course, s.balance
            FROM arrears a JOIN students s ON s.id=a.student_id
            WHERE a.settled=0 ORDER BY a.id DESC''')]
    else:
        owed = []
    booked = [dict(r) for r in c.execute('''SELECT s.id student_id, s.name student_name, s.course, s.balance,
        MIN(l.starts_at) next_lesson, COUNT(l.id) upcoming
        FROM students s
        JOIN lesson_students ls ON ls.student_id=s.id
        JOIN lessons l ON l.id=ls.lesson_id
        WHERE s.archived=0 AND s.balance<=0 AND l.status='scheduled' AND l.starts_at>=?
        GROUP BY s.id ORDER BY next_lesson''', (now_local().strftime('%Y-%m-%dT%H:%M'),))]
    return {'debts': owed, 'booked_without_credit': booked}


def low_balance(c):
    rows = []
    for student in c.execute('''SELECT id, profile_id, name, course, balance, billing_unit, grade, level_code
        FROM students WHERE archived=0 AND balance<=300 ORDER BY balance, name, id'''):
        item = dict(student)
        item['lessons_left'] = student['balance'] / 100
        rows.append(item)
    return rows


def statement(c, user, period, day, start, end):
    payroll.require_owner(user)
    if period == 'custom':
        start = payroll.day_value(start, '请选择开始日期。')
        end = payroll.day_value(end, '请选择结束日期。')
        if end < start:
            raise ValueError('结束日期不能早于开始日期。')
        if (end - start).days > 3660:
            raise ValueError('一次最多查询 10 年。')
    else:
        start, end = accounting.bounds(period, day or now_local().date().isoformat())
    pay = payroll.report(c, user, 'custom', None, start.isoformat(), end.isoformat())
    owner_ids = {row['user_id'] for row in c.execute('SELECT user_id FROM organization_owners')}
    teacher_users = {row['id']: row['user_id'] for row in c.execute('SELECT id, user_id FROM teachers')}
    helen_income = 0
    external_pay = 0
    teachers = []
    for teacher in pay['teachers']:
        own = teacher_users.get(teacher['teacher_id']) in owner_ids
        line = {'teacher_id': teacher['teacher_id'], 'name': teacher['name'], 'lessons': len(teacher['lessons']),
            'minutes': teacher['total_minutes'], 'fee_cents': teacher['total_fee_cents'],
            'pay_cents': teacher['total_pay_cents'], 'is_helen': own, 'rule': teacher['rule']}
        teachers.append(line)
        if own:
            helen_income += teacher['total_fee_cents']
        else:
            external_pay += teacher['total_pay_cents']
    turnover = sum(teacher['fee_cents'] for teacher in teachers)
    costs, cost_lines = payroll.costs_for(c, start, end, shared_only=False)
    gross = turnover - external_pay - sum(teacher['pay_cents'] for teacher in teachers if teacher['is_helen'])
    # Teacher pay shown per person includes Helen when she has a pay rule.
    teacher_pay = sum(teacher['pay_cents'] for teacher in teachers)
    organisation = turnover - teacher_pay - costs
    partner = pay['partner']
    helen_net = organisation - partner['share_cents']
    if helen_income and not any(teacher['is_helen'] and teacher['pay_cents'] for teacher in teachers):
        # Her lesson value was not paid out as wages, so it is already inside the profit.
        pass
    cash = accounting.cash_breakdown(c, start, end)
    margin = None if not turnover else round((turnover - teacher_pay) * 100 / turnover, 1)
    by_type = {}
    for teacher in pay['teachers']:
        for lesson in teacher['lessons']:
            label = lesson.get('course_type_name') or '未分类'
            bucket = by_type.setdefault(label, {'name': label, 'lessons': 0, 'minutes': 0, 'fee_cents': 0, 'pay_cents': 0})
            bucket['lessons'] += 1
            bucket['minutes'] += lesson['minutes']
            bucket['fee_cents'] += lesson['fee_cents']
            bucket['pay_cents'] += lesson['pay_cents']
    return {
        'period': period, 'start': start.isoformat(), 'end': end.isoformat(),
        'turnover_cents': turnover,
        'cash_received_cents': cash['received_cents'],
        'cash_refunded_cents': cash['refunded_cents'],
        'by_method': cash['by_method'],
        'by_receiver': cash['by_receiver'],
        'teachers': teachers,
        'teacher_pay_cents': teacher_pay,
        'external_teacher_pay_cents': external_pay,
        'operating_cost_cents': costs,
        'costs': cost_lines,
        'gross_margin_percent': margin,
        'organisation_profit_cents': organisation,
        'partner': partner,
        'helen_teaching_cents': helen_income,
        'helen_net_cents': helen_net,
        'unhanded': unhanded(c),
        'unknown_fee_count': sum(teacher['unknown_fee_count'] for teacher in pay['teachers']),
        'by_type': list(by_type.values()),
        'gst': False,
        'generated_at': now_local().isoformat(timespec='seconds'),
    }


def today_board(c, user, day):
    payroll.require_owner(user)
    day = day or now_local().date().isoformat()
    today = statement(c, user, 'day', day, None, None)
    month = statement(c, user, 'month', day, None, None)
    return {
        'today': _headlines(today), 'month': _headlines(month),
        'unhanded': today['unhanded'], 'arrears': arrears_rows(c), 'low_balance': low_balance(c),
        'date': day,
    }
