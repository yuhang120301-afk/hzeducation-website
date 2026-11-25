"""Relinking parents moves the named courses and leaves everyone else, and the books, alone."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'relink.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server
from scripts import relink_parents as relink


class RelinkParentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_known_families_leave_linjing_and_keep_the_books(self):
        with server.connect() as c:
            owner = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0455000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (owner,))
            linjing = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0470702742','林静','x','parent')").lastrowid
            jeffery = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0449917255','Jeffery家长','x','parent')").lastrowid
            ruby_parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0430155816','Ruby家长','x','parent')").lastrowid
            ruby = self.course(c, 'Ruby', ruby_parent, '数学')
            zachary = self.person(c, 'Zachary', linjing, ('数学', '英语'))
            sunny = self.person(c, 'Sunny', linjing, ('数学',))
            shirley = self.person(c, 'Shirley', linjing, ('数学',))
            amelia = self.person(c, 'Amelia', linjing, ('数学', '英语'))
            joanna = self.person(c, 'Joanna', linjing, ('数学',))
            cathy = self.person(c, 'Cathy', linjing, ('数学',))
            sister = self.person(c, 'Cathy 妹妹', linjing, ('数学',))
            david = self.person(c, 'David', linjing, ('数学',))
            felix = self.person(c, 'Felix', linjing, ('数学',))
            bella = self.person(c, 'Bella', linjing, ('数学', '英语'))
            zoey = self.person(c, 'Zoey', linjing, ('数学',))
            c.execute(
                "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,100,'credit','2026-11-01','充值',?,?)",
                (joanna[0], owner, uuid.uuid4().hex))
            before = relink.counts(c)
            source = {'id': linjing, 'name': '林静', 'phone': '0470702742'}
            moves = [
                self.move(zachary, 'Zachary', linjing, '林静', '0470702742'),
                self.move(sunny, 'Sunny', linjing, '林静', '0470702742'),
                self.move(shirley + amelia, None, 'new:Shirley/Amelia家长'),
                self.move(joanna, 'Joanna', jeffery, 'Jeffery家长', '0449917255'),
                self.move(cathy, 'Cathy', 'new:Cathy家长'),
                self.move([sister[0]], 'Cathy 妹妹', 'new:Cathy家长'),
                self.move(david, 'David', 'new:David/Felix家长'),
                self.move(felix, 'Felix', 'new:David/Felix家长'),
                self.move(bella, 'Bella', ruby_parent, 'Ruby家长', '0430155816'),
                self.move(zoey, 'Zoey', 'new:Zoey家长（待定）'),
            ]
            groups = relink.build_groups(c, source, [relink.normalize_move(item) for item in moves])
            lines = relink.describe(c, source, groups)
            self.assertTrue(any(line.startswith('保持') and 'Zachary' in line for line in lines))
            relink.apply_groups(c, owner, source, groups)
            self.assertEqual(relink.counts(c), before)
            self.assertEqual(self.parent_of(c, zachary), linjing)
            self.assertEqual(self.parent_of(c, sunny), linjing)
            family = self.parent_of(c, shirley)
            self.assertEqual(self.parent_of(c, amelia), family)
            self.assertNotEqual(family, linjing)
            self.assertTrue(c.execute('SELECT phone FROM users WHERE id=?', (family,)).fetchone()['phone'].startswith('pending-'))
            self.assertEqual(self.parent_of(c, joanna), jeffery)
            self.assertEqual(self.parent_of(c, cathy), self.parent_of(c, sister))
            self.assertEqual(self.parent_of(c, david), self.parent_of(c, felix))
            self.assertEqual(self.parent_of(c, bella), ruby_parent)
            self.assertEqual(c.execute('SELECT parent_id FROM students WHERE id=?', (ruby,)).fetchone()['parent_id'], ruby_parent)
            zoey_parent = self.parent_of(c, zoey)
            self.assertEqual(c.execute('SELECT name FROM users WHERE id=?', (zoey_parent,)).fetchone()['name'], 'Zoey家长（待定）')
            self.assertNotIn(linjing, self.links(c, zoey))
            self.assertGreaterEqual(relink.parent_count(c, self.profile(c, zoey)), 1)
            relink.apply_groups(c, owner, source, relink.build_groups(c, source, [relink.normalize_move(item) for item in moves]))
            self.assertEqual(self.parent_of(c, amelia), family)
            self.assertEqual(relink.counts(c), before)
            with self.assertRaises(relink.PlanError):
                relink.build_groups(c, source, [relink.normalize_move({'student_ids': [joanna[0]], 'names': {'%s' % joanna[0]: '不是Joanna'}, 'parent': jeffery})])

    def test_bundled_map_covers_the_families_helen_named(self):
        path = Path(__file__).with_name('scripts') / 'relink_linjing_parents.json'
        source, moves = relink.load_mapping(str(path), [])
        self.assertEqual(source['id'], 46)
        text = path.read_text()
        for token in ('Zachary', 'Sunny', 'Shirley/Amelia家长', 'Jeffery家长', '0449917255', 'Cathy家长', 'David/Felix家长', 'Ruby家长', '0430155816', 'Zoey家长（待定）'):
            self.assertIn(token, text)
        parents = [item['parent'] for item in moves]
        self.assertIn('new:Zoey家长（待定）', parents)
        self.assertIn(10, parents)
        self.assertEqual(len(moves), 8)

    def person(self, c, name, parent, courses):
        return [self.course(c, name, parent, course, profile=None if index else 'new') for index, course in enumerate(courses)]

    def course(self, c, name, parent, course, profile='new'):
        if profile == 'new':
            profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        elif profile is None:
            profile = c.execute('SELECT profile_id FROM students WHERE name=? ORDER BY id DESC LIMIT 1', (name,)).fetchone()['profile_id']
        sid = c.execute(
            'INSERT INTO students(name,course,parent_id,profile_id) VALUES(?,?,?,?)',
            (name, course, parent, profile)).lastrowid
        c.execute('INSERT OR IGNORE INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile, parent))
        return sid

    def move(self, student_ids, name, parent, parent_name='', parent_phone=''):
        names = {}
        if name:
            names = {str(sid): name for sid in student_ids}
        if isinstance(parent, int):
            return {'student_ids': student_ids, 'names': names, 'parent': parent, 'parent_name': parent_name, 'parent_phone': parent_phone}
        return {'student_ids': student_ids, 'names': names, 'parent': parent}

    def parent_of(self, c, student_ids):
        ids = student_ids if isinstance(student_ids, list) else [student_ids]
        found = {c.execute('SELECT parent_id FROM students WHERE id=?', (sid,)).fetchone()['parent_id'] for sid in ids}
        self.assertEqual(len(found), 1)
        return found.pop()

    def links(self, c, student_ids):
        profile = self.profile(c, student_ids)
        return {row['user_id'] for row in c.execute('SELECT user_id FROM profile_parents WHERE profile_id=?', (profile,))}

    def profile(self, c, student_ids):
        sid = student_ids[0] if isinstance(student_ids, list) else student_ids
        return c.execute('SELECT profile_id FROM students WHERE id=?', (sid,)).fetchone()['profile_id']


if __name__ == '__main__':
    unittest.main()
