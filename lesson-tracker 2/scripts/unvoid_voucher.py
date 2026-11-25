#!/usr/bin/env python3
"""Cancel one voided voucher and, when the course was marked 加错了, enrol it again.

Dry-run is the default. It runs the same un-void inside a transaction, prints
the before and after, then rolls back. --apply commits that one transaction.
Uses LESSON_DB. Do not set LESSON_DB yourself on production.

  python3 scripts/unvoid_voucher.py --voucher CZ-2026-0018
  python3 scripts/unvoid_voucher.py --voucher CZ-2026-0018 --apply
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def connect(db_path):
    # None keeps BEGIN/ROLLBACK in charge. The default wrapper commits before schema changes.
    c = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c


def has_table(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def money_totals(c):
    payments = 0
    balances = 0
    if has_table(c, 'cash_entries'):
        payments = int(c.execute('SELECT COALESCE(SUM(cash_delta),0) n FROM cash_entries').fetchone()['n'])
    if has_table(c, 'students'):
        balances = int(c.execute('SELECT COALESCE(SUM(balance),0) n FROM students').fetchone()['n'])
    return payments, balances


def owner_user(c):
    row = None
    if has_table(c, 'organization_owners'):
        row = c.execute('SELECT user_id id FROM organization_owners ORDER BY user_id LIMIT 1').fetchone()
    if not row and has_table(c, 'users'):
        row = c.execute("SELECT id FROM users WHERE role IN ('admin','owner') ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise SystemExit('找不到老板账号，不能取消作废。')
    return {'id': row['id'], 'role': 'owner'}


def load_voucher(c, number):
    row = c.execute('SELECT * FROM vouchers WHERE number=?', (number,)).fetchone()
    if not row:
        raise SystemExit(f'找不到单据 {number}。')
    return row


def picture(c, voucher):
    student = None
    if voucher['student_id']:
        student = c.execute('SELECT * FROM students WHERE id=?', (voucher['student_id'],)).fetchone()
    batch = None
    if voucher['ledger_id'] and has_table(c, 'credit_batches'):
        batch = c.execute('SELECT * FROM credit_batches WHERE ledger_id=? ORDER BY id LIMIT 1', (voucher['ledger_id'],)).fetchone()
    reversal = None
    if voucher['reversal_ledger_id']:
        reversal = c.execute('SELECT * FROM ledger WHERE id=?', (voucher['reversal_ledger_id'],)).fetchone()
    if not reversal and voucher['ledger_id']:
        reversal = c.execute('SELECT * FROM ledger WHERE reversal_of=? ORDER BY id DESC LIMIT 1', (voucher['ledger_id'],)).fetchone()
    fresh = c.execute('SELECT * FROM vouchers WHERE id=?', (voucher['id'],)).fetchone()
    return student, batch, reversal, fresh


def line_for(student, batch, voucher, reversal):
    who = '没有课程行'
    if student:
        reason = student['void_reason'] if 'void_reason' in student.keys() else ''
        who = (f"#{student['id']} {student['name']} {student['course']} "
            f"voided={int(student['voided'] or 0)} archived={int(student['archived'] or 0)} "
            f"reason={reason or '-'} balance={int(student['balance'] or 0)}")
    pack = '没有课时包'
    if batch:
        status = batch['status'] if 'status' in batch.keys() else 'active'
        payment = batch['payment_status'] if 'payment_status' in batch.keys() else 'paid'
        receivable = int(batch['receivable_cents'] or 0) if 'receivable_cents' in batch.keys() else 0
        pack = (f"#{batch['id']} status={status} paid_left={int(batch['paid_left'] or 0)} "
            f"gift_left={int(batch['gift_left'] or 0)} payment={payment} receivable={receivable}")
    undone = f"reversal=#{reversal['id']} delta={int(reversal['delta'] or 0)}" if reversal else '没有作废账'
    return f"{who} | voucher={voucher['number']} status={voucher['status']} | {pack} | {undone}"


def main():
    parser = argparse.ArgumentParser(description='Cancel a voided voucher and restore a 加错了 course.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--voucher', required=True, help='Voucher number, for example CZ-2026-0018.')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    import deletion
    import receivables
    import server
    import switches
    import vouchers
    c = connect(args.db)
    try:
        deletion.schema(c)
        switches.schema(c)
        receivables.schema(c)
        c.execute('BEGIN IMMEDIATE')
        voucher = load_voucher(c, args.voucher.strip())
        before_student, before_batch, reversal, _fresh = picture(c, voucher)
        payments_before, balances_before = money_totals(c)
        expected = -int(reversal['delta'] or 0) if reversal else 0
        user = owner_user(c)
        vouchers.unvoid(c, user, voucher['id'], server.units, restore_course=True)
        after_voucher = c.execute('SELECT * FROM vouchers WHERE id=?', (voucher['id'],)).fetchone()
        after_student, after_batch, _reversal, _again = picture(c, after_voucher)
        put_back = None
        if reversal:
            put_back = c.execute('SELECT * FROM ledger WHERE reversal_of=?', (reversal['id'],)).fetchone()
        payments_after, balances_after = money_totals(c)
        if payments_after != payments_before:
            raise RuntimeError(f'收款变了：{payments_before} → {payments_after}')
        if balances_after - balances_before != expected:
            raise RuntimeError(f'余额变化不是 {expected:+}：{balances_before} → {balances_after}')
        lines = [
            f"{'APPLY' if args.apply else 'DRY-RUN'}  database={os.path.realpath(args.db)}",
            f"voucher={args.voucher.strip()}",
            'before: ' + line_for(before_student, before_batch, voucher, reversal),
            'after:  ' + line_for(after_student, after_batch, after_voucher, reversal),
        ]
        if put_back:
            lines.append(f"ledger=#{put_back['id']} delta={int(put_back['delta'] or 0):+} reversal_of={put_back['reversal_of']}")
        lines.append(f'payments_before={payments_before} payments_after={payments_after}')
        lines.append(f'balances_before={balances_before} balances_after={balances_after} balances_delta={balances_after - balances_before:+}')
        if args.apply:
            c.execute('COMMIT')
            lines.append('已写入。')
        else:
            c.execute('ROLLBACK')
            lines.append('未写入。')
        print('\n'.join(lines))
    except Exception:
        if c.in_transaction:
            c.execute('ROLLBACK')
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
