"""退学 works for a student whose courses are already archived, and 复学 keeps the balance."""
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'withdraw.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import deletion
import profiles
import server


class WithdrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def people(self, c, phone):
        uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Helen', 'x', 'admin')", (phone,)).lastrowid
        c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
        parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, '家长', 'x', 'parent')", ('9' + phone,)).lastrowid
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        profiles.ensure_enrolment_columns(c)
        return {'id': uid, 'role': 'owner'}, parent, profile

    def test_shell_profile_can_withdraw_and_reinstate_keeps_balance(self):
        with server.connect() as c:
            owner, parent, profile = self.people(c, '0433000001')
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,archived)
                VALUES('Ricky','数学',?,?,400,1)''', (parent, profile)).lastrowid
            teacher = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Kelsey', 'x', 'parent')",
                ('8' + uuid.uuid4().hex[:8],)).lastrowid
            tid = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher, '数学')).lastrowid
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2027-06-01T16:00','2027-06-01T17:00',100,'教室','scheduled',?,?)''',
                (tid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (future, sid))
            with self.assertRaises(ValueError):
                deletion.withdraw_student(c, owner, {'id': sid, 'courses': []})
            deletion.withdraw_student(c, owner, {'id': sid, 'courses': [{'student_id': sid, 'reason': 'keep'}]})
            row = c.execute('SELECT archived, balance, settle_reason FROM students WHERE id=?', (sid,)).fetchone()
            self.assertEqual((row['archived'], row['balance'], row['settle_reason']), (1, 400, 'keep'))
            self.assertEqual(c.execute('SELECT status FROM student_profiles WHERE id=?', (profile,)).fetchone()['status'], 'withdrawn')
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (future,)).fetchone()['status'], 'cancelled')
            self.assertTrue(profiles.profile_withdrawn(c, profile))
            event = c.execute("SELECT action FROM profile_events WHERE profile_id=? AND action='withdraw'", (profile,)).fetchone()
            self.assertEqual(event['action'], 'withdraw')
            deletion.reinstate_student(c, owner, {'id': sid})
            back = c.execute('SELECT archived, balance FROM students WHERE id=?', (sid,)).fetchone()
            self.assertEqual((back['archived'], back['balance']), (0, 400))
            self.assertEqual(c.execute('SELECT status FROM student_profiles WHERE id=?', (profile,)).fetchone()['status'], 'active')
            self.assertFalse(profiles.profile_withdrawn(c, profile))
            self.assertIsNotNone(c.execute("SELECT 1 FROM profile_events WHERE profile_id=? AND action='reinstate'", (profile,)).fetchone())

    def test_forfeit_is_not_cash_and_the_backfill_script_is_dry_run(self):
        with server.connect() as c:
            owner, parent, profile = self.people(c, '0433000002')
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance)
                VALUES('Nora','英语',?,?,300)''', (parent, profile)).lastrowid
            deletion.withdraw_student(c, owner, {'id': sid, 'courses': [{'student_id': sid, 'reason': 'void'}]})
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 0)
            self.assertIsNotNone(c.execute("SELECT 1 FROM ledger WHERE student_id=? AND kind='forfeit'", (sid,)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?', (sid,)).fetchone())
        script = Path(__file__).with_name('scripts') / 'backfill_withdrawn_status.py'
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, check=True)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)


if __name__ == '__main__':
    unittest.main()
