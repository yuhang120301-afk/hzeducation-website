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


if __name__ == '__main__':
    unittest.main()
