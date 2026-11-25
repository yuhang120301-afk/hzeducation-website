"""The student card's 剩余课时 is paid hours. Gift hours are a separate line."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

DB = Path(tempfile.mkdtemp()) / 'card-hours.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import credit_batches
import server

ROOT = Path(__file__).resolve().parent


class CardHourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_paid_balance_leaves_gift_hours_out(self):
        with server.connect() as c:
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
                (('046' + uuid.uuid4().hex)[:15], '家长', 'x')).lastrowid
            profile = c.execute("INSERT INTO student_profiles(name) VALUES('Mia')").lastrowid
            sid = c.execute("INSERT INTO students(name,course,parent_id,profile_id,balance) VALUES('Mia','数学',?,?,1200)",
                (parent, profile)).lastrowid
            c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on)
                VALUES(?,?,?,?,?,?)''', (sid, 1000, 200, 800, 200, '2026-10-01'))
            person = dict(c.execute('SELECT * FROM students WHERE id=?', (sid,)).fetchone())
            credit_batches.enrich(c, [person])
            self.assertEqual(person['paid_balance'], 800)
            self.assertEqual(person['gift_balance'], 200)
            self.assertEqual(person['balance'], 1200)

    def test_card_labels_paid_hours_and_always_shows_gift_hours(self):
        app = (ROOT / 'static' / 'app.js').read_text()
        pay = (ROOT / 'static' / 'pay.js').read_text()
        overview = (ROOT / 'static' / 'teaching.js').read_text()
        card = app[app.index('function studentListCard'):app.index('const YEAR_LEVEL_ORDER')]
        self.assertIn('剩余课时', card)
        self.assertIn('剩余赠送课时', card)
        self.assertLess(card.index('剩余课时'), card.index('剩余赠送课时'))
        self.assertIn('regularHours(account)', card)
        self.assertIn('gift_balance||0', card)
        parent = app[app.index('function parentCards'):app.index('function personKey')]
        self.assertIn('剩余课时', parent)
        self.assertIn('剩余赠送课时', parent)
        self.assertIn('gift_balance||0', parent)
        self.assertIn('剩余课时 ${fmt(regularHours(student))}', pay)
        self.assertIn('剩余赠送课时 ${fmt(student.gift_balance||0)}', pay)
        self.assertIn('剩余赠送课时 ${balanceSummary(students,true)}', overview)
        self.assertIn('function regularHours(s){return s.paid_balance??s.balance;}', app)


if __name__ == '__main__':
    unittest.main()
