"""Back-dated packs get the gift that was typed, or the price-list gift, and nothing else moves."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(tempfile.mkdtemp()) / 'redo-gifts.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import credit_batches
import server

SCRIPT = ROOT / 'scripts' / 'redo_prior_packs.py'


class RedoPriorPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def _course(self, name, course, type_name):
        with server.connect() as c:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (('047' + uuid.uuid4().hex)[:15], name + '家长', 'x')).lastrowid
            profile = c.execute('INSERT INTO student_profiles(name) VALUES(?)', (name,)).lastrowid
            type_id = c.execute('SELECT id FROM course_types WHERE name=?', (type_name,)).fetchone()['id']
            subject_id = c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id)
                VALUES(?,?,?,?,0,?,?)''', (name, course, parent, profile, subject_id, type_id)).lastrowid
            actor = c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
            if not actor:
                actor_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
                    (('047' + uuid.uuid4().hex)[:15], 'Helen', 'x')).lastrowid
                c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (actor_id,))
            else:
                actor_id = actor['id']
                if not c.execute('SELECT 1 FROM organization_owners').fetchone():
                    c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (actor_id,))
            c.commit()
            return sid, actor_id

    def _pack(self, sid, actor, lessons, left, gift=0, note='补录以前的包', cash=200000, day='2026-10-03'):
        with server.connect() as c:
            units = lessons * 100
            gifts = gift * 100
            remain = left * 100
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,gift_delta,paid_delta,split_known)
                VALUES(?,?,'credit',?,?,?, ?,?, ?,1)''',
                (sid, units + gifts, day, note, actor, uuid.uuid4().hex, gifts, units)).lastrowid
            bid = c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,total_cents)
                VALUES(?,?,?,?,?,?,?,?)''', (sid, lid, units, gifts, remain, gifts, day, cash)).lastrowid
            c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)',
                (lid, bid, units, gifts))
            c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,?)',
                (lid, cash, 'bank', '', actor))
            c.execute('UPDATE students SET balance=balance+? WHERE id=?', (remain + gifts, sid))
            c.commit()
            return lid

    def _run(self, apply=False):
        cmd = [sys.executable, str(SCRIPT)] + (['--apply'] if apply else [])
        done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_paid_hours_are_spent_before_gift_hours(self):
        sid, actor = self._course('顺序', '数学', '一对一')
        with server.connect() as c:
            self._pack(sid, actor, 2, 2, gift=1)
            lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,0,'lesson','2026-11-01','上课',?,?)''', (sid, actor, uuid.uuid4().hex)).lastrowid
            credit_batches.consume(c, lid, sid, 200)
            batch = c.execute('SELECT paid_left, gift_left FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['paid_left'], batch['gift_left']), (0, 100))
            c.rollback()

    def test_catalog_gift_is_added_once_and_cash_stays(self):
        sid, actor = self._course('Mia', '数学', '一对一')
        self._pack(sid, actor, 20, 8)
        dry = self._run(False)
        self.assertIn('DRY-RUN', dry)
        self.assertIn('本次补上 1', dry)
        self.assertIn('未写入', dry)
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 800)
        applied = self._run(True)
        self.assertIn('APPLY', applied)
        self.assertIn('已写入', applied)
        again = self._run(True)
        self.assertIn('已经是这个数', again)
        self.assertNotIn('本次补上 1', again.split('UNKNOWN')[0] if False else again)
        with server.connect() as c:
            batch = c.execute('SELECT gifted, gift_left, paid_left, purchased FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['gifted'], batch['gift_left'], batch['paid_left'], batch['purchased']), (100, 100, 800, 2000))
            self.assertEqual(c.execute('SELECT lesson_date FROM ledger WHERE student_id=? AND kind=?', (sid, 'credit')).fetchone()['lesson_date'], '2026-10-03')
            self.assertEqual(c.execute('''SELECT COALESCE(SUM(cash.cash_delta),0) FROM cash_entries cash
                JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?''', (sid,)).fetchone()[0], 200000)
            self.assertEqual(c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'], 900)

    def test_a_logged_gift_wins_over_the_price_list(self):
        sid, actor = self._course('Lin', '数学', '一对一')
        self._pack(sid, actor, 20, 8, note='补录以前的包 · 还剩赠送 3 节')
        self._run(True)
        with server.connect() as c:
            batch = c.execute('SELECT gifted, gift_left, paid_left FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['gifted'], batch['gift_left'], batch['paid_left']), (300, 300, 800))

    def test_unknown_size_is_left_alone(self):
        sid, actor = self._course('Bo', '数学', '一对一')
        self._pack(sid, actor, 10, 4, cash=100000)
        text = self._run(True)
        self.assertIn('UNKNOWN', text)
        with server.connect() as c:
            batch = c.execute('SELECT gifted, paid_left FROM credit_batches WHERE student_id=?', (sid,)).fetchone()
            self.assertEqual((batch['gifted'], batch['paid_left']), (0, 400))
            self.assertEqual(c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id WHERE l.student_id=?', (sid,)).fetchone()[0], 100000)

    def test_singapore_maths_has_no_gift_to_add(self):
        sid, actor = self._course('Vic', '新加坡数学', '一对一')
        self._pack(sid, actor, 20, 20)
        text = self._run(True)
        self.assertIn('不送课', text)
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT gifted FROM credit_batches WHERE student_id=?', (sid,)).fetchone()['gifted'], 0)


if __name__ == '__main__':
    unittest.main()
