#!/usr/bin/env python3
"""Read-only list of parents and the students linked to them.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/report_parent_links.py

The database is opened with mode=ro. This script does not write.
"""
import datetime as dt
import os
import sqlite3
import sys
from zoneinfo import ZoneInfo


def connect(db_path):
    c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA query_only=ON')
    return c


def has(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def main():
    db = os.environ.get('LESSON_DB', '')
    if not db or not os.path.exists(db):
        raise SystemExit('请设置 LESSON_DB，指向现有的数据库文件。')
    c = connect(db)
    try:
        lines = ['只读  database=' + os.path.realpath(db)]
        if not has(c, 'users') or not has(c, 'students'):
            lines.append('数据库里没有家长或学生表。')
            print('\n'.join(lines))
            return
        cutoff = (dt.datetime.now(ZoneInfo('Australia/Melbourne')) - dt.timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M')
        parents = c.execute("SELECT id, name, phone FROM users WHERE role='parent' ORDER BY name").fetchall()
        for parent in parents:
            kids = list(c.execute('''SELECT s.id, s.name, s.course FROM students s
                WHERE s.parent_id=? OR EXISTS (
                    SELECT 1 FROM profile_parents pp WHERE pp.profile_id=s.profile_id AND pp.user_id=?)
                ORDER BY s.name, s.course''', (parent['id'], parent['id']))) if has(c, 'profile_parents') else list(c.execute(
                'SELECT id, name, course FROM students WHERE parent_id=? ORDER BY name, course', (parent['id'],)))
            surnames = {row['name'][:1] for row in kids if row['name']}
            flags = []
            if len(surnames) > 1:
                flags.append('学生姓不同')
            interesting = any(token in (parent['name'] or '') or any(token in (row['name'] or '') for row in kids) for token in ('林静', 'Zachary'))
            if interesting:
                flags.append('林静或Zachary')
            recent = []
            if has(c, 'profile_audit'):
                ids = [row['id'] for row in kids]
                if ids:
                    marks = ','.join('?' for _ in ids)
                    recent = c.execute(f'''SELECT action, created_at FROM profile_audit
                        WHERE student_id IN ({marks}) AND created_at>=? AND action LIKE '%parent%' ''', (*ids, cutoff)).fetchall()
            if recent:
                flags.append('24小时内改过家长')
            child_text = '、'.join(f"{row['name']}#{row['id']}{row['course']}" for row in kids) or '没有学生'
            lines.append(f"家长{parent['name']}#{parent['id']} {parent['phone']} → {child_text}" + (('  ' + ' '.join(flags)) if flags else ''))
    finally:
        c.close()
    print('\n'.join(lines))


if __name__ == '__main__':
    sys.exit(main())
