"""请假: charge or not, undo, balance, and who is allowed to mark it."""
import os
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'absence.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import deletion
import payroll
import server
import teaching


class AbsenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')
        self.n = 0
        self.owner = self.user('Helen', 'admin')

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def phone(self):
        self.n += 1
        return f'047{self.n:04d}{uuid.uuid4().int % 10000:04d}'[:15]

    def user(self, name, role='parent'):
        return self.c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
            (self.phone(), name, 'x', role)).lastrowid

    def teacher(self, name='Angela'):
        uid = self.user(name)
        tid = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (uid, '数学')).lastrowid
        return tid, uid

    def student(self, name, parent=None):
        parent = parent or self.user(name + '家长')
        profile = self.c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        sid = self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance)
            VALUES(?,?,?,?,0)''', (name, '数学', parent, profile)).lastrowid
        return sid, parent

    def topup(self, sid, paid=10, gift=0):
        ledger = self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit','2030-01-01','购课',?,?)",
            (sid, self.owner, uuid.uuid4().hex)).lastrowid
        import credit_batches
        credit_batches.apply(self.c, ledger, 'credit', {'amount': paid, 'gift_amount': gift}, server.units)
        return ledger

    def add_lesson(self, tid, students, day='2030-03-04', start='16:00', end='17:00', planned=100, title='数学 · 一对一'):
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id)
            VALUES(?,?,?,?,?,'教室',?,?)''',
            (tid, title, f'{day}T{start}', f'{day}T{end}', planned, self.owner, uuid.uuid4().hex)).lastrowid
        for sid in students:
            self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, sid))
        return lid

    def balance(self, sid):
        return self.c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']

    def pools(self, sid):
        row = self.c.execute('SELECT COALESCE(SUM(paid_left),0) paid, COALESCE(SUM(gift_left),0) gift FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
        return row['paid'], row['gift']

    def lesson_row(self, lid):
        return self.c.execute('SELECT * FROM lessons WHERE id=?', (lid,)).fetchone()

    def mark(self, lid, charge, role='owner', user=None, version=None):
        who = {'id': self.owner if user is None else user, 'role': role}
        current = self.lesson_row(lid)['version'] if version is None else version
        return teaching.mark_absent(self.c, who, {'lesson_id': lid, 'version': current, 'charge': charge}, server.units)

    def undo(self, lid, role='owner', user=None):
        who = {'id': self.owner if user is None else user, 'role': role}
        return teaching.undo_absent(self.c, who, {'lesson_id': lid, 'version': self.lesson_row(lid)['version']})

    def lesson_ledgers(self, sid):
        return self.c.execute(
            "SELECT id, delta, kind, note FROM ledger WHERE student_id=? AND kind='lesson' AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reversal_of=ledger.id) ORDER BY id",
            (sid,)).fetchall()

    def test_charged_absence_uses_balance_like_attendance_and_undo_puts_it_back(self):
        tid, _ = self.teacher()
        sid, parent = self.student('陈一诺')
        other, _ = self.student('旁听')
        self.topup(sid, paid=1, gift=1)
        self.topup(other, 5)
        lid = self.add_lesson(tid, [sid], start='10:00', end='12:00', planned=100)
        untouched = self.add_lesson(tid, [other], day='2030-03-05')
        self.assertEqual(self.balance(sid), 200)
        self.assertEqual(self.pools(sid), (100, 100))

        result = self.mark(lid, True)
        self.assertTrue(result['charged'])
        row = self.lesson_row(lid)
        self.assertEqual(row['status'], 'scheduled')
        self.assertEqual(row['absent'], 1)
        self.assertEqual(row['absent_charge'], 1)
        self.assertEqual(self.balance(sid), 100)
        self.assertEqual(self.pools(sid), (0, 100))
        charged = self.lesson_ledgers(sid)
        self.assertEqual(len(charged), 1)
        self.assertEqual(charged[0]['delta'], -100)
        self.assertIn('请假扣课时', charged[0]['note'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM lesson_reports WHERE lesson_id=?', (lid,)).fetchone()[0], 0)
        self.assertEqual(self.lesson_row(untouched)['absent'], 0)
        self.assertEqual(self.balance(other), 500)

        state = teaching.state_for(self.c, {'id': parent, 'role': 'parent'})
        visible = next(lesson for lesson in state['lessons'] if lesson['id'] == lid)
        self.assertEqual(visible['absent'], 1)
        self.assertEqual(visible['absent_charge'], 1)
        self.assertFalse(visible['recorded'])
        self.assertEqual(visible['students'][0]['balance'], 100)

        self.undo(lid)
        restored = self.lesson_row(lid)
        self.assertEqual(restored['status'], 'scheduled')
        self.assertEqual(restored['absent'], 0)
        self.assertEqual(restored['absent_charge'], 0)
        self.assertEqual(self.balance(sid), 200)
        self.assertEqual(self.pools(sid), (100, 100))
        self.assertEqual(self.lesson_ledgers(sid), [])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM lesson_absence_charges WHERE lesson_id=?', (lid,)).fetchone()[0], 0)
        self.assertTrue(self.c.execute("SELECT 1 FROM ledger WHERE student_id=? AND kind='reversal' AND note='取消请假，退回课时'", (sid,)).fetchone())

        self.mark(lid, True)
        self.assertEqual(self.balance(sid), 100)
        self.undo(lid)
        self.assertEqual(self.balance(sid), 200)
        with self.assertRaises(ValueError) as error:
            self.undo(lid)
        self.assertIn('没有请假', str(error.exception))

    def test_uncharged_absence_does_not_touch_balance_and_undo_is_free(self):
        tid, teacher_user = self.teacher()
        sid, _ = self.student('李沐阳')
        self.topup(sid, 4)
        lid = self.add_lesson(tid, [sid])
        admin = self.user('Amy', 'admin')
        self.mark(lid, False, role='admin', user=admin)
        row = self.lesson_row(lid)
        self.assertEqual((row['absent'], row['absent_charge'], row['status']), (1, 0, 'scheduled'))
        self.assertEqual(self.balance(sid), 400)
        self.assertEqual(self.lesson_ledgers(sid), [])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM lesson_reports WHERE lesson_id=?', (lid,)).fetchone()[0], 0)
        seen = teaching.state_for(self.c, {'id': teacher_user, 'role': 'teacher'})
        shown = next(lesson for lesson in seen['lessons'] if lesson['id'] == lid)
        self.assertEqual(shown['absent'], 1)
        self.assertNotIn('balance', shown['students'][0])
        self.assertFalse(shown['recorded'])
        self.undo(lid, role='admin', user=admin)
        self.assertEqual(self.lesson_row(lid)['absent'], 0)
        self.assertEqual(self.balance(sid), 400)
        self.assertFalse(self.c.execute("SELECT 1 FROM ledger WHERE student_id=? AND kind='reversal'", (sid,)).fetchone())

    def test_group_charge_is_all_or_nothing_and_hourly_uses_duration(self):
        tid, _ = self.teacher('Kelsey')
        rich, _ = self.student('余额够')
        poor, _ = self.student('余额不够')
        hourly, _ = self.student('按小时')
        self.topup(rich, 2)
        self.topup(hourly, paid=5)
        self.c.execute("UPDATE students SET billing_unit='hour' WHERE id=?", (hourly,))
        short = self.add_lesson(tid, [rich, poor])
        with self.assertRaises(ValueError) as error:
            self.mark(short, True)
        self.assertIn('余额不够', str(error.exception))
        self.assertEqual(self.lesson_row(short)['absent'], 0)
        self.assertEqual(self.balance(rich), 200)
        self.assertEqual(self.balance(poor), 0)
        self.assertEqual(self.lesson_ledgers(rich), [])

        mixed = self.add_lesson(tid, [rich, hourly], day='2030-03-06', start='10:00', end='11:30', planned=100)
        self.mark(mixed, True)
        self.assertEqual(self.balance(rich), 100)
        self.assertEqual(self.balance(hourly), 350)
        amounts = {row['student_id']: row['delta'] for row in self.c.execute(
            "SELECT student_id, delta FROM ledger WHERE kind='lesson' AND note LIKE '%请假扣课时%'")}
        self.assertEqual(amounts, {rich: -100, hourly: -150})

    def test_teacher_and_parent_cannot_mark_or_undo(self):
        tid, teacher_user = self.teacher('Ethan')
        sid, parent = self.student('王星然')
        self.topup(sid, 3)
        lid = self.add_lesson(tid, [sid])
        for role, uid in (('teacher', teacher_user), ('parent', parent)):
            with self.assertRaises(teaching.AccessError):
                self.mark(lid, True, role=role, user=uid)
            with self.assertRaises(teaching.AccessError):
                self.mark(lid, False, role=role, user=uid)
        self.assertEqual(self.lesson_row(lid)['absent'], 0)
        self.assertEqual(self.balance(sid), 300)
        self.mark(lid, True)
        for role, uid in (('teacher', teacher_user), ('parent', parent)):
            with self.assertRaises(teaching.AccessError):
                self.undo(lid, role=role, user=uid)
        self.assertEqual(self.lesson_row(lid)['absent'], 1)
        self.assertEqual(self.balance(sid), 200)

    def test_absence_is_not_a_report_and_is_not_teacher_pay(self):
        tid, _ = self.teacher('Christina')
        sid, _ = self.student('已写对比')
        self.topup(sid, 4)
        absent = self.add_lesson(tid, [sid], day='2030-04-02')
        self.mark(absent, True)
        charge = self.lesson_ledgers(sid)[0]
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
            VALUES(?,?,100,'不应出现','作业','反馈',?,?)''', (absent, sid, charge['id'], self.owner))
        attended = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?,?,?,?,100,'教室','completed',?,?)''',
            (tid, '数学', '2030-04-03T16:00', '2030-04-03T17:00', self.owner, uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (attended, sid))
        attended_ledger = self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson','2030-04-03','上课',?,?)",
            (sid, -100, self.owner, uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
            VALUES(?,?,100,'内容','作业','反馈',?,?)''', (attended, sid, attended_ledger, self.owner))
        counted = {row['lesson_id'] for row in payroll.confirmed_rows(self.c, date(2030, 4, 1), date(2030, 4, 30))}
        self.assertIn(attended, counted)
        self.assertNotIn(absent, counted)
        self.assertEqual(payroll.absence_pay_clause(), ' AND COALESCE(l.absent, 0)=0')
        shown = teaching.state_for(self.c, {'id': self.owner, 'role': 'owner'})
        payload = next(lesson for lesson in shown['lessons'] if lesson['id'] == absent)
        self.assertFalse(payload['recorded'])
        with self.assertRaises(ValueError) as error:
            teaching.save_reports(self.c, {'id': self.owner, 'role': 'owner'}, {
                'lesson_id': absent, 'version': self.lesson_row(absent)['version'], 'reports': [],
            }, server.units, 'complete')
        self.assertIn('不用填写课后记录', str(error.exception))
        with self.assertRaises(ValueError):
            teaching.cancel_lesson(self.c, {'id': self.owner, 'role': 'owner'}, {
                'lesson_id': absent, 'version': self.lesson_row(absent)['version'], 'reason': '取消',
            }, lambda raw, label, maximum: str(raw))
        with self.assertRaises(ValueError):
            teaching.save_lesson(self.c, {'id': self.owner, 'role': 'owner'}, {
                'lesson_id': absent, 'version': self.lesson_row(absent)['version'],
            }, server.units, lambda raw, label, maximum: str(raw))

    def test_completed_lesson_and_a_stale_version_are_refused(self):
        tid, _ = self.teacher()
        sid, _ = self.student('已上完')
        self.topup(sid, 2)
        lid = self.add_lesson(tid, [sid])
        self.c.execute("UPDATE lessons SET status='completed' WHERE id=?", (lid,))
        with self.assertRaises(ValueError):
            self.mark(lid, False)
        self.assertEqual(self.balance(sid), 200)
        self.c.execute("UPDATE lessons SET status='scheduled' WHERE id=?", (lid,))
        version = self.lesson_row(lid)['version']
        self.mark(lid, False)
        with self.assertRaises(ValueError):
            self.mark(lid, True, version=version)
        self.assertEqual(self.lesson_row(lid)['absent_charge'], 0)
        self.assertEqual(self.balance(sid), 200)
        with self.assertRaises(ValueError):
            teaching.mark_absent(self.c, {'id': self.owner, 'role': 'owner'}, {
                'lesson_id': lid, 'version': self.lesson_row(lid)['version'], 'charge': 'yes',
            }, server.units)

    def test_migration_adds_flags_without_rewriting_rows(self):
        tid, _ = self.teacher('旧老师')
        sid, _ = self.student('旧学生')
        self.topup(sid, 4)
        lid = self.add_lesson(tid, [sid], title='保留这节课')
        type_id = self.c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
        subject_id = self.c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
        self.c.execute('UPDATE lessons SET course_type_id=?, subject_id=? WHERE id=?', (type_id, subject_id, lid))
        before = self.c.execute(
            'SELECT id, status, title, planned_units, starts_at, ends_at, cancel_reason FROM lessons WHERE id=?', (lid,)).fetchone()
        balance = self.balance(sid)
        ledger = self.c.execute('SELECT id, delta, kind, note FROM ledger WHERE student_id=? ORDER BY id', (sid,)).fetchall()
        self.c.execute('ALTER TABLE lessons DROP COLUMN absent')
        self.c.execute('ALTER TABLE lessons DROP COLUMN absent_charge')
        teaching.schema(self.c)
        teaching.schema(self.c)
        after = self.c.execute(
            'SELECT id, status, title, planned_units, starts_at, ends_at, cancel_reason FROM lessons WHERE id=?', (lid,)).fetchone()
        flags = self.c.execute('SELECT absent, absent_charge FROM lessons WHERE id=?', (lid,)).fetchone()
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual((flags['absent'], flags['absent_charge']), (0, 0))
        self.assertEqual(self.balance(sid), balance)
        self.assertEqual(ledger, self.c.execute('SELECT id, delta, kind, note FROM ledger WHERE student_id=? ORDER BY id', (sid,)).fetchall())
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM lesson_absence_charges').fetchone()[0], 0)

    def test_stopping_a_course_reverses_a_future_charged_absence(self):
        tid, _ = self.teacher('Vincent')
        sid, _ = self.student('停课学生')
        self.topup(sid, 3)
        lid = self.add_lesson(tid, [sid], day='2035-06-02')
        self.mark(lid, True)
        self.assertEqual(self.balance(sid), 200)
        deletion.stop_course(self.c, {'id': self.owner, 'role': 'owner'}, {'student_id': sid})
        self.assertEqual(self.balance(sid), 300)
        row = self.lesson_row(lid)
        self.assertEqual(row['status'], 'cancelled')
        self.assertEqual((row['absent'], row['absent_charge']), (0, 0))
        self.assertEqual(self.pools(sid), (300, 0))


if __name__ == '__main__':
    unittest.main()
