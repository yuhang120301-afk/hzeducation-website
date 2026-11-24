"""Benjamin's maths course becomes 2027 一对一. Other courses are only archived."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'reset.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import profiles
import reset_2027_courses
import server
import teaching


class ResetCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_benjamin_moves_and_other_courses_stay_on_their_lessons(self):
        with server.connect() as c:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0430000001','家长','x','parent')").lastrowid
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0430000002','Helen','x','admin')").lastrowid
            teacher = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0430000003','Angela','x','parent')").lastrowid
            tid = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher, '数学')).lastrowid
            math = c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']

            def person(name, course, balance, subject=None, course_type=None):
                profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
                return c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id)
                    VALUES(?,?,?,?,?,?,?)''', (name, course, parent, profile, balance, subject, course_type)).lastrowid

            atticus = person('Atticus', '数学', 900, math, kind)
            benjamin = person('Benjamin', '数学 一对一', 500)
            other = person('Edward', '英语', 200)
            past = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'','completed',?,?)''', (tid, 'Edward 过去', '2026-10-01T16:00', '2026-10-01T17:00', uid, uuid.uuid4().hex)).lastrowid
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'','scheduled',?,?)''', (tid, 'Edward 以后', '2027-03-01T16:00', '2027-03-01T17:00', uid, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (past, other))
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (future, other))
            c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,500,'credit','2026-09-01','旧数学',?,?)",
                (benjamin, uid, uuid.uuid4().hex))
            ben_lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'','scheduled',?,?)''', (tid, 'Benjamin 数学', '2027-02-01T19:30', '2027-02-01T20:30', uid, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (ben_lesson, benjamin))
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,updated_by)
                VALUES(?,?,100,'内容','作业','反馈',?)''', (ben_lesson, benjamin, uid))

            preview = '\n'.join(reset_2027_courses.describe(c))
            self.assertIn('Benjamin', preview)
            self.assertIn('Edward', preview)
            self.assertIn('Atticus 保持原样', preview)
            reset_2027_courses.apply_changes(c)

            new_ben = c.execute('''SELECT s.id, s.balance, s.archived, ct.name type_name FROM students s
                JOIN course_types ct ON ct.id=s.course_type_id
                WHERE s.name='Benjamin' AND s.course='数学' AND s.archived=0''').fetchone()
            self.assertIsNotNone(new_ben)
            self.assertEqual(new_ben['type_name'], '一对一')
            self.assertEqual(new_ben['balance'], 500)
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (ben_lesson,)).fetchone()['student_id'], new_ben['id'])
            self.assertEqual(c.execute('SELECT student_id FROM lesson_reports WHERE lesson_id=?', (ben_lesson,)).fetchone()['student_id'], new_ben['id'])
            self.assertEqual(c.execute('SELECT archived, balance FROM students WHERE id=?', (benjamin,)).fetchone()['archived'], 1)
            self.assertEqual(c.execute('SELECT archived, balance FROM students WHERE id=?', (atticus,)).fetchone()['archived'], 0)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (atticus,)).fetchone()['balance'], 900)
            edward = c.execute('SELECT archived, balance FROM students WHERE id=?', (other,)).fetchone()
            self.assertEqual(edward['archived'], 1)
            self.assertEqual(edward['balance'], 200)
            self.assertEqual(c.execute('SELECT status, title FROM lessons WHERE id=?', (future,)).fetchone()['title'], 'Edward 以后')
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (future,)).fetchone()['student_id'], other)

            english = c.execute("SELECT id FROM subjects WHERE name='英语'").fetchone()['id']
            old_profile = c.execute('SELECT profile_id FROM students WHERE id=?', (other,)).fetchone()['profile_id']
            fresh = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id)
                VALUES('Edward','英语',?,?,0,?,?)''', (parent, old_profile, english, kind)).lastrowid
            moved = profiles.relink_future_lessons(c, fresh)
            self.assertEqual(moved, 1)
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (future,)).fetchone()['student_id'], fresh)
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (past,)).fetchone()['student_id'], other)
            self.assertEqual(c.execute('SELECT title FROM lessons WHERE id=?', (future,)).fetchone()['title'], 'Edward 以后')


if __name__ == '__main__':
    unittest.main()
