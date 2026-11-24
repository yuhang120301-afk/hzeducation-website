#!/usr/bin/env python3
"""Turn the Term 1 2027 lessons into weekly series through 31 December 2027.

Default is a dry run. Pass --apply to write. Running it again inserts nothing.

--apply uses one connection and one transaction. It does not copy or replace
the database file, and it does not change journal_mode. It waits if the
database is busy, checks integrity before it writes and before and after
commit, and rolls back if anything fails. It does not call initialize().
"""
import argparse
import hashlib
import json
import os
import sqlite3
from datetime import date, timedelta

import term1_2027_schedule as term1

UNTIL = date(2027, 12, 31)


def series_id(title, weekday, start):
    return hashlib.sha256(f'extend-2027-series|{title}|{weekday}|{start}'.encode()).hexdigest()[:32]


def extend_request_id(title, starts):
    return hashlib.sha256(f'extend-2027|{title}|{starts}'.encode()).hexdigest()[:32]


def weeks_from(first):
    days = []
    day = first
    while day <= UNTIL:
        days.append(day)
        day += timedelta(days=7)
    return days


def _connect_ro(db_path):
    c = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA query_only=ON')
    return c


def _connect_rw(db_path):
    c = sqlite3.connect(db_path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def _require_integrity(c, when):
    row = c.execute('PRAGMA integrity_check').fetchone()
    detail = row[0] if row else 'no result'
    if detail != 'ok':
        raise RuntimeError(f'integrity_check {when}: {detail}')


def _lesson_for(c, title, starts):
    for key in (term1.request_id(title, starts), extend_request_id(title, starts)):
        row = c.execute('SELECT * FROM lessons WHERE request_id=?', (key,)).fetchone()
        if row:
            return row
    return None


def _plan(c):
    slots = []
    for weekday, start, end, title, _teacher, _students, _color in term1.SLOTS:
        if '试听' in title:
            slots.append({'title': title, 'skip': 'trial'})
            continue
        term_days = list(term1.dates_for(weekday))
        found = []
        for day in term_days:
            row = _lesson_for(c, title, f'{day.isoformat()}T{start}')
            if row:
                found.append(row)
        active = [row for row in found if row['status'] != 'cancelled']
        if not active:
            slots.append({'title': title, 'weekday': weekday, 'start': start, 'skip': 'cancelled-or-missing',
                'existing': len(found), 'insert': 0, 'last': ''})
            continue
        first = term_days[0]
        calendar = weeks_from(first)
        last = max(date.fromisoformat(row['starts_at'][:10]) for row in found)
        missing = []
        for index, day in enumerate(calendar):
            if day <= last:
                continue
            starts = f'{day.isoformat()}T{start}'
            if _lesson_for(c, title, starts):
                continue
            missing.append((index, day, starts, f'{day.isoformat()}T{end}'))
        template = dict(active[-1])
        slots.append({
            'title': title, 'weekday': weekday, 'start': start, 'end': end, 'skip': '',
            'existing': len(found), 'insert': len(missing), 'last': last.isoformat(),
            'first': first, 'calendar': calendar, 'missing': missing, 'template_id': template['id'],
            'series_id': series_id(title, weekday, start),
        })
    return slots


def _summary(slots):
    lines = []
    insert = linked = skipped = 0
    for slot in slots:
        if slot['skip'] == 'trial':
            lines.append(f"跳过试听  {slot['title']}")
            skipped += 1
            continue
        if slot['skip']:
            lines.append(f"跳过  {slot['title']}  已有 {slot['existing']} 节都被取消或删除")
            skipped += 1
            continue
        lines.append(
            f"{slot['title']}  周{slot['weekday']+1} {slot['start']}  existing={slot['existing']}  "
            f"insert={slot['insert']}  last={slot['last']}  through={slot['calendar'][-1].isoformat()}")
        insert += slot['insert']
    return lines, insert, skipped


def _apply_slot(c, slot, actor_id):
    template = c.execute('SELECT * FROM lessons WHERE id=?', (slot['template_id'],)).fetchone()
    students = [row['student_id'] for row in c.execute(
        'SELECT student_id FROM lesson_students WHERE lesson_id=? ORDER BY student_id', (template['id'],))]
    sid = slot['series_id']
    payload = {
        'title': template['title'], 'teacher_id': template['teacher_id'],
        'starts_at': f"{slot['first'].isoformat()}T{slot['start']}",
        'ends_at': f"{slot['first'].isoformat()}T{slot['end']}",
        'location': template['location'] or '', 'color': template['color'] or 'green',
        'amount': str((template['planned_units'] or 100) / 100), 'student_ids': students,
        'course_type_id': template['course_type_id'], 'subject_id': template['subject_id'],
    }
    if not c.execute('SELECT 1 FROM lesson_series WHERE id=?', (sid,)).fetchone():
        c.execute('''INSERT INTO lesson_series(id,interval_days,endless,next_index,stop_index,template,created_by)
            VALUES(?,7,0,?,?,?,?)''', (sid, len(slot['calendar']), len(slot['calendar']), json.dumps(payload), actor_id))
    for index, day in enumerate(slot['calendar']):
        row = _lesson_for(c, slot['title'], f"{day.isoformat()}T{slot['start']}")
        if row and row['series_id'] != sid:
            c.execute('UPDATE lessons SET series_id=?, occurrence_index=? WHERE id=?', (sid, index, row['id']))
    for index, _day, starts, ends in slot['missing']:
        key = extend_request_id(slot['title'], starts)
        if c.execute('SELECT 1 FROM lessons WHERE request_id=?', (key,)).fetchone():
            continue
        lid = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id,color,course_type_id,subject_id,series_id,occurrence_index)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            template['teacher_id'], template['title'], starts, ends, template['planned_units'],
            template['location'] or '', actor_id, key, template['color'] or 'green',
            template['course_type_id'], template['subject_id'], sid, index)).lastrowid
        c.executemany('INSERT INTO lesson_students(lesson_id,student_id) VALUES(?,?)', [(lid, student) for student in students])


