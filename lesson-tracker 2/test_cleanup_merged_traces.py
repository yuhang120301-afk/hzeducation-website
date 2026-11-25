"""Empty test courses from the 2027 reset can be removed without touching real history."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'cleanup.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'scripts' / 'cleanup_merged_test_traces.py'


class CleanupMergedTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            owner = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433001001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner,))
            teacher = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (owner, '数学')).lastrowid
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433001002','家长','x','parent')").lastrowid

            def profile():
                return c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid

            def person(student_id, name, course, balance=0, archived=0, voided=0):
                pid = profile()
                c.execute('''INSERT INTO students(id,name,course,parent_id,profile_id,balance,archived,voided)
                    VALUES(?,?,?,?,?,?,?,?)''', (student_id, name, course, parent, pid, balance, archived, voided))
                c.execute('INSERT OR IGNORE INTO profile_parents(profile_id, user_id) VALUES(?,?)', (pid, parent))
                return pid

            def lesson(student, start, status='scheduled', title='数学'):
                lid = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,status)
                    VALUES(?,?,?,?,100,'教室',?,?,?)''',
                    (teacher, title, start, start[:10] + 'T17:00', owner, uuid.uuid4().hex, status)).lastrowid
                c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (lid, student))
                return lid

            def ledger(ledger_id, student, delta, note, reversal_of=None):
                c.execute('''INSERT INTO ledger(id,student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of)
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                    (ledger_id, student, delta, 'credit' if delta > 0 else 'reversal', '2026-08-01', note, owner, uuid.uuid4().hex, reversal_of))
                return ledger_id

            person(4, 'Atticus', '英语 一对一')
            person(26, 'Bryce', '数学 一对一')
            person(69, 'Claire', '数学')
            person(1, 'Austin Hao', '数学')
            person(28, 'Benjamin', '数学')
            person(46, 'Atticus', '数学 + 英语')
            person(66, 'Atticus', '英语')
            person(93, 'Amelia', '数学 + 英语', balance=1000)
            person(200, 'Mia Chen', '数学', archived=1)
            person(201, 'mia   chen', '数学', balance=500)
            person(202, 'Noah', '数学')
            person(203, 'Noah', '英语', balance=50)
            person(204, 'Owen', '数学', balance=20)
            person(205, 'Owen', '数学', balance=30)
            person(206, 'Pia', '数学', archived=1)
            person(207, 'Pia', '数学', balance=80)
            c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on)
                VALUES(4,0,0,0,0,'')''')
            lesson(26, '2026-11-02T16:00', 'cancelled')
            for index in range(12):
                lesson(46, f'2026-06-{index + 1:02d}T16:00', 'completed')
            kept = ledger(300, 46, 800, 'Atticus 真实充值')
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'上过','','',?,?)''',
                (c.execute('SELECT id FROM lessons WHERE id IN (SELECT lesson_id FROM lesson_students WHERE student_id=46) LIMIT 1').fetchone()[0], 46, kept, owner))
            ledger(301, 66, 100, 'Atticus 英语账')
            ledger(108, 93, 3700, '学期班 · 每节 2.5 小时 · 37 节 · 测试')
            ledger(118, 93, -3700, '作废单据 CZ-2026-0007', 108)
            ledger(119, 93, 1000, 'Amelia 真实余额')
            batch = c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on)
                VALUES(93,108,3700,0,0,0,'2026-08-01')''').lastrowid
            c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(108,?,3700,0,0)', (batch,))
            c.execute('INSERT INTO pack_payments(batch_id,ledger_id,amount_cents,paid_on,method,created_by) VALUES(?,108,0,?,"",?)',
                (batch, '2026-08-01', owner))
            c.execute('INSERT INTO ledger_edits(ledger_id,actor_id,reason,before_json,after_json) VALUES(108,?,?,?,?)',
                (owner, '测试', '{}', '{}'))
            ledger(400, 201, 500, 'Mia 的真账')
            lesson(206, '2027-03-01T16:00')
            c.commit()
            cls.owner = owner

    def test_dry_run_then_apply_removes_only_empty_traces(self):
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(SCRIPT), '--today', '2026-11-25'], env=env, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        self.assertIn('#4', dry.stdout)
        self.assertIn('#69', dry.stdout)
        self.assertIn('Helen 还没确认', dry.stdout)
        self.assertIn('没有多余记录', dry.stdout)
        self.assertIn('空的重复课程行', dry.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM students WHERE id=4').fetchone()[0], 1)
        applied = subprocess.run([sys.executable, str(SCRIPT), '--apply', '--today', '2026-11-25'], env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn('已写入', applied.stdout)
        self.assertIn('payments_before=', applied.stdout)
        self.assertIn('balances_before=', applied.stdout)
        with sqlite3.connect(DB) as c:
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id IN (4,26,200)').fetchone())
            self.assertIsNotNone(c.execute("SELECT 1 FROM student_profiles WHERE id IN (SELECT profile_id FROM students WHERE id=46)").fetchone())
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons l JOIN lesson_students ls ON ls.lesson_id=l.id WHERE ls.student_id=46').fetchone()[0], 12)
            self.assertIsNotNone(c.execute('SELECT 1 FROM ledger WHERE id=300').fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM ledger WHERE id=301').fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM ledger WHERE id IN (108,118)').fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM credit_batches WHERE ledger_id=108').fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM ledger_edits WHERE ledger_id=108').fetchone())
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=93').fetchone()[0], 1000)
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id=69').fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id IN (1,28,201,202,203,204,205,206,207)').fetchone())
            self.assertEqual(c.execute('SELECT COUNT(*) FROM students WHERE id IN (1,28,201,202,203,204,205,206,207)').fetchone()[0], 9)
            self.assertEqual(c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0],
                c.execute('SELECT balance FROM students WHERE id=93').fetchone()[0]
                + 500 + 50 + 20 + 30 + 80)
            orphans = c.execute('''SELECT COUNT(*) FROM student_profiles p
                WHERE NOT EXISTS (SELECT 1 FROM students s WHERE s.profile_id=p.id)''').fetchone()[0]
            self.assertGreaterEqual(orphans, 3)


if __name__ == '__main__':
    unittest.main()
