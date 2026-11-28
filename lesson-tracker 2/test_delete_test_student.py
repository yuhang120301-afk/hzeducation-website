"""Only the profile named exactly 测试学生 is removed, and a shared parent stays."""
import io
import os
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'test-student.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import delete_test_student
import profiles
import server


class DeleteTestStudentTests(unittest.TestCase):
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
        return f'047{self.n:07d}'

    def user(self, role, name):
        return self.c.execute(
            'INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
            (self.phone(), name, 'x', role)).lastrowid

    def profile(self, name, parent):
        profiles.ensure_enrolment_columns(self.c)
        pid = self.c.execute('INSERT INTO student_profiles(name) VALUES(?)', (name,)).lastrowid
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (pid, parent))
        return pid

    def course(self, profile, parent, course='数学'):
        return self.c.execute(
            'INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original) VALUES(?,?,?,?,0,0)',
            ('孩子', course, parent, profile)).lastrowid

    def run_fix(self):
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            delete_test_student.run(self.c, os.environ['LESSON_DB'])
        return buffer.getvalue()

    def test_exact_profile_is_removed_and_finance_is_logged(self):
        parent = self.user('parent', '测试家长')
        pid = self.profile('测试学生', parent)
        sid = self.course(pid, parent)
        boss = self.user('admin', 'Helen')
        ledger = self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,100,'credit','2026-01-01','购课',?,?)",
            (sid, boss, uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,10000,?,?,?)',
            (ledger, 'bank', '', boss))
        teacher = self.user('parent', '老师')
        tid = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher, '数学')).lastrowid
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?, '数学','2026-02-01T16:00','2026-02-01T17:00',100,'教室','completed',?,?)''',
            (tid, boss, uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
        charge = self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,-100,'lesson','2026-02-01','上课',?,?)",
            (sid, boss, uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,ledger_id,updated_by,fee_cents)
            VALUES(?,?,100,'内容',?,?,5000)''', (lid, sid, charge, boss))
        other_parent = self.user('parent', '别人家长')
        other_profile = self.profile('Ruby', other_parent)
        other = self.course(other_profile, other_parent, '英语')
        shared = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?, '数学','2026-03-01T16:00','2026-03-01T17:00',100,'教室','scheduled',?,?)''',
            (tid, boss, uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (shared, sid))
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (shared, other))
        lookalike = self.profile('测试学生2', other_parent)
        log = self.run_fix()
        self.assertIn('DRY-RUN  删除测试学生', log)
        self.assertIn('实收减少 $100.00', log)
        self.assertIn('计入分红的课酬减少 $50.00', log)
        self.assertIn('APPLY  已删除档案', log)
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (pid,)).fetchone())
        self.assertIsNone(self.c.execute('SELECT 1 FROM users WHERE id=?', (parent,)).fetchone())
        self.assertIsNone(self.c.execute('SELECT 1 FROM lessons WHERE id=?', (lid,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM lessons WHERE id=?', (shared,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=?', (shared, other)).fetchone())
        self.assertIsNone(self.c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=?', (shared, sid)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (other_profile,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (lookalike,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM users WHERE id=?', (other_parent,)).fetchone())
        again = self.run_fix()
        self.assertNotIn('APPLY', again)
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM students WHERE id=?', (other,)).fetchone())

    def test_parent_linked_to_another_child_is_only_unlinked(self):
        parent = self.user('parent', '共用家长')
        pid = self.profile('测试学生', parent)
        self.course(pid, parent)
        other = self.profile('Ruby', parent)
        log = self.run_fix()
        self.assertIn('只取消关联', log)
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (pid,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM users WHERE id=?', (parent,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?', (other, parent)).fetchone())

    def test_two_exact_names_are_left_alone(self):
        parent = self.user('parent', '家长')
        first = self.profile('测试学生', parent)
        second = self.profile('测试学生', parent)
        log = self.run_fix()
        self.assertIn('这次不删', log)
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (first,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (second,)).fetchone())


if __name__ == '__main__':
    unittest.main()
