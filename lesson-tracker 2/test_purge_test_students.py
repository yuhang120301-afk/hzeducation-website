"""Atticus and Benjamin lose lessons from December 2026 on, and cancelled ones."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'purge.sqlite3')

import scripts.purge_test_students_after as job


def build():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    c.executescript('''
        CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, profile_id INTEGER, course TEXT);
        CREATE TABLE lesson_series (
            id TEXT PRIMARY KEY, endless INTEGER, next_index INTEGER, stop_index INTEGER,
            template TEXT, error TEXT, version INTEGER);
        CREATE TABLE lessons (
            id INTEGER PRIMARY KEY, title TEXT, starts_at TEXT, ends_at TEXT, status TEXT, series_id TEXT);
        CREATE TABLE lesson_students (lesson_id INTEGER, student_id INTEGER);
        CREATE TABLE lesson_reports (lesson_id INTEGER, student_id INTEGER, ledger_id INTEGER, fee_cents INTEGER);
        CREATE TABLE report_edits (id INTEGER PRIMARY KEY, lesson_id INTEGER);
        CREATE TABLE ledger (
            id INTEGER PRIMARY KEY, student_id INTEGER, delta INTEGER, request_id TEXT, reversal_of INTEGER);
        CREATE TABLE arrears (id INTEGER PRIMARY KEY, student_id INTEGER, lesson_id INTEGER, settled INTEGER);
    ''')
    c.execute("INSERT INTO students VALUES (1,'Atticus',10,'写作')")
    c.execute("INSERT INTO students VALUES (2,'Benjamin',20,'数学')")
    c.execute("INSERT INTO students VALUES (3,'Cathy',30,'英语')")
    template = json.dumps({'student_ids': [1]})
    c.execute("INSERT INTO lesson_series VALUES ('atticus',1,5,NULL,?, '冲突', 1)", (template,))
    c.execute("INSERT INTO lesson_series VALUES ('shared',1,3,NULL,?, '', 1)", (json.dumps({'student_ids': [1, 3]}),))
    c.execute("INSERT INTO lesson_series VALUES ('only-future',1,2,NULL,?, '', 1)", (template,))
    c.execute("INSERT INTO lessons VALUES (1,'写作','2026-11-28T19:00','2026-11-28T20:00','scheduled','atticus')")
    c.execute("INSERT INTO lesson_students VALUES (1,1)")
    c.execute("INSERT INTO lessons VALUES (2,'写作','2026-12-05T19:00','2026-12-05T20:00','scheduled','atticus')")
    c.execute("INSERT INTO lesson_students VALUES (2,1)")
    c.execute("INSERT INTO lessons VALUES (3,'写作','2027-12-26T19:00','2027-12-26T20:00','scheduled','atticus')")
    c.execute("INSERT INTO lesson_students VALUES (3,1)")
    c.execute("INSERT INTO lessons VALUES (4,'写作','2026-11-07T19:00','2026-11-07T20:00','cancelled','atticus')")
    c.execute("INSERT INTO lesson_students VALUES (4,1)")
    c.execute("INSERT INTO report_edits VALUES (1,4)")
    c.execute("INSERT INTO lessons VALUES (5,'小班','2026-12-12T10:00','2026-12-12T11:00','scheduled','shared')")
    c.execute("INSERT INTO lesson_students VALUES (5,1)")
    c.execute("INSERT INTO lesson_students VALUES (5,3)")
    c.execute("INSERT INTO lessons VALUES (6,'数学','2026-11-20T17:30','2026-11-20T19:00','scheduled','only-future')")
    c.execute("INSERT INTO lesson_students VALUES (6,2)")
    c.execute("INSERT INTO lessons VALUES (7,'数学','2026-12-01T17:30','2026-12-01T19:00','scheduled','only-future')")
    c.execute("INSERT INTO lesson_students VALUES (7,2)")
    c.execute("INSERT INTO lessons VALUES (8,'写作','2027-01-02T19:00','2027-01-02T20:00','scheduled','atticus')")
    c.execute("INSERT INTO lesson_students VALUES (8,1)")
    c.execute("INSERT INTO lesson_reports VALUES (8,1,9,0)")
    c.execute("INSERT INTO ledger VALUES (9,1,0,'scheduled-8-student-1',NULL)")
    c.execute("INSERT INTO lessons VALUES (9,'写作','2027-02-06T19:00','2027-02-06T20:00','completed','atticus')")
    c.execute("INSERT INTO lesson_students VALUES (9,1)")
    c.execute("INSERT INTO lesson_reports VALUES (9,1,10,5100)")
    c.execute("INSERT INTO ledger VALUES (10,1,-100,'scheduled-9-student-1',NULL)")
    c.execute('ALTER TABLE lessons ADD COLUMN occurrence_index INTEGER')
    c.execute('UPDATE lessons SET occurrence_index=id')
    return c


class PurgeTests(unittest.TestCase):
    def test_future_and_cancelled_go_paid_and_past_stay(self):
        c = build()
        students = job.target_students(c)
        actions = job.classify(c, students)
        series = job.series_plan(c, students, actions)
        text = '\n'.join(job.describe(students, actions, series))
        self.assertIn('以后的课', text)
        self.assertIn('已取消', text)
        by_id = {item['lesson']['id']: item['kind'] for item in actions}
        self.assertEqual(by_id[2], 'delete')
        self.assertEqual(by_id[3], 'delete')
        self.assertEqual(by_id[4], 'delete')
        self.assertEqual(by_id[5], 'unlink')
        self.assertEqual(by_id[7], 'delete')
        self.assertEqual(by_id[8], 'delete')
        self.assertEqual(by_id[9], 'keep')
        self.assertNotIn(1, by_id)
        self.assertNotIn(6, by_id)
        kinds = {item['rule']['id']: item['kind'] for item in series}
        self.assertEqual(kinds['only-future'], 'end')
        self.assertEqual(kinds['shared'], 'strip')
        self.assertEqual(kinds['atticus'], 'end')
        job.apply_actions(c, actions, series)
        self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=1').fetchone())
        self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=6').fetchone())
        self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=9').fetchone())
        self.assertIsNone(c.execute('SELECT 1 FROM lessons WHERE id=2').fetchone())
        self.assertIsNone(c.execute('SELECT 1 FROM lessons WHERE id=4').fetchone())
        self.assertIsNone(c.execute('SELECT 1 FROM lessons WHERE id=8').fetchone())
        self.assertIsNone(c.execute('SELECT 1 FROM ledger WHERE id=9').fetchone())
        self.assertIsNotNone(c.execute('SELECT 1 FROM ledger WHERE id=10').fetchone())
        self.assertIsNone(c.execute('SELECT 1 FROM report_edits WHERE lesson_id=4').fetchone())
        self.assertEqual([row['student_id'] for row in c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=5')], [3])
        ended = c.execute('SELECT endless, stop_index FROM lesson_series WHERE id=?', ('atticus',)).fetchone()
        self.assertEqual(ended['endless'], 0)
        self.assertGreaterEqual(ended['stop_index'], 1)
        shared = json.loads(c.execute('SELECT template FROM lesson_series WHERE id=?', ('shared',)).fetchone()['template'])
        self.assertEqual(shared['student_ids'], [3])
        self.assertNotIn('2026-12-01', ' '.join(row['starts_at'] for row in c.execute("SELECT starts_at FROM lessons l JOIN lesson_students ls ON ls.lesson_id=l.id WHERE ls.student_id IN (1,2)")))


if __name__ == '__main__':
    unittest.main()
