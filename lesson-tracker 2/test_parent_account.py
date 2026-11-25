"""Boss and admin can edit a linked parent's login. Teachers and parents cannot."""
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

PORT = '8813'


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
        assert status == 200, (status, _)
        _, state = self.request('state')
        self.csrf = state['csrf']
        return state


class ParentAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': cls.tmp.name + '/accounts.sqlite3', 'LESSON_SECURE_COOKIE': '0'}
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
            raise RuntimeError('parent account server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)
        cls.tmp.cleanup()

    def test_boss_can_change_login_and_password_without_moving_other_students(self):
        boss = Client()
        boss.login('0400000000', 'TeacherDemo2026!')
        status, created = boss.request('students', {
            'name': '账号孩子', 'course': '数学', 'phone': '0499000111',
            'password': 'OriginalPass2026!', 'parent_name': '测试家长'})
        self.assertEqual(status, 201, created)
        sid = created['student_id']
        status, sibling = boss.request('students', {
            'name': '另一个孩子', 'course': '英语', 'phone': '0499000444', 'parent_name': '另一家长'})
        self.assertEqual(status, 201, sibling)
        state = boss.request('state')[1]
        account = next(row for row in state['students'] if row['id'] == sid)
        other = next(row for row in state['students'] if row['id'] == sibling['student_id'])
        parent_id = account['parents'][0]['id']
        parent = Client()
        parent.login('0499000111', 'OriginalPass2026!')
        teacher = Client()
        teacher.login('0400000003', 'TutorDemo2026!')
        payload = {
            'student_id': sid, 'parent_user_id': parent_id, 'parent_name': '家长新姓名',
            'phone': '0499000222', 'contact_phone': '0499000333', 'password': 'UpdatedPass2026!'}
        self.assertEqual(parent.request('students/guardian', payload)[0], 403)
        self.assertEqual(teacher.request('students/guardian', payload)[0], 403)
        self.assertEqual(boss.request('students/guardian', {**payload, 'phone': '不是手机号'})[0], 400)
        self.assertEqual(boss.request('students/guardian', {**payload, 'phone': '0400000000'})[0], 400)
        self.assertEqual(boss.request('students/guardian', payload)[0], 200)
        self.assertIsNone(parent.request('state')[1]['user'])
        signed = parent.login('0499000222', 'UpdatedPass2026!')
        child = next(row for row in signed['students'] if row['id'] == sid)
        brother = next(row for row in boss.request('state')[1]['students'] if row['id'] == sibling['student_id'])
        self.assertEqual(child['name'], '账号孩子')
        self.assertEqual(brother['name'], '另一个孩子')
        self.assertEqual(brother['parent_name'], other['parent_name'])
        self.assertEqual(brother['phone'], other['phone'])
        self.assertEqual(boss.request('students/guardian', {**payload, 'password': ''})[0], 200)
        parent.login('0499000222', 'UpdatedPass2026!')
        linked = boss.request('students/parents/link', {
            'student_id': sid, 'parent_name': '新家长', 'phone': '0499000555'})
        self.assertEqual(linked[0], 200, linked[1])
        Client().login('0499000555', '0499000555')

    def test_boss_dialog_shows_the_reset_box(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('playwright is not installed')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.fill('[name=phone]', '0400000000')
            page.fill('[name=password]', 'TeacherDemo2026!')
            page.click('#login-form button[type=submit]')
            page.wait_for_selector('.sidebar [data-view=overview]')
            page.click('.sidebar [data-view=overview]')
            page.wait_for_selector('#student-list .year-fold > summary')
            page.locator('#student-list .year-fold > summary').first.click()
            page.wait_for_selector('[data-open-student]')
            page.locator('[data-open-student]').first.click()
            page.wait_for_selector('#page-back')
            page.click('[data-guardian]')
            page.wait_for_selector('#modal[open]')
            text = page.locator('#modal').inner_text()
            self.assertIn('编辑家长账号', text)
            self.assertIn('登录手机号', text)
            self.assertIn('重置密码（选填）', text)
            self.assertIn('留空则保留原密码', text)
            self.assertIn('留空则用登录手机号作为初始密码', text)
            self.assertEqual(page.locator('[data-parent-password]').first.input_value(), '')
            browser.close()


if __name__ == '__main__':
    unittest.main()
