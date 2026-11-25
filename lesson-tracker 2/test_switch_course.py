"""Switching a pack moves its remaining value and does not count as income."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))
import repair_archived_series as repair

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'switch.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import auditlog
import deletion
import pricing
import server
import switches
import teaching


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
            self.assertEqual(c.execute("SELECT COUNT(*) FROM ledger WHERE kind='switch' AND student_id IN (?,?)", (sid, new['student_id'])).fetchone()[0], 2)
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

    def test_amelia_reuses_maths_plus_english_and_moves_the_series_on_row_57(self):
        self.assertTrue(pricing.level_is_primary('Y7', dt.date(2026, 11, 25)))
        self.assertFalse(pricing.level_is_primary('Y8', dt.date(2026, 11, 25)))
        with server.connect() as c:
            owner_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                ('0420000011', 'Helen', 'x')).lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner_id,))
            pricing.schema(c)
            owner = {'id': owner_id, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                ('0420000012', 'Amelia家长', 'x')).lastrowid
            tutor = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                ('0420000013', 'Kelsey', 'x')).lastrowid
            teacher = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?,?)", (tutor, '数学')).lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            combo = c.execute("SELECT id FROM subjects WHERE name='数学 + 英语'").fetchone()['id']
            maths = c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
            small = c.execute("SELECT id FROM course_types WHERE name='小班课'").fetchone()['id']
            live = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id,level_code,level_year,billing_unit)
                VALUES('Amelia','数学 + 英语',?,?,0,?,?, 'Y5',2027,'lesson')''', (parent, profile, combo, small)).lastrowid
            mistaken = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id,level_code,level_year,billing_unit)
                VALUES('Amelia','数学',?,?,400,?,?, 'Y5',2027,'lesson')''', (parent, profile, maths, small)).lastrowid
            c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,400,'credit','2026-11-01','加错了的充值',?,?)''', (mistaken, owner_id, uuid.uuid4().hex))
            fees = json.dumps([112500])
            batch = c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,pack_label,total_cents,unit_fees)
                VALUES(?,400,0,400,0,'2026-11-01','数学 加错了',4500,?)''', (mistaken, fees)).lastrowid
            c.execute('''INSERT INTO students(id,name,course,parent_id,profile_id,balance,subject_id,course_type_id,level_code,level_year,billing_unit,archived)
                VALUES(57,'Amelia','数学 + 英语',?,?,0,?,?, 'Y5',2027,'lesson',1)''', (parent, profile, combo, small))
            series = uuid.uuid4().hex
            c.execute('''INSERT INTO lesson_series(id,interval_days,endless,next_index,template,created_by)
                VALUES(?,7,1,2,?,?)''', (series, json.dumps({'student_ids': [57], 'title': 'Amelia 2027'}), owner_id))
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,series_id,occurrence_index)
                VALUES(?,?,?,?,100,'教室',?,?,?,1)''', (teacher, '数学 + 英语', '2027-03-02T16:00', '2027-03-02T18:30', owner_id, uuid.uuid4().hex, series)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,57)', (lesson,))
            with self.assertRaises(ValueError) as blocked:
                deletion.remove_course(c, owner, {'student_id': mistaken})
            self.assertIn('请先作废这门课的充值单据', str(blocked.exception))
            dry = repair.plan(c)
            self.assertTrue(any(item['student_id'] == 57 and item['active_ids'] == [live] for item in dry))
            result = switches.apply_switch(c, owner, {
                'batch_id': batch, 'subject': '数学加英语', 'course_type_id': small, 'level': 'Y7',
                'lesson_minutes': 150, 'teacher_id': teacher,
            })
            c.commit()
            self.assertEqual(result['target_student_id'], live)
            self.assertEqual(c.execute("SELECT COUNT(*) n FROM students WHERE profile_id=? AND course='数学 + 英语' AND archived=0", (profile,)).fetchone()['n'], 1)
            template = json.loads(c.execute('SELECT template FROM lesson_series WHERE id=?', (series,)).fetchone()['template'])
            self.assertEqual(template['student_ids'], [live])
            self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (lesson,)).fetchone()['student_id'], live)
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (lesson,)).fetchone()['status'], 'scheduled')
            self.assertEqual(teaching.canonical_subject('数学/英语'), '数学 + 英语')


if __name__ == '__main__':
    unittest.main()
