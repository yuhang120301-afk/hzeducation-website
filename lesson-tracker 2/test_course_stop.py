"""Stopping one course leaves the student's other courses alone."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'stop.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import deletion
import server
import teaching


class CourseStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_one_course_stops_and_a_blank_course_is_deleted(self):
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0410000001','Helen','x','admin')").lastrowid
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0410000002','家长','x','parent')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            math = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Atticus','数学',?,?,500)''',
                (parent, profile)).lastrowid
            english = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Atticus','英语',?,?,200)''',
                (parent, profile)).lastrowid
            blank = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Atticus','科学',?,?,0)''',
                (parent, profile)).lastrowid
            c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,200,'credit','2026-10-01','充值',?,?)",
                (english, uid, uuid.uuid4().hex))
            teacher = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0410000003','Kelsey','x','parent')").lastrowid
            tid = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher, '英语')).lastrowid
            past = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','completed',?,?)''', (tid, '英语', '2026-10-01T16:00', '2026-10-01T17:00', uid, uuid.uuid4().hex)).lastrowid
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','scheduled',?,?)''', (tid, '英语', '2027-03-01T16:00', '2027-03-01T17:00', uid, uuid.uuid4().hex)).lastrowid
            math_future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','scheduled',?,?)''', (tid, '数学', '2027-03-02T16:00', '2027-03-02T17:00', uid, uuid.uuid4().hex)).lastrowid
            shared = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','scheduled',?,?)''', (tid, '小班', '2027-03-03T16:00', '2027-03-03T17:00', uid, uuid.uuid4().hex)).lastrowid
            for lid, sid in ((past, english), (future, english), (math_future, math), (shared, english), (shared, math)):
                c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
            series = uuid.uuid4().hex
            c.execute('''INSERT INTO lesson_series(id,interval_days,endless,next_index,stop_index,template,created_by)
                VALUES(?,7,1,3,NULL,?,?)''', (series, json.dumps({'student_ids': [english], 'title': '英语'}), uid))
            c.execute('UPDATE lessons SET series_id=?, occurrence_index=2 WHERE id=?', (series, future))

            with self.assertRaises(teaching.AccessError):
                deletion.stop_course(c, {'id': parent, 'role': 'parent'}, {'student_id': english})
            stopped = deletion.stop_course(c, owner, {'student_id': english})
            self.assertTrue(stopped['archived'])
            self.assertFalse(stopped['deleted'])
            self.assertEqual(stopped['balance'], 200)
            self.assertEqual(c.execute('SELECT archived, balance FROM students WHERE id=?', (english,)).fetchone()['archived'], 1)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (english,)).fetchone()['balance'], 200)
            self.assertEqual(c.execute('SELECT archived FROM students WHERE id=?', (math,)).fetchone()['archived'], 0)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (math,)).fetchone()['balance'], 500)
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (past,)).fetchone()['status'], 'completed')
            self.assertEqual(c.execute('SELECT status, cancel_reason FROM lessons WHERE id=?', (future,)).fetchone()['status'], 'cancelled')
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (math_future,)).fetchone()['status'], 'scheduled')
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (shared,)).fetchone()['status'], 'scheduled')
            self.assertIsNone(c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=?', (shared, english)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=?', (shared, math)).fetchone())
            rule = c.execute('SELECT * FROM lesson_series WHERE id=?', (series,)).fetchone()
            self.assertEqual(rule['endless'], 0)
            self.assertNotIn(english, json.loads(rule['template'])['student_ids'])
            self.assertIsNotNone(c.execute('SELECT 1 FROM ledger WHERE student_id=?', (english,)).fetchone())

            removed = deletion.stop_course(c, owner, {'student_id': blank})
            self.assertTrue(removed['deleted'])
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id=?', (blank,)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id=?', (math,)).fetchone())

            deletion.restore(c, owner, {'id': english})
            self.assertEqual(c.execute('SELECT archived FROM students WHERE id=?', (english,)).fetchone()['archived'], 0)
            self.assertEqual(c.execute('SELECT archived FROM students WHERE id=?', (math,)).fetchone()['archived'], 0)


if __name__ == '__main__':
    unittest.main()
