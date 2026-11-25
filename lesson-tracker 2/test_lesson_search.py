"""Recording a lesson can find a student who was just added, including one with no course."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PORT = '8816'


class LessonSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        if not Path('/usr/local/bin/google-chrome').exists():
            raise unittest.SkipTest('chrome is not installed')
        cls.tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': cls.tmp.name + '/search.sqlite3', 'LESSON_SECURE_COOKIE': '0'}
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
            raise RuntimeError('lesson search server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)
        cls.tmp.cleanup()

    def test_new_student_is_searchable_without_reload(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.goto('http://127.0.0.1:%s/' % PORT)
            page.fill('[name=phone]', '0400000000')
            page.fill('[name=password]', 'TeacherDemo2026!')
            page.click('#login-form button[type=submit]')
            page.wait_for_selector('#add-schedule, .sidebar [data-view=overview]')
            created = page.evaluate('''async () => {
              const subject = (state.subjects || []).find(item => item.active && item.name === '数学') || (state.subjects || []).find(item => item.active);
              const kind = (state.course_types || []).find(item => item.active);
              const saved = await api('students', {
                name: '韩新同学', subject_id: subject && subject.id, course_type_id: kind && kind.id,
                phone: '0499111333', parent_name: '韩家长', grade: 'Y4', password: 'OriginalPass2026!'
              });
              await api('students', {
                name: 'Tom Newkid', subject_id: subject && subject.id, course_type_id: kind && kind.id,
                phone: '0499111444', parent_name: 'Tom Parent', grade: 'Y5', password: 'OriginalPass2026!'
              });
              await refresh();
              return saved;
            }''')
            self.assertTrue(created.get('student_id'), created)
            page.click('.sidebar [data-view=overview]')
            page.click('#add-schedule')
            page.wait_for_selector('#schedule-student-search')
            page.fill('#schedule-student-search', '新同')
            page.wait_for_function('''() => [...document.querySelectorAll('#schedule-student-picker label')].some(label => !label.hidden && label.textContent.includes('韩新同学'))''')
            page.fill('#schedule-student-search', 'newk')
            page.wait_for_function('''() => [...document.querySelectorAll('#schedule-student-picker label')].some(label => !label.hidden && label.textContent.includes('Tom Newkid'))''')
            page.evaluate('''() => { const student = state.students.find(item => item.name === '韩新同学'); student.no_course = true; }''')
            page.click('#modal .close')
            page.click('#add-schedule')
            page.wait_for_selector('#schedule-student-search')
            page.fill('#schedule-student-search', '韩新')
            page.wait_for_function('''() => {
              const label = [...document.querySelectorAll('#schedule-student-picker label')].find(item => !item.hidden && item.textContent.includes('韩新同学'));
              return label && label.textContent.includes('还没有课程，不能扣课') && label.querySelector('input').disabled;
            }''')
            browser.close()


if __name__ == '__main__':
    unittest.main()
