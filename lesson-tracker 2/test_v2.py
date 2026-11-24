"""Package value, price quotes, and the 48-hour leave rule."""
import os
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'v2.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import payroll
import pricing
import server
import teaching


class PackageValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')
        self.n = 0

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def phone(self):
        self.n += 1
        return f'048{self.n:04d}{uuid.uuid4().int % 10000:04d}'[:15]

    def user(self, name, role='parent'):
        return self.c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
            (self.phone(), name, 'x', role)).lastrowid

    def teacher(self, name):
        uid = self.user(name)
        return self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (uid, '数学')).lastrowid

    def student(self, name, level='Y6'):
        parent = self.user(name + '家长')
        profile = self.c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        return self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,level_code,level_year)
            VALUES(?,?,?,?,?,?,?)''', (name, '数学', parent, profile, 0, level, 2027)).lastrowid

    def test_gift_lesson_from_a_paid_package_shares_the_price(self):
        tid, sid = self.teacher('Angela'), self.student('陈一诺')
        paid, gift, cash = 2000, 100, 210000
        ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'credit','2027-02-01','课时包',1,?)",
            (sid, paid + gift, uuid.uuid4().hex)).lastrowid
        batch = self.c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on)
            VALUES(?,?,?,?,?,?,'2027-02-01')''', (sid, ledger, paid, gift, paid, gift)).lastrowid
        self.c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,1)',
            (ledger, cash, 'bank', ''))
        use = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson','2027-06-01','上课',1,?)",
            (sid, -100, uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,0,-100,0)', (use, batch))
        fee, paid_units, gift_units = payroll.fee_for_ledger(self.c, use, 100)
        self.assertEqual(gift_units, 100)
        self.assertEqual(paid_units, 0)
        self.assertEqual(fee, 10000)

    def test_quote_requires_twenty_and_adds_one_gift(self):
        sid = self.student('周可')
        owner = {'id': 1, 'role': 'owner'}
        with self.assertRaises(ValueError):
            pricing.normalize_purchase(self.c, owner, {
                'student_id': sid, 'product': 'one_to_one', 'lesson_minutes': 60, 'paid_lessons': 19,
            })
        bought = pricing.normalize_purchase(self.c, owner, {
            'student_id': sid, 'product': 'one_to_one', 'lesson_minutes': 90, 'paid_lessons': 20,
        })
        self.assertEqual(bought['amount'], 20)
        self.assertEqual(bought['gift_amount'], 1)
        self.assertEqual(bought['lesson_minutes'], 90)
        pricing.seed_2027(self.c)
        quoted = pricing.quote(self.c, owner, sid, 'one_to_one', 60, 20, '2027-03-01')
        self.assertEqual(quoted['gift_lessons'], 1)
        self.assertEqual(quoted['source'], 'table')
        self.assertEqual(quoted['total_cents'], 20 * 8500)

    def test_late_cancel_with_no_balance_does_not_go_negative(self):
        tid, sid = self.teacher('Kelsey'), self.student('王星然')
        soon = (teaching.now_local() + timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M')
        end = (teaching.now_local() + timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M')
        actor = self.c.execute('SELECT user_id FROM teachers WHERE id=?', (tid,)).fetchone()['user_id']
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id)
            VALUES(?,?,?,?,100,'教室',?,?)''', (tid, '数学', soon, end, actor, uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
        lesson = dict(self.c.execute('SELECT * FROM lessons WHERE id=?', (lid,)).fetchone())
        teaching.cancel_lesson(self.c, {'id': 1, 'role': 'owner'}, {'lesson_id': lid, 'version': lesson['version'], 'reason': '临时请假'}, lambda *a, **k: '请假')
        balance = self.c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']
        self.assertEqual(balance, 0)
        self.assertEqual(self.c.execute("SELECT status FROM lessons WHERE id=?", (lid,)).fetchone()['status'], 'cancelled')
        self.assertEqual(self.c.execute('SELECT COUNT(*) n FROM arrears WHERE student_id=?', (sid,)).fetchone()['n'], 1)

    def test_login_contact_is_only_the_school_email(self):
        self.assertEqual(server.contact_details(), {'email': 'helenzeducation@gmail.com'})


if __name__ == '__main__':
    unittest.main()
