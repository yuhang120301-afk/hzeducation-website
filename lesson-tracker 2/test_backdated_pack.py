"""A pack paid in an earlier month keeps that month's income and does not invent teacher pay."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'prior-pack.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import finance
import payroll
import server
from teaching import now_local


class Entry:
    path = '/api/entries'
    def response(self, code, body, *args, **kwargs):
        return code, body


class BackdatedPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_past_payment_stays_in_that_month_and_used_hours_do_not_pay_the_teacher(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499100001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            teacher_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499100002','Vincent','x','admin')").lastrowid
            teacher = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher_user, '数学')).lastrowid
            c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,created_by)
                VALUES(?,?,?,?,?,?,?)''', (teacher, 'percent', 4000, None, None, '2020-01-01', uid))
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499100003','家长','x','parent')").lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Mia')").lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Mia','数学',?,?,0)",
                (parent, profile)).lastrowid
            c.commit()

        def post(data):
            with server.connect() as c:
                server.Handler.record(Entry(), c, owner, data)

        with self.assertRaises(ValueError) as today:
            post({
                'student_id': sid, 'kind': 'credit', 'backdated': 'on', 'date': now_local().date().isoformat(),
                'amount': '10', 'remaining': '4', 'cash_amount': '1000', 'payment_method': 'bank',
                'payment_status': 'paid', 'request_id': uuid.uuid4().hex,
            })
        self.assertIn('收钱日期要早于今天', str(today.exception))
        post({
            'student_id': sid, 'kind': 'credit', 'backdated': 'on', 'date': '2026-10-05',
            'amount': '10', 'remaining': '4', 'cash_amount': '1000', 'payment_method': 'bank',
            'payment_status': 'paid', 'request_id': uuid.uuid4().hex,
        })
        with server.connect() as c:
            october = finance.monthly(c, owner, '2026-10')
            november = finance.monthly(c, owner, '2026-11')
            self.assertEqual(october['money_received_cents'], 100000)
            self.assertEqual(november['money_received_cents'], 0)
            self.assertEqual(october['teacher_pay_cents'], 0)
            self.assertEqual(november['teacher_pay_cents'], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_reports').fetchone()[0], 0)
            batch = c.execute('SELECT purchased, paid_left, gift_left FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['purchased'], batch['paid_left'], batch['gift_left']), (1000, 400, 0))
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 400)
            self.assertEqual(c.execute("SELECT lesson_date FROM ledger WHERE kind='credit' AND student_id=?", (sid,)).fetchone()['lesson_date'], '2026-10-05')
            day = '2026-11-12'
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','completed',?,?)''',
                (teacher, '数学', day + 'T16:00', day + 'T17:00', uid, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (lesson, sid))
            ledger = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,0,'lesson',?,'上课',?,?)''', (sid, day, uid, uuid.uuid4().hex)).lastrowid
            import credit_batches
            credit_batches.move(c, ledger, c.execute('SELECT id FROM credit_batches WHERE student_id=?', (sid,)).fetchone()['id'], -100, 0)
            credit_batches.finish(c, ledger)
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'上过了','','',?,?)''', (lesson, sid, ledger, uid))
            c.commit()
            taught = payroll.report(c, owner, 'custom', None, '2026-11-01', '2026-11-30')
            pay = sum(teacher['total_pay_cents'] for teacher in taught['teachers'])
            self.assertEqual(pay, 4000)
            self.assertEqual(finance.monthly(c, owner, '2026-10')['money_received_cents'], 100000)
            self.assertEqual(finance.monthly(c, owner, '2026-10')['teacher_pay_cents'], 0)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 0)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['teacher_pay_cents'], 4000)
            self.assertEqual(c.execute('SELECT paid_left FROM credit_batches WHERE student_id=?', (sid,)).fetchone()['paid_left'], 300)

    def test_form_offers_the_past_pack_fields(self):
        source = Path(__file__).resolve().parent.joinpath('static', 'app.js').read_text()
        self.assertIn('补录以前的包', source)
        self.assertIn('收钱日期', source)
        self.assertIn('还剩几节', source)
        self.assertIn('总节数', source)
        self.assertIn('还剩赠送几节', source)
        self.assertNotIn('赠送金额', source)
        self.assertIn('不算今天的新收款', source)

    def test_remaining_gift_lessons_are_not_cash_and_share_the_pack_price(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499100101','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            teacher_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499100102','Vincent','x','admin')").lastrowid
            teacher = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher_user, '数学')).lastrowid
            c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,created_by)
                VALUES(?,?,?,?,?,?,?)''', (teacher, 'percent', 4000, None, None, '2020-01-01', uid))
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499100103','家长','x','parent')").lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Lin')").lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Lin','数学',?,?,0)",
                (parent, profile)).lastrowid
            c.commit()
        with server.connect() as c:
            server.Handler.record(Entry(), c, owner, {
                'student_id': sid, 'kind': 'credit', 'backdated': 'on', 'date': '2026-10-05',
                'amount': '10', 'remaining': '4', 'gift_remaining': '2', 'cash_amount': '1000',
                'payment_method': 'bank', 'payment_status': 'paid', 'request_id': uuid.uuid4().hex,
            })
            batch = c.execute('SELECT purchased, gifted, paid_left, gift_left FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['purchased'], batch['gifted'], batch['paid_left'], batch['gift_left']), (1000, 200, 400, 200))
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 600)
            own_cash = c.execute('''SELECT COALESCE(SUM(cash.cash_delta),0) FROM cash_entries cash
                JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?''', (sid,)).fetchone()[0]
            self.assertEqual(own_cash, 100000)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id IN (SELECT lesson_id FROM lesson_students WHERE student_id=?)', (sid,)).fetchone()[0], 0)
            day = '2026-11-18'
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','completed',?,?)''',
                (teacher, '数学', day + 'T16:00', day + 'T17:00', uid, uuid.uuid4().hex)).lastrowid
            ledger = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,0,'lesson',?,'上课',?,?)''', (sid, day, uid, uuid.uuid4().hex)).lastrowid
            import credit_batches
            credit_batches.move(c, ledger, c.execute('SELECT id FROM credit_batches WHERE student_id=?', (sid,)).fetchone()['id'], -100, 0)
            credit_batches.finish(c, ledger)
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'上过了','','',?,?)''', (lesson, sid, ledger, uid))
            c.commit()
            taught = payroll.report(c, owner, 'custom', None, '2026-11-01', '2026-11-30')
            mine = next(row for row in taught['teachers'] if row['teacher_id'] == teacher)
            self.assertEqual(mine['total_fee_cents'], 8333)
            self.assertEqual(mine['total_pay_cents'], 3333)
            self.assertEqual(c.execute('''SELECT COALESCE(SUM(cash.cash_delta),0) FROM cash_entries cash
                JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?''', (sid,)).fetchone()[0], 100000)
            self.assertEqual(finance.monthly(c, owner, '2026-11')['money_received_cents'], 0)


if __name__ == '__main__':
    unittest.main()
