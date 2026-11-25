"""Switching a pack moves its remaining value and does not count as income."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'switch.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import auditlog
import pricing
import server
import switches


class SwitchCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_twenty_plus_one_keeps_the_leftover_and_can_be_undone(self):
        with server.connect() as c:
            owner_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                ('0420000001', 'Helen', 'x')).lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner_id,))
            owner = {'id': owner_id, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                ('0420000002', '家长', 'x')).lastrowid
            tutor = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                ('0420000003', 'Angela', 'x')).lastrowid
            teacher = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?,?)", (tutor, '英语')).lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            maths = c.execute('SELECT id FROM subjects WHERE name=?', ('数学',)).fetchone()['id']
            kind = c.execute('SELECT id FROM course_types WHERE name=?', ('一对一',)).fetchone()['id']
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id,level_code,level_year,billing_unit)
                VALUES('Mia','数学',?,?,2100,?,?, 'Y5',2027,'lesson')''', (parent, profile, maths, kind)).lastrowid
            fees = [value * 10 for value in pricing.lesson_prices_cents(170000, 21)]
            batch = c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,pack_label,total_cents,unit_fees)
                VALUES(?,2000,100,2000,100,'2026-11-01','数学 20+1',170000,?)''', (sid, json.dumps(fees))).lastrowid
            c.commit()
            preview = switches.quote_switch(c, owner, {
                'batch_id': batch, 'subject': '英语', 'course_type_id': kind, 'level': 'Y5',
                'lesson_minutes': 60, 'teacher_id': teacher, 'manual_price': '90',
            })
            self.assertEqual(preview['new_lessons'], 18)
            self.assertEqual(preview['leftover_millis'], 80000)
            self.assertEqual(preview['remaining_value'], '$1,700.00')
            self.assertEqual(preview['leftover'], '$80.00')
            result = switches.apply_switch(c, owner, {
                'batch_id': batch, 'subject': '英语', 'course_type_id': kind, 'level': 'Y5',
                'lesson_minutes': 60, 'teacher_id': teacher, 'manual_price': '90',
            })
            c.commit()
            old = c.execute('SELECT * FROM credit_batches WHERE id=?', (batch,)).fetchone()
            self.assertEqual(old['status'], 'switched')
            self.assertEqual(old['paid_left'] + old['gift_left'], 0)
            self.assertEqual(old['switched_to'], result['new_batch_id'])
            new = c.execute('SELECT * FROM credit_batches WHERE id=?', (result['new_batch_id'],)).fetchone()
            self.assertEqual(new['switched_from'], batch)
            self.assertEqual(new['purchased'], 1800)
            self.assertEqual(new['paid_left'], 1800)
            self.assertEqual(new['leftover_millis'], 80000)
            self.assertNotEqual(new['student_id'], sid)
            self.assertEqual(c.execute('SELECT course FROM students WHERE id=?', (new['student_id'],)).fetchone()['course'], '英语')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM ledger WHERE kind='switch'").fetchone()[0], 2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM cash_entries').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 0)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (new['student_id'],)).fetchone()['balance'], 1800)
            auditlog.undo(c, owner, result['audit_id'])
            c.commit()
            restored = c.execute('SELECT paid_left, gift_left, status FROM credit_batches WHERE id=?', (batch,)).fetchone()
            self.assertEqual(restored['paid_left'], 2000)
            self.assertEqual(restored['gift_left'], 100)
            self.assertEqual(restored['status'], 'active')
            self.assertIsNone(c.execute('SELECT 1 FROM credit_batches WHERE id=?', (result['new_batch_id'],)).fetchone())


if __name__ == '__main__':
    unittest.main()
