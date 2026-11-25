"""Vincent can be given 新加坡数学 without editing the production database by hand."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'vincent-subject.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'scripts' / 'allow_teacher_subject.py'


class AllowTeacherSubjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499200001','Vincent','x','admin')").lastrowid
            c.execute("INSERT INTO teachers(user_id,subject,subjects) VALUES(?,?,'[\"数学\"]')", (uid, '数学'))
            c.commit()

    def test_dry_run_then_apply_adds_singapore_maths(self):
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(SCRIPT), '--teacher', 'Vincent', '--subject', '新加坡数学'],
            env=env, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        self.assertIn('新加坡数学', dry.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute('SELECT subjects FROM teachers').fetchone()[0], '["数学"]')
        applied = subprocess.run([sys.executable, str(SCRIPT), '--teacher', 'Vincent', '--subject', '新加坡数学', '--apply'],
            env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn('已写入', applied.stdout)
        with sqlite3.connect(DB) as c:
            subject, subjects = c.execute('SELECT subject, subjects FROM teachers').fetchone()
        self.assertIn('新加坡数学', subject)
        self.assertIn('新加坡数学', subjects)
        again = subprocess.run([sys.executable, str(SCRIPT), '--teacher', 'Vincent', '--subject', '新加坡数学', '--apply'],
            env=env, capture_output=True, text=True)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('已经勾过这个科目', again.stdout)


if __name__ == '__main__':
    unittest.main()
