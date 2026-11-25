#!/usr/bin/env python3
"""Point future lessons at the active course, and rebuild the active-course index.

Dry-run is the default. Uses LESSON_DB.

  LESSON_DB=/path/to/lessons.sqlite3 python3 scripts/relink_course_lessons.py
  LESSON_DB=/path/to/lessons.sqlite3 python3 scripts/relink_course_lessons.py --apply
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

import deletion
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
    moves = []
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_series'").fetchone():
        return moves
    active = {}
    for row in c.execute('SELECT id, profile_id, course FROM students WHERE archived=0 AND IFNULL(voided,0)=0'):
        active[(row['profile_id'], row['course'])] = row['id']
    archived = {row['id']: row for row in c.execute('SELECT id, profile_id, course, name FROM students WHERE archived=1 OR IFNULL(voided,0)=1')}
    for rule in c.execute('SELECT id, template FROM lesson_series'):
        try:
            template = json.loads(rule['template'] or '{}')
        except json.JSONDecodeError:
            continue
        for item in template.get('student_ids') or []:
            try:
                sid = int(item)
            except (TypeError, ValueError):
                continue
            old = archived.get(sid)
            if not old:
                continue
            target = active.get((old['profile_id'], old['course']))
            moves.append({'series': rule['id'], 'from': sid, 'name': old['name'], 'course': old['course'], 'to': target})
    return moves


def main():
    parser = argparse.ArgumentParser(description='Relink future lessons onto the active course.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    c = connect(args.db, args.apply)
    try:
        if args.apply:
            deletion.schema(c)
            c.execute('BEGIN IMMEDIATE')
        moves = plan(c)
        lines = [f"{'APPLY' if args.apply else 'DRY-RUN'}  database={os.path.realpath(args.db)}",
            f'重复课模板指向已停课程：{len(moves)} 处']
        for item in moves:
            if item['to']:
                lines.append(f"  系列{item['series']} {item['name']} {item['course']} {item['from']} → {item['to']}")
            else:
                lines.append(f"  系列{item['series']} {item['name']} {item['course']} {item['from']} 没有在读的同一课程，不改")
        if args.apply:
            done = 0
            for item in moves:
                if item['to']:
                    profiles.move_future_lessons(c, item['from'], item['to'])
                    done += 1
            c.commit()
            lines.append(f'已改 {done} 处，并重建了在读课程的唯一索引。')
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
