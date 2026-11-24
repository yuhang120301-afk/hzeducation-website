#!/usr/bin/env python3
"""One-off Term 1 2027 timetable for the live lesson book.

Default is a dry run: it prints every future lesson it would cancel and every
Term 1 lesson it would create, then leaves the database unchanged. Pass
--apply to write. Running it again does not add a second copy.

Victorian Term 1 2027 runs through Thursday 25 March 2027. Lessons start in
the week of Monday 25 January 2027 and repeat weekly while the date is on or
before 25 March. That is nine Mondays–Thursdays and eight Fridays–Sundays.
The app's "forever" repeat is not used, because it would keep going for about
a year.

Cancellations use the normal cancel function with waive_leave, so the
operation log records them and no lesson is deducted and no arrears row is
written. Students, balances, and past or already-completed lessons stay.
Any future lesson that includes a student named Atticus or Benjamin stays,
even if other students are on it.

Four clashes cannot share one teacher. The later class is stored under a
待定 teacher and the title says who it was meant for:

- Thursday Jeffery English overlaps Lakyn, both meant for Helen.
- Saturday Cathy 妹妹 overlaps Bella 高数, both meant for Helen.
- Saturday Sunny + Shirley English overlaps Zachary English; both were
  unassigned, so they use 待定 and 待定 2.
- Sunday Cathy 妹妹 overlaps Cathy's VCE MM, and Yilia overlaps the
  中数 unit 3/4 group. Those two move to 待定, which is free then.
"""
import argparse
import hashlib
import os
import secrets
from datetime import date, timedelta

TERM_START = date(2027, 1, 25)  # Monday
TERM_END = date(2027, 3, 25)    # Thursday, Victorian term end
KEEP = ('atticus', 'benjamin')
ROSTER_PHONE = '0499000099'
CANCEL_REASON = '2027 第一学期排课前清理：取消未来课程，不扣课时。'

# weekday, start, end, title, teacher key, student names or None, colour
SLOTS = [
    (0, '17:45', '19:30', 'Edward', 'helen', ['Edward'], 'green'),
    (1, '18:00', '19:00', 'Sia + Molly · 1:2', 'vincent', ['Sia', 'Molly'], 'blue'),
    (1, '18:00', '19:30', 'Sheldon', 'helen', ['Sheldon'], 'green'),
    (1, '19:00', '20:00', 'Molly · 试听 · 待定', 'angela', ['Molly'], 'gray'),
    (1, '19:30', '21:00', 'Benjamin', 'helen', ['Benjamin'], 'green'),
    (2, '19:30', '21:00', 'Felix', 'helen', ['Felix'], 'green'),
    (3, '17:00', '19:00', 'Lakyn', 'helen', ['Lakyn'], 'green'),
    (3, '17:00', '18:30', 'Jeffery · English · 原定 Helen（与 Lakyn 重叠）', 'pending', ['Jeffery'], 'gray'),
    (3, '19:00', '21:00', 'Rebecca + Natasha', 'helen', ['Rebecca', 'Natasha'], 'green'),
    (4, '17:45', '19:00', 'Edward', 'helen', ['Edward'], 'green'),
    (4, '19:00', '20:30', 'Matthew', 'helen', ['Matthew'], 'green'),
    (5, '11:00', '13:00', 'VCE 中数快班', 'helen', None, 'purple'),
    (5, '14:00', '16:30', 'Joanna & Amelia · Y2 Maths + English', 'angela', ['Joanna', 'Amelia'], 'pink'),
    (5, '14:00', '15:00', 'Sunny + Shirley · Maths', 'vincent', ['Sunny', 'Shirley'], 'blue'),
    (5, '14:00', '15:30', 'Zachary · English', 'pending', ['Zachary'], 'gray'),
    (5, '15:00', '16:30', 'Sunny + Shirley · English', 'pending2', ['Sunny', 'Shirley'], 'gray'),
    (5, '15:30', '16:30', 'Zachary · Maths', 'vincent', ['Zachary'], 'blue'),
    (5, '14:00', '15:30', 'Bella · 高数', 'helen', ['Bella'], 'green'),
    (5, '14:30', '15:30', 'Cathy 妹妹 · 原定 Helen（与 Bella 高数重叠）', 'pending3', ['Cathy 妹妹'], 'gray'),
    (5, '15:30', '17:30', '中数34 H班', 'helen', None, 'purple'),
    (5, '17:30', '19:00', 'Benjamin', 'helen', ['Benjamin'], 'green'),
    (5, '19:00', '20:30', 'Carina', 'helen', ['Carina'], 'green'),
    (5, '19:00', '20:00', 'Atticus · Writing', 'angela', ['Atticus'], 'pink'),
    (6, '10:00', '11:00', 'Cathy · GM Unit 1/2', 'helen', ['Cathy'], 'green'),
    (6, '11:00', '13:00', 'VCE 高数', 'helen', None, 'purple'),
    (6, '13:00', '15:00', 'Cathy · VCE MM Unit 1/2', 'helen', ['Cathy'], 'green'),
    (6, '14:00', '15:00', 'Cathy 妹妹 · 原定 Helen（与 Cathy MM 重叠）', 'pending', ['Cathy 妹妹'], 'gray'),
    (6, '15:30', '17:30', '中数 unit 3/4 班', 'helen', None, 'purple'),
    (6, '16:30', '17:30', 'Yilia · 新加坡 · 原定 Helen（与中数 unit 3/4 班重叠）', 'pending', ['Yilia'], 'gray'),
    (6, '17:30', '19:00', 'Tecia + Angela + Zoey', 'helen', ['Tecia', 'Angela', 'Zoey'], 'green'),
    (6, '19:00', '20:30', 'David', 'helen', ['David'], 'green'),
    (6, '19:30', '20:30', 'Atticus · English GA', 'angela', ['Atticus'], 'pink'),
]

