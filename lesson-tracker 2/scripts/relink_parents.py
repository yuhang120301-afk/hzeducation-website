#!/usr/bin/env python3
"""Move chosen students from the wrong parent to the right one.

Dry-run is the default. It checks names and phones and does not write.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/relink_parents.py --map scripts/relink_linjing_parents.json
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/relink_parents.py --map scripts/relink_linjing_parents.json --apply
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/relink_parents.py --set 56=39 --set 64=new:Zoey家长（待定）

The numbers in the bundled map are students.id (the #id printed by
report_parent_links.py), not profile ids. A listed student takes every
course row of the same profile with them.

--apply uses one transaction and busy_timeout 30000. It changes
students.parent_id and profile_parents only, plus new placeholder parent
accounts. It does not delete students, lessons, or money, and it does not
change journal_mode or run VACUUM. A student is never left with no parent.
"""
import argparse
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auditlog
import profiles
import server


class PlanError(RuntimeError):
    pass


def connect(db_path, write):
    if write:
        # isolation_level=None does not open a transaction on the first statement.
        # Schema work can then finish before BEGIN IMMEDIATE.
        c = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        c.execute('PRAGMA foreign_keys=ON')
    else:
        c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
        c.execute('PRAGMA query_only=ON')
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    return c


def finish_implicit_transaction(c):
    """Schema reads and ALTERs can leave a transaction open under the default adapter."""
    if c.in_transaction:
        c.commit()


def integrity(c, when):
    row = c.execute('PRAGMA integrity_check').fetchone()
    if not row or row[0] != 'ok':
        raise RuntimeError(f'integrity_check {when}: {row[0] if row else "no result"}')


def counts(c):
    def n(table):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            return 0
        return c.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n']
    return {'students': n('students'), 'lessons': n('lessons'), 'ledger': n('ledger')}


def phone_digits(value):
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def load_mapping(path, sets):
    moves = []
    source = None
    if path:
        data = json.loads(Path(path).read_text())
        source = data.get('source_parent')
        for item in data.get('moves') or []:
            moves.append(normalize_move(item))
    for spec in sets or []:
        student, _, parent = str(spec).partition('=')
        if not student or not parent:
            raise PlanError(f'--set 格式应为 学生编号=家长编号 或 学生编号=new:名字，收到 {spec}')
        moves.append(normalize_move({'student_ids': [student], 'parent': parent}))
    if not moves:
        raise PlanError('请用 --map 或 --set 写出要改的学生。')
    return source, moves


def normalize_move(item):
    raw_ids = item.get('student_ids') or item.get('students') or []
    names = {str(key): value for key, value in (item.get('names') or {}).items()}
    student_ids = []
    for value in raw_ids:
        if isinstance(value, dict):
            student_ids.append(int(value.get('id') or value.get('student_id')))
            if value.get('name'):
                names[str(value['id'])] = value['name']
        else:
            text = str(value)
            if text.startswith('profile:'):
                raise PlanError('这一版按 students.id 填写。档案编号请先在报告里对上学生编号。')
            student_ids.append(int(text))
    parent = item.get('parent')
    if isinstance(parent, dict):
        parent = parent.get('id')
    return {
        'student_ids': student_ids,
        'names': names,
        'parent': parent,
        'parent_name': item.get('parent_name') or '',
        'parent_phone': item.get('parent_phone') or '',
    }


def owner_id(c):
    row = c.execute('SELECT user_id FROM organization_owners ORDER BY user_id LIMIT 1').fetchone()
    if row:
        return row['user_id']
    row = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise PlanError('找不到老板账号，无法写入操作日志。')
    return row['id']


def check_parent(c, parent_id, expect_name, expect_phone):
    row = c.execute('SELECT id, name, phone, role FROM users WHERE id=?', (int(parent_id),)).fetchone()
    if not row or row['role'] != 'parent':
        raise PlanError(f'家长 #{parent_id} 不存在，或不是家长账号。')
    if c.execute('SELECT 1 FROM teachers WHERE user_id=?', (row['id'],)).fetchone():
        raise PlanError(f"#{row['id']} {row['name']} 是老师账号，不能当成家长。")
    if expect_name and expect_name not in (row['name'] or ''):
        raise PlanError(f"家长 #{row['id']} 的名字是 {row['name']}，不是 {expect_name}。")
    if expect_phone and phone_digits(row['phone']) != phone_digits(expect_phone):
        raise PlanError(f"家长 #{row['id']} {row['name']} 的电话是 {row['phone']}，不是 {expect_phone}。")
    return row


def rows_for(c, student_ids, names):
    found = []
    seen = set()
    for sid in student_ids:
        row = c.execute('SELECT id, name, course, profile_id, parent_id FROM students WHERE id=?', (sid,)).fetchone()
        if not row:
            raise PlanError(f'学生 #{sid} 不存在。报告里的编号是 students.id。')
        expect = names.get(str(sid))
        if expect and row['name'] != expect:
            raise PlanError(f"学生 #{sid} 的名字是 {row['name']}，不是 {expect}。")
        if not row['profile_id']:
            raise PlanError(f"学生 #{sid} {row['name']} 没有档案编号，不能安全地改家长。")
        profile_rows = c.execute(
            'SELECT id, name, course, profile_id, parent_id FROM students WHERE profile_id=? ORDER BY id',
            (row['profile_id'],)).fetchall()
        for item in profile_rows:
            if item['id'] in seen:
                continue
            seen.add(item['id'])
            found.append(item)
    return found


