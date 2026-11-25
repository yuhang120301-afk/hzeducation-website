"""Re-adding a stopped course works, and future lessons follow it."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'relink.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import profiles
import server


class RelinkCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_readd_moves_future_lessons_and_the_series(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0444000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0444000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            subject = c.execute("SELECT id FROM subjects WHERE name='英语' AND active=1").fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,archived,subject_id,course_type_id)
                VALUES('Amy','英语',?,?,0,1,?,?)''', (parent, profile, subject, kind)).lastrowid
            holder = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id)
                VALUES('Amy','数学',?,?,0,?,?)''', (parent, profile, c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id'], kind)).lastrowid
            teacher = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Kelsey', 'x', 'parent')",
                ('8' + uuid.uuid4().hex[:8],)).lastrowid
            tid = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?, '英语')", (teacher,)).lastrowid
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '英语','2027-08-01T16:00','2027-08-01T17:00',100,'教室','scheduled',?,?)''',
                (tid, uid, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (future, sid))
            series = uuid.uuid4().hex
            c.execute('''INSERT INTO lesson_series(id,interval_days,endless,next_index,template,created_by)
                VALUES(?,7,1,2,?,?)''', (series, json.dumps({'student_ids': [sid], 'title': '英语'}), uid))
            added = profiles.add_course(c, owner, {'student_id': holder, 'subject_id': subject, 'course_type_id': kind}, server.text_value)
            self.assertEqual(added['student_id'], sid)
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (future,)).fetchone()['student_id'], sid)
            self.assertEqual(c.execute('SELECT archived, voided FROM students WHERE id=?', (sid,)).fetchone()['archived'], 0)
            template = json.loads(c.execute('SELECT template FROM lesson_series WHERE id=?', (series,)).fetchone()['template'])
            self.assertIn(sid, template['student_ids'])
            other = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2027-08-02T16:00','2027-08-02T17:00',100,'教室','scheduled',?,?)''',
                (tid, uid, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (other, holder))
            self.assertEqual(profiles.move_future_lessons(c, holder, sid), 1)
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (other,)).fetchone()['student_id'], sid)
            with self.assertRaises(ValueError):
                profiles.add_course(c, owner, {'student_id': holder, 'subject_id': subject, 'course_type_id': kind}, server.text_value)
        env = {**os.environ, 'LESSON_DB': str(DB)}
        script = Path(__file__).with_name('scripts') / 'relink_course_lessons.py'
        dry = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, check=True)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)


if __name__ == '__main__':
    unittest.main()
