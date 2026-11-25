#!/usr/bin/env python3
"""Remove empty test courses left by the 2027 reset, and empty duplicate rows.

Dry-run is the default. Uses LESSON_DB. One transaction on --apply.
Do not point this at production until there is a backup.

  LESSON_DB="$LESSON_DB" python3 scripts/cleanup_merged_test_traces.py
  LESSON_DB="$LESSON_DB" python3 scripts/cleanup_merged_test_traces.py --apply

The profile row is kept when a course row is removed. Atticus's taught
history on #46 and #66 is not touched. Claire #69 is only reported.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EMPTY_COURSES = (
    (4, 'atticus', '英语'),
    (26, 'bryce', '数学'),
)
SKIP_COURSES = ((69, 'claire', '数学'),)
AMELIA_ID = 93
AMELIA_LEDGERS = (
    (108, 3700, '学期班 · 每节 2.5 小时 · 37 节'),
    (118, -3700, '作废单据 CZ-2026-0007'),
)
CONFIRM_IDS = ((1, 'austin hao'), (28, 'benjamin'))
PROTECTED_IDS = {1, 28, 46, 66, 69, 93}


def connect(db_path, write):
    if write:
        c = sqlite3.connect(db_path, timeout=30)
        c.execute('PRAGMA foreign_keys=ON')
    else:
        c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
        c.execute('PRAGMA query_only=ON')
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    return c


def has_table(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def columns(c, table):
    if not has_table(c, table):
        return set()
    return {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}


def money_totals(c):
    payments = 0
    balances = 0
    if has_table(c, 'cash_entries'):
        payments = c.execute('SELECT COALESCE(SUM(cash_delta),0) n FROM cash_entries').fetchone()['n']
    if has_table(c, 'students'):
        balances = c.execute('SELECT COALESCE(SUM(balance),0) n FROM students').fetchone()['n']
    return int(payments), int(balances)


def norm(value):
    return ' '.join(str(value or '').strip().casefold().split())


def student_row(c, student_id):
    if not has_table(c, 'students'):
        return None
    return c.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()


def count_where(c, table, column, value):
    if not has_table(c, table) or column not in columns(c, table):
        return 0
    return int(c.execute(f'SELECT COUNT(*) n FROM {table} WHERE {column}=?', (value,)).fetchone()['n'])


def lesson_rows(c, student_id):
    if not has_table(c, 'lesson_students') or not has_table(c, 'lessons'):
        return []
    return c.execute('''SELECT l.* FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE ls.student_id=? ORDER BY l.id''', (student_id,)).fetchall()


def future_lesson_count(c, student_id, today):
    return sum(1 for lesson in lesson_rows(c, student_id)
        if lesson['status'] != 'cancelled' and str(lesson['starts_at'] or '')[:10] >= today)


def batch_is_empty(row):
    names = row.keys()
    for name in ('purchased', 'gifted', 'paid_left', 'gift_left', 'total_cents', 'receivable_cents', 'paid_cents'):
        if name in names and int(row[name] or 0) != 0:
            return False
    return True


def course_block(c, row):
    student_id = row['id']
    if count_where(c, 'lesson_reports', 'student_id', student_id):
        return '有课后记录'
    if count_where(c, 'ledger', 'student_id', student_id):
        return '有账'
    if int(row['balance'] or 0) != 0:
        return '余额不是 0'
    lessons = lesson_rows(c, student_id)
    if any(lesson['status'] != 'cancelled' for lesson in lessons):
        return '有没取消的课'
    if has_table(c, 'credit_batches'):
        for batch in c.execute('SELECT * FROM credit_batches WHERE student_id=?', (student_id,)):
            if not batch_is_empty(batch):
                return '课时包不是空的'
    if count_where(c, 'vouchers', 'student_id', student_id):
        return '有单据'
    if count_where(c, 'arrears', 'student_id', student_id):
        return '有欠费'
    return ''


def identity_ok(row, name, course_bit):
    got = norm(row['name'])
    if got != name and not got.startswith(name + ' '):
        return False
    return course_bit in norm(row['course'])


def plan_empty_courses(c):
    actions = []
    for student_id, name, course_bit in EMPTY_COURSES:
        row = student_row(c, student_id)
        if not row:
            actions.append({'id': student_id, 'action': 'missing', 'detail': '没有这一行'})
            continue
        if not identity_ok(row, name, course_bit):
            actions.append({'id': student_id, 'action': 'skip', 'name': row['name'], 'course': row['course'],
                'detail': '姓名或课程对不上，不删'})
            continue
        reason = course_block(c, row)
        if reason:
            actions.append({'id': student_id, 'action': 'skip', 'name': row['name'], 'course': row['course'],
                'detail': reason})
            continue
        actions.append({'id': student_id, 'action': 'delete', 'name': row['name'], 'course': row['course'],
            'detail': '空课，删除课程行'})
    for student_id, name, course_bit in SKIP_COURSES:
        row = student_row(c, student_id)
        if not row:
            actions.append({'id': student_id, 'action': 'skip', 'detail': 'Claire 这一行已经不在，仍不处理'})
            continue
        actions.append({'id': student_id, 'action': 'skip', 'name': row['name'], 'course': row['course'],
            'detail': 'Helen 还没确认，先留着'})
    return actions


def plan_amelia(c):
    row = student_row(c, AMELIA_ID)
    if not row:
        return {'action': 'missing', 'detail': '没有 Amelia 的课程行 #93'}
    if 'amelia' not in norm(row['name']) or '数学' not in norm(row['course']):
        return {'action': 'skip', 'detail': f"#{AMELIA_ID} 不是 Amelia 的数学课（{row['name']} {row['course']}）"}
    found = []
    for ledger_id, delta, note in AMELIA_LEDGERS:
        item = c.execute('SELECT * FROM ledger WHERE id=?', (ledger_id,)).fetchone() if has_table(c, 'ledger') else None
        if not item:
            return {'action': 'skip', 'detail': f'账本 #{ledger_id} 不在'}
        if int(item['student_id']) != AMELIA_ID or int(item['delta']) != delta or not str(item['note'] or '').startswith(note):
            return {'action': 'skip', 'detail': f'账本 #{ledger_id} 的学生、金额或备注对不上'}
        found.append(item)
    if 'reversal_of' in columns(c, 'ledger') and found[1]['reversal_of'] not in (None, found[0]['id']):
        return {'action': 'skip', 'detail': '作废账没有指向原来的充值'}
    if sum(int(item['delta']) for item in found) != 0:
        return {'action': 'skip', 'detail': '这两笔账加起来不是 0'}
    ids = [item['id'] for item in found]
    marks = ','.join('?' for _ in ids)
    cash = 0
    if has_table(c, 'cash_entries'):
        cash = int(c.execute(f'SELECT COALESCE(SUM(cash_delta),0) n FROM cash_entries WHERE ledger_id IN ({marks})', ids).fetchone()['n'])
    if cash != 0:
        return {'action': 'skip', 'detail': '这两笔账上的收款加起来不是 0'}
    if has_table(c, 'lesson_reports') and 'ledger_id' in columns(c, 'lesson_reports'):
        if c.execute(f'SELECT 1 FROM lesson_reports WHERE ledger_id IN ({marks})', ids).fetchone():
            return {'action': 'skip', 'detail': '这两笔账还挂在课后记录上'}
    return {'action': 'delete', 'ids': ids, 'detail': '两笔互相对冲的测试账，删除', 'balance': int(row['balance'] or 0)}


def describe_person(c, student_id, today):
    row = student_row(c, student_id)
    if not row:
        return {'id': student_id, 'missing': True, 'detail': '没有这一行'}
    reports = count_where(c, 'lesson_reports', 'student_id', student_id)
    ledger = count_where(c, 'ledger', 'student_id', student_id)
    lessons = lesson_rows(c, student_id)
    return {'id': student_id, 'missing': False, 'name': row['name'], 'course': row['course'],
        'reports': reports, 'ledger': ledger, 'lessons': len(lessons),
        'future': future_lesson_count(c, student_id, today), 'balance': int(row['balance'] or 0),
        'detail': '没有多余记录' if not reports and not ledger and not lessons else '有记录，未改动'}


def stats_for(c, row, today):
    student_id = row['id']
    return {'id': student_id, 'name': row['name'], 'course': row['course'],
        'archived': int(row['archived'] or 0), 'voided': int(row['voided'] or 0) if 'voided' in row.keys() else 0,
        'reports': count_where(c, 'lesson_reports', 'student_id', student_id),
        'ledger': count_where(c, 'ledger', 'student_id', student_id),
        'lessons': len(lesson_rows(c, student_id)),
        'non_cancelled': sum(1 for lesson in lesson_rows(c, student_id) if lesson['status'] != 'cancelled'),
        'future': future_lesson_count(c, student_id, today),
        'balance': int(row['balance'] or 0)}


def row_has_data(item):
    return item['reports'] or item['ledger'] or item['non_cancelled'] or item['balance']


def plan_duplicates(c, today, dropping):
    if not has_table(c, 'students'):
        return [], []
    rows = [row for row in c.execute('SELECT * FROM students ORDER BY id') if row['id'] not in dropping]
    by_course = {}
    by_name = {}
    for row in rows:
        item = stats_for(c, row, today)
        by_course.setdefault((norm(row['name']), norm(row['course'])), []).append(item)
        by_name.setdefault(norm(row['name']), []).append(item)
    same_course = []
    for group in by_course.values():
        if len(group) < 2 or not group[0]['name']:
            continue
        keepers = [item for item in group if row_has_data(item)]
        if not keepers:
            enrolled = [item for item in group if not item['archived'] and not item['voided']]
            if enrolled:
                keepers = [min(enrolled, key=lambda item: item['id'])]
        keeper_ids = {item['id'] for item in keepers}
        for item in group:
            empty = not row_has_data(item)
            if empty and item['id'] not in keeper_ids and keeper_ids and item['id'] not in PROTECTED_IDS:
                item['action'] = 'delete'
                item['detail'] = '空的重复课程行'
            else:
                item['action'] = 'keep'
                item['detail'] = '有记录或是留下的那一行' if row_has_data(item) or item['id'] in keeper_ids else '受保护，不删'
        same_course.append(group)
    different = []
    for name, group in by_name.items():
        courses = {norm(item['course']) for item in group}
        if name and len(group) > 1 and len(courses) > 1:
            different.append(group)
    return same_course, different


def build_plan(c, today):
    courses = plan_empty_courses(c)
    dropping = {item['id'] for item in courses if item['action'] == 'delete'}
    return {'courses': courses, 'amelia': plan_amelia(c),
        'confirm': [describe_person(c, student_id, today) for student_id, _name in CONFIRM_IDS],
        'same_course': plan_duplicates(c, today, dropping)[0],
        'different_course': plan_duplicates(c, today, dropping)[1]}


def _delete_where(c, table, column, value):
    if has_table(c, table) and column in columns(c, table):
        c.execute(f'DELETE FROM {table} WHERE {column}=?', (value,))


def _delete_lesson(c, lesson_id):
    for table in ('lesson_students', 'lesson_reports', 'report_edits', 'arrears', 'lesson_absence_charges'):
        _delete_where(c, table, 'lesson_id', lesson_id)
    if 'series_id' in columns(c, 'lessons'):
        c.execute('UPDATE lessons SET series_id=NULL WHERE id=?', (lesson_id,))
    c.execute('DELETE FROM lessons WHERE id=?', (lesson_id,))


def delete_course_row(c, student_id):
    import profiles
    profiles.remember_person(c, student_id)
    for lesson in list(lesson_rows(c, student_id)):
        others = c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id!=?',
            (lesson['id'], student_id)).fetchone()
        if others or lesson['status'] != 'cancelled':
            c.execute('DELETE FROM lesson_students WHERE lesson_id=? AND student_id=?', (lesson['id'], student_id))
            continue
        _delete_lesson(c, lesson['id'])
    if has_table(c, 'credit_batches'):
        batches = [row['id'] for row in c.execute('SELECT id FROM credit_batches WHERE student_id=?', (student_id,))]
        for batch_id in batches:
            if has_table(c, 'credit_movements'):
                c.execute('DELETE FROM credit_movements WHERE batch_id=?', (batch_id,))
            if has_table(c, 'pack_payments'):
                c.execute('DELETE FROM pack_payments WHERE batch_id=?', (batch_id,))
            c.execute('DELETE FROM credit_batches WHERE id=?', (batch_id,))
    for table, column in (
        ('lesson_students', 'student_id'), ('lesson_reports', 'student_id'),
        ('lesson_absence_charges', 'student_id'), ('arrears', 'student_id'),
        ('profile_events', 'student_id'), ('profile_audit', 'student_id'),
        ('vouchers', 'student_id'),
    ):
        _delete_where(c, table, column, student_id)
    c.execute('DELETE FROM students WHERE id=?', (student_id,))


def delete_ledger_pair(c, ledger_ids):
    marks = ','.join('?' for _ in ledger_ids)
    batch_ids = []
    if has_table(c, 'credit_batches') and 'ledger_id' in columns(c, 'credit_batches'):
        batch_ids = [row['id'] for row in c.execute(
            f'SELECT id FROM credit_batches WHERE ledger_id IN ({marks})', ledger_ids)]
    if has_table(c, 'credit_movements'):
        c.execute(f'DELETE FROM credit_movements WHERE ledger_id IN ({marks})', ledger_ids)
        for batch_id in batch_ids:
            c.execute('DELETE FROM credit_movements WHERE batch_id=?', (batch_id,))
    if has_table(c, 'pack_payments'):
        if 'ledger_id' in columns(c, 'pack_payments'):
            c.execute(f'DELETE FROM pack_payments WHERE ledger_id IN ({marks})', ledger_ids)
        for batch_id in batch_ids:
            c.execute('DELETE FROM pack_payments WHERE batch_id=?', (batch_id,))
    if has_table(c, 'ledger_edits'):
        c.execute(f'DELETE FROM ledger_edits WHERE ledger_id IN ({marks})', ledger_ids)
    if has_table(c, 'cash_entries'):
        c.execute(f'DELETE FROM cash_entries WHERE ledger_id IN ({marks})', ledger_ids)
    if has_table(c, 'vouchers'):
        if 'ledger_id' in columns(c, 'vouchers'):
            c.execute(f'UPDATE vouchers SET ledger_id=NULL WHERE ledger_id IN ({marks})', ledger_ids)
        if 'reversal_ledger_id' in columns(c, 'vouchers'):
            c.execute(f'UPDATE vouchers SET reversal_ledger_id=NULL WHERE reversal_ledger_id IN ({marks})', ledger_ids)
    for batch_id in batch_ids:
        c.execute('DELETE FROM credit_batches WHERE id=?', (batch_id,))
    if 'reversal_of' in columns(c, 'ledger'):
        c.execute(f'UPDATE ledger SET reversal_of=NULL WHERE reversal_of IN ({marks})', ledger_ids)
    for ledger_id in sorted(ledger_ids, reverse=True):
        c.execute('DELETE FROM ledger WHERE id=?', (ledger_id,))


def apply_plan(c, plan):
    for item in plan['courses']:
        if item['action'] == 'delete':
            delete_course_row(c, item['id'])
    amelia = plan['amelia']
    if amelia['action'] == 'delete':
        before = amelia['balance']
        delete_ledger_pair(c, amelia['ids'])
        after = int(c.execute('SELECT COALESCE(SUM(delta),0) n FROM ledger WHERE student_id=?', (AMELIA_ID,)).fetchone()['n'])
        if after != before:
            raise RuntimeError(f'Amelia 余额对不上：之前 {before}，按账本重算 {after}')
        c.execute('UPDATE students SET balance=? WHERE id=?', (after, AMELIA_ID))
    for group in plan['same_course']:
        for item in group:
            if item['action'] == 'delete':
                delete_course_row(c, item['id'])


def render(db_path, apply, plan, before, after):
    lines = [f"{'APPLY' if apply else 'DRY-RUN'}  database={os.path.realpath(db_path)}",
        f'payments_before={before[0]} balances_before={before[1]}']
    deleted = [item for item in plan['courses'] if item['action'] == 'delete']
    skipped = [item for item in plan['courses'] if item['action'] != 'delete']
    lines.append(f"courses_delete={len(deleted)} courses_skip={len(skipped)}")
    lines.append('空课：')
    for item in plan['courses']:
        who = f"{item.get('name') or ''} {item.get('course') or ''}".strip()
        lines.append(f"  #{item['id']} {who} {item['detail']}")
    amelia = plan['amelia']
    lines.append(f"amelia_ledgers={'delete' if amelia['action']=='delete' else 'skip'} {amelia['detail']}")
    lines.append('确认没有多余记录：')
    for item in plan['confirm']:
        if item['missing']:
            lines.append(f"  #{item['id']} {item['detail']}")
        else:
            lines.append(f"  #{item['id']} {item['name']} {item['course']} 课后{item['reports']} 账{item['ledger']} 课{item['lessons']} {item['detail']}")
    dup_delete = sum(1 for group in plan['same_course'] for item in group if item['action'] == 'delete')
    lines.append(f"duplicate_groups={len(plan['same_course'])} duplicate_delete={dup_delete}")
    lines.append('同名同课：')
    if not plan['same_course']:
        lines.append('  没有')
    for group in plan['same_course']:
        lines.append(f"  {group[0]['name']} · {group[0]['course']}")
        for item in group:
            lines.append(f"    #{item['id']} archived={item['archived']} voided={item['voided']} "
                f"课后{item['reports']} 账{item['ledger']} 课{item['lessons']} 以后{item['future']} "
                f"余额{item['balance']} {item['detail']}")
    lines.append('同名不同课（只报告）：')
    if not plan['different_course']:
        lines.append('  没有')
    for group in plan['different_course']:
        lines.append(f"  {group[0]['name']}")
        for item in group:
            lines.append(f"    #{item['id']} {item['course']} archived={item['archived']} 课后{item['reports']} 账{item['ledger']} 课{item['lessons']}")
    if apply:
        lines.append(f'payments_after={after[0]} balances_after={after[1]}')
        lines.append('已写入。档案行没有删除。')
    else:
        lines.append('未写入。')
    return lines


def main():
    parser = argparse.ArgumentParser(description='Clean empty courses left after the 2027 reset.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--today', default='')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    from teaching import now_local
    today = args.today or now_local().date().isoformat()
    c = connect(args.db, args.apply)
    try:
        if args.apply:
            c.execute('BEGIN IMMEDIATE')
        before = money_totals(c)
        plan = build_plan(c, today)
        after = before
        if args.apply:
            apply_plan(c, plan)
            after = money_totals(c)
            if after != before:
                raise RuntimeError(f'钱对不上：之前 {before}，之后 {after}')
            c.commit()
        print('\n'.join(render(args.db, args.apply, plan, before, after)))
    except BaseException:
        if args.apply:
            c.rollback()
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
