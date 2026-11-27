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


def _subject_key(row):
    import teaching
    return teaching.canonical_subject(row.get('subject_name') or row.get('course') or '')


def _covered_by_sibling(active, row):
    """An empty course is not 欠费 when another live course of the same subject still has a balance."""
    subject = _subject_key(row)
    profile = row.get('profile_id')
    own = row.get('student_id') or row.get('id')
    if not profile or not subject:
        return False
    for other in active:
        if other['id'] == own or other['profile_id'] != profile or other['balance'] <= 0:
            continue
        if _subject_key(other) == subject:
            return True
    return False


def arrears_rows(c):
    active = [dict(r) for r in c.execute('''SELECT s.id, s.profile_id, s.name, s.course, s.balance, sb.name subject_name
        FROM students s LEFT JOIN subjects sb ON sb.id=s.subject_id
        WHERE s.archived=0''')]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='arrears'").fetchone():
        owed = [dict(r) for r in c.execute('''SELECT a.*, s.name student_name, s.course, s.balance, s.profile_id, sb.name subject_name
            FROM arrears a JOIN students s ON s.id=a.student_id
            LEFT JOIN subjects sb ON sb.id=s.subject_id
            WHERE a.settled=0 AND s.archived=0 ORDER BY a.id DESC''')]
    else:
        owed = []
    owed = [row for row in owed if not _covered_by_sibling(active, row)]
    booked = [dict(r) for r in c.execute('''SELECT s.id student_id, s.profile_id, s.name student_name, s.course, s.balance,
        sb.name subject_name, MIN(l.starts_at) next_lesson, COUNT(l.id) upcoming
        FROM students s
        JOIN lesson_students ls ON ls.student_id=s.id
        JOIN lessons l ON l.id=ls.lesson_id
        LEFT JOIN subjects sb ON sb.id=s.subject_id
        WHERE s.archived=0 AND s.balance<=0 AND l.status='scheduled' AND l.starts_at>=?
        GROUP BY s.id ORDER BY next_lesson''', (now_local().strftime('%Y-%m-%dT%H:%M'),))]
    booked = [row for row in booked if not _covered_by_sibling(active, row)]
    for row in owed + booked:
        row['subject_name'] = _subject_key(row)
    return {'debts': owed, 'booked_without_credit': booked}


def paid_units(c, student_id):
    """Renewal looks at paid hours left on packs, not gift hours and not the balance cache."""
    row = c.execute('SELECT COALESCE(SUM(paid_left),0) n FROM credit_batches WHERE student_id=?', (student_id,)).fetchone()
    return int(row['n'] if row else 0)


def low_balance(c):
    rows = []
    for student in c.execute('''SELECT s.id, s.profile_id, s.name, s.course, s.balance, s.billing_unit, s.grade, s.level_code,
        COALESCE((SELECT SUM(paid_left) FROM credit_batches b WHERE b.student_id=s.id),0) paid_left
        FROM students s WHERE s.archived=0
        AND COALESCE((SELECT SUM(paid_left) FROM credit_batches b WHERE b.student_id=s.id),0)<300
        ORDER BY paid_left, s.name, s.id'''):
        item = dict(student)
        item['lessons_left'] = item['paid_left'] / 100
        rows.append(item)
    return rows


