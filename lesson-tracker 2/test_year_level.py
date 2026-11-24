"""2027 enrolment year is shown and priced as the calendar year of the date."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'years.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import pricing
import server


class YearLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0412000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            pricing.seed_2027(c)
            pricing.publish_seed(c)
            cls.owner = {'id': uid, 'role': 'owner'}
            cls.parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0412000002','家长','x','parent')").lastrowid
            cls.kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']

    def enrol(self, c, code, study=''):
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,level_code,level_year,course_type_id,study_level,billing_unit)
            VALUES(?,?,?,?,0,?,2026,?,?,'lesson')''',
            ('学生'+code+study, '数学', self.parent, profile, code, self.kind, study)).lastrowid
        return sid

    def hourly(self, sid, day):
        with server.connect() as c:
            offer = pricing.presets(c, self.owner, student_id=sid, day=day)
        return offer['level'], offer['hourly_cents'], offer['source']

    def test_display_moves_on_1_january_without_rewriting_the_stored_year(self):
        student = {'level_code': 'Y5', 'level_year': 2026, 'grade': 'Y5', 'study_level': ''}
        shown = pricing.annotate(dict(student), dt.date(2026, 12, 31))
        self.assertEqual(shown['level_label'], 'Year 4')
        self.assertEqual(shown['level_stored'], 'Y5')
        self.assertFalse(shown['level_past'])
        later = pricing.annotate(dict(student), dt.date(2027, 1, 1))
        self.assertEqual(later['level_label'], 'Year 5')
        further = pricing.annotate(dict(student), dt.date(2028, 1, 1))
        self.assertEqual(further['level_label'], 'Year 6')
        self.assertEqual(student['level_code'], 'Y5')
        self.assertEqual(student['level_year'], 2026)

    def test_prep_and_year_12_edges(self):
        prep = pricing.annotate({'level_code': 'Prep', 'grade': 'Prep'}, dt.date(2026, 6, 1))
        self.assertEqual(prep['level_label'], 'K')
        first = pricing.annotate({'level_code': 'Y1', 'grade': 'Y1'}, dt.date(2026, 6, 1))
        self.assertEqual(first['level_label'], 'Prep')
        top = pricing.annotate({'level_code': 'Y12', 'grade': 'Y12'}, dt.date(2028, 1, 1))
        self.assertEqual(top['level_price'], 'Y12')
        self.assertTrue(top['level_past'])
        self.assertIn('已毕业?', top['level_label'])

    def test_renewal_year_and_study_level_override(self):
        with server.connect() as c:
            plain = self.enrol(c, 'Y7')
            higher = self.enrol(c, 'Y7', 'Y9')
            lower = self.enrol(c, 'Y7', 'Y5')
            legacy = self.enrol(c, 'Y7')
            pricing.save_legacy_price(c, self.owner, {'student_id': legacy, 'hourly': '80'})
        self.assertEqual(self.hourly(plain, '2026-11-24'), ('Y6', 8500, 'table'))
        self.assertEqual(self.hourly(plain, '2027-02-01'), ('Y7', 9000, 'table'))
        self.assertEqual(self.hourly(higher, '2026-11-24'), ('Y9', 10000, 'table'))
        self.assertEqual(self.hourly(lower, '2026-11-24'), ('Y6', 8500, 'table'))
        self.assertEqual(self.hourly(lower, '2027-02-01'), ('Y7', 9000, 'table'))
        level, cents, source = self.hourly(legacy, '2027-02-01')
        self.assertEqual((level, cents, source), ('Y7', 8000, 'custom'))