def run(db_path, apply=False, out_path=None):
    if not apply:
        c = _connect_ro(db_path)
        try:
            _require_integrity(c, 'before dry-run')
            lines, insert, skipped = _summary(_plan(c))
        finally:
            c.close()
        _emit(db_path, False, out_path, lines, insert, skipped)
        return {'insert': insert, 'skipped': skipped}
    c = _connect_rw(db_path)
    try:
        _require_integrity(c, 'before changes')
        c.execute('BEGIN IMMEDIATE')
        actor = c.execute(
            '''SELECT u.id FROM organization_owners o JOIN users u ON u.id=o.user_id
               WHERE u.active=1 ORDER BY u.id LIMIT 1''').fetchone()
        if not actor:
            raise RuntimeError('没有可用的校长账号，已停止，未修改任何课程。')
        slots = _plan(c)
        for slot in slots:
            if not slot['skip']:
                _apply_slot(c, slot, actor['id'])
        lines, insert, skipped = _summary(slots)
        _require_integrity(c, 'before commit')
        c.commit()
        _require_integrity(c, 'after commit')
    except BaseException:
        try:
            c.rollback()
        except Exception:
            pass
        c.close()
        raise
    c.close()
    _emit(db_path, True, out_path, lines, insert, skipped)
    return {'insert': insert, 'skipped': skipped}


def _emit(db_path, apply, out_path, lines, insert, skipped):
    mode = 'APPLY' if apply else 'DRY-RUN'
    summary = [f'{mode}  database={db_path}', f'insert={insert} skipped_slots={skipped}']
    text = '\n'.join(lines + [''] + summary) + '\n'
    if out_path:
        summary.append(f'detail: {out_path}')
        with open(out_path, 'w', encoding='utf-8') as handle:
            handle.write(text)
    for line in summary:
        print(line)
    for line in lines:
        print(line)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Extend Term 1 2027 lessons weekly through 2027-12-31.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', '/var/data/lessons.sqlite3'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        raise SystemExit('请只选 --dry-run 或 --apply 其中一个。')
    run(args.db, apply=args.apply, out_path=args.out)


if __name__ == '__main__':
    main()
