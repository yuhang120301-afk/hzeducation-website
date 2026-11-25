"""Mistaken courses are voided. A real withdrawal still writes a 退课 receipt."""
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

import auditlog
import deletion
import server
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

    def test_mistake_voids_without_a_receipt_and_undo_puts_it_back(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000001')
            sid = self.course(c, parent, profile, 'Mia', 200)
            ledger = c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,200,'credit','2026-11-01','充值',?,?)",
                (sid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute(
                "INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on) VALUES(?,?,200,0,200,0,'2026-11-01')",
                (sid, ledger))
            tid = self.teacher(c, owner)
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2027-04-01T16:00','2027-04-01T17:00',100,'教室','scheduled',?,?)''',
                (tid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (future, sid))
            result = deletion.remove_course(c, owner, {'student_id': sid})
            self.assertTrue(result['voided'])
            self.assertFalse(result['deleted'])
            row = c.execute('SELECT archived, voided, balance FROM students WHERE id=?', (sid,)).fetchone()
            self.assertEqual((row['archived'], row['voided'], row['balance']), (1, 1, 0))
            self.assertIsNone(c.execute("SELECT 1 FROM vouchers WHERE kind='stop' AND student_id=?", (sid,)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM ledger WHERE id=?', (ledger,)).fetchone())
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (future,)).fetchone()['status'], 'cancelled')
            listed = [item for item in c.execute('SELECT id, archived, voided FROM students')]
            hidden = [item['id'] for item in listed if item['archived'] and not item['voided']]
            self.assertNotIn(sid, hidden)
            last = auditlog.last_for(c, owner)
            self.assertTrue(last['entry']['money'])
            self.assertIn('加错了', last['entry']['summary'])
            undone = auditlog.undo(c, owner, last['entry']['id'])
            auditlog.mark_undone(c, undone['undone'], owner['id'])
            back = c.execute('SELECT archived, voided, balance FROM students WHERE id=?', (sid,)).fetchone()
            self.assertEqual((back['archived'], back['voided'], back['balance']), (0, 0, 200))
            self.assertIsNotNone(c.execute('SELECT 1 FROM ledger WHERE id=?', (ledger,)).fetchone())
            self.assertEqual(c.execute('SELECT status FROM lessons WHERE id=?', (future,)).fetchone()['status'], 'scheduled')
            self.assertIsNone(auditlog.last_for(c, owner)['entry'])

    def test_attended_or_paid_course_can_only_be_withdrawn(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000002')
            attended = self.course(c, parent, profile, 'Noah', subject='数学')
            paid = self.course(c, parent, profile, 'Noah', subject='英语')
            tid = self.teacher(c, owner)
            lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
                VALUES(?, '数学','2026-10-01T16:00','2026-10-01T17:00',100,'教室','completed',?,?)''',
                (tid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (lesson, attended))
            ledger = c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,200,'credit','2026-11-01','收款',?,?)",
                (paid, owner['id'], uuid.uuid4().hex)).lastrowid
            c.execute(
                'INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,recorded_by) VALUES(?,2000,?,?)',
                (ledger, 'cash', owner['id']))
            with self.assertRaises(ValueError):
                deletion.remove_course(c, owner, {'student_id': attended, 'reason': 'mistake'})
            with self.assertRaises(ValueError):
                deletion.remove_course(c, owner, {'student_id': paid, 'reason': 'other', 'note': '录重了'})
            withdrawn = deletion.remove_course(c, owner, {'student_id': attended, 'reason': 'withdraw'})
            self.assertTrue(withdrawn['archived'])
            self.assertFalse(withdrawn.get('voided'))
            self.assertIsNotNone(c.execute("SELECT 1 FROM vouchers WHERE kind='stop' AND student_id=? AND status!='void'", (attended,)).fetchone())
            found = vouchers.search(c, owner, '', '', '', '', '')
            self.assertTrue(any(item['student_id'] == attended and item['kind'] == 'stop' for item in found['vouchers']))

    def test_other_reason_is_stored_and_blank_course_is_removed(self):
        with server.connect() as c:
            owner, parent, profile = self.owner_and_parent(c, '0422000003')
            noted = self.course(c, parent, profile, 'Leo', 0, '数学')
            c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'adjustment','2026-11-01','备注',?,?)",
                (noted, owner['id'], uuid.uuid4().hex))
            blank = self.course(c, parent, profile, 'Leo', 0, '英语')
            with self.assertRaises(ValueError):
                deletion.remove_course(c, owner, {'student_id': noted, 'reason': 'other'})
            done = deletion.remove_course(c, owner, {'student_id': noted, 'reason': 'other', 'note': '选错课型'})
            self.assertTrue(done['voided'])
            self.assertEqual(c.execute('SELECT void_reason FROM students WHERE id=?', (noted,)).fetchone()['void_reason'], '选错课型')
            gone = deletion.remove_course(c, owner, {'student_id': blank})
            self.assertTrue(gone['deleted'])
            self.assertIsNone(c.execute('SELECT 1 FROM students WHERE id=?', (blank,)).fetchone())
            self.assertIsNone(c.execute("SELECT 1 FROM vouchers WHERE student_name='Leo' AND course='数学' AND kind='stop' AND student_id=?", (blank,)).fetchone())

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

    def test_one_delete_button_and_undo_in_the_top_bar(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 800})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('#undo-last')
            for view in ('today', 'overview', 'finance', 'audit', 'setup'):
                page.click('.sidebar [data-view="%s"]' % view)
                page.wait_for_selector('#undo-last')
                self.assertEqual(page.locator('#undo-last').inner_text(), '撤销上一步')
            page.click('.sidebar [data-view="overview"]')
            page.wait_for_selector('[data-open-student]')
            page.locator('[data-open-student]').first.click()
            page.wait_for_selector('[data-remove-course]')
            self.assertEqual(page.locator('text=停课/删除这门课').count(), 0)
            page.locator('[data-remove-course]').first.click()
            page.wait_for_selector('#modal-form select[name=reason]')
            options = page.locator('#modal-form select[name=reason] option').all_inner_texts()
            selected = page.locator('#modal-form select[name=reason]').input_value()
            if '加错了' in options:
                self.assertEqual(selected, 'mistake')
            else:
                self.assertEqual(options, ['退课'])
                self.assertEqual(selected, 'withdraw')
            page.click('#modal-form [type=submit]')
            page.wait_for_function('''() => { const el = document.querySelector('#toast'); return el && getComputedStyle(el).display !== 'none' && /删除|退课/.test(el.textContent || ''); }''')
            self.assertTrue('删除' in page.locator('#toast').inner_text() or '退课' in page.locator('#toast').inner_text())
            page.wait_for_function('''() => !document.querySelector('#modal[open]')''')
            page.click('#undo-last')
            confirm = page.locator('#modal[open] [type=submit]')
            if confirm.count():
                confirm.click()
            page.wait_for_function('''() => (document.querySelector('#toast')?.textContent || '').includes('已撤销')''')
            self.assertIn('已撤销', page.locator('#toast').inner_text())
            browser.close()


if __name__ == '__main__':
    unittest.main()
