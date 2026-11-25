#!/usr/bin/env python3
"""Add 新加坡数学 enrolments for students Helen named.

Dry-run is the default and writes nothing.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/seed_singapore_enrolments.py
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/seed_singapore_enrolments.py --apply

Each new row uses the same profile_id as that student's existing enrolment.
The course starts with 0 lessons. The hourly rate is stored on that row in
students.custom_hourly_cents (cents, so $100 is 10000 and $0 is 0). NULL would
mean the catalog default. These students get the rate Helen set, including $0.

A name must match one profile. Active enrolments are preferred. A student
whose rows are all archived, such as Austin Hao, still uses that profile_id.
If a 新加坡数学 enrolment already exists for the profile, it is left as it is.

--apply uses one connection, PRAGMA busy_timeout=30000, and one
BEGIN IMMEDIATE transaction. It does not change journal_mode and does not
run VACUUM. If any name is ambiguous, nothing is written.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUBJECT = '新加坡数学'

# hourly_cents is the per-enrolment override. enrolment_id and profile_id are
# checks, not a search key. The search key is the enrolment name.
SPECS = (
    {'name': 'Austin Hao', 'hourly_cents': 0, 'kind': '一对一', 'enrolment_id': 1, 'profile_id': 1,
     'note': '报名 1 和 67 已归档，仍用档案 1'},
    {'name': 'Scarlett', 'hourly_cents': 10000, 'kind': '小班课', 'enrolment_id': 12, 'profile_id': None,
     'note': '小班课'},
    {'name': 'Andy', 'hourly_cents': 10000, 'kind': '小班课', 'enrolment_id': 11, 'profile_id': 11,
     'note': '报名 11 已归档，档案 11。与 Scarlett 同一小班，排课时把两人放在同一节'},
    {'name': 'Yilia', 'hourly_cents': 10000, 'kind': '小班课', 'enrolment_id': 14, 'profile_id': None,
     'note': '暂时上一对一补课，报名仍是小班课，价格仍是 $100'},
    {'name': 'Benjamin', 'hourly_cents': 8500, 'kind': '一对一', 'enrolment_id': 68, 'profile_id': 28,
     'note': '一对一'},
    {'name': 'Edward', 'hourly_cents': 8500, 'kind': '一对一', 'enrolment_id': 39, 'profile_id': None,
     'note': '一对一'},
    {'name': 'Shawn Lyu', 'hourly_cents': 8500, 'kind': '一对一', 'enrolment_id': 23, 'profile_id': None,
     'note': '一对一'},
    {'name': 'Aaron', 'hourly_cents': 12000, 'kind': '一对一', 'enrolment_id': 25, 'profile_id': None,
     'note': '一对一'},
    {'name': 'Sheldon', 'hourly_cents': 12000, 'kind': '一对一', 'enrolment_id': 34, 'profile_id': None,
     'note': '一对一'},
)


class PlanError(RuntimeError):
    pass


def connect(db_path, write):
    if write:
        c = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        c.execute('PRAGMA foreign_keys=ON')
    else:
        c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
        c.execute('PRAGMA query_only=ON')
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    return c


def integrity(c, when):
    row = c.execute('PRAGMA integrity_check').fetchone()
    detail = row[0] if row else 'no result'
    if detail != 'ok':
        raise RuntimeError(f'integrity_check {when}: {detail}')


def norm(name):
    return ' '.join(str(name or '').casefold().split())


def columns(c, table):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return set()
    return {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}


def named_rows(c, name):
    target = norm(name)
    return [row for row in c.execute('SELECT * FROM students') if norm(row['name']) == target]


def resolve_student(c, spec):
    """One profile for this name. Active rows win. Archived-only still resolves."""
    rows = named_rows(c, spec['name'])
    known = None
    if spec.get('enrolment_id'):
        known = c.execute('SELECT * FROM students WHERE id=?', (spec['enrolment_id'],)).fetchone()
        if not known:
            raise PlanError(f"{spec['name']}：找不到报名 {spec['enrolment_id']}")
        if norm(known['name']) != norm(spec['name']):
            raise PlanError(f"{spec['name']}：报名 {spec['enrolment_id']} 的名字是 {known['name']}")
        if spec.get('profile_id') is not None and known['profile_id'] != spec['profile_id']:
            raise PlanError(
                f"{spec['name']}：报名 {spec['enrolment_id']} 属于档案 {known['profile_id']}，不是 {spec['profile_id']}")
        if all(row['id'] != known['id'] for row in rows):
            rows = rows + [known]
    if not rows:
        raise PlanError(f"{spec['name']}：没有同名报名")
    active = [row for row in rows if not row['archived']]
    pool = active or rows
    profiles = sorted({row['profile_id'] for row in pool})
    if spec.get('profile_id') is not None:
        known_profile = spec['profile_id']
        if known_profile not in {row['profile_id'] for row in rows}:
            raise PlanError(f"{spec['name']}：同名报名不在档案 {known_profile}")
        if known_profile not in profiles:
            raise PlanError(f"{spec['name']}：在读报名不在档案 {known_profile}")
        profiles = [known_profile]
    if len(profiles) != 1:
        detail = []
        for pid in profiles:
            ids = ', '.join(str(row['id']) for row in pool if row['profile_id'] == pid)
            detail.append(f'档案 {pid}（报名 {ids}）')
        raise PlanError(f"{spec['name']}：名字对应多个学生，已停止。{'；'.join(detail)}")
    profile_id = profiles[0]
    if known and known['profile_id'] != profile_id:
        raise PlanError(
            f"{spec['name']}：报名 {known['id']} 属于档案 {known['profile_id']}，同名在读学生是档案 {profile_id}")
    chosen = [row for row in pool if row['profile_id'] == profile_id]
    chosen.sort(key=lambda row: (int(row['archived'] or 0), 0 if known and row['id'] == known['id'] else 1, row['id']))
    return chosen[0]


def existing_singapore(c, profile_id):
    cols = columns(c, 'students')
    if 'subject_id' in cols and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='subjects'").fetchone():
        return c.execute('''SELECT id, archived FROM students
            WHERE profile_id=? AND (course=? OR subject_id=(SELECT id FROM subjects WHERE name=?))
            ORDER BY id''', (profile_id, SUBJECT, SUBJECT)).fetchall()
    return c.execute('SELECT id, archived FROM students WHERE profile_id=? AND course=? ORDER BY id',
        (profile_id, SUBJECT)).fetchall()


def money(cents):
    return f'${cents / 100:.2f}'


def describe(c, spec, source):
    found = existing_singapore(c, source['profile_id'])
    state = '已归档' if source['archived'] else '在读'
    base = (f"{spec['name']}  档案 {source['profile_id']}  来源报名 {source['id']}（{state}）  "
            f"{spec['kind']}  {money(spec['hourly_cents'])}/小时  余额 0")
    if spec.get('note'):
        base += f"  {spec['note']}"
    if found:
        ids = ', '.join(str(row['id']) for row in found)
        return {'action': 'skip', 'line': base + f'  已有新加坡数学报名 {ids}，跳过', 'spec': spec, 'source': source}
    return {'action': 'create', 'line': base + '  将新建报名', 'spec': spec, 'source': source}


def build_plan(c):
    errors = []
    items = []
    for spec in SPECS:
        try:
            items.append(describe(c, spec, resolve_student(c, spec)))
        except PlanError as exc:
            errors.append(str(exc))
    if errors:
        raise PlanError('\n'.join(errors))
    return items


def ensure_ready(c):
    # Do not call pricing.schema: its executescript commits the open transaction.
    import pricing
    import teaching
    teaching.ensure_catalogs(c)
    pricing.ensure_enrolment_price(c)
    subject = c.execute('SELECT id FROM subjects WHERE name=?', (SUBJECT,)).fetchone()
    if not subject:
        raise PlanError('目录里没有新加坡数学。')
    types = {}
    for name in ('一对一', '小班课'):
        row = c.execute('SELECT id FROM course_types WHERE name=?', (name,)).fetchone()
        if not row:
            raise PlanError(f'课型 {name} 不存在。')
        types[name] = row['id']
    if 'custom_hourly_cents' not in columns(c, 'students'):
        raise PlanError('报名上还没有 custom_hourly_cents。')
    return subject['id'], types


def insert_enrolment(c, source, subject_id, type_id, spec):
    cols = columns(c, 'students')
    data = {
        'name': source['name'],
        'course': SUBJECT,
        'parent_id': source['parent_id'],
        'profile_id': source['profile_id'],
        'balance': 0,
        'archived': 0,
        'billing_unit': source['billing_unit'] if 'billing_unit' in source.keys() and source['billing_unit'] else 'lesson',
        'grade': source['grade'] if 'grade' in source.keys() else '',
        'birthday': source['birthday'] if 'birthday' in source.keys() else '',
        'notes': source['notes'] if 'notes' in source.keys() else '',
        'helen_original': int(source['helen_original'] or 0) if 'helen_original' in source.keys() else 0,
        'subject_id': subject_id,
        'course_type_id': type_id,
        'level_code': source['level_code'] if 'level_code' in source.keys() else '',
        'level_year': int(source['level_year'] or 0) if 'level_year' in source.keys() else 0,
        'study_level': source['study_level'] if 'study_level' in source.keys() else '',
        'custom_hourly_cents': int(spec['hourly_cents']),
        'voided': 0,
        'course_note': '',
    }
    use = [(key, value) for key, value in data.items() if key in cols]
    keys = ','.join(key for key, _value in use)
    marks = ','.join('?' for _value in use)
    cursor = c.execute(f'INSERT INTO students({keys}) VALUES({marks})', [value for _key, value in use])
    return cursor.lastrowid


def apply_plan(c, items, subject_id, types):
    made = []
    for item in items:
        if item['action'] != 'create':
            continue
        if existing_singapore(c, item['source']['profile_id']):
            item['action'] = 'skip'
            item['line'] += '  写入前已存在，跳过'
            continue
        new_id = insert_enrolment(c, item['source'], subject_id, types[item['spec']['kind']], item['spec'])
        made.append(new_id)
        item['line'] += f'  已新建报名 {new_id}'
    return made


def counts(c):
    def n(table):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            return 0
        return c.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n']
    return {'ledger': n('ledger'), 'credit_batches': n('credit_batches'), 'lessons': n('lessons')}


def main():
    parser = argparse.ArgumentParser(description='Add 新加坡数学 enrolments. Dry-run unless --apply.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    if not args.apply:
        c = connect(args.db, False)
        try:
            integrity(c, 'before dry-run')
            items = build_plan(c)
            ready = c.execute('SELECT 1 FROM subjects WHERE name=?', (SUBJECT,)).fetchone() if c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='subjects'").fetchone() else None
            header = [f'DRY-RUN  database={os.path.realpath(args.db)}']
            if not ready:
                header.append('目录里还没有新加坡数学。--apply 会补上这一科，不改其他科目。')
            if 'custom_hourly_cents' not in columns(c, 'students'):
                header.append('报名上还没有单独时薪栏。--apply 会加上，空值表示用目录价。')
        finally:
            c.close()
        print('\n'.join([*header, *(item['line'] for item in items), '未写入。']))
        return
    c = connect(args.db, True)
    try:
        c.execute('BEGIN IMMEDIATE')
        integrity(c, 'before changes')
        before = counts(c)
        subject_id, types = ensure_ready(c)
        items = build_plan(c)
        apply_plan(c, items, subject_id, types)
        after = counts(c)
        if after != before:
            raise PlanError(f'账本、课时包或课程数量变了：{before} → {after}')
        integrity(c, 'before commit')
        c.execute('COMMIT')
        print('\n'.join([f'APPLY  database={os.path.realpath(args.db)}', *(item['line'] for item in items), '已写入。']))
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
