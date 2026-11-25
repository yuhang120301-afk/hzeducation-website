"""Parent passwords can be set to the login mobile without printing the secret."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'reset-unused.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server
from scripts import reset_parent_passwords_to_phone as reset

SCRIPT = Path(__file__).with_name('scripts') / 'reset_parent_passwords_to_phone.py'
PHONE = '0411222333'


def build_db():
    path = Path(tempfile.mkdtemp()) / 'parents.sqlite3'
    os.environ['LESSON_DB'] = str(path)
    server.DB_PATH = str(path)
    server.initialize()
    with server.connect() as c:
        parent = c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            (PHONE, '测试家长', server.password_hash('OldPassword2026!'))).lastrowid
        pending = c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            ('pending-abc123', '待定家长', server.password_hash('AnotherPass2026!'))).lastrowid
        tutor_user = c.execute(
            "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
            ('0499888777', 'Emma', server.password_hash('TutorPass2026!'))).lastrowid
        c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (tutor_user, '数学'))
        c.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)',
            ('parent-session', parent, 'csrf', 9999999999))
        c.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)',
            ('tutor-session', tutor_user, 'csrf', 9999999999))
    return path, parent, pending, tutor_user


class ResetParentPasswordTests(unittest.TestCase):
    def test_dry_run_changes_nothing_and_masks_logins(self):
        path, parent, pending, tutor = build_db()
        code, out, err = self.invoke(path)
        self.assertEqual(code, 0, err)
        self.assertIn('将改密码：1', out)
        self.assertIn('跳过非手机号登录：1', out)
        self.assertIn('pending-******', out)
        self.assertEqual(reset.mask_login(PHONE), '04xx xxx 333')
        self.assertIn('任课老师账号已跳过：1', out)
        self.assertNotIn(PHONE, out)
        self.assertNotIn('0499888777', out)
        self.assertNotIn('pending-abc123', out)
        self.assertNotIn('OldPassword', out)
        with server.connect() as c:
            self.assertFalse(self.matches(c, parent, PHONE))
            self.assertIsNotNone(c.execute("SELECT 1 FROM sessions WHERE token_hash='parent-session'").fetchone())

    def test_apply_sets_the_phone_password_and_signs_that_parent_out(self):
        path, parent, pending, tutor = build_db()
        code, out, err = self.invoke(path, '--apply')
        self.assertEqual(code, 0, err)
        self.assertIn('已写入', out)
        self.assertNotIn(PHONE, out)
        with server.connect() as c:
            self.assertTrue(self.matches(c, parent, PHONE))
            self.assertFalse(self.matches(c, pending, 'pending-abc123'))
            self.assertFalse(self.matches(c, tutor, '0499888777'))
            self.assertIsNone(c.execute("SELECT 1 FROM sessions WHERE user_id=?", (parent,)).fetchone())
            self.assertIsNotNone(c.execute("SELECT 1 FROM sessions WHERE user_id=?", (tutor,)).fetchone())
        again, out2, err2 = self.invoke(path, '--apply')
        self.assertEqual(again, 0, err2)
        self.assertIn('已是手机号密码：1', out2)
        self.assertIn('将改密码：0', out2)

    def matches(self, c, user_id, phone):
        stored = c.execute('SELECT password FROM users WHERE id=?', (user_id,)).fetchone()['password']
        salt = stored.split(':', 1)[0]
        return server.password_hash(phone, salt) == stored

    def invoke(self, path, *args):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), '--db', str(path), *args],
            capture_output=True, text=True, check=False)
        return proc.returncode, proc.stdout, proc.stderr


if __name__ == '__main__':
    unittest.main()
