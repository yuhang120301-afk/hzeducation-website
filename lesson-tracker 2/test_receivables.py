"""A 挂账 pack can be used before the money arrives, and each payment is income on its own date."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'receivable.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import credit_batches
import finance
import receivables
import server
import vouchers


class ReceivableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_existing_pack_is_treated_as_paid_in_full(self):
        with server.connect() as c:
            c.execute("DELETE FROM app_meta WHERE key='receivable_paid_v1'")
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0466000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('旧生','数学',?,?,0)",
                (parent, profile)).lastrowid
            bid = c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents,payment_status,receivable_cents,paid_cents)
                VALUES(?,1000,0,1000,0,'2026-01-01',8500,'paid',0,0)''', (sid,)).lastrowid
            receivables.schema(c)
            row = c.execute('SELECT payment_status, receivable_cents, paid_cents FROM credit_batches WHERE id=?', (bid,)).fetchone()
            self.assertEqual(row['payment_status'], 'paid')
            self.assertEqual(row['paid_cents'], 8500)
            self.assertEqual(receivables.owed_cents(row), 0)
            receivables.schema(c)

    def test_unpaid_pack_is_usable_and_payments_are_income_until_voided(self):
        with server.connect() as c:
            owner_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0466000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner_id,))
            owner = {'id': owner_id, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0466000003','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Mia','数学',?,?,0)",
                (parent, profile)).lastrowid
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,0,'credit','2026-11-01','挂账',?,?)''', (sid, owner_id, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, lid, 'credit', {
                'amount': '10', 'gift_amount': '0', 'total_cents': 17000, 'pack_label': '10节', 'unit_fees': '[17000]',
            }, server.units)
            receivables.open_on_ledger(c, lid)
            self.assertIsNone(c.execute('SELECT 1 FROM cash_entries WHERE ledger_id=?', (lid,)).fetchone())
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 1000)
            use = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,-100,'lesson','2026-11-02','上课',?,?)''', (sid, owner_id, uuid.uuid4().hex)).lastrowid
            credit_batches.apply(c, use, 'lesson', {}, server.units)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 900)
            first = receivables.collect(c, owner, {'batch_id': c.execute('SELECT id FROM credit_batches WHERE ledger_id=?', (lid,)).fetchone()['id'],
                'amount': '50.00', 'date': '2026-11-03', 'payment_method': 'bank'})
            self.assertEqual(first['owed_cents'], 12000)
            self.assertEqual(first['payment_status'], 'unpaid')
            report = finance.monthly(c, owner, '2026-11')
            self.assertEqual(report['money_received_cents'], 5000)
            self.assertEqual(report['receivable_cents'], 12000)
            self.assertEqual(report['forfeit_units'], 0)
            batch_id = c.execute('SELECT id FROM credit_batches WHERE ledger_id=?', (lid,)).fetchone()['id']
            second = receivables.collect(c, owner, {'batch_id': batch_id, 'amount': '120.00', 'date': '2026-11-20', 'payment_method': 'cash'})
            self.assertEqual(second['owed_cents'], 0)
            self.assertEqual(second['payment_status'], 'paid')
            self.assertEqual(finance.monthly(c, owner, '2026-11')['receivable_cents'], 0)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 17000)
            voucher = c.execute('SELECT id FROM vouchers WHERE ledger_id=?', (second['ledger_id'],)).fetchone()
            vouchers.void(c, owner, voucher['id'], server.units)
            again = c.execute('SELECT payment_status, paid_cents FROM credit_batches WHERE id=?', (batch_id,)).fetchone()
            self.assertEqual(again['payment_status'], 'unpaid')
            self.assertEqual(again['paid_cents'], 5000)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['receivable_cents'], 12000)
            notes = [row['summary'] for row in c.execute('SELECT summary FROM profile_events WHERE profile_id=? ORDER BY id', (profile,))]
            self.assertTrue(any('挂账收款' in item for item in notes))
            self.assertTrue(any('作废' in item for item in notes))
            self.assertFalse(finance.low_balance(c))


if __name__ == '__main__':
    unittest.main()
