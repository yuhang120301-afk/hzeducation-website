"""A person can leave without losing their account, history or money."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'left.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import auditlog
import deletion
import profiles
import server
import teaching


class StudentLeftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_leave_keeps_money_and_blocks_on_future_lessons(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433300001','Helen','x','admin')").lastrowid
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0433300002','家长','x','parent')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            teacher = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (uid, '数学')).lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Lachlan')").lastrowid
            c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
            course = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance)
                VALUES('Lachlan','数学',?,?,400)''', (parent, profile)).lastrowid
            c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,400,'credit','2026-08-01','充值',?,?)''', (course, uid, uuid.uuid4().hex))
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','scheduled',?,?)''',
                (teacher, '数学', '2027-04-01T16:00', '2027-04-01T17:00', uid, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (future, course))
            blocked = profiles.mark_left(c, owner, {'profile_id': profile, 'reason': '搬去新西兰'})
            self.assertTrue(blocked['blocked'])
            self.assertEqual(blocked['lessons'][0]['lesson_id'], future)
            self.assertEqual(c.execute('SELECT left_on FROM student_profiles WHERE id=?', (profile,)).fetchone()[0], '')
            with self.assertRaises(teaching.AccessError):
                profiles.mark_left(c, {'id': parent, 'role': 'parent'}, {'profile_id': profile})
            deletion.stop_course(c, owner, {'student_id': course})
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (future,)).fetchone()[0], 'cancelled')
            done = profiles.mark_left(c, owner, {'profile_id': profile, 'reason': '搬去新西兰'})
            self.assertTrue(done['ok'])
            kept = c.execute('SELECT left_on, left_reason, name FROM student_profiles WHERE id=?', (profile,)).fetchone()
            self.assertEqual(kept['name'], 'Lachlan')
            self.assertEqual(kept['left_reason'], '搬去新西兰')
            self.assertTrue(kept['left_on'])
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (course,)).fetchone()[0], 400)
            self.assertIsNotNone(c.execute('SELECT 1 FROM ledger WHERE student_id=?', (course,)).fetchone())
            audit = c.execute("SELECT id, summary FROM audit_log WHERE summary LIKE '不再上课%' ORDER BY id DESC").fetchone()
            self.assertIn('Lachlan', audit['summary'])
            self.assertIn('搬去新西兰', audit['summary'])
            auditlog.undo(c, owner, audit['id'])
            self.assertEqual(c.execute("SELECT left_on FROM student_profiles WHERE id=?", (profile,)).fetchone()[0], '')
            profiles.mark_left(c, owner, {'profile_id': profile})
            profiles.mark_returned(c, owner, {'profile_id': profile})
            back = c.execute('SELECT left_on, left_reason FROM student_profiles WHERE id=?', (profile,)).fetchone()
            self.assertEqual(tuple(back), ('', ''))
            self.assertEqual(c.execute('SELECT archived FROM students WHERE id=?', (course,)).fetchone()[0], 1)
            rows = [dict(row) for row in c.execute('SELECT * FROM students WHERE profile_id=?', (profile,))]
            shells = profiles.course_shells(c, rows)
            self.assertEqual(len(shells), 1)
            self.assertTrue(shells[0]['no_course'])
            self.assertEqual(shells[0]['name'], 'Lachlan')
            self.assertEqual(shells[0]['course'], '')


if __name__ == '__main__':
    unittest.main()