def build_groups(c, source, moves):
    if source:
        check_parent(c, source['id'], source.get('name') or '', source.get('phone') or '')
    groups = []
    claimed = {}
    for move in moves:
        rows = rows_for(c, move['student_ids'], move['names'])
        parent = move['parent']
        created_name = ''
        parent_row = None
        if isinstance(parent, str) and parent.startswith('new:'):
            created_name = parent[4:].strip()
            if not created_name:
                raise PlanError('new: 后面要写家长显示名。')
        else:
            parent_row = check_parent(c, parent, move['parent_name'], move['parent_phone'])
        for row in rows:
            previous = claimed.get(row['profile_id'])
            target_key = created_name or int(parent)
            if previous and previous != target_key:
                raise PlanError(f"档案 {row['profile_id']}（{row['name']}）被分到了两位家长。")
            claimed[row['profile_id']] = target_key
        groups.append({'rows': rows, 'parent': parent_row, 'new_name': created_name, 'stay': bool(parent_row and source and parent_row['id'] == source['id'])})
    return groups


def describe(c, source, groups):
    lines = []
    source_id = source['id'] if source else None
    for group in groups:
        names = '、'.join(f"{row['name']}#{row['id']}{row['course']}" for row in group['rows'])
        if group['stay']:
            lines.append(f'保持  {names}  仍是 {group["parent"]["name"]}#{group["parent"]["id"]}')
            for row in group['rows']:
                if source_id and row['parent_id'] != source_id:
                    raise PlanError(f"{row['name']}#{row['id']} 现在的家长是 #{row['parent_id']}，不是要保留的 #{source_id}。")
            continue
        if group['new_name']:
            existing = placeholder(c, group['new_name'])
            label = f"新建 {group['new_name']}" if not existing else f"沿用 {group['new_name']}#{existing['id']}"
        else:
            label = f"{group['parent']['name']}#{group['parent']['id']} {group['parent']['phone']}"
        lines.append(f'改挂  {names}  → {label}')
    return lines


def placeholder(c, name):
    return c.execute(
        "SELECT id, name, phone FROM users WHERE role='parent' AND name=? AND phone LIKE 'pending-%' ORDER BY id LIMIT 1",
        (name,)).fetchone()


_PLACEHOLDER_PASSWORD = None


def placeholder_password():
    global _PLACEHOLDER_PASSWORD
    if _PLACEHOLDER_PASSWORD is None:
        _PLACEHOLDER_PASSWORD = server.password_hash(secrets.token_urlsafe(18))
    return _PLACEHOLDER_PASSWORD


def ensure_parent(c, group, made):
    if group['parent']:
        return group['parent']['id']
    name = group['new_name']
    if name in made:
        return made[name]
    existing = placeholder(c, name)
    if existing:
        made[name] = existing['id']
        return existing['id']
    phone = 'pending-' + secrets.token_hex(6)
    pid = c.execute(
        'INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
        (phone, name, placeholder_password(), 'parent')).lastrowid
    made[name] = pid
    return pid


def parent_count(c, profile_id):
    primary = {row['parent_id'] for row in c.execute('SELECT parent_id FROM students WHERE profile_id=?', (profile_id,))}
    extra = {row['user_id'] for row in c.execute('SELECT user_id FROM profile_parents WHERE profile_id=?', (profile_id,))}
    return len(primary | extra)


def apply_groups(c, actor, source, groups):
    before = counts(c)
    made = {}
    source_id = source['id'] if source else None
    auditlog.schema(c)
    profiles.schema(c)
    auditlog.begin(c)
    for group in groups:
        if group['stay']:
            continue
        parent_id = ensure_parent(c, group, made)
        profiles_done = set()
        for row in group['rows']:
            if row['profile_id'] in profiles_done:
                continue
            profiles_done.add(row['profile_id'])
            c.execute('UPDATE students SET parent_id=? WHERE profile_id=?', (parent_id, row['profile_id']))
            c.execute('INSERT OR IGNORE INTO profile_parents(profile_id, user_id) VALUES(?,?)', (row['profile_id'], parent_id))
            if source_id and source_id != parent_id:
                c.execute('DELETE FROM profile_parents WHERE profile_id=? AND user_id=?', (row['profile_id'], source_id))
            if parent_count(c, row['profile_id']) < 1:
                raise PlanError(f"{row['name']} 会变成没有家长，已停止。")
            c.execute(
                'INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',
                (row['id'], actor, 'parent_relinked'))
    auditlog.hint(c, '纠正林静名下误挂的家长')
    auditlog.finish(c, {'id': actor, 'role': 'owner'})
    after = counts(c)
    if after != before:
        raise PlanError(f'学生、课程或账目数量变了：{before} → {after}')


def main():
    parser = argparse.ArgumentParser(description='Relink students to the correct parent.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--map', default='')
    parser.add_argument('--set', action='append', default=[], help='学生编号=家长编号，或 学生编号=new:显示名')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit('只能选 --dry-run 或 --apply 其中一个。')
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    source, moves = load_mapping(args.map, args.set)
    if not args.apply:
        c = connect(args.db, False)
        try:
            groups = build_groups(c, source, moves)
            lines = describe(c, source, groups)
        finally:
            c.close()
        print('\n'.join([f'DRY-RUN  database={os.path.realpath(args.db)}', *lines, '未写入。']))
        return
    c = connect(args.db, True)
    try:
        profiles.schema(c)
        auditlog.schema(c)
        finish_implicit_transaction(c)
        c.execute('BEGIN IMMEDIATE')
        integrity(c, 'before changes')
        groups = build_groups(c, source, moves)
        lines = describe(c, source, groups)
        apply_groups(c, owner_id(c), source, groups)
        integrity(c, 'before commit')
        c.commit()
        print('\n'.join([f'APPLY  database={os.path.realpath(args.db)}', *lines, '已写入。学生、课程和账目数量没有变。']))
    except BaseException:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        c.close()


if __name__ == '__main__':
    try:
        main()
    except PlanError as exc:
        raise SystemExit(str(exc))
