"""Every boss page that is not in the sidebar has a 返回 button."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'back.sqlite3')
os.environ['LESSON_DEMO'] = '1'
os.environ['LESSON_SECURE_COOKIE'] = '0'

PORT = '8786'
SIDEBAR = (
    'today', 'schedule', 'overview', 'pay', 'finance', 'vouchers',
    'share', 'feedback', 'accounting', 'prices', 'audit', 'setup',
)
SETTINGS = (
    ('teachers', '老师'),
    ('settings', '课程与地点'),
    ('administrators', '管理员'),
)


class BackButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        if not Path('/usr/local/bin/google-chrome').exists():
            raise unittest.SkipTest('chrome is not installed')
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': os.environ['LESSON_DB']}
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
            raise RuntimeError('back-button server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_settings_subpages_and_other_detail_pages_have_back(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.sidebar [data-view=setup]')
            for view in SIDEBAR:
                page.click('.sidebar [data-view="%s"]' % view)
                page.wait_for_selector('#surface')
                self.assertEqual(page.locator('#page-back').count(), 0, view)
            for view, title in SETTINGS:
                page.click('.sidebar [data-view=setup]')
                page.wait_for_selector('#surface [data-view="%s"]' % view)
                page.click('#surface [data-view="%s"]' % view)
                page.wait_for_function('title => document.querySelector("h1")?.textContent === title', arg=title)
                self._expect_back(page, title)
                page.click('#page-back')
                page.wait_for_function('() => document.querySelector("h1")?.textContent === "设置"')
                self.assertIn('view=setup', page.url)
            page.goto('http://127.0.0.1:%s/?view=teachers' % PORT)
            page.wait_for_function('() => document.querySelector("h1")?.textContent === "老师"')
            self._expect_back(page, '老师')
            page.click('#page-back')
            page.wait_for_function('() => document.querySelector("h1")?.textContent === "设置"')
            page.click('.sidebar [data-view=overview]')
            page.wait_for_selector('#student-list .year-fold > summary')
            page.locator('#student-list .year-fold > summary').first.click()
            page.wait_for_selector('[data-open-student]')
            page.locator('[data-open-student]').first.click()
            page.wait_for_function('() => location.pathname.startsWith("/students/")')
            self._expect_back(page, '学生档案')
            page.click('.sidebar [data-view=pay]')
            page.wait_for_selector('.pay-card')
            page.locator('.pay-card').first.click()
            page.wait_for_function('() => /\\/teachers\\/\\d+\\/pay/.test(location.pathname)')
            self._expect_back(page, '工资')
            page.click('.sidebar [data-view=overview]')
            page.click('#all-records')
            page.wait_for_function('() => document.querySelector("h1")?.textContent === "余额明细"')
            self._expect_back(page, '余额明细')
            page.click('#page-back')
            page.wait_for_function('() => document.querySelector("h1")?.textContent === "学生"')
            browser.close()

    def _expect_back(self, page, title):
        page.wait_for_selector('#page-back')
        self.assertEqual(page.locator('#page-back').inner_text(), '返回')
        box = page.locator('#page-back').bounding_box()
        surface = page.locator('#surface').bounding_box()
        self.assertIsNotNone(box)
        self.assertLess(box['x'], surface['x'] + 40)
        self.assertLess(box['y'], surface['y'] + 8)
        self.assertEqual(page.locator('h1').inner_text(), title)


if __name__ == '__main__':
    unittest.main()
