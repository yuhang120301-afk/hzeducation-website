"""Upcoming lessons on a student profile come before past ones."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class UpcomingLessonTests(unittest.TestCase):
    def test_next_five_are_soonest_and_past_is_newest_first(self):
        script = r'''
const fs = require('fs');
const src = fs.readFileSync('static/app.js', 'utf8');
const start = src.indexOf('function splitLessonLists');
const end = src.indexOf('/* splitLessonLists:end */');
if (start < 0 || end < 0) process.exit(2);
eval(src.slice(start, end));
const today = '2026-11-24';
const lessons = [
  {id:1, starts_at:'2026-11-20T10:00', status:'scheduled'},
  {id:2, starts_at:'2026-11-24T18:00', status:'scheduled'},
  {id:3, starts_at:'2026-11-25T09:00', status:'cancelled'},
  {id:4, starts_at:'2026-12-01T09:00', status:'scheduled'},
  {id:5, starts_at:'2026-11-24T08:00', status:'completed'},
  {id:6, starts_at:'2026-12-02T09:00', status:'scheduled'},
  {id:7, starts_at:'2026-12-03T09:00', status:'scheduled'},
  {id:8, starts_at:'2026-12-04T09:00', status:'scheduled'},
  {id:9, starts_at:'2026-12-05T09:00', status:'scheduled'},
  {id:10, starts_at:'2026-12-06T09:00', status:'scheduled'},
  {id:11, starts_at:'2026-11-01T09:00', status:'completed'},
];
const parts = splitLessonLists(lessons, today);
const upcoming = parts.upcoming.map(item => item.id).join(',');
const past = parts.past.map(item => item.id).join(',');
if (upcoming !== '5,2,4,6,7,8,9,10') {
  console.error('upcoming', upcoming);
  process.exit(1);
}
if (past !== '3,1,11') {
  console.error('past', past);
  process.exit(1);
}
const html = src.slice(src.indexOf('function lessonTimeline'), src.indexOf('function bindProfileSections'));
if (!html.includes('接下来的课') || !html.includes('已上过的课')) process.exit(3);
const pay = fs.readFileSync('static/pay.js', 'utf8');
if (!pay.includes('lessonTimeline(lessons, lessonRow)')) process.exit(4);
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
