"""Teacher pay: percent, hourly floor, hourly rate, and partner share."""
import os
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'pay.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import payroll
import server
import teaching


class PayCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')
        self.n = 0

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def phone(self):
        self.n += 1
        return f'049{self.n:04d}{uuid.uuid4().int % 10000:04d}'[:15]

    def user(self, name, role='parent'):
        return self.c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
            (self.phone(), name, 'x', role)).lastrowid

    def teacher(self, name):
        uid = self.user(name)
        return self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (uid, '数学')).lastrowid

    def student(self, name, original=False):
        parent = self.user(name + '家长')
        profile = self.c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        sid = self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original)
            VALUES(?,?,?,?,?,?)''', (name, '数学', parent, profile, 100000, int(original))).lastrowid
        return sid

    def package(self, sid, lessons, cash_cents):
        units = lessons * 100
        ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'credit','2030-01-01','购课',1,?)",
            (sid, units, uuid.uuid4().hex)).lastrowid
        batch = self.c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on)
            VALUES(?,?,?,0,?,0,'2030-01-01')''', (sid, ledger, units, units)).lastrowid
        if cash_cents is not None:
            self.c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,1)',
                (ledger, cash_cents, 'bank', ''))
        return batch

    def confirmed(self, tid, sid, day, start, end, units, batch, paid=True):
        start_at, end_at = f'{day}T{start}', f'{day}T{end}'
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?,?,?,?,100,'教室','completed',1,?)''', (tid, '数学', start_at, end_at, uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
        ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'上课',1,?)",
            (sid, -units, day, uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
            VALUES(?,?,?,'内容','作业','反馈',?,1)''', (lid, sid, units, ledger))
        self.c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)',
            (ledger, batch, -units if paid else 0, 0 if paid else -units))
        return lid

    def rule(self, tid, kind, percent=None, floor=None, rate=None, start='2000-01-01'):
        bp = None if percent is None else int(percent * 100)
        self.c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,created_by)
            VALUES(?,?,?,?,?,?,1)''', (tid, kind, bp, floor, rate, start))

    def partner(self, tid, percent=30, start='2000-01-01'):
        self.c.execute('INSERT INTO partner_share_rules(teacher_id,percent_bp,effective_from,created_by) VALUES(?,?,?,1)',
            (tid, int(percent * 100), start))

    def pay(self, start, end):
        return payroll.report(self.c, {'id': 1, 'role': 'owner'}, 'custom', None, start, end)

    def test_percent_of_lesson_fee(self):
        tid, sid = self.teacher('Angela'), self.student('学生甲')
        batch = self.package(sid, 10, 100000)
        self.confirmed(tid, sid, '2030-03-04', '16:00', '17:00', 100, batch)
        self.rule(tid, 'percent', 40)
        lesson = self.pay('2030-03-04', '2030-03-04')['teachers'][0]
        self.assertEqual(lesson['total_fee_cents'], 10000)
        self.assertEqual(lesson['total_pay_cents'], 4000)
        self.assertEqual(lesson['lessons'][0]['pay_basis'], 'percent')
        self.assertEqual(lesson['total_minutes'], 60)

    def test_percent_with_hourly_floor(self):
        tid, sid = self.teacher('Angela'), self.student('学生乙')
        small = self.package(sid, 1, 5000)
        large = self.package(sid, 1, 20000)
        self.confirmed(tid, sid, '2030-04-01', '16:00', '17:00', 100, small)
        self.confirmed(tid, sid, '2030-04-02', '16:00', '17:00', 100, large)
        self.rule(tid, 'percent', 40, floor=3500)
        teachers = {lesson['date']: lesson for lesson in self.pay('2030-04-01', '2030-04-02')['teachers'][0]['lessons']}
        self.assertEqual(teachers['2030-04-01']['fee_cents'], 5000)
        self.assertEqual(teachers['2030-04-01']['pay_cents'], 3500)
        self.assertEqual(teachers['2030-04-01']['pay_basis'], 'floor')
        self.assertEqual(teachers['2030-04-02']['fee_cents'], 20000)
        self.assertEqual(teachers['2030-04-02']['pay_cents'], 8000)
        self.assertEqual(teachers['2030-04-02']['pay_basis'], 'percent')

    def test_hourly_rate_ignores_fee(self):
        tid, sid = self.teacher('未来老师'), self.student('学生丙')
        batch = self.package(sid, 1, 10000)
        self.confirmed(tid, sid, '2030-05-06', '10:00', '11:30', 100, batch)
        self.rule(tid, 'hourly', rate=4000)
        lesson = self.pay('2030-05-01', '2030-05-31')['teachers'][0]['lessons'][0]
        self.assertEqual(lesson['minutes'], 90)
        self.assertEqual(lesson['pay_cents'], 6000)
        self.assertEqual(lesson['pay_basis'], 'hourly')
        self.assertEqual(lesson['fee_cents'], 10000)

    def test_later_rule_does_not_rewrite_earlier_lessons(self):
        tid, sid = self.teacher('Angela'), self.student('学生丁')
        batch = self.package(sid, 2, 20000)
        self.confirmed(tid, sid, '2031-05-15', '16:00', '17:00', 100, batch)
        self.confirmed(tid, sid, '2031-06-15', '16:00', '17:00', 100, batch)
        self.rule(tid, 'percent', 40, start='2000-01-01')
        self.rule(tid, 'hourly', rate=1000, start='2031-06-01')
        lessons = {lesson['date']: lesson for lesson in self.pay('2031-05-01', '2031-06-30')['teachers'][0]['lessons']}
        self.assertEqual(lessons['2031-05-15']['pay_cents'], 4000)
        self.assertEqual(lessons['2031-05-15']['pay_basis'], 'percent')
        self.assertEqual(lessons['2031-06-15']['pay_cents'], 1000)
        self.assertEqual(lessons['2031-06-15']['pay_basis'], 'hourly')

    def test_partner_share_excludes_original_students_and_shares_costs(self):
        teacher = self.teacher('Vincent')
        new_student = self.student('新学生')
        original = self.student('Helen 的原有学生', original=True)
        new_batch = self.package(new_student, 1, 10000)
        old_batch = self.package(original, 1, 10000)
        day = '2030-07-07'
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?,?,?,?,100,'教室','completed',1,?)''', (teacher, '小班', day+'T16:00', day+'T17:00', uuid.uuid4().hex)).lastrowid
        for sid, batch in ((new_student, new_batch), (original, old_batch)):
            self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
            ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'上课',1,?)",
                (sid, -100, day, uuid.uuid4().hex)).lastrowid
            self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'内容','作业','反馈',?,1)''', (lid, sid, ledger))
            self.c.execute('INSERT INTO credit_movements VALUES(?,?,?,?,0)', (ledger, batch, -100, 0))
        solo = self.package(original, 1, 20000)
        self.confirmed(teacher, original, '2030-07-08', '16:00', '17:00', 100, solo)
        self.rule(teacher, 'percent', 40)
        self.partner(teacher, 30)
        self.c.execute("INSERT INTO cost_entries(cost_date,label,amount_cents,shared,created_by) VALUES(?,'房租',1000,1,1)", (day,))
        self.c.execute("INSERT INTO cost_entries(cost_date,label,amount_cents,shared,created_by) VALUES(?,'私人开支',5000,0,1)", (day,))
        data = self.pay('2030-07-01', '2030-07-31')
        group = next(lesson for lesson in data['teachers'][0]['lessons'] if lesson['lesson_id'] == lid)
        self.assertEqual(group['fee_cents'], 20000)
        self.assertEqual(group['pay_cents'], 8000)
        self.assertEqual(sorted(line['pay_cents'] for line in group['lines']), [4000, 4000])
        partner = data['partner']
        self.assertEqual(partner['revenue_cents'], 10000)
        self.assertEqual(partner['shared_cost_cents'], 1000)
        self.assertEqual(partner['remainder_cents'], 9000)
        self.assertEqual(partner['share_cents'], 2700)
        self.assertEqual(partner['teaching_pay_cents'], data['teachers'][0]['total_pay_cents'])
        self.assertNotEqual(partner['share_cents'], 1500)
        self.assertEqual([line['student_id'] for line in partner['lines']], [new_student])

    def test_partner_share_is_zero_when_remainder_is_negative(self):
        tid, sid = self.teacher('Vincent'), self.student('新学生')
        batch = self.package(sid, 1, 1000)
        self.confirmed(tid, sid, '2030-08-01', '16:00', '17:00', 100, batch)
        self.rule(tid, 'percent', 40)
        self.partner(tid, 30)
        self.c.execute("INSERT INTO cost_entries(cost_date,label,amount_cents,shared,created_by) VALUES('2030-08-01','广告',5000,1,1)")
        partner = self.pay('2030-08-01', '2030-08-01')['partner']
        self.assertLess(partner['remainder_cents'], 0)
        self.assertEqual(partner['share_cents'], 0)

    def test_original_flag_is_per_student_and_not_inherited(self):
        tid = self.teacher('Vincent')
        plain = self.student('未勾选的学生')
        sibling = self.student('原有学生的弟弟')
        original = self.student('名单上的原有学生', original=True)
        for sid in (plain, sibling, original):
            batch = self.package(sid, 1, 10000)
            self.confirmed(tid, sid, '2030-08-02', '10:00', '11:00', 100, batch)
        self.rule(tid, 'percent', 40)
        self.partner(tid, 30)
        counted = {line['student_id'] for line in self.pay('2030-08-01', '2030-08-31')['partner']['lines']}
        self.assertEqual(counted, {plain, sibling})
        profile = self.c.execute('SELECT profile_id FROM students WHERE id=?', (sibling,)).fetchone()[0]
        payroll.set_original(self.c, {'id': 1, 'role': 'owner'}, {'profile_ids': [profile], 'helen_original': True})
        counted = {line['student_id'] for line in self.pay('2030-08-01', '2030-08-31')['partner']['lines']}
        self.assertEqual(counted, {plain})

    def test_only_owner_can_change_original_flag(self):
        sid = self.student('权限学生')
        profile = self.c.execute('SELECT profile_id FROM students WHERE id=?', (sid,)).fetchone()[0]
        payload = {'profile_ids': [profile], 'helen_original': True}
        for role in ('admin', 'teacher', 'parent'):
            with self.assertRaises(teaching_access()):
                payroll.set_original(self.c, {'id': 9, 'role': role}, payload)
            with self.assertRaises(teaching_access()):
                payroll.reject_original_flag({'id': 9, 'role': role}, {'helen_original': False, 'name': 'x'})
        self.assertEqual(self.c.execute('SELECT helen_original FROM students WHERE id=?', (sid,)).fetchone()[0], 0)
        payroll.set_original(self.c, {'id': 1, 'role': 'owner'}, payload)
        self.assertEqual(self.c.execute('SELECT helen_original FROM students WHERE id=?', (sid,)).fetchone()[0], 1)

    def test_typed_fee_replaces_package_price(self):
        tid, sid = self.teacher('Angela'), self.student('学生庚')
        batch = self.package(sid, 1, 10000)
        lid = self.confirmed(tid, sid, '2030-11-01', '16:00', '17:00', 100, batch)
        self.rule(tid, 'percent', 40)
        self.assertEqual(self.pay('2030-11-01', '2030-11-01')['teachers'][0]['total_pay_cents'], 4000)
        self.c.execute('UPDATE lesson_reports SET fee_cents=5000, fee_overridden=1 WHERE lesson_id=?', (lid,))
        lesson = self.pay('2030-11-01', '2030-11-01')['teachers'][0]['lessons'][0]
        self.assertEqual(lesson['fee_cents'], 5000)
        self.assertEqual(lesson['pay_cents'], 2000)
        self.assertTrue(lesson['lines'][0]['fee_overridden'])

    def test_gift_lesson_has_zero_fee_and_legacy_price_stays_unknown(self):
        tid, sid = self.teacher('Kelsey'), self.student('学生戊')
        gift_ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,100,'credit','2030-01-01','赠课',1,?)",
            (sid, uuid.uuid4().hex)).lastrowid
        gift_batch = self.c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on)
            VALUES(?,?,0,100,0,100,'2030-01-01')''', (sid, gift_ledger)).lastrowid
        legacy = self.c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,legacy)
            VALUES(?,100,0,100,0,'',1)''', (sid,)).lastrowid
        self.confirmed(tid, sid, '2030-09-01', '16:00', '17:00', 100, gift_batch, paid=False)
        self.confirmed(tid, sid, '2030-09-02', '16:00', '17:00', 100, legacy)
        self.rule(tid, 'percent', 40, floor=3500)
        lessons = {lesson['date']: lesson for lesson in self.pay('2030-09-01', '2030-09-02')['teachers'][0]['lessons']}
        self.assertEqual(lessons['2030-09-01']['fee_cents'], 0)
        self.assertTrue(lessons['2030-09-01']['fee_known'])
        self.assertEqual(lessons['2030-09-01']['pay_cents'], 3500)
        self.assertFalse(lessons['2030-09-02']['fee_known'])
        self.assertEqual(lessons['2030-09-02']['pay_cents'], 3500)

    def test_non_owner_cannot_read_pay(self):
        with self.assertRaises(teaching_access()):
            payroll.report(self.c, {'id': 2, 'role': 'teacher'}, 'week', '2030-01-06', None, None)
        with self.assertRaises(teaching_access()):
            payroll.report(self.c, {'id': 3, 'role': 'parent'}, 'month', '2030-01-06', None, None)
        with self.assertRaises(teaching_access()):
            payroll.report(self.c, {'id': 4, 'role': 'admin'}, 'week', '2030-01-06', None, None)

    def test_a_written_report_counts_without_changing_status(self):
        self.assertFalse(teaching.report_written({'content': '', 'homework': ' ', 'feedback': '', 'ledger_id': None}))
        self.assertTrue(teaching.report_written({'content': '分数运算', 'homework': '', 'feedback': '', 'ledger_id': None}))
        self.assertTrue(teaching.lesson_recorded({'status': 'scheduled', 'reports': [{'content': '分数运算', 'homework': '', 'feedback': ''}]}))
        self.assertFalse(teaching.lesson_recorded({'status': 'scheduled', 'reports': [{'content': '', 'homework': '', 'feedback': ''}]}))
        tid, sid = self.teacher('Angela'), self.student('已写记录')
        batch = self.package(sid, 1, 8000)
        lid = self.confirmed(tid, sid, '2030-04-02', '16:00', '17:00', 100, batch)
        self.c.execute("UPDATE lessons SET status='scheduled' WHERE id=?", (lid,))
        counted = [row['lesson_id'] for row in payroll.confirmed_rows(self.c, date(2030, 4, 1), date(2030, 4, 30))]
        self.assertIn(lid, counted)
        draft = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?,?,?,?,100,'教室','scheduled',1,?)''', (tid, '空草稿', '2030-04-03T16:00', '2030-04-03T17:00', uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,updated_by)
            VALUES(?,?,100,'','','',1)''', (draft, sid))
        counted = [row['lesson_id'] for row in payroll.confirmed_rows(self.c, date(2030, 4, 1), date(2030, 4, 30))]
        self.assertNotIn(draft, counted)

    def test_csv_is_utf8_with_bom(self):
        tid, sid = self.teacher('Christina'), self.student('学生己')
        batch = self.package(sid, 1, 8000)
        self.confirmed(tid, sid, '2030-10-01', '15:00', '16:00', 100, batch)
        self.rule(tid, 'percent', 40)
        data = self.pay('2030-10-01', '2030-10-01')
        blob = payroll.csv_bytes(data)
        self.assertTrue(blob.startswith(b'\xef\xbb\xbf'))
        text = blob.decode('utf-8-sig')
        self.assertIn('老师工资', text)
        self.assertIn('Christina', text)
        self.assertIn('80.00', text)
        self.assertIn('32.00', text)

    def test_seed_only_matching_existing_teachers(self):
        self.c.execute("DELETE FROM app_meta WHERE key='pay_seed_v1'")
        names = {'Angela': (4000, 3500), 'Kelsey': (4000, None), 'Ethan': (4000, None),
            'Christina': (4000, None), 'Vincent': (4000, None), 'Bob': None}
        ids = {name: self.teacher(name) for name in names}
        self.user('老板', 'admin')
        owner = self.c.execute("SELECT id FROM users WHERE name='老板'").fetchone()['id']
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner,))
        payroll.seed_if_needed(self.c)
        payroll.seed_if_needed(self.c)
        for name, expected in names.items():
            row = self.c.execute('SELECT percent_bp, hourly_floor_cents FROM pay_rules WHERE teacher_id=?', (ids[name],)).fetchone()
            if expected is None:
                self.assertIsNone(row)
            else:
                self.assertEqual((row['percent_bp'], row['hourly_floor_cents']), expected)
        partner = self.c.execute('SELECT teacher_id, percent_bp FROM partner_share_rules').fetchone()
        self.assertEqual(partner['teacher_id'], ids['Vincent'])
        self.assertEqual(partner['percent_bp'], 3000)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM pay_rules').fetchone()[0], 5)

    def test_schema_does_not_drop_students(self):
        sid = self.student('保留学生')
        payroll.schema(self.c)
        row = self.c.execute('SELECT name, helen_original, balance FROM students WHERE id=?', (sid,)).fetchone()
        self.assertEqual(row['name'], '保留学生')
        self.assertEqual(row['helen_original'], 0)
        self.assertEqual(row['balance'], 100000)

    def test_fixed_costs_prorate_by_day_week_and_month(self):
        self.assertEqual(payroll.schedule_cost(500, 'day', date(2030, 1, 1), None, date(2030, 1, 2), date(2030, 1, 4)), 1500)
        self.assertEqual(payroll.schedule_cost(7000, 'week', date(2030, 1, 6), None, date(2030, 1, 6), date(2030, 1, 12)), 7000)
        self.assertEqual(payroll.schedule_cost(3100, 'month', date(2030, 1, 1), None, date(2030, 1, 1), date(2030, 1, 31)), 3100)
        self.assertEqual(payroll.schedule_cost(7000, 'week', date(2030, 2, 1), date(2030, 1, 1), date(2030, 3, 1), date(2030, 3, 7)), 0)


def teaching_access():
    import teaching
    return teaching.AccessError


if __name__ == '__main__':
    unittest.main(verbosity=2)
