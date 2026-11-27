"""A saved draft is yellow, not the grey used for a deducted lesson."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class DraftColourTests(unittest.TestCase):
    def test_draft_is_not_painted_as_completed(self):
        script = r'''
const fs = require('fs');
const src = fs.readFileSync('static/calendar.js', 'utf8');
const start = src.indexOf('/* lessonPaint:start */');
const end = src.indexOf('/* lessonPaint:end */');
if (start < 0 || end < 0) process.exit(2);
eval(src.slice(start, end));
const draft = {status:'scheduled', reports:[{content:'分数运算', homework:'', feedback:'', ledger_id:null}]};
const empty = {status:'scheduled', reports:[{content:'', homework:'', feedback:''}]};
const plain = {status:'scheduled', reports:[]};
const done = {status:'completed', reports:[{content:'分数运算', homework:'作业', feedback:'很好', ledger_id:9}]};
const closed = {status:'completed', reports:[{content:'', homework:'', feedback:'', ledger_id:4}]};
const recordedOnly = {status:'scheduled', recorded:true, reports:[{content:'草稿内容', homework:'', feedback:''}]};
if (lessonDone(draft) || !lessonDraft(draft)) process.exit(3);
if (lessonDone(empty) || lessonDraft(empty) || lessonDone(plain) || lessonDraft(plain)) process.exit(4);
if (!lessonDone(done) || lessonDraft(done) || !lessonDone(closed) || lessonDraft(closed)) process.exit(5);
if (lessonDone(recordedOnly) || !lessonDraft(recordedOnly)) process.exit(6);
const absent = {status:'scheduled', absent:1, reports:[{content:'请假前的草稿', homework:'', feedback:''}]};
if (lessonDone(absent) || lessonDraft(absent)) process.exit(7);
const teach = fs.readFileSync('static/teaching.js', 'utf8');
const css = fs.readFileSync('static/style.css', 'utf8');
if (!src.includes("draft?' draft'") || !src.includes('draft-tag">草稿')) process.exit(8);
if (!teach.includes("draft?' draft'") || !teach.includes('draft-tag">草稿') || !teach.includes("?'草稿'")) process.exit(9);
if (!css.includes('.gcal-event.draft') || !css.includes('#FFF6D8') || !css.includes('.lesson-card.draft')) process.exit(10);
if (!src.includes('month-chip') || !teach.includes('lesson-card')) process.exit(11);
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
