"""Month arrows move one month, including when the 1st is not a Monday."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class CalendarMonthTests(unittest.TestCase):
    def test_next_month_does_not_fall_back_into_the_same_month(self):
        script = r'''
const fs = require('fs');
const src = fs.readFileSync('static/calendar.js', 'utf8');
const start = src.indexOf('function monthStart');
const end = src.indexOf('/* shiftMonth:end */');
if (start < 0 || end < 0) process.exit(2);
eval(src.slice(start, end));
const cases = [
  ['2026-11-01', 1, '2026-12-01'],
  ['2026-11-30', 1, '2026-12-01'],
  ['2026-12-01', -1, '2026-11-01'],
  ['2026-03-01', 1, '2026-04-01'],
  ['2026-01-31', 1, '2026-02-01'],
  ['2026-01-31', -1, '2025-12-01'],
];
for (const [day, direction, expect] of cases) {
  const got = shiftMonth(day, direction);
  if (got !== expect) {
    console.error(day, direction, got, expect);
    process.exit(1);
  }
}
const teach = fs.readFileSync('static/teaching.js', 'utf8');
if (!teach.includes("calendarSpan!=='month'")) process.exit(3);
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
