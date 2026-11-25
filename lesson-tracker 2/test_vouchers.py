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
import finance
import receivables
import server
import timeline
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

    def test_unvoid_puts_back_the_ledger_pack_and_month(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000101','Helen','x','admin')").lastrowid
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000102','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('林晓',)).lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('林晓','数学',?,?,0)",
                (parent, profile)).lastrowid
            day = '2026-11-04'
            lid = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit',?,'充值',?,?)",
                (sid, day, uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, lid, 'credit', {'amount': '2', 'gift_amount': '1', 'pack_label': '数学包'}, server.units)
            accounting.record_cash(c, lid, 15000, 'bank', '', uid)
            vid = vouchers.issue_ledger(c, owner, lid)
            vouchers.approve(c, owner, vid)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 15000)
            vouchers.void(c, owner, vid, server.units)
            parked = c.execute('SELECT status, paid_left, gift_left FROM credit_batches WHERE ledger_id=?', (lid,)).fetchone()
            self.assertEqual((parked['status'], parked['paid_left'], parked['gift_left']), ('voided', 0, 0))
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 0)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 0)
            restored = vouchers.unvoid(c, owner, vid, server.units)
            self.assertEqual(restored['status'], 'approved')
            row = c.execute('SELECT status FROM vouchers WHERE id=?', (vid,)).fetchone()
            self.assertEqual(row['status'], 'approved')
            balance = c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']
            packs = c.execute('SELECT COALESCE(SUM(paid_left+gift_left),0) FROM credit_batches WHERE student_id=?', (sid,)).fetchone()[0]
            ledger = c.execute('SELECT COALESCE(SUM(delta),0) FROM ledger WHERE student_id=?', (sid,)).fetchone()[0]
            self.assertEqual((balance, packs, ledger), (300, 300, 300))
            reopened = c.execute('SELECT status, paid_left, gift_left FROM credit_batches WHERE ledger_id=?', (lid,)).fetchone()
            self.assertEqual((reopened['status'], reopened['paid_left'], reopened['gift_left']), ('active', 200, 100))
            reversal = c.execute('SELECT id FROM ledger WHERE reversal_of=?', (lid,)).fetchone()
            put_back = c.execute('SELECT * FROM ledger WHERE reversal_of=?', (reversal['id'],)).fetchone()
            self.assertEqual(put_back['kind'], 'reversal')
            self.assertEqual(put_back['lesson_date'], day)
            self.assertEqual(put_back['delta'], 300)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 15000)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_log WHERE summary=?", ('取消作废 ' + c.execute('SELECT number FROM vouchers WHERE id=?', (vid,)).fetchone()['number'],)).fetchone()[0], 1)
            self.assertIn('取消作废', [item['action'] for item in vouchers.events(c, owner, vid)])
            self.assertTrue(any(item['action'] == 'unvoid' for item in timeline.for_staff(c) if item['student_id'] == sid))
            vouchers.void(c, owner, vid, server.units)
            other = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit',?,'补开',?,?)",
                (sid, day, uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, other, 'credit', {'amount': '1', 'gift_amount': '0'}, server.units)
            replacement = vouchers.issue_ledger(c, owner, other)
            number = c.execute('SELECT number FROM vouchers WHERE id=?', (replacement,)).fetchone()['number']
            c.execute("UPDATE vouchers SET created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now','+2 seconds') WHERE id=?", (replacement,))
            with self.assertRaises(ValueError) as blocked:
                vouchers.unvoid(c, owner, vid, server.units)
            self.assertIn(number, str(blocked.exception))
            self.assertIn('不能再取消作废', str(blocked.exception))
            self.assertEqual(c.execute('SELECT status FROM vouchers WHERE id=?', (vid,)).fetchone()['status'], 'void')

    def test_unvoid_refuses_a_missing_course_and_restores_a_receipt(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000201','Helen','x','admin')").lastrowid
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000202','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('周宁',)).lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('周宁','英语',?,?,0)",
                (parent, profile)).lastrowid
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,0,'credit','2026-11-05','挂账',?,?)''', (sid, uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, lid, 'credit', {
                'amount': '4', 'gift_amount': '0', 'total_cents': 8000, 'pack_label': '4节',
            }, server.units)
            receivables.open_on_ledger(c, lid)
            batch = c.execute('SELECT id FROM credit_batches WHERE ledger_id=?', (lid,)).fetchone()['id']
            paid = receivables.collect(c, owner, {'batch_id': batch, 'amount': '80.00', 'date': '2026-11-06', 'payment_method': 'bank'})
            voucher = c.execute('SELECT id, number FROM vouchers WHERE ledger_id=?', (paid['ledger_id'],)).fetchone()
            self.assertEqual(finance.monthly(c, owner, '2026-11')['receivable_cents'], 0)
            vouchers.void(c, owner, voucher['id'], server.units)
            self.assertEqual(c.execute('SELECT payment_status, paid_cents FROM credit_batches WHERE id=?', (batch,)).fetchone()['payment_status'], 'unpaid')
            self.assertEqual(finance.monthly(c, owner, '2026-11')['receivable_cents'], 8000)
            c.execute('UPDATE vouchers SET student_id=? WHERE id=?', (999999, voucher['id']))
            with self.assertRaises(ValueError) as missing:
                vouchers.unvoid(c, owner, voucher['id'], server.units)
            self.assertEqual(str(missing.exception), '这门课已经不在了，不能取消作废。')
            c.execute('UPDATE vouchers SET student_id=? WHERE id=?', (sid, voucher['id']))
            vouchers.unvoid(c, owner, voucher['id'], server.units)
            again = c.execute('SELECT payment_status, paid_cents FROM credit_batches WHERE id=?', (batch,)).fetchone()
            self.assertEqual(again['payment_status'], 'paid')
            self.assertEqual(again['paid_cents'], 8000)
            self.assertEqual(c.execute('SELECT voided FROM pack_payments WHERE ledger_id=?', (paid['ledger_id'],)).fetchone()['voided'], 0)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['receivable_cents'], 0)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 8000)
            balance = c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']
            packs = c.execute('SELECT COALESCE(SUM(paid_left+gift_left),0) FROM credit_batches WHERE student_id=?', (sid,)).fetchone()[0]
            self.assertEqual(balance, packs)

    def test_unvoid_refuses_when_the_hours_were_used(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000301','Helen','x','admin')").lastrowid
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000302','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('吴安',)).lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('吴安','数学',?,?,0)",
                (parent, profile)).lastrowid
            credit = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit','2026-11-07','充值',?,?)",
                (sid, uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, credit, 'credit', {'amount': '2', 'gift_amount': '0'}, server.units)
            refund = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'refund','2026-11-08','退费',?,?)",
                (sid, uid, uuid.uuid4().hex)).lastrowid
            batch = c.execute('SELECT id FROM credit_batches WHERE ledger_id=?', (credit,)).fetchone()['id']
            credit_batches.apply(c, refund, 'refund', {'batch_id': batch, 'amount': '1'}, server.units)
            vid = vouchers.issue_ledger(c, owner, refund)
            vouchers.void(c, owner, vid, server.units)
            lesson = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,-200,'lesson','2026-11-09','上课',?,?)",
                (sid, uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, lesson, 'lesson', {}, server.units)
            with self.assertRaises(ValueError) as used:
                vouchers.unvoid(c, owner, vid, server.units)
            self.assertIn('课时冲突', str(used.exception))
            self.assertEqual(c.execute('SELECT status FROM vouchers WHERE id=?', (vid,)).fetchone()['status'], 'void')

    def test_cancel_void_button_is_on_the_receipt_and_the_student_history(self):
        root = Path(__file__).resolve().parent
        receipt = (root / 'static' / 'vouchers.js').read_text()
        history = (root / 'static' / 'app.js').read_text()
        self.assertIn('取消作废', receipt)
        self.assertIn("api('vouchers/unvoid'", receipt)
        self.assertIn('data-unvoid-voucher', history)
        self.assertIn("event.voucher_status==='void'", history)
        self.assertIn('e.void_voucher_id', history)
        self.assertIn('同时恢复这门课', receipt)
        self.assertIn('restore_course', receipt)


if __name__ == '__main__':
    unittest.main()
