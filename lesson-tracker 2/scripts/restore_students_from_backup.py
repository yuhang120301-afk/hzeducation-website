#!/usr/bin/env python3
"""Recreate student accounts that the 2027 reset removed, without their courses.

Dry-run is the default. The backup is opened read-only. --apply writes one
transaction to LESSON_DB. A person who is already there is not created again.
No course, lesson, or money row is copied. Payment and balance totals must match.

  LESSON_DB="$LESSON_DB" python3 scripts/restore_students_from_backup.py --backup /path/to/backup.sqlite3
  LESSON_DB="$LESSON_DB" python3 scripts/restore_students_from_backup.py --backup /path/to/backup.sqlite3 --apply
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


def has_table(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def columns(c, table):
    if not has_table(c, table):
        return set()
    return {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}


def field(row, name):
    return (row[name] if row and name in row.keys() and row[name] else '') or ''


def money_totals(c):
    payments = c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0] if has_table(c, 'cash_entries') else 0
    balances = c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0] if has_table(c, 'students') else 0
    return int(payments), int(balances)


def backup_people(backup):
    people = []
    if not has_table(backup, 'student_profiles'):
        return people
    for profile in backup.execute('SELECT * FROM student_profiles ORDER BY id'):
        courses = []
        if has_table(backup, 'students') and 'profile_id' in columns(backup, 'students'):
            courses = backup.execute('SELECT * FROM students WHERE profile_id=? ORDER BY archived, id', (profile['id'],)).fetchall()
        name = field(profile, 'name') or next((field(row, 'name') for row in courses if field(row, 'name')), '')
        if not str(name).strip():
            continue
        birthday = field(profile, 'birthday') or next((field(row, 'birthday') for row in courses if field(row, 'birthday')), '')
        grade = field(profile, 'grade') or next((field(row, 'grade') for row in courses if field(row, 'grade')), '')
        notes = field(profile, 'notes') or next((field(row, 'notes') for row in courses if field(row, 'notes')), '')
        parent_ids = []
        if has_table(backup, 'profile_parents'):
            parent_ids = [row['user_id'] for row in backup.execute(
                'SELECT user_id FROM profile_parents WHERE profile_id=? ORDER BY user_id', (profile['id'],))]
        for row in courses:
            if row['parent_id'] not in parent_ids:
                parent_ids.append(row['parent_id'])
        parents = []
        if has_table(backup, 'users'):
            for user_id in parent_ids:
                user = backup.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
                if user and user['role'] == 'parent':
                    parents.append(user)
        people.append({'id': profile['id'], 'name': str(name).strip(), 'birthday': birthday, 'grade': grade,
            'notes': notes, 'parents': parents, 'study_status': field(profile, 'study_status') or 'studying'})
    return people


def live_names(c):
    found = {}
    if 'name' in columns(c, 'student_profiles'):
        for row in c.execute("SELECT id, name FROM student_profiles WHERE TRIM(COALESCE(name,''))!=''"):
            found.setdefault(profiles.normalize_person_name(row['name']), set()).add(row['id'])
    if has_table(c, 'students'):
        for row in c.execute("SELECT profile_id, name FROM students WHERE TRIM(COALESCE(name,''))!=''"):
            found.setdefault(profiles.normalize_person_name(row['name']), set()).add(row['profile_id'])
    return found


def plan_restore(backup, live):
    profiles.ensure_identity(live)
    known = live_names(live)
    actions = []
    for person in backup_people(backup):
        existing = live.execute('SELECT * FROM student_profiles WHERE id=?', (person['id'],)).fetchone()
        name_key = profiles.normalize_person_name(person['name'])
        named = known.get(name_key, set())
        if existing and str(existing['name'] or '').strip():
            actions.append({**person, 'action': 'skip', 'detail': '档案还在'})
            continue
        if named - ({existing['id']} if existing else set()):
            actions.append({**person, 'action': 'skip', 'detail': '已有同名学生，不重复建档'})
            continue
        actions.append({**person, 'action': 'fill' if existing else 'create', 'detail': '补上姓名，不开课' if existing else '恢复学生档案，不开课'})
    return actions


def ensure_parent(c, backup_user):
    found = c.execute('SELECT id, role FROM users WHERE phone=?', (backup_user['phone'],)).fetchone()
    if found:
        return found['id'] if found['role'] == 'parent' else None
    return c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
        (backup_user['phone'], backup_user['name'], backup_user['password'], 'parent')).lastrowid


def apply_restore(c, actions):
    profiles.ensure_identity(c)
    for person in actions:
        if person['action'] not in ('create', 'fill'):
            continue
        if person['action'] == 'create':
            c.execute('INSERT INTO student_profiles(id,name,birthday,grade,notes) VALUES(?,?,?,?,?)',
                (person['id'], person['name'], person['birthday'], person['grade'], person['notes']))
        else:
            c.execute('UPDATE student_profiles SET name=?,birthday=?,grade=?,notes=? WHERE id=? AND TRIM(COALESCE(name,""))=""',
                (person['name'], person['birthday'], person['grade'], person['notes'], person['id']))
        for parent in person['parents']:
            user_id = ensure_parent(c, parent)
            if user_id:
                c.execute('INSERT OR IGNORE INTO profile_parents(profile_id, user_id) VALUES(?,?)', (person['id'], user_id))


def render(live_path, backup_path, apply, actions, before, after):
    chosen = [item for item in actions if item['action'] in ('create', 'fill')]
    lines = [f"{'APPLY' if apply else 'DRY-RUN'}  database={os.path.realpath(live_path)}",
        f'backup={os.path.realpath(backup_path)}',
        f'payments_before={before[0]} balances_before={before[1]}',
        f'restore={len(chosen)} skip={len(actions) - len(chosen)}']
    for item in actions:
        lines.append(f"  #{item['id']} {item['name']} {item['detail']}")
    if not actions:
        lines.append('备份里没有可恢复的学生。')
    if apply:
        lines.append(f'payments_after={after[0]} balances_after={after[1]}')
        lines.append('已写入。没有恢复课程、课时或钱。')
    else:
        lines.append('未写入。')
    return lines


def main():
    parser = argparse.ArgumentParser(description='Restore missing student profiles from a backup.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    if not os.path.exists(args.backup):
        raise SystemExit('找不到备份文件。')
    live = connect(args.db, True)
    backup = connect(args.backup, False)
    try:
        live.execute('BEGIN IMMEDIATE')
        profiles.schema(live)
        before = money_totals(live)
        actions = plan_restore(backup, live)
        after = before
        if args.apply:
            apply_restore(live, actions)
            after = money_totals(live)
            if after != before:
                raise RuntimeError(f'钱对不上：之前 {before}，之后 {after}')
            live.commit()
        else:
            live.rollback()
        print('\n'.join(render(args.db, args.backup, args.apply, actions, before, after)))
    except BaseException:
        if args.apply:
            live.rollback()
        raise
    finally:
        live.close()
        backup.close()


if __name__ == '__main__':
    main()
