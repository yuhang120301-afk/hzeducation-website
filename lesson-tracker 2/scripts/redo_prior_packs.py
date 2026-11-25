#!/usr/bin/env python3
"""Put the right gift lessons back on every back-dated pack.

上课先扣付费课时，付费用完才扣赠送。补录已用课时也只扣付费，所以当时的赠课都还没用掉。
先用单据、audit_log 里记下的「还剩赠送」。没有记下的，用价目：一对一和一对二是 20 节送 1 节，
新加坡数学和学期班不送。两边都看不出来的，列成 UNKNOWN，不改。

收款、收钱日期、已用的付费课时不动。Dry-run 是默认。不要自己设置 LESSON_DB。

  python3 scripts/redo_prior_packs.py
  python3 scripts/redo_prior_packs.py --apply
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LESSON = 100
GIFT_RE = re.compile(r'还剩赠送\s*([0-9]+(?:\.[0-9]+)?)')


def connect(db_path):
    c = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c


def money(cents):
    if cents is None:
        return '—'
    cents = int(cents)
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}${cents // 100}.{cents % 100:02d}'


def lessons(units):
    units = int(units or 0)
    if units % LESSON == 0:
        return str(units // LESSON)
    return f'{units / LESSON:.2f}'


def _units_from_lessons(raw):
    try:
        number = Decimal(str(raw))
    except InvalidOperation:
        return None
    scaled = number * LESSON
    if scaled != scaled.to_integral_value() or scaled < 0 or scaled > 10000 * LESSON:
        return None
    return int(scaled)


def gift_rule(purchased, course, type_name, subject):
    """Catalog gift in lesson-units, or None when the price list does not say."""
    purchased = int(purchased or 0)
    if purchased <= 0 or purchased % LESSON:
        return None, '节数不是整节，无法对照价目'
    count = purchased // LESSON
    course = course or ''
    type_name = type_name or ''
    subject = subject or ''
    text = f'{course} {subject} {type_name}'
    if '新加坡' in text:
        return 0, '新加坡数学价目不送课'
    private = type_name in ('一对一', '一对二')
    term = type_name == '小班课' or '数学 + 英语' in course or '数学+英语' in course
    if term and not private:
        return 0, '学期班价目不送课'
    if private:
        if count == 20:
            return LESSON, '一对一和一对二价目：20 节送 1 节'
        return None, f'价目只有 20 节送 1 节，这包是 {count} 节，不猜测'
    return None, '看不出课型，无法对照价目'


def _columns(c, table):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return set()
    return {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}


def _gift_in_text(text):
    found = GIFT_RE.findall(text or '')
    if not found:
        return None
    units = _units_from_lessons(found[-1])
    if units is None:
        return None
    return units


def _audit_hits_pack(row, pack):
    try:
        ops = json.loads(row['ops_json'] or '[]')
    except json.JSONDecodeError:
        ops = []
    for op in ops:
        after = op.get('after') or {}
        before = op.get('before') or {}
        table = op.get('table')
        if table == 'credit_batches' and (after.get('id') == pack['id'] or after.get('ledger_id') == pack['ledger_id'] or before.get('id') == pack['id']):
            return True
        if table == 'ledger' and (after.get('id') == pack['ledger_id'] or before.get('id') == pack['ledger_id']):
            return True
    return False


def logged_gift(c, pack, audits, events_by_student, prior_counts):
    """Gift units written down for this pack, or None."""
    noted = _gift_in_text(pack.get('note'))
    if noted is not None:
        return noted, '单据备注里的还剩赠送'
    matched = []
    for row in audits:
        if not _audit_hits_pack(row, pack):
            continue
        units = _gift_in_text(row['summary'])
        if units is not None:
            matched.append(units)
    if matched:
        if len(set(matched)) > 1:
            return None, 'audit_log 里的赠课不一致'
        return matched[-1], 'audit_log 里的还剩赠送'
    if prior_counts.get(pack['student_id']) == 1:
        ev = events_by_student.get(pack['student_id']) or []
        numbers = [item for item in ev if item is not None]
        if len(numbers) == 1:
            return numbers[0], '学生记录里的还剩赠送'
        if len(set(numbers)) > 1:
            return None, '学生记录里的赠课不一致'
    return None, None


def load_packs(c):
    batch_cols = _columns(c, 'credit_batches')
    status = 'b.status' if 'status' in batch_cols else "''"
    fees = 'b.unit_fees' if 'unit_fees' in batch_cols else "''"
    total = 'b.total_cents' if 'total_cents' in batch_cols else 'NULL'
    student_cols = _columns(c, 'students')
    type_name = 'ct.name' if 'course_type_id' in student_cols else "''"
    subject = 'sj.name' if 'subject_id' in student_cols else "''"
    join_type = 'LEFT JOIN course_types ct ON ct.id=s.course_type_id' if type_name != "''" else ''
    join_subject = 'LEFT JOIN subjects sj ON sj.id=s.subject_id' if subject != "''" else ''
    rows = c.execute(f'''SELECT b.id, b.student_id, b.ledger_id, b.purchased, b.gifted, b.paid_left, b.gift_left,
            {total} AS total_cents, {fees} AS unit_fees, {status} AS status,
            l.lesson_date, l.note, s.name AS student, s.course,
            {type_name} AS type_name, {subject} AS subject,
            cash.cash_delta
        FROM credit_batches b
        JOIN ledger l ON l.id=b.ledger_id
        JOIN students s ON s.id=b.student_id
        {join_type}
        {join_subject}
        LEFT JOIN cash_entries cash ON cash.ledger_id=l.id
        WHERE l.kind='credit' AND l.note LIKE '%补录%'
        ORDER BY l.lesson_date, b.id''').fetchall()
    return [dict(row) for row in rows]


def _context(c, packs):
    audits = []
    if _columns(c, 'audit_log'):
        audits = [dict(row) for row in c.execute("SELECT summary, ops_json FROM audit_log WHERE summary LIKE '%还剩赠送%'")]
    events_by_student = {}
    if _columns(c, 'profile_events'):
        for row in c.execute("SELECT student_id, summary FROM profile_events WHERE summary LIKE '%还剩赠送%'"):
            events_by_student.setdefault(row['student_id'], []).append(_gift_in_text(row['summary']))
    counts = {}
    for pack in packs:
        counts[pack['student_id']] = counts.get(pack['student_id'], 0) + 1
    return audits, events_by_student, counts


def plan_pack(c, pack, audits, events_by_student, counts):
    logged, logged_source = logged_gift(c, pack, audits, events_by_student, counts)
    catalog, catalog_source = gift_rule(pack['purchased'], pack['course'], pack['type_name'], pack['subject'])
    item = dict(pack)
    item['add_units'] = 0
    status = pack.get('status') or ''
    if status in ('voided', 'switched'):
        item['action'] = 'skip'
        item['target'] = None
        item['source'] = '这包已作废或已换走，不补'
        return item
    if logged_source and logged is None and '不一致' in logged_source:
        item['action'] = 'unknown'
        item['target'] = None
        item['source'] = logged_source
        return item
    if logged is not None:
        target, source = logged, logged_source
    elif catalog is not None:
        target, source = catalog, catalog_source
    else:
        item['action'] = 'unknown'
        item['target'] = None
        item['source'] = catalog_source
        return item
    gifted = int(pack['gifted'] or 0)
    item['target'] = target
    item['source'] = source
    if gifted == target:
        item['action'] = 'skip'
        item['source'] = source + '，已经是这个数'
        return item
    if gifted > target:
        item['action'] = 'skip'
        item['source'] = f"已有赠课 {lessons(gifted)} 节，多于要补的 {lessons(target)} 节，不减少"
        return item
    item['action'] = 'add'
    item['add_units'] = target - gifted
    return item


def plan(c):
    packs = load_packs(c)
    audits, events_by_student, counts = _context(c, packs)
    return [plan_pack(c, pack, audits, events_by_student, counts) for pack in packs]


def _cell(value, width):
    text = str(value)
    return text + ' ' * max(0, width - len(text))


def render(items, apply):
    headers = ['学生', '课程', '收钱日期', '金额', '总节数', '剩余付费', '现在赠送', '应有赠送', '本次补上', '依据']
    body = []
    for item in items:
        cents = item['cash_delta'] if item['cash_delta'] is not None else item['total_cents']
        target = 'UNKNOWN' if item['target'] is None else lessons(item['target'])
        body.append([
            item['student'], item['course'], item['lesson_date'] or '', money(cents),
            lessons(item['purchased']), lessons(item['paid_left']), lessons(item['gifted']),
            target, lessons(item['add_units']), item['source'],
        ])
    widths = [len(header) for header in headers]
    for row in body:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ['APPLY' if apply else 'DRY-RUN', '  '.join(_cell(header, widths[i]) for i, header in enumerate(headers))]
    lines.append('  '.join('-' * width for width in widths))
    lines.extend('  '.join(_cell(cell, widths[i]) for i, cell in enumerate(row)) for row in body)
    if not body:
        lines.append('没有找到补录的课时包。')
    unknown = [item for item in items if item['action'] == 'unknown']
    lines.append('')
    if unknown:
        lines.append('UNKNOWN，这些包没有改动：')
        for item in unknown:
            lines.append(f"  #{item['id']} {item['student']} · {item['course']} · {item['source']}")
    else:
        lines.append('没有 UNKNOWN。')
    adding = [item for item in items if item['action'] == 'add' and item['add_units']]
    total = sum(item['add_units'] for item in adding)
    lines.append(f"本次补上 {lessons(total)} 节赠课，共 {len(adding)} 包。收款、收钱日期、已用付费课时不变。")
    lines.append('上课先扣付费课时，付费用完才扣赠送。补录已用课时只扣付费，所以补的是当时的全部赠课。')
    if apply:
        lines.append('已写入。')
    else:
        lines.append('未写入。加上 --apply 才会改。')
    return '\n'.join(lines)


def _owner(c):
    row = c.execute('SELECT user_id FROM organization_owners ORDER BY user_id LIMIT 1').fetchone()
    if not row:
        raise SystemExit('没有老板账号，不能写入。')
    return {'id': row['user_id'], 'role': 'owner'}


def _apply_one(c, item):
    units = int(item['add_units'])
    c.execute('UPDATE credit_batches SET gifted=gifted+?, gift_left=gift_left+? WHERE id=?', (units, units, item['id']))
    if str(item.get('unit_fees') or '').strip():
        c.execute("UPDATE credit_batches SET unit_fees='' WHERE id=?", (item['id'],))
    moved = c.execute('SELECT gift FROM credit_movements WHERE ledger_id=? AND batch_id=?',
        (item['ledger_id'], item['id'])).fetchone()
    if moved:
        c.execute('UPDATE credit_movements SET gift=gift+? WHERE ledger_id=? AND batch_id=?',
            (units, item['ledger_id'], item['id']))
    else:
        c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,0,?,0)',
            (item['ledger_id'], item['id'], units))
    c.execute('UPDATE ledger SET delta=delta+?, gift_delta=COALESCE(gift_delta,0)+?, split_known=1 WHERE id=?',
        (units, units, item['ledger_id']))
    c.execute('UPDATE students SET balance=balance+? WHERE id=?', (units, item['student_id']))
    if _columns(c, 'vouchers'):
        c.execute('UPDATE vouchers SET gift_units=gift_units+? WHERE ledger_id=?', (units, item['ledger_id']))


def apply_plan(c, items, user):
    import auditlog
    adding = [item for item in items if item['action'] == 'add' and item['add_units']]
    if not adding:
        return 0
    before_cash = c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0]
    before_balance = c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0]
    before_paid = {row['id']: row['paid_left'] for row in c.execute('SELECT id, paid_left FROM credit_batches')}
    before_dates = {row['id']: row['lesson_date'] for row in c.execute('SELECT id, lesson_date FROM ledger')}
    units = sum(item['add_units'] for item in adding)
    for item in adding:
        auditlog.begin(c)
        auditlog.hint(c, f"补上补录赠课 {item['student']} {item['course']} {lessons(item['add_units'])} 节")
        _apply_one(c, item)
        auditlog.finish(c, user)
    after_cash = c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0]
    after_balance = c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0]
    after_paid = {row['id']: row['paid_left'] for row in c.execute('SELECT id, paid_left FROM credit_batches')}
    after_dates = {row['id']: row['lesson_date'] for row in c.execute('SELECT id, lesson_date FROM ledger')}
    if after_cash != before_cash:
        raise RuntimeError('收款数字变了，已停止。')
    if after_balance != before_balance + units:
        raise RuntimeError('余额增加和补上的赠课不一致，已停止。')
    if after_paid != before_paid or after_dates != before_dates:
        raise RuntimeError('已用课时或收钱日期变了，已停止。')
    return len(adding)


def main():
    parser = argparse.ArgumentParser(description='Restore gift lessons on back-dated packs.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    import auditlog
    import credit_batches
    c = connect(args.db)
    try:
        credit_batches.schema(c)
        auditlog.schema(c)
        items = plan(c)
        if args.apply:
            user = _owner(c)
            c.execute('BEGIN IMMEDIATE')
            apply_plan(c, items, user)
            c.execute('COMMIT')
        print(render(items, args.apply))
        print(f"database={os.path.realpath(args.db)}")
    except BaseException:
        if c.in_transaction:
            c.execute('ROLLBACK')
        raise


if __name__ == '__main__':
    main()
