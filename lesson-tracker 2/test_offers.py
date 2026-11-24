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
        named = {tuple(item['terms']): item['total_cents'] for item in offer['packages']}
        self.assertEqual(named[('T1',)], 90000)
        self.assertEqual(named[('T1', 'T2')], 192375)
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

    def test_b_each_subject_keeps_its_own_legacy_price(self):
        import payroll
        owner = {'id': 1, 'role': 'owner'}
        with server.connect() as c:
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            math = c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
            english = c.execute("SELECT id FROM subjects WHERE name='英语'").fetchone()['id']
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            actor = c.execute('SELECT user_id FROM organization_owners LIMIT 1').fetchone()['user_id']

            def add(name, subject_id):
                return c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,level_code,level_year,course_type_id,subject_id,billing_unit)
                    VALUES(?,?,1,?,0,'Y6',2026,?,?,'lesson')''', (name, name, profile, kind, subject_id)).lastrowid

            math_id, english_id = add('数学生', math), add('英语生', english)

            def info(sid):
                row = c.execute('''SELECT s.*, ct.name course_type_name, sb.name subject_name FROM students s
                    JOIN course_types ct ON ct.id=s.course_type_id
                    JOIN subjects sb ON sb.id=s.subject_id WHERE s.id=?''', (sid,)).fetchone()
                return pricing.legacy_price(c, row)

            c.execute('DELETE FROM app_meta WHERE key=?', (pricing.SUBJECT_PRICE_KEY,))
            c.execute('''INSERT INTO student_prices(profile_id,product,lesson_minutes,per_lesson_cents,note,updated_by)
                VALUES(?,?,?,?,?,?)''', (profile, 'one_to_one', 60, 8000, '老学员', actor))
            c.execute('''INSERT INTO student_prices(profile_id,product,lesson_minutes,per_lesson_cents,note,updated_by)
                VALUES(?,?,?,?,?,?)''', (profile, 'one_to_one', 90, 12000, '老学员', actor))
            pricing.ensure_subject_prices(c)
            pricing.ensure_subject_prices(c)
            self.assertEqual(info(math_id)['custom_hourly_cents'], 8000)
            self.assertEqual(info(english_id)['custom_hourly_cents'], 8000)
            self.assertEqual(info(math_id)['legacy_subjects'], ['数学', '英语'])
            copied = c.execute('SELECT COUNT(*) FROM student_subject_prices WHERE profile_id=? AND per_lesson_cents=8000', (profile,)).fetchone()[0]
            self.assertEqual(copied, 2)

            pricing.save_legacy_price(c, owner, {'student_id': english_id, 'hourly': '70'})
            self.assertEqual(info(math_id)['custom_hourly_cents'], 8000)
            self.assertEqual(info(english_id)['custom_hourly_cents'], 7000)
            self.assertEqual(info(math_id)['legacy_subjects'], ['数学', '英语'])
            lesson = {'starts_at': '2026-11-24T16:00', 'ends_at': '2026-11-24T17:00'}
            math_fee = pricing.charged_fee_cents(c, math_id, lesson, 100)
            english_fee = pricing.charged_fee_cents(c, english_id, lesson, 100)
            self.assertEqual(math_fee, 8000)
            self.assertEqual(english_fee, 7000)
            math_quote = pricing.quote(c, owner, math_id, 'one_to_one', 60, 20, '2026-11-24')
            english_quote = pricing.quote(c, owner, english_id, 'one_to_one', 60, 20, '2026-11-24')
            self.assertEqual(math_quote['total_cents'], 160000)
            self.assertEqual(english_quote['total_cents'], 140000)
            self.assertEqual(math_quote['source'], 'custom')

            pricing.save_legacy_price(c, owner, {'student_id': english_id, 'hourly': ''})
            self.assertFalse(info(english_id)['legacy'])
            self.assertEqual(info(english_id)['legacy_subjects'], ['数学'])
            self.assertEqual(pricing.charged_fee_cents(c, english_id, lesson, 100), 8500)
            self.assertEqual(pricing.quote(c, owner, english_id, 'one_to_one', 60, 20, '2026-11-24')['total_cents'], 170000)
            self.assertEqual(pricing.list_lesson_cents(c, math_id, '2026-11-24', 'one_to_one', 60), 8000)
            self.assertEqual(pricing.list_lesson_cents(c, english_id, '2026-11-24', 'one_to_one', 60), 8500)

            rule = {'id': 1, 'teacher_id': 1, 'rule_type': 'percent', 'percent_bp': 4000,
                'hourly_floor_cents': None, 'hourly_rate_cents': None, 'effective_from': '2000-01-01', 'note': ''}

            def line(fee, subject):
                return {'lesson_id': 1, 'teacher_id': 1, 'teacher_name': 'Kelsey', 'title': subject,
                    'starts_at': '2026-11-24T16:00', 'ends_at': '2026-11-24T17:30',
                    'course_type_name': '小班课', 'subject_name': subject, 'student_id': 1, 'amount': 100,
                    'ledger_id': 0, 'fee_cents': fee, 'fee_millis': fee * 10, 'fee_overridden': 0,
                    'student_name': '学生', 'course': subject, 'billing_unit': 'lesson', 'profile_id': profile,
                    'helen_original': 0}

            paid = payroll.build_lessons(c, [line(math_fee, '数学'), line(8500, '英语')], {1: [rule]})
            self.assertEqual(paid[0]['pay_cents'], 3200 + 3400)

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
