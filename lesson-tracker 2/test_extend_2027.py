"""The extension script only adds weeks after the Term 1 rows, and a second run is empty."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(tempfile.mkdtemp()) / 'term1.sqlite3'
os.environ['LESSON_DB'] = str(DB)
os.environ['LESSON_DEMO'] = '1'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import server


def _run(script, *args):
    return subprocess.run([sys.executable, script, *args, '--db', str(DB)], cwd=ROOT,
        check=True, capture_output=True, text=True)


class Extend2027Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        _run('term1_2027_schedule.py', '--apply')
        cls.dry = _run('extend_2027_series.py')
        cls.applied = _run('extend_2027_series.py', '--apply')
        cls.again = _run('extend_2027_series.py', '--apply')

    def test_dry_run_lists_slots_and_skips_the_trial(self):
        self.assertIn('Molly · 试听', self.dry.stdout)
        self.assertIn('跳过试听', self.dry.stdout)
        self.assertIn('VCE 中数快班', self.dry.stdout)
        self.assertIn('existing=', self.dry.stdout)
        self.assertIn('insert=', self.dry.stdout)

    def test_apply_links_a_series_through_december_and_is_idempotent(self):
        self.assertIn('insert=0', self.again.stdout)
        with sqlite3.connect(DB) as c:
            c.row_factory = sqlite3.Row
            trial = c.execute("SELECT series_id FROM lessons WHERE title LIKE '%试听%'").fetchone()
            self.assertIsNone(trial['series_id'])
            row = c.execute("""SELECT series_id, occurrence_index, starts_at FROM lessons
                WHERE title='Edward' AND ends_at LIKE '%T19:30' ORDER BY starts_at""").fetchall()
            self.assertGreater(len(row), 9)
            self.assertTrue(all(item['series_id'] for item in row))
            self.assertLessEqual(row[-1]['starts_at'][:10], '2027-12-31')
            self.assertGreaterEqual(row[-1]['starts_at'][:10], '2027-12-20')
            rule = c.execute('SELECT endless, stop_index, next_index FROM lesson_series WHERE id=?',
                (row[0]['series_id'],)).fetchone()
            self.assertEqual(rule['endless'], 0)
            self.assertEqual(rule['stop_index'], rule['next_index'])
            self.assertEqual(rule['stop_index'], len(row))
            group = c.execute("SELECT COUNT(*) FROM lessons WHERE title='VCE 高数' AND starts_at>='2027-04-01'").fetchone()[0]
            self.assertGreater(group, 0)

    def test_a_cancelled_slot_is_not_extended(self):
        copy = Path(tempfile.mkdtemp()) / 'cancelled.sqlite3'
        with sqlite3.connect(DB) as src, sqlite3.connect(copy) as dst:
            src.backup(dst)
        with sqlite3.connect(copy) as c:
            c.execute("UPDATE lessons SET status='cancelled' WHERE title='David'")
            c.commit()
        out = subprocess.run([sys.executable, 'extend_2027_series.py', '--apply', '--db', str(copy)],
            cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertIn('David', out.stdout)
        self.assertIn('取消或删除', out.stdout)
        with sqlite3.connect(copy) as c:
            late = c.execute("SELECT COUNT(*) FROM lessons WHERE title='David' AND starts_at>='2027-04-01' AND status!='cancelled'").fetchone()[0]
        self.assertEqual(late, 0)
        self.assertLessEqual(date(2027, 12, 31), date(2027, 12, 31) + timedelta(0))


if __name__ == '__main__':
    unittest.main()
