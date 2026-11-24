"""Partner profit share. Teaching pay stays on the wage page and is not added here."""
import csv
import io

import payroll
from teaching import now_local


def _split(total, part, whole):
    if total == 0 or whole <= 0 or part <= 0:
        return 0
    return payroll.mul_div(total, part, whole)


def _line_pay(lesson):
    lines = lesson['lines']
    fees = [line['fee_cents'] or 0 for line in lines if line['fee_known']]
    whole = sum(fees)
    shares = []
    for line in lines:
        if whole > 0 and line['fee_known']:
            shares.append(_split(lesson['pay_cents'], line['fee_cents'] or 0, whole))
        elif lines:
            shares.append(_split(lesson['pay_cents'], 1, len(lines)))
        else:
            shares.append(0)
    return shares


def report(c, user, period, day, start, end):
    payroll.require_owner(user)
    if period == 'custom':
        start = payroll.day_value(start, '请选择开始日期。')
        end = payroll.day_value(end, '请选择结束日期。')
        if end < start:
            raise ValueError('结束日期不能早于开始日期。')
        if (end - start).days > 3660:
            raise ValueError('一次最多查询 10 年。')
    else:
        import accounting
        start, end = accounting.bounds(period, day or now_local().date().isoformat())
    rules = [dict(row) for row in c.execute('SELECT * FROM pay_rules ORDER BY teacher_id, effective_from, id')]
    by_teacher = {}
    for rule in rules:
        by_teacher.setdefault(rule['teacher_id'], []).append(rule)
    lessons = payroll.build_lessons(c, payroll.confirmed_rows(c, start, end), by_teacher)
    teachers = []
    for teacher in c.execute('''SELECT t.id, u.name FROM teachers t JOIN users u ON u.id=t.user_id ORDER BY t.id'''):
        own = [lesson for lesson in lessons if lesson['teacher_id'] == teacher['id']]
        teachers.append({'teacher_id': teacher['id'], 'name': teacher['name'], 'lessons': own,
            'total_pay_cents': sum(lesson['pay_cents'] for lesson in own)})
    partner = payroll.partner_section(c, lessons, teachers, start, end)
    roster = []
    for row in c.execute('''SELECT id, profile_id, name, course, helen_original, archived
        FROM students ORDER BY helen_original DESC, name, course, id'''):
        item = dict(row)
        item['is_new'] = payroll.student_is_new(row['helen_original'])
        roster.append(item)
    percent = partner['percent_bp'] or 0
    new_fee = original_fee = new_pay = original_pay = 0
    students = {}
    months = {}
    for lesson in lessons:
        pays = _line_pay(lesson)
        month = lesson['date'][:7]
        bucket = months.setdefault(month, {'month': month, 'new_fee_cents': 0, 'original_fee_cents': 0,
            'teacher_pay_cents': 0, 'new_pay_cents': 0, 'original_pay_cents': 0})
        for line, pay in zip(lesson['lines'], pays):
            fee = line['fee_cents'] or 0 if line['fee_known'] else 0
            row = students.setdefault(line['student_id'], {
                'student_id': line['student_id'], 'name': line['student_name'], 'course': line['course'],
                'is_new': line['is_new'], 'fee_cents': 0, 'pay_cents': 0, 'lessons': 0})
            row['fee_cents'] += fee
            row['pay_cents'] += pay
            row['lessons'] += 1
            bucket['teacher_pay_cents'] += pay
            if line['is_new']:
                new_fee += fee
                new_pay += pay
                bucket['new_fee_cents'] += fee
                bucket['new_pay_cents'] += pay
            else:
                original_fee += fee
                original_pay += pay
                bucket['original_fee_cents'] += fee
                bucket['original_pay_cents'] += pay
    shared = partner['shared_cost_cents']
    whole = new_fee + original_fee
    new_cost = _split(shared, new_fee, whole) if whole else 0
    original_cost = shared - new_cost
    new_profit = new_fee - new_pay - new_cost
    original_profit = original_fee - original_pay - original_cost
    vincent = payroll.mul_div(new_profit, percent, 10000) if new_profit > 0 and percent else 0
    helen_new = new_profit - vincent
    people = sorted(students.values(), key=lambda row: (not row['is_new'], row['name'], row['student_id']))
    for row in people:
        portion = _split(new_cost if row['is_new'] else original_cost, row['fee_cents'], new_fee if row['is_new'] else original_fee)
        row['cost_cents'] = portion
        row['profit_cents'] = row['fee_cents'] - row['pay_cents'] - portion
        if row['is_new'] and new_profit > 0:
            row['vincent_cents'] = _split(vincent, row['profit_cents'] if row['profit_cents'] > 0 else 0,
                sum(item['profit_cents'] for item in people if item['is_new'] and item['profit_cents'] > 0) or 1)
            row['helen_cents'] = row['profit_cents'] - row['vincent_cents']
        elif row['is_new']:
            row['vincent_cents'] = 0
            row['helen_cents'] = row['profit_cents']
        else:
            row['vincent_cents'] = 0
            row['helen_cents'] = row['profit_cents']
    month_rows = []
    for month in sorted(months):
        item = months[month]
        month_whole = item['new_fee_cents'] + item['original_fee_cents']
        item['cost_cents'] = _split(shared, month_whole, whole) if whole else 0
        item['new_cost_cents'] = _split(item['cost_cents'], item['new_fee_cents'], month_whole) if month_whole else 0
        item['new_profit_cents'] = item['new_fee_cents'] - item['new_pay_cents'] - item['new_cost_cents']
        item['vincent_cents'] = payroll.mul_div(item['new_profit_cents'], percent, 10000) if item['new_profit_cents'] > 0 and percent else 0
        item['helen_cents'] = (item['new_profit_cents'] - item['vincent_cents']) + (
            item['original_fee_cents'] - item['original_pay_cents'] - (item['cost_cents'] - item['new_cost_cents']))
        month_rows.append(item)
    costs = []
    for cost in partner['costs']:
        costs.append({**cost, 'new_cents': _split(cost['amount_cents'], new_fee, whole) if whole else 0,
            'original_cents': cost['amount_cents'] - (_split(cost['amount_cents'], new_fee, whole) if whole else 0),
            'method': '按新学生和原有学生的课酬比例分摊'})
    return {
        'period': period, 'start': start.isoformat(), 'end': end.isoformat(),
        'partner_name': partner['teacher_name'] or 'Vincent', 'percent_bp': percent,
        'new_fee_cents': new_fee, 'new_pay_cents': new_pay, 'new_cost_cents': new_cost, 'new_profit_cents': new_profit,
        'vincent_cents': vincent, 'helen_new_cents': helen_new,
        'original_fee_cents': original_fee, 'original_pay_cents': original_pay,
        'original_cost_cents': original_cost, 'original_profit_cents': original_profit,
        'helen_cents': helen_new + original_profit, 'allocation': '共同成本按课酬比例分给新学生和原有学生。老师课酬已从利润里减去，但不算进任何人的分红。',
        'students': people, 'months': month_rows, 'costs': costs,
        'rules': partner['rules'], 'roster': roster,
    }


