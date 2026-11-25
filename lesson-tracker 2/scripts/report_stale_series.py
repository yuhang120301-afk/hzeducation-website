#!/usr/bin/env python3
"""List old repeating series that are still dropping lessons into 2027 and 2028.

Read-only. The January 2027 timetable (series whose template starts
2027-01-25 through 2027-01-31) is not listed. Uses LESSON_DB.

  LESSON_DB="$LESSON_DB" python3 scripts/report_stale_series.py

These series began around September or October 2026. Saving any later lesson
asks the repeater to fill every endless series up to that lesson's date, so
the old rule keeps copying itself forward. Each copy keeps the teacher stored
on the original template. The 2026 lessons were Helen's, so the new copies
still show Helen. The person who saves a new lesson is not written as the teacher.
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recurrence
from teaching import now_local


def main():
    db = os.environ.get('LESSON_DB', '')
    if not db or not os.path.exists(db):
        raise SystemExit('请设置 LESSON_DB。')
    c = sqlite3.connect(f'file:{os.path.realpath(db)}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    c.execute('PRAGMA busy_timeout=30000')
    try:
        now = now_local().strftime('%Y-%m-%dT%H:%M')
        rows = recurrence.stale_series_report(c, now)
        print(f'只读  database={os.path.realpath(db)}')
        print('一月下旬开始的 2027 课表不在这里。任课老师来自原来的重复课模板，不是后来点保存的那个人。')
        print(f'过期重复课：{len(rows)}')
        if not rows:
            print('没有还在往后排的 2026 年旧课。')
            return
        for item in rows:
            students = '、'.join(item['students']) or '没有学生'
            print(f"系列 {item['series_id']}  从 {item['started']}  老师 {item['teacher'] or '未填'}  {students}  以后 {len(item['lessons'])} 节")
            for lesson in item['lessons']:
                mark = '保留（已有记录或账）' if lesson['locked'] else '可清理'
                print(f"  {lesson['starts_at']}  {lesson['title']}  {mark}")
    finally:
        c.close()


if __name__ == '__main__':
    main()
