"""2027 packages follow the year level, and finance can use last month or a year."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'offers.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import accounting
import pricing
import server


class OfferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0400999000','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            pricing.seed_2027(c)
            pricing.publish_seed(c)

    def test_year_presets_match_the_2027_list(self):
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            kind = c.execute("SELECT id FROM course_types WHERE name='一对二'").fetchone()['id']
            offer = pricing.presets(c, owner, level='Y11', course_type_id=kind, day='2027-03-01')
        packs = {item['lesson_minutes']: item['total_cents'] for item in offer['packages']}
        self.assertEqual(offer['hourly_cents'], 9500)
        self.assertEqual(packs[60], 190000)
        self.assertEqual(packs[90], 285000)
        self.assertTrue(all(item['gift_lessons'] == 1 for item in offer['packages']))

    def test_small_class_two_terms_are_five_percent_off(self):
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            kind = c.execute("SELECT id FROM course_types WHERE name='小班课'").fetchone()['id']
            offer = pricing.presets(c, owner, level='Y6', course_type_id=kind, day='2027-03-01')
        named = {item['label'].split(' · ')[0]: item['total_cents'] for item in offer['packages']}
        self.assertEqual(named['T1'], 90000)
        self.assertEqual(named['T1+T2'], 192375)
        self.assertTrue(all(item['gift_lessons'] == 0 for item in offer['packages']))

    def test_a_different_hourly_price_marks_a_legacy_student(self):
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,level_code,level_year,course_type_id,billing_unit)
                VALUES('老学员','数学',1,?,0,'Y6',2026,?,'lesson')''', (profile, kind)).lastrowid
            def load():
                return c.execute('''SELECT s.*, ct.name course_type_name FROM students s
                    JOIN course_types ct ON ct.id=s.course_type_id WHERE s.id=?''', (sid,)).fetchone()
            self.assertFalse(pricing.legacy_price(c, load())['legacy'])
            pricing.save_legacy_price(c, owner, {'student_id': sid, 'hourly': '80'})
            info = pricing.legacy_price(c, load())
            self.assertTrue(info['legacy'])
            self.assertEqual(info['custom_hourly_cents'], 8000)
            offer = pricing.presets(c, owner, student_id=sid, day='2026-11-24')
            packs = {item['lesson_minutes']: item['total_cents'] for item in offer['packages']}
            self.assertEqual(offer['hourly_cents'], 8000)
            self.assertEqual(packs[60], 160000)
            pricing.save_legacy_price(c, owner, {'student_id': sid, 'hourly': ''})
            self.assertFalse(pricing.legacy_price(c, load())['legacy'])

    def test_year_code_is_recognised(self):
        self.assertEqual(pricing.parse_level('Y6'), 'Y6')
        self.assertEqual(pricing.parse_level('6年级'), 'Y6')
        self.assertEqual(pricing.remember_level({'grade': 'Y6'}, 'Y6', dt.date(2026, 11, 24)), ('Y6', 2026))

    def test_finance_presets_cover_last_month_and_this_year(self):
        start, end = accounting.bounds('last_month', '2026-03-15')
        self.assertEqual((start, end), (dt.date(2026, 2, 1), dt.date(2026, 2, 28)))
        start, end = accounting.bounds('year', '2026-11-24')
        self.assertEqual((start, end), (dt.date(2026, 1, 1), dt.date(2026, 12, 31)))


if __name__ == '__main__':
    unittest.main()
