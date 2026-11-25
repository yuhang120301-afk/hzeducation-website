"""A top-up can be saved with every payment method the picker offers."""
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
import uuid
from pathlib import Path

PORT = '8805'
# Everything except cash. Gift is a real method and needs a zero paid amount.
NON_CASH = ('bank', 'cny', 'alipay', 'card', 'wechat', 'other', 'gift')


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


class PaymentMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': cls.tmp.name + '/pay-methods.sqlite3', 'LESSON_SECURE_COOKIE': '0'}
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
            raise RuntimeError('payment method server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)
        cls.tmp.cleanup()

    def test_each_defined_method_can_be_saved(self):
        owner = Client()
        state = owner.login('0400000000', 'TeacherDemo2026!')
        student = next(person for person in state['students'] if not person.get('no_course'))
        saved = {}
        for method in NON_CASH + ('cash',):
            gift = method == 'gift'
            status, body = owner.request('entries', {
                'student_id': student['id'], 'kind': 'credit',
                'amount': '0' if gift else '1', 'gift_amount': '1' if gift else '0',
                'cash_amount': '0' if gift else '10', 'payment_method': method,
                'date': state['today'], 'note': 'api-' + method, 'request_id': str(uuid.uuid4()),
            })
            self.assertEqual(status, 201, body)
            saved[method] = 'api-' + method
        self.assertEqual(owner.request('entries', {
            'student_id': student['id'], 'kind': 'credit', 'amount': '1', 'gift_amount': '0',
            'cash_amount': '10', 'payment_method': '微信', 'date': state['today'],
            'note': 'api-label', 'request_id': str(uuid.uuid4()),
        })[0], 201)
        _, again = owner.request('state')
        by_note = {entry['note']: entry.get('payment_method') for entry in again['entries']}
        for method, note in saved.items():
            self.assertEqual(by_note[note], method)
        self.assertEqual(by_note['api-label'], 'wechat')
        status, body = owner.request('entries', {
            'student_id': student['id'], 'kind': 'credit', 'amount': '1', 'gift_amount': '0',
            'cash_amount': '10', 'payment_method': '', 'date': state['today'],
            'note': 'blank', 'request_id': str(uuid.uuid4()),
        })
        self.assertEqual(status, 400, body)

    def test_top_up_form_records_each_non_cash_method(self):
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
            page.wait_for_selector('#student-list [data-credit]')
            for method in NON_CASH:
                page.locator('#student-list [data-credit]').first.click()
                page.wait_for_selector('#modal[open] [name=payment_method]')
                values = page.locator('#modal [name=payment_method] option').evaluate_all(
                    'options => options.map(option => option.value)')
                self.assertIn(method, values)
                if method == 'gift':
                    page.fill('#amount', '0')
                    page.fill('#gift-amount', '1')
                    page.fill('[name=cash_amount]', '0')
                else:
                    page.fill('[name=cash_amount]', '15')
                page.select_option('#modal [name=payment_method]', method)
                self.assertEqual(page.input_value('#modal [name=payment_method]'), method)
                page.fill('#entry-note', 'browser-' + method)
                page.click('#modal-form button[type=submit]')
                page.wait_for_function(
                    '''method => (state.entries || []).some(entry => entry.note === 'browser-' + method)
                        || !!document.querySelector('#modal-error')?.textContent''',
                    arg=method, timeout=8000)
                problem = page.locator('#modal-error').inner_text()
                self.assertFalse(problem.strip(), problem)
            recorded = page.evaluate('''() => Object.fromEntries(
                (state.entries || []).filter(entry => String(entry.note || '').startsWith('browser-'))
                    .map(entry => [entry.note, entry.payment_method]))''')
            for method in NON_CASH:
                self.assertEqual(recorded.get('browser-' + method), method)
            browser.close()


if __name__ == '__main__':
    unittest.main()
