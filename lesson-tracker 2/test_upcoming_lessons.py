"""Student lesson lists: upcoming first, attended history without cancellations."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class UpcomingLessonTests(unittest.TestCase):
    def test_attended_history_skips_cancelled_and_opens_the_record(self):
        script = r'''
const fs = require('fs');
const src = fs.readFileSync('static/app.js', 'utf8');
const start = src.indexOf('/* splitLessonLists:start */');
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
  {id:12, starts_at:'2026-10-02T09:00', status:'voided'},
  {id:13, starts_at:'2026-10-03T09:00', status:'undone'},
  {id:14, starts_at:'2026-10-04T09:00', status:'已取消'},
  {id:15, starts_at:'2026-12-08T09:00', status:'canceled'},
  {id:16, starts_at:'2026-09-01T09:00', status:'Cancelled'},
  {id:17, starts_at:'2026-12-09T09:00', status:'completed'},
  {id:18, starts_at:'2026-12-10T09:00', status:'scheduled', recorded:true},
];
const parts = splitLessonLists(lessons, today);
const upcoming = parts.upcoming.map(item => item.id).join(',');
const past = parts.past.map(item => item.id).join(',');
if (upcoming !== '2,4,6,7,8,9,10') {
  console.error('upcoming', upcoming);
  process.exit(1);
}
if (past !== '18,17,5,1,11') {
  console.error('past', past);
  process.exit(1);
}
const hidden = new Set([3,12,13,14,15,16]);
const shown = parts.upcoming.concat(parts.past);
if (shown.some(item => hidden.has(item.id) || lessonIsCancelled(item))) {
  console.error('cancelled leaked', shown.map(item => item.id).join(','));
  process.exit(1);
}
if (parts.past.length !== 5) process.exit(1);
const timeline = src.slice(src.indexOf('function lessonTimeline'), src.indexOf('function bindProfileSections'));
if (!timeline.includes('即将要上的课') || !timeline.includes('已上过的课')) process.exit(3);
if (timeline.includes('接下来的课') || timeline.includes('已取消的课')) process.exit(5);
if (!timeline.includes('已上过的课 (${parts.past.length})')) process.exit(6);
const fold = src.slice(src.indexOf('function studentFold'), src.indexOf('function renderStudents'));
if (!fold.includes('data-open-lesson') || !fold.includes('lessonTimeline(lessons, lessonRow, attendedRow)')) process.exit(7);
const page = src.slice(src.indexOf('function renderLessonRecord'), src.indexOf('function bindProfileActions'));
if (!page.includes('还没有课后记录') || !page.includes('backBar') || !page.includes('填写课后记录')) process.exit(8);
if (!src.includes("'/students/'+profileId+'/lessons/'")) process.exit(9);
const pay = fs.readFileSync('static/pay.js', 'utf8');
if (!pay.includes('lessonTimeline(lessons, lessonRow')) process.exit(4);
if (!pay.includes('lessonIsCancelled')) process.exit(10);
const teaching = fs.readFileSync('static/teaching.js', 'utf8');
if (!teaching.includes("view==='lesson-record'")) process.exit(11);
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
