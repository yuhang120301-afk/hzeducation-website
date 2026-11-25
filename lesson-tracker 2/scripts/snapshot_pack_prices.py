#!/usr/bin/env python3
"""Write a unit price onto packs that do not have one yet. Dry-run is the default.

Already-priced packs are left alone, so a later price rise does not change them.
Uses LESSON_DB.

  LESSON_DB=/path/to/lessons.sqlite3 python3 scripts/snapshot_pack_prices.py
  LESSON_DB=/path/to/lessons.sqlite3 python3 scripts/snapshot_pack_prices.py --apply
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

import pricing


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


def fee_list(c, pack):
    purchased = int(pack['purchased'] or 0)
    lessons = purchased // 100
    if lessons <= 0:
        return None
    cash = pack['cash_delta']
    if cash:
        each = int(round(cash * 10 / lessons))
        return [each] * lessons
    student = c.execute('SELECT * FROM students WHERE id=?', (pack['student_id'],)).fetchone()
    if not student:
        return None
    hourly = pricing.price_for(c, student, pack['credited_on'] or None)
    if hourly is None:
        return None
    each = pricing.per_lesson_cents(hourly, 60) * 10
    return [each] * lessons


def plan(c):
    rows = c.execute('''SELECT b.*, cash.cash_delta FROM credit_batches b
        LEFT JOIN cash_entries cash ON cash.ledger_id=b.ledger_id
        WHERE IFNULL(b.unit_fees,'')='' AND b.purchased>0''').fetchall()
    ready = []
    skipped = []
    for pack in rows:
        fees = fee_list(c, pack)
        if fees:
            ready.append((pack, fees))
        else:
            skipped.append(pack)
    return ready, skipped


def main():
    parser = argparse.ArgumentParser(description='Snapshot a unit price onto old packs.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    c = connect(args.db, args.apply)
    try:
        if args.apply:
            pricing.schema(c)
            c.commit()
            c.execute('BEGIN IMMEDIATE')
        ready, skipped = plan(c)
        lines = [f"{'APPLY' if args.apply else 'DRY-RUN'}  database={os.path.realpath(args.db)}",
            f'将写入单价的课时包：{len(ready)} 个', f'算不出价格、不改：{len(skipped)} 个']
        for pack, fees in ready:
            lines.append(f"  包{pack['id']} 学生{pack['student_id']} {len(fees)} 节 每节 {fees[0]/1000:.2f} 元")
        for pack in skipped:
            lines.append(f"  包{pack['id']} 学生{pack['student_id']} 没有可用价格")
        if args.apply:
            for pack, fees in ready:
                c.execute('UPDATE credit_batches SET unit_fees=? WHERE id=? AND IFNULL(unit_fees,\'\')=\'\'',
                    (json.dumps(fees), pack['id']))
            c.commit()
            lines.append(f'已写入 {len(ready)} 个课时包。')
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
