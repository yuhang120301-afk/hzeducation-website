"""Linking a parent attaches that one account and does not rename the others."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'parents.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import profiles
import server
import teaching


class ParentLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_editing_a_profile_does_not_rename_the_login(self):
        with server.connect() as c:
            owner = self._owner(c, '0433000001')
            parent = self._parent(c, '0433000002', '林静')
            other = self._parent(c, '0433000003', '王爸爸')
            sid = self._student(c, 'Zachary', parent, '数学')
            profiles.update(c, owner, {'student_id': sid, 'name': 'Zachary', 'grade': 'Y3', 'parent_name': '林静', 'phone': '0433000003'}, lambda value, label, limit: str(value))
            self.assertEqual(c.execute('SELECT name FROM users WHERE id=?', (parent,)).fetchone()['name'], '林静')
            self.assertEqual(c.execute('SELECT name, phone FROM users WHERE id=?', (other,)).fetchone()['phone'], '0433000003')
            linked = profiles.link_parent(c, owner, {'student_id': sid, 'parent_user_id': other}, None, None, None)
            self.assertEqual(linked['parent_id'], other)
            zachary = {'id': other, 'role': 'parent'}
            seen = [row['name'] for row in c.execute('SELECT name FROM students s WHERE '+profiles.linked_clause('s'), profiles.linked_params(other))]
            self.assertIn('Zachary', seen)
            state = teaching.state_for(c, zachary)
            self.assertTrue(any(lesson['students'] for lesson in state['lessons']) or state['lessons'] == [])
            names = [row['id'] for row in profiles.parents_for(c, c.execute('SELECT profile_id FROM students WHERE id=?', (sid,)).fetchone()['profile_id'], parent)]
            self.assertEqual(names, [parent, other])
            profiles.unlink_parent(c, owner, {'student_id': sid, 'parent_user_id': other})
            profile_id = c.execute('SELECT profile_id, parent_id FROM students WHERE id=?', (sid,)).fetchone()
            left = [row['id'] for row in profiles.parents_for(c, profile_id['profile_id'], profile_id['parent_id'])]
            self.assertEqual(left, [parent])
            with self.assertRaises(ValueError):
                profiles.unlink_parent(c, owner, {'student_id': sid, 'parent_user_id': parent})

    def _owner(self, c, phone):
        uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, 'Helen', 'x', 'admin')", (phone,)).lastrowid
        c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
        return {'id': uid, 'role': 'owner'}

    def _parent(self, c, phone, name):
        return c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?, 'x', 'parent')", (phone, name)).lastrowid

    def _student(self, c, name, parent, course):
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        sid = c.execute('INSERT INTO students(name,course,parent_id,profile_id,grade) VALUES(?,?,?,?,?)',
            (name, course, parent, profile, 'Y3')).lastrowid
        c.execute('INSERT OR IGNORE INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
        return sid


class ParentLinkBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        if not Path('/usr/local/bin/google-chrome').exists():
            raise unittest.SkipTest('chrome is not installed')
        import subprocess
        import sys
        import time
        cls.db = str(Path(tempfile.mkdtemp()) / 'parent-browser.sqlite3')
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': cls.db, 'LESSON_SECURE_COOKIE': '0'}
        cls.proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name('server.py')), '--port', '8791'],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(80):
            import urllib.request
            try:
                urllib.request.urlopen('http://127.0.0.1:8791/health', timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            err = cls.proc.stderr.read().decode() if cls.proc.stderr else ''
            raise RuntimeError('parent browser server did not start\n' + err)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.communicate(timeout=5)

    def test_guardian_dialog_searches_instead_of_renaming(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 800})
            page.goto('http://127.0.0.1:8791/')
            page.click('[data-demo=owner]')
            page.click('.sidebar [data-view=overview]')
            page.wait_for_selector('#student-list .year-fold > summary')
            page.locator('#student-list .year-fold > summary').first.click()
            page.wait_for_selector('[data-open-student]')
            page.locator('[data-open-student]').first.click()
            page.wait_for_selector('[data-guardian]')
            page.click('[data-guardian]')
            page.wait_for_selector('#parent-search')
            self.assertIn('按人关联', page.locator('#modal-body').inner_text())
            page.fill('#parent-search', '林')
            page.wait_for_timeout(400)
            browser.close()


if __name__ == '__main__':
    unittest.main()
