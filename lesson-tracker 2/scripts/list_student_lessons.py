#!/usr/bin/env python3
"""Read-only list of one student's lessons, plus clashes and the calendar banner.

Nothing in this script writes. The database is opened with mode=ro.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/list_student_lessons.py
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/list_student_lessons.py \
      --students 'Atticus,Benjamin' --from 2027-11-15 --to 2028-01-31

The default range is 15 November 2027 through 31 January 2028, which covers
the December 2027 week Helen is looking at (including 26 December 2027).
Any --from and --to dates are accepted.

Each line is one lesson that still exists. Overlaps use the same rules as
saving a lesson: another live lesson for the same student, or the same
teacher, in the same time. An exact duplicate is the same student on the
same date at the same start time. Cancelled lessons are listed and are not
treated as overlaps.

A clash line names the other lesson and which series made each one.
2027新系列 is a series created by extend_2027_series.py. 旧的有结束日期的系列
is any other series that is not open-ended. 旧的未结束系列 still has endless=1.

The last section is the calendar banner for this date range. It uses
recurrence.warnings and the same date filter as the calendar.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import extend_2027_series
import recurrence
import term1_2027_schedule as term1

WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
STATUS = {'scheduled': '待上', 'completed': '已上', 'cancelled': '已取消'}


def connect(db_path):
    c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA query_only=ON')
    return c


def has_table(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def new_series_ids():
    return {extend_2027_series.series_id(title, weekday, start) for weekday, start, _end, title, *_rest in term1.SLOTS}


def wanted(name, tokens):
    text = (name or '').casefold()
    return any(token.casefold() in text for token in tokens)


def weekday(value):
    return WEEKDAYS[dt.date.fromisoformat(value[:10]).weekday()]


def clock(row):
    return f"{row['starts_at'][11:16]}–{row['ends_at'][11:16]}"


def series_id_of(row):
    if row is None:
        return None
    if 'rule_id' in row.keys():
        return row['rule_id']
    return row['id']


def series_kind(row, fresh_ids):
    sid = series_id_of(row)
    if not sid:
        return '单次课'
    if sid in fresh_ids:
        return '2027新系列'
    if row['endless']:
        return '旧的未结束系列'
    return '旧的有结束日期的系列'


def template_start(row):
    if not row or not series_id_of(row):
        return ''
    try:
        start = str(json.loads(row['template'] or '{}').get('starts_at') or '')
    except json.JSONDecodeError:
        return ''
    return start[:10]


def series_text(row, fresh_ids):
    sid = series_id_of(row)
    if not sid:
        return '系列无'
    kind = series_kind(row, fresh_ids)
    end = '未结束' if row['endless'] else '已结束'
    stop = row['stop_index'] if row['stop_index'] is not None else '无'
    origin = template_start(row)
    origin_text = f"/从{origin}" if origin else ''
    return f"系列{sid}/{kind}/{end}/止于{stop}{origin_text}"


def banner_lines(items, start, end):
    """Same date filter and line shape as the calendar banner."""
    lines = []
    for item in items:
        if isinstance(item, str):
            day = item[:10]
            text = ' '.join(item.split())
        else:
            day = item.get('date') or ''
            who = ' · '.join(part for part in [item.get('teacher'), *(item.get('students') or [])] if part)
            text = ' '.join(f"{item.get('date') or ''} {item.get('time') or ''} {who}：{item.get('message') or ''}".split())
        if day and start <= day <= end:
            lines.append(text)
    return lines


def load(c, tokens, start, end):
    fresh_ids = new_series_ids()
    students = [row for row in c.execute('SELECT * FROM students') if wanted(row['name'], tokens)]
    ids = {row['id'] for row in students}
    if not ids:
        return students, [], {}, fresh_ids, []
    marks = ','.join('?' for _ in ids)
    subject = 'sb.name subject_name,' if has_table(c, 'subjects') else "'' subject_name,"
    kind = 'ct.name type_name,' if has_table(c, 'course_types') else "'' type_name,"
    subject_join = 'LEFT JOIN subjects sb ON sb.id=l.subject_id' if has_table(c, 'subjects') else ''
    type_join = 'LEFT JOIN course_types ct ON ct.id=l.course_type_id' if has_table(c, 'course_types') else ''
    window_end = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
    rows = c.execute(f'''SELECT l.*, u.name teacher_name, {subject} {kind}
            ls.id rule_id, ls.endless, ls.stop_index, ls.template, ls.error series_error
        FROM lessons l
        JOIN teachers t ON t.id=l.teacher_id
        JOIN users u ON u.id=t.user_id
        LEFT JOIN lesson_series ls ON ls.id=l.series_id
        {subject_join}
        {type_join}
        WHERE l.starts_at < ? AND l.ends_at > ?
        ORDER BY l.starts_at, l.id''', (window_end + 'T00:00', start + 'T00:00')).fetchall()
    people = {}
    if rows:
        lesson_marks = ','.join('?' for _ in rows)
        for row in c.execute(f'''SELECT ls.lesson_id, s.id, s.name, s.profile_id, s.archived, s.course
            FROM lesson_students ls JOIN students s ON s.id=ls.student_id
            WHERE ls.lesson_id IN ({lesson_marks}) ORDER BY s.name, s.id''', tuple(row['id'] for row in rows)):
            people.setdefault(row['lesson_id'], []).append(row)
    chosen = []
    for row in rows:
        roster = people.get(row['id'], [])
        if any(person['id'] in ids for person in roster) and start <= row['starts_at'][:10] <= end:
            chosen.append(row)
    return students, chosen, people, fresh_ids, rows


def overlaps(left, right):
    return left['starts_at'] < right['ends_at'] and left['ends_at'] > right['starts_at']


def same_student(left_people, right_people):
    for left in left_people:
        for right in right_people:
            if left['id'] == right['id'] or (left['profile_id'] and left['profile_id'] == right['profile_id']):
                return True
    return False


def clash_marks(lesson, others, people):
    marks = []
    mine = people.get(lesson['id'], [])
    for other in others:
        if other['id'] == lesson['id'] or other['status'] == 'cancelled' or lesson['status'] == 'cancelled':
            continue
        if not overlaps(lesson, other):
            continue
        reasons = []
        student = same_student(mine, people.get(other['id'], []))
        if student:
            reasons.append('同一学生')
        if lesson['teacher_id'] == other['teacher_id']:
            reasons.append('同一老师')
        if student and lesson['starts_at'][:10] == other['starts_at'][:10] and lesson['starts_at'][11:16] == other['starts_at'][11:16]:
            reasons.append('同一时间')
        if reasons:
            marks.append((other, reasons))
    return marks


def recorded(c, lesson):
    record = lesson['status'] == 'completed'
    charge = False
    if has_table(c, 'lesson_reports'):
        row = c.execute('SELECT ledger_id FROM lesson_reports WHERE lesson_id=? LIMIT 1', (lesson['id'],)).fetchone()
        if row:
            record = True
            charge = row['ledger_id'] is not None
    if has_table(c, 'report_edits') and c.execute('SELECT 1 FROM report_edits WHERE lesson_id=?', (lesson['id'],)).fetchone():
        record = True
    if has_table(c, 'ledger') and c.execute(
            "SELECT 1 FROM ledger WHERE request_id LIKE ?", (f"scheduled-{lesson['id']}-student-%",)).fetchone():
        charge = True
    return record, charge


def person_text(person):
    flag = '已停' if person['archived'] else '在读'
    return f"{person['name']}#{person['id']}{flag}"


def lesson_line(c, lesson, people, fresh_ids, others):
    roster = people.get(lesson['id'], [])
    students = '、'.join(person['name'] for person in roster) or '无'
    courses = '、'.join(person_text(person) for person in roster) or '无'
    subject = lesson['subject_name'] or lesson['title'] or ''
    kind = lesson['type_name'] or ''
    subject = f"{subject}/{kind}" if kind else subject
    record, charge = recorded(c, lesson)
    clashes = clash_marks(lesson, others, people)
    clash_text = '冲突无'
    if clashes:
        parts = []
        for other, reasons in clashes:
            parts.append(f"#{other['id']} {'、'.join(reasons)}（对方{series_kind_of(other, fresh_ids)}）")
        clash_text = '冲突' + '；'.join(parts)
    return (
        f"#{lesson['id']} {lesson['starts_at'][:10]} {weekday(lesson['starts_at'])} {clock(lesson)}"
        f" 老师{lesson['teacher_name']} 学生{students} 科目{subject}"
        f" 课程{courses} 状态{STATUS.get(lesson['status'], lesson['status'])}"
        f" {series_text(lesson, fresh_ids)}"
        f" 记录{'有' if record else '无'} 扣课{'有' if charge else '无'} {clash_text}"
    ), clashes


def series_kind_of(row, fresh_ids):
    if not row['rule_id']:
        return '单次课'
    return series_kind(row, fresh_ids)


def build(c, tokens, start, end):
    students, chosen, people, fresh_ids, window = load(c, tokens, start, end)
    lines = [
        f"只读  学生{'、'.join(tokens)}  {start} 至 {end}",
        '2027新系列＝extend_2027_series.py 生成的系列。旧的有结束日期的系列＝除此之外、已经停住的系列。',
    ]
    if not students:
        lines.append('没有找到这些学生。')
        return lines
    found = '、'.join(f"{row['name']}#{row['id']}" for row in students)
    lines.append(f"匹配到 {found}")
    counts = {'lessons': 0, 'cancelled': 0, 'clash': 0, 'student': 0, 'teacher': 0, 'exact': 0,
              'new': 0, 'old': 0, 'record': 0, 'charge': 0}
    for lesson in chosen:
        text, clashes = lesson_line(c, lesson, people, fresh_ids, window)
        lines.append(text)
        counts['lessons'] += 1
        if lesson['status'] == 'cancelled':
            counts['cancelled'] += 1
        record, charge = recorded(c, lesson)
        counts['record'] += int(record)
        counts['charge'] += int(charge)
        if clashes:
            counts['clash'] += 1
            reasons = {reason for _other, reasons in clashes for reason in reasons}
            counts['student'] += int('同一学生' in reasons)
            counts['teacher'] += int('同一老师' in reasons)
            counts['exact'] += int('同一时间' in reasons)
            kind = series_kind_of(lesson, fresh_ids)
            if kind == '2027新系列':
                counts['new'] += 1
            elif kind.startswith('旧'):
                counts['old'] += 1
    banner = banner_lines(recurrence.warnings(c), start, end)
    lines.append(f"—— 日历横幅 {start} 至 {end} ——")
    lines.append('横幅只显示系列上已经记下的错误，并且只保留日期落在这段里的。这和课表上的「重复排课需要处理」是同一份。')
    lines.extend(banner or ['这段日期里，日历横幅没有冲突提示。'])
    lines.append(
        f"合计 课节{counts['lessons']} 已取消{counts['cancelled']} 有冲突{counts['clash']}"
        f" 同一学生{counts['student']} 同一老师{counts['teacher']} 同一时间{counts['exact']}"
        f" 冲突中的2027新系列{counts['new']} 冲突中的旧系列{counts['old']}"
        f" 有记录{counts['record']} 有扣课{counts['charge']} 横幅{len(banner)}"
    )
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description='List lessons for named students. Read only.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--students', default='Atticus,Benjamin')
    parser.add_argument('--from', dest='start', default='2027-11-15')
    parser.add_argument('--to', dest='end', default='2028-01-31')
    args = parser.parse_args(argv)
    try:
        dt.date.fromisoformat(args.start)
        dt.date.fromisoformat(args.end)
    except ValueError:
        raise SystemExit('日期请用 YYYY-MM-DD。')
    if args.start > args.end:
        raise SystemExit('--from 不能晚于 --to。')
    tokens = [part.strip() for part in args.students.split(',') if part.strip()]
    if not tokens:
        raise SystemExit('请用 --students 写出学生姓名。')
    if not args.db:
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    if not os.path.exists(args.db):
        raise SystemExit(f'找不到数据库：{args.db}')
    c = connect(args.db)
    try:
        print('\n'.join(build(c, tokens, args.start, args.end)))
    finally:
        c.close()


if __name__ == '__main__':
    main()
