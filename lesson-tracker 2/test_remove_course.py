"""Deleting a course means 加错了. A live top-up blocks it; a voided one does not."""
import datetime as dt
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'remove.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import accounting
import auditlog
import credit_batches
import deletion
import server
import timeline
import vouchers


class RemoveCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def owner_and_parent(self, c, phone):
        uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Helen', 'x', 'admin')", (phone,)).lastrowid
        c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
        parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, '家长', 'x', 'parent')", ('9' + phone,)).lastrowid
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        owner = {'id': uid, 'role': 'owner'}
        return owner, parent, profile

    def course(self, c, parent, profile, name, balance=0, subject='数学'):
        return c.execute(
            'INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES(?,?,?,?,?)',
            (name, subject, parent, profile, balance)).lastrowid

    def teacher(self, c, owner):
        uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Kelsey', 'x', 'parent')",
            ('8' + uuid.uuid4().hex[:8],)).lastrowid
        return c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (uid, '数学')).lastrowid

    def _topup(self, c, owner, sid, cents=15000):
        ledger = c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit','2026-11-01','充值',?,?)",
            (sid, owner['id'], uuid.uuid4().hex)).lastrowid
        credit_batches.apply(c, ledger, 'credit', {'amount': '2', 'gift_amount': '0', 'pack_label': '数学 2'}, server.units)
        accounting.record_cash(c, ledger, cents, 'bank', '', owner['id'])
        vid = vouchers.issue_ledger(c, owner, ledger)
        return ledger, vid

    def test_mistake_keeps_the_course_on_file_and_undo_puts_it_back(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000001')
            sid = self.course(c, parent, profile, 'Mia', 200)
            tid = self.teacher(c, owner)
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2027-04-01T16:00','2027-04-01T17:00',100,'教室','scheduled',?,?)''',
                (tid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (future, sid))
            result = deletion.remove_course(c, owner, {'student_id': sid, 'reason': 'withdraw'})
            self.assertTrue(result['voided'])
            self.assertFalse(result['deleted'])
            self.assertEqual(result['reason'], 'mistake')
            row = c.execute('SELECT archived, voided, balance, void_reason FROM students WHERE id=?', (sid,)).fetchone()
            self.assertEqual((row['archived'], row['voided'], row['balance'], row['void_reason']), (1, 1, 0, '加错了'))
            self.assertIsNone(c.execute("SELECT 1 FROM vouchers WHERE kind='stop' AND student_id=?", (sid,)).fetchone())
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (future,)).fetchone()['status'], 'cancelled')
            event = c.execute("SELECT summary, actor_id FROM profile_events WHERE student_id=? AND action='mistake'", (sid,)).fetchone()
            self.assertIn('加错了', event['summary'])
            self.assertIn('数学', event['summary'])
            self.assertEqual(event['actor_id'], owner['id'])
            listed = [item for item in c.execute('SELECT id, archived, voided FROM students')]
            hidden = [item['id'] for item in listed if item['archived'] and not item['voided']]
            self.assertNotIn(sid, hidden)
            last = auditlog.last_for(c, owner)
            self.assertIn('加错了', last['entry']['summary'])
            undone = auditlog.undo(c, owner, last['entry']['id'])
            auditlog.mark_undone(c, undone['undone'], owner['id'])
            back = c.execute('SELECT archived, voided, balance FROM students WHERE id=?', (sid,)).fetchone()
            self.assertEqual((back['archived'], back['voided'], back['balance']), (0, 0, 200))
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (future,)).fetchone()['status'], 'scheduled')
            self.assertIsNone(c.execute("SELECT 1 FROM profile_events WHERE student_id=? AND action='mistake'", (sid,)).fetchone())
            self.assertIsNone(auditlog.last_for(c, owner)['entry'])

    def test_live_topup_blocks_until_the_receipt_is_voided(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000002')
            attended = self.course(c, parent, profile, 'Noah', subject='数学')
            paid = self.course(c, parent, profile, 'Noah', subject='英语', balance=0)
            tid = self.teacher(c, owner)
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2026-10-01T16:00','2026-10-01T17:00',100,'教室','completed',?,?)''',
                (tid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (lesson, attended))
            deducted = self.course(c, parent, profile, 'Noah', subject='VCE 中数', balance=0)
            c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,-100,'lesson','2026-10-02','上课',?,?)",
                (deducted, owner['id'], uuid.uuid4().hex))
            _ledger, vid = self._topup(c, owner, paid)
            day = dt.date(2026, 11, 1)
            self.assertGreater(accounting.cash_breakdown(c, day, day)['received_cents'], 0)
            with self.assertRaises(ValueError) as attended_error:
                deletion.remove_course(c, owner, {'student_id': attended})
            self.assertIn('已经上过或写过记录', str(attended_error.exception))
            with self.assertRaises(ValueError) as deducted_error:
                deletion.remove_course(c, owner, {'student_id': deducted})
            self.assertIn('已经扣过课时', str(deducted_error.exception))
            with self.assertRaises(ValueError) as paid_error:
                deletion.remove_course(c, owner, {'student_id': paid, 'reason': 'withdraw'})
            self.assertEqual(str(paid_error.exception), '请先作废这门课的充值单据')
            self.assertIsNone(c.execute("SELECT 1 FROM vouchers WHERE kind='stop' AND student_id=?", (paid,)).fetchone())
            vouchers.void(c, owner, vid, server.units)
            self.assertEqual(accounting.cash_breakdown(c, day, day)['received_cents'], 0)
            self.assertEqual(deletion.course_blockers(c, paid), [])
            done = deletion.remove_course(c, owner, {'student_id': paid})
            self.assertTrue(done['voided'])
            self.assertIsNone(c.execute("SELECT 1 FROM vouchers WHERE kind='stop' AND student_id=?", (paid,)).fetchone())
            kept = c.execute('SELECT archived, voided FROM students WHERE id=?', (paid,)).fetchone()
            self.assertEqual((kept['archived'], kept['voided']), (1, 1))
            found = vouchers.search(c, owner, '', '', '', '', '')
            receipt = next(item for item in found['vouchers'] if item['id'] == vid)
            self.assertEqual(receipt['status_label'], '已作废')
            self.assertEqual(found['totals']['credit_cents'], 0)
            self.assertTrue(any(item['action'] == 'mistake' and '英语' in item['summary'] for item in timeline.for_staff(c)))
            self.assertTrue(any(item['action'] == 'void' for item in timeline.for_staff(c)))

    def test_voided_or_reversed_credit_is_not_money_and_blank_course_stays_listed(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000003')
            reversed_course = self.course(c, parent, profile, 'Leo', 0, '数学')
            credit = c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,200,'credit','2026-11-01','充值',?,?)",
                (reversed_course, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of) VALUES(?,-200,'reversal','2026-11-02','冲回',?,?,?)",
                (reversed_course, owner['id'], uuid.uuid4().hex, credit))
            c.execute(
                'INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,recorded_by) VALUES(?,2000,?,?)',
                (credit, 'bank', owner['id']))
            self.assertEqual(deletion.course_blockers(c, reversed_course), [])
            blank = self.course(c, parent, profile, 'Leo', 0, '英语')
            c.execute('''INSERT INTO vouchers(number,kind,status,student_id,student_name,course,lesson_date,created_by)
                VALUES('TZ-2026-0099','adjust','pending',?,?,?,'2026-11-01',?)''',
                (blank, 'Leo', '英语', owner['id']))
            self.assertEqual(deletion.course_blockers(c, blank), ['请先作废这门课的充值单据'])
            c.execute("UPDATE vouchers SET status='void' WHERE student_id=? AND kind='adjust'", (blank,))
            self.assertEqual(deletion.course_blockers(c, blank), [])
            done = deletion.remove_course(c, owner, {'student_id': blank})
            self.assertTrue(done['voided'])
            self.assertIsNotNone(c.execute('SELECT 1 FROM students WHERE id=?', (blank,)).fetchone())
            self.assertIsNone(c.execute("SELECT 1 FROM vouchers WHERE student_id=? AND kind='stop'", (blank,)).fetchone())
            self.assertEqual(c.execute("SELECT status FROM vouchers WHERE student_id=? AND kind='adjust'", (blank,)).fetchone()['status'], 'void')

    def test_archiving_a_student_is_logged_for_the_withdrawn_list(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000005')
            sid = self.course(c, parent, profile, 'Rita', 0, '数学')
            deletion.remove(c, owner, {'kind': 'student', 'id': sid})
            self.assertEqual(c.execute('SELECT archived FROM students WHERE id=?', (sid,)).fetchone()['archived'], 1)
            event = c.execute("SELECT action, summary, actor_id FROM profile_events WHERE profile_id=? AND action='withdraw'", (profile,)).fetchone()
            self.assertEqual(event['action'], 'withdraw')
            self.assertIn('退学', event['summary'])
            self.assertEqual(event['actor_id'], owner['id'])
            flagged = c.execute('''SELECT 1 FROM profile_audit a JOIN students s ON s.id=a.student_id
                WHERE s.profile_id=? AND a.action='archived' ''', (profile,)).fetchone()
            self.assertIsNotNone(flagged)

    def test_report_and_cleanup_leave_real_withdrawals(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000004')
            mistake = self.course(c, parent, profile, 'Ivy', subject='数学')
            real = self.course(c, parent, profile, 'Ivy', subject='英语')
            tid = self.teacher(c, owner)
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2026-09-01T16:00','2026-09-01T17:00',100,'教室','completed',?,?)''',
                (tid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (lesson, real))
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2027-05-01T16:00','2027-05-01T17:00',100,'教室','scheduled',?,?)''',
                (tid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (future, mistake))
            deletion.stop_course(c, owner, {'student_id': mistake})
            deletion.stop_course(c, owner, {'student_id': real})
            mistake_id = c.execute("SELECT id FROM vouchers WHERE student_id=? AND kind='stop'", (mistake,)).fetchone()['id']
            real_id = c.execute("SELECT id FROM vouchers WHERE student_id=? AND kind='stop'", (real,)).fetchone()['id']
        script_dir = Path(__file__).with_name('scripts')
        env = {**os.environ, 'LESSON_DB': str(DB)}
        report = subprocess.run([sys.executable, str(script_dir / 'report_withdrawals.py')], env=env, capture_output=True, text=True, check=True)
        self.assertIn('可能录错', report.stdout)
        self.assertIn(f'单据{mistake_id}', report.stdout)
        self.assertIn(f'单据{real_id}', report.stdout)
        dry = subprocess.run(
            [sys.executable, str(script_dir / 'void_mistaken_courses.py'), '--ids', f'{mistake_id},{real_id}'],
            env=env, capture_output=True, text=True, check=True)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('不改', dry.stdout)
        with sqlite3.connect(DB) as raw:
            self.assertEqual(raw.execute("SELECT status FROM vouchers WHERE id=?", (mistake_id,)).fetchone()[0], 'pending')
        applied = subprocess.run(
            [sys.executable, str(script_dir / 'void_mistaken_courses.py'), '--ids', f'{mistake_id},{real_id}', '--apply'],
            env=env, capture_output=True, text=True, check=True)
        self.assertIn('已作废 1 张', applied.stdout)
        with sqlite3.connect(DB) as raw:
            raw.row_factory = sqlite3.Row
            self.assertEqual(raw.execute('SELECT status FROM vouchers WHERE id=?', (mistake_id,)).fetchone()['status'], 'void')
            self.assertEqual(raw.execute('SELECT voided FROM students WHERE id=?', (mistake,)).fetchone()['voided'], 1)
            self.assertEqual(raw.execute('SELECT status FROM vouchers WHERE id=?', (real_id,)).fetchone()['status'], 'pending')
            self.assertEqual(raw.execute('SELECT voided FROM students WHERE id=?', (real,)).fetchone()['voided'], 0)
        again = subprocess.run([sys.executable, str(script_dir / 'report_withdrawals.py')], env=env, capture_output=True, text=True, check=True)
        self.assertNotIn(f'单据{mistake_id}', again.stdout)
        self.assertIn(f'单据{real_id}', again.stdout)


PORT = '8784'


class RemoveCourseBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        if not Path('/usr/local/bin/google-chrome').exists():
            raise unittest.SkipTest('chrome is not installed')
        cls.db = str(Path(tempfile.mkdtemp()) / 'remove-browser.sqlite3')
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': cls.db, 'LESSON_SECURE_COOKIE': '0'}
        cls.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('server.py')), '--port', PORT],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(50):
            import urllib.request
            try:
                urllib.request.urlopen('http://127.0.0.1:%s/health' % PORT, timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('remove-course browser server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_delete_has_no_reason_and_the_course_stays_findable(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 800})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('#undo-last')
            page.click('.sidebar [data-view="overview"]')
            page.wait_for_selector('#study-filter [data-study=withdrawn]')
            self.assertEqual(page.locator('#study-filter [data-study=studying]').inner_text(), '在读')
            self.assertEqual(page.locator('#study-filter [data-study=withdrawn]').inner_text(), '退学')
            page.wait_for_selector('#student-list .year-fold > summary')
            page.locator('#student-list .year-fold > summary').first.click()
            page.wait_for_selector('[data-open-student]')
            page.locator('[data-open-student]').first.click()
            page.wait_for_selector('[data-remove-course]')
            self.assertEqual(page.locator('text=把已停课的以后课移过来').count(), 0)
            self.assertEqual(page.locator('[data-course-tab=current]').inner_text(), '在上')
            self.assertIn('已停', page.locator('[data-course-tab=stopped]').inner_text())
            self.assertGreater(page.locator('text=操作记录').count(), 0)
            page.locator('[data-add-course]').first.click()
            page.wait_for_selector('#modal-form select[name=subject_id]')
            subject = page.locator('#modal-form select[name=subject_id] option').nth(1)
            page.select_option('#modal-form select[name=subject_id]', subject.get_attribute('value'))
            kind = page.locator('#modal-form select[name=course_type_id] option').nth(1)
            page.select_option('#modal-form select[name=course_type_id]', kind.get_attribute('value'))
            page.click('#modal-form [type=submit]')
            page.wait_for_function('''() => !document.querySelector('#modal[open]')''')
            page.wait_for_selector('[data-remove-course]')
            page.locator('[data-remove-course]').last.click()
            page.wait_for_selector('#modal-form')
            self.assertEqual(page.locator('#modal-form select[name=reason]').count(), 0)
            blocked = page.locator('#modal-title').inner_text() == '不能删除这门课'
            if blocked:
                self.assertGreater(page.locator('#modal-form .error').count(), 0)
                page.click('#modal-form [type=submit]')
            else:
                self.assertIn('加错了', page.locator('#modal-form').inner_text())
                page.click('#modal-form [type=submit]')
                page.wait_for_function('''() => (document.querySelector('#toast')?.textContent || '').includes('加错了')''')
                page.wait_for_selector('text=按加错了删除了课程')
                page.click('[data-course-tab=stopped]')
                self.assertGreater(page.locator('text=加错了，已删除').count(), 0)
            browser.close()


if __name__ == '__main__':
    unittest.main()
