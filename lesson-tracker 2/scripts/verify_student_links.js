#!/usr/bin/env node
/* Given /api/state JSON, every student card links with the first enrolment id.
   That id must open the same group, even when it equals another student's profile_id. */
const fs = require('fs');
const path = require('path');

function fail(message, code) {
  console.error(message);
  process.exit(code || 1);
}

const file = process.argv[2];
if (!file) fail('usage: node scripts/verify_student_links.js <api-state.json>', 2);

const root = path.resolve(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'static', 'app.js'), 'utf8');
const start = src.indexOf('/* studentGroupById:start */');
const end = src.indexOf('/* studentGroupById:end */');
if (start < 0 || end < start) fail('studentGroupById markers missing from static/app.js', 2);

let payload;
try {
  payload = JSON.parse(fs.readFileSync(file, 'utf8'));
} catch (error) {
  fail('could not read state JSON: ' + error.message, 2);
}
if (!payload || !Array.isArray(payload.students)) fail('state JSON needs a students array', 2);

var state = {students: payload.students};
const lookup = eval(src.slice(start, end) + '\n;({studentGroups, studentGroupById});');

function signature(group) {
  return group.map(student => [student.id, student.profile_id, student.name].join(':')).join('|');
}

const groups = lookup.studentGroups();
const problems = [];
groups.forEach(group => {
  const first = group[0];
  const opened = lookup.studentGroupById(first.id);
  if (!opened || signature(opened) !== signature(group)) {
    const got = opened && opened[0] ? opened[0].name + ' #' + opened[0].id : 'nobody';
    problems.push(first.name + ' enrolment ' + first.id + ' opened ' + got);
  }
});
if (problems.length) fail(problems.join('\n'));
console.log('ok ' + groups.length + ' groups');
