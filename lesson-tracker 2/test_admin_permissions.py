"""Each admin switch is on by default and is enforced on the server."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'perms.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import deletion
import permissions
import pricing
import profiles
import server
import teaching
from teaching import AccessError


class AdminPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def people(self):
        owner_id = self.c.execute("INSERT INTO users(phone,name,password,role) VALUES('0410000001','Helen','x','admin')").lastrowid
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner_id,))
        admin_id = self.c.execute("INSERT INTO users(phone,name,password,role) VALUES('0410000002','教务','x','admin')").lastrowid
        self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (admin_id, '数学'))
        owner = {'id': owner_id, 'role': 'owner'}
        admin = {'id': admin_id, 'role': 'admin'}
        return owner, admin

    def test_each_switch_defaults_on_and_can_be_turned_off(self):
        owner, admin = self.people()
        for key, _label in permissions.KEYS:
            permissions.allow(self.c, admin, key)
            permissions.allow(self.c, owner, key)
            permissions.set_flag(self.c, owner, {'admin_id': admin['id'], 'key': key, 'on': False})
            with self.assertRaises(AccessError):
                permissions.allow(self.c, admin, key)
            permissions.allow(self.c, owner, key)
            permissions.set_flag(self.c, owner, {'admin_id': admin['id'], 'key': key, 'on': True})
            permissions.allow(self.c, admin, key)
        with self.assertRaises(AccessError):
            permissions.set_flag(self.c, admin, {'admin_id': admin['id'], 'key': 'schedule', 'on': False})

    def test_schedule_students_parents_topup_reverse_reports_teachers_and_places(self):
        owner, admin = self.people()
        parent = self.c.execute("INSERT INTO users(phone,name,password,role) VALUES('0410000003','家长','x','parent')").lastrowid
        profiles.ensure_enrolment_columns(self.c)
        profile = self.c.execute("INSERT INTO student_profiles(name) VALUES('Mia')").lastrowid
        self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
        sid = self.c.execute('INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES(?,?,?,?,0)',
            ('Mia', '数学', parent, profile)).lastrowid
        teacher = self.c.execute("INSERT INTO users(phone,name,password,role) VALUES('0410000004','老师','x','parent')").lastrowid
        tid = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher, '英语')).lastrowid
        lesson = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id,version)
            VALUES(?, '英语','2026-06-01T16:00','2026-06-01T17:00',100,'教室','scheduled',?, 'req-perm', 1)''',
            (tid, owner['id'])).lastrowid
        checks = [
            ('schedule', lambda: teaching.require_scheduler(self.c, admin, {})),
            ('students', lambda: profiles.update(self.c, admin, {'student_id': sid, 'name': 'Mia', 'grade': 'Y5'}, lambda value, label, limit: str(value))),
            ('parents', lambda: profiles.search_parents(self.c, admin, '家')),
            ('places', lambda: teaching.save_option(self.c, admin, {'kind': 'location', 'name': '新教室', 'active': True}, lambda value, label, limit: str(value))),
            ('teachers', lambda: teaching.teacher_status(self.c, admin, {'teacher_id': tid, 'active': False})),
            ('reports', lambda: teaching.allowed_lesson(self.c, admin, lesson)),
        ]
        for key, call in checks:
            call()
            permissions.set_flag(self.c, owner, {'admin_id': admin['id'], 'key': key, 'on': False})
            with self.assertRaises(AccessError):
                call()
            permissions.set_flag(self.c, owner, {'admin_id': admin['id'], 'key': key, 'on': True})
        permissions.set_flag(self.c, owner, {'admin_id': admin['id'], 'key': 'topup', 'on': False})
        with self.assertRaises(AccessError):
            pricing.quote(self.c, admin, sid, 'one_to_one', 60, 20, '2026-06-01')
        permissions.set_flag(self.c, owner, {'admin_id': admin['id'], 'key': 'topup', 'on': True})
        offer = pricing.presets(self.c, admin, sid)
        self.assertTrue(offer.get('packages') or offer.get('reason') != '充值权限已关闭。')
        with self.assertRaises(AccessError):
            pricing.list_prices(self.c, admin)
        deletion.settle_course(self.c, admin, {'student_id': sid, 'reason': 'keep'})
        self.assertEqual(self.c.execute('SELECT archived FROM students WHERE id=?', (sid,)).fetchone()['archived'], 1)
        teaching.save_catalog_item(self.c, admin, 'course_types', {'name': '试听课'}, lambda value, label, limit: str(value))

    def test_receivables_and_refunds_stay_with_the_boss(self):
        _owner, admin = self.people()
        page = Path(__file__).with_name('server.py').read_text()
        self.assertIn("user['role']!='owner'", page)
        self.assertIn('只有老板可以查看挂账', page)
        self.assertIn("self.path == '/api/refunds'", page)
        self.assertIn('只有老板可以退课退款', page)
        with self.assertRaises(AccessError):
            permissions.allow(self.c, {'id': admin['id'], 'role': 'parent'}, 'topup')

    def test_login_hint_uses_the_polished_wording(self):
        page = Path(__file__).with_name('static') / 'app.js'
        text = page.read_text()
        self.assertIn('placeholder="例如 0412 345 678"', text)
        self.assertNotIn('placeholder="手机号，例如 0412 345 678"', text)
        self.assertIn('请用您登记的手机号登录（04 开头）', text)
        self.assertNotIn('例如 +61 412 345 678', text.split('login-form')[1].split('</form>')[0])
        self.assertIn('?v=20261128hint', (Path(__file__).with_name('static') / 'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
