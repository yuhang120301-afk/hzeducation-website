#!/usr/bin/env python3
"""Turn chosen 退课 receipts into voids. Dry-run is the default.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/void_mistaken_courses.py --ids 12,15
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/void_mistaken_courses.py --ids 12,15 --apply

A row with an attended lesson, a charged lesson, or any money is left alone.
--apply uses one transaction. It does not change journal_mode and does not run VACUUM.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import deletion


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


def integrity(c, when):
    row = c.execute('PRAGMA integrity_check').fetchone()
    if not row or row[0] != 'ok':
        raise RuntimeError(f'integrity_check {when}: {row[0] if row else "no result"}')


def plan(c, ids):
    lines = []
    actions = []
    for vid in ids:
        row = c.execute("SELECT * FROM vouchers WHERE id=?", (vid,)).fetchone()
        if not row or row['kind'] != 'stop':
            lines.append(f'#{vid} 不是退课单据，跳过。')
            continue
        sid = row['student_id']
        problems = deletion.course_problems(c, sid) if sid else []
        if problems:
            lines.append(f"#{vid} {row['student_name']} {row['course']} 不改：{'；'.join(problems)}")
            continue
        lines.append(f"#{vid} {row['student_name']} {row['course']} 将作废这张退课单据，并从已停课程里隐藏。")
        actions.append(row)
    return lines, actions


def apply_actions(c, actions):
    for row in actions:
        c.execute("UPDATE vouchers SET status='void' WHERE id=? AND kind='stop'", (row['id'],))
        if row['student_id']:
            c.execute("UPDATE students SET voided=1, void_reason='加错了' WHERE id=?", (row['student_id'],))


def main():
    parser = argparse.ArgumentParser(description='Void chosen withdrawal receipts.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--ids', required=True, help='退课单据编号，逗号分隔，例如 12,15')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit('只能选 --dry-run 或 --apply 其中一个。')
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    ids = []
    for part in args.ids.split(','):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise SystemExit(f'编号无效：{part}')
        ids.append(int(part))
    if not ids:
        raise SystemExit('请用 --ids 写出单据编号。')
    if not args.apply:
        c = connect(args.db, False)
        try:
            lines, _actions = plan(c, ids)
        finally:
            c.close()
        print('\n'.join([f'DRY-RUN  database={os.path.realpath(args.db)}', *lines]))
        return
    c = connect(args.db, True)
    try:
        deletion.schema(c)
        c.execute('BEGIN IMMEDIATE')
        integrity(c, 'before changes')
        lines, actions = plan(c, ids)
        apply_actions(c, actions)
        integrity(c, 'before commit')
        c.commit()
        print('\n'.join([f'APPLY  database={os.path.realpath(args.db)}', *lines, f'已作废 {len(actions)} 张。']))
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
