#!/usr/bin/env python3
"""Stop old 2026 repeating series and remove only their future unused lessons.

Dry-run is the default. Uses LESSON_DB. Take a backup before --apply.

  LESSON_DB="$LESSON_DB" python3 scripts/cleanup_stale_series.py
  LESSON_DB="$LESSON_DB" python3 scripts/cleanup_stale_series.py --apply

Deletes a lesson only when it is in the future, still scheduled, has no
课后记录, and has no ledger entry. Completed lessons stay. Series that start
from 2027-01-25 through 2027-01-31 stay, including every lesson on them.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recurrence
from teaching import now_local


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


def main():
    parser = argparse.ArgumentParser(description='Remove future lessons from stale 2026 series.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    c = connect(args.db, args.apply)
    try:
        now = now_local().strftime('%Y-%m-%dT%H:%M')
        if args.apply:
            c.execute('BEGIN IMMEDIATE')
        rows = recurrence.stale_series_report(c, now)
        removable = sum(1 for item in rows for lesson in item['lessons'] if not lesson['locked'])
        kept = sum(1 for item in rows for lesson in item['lessons'] if lesson['locked'])
        lines = [f"{'APPLY' if args.apply else 'DRY-RUN'}  database={os.path.realpath(args.db)}",
            f'过期重复课 {len(rows)}，可删的以后的课 {removable}，因已有记录或账而保留 {kept}。',
            '2027 年 1 月 25 日到 31 日开始的课表不会动。']
        for item in rows:
            lines.append(f"系列 {item['series_id']}  从 {item['started']}  老师 {item['teacher'] or '未填'}  {'、'.join(item['students'])}")
            for lesson in item['lessons']:
                lines.append(f"  {'删除' if args.apply and not lesson['locked'] else '将删除' if not lesson['locked'] else '保留'}  {lesson['starts_at']}  {lesson['title']}")
        if args.apply:
            result = recurrence.stop_stale_series(c, now)
            c.commit()
            lines.append(f"已删除 {result['removed']} 节，已停止 {result['stopped']} 个重复课。")
        else:
            lines.append('未写入。')
        print('\n'.join(lines))
    except BaseException:
        if args.apply:
            c.rollback()
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
