#!/usr/bin/env python3
"""List lessons whose subject does not match the course they charge.

Read-only. Uses LESSON_DB. Does not write.

  LESSON_DB=/path/to/lessons.sqlite3 python3 scripts/report_lesson_course_mismatch.py
"""
import os
import sqlite3
import sys


def connect(db_path):
    c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA query_only=ON')
    return c


def main():
    db_path = os.environ.get('LESSON_DB', '')
    if not db_path or not os.path.exists(db_path):
        raise SystemExit('请设置 LESSON_DB，指向要查看的数据库。')
    c = connect(db_path)
    try:
        rows = c.execute('''SELECT l.id, l.starts_at, l.status, sb.name lesson_subject,
            s.id student_id, s.name student_name, s.course, cb.name course_subject
            FROM lessons l
            JOIN lesson_students ls ON ls.lesson_id=l.id
            JOIN students s ON s.id=ls.student_id
            LEFT JOIN subjects sb ON sb.id=l.subject_id
            LEFT JOIN subjects cb ON cb.id=s.subject_id
            WHERE s.subject_id IS NOT NULL AND l.subject_id IS NOT NULL AND s.subject_id!=l.subject_id
            ORDER BY l.starts_at, l.id, s.id''').fetchall()
    finally:
        c.close()
    print(f'只读  database={os.path.realpath(db_path)}')
    print(f'科目和课程不一致的课：{len(rows)} 条')
    for row in rows:
        print(f"  课{row['id']} {row['starts_at']} {row['status']} 课上科目{row['lesson_subject'] or '空'} / {row['student_name']} 课程{row['course']}（{row['course_subject'] or '空'}）")
    if not rows:
        print('没有不一致的课。')


if __name__ == '__main__':
    main()
