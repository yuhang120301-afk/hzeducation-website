"""Course types and the daily pay period stay additive."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'catalog.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import payroll
import server
import teaching


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def test_old_labels_split_into_subject_and_type(self):
        subject, kind, original = teaching.parse_label('数学 · 1:1', 1)
        self.assertEqual((subject, kind, original), ('数学', '一对一', '数学 · 1:1'))
        self.assertEqual(teaching.parse_label('英语 · 班课', 4)[1], '小班课')
        self.assertEqual(teaching.infer_type_name(1), '一对一')
        self.assertEqual(teaching.infer_type_name(2), '一对二')
        self.assertEqual(teaching.infer_type_name(5), '小班课')

    def test_boss_can_add_a_course_type(self):
        with server.connect() as c:
            names = [row['name'] for row in c.execute('SELECT name FROM course_types ORDER BY sort_order, id')]
            self.assertEqual(names[:3], ['一对一', '一对二', '小班课'])
            teaching.save_catalog_item(c, {'id': 1, 'role': 'owner'}, 'course_types', {'name': '集训营'}, server.text_value)
            self.assertIsNotNone(c.execute("SELECT 1 FROM course_types WHERE name='集训营'").fetchone())

    def test_daily_pay_period_is_one_day(self):
        start, end = payroll.period_bounds('day', '2026-11-24', None, None)
        self.assertEqual(start.isoformat(), '2026-11-24')
        self.assertEqual(end.isoformat(), '2026-11-24')


if __name__ == '__main__':
    unittest.main()
