"""Saving a teacher keeps subjects that are not in the old two-item checkbox list."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PORT = '8817'
KEPT = ['数学', '物理', '科学', '学业跟踪辅导']


class TeacherSubjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        if not Path('/usr/local/bin/google-chrome').exists():
            raise unittest.SkipTest('chrome is not installed')
        cls.tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': cls.tmp.name + '/subjects.sqlite3', 'LESSON_SECURE_COOKIE': '0'}
        cls.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('server.py')), '--port', PORT],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(60):
            import urllib.request
            try:
                urllib.request.urlopen('http://127.0.0.1:%s/health' % PORT, timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('teacher subject server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)
        cls.tmp.cleanup()

    def test_editing_keeps_subjects_that_were_not_unchecked(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.fill('[name=phone]', '0400000000')
            page.fill('[name=password]', 'TeacherDemo2026!')
            page.click('#login-form button[type=submit]')
            page.wait_for_selector('.sidebar [data-view=setup]')
            created = page.evaluate('''async (subjects) => {
              const saved = await api('teachers', {
                name: 'Vincent Extra', phone: '0493555001', password: 'VincentPass2026!',
                subjects, duty: ''
              });
              await refresh();
              return saved;
            }''', KEPT)
            self.assertTrue(created.get('teacher_id'), created)
            page.click('.sidebar [data-view=setup]')
            page.click('#surface [data-view=teachers]')
            page.wait_for_selector('[data-teacher-edit]')
            page.locator('article.teacher-card', has_text='Vincent Extra').locator('[data-teacher-edit]').click()
            page.wait_for_selector('#modal[open] [name=subjects]')
            checked = page.locator('#modal [name=subjects]:checked').evaluate_all('boxes => boxes.map(box => box.value)')
            for subject in KEPT:
                self.assertIn(subject, checked)
            page.fill('#modal [name=extra_subjects]', '化学、高数')
            page.click('#modal-form button[type=submit]')
            page.wait_for_function('() => !document.querySelector("#modal[open]")')
            saved = page.evaluate('''() => state.teachers.find(teacher => teacher.name === 'Vincent Extra').subjects''')
            for subject in KEPT + ['化学', '高数']:
                self.assertIn(subject, saved)
            browser.close()


if __name__ == '__main__':
    unittest.main()
