"""The monthly page ties money, lessons, hours, pay and forfeits together."""
import os
import tempfile
import unittest
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'month.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import finance
import server


class MonthlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_empty_month_lists_a_balance_that_does_not_match(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            owner = {'id': uid, 'role': 'owner'}
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0499000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Mia','数学',?,?,400)",
                (parent, profile))
            report = finance.monthly(c, owner, '2026-11')
            self.assertEqual(report['month'], '2026-11')
            self.assertEqual(report['money_received_cents'], 0)
            self.assertEqual(report['teacher_pay_cents'], 0)
            self.assertEqual(report['cost_cents'], 0)
            self.assertEqual(report['forfeit_units'], 0)
            self.assertTrue(any('不一致' in item for item in report['exceptions']))


if __name__ == '__main__':
    unittest.main()
