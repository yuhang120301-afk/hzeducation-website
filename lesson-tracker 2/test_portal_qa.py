"""Portal fixes that do not need the running site."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'qa.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import auditlog
import finance
import pricing
import server
import teaching


class PortalQaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_audit_search_returns_a_list(self):
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0413000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            c.execute("INSERT INTO audit_log(actor_id,action,summary,ops_json) VALUES(?, 'update', '改了一处', '[]')", (uid,))
            found = auditlog.search(c, {'id': uid, 'role': 'owner'}, None, None, None)
        self.assertIsInstance(found['entries'], list)
        self.assertEqual(found['entries'][0]['summary'], '改了一处')

    def test_subject_names_match_and_prices_sort_by_year(self):
        self.assertEqual(teaching.canonical_subject('Science'), '科学')
        self.assertEqual(teaching.canonical_subject('English GA'), '英语')
        self.assertEqual(teaching.display_person('HELEN'), 'Helen')
        with server.connect() as c:
            pricing.seed_2027(c)
            pricing.publish_seed(c)
            owner = {'id': 1, 'role': 'owner'}
            rows = pricing.list_prices(c, owner)['tables'][0]['rows']
            order = [row['level_from'] for row in rows if row['product']=='one_to_one']
            self.assertEqual(order, sorted(order, key=pricing.level_rank))

    def test_packs_infer_type_from_the_course_name(self):
        with server.connect() as c:
            if not c.execute("SELECT 1 FROM price_tables WHERE effective_from='2027-01-01'").fetchone():
                pricing.seed_2027(c)
                pricing.publish_seed(c)
            uid = c.execute("SELECT user_id FROM organization_owners LIMIT 1").fetchone()
            if not uid:
                uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0413000009','Helen','x','admin')").lastrowid
                c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            else:
                uid = uid[0]
            parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES(?, '家长','x','parent')", ('0413'+uuid.uuid4().hex[:6],)).lastrowid
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
            sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,grade,level_code,level_year)
                VALUES('Atticus','数学 一对一',?,?,0,'Year 5','Y5',2027)''', (parent, profile)).lastrowid
            offer = pricing.presets(c, {'id': uid, 'role': 'owner'}, student_id=sid, day='2027-03-01')
        self.assertEqual(offer['course_type'], '一对一')
        self.assertTrue(offer['packages'])

    def test_zero_balance_is_not_arrears_when_the_same_subject_has_credit(self):
        active = [{'id': 1, 'profile_id': 9, 'balance': 0, 'subject_name': '数学', 'course': '数学'},
                  {'id': 2, 'profile_id': 9, 'balance': 500, 'subject_name': '数学', 'course': '数学 #2'}]
        self.assertTrue(finance._covered_by_sibling(active, {'student_id': 1, 'profile_id': 9, 'subject_name': '数学', 'course': '数学'}))
        self.assertFalse(finance._covered_by_sibling(active, {'student_id': 3, 'profile_id': 9, 'subject_name': '英语', 'course': '英语'}))
        self.assertFalse(finance._covered_by_sibling(active, {'student_id': 4, 'profile_id': 9, 'subject_name': '', 'course': 'Science'}))
