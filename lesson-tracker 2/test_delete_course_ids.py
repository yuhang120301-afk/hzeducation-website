"""--delete-course-ids removes an empty course row and leaves the person."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'drop-courses.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import profiles
import server

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'scripts' / 'cleanup_merged_test_traces.py'


class DeleteCourseIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            owner = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433200001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner,))
            teacher = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (owner, '数学')).lastrowid
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433200002','家长','x','parent')").lastrowid

            def add_person(student_id, name, course, balance=0, note=''):
                profile = c.execute('INSERT INTO student_profiles(name,grade) VALUES(?,?)', (name, 'Y6')).lastrowid
                c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
                c.execute('''INSERT INTO students(id,name,course,parent_id,profile_id,balance,archived,voided,course_note)
                    VALUES(?,?,?,?,?,?,0,0,?)''', (student_id, name, course, parent, profile, balance, note))
                return profile

            cls.bryce = add_person(26, 'Bryce', '数学 一对一')
            cls.bryce_kept = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance)
                VALUES('Bryce','英语',?,?,20)''', (parent, cls.bryce)).lastrowid
            cls.claire = add_person(69, 'Claire', '数学', note='加错了')
            add_person(90, 'Paid', '数学', balance=15)
            paid = add_person(91, 'Pack', '数学')
            add_person(92, 'Future', '数学')
            add_person(80, 'Other', '数学')
            c.execute('''INSERT INTO lessons(id,teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,status)
                VALUES(424,?,?,?,?,100,'教室',?,?,'cancelled')''',
                (teacher, '数学', '2026-11-02T16:00', '2026-11-02T17:00', owner, uuid.uuid4().hex))
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(424,26)')
            shared = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,status)
                VALUES(?,?,?,?,100,'教室',?,?,'cancelled')''',
                (teacher, '数学', '2026-11-03T16:00', '2026-11-03T17:00', owner, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,26)', (shared,))
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,80)', (shared,))
            scheduled = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,status)
                VALUES(?,?,?,?,100,'教室',?,?,'scheduled')''',
                (teacher, '数学', '2027-03-01T16:00', '2027-03-01T17:00', owner, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,92)', (scheduled,))
            ledger = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(80,0,'credit','2026-08-01','空收款',?,?)''', (owner, uuid.uuid4().hex)).lastrowid
            batch = c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on)
                VALUES(91,0,0,0,0,'')''').lastrowid
            c.execute('''INSERT INTO pack_payments(batch_id,ledger_id,amount_cents,paid_on,method,created_by)
                VALUES(?,?,0,'2026-08-01','',?)''', (batch, ledger, owner))
            c.commit()
            cls.shared = shared
            cls.owner = owner

    def test_listed_ids_drop_only_empty_courses_and_keep_the_person(self):
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(SCRIPT), '--delete-course-ids', '26,69,90,91,92'],
            env=env, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        self.assertIn('delete_course_ids=26,69,90,91,92', dry.stdout)
        self.assertIn('有课时包收款', dry.stdout)
        self.assertIn('余额不是 0', dry.stdout)
        self.assertIn('有没取消的课', dry.stdout)
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM students WHERE id IN (26,69)').fetchone()[0], 2)
        applied = subprocess.run([sys.executable, str(SCRIPT), '--delete-course-ids', '26,69,90,91,92', '--apply'],
            env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn('已写入', applied.stdout)
        self.assertIn('payments_before=0', applied.stdout)
        self.assertIn('payments_after=0', applied.stdout)
        self.assertIn('balances_before=35', applied.stdout)
        self.assertIn('balances_after=35', applied.stdout)
        with server.connect() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id IN (26,69)').fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM lessons WHERE id=424').fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=?', (self.shared,)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=26', (self.shared,)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=80', (self.shared,)).fetchone())
            self.assertEqual(c.execute('SELECT name FROM student_profiles WHERE id=?', (self.claire,)).fetchone()[0], 'Claire')
            self.assertEqual(c.execute('SELECT name FROM student_profiles WHERE id=?', (self.bryce,)).fetchone()[0], 'Bryce')
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id=?', (self.bryce_kept,)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id IN (90,91,92)').fetchone())
            self.assertEqual(c.execute('SELECT COUNT(*) FROM students WHERE id IN (90,91,92)').fetchone()[0], 3)
            shells = profiles.profiles_without_courses(c, {row[0] for row in c.execute('SELECT profile_id FROM students')},
                {'id': self.owner, 'role': 'owner'})
            claire = next(item for item in shells if item['profile_id'] == self.claire)
            self.assertTrue(claire['no_course'])
            self.assertEqual(claire['name'], 'Claire')
            self.assertEqual(claire['course'], '')

    def test_force_names_the_rows_and_drops_only_zero_documents(self):
        env = {**os.environ, 'LESSON_DB': str(DB)}
        with server.connect() as c:
            parent = c.execute("SELECT id FROM users WHERE phone='0433200002'").fetchone()[0]
            owner = c.execute("SELECT id FROM users WHERE phone='0433200001'").fetchone()[0]
            teacher = c.execute('SELECT id FROM teachers LIMIT 1').fetchone()[0]

            def add_person(student_id, name):
                profile = c.execute('INSERT INTO student_profiles(name,grade) VALUES(?,?)', (name, 'Y5')).lastrowid
                c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
                c.execute('''INSERT INTO students(id,name,course,parent_id,profile_id,balance,archived,voided)
                    VALUES(?,?,?,?,?,0,0,0)''', (student_id, name, '数学', parent, profile))
                return profile

            void_person = add_person(126, 'VoidDoc')
            zero_person = add_person(169, 'ZeroDoc')
            money_person = add_person(170, 'MoneyDoc')
            taught_person = add_person(171, 'Taught')
            void_id = c.execute('''INSERT INTO vouchers(number,kind,status,student_id,student_name,course,lesson_date,amount_cents,created_by)
                VALUES('CZ-TEST-VOID','receipt','void',126,'VoidDoc','数学','2026-10-01',0,?)''', (owner,)).lastrowid
            event_id = c.execute('''INSERT INTO voucher_events(voucher_id,actor_id,action,detail)
                VALUES(?,?,'void','作废')''', (void_id, owner)).lastrowid
            zero_id = c.execute('''INSERT INTO vouchers(number,kind,status,student_id,student_name,course,lesson_date,amount_cents,paid_units,gift_units,created_by)
                VALUES('CZ-TEST-ZERO','receipt','pending',169,'ZeroDoc','数学','2026-10-02',0,0,0,?)''', (owner,)).lastrowid
            money_id = c.execute('''INSERT INTO vouchers(number,kind,status,student_id,student_name,course,lesson_date,amount_cents,created_by)
                VALUES('CZ-TEST-MONEY','receipt','approved',170,'MoneyDoc','数学','2026-10-03',8000,?)''', (owner,)).lastrowid
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,status)
                VALUES(?,?,?,?,100,'教室',?,?,'completed')''',
                (teacher, '数学', '2026-10-04T16:00', '2026-10-04T17:00', owner, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,171)', (lesson,))
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,updated_by)
                VALUES(?,171,100,'上过了',?)''', (lesson, owner))
            c.commit()
        ids = '126,169,170,171'
        dry = subprocess.run([sys.executable, str(SCRIPT), '--delete-course-ids', ids], env=env, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn(f'vouchers #{void_id}', dry.stdout)
        self.assertIn(f'voucher_events #{event_id}', dry.stdout)
        self.assertIn(f'vouchers #{zero_id}', dry.stdout)
        self.assertIn(f'vouchers #{money_id}（有单据）', dry.stdout)
        self.assertIn(f'lesson_reports lesson={lesson} student=171（有上课记录）', dry.stdout)
        self.assertIn('courses_delete=0', dry.stdout)
        forced = subprocess.run([sys.executable, str(SCRIPT), '--delete-course-ids', ids, '--force'],
            env=env, capture_output=True, text=True)
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertIn('courses_delete=2', forced.stdout)
        self.assertIn(f'vouchers #{money_id}（有单据）', forced.stdout)
        self.assertIn('有上课记录', forced.stdout)
        self.assertIn('未写入', forced.stdout)
        applied = subprocess.run([sys.executable, str(SCRIPT), '--delete-course-ids', ids, '--force', '--apply'],
            env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn('payments_before=0', applied.stdout)
        self.assertIn('payments_after=0', applied.stdout)
        with server.connect() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id IN (126,169)').fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM vouchers WHERE id IN (?,?)', (void_id, zero_id)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM voucher_events WHERE id=?', (event_id,)).fetchone())
            self.assertEqual(c.execute('SELECT name FROM student_profiles WHERE id=?', (void_person,)).fetchone()[0], 'VoidDoc')
            self.assertEqual(c.execute('SELECT name FROM student_profiles WHERE id=?', (zero_person,)).fetchone()[0], 'ZeroDoc')
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id=170').fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM vouchers WHERE id=?', (money_id,)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id=171').fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM lesson_reports WHERE student_id=171').fetchone())
            self.assertEqual(c.execute('SELECT name FROM student_profiles WHERE id=?', (money_person,)).fetchone()[0], 'MoneyDoc')
            self.assertEqual(c.execute('SELECT name FROM student_profiles WHERE id=?', (taught_person,)).fetchone()[0], 'Taught')


if __name__ == '__main__':
    unittest.main()
