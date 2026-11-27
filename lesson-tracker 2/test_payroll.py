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

    def test_small_class_uses_the_teachers_own_percent_and_warns(self):
        tid = self.teacher('Kelsey')
        known = self.student('知道价格')
        unknown = self.student('不知道价格')
        batch = self.package(known, 1, 10000)
        kind = self.c.execute("SELECT id FROM course_types WHERE name='小班课'").fetchone()['id']
        day = '2030-09-01'
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id,course_type_id)
            VALUES(?,?,?,?,100,'教室','completed',1,?,?)''', (tid, '小班课', day+'T16:00', day+'T17:00', uuid.uuid4().hex, kind)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, known))
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, unknown))
        ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'上课',1,?)",
            (known, -100, day, uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
            VALUES(?,?,100,'内容','作业','反馈',?,1)''', (lid, known, ledger))
        self.c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)', (ledger, batch, -100, 0))
        missing = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'上课',1,?)",
            (unknown, -100, day, uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
            VALUES(?,?,100,'内容','作业','反馈',?,1)''', (lid, unknown, missing))
        self.rule(tid, 'percent', 30)
        lesson = next(item for item in self.pay(day, day)['teachers'][0]['lessons'] if item['lesson_id'] == lid)
        self.assertEqual(lesson['pay_cents'], 3000)
        self.assertIn('不知道价格', lesson['warnings'])

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
        self.assertEqual(partner['remainder_cents'], -4000)
        self.assertEqual(partner['share_cents'], -1200)
        self.assertEqual(partner['helen_share_cents'], -2800)
        self.assertEqual(partner['share_cents'] + partner['helen_share_cents'], partner['remainder_cents'])

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

    def test_existing_helen_zero_percent_becomes_forty_once(self):
        uid = self.user('Helen', 'admin')
        tid = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (uid, '数学')).lastrowid
        actor = self.c.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()['id']
        rule = self.c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,note,created_by)
            VALUES(?,?,?,?,?,?,?,?)''', (tid, 'percent', 0, None, None, '2000-01-01', '旧规则', actor)).lastrowid
        self.c.execute("DELETE FROM app_meta WHERE key='helen_pay_40_v1'")
        payroll.apply_helen_percent(self.c)
        self.assertEqual(self.c.execute('SELECT percent_bp FROM pay_rules WHERE id=?', (rule,)).fetchone()['percent_bp'], 4000)
        self.c.execute('UPDATE pay_rules SET percent_bp=0 WHERE id=?', (rule,))
        payroll.apply_helen_percent(self.c)
        self.assertEqual(self.c.execute('SELECT percent_bp FROM pay_rules WHERE id=?', (rule,)).fetchone()['percent_bp'], 0)

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


    def test_institution_and_own_students_use_one_share_formula(self):
        import json
        import dividend
        import finance
        vincent = self.teacher('Vincent')
        angela = self.teacher('Angela')
        new_student = self.student('机构学生甲')
        original = self.student('我的学生甲', original=True)
        new_batch = self.package(new_student, 1, 10000)
        old_batch = self.package(original, 1, 20000)
        self.confirmed(vincent, new_student, '2030-07-07', '16:00', '17:00', 100, new_batch)
        self.confirmed(angela, original, '2030-07-08', '16:00', '17:00', 100, old_batch)
        self.rule(vincent, 'percent', 40)
        self.rule(angela, 'percent', 40)
        self.partner(vincent, 30)
        self.c.execute("INSERT INTO cost_entries(cost_date,label,amount_cents,shared,created_by) VALUES('2030-07-07','房租',1000,1,1)")
        self.c.execute("INSERT INTO cost_entries(cost_date,label,amount_cents,shared,created_by) VALUES('2030-07-07','私人开支',5000,0,1)")
        boss = {'id': 1, 'role': 'owner'}
        statement = finance.statement(self.c, boss, 'custom', None, '2030-07-01', '2030-07-31')
        board = statement['dashboard']
        share = dividend.report(self.c, boss, 'custom', None, '2030-07-01', '2030-07-31')
        vincent_user = self.c.execute('SELECT user_id FROM teachers WHERE id=?', (vincent,)).fetchone()['user_id']
        angela_user = self.c.execute('SELECT user_id FROM teachers WHERE id=?', (angela,)).fetchone()['user_id']
        own = payroll.report(self.c, {'id': vincent_user, 'role': 'teacher'}, 'month', '2030-07-15', None, None)
        other = payroll.report(self.c, {'id': angela_user, 'role': 'teacher'}, 'month', '2030-07-15', None, None)
        self.assertEqual(board['revenue_cents'], 10000)
        self.assertEqual(board['cost_cents'], 1000)
        self.assertEqual(board['profit_cents'], 9000)
        self.assertEqual(board['vincent_cents'], 2700)
        self.assertEqual(board['helen_share_cents'], 6300)
        self.assertEqual(board['own_revenue_cents'], 12000)
        self.assertEqual(board['helen_taught_cents'], 0)
        self.assertEqual(board['other_teacher_cents'], 12000)
        self.assertEqual(board['own_lines'][0]['teacher_pay_cents'], 8000)
        self.assertEqual(board['total_cents'], 18300)
        self.assertNotEqual(board['vincent_cents'], 1500)
        self.assertEqual(share['revenue_cents'], board['revenue_cents'])
        self.assertEqual(share['cost_cents'], board['cost_cents'])
        self.assertEqual(share['share_cents'], board['vincent_cents'])
        self.assertEqual(share['helen_share_cents'], board['helen_share_cents'])
        self.assertEqual(own['profit_share']['revenue_cents'], board['revenue_cents'])
        self.assertEqual(own['profit_share']['cost_cents'], board['cost_cents'])
        self.assertEqual(own['profit_share']['share_cents'], board['vincent_cents'])
        self.assertEqual(sum(line['share_cents'] for line in own['profit_share']['lines']), 2700)
        self.assertNotIn('我的学生甲', json.dumps(own))
        self.assertNotIn('我的学生甲', json.dumps(share['lines']) + json.dumps(share['students']) + json.dumps(share['costs']))
        self.assertNotIn('profit_share', other)
        self.assertIsNone(other['partner'])
        self.assertTrue(payroll.SEPARATE_ORIGINAL_STUDENTS)
        previous = payroll.SEPARATE_ORIGINAL_STUDENTS
        payroll.SEPARATE_ORIGINAL_STUDENTS = False
        try:
            folded = finance.statement(self.c, boss, 'custom', None, '2030-07-01', '2030-07-31')['dashboard']
        finally:
            payroll.SEPARATE_ORIGINAL_STUDENTS = previous
        self.assertEqual(folded['own_revenue_cents'], 0)
        self.assertEqual(folded['revenue_cents'], 30000)
        self.assertEqual(folded['vincent_cents'], 8700)

    def test_ticked_students_keep_helens_fee_and_drop_other_teachers_pay(self):
        import json
        import finance
        helen_uid = self.user('Helen', 'admin')
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (helen_uid,))
        helen = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (helen_uid, '数学')).lastrowid
        vincent = self.teacher('Vincent')
        angela = self.teacher('Angela')
        original = self.student('勾选的原有学生', original=True)
        fresh = self.student('没勾选的学生')
        self.rule(helen, 'percent', 40)
        self.rule(vincent, 'percent', 40)
        self.rule(angela, 'percent', 40, floor=3500)
        self.partner(vincent, 30)
        self.confirmed(helen, original, '2030-12-02', '16:00', '17:00', 100, self.package(original, 1, 10000))
        self.confirmed(vincent, original, '2030-12-03', '16:00', '17:00', 100, self.package(original, 1, 10000))
        self.confirmed(vincent, fresh, '2030-12-04', '16:00', '17:00', 100, self.package(fresh, 1, 10000))
        self.confirmed(angela, original, '2030-12-05', '16:00', '17:00', 100, self.package(original, 1, 5000))
        self.confirmed(vincent, fresh, '2030-11-30', '16:00', '17:00', 100, self.package(fresh, 1, 10000))
        cancelled = self.confirmed(helen, original, '2030-12-06', '16:00', '17:00', 100, self.package(original, 1, 10000))
        self.c.execute("UPDATE lessons SET status='cancelled' WHERE id=?", (cancelled,))
        absent = self.confirmed(vincent, original, '2030-12-07', '16:00', '17:00', 100, self.package(original, 1, 10000))
        self.c.execute('UPDATE lessons SET absent=1 WHERE id=?', (absent,))
        gift_ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,100,'credit','2030-12-01','赠课',1,?)",
            (original, uuid.uuid4().hex)).lastrowid
        gift_batch = self.c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on)
            VALUES(?,?,0,100,0,100,'2030-12-01')''', (original, gift_ledger)).lastrowid
        self.confirmed(angela, original, '2030-12-08', '16:00', '17:00', 100, gift_batch, paid=False)
        self.c.execute("INSERT INTO cost_entries(cost_date,label,amount_cents,shared,created_by) VALUES('2030-12-01','房租',2000,1,1)")
        board = finance.statement(self.c, {'id': 1, 'role': 'owner'}, 'custom', None, '2030-12-01', '2030-12-31')['dashboard']
        by_teacher = {}
        for line in board['own_lines']:
            by_teacher.setdefault(line['teacher_name'], []).append(line)
        helen_line = by_teacher['Helen'][0]
        vincent_line = by_teacher['Vincent'][0]
        angela_lines = {line['fee_cents']: line for line in by_teacher['Angela']}
        self.assertEqual(helen_line['teacher_pay_cents'], 0)
        self.assertEqual(helen_line['net_cents'], 10000)
        self.assertEqual(vincent_line['teacher_pay_cents'], 4000)
        self.assertEqual(vincent_line['net_cents'], 6000)
        self.assertEqual(angela_lines[5000]['teacher_pay_cents'], 3500)
        self.assertEqual(angela_lines[5000]['net_cents'], 1500)
        self.assertEqual(angela_lines[0]['fee_cents'], 0)
        self.assertEqual(angela_lines[0]['teacher_pay_cents'], 0)
        self.assertEqual(angela_lines[0]['net_cents'], 0)
        self.assertEqual(board['helen_taught_cents'], 10000)
        self.assertEqual(board['other_teacher_cents'], 6000 + 1500)
        self.assertEqual(board['own_revenue_cents'], 17500)
        self.assertNotIn('没勾选的学生', [line['student_name'] for line in board['own_lines']])
        free = [cost for cost in board['costs'] if cost['label'] == '免费课老师工资']
        self.assertEqual([(cost['student_name'], cost['teacher_name'], cost['amount_cents'], cost['date']) for cost in free],
            [('勾选的原有学生', 'Angela', 3500, '2030-12-08')])
        self.assertEqual(board['revenue_cents'], 10000)
        self.assertEqual(board['cost_cents'], 5500)
        self.assertEqual(board['profit_cents'], 4500)
        self.assertEqual(board['vincent_cents'], 1350)
        self.assertEqual(board['total_cents'], board['own_revenue_cents'] + board['helen_share_cents'])
        vincent_user = self.c.execute('SELECT user_id FROM teachers WHERE id=?', (vincent,)).fetchone()['user_id']
        own = payroll.report(self.c, {'id': vincent_user, 'role': 'teacher'}, 'month', '2030-12-15', None, None)
        self.assertEqual(own['teachers'][0]['total_pay_cents'], 8000)
        self.assertEqual(own['profit_share']['revenue_cents'], 10000)
        self.assertEqual(own['profit_share']['cost_cents'], 5500)
        self.assertEqual(own['profit_share']['share_cents'], 1350)
        self.assertNotIn('勾选的原有学生', json.dumps(own['profit_share']))
        self.assertNotIn('免费课老师工资', json.dumps(own['profit_share']))
        angela_user = self.c.execute('SELECT user_id FROM teachers WHERE id=?', (angela,)).fetchone()['user_id']
        angela_pay = payroll.report(self.c, {'id': angela_user, 'role': 'teacher'}, 'month', '2030-12-15', None, None)
        self.assertEqual(angela_pay['teachers'][0]['total_pay_cents'], 7000)
        for lesson in own['teachers'][0]['lessons']:
            for line in lesson['lines']:
                self.assertNotIn('is_new', line)
                self.assertNotIn('helen_original', line)
        exported = payroll.csv_bytes(own, vincent).decode('utf-8')
        self.assertIn('勾选的原有学生', exported)
        self.assertNotIn('is_new', exported)
        boss_pay = payroll.report(self.c, {'id': helen_uid, 'role': 'owner'}, 'custom', None, '2030-12-01', '2030-12-31')
        self.assertTrue(any('is_new' in line for teacher in boss_pay['teachers'] for lesson in teacher['lessons'] for line in lesson['lines']))

    def test_origin_tick_changes_lessons_only_from_that_day(self):
        import datetime as dt
        import finance
        helen_uid = self.user('Helen', 'admin')
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (helen_uid,))
        helen = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (helen_uid, '数学')).lastrowid
        self.rule(helen, 'percent', 40)
        student = self.student('后来勾选')
        today = dt.date.today()
        before = (today - dt.timedelta(days=40)).isoformat()
        after = (today + dt.timedelta(days=10)).isoformat()
        self.confirmed(helen, student, before, '16:00', '17:00', 100, self.package(student, 1, 10000))
        self.confirmed(helen, student, after, '16:00', '17:00', 100, self.package(student, 1, 10000))
        profile = self.c.execute('SELECT profile_id FROM students WHERE id=?', (student,)).fetchone()['profile_id']
        boss = {'id': helen_uid, 'role': 'owner'}
        early = finance.statement(self.c, boss, 'custom', None, before, before)['dashboard']
        self.assertEqual(early['revenue_cents'], 10000)
        self.assertEqual(early['own_revenue_cents'], 0)
        payroll.set_original(self.c, boss, {'profile_ids': [profile], 'helen_original': True})
        early = finance.statement(self.c, boss, 'custom', None, before, before)['dashboard']
        later = finance.statement(self.c, boss, 'custom', None, after, after)['dashboard']
        self.assertEqual(early['revenue_cents'], 10000)
        self.assertEqual(early['own_revenue_cents'], 0)
        self.assertEqual(later['revenue_cents'], 0)
        self.assertEqual(later['own_revenue_cents'], 10000)
        since = payroll.origin_since_by_profile(self.c)[profile]
        self.assertEqual(since, today.isoformat())
        kept = self.c.execute('SELECT COUNT(*) FROM student_origin_events WHERE profile_id=?', (profile,)).fetchone()[0]
        payroll.set_original(self.c, boss, {'profile_ids': [profile], 'helen_original': False})
        self.assertEqual(finance.statement(self.c, boss, 'custom', None, before, before)['dashboard']['own_revenue_cents'], 0)
        self.assertEqual(finance.statement(self.c, boss, 'custom', None, after, after)['dashboard']['revenue_cents'], 10000)
        self.assertGreater(self.c.execute('SELECT COUNT(*) FROM student_origin_events WHERE profile_id=?', (profile,)).fetchone()[0], kept)

    def test_existing_tick_covers_past_lessons_without_deleting_rows(self):
        student = self.student('一开始就是原有', original=True)
        profile = self.c.execute('SELECT profile_id FROM students WHERE id=?', (student,)).fetchone()['profile_id']
        before = self.c.execute('SELECT COUNT(*) FROM students').fetchone()[0]
        payroll.migrate_origin_history(self.c)
        payroll.migrate_origin_history(self.c)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM students').fetchone()[0], before)
        self.assertEqual(self.c.execute('SELECT helen_original FROM students WHERE id=?', (student,)).fetchone()[0], 1)
        rows = self.c.execute('SELECT helen_original, effective_from FROM student_origin_events WHERE profile_id=?', (profile,)).fetchall()
        self.assertEqual([(row['helen_original'], row['effective_from']) for row in rows], [(1, '2000-01-01')])

    def test_unpriced_lesson_is_listed_for_the_boss_only(self):
        import finance
        tid = self.teacher('Kelsey')
        sid = self.student('没有价格')
        legacy = self.c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,legacy)
            VALUES(?,100,0,100,0,'',1)''', (sid,)).lastrowid
        self.confirmed(tid, sid, '2030-08-02', '16:00', '17:00', 100, legacy)
        self.rule(tid, 'percent', 40, floor=3500)
        self.partner(tid, 30)
        board = finance.statement(self.c, {'id': 1, 'role': 'owner'}, 'custom', None, '2030-08-01', '2030-08-31')['dashboard']
        self.assertEqual(board['revenue_cents'], 0)
        self.assertEqual(len(board['unpriced']), 1)
        row = board['unpriced'][0]
        self.assertEqual((row['date'], row['student_name'], row['course'], row['teacher_name']), ('2030-08-02', '没有价格', '数学', 'Kelsey'))
        self.assertTrue(row['lesson_id'] and row['student_id'])
        user_id = self.c.execute('SELECT user_id FROM teachers WHERE id=?', (tid,)).fetchone()['user_id']
        own = payroll.report(self.c, {'id': user_id, 'role': 'teacher'}, 'month', '2030-08-15', None, None)
        self.assertNotIn('unpriced', own)
        self.assertEqual(own['teachers'][0]['total_pay_cents'], 3500)
        page = Path(__file__).resolve().parent.joinpath('static', 'pay.js').read_text()
        self.assertIn('有 ${missing.length} 节课没有价格，请补上', page)

    def test_month_lists_both_student_groups_and_excel_pay_is_complete(self):
        import finance
        import exports
        import receivables
        receivables.total_owed = lambda c: 0
        helen_uid = self.user('Helen', 'admin')
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (helen_uid,))
        helen = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (helen_uid, '数学')).lastrowid
        vincent = self.teacher('Vincent')
        original = self.student('月度原有', original=True)
        fresh = self.student('月度机构')
        self.rule(helen, 'percent', 40)
        self.rule(vincent, 'percent', 40)
        self.partner(vincent, 30)
        self.confirmed(helen, original, '2031-03-02', '16:00', '17:00', 100, self.package(original, 1, 10000))
        self.confirmed(vincent, fresh, '2031-03-03', '16:00', '17:00', 100, self.package(fresh, 1, 20000))
        boss = {'id': helen_uid, 'role': 'owner'}
        month = finance.monthly(self.c, boss, '2031-03')
        self.assertEqual(month['institution_lessons_cents'], 20000)
        self.assertEqual(month['own_lessons_cents'], 10000)
        self.assertEqual(month['lessons_value_cents'], 30000)
        wages = payroll.report(self.c, boss, 'custom', None, '2031-03-01', '2031-03-31')
        full_pay = sum(teacher['total_pay_cents'] for teacher in wages['teachers'])
        self.assertEqual(full_pay, 4000 + 8000)
        statement = finance.statement(self.c, boss, 'custom', None, '2031-03-01', '2031-03-31')
        self.assertEqual(sum(teacher['pay_cents'] for teacher in statement['teachers']), full_pay)
        sheet = exports.finance_rows(statement)[0][1]
        pay_cells = [row[-1] for row in sheet if row and row[0] in ('Helen（Helen）', 'Vincent')]
        self.assertEqual(pay_cells, ['40.00', '80.00'])
        self.assertIn('机构学生上过的课', Path(__file__).resolve().parent.joinpath('static', 'pay.js').read_text())

    def test_maths_names_and_saved_flag(self):
        for name in ('数学', '中数', '高数', 'VCE 中数', 'VCE 低数', 'VCE 高数', '新加坡数学', '数学 + 英语',
                'Singapore Maths', 'Methods', 'Specialist Mathematics', 'General Maths', 'general mathematics'):
            self.assertTrue(teaching.name_is_maths(name), name)
        for name in ('英语', '科学', '物理', '化学', '中文', '写作', 'Science', 'English'):
            self.assertFalse(teaching.name_is_maths(name), name)
        stored = {row['name']: row['is_maths'] for row in self.c.execute('SELECT name, is_maths FROM subjects')}
        for name in ('数学', '中数', '高数', 'VCE 中数', 'VCE 低数', 'VCE 高数', '新加坡数学', '数学 + 英语'):
            self.assertEqual(stored[name], 1, name)
        for name in ('英语', '科学', '物理', '化学', '中文', '写作'):
            self.assertEqual(stored[name], 0, name)
        forced = teaching.save_catalog_item(self.c, {'id': 1, 'role': 'owner'}, 'subjects',
            {'name': '科学实验', 'is_maths': True, 'active': True}, server.text_value)
        self.assertEqual(self.c.execute('SELECT is_maths FROM subjects WHERE id=?', (forced['id'],)).fetchone()['is_maths'], 1)
        teaching.ensure_maths_flag(self.c)
        self.assertEqual(self.c.execute('SELECT is_maths FROM subjects WHERE id=?', (forced['id'],)).fetchone()['is_maths'], 1)
        guessed = teaching.save_catalog_item(self.c, {'id': 1, 'role': 'owner'}, 'subjects',
            {'name': 'Methods Unit', 'active': True}, server.text_value)
        plain = teaching.save_catalog_item(self.c, {'id': 1, 'role': 'owner'}, 'subjects',
            {'name': 'Science Lab', 'active': True}, server.text_value)
        self.assertEqual(self.c.execute('SELECT is_maths FROM subjects WHERE id=?', (guessed['id'],)).fetchone()['is_maths'], 1)
        self.assertEqual(self.c.execute('SELECT is_maths FROM subjects WHERE id=?', (plain['id'],)).fetchone()['is_maths'], 0)
        english = self.c.execute("SELECT id FROM subjects WHERE name='英语'").fetchone()['id']
        with self.assertRaises(teaching.AccessError):
            teaching.save_catalog_item(self.c, {'id': 2, 'role': 'teacher'}, 'subjects',
                {'id': english, 'name': '英语', 'is_maths': True, 'active': True}, server.text_value)
        page = Path(__file__).resolve().parent.joinpath('static')
        self.assertIn('data-maths-subject', (page / 'pay.js').read_text())
        self.assertIn('name="is_maths"', (page / 'teaching.js').read_text())
        self.assertIn('20261127draft', (page / 'index.html').read_text())

    def test_original_tick_is_maths_only(self):
        import json
        import finance
        import dividend
        import receivables
        receivables.total_owed = lambda c: 0
        helen_uid = self.user('Helen', 'admin')
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (helen_uid,))
        helen = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (helen_uid, '数学')).lastrowid
        vincent = self.teacher('Vincent')
        self.rule(helen, 'percent', 40)
        self.rule(vincent, 'percent', 40)
        self.partner(vincent, 30)
        parent = self.user('原有家长')
        profile = self.c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        maths_id = self.c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
        english_id = self.c.execute("SELECT id FROM subjects WHERE name='英语'").fetchone()['id']
        maths = self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original,subject_id)
            VALUES(?,?,?,?,?,?,?)''', ('同一原有学生', '数学', parent, profile, 100000, 1, maths_id)).lastrowid
        english = self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original,subject_id)
            VALUES(?,?,?,?,?,?,?)''', ('同一原有学生', '英语', parent, profile, 100000, 1, english_id)).lastrowid
        maths_lesson = self.confirmed(helen, maths, '2031-04-02', '16:00', '17:00', 100, self.package(maths, 1, 10000))
        english_lesson = self.confirmed(vincent, english, '2031-04-03', '16:00', '17:00', 100, self.package(english, 1, 10000))
        self.c.execute('UPDATE lessons SET subject_id=?, title=? WHERE id=?', (maths_id, '数学', maths_lesson))
        self.c.execute('UPDATE lessons SET subject_id=?, title=? WHERE id=?', (english_id, '英语', english_lesson))
        boss = {'id': helen_uid, 'role': 'owner'}
        board = finance.statement(self.c, boss, 'custom', None, '2031-04-01', '2031-04-30')['dashboard']
        self.assertEqual([line['lesson'] for line in board['own_lines']], ['数学'])
        self.assertEqual(board['own_revenue_cents'], 10000)
        self.assertEqual(board['revenue_cents'], 10000)
        self.assertEqual(board['vincent_cents'], 3000)
        month = finance.monthly(self.c, boss, '2031-04')
        self.assertEqual(month['own_lessons_cents'], 10000)
        self.assertEqual(month['institution_lessons_cents'], 10000)
        self.assertEqual(month['lessons_value_cents'], 20000)
        share = dividend.report(self.c, boss, 'custom', None, '2031-04-01', '2031-04-30')
        self.assertEqual([line['student_name'] for line in share['lines']], ['同一原有学生'])
        self.assertEqual(share['revenue_cents'], 10000)
        self.assertTrue(all('is_new' not in line and 'helen_original' not in line for line in share['lines']))
        vincent_user = self.c.execute('SELECT user_id FROM teachers WHERE id=?', (vincent,)).fetchone()['user_id']
        own = payroll.report(self.c, {'id': vincent_user, 'role': 'teacher'}, 'month', '2031-04-15', None, None)
        self.assertEqual(own['teachers'][0]['total_pay_cents'], 4000)
        self.assertEqual(own['profit_share']['revenue_cents'], 10000)
        self.assertEqual(own['profit_share']['share_cents'], 3000)
        dumped = json.dumps(own['profit_share'], ensure_ascii=False)
        self.assertIn('同一原有学生', dumped)
        self.assertNotIn('原有学生', dumped.replace('同一原有学生', ''))
        self.assertNotIn('新学生', dumped)
        for lesson in own['teachers'][0]['lessons']:
            for line in lesson['lines']:
                self.assertNotIn('is_new', line)
                self.assertNotIn('is_maths', line)
        self.c.execute('UPDATE subjects SET is_maths=0 WHERE id=?', (maths_id,))
        moved = finance.statement(self.c, boss, 'custom', None, '2031-04-01', '2031-04-30')['dashboard']
        self.assertEqual(moved['own_lines'], [])
        self.assertEqual(moved['revenue_cents'], 20000)
        self.assertEqual(moved['vincent_cents'], 6000)


def teaching_access():
    import teaching
    return teaching.AccessError


if __name__ == '__main__':
    unittest.main(verbosity=2)
