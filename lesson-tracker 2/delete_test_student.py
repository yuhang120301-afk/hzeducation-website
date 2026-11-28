"""Remove the one profile named exactly 测试学生.

Helen asked for this test profile to be deleted from the live database.
A backup is written first. The parent login is removed only when it is not
linked to any other student. Every other profile is left as it is.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import backup

KEY = 'delete_test_student_v1'
NAME = '测试学生'


def _log(lines):
    print('\n'.join(lines), file=sys.stderr, flush=True)


def _marked(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'").fetchone():
        return False
    return c.execute('SELECT 1 FROM app_meta WHERE key=?', (KEY,)).fetchone() is not None


def _has(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _money(cents):
    return '$%.2f' % ((cents or 0) / 100)


def _matches(c):
    if not _has(c, 'student_profiles'):
        return []
    found = []
    for row in c.execute('SELECT id, name FROM student_profiles'):
        if str(row['name'] or '').strip() == NAME:
            found.append(row['id'])
    return found


def _courses(c, profile_id):
    if not _has(c, 'students'):
        return []
    return list(c.execute('SELECT * FROM students WHERE profile_id=? ORDER BY id', (profile_id,)))


def _parents(c, profile_id, course_ids):
    found = []
    if _has(c, 'profile_parents'):
        found += [row['user_id'] for row in c.execute(
            'SELECT user_id FROM profile_parents WHERE profile_id=?', (profile_id,))]
    if course_ids and _has(c, 'students'):
        marks = ','.join('?' for _ in course_ids)
        found += [row['parent_id'] for row in c.execute(
            f'SELECT parent_id FROM students WHERE id IN ({marks})', course_ids)]
    seen = []
    for uid in found:
        if uid and uid not in seen:
            seen.append(uid)
    return seen


def _other_links(c, user_id, profile_id):
    others = set()
    if _has(c, 'profile_parents'):
        for row in c.execute('SELECT profile_id FROM profile_parents WHERE user_id=? AND profile_id!=?', (user_id, profile_id)):
            others.add(row['profile_id'])
    if _has(c, 'students'):
        for row in c.execute('SELECT DISTINCT profile_id FROM students WHERE parent_id=? AND profile_id!=?', (user_id, profile_id)):
            if row['profile_id']:
                others.add(row['profile_id'])
    return others


def _keep_parent(c, user_id):
    if _has(c, 'teachers') and c.execute('SELECT 1 FROM teachers WHERE user_id=?', (user_id,)).fetchone():
        return True
    if _has(c, 'organization_owners') and c.execute('SELECT 1 FROM organization_owners WHERE user_id=?', (user_id,)).fetchone():
        return True
    role = c.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
    return bool(role and role['role'] in ('admin', 'owner'))


def _lesson_ids(c, course_ids):
    if not course_ids or not _has(c, 'lesson_students'):
        return []
    marks = ','.join('?' for _ in course_ids)
    return [row['lesson_id'] for row in c.execute(
        f'SELECT DISTINCT lesson_id FROM lesson_students WHERE student_id IN ({marks})', course_ids)]


def _shared(c, lesson_id, course_ids):
    marks = ','.join('?' for _ in course_ids)
    row = c.execute(
        f'SELECT COUNT(*) n FROM lesson_students WHERE lesson_id=? AND student_id NOT IN ({marks})',
        (lesson_id, *course_ids)).fetchone()
    return row['n'] > 0


def _finance(c, profile_id, courses):
    """Cents this profile adds to cash received and to institution lesson fees."""
    course_ids = [row['id'] for row in courses]
    cash = 0
    counted = 0
    excluded = 0
    if not course_ids or not _has(c, 'ledger'):
        return cash, counted, excluded
    marks = ','.join('?' for _ in course_ids)
    if _has(c, 'cash_entries'):
        cash = c.execute(f'''SELECT COALESCE(SUM(cash.cash_delta),0) n
            FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id
            WHERE l.student_id IN ({marks}) AND l.kind!='reversal'
              AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reversal_of=l.id)''', course_ids).fetchone()['n']
    import payroll
    original = payroll.current_origin_flag(c, profile_id, 0)
    if _has(c, 'lesson_reports'):
        rows = c.execute(f'''SELECT r.ledger_id, r.amount, r.fee_cents, s.course, sb.is_maths
            FROM lesson_reports r JOIN students s ON s.id=r.student_id
            LEFT JOIN subjects sb ON sb.id=s.subject_id
            LEFT JOIN ledger l ON l.id=r.ledger_id
            WHERE r.student_id IN ({marks})
              AND (r.ledger_id IS NULL OR (
                l.kind!='reversal' AND NOT EXISTS (SELECT 1 FROM ledger x WHERE x.reversal_of=l.id)))''', course_ids)
        for row in rows:
            maths = bool(row['is_maths']) or ('数学' in str(row['course'] or ''))
            counts = payroll.counts_for_institution({'is_new': not original, 'is_maths': maths})
            fee = row['fee_cents']
            if fee is None and row['ledger_id']:
                try:
                    fee, _, _ = payroll.fee_for_ledger(c, row['ledger_id'], row['amount'])
                except Exception:
                    fee = None
            if not counts:
                excluded += fee or 0
            elif fee is not None:
                counted += fee
    return int(cash or 0), int(counted or 0), int(excluded or 0)


def _describe(c, profile_id):
    courses = _courses(c, profile_id)
    course_ids = [row['id'] for row in courses]
    lessons = _lesson_ids(c, course_ids)
    shared = [lid for lid in lessons if _shared(c, lid, course_ids)]
    alone = [lid for lid in lessons if lid not in shared]
    reports = 0
    if course_ids and _has(c, 'lesson_reports'):
        marks = ','.join('?' for _ in course_ids)
        reports = c.execute(f'SELECT COUNT(*) n FROM lesson_reports WHERE student_id IN ({marks})', course_ids).fetchone()['n']
    ledger = 0
    if course_ids and _has(c, 'ledger'):
        marks = ','.join('?' for _ in course_ids)
        ledger = c.execute(f'SELECT COUNT(*) n FROM ledger WHERE student_id IN ({marks})', course_ids).fetchone()['n']
    batches = 0
    if course_ids and _has(c, 'credit_batches'):
        marks = ','.join('?' for _ in course_ids)
        batches = c.execute(f'SELECT COUNT(*) n FROM credit_batches WHERE student_id IN ({marks})', course_ids).fetchone()['n']
    vouchers = 0
    if course_ids and _has(c, 'vouchers'):
        marks = ','.join('?' for _ in course_ids)
        vouchers = c.execute(f'SELECT COUNT(*) n FROM vouchers WHERE student_id IN ({marks})', course_ids).fetchone()['n']
    parents = []
    for uid in _parents(c, profile_id, course_ids):
        user = c.execute('SELECT id, name FROM users WHERE id=?', (uid,)).fetchone()
        others = _other_links(c, uid, profile_id)
        if others or _keep_parent(c, uid):
            parents.append(f"#{uid} {user['name'] if user else ''} 只取消关联（还挂着 {len(others)} 个其他学生）")
        else:
            parents.append(f"#{uid} {user['name'] if user else ''} 连同登录一起删除")
    cash, counted, excluded = _finance(c, profile_id, courses)
    course_text = '、'.join(f"#{row['id']} {row['course']}" for row in courses) or '没有课程'
    lines = [
        'DRY-RUN  删除测试学生',
        f'档案 #{profile_id} {NAME}',
        f'课程：{course_text}',
        f'上课 {len(lessons)} 节（独自 {len(alone)}，和其他学生一起 {len(shared)}），课后记录 {reports}',
        f'账目 {ledger} 笔，课时包 {batches}，单据 {vouchers}',
        '家长：' + ('；'.join(parents) if parents else '没有'),
        f'实收减少 {_money(cash)}。计入分红的课酬减少 {_money(counted)}。不计入分红的课酬 {_money(excluded)}。',
        '其他学生的课和账不改。和其他学生一起上的课只去掉测试学生。',
    ]
    return lines, {
        'courses': courses, 'course_ids': course_ids, 'alone': alone, 'shared': shared,
        'cash': cash, 'counted': counted, 'excluded': excluded,
    }


def _delete_in(c, table, column, ids):
    if not ids or not _has(c, table):
        return
    columns = {row['name'] for row in c.execute('PRAGMA table_info(' + table + ')')}
    if column not in columns:
        return
    marks = ','.join('?' for _ in ids)
    c.execute(f'DELETE FROM {table} WHERE {column} IN ({marks})', ids)


def _drop_series(c, course_ids):
    if not _has(c, 'lesson_series'):
        return
    wanted = {str(item) for item in course_ids}
    for rule in c.execute('SELECT id, template, stop_index, next_index FROM lesson_series'):
        try:
            template = json.loads(rule['template'] or '{}')
        except json.JSONDecodeError:
            continue
        raw = template.get('student_ids') or []
        kept = [item for item in raw if str(item) not in wanted]
        if len(kept) == len(raw):
            continue
        template['student_ids'] = kept
        if kept:
            c.execute('UPDATE lesson_series SET template=? WHERE id=?', (json.dumps(template), rule['id']))
        else:
            stop = rule['stop_index'] if rule['stop_index'] is not None else rule['next_index']
            c.execute('UPDATE lesson_series SET template=?, endless=0, stop_index=? WHERE id=?',
                (json.dumps(template), stop, rule['id']))


def _apply(c, profile_id, plan):
    course_ids = plan['course_ids']
    _delete_in(c, 'lesson_students', 'student_id', course_ids)
    _delete_in(c, 'lesson_reports', 'student_id', course_ids)
    _delete_in(c, 'arrears', 'student_id', course_ids)
    _delete_in(c, 'profile_audit', 'student_id', course_ids)
    empty = []
    if plan['alone'] and _has(c, 'lesson_students'):
        marks = ','.join('?' for _ in plan['alone'])
        empty = [row['id'] for row in c.execute(
            f'''SELECT l.id FROM lessons l WHERE l.id IN ({marks})
                AND NOT EXISTS (SELECT 1 FROM lesson_students ls WHERE ls.lesson_id=l.id)''', plan['alone'])]
    _delete_in(c, 'report_edits', 'lesson_id', empty)
    _delete_in(c, 'lesson_reports', 'lesson_id', empty)
    _delete_in(c, 'lessons', 'id', empty)
    if course_ids and _has(c, 'vouchers'):
        marks = ','.join('?' for _ in course_ids)
        voucher_ids = [row['id'] for row in c.execute(
            f'SELECT id FROM vouchers WHERE student_id IN ({marks})', course_ids)]
        _delete_in(c, 'voucher_events', 'voucher_id', voucher_ids)
        _delete_in(c, 'vouchers', 'id', voucher_ids)
    if course_ids and _has(c, 'ledger'):
        marks = ','.join('?' for _ in course_ids)
        ledger_ids = [row['id'] for row in c.execute(
            f'SELECT id FROM ledger WHERE student_id IN ({marks})', course_ids)]
        _delete_in(c, 'cash_entries', 'ledger_id', ledger_ids)
        _delete_in(c, 'credit_movements', 'ledger_id', ledger_ids)
        _delete_in(c, 'pack_payments', 'ledger_id', ledger_ids)
        _delete_in(c, 'credit_batches', 'student_id', course_ids)
        _delete_in(c, 'ledger', 'id', ledger_ids)
    _drop_series(c, course_ids)
    parent_ids = _parents(c, profile_id, course_ids)
    removed_parents = []
    unlinked_parents = []
    for uid in parent_ids:
        others = _other_links(c, uid, profile_id)
        if others or _keep_parent(c, uid):
            unlinked_parents.append(uid)
        else:
            removed_parents.append(uid)
    if _has(c, 'students'):
        c.execute('DELETE FROM students WHERE profile_id=?', (profile_id,))
    if _has(c, 'profile_parents'):
        c.execute('DELETE FROM profile_parents WHERE profile_id=?', (profile_id,))
    for table in ('student_origin_events', 'student_subject_prices', 'profile_events'):
        if _has(c, table):
            c.execute(f'DELETE FROM {table} WHERE profile_id=?', (profile_id,))
    c.execute('DELETE FROM student_profiles WHERE id=?', (profile_id,))
    for uid in removed_parents:
        if _other_links(c, uid, profile_id) or _keep_parent(c, uid):
            unlinked_parents.append(uid)
            continue
        if _has(c, 'sessions'):
            c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        c.execute('DELETE FROM users WHERE id=?', (uid,))
    c.execute('INSERT INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))
    return {'empty_lessons': empty, 'removed_parents': removed_parents, 'unlinked_parents': unlinked_parents}


def _production(db_path):
    real = os.path.realpath(db_path) if db_path else ''
    return real == '/var/data/lessons.sqlite3' or real.startswith('/var/data/')


def _backup(db_path):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    destination = f'/var/data/backup-delete-test-student-{stamp}.sqlite3'
    backup.write_snapshot(db_path, destination)
    return destination


def run(c, db_path):
    try:
        if _marked(c):
            return
        matches = _matches(c)
    except sqlite3.Error as exc:
        _log([f'测试学生没有读成：{exc}'])
        return
    if len(matches) != 1:
        populated = _has(c, 'student_profiles') and c.execute('SELECT COUNT(*) n FROM student_profiles').fetchone()['n']
        if populated and _has(c, 'app_meta'):
            if len(matches) == 0:
                c.execute('INSERT OR IGNORE INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))
                _log(['没有名为测试学生的档案。'])
            else:
                _log([f'名为测试学生的档案有 {len(matches)} 个（{"、".join("#%s" % item for item in matches)}），这次不删。'])
        return
    profile_id = matches[0]
    lines, plan = _describe(c, profile_id)
    _log(lines)
    if _production(db_path):
        try:
            copied = _backup(db_path)
        except (OSError, FileExistsError, FileNotFoundError, RuntimeError) as exc:
            _log([f'备份没有写成，这次不删除：{exc}'])
            return
        _log([f'已备份到 {copied}，没有替换正在用的数据库。'])
    c.execute('SAVEPOINT delete_test_student')
    try:
        done = _apply(c, profile_id, plan)
    except Exception as exc:
        c.execute('ROLLBACK TO delete_test_student')
        c.execute('RELEASE delete_test_student')
        _log([f'没有删除：{exc}'])
        return
    c.execute('RELEASE delete_test_student')
    _log([
        f'APPLY  已删除档案 #{profile_id} {NAME}',
        f'课程 {len(plan["course_ids"])} 门，独自的课 {len(done["empty_lessons"])} 节已去掉，和其他学生一起的课保留。',
        f'删除的家长登录：{"、".join("#%s" % item for item in done["removed_parents"]) or "没有"}。只取消关联：{"、".join("#%s" % item for item in done["unlinked_parents"]) or "没有"}。',
        f'实收减少 {_money(plan["cash"])}。计入分红的课酬减少 {_money(plan["counted"])}。不计入分红的课酬 {_money(plan["excluded"])}。',
    ])
