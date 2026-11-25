"""Changing a lesson's teacher must save, or show a Chinese reason and leave it unchanged.

A recurring lesson used to close its dialog before the server answered. A rejection
(the new teacher is already busy, or Singapore Maths is not taught by Helen) then
vanished, and the save button looked like it did nothing.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'teacher-change.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server
import teaching


ROOT = Path(__file__).resolve().parent


class TeacherChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')
        self.owner = self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",
            (self.phone(), 'Helen', 'x')).lastrowid
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (self.owner,))
        self.helen = self.c.execute(
            "INSERT INTO teachers(user_id,subject) VALUES(?,?)", (self.owner, '数学')).lastrowid
        other = self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            (self.phone(), 'Angela', 'x')).lastrowid
        self.angela = self.c.execute(
            "INSERT INTO teachers(user_id,subject) VALUES(?,?)", (other, '数学')).lastrowid
        self.user = {'id': self.owner, 'role': 'owner'}
        self.math = self.c.execute("SELECT id FROM subjects WHERE name='数学'").fetchone()['id']
        self.singapore = self.c.execute("SELECT id FROM subjects WHERE name='新加坡数学'").fetchone()['id']
        self.one = self.c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']
        self.two = self.c.execute("SELECT id FROM course_types WHERE name='一对二'").fetchone()['id']
        self.small = self.c.execute("SELECT id FROM course_types WHERE name='小班课'").fetchone()['id']

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def phone(self):
        return ('046' + uuid.uuid4().hex)[:15]

    def student(self, name='林晓'):
        parent = self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            (self.phone(), name + '家长', 'x')).lastrowid
        profile = self.c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        return self.c.execute(
            '''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id)
               VALUES(?,?,?,?,0,?,?)''',
            (name, '数学', parent, profile, self.math, self.one)).lastrowid

    def payload(self, teacher, students, day='2027-05-04', start='09:00', end='10:00', **extra):
        body = {
            'teacher_id': teacher, 'student_ids': students, 'title': '数学 · 一对一',
            'subject_id': self.math, 'course_type_id': self.one,
            'starts_at': day + 'T' + start, 'ends_at': day + 'T' + end,
            'amount': '1', 'location': '教室', 'color': 'green',
            'request_id': uuid.uuid4().hex,
        }
        body.update(extra)
        return body

    def save(self, **kwargs):
        data = kwargs.pop('data', None) or self.payload(**kwargs)
        return teaching.save_schedule(self.c, self.user, data, server.units, server.text_value)

    def teacher_of(self, lesson_id):
        return self.c.execute('SELECT teacher_id FROM lessons WHERE id=?', (lesson_id,)).fetchone()['teacher_id']

    def test_boss_can_change_the_teacher(self):
        sid = self.student()
        lesson_id = self.save(teacher=self.helen, students=[sid])['lesson_id']
        lesson = self.c.execute('SELECT * FROM lessons WHERE id=?', (lesson_id,)).fetchone()
        self.save(teacher=self.angela, students=[sid], data={
            **self.payload(self.angela, [sid]),
            'lesson_id': lesson_id, 'version': lesson['version'], 'scope': 'single',
        })
        self.assertEqual(self.teacher_of(lesson_id), self.angela)

    def test_a_busy_teacher_is_rejected_in_chinese_and_the_lesson_stays(self):
        sid = self.student()
        other = self.student('陈一诺')
        kept = self.save(teacher=self.helen, students=[sid])['lesson_id']
        self.save(teacher=self.angela, students=[other])
        lesson = self.c.execute('SELECT * FROM lessons WHERE id=?', (kept,)).fetchone()
        self.c.execute('SAVEPOINT busy')
        with self.assertRaises(ValueError) as caught:
            self.save(teacher=self.angela, students=[sid], data={
                **self.payload(self.angela, [sid]),
                'lesson_id': kept, 'version': lesson['version'], 'scope': 'single',
            })
        self.assertIn('这位老师在该时段已有课程', str(caught.exception))
        self.assertNotIn('Traceback', str(caught.exception))
        self.c.execute('ROLLBACK TO busy')
        self.assertEqual(self.teacher_of(kept), self.helen)

    def test_a_blank_teacher_is_a_chinese_error(self):
        sid = self.student()
        with self.assertRaises(ValueError) as caught:
            self.save(teacher='', students=[sid])
        self.assertEqual(str(caught.exception), '请选择有效的任课老师。')

    def test_one_occurrence_or_the_rest_of_a_series(self):
        sid = self.student()
        created = self.save(teacher=self.helen, students=[sid], data={
            **self.payload(self.helen, [sid], day='2027-06-01'),
            'repeat': 'weekly', 'repeat_count': '3',
        })
        ids = created['lesson_ids']
        self.assertEqual(len(ids), 3)
        second = self.c.execute('SELECT * FROM lessons WHERE id=?', (ids[1],)).fetchone()
        series_version = self.c.execute(
            'SELECT version FROM lesson_series WHERE id=?', (second['series_id'],)).fetchone()['version']
        self.save(teacher=self.angela, students=[sid], data={
            **self.payload(self.angela, [sid], day='2027-06-08'),
            'lesson_id': ids[1], 'version': second['version'],
            'series_version': series_version, 'scope': 'single',
        })
        self.assertEqual(self.teacher_of(ids[0]), self.helen)
        self.assertEqual(self.teacher_of(ids[1]), self.angela)
        self.assertEqual(self.teacher_of(ids[2]), self.helen)
        third = self.c.execute('SELECT * FROM lessons WHERE id=?', (ids[2],)).fetchone()
        series_version = self.c.execute(
            'SELECT version FROM lesson_series WHERE id=?', (third['series_id'],)).fetchone()['version']
        self.save(teacher=self.angela, students=[sid], data={
            **self.payload(self.angela, [sid], day='2027-06-15'),
            'lesson_id': ids[2], 'version': third['version'],
            'series_version': series_version, 'scope': 'future',
        })
        self.assertEqual(self.teacher_of(ids[0]), self.helen)
        self.assertEqual(self.teacher_of(ids[1]), self.angela)
        self.assertEqual(self.teacher_of(ids[2]), self.angela)

    def test_singapore_maths_rejects_anyone_but_helen_in_chinese(self):
        sid = self.student('七年级')
        self.c.execute("UPDATE students SET subject_id=?, course='新加坡数学' WHERE id=?", (self.singapore, sid))
        base = self.payload(self.angela, [sid], day='2027-07-06')
        base['subject_id'] = self.singapore
        base['title'] = '新加坡数学 · 一对一'
        with self.assertRaises(ValueError) as caught:
            self.save(data=base)
        self.assertIn('勾选新加坡数学', str(caught.exception))
        self.c.execute('UPDATE teachers SET subjects=? WHERE id=?', ('["数学","新加坡数学"]', self.angela))
        base['request_id'] = uuid.uuid4().hex
        allowed = self.save(data=base)
        self.assertEqual(self.teacher_of(allowed['lesson_id']), self.angela)
        self.c.execute("UPDATE lessons SET status='cancelled' WHERE id=?", (allowed['lesson_id'],))
        self.c.execute('UPDATE teachers SET subjects=? WHERE id=?', ('["数学"]', self.angela))
        base['teacher_id'] = self.helen
        base['request_id'] = uuid.uuid4().hex
        saved = self.save(data=base)
        self.assertEqual(self.teacher_of(saved['lesson_id']), self.helen)
        lesson = self.c.execute('SELECT * FROM lessons WHERE id=?', (saved['lesson_id'],)).fetchone()
        self.c.execute('SAVEPOINT sg')
        with self.assertRaises(ValueError) as caught:
            self.save(data={
                **base, 'teacher_id': self.angela, 'lesson_id': saved['lesson_id'],
                'version': lesson['version'], 'scope': 'single', 'request_id': uuid.uuid4().hex,
            })
        self.assertIn('勾选新加坡数学', str(caught.exception))
        self.c.execute('ROLLBACK TO sg')
        self.assertEqual(self.teacher_of(saved['lesson_id']), self.helen)

    def test_course_types_can_be_scheduled(self):
        one = self.student('一对一学生')
        two_a, two_b = self.student('一对二甲'), self.student('一对二乙')
        group = [self.student('小班' + str(i)) for i in range(3)]
        for type_id, students, day in (
            (self.one, [one], '2027-08-03'),
            (self.two, [two_a, two_b], '2027-08-04'),
            (self.small, group, '2027-08-05'),
        ):
            saved = self.save(data=self.payload(
                self.helen, students, day=day, course_type_id=type_id,
                title='数学 · 课'))
            stored = self.c.execute(
                'SELECT course_type_id FROM lessons WHERE id=?', (saved['lesson_id'],)).fetchone()['course_type_id']
            self.assertEqual(stored, type_id)
            self.assertEqual(
                self.c.execute('SELECT COUNT(*) n FROM lesson_students WHERE lesson_id=?', (saved['lesson_id'],)).fetchone()['n'],
                len(students))

    def test_schedule_form_does_not_close_before_the_server_answers(self):
        """The save handler must keep the form, so a rejection can be shown on it."""
        source = (ROOT / 'static' / 'teaching.js').read_text()
        body = source[source.find('function scheduleModal'):source.find('function askAbsenceCharge')]
        self.assertNotIn('askSeriesScope', body)
        self.assertIn("name=scope", body)
        app = (ROOT / 'static' / 'app.js').read_text()
        self.assertIn('function showModalError', app)
        self.assertIn('novalidate', app)


class ScheduleUiTests(unittest.TestCase):
    """Browser check of the boss schedule. Skips when Playwright or Chrome is missing."""

    PORT = '8778'

    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        chrome = next((path for path in ('/usr/bin/google-chrome', '/usr/local/bin/google-chrome') if Path(path).exists()), '')
        if not chrome:
            raise unittest.SkipTest('chrome is not installed')
        cls.chrome = chrome
        cls.tmp = tempfile.TemporaryDirectory()
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': str(Path(cls.tmp.name) / 'ui.sqlite3'), 'LESSON_SECURE_COOKIE': '0'}
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'server.py'), '--port', cls.PORT],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        import urllib.request
        for _ in range(50):
            try:
                urllib.request.urlopen('http://127.0.0.1:%s/health' % cls.PORT, timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('schedule UI server did not start')

    @classmethod
    def tearDownClass(cls):
        proc = getattr(cls, 'proc', None)
        if proc:
            proc.terminate()
            proc.communicate(timeout=5)
        tmp = getattr(cls, 'tmp', None)
        if tmp:
            tmp.cleanup()

    def test_changing_teacher_shows_the_chinese_reason_then_saves(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=self.chrome, headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.goto('http://127.0.0.1:%s/' % self.PORT)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.nav-item')
            page.locator('.nav-item', has_text='课表').click()
            page.wait_for_timeout(300)
            created = page.evaluate('''async () => {
              const helen = state.teachers.find(t => t.account_role === 'owner');
              const angela = state.teachers.find(t => t.name.includes('Angela'));
              const ethan = state.teachers.find(t => t.name.includes('Ethan'));
              const students = state.students.filter(s => !s.no_course && !s.archived);
              const subject = state.subjects.find(s => s.name === '数学').id;
              const type = state.course_types.find(t => t.name === '一对一').id;
              const day = '2027-09-07';
              await api('lessons', {teacher_id: angela.id, student_ids:[students[0].id], title:'数学 · 一对一', subject_id:subject, course_type_id:type, starts_at:day+'T11:00', ends_at:day+'T12:00', amount:'1', color:'green', location:'', request_id:crypto.randomUUID()});
              const series = await api('lessons', {teacher_id: helen.id, student_ids:[students[1].id], title:'数学 · 一对一', subject_id:subject, course_type_id:type, starts_at:day+'T11:00', ends_at:day+'T12:00', amount:'1', color:'blue', location:'', request_id:crypto.randomUUID(), repeat:'weekly', repeat_count:3});
              await refresh();
              return {lesson: series.lesson_id, angela: String(angela.id), ethan: String(ethan.id)};
            }''')
            page.evaluate('id => lessonDetail(id)', created['lesson'])
            page.click('#edit-schedule')
            page.wait_for_selector('[name=teacher_id]')
            page.select_option('[name=teacher_id]', created['angela'])
            page.click('#modal-form [type=submit]')
            page.wait_for_selector('#modal-error:not([hidden])')
            error = page.locator('#modal-error').inner_text()
            self.assertIn('这位老师在该时段已有课程', error)
            self.assertTrue(page.locator('#modal').evaluate('el => el.open'))
            self.assertEqual(page.locator('#scope-single').count(), 0)
            still = page.evaluate('id => state.lessons.find(l => l.id === id).teacher_name', created['lesson'])
            self.assertIn('Helen', still)
            page.select_option('[name=teacher_id]', created['ethan'])
            page.click('#modal-form [type=submit]')
            page.wait_for_function('id => { const lesson = state.lessons.find(l => l.id === id); return lesson && lesson.teacher_name.includes("Ethan"); }', arg=created['lesson'])
            toast = page.locator('#toast').inner_text()
            self.assertIn('课程已更新', toast)
            self.assertIn('Ethan', toast)
            shown = page.evaluate('id => state.lessons.find(l => l.id === id).teacher_name', created['lesson'])
            self.assertIn('Ethan', shown)
            page.evaluate('''() => { weekStart = monday('2027-09-07'); gcalDay = '2027-09-07'; renderSchedule(); }''')
            page.wait_for_timeout(300)
            shot = Path('/opt/cursor/artifacts/teacher-change-saved.png')
            try:
                shot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shot))
            except OSError:
                pass
            browser.close()


if __name__ == '__main__':
    unittest.main()
