"""The Term 1 script must be reversible in a dry run and safe on an old database."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path


def add_live_rows(path, soon):
    with sqlite3.connect(path) as c:
        c.execute('INSERT INTO student_profiles(id) VALUES(2)')
        c.execute('INSERT INTO student_profiles(id) VALUES(3)')
        c.execute("INSERT INTO students(id,name,course,parent_id,balance,profile_id,notes) VALUES(8,'Atticus Chen','数学',2,500,2,'保留')")
        c.execute("INSERT INTO students(id,name,course,parent_id,balance,profile_id) VALUES(9,'Benjamin','数学',2,800,3)")
        c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(8,500,'credit','2026-10-01','购入',1,?)", (uuid.uuid4().hex,))
        c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(9,800,'credit','2026-10-01','购入',1,?)", (uuid.uuid4().hex,))
        c.execute("INSERT INTO teachers(id,user_id,subject) VALUES(3,1,'数学')")
        rows = [
            (20, 2, '2026-11-01T16:00', '2026-11-01T17:00', '过去的课', 'scheduled', [7]),
            (21, 2, soon, soon[:11] + '11:00', '即将上课', 'scheduled', [7]),
            (22, 2, '2027-06-01T16:00', '2027-06-01T17:00', '远期课', 'scheduled', [7]),
            (23, 2, '2027-01-30T19:00', '2027-01-30T20:00', 'Atticus 已有', 'scheduled', [8]),
            (24, 3, '2027-01-26T19:30', '2027-01-26T21:00', 'Benjamin 已有', 'scheduled', [9]),
            (26, 3, '2027-04-01T16:00', '2027-04-01T17:00', 'Atticus 与陈一诺', 'scheduled', [8, 7]),
            (27, 3, '2026-10-02T16:00', '2026-10-02T17:00', 'Atticus 过去的课', 'completed', [8]),
        ]
        for lesson_id, teacher_id, start, end, title, status, students in rows:
            c.execute(
                'INSERT INTO lessons(id,teacher_id,title,starts_at,ends_at,planned_units,status,created_by,request_id) VALUES(?,?,?,?,?,100,?,1,?)',
                (lesson_id, teacher_id, title, start, end, status, uuid.uuid4().hex))
            c.executemany('INSERT INTO lesson_students VALUES(?,?)', [(lesson_id, sid) for sid in students])
        c.execute("INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,updated_by) VALUES(27,8,100,'保留反馈','作业','很好',1)")
        c.execute('''CREATE TABLE cash_entries (
            ledger_id INTEGER PRIMARY KEY, cash_delta INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'AUD',
            payment_method TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '', recorded_by INTEGER NOT NULL)''')
        c.execute("INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(3,200000,'bank','测试收款',1)")
        c.execute('''CREATE TABLE credit_batches (
            id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, ledger_id INTEGER UNIQUE,
            purchased INTEGER NOT NULL, gifted INTEGER NOT NULL, paid_left INTEGER NOT NULL,
            gift_left INTEGER NOT NULL, credited_on TEXT NOT NULL, legacy INTEGER NOT NULL DEFAULT 0)''')
        c.execute("INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on) VALUES(7,3,2000,0,1350,0,'2026-09-01')")


def dump(path):
    with sqlite3.connect(path) as c:
        return {
            'students': c.execute('SELECT id,name,balance,notes FROM students ORDER BY id').fetchall(),
            'lessons': c.execute('SELECT id,status,starts_at,title FROM lessons ORDER BY id').fetchall(),
            'ledger': c.execute('SELECT id,student_id,delta,kind FROM ledger ORDER BY id').fetchall(),
            'tables': [row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")],
        }


class Term1ScheduleTests(unittest.TestCase):
    def test_dry_run_is_idle_and_apply_is_idempotent(self):
        import server
        import teaching
        from test_migration import build_old_database
        import term1_2027_schedule as job

        folder = tempfile.mkdtemp()
        path = str(Path(folder) / 'old.sqlite3')
        build_old_database(path)
        soon = (teaching.now_local() + __import__('datetime').timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M')
        add_live_rows(path, soon)
        before = dump(path)
        previous = server.DB_PATH
        previous_demo = os.environ.get('LESSON_DEMO')
        try:
            os.environ['LESSON_DEMO'] = '1'
            os.environ['LESSON_DB'] = '/var/data/lessons.sqlite3'
            self.assertFalse(server.demo_seed_allowed())
            os.environ['LESSON_DB'] = path
            self.assertTrue(server.demo_seed_allowed())
            os.environ['LESSON_DEMO'] = '0'
            self.assertFalse(server.demo_seed_allowed())

            server.DB_PATH = path
            os.environ['LESSON_ORG_NAME'] = "HELEN'S MATH SECRETS"
            self.assertEqual(server.ORG_NAME, 'HZ Education Melbourne')
            out = str(Path(folder) / 'dry.txt')
            dry = job.run(path, apply=False, out_path=out)
            self.assertEqual(dump(path), before)
            self.assertGreaterEqual(dry['cancel'], 2)
            self.assertGreaterEqual(dry['keep'], 3)
            self.assertGreater(dry['create'], 0)
            self.assertIn('陈一诺', dry['cleared'])
            self.assertNotIn('Atticus Chen', dry['cleared'])
            self.assertNotIn('Benjamin', dry['cleared'])
            written = Path(out).read_text(encoding='utf-8')
            self.assertIn('取消', written)
            self.assertIn('清空', written)
            self.assertIn('cancel=', written)

            applied = job.run(path, apply=True, out_path=out)
            self.assertEqual(applied['cancel'], dry['cancel'])
            self.assertEqual(applied['create'], dry['create'])
            self.assertEqual(applied['clear_students'], dry['clear_students'])
            again = job.run(path, apply=True, out_path=out)
            self.assertEqual(again['cancel'], 0)
            self.assertEqual(again['create'], 0)
            self.assertEqual(again['clear_students'], 0)

            with server.connect() as c:
                status = {row['id']: row['status'] for row in c.execute('SELECT id,status FROM lessons')}
                self.assertNotIn(9, status)
                self.assertNotIn(20, status)
                self.assertEqual(status[21], 'cancelled')
                self.assertEqual(status[22], 'cancelled')
                self.assertEqual(status[23], 'scheduled')
                self.assertEqual(status[24], 'scheduled')
                self.assertEqual(status[26], 'scheduled')
                self.assertEqual(status[27], 'completed')
                self.assertEqual(c.execute("SELECT feedback FROM lesson_reports WHERE lesson_id=27 AND student_id=8").fetchone()['feedback'], '很好')
                balances = {row['id']: row['balance'] for row in c.execute('SELECT id,balance FROM students')}
                self.assertEqual(balances[7], 0)
                self.assertEqual(balances[8], 500)
                self.assertEqual(balances[9], 800)
                kept = c.execute('SELECT name, notes FROM students WHERE id=7').fetchone()
                self.assertEqual(kept['name'], '陈一诺')
                self.assertEqual(kept['notes'], '内部备注保留')
                self.assertEqual(c.execute('SELECT COUNT(*) FROM ledger WHERE student_id=7').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT SUM(delta) FROM ledger WHERE student_id=8').fetchone()[0], 500)
                self.assertEqual(c.execute('SELECT SUM(delta) FROM ledger WHERE student_id=9').fetchone()[0], 800)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM cash_entries').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM credit_batches WHERE student_id=7').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_reports WHERE student_id=7').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_students WHERE lesson_id=26 AND student_id=8').fetchone()[0], 1)
                self.assertEqual(c.execute('''SELECT COUNT(*) FROM students s WHERE s.balance!=COALESCE((SELECT SUM(l.delta) FROM ledger l WHERE l.student_id=s.id),0)''').fetchone()[0], 0)
                jeffery = c.execute("SELECT u.name FROM lessons l JOIN teachers t ON t.id=l.teacher_id JOIN users u ON u.id=t.user_id WHERE l.title='Jeffery · English' LIMIT 1").fetchone()
                self.assertEqual(jeffery['name'], 'Angela')
                self.assertEqual(c.execute("SELECT COUNT(*) FROM lessons WHERE title LIKE '%Yilia%'").fetchone()[0], 0)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM lessons WHERE title LIKE '%Bella 高数重叠%'").fetchone()[0], 0)
                self.assertGreater(c.execute("SELECT COUNT(*) FROM lessons WHERE title='Cathy 妹妹' AND status!='cancelled'").fetchone()[0], 0)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM users WHERE name='待定 3'").fetchone()[0], 0)
                if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='arrears'").fetchone():
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM arrears').fetchone()[0], 0)
                groups = c.execute("SELECT id FROM lessons WHERE title='VCE 中数快班' AND status!='cancelled'").fetchall()
                self.assertGreaterEqual(len(groups), 8)
                for group in groups:
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_students WHERE lesson_id=?', (group['id'],)).fetchone()[0], 0)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM users WHERE name='待定'").fetchone()[0], 1)
                self.assertGreaterEqual(c.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0], 1)
                writing = c.execute("SELECT COUNT(*) FROM lessons WHERE title='Atticus · Writing' AND status!='cancelled'").fetchone()[0]
                self.assertEqual(writing, 7)
        finally:
            server.DB_PATH = previous
            if previous_demo is None:
                os.environ.pop('LESSON_DEMO', None)
            else:
                os.environ['LESSON_DEMO'] = previous_demo


if __name__ == '__main__':
    unittest.main()
