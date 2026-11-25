"""The sidebar must not sit on top of the page it just opened."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'clicks.sqlite3')
os.environ['LESSON_DEMO'] = '1'
os.environ['LESSON_SECURE_COOKIE'] = '0'

PORT = '8782'
VIEWS = ('today', 'schedule', 'overview', 'pay', 'finance', 'audit', 'setup')


class SidebarClickTests(unittest.TestCase):
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
            raise RuntimeError('click test server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_main_content_receives_clicks_on_every_page(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 800})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.sidebar')
            blocked = []
            for view in VIEWS:
                page.click('.sidebar [data-view="%s"]' % view)
                page.wait_for_selector('#surface')
                hit = page.evaluate('''() => {
                  const main = document.querySelector('.main').getBoundingClientRect();
                  const x = main.x + Math.min(180, main.width / 2);
                  const y = main.y + 180;
                  const el = document.elementFromPoint(x, y);
                  const cover = el && el.closest('.sidebar, .nav-backdrop');
                  return {view: document.querySelector('h1')?.textContent || '', cover: cover ? cover.className : '', tag: el ? el.tagName : ''};
                }''')
                if hit['cover']:
                    blocked.append(hit)
            page.click('.sidebar [data-view="setup"]')
            page.click('#surface [data-view="settings"]')
            page.wait_for_selector('#surface input, #surface button, #surface select')
            settings_hit = page.evaluate('''() => {
              const control = document.querySelector('#surface input, #surface button, #surface select');
              const box = control.getBoundingClientRect();
              const el = document.elementFromPoint(box.x + 8, box.y + 8);
              const cover = el && el.closest('.sidebar, .nav-backdrop');
              return cover ? cover.className : (el === control || control.contains(el) ? 'control' : (el ? el.tagName : ''));
            }''')
            page.set_viewport_size({'width': 390, 'height': 800})
            page.click('#nav-toggle')
            page.wait_for_selector('.shell.nav-open')
            open_hit = page.evaluate('''() => {
              const el = document.elementFromPoint(370, 400);
              return el ? (el.id || el.className || el.tagName) : '';
            }''')
            page.click('#nav-backdrop')
            page.wait_for_function('() => !document.querySelector(".shell").classList.contains("nav-open")')
            closed_hit = page.evaluate('''() => {
              const el = document.elementFromPoint(200, 400);
              const cover = el && el.closest('.sidebar, .nav-backdrop');
              return cover ? cover.className : (el ? el.tagName : '');
            }''')
            browser.close()
        self.assertEqual(blocked, [])
        self.assertEqual(settings_hit, 'control')
        self.assertIn('nav-backdrop', open_hit)
        self.assertNotIn('nav-backdrop', closed_hit)
        self.assertNotIn('sidebar', closed_hit)


if __name__ == '__main__':
    unittest.main()