TEACHERS = {
    'helen': ('Helen', None),
    'vincent': ('Vincent', '0499000011'),
    'angela': ('Angela', '0499000012'),
    'pending': ('待定', '0499000021'),
    'pending2': ('待定 2', '0499000022'),
    'pending3': ('待定 3', '0499000023'),
}


def kept(name):
    folded = (name or '').casefold()
    return any(token in folded for token in KEEP)


def dates_for(weekday):
    day = TERM_START + timedelta(days=weekday)
    while day <= TERM_END:
        yield day
        day += timedelta(days=7)


def request_id(title, starts):
    return hashlib.sha256(f'term1-2027|{title}|{starts}'.encode()).hexdigest()[:32]


def lesson_names(c, lesson_id):
    return [row['name'] for row in c.execute(
        'SELECT s.name FROM lesson_students ls JOIN students s ON s.id=ls.student_id WHERE ls.lesson_id=? ORDER BY s.name',
        (lesson_id,))]


def find_student(c, name):
    rows = c.execute('SELECT id, name FROM students WHERE archived=0').fetchall()
    exact = [row for row in rows if row['name'].casefold() == name.casefold()]
    if exact:
        return exact[0]['id']
    if name.casefold() in KEEP:
        prefixed = [row for row in rows if row['name'].casefold().startswith(name.casefold())]
        if len(prefixed) == 1:
            return prefixed[0]['id']
    return None


def student_busy(c, student_id, start, end):
    return c.execute(
        """SELECT l.id FROM lesson_students ls
           JOIN lessons l ON l.id=ls.lesson_id
           JOIN students enrolled ON enrolled.id=ls.student_id
           WHERE enrolled.profile_id=(SELECT profile_id FROM students WHERE id=?)
             AND l.status!='cancelled' AND l.starts_at<? AND l.ends_at>?""",
        (student_id, end, start)).fetchone()


def ensure_roster_parent(c, password_hash):
    row = c.execute('SELECT id FROM users WHERE phone=?', (ROSTER_PHONE,)).fetchone()
    if row:
        return row['id']
    return c.execute(
        "INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",
        (ROSTER_PHONE, '课时名册', password_hash(secrets.token_urlsafe(24)))).lastrowid


