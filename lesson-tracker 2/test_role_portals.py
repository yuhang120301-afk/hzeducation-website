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
        self.assertTrue(all('cash_delta' not in entry for entry in state['entries']))
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

    def test_parent_sees_only_linked_children_and_not_the_back_office(self):
        parent = Client()
        state = parent.login('0400000001', 'ParentDemo2026!')
        self.assertEqual(state['user']['role'], 'parent')
        self.assertTrue(state['students'])
        self.assertTrue(all('notes' not in student for student in state['students']))
        self.assertTrue(all('credit_batches' in student or student.get('no_course') for student in state['students']))
        self.assertTrue(all(entry['kind'] in ('credit', 'refund') for entry in state['entries']))
        self.assertEqual(parent.request('pay')[0], 403)
        self.assertEqual(parent.request('finance')[0], 403)
        self.assertEqual(parent.request('vouchers')[0], 403)
        self.assertEqual(parent.request('vouchers/approve', {'id': 1})[0], 403)
        self.assertEqual(parent.request('share')[0], 403)
        self.assertEqual(parent.request('audit')[0], 403)

    def test_admin_can_still_schedule(self):
        admin = Client()
        admin.login('0400000004', 'AdminDemo2026!')
        status, _ = admin.request('lessons', {})
        self.assertNotEqual(status, 403)


if __name__ == '__main__':
    unittest.main()
