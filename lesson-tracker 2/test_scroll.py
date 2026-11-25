"""A save re-renders the portal without sending Helen back to the top."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'scroll.sqlite3')
os.environ['LESSON_DEMO'] = '1'
os.environ['LESSON_SECURE_COOKIE'] = '0'

PORT = '8775'


class ScrollPlaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        chrome = '/usr/local/bin/google-chrome'
        if not Path(chrome).exists():
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
            raise RuntimeError('scroll test server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_refresh_keeps_scroll_and_open_card(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 700})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.sidebar [data-view=overview]')
            page.click('.sidebar [data-view=overview]')
            page.wait_for_selector('#student-list .year-fold > summary')
            page.locator('#student-list .year-fold > summary').first.click()
            page.wait_for_selector('#student-list .pay-card')
            page.locator('#student-list .pay-card').first.click()
            page.wait_for_selector('[data-profile-section="lessons"]')
            page.evaluate('''() => {
              document.body.style.minHeight = '4000px';
              window.scrollTo(0, 900);
              document.querySelector('[data-profile-section="lessons"]').open = true;
            }''')
            page.evaluate('() => refresh()')
            page.wait_for_timeout(400)
            place = page.evaluate('''() => ({
              y: window.scrollY,
              open: document.querySelector('[data-profile-section="lessons"]').open
            })''')
            browser.close()
        self.assertGreater(place['y'], 700)
        self.assertTrue(place['open'])


if __name__ == '__main__':
    unittest.main()
