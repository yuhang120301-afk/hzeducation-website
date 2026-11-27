"""Booking forms label teachers from the ticked subject list and offer a match first."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TeacherPickerTests(unittest.TestCase):
    def test_course_puts_matching_teachers_first_without_hiding_the_rest(self):
        script = r'''
const fs = require('fs');
const src = fs.readFileSync('static/teaching.js', 'utf8');
const start = src.indexOf('/* teacherPicker:start */');
const end = src.indexOf('/* teacherPicker:end */');
if (start < 0 || end < 0) process.exit(2);
const state = {teachers: [
  {id: 1, name: 'Vincent', active: 1, subjects: ['数学', '新加坡数学', 'Science 7-10', '科学'], subject: '新加坡数学'},
  {id: 2, name: 'Ethan', active: 1, subjects: ['数学', '科学'], subject: '数学、科学'},
  {id: 3, name: 'Helen', active: 1, subjects: ['英语'], subject: '英语'},
]};
const escapeHTML = value => String(value ?? '');
eval(src.slice(start, end));
if (teacherSubjectLabel(state.teachers[0]) !== '数学、新加坡数学、Science 7-10、科学') process.exit(3);
const one = teacherOptionRows('Science 7-10', '');
if (!one.includes('Vincent · 数学、新加坡数学、Science 7-10、科学')) process.exit(4);
if (!one.includes('value="1" selected')) process.exit(5);
if (!one.includes('label="其他老师"') || !one.includes('Ethan · 数学、科学') || !one.includes('Helen · 英语')) process.exit(6);
if (one.indexOf('Vincent') > one.indexOf('其他老师')) process.exit(7);
const maths = teacherOptionRows('数学', '');
if (!maths.includes('label="教这科"') || !maths.includes('Vincent') || !maths.includes('Ethan')) process.exit(8);
if (maths.includes('selected')) process.exit(9);
const helen = maths.slice(maths.indexOf('其他老师'));
if (!helen.includes('Helen · 英语')) process.exit(10);
const schedule = fs.readFileSync('static/teaching.js', 'utf8');
const app = fs.readFileSync('static/app.js', 'utf8');
if (!schedule.includes('bindTeacherPicker(l?.teacher_id') || !app.includes("bindTeacherPicker('', false, true)")) process.exit(11);
if (schedule.includes('escapeHTML(t.subject)') || app.includes('teacherTeaches(teacher,\'新加坡数学\')')) process.exit(12);
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
