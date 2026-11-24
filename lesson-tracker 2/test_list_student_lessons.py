"""The read-only lesson list names December 2027 clashes and their series."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'list-lessons.sqlite3')

import extend_2027_series
import scripts.list_student_lessons as report


def build():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    c.executescript('''
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE teachers (id INTEGER PRIMARY KEY, user_id INTEGER);
        CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, profile_id INTEGER, archived INTEGER, course TEXT);
        CREATE TABLE lesson_series (
            id TEXT PRIMARY KEY, endless INTEGER, stop_index INTEGER, template TEXT, error TEXT);
        CREATE TABLE lessons (
            id INTEGER PRIMARY KEY, teacher_id INTEGER, title TEXT, starts_at TEXT, ends_at TEXT,
            status TEXT, series_id TEXT);
        CREATE TABLE lesson_students (lesson_id INTEGER, student_id INTEGER);
        CREATE TABLE lesson_reports (lesson_id INTEGER, student_id INTEGER, ledger_id INTEGER);
    ''')
    c.execute("INSERT INTO users VALUES (1,'Helen')")
    c.execute("INSERT INTO teachers VALUES (1,1)")
    c.execute("INSERT INTO students VALUES (1,'Atticus',10,0,'写作')")
    c.execute("INSERT INTO students VALUES (2,'Benjamin',20,1,'数学')")
    fresh = extend_2027_series.series_id('Atticus · Writing', 5, '19:00')
    template = json.dumps({'teacher_id': 1, 'student_ids': [1], 'starts_at': '2027-02-06T19:00', 'ends_at': '2027-02-06T20:00'})
    old_template = json.dumps({'teacher_id': 1, 'student_ids': [1], 'starts_at': '2026-02-07T19:00', 'ends_at': '2026-02-07T20:00'})
    c.execute('INSERT INTO lesson_series VALUES (?,?,?,?,?)', (fresh, 0, 48, template, ''))
    c.execute('INSERT INTO lesson_series VALUES (?,?,?,?,?)', ('old-finite', 0, 90, old_template, '2027-12-26：这位老师在该时段已有课程'))
    c.execute('INSERT INTO lesson_series VALUES (?,?,?,?,?)', ('other', 0, 10, old_template, '2026-12-01：不在这段日期里'))
    c.execute("INSERT INTO lessons VALUES (10,1,'写作','2027-12-26T19:00','2027-12-26T20:00','scheduled',?)", (fresh,))
    c.execute("INSERT INTO lesson_students VALUES (10,1)")
    c.execute("INSERT INTO lessons VALUES (11,1,'写作','2027-12-26T19:00','2027-12-26T20:00','scheduled','old-finite')")
    c.execute("INSERT INTO lesson_students VALUES (11,1)")
    c.execute("INSERT INTO lessons VALUES (12,1,'数学','2027-12-20T17:30','2027-12-20T19:00','scheduled','old-finite')")
    c.execute("INSERT INTO lesson_students VALUES (12,2)")
    c.execute("INSERT INTO lessons VALUES (13,1,'写作','2027-12-26T19:00','2027-12-26T20:00','cancelled',?)", (fresh,))
    c.execute("INSERT INTO lesson_students VALUES (13,1)")
    c.execute("INSERT INTO lessons VALUES (14,1,'写作','2026-12-26T19:00','2026-12-26T20:00','scheduled','old-finite')")
    c.execute("INSERT INTO lesson_students VALUES (14,1)")
    c.execute("INSERT INTO lesson_reports VALUES (11,1,4)")
    return c, fresh


class ListLessonTests(unittest.TestCase):
    def test_december_2027_clash_names_both_series_and_the_banner(self):
        c, fresh = build()
        text = '\n'.join(report.build(c, ['Atticus', 'Benjamin'], '2027-11-15', '2028-01-31'))
        self.assertIn('#10 2027-12-26 周日 19:00–20:00', text)
        self.assertIn(f'系列{fresh}/2027新系列/已结束/止于48/从2027-02-06', text)
        self.assertIn('系列old-finite/旧的有结束日期的系列/已结束/止于90/从2026-02-07', text)
        self.assertIn('#11 同一学生、同一老师、同一时间（对方旧的有结束日期的系列）', text)
        self.assertIn('#10 同一学生、同一老师、同一时间（对方2027新系列）', text)
        self.assertIn('课程Atticus#1在读', text)
        self.assertIn('课程Benjamin#2已停', text)
        self.assertIn('#12 2027-12-20', text)
        self.assertIn('#13', text)
        self.assertNotIn('#14', text)
        self.assertIn('2027-12-26 19:00 Helen · Atticus：这位老师在该时段已有课程', text)
        self.assertNotIn('不在这段日期里', text)
        self.assertIn('合计 课节4', text)
        self.assertIn('有冲突2', text)
        self.assertIn('横幅1', text)
        cancelled = next(line for line in text.splitlines() if line.startswith('#13'))
        self.assertIn('冲突无', cancelled)
        quiet = next(line for line in text.splitlines() if line.startswith('#12'))
        self.assertIn('冲突无', quiet)


if __name__ == '__main__':
    unittest.main()
