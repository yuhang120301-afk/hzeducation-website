"""A student with no current course still has a profile. Status lives on that profile."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'visible.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import profiles
import server


class StudentVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_archived_courses_leave_the_profile_visible(self):
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0411000001','Helen','x','admin')").lastrowid
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0411000002','家长','x','parent')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            course = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,grade,archived)
                VALUES('Edward','数学',?,?,400,'Y5',0)''', (parent, profile)).lastrowid
            profiles.ensure_enrolment_columns(c)
            self.assertEqual(c.execute('SELECT study_status FROM student_profiles WHERE id=?', (profile,)).fetchone()[0], 'studying')
            c.execute("UPDATE students SET archived=1, course=? WHERE id=?", (f'数学 #{course}', course))
            rows = [dict(r) for r in c.execute('SELECT * FROM students WHERE profile_id=?', (profile,))]
            shells = profiles.course_shells(c, rows)
            self.assertEqual(len(shells), 1)
            self.assertTrue(shells[0]['no_course'])
            self.assertEqual(shells[0]['course'], '')
            self.assertEqual(shells[0]['balance'], 0)
            self.assertFalse(shells[0]['archived'])
            self.assertFalse(profiles.profile_withdrawn(c, profile))
            c.execute("INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?, 'archived')", (course, uid))
            self.assertEqual(profiles.course_shells(c, rows), [])
            c.execute('DELETE FROM profile_audit WHERE student_id=?', (course,))
            subject = c.execute("SELECT id FROM subjects WHERE name='英语' AND active=1").fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            added = profiles.add_course(c, owner, {
                'student_id': course, 'subject_id': subject, 'course_type_id': kind,
            }, server.text_value)
            active = c.execute('SELECT course, archived FROM students WHERE id=?', (added['student_id'],)).fetchone()
            self.assertEqual(active['archived'], 0)
            self.assertEqual(active['course'], '英语')
            profiles.update(c, owner, {
                'student_id': added['student_id'], 'name': 'Edward', 'grade': 'Y5',
                'billing_unit': 'lesson', 'study_status': 'graduated',
            }, server.text_value)
            self.assertEqual(c.execute('SELECT study_status FROM student_profiles WHERE id=?', (profile,)).fetchone()[0], 'graduated')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM profile_audit WHERE action='archived'").fetchone()[0], 0)
