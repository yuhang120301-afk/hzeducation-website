"""Partner profit share. Same numbers as the finance institution cards.

机构利润 = 机构收入 − 机构成本. Vincent's share is that profit times his percent,
including a loss. Helen's share is the rest, so the two always add up.
A ticked student's maths lessons are left out. Their other lessons stay in.
"""
import calendar
import csv
import datetime as dt
import io

import payroll
from teaching import now_local


def _months(c, lessons, start, end, rules):
    rows = []
    cursor = start.replace(day=1)
    while cursor <= end:
        last = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = cursor.replace(day=last)
        window_start = max(start, cursor)
        window_end = min(end, month_end)
        month_lessons = [lesson for lesson in lessons if window_start.isoformat() <= lesson['date'] <= window_end.isoformat()]
        pieces = []
        revenue = 0
        for lesson in month_lessons:
            percent = payroll.percent_bp_on(rules, lesson['date'])
            for line in lesson['lines']:
                if not payroll.counts_for_institution(line):
                    continue
                if line['fee_known']:
                    revenue += line['fee_cents'] or 0
                    pieces.append((line['fee_cents'] or 0, percent))
                pay = int(line.get('pay_cents') or 0)
                if pay:
                    pieces.append((-pay, percent))
        cost, details = payroll.costs_for(c, window_start, window_end, shared_only=True)
        wage, _, _helen = payroll.institution_wage_costs(month_lessons)
        free, free_details = payroll.free_lesson_wage_costs(month_lessons)
        for item in list(details) + free_details:
            day = str(item.get('date') or window_start.isoformat())
            if day < window_start.isoformat():
                day = window_start.isoformat()
            pieces.append((-int(item['amount_cents'] or 0), payroll.percent_bp_on(rules, day)))
        remainder = revenue - cost - wage - free
        share = payroll.share_of_pieces(pieces)
        if revenue or cost or wage or free:
            rows.append({'month': cursor.strftime('%Y-%m'), 'revenue_cents': revenue,
                'cost_cents': cost + wage + free, 'profit_cents': remainder,
                'share_cents': share, 'helen_share_cents': remainder - share})
        cursor = month_end + dt.timedelta(days=1)
    return rows


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
    view = payroll.public_profit_share(partner)
    percent = partner['percent_bp'] or 0
    profit = partner['remainder_cents']
    helen_share = partner['helen_share_cents']
    students = {}
    for line in view['lines']:
        row = students.setdefault(line['student_name'], {'name': line['student_name'], 'revenue_cents': 0, 'share_cents': 0, 'lessons': 0})
        if line['fee_known']:
            row['revenue_cents'] += line['revenue_cents'] or 0
        row['share_cents'] += line['share_cents']
        row['lessons'] += 1
    since = payroll.origin_since_by_profile(c)
    roster = []
    for row in c.execute('''SELECT id, profile_id, name, course, helen_original, archived
        FROM students ORDER BY name, course, id'''):
        item = dict(row)
        item['is_new'] = payroll.student_is_new(row['helen_original'])
        item['origin_since'] = since.get(row['profile_id'])
        roster.append(item)
    return {
        'period': period, 'start': start.isoformat(), 'end': end.isoformat(),
        'partner_name': partner['teacher_name'] or 'Vincent', 'percent_bp': percent,
        'revenue_cents': partner['revenue_cents'], 'cost_cents': partner['shared_cost_cents'],
        'profit_cents': profit, 'share_cents': partner['share_cents'], 'helen_share_cents': helen_share,
        'lines': view['lines'], 'costs': view['costs'],
        'students': sorted(students.values(), key=lambda row: (row['name'],)),
        'months': _months(c, lessons, start, end, partner['rules']),
        'roster': roster, 'rules': partner['rules'],
    }


def csv_bytes(data):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['开始', data['start'], '结束', data['end']])
    writer.writerow(['机构收入', data['revenue_cents'] / 100, '机构成本', data['cost_cents'] / 100,
        '机构利润', data['profit_cents'] / 100])
    writer.writerow(['Vincent 分红', data['share_cents'] / 100, '我的机构分成', data['helen_share_cents'] / 100])
    writer.writerow([])
    writer.writerow(['日期', '学生', '课程', '收入', 'Vincent 分红'])
    for line in data['lines']:
        writer.writerow([line['date'], line['student_name'], line['lesson'],
            '' if not line['fee_known'] else line['revenue_cents'] / 100, line['share_cents'] / 100])
    writer.writerow([])
    writer.writerow(['日期', '成本', '金额'])
    for cost in data['costs']:
        writer.writerow([cost['date'], cost['label'], cost['amount_cents'] / 100])
    return buffer.getvalue().encode('utf-8-sig')
