"""Endless series close, and only clashing December lessons for two students go."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'stop-endless.sqlite3')

import scripts.stop_endless_series as job


def build():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    c.executescript('''
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE teachers (id INTEGER PRIMARY KEY, user_id INTEGER, subject TEXT);
        CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, profile_id INTEGER);
        CREATE TABLE lesson_series (
            id TEXT PRIMARY KEY, interval_days INTEGER, endless INTEGER, next_index INTEGER,
            stop_index INTEGER, template TEXT, created_by INTEGER, version INTEGER, error TEXT);
        CREATE TABLE lessons (
            id INTEGER PRIMARY KEY, teacher_id INTEGER, title TEXT, starts_at TEXT, ends_at TEXT,
            status TEXT, series_id TEXT, occurrence_index INTEGER, subject_id INTEGER);
        CREATE TABLE lesson_students (lesson_id INTEGER, student_id INTEGER);
        CREATE TABLE lesson_reports (lesson_id INTEGER, student_id INTEGER, ledger_id INTEGER);
    ''')
    c.execute("INSERT INTO users VALUES (1,'Helen')")
    c.execute("INSERT INTO teachers VALUES (1,1,'数学')")
    c.execute("INSERT INTO students VALUES (1,'Atticus',10)")
    c.execute("INSERT INTO students VALUES (2,'Benjamin',20)")
    c.execute("INSERT INTO students VALUES (3,'Cathy',30)")
    c.execute('''INSERT INTO lesson_series VALUES ('old',7,1,3,NULL,'{"starts_at":"2026-11-07T19:00","ends_at":"2026-11-07T20:00"}',1,1,'2027-11-28：冲突')''')
    c.execute('''INSERT INTO lesson_series VALUES ('finite',7,0,2,2,'{}',1,1,'')''')
    # Endless Saturday lesson in December, overlapping a finite lesson.
    c.execute("INSERT INTO lessons VALUES (10,1,'写作','2026-12-05T19:00','2026-12-05T20:00','scheduled','old',1,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (10,1)")
    c.execute("INSERT INTO lessons VALUES (11,1,'数学','2026-12-05T19:00','2026-12-05T20:00','scheduled','finite',1,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (11,1)")
    # Endless December lesson with nobody else at that time. Keep it.
    c.execute("INSERT INTO lessons VALUES (12,1,'英语','2026-12-06T17:00','2026-12-06T18:00','scheduled','old',2,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (12,2)")
    # 2027 overlap. Keep it.
    c.execute("INSERT INTO lessons VALUES (13,1,'写作','2027-01-02T19:00','2027-01-02T20:00','scheduled','old',3,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (13,1)")
    c.execute("INSERT INTO lessons VALUES (14,1,'数学','2027-01-02T19:00','2027-01-02T20:00','scheduled','finite',2,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (14,1)")
    # December clash that already has a record. Keep it.
    c.execute("INSERT INTO lessons VALUES (15,1,'写作','2026-12-12T19:00','2026-12-12T20:00','scheduled','old',4,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (15,1)")
    c.execute("INSERT INTO lessons VALUES (16,1,'数学','2026-12-12T19:00','2026-12-12T20:00','scheduled','finite',3,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (16,1)")
    c.execute("INSERT INTO lesson_reports VALUES (15,1,NULL)")
    # Shared class. Only take Atticus off.
    c.execute("INSERT INTO lessons VALUES (17,1,'小班','2026-12-19T10:00','2026-12-19T11:00','scheduled','old',5,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (17,1)")
    c.execute("INSERT INTO lesson_students VALUES (17,3)")
    c.execute("INSERT INTO lessons VALUES (18,1,'另一班','2026-12-19T10:00','2026-12-19T11:00','scheduled',NULL,NULL,NULL)")
    c.execute("INSERT INTO lesson_students VALUES (18,3)")
    return c


class StopEndlessTests(unittest.TestCase):
    def test_only_december_clashes_are_removed_and_series_close(self):
        c = build()
        people = job.target_people(c)
        remove, skipped = job.december_plan(c, ['old'], people)
        self.assertEqual(sorted(record['lesson']['id'] for record in remove), [10, 17])
        self.assertEqual([record['lesson']['id'] for record in skipped], [15])
        self.assertIn('同一学生', remove[0]['clashes'][0][1])
        text = '\n'.join(job.lesson_lines(remove[0], '将去掉'))
        self.assertIn('2026-12-05', text)
        self.assertIn('周六', text)
        self.assertIn('系列 old', text)
        self.assertIn('#11', text)
        job.apply_series(c, job.load_series(c))
        job.apply_december(c, remove, people)
        closed = c.execute('SELECT endless, stop_index, error FROM lesson_series WHERE id=?', ('old',)).fetchone()
        self.assertEqual(closed['endless'], 0)
        self.assertEqual(closed['stop_index'], 6)
        self.assertEqual(closed['error'], '')
        self.assertIsNone(c.execute('SELECT 1 FROM lessons WHERE id=10').fetchone())
        self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=12').fetchone())
        self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=13').fetchone())
        self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=15').fetchone())
        self.assertIsNotNone(c.execute('SELECT 1 FROM lessons WHERE id=17').fetchone())
        self.assertEqual(c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=17').fetchall()[0]['student_id'], 3)


if __name__ == '__main__':
    unittest.main()
