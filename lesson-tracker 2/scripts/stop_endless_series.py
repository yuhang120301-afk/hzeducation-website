#!/usr/bin/env python3
"""Stop open-ended repeating lessons, and list December 2026 clashes.

Dry-run is the default. It prints the plan and does not write.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/stop_endless_series.py
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/stop_endless_series.py --apply

Step 1. Every lesson_series row with endless=1 is closed. endless becomes 0,
stop_index is set just after its last existing occurrence, and error is
cleared. Existing lessons are not changed by this step, so nothing new is
generated and nothing already on the calendar is removed.

Step 2. Only Atticus and Benjamin, and only 2026-12-01 through 2026-12-31.
A lesson is removed when it belongs to one of those open-ended series and it
overlaps another lesson for the same student or the same teacher. 2027 is
not touched. A lesson that already has a record, attendance, or charge is
listed and kept. If other students are on the lesson, only Atticus or
Benjamin is taken off it.

--apply uses one connection, PRAGMA busy_timeout=30000, and one
BEGIN IMMEDIATE transaction. It does not change journal_mode and does not
run VACUUM.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
RANGE_START = '2026-12-01'
RANGE_END = '2026-12-31'
TARGETS = ('atticus', 'benjamin')


def connect(db_path, write):
    if write:
        c = sqlite3.connect(db_path, timeout=30)
    else:
        c = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    if write:
        c.execute('PRAGMA foreign_keys=ON')
    else:
        c.execute('PRAGMA query_only=ON')
    return c


def integrity(c, when):
    row = c.execute('PRAGMA integrity_check').fetchone()
    detail = row[0] if row else 'no result'
    if detail != 'ok':
        raise RuntimeError(f'integrity_check {when}: {detail}')


def has_table(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def today():
    return dt.datetime.now(ZoneInfo('Australia/Melbourne')).date().isoformat()


def is_target(name):
    text = (name or '').casefold()
    return any(token in text for token in TARGETS)


def clock(row):
    return f"{row['starts_at'][11:16]}–{row['ends_at'][11:16]}"


def weekday(value):
    return WEEKDAYS[dt.date.fromisoformat(value[:10]).weekday()]


def subject_of(row):
    if 'subject_name' in row.keys() and row['subject_name']:
        return row['subject_name']
    return row['title'] or ''


def load_series(c):
    return list(c.execute('SELECT * FROM lesson_series WHERE endless=1 ORDER BY id'))


def lessons_of(c, series_id):
    subject = ''
    if has_table(c, 'subjects'):
        subject = ', sb.name subject_name'
        join = ' LEFT JOIN subjects sb ON sb.id=l.subject_id'
    else:
        join = ''
    return list(c.execute(f'''SELECT l.*, u.name teacher_name{subject}
        FROM lessons l
        JOIN teachers t ON t.id=l.teacher_id
        JOIN users u ON u.id=t.user_id
        {join}
        WHERE l.series_id=?
        ORDER BY l.starts_at, l.id''', (series_id,)))


def names_for(c, lesson_id):
    return [row['name'] for row in c.execute('''SELECT s.id, s.name, s.profile_id
        FROM lesson_students ls JOIN students s ON s.id=ls.student_id
        WHERE ls.lesson_id=? ORDER BY s.name, s.id''', (lesson_id,))]


def students_of_series(c, rule, lessons):
    found = []
    seen = set()
    for lesson in lessons:
        for name in names_for(c, lesson['id']):
            if name not in seen:
                seen.add(name)
                found.append(name)
    if found:
        return found
    try:
        template = json.loads(rule['template'] or '{}')
    except json.JSONDecodeError:
        template = {}
    for sid in template.get('student_ids') or []:
        row = c.execute('SELECT name FROM students WHERE id=?', (int(sid),)).fetchone()
        if row and row['name'] not in seen:
            seen.add(row['name'])
            found.append(row['name'])
    return found


def slot_text(rule, lessons):
    source = lessons[0] if lessons else None
    if source is None:
        try:
            template = json.loads(rule['template'] or '{}')
        except json.JSONDecodeError:
            template = {}
        start = str(template.get('starts_at') or '')
        end = str(template.get('ends_at') or '')
        if len(start) < 16:
            return '时间未知'
        return f"{weekday(start)} {start[11:16]}–{end[11:16]}"
    return f"{weekday(source['starts_at'])} {clock(source)}"


def clash_rows(c, lesson, same_student):
    """Other live lessons at the same time for this teacher or these students."""
    ids = list(same_student['ids'])
    profiles = [item for item in same_student['profiles'] if item]
    id_marks = ','.join('?' for _ in ids) or 'NULL'
    profile_marks = ','.join('?' for _ in profiles) or 'NULL'
    rows = c.execute(f'''SELECT l.id, l.starts_at, l.ends_at, l.title, l.series_id, l.teacher_id, l.status,
        u.name teacher_name
        FROM lessons l
        JOIN teachers t ON t.id=l.teacher_id
        JOIN users u ON u.id=t.user_id
        WHERE l.id!=? AND l.status!='cancelled'
          AND l.starts_at < ? AND l.ends_at > ?
          AND (
            l.teacher_id=?
            OR EXISTS (
              SELECT 1 FROM lesson_students ls
              JOIN students s ON s.id=ls.student_id
              WHERE ls.lesson_id=l.id
                AND (s.id IN ({id_marks}) OR s.profile_id IN ({profile_marks}))
            )
          )''', (lesson['id'], lesson['ends_at'], lesson['starts_at'], lesson['teacher_id'], *ids, *profiles)).fetchall()
    found = []
    for other in rows:
        why = []
        if other['teacher_id'] == lesson['teacher_id']:
            why.append('同一老师')
        matched = c.execute(f'''SELECT 1 FROM lesson_students ls
            JOIN students s ON s.id=ls.student_id
            WHERE ls.lesson_id=? AND (s.id IN ({id_marks}) OR s.profile_id IN ({profile_marks}))''',
            (other['id'], *ids, *profiles)).fetchone()
        if matched:
            why.append('同一学生')
        if why:
            found.append((other, '、'.join(why)))
    return found


def future_clash_count(c, lessons, today_text):
    future = [row for row in lessons if row['status'] != 'cancelled' and row['starts_at'][:10] >= today_text]
    clashes = 0
    for lesson in future:
        if clash_rows(c, lesson, {'ids': set(), 'profiles': set()}):
            clashes += 1
    return len(future), clashes


def describe_series(c, today_text):
    lines = ['—— 未结束的重复系列 ——']
    rules = load_series(c)
    if not rules:
        lines.append('没有 endless=1 的系列。')
        return lines, rules
    for rule in rules:
        lessons = lessons_of(c, rule['id'])
        students = '、'.join(students_of_series(c, rule, lessons)) or '（没有学生）'
        teacher = lessons[0]['teacher_name'] if lessons else '（没有已生成的课）'
        subject = subject_of(lessons[0]) if lessons else ''
        last = lessons[-1]['starts_at'][:10] if lessons else '（没有已生成的课）'
        future, clashes = future_clash_count(c, lessons, today_text)
        lines.append(
            f"系列 {rule['id']}  老师 {teacher}  学生 {students}  时间 {slot_text(rule, lessons)}  科目 {subject}"
        )
        lines.append(f"  最后一节 {last}  已生成的以后课程 {future} 节，其中 {clashes} 节和另一节课时间重叠")
    lines.append(f'共 {len(rules)} 个未结束的系列。将设为结束，不改已有课程。')
    return lines, rules


def target_people(c):
    rows = [row for row in c.execute('SELECT id, name, profile_id FROM students') if is_target(row['name'])]
    return {
        'ids': {row['id'] for row in rows},
        'profiles': {row['profile_id'] for row in rows if row['profile_id']},
        'rows': rows,
    }


def protected_reason(c, lesson, people):
    if lesson['status'] == 'completed':
        return '这节课已上了'
    marks = ','.join('?' for _ in people['ids']) or 'NULL'
    ids = tuple(people['ids'])
    if has_table(c, 'lesson_reports') and ids and c.execute(
            f'SELECT 1 FROM lesson_reports WHERE lesson_id=? AND student_id IN ({marks})',
            (lesson['id'], *ids)).fetchone():
        return '已有课后记录'
    if has_table(c, 'arrears') and ids and c.execute(
            f'SELECT 1 FROM arrears WHERE lesson_id=? AND student_id IN ({marks})',
            (lesson['id'], *ids)).fetchone():
        return '已有欠费记录'
    if has_table(c, 'report_edits') and c.execute(
            'SELECT 1 FROM report_edits WHERE lesson_id=?', (lesson['id'],)).fetchone():
        return '已有修改记录'
    if ids and has_table(c, 'ledger'):
        for sid in ids:
            if c.execute("SELECT 1 FROM ledger WHERE request_id LIKE ?", (f'scheduled-{lesson["id"]}-student-{sid}%',)).fetchone():
                return '已扣过课时'
    return ''


def december_plan(c, endless_ids, people):
    """Endless-series lessons in December 2026 that clash with another lesson."""
    if not people['ids'] or not endless_ids:
        return [], []
    marks = ','.join('?' for _ in endless_ids)
    student_marks = ','.join('?' for _ in people['ids'])
    rows = c.execute(f'''SELECT DISTINCT l.id
        FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE l.series_id IN ({marks})
          AND l.status!='cancelled'
          AND substr(l.starts_at,1,10)>=? AND substr(l.starts_at,1,10)<=?
          AND ls.student_id IN ({student_marks})
        ORDER BY l.starts_at, l.id''', (*endless_ids, RANGE_START, RANGE_END, *people['ids'])).fetchall()
    remove = []
    skipped = []
    for item in rows:
        lesson = lesson_detail(c, item['id'])
        clashes = clash_rows(c, lesson, people)
        if not clashes:
            continue
        reason = protected_reason(c, lesson, people)
        record = {'lesson': lesson, 'clashes': clashes, 'names': target_names(c, lesson['id'], people)}
        if reason:
            record['reason'] = reason
            skipped.append(record)
        else:
            remove.append(record)
    return remove, skipped


def lesson_detail(c, lesson_id):
    subject = ', sb.name subject_name' if has_table(c, 'subjects') else ''
    join = ' LEFT JOIN subjects sb ON sb.id=l.subject_id' if subject else ''
    return c.execute(f'''SELECT l.*, u.name teacher_name{subject}
        FROM lessons l
        JOIN teachers t ON t.id=l.teacher_id
        JOIN users u ON u.id=t.user_id
        {join}
        WHERE l.id=?''', (lesson_id,)).fetchone()


def target_names(c, lesson_id, people):
    return [row['name'] for row in c.execute('''SELECT s.name FROM lesson_students ls
        JOIN students s ON s.id=ls.student_id
        WHERE ls.lesson_id=? AND s.id IN ({})
        ORDER BY s.name'''.format(','.join('?' for _ in people['ids'])), (lesson_id, *people['ids']))]


def describe_december(remove, skipped):
    lines = ['—— 2026 年 12 月里要去掉的重复课 ——']
    if not remove and not skipped:
        lines.append('没有 Atticus 或 Benjamin 在这个月、由未结束系列生成、又和另一节课重叠的课。')
        return lines
    for record in remove:
        lines.extend(lesson_lines(record, '将去掉'))
    lines.append(f'将处理 {len(remove)} 节。不改 2027 年的课，也不改没有重叠的 12 月课。')
    if skipped:
        lines.append(f'有 {len(skipped)} 节因为已有记录而保留：')
        for record in skipped:
            lines.extend(lesson_lines(record, '保留'))
            lines.append(f"  原因：{record['reason']}")
    return lines


def lesson_lines(record, label):
    lesson = record['lesson']
    students = '、'.join(record['names'])
    lines = [
        f"{label}  #{lesson['id']}  {lesson['starts_at'][:10]} {weekday(lesson['starts_at'])} {clock(lesson)}"
        f"  老师 {lesson['teacher_name']}  学生 {students}  科目 {subject_of(lesson)}  系列 {lesson['series_id']}"
    ]
    for other, why in record['clashes']:
        lines.append(
            f"  重叠 {why}：#{other['id']}  {other['starts_at'][:10]} {weekday(other['starts_at'])} {clock(other)}"
            f"  老师 {other['teacher_name']}  系列 {other['series_id'] or '无'}"
        )
    return lines


def other_students(c, lesson_id, people):
    return c.execute('''SELECT COUNT(*) FROM lesson_students WHERE lesson_id=? AND student_id NOT IN ({})'''.format(
        ','.join('?' for _ in people['ids'])), (lesson_id, *people['ids'])).fetchone()[0]


def apply_series(c, rules):
    for rule in rules:
        lessons = lessons_of(c, rule['id'])
        indexes = [row['occurrence_index'] for row in lessons if row['occurrence_index'] is not None]
        stop = (max(indexes) + 1) if indexes else rule['next_index']
        c.execute("UPDATE lesson_series SET endless=0, stop_index=?, error='' WHERE id=?", (stop, rule['id']))


def apply_december(c, remove, people):
    unlinked = 0
    deleted = 0
    for record in remove:
        lesson_id = record['lesson']['id']
        marks = ','.join('?' for _ in people['ids'])
        others = other_students(c, lesson_id, people)
        c.execute(f'DELETE FROM lesson_students WHERE lesson_id=? AND student_id IN ({marks})', (lesson_id, *people['ids']))
        unlinked += 1
        if others:
            continue
        if has_table(c, 'lesson_reports'):
            c.execute('DELETE FROM lesson_reports WHERE lesson_id=?', (lesson_id,))
        c.execute('DELETE FROM lessons WHERE id=?', (lesson_id,))
        deleted += 1
    return unlinked, deleted


def report(c):
    today_text = today()
    series_lines, rules = describe_series(c, today_text)
    people = target_people(c)
    remove, skipped = december_plan(c, [rule['id'] for rule in rules], people)
    lines = [
        f'今天（墨尔本）{today_text}',
        *series_lines,
        *describe_december(remove, skipped),
        f'合计：结束 {len(rules)} 个系列，去掉 {len(remove)} 节重复课，保留 {len(skipped)} 节已有记录的课。',
    ]
    return lines, rules, remove, people


def main():
    parser = argparse.ArgumentParser(description='Stop endless series and remove December 2026 clashes for Atticus and Benjamin.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit('只能选 --dry-run 或 --apply 其中一个。')
    if not args.db:
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    db = os.path.realpath(args.db)
    if not os.path.exists(db):
        raise SystemExit(f'找不到数据库：{db}')
    apply = args.apply
    if not apply:
        c = connect(db, False)
        try:
            lines, _rules, _remove, _people = report(c)
            print('\n'.join([f'DRY-RUN  database={db}', *lines]))
        finally:
            c.close()
        return
    c = connect(db, True)
    try:
        c.execute('BEGIN IMMEDIATE')
        integrity(c, 'before changes')
        lines, rules, remove, people = report(c)
        apply_series(c, rules)
        unlinked, deleted = apply_december(c, remove, people)
        integrity(c, 'before commit')
        c.commit()
        print('\n'.join([
            f'APPLY  database={db}',
            *lines,
            f'已写入。从课上移下 {unlinked} 处学生，删除 {deleted} 节只有他们的课。',
        ]))
    except BaseException:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
