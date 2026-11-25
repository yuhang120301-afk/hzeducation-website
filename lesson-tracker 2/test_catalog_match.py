"""Scheduling and 换课 follow the 设置 catalog, and the lesson must match the course."""
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'catalog-match.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import pricing
import server
import teaching


class CatalogMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def owner(self, c):
        uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Helen', 'x', 'admin')",
            ('0418' + uuid.uuid4().hex[:6],)).lastrowid
        c.execute('INSERT OR IGNORE INTO organization_owners(user_id) VALUES(?)', (uid,))
        return {'id': uid, 'role': 'owner'}

    def test_combo_subject_has_its_own_prep_price(self):
        with server.connect() as c:
            owner = self.owner(c)
            pricing.schema(c)
            row = c.execute("SELECT active FROM subjects WHERE name='数学加英语'").fetchone()
            self.assertEqual(row['active'], 1)
            kind = c.execute("SELECT id, product FROM course_types WHERE name='一对一'").fetchone()
            self.assertEqual(kind['product'], 'one_to_one')
            offer = pricing.presets(c, owner, level='Prep', course_type_id=kind['id'],
                subject_id=c.execute("SELECT id FROM subjects WHERE name='数学加英语'").fetchone()['id'],
                day='2027-03-01')
            self.assertEqual(offer['hourly_cents'], pricing.COMBO_HOURLY_CENTS)
            self.assertEqual(offer['reason'], '')
            self.assertEqual(offer['product'], pricing.COMBO_PRODUCT)
            other = pricing.presets(c, owner, level='Y4', course_type_id=kind['id'],
                subject_id=c.execute("SELECT id FROM subjects WHERE name='数学加英语'").fetchone()['id'],
                day='2027-03-01')
            self.assertEqual(other['reason'], '数学加英语的价格用在 Prep。')
            c.execute("INSERT INTO course_types(name, sort_order, active, product) VALUES('一对三', 80, 1, '')")
            new_id = c.execute("SELECT id FROM course_types WHERE name='一对三'").fetchone()['id']
            missing = pricing.presets(c, owner, level='Prep', course_type_id=new_id, day='2027-03-01')
            self.assertEqual(missing['reason'], '还没有价格')

    def test_lesson_subject_must_match_the_course(self):
        with server.connect() as c:
            owner = self.owner(c)
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, '家长', 'x', 'parent')",
                ('0419' + uuid.uuid4().hex[:6],)).lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            math = c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
            combo = c.execute("SELECT id FROM subjects WHERE name='数学加英语'").fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id)
                VALUES('Mia','数学加英语',?,?,0,?,?)''', (parent, profile, combo, kind)).lastrowid
            teacher_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Kelsey', 'x', 'parent')",
                ('0420' + uuid.uuid4().hex[:6],)).lastrowid
            tid = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher_user, '数学')).lastrowid
            payload = {
                'teacher_id': tid, 'student_ids': [sid], 'title': '数学 · 一对一',
                'subject_id': math, 'course_type_id': kind, 'starts_at': '2027-04-01T16:00',
                'ends_at': '2027-04-01T17:00', 'amount': '1', 'location': '', 'color': 'green',
                'request_id': uuid.uuid4().hex,
            }
            with self.assertRaises(ValueError) as caught:
                teaching.save_lesson(c, owner, payload, server.units, server.text_value)
            self.assertIn('科目和所选课程不一致', str(caught.exception))
            payload['subject_id'] = combo
            payload['title'] = '数学加英语 · 一对一'
            payload['request_id'] = uuid.uuid4().hex
            saved = teaching.save_lesson(c, owner, payload, server.units, server.text_value)
            stored = c.execute('SELECT subject_id FROM lessons WHERE id=?', (saved['lesson_id'],)).fetchone()
            self.assertEqual(stored['subject_id'], combo)

    def test_mismatch_report_is_read_only(self):
        script = Path(__file__).with_name('scripts') / 'report_lesson_course_mismatch.py'
        env = {**os.environ, 'LESSON_DB': str(DB)}
        report = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, check=True)
        self.assertIn('只读', report.stdout)
        self.assertIn('科目和课程不一致', report.stdout)


if __name__ == '__main__':
    unittest.main()
