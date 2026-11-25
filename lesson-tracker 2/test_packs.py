"""Package prices follow year level and course type. Subject does not change them."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'packs.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import credit_batches
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
            active = [row['name'] for row in c.execute('SELECT name FROM subjects WHERE active=1 ORDER BY sort_order, id')]
            hidden = c.execute("SELECT active FROM subjects WHERE name='物理'").fetchone()
            textbook = c.execute("SELECT active FROM schedule_options WHERE kind='course' AND name LIKE '%课本%'").fetchone()
            old_methods = c.execute("SELECT active FROM subjects WHERE name='中数'").fetchone()
            old_specialist = c.execute("SELECT active FROM subjects WHERE name='高数'").fetchone()
            courses = [row['name'] for row in c.execute("SELECT name FROM schedule_options WHERE kind='course' AND active=1")]
            self.assertEqual(active, ['数学', '英语', 'VCE 中数', 'VCE 低数', 'VCE 高数', '新加坡数学', '数学 + 英语'])
            self.assertEqual(hidden['active'], 0)
            self.assertEqual(old_methods['active'], 0)
            self.assertEqual(old_specialist['active'], 0)
            self.assertTrue(textbook is None or textbook['active'] == 0)
            for name in ('数学', '英语', 'VCE 中数', 'VCE 低数', 'VCE 高数', '新加坡数学', '数学 + 英语'):
                self.assertIn(name, courses)
            kept = {row['name']: row['active'] for row in c.execute("SELECT name, active FROM subjects WHERE name IN ('中数','高数','数学','英语')")}
            c.execute("DELETE FROM app_meta WHERE key='catalog_vce_maths_v1'")
            c.execute("UPDATE subjects SET active=0 WHERE name IN ('VCE 中数','VCE 低数','VCE 高数')")
            teaching.activate_vce_subjects(c)
            teaching.activate_vce_subjects(c)
            again = {row['name']: row['active'] for row in c.execute("SELECT name, active FROM subjects WHERE name IN ('中数','高数','数学','英语','VCE 中数','VCE 低数','VCE 高数')")}
            self.assertEqual({name: kept[name] for name in kept}, {name: again[name] for name in kept})
            for name in ('VCE 中数', 'VCE 低数', 'VCE 高数'):
                self.assertEqual(again[name], 1)
        self.assertEqual(teaching.canonical_subject('VCE 中数'), 'VCE 中数')
        self.assertEqual(teaching.canonical_subject('Math Methods'), 'VCE 中数')
        self.assertEqual(teaching.canonical_subject('Mathematical Methods'), 'VCE 中数')
        self.assertEqual(teaching.canonical_subject('General Mathematics'), 'VCE 低数')
        self.assertEqual(teaching.canonical_subject('Specialist Mathematics'), 'VCE 高数')
        self.assertEqual(teaching.canonical_subject('中数'), '中数')
        self.assertEqual(teaching.canonical_subject('高数'), '高数')
        self.assertEqual(teaching.canonical_subject('数学'), '数学')
        self.assertEqual(teaching.canonical_subject('maths'), '数学')
        self.assertNotEqual(teaching.canonical_subject('VCE 中数'), '数学')
        self.assertEqual(pricing.canonical_subject('VCE 中数'), 'VCE 中数')
        self.assertEqual(pricing.canonical_subject('VCE 低数'), 'VCE 低数')
        self.assertEqual(pricing.canonical_subject('VCE 高数'), 'VCE 高数')
        self.assertEqual(pricing.canonical_subject('Math Methods'), 'VCE 中数')
        self.assertEqual(pricing.canonical_subject('数学 一对一'), '数学')
        self.assertFalse(profiles.same_subject('VCE 中数', 'VCE 中数', '数学', '数学'))
        self.assertFalse(profiles.same_subject('Math Methods', '', '数学', '数学'))
        self.assertTrue(profiles.same_subject('VCE 中数', 'VCE 中数', 'Math Methods', ''))
        self.assertTrue(profiles.same_subject('数学 一对一', '数学', '数学', '数学'))
        self.assertFalse(profiles.same_subject('VCE 中数', 'VCE 中数', 'VCE 高数', 'VCE 高数'))

    def test_one_profile_holds_separate_vce_maths_packs(self):
        with server.connect() as c:
            owner_id = c.execute('SELECT user_id FROM organization_owners').fetchone()['user_id']
            owner = {'id': owner_id, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                ('0400' + uuid.uuid4().hex[:8], '家长', 'x')).lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            maths_subject = c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            maths = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id,level_code,level_year,billing_unit,grade)
                VALUES('Nora','数学',?,?,0,?,?,'Y11',2027,'lesson','Y11')''', (parent, profile, maths_subject, kind)).lastrowid

            def add(name):
                subject_id = c.execute('SELECT id FROM subjects WHERE name=? AND active=1', (name,)).fetchone()['id']
                return profiles.add_course(c, owner, {'student_id': maths, 'subject_id': subject_id, 'course_type_id': kind}, server.text_value)['student_id']

            methods = add('VCE 中数')
            specialist = add('VCE 高数')
            rows = c.execute('SELECT id, course, profile_id FROM students WHERE profile_id=? ORDER BY course', (profile,)).fetchall()
            self.assertEqual([row['course'] for row in rows], ['VCE 中数', 'VCE 高数', '数学'])
            self.assertEqual({row['profile_id'] for row in rows}, {profile})

            def pack(sid, label, units):
                c.execute('UPDATE students SET balance=? WHERE id=?', (units, sid))
                return c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,pack_label)
                    VALUES(?,?,0,?,0,'2026-11-01',?)''', (sid, units, units, label)).lastrowid

            packs = {
                maths: pack(maths, '数学 10', 1000),
                methods: pack(methods, 'VCE 中数 8', 800),
                specialist: pack(specialist, 'VCE 高数 6', 600),
            }
            before = {sid: dict(c.execute('SELECT paid_left, gift_left FROM credit_batches WHERE id=?', (bid,)).fetchone()) for sid, bid in packs.items()}
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,?,?,?,?,?,?)''', (methods, -100, 'lesson', '2026-11-20', '扣一节', owner_id, uuid.uuid4().hex)).lastrowid
            credit_batches.consume(c, lid, methods, 100)
            credit_batches.finish(c, lid)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (methods,)).fetchone()['balance'], 700)
            self.assertEqual(c.execute('SELECT paid_left, gift_left FROM credit_batches WHERE id=?', (packs[methods],)).fetchone()['paid_left'], 700)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (maths,)).fetchone()['balance'], before[maths]['paid_left'])
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (specialist,)).fetchone()['balance'], before[specialist]['paid_left'])
            for sid in (maths, specialist):
                left = c.execute('SELECT paid_left, gift_left FROM credit_batches WHERE id=?', (packs[sid],)).fetchone()
                self.assertEqual(left['paid_left'], before[sid]['paid_left'])
                self.assertEqual(left['gift_left'], before[sid]['gift_left'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM credit_movements WHERE batch_id=?', (packs[maths],)).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM credit_movements WHERE batch_id=?', (packs[specialist],)).fetchone()[0], 0)
            maths_row = c.execute('SELECT * FROM students WHERE id=?', (maths,)).fetchone()
            methods_row = c.execute('SELECT * FROM students WHERE id=?', (methods,)).fetchone()
            self.assertEqual(pricing.subject_of(c, maths_row), '数学')
            self.assertEqual(pricing.subject_of(c, methods_row), 'VCE 中数')
            maths_price = pricing.presets(c, owner, student_id=maths, day='2027-03-01')['packages'][0]['total_cents']
            methods_price = pricing.presets(c, owner, student_id=methods, day='2027-03-01')['packages'][0]['total_cents']
            self.assertEqual(maths_price, methods_price)
            with self.assertRaises(ValueError) as caught:
                add('VCE 中数')
            self.assertIn('已有关联课程', str(caught.exception))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('INSERT INTO students(name,course,parent_id,profile_id) VALUES(?,?,?,?)', ('Nora', 'VCE 中数', parent, profile))

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
