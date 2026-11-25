#!/usr/bin/env python3
"""Retarget 2027 series that still point at an archived enrolment.

Dry-run is the default. It does not delete series or lessons. Uses LESSON_DB.
Take a backup before --apply. This does not run against production by itself.

  LESSON_DB="$LESSON_DB" python3 scripts/repair_archived_series.py
  LESSON_DB="$LESSON_DB" python3 scripts/repair_archived_series.py --apply

A series moves onto the one active course of the same subject when that course
exists. If the archived row is the only course, the profile is not withdrawn,
and a future series still points at it, --apply marks that row in study again.
A withdrawn profile is only reported.
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

import profiles
import teaching


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


def _loads(raw):
    try:
        return json.loads(raw or '{}')
    except json.JSONDecodeError:
        return {}


def _withdrawn(c, profile_id):
    if not profile_id:
        return False
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_profiles'").fetchone():
        return False
    row = c.execute('SELECT status FROM student_profiles WHERE id=?', (profile_id,)).fetchone()
    return bool(row and 'status' in row.keys() and row['status'] == 'withdrawn')


def _active_match(c, archived):
    subject = teaching.canonical_subject(archived['subject_name'] or archived['course'] or '')
    rows = []
    if archived['profile_id']:
        rows += c.execute('''SELECT s.*, sb.name subject_name FROM students s
            LEFT JOIN subjects sb ON sb.id=s.subject_id
            WHERE s.profile_id=? AND s.archived=0 AND IFNULL(s.voided,0)=0 AND s.id!=?''',
            (archived['profile_id'], archived['id'])).fetchall()
    rows += c.execute('''SELECT s.*, sb.name subject_name FROM students s
        LEFT JOIN subjects sb ON sb.id=s.subject_id
        WHERE s.name=? AND s.parent_id=? AND s.archived=0 AND IFNULL(s.voided,0)=0 AND s.id!=?''',
        (archived['name'], archived['parent_id'], archived['id'])).fetchall()
    seen = set()
    matches = []
    for row in rows:
        if row['id'] in seen:
            continue
        seen.add(row['id'])
        other = teaching.canonical_subject(row['subject_name'] or row['course'] or '')
        if subject and other == subject:
            matches.append(row)
    return matches


def plan(c):
    items = []
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_series'").fetchone():
        return items
    for rule in c.execute('SELECT id, template FROM lesson_series'):
        template = _loads(rule['template'])
        for raw in template.get('student_ids') or []:
            try:
                sid = int(raw)
            except (TypeError, ValueError):
                continue
            student = c.execute('''SELECT s.*, sb.name subject_name FROM students s
                LEFT JOIN subjects sb ON sb.id=s.subject_id WHERE s.id=?''', (sid,)).fetchone()
            if not student or not student['archived']:
                continue
            matches = _active_match(c, student)
            items.append({
                'series_id': rule['id'], 'student_id': sid, 'name': student['name'],
                'course': student['course'], 'profile_id': student['profile_id'],
                'withdrawn': _withdrawn(c, student['profile_id']),
                'active_ids': [row['id'] for row in matches],
            })
    return items


def apply_plan(c, items):
    moved = restored = 0
    for item in items:
        if item['withdrawn']:
            continue
        if len(item['active_ids']) == 1:
            profiles.move_future_lessons(c, item['student_id'], item['active_ids'][0])
            moved += 1
            continue
        if item['active_ids']:
            continue
        c.execute('UPDATE students SET archived=0 WHERE id=? AND IFNULL(voided,0)=0', (item['student_id'],))
        restored += 1
    return moved, restored


def main():
    parser = argparse.ArgumentParser(description='Repair series that point at archived enrolments.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    c = connect(args.db, args.apply)
    try:
        if args.apply:
            c.execute('BEGIN IMMEDIATE')
        items = plan(c)
        lines = [f"{'APPLY' if args.apply else 'DRY-RUN'}  database={os.path.realpath(args.db)}",
            f'重复课还挂在已归档报名上：{len(items)} 处。不会删除这些课。']
        for item in items:
            if item['withdrawn']:
                action = '退学档案，只报告，不恢复'
            elif len(item['active_ids']) == 1:
                action = f"改挂到在读课 #{item['active_ids'][0]}"
            elif item['active_ids']:
                action = '有多门在读课，不自动改'
            else:
                action = '没有另一门在读课，恢复这一行为在读' if args.apply else '没有另一门在读课，--apply 会恢复为在读'
            profile = item['profile_id'] if item['profile_id'] is not None else '空'
            lines.append(f"  {item['name']} #{item['student_id']} {item['course']} 档案{profile}：{action}")
        if args.apply:
            moved, restored = apply_plan(c, items)
            c.commit()
            lines.append(f'已改挂 {moved} 处，已恢复在读 {restored} 行。')
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
