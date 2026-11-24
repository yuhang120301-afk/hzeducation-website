#!/usr/bin/env python3
"""Remove Atticus and Benjamin lessons from 1 December 2026 onward.

Dry-run is the default and writes nothing.

  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/purge_test_students_after.py
  LESSON_DB=/var/data/lessons.sqlite3 python3 scripts/purge_test_students_after.py --apply

For every course row named Atticus or Benjamin:

- Delete lessons dated 2026-12-01 or later, including all of 2027 and after.
- Delete cancelled lessons on any date.
- Keep lessons before 2026-12-01 that are not cancelled.
- If other students are on a lesson, only Atticus or Benjamin is taken off it.
- End or delete their repeating series so nothing is generated after 2026-11-30.
  A series other students still use is left in place, with these two names
  removed from its template.

Lesson records and charges on a lesson being removed are listed. They are
deleted only when no money or credit was taken. A lesson with a real charge
is kept and listed.

--apply uses one connection, PRAGMA busy_timeout=30000, and one
BEGIN IMMEDIATE transaction. It does not change journal_mode and does not
run VACUUM.
"""
import argparse
import json
import os
import sqlite3

CUTOFF = '2026-12-01'
NAMES = ('atticus', 'benjamin')
STATUS = {'scheduled': '待上', 'completed': '已上', 'cancelled': '已取消'}


