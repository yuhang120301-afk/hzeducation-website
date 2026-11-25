"""Old packs keep a snapshot of their price, and price_for is the lookup."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'price.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import pricing
import server


class PriceSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_price_for_combo_and_snapshot_is_dry_run_first(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0477000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            pricing.schema(c)
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0477000002','家长','x','parent')").lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            subject = c.execute("SELECT id FROM subjects WHERE name='数学 + 英语'").fetchone()['id']
            kind = c.execute("SELECT id FROM course_types WHERE name='小班课'").fetchone()['id']
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,subject_id,course_type_id,level_code)
                VALUES('Mia','数学 + 英语',?,?,0,?,?,'Prep')''', (parent, profile, subject, kind)).lastrowid
            student = c.execute('SELECT * FROM students WHERE id=?', (sid,)).fetchone()
            self.assertEqual(pricing.price_for(c, student, '2027-03-01'), pricing.COMBO_HOURLY_CENTS)
            ledger = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,200,'credit','2027-03-01','充值',?, 'snap-1')",
                (sid, uid)).lastrowid
            c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on,unit_fees)
                VALUES(?,?,200,0,200,0,'2027-03-01','')''', (sid, ledger))
            c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,recorded_by) VALUES(?,17000,?,?)',
                (ledger, 'bank', uid))
        script = Path(__file__).with_name('scripts') / 'snapshot_pack_prices.py'
        env = {**os.environ, 'LESSON_DB': str(DB)}
        dry = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, check=True)
        self.assertIn('DRY-RUN', dry.stdout)
        self.assertIn('未写入', dry.stdout)
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT unit_fees FROM credit_batches').fetchone()['unit_fees'], '')
        applied = subprocess.run([sys.executable, str(script), '--apply'], env=env, capture_output=True, text=True, check=True)
        self.assertIn('已写入 1', applied.stdout)
        with server.connect() as c:
            fees = json.loads(c.execute('SELECT unit_fees FROM credit_batches').fetchone()['unit_fees'])
            self.assertEqual(len(fees), 2)
            self.assertGreater(fees[0], 0)


if __name__ == '__main__':
    unittest.main()