def ensure_student(c, name, parent_id):
    found = find_student(c, name)
    if found:
        return found, False
    profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
    sid = c.execute(
        "INSERT INTO students(name,course,parent_id,balance,profile_id,billing_unit) VALUES(?,?,?,0,?,'lesson')",
        (name, '课时', parent_id, profile)).lastrowid
    return sid, True


def find_teacher(c, key):
    label, _phone = TEACHERS[key]
    rows = c.execute(
        '''SELECT t.id, u.name, u.id user_id,
                  EXISTS(SELECT 1 FROM organization_owners o WHERE o.user_id=u.id) owner
           FROM teachers t JOIN users u ON u.id=t.user_id
           WHERE u.active=1''').fetchall()
    if key == 'helen':
        matches = [row for row in rows if 'helen' in row['name'].casefold()]
        owners = [row for row in matches if row['owner']]
        return (owners or matches or [None])[0]
    exact = [row for row in rows if row['name'].casefold() == label.casefold()]
    return exact[0] if exact else None


def ensure_teacher(c, key, password_hash):
    found = find_teacher(c, key)
    if found:
        return found['id'], False
    label, phone = TEACHERS[key]
    if key == 'helen':
        owner = c.execute(
            '''SELECT u.id, u.name FROM organization_owners o
               JOIN users u ON u.id=o.user_id WHERE u.active=1 ORDER BY u.id LIMIT 1''').fetchone()
        if owner and 'helen' in owner['name'].casefold():
            return c.execute(
                "INSERT INTO teachers(user_id,subject,subjects) VALUES(?,?,'[\"数学\"]')",
                (owner['id'], '数学')).lastrowid, True
        phone = '0499000010'
    user = c.execute('SELECT id FROM users WHERE phone=?', (phone,)).fetchone()
    uid = user['id'] if user else c.execute(
        "INSERT INTO users(phone,name,password,role,active) VALUES(?,?,?,'parent',1)",
        (phone, label, password_hash(secrets.token_urlsafe(24)))).lastrowid
    existing = c.execute('SELECT id FROM teachers WHERE user_id=?', (uid,)).fetchone()
    if existing:
        return existing['id'], False
    return c.execute(
        "INSERT INTO teachers(user_id,subject,subjects) VALUES(?,?,'[\"数学\"]')",
        (uid, '数学')).lastrowid, True


def owner_actor(c):
    row = c.execute(
        '''SELECT u.id FROM organization_owners o JOIN users u ON u.id=o.user_id
           WHERE u.active=1 ORDER BY u.id LIMIT 1''').fetchone()
    if not row:
        raise SystemExit('没有可用的校长账号，已停止，未修改任何课程。')
    return {'id': row['id'], 'role': 'owner'}


def owned_ids():
    found = set()
    for weekday, start, _end, title, _teacher, _students, _color in SLOTS:
        for day in dates_for(weekday):
            found.add(request_id(title, f'{day.isoformat()}T{start}'))
    return found


def future_rows(c, now_stamp):
    return c.execute(
        """SELECT id, version, title, starts_at, ends_at, request_id FROM lessons
           WHERE status='scheduled' AND starts_at>=? ORDER BY starts_at, id""",
        (now_stamp,)).fetchall()


def occurrences(teacher_ids):
    planned = []
    for weekday, start, end, title, teacher, students, color in SLOTS:
        for day in dates_for(weekday):
            starts = f'{day.isoformat()}T{start}'
            ends = f'{day.isoformat()}T{end}'
            planned.append({
                'title': title, 'teacher': teacher, 'teacher_id': teacher_ids[teacher],
                'students': students or [], 'group': students is None, 'color': color,
                'starts': starts, 'ends': ends,
            })
    by_teacher = {}
    for item in planned:
        by_teacher.setdefault(item['teacher_id'], []).append(item)
    for items in by_teacher.values():
        items.sort(key=lambda item: item['starts'])
        for left, right in zip(items, items[1:]):
            if left['starts'] < right['ends'] and right['starts'] < left['ends']:
                raise SystemExit(f"课表内部冲突：{left['title']} {left['starts']} 与 {right['title']} {right['starts']}")
    return planned


