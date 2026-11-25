"""Hourly course prices are calculated for the boss and withheld from everyone else."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'rates.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import pricing
import server
from teaching import AccessError


class UnitRateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def _person(self, name, course='数学', hourly=None):
        with server.connect() as c:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (('048' + uuid.uuid4().hex)[:15], name + '家长', 'x')).lastrowid
            profile = c.execute('INSERT INTO student_profiles(name) VALUES(?)', (name,)).lastrowid
            type_id = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
            subject_id = c.execute("SELECT id FROM subjects WHERE name=?", (course,)).fetchone()['id']
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id,custom_hourly_cents)
                VALUES(?,?,?,?,0,?,?,?)''', (name, course, parent, profile, subject_id, type_id, hourly)).lastrowid
            c.commit()
            return sid

    def _pack(self, sid, lessons, gift, cash_cents, minutes=60, note='充值'):
        with server.connect() as c:
            uid = c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
            actor = uid['id'] if uid else c.execute(
                "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('048' + uuid.uuid4().hex)[:15], 'Helen', 'x')).lastrowid
            units = lessons * 100
            gifts = gift * 100
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,?,'credit','2026-10-01',?,?,?)''', (sid, units + gifts, note, actor, uuid.uuid4().hex)).lastrowid
            c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents,lesson_minutes,pack_label)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (sid, lid, units, gifts, units, gifts, '2026-10-01', cash_cents, minutes, '10+2'))
            c.execute('''INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by)
                VALUES(?,?,?,?,?)''', (lid, cash_cents, 'bank', '', actor))
            c.execute('UPDATE students SET balance=balance+? WHERE id=?', (units + gifts, sid))
            c.commit()

    def test_next_pack_sets_the_hourly_rate_and_a_later_pack_is_only_a_hint(self):
        sid = self._person('Mia')
        self._pack(sid, 10, 2, 120000, 60)
        self._pack(sid, 10, 0, 90000, 60, note='下一包')
        with server.connect() as c:
            row = next(item for item in pricing.list_course_rates(c, include_left=True) if item['student_id'] == sid)
        self.assertEqual(row['hourly_label'], '$100.00/小时')
        self.assertEqual(row['per_lesson_label'], '$100.00/节')
        self.assertIn('$90.00/小时', row['hint'])
        self.assertEqual(row['source'], '课时包 · 10+2')
        self.assertEqual(row['remaining_units'], 2200)

    def test_backdated_pack_is_named_and_a_course_without_a_price_is_blank(self):
        sid = self._person('Lin')
        self._pack(sid, 8, 0, 80000, 60, note='补录以前的包')
        blank = self._person('No Price')
        with server.connect() as c:
            back = next(row for row in pricing.list_course_rates(c, include_left=True) if row['student_id'] == sid)
            missing = next(row for row in pricing.list_course_rates(c, include_left=True) if row['student_id'] == blank)
        self.assertEqual(back['source'], '补录')
        self.assertEqual(back['hourly_label'], '$100.00/小时')
        self.assertEqual(missing['hourly_label'], '未定价')
        self.assertFalse(missing['priced'])

    def test_saved_hourly_rate_is_used_when_there_is_no_pack(self):
        sid = self._person('Quoted', hourly=8000)
        with server.connect() as c:
            row = next(item for item in pricing.list_course_rates(c) if item['student_id'] == sid)
        self.assertEqual(row['hourly_label'], '$80.00/小时')
        self.assertEqual(row['source'], '报价')
        self.assertEqual(row['per_lesson_label'], '$80.00/节')

    def test_only_the_boss_receives_the_rate_or_the_page(self):
        sid = self._person('Hidden', hourly=8000)
        with server.connect() as c:
            people = [dict(c.execute('SELECT * FROM students WHERE id=?', (sid,)).fetchone())]
            people[0]['rate_label'] = '$1.00/小时'
            pricing.apply_rate_visibility(c, {'id': 1, 'role': 'admin'}, people)
            self.assertNotIn('rate_label', people[0])
            pricing.apply_rate_visibility(c, {'id': 1, 'role': 'teacher'}, people)
            pricing.apply_rate_visibility(c, {'id': 1, 'role': 'parent'}, people)
            self.assertNotIn('rate_label', people[0])
            owner = {'id': 1, 'role': 'owner'}
            pricing.apply_rate_visibility(c, owner, people)
            self.assertEqual(people[0]['rate_label'], '$80.00/小时')
            for role in ('admin', 'teacher', 'parent'):
                with self.assertRaises(AccessError):
                    pricing.unit_price_page(c, {'id': 1, 'role': role})
            page = pricing.unit_price_page(c, owner)
            self.assertTrue(any(row['student_id'] == sid and row['hourly_label'] == '$80.00/小时' for row in page['rows']))

    def test_the_page_and_cards_are_boss_only_in_the_client(self):
        root = Path(__file__).resolve().parent
        app = (root / 'static' / 'app.js').read_text()
        nav = (root / 'static' / 'teaching.js').read_text()
        self.assertIn("state.user.role!=='owner'", app)
        self.assertIn('单价一览', nav)
        self.assertIn("view==='rates'", nav)
        self.assertIn('只有老板可以看单价', app)


if __name__ == '__main__':
    unittest.main()
