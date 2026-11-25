"""Settings tiles must open their page, not snap back to 设置."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'settings-tiles.sqlite3')
os.environ['LESSON_DEMO'] = '1'
os.environ['LESSON_SECURE_COOKIE'] = '0'

PORT = '8783'
TILES = (
    ('teachers', '老师'),
    ('settings', '课程与地点'),
    ('administrators', '管理员'),
)
SIZES = ((1440, 900), (1366, 768), (768, 1024))


class SettingsTileTests(unittest.TestCase):
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
            raise RuntimeError('settings tile server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_each_settings_tile_opens_at_desktop_laptop_and_ipad_widths(self):
        from playwright.sync_api import sync_playwright
        failures = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            errors = []
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.sidebar [data-view=setup]')
            for width, height in SIZES:
                page.set_viewport_size({'width': width, 'height': height})
                self._open_setup(page)
                tiles = page.locator('#surface [data-view]')
                self.assertEqual(tiles.count(), 3)
                for index, (view, title) in enumerate(TILES):
                    card = page.locator('#surface [data-view="%s"]' % view)
                    box = card.bounding_box()
                    hit = page.evaluate('''(pos) => {
                      const el = document.elementFromPoint(pos.x, pos.y);
                      const cover = el && el.closest('.sidebar, .nav-backdrop');
                      return {
                        tag: el ? el.tagName : '',
                        view: el && el.closest('[data-view]') ? el.closest('[data-view]').dataset.view : '',
                        cover: cover ? cover.className : ''
                      };
                    }''', {'x': box['x'] + box['width'] / 2, 'y': box['y'] + box['height'] / 2})
                    if hit['cover'] or hit['view'] != view:
                        failures.append((width, height, view, hit))
                        continue
                    card.click()
                    page.wait_for_function('title => document.querySelector("h1")?.textContent === title', arg=title)
                    if 'view=%s' % view not in page.url:
                        failures.append((width, height, view, page.url))
                    self._open_setup(page)
                backup = page.locator('#download-backup')
                box = backup.bounding_box()
                hit = page.evaluate('''(pos) => {
                  const el = document.elementFromPoint(pos.x, pos.y);
                  return el && (el.id === 'download-backup' || !!el.closest('#download-backup'));
                }''', {'x': box['x'] + box['width'] / 2, 'y': box['y'] + box['height'] / 2})
                if not hit:
                    failures.append((width, height, 'download-backup', 'covered'))
            browser.close()
        self.assertEqual(errors, [])
        self.assertEqual(failures, [])

    def _open_setup(self, page):
        if page.locator('.sidebar [data-view=setup]').is_visible():
            page.click('.sidebar [data-view=setup]')
        else:
            page.click('#nav-toggle')
            page.click('.sidebar [data-view=setup]')
        page.wait_for_selector('#surface [data-view=teachers]')
        page.wait_for_function('() => document.querySelector("h1")?.textContent === "设置"')


if __name__ == '__main__':
    unittest.main()
