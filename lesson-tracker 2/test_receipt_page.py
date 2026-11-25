"""A receipt opens on its own page instead of under the list."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'receipts.sqlite3')
os.environ['LESSON_DEMO'] = '1'
os.environ['LESSON_SECURE_COOKIE'] = '0'

PORT = '8793'


class ReceiptPageTests(unittest.TestCase):
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
        for _ in range(80):
            import urllib.request
            try:
                urllib.request.urlopen('http://127.0.0.1:%s/health' % PORT, timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            err = cls.proc.stderr.read().decode() if cls.proc.stderr else ''
            raise RuntimeError('receipt server did not start\n' + err)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_receipt_and_pay_detail_are_their_own_pages(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 800})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.sidebar [data-view=vouchers]')
            page.evaluate('''async () => {
              const student = state.students.find(item => !item.no_course);
              await api('entries', {kind:'credit', student_id: student.id, amount: 1, gift_amount: 0, date: state.today, cash_amount: 10, payment_method: 'cash', note: '测试单据', request_id: crypto.randomUUID()});
            }''')
            page.click('.sidebar [data-view=vouchers]')
            page.wait_for_selector('[data-voucher]')
            self.assertEqual(page.locator('.voucher-sheet').count(), 0)
            number = page.locator('[data-voucher] td').nth(1).inner_text()
            page.locator('[data-voucher]').first.click()
            page.wait_for_function('() => /\\/receipts\\/\\d+/.test(location.pathname)')
            page.wait_for_selector('.voucher-sheet')
            self.assertEqual(page.locator('#page-back').inner_text(), '返回')
            self.assertEqual(page.locator('.voucher-tools table').count(), 0)
            self.assertIn(number, page.locator('.voucher-sheet').inner_text())
            page.click('#page-back')
            page.wait_for_function('() => location.search.includes("view=vouchers")')
            page.wait_for_selector('[data-voucher]')
            self.assertEqual(page.locator('.voucher-sheet').count(), 0)
            page.click('.sidebar [data-view=pay]')
            page.wait_for_selector('.pay-card')
            self.assertEqual(page.locator('.pay-fold').count(), 0)
            page.locator('.pay-card').first.click()
            page.wait_for_function('() => /\\/teachers\\/\\d+\\/pay/.test(location.pathname)')
            page.wait_for_selector('#page-back')
            page.wait_for_selector('.pay-teacher')
            self.assertGreater(page.locator('.pay-teacher').count(), 0)
            browser.close()


if __name__ == '__main__':
    unittest.main()
