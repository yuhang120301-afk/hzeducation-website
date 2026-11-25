#!/usr/bin/env python3
"""Add one teaching subject to a teacher. Dry-run is the default.

The boss can also tick the subject on the teacher page. This is the same
change, for the production shell. Do not set LESSON_DB.

  python3 scripts/allow_teacher_subject.py --teacher Vincent --subject 新加坡数学
  python3 scripts/allow_teacher_subject.py --teacher Vincent --subject 新加坡数学 --apply
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def connect(db_path):
    c = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c


def names_of(row):
    found = []
    if row['subject']:
        found.extend(part.strip() for part in str(row['subject']).replace('，', '、').split('、') if part.strip())
    try:
        stored = json.loads(row['subjects'] or '[]')
    except json.JSONDecodeError:
        stored = []
    if isinstance(stored, list):
        found.extend(str(item).strip() for item in stored if str(item).strip())
    out = []
    for name in found:
        if name not in out:
            out.append(name)
    return out


def main():
    parser = argparse.ArgumentParser(description='Let one teacher teach one more subject.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--teacher', required=True, help='Teacher name, for example Vincent.')
    parser.add_argument('--subject', required=True, help='Subject to add, for example 新加坡数学.')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    import teaching
    subject = teaching.canonical_subject(args.subject.strip())
    if not subject:
        raise SystemExit('请填写科目。')
    wanted = ' '.join(args.teacher.strip().casefold().split())
    c = connect(args.db)
    try:
        if 'subjects' not in {row['name'] for row in c.execute('PRAGMA table_info(teachers)')}:
            c.execute("ALTER TABLE teachers ADD COLUMN subjects TEXT NOT NULL DEFAULT '[]'")
        rows = c.execute('''SELECT t.id, t.subject, t.subjects, u.name
            FROM teachers t JOIN users u ON u.id=t.user_id ORDER BY t.id''').fetchall()
        matches = [row for row in rows if ' '.join(str(row['name'] or '').strip().casefold().split()) == wanted]
        if not matches:
            raise SystemExit(f'找不到老师 {args.teacher.strip()}。')
        if len(matches) > 1:
            listed = '，'.join(f"#{row['id']} {row['name']}" for row in matches)
            raise SystemExit(f'有好几位同名老师：{listed}。')
        row = matches[0]
        before = names_of(row)
        after = list(before)
        if subject not in after:
            after.append(subject)
        lines = [
            f"{'APPLY' if args.apply else 'DRY-RUN'}  database={os.path.realpath(args.db)}",
            f"teacher=#{row['id']} {row['name']}",
            'before: ' + '、'.join(before or ['（没有科目）']),
            'after:  ' + '、'.join(after),
        ]
        if subject in before:
            lines.append('已经勾过这个科目。')
        if args.apply and subject not in before:
            c.execute('BEGIN IMMEDIATE')
            c.execute('UPDATE teachers SET subject=?, subjects=? WHERE id=?',
                ('、'.join(after), json.dumps(after, ensure_ascii=False), row['id']))
            c.execute('COMMIT')
            lines.append('已写入。')
        else:
            lines.append('未写入。' if not args.apply else '已写入。')
        print('\n'.join(lines))
    except Exception:
        if c.in_transaction:
            c.execute('ROLLBACK')
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
