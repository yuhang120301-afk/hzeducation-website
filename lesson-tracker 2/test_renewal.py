"""Renewal uses paid hours on the packs, not gift hours."""
import os
import tempfile
import unittest
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'renew.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import finance
import server


class RenewalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_gift_hours_do_not_count_as_paid(self):
        with server.connect() as c:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0488000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            gift = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('礼','数学',?,?,800)",
                (parent, profile)).lastrowid
            paid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('付','英语',?,?,800)",
                (parent, profile)).lastrowid
            c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on)
                VALUES(?,0,800,0,800,'2026-11-01')''', (gift,))
            c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on)
                VALUES(?,800,0,800,0,'2026-11-01')''', (paid,))
            low = {row['id'] for row in finance.low_balance(c)}
            self.assertIn(gift, low)
            self.assertNotIn(paid, low)


if __name__ == '__main__':
    unittest.main()
