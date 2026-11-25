"""Teacher pay still loads when a lesson was taken from a back-dated gift pack."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'teacher-pay.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import payroll
import server


class TeacherPayPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_teacher_row_can_price_a_gift_pack_and_a_null_price_list(self):
        with server.connect() as c:
            owner = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('043' + uuid.uuid4().hex)[:15], 'Boss', 'x')).lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner,))
            tuser = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('043' + uuid.uuid4().hex)[:15], 'Helen', 'x')).lastrowid
            tid = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?,?)", (tuser, '新加坡数学')).lastrowid
            c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,created_by)
                VALUES(?,?,?,?,?,?,?)''', (tid, 'percent', 4000, None, None, '2020-01-01', owner))
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (('043' + uuid.uuid4().hex)[:15], '家长', 'x')).lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Aaron')").lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Aaron','新加坡数学',?,?,0)",
                (parent, profile)).lastrowid

            def pack(purchased, gifted, cash, fees, day):
                credit = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,paid_delta,gift_delta,split_known)
                    VALUES(?,?,'credit',?,?,?,?,?,?,1)''',
                    (sid, purchased + gifted, day, '补录以前的包', owner, uuid.uuid4().hex, purchased, gifted)).lastrowid
                batch = c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents,unit_fees)
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                    (sid, credit, purchased, gifted, purchased, gifted, day, cash, fees)).lastrowid
                c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)',
                    (credit, batch, purchased, gifted))
                c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,?)',
                    (credit, cash, 'bank', '', owner))
                return batch

            gift_pack = pack(2000, 133, 255000, '', '2026-09-05')
            null_pack = pack(1000, 0, 100000, '[null, 5000]', '2026-08-01')

            def taught(batch, hour):
                day = '2026-11-24'
                lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                    VALUES(?,?,?,?,100,'教室','completed',?,?)''',
                    (tid, '新加坡数学', f'{day}T{hour}:00', f'{day}T{hour+1}:00', owner, uuid.uuid4().hex)).lastrowid
                ledger = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,paid_delta,gift_delta,split_known)
                    VALUES(?,?,'lesson',?,'上课',?,?,?,0,1)''', (sid, -100, day, owner, uuid.uuid4().hex, -100)).lastrowid
                c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,0,0)', (ledger, batch, -100))
                c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                    VALUES(?,?,100,'上过','','',?,?)''', (lesson, sid, ledger, owner))
                return lesson

            gift_lesson = taught(gift_pack, 16)
            null_lesson = taught(null_pack, 18)
            c.commit()
            user = c.execute("SELECT id, name, phone, 'teacher' AS role, ? AS teacher_id FROM users WHERE id=?", (tid, tuser)).fetchone()
            self.assertIsInstance(user, sqlite3.Row)
            result = payroll.report(c, user, 'week', '2026-11-25', None, None)
        self.assertEqual(len(result['teachers']), 1)
        self.assertEqual(result['teachers'][0]['teacher_id'], tid)
        by_lesson = {lesson['lesson_id']: lesson for lesson in result['teachers'][0]['lessons']}
        gift_line = by_lesson[gift_lesson]['lines'][0]
        self.assertTrue(gift_line['fee_known'])
        self.assertEqual(gift_line['fee_cents'], payroll.mul_div(100, 255000, 2133))
        null_line = by_lesson[null_lesson]['lines'][0]
        self.assertTrue(null_line['fee_known'])
        self.assertEqual(null_line['fee_cents'], payroll.mul_div(100, 100000, 1000))
        self.assertIsNone(result['partner'])


if __name__ == '__main__':
    unittest.main()
