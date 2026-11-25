"""One back-dated pack can be rewritten to Helen's exact paid and gift numbers."""
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(tempfile.mkdtemp()) / 'fix-pack.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server

SCRIPT = ROOT / 'scripts' / 'fix_prior_pack.py'


class FixPriorPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def _student(self, name):
        with server.connect() as c:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (('045' + uuid.uuid4().hex)[:15], name + '家长', 'x')).lastrowid
            profile = c.execute('INSERT INTO student_profiles(name) VALUES(?)', (name,)).lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES(?, '新加坡数学', ?, ?, 0)",
                (name, parent, profile)).lastrowid
            actor = c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
            if not actor:
                actor_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                    (('045' + uuid.uuid4().hex)[:15], 'Helen', 'x')).lastrowid
            else:
                actor_id = actor['id']
            if not c.execute('SELECT 1 FROM organization_owners').fetchone():
                c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (actor_id,))
            c.commit()
            return sid, actor_id

    def _pack(self, sid, actor, purchased, gifted, paid_left, gift_left, cash, day, batch_id=None):
        with server.connect() as c:
            request = uuid.uuid4().hex
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,paid_delta,gift_delta,split_known)
                VALUES(?,?,'credit',?,?,?,?,?,?,1)''',
                (sid, purchased + gifted, day, '补录以前的包', actor, request, purchased, gifted)).lastrowid
            if batch_id:
                c.execute('''INSERT INTO credit_batches(id,student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents,unit_fees)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (batch_id, sid, lid, purchased, gifted, paid_left, gift_left, day, cash, '[1]'))
                bid = batch_id
            else:
                bid = c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents,unit_fees)
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                    (sid, lid, purchased, gifted, paid_left, gift_left, day, cash, '[1]')).lastrowid
            c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)',
                (lid, bid, purchased, gifted))
            used = purchased - paid_left
            if used:
                hid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,paid_delta,gift_delta,split_known)
                    VALUES(?,?,'lesson',?,?,?,?,?,0,1)''',
                    (sid, -used, day, '补录已用课时，没有对应课程', actor, request + '-used', -used)).lastrowid
                c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,0,0)',
                    (hid, bid, -used))
            c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,?)',
                (lid, cash, 'bank', '', actor))
            c.execute('''INSERT INTO vouchers(number,kind,status,student_id,student_name,course,ledger_id,lesson_date,paid_units,gift_units,amount_cents,created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('CZ-TEST-' + str(bid), 'credit', 'approved', sid, '学生', '新加坡数学', lid, day, purchased, gifted, cash, actor))
            c.execute('UPDATE students SET balance=? WHERE id=?', (paid_left + gift_left, sid))
            c.commit()
            return bid, lid

    def _run(self, *args):
        done = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        return done.stdout

    def _fail(self, *args):
        done = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, env=os.environ.copy())
        self.assertNotEqual(done.returncode, 0)
        return done.stderr + done.stdout

    def test_aaron_pack_becomes_twenty_plus_one_with_thirteen_paid_left(self):
        sid, actor = self._student('Aaron')
        self._pack(sid, actor, 1400, 0, 0, 0, 240000, '2026-09-05')
        dry = self._run('--student', 'Aaron', '--total', '20', '--gift', '1', '--remaining-paid', '13', '--remaining-gift', '1')
        self.assertIn('DRY-RUN', dry)
        self.assertIn('未写入', dry)
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 0)
        self._run('--student', 'Aaron', '--total', '20', '--gift', '1', '--remaining-paid', '13', '--remaining-gift', '1', '--apply')
        again = self._run('--student', 'Aaron', '--total', '20', '--gift', '1', '--remaining-paid', '13', '--remaining-gift', '1', '--apply')
        self.assertIn('已经是这些数字', again)
        with server.connect() as c:
            batch = c.execute('SELECT purchased, gifted, paid_left, gift_left, unit_fees FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['purchased'], batch['gifted'], batch['paid_left'], batch['gift_left']), (2000, 100, 1300, 100))
            self.assertEqual(batch['unit_fees'], '')
            credit = c.execute("SELECT delta, lesson_date, gift_delta FROM ledger WHERE student_id=? AND kind='credit'", (sid,)).fetchone()
            self.assertEqual((credit['delta'], credit['lesson_date'], credit['gift_delta']), (2100, '2026-09-05', 100))
            history = c.execute("SELECT delta, paid_delta, gift_delta FROM ledger WHERE student_id=? AND note LIKE '%补录已用%'", (sid,)).fetchone()
            self.assertEqual((history['delta'], history['paid_delta'], history['gift_delta']), (-700, -700, 0))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_reports WHERE student_id=?', (sid,)).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT cash.cash_delta FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?', (sid,)).fetchone()['cash_delta'], 240000)
            voucher = c.execute('SELECT paid_units, gift_units, amount_cents, lesson_date FROM vouchers WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((voucher['paid_units'], voucher['gift_units'], voucher['amount_cents'], voucher['lesson_date']), (2000, 100, 240000, '2026-09-05'))
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 1400)
            self.assertTrue(c.execute("SELECT 1 FROM audit_log WHERE summary LIKE '%更正补录 Aaron%'").fetchone())

    def test_fractional_gift_and_edward_batch_are_exact(self):
        shawn, actor = self._student('Shawn Lyu')
        self._pack(shawn, actor, 2000, 67, 833, 67, 255000, '2026-05-03')
        edward, _actor = self._student('Edward')
        self._pack(edward, actor, 1333, 0, 900, 0, 170000, '2026-10-26', batch_id=117)
        self._run('--student', 'Shawn Lyu', '--total', '20', '--gift', '1.33', '--remaining-paid', '8.33', '--remaining-gift', '1.33', '--apply')
        self._run('--student', 'Edward', '--batch', '117', '--total', '13.33', '--gift', '0.67', '--remaining-paid', '9', '--remaining-gift', '0.67', '--apply')
        with server.connect() as c:
            shawn_pack = c.execute('SELECT purchased, gifted, paid_left, gift_left FROM credit_batches WHERE student_id=?', (shawn,)).fetchone()
            self.assertEqual((shawn_pack['purchased'], shawn_pack['gifted'], shawn_pack['paid_left'], shawn_pack['gift_left']), (2000, 133, 833, 133))
            self.assertEqual(c.execute('SELECT lesson_date FROM ledger WHERE student_id=? AND kind=?', (shawn, 'credit')).fetchone()['lesson_date'], '2026-05-03')
            self.assertEqual(c.execute('SELECT cash_delta FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?', (shawn,)).fetchone()['cash_delta'], 255000)
            edward_pack = c.execute('SELECT id, purchased, gifted, paid_left, gift_left FROM credit_batches WHERE id=117').fetchone()
            self.assertEqual((edward_pack['purchased'], edward_pack['gifted'], edward_pack['paid_left'], edward_pack['gift_left']), (1333, 67, 900, 67))
            history = c.execute("SELECT delta FROM ledger WHERE student_id=? AND note LIKE '%补录已用%'", (edward,)).fetchone()
            self.assertEqual(history['delta'], -433)
            self.assertEqual(c.execute('SELECT amount_cents, lesson_date FROM vouchers WHERE ledger_id=(SELECT ledger_id FROM credit_batches WHERE id=117)').fetchone()['amount_cents'], 170000)

    def test_a_real_lesson_stays_deducted_and_does_not_pay_twice(self):
        sid, actor = self._student('Aaron Real')
        _bid, _lid = self._pack(sid, actor, 1400, 0, 1000, 0, 240000, '2026-09-05')
        with server.connect() as c:
            batch = c.execute('SELECT id FROM credit_batches WHERE student_id=?', (sid,)).fetchone()['id']
            teacher_user = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                (('045' + uuid.uuid4().hex)[:15], 'Vincent', 'x')).lastrowid
            teacher = c.execute('INSERT INTO teachers(user_id, subject) VALUES(?,?)', (teacher_user, '新加坡数学')).lastrowid
            day = '2026-11-02'
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?,?,?,?,100,'教室','completed',?,?)''',
                (teacher, '新加坡数学', day + 'T16:00', day + 'T17:00', actor, uuid.uuid4().hex)).lastrowid
            ledger = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,paid_delta,gift_delta,split_known)
                VALUES(?,?,'lesson',?,'上课',?,?,?,0,1)''', (sid, -100, day, actor, uuid.uuid4().hex, -100)).lastrowid
            c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,0,0)', (ledger, batch, -100))
            c.execute('UPDATE credit_batches SET paid_left=paid_left-100 WHERE id=?', (batch,))
            c.execute('UPDATE students SET balance=balance-100 WHERE id=?', (sid,))
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'上过了','','',?,?)''', (lesson, sid, ledger, actor))
            c.commit()
        text = self._run('--student', 'Aaron Real', '--total', '20', '--gift', '1', '--remaining-paid', '13', '--remaining-gift', '1', '--apply')
        self.assertIn('已经上过这些课', text)
        with server.connect() as c:
            batch = c.execute('SELECT paid_left, gift_left, purchased, gifted FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['purchased'], batch['gifted'], batch['paid_left'], batch['gift_left']), (2000, 100, 1200, 100))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lesson_reports WHERE student_id=?', (sid,)).fetchone()[0], 1)
            taught = c.execute("SELECT delta, paid_delta FROM ledger WHERE student_id=? AND note='上课'", (sid,)).fetchone()
            self.assertEqual((taught['delta'], taught['paid_delta']), (-100, -100))
            self.assertEqual(c.execute('SELECT cash.cash_delta FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?', (sid,)).fetchone()['cash_delta'], 240000)

    def test_a_real_lesson_larger_than_the_corrected_remainder_is_refused(self):
        sid, actor = self._student('Too Much')
        self._pack(sid, actor, 500, 0, 500, 0, 100000, '2026-08-01')
        with server.connect() as c:
            batch = c.execute('SELECT id FROM credit_batches WHERE student_id=?', (sid,)).fetchone()['id']
            ledger = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,?,'lesson','2026-11-03','上课',?,?)''', (sid, -400, actor, uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,0,0)', (ledger, batch, -400))
            c.execute('UPDATE credit_batches SET paid_left=100 WHERE id=?', (batch,))
            c.commit()
        text = self._fail('--student', 'Too Much', '--total', '2', '--gift', '0', '--remaining-paid', '1', '--remaining-gift', '0', '--apply')
        self.assertIn('没有改', text)
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT purchased, paid_left FROM credit_batches WHERE student_id=?', (sid,)).fetchone()['purchased'], 500)


if __name__ == '__main__':
    unittest.main()
