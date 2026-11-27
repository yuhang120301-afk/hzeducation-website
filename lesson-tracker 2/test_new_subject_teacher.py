"""A subject the boss just added can be given to a teacher and keeps its name."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'subjects.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server
import teaching


class NewSubjectTeacherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_new_subjects_stay_assigned_to_an_existing_teacher(self):
        c = server.connect()
        c.execute('BEGIN')
        try:
            phone = '049' + f'{uuid.uuid4().int % 100000000:08d}'
            user_id = c.execute(
                "INSERT INTO users(phone,name,password,role) VALUES(?, 'Vincent', 'x', 'parent')",
                (phone,)).lastrowid
            teacher_id = c.execute(
                "INSERT INTO teachers(user_id, subject) VALUES(?, '数学')", (user_id,)).lastrowid
            c.execute("UPDATE teachers SET subjects=? WHERE id=?", ('["数学"]', teacher_id))
            owner = {'id': 1, 'role': 'owner'}
            created = []
            for name in ('Science 7-10', 'Workshop 4-6'):
                saved = teaching.save_catalog_item(
                    c, owner, 'subjects', {'name': name, 'active': True}, server.text_value)
                created.append(saved['id'])
            teaching.edit_teacher(c, owner, {
                'teacher_id': teacher_id,
                'name': 'Vincent',
                'phone': phone,
                'subjects': ['数学', 'Science 7-10', 'Workshop 4-6'],
            }, server.phone_value, lambda password: 'hashed', server.text_value)
            names = teaching.teacher_subject_names(c, teacher_id)
            self.assertEqual(list(dict.fromkeys(names)), ['数学', 'Science 7-10', 'Workshop 4-6'])
            self.assertNotIn('科学', names)
            known = teaching.subject_names(c)
            self.assertEqual(teaching.canonical_subject('Science 7-10', known), 'Science 7-10')
            self.assertEqual(teaching.canonical_subject('Workshop 4-6', known), 'Workshop 4-6')
            self.assertEqual(teaching.canonical_subject('Science'), '科学')
            self.assertEqual(teaching.canonical_subject('English GA'), '英语')
            state = teaching.state_for(c, owner)
            teacher = next(item for item in state['teachers'] if item['id'] == teacher_id)
            self.assertEqual(teacher['subjects'], ['数学', 'Science 7-10', 'Workshop 4-6'])
            listed = {item['name']: item['active'] for item in state['subjects']}
            self.assertEqual(listed['Science 7-10'], 1)
            self.assertEqual(listed['Workshop 4-6'], 1)
            self.assertTrue(all(item for item in created))
        finally:
            c.rollback()
            c.close()


if __name__ == '__main__':
    unittest.main()