def csv_bytes(data):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['开始', data['start'], '结束', data['end']])
    writer.writerow(['新学生课酬', data['new_fee_cents'] / 100, '老师课酬', data['new_pay_cents'] / 100,
        '分摊成本', data['new_cost_cents'] / 100, '新学生利润', data['new_profit_cents'] / 100])
    writer.writerow(['Vincent 分红', data['vincent_cents'] / 100, 'Helen 新学生', data['helen_new_cents'] / 100,
        'Helen 原有学生', data['original_profit_cents'] / 100, 'Helen 合计', data['helen_cents'] / 100])
    writer.writerow([])
    writer.writerow(['学生', '类型', '课酬', '老师课酬', '分摊成本', '利润', 'Vincent', 'Helen'])
    for row in data['students']:
        writer.writerow([row['name'], '新学生' if row['is_new'] else '原有学生', row['fee_cents'] / 100,
            row['pay_cents'] / 100, row['cost_cents'] / 100, row['profit_cents'] / 100,
            row['vincent_cents'] / 100, row['helen_cents'] / 100])
    writer.writerow([])
    writer.writerow(['月份', '新学生课酬', '原有课酬', '老师课酬', '成本', 'Vincent', 'Helen'])
    for row in data['months']:
        writer.writerow([row['month'], row['new_fee_cents'] / 100, row['original_fee_cents'] / 100,
            row['teacher_pay_cents'] / 100, row['cost_cents'] / 100, row['vincent_cents'] / 100, row['helen_cents'] / 100])
    return buffer.getvalue().encode('utf-8-sig')
