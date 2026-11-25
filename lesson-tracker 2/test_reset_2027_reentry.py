"""The 2027 re-entry reset keeps 2026 money and taught lessons, and drops the empty future."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'reentry.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'scripts' / 'reset_for_2027_reentry.py'


class ResetFor2027Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        cls._seed()

    @classmethod
    def _seed(cls):
        with server.connect() as c:
            owner = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner,))
            teacher = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?,?)", (owner, '数学')).lastrowid
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
            active = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,archived,voided)
                VALUES('陈一诺','数学',?,?,1000,0,0)''', (parent, profile)).lastrowid
            stopped = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,archived,voided)
                VALUES('陈一诺','英语',?,?,400,1,0)''', (parent, profile)).lastrowid
            empty = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,archived,voided)
                VALUES('陈一诺','测试课',?,?,0,1,0)''', (parent, profile)).lastrowid
            other_parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433000003','另一位','x','parent')").lastrowid
            other_profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            alone = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,archived,voided)
                VALUES('王星然','英语',?,?,200,1,1)''', (other_parent, other_profile)).lastrowid

            def lesson(student, start, status='scheduled'):
                lid = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,status)
                    VALUES(?,?,?,?,100,'教室',?,?,?)''',
                    (teacher, '数学', start, start[:10] + 'T17:00', owner, uuid.uuid4().hex, status)).lastrowid
                c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (lid, student))
                return lid

            def cash(student, cents, day):
                lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                    VALUES(?,?,'credit',?,'充值',?,?)''', (student, cents, day, owner, uuid.uuid4().hex)).lastrowid
                c.execute('''INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by)
                    VALUES(?,?, 'bank','',?)''', (lid, cents, owner))
                c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents)
                    VALUES(?,?,?,0,?,0,?,?)''', (student, lid, cents, cents, day, cents))
                return lid

            cls.november = lesson(active, '2026-11-30T16:00')
            cls.dec_empty = lesson(active, '2026-12-01T16:00')
            cls.dec_cancelled = lesson(active, '2026-12-10T16:00', 'cancelled')
            cls.dec_kept = lesson(stopped, '2026-12-20T16:00', 'completed')
            cls.year_2027 = lesson(empty, '2027-03-01T16:00')
            cls.taught = lesson(stopped, '2026-06-01T16:00', 'completed')
            cls.alone_taught = lesson(alone, '2026-08-01T16:00', 'completed')
            pay = cash(stopped, 400, '2026-06-01')
            cash(active, 1000, '2026-03-01')
            cash(alone, 200, '2026-08-01')
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'上过了','','',?,?)''', (cls.dec_kept, stopped, pay, owner))
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'六月','','',NULL,?)''', (cls.taught, stopped, owner))
            series = uuid.uuid4().hex
            c.execute('''INSERT INTO lesson_series(id,interval_days,endless,next_index,template,created_by)
                VALUES(?,7,1,1,'{}',?)''', (series, owner))
            c.execute('UPDATE lessons SET series_id=? WHERE id=?', (series, cls.november))
            c.commit()
            cls.owner = owner
            cls.teacher = teacher
            cls.parent = parent
            cls.profile = profile
            cls.active = active
            cls.stopped = stopped
            cls.empty = empty
            cls.alone = alone
            cls.series = series

    def test_dry_run_then_apply_keeps_money_and_december_records(self):
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        self.assertIn('2026-12-20', dry.stdout)
        self.assertIn('有课后记录', dry.stdout)
        self.assertIn('并入', dry.stdout)
        self.assertIn('删除（没有上课记录，也没有钱）', dry.stdout)
        self.assertIn('恢复为在读', dry.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (self.dec_empty,)).fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_series').fetchone()[0], 1)
        env = {**os.environ, 'LESSON_DB': str(DB)}
        applied = subprocess.run([sys.executable, str(SCRIPT), '--apply'], env=env, capture_output=True, text=True, check=True)
        self.assertIn('已写入', applied.stdout)
        self.assertIn('payments_before=1600 payments_after=1600', applied.stdout)
        self.assertIn('balances_before=1600 balances_after=1600', applied.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (self.november,)).fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (self.dec_empty,)).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (self.dec_cancelled,)).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (self.year_2027,)).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (self.dec_kept,)).fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (self.dec_kept,)).fetchone()[0], self.active)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_series').fetchone()[0], 0)
            self.assertIsNone(c.execute('SELECT series_id FROM lessons WHERE id=?', (self.november,)).fetchone()[0])
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id=?', (self.empty,)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id=?', (self.stopped,)).fetchone())
            self.assertEqual(c.execute('SELECT balance, archived, voided FROM students WHERE id=?', (self.active,)).fetchone(), (1400, 0, 0))
            alone = c.execute('SELECT balance, archived, voided FROM students WHERE id=?', (self.alone,)).fetchone()
            self.assertEqual(tuple(alone), (200, 0, 0))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM student_profiles').fetchone()[0], 2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM profile_parents').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM teachers').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0], 1600)
            self.assertEqual(c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0], 1600)


if __name__ == '__main__':
    unittest.main()
