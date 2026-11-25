"""Old archived series must not grow into 2028, and the January 2027 timetable stays."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'stale.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import recurrence
import server

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / 'scripts' / 'report_stale_series.py'
CLEAN = ROOT / 'scripts' / 'cleanup_stale_series.py'


class StaleSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def _people(self, c, name, archived):
        owner = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,'x','admin')",
            ('045' + uuid.uuid4().hex[:8], 'Helen')).lastrowid
        c.execute('INSERT OR IGNORE INTO organization_owners(user_id) VALUES(?)', (owner,))
        teacher = c.execute("INSERT INTO teachers(user_id,subject) VALUES(?,?)", (owner, '数学')).lastrowid
        parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,'x','parent')",
            ('046' + uuid.uuid4().hex[:8], name + '家长')).lastrowid
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        student = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,archived)
            VALUES(?,?,?,?,0,?)''', (name, '数学', parent, profile, archived)).lastrowid
        return owner, teacher, student

    def _series(self, c, owner, teacher, student, start, endless=1):
        series = uuid.uuid4().hex
        template = {'title': '旧课', 'teacher_id': teacher, 'starts_at': start + 'T16:00',
            'ends_at': start + 'T17:00', 'student_ids': [student], 'amount': '1', 'location': '', 'color': 'green'}
        c.execute('''INSERT INTO lesson_series(id,interval_days,endless,next_index,stop_index,template,created_by)
            VALUES(?,7,?,1,NULL,?,?)''', (series, endless, json.dumps(template), owner))
        lesson = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,series_id,occurrence_index)
            VALUES(?,?,?,?,100,'',?,?,?,0)''',
            (teacher, '旧课', start + 'T16:00', start + 'T17:00', owner, uuid.uuid4().hex, series)).lastrowid
        c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (lesson, student))
        return series, lesson

    def test_archived_2026_series_does_not_grow_and_cleanup_spares_january(self):
        with server.connect() as c:
            owner, teacher, archived = self._people(c, 'Sia', 1)
            _, _, active = self._people(c, '在读', 0)
            stale, _old = self._series(c, owner, teacher, archived, '2026-09-07')
            live, _kept = self._series(c, owner, teacher, active, '2026-11-02')
            january, january_lesson = self._series(c, owner, teacher, archived, '2027-01-25', endless=0)
            c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,series_id,occurrence_index,status)
                VALUES(?,?,?,?,100,'',?,?,?,2,'completed')''',
                (teacher, '旧课', '2026-09-21T16:00', '2026-09-21T17:00', owner, uuid.uuid4().hex, stale))
            future = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,series_id,occurrence_index)
                VALUES(?,?,?,?,100,'',?,?,?,60)''',
                (teacher, '旧课', '2027-11-29T16:00', '2027-11-29T17:00', owner, uuid.uuid4().hex, stale)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (future, archived))
            reported = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,series_id,occurrence_index)
                VALUES(?,?,?,?,100,'',?,?,?,61)''',
                (teacher, '旧课', '2027-12-06T16:00', '2027-12-06T17:00', owner, uuid.uuid4().hex, stale)).lastrowid
            c.execute('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', (reported, archived))
            ledger = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
                VALUES(?,-100,'lesson','2027-12-06','已上',?,?)''', (archived, owner, uuid.uuid4().hex)).lastrowid
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'上过了','','',?,?)''', (reported, archived, ledger, owner))
            before = c.execute('SELECT COUNT(*) n FROM lessons WHERE series_id=?', (stale,)).fetchone()['n']
            recurrence.extend(c, '2028-02-01', server.units, server.text_value)
            self.assertEqual(c.execute('SELECT COUNT(*) n FROM lessons WHERE series_id=?', (stale,)).fetchone()['n'], before)
            self.assertGreater(c.execute('SELECT COUNT(*) n FROM lessons WHERE series_id=?', (live,)).fetchone()['n'], 1)
            shown = recurrence.teacher_name(c, {'teacher_id': teacher})
            self.assertEqual(shown, 'Helen')
            env = {**os.environ, 'LESSON_DB': str(DB)}
            c.commit()
        report = subprocess.run([sys.executable, str(REPORT)], env=env, capture_output=True, text=True, check=True)
        self.assertIn('2027-11-29', report.stdout)
        self.assertIn('Helen', report.stdout)
        self.assertNotIn('2027-01-25', report.stdout)
        dry = subprocess.run([sys.executable, str(CLEAN)], env=env, capture_output=True, text=True, check=True)
        self.assertIn('未写入', dry.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (future,)).fetchone()[0], 1)
        applied = subprocess.run([sys.executable, str(CLEAN), '--apply'], env=env, capture_output=True, text=True, check=True)
        self.assertIn('已删除', applied.stdout)
        with sqlite3.connect(DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (future,)).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (reported,)).fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM lessons WHERE id=?', (january_lesson,)).fetchone()[0], 1)
            rule = c.execute('SELECT endless FROM lesson_series WHERE id=?', (stale,)).fetchone()
            self.assertEqual(rule[0], 0)


if __name__ == '__main__':
    unittest.main()
