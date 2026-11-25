"""Teacher and parent portals only receive what each role is allowed to see."""
import http.cookiejar
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

PORT = '8798'


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ''

    def request(self, path, data=None):
        headers = {'Content-Type': 'application/json'}
        if data is not None:
            headers['X-CSRF-Token'] = self.csrf
        req = urllib.request.Request(
            'http://127.0.0.1:%s/api/%s' % (PORT, path),
            data=None if data is None else json.dumps(data).encode(),
            headers=headers)
        try:
            response = self.opener.open(req)
        except urllib.error.HTTPError as exc:
            response = exc
        return response.status, json.loads(response.read())

    def login(self, phone, password):
        status, _ = self.request('login', {'phone': phone, 'password': password})
        assert status == 200
        _, state = self.request('state')
        self.csrf = state['csrf']
        return state


class RolePortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': cls.tmp.name + '/roles.sqlite3', 'LESSON_SECURE_COOKIE': '0'}
        cls.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('server.py')), '--port', PORT],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(60):
            try:
                Client().request('state')
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('role portal server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)
        cls.tmp.cleanup()

    def test_teacher_is_read_only_except_records_and_own_pay(self):
        teacher = Client()
        state = teacher.login('0400000011', 'TutorDemo2026!')
        self.assertEqual(state['user']['role'], 'teacher')
        self.assertTrue(state['lessons'])
        self.assertTrue(all(lesson['teacher_id'] == state['user']['teacher_id'] for lesson in state['lessons']))
        self.assertTrue(all('credit_batches' not in student for student in state['students']))
        self.assertTrue(all('balance' not in student for student in state['students']))
        self.assertTrue(all('balance' not in member for lesson in state['lessons'] for member in lesson['students']))
        self.assertTrue(all('cash_delta' not in entry for entry in state['entries']))
        scheduled = next(lesson for lesson in state['lessons'] if lesson['status'] == 'scheduled')
        denied = teacher.request('reports/draft', {
            'lesson_id': scheduled['id'], 'version': scheduled['version'],
            'reports': [{'student_id': member['id'], 'amount': 99, 'content': 'x', 'homework': 'x', 'feedback': 'x'} for member in scheduled['students']]})
        self.assertEqual(denied[0], 403)
        self.assertEqual(teacher.request('finance')[0], 403)
        self.assertEqual(teacher.request('vouchers')[0], 403)
        self.assertEqual(teacher.request('share')[0], 403)
        self.assertEqual(teacher.request('reconciliation')[0], 403)
        self.assertEqual(teacher.request('lessons', {'teacher_id': state['user']['teacher_id']})[0], 403)
        self.assertEqual(teacher.request('lessons/cancel', {'lesson_id': state['lessons'][0]['id']})[0], 403)
        status, pay = teacher.request('pay?period=fortnight')
        self.assertEqual(status, 200)
        self.assertEqual({row['teacher_id'] for row in pay['teachers']}, {state['user']['teacher_id']})
        self.assertIsNone(pay['partner'])
        self.assertEqual(pay['cost_entries'], [])
        self.assertEqual(teacher.request('pay?period=custom&start=2026-11-01&end=2026-11-02')[0], 400)
        self.assertEqual(teacher.request('pay?period=week&teacher_id=99999')[0], 403)
        self.assertEqual(teacher.request('entries', {'kind': 'credit', 'student_id': state['students'][0]['id'], 'amount': 1})[0], 403)

    def test_parent_sees_only_linked_children_and_not_the_back_office(self):
        parent = Client()
        state = parent.login('0400000001', 'ParentDemo2026!')
        self.assertEqual(state['user']['role'], 'parent')
        self.assertTrue(state['students'])
        self.assertTrue(all('notes' not in student for student in state['students']))
        self.assertTrue(all('credit_batches' in student or student.get('no_course') for student in state['students']))
        packs = [batch for student in state['students'] for batch in student.get('credit_batches') or []]
        self.assertTrue(all('unit_fees' not in batch for batch in packs))
        self.assertTrue(any(entry.get('cash_delta') for entry in state['entries']))
        self.assertTrue(all(entry['kind'] in ('credit', 'refund') for entry in state['entries']))
        self.assertEqual(parent.request('pay')[0], 403)
        self.assertEqual(parent.request('finance')[0], 403)
        self.assertEqual(parent.request('vouchers')[0], 403)
        self.assertEqual(parent.request('vouchers/approve', {'id': 1})[0], 403)
        self.assertEqual(parent.request('share')[0], 403)
        self.assertEqual(parent.request('audit')[0], 403)
        self.assertEqual(parent.request('lessons', {})[0], 403)
        self.assertEqual(parent.request('reports/complete', {'lesson_id': 1})[0], 403)

    def test_teacher_and_parent_pages_match_the_boss_layout(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('playwright is not installed')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            self._open(page, '0400000011', 'TutorDemo2026!')
            self.assertEqual(page.locator('h1').inner_text(), '我的课程')
            self.assertEqual(page.locator('.sidebar').evaluate('el => getComputedStyle(el).position'), 'sticky')
            self.assertEqual(page.locator('#add-schedule').count(), 0)
            self.assertEqual(page.locator('[data-slot]').count(), 0)
            page.locator('[data-lesson-detail]').first.click()
            page.wait_for_selector('#modal[open]')
            self.assertEqual(page.locator('#edit-schedule').count(), 0)
            self.assertEqual(page.locator('#cancel-schedule').count(), 0)
            self.assertGreater(page.locator('#write-report').count(), 0)
            page.click('#close-detail')
            page.click('.sidebar [data-view=pay]')
            page.wait_for_selector('[data-pay-period=fortnight]')
            self.assertEqual([button.inner_text() for button in page.locator('[data-pay-period]').all()], ['每天', '每周', '双周', '每月'])
            page.click('.sidebar [data-view=overview]')
            page.wait_for_selector('[data-open-student]')
            page.locator('[data-open-student]').first.click()
            page.wait_for_function('() => location.pathname.startsWith("/students/")')
            page.wait_for_selector('#page-back')
            self.assertEqual(page.locator('summary').filter(has_text='备注').count(), 0)
            self.assertEqual(page.locator('summary').filter(has_text='付款').count(), 0)
            page.click('#page-back')
            page.wait_for_function('() => document.querySelector("h1")?.textContent === "我的学生"')
            page.click('#logout')
            page.wait_for_selector('#login-form')
            self._open(page, '0400000001', 'ParentDemo2026!')
            self.assertEqual([button.inner_text() for button in page.locator('.sidebar .nav-item').all()], ['孩子的课表', '课后记录', '剩余课时', '付款记录'])
            page.click('.sidebar [data-view=overview]')
            page.wait_for_selector('.child-card')
            self.assertIn('剩余', page.locator('.child-card').first.inner_text())
            page.locator('.child-card').first.click()
            page.wait_for_function('() => location.pathname.startsWith("/students/")')
            page.wait_for_selector('#page-back')
            self.assertGreater(page.locator('summary').filter(has_text='付款记录').count(), 0)
            self.assertEqual(page.locator('summary').filter(has_text='备注').count(), 0)
            page.click('#page-back')
            page.wait_for_function('() => document.querySelector("h1")?.textContent === "剩余课时"')
            page.click('.sidebar [data-view=records]')
            page.wait_for_selector('#records-list')
            self.assertIn('$', page.locator('#records-list').inner_text())
            browser.close()

    def _open(self, page, phone, password):
        page.goto('http://127.0.0.1:%s/' % PORT)
        page.fill('[name=phone]', phone)
        page.fill('[name=password]', password)
        page.click('#login-form button[type=submit]')
        page.wait_for_selector('.sidebar')

    def test_admin_can_still_schedule(self):
        admin = Client()
        admin.login('0400000004', 'AdminDemo2026!')
        status, _ = admin.request('lessons', {})
        self.assertNotEqual(status, 403)


if __name__ == '__main__':
    unittest.main()
