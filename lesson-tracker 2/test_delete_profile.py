"""退学 finds a profile with no course, and 删除档案 only removes an empty one."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'erase.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import deletion
import profiles
import server


class EraseProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')
        self.n = 0

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def phone(self):
        self.n += 1
        return f'049{self.n:07d}'

    def owner(self):
        uid = self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?, 'Helen', 'x', 'admin')",
            (self.phone(),)).lastrowid
        self.c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
        return {'id': uid, 'role': 'owner'}

    def parent(self, phone=None):
        return self.c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?, '家长', 'x', 'parent')",
            (phone or self.phone(),)).lastrowid

    def profile(self, name, parent=None):
        profiles.ensure_enrolment_columns(self.c)
        pid = self.c.execute('INSERT INTO student_profiles(name) VALUES(?)', (name,)).lastrowid
        if parent:
            self.c.execute('INSERT INTO profile_parents(profile_id, user_id) VALUES(?,?)', (pid, parent))
        return pid

    def course(self, profile, parent, name='数学', balance=0):
        return self.c.execute(
            'INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES(?,?,?,?,?)',
            (name and '学生', '数学', parent, profile, balance)).lastrowid

    def test_withdraw_accepts_a_profile_with_no_course(self):
        boss = self.owner()
        pid = self.profile('空档案')
        deletion.withdraw_student(self.c, boss, {'profile_id': pid, 'id': 'p%s' % pid})
        self.assertEqual(self.c.execute('SELECT status FROM student_profiles WHERE id=?', (pid,)).fetchone()['status'], 'withdrawn')
        self.assertIsNotNone(self.c.execute("SELECT 1 FROM profile_events WHERE profile_id=? AND action='withdraw'", (pid,)).fetchone())

    def test_withdraw_still_asks_how_to_handle_a_balance(self):
        boss = self.owner()
        parent = self.parent()
        pid = self.profile('有余额', parent)
        sid = self.course(pid, parent, balance=400)
        with self.assertRaises(ValueError) as caught:
            deletion.withdraw_student(self.c, boss, {'profile_id': pid, 'courses': []})
        self.assertIn('请选择', str(caught.exception))
        deletion.withdraw_student(self.c, boss, {'profile_id': pid, 'courses': [{'student_id': sid, 'reason': 'keep'}]})
        row = self.c.execute('SELECT archived, balance FROM students WHERE id=?', (sid,)).fetchone()
        self.assertEqual((row['archived'], row['balance']), (1, 400))

    def test_erase_removes_an_empty_profile_and_its_placeholder_parent(self):
        boss = self.owner()
        placeholder = self.parent('pending-' + uuid.uuid4().hex[:8])
        pid = self.profile('写错了', placeholder)
        self.course(pid, placeholder)
        kept = self.profile('别人', self.parent())
        deletion.erase_profile(self.c, boss, {'profile_id': pid}, os.environ['LESSON_DB'])
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (pid,)).fetchone())
        self.assertIsNone(self.c.execute('SELECT 1 FROM users WHERE id=?', (placeholder,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (kept,)).fetchone())
        backups = list(Path(os.environ['LESSON_DB']).parent.glob('backup-delete-profile-*-%s-*.sqlite3' % pid))
        self.assertTrue(backups)
        self.assertGreater(backups[0].stat().st_size, 0)

    def test_erase_keeps_a_placeholder_parent_used_by_another_child(self):
        boss = self.owner()
        placeholder = self.parent('pending-' + uuid.uuid4().hex[:8])
        gone = self.profile('空的', placeholder)
        other = self.profile('另一个', placeholder)
        deletion.erase_profile(self.c, boss, {'profile_id': gone}, os.environ['LESSON_DB'])
        self.assertIsNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (gone,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM users WHERE id=?', (placeholder,)).fetchone())
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?', (other, placeholder)).fetchone())

    def test_erase_is_blocked_by_history_a_real_parent_or_a_duplicate_name(self):
        boss = self.owner()
        parent = self.parent()
        paid = self.profile('上过课', parent)
        sid = self.course(paid, parent)
        self.c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,100,'credit','2026-01-01','购课',?,?)",
            (sid, boss['id'], uuid.uuid4().hex))
        with self.assertRaises(ValueError) as paid_block:
            deletion.erase_profile(self.c, boss, {'profile_id': paid}, os.environ['LESSON_DB'])
        self.assertIn('退学', str(paid_block.exception))
        self.assertIsNotNone(self.c.execute('SELECT 1 FROM student_profiles WHERE id=?', (paid,)).fetchone())

        taught = self.profile('只排过课', self.parent())
        lesson_student = self.course(taught, self.parent())
        teacher = self.c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, '老师', 'x', 'parent')", (self.phone(),)).lastrowid
        tid = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher, '数学')).lastrowid
        lid = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?, '数学','2026-02-01T16:00','2026-02-01T17:00',100,'教室','completed',?,?)''',
            (tid, boss['id'], uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, lesson_student))
        with self.assertRaises(ValueError) as lesson_block:
            deletion.erase_profile(self.c, boss, {'profile_id': taught}, os.environ['LESSON_DB'])
        self.assertIn('退学', str(lesson_block.exception))

        billed = self.profile('有单据', self.parent())
        bill_student = self.course(billed, self.parent())
        self.c.execute('''INSERT INTO vouchers(number,kind,student_id,lesson_date,created_by)
            VALUES(?,?,?,?,?)''', ('T' + uuid.uuid4().hex[:8], 'credit', bill_student, '2026-03-01', boss['id']))
        with self.assertRaises(ValueError) as voucher_block:
            deletion.erase_profile(self.c, boss, {'profile_id': billed}, os.environ['LESSON_DB'])
        self.assertIn('退学', str(voucher_block.exception))

        linked = self.profile('有家长', self.parent())
        with self.assertRaises(ValueError) as parent_block:
            deletion.erase_profile(self.c, boss, {'profile_id': linked}, os.environ['LESSON_DB'])
        self.assertIn('家长', str(parent_block.exception))

        self.profile('重名')
        copy = self.profile('重名')
        with self.assertRaises(ValueError) as copy_block:
            deletion.erase_profile(self.c, boss, {'profile_id': copy}, os.environ['LESSON_DB'])
        self.assertIn('合并', str(copy_block.exception))
        from teaching import AccessError
        with self.assertRaises(AccessError):
            deletion.erase_profile(self.c, {'id': self.parent(), 'role': 'parent'}, {'profile_id': copy}, os.environ['LESSON_DB'])

    def test_home_counts_match_the_boss_cards(self):
        counts = deletion.roster_counts({
            'students': [
                {'id': 1, 'profile_id': 1, 'name': '在读', 'study_status': 'studying', 'no_course': False, 'archived': 0, 'voided': 0, 'needs_renewal': True},
                {'id': 2, 'profile_id': 1, 'name': '在读', 'study_status': 'studying', 'no_course': False, 'archived': 0, 'voided': 0, 'needs_renewal': False},
                {'id': 'p3', 'profile_id': 3, 'name': '未开课', 'study_status': 'studying', 'no_course': True, 'archived': 0, 'voided': 0},
                {'id': 4, 'profile_id': 4, 'name': '已毕业', 'study_status': 'graduated', 'no_course': False, 'archived': 0, 'voided': 0, 'needs_renewal': True},
            ],
            'withdrawn_students': [
                {'id': 5, 'profile_id': 5, 'name': '退学', 'withdrawn': True, 'no_course': False, 'archived': 1, 'voided': 0},
            ],
            'left_students': [
                {'id': 6, 'profile_id': 6, 'name': '离开', 'left_on': '2026-01-01', 'no_course': False, 'archived': 0, 'voided': 0, 'needs_renewal': True},
            ],
        })
        self.assertEqual(counts['enrolled'], 1)
        self.assertEqual(counts['everyone'], 5)
        self.assertEqual((counts['renewal_people'], counts['renewal_courses']), (1, 1))

    def test_page_looks_up_left_students_and_names_the_two_counts(self):
        page = Path(__file__).with_name('static')
        script = (page / 'app.js').read_text()
        home = (page / 'teaching.js').read_text()
        self.assertIn('state.left_students', script)
        self.assertIn('请刷新后再试', script)
        self.assertIn('profile_id:item.profile_id', script)
        self.assertIn('在读学员', home)
        self.assertIn('全部学员', home)
        self.assertIn('data-roster="renewal"', home)
        self.assertIn('?v=20261128perms', (page / 'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
