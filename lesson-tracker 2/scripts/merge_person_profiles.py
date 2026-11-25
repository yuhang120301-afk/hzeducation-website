#!/usr/bin/env python3
"""Put every person's courses on one student account.

Dry-run is the default. Uses LESSON_DB. One transaction on --apply.
People match by profile id, or by the same normalized name and a shared parent.
Rows that would put two identical course names on one account are only reported.

  LESSON_DB="$LESSON_DB" python3 scripts/merge_person_profiles.py
  LESSON_DB="$LESSON_DB" python3 scripts/merge_person_profiles.py --apply
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


def connect(db_path):
    c = sqlite3.connect(db_path, timeout=30)
    c.execute('PRAGMA foreign_keys=ON')
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    return c


def money_totals(c):
    payments = c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0] if c.execute(
        "SELECT 1 FROM sqlite_master WHERE name='cash_entries'").fetchone() else 0
    balances = c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0]
    return int(payments), int(balances)


def course_clash(group):
    names = [' '.join(str(row['course'] or '').strip().casefold().split()) for row in group['rows']]
    return len(names) != len(set(names))


def render(db_path, apply, plan, before, after):
    lines = [f"{'APPLY' if apply else 'DRY-RUN'}  database={os.path.realpath(db_path)}",
        f'payments_before={before[0]} balances_before={before[1]}',
        f'groups={len(plan)}']
    moved = blocked = 0
    if not plan:
        lines.append('没有需要合并的人。')
    for group in plan:
        clash = course_clash(group)
        if clash:
            blocked += 1
            lines.append(f"不并 {group['name']}：两门课的名称一样，不能放进同一个档案")
        else:
            moved += 1
            lines.append(f"并入档案 #{group['keeper']} {group['name']}")
        for row in group['rows']:
            lines.append(f"  #{row['id']} {row['course']} 原档案 #{row['profile_id']}")
    lines.append(f'merge={moved} blocked={blocked}')
    if apply:
        lines.append(f'payments_after={after[0]} balances_after={after[1]}')
        lines.append('已写入。')
    else:
        lines.append('未写入。')
    return lines


def main():
    parser = argparse.ArgumentParser(description='Group one person onto one profile.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    c = connect(args.db)
    try:
        c.execute('BEGIN IMMEDIATE')
        profiles.schema(c)
        before = money_totals(c)
        plan = profiles.merge_plan(c)
        safe = [group for group in plan if not course_clash(group)]
        after = before
        if args.apply:
            profiles.apply_merge(c, safe)
            after = money_totals(c)
            if after != before:
                raise RuntimeError(f'钱对不上：之前 {before}，之后 {after}')
            c.commit()
        else:
            c.rollback()
        print('\n'.join(render(args.db, args.apply, plan, before, after)))
    except BaseException:
        if args.apply:
            c.rollback()
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