def run(db_path, apply=False):
    os.environ['LESSON_DB'] = db_path
    os.environ['LESSON_DEMO'] = '0'
    import server
    server.DB_PATH = db_path
    if not apply:
        return _dry(db_path)
    server.initialize()
    return _apply(db_path)


def _connect_ro(db_path):
    import sqlite3
    c = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def _dry(db_path):
    import teaching
    c = _connect_ro(db_path)
    try:
        now_stamp = teaching.now_local().strftime('%Y-%m-%dT%H:%M')
        owned = owned_ids()
        cancel_lines, keep_lines = [], []
        for row in future_rows(c, now_stamp):
            names = lesson_names(c, row['id'])
            label = f"{row['id']}  {row['starts_at']}–{row['ends_at'][11:]}  {row['title']}  学生：{('、'.join(names) or '（无）')}"
            if row['request_id'] in owned:
                continue
            if any(kept(name) for name in names):
                keep_lines.append(label)
            else:
                cancel_lines.append(label)
        teacher_ids = {}
        for index, key in enumerate(TEACHERS, start=1):
            found = find_teacher(c, key)
            teacher_ids[key] = found['id'] if found else -index
        planned = occurrences(teacher_ids)
        create_lines, skip_lines, student_names = _classify(c, planned)
        new_teachers = [TEACHERS[key][0] for key, tid in teacher_ids.items() if tid < 0]
    finally:
        c.close()
    _print(db_path, False, cancel_lines, keep_lines, create_lines, skip_lines, student_names, new_teachers)
    return {'cancel': len(cancel_lines), 'keep': len(keep_lines), 'create': len(create_lines), 'skip': len(skip_lines)}


def _classify(c, planned):
    create_lines = []
    skip_lines = []
    needed = []
    for item in planned:
        existing = c.execute(
            "SELECT id FROM lessons WHERE request_id=? OR (teacher_id=? AND title=? AND starts_at=? AND status!='cancelled')",
            (request_id(item['title'], item['starts']), item['teacher_id'], item['title'], item['starts'])).fetchone()
        if existing:
            skip_lines.append(f"已有  {item['starts']}  {item['title']}")
            continue
        busy = None
        ids = []
        for name in item['students']:
            sid = find_student(c, name)
            if sid and name.casefold() in KEEP:
                hit = student_busy(c, sid, item['starts'], item['ends'])
                if hit:
                    busy = name
                    break
            if sid:
                ids.append(sid)
            else:
                needed.append(name)
        if busy:
            skip_lines.append(f"已有同时段  {item['starts']}  {item['title']}  （{busy}）")
            continue
        who = '小组课，无学生' if item['group'] else '、'.join(item['students'])
        create_lines.append(f"{item['starts']}–{item['ends'][11:]}  {item['title']}  老师键 {item['teacher']}  {who}")
    return create_lines, skip_lines, sorted(set(needed))


