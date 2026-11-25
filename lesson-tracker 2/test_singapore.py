"""新加坡数学 keeps its own price, a 20-lesson pack, and a per-enrolment hourly rate."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'singapore.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import payroll
import pricing
import profiles
import server
import teaching

SCRIPT = Path(__file__).resolve().parent / 'scripts' / 'seed_singapore_enrolments.py'
sys.path.insert(0, str(SCRIPT.parent))
import seed_singapore_enrolments as seed


class SingaporeMathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0400777001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            c.execute("INSERT INTO teachers(user_id,subject,subjects) VALUES(?,?,'[\"数学\"]')", (uid, '数学'))
            pricing.seed_2027(c)
            pricing.publish_seed(c)

    def test_subject_exists_after_startup_and_a_second_startup_changes_nothing_else(self):
        def snap():
            with server.connect() as c:
                subjects = [tuple(row) for row in c.execute(
                    'SELECT id, name, active, sort_order FROM subjects ORDER BY id')]
                prices = [tuple(row) for row in c.execute(
                    'SELECT id, product, level_from, level_to, hourly_cents FROM price_rows ORDER BY id')]
                students = c.execute('SELECT COUNT(*) n FROM students').fetchone()['n']
                meta = c.execute("SELECT value FROM app_meta WHERE key='catalog_singapore_maths_v1'").fetchone()
                hidden = c.execute("SELECT active FROM subjects WHERE name='中数'").fetchone()['active']
                count = c.execute("SELECT COUNT(*) n FROM subjects WHERE name='新加坡数学'").fetchone()['n']
                active = c.execute("SELECT active FROM subjects WHERE name='新加坡数学'").fetchone()['active']
                return subjects, prices, students, meta['value'] if meta else None, hidden, count, active
        before = snap()
        self.assertEqual(before[3], '1')
        self.assertEqual(before[4], 0)
        self.assertEqual(before[5], 1)
        self.assertEqual(before[6], 1)
        self.assertEqual(teaching.canonical_subject('新加坡数学'), '新加坡数学')
        self.assertEqual(teaching.canonical_subject('Singapore Maths'), '新加坡数学')
        self.assertEqual(pricing.canonical_subject('新加坡数学 一对一'), '新加坡数学')
        self.assertNotEqual(pricing.canonical_subject('新加坡数学'), '数学')
        self.assertFalse(profiles.same_subject('新加坡数学', '新加坡数学', '数学', '数学'))
        self.assertTrue(profiles.same_subject('Singapore Maths', '', '新加坡数学', '新加坡数学'))
        server.initialize()
        with server.connect() as c:
            teaching.ensure_catalogs(c)
            teaching.activate_singapore_maths(c)
        self.assertEqual(snap(), before)

    def _student(self, c, name, subject, kind, level, hourly=None, original=0):
        parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            ('049' + uuid.uuid4().hex[:8], name + '家长', 'x')).lastrowid
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        subject_id = c.execute('SELECT id FROM subjects WHERE name=?', (subject,)).fetchone()['id']
        type_id = c.execute('SELECT id FROM course_types WHERE name=?', (kind,)).fetchone()['id']
        sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id,
            level_code,level_year,billing_unit,grade,helen_original,custom_hourly_cents)
            VALUES(?,?,?,?,0,?,?,?,2027,'lesson',?,?,?)''',
            (name, subject, parent, profile, subject_id, type_id, level, level, original, hourly)).lastrowid
        return sid

    def test_custom_hourly_rate_is_used_including_zero_and_not_the_other_price_table(self):
        owner = {'id': 1, 'role': 'owner'}
        lesson = {'starts_at': '2026-11-24T16:00', 'ends_at': '2026-11-24T17:00'}
        with server.connect() as c:
            c.execute('BEGIN')
            free = self._student(c, '免费生', '新加坡数学', '一对一', 'Y8', hourly=0)
            custom = self._student(c, '自定价', '新加坡数学', '一对一', 'Y9', hourly=8500)
            newer = self._student(c, '新生', '新加坡数学', '一对一', 'Y7', hourly=None, original=0)
            older = self._student(c, '老生', '新加坡数学', '小班课', 'Y10', hourly=None, original=1)
            maths = self._student(c, '数学生', '数学', '一对一', 'Y8', hourly=None)
            price_rows = c.execute('SELECT COUNT(*) n FROM price_rows').fetchone()['n']
            self.assertEqual(pricing.charged_fee_cents(c, free, lesson, 100), 0)
            self.assertEqual(pricing.charged_fee_cents(c, custom, lesson, 100), 8500)
            self.assertEqual(pricing.charged_fee_cents(c, newer, lesson, 100), 15000)
            self.assertEqual(pricing.charged_fee_cents(c, older, lesson, 100), 12000)
            self.assertEqual(pricing.charged_fee_cents(c, maths, lesson, 100), 9000)
            self.assertEqual(c.execute('SELECT COUNT(*) n FROM price_rows').fetchone()['n'], price_rows)
            free_offer = pricing.presets(c, owner, student_id=free, day='2026-11-24')
            self.assertEqual(free_offer['hourly_cents'], 0)
            self.assertEqual(free_offer['source'], 'custom')
            self.assertTrue(free_offer['packages'])
            self.assertTrue(all(item['paid_lessons'] == 20 and item['gift_lessons'] == 0 for item in free_offer['packages']))
            self.assertEqual(free_offer['packages'][0]['total_cents'], 0)
            self.assertNotIn('20+1', free_offer['packages'][0]['label'])
            new_offer = pricing.presets(c, owner, student_id=newer, day='2026-11-24')
            self.assertEqual(new_offer['hourly_cents'], 15000)
            self.assertEqual(new_offer['source'], 'catalog')
            self.assertEqual(new_offer['packages'][0]['total_cents'], 15000 * 20)
            self.assertEqual(new_offer['packages'][0]['gift_lessons'], 0)
            old_offer = pricing.presets(c, owner, student_id=older, day='2026-11-24')
            self.assertEqual(old_offer['hourly_cents'], 12000)
            self.assertTrue(all(item['gift_lessons'] == 0 and item['paid_lessons'] == 20 and not item['terms'] for item in old_offer['packages']))
            maths_offer = pricing.presets(c, owner, student_id=maths, day='2026-11-24')
            self.assertEqual(maths_offer['hourly_cents'], 9000)
            self.assertEqual(maths_offer['packages'][0]['gift_lessons'], 1)
            self.assertIn('20+1', maths_offer['packages'][0]['label'])
            subject_id = c.execute("SELECT id FROM subjects WHERE name='新加坡数学'").fetchone()['id']
            kind_id = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            preview = pricing.presets(c, owner, level='Y8', course_type_id=kind_id, subject_id=subject_id, day='2026-11-24')
            self.assertEqual(preview['hourly_cents'], 15000)
            self.assertEqual(preview['packages'][0]['gift_lessons'], 0)
            too_young = pricing.presets(c, owner, level='Y6', course_type_id=kind_id, subject_id=subject_id, day='2026-11-24')
            self.assertEqual(too_young['packages'], [])
            self.assertIn('Year 7', too_young['reason'])
            quoted = pricing.quote(c, owner, free, 'one_to_one', 60, 20, '2026-11-24')
            self.assertEqual(quoted['gift_lessons'], 0)
            self.assertEqual(quoted['paid_lessons'], 20)
            self.assertEqual(quoted['total_cents'], 0)
            self.assertEqual(quoted['source'], 'custom')
            pricing.save_legacy_price(c, owner, {'student_id': newer, 'hourly': '0'})
            self.assertEqual(c.execute('SELECT custom_hourly_cents FROM students WHERE id=?', (newer,)).fetchone()[0], 0)
            self.assertEqual(pricing.charged_fee_cents(c, newer, lesson, 100), 0)
            self.assertEqual(c.execute('SELECT COUNT(*) n FROM price_rows').fetchone()['n'], price_rows)
            c.rollback()

    def test_boss_small_class_pay_follows_her_own_rule(self):
        with server.connect() as c:
            c.execute('BEGIN')
            helen = c.execute('SELECT t.id FROM teachers t JOIN organization_owners o ON o.user_id=t.user_id').fetchone()['id']
            tutor_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                ('049' + uuid.uuid4().hex[:8], 'Angela', 'x')).lastrowid
            tutor = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (tutor_user, '数学')).lastrowid
            c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,created_by)
                VALUES(?,'percent',0,NULL,NULL,'2000-01-01',1)''', (helen,))
            c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,created_by)
                VALUES(?,'percent',4000,NULL,NULL,'2000-01-01',1)''', (tutor,))
            sid = self._student(c, '小班生', '新加坡数学', '小班课', 'Y8', hourly=10000)
            subject_id = c.execute("SELECT id FROM subjects WHERE name='新加坡数学'").fetchone()['id']
            small = c.execute("SELECT id FROM course_types WHERE name='小班课'").fetchone()['id']
            day = '2030-03-04'

            def lesson(teacher):
                lid = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id,course_type_id,subject_id)
                    VALUES(?,?,?,?,100,'教室','completed',1,?,?,?)''',
                    (teacher, '新加坡数学', f'{day}T16:00', f'{day}T17:00', uuid.uuid4().hex, small, subject_id)).lastrowid
                c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
                ledger = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'上课',1,?)",
                    (sid, -100, day, uuid.uuid4().hex)).lastrowid
                c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by,fee_cents,fee_millis)
                    VALUES(?,?,100,'内容','作业','反馈',?,1,10000,100000)''', (lid, sid, ledger))
                return lid

            helen_lesson = lesson(helen)
            tutor_lesson = lesson(tutor)
            report = payroll.report(c, {'id': 1, 'role': 'owner'}, 'custom', None, day, day)
            by_lesson = {item['lesson_id']: item for teacher in report['teachers'] for item in teacher['lessons']}
            self.assertEqual(by_lesson[helen_lesson]['pay_cents'], 0)
            self.assertEqual(by_lesson[helen_lesson]['fee_cents'], 10000)
            self.assertEqual(by_lesson[tutor_lesson]['pay_cents'], 4000)
            c.rollback()

    def test_only_helen_can_teach_it_and_the_year_is_limited(self):
        with server.connect() as c:
            c.execute('BEGIN')
            owner_id = c.execute('SELECT user_id FROM organization_owners').fetchone()['user_id']
            helen = c.execute('SELECT id FROM teachers WHERE user_id=?', (owner_id,)).fetchone()['id']
            tutor_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                ('049' + uuid.uuid4().hex[:8], '其他老师', 'x')).lastrowid
            tutor = c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (tutor_user, '数学')).lastrowid
            sid = self._student(c, '七年级', '新加坡数学', '一对一', 'Y8')
            subject_id = c.execute("SELECT id FROM subjects WHERE name='新加坡数学'").fetchone()['id']
            one = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            two = c.execute("SELECT id FROM course_types WHERE name='一对二'").fetchone()['id']
            user = {'id': owner_id, 'role': 'owner'}
            base = {'title': '新加坡数学 · 一对一', 'starts_at': '2026-11-26T16:00', 'ends_at': '2026-11-26T17:00',
                'amount': '1', 'student_ids': [sid], 'subject_id': subject_id, 'location': '', 'color': 'green'}
            with self.assertRaises(ValueError) as caught:
                teaching.save_lesson(c, user, {**base, 'teacher_id': tutor, 'course_type_id': one, 'request_id': uuid.uuid4().hex}, server.units, server.text_value)
            self.assertIn('勾选新加坡数学', str(caught.exception))
            c.execute('UPDATE teachers SET subjects=? WHERE id=?', ('["数学","新加坡数学"]', tutor))
            ticked = teaching.save_lesson(c, user, {**base, 'teacher_id': tutor, 'course_type_id': one, 'request_id': uuid.uuid4().hex}, server.units, server.text_value)
            self.assertEqual(c.execute('SELECT teacher_id FROM lessons WHERE id=?', (ticked['lesson_id'],)).fetchone()['teacher_id'], tutor)
            c.execute("UPDATE lessons SET status='cancelled' WHERE id=?", (ticked['lesson_id'],))
            with self.assertRaises(ValueError) as caught:
                teaching.save_lesson(c, user, {**base, 'teacher_id': helen, 'course_type_id': two, 'request_id': uuid.uuid4().hex}, server.units, server.text_value)
            self.assertIn('一对一', str(caught.exception))
            saved = teaching.save_lesson(c, user, {**base, 'teacher_id': helen, 'course_type_id': one, 'request_id': uuid.uuid4().hex}, server.units, server.text_value)
            self.assertTrue(saved['lesson_id'])
            with self.assertRaises(ValueError):
                profiles.add_course(c, user, {'student_id': sid, 'subject_id': subject_id, 'course_type_id': one}, server.text_value)
            young = self._student(c, '六年级', '数学', '一对一', 'Y6')
            with self.assertRaises(ValueError) as caught:
                profiles.add_course(c, user, {'student_id': young, 'subject_id': subject_id, 'course_type_id': one}, server.text_value)
            self.assertIn('Year 7', str(caught.exception))
            c.rollback()


class SeedScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def database(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / 'seed.sqlite3'
        source = sqlite3.connect(server.DB_PATH)
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return path

    def load(self, path, rows):
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        for row in rows:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (f"048{row['id']:07d}"[:15], row['name'] + '家长', 'x')).lastrowid
            profile = row['profile_id']
            c.execute('INSERT OR IGNORE INTO student_profiles(id) VALUES(?)', (profile,))
            course = row.get('course') or '数学'
            subject = c.execute('SELECT id FROM subjects WHERE name=?', (course,)).fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            c.execute('''INSERT INTO students(id,name,course,parent_id,profile_id,balance,archived,subject_id,course_type_id,level_code,level_year,billing_unit)
                VALUES(?,?,?,?,?,0,?,?,?, 'Y8', 2027, 'lesson')''',
                (row['id'], row['name'], course, parent, profile, row['archived'], subject, kind))
        c.commit()
        c.close()

    def test_apply_is_idempotent_and_keeps_zero_balance_and_custom_rates(self):
        path = self.database()
        self.load(path, [
            {'id': 1, 'name': 'Austin Hao', 'profile_id': 1, 'archived': 1, 'course': '数学'},
            {'id': 67, 'name': 'Austin Hao', 'profile_id': 1, 'archived': 1, 'course': '英语'},
            {'id': 12, 'name': 'Scarlett', 'profile_id': 4, 'archived': 0},
            {'id': 11, 'name': 'Andy', 'profile_id': 11, 'archived': 1},
            {'id': 14, 'name': 'Yilia', 'profile_id': 6, 'archived': 0},
            {'id': 68, 'name': 'Benjamin', 'profile_id': 28, 'archived': 0},
            {'id': 39, 'name': 'Edward', 'profile_id': 9, 'archived': 0},
            {'id': 23, 'name': 'Shawn Lyu', 'profile_id': 8, 'archived': 0},
            {'id': 25, 'name': 'Aaron', 'profile_id': 10, 'archived': 0},
            {'id': 34, 'name': 'Sheldon', 'profile_id': 12, 'archived': 0},
        ])
        dry = subprocess.run([sys.executable, str(SCRIPT), '--db', str(path)], capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        c = sqlite3.connect(path)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM students WHERE course='新加坡数学'").fetchone()[0], 0)
        c.close()
        applied = subprocess.run([sys.executable, str(SCRIPT), '--db', str(path), '--apply'], capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        rows = list(c.execute("SELECT * FROM students WHERE course='新加坡数学' ORDER BY name"))
        by_name = {row['name']: row for row in rows}
        self.assertEqual(set(by_name), {'Austin Hao', 'Scarlett', 'Andy', 'Yilia', 'Benjamin', 'Edward', 'Shawn Lyu', 'Aaron', 'Sheldon'})
        self.assertEqual(by_name['Austin Hao']['profile_id'], 1)
        self.assertEqual(by_name['Austin Hao']['custom_hourly_cents'], 0)
        self.assertEqual(by_name['Austin Hao']['balance'], 0)
        self.assertEqual(by_name['Andy']['profile_id'], 11)
        self.assertEqual(by_name['Scarlett']['custom_hourly_cents'], 10000)
        self.assertEqual(by_name['Andy']['custom_hourly_cents'], 10000)
        self.assertEqual(c.execute('SELECT name FROM course_types WHERE id=?', (by_name['Yilia']['course_type_id'],)).fetchone()['name'], '小班课')
        self.assertEqual(by_name['Yilia']['custom_hourly_cents'], 10000)
        self.assertEqual(by_name['Benjamin']['profile_id'], 28)
        self.assertEqual(by_name['Benjamin']['custom_hourly_cents'], 8500)
        self.assertEqual(by_name['Aaron']['custom_hourly_cents'], 12000)
        self.assertEqual(by_name['Sheldon']['custom_hourly_cents'], 12000)
        self.assertTrue(all(row['balance'] == 0 for row in rows))
        self.assertEqual(c.execute('SELECT COUNT(*) FROM ledger').fetchone()[0], 0)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM credit_batches').fetchone()[0], 0)
        maths_left = c.execute("SELECT COUNT(*) FROM students WHERE course='数学'").fetchone()[0]
        c.close()
        again = subprocess.run([sys.executable, str(SCRIPT), '--db', str(path), '--apply'], capture_output=True, text=True)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('跳过', again.stdout)
        c = sqlite3.connect(path)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM students WHERE course='新加坡数学'").fetchone()[0], 9)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM students WHERE course='数学'").fetchone()[0], maths_left)
        c.close()

    def test_ambiguous_name_writes_nothing(self):
        path = self.database()
        self.load(path, [
            {'id': 1, 'name': 'Austin Hao', 'profile_id': 1, 'archived': 1, 'course': '数学'},
            {'id': 67, 'name': 'Austin Hao', 'profile_id': 1, 'archived': 1, 'course': '英语'},
            {'id': 12, 'name': 'Scarlett', 'profile_id': 4, 'archived': 0},
            {'id': 99, 'name': 'Scarlett', 'profile_id': 99, 'archived': 0},
            {'id': 11, 'name': 'Andy', 'profile_id': 11, 'archived': 1},
            {'id': 14, 'name': 'Yilia', 'profile_id': 6, 'archived': 0},
            {'id': 68, 'name': 'Benjamin', 'profile_id': 28, 'archived': 0},
            {'id': 39, 'name': 'Edward', 'profile_id': 9, 'archived': 0},
            {'id': 23, 'name': 'Shawn Lyu', 'profile_id': 8, 'archived': 0},
            {'id': 25, 'name': 'Aaron', 'profile_id': 10, 'archived': 0},
            {'id': 34, 'name': 'Sheldon', 'profile_id': 12, 'archived': 0},
        ])
        result = subprocess.run([sys.executable, str(SCRIPT), '--db', str(path), '--apply'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Scarlett', result.stderr)
        c = sqlite3.connect(path)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM students WHERE course='新加坡数学'").fetchone()[0], 0)
        c.close()


if __name__ == '__main__':
    unittest.main()
