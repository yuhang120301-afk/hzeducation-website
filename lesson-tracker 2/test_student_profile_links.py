"""Student list links use enrolment ids, and those ids open that same student."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build_colliding_state():
    """Enrolment order matches /api/state (ORDER BY students.id).

    Shirley profile 12 is listed before Declan enrolment 12.
    Amelia profile 13 is listed before Eva enrolment 13.
    Ten later enrolments also reuse an earlier student's profile id.
    """
    specs = []

    def person(name, courses, profile=None, role=''):
        specs.append({'name': name, 'courses': list(courses), 'profile': profile, 'role': role, 'ids': []})

    person('Shirley', ['数学', '英语'], 12)
    person('Amelia', ['数学', 'VCE 中数'], 13)
    for name in ('Noah', 'Olivia', 'Liam', 'Mia', 'Jack', 'Chloe', 'Lucas'):
        person(name, ['数学'], role='filler')
    person('Declan', ['数学'], 400)
    person('Eva', ['英语'], 410)
    person('Declan', ['英语'], 400)
    person('Eva', ['数学'], 410)
    hosts = ('Zoe', 'Henry', 'Grace', 'Leo', 'Isla', 'Oscar', 'Ruby', 'Finn', 'Nora', 'Hugo')
    laters = ('Priya', 'Caleb', 'Maya', 'Theo', 'Elise', 'Jonah', 'Freya', 'Arlo', 'Nina', 'Felix')
    for index, name in enumerate(hosts):
        person(name, ['数学', '英语'] if index % 2 == 0 else ['数学'], role='host')
    for index, name in enumerate(laters):
        courses = ['英语'] if index % 3 == 0 else ['数学', 'VCE 低数']
        person(name, courses, role='later')
    person('Harper', ['数学'], 900)

    students = []
    for spec in specs:
        for course in spec['courses']:
            sid = len(students) + 1
            spec['ids'].append(sid)
            students.append({
                'id': sid,
                'profile_id': spec['profile'],
                'name': spec['name'],
                'course': course,
                'subject_name': course,
                'grade': 'Y8',
                'level_calendar': 'Y8',
                'phone': '',
                'study_status': 'studying',
                'no_course': False,
                'archived': 0,
                'balance': 800,
            })

    fillers = [spec for spec in specs if spec['role'] == 'filler']
    hosts = [spec for spec in specs if spec['role'] == 'host']
    laters = [spec for spec in specs if spec['role'] == 'later']
    by_id = {row['id']: row for row in students}
    for index, spec in enumerate(fillers):
        for sid in spec['ids']:
            by_id[sid]['profile_id'] = 300 + index
    for index, (host, later) in enumerate(zip(hosts, laters)):
        for sid in host['ids']:
            by_id[sid]['profile_id'] = later['ids'][0]
        for sid in later['ids']:
            by_id[sid]['profile_id'] = 800 + index

    declan = by_id[12]
    eva = by_id[13]
    if declan['name'] != 'Declan' or declan['profile_id'] != 400:
        raise AssertionError('Declan must be enrolment 12, got %s' % declan)
    if eva['name'] != 'Eva' or eva['profile_id'] != 410:
        raise AssertionError('Eva must be enrolment 13, got %s' % eva)
    if by_id[1]['name'] != 'Shirley' or by_id[1]['profile_id'] != 12:
        raise AssertionError('Shirley must be the earlier profile 12')
    if by_id[3]['name'] != 'Amelia' or by_id[3]['profile_id'] != 13:
        raise AssertionError('Amelia must be the earlier profile 13')
    collisions = [
        (earlier['name'], later['name'], later['id'])
        for earlier in students for later in students
        if earlier['name'] != later['name'] and earlier['profile_id'] == later['id'] and earlier['id'] < later['id']
    ]
    if len(collisions) < 12:
        raise AssertionError('need enrolment ids that reuse earlier profile ids, found %s' % collisions)

    archived = [
        {'id': 500, 'profile_id': 12, 'name': 'Shirley', 'course': 'VCE 高数'},
        {'id': 501, 'profile_id': 400, 'name': 'Declan', 'course': 'VCE 高数'},
    ]
    lessons = [
        {'id': 1, 'starts_at': '2026-11-20T10:00', 'status': 'completed', 'students': [{'id': 1, 'name': 'Shirley'}]},
        {'id': 2, 'starts_at': '2026-11-21T10:00', 'status': 'completed', 'students': [{'id': 12, 'name': 'Declan'}]},
        {'id': 3, 'starts_at': '2026-11-22T10:00', 'status': 'completed', 'students': [{'id': 40, 'name': by_id[40]['name']}]},
    ]
    return {'students': students, 'archived_students': archived, 'lessons': lessons}


class StudentProfileLinkTests(unittest.TestCase):
    def test_each_enrolment_link_opens_that_student(self):
        state = build_colliding_state()
        keys = []
        for student in state['students']:
            key = student['profile_id'] or student['id']
            if key not in keys:
                keys.append(key)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text(json.dumps(state), encoding='utf-8')
            checked = subprocess.run(
                ['node', str(ROOT / 'scripts' / 'verify_student_links.js'), str(path)],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr or checked.stdout)
            self.assertEqual(checked.stdout.strip(), 'ok %s groups' % len(keys))
            opened = subprocess.run(
                ['node', '-e', OPEN_CHECK, str(path)],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(opened.returncode, 0, opened.stderr or opened.stdout)


OPEN_CHECK = r'''
const fs = require('fs');
const src = fs.readFileSync('static/app.js', 'utf8');
const start = src.indexOf('/* studentGroupById:start */');
const end = src.indexOf('/* studentGroupById:end */');
if (start < 0 || end < start) process.exit(2);
const payload = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
var state = {
  students: payload.students,
  archived_students: payload.archived_students || [],
  lessons: payload.lessons || []
};
const lookup = eval(src.slice(start, end) + '\n;({studentGroups, studentGroupById});');
var studentGroups = lookup.studentGroups;
var studentGroupById = lookup.studentGroupById;
const lessonStart = src.indexOf('function profileLessonIds');
const lessonEnd = src.indexOf('function studentFold');
var profileLessonIds = eval(src.slice(lessonStart, lessonEnd) + '\n;profileLessonIds;');

function die(message, code) {
  console.error(message);
  process.exit(code || 1);
}
function legacyGroup(id) {
  return studentGroups().find(item => item.some(student => String(student.id) === String(id) || String(student.profile_id) === String(id))) || null;
}
function idsOf(group) {
  return (group || []).map(student => student.id).join(',');
}

if (!legacyGroup(12) || legacyGroup(12)[0].name !== 'Shirley') die('fixture no longer collides on 12: ' + (legacyGroup(12) && legacyGroup(12)[0].name));
if (!legacyGroup(13) || legacyGroup(13)[0].name !== 'Amelia') die('fixture no longer collides on 13: ' + (legacyGroup(13) && legacyGroup(13)[0].name));
if (!studentGroupById(12) || studentGroupById(12)[0].name !== 'Declan') die('enrolment 12 opened ' + (studentGroupById(12) && studentGroupById(12)[0].name));
if (!studentGroupById('12') || studentGroupById('12')[0].name !== 'Declan') die('string enrolment 12 opened the wrong student');
if (!studentGroupById(13) || studentGroupById(13)[0].name !== 'Eva') die('enrolment 13 opened ' + (studentGroupById(13) && studentGroupById(13)[0].name));
if (!studentGroupById('13') || studentGroupById('13')[0].name !== 'Eva') die('string enrolment 13 opened the wrong student');

const groups = studentGroups();
groups.forEach(group => {
  const linkId = group[0].id;
  const opened = studentGroupById(linkId);
  if (idsOf(opened) !== idsOf(group)) die(group[0].name + ' list link /students/' + linkId + ' opened ' + (opened && opened[0] && opened[0].name));
  group.forEach(student => {
    const again = studentGroupById(student.id);
    if (!again || !again.some(item => item.id === student.id) || again[0].name !== student.name) {
      die(student.name + ' enrolment ' + student.id + ' opened ' + (again && again[0] && again[0].name));
    }
  });
});

const declanIds = profileLessonIds(12);
['12', '14', '501'].forEach(id => { if (!declanIds.has(id)) die('Declan lessons missing ' + id); });
['1', '2', '500'].forEach(id => { if (declanIds.has(id)) die('Declan lessons include Shirley ' + id); });
const shirleyIds = profileLessonIds(1);
['1', '2', '500'].forEach(id => { if (!shirleyIds.has(id)) die('Shirley lessons missing ' + id); });
if (shirleyIds.has('12') || shirleyIds.has('501')) die('Shirley lessons include Declan');
const shown = new Set();
state.lessons.forEach(lesson => (lesson.students || []).forEach(student => {
  if (declanIds.has(String(student.id))) shown.add(student.name);
}));
if (shown.has('Shirley') || !shown.has('Declan')) die('Declan profile lessons are ' + [...shown].join(','));

const harper = state.students.find(student => student.name === 'Harper');
if (!studentGroupById(900) || studentGroupById(900)[0].name !== 'Harper') die('profile id 900 did not fall back to Harper');
if (!studentGroupById(harper.id) || studentGroupById(harper.id)[0].name !== 'Harper') die('Harper enrolment opened the wrong student');
if (studentGroupById(99999) !== null) die('unknown id should miss');
const missing = profileLessonIds(99999);
if (missing.size !== 1 || !missing.has('99999')) die('unknown id lesson set changed');

if (src.includes('||String(student.profile_id)===String(')) die('app.js still matches enrolment id or profile_id together', 3);
const profileFn = src.slice(src.indexOf('function profileLessonIds'), src.indexOf('function studentFold'));
const renderFn = src.slice(src.indexOf('function renderStudentProfile'), src.indexOf('function reportHasRecord'));
if (!profileFn.includes('studentGroupById(id)')) die('profileLessonIds does not use studentGroupById', 3);
if (!renderFn.includes('studentGroupById(profileId)')) die('renderStudentProfile does not use studentGroupById', 3);
if (!src.includes('data-open-student="${person.id}"')) die('student list link is not the enrolment id', 3);
if (!src.includes("'/students/'+card.dataset.openStudent")) die('student list no longer opens /students/<enrolment id>', 3);
if (!src.includes("'/students/'+profileId+'/lessons/'")) die('lesson record url changed', 3);
const parentCards = src.slice(src.indexOf('function parentCards'), src.indexOf('function studentGroups'));
if (parentCards.includes('/students/')) die('parent cards link to /students/', 3);
const pay = fs.readFileSync('static/pay.js', 'utf8');
if (!pay.includes('studentGroupById(routeId)')) die('renderProfile does not use studentGroupById', 3);
if (!pay.includes('const sid=student.id')) die('renderProfile lesson url is not the enrolment id', 3);
if (!pay.includes("'/students/'+sid+'/lessons/'")) die('renderProfile lesson url changed', 3);
const calendar = fs.readFileSync('static/calendar.js', 'utf8');
if (!calendar.includes('studentGroups().map(group=>group[0])')) die('calendar search no longer uses the first enrolment', 3);
if (!calendar.includes('data-open-student="${student.id}"')) die('calendar search link is not the enrolment id', 3);
if (!calendar.includes("'/students/'+button.dataset.openStudent")) die('calendar search no longer opens /students/<enrolment id>', 3);
const teaching = fs.readFileSync('static/teaching.js', 'utf8');
if (!teaching.includes("'/students/'+card.dataset.openStudent")) die('child card handler no longer uses the enrolment id on the card', 3);
fs.readdirSync('static').filter(name => name.endsWith('.js')).forEach(name => {
  const text = fs.readFileSync('static/' + name, 'utf8');
  if (text.includes('||String(student.profile_id)===String(')) die(name + ' still matches enrolment id or profile_id together', 3);
});
'''


if __name__ == '__main__':
    unittest.main()
