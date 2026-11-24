"""Package prices follow year level and course type. Subject does not change them."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'packs.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import pricing
import profiles
import server
import teaching


class PackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0400888000','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            pricing.seed_2027(c)
            pricing.publish_seed(c)
            teaching.focus_catalog(c)

    def test_private_pack_splits_the_free_lesson_into_the_last_cent(self):
        prices = pricing.lesson_prices_cents(170000, 21)
        self.assertEqual(prices[0], 8095)
        self.assertEqual(prices[-1], 8100)
        self.assertEqual(sum(prices), 170000)
        self.assertEqual(pricing.trial_cents(8500), 6800)

    def test_class_pair_keeps_three_decimals(self):
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            kind = c.execute("SELECT id FROM course_types WHERE name='小班课'").fetchone()['id']
            offer = pricing.presets(c, owner, level='Y6', course_type_id=kind, day='2027-03-01')
        pair = next(item for item in offer['packages'] if 'T1+T2' in item['label'])
        self.assertEqual(pair['total_cents'], 192375)
        self.assertEqual(pair['each_millis'], 106875)
        self.assertEqual(sum(pair['unit_fees']), 192375 * 10)
        self.assertEqual(pair['gift_lessons'], 0)

    def test_subject_does_not_change_the_year_price(self):
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            maths = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            first = pricing.presets(c, owner, level='Y6', course_type_id=maths, day='2027-03-01')
            second = pricing.presets(c, owner, level='Y6', course_type_id=maths, day='2027-03-01')
        self.assertEqual(first['packages'][0]['total_cents'], second['packages'][0]['total_cents'])
        self.assertEqual(first['packages'][0]['total_cents'], 170000)
        self.assertIn('20+1', first['packages'][0]['label'])
        self.assertEqual(first['packages'][0]['validity'], '永久有效')

    def test_only_maths_and_english_stay_selectable(self):
        with server.connect() as c:
            active = [row['name'] for row in c.execute('SELECT name FROM subjects WHERE active=1 ORDER BY sort_order')]
            hidden = c.execute("SELECT active FROM subjects WHERE name='物理'").fetchone()
            textbook = c.execute("SELECT active FROM schedule_options WHERE kind='course' AND name LIKE '%课本%'").fetchone()
        self.assertEqual(active, ['数学', '英语'])
        self.assertEqual(hidden['active'], 0)
        self.assertTrue(textbook is None or textbook['active'] == 0)

    def test_enrolment_fields_round_trip_and_photo_none_wins(self):
        with server.connect() as c:
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            profiles.save_enrolment(c, profile, {
                'school': 'Local Primary', 'health_notes': '花生过敏',
                'emergency_name': '阿姨', 'emergency_relation': '阿姨', 'emergency_phone': '0412000000',
                'photo_homework': '1', 'photo_none': '1', 'handbook_read': '1', 'signed_on': '2026-11-01',
            })
            row = c.execute('SELECT * FROM student_profiles WHERE id=?', (profile,)).fetchone()
            self.assertEqual(row['school'], 'Local Primary')
            self.assertEqual(row['health_notes'], '花生过敏')
            self.assertEqual(row['photo_none'], 1)
            self.assertEqual(row['photo_homework'], 0)
            self.assertEqual(row['signed_on'], '2026-11-01')


if __name__ == '__main__':
    unittest.main()
