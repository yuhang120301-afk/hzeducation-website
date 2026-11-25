#!/usr/bin/env python3
"""Clear the calendar from 1 December 2026 and fold stopped courses.

Dry-run is the default. Uses LESSON_DB. One transaction on --apply.
Do not point this at production until there is a backup.

  LESSON_DB="$LESSON_DB" python3 scripts/reset_for_2027_reentry.py
  LESSON_DB="$LESSON_DB" python3 scripts/reset_for_2027_reentry.py --apply

Lessons on or after 2026-12-01 are deleted when they have no class report
and no ledger row (scheduled, cancelled and unbilled, or otherwise empty).
Lessons that do have a report or a ledger stay, and are listed.
Every repeating-series row is deleted. Remaining lessons keep their history
with series_id cleared.

A stopped or voided course with no taught lesson, no ledger, no payment,
no pack, no voucher and no balance is deleted. One that has money or taught
history is merged onto the profile's active course, or reopened when it is
the only course. Profiles, parents, guardians, teachers and 2026 history stay.
The sum of payments and the sum of balances must match before and after.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CUTOFF = '2026-12-01'


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


def money_totals(c):
    payments = 0
    balances = 0
    if has_table(c, 'cash_entries'):
        payments = c.execute('SELECT COALESCE(SUM(cash_delta),0) n FROM cash_entries').fetchone()['n']
    if has_table(c, 'students'):
        balances = c.execute('SELECT COALESCE(SUM(balance),0) n FROM students').fetchone()['n']
    return int(payments), int(balances)


def lesson_keep_reason(c, lesson_id):
    """A report or a ledger row keeps the lesson. Empty text means it can go."""
    if has_table(c, 'lesson_reports') and c.execute(
            'SELECT 1 FROM lesson_reports WHERE lesson_id=?', (lesson_id,)).fetchone():
        return '有课后记录'
    if has_table(c, 'lesson_reports') and c.execute(
            'SELECT 1 FROM lesson_reports WHERE lesson_id=? AND ledger_id IS NOT NULL', (lesson_id,)).fetchone():
        return '有账'
    if has_table(c, 'lesson_absence_charges') and c.execute(
            'SELECT 1 FROM lesson_absence_charges WHERE lesson_id=?', (lesson_id,)).fetchone():
        return '有账'
    return ''


def has_taught_history(c, student_id, dropping_lessons):
    if has_table(c, 'lesson_reports') and c.execute(
            'SELECT 1 FROM lesson_reports WHERE student_id=?', (student_id,)).fetchone():
        return True
    if not has_table(c, 'lessons'):
        return False
    skip = ''
    params = [student_id]
    if dropping_lessons:
        skip = f" AND l.id NOT IN ({','.join('?' for _ in dropping_lessons)})"
        params.extend(dropping_lessons)
    row = c.execute(f'''SELECT 1 FROM lesson_students ls
        JOIN lessons l ON l.id=ls.lesson_id
        WHERE ls.student_id=? AND l.status='completed'{skip}''', params).fetchone()
    return row is not None


def has_money(c, student_id):
    if has_table(c, 'ledger') and c.execute(
            'SELECT 1 FROM ledger WHERE student_id=?', (student_id,)).fetchone():
        return True
    if has_table(c, 'credit_batches') and c.execute(
            'SELECT 1 FROM credit_batches WHERE student_id=?', (student_id,)).fetchone():
        return True
    if has_table(c, 'vouchers') and c.execute(
            'SELECT 1 FROM vouchers WHERE student_id=?', (student_id,)).fetchone():
        return True
    if has_table(c, 'pack_payments') and has_table(c, 'credit_batches') and c.execute(
            '''SELECT 1 FROM pack_payments p JOIN credit_batches b ON b.id=p.batch_id
               WHERE b.student_id=?''', (student_id,)).fetchone():
        return True
    if has_table(c, 'cash_entries') and has_table(c, 'ledger') and c.execute(
            '''SELECT 1 FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id
               WHERE l.student_id=?''', (student_id,)).fetchone():
        return True
    balance = c.execute('SELECT balance FROM students WHERE id=?', (student_id,)).fetchone()
    return bool(balance and int(balance['balance'] or 0) != 0)


def active_target(c, source):
    if not source['profile_id']:
        return None
    rows = c.execute('''SELECT * FROM students
        WHERE profile_id=? AND id!=? AND archived=0 AND IFNULL(voided,0)=0
        ORDER BY CASE WHEN course=? THEN 0 ELSE 1 END, id''',
        (source['profile_id'], source['id'], source['course'])).fetchall()
    return rows[0] if rows else None


def build_plan(c):
    lessons_delete = []
    lessons_keep = []
    if has_table(c, 'lessons'):
        for lesson in c.execute('''SELECT id, title, starts_at, status FROM lessons
                WHERE starts_at>=? ORDER BY starts_at, id''', (CUTOFF,)):
            reason = lesson_keep_reason(c, lesson['id'])
            item = {'id': lesson['id'], 'title': lesson['title'], 'starts_at': lesson['starts_at'],
                'status': lesson['status'], 'reason': reason}
            if reason:
                lessons_keep.append(item)
            else:
                lessons_delete.append(item)
    dropping = {item['id'] for item in lessons_delete}
    series = []
    if has_table(c, 'lesson_series'):
        series = [row['id'] for row in c.execute('SELECT id FROM lesson_series ORDER BY id')]
    courses = []
    if has_table(c, 'students'):
        sources = c.execute('''SELECT * FROM students
            WHERE archived=1 OR IFNULL(voided,0)=1 ORDER BY id''').fetchall()
        opened = []
        for source in sources:
            item = {'id': source['id'], 'name': source['name'], 'course': source['course'],
                'profile_id': source['profile_id'], 'archived': source['archived'],
                'voided': int(source['voided'] or 0) if 'voided' in source.keys() else 0}
            if not has_money(c, source['id']) and not has_taught_history(c, source['id'], dropping):
                item['action'] = 'delete'
                item['detail'] = '删除（没有上课记录，也没有钱）'
            else:
                target = active_target(c, source)
                if target is None:
                    target = next((row for row in opened if row['profile_id'] and row['profile_id'] == source['profile_id']), None)
                if target is not None:
                    item['action'] = 'move'
                    item['target_id'] = target['id'] if isinstance(target, sqlite3.Row) else target['id']
                    item['detail'] = f"有记录或有钱，并入 #{item['target_id']}"
                else:
                    item['action'] = 'reopen'
                    item['detail'] = '有记录或有钱，没有另一门在读课，恢复为在读'
                    opened.append(item)
            courses.append(item)
        for row in c.execute('''SELECT id, name, course FROM students
                WHERE archived=0 AND IFNULL(voided,0)=0 ORDER BY id'''):
            if any(item['id'] == row['id'] for item in courses):
                continue
            courses.append({'id': row['id'], 'name': row['name'], 'course': row['course'],
                'action': 'keep', 'detail': '在读，保留'})
    return {'lessons_delete': lessons_delete, 'lessons_keep': lessons_keep,
        'series': series, 'courses': courses}


def _delete_lesson(c, lesson_id):
    for table in ('lesson_students', 'lesson_reports', 'report_edits', 'arrears', 'lesson_absence_charges'):
        if has_table(c, table) and c.execute(f"SELECT 1 FROM pragma_table_info('{table}') WHERE name='lesson_id'").fetchone():
            c.execute(f'DELETE FROM {table} WHERE lesson_id=?', (lesson_id,))
    c.execute('DELETE FROM lessons WHERE id=?', (lesson_id,))


def _retarget_pair(c, table, source, target):
    if not has_table(c, table):
        return
    cols = {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}
    if 'student_id' not in cols:
        return
    if 'lesson_id' in cols:
        for row in c.execute(f'SELECT lesson_id FROM {table} WHERE student_id=?', (source,)):
            clash = c.execute(f'SELECT 1 FROM {table} WHERE lesson_id=? AND student_id=?',
                (row['lesson_id'], target)).fetchone()
            if clash:
                c.execute(f'DELETE FROM {table} WHERE lesson_id=? AND student_id=?', (row['lesson_id'], source))
            else:
                c.execute(f'UPDATE {table} SET student_id=? WHERE lesson_id=? AND student_id=?',
                    (target, row['lesson_id'], source))
        return
    c.execute(f'UPDATE {table} SET student_id=? WHERE student_id=?', (target, source))


def _move_course(c, source, target):
    for table in ('ledger', 'credit_batches', 'vouchers', 'profile_audit', 'profile_events', 'arrears'):
        _retarget_pair(c, table, source, target)
    for table in ('lesson_students', 'lesson_reports', 'lesson_absence_charges'):
        _retarget_pair(c, table, source, target)
    balance = c.execute('SELECT balance FROM students WHERE id=?', (source,)).fetchone()['balance']
    c.execute('UPDATE students SET balance=balance+? WHERE id=?', (int(balance or 0), target))
    c.execute('UPDATE students SET balance=0 WHERE id=?', (source,))
    _delete_student(c, source)


def _delete_student(c, student_id):
    for table in ('profile_events', 'profile_audit', 'lesson_students', 'lesson_reports',
            'lesson_absence_charges', 'arrears'):
        if has_table(c, table) and c.execute(f"SELECT 1 FROM pragma_table_info('{table}') WHERE name='student_id'").fetchone():
            c.execute(f'DELETE FROM {table} WHERE student_id=?', (student_id,))
    c.execute('DELETE FROM students WHERE id=?', (student_id,))


def apply_plan(c, plan):
    for lesson in plan['lessons_delete']:
        _delete_lesson(c, lesson['id'])
    if has_table(c, 'lessons') and c.execute("SELECT 1 FROM pragma_table_info('lessons') WHERE name='series_id'").fetchone():
        c.execute('UPDATE lessons SET series_id=NULL')
        if c.execute("SELECT 1 FROM pragma_table_info('lessons') WHERE name='occurrence_index'").fetchone():
            c.execute('UPDATE lessons SET occurrence_index=NULL')
    if has_table(c, 'lesson_series'):
        c.execute('DELETE FROM lesson_series')
    for course in plan['courses']:
        if course['action'] == 'delete':
            _delete_student(c, course['id'])
        elif course['action'] == 'move':
            _move_course(c, course['id'], course['target_id'])
        elif course['action'] == 'reopen':
            c.execute('UPDATE students SET archived=0, voided=0 WHERE id=?', (course['id'],))


def render(db_path, apply, plan, before, after):
    lines = [f"{'APPLY' if apply else 'DRY-RUN'}  database={os.path.realpath(db_path)}",
        f'cutoff={CUTOFF}',
        f"lessons_delete={len(plan['lessons_delete'])}",
        f"lessons_keep={len(plan['lessons_keep'])}",
        f"series_delete={len(plan['series'])}",
        f"courses_delete={sum(1 for item in plan['courses'] if item['action']=='delete')}",
        f"courses_move={sum(1 for item in plan['courses'] if item['action']=='move')}",
        f"courses_reopen={sum(1 for item in plan['courses'] if item['action']=='reopen')}",
        f"courses_keep={sum(1 for item in plan['courses'] if item['action']=='keep')}",
        f'payments_cents={before[0]} balances={before[1]}']
    if plan['lessons_keep']:
        lines.append('保留的课（有课后记录或账）：')
        for lesson in plan['lessons_keep']:
            lines.append(f"  保留 #{lesson['id']} {lesson['starts_at']} {lesson['title']} {lesson['reason']}")
    else:
        lines.append('没有需要因为记录或账而保留的课。')
    lines.append('学生：')
    for course in plan['courses']:
        lines.append(f"  #{course['id']} {course['name']} {course['course']} {course['detail']}")
    if apply:
        lines.append(f'payments_before={before[0]} payments_after={after[0]}')
        lines.append(f'balances_before={before[1]} balances_after={after[1]}')
        lines.append('已写入。')
    else:
        lines.append('未写入。')
    return lines


def main():
    parser = argparse.ArgumentParser(description='Reset the book for 2027 re-entry.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    c = connect(args.db, args.apply)
    try:
        if args.apply:
            c.execute('BEGIN IMMEDIATE')
        before = money_totals(c)
        plan = build_plan(c)
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
