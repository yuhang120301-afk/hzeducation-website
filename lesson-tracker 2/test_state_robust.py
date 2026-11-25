"""One bad course or teacher record must not take down GET /api/state."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'state-robust.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import pricing
import server


class StateRobustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_fractional_packs_and_a_bad_teacher_record_still_load(self):
        with server.connect() as c:
            owner = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('041' + uuid.uuid4().hex)[:15], 'Helen', 'x')).lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner,))
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (('041' + uuid.uuid4().hex)[:15], '家长', 'x')).lastrowid
            teacher_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('041' + uuid.uuid4().hex)[:15], 'Vincent', 'x')).lastrowid
            teacher = c.execute("INSERT INTO teachers(user_id,subject,subjects) VALUES(?,?,'')", (teacher_user, '数学')).lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Aaron')").lastrowid
            type_id = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            subject_id = c.execute("SELECT id FROM subjects WHERE name='新加坡数学'").fetchone()['id']
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id)
                VALUES('Aaron','新加坡数学',?,?,1400,?,?)''', (parent, profile, subject_id, type_id)).lastrowid
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,2100,'credit','2026-09-05','补录以前的包',?,?)''', (sid, owner, uuid.uuid4().hex)).lastrowid
            c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents,unit_fees,lesson_minutes)
                VALUES(?,?,2000,100,1300,100,'2026-09-05',240000,'','bad')''', (sid, lid))
            c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,240000,\'bank\',\'\',?)', (lid, owner))
            c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','completed',?,?)''',
                (teacher, '新加坡数学', 'not-a-date', 'also-bad', owner, uuid.uuid4().hex))
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)',
                (c.execute('SELECT id FROM lessons').fetchone()['id'], sid))
            c.commit()
            user = {'id': owner, 'role': 'owner', 'name': 'Helen', 'phone': 'x', 'teacher_id': None, 'csrf': 'tok'}
            payload = server.build_state(c, user)
            names = [person['name'] for person in payload['students']]
            self.assertIn('Aaron', names)
            aaron = next(person for person in payload['students'] if person['name'] == 'Aaron')
            self.assertEqual(aaron['paid_balance'], 1300)
            self.assertEqual(aaron['gift_balance'], 100)
            self.assertEqual(aaron['rate_label'], '$114.29/小时')
            self.assertEqual(payload['teachers'][0]['subjects'], ['数学'])
            rated = pricing.list_course_rates(c, include_left=True)
            self.assertTrue(any(row['student_name'] == 'Aaron' and row['hourly_label'] == '$114.29/小时' for row in rated))

    def _row(self, user_id, role, teacher_id=None):
        with server.connect() as c:
            return c.execute('SELECT id, name, phone, ? AS role, ? AS teacher_id, ? AS csrf FROM users WHERE id=?',
                (role, teacher_id, 'tok', user_id)).fetchone()

    def test_build_state_accepts_the_session_row_for_each_role(self):
        with server.connect() as c:
            owner_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('042' + uuid.uuid4().hex)[:15], 'Helen', 'x')).lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner_id,))
            parent_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (('042' + uuid.uuid4().hex)[:15], '家长', 'x')).lastrowid
            teacher_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('042' + uuid.uuid4().hex)[:15], 'Vincent', 'x')).lastrowid
            teacher_id = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?,?)", (teacher_user, '数学')).lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Row Child')").lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Row Child','数学',?,?,0)",
                (parent_id, profile)).lastrowid
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','scheduled',?,?)''',
                (teacher_id, '数学', '2026-11-20T10:00', '2026-11-20T11:00', owner_id, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (lesson, sid))
            c.commit()
        owner = self._row(owner_id, 'owner')
        teacher = self._row(teacher_user, 'teacher', teacher_id)
        parent = self._row(parent_id, 'parent')
        self.assertIsInstance(owner, sqlite3.Row)
        self.assertFalse(hasattr(owner, 'get'))
        with server.connect() as c:
            boss = server.build_state(c, owner)
            taught = server.build_state(c, teacher)
            family = server.build_state(c, parent)
        self.assertEqual(boss['user']['role'], 'owner')
        child = next(person for person in boss['students'] if person['id'] == sid)
        self.assertIn('rate_label', child)
        self.assertEqual(taught['user']['role'], 'teacher')
        self.assertTrue(all('rate_label' not in person for person in taught['students']))
        self.assertEqual(family['user']['role'], 'parent')
        self.assertTrue(all('rate_label' not in person for person in family['students']))
        self.assertTrue(any(person['id'] == sid for person in family['students']))


if __name__ == '__main__':
    unittest.main()
