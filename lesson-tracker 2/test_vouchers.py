"""Receipts are created for credits and refunds, and a void drops out of finance."""
import datetime as dt
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'vouchers.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import accounting
import credit_batches
import server
import vouchers


class VoucherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_credit_refund_and_void_leave_finance(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000001','Helen','x','admin')").lastrowid
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000002','家长','x','parent')").lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,balance) VALUES('陈一诺','数学',?,0)", (parent,)).lastrowid
            day = '2026-11-01'
            lid = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit',?,'充值数学包',?,?)",
                (sid, day, uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, lid, 'credit', {'amount': '2', 'gift_amount': '1', 'pack_label': '数学 20+1'}, server.units)
            accounting.record_cash(c, lid, 170000, 'bank', '', uid)
            vid = vouchers.issue_ledger(c, owner, lid)
            row = c.execute('SELECT * FROM vouchers WHERE id=?', (vid,)).fetchone()
            self.assertTrue(row['number'].startswith('CZ-2026-'))
            self.assertEqual(row['status'], 'pending')
            self.assertEqual(row['paid_units'], 200)
            self.assertEqual(row['gift_units'], 100)
            self.assertEqual(row['amount_cents'], 170000)
            self.assertEqual(row['pack_label'], '数学 20+1')
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 300)
            lesson = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'lesson',?,'上课',?,?)",
                (sid, day, uid, uuid.uuid4().hex)).lastrowid
            self.assertIsNone(vouchers.issue_ledger(c, owner, lesson))
            vouchers.edit(c, owner, {'id': vid, 'date': day, 'note': '改成实收', 'amount': '2', 'gift_amount': '1', 'cash_amount': '150', 'payment_method': 'bank'}, server.units, server.text_value)
            edited = c.execute('SELECT amount_cents, status FROM vouchers WHERE id=?', (vid,)).fetchone()
            self.assertEqual(edited['amount_cents'], 15000)
            self.assertEqual(edited['status'], 'pending')
            vouchers.approve(c, owner, vid)
            self.assertEqual(c.execute('SELECT status FROM vouchers WHERE id=?', (vid,)).fetchone()['status'], 'approved')
            with self.assertRaises(ValueError):
                vouchers.edit(c, owner, {'id': vid, 'date': day, 'note': '不行', 'amount': '2', 'gift_amount': '1', 'cash_amount': '1', 'payment_method': 'bank'}, server.units, server.text_value)
            vouchers.unapprove(c, owner, vid)
            before = accounting.cash_breakdown(c, dt.date(2026, 11, 1), dt.date(2026, 11, 30))
            self.assertEqual(before['received_cents'], 15000)
            second = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit',?,'再充',?,?)",
                (sid, day, uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, second, 'credit', {'amount': '2', 'gift_amount': '0'}, server.units)
            accounting.record_cash(c, second, 0, 'cash', '', uid)
            refund = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'refund',?,'退费',?,?)",
                (sid, day, uid, uuid.uuid4().hex)).lastrowid
            batch = c.execute('SELECT id FROM credit_batches WHERE ledger_id=?', (second,)).fetchone()['id']
            credit_batches.apply(c, refund, 'refund', {'batch_id': batch, 'amount': '1'}, server.units)
            accounting.record_cash(c, refund, 0, 'cash', '', uid)
            rid = vouchers.issue_ledger(c, owner, refund)
            receipt = c.execute('SELECT * FROM vouchers WHERE id=?', (rid,)).fetchone()
            self.assertTrue(receipt['number'].startswith('TF-2026-'))
            self.assertEqual(receipt['amount_cents'], 0)
            vouchers.void(c, owner, vid, server.units)
            self.assertEqual(c.execute('SELECT status FROM vouchers WHERE id=?', (vid,)).fetchone()['status'], 'void')
            after = accounting.cash_breakdown(c, dt.date(2026, 11, 1), dt.date(2026, 11, 30))
            self.assertEqual(after['received_cents'], 0)
            self.assertGreaterEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 0)
            log = vouchers.events(c, owner, vid)
            self.assertIn('作废', [item['action'] for item in log])


if __name__ == '__main__':
    unittest.main()
