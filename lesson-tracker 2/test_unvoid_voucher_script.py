"""CZ-2026-0018 can be un-voided, and the 加错了 course comes back enrolled."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'unvoid-joanna.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import credit_batches
import receivables
import server
import vouchers

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'scripts' / 'unvoid_voucher.py'


class UnvoidVoucherScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_dry_run_then_apply_restores_joanna(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000401','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0420000402','家长','x','parent')").lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Joanna')").lastrowid
            c.execute('''INSERT INTO students(id,name,course,parent_id,profile_id,balance,archived,voided)
                VALUES(97,'Joanna','数学 + 英语',?,?,0,0,0)''', (parent, profile))
            lid = c.execute('''INSERT INTO ledger(id,student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(120,97,0,'credit','2026-11-01','挂账，课时先用，钱还没到',?,?)''', (uid, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, lid, 'credit', {
                'amount': '37', 'gift_amount': '0', 'total_cents': 185000, 'pack_label': '数学 + 英语',
            }, server.units)
            receivables.open_on_ledger(c, lid)
            vid = vouchers.issue_ledger(c, owner, lid)
            c.execute("UPDATE vouchers SET number='CZ-2026-0018' WHERE id=?", (vid,))
            vouchers.void(c, owner, vid, server.units)
            # Prod void left the pack looking active, with the hours already gone.
            c.execute('''UPDATE credit_batches SET status='active', payment_status='unpaid', receivable_cents=0,
                paid_left=0, gift_left=0 WHERE ledger_id=120''')
            c.execute("UPDATE students SET archived=1, voided=1, void_reason='加错了', balance=0 WHERE id=97")
            c.commit()
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(SCRIPT), '--voucher', 'CZ-2026-0018'], env=env, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        self.assertIn('#97 Joanna 数学 + 英语', dry.stdout)
        self.assertIn('balances_delta=+3700', dry.stdout)
        self.assertIn('payments_before=0', dry.stdout)
        self.assertIn('payments_after=0', dry.stdout)
        self.assertIn('reversal_of=121', dry.stdout)
        with server.connect() as c:
            still = c.execute('SELECT voided, void_reason, balance FROM students WHERE id=97').fetchone()
            self.assertEqual((still['voided'], still['void_reason'], still['balance']), (1, '加错了', 0))
            self.assertEqual(c.execute("SELECT status FROM vouchers WHERE number='CZ-2026-0018'").fetchone()['status'], 'void')
        applied = subprocess.run([sys.executable, str(SCRIPT), '--voucher', 'CZ-2026-0018', '--apply'],
            env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn('已写入', applied.stdout)
        self.assertIn('balances_delta=+3700', applied.stdout)
        with server.connect() as c:
            course = c.execute('SELECT archived, voided, void_reason, balance FROM students WHERE id=97').fetchone()
            self.assertEqual((course['archived'], course['voided'], course['void_reason'], course['balance']), (0, 0, '', 3700))
            batch = c.execute('SELECT status, paid_left, gift_left, payment_status, receivable_cents FROM credit_batches WHERE ledger_id=120').fetchone()
            self.assertEqual(batch['status'], 'active')
            self.assertEqual(batch['paid_left'], 3700)
            self.assertEqual(batch['gift_left'], 0)
            self.assertEqual(batch['payment_status'], 'unpaid')
            self.assertEqual(batch['receivable_cents'], 185000)
            self.assertEqual(c.execute("SELECT status FROM vouchers WHERE number='CZ-2026-0018'").fetchone()['status'], 'pending')
            put_back = c.execute('SELECT delta, reversal_of FROM ledger WHERE reversal_of=121').fetchone()
            self.assertEqual((put_back['delta'], put_back['reversal_of']), (3700, 121))
            self.assertTrue(c.execute("SELECT 1 FROM audit_log WHERE summary LIKE '取消作废 CZ-2026-0018%'").fetchone())
            self.assertEqual(c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0], 3700)


if __name__ == '__main__':
    unittest.main()
