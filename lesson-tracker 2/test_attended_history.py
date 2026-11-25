"""Cancelled lessons stay out of 已上过的课, and an attended row opens its record."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'attended.sqlite3')
os.environ['LESSON_DEMO'] = '1'
os.environ['LESSON_SECURE_COOKIE'] = '0'

PORT = '8771'


class AttendedHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        if not Path('/usr/local/bin/google-chrome').exists():
            raise unittest.SkipTest('chrome is not installed')
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': os.environ['LESSON_DB'], 'LESSON_SECURE_COOKIE': '0'}
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
            raise RuntimeError('attended-history server did not start\n' + err)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_profile_hides_cancelled_and_opens_the_lesson_record(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.sidebar [data-view=overview]')
            setup = page.evaluate('''async () => {
              try {
                const teacher = state.teachers.find(item => item.active);
                const created = await api('students', {name:'取消过滤学生', course:'数学', phone:'0400000001'});
                const sid = created.student_id;
                await api('entries', {kind:'credit', student_id: sid, amount: 4, date: state.today, cash_amount: 40, payment_method: 'cash', note: '测试课时', request_id: crypto.randomUUID()});
                const past = datePlus(state.today, -8);
                const future = datePlus(state.today, 1);
                const book = async (day, start, end) => api('lessons', {
                  teacher_id: teacher.id, student_ids: [sid], title: '数学 · 一对一', amount: '1', location: '教室',
                  starts_at: day + 'T' + start, ends_at: day + 'T' + end, request_id: crypto.randomUUID()
                });
                const attended = await book(past, '10:00', '11:00');
                const bare = await book(past, '14:00', '15:00');
                const upcoming = await book(future, '11:20', '12:20');
                const cancelled = await book(future, '07:05', '08:05');
                await refresh();
                const done = state.lessons.find(item => item.id === attended.lesson_id);
                await api('reports/complete', {lesson_id: done.id, version: done.version, reports: [{student_id: sid, amount: '1', content: '通分与约分', homework: '练习册', feedback: '掌握良好'}]});
                const dropped = state.lessons.find(item => item.id === cancelled.lesson_id);
                await api('lessons/cancel', {lesson_id: dropped.id, version: dropped.version, scope: 'single', reason: '测试撤销'});
                await refresh();
                return {ok: true, sid, past, future, attended: attended.lesson_id, bare: bare.lesson_id, upcoming: upcoming.lesson_id};
              } catch (error) {
                return {ok: false, error: String(error && error.message || error)};
              }
            }''')
            self.assertTrue(setup['ok'], setup.get('error'))
            page.goto('http://127.0.0.1:%s/students/%s' % (PORT, setup['sid']))
            page.wait_for_selector('[data-profile-section="lessons"]')
            section = page.locator('[data-profile-section="lessons"]')
            text = section.inner_text()
            self.assertIn('即将要上的课', text)
            self.assertIn('已上过的课 (2)', text)
            self.assertNotIn('接下来的课', text)
            self.assertNotIn('已取消', text)
            self.assertNotIn('07:05', text)
            self.assertIn('11:20', text)
            page.locator('[data-profile-section="lessons"] summary').filter(has_text='已上过的课').click()
            self.assertEqual(section.locator('[data-open-lesson]').count(), 2)
            section.locator('[data-open-lesson]').filter(has_text='10:00').click()
            page.wait_for_function('() => /\\/students\\/\\d+\\/lessons\\/\\d+/.test(location.pathname)')
            page.wait_for_selector('#page-back')
            self.assertEqual(page.locator('h1').inner_text(), '课时记录')
            self.assertIn('通分与约分', page.locator('#surface').inner_text())
            self.assertEqual(page.locator('#fill-report').count(), 0)
            page.click('#page-back')
            page.wait_for_function('() => /\\/students\\/\\d+\\/?$/.test(location.pathname)')
            page.wait_for_selector('[data-profile-section="lessons"]')
            page.locator('[data-profile-section="lessons"] summary').filter(has_text='已上过的课').click()
            page.locator('[data-open-lesson]').filter(has_text='14:00').click()
            page.wait_for_selector('#page-back')
            record = page.locator('#surface').inner_text()
            self.assertIn('还没有课后记录', record)
            self.assertEqual(page.locator('#fill-report').inner_text(), '填写课后记录')
            page.click('#fill-report')
            page.wait_for_selector('#modal[open]')
            self.assertIn('填写课后记录', page.locator('#modal-title').inner_text())
            page.click('#modal .close')
            page.wait_for_function('() => !document.querySelector("#modal[open]")')
            page.click('#logout')
            page.wait_for_selector('[data-demo=parent]')
            page.click('[data-demo=parent]')
            page.wait_for_selector('.sidebar [data-view=schedule]')
            page.click('.sidebar [data-view=schedule]')
            page.wait_for_selector('.week-grid')
            parent_text = page.locator('#surface').inner_text()
            self.assertNotIn('07:05', parent_text)
            self.assertNotIn('已取消', parent_text)
            self.assertIn('11:20', parent_text)
            browser.close()


if __name__ == '__main__':
    unittest.main()
