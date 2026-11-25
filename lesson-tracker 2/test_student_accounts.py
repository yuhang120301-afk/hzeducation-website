"""A person stays visible with no course, and same-person courses share one account."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'people.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import profiles
import deletion
import server

ROOT = Path(__file__).resolve().parent
MERGE = ROOT / 'scripts' / 'merge_person_profiles.py'
RESTORE = ROOT / 'scripts' / 'restore_students_from_backup.py'


class StudentAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_deleting_the_last_course_keeps_the_student_visible(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433100001','Helen','x','admin')").lastrowid
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433100002','家长','x','parent')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
            course = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,grade,birthday)
                VALUES('Selina','数学',?,?,0,'Y4','2016-04-01')''', (parent, profile)).lastrowid
            removed = deletion.stop_course(c, owner, {'student_id': course})
            self.assertTrue(removed['deleted'])
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id=?', (course,)).fetchone())
            kept = c.execute('SELECT name, grade, birthday FROM student_profiles WHERE id=?', (profile,)).fetchone()
            self.assertEqual(tuple(kept), ('Selina', 'Y4', '2016-04-01'))
            shells = profiles.profiles_without_courses(c, set(), owner)
            shell = next(item for item in shells if item['profile_id'] == profile)
            self.assertTrue(shell['no_course'])
            self.assertEqual(shell['name'], 'Selina')
            self.assertEqual(shell['course'], '')
            subject = c.execute("SELECT id FROM subjects WHERE name='英语' AND active=1").fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            added = profiles.add_course(c, owner, {'profile_id': profile, 'subject_id': subject, 'course_type_id': kind}, server.text_value)
            row = c.execute('SELECT name, course, profile_id FROM students WHERE id=?', (added['student_id'],)).fetchone()
            self.assertEqual(tuple(row), ('Selina', '英语', profile))

    def test_merge_groups_same_person_and_restore_is_idempotent(self):
        with server.connect() as c:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433100003','妈妈','x','parent')").lastrowid
            other = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433100004','另一位','x','parent')").lastrowid
            first = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('Zachary',)).lastrowid
            second = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('Zachary',)).lastrowid
            c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Zachary','数学',?,?,100)''', (parent, first))
            c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('zachary','英语',?,?,40)''', (parent, second))
            c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (first, parent))
            c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (second, parent))
            solo = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('Ruby',)).lastrowid
            c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Ruby','数学',?,?,10)''', (other, solo))
            clash_a = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('Sunny',)).lastrowid
            clash_b = c.execute('INSERT INTO student_profiles(name) VALUES(?)', ('Sunny',)).lastrowid
            c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Sunny','数学',?,?,1)''', (parent, clash_a))
            c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Sunny','数学',?,?,1)''', (parent, clash_b))
            c.execute("INSERT INTO student_profiles(name) VALUES('Selina')")
            before = c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0]
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(MERGE)], env=env, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('Zachary', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        self.assertIn('不并', dry.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(DISTINCT profile_id) FROM students WHERE name LIKE "Zachary" OR name LIKE "zachary"').fetchone()[0], 2)
        applied = subprocess.run([sys.executable, str(MERGE), '--apply'], env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn('已写入', applied.stdout)
        with sqlite3.connect(DB) as c:
            profiles_used = c.execute('''SELECT COUNT(DISTINCT profile_id) FROM students
                WHERE LOWER(name)="zachary"''').fetchone()[0]
            self.assertEqual(profiles_used, 1)
            self.assertEqual(c.execute('SELECT COUNT(DISTINCT profile_id) FROM students WHERE name="Sunny"').fetchone()[0], 2)
            self.assertEqual(c.execute('SELECT profile_id FROM students WHERE name="Ruby"').fetchone()[0], solo)
            self.assertEqual(c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0], before)
        again = subprocess.run([sys.executable, str(MERGE)], env=env, capture_output=True, text=True)
        self.assertNotIn('Zachary', again.stdout)
        self.assertIn('不并 Sunny', again.stdout)
        backup = Path(tempfile.mkdtemp()) / 'backup.sqlite3'
        with sqlite3.connect(backup) as b:
            b.execute('CREATE TABLE student_profiles(id INTEGER PRIMARY KEY, name TEXT, birthday TEXT, grade TEXT, notes TEXT, study_status TEXT)')
            b.execute('CREATE TABLE users(id INTEGER PRIMARY KEY, phone TEXT, name TEXT, password TEXT, role TEXT)')
            b.execute('CREATE TABLE students(id INTEGER PRIMARY KEY, name TEXT, course TEXT, parent_id INTEGER, profile_id INTEGER, balance INTEGER, archived INTEGER, birthday TEXT, grade TEXT, notes TEXT)')
            b.execute('CREATE TABLE profile_parents(profile_id INTEGER, user_id INTEGER)')
            b.execute("INSERT INTO users VALUES(7,'0433999001','Lachlan妈妈','secret','parent')")
            b.execute("INSERT INTO student_profiles VALUES(800,'Lachlan','2015-01-02','Y5','喜欢画画','studying')")
            b.execute("INSERT INTO students VALUES(1,'Lachlan','数学',7,800,500,1,'2015-01-02','Y5','')")
            b.execute('INSERT INTO profile_parents VALUES(800,7)')
            b.execute("INSERT INTO student_profiles VALUES(81,'Selina','','','','studying')")
        with server.connect() as c:
            c.execute("INSERT INTO student_profiles(id,name) VALUES(800,'')")
        dry_restore = subprocess.run([sys.executable, str(RESTORE), '--backup', str(backup)], env=env, capture_output=True, text=True)
        self.assertEqual(dry_restore.returncode, 0, dry_restore.stderr)
        self.assertIn('Lachlan', dry_restore.stdout)
        self.assertIn('未写入', dry_restore.stdout)
        self.assertIn('已有同名学生', dry_restore.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute("SELECT name FROM student_profiles WHERE id=800").fetchone()[0], '')
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE name="Lachlan"').fetchone())
        applied_restore = subprocess.run([sys.executable, str(RESTORE), '--backup', str(backup), '--apply'], env=env, capture_output=True, text=True)
        self.assertEqual(applied_restore.returncode, 0, applied_restore.stderr)
        with sqlite3.connect(DB) as c:
            restored = c.execute('SELECT name, grade, birthday, notes FROM student_profiles WHERE id=800').fetchone()
            self.assertEqual(tuple(restored), ('Lachlan', 'Y5', '2015-01-02', '喜欢画画'))
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE profile_id=800').fetchone())
            self.assertIsNotNone(c.execute("SELECT 1 FROM users WHERE phone='0433999001'").fetchone())
            self.assertEqual(c.execute('SELECT COALESCE(SUM(balance),0) FROM students').fetchone()[0], before)
        second = subprocess.run([sys.executable, str(RESTORE), '--backup', str(backup)], env=env, capture_output=True, text=True)
        self.assertIn('档案还在', second.stdout)
        self.assertNotIn('恢复学生档案', second.stdout)


if __name__ == '__main__':
    unittest.main()
