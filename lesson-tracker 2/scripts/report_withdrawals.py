#!/usr/bin/env python3
"""Read-only list of 退课 and stopped courses.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/report_withdrawals.py

Prints one line per withdrawal. A row is flagged 可能录错 when it was stopped
on the same day it was created, with no attended or charged lesson and no money.
The database is opened with mode=ro. This script does not write.
"""
import datetime as dt
import os
import sqlite3
import sys


def connect(db_path):
    c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA query_only=ON')
    return c


def has(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def stamp(value):
    text = str(value or '').replace('T', ' ')
    return text[:19]


def parse(value):
    text = stamp(value)
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return dt.datetime.strptime(text[:len(dt.datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


def counts(c, sid):
    attended = c.execute('''SELECT COUNT(*) n FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE ls.student_id=? AND l.status='completed' ''', (sid,)).fetchone()['n'] if sid else 0
    charged = c.execute('''SELECT COUNT(*) n FROM ledger WHERE student_id=? AND kind='lesson'
        AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reversal_of=ledger.id)''', (sid,)).fetchone()['n'] if sid else 0
    paid = refunded = 0
    if sid and has(c, 'cash_entries'):
        for row in c.execute('''SELECT cash.cash_delta FROM cash_entries cash
            JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?''', (sid,)):
            if row['cash_delta'] > 0:
                paid += row['cash_delta']
            elif row['cash_delta'] < 0:
                refunded -= row['cash_delta']
    return attended, charged, paid, refunded


def teacher_of(c, sid):
    if not sid:
        return ''
    row = c.execute('''SELECT u.name FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        JOIN teachers t ON t.id=l.teacher_id
        JOIN users u ON u.id=t.user_id
        WHERE ls.student_id=? ORDER BY l.starts_at DESC LIMIT 1''', (sid,)).fetchone()
    return row['name'] if row else ''


def created_of(c, sid):
    times = []
    if not sid:
        return ''
    for sql in (
        'SELECT MIN(created_at) t FROM ledger WHERE student_id=?',
        '''SELECT MIN(l.updated_at) t FROM lessons l JOIN lesson_students ls ON ls.lesson_id=l.id WHERE ls.student_id=?''',
    ):
        row = c.execute(sql, (sid,)).fetchone()
        if row and row['t']:
            times.append(row['t'])
    return min(times) if times else ''


def load(c):
    found = []
    seen = set()
    if has(c, 'vouchers'):
        for row in c.execute("SELECT * FROM vouchers WHERE kind='stop' ORDER BY id"):
            sid = row['student_id']
            seen.add(sid)
            if row['status'] == 'void':
                continue
            found.append({
                'id': f"单据{row['id']}", 'voucher_id': row['id'], 'student_id': sid,
                'student': row['student_name'], 'course': row['course'], 'type': '',
                'stopped': row['created_at'], 'status': row['status'],
            })
    if has(c, 'profile_audit'):
        voided_sql = ''
        cols = {item['name'] for item in c.execute('PRAGMA table_info(students)')}
        if 'voided' in cols:
            voided_sql = ' AND s.voided=0'
        for row in c.execute('''SELECT a.created_at, s.id student_id, s.name, s.course
            FROM profile_audit a JOIN students s ON s.id=a.student_id
            WHERE a.action='course_stopped' ''' + voided_sql + ' ORDER BY a.id'):
            if row['student_id'] in seen:
                continue
            found.append({
                'id': f"学生{row['student_id']}", 'voucher_id': None, 'student_id': row['student_id'],
                'student': row['name'], 'course': row['course'], 'type': '',
                'stopped': row['created_at'], 'status': 'stopped',
            })
    lines = []
    for item in found:
        sid = item['student_id']
        extra = None
        if sid and has(c, 'course_types'):
            extra = c.execute('''SELECT s.course, ct.name type_name FROM students s
                LEFT JOIN course_types ct ON ct.id=s.course_type_id WHERE s.id=?''', (sid,)).fetchone()
        elif sid:
            extra = c.execute("SELECT course, '' type_name FROM students WHERE id=?", (sid,)).fetchone()
        course = (extra['course'] if extra else '') or item['course']
        kind = extra['type_name'] if extra and extra['type_name'] else ''
        created = created_of(c, sid)
        stopped = item['stopped']
        began, ended = parse(created), parse(stopped)
        minutes = int((ended - began).total_seconds() // 60) if began and ended and ended >= began else ''
        attended, charged, paid, refunded = counts(c, sid)
        same_day = began and ended and began.date() == ended.date()
        mistake = bool(same_day and attended == 0 and charged == 0 and paid == 0 and refunded == 0)
        lines.append(
            f"{item['id']} 学生{item['student']}#{sid or '无'} 课程{course}{('/' + kind) if kind else ''}"
            f" 老师{teacher_of(c, sid) or '无'} 建立{stamp(created) or '未知'} 停课{stamp(stopped)}"
            f" 间隔{minutes if minutes != '' else '未知'}分钟 已上{attended} 已扣{charged}"
            f" 收款{paid/100:.2f} 退款{refunded/100:.2f} 状态{item['status']}"
            + (' 可能录错' if mistake else '')
        )
    return lines


def main():
    db = os.environ.get('LESSON_DB', '')
    if not db or not os.path.exists(db):
        raise SystemExit('请设置 LESSON_DB，指向现有的数据库文件。')
    c = connect(db)
    try:
        lines = load(c)
    finally:
        c.close()
    print('\n'.join([f'只读  database={os.path.realpath(db)}', *lines, f'合计 {len(lines)} 条退课或停课记录。']))


if __name__ == '__main__':
    sys.exit(main())