def _apply(db_path):
    import server
    import teaching
    import auditlog
    server.DB_PATH = db_path
    c = server.connect()
    created_students = []
    new_teachers = []
    cancel_lines = []
    keep_lines = []
    create_lines = []
    skip_lines = []
    try:
        c.execute('BEGIN IMMEDIATE')
        actor = owner_actor(c)
        auditlog.begin(c)
        now_stamp = teaching.now_local().strftime('%Y-%m-%dT%H:%M')
        owned = owned_ids()
        teacher_ids = {}
        for key in TEACHERS:
            teacher_id, made = ensure_teacher(c, key, server.password_hash)
            teacher_ids[key] = teacher_id
            if made:
                new_teachers.append(TEACHERS[key][0])
        parent_id = ensure_roster_parent(c, server.password_hash)
        for row in future_rows(c, now_stamp):
            names = lesson_names(c, row['id'])
            label = f"{row['id']}  {row['starts_at']}–{row['ends_at'][11:]}  {row['title']}  学生：{('、'.join(names) or '（无）')}"
            if row['request_id'] in owned:
                continue
            if any(kept(name) for name in names):
                keep_lines.append(label)
                continue
            teaching.cancel_lesson(c, actor, {
                'lesson_id': row['id'], 'version': row['version'], 'scope': 'single',
                'reason': CANCEL_REASON, 'waive_leave': True,
            }, server.text_value)
            cancel_lines.append(label)
        planned = occurrences(teacher_ids)
        for item in planned:
            key = request_id(item['title'], item['starts'])
            existing = c.execute(
                "SELECT id FROM lessons WHERE request_id=? OR (teacher_id=? AND title=? AND starts_at=? AND status!='cancelled')",
                (key, item['teacher_id'], item['title'], item['starts'])).fetchone()
            if existing:
                skip_lines.append(f"已有  {item['starts']}  {item['title']}")
                continue
            ids = []
            busy = None
            for name in item['students']:
                sid = find_student(c, name)
                if sid and name.casefold() in KEEP and student_busy(c, sid, item['starts'], item['ends']):
                    busy = name
                    break
                if not sid:
                    sid, made = ensure_student(c, name, parent_id)
                    if made and name not in created_students:
                        created_students.append(name)
                ids.append(sid)
            if busy:
                skip_lines.append(f"已有同时段  {item['starts']}  {item['title']}  （{busy}）")
                continue
            try:
                teaching.save_lesson(c, actor, {
                    'request_id': key, 'title': item['title'], 'teacher_id': item['teacher_id'],
                    'starts_at': item['starts'], 'ends_at': item['ends'], 'amount': 1,
                    'student_ids': ids, 'allow_empty': item['group'], 'color': item['color'],
                    'location': '',
                }, server.units, server.text_value)
            except ValueError as exc:
                raise ValueError(f"{item['starts']} {item['title']}：{exc}") from exc
            who = '小组课，无学生' if item['group'] else '、'.join(item['students'])
            create_lines.append(f"{item['starts']}–{item['ends'][11:]}  {item['title']}  老师键 {item['teacher']}  {who}")
        auditlog.hint(c, '2027 第一学期课表：取消未来排课（保留 Atticus、Benjamin，不扣课）并排入周课')
        auditlog.finish(c, actor)
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    _print(db_path, True, cancel_lines, keep_lines, create_lines, skip_lines, created_students, new_teachers)
    return {'cancel': len(cancel_lines), 'keep': len(keep_lines), 'create': len(create_lines), 'skip': len(skip_lines)}


def _print(db_path, apply, cancel_lines, keep_lines, create_lines, skip_lines, created_students, new_teachers):
    mode = 'APPLY' if apply else 'DRY-RUN'
    print(f'{mode}  database={db_path}')
    print(f'取消 {len(cancel_lines)} 节未来课程（不扣课）')
    for line in cancel_lines:
        print('  取消  ' + line)
    print(f'保留 {len(keep_lines)} 节（学生名含 Atticus 或 Benjamin）')
    for line in keep_lines:
        print('  保留  ' + line)
    print(f'新建 {len(create_lines)} 节，跳过 {len(skip_lines)} 节')
    for line in create_lines:
        print('  新建  ' + line)
    for line in skip_lines:
        print('  跳过  ' + line)
    print('新建学生：' + ('、'.join(created_students) if created_students else '无'))
    print('新建老师：' + ('、'.join(new_teachers) if new_teachers else '无'))
    print(f'合计 cancel={len(cancel_lines)} keep={len(keep_lines)} create={len(create_lines)} skip={len(skip_lines)}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Term 1 2027 timetable. Dry-run unless --apply.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', '/var/data/lessons.sqlite3'))
    parser.add_argument('--dry-run', action='store_true', help='Print the changes and write nothing. This is the default.')
    parser.add_argument('--apply', action='store_true', help='Cancel and create the lessons.')
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        raise SystemExit('请只选 --dry-run 或 --apply 其中一个。')
    run(args.db, apply=args.apply)


if __name__ == '__main__':
    main()
