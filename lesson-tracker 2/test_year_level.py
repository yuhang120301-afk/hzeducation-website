"""2027 enrolment year is shown and priced as the calendar year of the date."""
import datetime as dt
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'years.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import pricing
import server


class YearLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()
        with server.connect() as c:
            uid = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0412000001','Helen','x','admin')").lastrowid
            c.execute('INSERT INTO organization_owners(user_id) VALUES(?)', (uid,))
            pricing.seed_2027(c)
            pricing.publish_seed(c)
            cls.owner = {'id': uid, 'role': 'owner'}
            cls.parent = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0412000002','家长','x','parent')").lastrowid
            cls.kind = c.execute("SELECT id FROM course_types WHERE name='一对一'").fetchone()['id']

    def enrol(self, c, code, study=''):
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,level_code,level_year,course_type_id,study_level,billing_unit)
            VALUES(?,?,?,?,0,?,2026,?,?,'lesson')''',
            ('学生'+code+study, '数学', self.parent, profile, code, self.kind, study)).lastrowid
        return sid

    def hourly(self, sid, day):
        with server.connect() as c:
            offer = pricing.presets(c, self.owner, student_id=sid, day=day)
        return offer['level'], offer['hourly_cents'], offer['source']

    def test_display_moves_on_1_january_without_rewriting_the_stored_year(self):
        student = {'level_code': 'Y5', 'level_year': 2026, 'grade': 'Y5', 'study_level': ''}
        shown = pricing.annotate(dict(student), dt.date(2026, 12, 31))
        self.assertEqual(shown['level_label'], 'Year 4')
        self.assertEqual(shown['level_stored'], 'Y5')
        self.assertFalse(shown['level_past'])
        later = pricing.annotate(dict(student), dt.date(2027, 1, 1))
        self.assertEqual(later['level_label'], 'Year 5')
        further = pricing.annotate(dict(student), dt.date(2028, 1, 1))
        self.assertEqual(further['level_label'], 'Year 6')
        self.assertEqual(student['level_code'], 'Y5')
        self.assertEqual(student['level_year'], 2026)

    def test_prep_and_year_12_edges(self):
        prep = pricing.annotate({'level_code': 'Prep', 'grade': 'Prep'}, dt.date(2026, 6, 1))
        self.assertEqual(prep['level_code'], 'Prep')
        self.assertEqual(prep['level_calendar'], 'Prep')
        self.assertEqual(prep['level_price'], 'Prep')
        self.assertEqual(prep['level_label'], 'Prep')
        same_year = pricing.annotate({'level_code': 'Prep', 'grade': 'Prep'}, dt.date(2027, 6, 1))
        self.assertEqual(same_year['level_label'], 'Prep')
        first = pricing.annotate({'level_code': 'Y1', 'grade': 'Y1'}, dt.date(2026, 6, 1))
        self.assertEqual(first['level_label'], 'Prep')
        self.assertEqual(pricing.move_level('Prep', -1), ('Prep', False))
        self.assertEqual(pricing.move_level('Y12', 1), ('Y12', True))
        top = pricing.annotate({'level_code': 'Y12', 'grade': 'Y12'}, dt.date(2028, 1, 1))
        self.assertEqual(top['level_price'], 'Y12')
        self.assertTrue(top['level_past'])
        self.assertIn('已毕业?', top['level_label'])

    def test_old_kindergarten_text_still_parses_and_displays_as_prep(self):
        for text in ('K', 'k', 'kindergarten', 'Kindy', '学前', '幼儿园'):
            self.assertEqual(pricing.parse_level(text), 'K')
        legacy = pricing.annotate({'level_code': '', 'grade': '幼儿园'}, dt.date(2026, 11, 25))
        self.assertEqual(legacy['grade'], '幼儿园')
        self.assertEqual(legacy['level_stored'], 'K')
        self.assertEqual(legacy['level_calendar'], 'Prep')
        self.assertEqual(legacy['level_label'], 'Prep')
        stored = pricing.annotate({'level_code': 'K', 'grade': 'K'}, dt.date(2027, 3, 1))
        self.assertEqual(stored['level_code'], 'K')
        self.assertEqual(stored['level_label'], 'Prep')
        advanced = pricing.annotate({'level_code': 'K', 'grade': 'K'}, dt.date(2029, 1, 1))
        self.assertEqual(advanced['level_code'], 'K')
        self.assertEqual(advanced['level_calendar'], 'Y1')
        self.assertEqual(pricing.remember_level({}, '幼儿园'), ('K', 2027))
        self.assertEqual(pricing.remember_level({}, 'Y5', dt.date(2026, 6, 1)), ('Y6', 2027))
        self.assertEqual(pricing.remember_level({}, 'Y5', dt.date(2027, 6, 1)), ('Y5', 2027))
        self.assertEqual(pricing.remember_level({}, 'Prep', dt.date(2028, 1, 1)), ('Prep', 2027))
        self.assertEqual(pricing.clean_study_level('kindy'), 'K')
        self.assertEqual(pricing.level_label('K', past=True), 'Prep · 已毕业?')

    def test_kindergarten_row_is_not_rewritten_and_prices_as_prep(self):
        with server.connect() as c:
            kindy = self.enrol(c, 'K')
            prep = self.enrol(c, 'Prep')
            before = {
                sid: tuple(c.execute('SELECT level_code, grade, level_year, study_level FROM students WHERE id=?', (sid,)).fetchone())
                for sid in (kindy, prep)
            }
        self.assertEqual(before[kindy][0], 'K')
        self.assertEqual(before[prep][0], 'Prep')
        self.assertEqual(self.hourly(kindy, '2026-06-01'), ('Prep', 8500, 'table'))
        self.assertEqual(self.hourly(prep, '2026-06-01'), ('Prep', 8500, 'table'))
        self.assertEqual(self.hourly(prep, '2027-02-01'), ('Prep', 8500, 'table'))
        with server.connect() as c:
            after = {
                sid: tuple(c.execute('SELECT level_code, grade, level_year, study_level FROM students WHERE id=?', (sid,)).fetchone())
                for sid in (kindy, prep)
            }
            listed = pricing.list_prices(c, self.owner)
        self.assertEqual(after, before)
        self.assertEqual(listed['levels'][0], 'Prep')
        self.assertNotIn('K', listed['levels'])
        bands = [row for table in listed['tables'] for row in table['rows']]
        self.assertTrue(any(row['product'] == 'term' and row['level_from'] == 'Prep' and row['level_to'] == 'Y6' for row in bands))
        self.assertFalse(any(row['level_from'] == 'K' for row in bands))

    def test_screens_do_not_offer_kindergarten(self):
        root = Path(__file__).resolve().parent
        app = root / 'static' / 'app.js'
        pay = (root / 'static' / 'pay.js').read_text(encoding='utf-8')
        calendar = (root / 'static' / 'calendar.js').read_text(encoding='utf-8')
        self.assertIn('displayLevel(row.level_from)', pay)
        self.assertIn('displayLevel(student.grade)', calendar)
        self.assertIn('displayLevel(item.grade', calendar)
        checked = subprocess.run(['node', '-e', SCREEN_CHECK, str(app)], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr or checked.stdout)
        self.assertEqual(checked.stdout.strip(), 'ok')

    def test_renewal_year_and_study_level_override(self):
        with server.connect() as c:
            plain = self.enrol(c, 'Y7')
            higher = self.enrol(c, 'Y7', 'Y9')
            lower = self.enrol(c, 'Y7', 'Y5')
            legacy = self.enrol(c, 'Y7')
            pricing.save_legacy_price(c, self.owner, {'student_id': legacy, 'hourly': '80'})
        self.assertEqual(self.hourly(plain, '2026-11-24'), ('Y6', 8500, 'table'))
        self.assertEqual(self.hourly(plain, '2027-02-01'), ('Y7', 9000, 'table'))
        self.assertEqual(self.hourly(higher, '2026-11-24'), ('Y9', 10000, 'table'))
        self.assertEqual(self.hourly(lower, '2026-11-24'), ('Y6', 8500, 'table'))
        self.assertEqual(self.hourly(lower, '2027-02-01'), ('Y7', 9000, 'table'))
        level, cents, source = self.hourly(legacy, '2027-02-01')
        self.assertEqual((level, cents, source), ('Y7', 8000, 'custom'))


SCREEN_CHECK = r'''
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function grab(name) {
  const token = 'function ' + name + '(';
  const start = src.indexOf(token);
  if (start < 0) throw new Error('missing ' + name);
  let i = start + token.length;
  let paren = 1;
  for (; i < src.length; i++) {
    if (src[i] === '(') paren++;
    else if (src[i] === ')') {
      paren--;
      if (paren === 0) { i++; break; }
    }
  }
  while (src[i] === ' ' || src[i] === '\n') i++;
  if (src[i] !== '{') throw new Error('no body ' + name);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') {
      depth--;
      if (depth === 0) return src.slice(start, j + 1);
    }
  }
  throw new Error('unclosed ' + name);
}
const helpersStart = src.indexOf('const KINDERGARTEN_LEVELS');
const helpersEnd = src.indexOf('function shownLevel');
if (helpersStart < 0 || helpersEnd < helpersStart) throw new Error('year helpers missing');
const order = src.match(/const YEAR_LEVEL_ORDER=\[[^\]]+\];/);
if (!order || order[0].includes("'K'")) throw new Error('year groups still offer K');
const code = [
  'let pendingListFocus = null;',
  'let state = {today:"2026-11-25", user:{role:"owner"}};',
  'function escapeHTML(v){return String(v ?? "");}',
  'function ageText(){return "";}',
  'function studentListCard(group){return String(group[0].id);}',
  src.slice(helpersStart, helpersEnd),
  order[0],
  grab('yearLevels'),
  grab('currentYearLabel'),
  grab('currentYearRank'),
  grab('studyLevelSelect'),
  grab('profileFields'),
  grab('yearLevelFolds'),
  'if (yearLevels().includes("K") || yearLevels()[0] !== "Prep") throw new Error("year list " + yearLevels().join(","));',
  'const kinder = currentYearLabel({level_calendar:"K", level_past:false});',
  'const prep = currentYearLabel({level_calendar:"Prep", level_past:false});',
  'if (kinder !== "Prep" || prep !== "Prep") throw new Error("labels " + kinder + " / " + prep);',
  'if (currentYearRank({level_calendar:"K"}) !== currentYearRank({level_calendar:"Prep"})) throw new Error("K is not grouped with Prep");',
  'if (currentYearLabel({level_calendar:"Y1", level_past:false}) !== "Year 1") throw new Error("Year 1 moved");',
  'const folds = yearLevelFolds([[{id:1, level_calendar:"K"}], [{id:2, level_calendar:"Prep"}]], false);',
  'const labels = folds.match(/year-fold-label">([^<]*)</g) || [];',
  "if (labels.length !== 1 || labels[0] !== 'year-fold-label\">Prep<') throw new Error('groups ' + labels.join(' | '));",
  'const dropped = profileFields({level_code:"K", grade:"幼儿园"});',
  'if (dropped.includes("value=\\"K\\"") || dropped.includes("value=\\"幼儿园\\"") || dropped.includes(">K</option>")) throw new Error("2027 dropdown still offers kindergarten");',
  'if (!dropped.includes("value=\\"Prep\\"")) throw new Error("Prep missing from 2027 dropdown");',
  'const kept = profileFields({level_code:"Year 6"});',
  'if (!kept.includes("value=\\"Year 6\\"")) throw new Error("old free-text grade was dropped");',
  'const study = studyLevelSelect("K") + studyLevelSelect("幼儿园") + studyLevelSelect("Prep");',
  'if (study.includes("value=\\"K\\"") || study.includes("幼儿园")) throw new Error("study level still offers kindergarten");',
  'if (!study.includes("value=\\"Prep\\"")) throw new Error("study level missing Prep");',
  'const priced = studyLevelSelect("K").includes("selected") ? "selected-k" : "clear";',
  'if (priced !== "clear") throw new Error("stored K is still selected as a study level");',
  'if (displayLevel("K · 已毕业?") !== "Prep · 已毕业?") throw new Error(displayLevel("K · 已毕业?"));',
  'if (displayLevel("Year 4") !== "Year 4") throw new Error("Year 4 label changed");',
  'console.log("ok");'
].join('\n');
new Function(code)();
'''
