"""Only Miya, Rebecca, and Zoey Xue are merged, and a money clash is left alone."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'merge.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import merge_named_profiles
import server


class MergeNamedProfilesTests(unittest.TestCase):
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
        return f'048{self.n:04d}{uuid.uuid4().int % 10000:04d}'[:15]

    def parent(self, name):
        return self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            (self.phone(), name, 'x')).lastrowid

    def profile(self, name):
        return self.c.execute('INSERT INTO student_profiles(name) VALUES(?)', (name,)).lastrowid

    def course(self, profile, parent, course, archived=0):
        return self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original,archived)
            VALUES(?,?,?,?,0,0,?)''', (course and 'child', course, parent, profile, archived)).lastrowid

    def test_empty_duplicate_is_merged_and_other_names_stay(self):
        keeper = self.profile('Miya')
        parent = self.parent('Miya家长')
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (keeper, parent))
        course = self.course(keeper, parent, '数学')
        empty = self.profile('Miya')
        other_parent = self.parent('另一位')
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (empty, other_parent))
        self.c.execute('''INSERT INTO student_origin_events(profile_id, helen_original, effective_from, created_by)
            VALUES(?,1,'2000-01-01',?)''', (empty, parent))
        rebecca_kept = self.profile('Rebecca')
        self.course(rebecca_kept, self.parent('Rebecca家长'), '英语')
        rebecca_empty = self.profile('Rebecca')
        stranger = self.profile('Mia')
        stranger_course = self.course(stranger, self.parent('Mia家长'), '科学')
        merge_named_profiles.run(self.c, os.environ['LESSON_DB'])
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (empty,)).fetchone())
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (rebecca_empty,)).fetchone())
        self.assertEqual(self.c.execute('SELECT profile_id FROM students WHERE id=?', (course,)).fetchone()[0], keeper)
        self.assertIsNotNone(self.c.execute(
            'SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?', (keeper, other_parent)).fetchone())
        self.assertEqual(self.c.execute(
            'SELECT profile_id FROM students WHERE id=?', (stranger_course,)).fetchone()[0], stranger)
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (stranger,)).fetchone())
        again = self.c.execute('SELECT COUNT(*) FROM student_profiles WHERE name=?', ('Miya',)).fetchone()[0]
        merge_named_profiles.run(self.c, os.environ['LESSON_DB'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM student_profiles WHERE name=?', ('Miya',)).fetchone()[0], again)

    def test_two_profiles_with_lessons_are_skipped(self):
        first = self.profile('Zoey Xue')
        second = self.profile('Zoey Xue')
        parent = self.parent('Zoey家长')
        left = self.course(first, parent, '数学', archived=1)
        right = self.course(second, parent, '英语', archived=1)
        for sid in (left, right):
            self.c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'credit','2026-01-01','购课',?,?)",
                (sid, 100, parent, uuid.uuid4().hex))
        merge_named_profiles.run(self.c, os.environ['LESSON_DB'])
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (first,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (second,)).fetchone())
        self.assertEqual(self.c.execute('SELECT profile_id FROM students WHERE id=?', (left,)).fetchone()[0], first)
        self.assertEqual(self.c.execute('SELECT profile_id FROM students WHERE id=?', (right,)).fetchone()[0], second)


if __name__ == '__main__':
    unittest.main()
