"""退课/停课 writes one document and a forfeited balance is not cash."""
import os
import tempfile
import unittest
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'settle.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import auditlog
import deletion
import server


class SettleCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_void_balance_is_not_income_and_keep_stays(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0455000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0455000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            voided = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Mia','数学',?,?,200)",
                (parent, profile)).lastrowid
            kept = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Mia','英语',?,?,150)",
                (parent, profile)).lastrowid
            with self.assertRaises(ValueError):
                deletion.settle_course(c, owner, {'student_id': voided})
            done = deletion.settle_course(c, owner, {'student_id': voided, 'reason': 'void'})
            self.assertEqual(done['reason'], 'void')
            self.assertEqual(c.execute('SELECT balance, archived FROM students WHERE id=?', (voided,)).fetchone()['balance'], 0)
            self.assertIsNone(c.execute('SELECT 1 FROM cash_entries').fetchone())
            note = c.execute("SELECT note FROM vouchers WHERE student_id=? AND kind='stop'", (voided,)).fetchone()['note']
            self.assertEqual(note, '作废余额')
            self.assertIsNotNone(c.execute("SELECT 1 FROM profile_events WHERE student_id=? AND action='stop'", (voided,)).fetchone())
            deletion.settle_course(c, owner, {'student_id': kept, 'reason': 'keep'})
            self.assertEqual(c.execute('SELECT balance, archived FROM students WHERE id=?', (kept,)).fetchone()['balance'], 150)
            last = auditlog.last_for(c, owner)
            self.assertIn('停课，余额保留', last['entry']['summary'])


if __name__ == '__main__':
    unittest.main()
