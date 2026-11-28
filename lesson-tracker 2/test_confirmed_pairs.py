"""Cathy Bao folds into Cathy, and Zoey folds into Zoey Xue."""
import io
import os
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'pairs.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import merge_confirmed_pairs
import profiles
import server


class ConfirmedPairTests(unittest.TestCase):
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
        return f'046{self.n:07d}'

    def parent(self, name):
        return self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            (self.phone(), name, 'x')).lastrowid

    def profile(self, name):
        profiles.ensure_enrolment_columns(self.c)
        return self.c.execute('INSERT INTO student_profiles(name) VALUES(?)', (name,)).lastrowid

    def course(self, profile, parent, course):
        return self.c.execute(
            'INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES(?,?,?,?,0)',
            (course and '孩子', course, parent, profile)).lastrowid

    def run_fix(self):
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            merge_confirmed_pairs.run(self.c, os.environ['LESSON_DB'])
        return buffer.getvalue()

    def test_cathy_and_zoey_duplicates_fold_into_the_profile_with_data(self):
        parent = self.parent('Cathy家长')
        cathy = self.profile('Cathy')
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (cathy, parent))
        maths = self.course(cathy, parent, '数学')
        vce = self.course(cathy, parent, 'VCE 中数')
        bao = self.profile('Cathy Bao')
        extra = self.parent('另一位')
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (bao, extra))
        self.c.execute('''INSERT INTO student_origin_events(profile_id, helen_original, effective_from, created_by)
            VALUES(?,1,'2000-01-01',?)''', (bao, parent))
        zoey = self.profile('Zoey')
        xue = self.profile('Zoey Xue')
        xue_parent = self.parent('Zoey家长')
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (xue, xue_parent))
        ruby = self.profile('Ruby')
        self.course(ruby, self.parent('Ruby家长'), '英语')
        log = self.run_fix()
        self.assertIn('Cathy：保留', log)
        self.assertIn('Zoey Xue：保留', log)
        self.assertIn('姓名用「Zoey Xue」', log)
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (bao,)).fetchone())
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (zoey,)).fetchone())
        self.assertEqual(self.c.execute('SELECT name FROM student_profiles WHERE id=?', (cathy,)).fetchone()['name'], 'Cathy')
        self.assertEqual(self.c.execute('SELECT name FROM student_profiles WHERE id=?', (xue,)).fetchone()['name'], 'Zoey Xue')
        self.assertEqual(self.c.execute('SELECT profile_id FROM students WHERE id=?', (maths,)).fetchone()[0], cathy)
        self.assertEqual(self.c.execute('SELECT profile_id FROM students WHERE id=?', (vce,)).fetchone()[0], cathy)
        self.assertIsNotNone(self.c.execute(
            'SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?', (cathy, extra)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (ruby,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM users WHERE id=?', (extra,)).fetchone())
        again = self.run_fix()
        self.assertNotIn('APPLY', again)

    def test_a_pair_with_lessons_on_both_sides_is_skipped(self):
        parent = self.parent('家长')
        left = self.profile('Zoey')
        right = self.profile('Zoey Xue')
        a = self.course(left, parent, '数学')
        b = self.course(right, parent, '英语')
        boss = self.parent('记录人')
        for sid in (a, b):
            self.c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,100,'credit','2026-01-01','购课',?,?)",
                (sid, boss, uuid.uuid4().hex))
        log = self.run_fix()
        self.assertIn('不合并', log)
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (left,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (right,)).fetchone())

    def test_zoey_keeps_her_own_name_when_she_has_the_history(self):
        parent = self.parent('家长')
        zoey = self.profile('Zoey')
        sid = self.course(zoey, parent, '数学')
        boss = self.parent('记录人')
        self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,100,'credit','2026-01-01','购课',?,?)",
            (sid, boss, uuid.uuid4().hex))
        xue = self.profile('Zoey Xue')
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (xue, parent))
        log = self.run_fix()
        self.assertIn('姓名用「Zoey」', log)
        self.assertEqual(self.c.execute('SELECT name FROM student_profiles WHERE id=?', (zoey,)).fetchone()['name'], 'Zoey')
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (xue,)).fetchone())


class UnlinkParentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_unlinking_an_empty_profile_keeps_the_login_for_the_other_child(self):
        with server.connect() as c:
            owner = {'id': c.execute("INSERT INTO users(phone,name,password,role) VALUES('0450000001','Helen','x','admin')").lastrowid, 'role': 'owner'}
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner['id'],))
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0450000002','家长','x','parent')").lastrowid
            profiles.ensure_enrolment_columns(c)
            empty = c.execute("INSERT INTO student_profiles(name) VALUES('空的')").lastrowid
            other = c.execute("INSERT INTO student_profiles(name) VALUES('另一个')").lastrowid
            c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (empty, parent))
            c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (other, parent))
            c.execute('INSERT INTO students(name,course,parent_id,profile_id) VALUES(?,?,?,?)', ('另一个', '英语', parent, other))
            profiles.unlink_parent(c, owner, {'profile_id': empty, 'student_id': 'p%s' % empty, 'parent_user_id': parent})
            self.assertIsNone(c.execute('SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?', (empty, parent)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM users WHERE id=?', (parent,)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?', (other, parent)).fetchone())


if __name__ == '__main__':
    unittest.main()
