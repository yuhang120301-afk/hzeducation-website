#!/usr/bin/env python3
"""Reset course enrolments so Helen can pick the 2027 course types.

Dry-run is the default. It prints one line per student and does not write.

  python3 reset_2027_courses.py --dry-run --db /var/data/lessons.sqlite3
  python3 reset_2027_courses.py --apply --db /var/data/lessons.sqlite3

Benjamin's old maths enrolment is moved onto a 2027 数学 + 一对一 row, the
same shape as Atticus's new 数学 course. Lessons, reports, ledger rows and
the balance move with it, and the old maths row is archived.

Atticus is left as he is. Every other student's course rows are archived.
Their lessons, reports and ledger stay on those rows, and calendar lessons
are not edited. Archived courses disappear from the student cards and from
the scheduling list.

--apply uses one connection, PRAGMA busy_timeout=30000 and one
BEGIN IMMEDIATE transaction. It does not change journal_mode and does not
run VACUUM.
"""
import argparse
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEEP = ('atticus', 'benjamin')


def kept(name):
    text = (name or '').casefold()
    return any(token in text for token in KEEP)


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


def catalog_id(c, table, name):
    row = c.execute(f'SELECT id FROM {table} WHERE name=?', (name,)).fetchone()
    if not row:
        raise RuntimeError(f'找不到{name}（{table}）。')
    return row['id']


def load(c):
    return list(c.execute('''SELECT s.*, sb.name subject_name, ct.name type_name
        FROM students s
        LEFT JOIN subjects sb ON sb.id=s.subject_id
        LEFT JOIN course_types ct ON ct.id=s.course_type_id
        ORDER BY s.name, s.id'''))


def is_maths(row):
    text = f"{row['subject_name'] or ''} {row['course'] or ''}"
    return '数学' in text


def is_canonical(row):
    return row['course'] == '数学' and row['subject_name'] == '数学' and row['type_name'] == '一对一' and not row['archived']


def counts(c, sid):
    lessons = c.execute('SELECT COUNT(*) FROM lesson_students WHERE student_id=?', (sid,)).fetchone()[0]
    reports = c.execute('SELECT COUNT(*) FROM lesson_reports WHERE student_id=?', (sid,)).fetchone()[0] if has_table(c, 'lesson_reports') else 0
    ledger = c.execute('SELECT COUNT(*) FROM ledger WHERE student_id=?', (sid,)).fetchone()[0] if has_table(c, 'ledger') else 0
    balance = c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']
    return lessons, reports, ledger, balance


def move_links(c, old_id, new_id):
    moved = {'lessons': 0, 'reports': 0, 'ledger': 0, 'batches': 0}
    for lesson in c.execute('SELECT lesson_id FROM lesson_students WHERE student_id=?', (old_id,)):
        if c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=?', (lesson['lesson_id'], new_id)).fetchone():
            c.execute('DELETE FROM lesson_students WHERE lesson_id=? AND student_id=?', (lesson['lesson_id'], old_id))
        else:
            c.execute('UPDATE lesson_students SET student_id=? WHERE lesson_id=? AND student_id=?', (new_id, lesson['lesson_id'], old_id))
        moved['lessons'] += 1
    if has_table(c, 'lesson_reports'):
        for report in c.execute('SELECT lesson_id FROM lesson_reports WHERE student_id=?', (old_id,)):
            if c.execute('SELECT 1 FROM lesson_reports WHERE lesson_id=? AND student_id=?', (report['lesson_id'], new_id)).fetchone():
                c.execute('DELETE FROM lesson_reports WHERE lesson_id=? AND student_id=?', (report['lesson_id'], old_id))
            else:
                c.execute('UPDATE lesson_reports SET student_id=? WHERE lesson_id=? AND student_id=?', (new_id, report['lesson_id'], old_id))
            moved['reports'] += 1
    if has_table(c, 'ledger'):
        moved['ledger'] = c.execute('SELECT COUNT(*) FROM ledger WHERE student_id=?', (old_id,)).fetchone()[0]
        c.execute('UPDATE ledger SET student_id=? WHERE student_id=?', (new_id, old_id))
    if has_table(c, 'credit_batches'):
        moved['batches'] = c.execute('SELECT COUNT(*) FROM credit_batches WHERE student_id=?', (old_id,)).fetchone()[0]
        c.execute('UPDATE credit_batches SET student_id=? WHERE student_id=?', (new_id, old_id))
    if has_table(c, 'arrears'):
        c.execute('UPDATE arrears SET student_id=? WHERE student_id=?', (new_id, old_id))
    for sid in (old_id, new_id):
        if has_table(c, 'ledger'):
            total = c.execute('SELECT COALESCE(SUM(delta),0) FROM ledger WHERE student_id=?', (sid,)).fetchone()[0]
        else:
            total = 0 if sid == old_id else c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']
        if total < 0:
            raise RuntimeError(f'学生 #{sid} 移动后余额为负（{total}），已回滚。')
        c.execute('UPDATE students SET balance=? WHERE id=?', (total, sid))
    return moved


