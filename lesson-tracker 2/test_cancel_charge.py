"""Cancelling inside 48 hours does not charge unless Helen says so."""
import datetime as dt
import os
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'cancel.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server
import teaching


class CancelChargeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def lesson(self, c, owner, sid, when):
        teacher = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Kelsey', 'x', 'parent')",
            ('8' + uuid.uuid4().hex[:8],)).lastrowid
        tid = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?, '数学')", (teacher,)).lastrowid
        lid = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?, '数学', ?, ?, 100, '教室', 'scheduled', ?, ?)''',
            (tid, when, when[:11] + '17:00', owner['id'], uuid.uuid4().hex)).lastrowid
        c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
        return lid

    def test_late_cancel_asks_before_it_deducts(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0466000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0466000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Mia','数学',?,?,500)",
                (parent, profile)).lastrowid
            c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on)
                VALUES(?,500,0,500,0,'2026-11-01')''', (sid,))
            soon = (dt.datetime.now() + dt.timedelta(hours=20)).strftime('%Y-%m-%dT%H:%M')
            quiet = self.lesson(c, owner, sid, soon)
            row = c.execute('SELECT * FROM lessons WHERE id=?', (quiet,)).fetchone()
            teaching.cancel_lesson(c, owner, {'lesson_id': quiet, 'version': row['version']}, server.text_value)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 500)
            charged = self.lesson(c, owner, sid, soon)
            row = c.execute('SELECT * FROM lessons WHERE id=?', (charged,)).fetchone()
            teaching.cancel_lesson(c, owner, {'lesson_id': charged, 'version': row['version'], 'charge': True}, server.text_value)
            self.assertLess(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 500)
            self.assertIsNone(c.execute('SELECT 1 FROM lesson_reports WHERE lesson_id=?', (charged,)).fetchone())


if __name__ == '__main__':
    unittest.main()
