"""New code must open a pre-pay database without dropping or rewriting rows."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

TMP = tempfile.mkdtemp()
DB = str(Path(TMP) / 'old.sqlite3')
os.environ['LESSON_DB'] = DB
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'


def build_old_database(path):
    """Schema as it is on the live site before this pay change, plus real rows."""
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','parent')),
            active INTEGER NOT NULL DEFAULT 1,
            contact_phone TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE students (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, course TEXT NOT NULL,
            parent_id INTEGER NOT NULL REFERENCES users(id),
            balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
            profile_id INTEGER, archived INTEGER NOT NULL DEFAULT 0,
            billing_unit TEXT NOT NULL DEFAULT 'lesson',
            birthday TEXT NOT NULL DEFAULT '', grade TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE ledger (
            id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id),
            delta INTEGER NOT NULL, kind TEXT NOT NULL, lesson_date TEXT NOT NULL,
            note TEXT NOT NULL, actor_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            request_id TEXT UNIQUE NOT NULL, reversal_of INTEGER UNIQUE REFERENCES ledger(id),
            paid_delta INTEGER NOT NULL DEFAULT 0, gift_delta INTEGER NOT NULL DEFAULT 0,
            gift_void INTEGER NOT NULL DEFAULT 0, split_known INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE attempts (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
        CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE teachers (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            subject TEXT NOT NULL DEFAULT '数学', subjects TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE lessons (
            id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
            title TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
            planned_units INTEGER NOT NULL, location TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'scheduled', cancel_reason TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1, created_by INTEGER NOT NULL REFERENCES users(id),
            request_id TEXT NOT NULL UNIQUE, color TEXT NOT NULL DEFAULT 'green',
            series_id TEXT, occurrence_index INTEGER
        );
        CREATE TABLE lesson_students (
            lesson_id INTEGER NOT NULL, student_id INTEGER NOT NULL, PRIMARY KEY(lesson_id, student_id)
        );
        CREATE TABLE lesson_reports (
            lesson_id INTEGER NOT NULL, student_id INTEGER NOT NULL,
            amount INTEGER NOT NULL, content TEXT NOT NULL DEFAULT '',
            homework TEXT NOT NULL DEFAULT '', feedback TEXT NOT NULL DEFAULT '',
            ledger_id INTEGER UNIQUE, updated_by INTEGER NOT NULL,
            PRIMARY KEY(lesson_id, student_id)
        );
        CREATE TABLE organization_owners (user_id INTEGER PRIMARY KEY);
        CREATE TABLE student_profiles (id INTEGER PRIMARY KEY);
        ''')
        c.execute("INSERT INTO users(id,phone,name,password,role) VALUES(1,'0400111222','Helen','x','admin')")
        c.execute("INSERT INTO users(id,phone,name,password,role) VALUES(2,'0400333444','陈家长','x','parent')")
        c.execute('INSERT INTO organization_owners VALUES(1)')
        c.execute('INSERT INTO student_profiles(id) VALUES(1)')
        c.execute("INSERT INTO students(id,name,course,parent_id,balance,profile_id,notes) VALUES(7,'陈一诺','数学 · 一对一',2,1350,1,'内部备注保留')")
        c.execute("INSERT INTO ledger(id,student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(3,7,2000,'credit','2026-09-01','购入 20 课时',1,?)", (uuid.uuid4().hex,))
        c.execute("INSERT INTO ledger(id,student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(4,7,-650,'lesson','2026-09-20','历史上课',1,?)", (uuid.uuid4().hex,))
        c.execute("INSERT INTO users(id,phone,name,password,role) VALUES(8,'0400555666','Angela','x','parent')")
        c.execute("INSERT INTO teachers(id,user_id,subject) VALUES(2,8,'数学')")
        c.execute("INSERT INTO lessons(id,teacher_id,title,starts_at,ends_at,planned_units,status,created_by,request_id) VALUES(9,2,'数学 · 一对一','2026-10-01T16:00','2026-10-01T17:00',100,'completed',1,?)", (uuid.uuid4().hex,))
        c.execute('INSERT INTO lesson_students VALUES(9,7)')
        c.execute("INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,updated_by) VALUES(9,7,100,'通分与约分','练习册','掌握良好',1)")
        for key in ('schedule_options_v1', 'credit_batches_v1', 'series_links_v1'):
            c.execute('INSERT INTO app_meta VALUES(?,?)', (key, '1'))


build_old_database(DB)
import server


class OldDatabaseMigrationTests(unittest.TestCase):
    def test_startup_keeps_existing_rows_and_only_adds_columns(self):
        before = snapshot(DB)
        server.initialize()
        server.initialize()
        after = snapshot(DB)
        self.assertEqual(before['students'], after['students_core'])
        self.assertEqual(before['ledger'], after['ledger'])
        self.assertEqual(before['reports'], after['reports_core'])
        self.assertEqual(after['helen_original'], [(7, 0)])
        self.assertEqual(after['fee'], [(9, 7, None, 0)])
        self.assertTrue(after['pay_tables'])
        rule = after['angela_rule']
        self.assertIsNotNone(rule)
        self.assertEqual(rule[0], 4000)
        self.assertEqual(rule[1], 3500)
        self.assertEqual(after['student_count'], 1)
        self.assertEqual(after['ledger_count'], 2)


def snapshot(path):
    with sqlite3.connect(path) as c:
        students = c.execute('SELECT id,name,course,balance,notes FROM students ORDER BY id').fetchall()
        ledger = c.execute('SELECT id,student_id,delta,kind,note FROM ledger ORDER BY id').fetchall()
        reports = c.execute('SELECT lesson_id,student_id,amount,content,homework,feedback FROM lesson_reports ORDER BY lesson_id').fetchall()
        helen = fee = angela = None
        cols = {row[1] for row in c.execute('PRAGMA table_info(students)')}
        if 'helen_original' in cols:
            helen = c.execute('SELECT id,helen_original FROM students ORDER BY id').fetchall()
        report_cols = {row[1] for row in c.execute('PRAGMA table_info(lesson_reports)')}
        if 'fee_cents' in report_cols:
            fee = c.execute('SELECT lesson_id,student_id,fee_cents,fee_overridden FROM lesson_reports').fetchall()
        tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'pay_rules' in tables:
            angela = c.execute("SELECT percent_bp, hourly_floor_cents FROM pay_rules JOIN teachers ON teachers.id=pay_rules.teacher_id JOIN users ON users.id=teachers.user_id WHERE users.name='Angela'").fetchone()
        return {'students': students, 'students_core': students, 'ledger': ledger, 'reports': reports,
            'reports_core': reports, 'helen_original': helen, 'fee': fee, 'pay_tables': 'pay_rules' in tables,
            'angela_rule': angela, 'student_count': len(students), 'ledger_count': len(ledger)}


if __name__ == '__main__':
    unittest.main(verbosity=2)