def ensure_benjamin_target(c, source):
    existing = c.execute('''SELECT s.id FROM students s
        JOIN subjects sb ON sb.id=s.subject_id
        JOIN course_types ct ON ct.id=s.course_type_id
        WHERE s.profile_id=? AND s.archived=0 AND s.course='数学' AND sb.name='数学' AND ct.name='一对一'
        ORDER BY s.id LIMIT 1''', (source['profile_id'],)).fetchone()
    subject_id = catalog_id(c, 'subjects', '数学')
    type_id = catalog_id(c, 'course_types', '一对一')
    if existing:
        return existing['id'], False
    named = c.execute("SELECT id FROM students WHERE profile_id=? AND archived=0 AND course='数学' ORDER BY id LIMIT 1",
        (source['profile_id'],)).fetchone()
    if named:
        c.execute('UPDATE students SET subject_id=?, course_type_id=? WHERE id=?', (subject_id, type_id, named['id']))
        return named['id'], False
    cols = {r['name'] for r in c.execute('PRAGMA table_info(students)')}
    data = {
        'name': source['name'], 'course': '数学', 'parent_id': source['parent_id'], 'profile_id': source['profile_id'],
        'balance': 0, 'course_type_id': type_id, 'subject_id': subject_id,
        'course_note': source['course_note'] or source['course'] or '',
        'billing_unit': source['billing_unit'] or 'lesson', 'birthday': source['birthday'] or '',
        'grade': source['grade'] or '', 'notes': source['notes'] or '',
        'helen_original': source['helen_original'] or 0, 'level_code': source['level_code'] or '',
        'level_year': source['level_year'] or 0,
    }
    use = [(key, value) for key, value in data.items() if key in cols]
    new_id = c.execute(
        f"INSERT INTO students({','.join(key for key,_ in use)}) VALUES({','.join('?' for _ in use)})",
        [value for _, value in use]).lastrowid
    return new_id, True


def describe(c):
    rows = load(c)
    lines = []
    benjamin = [row for row in rows if 'benjamin' in (row['name'] or '').casefold()]
    maths = [row for row in benjamin if is_maths(row) and not row['archived']]
    canonical = [row for row in maths if is_canonical(row)]
    if benjamin and maths:
        target = canonical[0]['id'] if canonical else '新建'
        sources = [row for row in maths if row['id'] != (canonical[0]['id'] if canonical else None)]
        if not sources and canonical:
            lines.append(f"Benjamin 数学已经是 2027 一对一（#{canonical[0]['id']}），不改。")
        for source in sources:
            lessons, reports, ledger, balance = counts(c, source['id'])
            lines.append(
                f"Benjamin #{source['id']} {source['course']} 余额 {balance/100:g}，课 {lessons}，记录 {reports}，账 {ledger}"
                f" -> 数学 一对一（{('#'+str(target)) if target!='新建' else '新建一行'}），旧行归档。课表本身不改。"
            )
    elif benjamin:
        lines.append('Benjamin 没有未归档的数学课，不改。')
    else:
        lines.append('没有找到 Benjamin。')
    lines.append('Atticus 保持原样，不归档。')
    archived = 0
    for row in rows:
        if kept(row['name']) or row['archived']:
            continue
        lessons, reports, ledger, balance = counts(c, row['id'])
        lines.append(f"归档 {row['name']} #{row['id']} {row['course']} 余额 {balance/100:g}，课 {lessons}，记录 {reports}，账 {ledger}（都留在原行）")
        archived += 1
    lines.append(f'将归档 {archived} 门其他学生的课。')
    return lines


def apply_changes(c):
    rows = load(c)
    benjamin = [row for row in rows if 'benjamin' in (row['name'] or '').casefold() and is_maths(row) and not row['archived']]
    canonical = [row for row in benjamin if is_canonical(row)]
    sources = [row for row in benjamin if not canonical or row['id'] != canonical[0]['id']]
    if sources:
        target_id, _created = ensure_benjamin_target(c, sources[0])
        for source in sources:
            if source['id'] == target_id:
                continue
            move_links(c, source['id'], target_id)
            c.execute('UPDATE students SET archived=1, balance=0 WHERE id=?', (source['id'],))
    for row in rows:
        if kept(row['name']) or row['archived']:
            continue
        fresh = c.execute('SELECT archived FROM students WHERE id=?', (row['id'],)).fetchone()
        if fresh and fresh['archived']:
            continue
        note = row['course_note'] or row['course'] or ''
        c.execute('UPDATE students SET archived=1, course_note=?, course=? WHERE id=?',
            (note, f"{row['course']} #{row['id']}", row['id']))


def main():
    parser = argparse.ArgumentParser(description='Archive old courses and move Benjamin onto 2027 数学 一对一.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', str(ROOT / 'data' / 'lessons.sqlite3')))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit('只能选 --dry-run 或 --apply 其中一个。')
    apply = args.apply
    db = os.path.realpath(args.db)
    if not os.path.exists(db):
        raise SystemExit(f'找不到数据库：{db}')
    if not apply:
        c = connect(db, False)
        try:
            text = '\n'.join([f'DRY-RUN  database={db}', *describe(c)])
        finally:
            c.close()
    else:
        c = connect(db, True)
        try:
            c.execute('BEGIN IMMEDIATE')
            integrity(c, 'before changes')
            preview = describe(c)
            apply_changes(c)
            integrity(c, 'before commit')
            c.commit()
            integrity(c, 'after commit')
            text = '\n'.join([f'APPLY  database={db}', *preview, '已写入。'])
        except BaseException:
            try:
                c.rollback()
            except Exception:
                pass
            raise
        finally:
            c.close()
    print(text)
    if args.out:
        Path(args.out).write_text(text + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
