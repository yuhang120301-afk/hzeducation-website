#!/usr/bin/env python3
"""Set each parent's password to their login mobile number.

Dry-run is the default. It prints counts and masked logins only.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/reset_parent_passwords_to_phone.py
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/reset_parent_passwords_to_phone.py --apply

A login that is not a mobile number, including pending- placeholders, is left
alone and listed in masked form. A teacher account is skipped even when its
role column still says parent. --apply uses one transaction. It does not
change the schema, and it signs out only the parents whose password changes.
"""
import argparse
import hmac
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


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


def mask_login(phone):
    text = str(phone or '')
    if text.startswith('pending-'):
        return 'pending-******'
    digits = ''.join(ch for ch in text if ch.isdigit())
    if len(digits) == 10:
        return f'{digits[:2]}xx xxx {digits[-3:]}'
    if len(digits) >= 5:
        return f'{digits[:2]}{"x" * (len(digits) - 5)} {digits[-3:]}'
    return '****'


def mobile_login(phone):
    try:
        return server.phone_value(phone)
    except ValueError:
        return None


def already_phone_password(phone, stored):
    try:
        salt = str(stored or '').split(':', 1)[0]
        return hmac.compare_digest(server.password_hash(phone, salt), stored)
    except (ValueError, IndexError):
        return False


def classify(c):
    has_teachers = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='teachers'").fetchone()
    rows = c.execute("SELECT id, phone, password FROM users WHERE role='parent' ORDER BY id").fetchall()
    change, same, skipped, teachers = [], [], [], 0
    for row in rows:
        if has_teachers and c.execute('SELECT 1 FROM teachers WHERE user_id=?', (row['id'],)).fetchone():
            teachers += 1
            continue
        phone = mobile_login(row['phone'])
        if not phone:
            skipped.append(mask_login(row['phone']))
            continue
        if already_phone_password(phone, row['password']):
            same.append(row['id'])
        else:
            change.append((row['id'], phone))
    return {'change': change, 'same': same, 'skipped': skipped, 'teachers': teachers}


def report(db_path, plan, applied):
    lines = [
        f"{'APPLY' if applied else 'DRY-RUN'}  database={os.path.realpath(db_path)}",
        f"将改密码：{len(plan['change'])}",
        f"已是手机号密码：{len(plan['same'])}",
        f"跳过非手机号登录：{len(plan['skipped'])}",
    ]
    lines.extend(f"  {item}" for item in plan['skipped'])
    lines.append(f"任课老师账号已跳过：{plan['teachers']}")
    lines.append('已写入。改过密码的家长需要重新登录。' if applied else '未写入。')
    return '\n'.join(lines)


def apply_plan(c, plan):
    for user_id, phone in plan['change']:
        c.execute('UPDATE users SET password=? WHERE id=? AND role=?', (server.password_hash(phone), user_id, 'parent'))
        c.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Set parent passwords to their login mobile number.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        raise SystemExit('只能选 --dry-run 或 --apply 其中一个。')
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    if not args.apply:
        c = connect(args.db, False)
        try:
            text = report(args.db, classify(c), False)
        finally:
            c.close()
        print(text)
        return 0
    c = connect(args.db, True)
    try:
        c.execute('BEGIN IMMEDIATE')
        plan = classify(c)
        apply_plan(c, plan)
        c.commit()
    except BaseException:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        c.close()
    print(report(args.db, plan, True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