def connect(db_path, write):
    if write:
        c = sqlite3.connect(db_path, timeout=30)
    else:
        c = sqlite3.connect(f'file:{os.path.realpath(db_path)}?mode=ro', uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    if write:
        c.execute('PRAGMA foreign_keys=ON')
    else:
        c.execute('PRAGMA query_only=ON')
    return c


def integrity(c, when):
    row = c.execute('PRAGMA integrity_check').fetchone()
    detail = row[0] if row else 'no result'
    if detail != 'ok':
        raise RuntimeError(f'integrity_check {when}: {detail}')


def has_table(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def columns(c, table):
    if not has_table(c, table):
        return set()
    return {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}


def is_target(name):
    text = (name or '').casefold()
    return any(token in text for token in NAMES)


def target_students(c):
    return [row for row in c.execute('SELECT id, name, profile_id, course FROM students ORDER BY name, id') if is_target(row['name'])]


def roster(c, lesson_id):
    return list(c.execute('''SELECT s.id, s.name, s.profile_id FROM lesson_students ls
        JOIN students s ON s.id=ls.student_id WHERE ls.lesson_id=? ORDER BY s.id''', (lesson_id,)))


def candidate_lessons(c, ids):
    marks = ','.join('?' for _ in ids)
    return list(c.execute(f'''SELECT DISTINCT l.* FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE ls.student_id IN ({marks})
          AND (substr(l.starts_at,1,10)>=? OR l.status='cancelled')
        ORDER BY l.starts_at, l.id''', (*ids, CUTOFF)))


def linked_ledgers(c, lesson_id, student_ids):
    found = {}
    if not student_ids or not has_table(c, 'ledger'):
        return found
    marks = ','.join('?' for _ in student_ids)
    if has_table(c, 'lesson_reports') and 'ledger_id' in columns(c, 'lesson_reports'):
        for row in c.execute(f'''SELECT ledger_id FROM lesson_reports
            WHERE lesson_id=? AND student_id IN ({marks}) AND ledger_id IS NOT NULL''', (lesson_id, *student_ids)):
            found[row['ledger_id']] = True
    for sid in student_ids:
        for row in c.execute('SELECT id FROM ledger WHERE request_id LIKE ?', (f'scheduled-{lesson_id}-student-{sid}%',)):
            found[row['id']] = True
    return list(found)


def ledger_blocks(c, ledger_id):
    row = c.execute('SELECT * FROM ledger WHERE id=?', (ledger_id,)).fetchone()
    if not row:
        return ''
    if row['delta']:
        return f'账本#{ledger_id} 变动 {row["delta"]}'
    if has_table(c, 'credit_movements'):
        moved = c.execute('SELECT COALESCE(SUM(ABS(paid)+ABS(gift)+ABS(voided)),0) n FROM credit_movements WHERE ledger_id=?', (ledger_id,)).fetchone()['n']
        if moved:
            return f'账本#{ledger_id} 已扣课时'
    if has_table(c, 'credit_batches') and c.execute('SELECT 1 FROM credit_batches WHERE ledger_id=?', (ledger_id,)).fetchone():
        return f'账本#{ledger_id} 关联课时包'
    voucher_cols = columns(c, 'vouchers')
    if 'ledger_id' in voucher_cols and c.execute('SELECT 1 FROM vouchers WHERE ledger_id=?', (ledger_id,)).fetchone():
        return f'账本#{ledger_id} 已有单据'
    if 'reversal_ledger_id' in voucher_cols and c.execute('SELECT 1 FROM vouchers WHERE reversal_ledger_id=?', (ledger_id,)).fetchone():
        return f'账本#{ledger_id} 已有单据'
    if has_table(c, 'ledger_edits') and c.execute('SELECT 1 FROM ledger_edits WHERE ledger_id=?', (ledger_id,)).fetchone():
        return f'账本#{ledger_id} 已有修改记录'
    if 'reversal_of' in columns(c, 'ledger') and c.execute('SELECT 1 FROM ledger WHERE reversal_of=?', (ledger_id,)).fetchone():
        return f'账本#{ledger_id} 已撤销过'
    return ''


def money_reason(c, lesson_id, student_ids):
    reasons = []
    for ledger_id in linked_ledgers(c, lesson_id, student_ids):
        reason = ledger_blocks(c, ledger_id)
        if reason:
            reasons.append(reason)
    if has_table(c, 'lesson_reports') and 'fee_cents' in columns(c, 'lesson_reports') and student_ids:
        marks = ','.join('?' for _ in student_ids)
        fee = c.execute(f'''SELECT fee_cents FROM lesson_reports
            WHERE lesson_id=? AND student_id IN ({marks}) AND COALESCE(fee_cents,0)!=0 LIMIT 1''', (lesson_id, *student_ids)).fetchone()
        if fee:
            reasons.append(f'课酬 {fee["fee_cents"]/100:.2f}')
    if has_table(c, 'arrears') and 'settled' in columns(c, 'arrears') and student_ids:
        marks = ','.join('?' for _ in student_ids)
        if c.execute(f'''SELECT 1 FROM arrears WHERE lesson_id=? AND student_id IN ({marks}) AND settled=1''', (lesson_id, *student_ids)).fetchone():
            reasons.append('欠费已结清')
    return '；'.join(reasons)


def attached_notes(c, lesson_id, student_ids):
    notes = []
    if has_table(c, 'lesson_reports') and student_ids:
        marks = ','.join('?' for _ in student_ids)
        count = c.execute(f'SELECT COUNT(*) n FROM lesson_reports WHERE lesson_id=? AND student_id IN ({marks})', (lesson_id, *student_ids)).fetchone()['n']
        if count:
            notes.append(f'课后记录 {count}')
    if has_table(c, 'report_edits') and c.execute('SELECT 1 FROM report_edits WHERE lesson_id=?', (lesson_id,)).fetchone():
        notes.append('修改记录')
    if has_table(c, 'arrears') and student_ids:
        marks = ','.join('?' for _ in student_ids)
        count = c.execute(f'SELECT COUNT(*) n FROM arrears WHERE lesson_id=? AND student_id IN ({marks})', (lesson_id, *student_ids)).fetchone()['n']
        if count:
            notes.append(f'欠费 {count}')
    ledgers = linked_ledgers(c, lesson_id, student_ids)
    if ledgers:
        notes.append('账本 ' + '、'.join(f'#{item}' for item in ledgers))
    return '、'.join(notes)


def classify(c, students):
    ids = {row['id'] for row in students}
    actions = []
    for lesson in candidate_lessons(c, ids):
        people = roster(c, lesson['id'])
        targets = [row for row in people if row['id'] in ids]
        others = [row for row in people if row['id'] not in ids]
        free = []
        kept = []
        for person in targets:
            reason = money_reason(c, lesson['id'], [person['id']])
            if reason:
                kept.append((person, reason))
            else:
                free.append(person)
        if free and not others and not kept:
            kind = 'delete'
        elif free:
            kind = 'unlink'
        else:
            kind = 'keep'
        actions.append({
            'kind': kind, 'lesson': lesson, 'free': free, 'kept': kept, 'others': others,
            'notes': attached_notes(c, lesson['id'], [person['id'] for person in targets]),
        })
    return actions


def template_students(rule):
    try:
        raw = json.loads(rule['template'] or '{}').get('student_ids') or []
    except json.JSONDecodeError:
        raw = []
    found = []
    for item in raw:
        try:
            found.append(int(item))
        except (TypeError, ValueError):
            continue
    return found


def series_plan(c, students, actions):
    ids = {row['id'] for row in students}
    deleted = {item['lesson']['id'] for item in actions if item['kind'] == 'delete'}
    touched = set()
    if ids:
        marks = ','.join('?' for _ in ids)
        for row in c.execute(f'''SELECT DISTINCT l.series_id FROM lessons l
            JOIN lesson_students ls ON ls.lesson_id=l.id
            WHERE ls.student_id IN ({marks}) AND l.series_id IS NOT NULL''', tuple(ids)):
            touched.add(row['series_id'])
    if has_table(c, 'lesson_series'):
        for rule in c.execute('SELECT id, template FROM lesson_series'):
            if any(sid in ids for sid in template_students(rule)):
                touched.add(rule['id'])
    plan = []
    for sid in sorted(touched, key=str):
        rule = c.execute('SELECT * FROM lesson_series WHERE id=?', (sid,)).fetchone()
        if not rule:
            continue
        lessons = list(c.execute('SELECT id, occurrence_index FROM lessons WHERE series_id=?', (sid,)))
        remaining = [row for row in lessons if row['id'] not in deleted]
        other_people = []
        for row in remaining:
            other_people.extend(person for person in roster(c, row['id']) if person['id'] not in ids)
        others_in_template = [sid_ for sid_ in template_students(rule) if sid_ not in ids]
        if other_people or others_in_template:
            remove = [sid_ for sid_ in template_students(rule) if sid_ in ids]
            if remove:
                plan.append({'kind': 'strip', 'rule': rule, 'remove': remove})
            continue
        if not remaining:
            plan.append({'kind': 'drop', 'rule': rule})
            continue
        indexes = [row['occurrence_index'] for row in remaining if row['occurrence_index'] is not None]
        stop = (max(indexes) + 1) if indexes else 0
        plan.append({'kind': 'end', 'rule': rule, 'stop': stop})
    return plan


def student_key(person):
    return person['name'].casefold()


def counts_for(students, actions, series):
    grouped = {}
    for student in students:
        key = student_key(student)
        bucket = grouped.setdefault(key, {'name': student['name'], 'rows': [], 'future': 0, 'cancelled': 0,
            'shared': 0, 'kept': 0, 'samples': []})
        bucket['rows'].append(student)
    series_names = {}
    for item in actions:
        lesson = item['lesson']
        future = lesson['starts_at'][:10] >= CUTOFF
        cancelled = lesson['status'] == 'cancelled'
        shared = bool(item['others'])
        for person in item['free'] + [pair[0] for pair in item['kept']]:
            bucket = grouped.get(student_key(person))
            if not bucket:
                continue
            if future:
                bucket['future'] += 1
            if cancelled:
                bucket['cancelled'] += 1
            if shared and person in item['free']:
                bucket['shared'] += 1
            if any(pair[0]['id'] == person['id'] for pair in item['kept']):
                bucket['kept'] += 1
            if len(bucket['samples']) < 5 and person in item['free']:
                bucket['samples'].append(item)
            series_names.setdefault(lesson['series_id'], set()).add(student_key(person))
    for item in series:
        names = series_names.get(item['rule']['id'], set())
        if not names:
            for student in students:
                if student['id'] in template_students(item['rule']) or student['id'] in item.get('remove', []):
                    names.add(student_key(student))
        for key in names:
            if key in grouped:
                grouped[key].setdefault('series', []).append(item)
    return grouped


def lesson_sample(item):
    lesson = item['lesson']
    action = {'delete': '删除整节', 'unlink': '只移出这两位', 'keep': '保留'}[item['kind']]
    extra = item['notes'] or '没有课后记录或账本'
    kept = '；'.join(f"{pair[0]['name']} {pair[1]}" for pair in item['kept'])
    if kept:
        extra = f'{extra}；保留因为{kept}' if item['notes'] else f'保留因为{kept}'
    return (f"  #{lesson['id']} {lesson['starts_at'][:16].replace('T',' ')} {STATUS.get(lesson['status'], lesson['status'])}"
            f" {lesson['title']} 系列{lesson['series_id'] or '无'} {action} {extra}")


def describe(students, actions, series):
    grouped = counts_for(students, actions, series)
    lines = [f'截止日期 {CUTOFF}。这一天和之后的课会去掉。更早的已取消课也会去掉。更早且没取消的课保留。']
    if not students:
        lines.append('没有找到 Atticus 或 Benjamin。')
        return lines
    for bucket in grouped.values():
        rows = '、'.join(f"#{row['id']} {row['course'] or ''}".strip() for row in bucket['rows'])
        owned = bucket.get('series') or []
        lines.append(f"{bucket['name']}  课程行 {rows}")
        lines.append(f"  以后的课 {bucket['future']}  已取消 {bucket['cancelled']}  和别人合上并移出 {bucket['shared']}  因已扣费保留 {bucket['kept']}  系列 {len(owned)}")
        for item in bucket['samples']:
            lines.append(lesson_sample(item))
        if not bucket['samples'] and bucket['kept']:
            lines.append('  样例：这些课因为已扣费而保留，没有可删的样例。')
    drops = [item for item in series if item['kind'] == 'drop']
    ends = [item for item in series if item['kind'] == 'end']
    strips = [item for item in series if item['kind'] == 'strip']
    lines.append(f"系列：删除 {len(drops)}，结束 {len(ends)}，从别人的系列模板里去掉 {len(strips)}。")
    for item in (drops + ends + strips)[:8]:
        rule = item['rule']
        if item['kind'] == 'drop':
            lines.append(f"  删除系列 {rule['id']}")
        elif item['kind'] == 'end':
            lines.append(f"  结束系列 {rule['id']}  止于序号 {item['stop']}")
        else:
            lines.append(f"  系列 {rule['id']} 去掉学生 {item['remove']}")
    kept = [item for item in actions if item['kind'] == 'keep' or item['kept']]
    if kept:
        lines.append(f'有扣费所以整节或这位学生保留 {len(kept)} 节：')
        for item in kept[:8]:
            lines.append(lesson_sample(item))
    delete_n = sum(1 for item in actions if item['kind'] == 'delete')
    unlink_n = sum(1 for item in actions if item['kind'] == 'unlink')
    lines.append(f'合计 删除课节 {delete_n}  只移出学生 {unlink_n}  系列 {len(series)}')
    return lines


def delete_student_bits(c, lesson_id, student_ids):
    if not student_ids:
        return
    marks = ','.join('?' for _ in student_ids)
    ledger_ids = linked_ledgers(c, lesson_id, student_ids)
    if has_table(c, 'lesson_reports'):
        c.execute(f'DELETE FROM lesson_reports WHERE lesson_id=? AND student_id IN ({marks})', (lesson_id, *student_ids))
    if has_table(c, 'arrears'):
        c.execute(f'DELETE FROM arrears WHERE lesson_id=? AND student_id IN ({marks})', (lesson_id, *student_ids))
    for ledger_id in ledger_ids:
        if ledger_blocks(c, ledger_id):
            continue
        if has_table(c, 'credit_movements'):
            c.execute('DELETE FROM credit_movements WHERE ledger_id=?', (ledger_id,))
        c.execute('DELETE FROM ledger WHERE id=?', (ledger_id,))
    c.execute(f'DELETE FROM lesson_students WHERE lesson_id=? AND student_id IN ({marks})', (lesson_id, *student_ids))


def apply_actions(c, actions, series):
    for item in actions:
        if item['kind'] == 'keep':
            continue
        lesson_id = item['lesson']['id']
        student_ids = [person['id'] for person in item['free']]
        delete_student_bits(c, lesson_id, student_ids)
        if item['kind'] != 'delete':
            continue
        if has_table(c, 'report_edits'):
            c.execute('DELETE FROM report_edits WHERE lesson_id=?', (lesson_id,))
        if has_table(c, 'lesson_reports'):
            c.execute('DELETE FROM lesson_reports WHERE lesson_id=?', (lesson_id,))
        if has_table(c, 'arrears'):
            c.execute('DELETE FROM arrears WHERE lesson_id=?', (lesson_id,))
        c.execute('DELETE FROM lessons WHERE id=?', (lesson_id,))
    for item in series:
        rule = item['rule']
        if item['kind'] == 'drop':
            if c.execute('SELECT 1 FROM lessons WHERE series_id=?', (rule['id'],)).fetchone():
                indexes = [row['occurrence_index'] for row in c.execute('SELECT occurrence_index FROM lessons WHERE series_id=?', (rule['id'],)) if row['occurrence_index'] is not None]
                stop = (max(indexes) + 1) if indexes else 0
                c.execute("UPDATE lesson_series SET endless=0, stop_index=?, error='' WHERE id=?", (stop, rule['id']))
                continue
            c.execute('DELETE FROM lesson_series WHERE id=?', (rule['id'],))
        elif item['kind'] == 'end':
            c.execute("UPDATE lesson_series SET endless=0, stop_index=?, error='' WHERE id=?", (item['stop'], rule['id']))
        else:
            kept = [sid for sid in template_students(rule) if sid not in item['remove']]
            try:
                payload = json.loads(rule['template'] or '{}')
            except json.JSONDecodeError:
                payload = {}
            payload['student_ids'] = kept
            c.execute('UPDATE lesson_series SET template=?, version=version+1 WHERE id=?', (json.dumps(payload), rule['id']))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Purge Atticus and Benjamin lessons from 2026-12-01 onward.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        raise SystemExit('只能选 --dry-run 或 --apply 其中一个。')
    if not args.db:
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    if not os.path.exists(args.db):
        raise SystemExit(f'找不到数据库：{args.db}')
    if not args.apply:
        c = connect(args.db, False)
        try:
            students = target_students(c)
            actions = classify(c, students) if students else []
            series = series_plan(c, students, actions) if students else []
            print('\n'.join([f'DRY-RUN  database={os.path.realpath(args.db)}', *describe(students, actions, series)]))
        finally:
            c.close()
        return
    c = connect(args.db, True)
    try:
        c.execute('BEGIN IMMEDIATE')
        integrity(c, 'before changes')
        students = target_students(c)
        actions = classify(c, students) if students else []
        series = series_plan(c, students, actions) if students else []
        apply_actions(c, actions, series)
        integrity(c, 'before commit')
        c.commit()
        print('\n'.join([f'APPLY  database={os.path.realpath(args.db)}', *describe(students, actions, series), '已写入。']))
    except BaseException:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        c.close()


if __name__ == '__main__':
    main()
