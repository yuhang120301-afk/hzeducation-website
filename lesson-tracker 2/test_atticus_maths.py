"""Atticus's 12 maths lessons move off the English enrolment without changing balances."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'atticus.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import atticus_maths
import payroll
import server

DATES = atticus_maths.DATES


class AtticusMathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def _person(self, name, course, grade='Year 5'):
        parent = self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            (f'04{uuid.uuid4().hex[:8]}', name + '家长', 'x')).lastrowid
        profile = self.c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        kind = self.c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
        subject = self.c.execute('SELECT id FROM subjects WHERE name=?', (course,)).fetchone()['id']
        sid = self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original,grade,subject_id,course_type_id)
            VALUES(?,?,?,?,0,1,?,?,?)''', (name, course, parent, profile, grade, subject, kind)).lastrowid
        return profile, sid

    def _pack(self, sid, purchased, gifted, paid_left, gift_left, cash=None, day='2026-09-25'):
        units = (purchased + gifted) * 100
        ledger = self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'credit',?,'购课',1,?)",
            (sid, units, day, uuid.uuid4().hex)).lastrowid
        batch = self.c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents,unit_fees)
            VALUES(?,?,?,?,?,?,? ,?,?)''',
            (sid, ledger, purchased * 100, gifted * 100, paid_left * 100, gift_left * 100, day,
             cash, '' if cash is None else json.dumps([cash * 10 // max(purchased + gifted, 1)] * (purchased + gifted)))).lastrowid
        if cash:
            self.c.execute(
                'INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,1)',
                (ledger, cash, 'bank', ''))
        return batch

    def _lesson(self, teacher, sid, batch, day):
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id,subject_id)
            VALUES(?,?,?,?,100,'教室','completed',1,?, (SELECT id FROM subjects WHERE name='数学'))''',
            (teacher, '数学', f'{day}T16:00', f'{day}T17:00', uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
        ledger = self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'上课',1,?)",
            (sid, -100, day, uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
            VALUES(?,?,100,'内容','作业','反馈',?,1)''', (lid, sid, ledger))
        self.c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)',
            (ledger, batch, -100, 0))
        return lid

    def _scene(self):
        helen_uid = self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES('0400000099','Helen','x','admin')").lastrowid
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (helen_uid,))
        helen = self.c.execute(
            'INSERT INTO teachers(user_id,subject) VALUES(?,?)', (helen_uid, '数学')).lastrowid
        profile, english = self._person('Atticus', '英语')
        maths = self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original,grade,subject_id,course_type_id)
            VALUES('Atticus','数学', (SELECT parent_id FROM students WHERE id=?), ?,0,1,'Year 5',
            (SELECT id FROM subjects WHERE name='数学'), (SELECT id FROM course_types WHERE name='一对一'))''',
            (english, profile)).lastrowid
        used = self._pack(english, 21, 2, 0, 0)
        kept = self._pack(english, 8, 0, 8, 0)
        priced = self._pack(english, 1, 0, 0, 0, cash=10000, day='2026-09-01')
        self.c.execute('UPDATE students SET balance=? WHERE id=?', (800, english))
        maths_pack = self._pack(maths, 9, 2, 9, 2, day='2026-11-25')
        self.c.execute('UPDATE students SET balance=? WHERE id=?', (1100, maths))
        for day in DATES:
            self._lesson(helen, english, used, day)
        self.c.execute('UPDATE credit_batches SET paid_left=0 WHERE id=?', (used,))
        return english, maths, used, kept, priced, maths_pack

    def test_moves_the_twelve_lessons_and_keeps_both_balances(self):
        english, maths, used, kept, priced, maths_pack = self._scene()
        atticus_maths.run(self.c, os.environ['LESSON_DB'])
        self.assertEqual(atticus_maths._left(self.c, english), (800, 0))
        self.assertEqual(atticus_maths._left(self.c, maths), (900, 200))
        self.assertEqual(self.c.execute('SELECT balance FROM students WHERE id=?', (english,)).fetchone()[0], 800)
        self.assertEqual(self.c.execute('SELECT balance FROM students WHERE id=?', (maths,)).fetchone()[0], 1100)
        reports = self.c.execute('''SELECT r.student_id, r.ledger_id FROM lesson_reports r
            JOIN lessons l ON l.id=r.lesson_id WHERE substr(l.starts_at,1,10) IN ({})'''.format(
            ','.join('?' for _ in DATES)), DATES).fetchall()
        self.assertEqual({row['student_id'] for row in reports}, {maths})
        for row in reports:
            fee, _, _ = payroll.fee_for_ledger(self.c, row['ledger_id'], 100)
            self.assertEqual(fee, atticus_maths.MATHS_FEE_CENTS)
        kept_maths = self.c.execute('SELECT paid_left, gift_left FROM credit_batches WHERE id=?', (maths_pack,)).fetchone()
        self.assertEqual((kept_maths['paid_left'], kept_maths['gift_left']), (900, 200))
        self.assertEqual(self.c.execute('SELECT paid_left FROM credit_batches WHERE id=?', (used,)).fetchone()[0], 0)
        kept_fees = self.c.execute('SELECT unit_fees, total_cents FROM credit_batches WHERE id=?', (kept,)).fetchone()
        self.assertNotEqual(kept_fees['unit_fees'] or '', '')
        self.assertEqual(self.c.execute('SELECT total_cents FROM credit_batches WHERE id=?', (priced,)).fetchone()[0], 10000)
        packs = self.c.execute('SELECT COUNT(*) FROM credit_batches WHERE student_id=?', (maths,)).fetchone()[0]
        atticus_maths.run(self.c, os.environ['LESSON_DB'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM credit_batches WHERE student_id=?', (maths,)).fetchone()[0], packs)
        self.assertEqual(atticus_maths._left(self.c, english), (800, 0))

    def test_two_students_named_atticus_are_left_alone(self):
        self._scene()
        self._person('Atticus', '科学', 'Year 6')
        english_before = self.c.execute("SELECT balance FROM students WHERE name='Atticus' AND course='英语'").fetchone()[0]
        atticus_maths.run(self.c, os.environ['LESSON_DB'])
        self.assertIsNone(self.c.execute('SELECT 1 FROM app_meta WHERE key=?', (atticus_maths.KEY,)).fetchone())
        self.assertEqual(self.c.execute("SELECT balance FROM students WHERE name='Atticus' AND course='英语'").fetchone()[0], english_before)


if __name__ == '__main__':
    unittest.main()
