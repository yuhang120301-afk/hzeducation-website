#!/usr/bin/env python3
"""Mark profiles that were archived as withdrawn. Dry-run is the default.

Uses LESSON_DB. Does not use /var/data/lessons.sqlite3 unless that is LESSON_DB.

  LESSON_DB=/path/to/lessons.sqlite3 python3 scripts/backfill_withdrawn_status.py
  LESSON_DB=/path/to/lessons.sqlite3 python3 scripts/backfill_withdrawn_status.py --apply
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import profiles


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


def plan(c):
    profiles.ensure_enrolment_columns(c)
    rows = []
    seen = set()
    for row in c.execute('''SELECT s.profile_id, s.name, a.action FROM profile_audit a
        JOIN students s ON s.id=a.student_id
        WHERE s.profile_id IS NOT NULL AND a.action IN ('archived','reinstated')
        ORDER BY a.id'''):
        seen.add(row['profile_id'])
        rows.append(row)
    latest = {}
    names = {}
    for row in rows:
        latest[row['profile_id']] = row['action']
        names[row['profile_id']] = row['name']
    todo = []
    for profile_id, action in latest.items():
        if action != 'archived':
            continue
        status = c.execute('SELECT status FROM student_profiles WHERE id=?', (profile_id,)).fetchone()
        if status and status['status'] == 'withdrawn':
            continue
        todo.append((profile_id, names.get(profile_id) or ''))
    return todo


def main():
    parser = argparse.ArgumentParser(description='Backfill withdrawn profile status.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    c = connect(args.db, args.apply)
    try:
        if args.apply:
            c.execute('BEGIN IMMEDIATE')
        todo = plan(c)
        lines = [f"{'APPLY' if args.apply else 'DRY-RUN'}  database={os.path.realpath(args.db)}",
            f'将标成退学的学员：{len(todo)} 人']
        for profile_id, name in todo:
            lines.append(f'  档案{profile_id} {name}')
        if not todo:
            lines.append('没有需要补记的退学学员。')
        if args.apply:
            for profile_id, _name in todo:
                c.execute("UPDATE student_profiles SET status='withdrawn' WHERE id=? AND status!='withdrawn'", (profile_id,))
            c.commit()
            lines.append(f'已更新 {len(todo)} 人。')
        else:
            lines.append('未写入。确认后加 --apply。')
        print('\n'.join(lines))
    except BaseException:
        if args.apply:
            c.rollback()
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
