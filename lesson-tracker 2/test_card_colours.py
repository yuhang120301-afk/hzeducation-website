"""A person's card is split across the teachers of their current courses."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CHECK = r'''
const fs = require('fs');
const src = fs.readFileSync('static/app.js', 'utf8');
const start = src.indexOf('function studentToneName');
const end = src.indexOf('/* cardPaint:end */');
if (start < 0 || end < start) process.exit(2);
var state = {lessons: []};
const api = eval(src.slice(start, end) + '\n;({courseTeachers, cardPaint});');
function die(message){ console.error(message); process.exit(1); }

const zachary = [
  {id: 74, course: '数学', archived: 0, voided: 0, no_course: false},
  {id: 75, course: '英语', archived: 0, voided: 0, no_course: false}
];
state.lessons = [
  {id: 1, status: 'scheduled', starts_at: '2026-11-01T10:00', teacher_name: 'Helen', students: [{id: 74}]},
  {id: 2, status: 'scheduled', starts_at: '2026-11-02T10:00', teacher_name: 'Vincent', students: [{id: 75}]},
  {id: 3, status: 'cancelled', starts_at: '2026-11-03T10:00', teacher_name: 'Angela', students: [{id: 75}]}
];
const names = api.courseTeachers(zachary);
if (names.join('|') !== 'Helen|Vincent') die('teachers ' + names.join('|'));
const split = api.cardPaint(names);
if (split.className !== 'is-split') die('class ' + split.className);
if (!split.style.includes('linear-gradient(to right, #E4F0E9 0% 50%, #93C5FD 50% 100%)')) die('gradient ' + split.style);
if (!split.style.includes('#1F2A27') && split.style.includes('#E4F0E9') && split.style.includes('#93C5FD')) {
  /* fills are the light teacher colours, so dark text stays readable */
}
const one = api.cardPaint(['Helen']);
if (one.className !== 't-helen' || one.style) die('single teacher ' + JSON.stringify(one));
const thirds = api.cardPaint(['Helen', 'Vincent', 'Angela']);
if (!thirds.style.includes('#E4F0E9 0% 33.33333333333333%') && !thirds.style.includes('33.333')) die('thirds ' + thirds.style);
if (!thirds.style.includes('#F5EAE8')) die('third colour missing ' + thirds.style);
const none = api.cardPaint(api.courseTeachers([{id: 9, no_course: true, archived: 0, voided: 0}]));
if (none.className || none.style) die('empty course should be neutral ' + JSON.stringify(none));
const stopped = api.courseTeachers([{id: 74, archived: 1, voided: 0, no_course: false}]);
if (stopped.length) die('stopped course should not colour the card');
console.log('ok');
'''


SCHEDULE = r'''
const fs = require('fs');
const src = fs.readFileSync('static/teaching.js', 'utf8');
if (src.includes('lessonColorPicker')) { console.error('picker still offered'); process.exit(1); }
if (!src.includes('lessonColorLive()')) { console.error('live swatch missing'); process.exit(1); }
if (!src.includes('name="color"')) { console.error('saved colour missing'); process.exit(1); }
if (!src.includes("addEventListener('change', syncTeacherColor)")) { console.error('teacher change does not recolour'); process.exit(1); }
const start = src.indexOf('function teacherToneName');
const end = src.indexOf('function lessonCard');
if (start < 0 || end < start) process.exit(2);
const api = eval(src.slice(start, end) + '\n;({teacherToneName, teacherLessonColor});');
const pairs = [['Helen','helen','green'],['Vincent','vincent','blue'],['Angela','angela','pink'],['Kelsey','kelsey','purple'],['Ethan','ethan','gray'],['Christina','christina','yellow'],['New Teacher','other','gray']];
for (const [name, tone, color] of pairs) {
  if (api.teacherToneName(name) !== tone) { console.error(name); process.exit(1); }
  if (api.teacherLessonColor[tone] !== color) { console.error(color); process.exit(1); }
}
const cardStart = src.indexOf('function lessonCard');
const cardEnd = src.indexOf('function lessonColorLive');
const card = src.slice(cardStart, cardEnd);
if (!card.includes("tone-'+tone")) { console.error('week card ignores the teacher'); process.exit(1); }
console.log('ok');
'''


class CardColourTests(unittest.TestCase):
    def test_two_teachers_split_the_card(self):
        checked = subprocess.run(['node', '-e', CHECK], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr or checked.stdout)
        self.assertIn('ok', checked.stdout)

    def test_new_lesson_takes_the_teacher_colour(self):
        checked = subprocess.run(['node', '-e', SCHEDULE], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr or checked.stdout)
        self.assertIn('ok', checked.stdout)


if __name__ == '__main__':
    unittest.main()