def monthly(c, user, month):
    """One month: money in, lesson value, hours left, teacher pay, forfeits, and what does not add up."""
    import calendar as cal
    text = str(month or '')
    try:
        year, mon = int(text[:4]), int(text[5:7])
        start = dt.date(year, mon, 1)
    except (ValueError, IndexError):
        raise ValueError('请选择月份。')
    end = dt.date(year, mon, cal.monthrange(year, mon)[1])
    report = statement(c, user, 'custom', None, start.isoformat(), end.isoformat())
    outstanding = c.execute('''SELECT COALESCE(SUM(b.paid_left+b.gift_left),0) FROM credit_batches b
        JOIN students s ON s.id=b.student_id WHERE s.archived=0 AND s.voided=0''').fetchone()[0]
    value = 0
    unpriced = []
    for row in c.execute('''SELECT s.*, b.paid_left FROM credit_batches b
        JOIN students s ON s.id=b.student_id
        WHERE s.archived=0 AND s.voided=0 AND b.paid_left>0'''):
        hourly = __import__('pricing').price_for(c, row, end.isoformat())
        if hourly is None:
            unpriced.append(f"{row['name']} {row['course']} 的剩余课时没有价格")
            continue
        value += int(hourly) * int(row['paid_left']) // 100
    mismatches = c.execute('''SELECT s.name, s.course, s.balance,
        COALESCE((SELECT SUM(paid_left+gift_left) FROM credit_batches b WHERE b.student_id=s.id),0) packs
        FROM students s WHERE s.voided=0
        AND s.balance != COALESCE((SELECT SUM(paid_left+gift_left) FROM credit_batches b WHERE b.student_id=s.id),0)''').fetchall()
    exceptions = list(unpriced)
    if report['unknown_fee_count']:
        exceptions.append(f"有 {report['unknown_fee_count']} 节课算不出上课费用")
    for row in mismatches:
        exceptions.append(f"{row['name']} {row['course']} 的余额和课时包不一致")
    return {
        'month': f'{year:04d}-{mon:02d}',
        'money_received_cents': report['cash_received_cents'],
        'money_refunded_cents': report['cash_refunded_cents'],
        'institution_lessons_cents': report['turnover_cents'],
        'own_lessons_cents': report['dashboard']['own_lesson_fee_cents'],
        'lessons_value_cents': report['turnover_cents'] + report['dashboard']['own_lesson_fee_cents'],
        'outstanding_units': outstanding,
        'outstanding_value_cents': value,
        'teacher_pay_cents': report['teacher_pay_cents'],
        'cost_cents': report['dashboard']['cost_cents'],
        'hms_wage_cents': report['dashboard']['hms_wage_cents'],
        'hms_dividend_cents': report['dashboard']['hms_dividend_cents'],
        'hms_percent_bp': report['dashboard']['hms_percent_bp'],
        'helen_institution_wage_cents': report['dashboard']['helen_institution_wage_cents'],
        'forfeit_units': report['forfeit_units'],
        'receivable_cents': __import__('receivables').total_owed(c),
        'exceptions': exceptions,
    }


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
        line = {'teacher_id': teacher['teacher_id'], 'name': teacher['name'],
            'lessons': len(teacher['lessons']), 'minutes': teacher['total_minutes'],
            'fee_cents': teacher['total_fee_cents'], 'pay_cents': teacher['total_pay_cents'],
            'is_helen': own, 'rule': teacher['rule']}
        teachers.append(line)
        if own:
            helen_income += line['fee_cents']
        else:
            external_pay += line['pay_cents']
    partner = pay['partner']
    lessons = [lesson for teacher in pay['teachers'] for lesson in teacher['lessons']]
    own = payroll.original_student_lines(lessons)
    own_revenue = own['revenue_cents']
    own_lines = own['lines']
    revenue = partner['revenue_cents']
    institution_cost = partner['shared_cost_cents']
    profit = partner['remainder_cents']
    percent = partner['percent_bp'] or 0
    helen_share = partner['helen_share_cents']
    helen_wage = partner.get('helen_institution_wage_cents') or 0
    total = own_revenue + helen_share + helen_wage
    share_view = payroll.public_profit_share(partner)
    dashboard = {
        'own_revenue_cents': own_revenue,
        'own_lines': own_lines,
        'helen_taught_cents': own['helen_taught_cents'],
        'other_teacher_cents': own['other_teacher_cents'],
        'revenue_cents': revenue,
        'cost_cents': institution_cost,
        'profit_cents': profit,
        'percent_bp': percent,
        'vincent_cents': partner['share_cents'],
        'helen_share_cents': helen_share,
        'helen_institution_wage_cents': helen_wage,
        'hms_wage_cents': own['hms_wage_cents'],
        'hms_dividend_cents': own['hms_dividend_cents'],
        'hms_percent_bp': own['hms_percent_bp'],
        'hms_fee_cents': own['helen_fee_cents'],
        'total_cents': total,
        'lines': share_view['lines'],
        'costs': [{
            'date': cost.get('date') or '', 'label': cost.get('label') or '',
            'amount_cents': cost.get('amount_cents') or 0,
            'student_name': cost.get('student_name') or '', 'teacher_name': cost.get('teacher_name') or '',
        } for cost in partner['costs']],
        'unpriced': payroll.unpriced_lessons(lessons),
        'own_lesson_fee_cents': sum((line['fee_cents'] or 0) for line in own_lines if line.get('fee_known')),
    }
    turnover = revenue
    costs, cost_lines = payroll.costs_for(c, start, end, shared_only=False)
    teacher_pay = sum(teacher['pay_cents'] for teacher in teachers)
    organisation = profit
    helen_income = own_revenue
    helen_net = total
    cash = accounting.cash_breakdown(c, start, end)
    forfeit_units = c.execute('''SELECT COALESCE(SUM(-delta),0) FROM ledger
        WHERE kind='forfeit' AND lesson_date>=? AND lesson_date<=?''', (start.isoformat(), end.isoformat())).fetchone()[0]
    margin = None if not turnover else round((turnover - teacher_pay) * 100 / turnover, 1)
    by_type = {}
    unknown_fee = 0
    for teacher in pay['teachers']:
        unknown_fee += payroll.institution_totals(teacher['lessons'])['unknown_fee_count']
        for lesson in teacher['lessons']:
            counted = [line for line in lesson['lines'] if payroll.counts_for_institution(line)]
            if payroll.SEPARATE_ORIGINAL_STUDENTS and not counted:
                continue
            label = lesson.get('course_type_name') or '未分类'
            bucket = by_type.setdefault(label, {'name': label, 'lessons': 0, 'minutes': 0, 'fee_cents': 0, 'pay_cents': 0})
            bucket['lessons'] += 1
            bucket['minutes'] += lesson['minutes']
            for line in counted:
                if line['fee_known']:
                    bucket['fee_cents'] += line['fee_cents'] or 0
                bucket['pay_cents'] += line.get('pay_cents') or 0
    return {
        'period': period, 'start': start.isoformat(), 'end': end.isoformat(),
        'turnover_cents': turnover,
        'cash_received_cents': cash['received_cents'],
        'forfeit_units': forfeit_units,
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
        'unknown_fee_count': unknown_fee,
        'separate_originals': payroll.SEPARATE_ORIGINAL_STUDENTS,
        'dashboard': dashboard,
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
