"""课时簿 — standalone, standard-library application. See README.md."""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import time
from decimal import Decimal, InvalidOperation
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import teaching
import profiles
import record_edits
import credit_batches
import accounting
import deletion
import payroll
import pricing
import auditlog
import switches
import finance
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
DB_PATH = os.environ.get('LESSON_DB', str(ROOT / 'data' / 'lessons.sqlite3'))
DEMO = os.environ.get('LESSON_DEMO') == '1'

def demo_seed_allowed():
    """Sample students are only for a local demo file, never the production disk."""
    if os.environ.get('LESSON_DEMO') != '1':
        return False
    db = os.path.realpath(os.environ.get('LESSON_DB', DB_PATH))
    if db == '/var/data/lessons.sqlite3' or db.startswith('/var/data/'):
        return False
    return True
SECURE = os.environ.get('LESSON_SECURE_COOKIE') == '1'
ORG_NAME = 'HZ Education Melbourne'
DB_ERROR = None
NOT_FOUND_PAGE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>页面不存在</title><link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png"><link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"><link rel="stylesheet" href="/style.css"></head><body><main class="error-page"><p class="eyebrow">HZ Education Melbourne</p><h1>找不到这个页面</h1><p>这个地址没有对应的页面。请回到课时管理首页，或联系老师帮忙。</p><p><a class="btn primary" href="/">返回首页</a></p></main></body></html>'''

def contact_details():
    email = os.environ.get('LESSON_CONTACT_EMAIL', 'helenzeducation@gmail.com').strip()[:80]
    return {'email': email or 'helenzeducation@gmail.com'}

def connect():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return salt + ':' + digest

def phone_value(raw):
    phone = re.sub(r'[\s()\-]', '', str(raw or ''))
    if not re.fullmatch(r'\+?[0-9]{7,15}', phone):
        raise ValueError('请输入完整手机号，可包含国家区号。')
    return phone

def _lesson_count(raw_units):
    value = int(raw_units or 0)
    if value % 100 == 0:
        return str(value // 100)
    return f'{value / 100:.2f}'.rstrip('0').rstrip('.')


def _backdated_gift_units(data):
    """Gift lessons still unused on a back-dated pack.

    还剩赠送几节 wins when the form sent it. An older page, or a gift typed in
    赠送课时 before that box was hidden, only sends gift_amount. Missing must
    not be turned into zero, or the gift she entered is thrown away.
    """
    if 'gift_remaining' in data and str(data.get('gift_remaining')).strip() != '':
        return _units_or_zero(data.get('gift_remaining'), '还剩赠送几节')
    return credit_batches.zero_units(data.get('gift_amount', 0), units)


def _units_or_zero(raw, label):
    text = str(raw if raw is not None else '').strip()
    if text in ('',):
        raise ValueError(f'请填写{label}。')
    if text in ('0', '0.0', '0.00'):
        return 0
    try:
        return units(raw)
    except ValueError:
        raise ValueError(f'{label}必须是 0 到 10000 之间的数。')


def _consume_prior_hours(c, user, student_id, credit_ledger_id, day, used, request_id):
    """Paid lessons already taught. Gift lessons are not reduced here. No lesson row and no teacher pay."""
    batch = c.execute('SELECT id, paid_left FROM credit_batches WHERE ledger_id=?', (credit_ledger_id,)).fetchone()
    if not batch:
        raise ValueError('没有找到这次补录的课时包。')
    if used > int(batch['paid_left'] or 0):
        raise ValueError('已用的付费课时多于总节数。')
    use_id = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
        VALUES(?,0,'lesson',?,?,?,?)''', (
        student_id, day, '补录已用课时，没有对应课程', user['id'], request_id + '-used')).lastrowid
    credit_batches.move(c, use_id, batch['id'], -used, 0)
    credit_batches.finish(c, use_id)


def units(raw):
    try:
        n = Decimal(str(raw))
        if not n.is_finite() or n <= 0 or n > 10000 or n * 100 != (n * 100).to_integral_value():
            raise ValueError()
        return int(n * 100)
    except (InvalidOperation, ValueError):
        raise ValueError('数量必须大于 0，最多保留两位小数，且不超过 10000。')

def text_value(raw, label, maximum=100):
    value = str(raw or '').strip()
    if not value or len(value) > maximum:
        raise ValueError(f'{label}不能为空，且不能超过 {maximum} 个字。')
    return value

def initialize():
    """Open the lesson database and add any missing tables.

    A malformed file is logged and left untouched. Startup continues so the
    process can answer /health instead of crash-looping on the same executescript.
    """
    global DB_ERROR
    DB_ERROR = None
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    try:
        with connect() as c:
            try:
                check = c.execute('PRAGMA integrity_check').fetchone()
            except sqlite3.DatabaseError as exc:
                raise sqlite3.DatabaseError(f'integrity_check could not read {DB_PATH}: {exc}') from exc
            if not check or check[0] != 'ok':
                raise sqlite3.DatabaseError(f'integrity_check failed for {DB_PATH}: {check[0] if check else "no result"}')
            mode = c.execute('PRAGMA journal_mode').fetchone()[0]
            if str(mode).lower() != 'wal':
                switched = c.execute('PRAGMA journal_mode=WAL').fetchone()[0]
                if str(switched).lower() != 'wal':
                    print(f'lesson database left in journal_mode={switched}', file=sys.stderr, flush=True)
            _create_base_tables(c)
    except sqlite3.DatabaseError as exc:
        DB_ERROR = f'{DB_PATH} is malformed or unreadable ({exc}). Schema changes were not applied. Restore the backup before using the site.'
        print(DB_ERROR, file=sys.stderr, flush=True)


def _create_base_tables(c):
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','parent'))
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, course TEXT NOT NULL,
            parent_id INTEGER NOT NULL REFERENCES users(id),
            balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0)
        );
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id),
            delta INTEGER NOT NULL, kind TEXT NOT NULL, lesson_date TEXT NOT NULL,
            note TEXT NOT NULL, actor_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            request_id TEXT UNIQUE NOT NULL, reversal_of INTEGER UNIQUE REFERENCES ledger(id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attempts (
            key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ledger_student ON ledger(student_id,id);
        ''')
        if demo_seed_allowed() and not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            c.execute('INSERT INTO users(id,phone,name,password,role) VALUES(1,?,?,?,?)', ('0400000000', 'Helen 老师', password_hash('TeacherDemo2026!'), 'admin'))
            c.execute('INSERT INTO users(id,phone,name,password,role) VALUES(2,?,?,?,?)', ('0400000001', '陈同学家长', password_hash('ParentDemo2026!'), 'parent'))
            c.execute('INSERT INTO users(id,phone,name,password,role) VALUES(3,?,?,?,?)', ('0400000002', '其他学生家长', password_hash(secrets.token_urlsafe(24)), 'parent'))
            for sid, name, course, pid, total, used in [(1,'陈一诺','数学 · 一对一',2,2000,650),(2,'陈子墨','数学 · 小班课',2,1200,300),(3,'王星然','数学 · 一对一',3,1000,800),(4,'李沐阳','数学 · 小班课',3,2000,400)]:
                c.execute('INSERT INTO students(id,name,course,parent_id,balance) VALUES(?,?,?,?,?)',(sid,name,course,pid,total-used))
                c.execute('INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,?,?,?,1,?)',(sid,total,'credit','2026-09-01','示例：购入课时',secrets.token_hex(16)))
                c.execute('INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,?,?,?,1,?)',(sid,-used,'lesson','2026-09-20','示例：历史上课汇总',secrets.token_hex(16)))
        c.execute('CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        teaching.schema(c)
        if demo_seed_allowed() and not c.execute("SELECT 1 FROM app_meta WHERE key='teaching_demo_v1'").fetchone():
            demo_teacher=c.execute("SELECT id FROM users WHERE phone='0400000003'").fetchone()
            if not demo_teacher:
                uid=c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",('0400000003','Emma 老师',password_hash('TutorDemo2026!'))).lastrowid
                tid=c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)',(uid,'数学')).lastrowid
                admin=c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
                student=c.execute('SELECT id FROM students ORDER BY id LIMIT 1').fetchone()
                if admin and student:
                    for offset,hour in [(-1,16),(1,17)]:
                        day=(teaching.now_local().date()+dt.timedelta(days=offset)).isoformat()
                        lid=c.execute('INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id) VALUES(?,?,?,?,?,?,?,?)',(tid,'数学 · 一对一',f'{day}T{hour}:00',f'{day}T{hour+1}:00',100,'教室 1',admin['id'],secrets.token_hex(16))).lastrowid
                        c.execute('INSERT INTO lesson_students VALUES(?,?)',(lid,student['id']))
            c.execute("INSERT INTO app_meta VALUES('teaching_demo_v1','1')")
        accounting.schema(c, demo_seed_allowed())
        profiles.schema(c)
        deletion.schema(c)
        credit_batches.schema(c)
        record_edits.schema(c)
        if demo_seed_allowed() and not c.execute("SELECT 1 FROM app_meta WHERE key='owner_demo_v1'").fetchone():
            if not c.execute("SELECT 1 FROM users WHERE phone='0400000004'").fetchone():
                uid=c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",('0400000004','Amy 管理员',password_hash('AdminDemo2026!'))).lastrowid
                c.execute('INSERT INTO teachers(user_id) VALUES(?)',(uid,))
            c.execute("INSERT INTO app_meta VALUES('owner_demo_v1','1')")
        payroll.schema(c)
        pricing.schema(c)
        auditlog.schema(c)
        switches.schema(c)
        if demo_seed_allowed():
            seed_portal_cast(c)
        import vouchers
        vouchers.schema(c)
        import timeline
        timeline.schema(c)
        try:
            import atticus_maths
            atticus_maths.run(c, DB_PATH)
            atticus_maths.run_prices(c, DB_PATH)
            import merge_named_profiles
            merge_named_profiles.run(c, DB_PATH)
            import delete_test_student
            delete_test_student.run(c, DB_PATH)
            import merge_confirmed_pairs
            merge_confirmed_pairs.run(c, DB_PATH)
        except Exception:
            logging.exception('Atticus maths correction failed')
        try:
            deletion.report_roster_once(c)
        except Exception:
            logging.exception('roster report failed')

def seed_portal_cast(c):
    """Demo teachers and students from the approved mockups. Additive and skipped once recorded."""
    if c.execute("SELECT 1 FROM app_meta WHERE key='portal_cast_v1'").fetchone():
        return
    helen = c.execute("SELECT id FROM users WHERE phone='0400000000'").fetchone()
    if not helen:
        return
    def teacher(phone, name):
        row = c.execute('SELECT id FROM users WHERE phone=?', (phone,)).fetchone()
        uid = row['id'] if row else c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')", (phone, name, password_hash('TutorDemo2026!'))).lastrowid
        existing = c.execute('SELECT id FROM teachers WHERE user_id=?', (uid,)).fetchone()
        if existing:
            return existing['id']
        return c.execute("INSERT INTO teachers(user_id,subject,subjects) VALUES(?,?,'[\"数学\"]')", (uid, '数学')).lastrowid
    helen_teacher = c.execute('SELECT id FROM teachers WHERE user_id=?', (helen['id'],)).fetchone()
    cast = {
        'Helen': helen_teacher['id'] if helen_teacher else c.execute("INSERT INTO teachers(user_id,subject,subjects) VALUES(?,?,'[\"数学\"]')", (helen['id'], '数学')).lastrowid,
        'Vincent': teacher('0400000011', 'Vincent'),
        'Angela': teacher('0400000012', 'Angela'),
        'Kelsey': teacher('0400000013', 'Kelsey'),
        'Ethan': teacher('0400000014', 'Ethan'),
        'Christina': teacher('0400000015', 'Christina'),
    }
    for name, tid in cast.items():
        if c.execute('SELECT 1 FROM pay_rules WHERE teacher_id=?', (tid,)).fetchone():
            continue
        folded = name.casefold()
        for fragment, kind, bp, floor in payroll.SEED_RULES:
            if fragment in folded:
                c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,hourly_floor_cents,hourly_rate_cents,effective_from,note,created_by)
                    VALUES(?,?,?,?,NULL,'2000-01-01','初始规则',?)''', (tid, kind, bp, floor, helen['id']))
                if fragment == 'vincent' and not c.execute('SELECT 1 FROM partner_share_rules WHERE teacher_id=?', (tid,)).fetchone():
                    c.execute('''INSERT INTO partner_share_rules(teacher_id,percent_bp,effective_from,note,created_by)
                        VALUES(?,3000,'2000-01-01','新学生课酬减去共同成本后的分成',?)''', (tid, helen['id']))
    parent = c.execute("SELECT id FROM users WHERE phone='0400000001'").fetchone()
    if not parent:
        return
    def student(name, grade, level, balance):
        row = c.execute('SELECT id FROM students WHERE name=?', (name,)).fetchone()
        if row:
            c.execute('UPDATE students SET billing_unit=?,grade=?,level_code=?,level_year=? WHERE id=?', ('lesson', grade, level, 2026, row['id']))
            return row['id']
        profile = c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,billing_unit,grade,level_code,level_year)
            VALUES(?,?,?,?,?,'lesson',?,?,?)''', (name, '数学', parent['id'], profile, balance, grade, level, 2026)).lastrowid
        if balance:
            c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'credit',?,'演示余额',?,?)",
                (sid, balance, '2026-11-01', helen['id'], secrets.token_hex(16)))
            c.execute("INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,legacy) VALUES(?,?,0,?,0,'',1)", (sid, balance, balance))
        return sid
    kids = {
        '陈一诺': student('陈一诺', 'Y6', 'Y6', 200),
        '赵恩希': student('赵恩希', 'Y6', 'Y6', 300),
        '王星然': student('王星然', 'Y4', 'Y4', 0),
        '周可': student('周可', 'Y11', 'Y11', 1200),
        '李沐阳': student('李沐阳', 'Y12', 'Y12', 800),
        '陈子墨': student('陈子墨', 'Y3', 'Y3', 1500),
        '林晓': student('林晓', 'Y8', 'Y8', 600),
    }
    today = teaching.now_local().date()
    monday = today - dt.timedelta(days=today.weekday())
    def at(offset, start, end):
        day = monday + dt.timedelta(days=offset)
        return f'{day.isoformat()}T{start}', f'{day.isoformat()}T{end}', day.isoformat()
    plan = [
        ('Angela', ['陈一诺'], 0, '16:00', '17:00', 'scheduled', '1:1'),
        ('Kelsey', ['王星然', '陈子墨'], 0, '16:00', '17:30', 'scheduled', '1:2'),
        ('Vincent', ['周可'], 0, '18:00', '19:00', 'scheduled', '1:1'),
        ('Angela', ['赵恩希'], today.weekday(), '15:00', '16:00', 'completed', '1:1'),
        ('Angela', ['陈一诺'], today.weekday(), '16:00', '17:00', 'scheduled', '1:1'),
        ('Kelsey', ['王星然'], today.weekday(), '17:00', '18:30', 'scheduled', '1:2'),
        ('Helen', ['李沐阳'], today.weekday(), '18:30', '20:00', 'scheduled', '1:1'),
        ('Ethan', ['陈子墨'], 2, '15:30', '17:00', 'scheduled', '1:1'),
        ('Vincent', ['周可'], 3, '16:00', '17:00', 'scheduled', '1:1'),
        ('Christina', ['林晓'], 4, '17:00', '18:00', 'scheduled', '1:1'),
        ('Helen', ['李沐阳'], 5, '10:00', '11:30', 'scheduled', '1:1'),
        ('Christina', ['林晓'], 6, '09:00', '10:00', 'scheduled', '1:1'),
        ('Helen', ['李沐阳', '林晓', '周可'], 1, '11:00', '12:30', 'scheduled', '小班课'),
        ('Angela', ['陈一诺'], 2, '14:00', '15:00', 'scheduled', '试听 · 一对一'),
    ]
    for who, names, offset, start, end, status, kind in plan:
        starts, ends, day = at(offset, start, end)
        if c.execute('SELECT 1 FROM lessons WHERE teacher_id=? AND starts_at=? AND title=?', (cast[who], starts, f'数学 · {kind}')).fetchone():
            continue
        lid = c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?,?,?,?,100,'教室',?,?,?)''', (cast[who], f'数学 · {kind}', starts, ends, status, helen['id'], secrets.token_hex(16))).lastrowid
        for name in names:
            c.execute('INSERT INTO lesson_students VALUES(?,?)', (lid, kids[name]))
        if status == 'completed':
            sid = kids[names[0]]
            ledger = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'已上了',?,?)",
                (sid, -100, day, helen['id'], secrets.token_hex(16))).lastrowid
            c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
                VALUES(?,?,100,'分数运算','练习册第 3 页','今天的课已上完。',?,?)''', (lid, sid, ledger, helen['id']))
            c.execute('UPDATE students SET balance=MAX(balance-100,0) WHERE id=?', (sid,))
    samples = [
        ('陈一诺', 170000, 'bank', 1),
        ('王星然', 120000, 'cash', 0),
        ('赵恩希', 170000, 'wechat', 1),
    ]
    kelsey_user = c.execute('SELECT user_id FROM teachers WHERE id=?', (cast['Kelsey'],)).fetchone()['user_id']
    for name, cents, method, handed in samples:
        sid = kids[name]
        ledger = c.execute("SELECT id FROM ledger WHERE student_id=? AND kind='credit' ORDER BY id LIMIT 1", (sid,)).fetchone()
        if not ledger or c.execute('SELECT 1 FROM cash_entries WHERE ledger_id=?', (ledger['id'],)).fetchone():
            continue
        recv = helen['id'] if handed else kelsey_user
        c.execute('''INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by,received_by,handed_over)
            VALUES(?,?,?,?,?,?,?)''', (ledger['id'], cents, method, '', helen['id'], recv, handed))
    c.execute("INSERT INTO audit_log(actor_id,action,summary,ops_json) VALUES(?,?,'演示：登记陈一诺的课时包','[]')", (helen['id'], 'purchase'))
    teaching.ensure_catalogs(c)
    c.execute("INSERT INTO app_meta VALUES('portal_cast_v1','1')")

def build_state(c, user):
    """Owner, staff and parent payload for GET /api/state.

    One bad course or teacher record is logged and skipped. It does not
    take down the rest of the page.
    """
    condition = ''
    params = ()
    if user['role']=='teacher':
        condition=' WHERE EXISTS (SELECT 1 FROM lesson_students ls JOIN lessons tl ON ls.lesson_id=tl.id WHERE ls.student_id=s.id AND tl.teacher_id=?)'
        params=(user['teacher_id'],)
    elif user['role']=='parent':
        profiles.schema(c)
        condition=' WHERE '+profiles.linked_clause('s')
        params=profiles.linked_params(user['id'])
    students = [dict(x) for x in c.execute('''SELECT s.*,u.name parent_name,u.phone,u.contact_phone,
        ct.name course_type_name, sb.name subject_name
        FROM students s JOIN users u ON s.parent_id=u.id
        LEFT JOIN course_types ct ON ct.id=s.course_type_id
        LEFT JOIN subjects sb ON sb.id=s.subject_id'''+condition+' ORDER BY s.id',params)]
    profiles.ensure_enrolment_columns(c)
    extras = {row['id']: dict(row) for row in c.execute('SELECT * FROM student_profiles')}
    for person in students:
        extra = extras.get(person.get('profile_id')) or {}
        for key, value in extra.items():
            if key != 'id':
                person[key] = value
        pricing.annotate(person)
    if user['role'] in ('owner','admin'):
        profiles.schema(c)
        for person in students:
            person['parents']=profiles.parents_for(c, person.get('profile_id'), person.get('parent_id'))
    if user['role'] not in ('owner','admin'):
        for s in students: s.pop('notes',None)
    credit_batches.enrich(c,students)
    for person in students:
        paid = person.get('paid_balance')
        person['needs_renewal'] = (paid if paid is not None else person.get('balance') or 0) < 300
    if user['role'] == 'owner':
        for person in students:
            try:
                offer=pricing.legacy_price(c, person)
            except Exception:
                logging.exception('price label failed for student %s', person.get('id'))
                offer={'legacy': False, 'legacy_subjects': [], 'list_hourly_cents': None, 'custom_hourly_cents': None}
            person['legacy']=offer['legacy']
            person['legacy_subjects']=offer['legacy_subjects']
            person['list_hourly_cents']=offer['list_hourly_cents']
            person['custom_hourly_cents']=offer['custom_hourly_cents']
    if user['role'] == 'teacher':
        for person in students:
            for key in ('parent_email', 'phone', 'contact_phone', 'parent_name', 'legacy', 'legacy_subjects', 'list_hourly_cents', 'custom_hourly_cents', 'balance', 'paid_balance', 'gift_balance', 'credit_batches', 'health_notes'):
                person.pop(key, None)
    if user['role'] == 'parent':
        for person in students:
            for key in ('legacy', 'legacy_subjects', 'list_hourly_cents', 'custom_hourly_cents', 'phone', 'contact_phone'):
                person.pop(key, None)
            for batch in person.get('credit_batches') or []:
                batch.pop('unit_fees', None)
    covered={row.get('profile_id') for row in students}
    shells=profiles.course_shells(c, students)+profiles.profiles_without_courses(c, covered, user)
    staff=user['role'] in ('owner','admin')
    archived_students=[s for s in students if s['archived'] and not s.get('voided')] if user['role']=='owner' else []
    voided_students=[s for s in students if s['archived'] and s.get('voided')] if staff else []
    withdrawn_ids=set()
    if staff:
        profiles.ensure_enrolment_columns(c)
        withdrawn_ids={row['id'] for row in c.execute("SELECT id FROM student_profiles WHERE status='withdrawn'")}
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_audit'").fetchone():
            for row in c.execute('''SELECT profile_id, action FROM (
                SELECT s.profile_id, a.action, ROW_NUMBER() OVER (PARTITION BY s.profile_id ORDER BY a.id DESC) n
                FROM profile_audit a JOIN students s ON s.id=a.student_id
                WHERE s.profile_id IS NOT NULL AND a.action IN ('archived','reinstated')
            ) WHERE n=1 AND action='archived' '''):
                withdrawn_ids.add(row['profile_id'])
    withdrawn_students=[]
    for person in students:
        if person.get('profile_id') in withdrawn_ids:
            card=dict(person)
            card['withdrawn']=True
            withdrawn_students.append(card)
    if not staff:
        withdrawn_students=[]
    students=[s for s in students if not s['archived']]+shells
    left_students=[]
    if staff:
        left_ids={row['id'] for row in c.execute("SELECT id FROM student_profiles WHERE TRIM(COALESCE(left_on,''))!=''")}
        left_students=[person for person in students if person.get('profile_id') in left_ids]
        students=[person for person in students if person.get('profile_id') not in left_ids]
        left_students+=profiles.profiles_without_courses(c, covered, user, include_left=True)
    if user['role']=='owner':
        deletion.annotate_blockers(c, [person for person in students if not person.get('no_course')])
        deletion.annotate_erase(c, students+archived_students+voided_students+withdrawn_students+left_students)
    if user['role']!='owner':
        for person in students+archived_students+voided_students+withdrawn_students+left_students:
            person.pop('helen_original', None)
            person.pop('origin_override', None)
            person.pop('created_on', None)
    entry_condition=condition
    if user['role']=='teacher':
        entry_condition=' WHERE EXISTS (SELECT 1 FROM lesson_reports lr JOIN lessons tl ON lr.lesson_id=tl.id WHERE lr.ledger_id=l.id AND tl.teacher_id=?)'
    entries = [dict(x) for x in c.execute('''SELECT l.*,s.name student_name,s.course,sb.name subject_name,s.billing_unit,u.name actor_name,cash.cash_delta,cash.payment_method,cash.reference,pack.total_cents pack_cents,r.id reversed_by,
        CASE WHEN EXISTS (SELECT 1 FROM vouchers v WHERE v.status='void' AND (v.ledger_id=l.id OR v.reversal_ledger_id=l.id)) THEN 1 ELSE 0 END voided_payment,
        (SELECT v.id FROM vouchers v WHERE v.status='void' AND v.ledger_id=l.id LIMIT 1) void_voucher_id
        FROM ledger l JOIN students s ON l.student_id=s.id JOIN users u ON l.actor_id=u.id LEFT JOIN subjects sb ON sb.id=s.subject_id LEFT JOIN ledger r ON r.reversal_of=l.id LEFT JOIN cash_entries cash ON cash.ledger_id=l.id LEFT JOIN credit_batches pack ON pack.ledger_id=l.id'''+entry_condition+' ORDER BY l.lesson_date DESC, l.created_at DESC, l.id DESC',params)]
    if user['role']=='teacher':
        entries=[e for e in entries if e['kind']=='lesson']
        for e in entries:
            for key in ('cash_delta','payment_method','reference','pack_cents','request_id','reversal_of'):
                e.pop(key, None)
    if user['role']=='parent':
        entries=[e for e in entries if e['kind'] in ('credit','refund') and not e['reversed_by'] and not e.get('voided_payment')]
        for e in entries:
            for key in ('request_id','reversal_of','version'):e.pop(key,None)
    known = teaching.subject_names(c)
    for person in students+archived_students+voided_students+withdrawn_students+left_students:
        person['subject_name']=teaching.canonical_subject(person.get('subject_name') or '', known)
    pricing.apply_rate_visibility(c, user, students+archived_students+voided_students+withdrawn_students+left_students)
    import timeline
    try:
        schedule = teaching.state_for(c, user)
    except Exception:
        logging.exception('schedule state failed')
        schedule = {'lessons': [], 'teachers': [], 'course_types': [], 'subjects': [], 'recurrence_warnings': [], 'schedule_options': [], 'timezone': teaching.TIMEZONE, 'today': teaching.now_local().date().isoformat(), 'now': teaching.now_local().strftime('%Y-%m-%dT%H:%M')}
    try:
        events = timeline.for_staff(c) if staff else []
    except Exception:
        logging.exception('profile events failed')
        events = []
    try:
        admins = accounting.administrators(c, user) if user['role']=='owner' else []
    except Exception:
        logging.exception('administrator list failed')
        admins = []
    return {'user':{'id':user['id'],'name':teaching.display_person(user['name']),'role':user['role'],'phone':user['phone'],'teacher_id':user['teacher_id']},'csrf':user['csrf'],'students':students,'archived_students':archived_students,'voided_students':voided_students,'withdrawn_students':withdrawn_students,'left_students':left_students,'profile_events':events,'entries':entries,'demo':DEMO,'organization':ORG_NAME,**schedule,'administrators':admins}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Never log request bodies, passwords, or sessions.
        pass

    def client_proto(self):
        return (self.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip().lower()

    def redirect_to_https(self):
        # Only when a proxy says the visitor used http. Direct health checks have no forwarded proto.
        if self.client_proto() != 'http' or self.path.split('?')[0] == '/health':
            return False
        host = (self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or '').split(',')[0].strip()
        if not host or any(ch in host for ch in ' \r\n'):
            return False
        self.send_response(301)
        self.send_header('Location', 'https://'+host+self.path)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        return True

    def response(self, status, value, cookie=None, content_type='application/json; charset=utf-8', extra=None):
        data = json.dumps(value, ensure_ascii=False).encode() if isinstance(value,(dict,list)) else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Robots-Tag', 'noindex, nofollow')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
        if self.client_proto() == 'https':
            self.send_header('Strict-Transport-Security', 'max-age=15552000')
        if extra:
            for key, item in extra:
                self.send_header(key, item)
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(data)

    def current(self, c):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie',''))
            token = cookies['session'].value if 'session' in cookies else ''
        except Exception:
            return None
        return c.execute("SELECT u.id,u.name,u.phone,u.password,CASE WHEN o.user_id IS NOT NULL THEN 'owner' WHEN u.role='admin' THEN 'admin' WHEN t.id IS NOT NULL THEN 'teacher' ELSE 'parent' END role,t.id teacher_id,s.csrf,s.token_hash FROM sessions s JOIN users u ON s.user_id=u.id LEFT JOIN teachers t ON t.user_id=u.id LEFT JOIN organization_owners o ON o.user_id=u.id WHERE s.token_hash=? AND s.expires>? AND u.active=1",(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()

    def do_GET(self):
        if self.redirect_to_https():
            return
        path = self.path.split('?')[0]
        if path in ('/api/reconciliation', '/api/reconciliation.csv'):
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    result=accounting.reconciliation(c,user,params.get('period',['day'])[0],params.get('date',[teaching.now_local().date().isoformat()])[0])
                    if path.endswith('.csv'):
                        filename=f'accounting-{result["start"]}-to-{result["end"]}.csv'
                        return self.response(200,payroll.accounting_csv(result),content_type='text/csv; charset=utf-8',extra=[('Content-Disposition',f'attachment; filename="{filename}"')])
                    return self.response(200,result)
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/entries/history':
            with connect() as c:
                user=self.current(c)
                if not user or user['role']!='owner':return self.response(403,{'error':'仅老板可查看修改记录。'})
                try:ident=int(parse_qs(urlsplit(self.path).query).get('id',['0'])[0])
                except ValueError:return self.response(400,{'error':'单据编号无效。'})
                rows=[dict(r) for r in c.execute('SELECT e.*,u.name actor_name FROM ledger_edits e JOIN users u ON u.id=e.actor_id WHERE e.ledger_id=? ORDER BY e.id DESC',(ident,))]
                return self.response(200,{'edits':rows})
        if path in ('/api/share', '/api/share.csv'):
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    import dividend
                    params=parse_qs(urlsplit(self.path).query)
                    result=dividend.report(c,user,params.get('period',['month'])[0],params.get('date',[None])[0],params.get('start',[None])[0],params.get('end',[None])[0])
                    if path.endswith('.csv'):
                        return self.response(200, dividend.csv_bytes(result), content_type='text/csv; charset=utf-8',
                            extra=[('Content-Disposition', f'attachment; filename="partner-share-{result["start"]}-to-{result["end"]}.csv"')])
                    return self.response(200, result)
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path in ('/api/pay', '/api/pay.csv'):
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    result=payroll.report(c,user,params.get('period',['week'])[0],params.get('date',[None])[0],params.get('start',[None])[0],params.get('end',[None])[0])
                    if path.endswith('.csv'):
                        raw=params.get('teacher_id',[''])[0]
                        blob=payroll.csv_bytes(result, payroll.export_id_for(user, result, raw))
                        filename=f'teacher-pay-{result["start"]}-to-{result["end"]}.csv'
                        return self.response(200,blob,content_type='text/csv; charset=utf-8',extra=[('Content-Disposition',f'attachment; filename="{filename}"')])
                    return self.response(200,result)
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
                except Exception:
                    logging.exception('GET /api/pay failed')
                    return self.response(500,{'error':'工资暂时算不出来，请稍后重试。'})
        if path == '/api/today':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    return self.response(200, finance.today_board(c, user, params.get('date',[None])[0]))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path in ('/api/prices', '/api/prices/presets'):
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    if path == '/api/prices/presets':
                        params=parse_qs(urlsplit(self.path).query)
                        return self.response(200, pricing.presets(c, user, params.get('student_id',[None])[0], params.get('level',[None])[0], params.get('course_type_id',[None])[0], params.get('date',[None])[0], params.get('subject_id',[None])[0]))
                    return self.response(200, pricing.list_prices(c, user))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/receivables':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    import receivables
                    return self.response(200, {'rows': receivables.outstanding(c), 'owed_cents': receivables.total_owed(c)})
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/reports/monthly':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    return self.response(200, finance.monthly(c, user, params.get('month', [''])[0]))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/expenses':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    import expenses
                    params=parse_qs(urlsplit(self.path).query)
                    return self.response(200, expenses.page(c, user, params.get('month', [''])[0]))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path in ('/api/finance', '/api/finance.xlsx', '/api/finance.pdf'):
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    result=finance.statement(c,user,params.get('period',['month'])[0],params.get('date',[None])[0],params.get('start',[None])[0],params.get('end',[None])[0])
                    if path.endswith('.xlsx') or path.endswith('.pdf'):
                        import exports
                        blob=exports.finance_xlsx(result) if path.endswith('.xlsx') else exports.finance_pdf(result)
                        kind='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if path.endswith('.xlsx') else 'application/pdf'
                        name='HZ-Education-Melbourne-finance.'+('xlsx' if path.endswith('.xlsx') else 'pdf')
                        return self.response(200, blob, content_type=kind, extra=[('Content-Disposition', f'attachment; filename="{name}"')])
                    return self.response(200,result)
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/unit-prices':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    include_left = params.get('include_left', ['0'])[0] in ('1', 'true', 'yes')
                    return self.response(200, pricing.unit_price_page(c, user, include_left))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/vouchers':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    import vouchers
                    found=vouchers.search(c,user,params.get('student',[None])[0],params.get('kind',[None])[0],params.get('status',[None])[0],params.get('start',[None])[0],params.get('end',[None])[0],params.get('q',[None])[0])
                    if params.get('id',[None])[0]:
                        found['events']=vouchers.events(c,user,params.get('id')[0])
                    return self.response(200,found)
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/audit':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    return self.response(200,auditlog.search(c,user,params.get('actor',[None])[0],params.get('start',[None])[0],params.get('end',[None])[0]))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/health':
            if DB_ERROR:
                return self.response(503, {'ok': False, 'error': DB_ERROR})
            try:
                with connect() as c:
                    c.execute('SELECT 1 FROM users LIMIT 1').fetchone()
            except sqlite3.DatabaseError as exc:
                message = f'{DB_PATH} is malformed or unreadable ({exc}). Restore the backup before using the site.'
                print(message, file=sys.stderr, flush=True)
                return self.response(503, {'ok': False, 'error': message})
            return self.response(200, {'ok': True})
        if path == '/api/parents/search':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    return self.response(200, profiles.search_parents(c, user, parse_qs(urlsplit(self.path).query).get('q',[''])[0]))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/api/state':
            with connect() as c:
                user = self.current(c)
                if not user:
                    return self.response(200, {'user':None,'demo':DEMO,'organization':ORG_NAME,'contact':contact_details()})
                try:
                    requested=parse_qs(urlsplit(self.path).query).get('through')
                    if requested:
                        teaching.dt.date.fromisoformat(requested[0])
                except (ValueError,OverflowError,IndexError):return self.response(400,{'error':'日期无效。'})
                try:
                    return self.response(200, build_state(c, user))
                except Exception:
                    logging.exception('GET /api/state failed')
                    return self.response(500, {'error':'暂时无法完成操作，请稍后重试。'})
        if path == '/robots.txt':
            return self.response(200, b'User-agent: *\nDisallow: /\n', content_type='text/plain; charset=utf-8')
        student_page = re.fullmatch(r'/students/\d+(?:/lessons/\d+)?/?', path)
        if student_page:
            with connect() as c:
                user = self.current(c)
                if user and user['role'] == 'parent':
                    return self.response(403, {'error': '家长不能打开学生档案。'})
        if student_page or re.fullmatch(r'/teachers/\d+/pay/?', path) or re.fullmatch(r'/receipts/\d+/?', path):
            path = '/'
        files = {'/':'index.html','/app.js':'app.js','/teaching.js':'teaching.js','/accounting.js':'accounting.js','/calendar.js':'calendar.js','/pay.js':'pay.js','/vouchers.js':'vouchers.js','/i18n.js':'i18n.js','/style.css':'style.css','/favicon.ico':'favicon.ico','/favicon-16.png':'favicon-16.png','/favicon-32.png':'favicon-32.png','/apple-touch-icon.png':'apple-touch-icon.png','/logo.jpg':'logo.jpg'}
        if path not in files:
            if path.startswith('/api/'):
                return self.response(404, {'error':'页面不存在。'})
            return self.response(404, NOT_FOUND_PAGE.encode(), content_type='text/html; charset=utf-8')
        name = files[path]
        mime = {'html':'text/html; charset=utf-8','js':'application/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml','jpg':'image/jpeg','png':'image/png','ico':'image/x-icon'}[name.rsplit('.',1)[1]]
        content = (ROOT/'static'/name).read_bytes()
        return self.response(200,content,content_type=mime)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length <= 0 or length > 1048576:
                return self.response(400, {'error':'请求内容无效。'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError('请求内容无效。')
            # Reject cross-site requests, including login CSRF. No permissive CORS.
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://'+self.headers.get('Host',''), 'https://'+self.headers.get('Host','')):
                return self.response(403, {'error':'请求来源无效。'})
            with connect() as c:
                if self.path == '/api/login':
                    return self.login(c,data)
                user = self.current(c)
                if not user:
                    return self.response(401, {'error':'登录已过期，请重新登录。'})
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),user['csrf']):
                    return self.response(403, {'error':'页面已过期，请刷新后重试。'})
                if self.path == '/api/logout':
                    c.execute('DELETE FROM sessions WHERE token_hash=?',(user['token_hash'],))
                    c.commit()
                    return self.response(200,{'ok':True},'session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'+('; Secure' if SECURE else ''))
                if self.path == '/api/password':
                    old = str(data.get('old',''))
                    if not hmac.compare_digest(password_hash(old,user['password'].split(':')[0]),user['password']):
                        raise ValueError('当前密码不正确。')
                    new = str(data.get('password',''))
                    if not 10 <= len(new) <= 128:
                        raise ValueError('新密码需为 10–128 位。')
                    c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(new),user['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                    c.commit()
                    return self.response(200,{'ok':True})
                if self.path in ('/api/vouchers/approve','/api/vouchers/approve-bulk','/api/vouchers/unapprove','/api/vouchers/edit','/api/vouchers/void','/api/vouchers/unvoid'):
                    c.execute('BEGIN IMMEDIATE')
                    import vouchers
                    if self.path == '/api/vouchers/approve-bulk': result=vouchers.approve_many(c,user,data.get('ids'))
                    elif self.path == '/api/vouchers/unvoid': result=vouchers.unvoid(c,user,data.get('id'),units,restore_course=data.get('restore_course') in (True,1,'1','true','on','yes'))
                    elif self.path.endswith('/approve'): result=vouchers.approve(c,user,data.get('id'))
                    elif self.path.endswith('/unapprove'): result=vouchers.unapprove(c,user,data.get('id'))
                    elif self.path.endswith('/edit'): result=vouchers.edit(c,user,data,units,text_value)
                    else: result=vouchers.void(c,user,data.get('id'),units)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/packs/collect':
                    import receivables
                    c.execute('BEGIN IMMEDIATE')
                    result = receivables.collect(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/students/course/switch/preview':
                    return self.response(200, switches.quote_switch(c, user, data))
                if self.path == '/api/students/course/switch':
                    c.execute('BEGIN IMMEDIATE')
                    result = switches.apply_switch(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/audit/last':
                    return self.response(200, auditlog.last_for(c, user))
                if self.path == '/api/students/course/remove':
                    c.execute('BEGIN IMMEDIATE')
                    result=deletion.remove_course(c,user,data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/students/course/settle':
                    c.execute('BEGIN IMMEDIATE')
                    result=deletion.settle_course(c,user,data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/students/leave':
                    c.execute('BEGIN IMMEDIATE')
                    result=profiles.mark_left(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/students/return':
                    c.execute('BEGIN IMMEDIATE')
                    result=profiles.mark_returned(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/students/course/stop':
                    c.execute('BEGIN IMMEDIATE')
                    result=deletion.stop_course(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path in ('/api/profiles/delete','/api/profiles/restore','/api/profiles/reinstate'):
                    c.execute('BEGIN IMMEDIATE')
                    if self.path.endswith('/reinstate'):
                        result=deletion.reinstate_student(c,user,data)
                    elif self.path.endswith('/restore'):
                        result=deletion.restore(c,user,data)
                    else:
                        result=deletion.remove(c,user,data,DB_PATH)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/backup':
                    import backup
                    if user['role'] != 'owner':
                        return self.response(403, {'error':'只有老板可以下载数据库备份。'})
                    blob = backup.snapshot_bytes(DB_PATH)
                    name = 'lessons-'+teaching.now_local().date().isoformat()+'.sqlite3'
                    return self.response(200, blob, content_type='application/vnd.sqlite3', extra=[('Content-Disposition', f'attachment; filename="{name}"')])
                if self.path.split('?')[0].startswith('/api/expenses'):
                    import expenses
                    c.execute('BEGIN IMMEDIATE')
                    result=expenses.handle_post(c, user, self.path.split('?')[0], data)
                    c.commit()
                    return self.response(200, result)
                if self.path.startswith('/api/pay/'):
                    c.execute('BEGIN IMMEDIATE')
                    result=payroll.handle_post(c,user,self.path,data)
                    c.commit()
                    return self.response(200,result)
                if self.path in ('/api/administrators','/api/administrators/edit','/api/administrators/status','/api/accounting/cash','/api/accounting/handover'):
                    c.execute('BEGIN IMMEDIATE')
                    if self.path=='/api/administrators':result=accounting.add_administrator(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/administrators/edit':result=accounting.edit_administrator(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/administrators/status':result=accounting.set_active(c,user,data)
                    elif self.path=='/api/accounting/handover':result=accounting.mark_handover(c,user,data)
                    else:result=accounting.supplement_cash(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path in ('/api/schedule-options','/api/teachers/edit','/api/teachers/status','/api/teachers','/api/lessons','/api/lessons/cancel','/api/lessons/absent','/api/lessons/absent/undo','/api/reports/draft','/api/reports/complete','/api/reports/close','/api/reports/edit'):
                    c.execute('BEGIN IMMEDIATE')
                    if self.path=='/api/schedule-options':
                        result=teaching.save_option(c,user,data,text_value)
                    elif self.path=='/api/teachers/edit':
                        result=teaching.edit_teacher(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/teachers/status':
                        result=teaching.teacher_status(c,user,data)
                    elif self.path=='/api/teachers':
                        result=teaching.create_teacher(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/lessons':
                        teaching.require_scheduler(c,user,data)
                        if not data.get('lesson_id'):
                            horizon=teaching.datetime_value(data.get('ends_at')).date().isoformat()
                            teaching.recurrence.extend(c,horizon,units,text_value)
                        result=teaching.save_schedule(c,user,data,units,text_value)
                    elif self.path=='/api/lessons/cancel':
                        result=teaching.cancel_lesson(c,user,data,text_value)
                    elif self.path=='/api/lessons/absent':
                        result=teaching.mark_absent(c,user,data,units)
                    elif self.path=='/api/lessons/absent/undo':
                        result=teaching.undo_absent(c,user,data)
                    else:
                        result=teaching.save_reports(c,user,data,units,self.path.rsplit('/',1)[1])
                    c.commit()
                    return self.response(200,result)
                if user['role'] not in ('owner','admin'):
                    return self.response(403, {'error':'只有老师可以修改课时。'})
                if self.path == '/api/students/course/level':
                    c.execute('BEGIN IMMEDIATE')
                    result=profiles.set_study_level(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/students/course/relink':
                    c.execute('BEGIN IMMEDIATE')
                    result=profiles.relink_future(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/students/study-status':
                    c.execute('BEGIN IMMEDIATE')
                    result=profiles.set_study_status(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/students/parents/link':
                    c.execute('BEGIN IMMEDIATE')
                    result=profiles.link_parent(c,user,data,phone_value,password_hash,text_value)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/students/parents/unlink':
                    c.execute('BEGIN IMMEDIATE')
                    result=profiles.unlink_parent(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path in ('/api/students/profile','/api/students/guardian','/api/students/course'):
                    c.execute('BEGIN IMMEDIATE')
                    if self.path.endswith('/profile'): result=profiles.update(c,user,data,text_value)
                    elif self.path.endswith('/course'): result=profiles.add_course(c,user,data,text_value)
                    else: result=profiles.guardian(c,user,data,text_value,phone_value,password_hash)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/entries/edit':
                    c.execute('BEGIN IMMEDIATE')
                    result=record_edits.edit(c,user,data,units,text_value)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/students':
                    return self.add_student(c,user,data)
                if self.path in ('/api/course-types', '/api/subjects'):
                    c.execute('BEGIN IMMEDIATE')
                    table = 'course_types' if self.path.endswith('course-types') else 'subjects'
                    result = teaching.save_catalog_item(c, user, table, data, text_value)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/prices':
                    return self.response(200, pricing.list_prices(c, user))
                if self.path == '/api/prices/save':
                    c.execute('BEGIN IMMEDIATE')
                    result = pricing.save_type_price(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/prices/row':
                    c.execute('BEGIN IMMEDIATE')
                    result = pricing.save_band(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/prices/validity':
                    c.execute('BEGIN IMMEDIATE')
                    result = pricing.save_validity(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/prices/legacy':
                    c.execute('BEGIN IMMEDIATE')
                    result = pricing.save_legacy_price(c, user, data)
                    c.commit()
                    return self.response(200, result)
                if self.path == '/api/prices/quote':
                    return self.response(200, pricing.quote(c,user,data.get('student_id'),data.get('product'),data.get('lesson_minutes'),data.get('paid_lessons'),data.get('date') or teaching.now_local().date().isoformat(),data.get('terms')))
                if self.path == '/api/audit/undo':
                    c.execute('BEGIN IMMEDIATE')
                    result=auditlog.undo(c,user,int(data.get('id') or 0))
                    auditlog.mark_undone(c, result['undone'], user['id'])
                    summary=c.execute('SELECT summary FROM audit_log WHERE id=?', (result['undone'],)).fetchone()
                    result['summary']=summary['summary'] if summary else ''
                    c.commit()
                    return self.response(200,result)
                if self.path in ('/api/entries','/api/reverse','/api/refunds'):
                    return self.record(c,user,data)
                return self.response(404,{'error':'接口不存在。'})
        except teaching.AccessError as e:
            return self.response(403,{'error':str(e)})
        except (ValueError, TypeError, KeyError) as e:
            return self.response(400,{'error':str(e) or '输入内容无效。'})
        except sqlite3.IntegrityError:
            return self.response(409,{'error':'记录已存在，请刷新后查看。'})
        except Exception:
            return self.response(500,{'error':'暂时无法完成操作，请稍后重试。'})

    def login(self,c,data):
        phone = phone_value(data.get('phone'))
        password = str(data.get('password',''))
        if len(password)>128:
            raise ValueError('手机号或密码不正确。')
        now = time.time()
        keys = ('phone:'+phone, 'ip:'+self.client_address[0])
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM attempts WHERE expires<?',(now,))
        for key in keys:
            attempt = c.execute('SELECT count FROM attempts WHERE key=?',(key,)).fetchone()
            if attempt and attempt['count'] >= (10 if key.startswith('phone:') else 50):
                return self.response(429,{'error':'登录尝试过多，请 15 分钟后重试。'})
        user = c.execute('SELECT * FROM users WHERE phone=?',(phone,)).fetchone()
        expected = user['password'] if user else '00'*16+':'+ '00'*32
        valid = hmac.compare_digest(password_hash(password,expected.split(':')[0]),expected)
        if not user or not valid or not user['active']:
            for key in keys:
                c.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',(key,now+900))
            c.commit()
            return self.response(401,{'error':'手机号或密码不正确。'})
        c.execute('DELETE FROM attempts WHERE key=?',(keys[0],))
        c.execute('DELETE FROM sessions WHERE expires<?',(now,))
        token = secrets.token_urlsafe(32)
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],secrets.token_urlsafe(24),now+43200))
        c.commit()
        return self.response(200,{'ok':True},f'session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200'+('; Secure' if SECURE else ''))

    def add_student(self,c,user,data):
        import payroll
        payroll.reject_original_flag(user, data)
        name = text_value(data.get('name'),'学生姓名',40)
        if data.get('subject_id'):
            subject = c.execute('SELECT name FROM subjects WHERE id=? AND active=1', (int(data.get('subject_id') or 0),)).fetchone()
            if not subject:
                raise ValueError('请选择科目。')
            course = subject['name']
        else:
            course = text_value(data.get('course'),'课程名称',80)
        birthday,grade,notes=profiles.fields(data)
        if 'grade' in data and not str(data.get('grade') or '').strip():
            raise ValueError('请选择年级。')
        level_code, level_year = pricing.remember_level(data, grade)
        type_guess = c.execute('SELECT id, name FROM course_types WHERE id=?', (int(data.get('course_type_id') or 0),)).fetchone() if data.get('course_type_id') else None
        course, forced_subject, forced_type = pricing.apply_primary_class(
            c, course, data.get('subject_id'), type_guess['id'] if type_guess else None,
            type_guess['name'] if type_guess else '', level_code)
        if forced_subject:
            data['subject_id'] = forced_subject
        if forced_type:
            data['course_type_id'] = forced_type
        if teaching.singapore_subject(course):
            type_row = c.execute('SELECT name FROM course_types WHERE id=?', (int(data.get('course_type_id') or 0),)).fetchone()
            pricing.assert_singapore_enrolment(course, type_row['name'] if type_row else '', level_code)
        billing_unit=profiles.billing_unit(data.get('billing_unit','lesson'))
        phone_raw = str(data.get('phone') or '').strip()
        phone = phone_value(phone_raw) if phone_raw else 'pending-' + secrets.token_hex(6)
        c.execute('BEGIN IMMEDIATE')
        parent = c.execute('SELECT * FROM users WHERE phone=?',(phone,)).fetchone() if phone_raw else None
        if parent and (parent['role'] != 'parent' or c.execute('SELECT 1 FROM teachers WHERE user_id=?',(parent['id'],)).fetchone()):
            raise ValueError('此手机号是老师账号，请使用家长手机号。')
        if parent:
            pid = parent['id']
        else:
            password = str(data.get('password') or '').strip()
            if phone_raw and not password:
                password = phone
            elif phone_raw and not 10 <= len(password) <=128:
                raise ValueError('新家长的初始密码需为 10–128 位。')
            if not phone_raw:
                password = secrets.token_urlsafe(18)
            pid = c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',(phone,text_value(data.get('parent_name') or name+'家长','家长姓名',40),password_hash(password),'parent')).lastrowid
        profile_id=c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        profiles.ensure_identity(c)
        c.execute('UPDATE student_profiles SET name=?,birthday=?,grade=?,notes=? WHERE id=?',(name,birthday,grade,notes,profile_id))
        profiles.save_enrolment(c, profile_id, data)
        sid = c.execute('INSERT INTO students(name,course,parent_id,profile_id) VALUES(?,?,?,?)',(name,course,pid,profile_id)).lastrowid
        c.execute('INSERT OR IGNORE INTO profile_parents(profile_id, user_id) VALUES(?,?)', (profile_id, pid))
        type_id, subject_id = teaching.resolve_catalog(c, data, None, course)
        c.execute('UPDATE students SET birthday=?,grade=?,notes=?,billing_unit=?,course_type_id=?,subject_id=?,course_note=?,level_code=?,level_year=? WHERE id=?',(birthday,grade,notes,billing_unit,type_id,subject_id,course,level_code,level_year,sid))
        import timeline
        timeline.record(c, user, sid, 'course_added', f'添加课程 {course}')
        c.commit()
        return self.response(201,{'ok':True,'student_id':sid})

    def record(self,c,user,data):
        request_id = str(data.get('request_id',''))
        if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',request_id):
            raise ValueError('操作编号无效，请刷新后重试。')
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM ledger WHERE request_id=?',(request_id,)).fetchone():
            return self.response(200,{'ok':True,'duplicate':True})
        reversal_of = None
        cash=None
        backdated = False
        unpaid = False
        if self.path == '/api/reverse':
            original = c.execute('SELECT * FROM ledger WHERE id=?',(int(data['entry_id']),)).fetchone()
            if not original or original['kind']=='reversal':
                raise ValueError('此记录不能撤销。')
            if c.execute('SELECT 1 FROM ledger WHERE reversal_of=?',(original['id'],)).fetchone():
                raise ValueError('此记录已撤销。')
            sid, delta, kind = original['student_id'], -original['delta'], 'reversal'
            reversal_of = original['id']
            day = teaching.now_local().date().isoformat()
            note = '撤销原因：'+text_value(data.get('note'),'撤销原因',250)
            original_cash=c.execute('SELECT * FROM cash_entries WHERE ledger_id=?',(original['id'],)).fetchone()
            if original_cash:
                cash=(-original_cash['cash_delta'],original_cash['payment_method'],'纠正原记账 #'+str(original['id']))
        else:
            sid = int(data['student_id'])
            kind = 'refund' if self.path=='/api/refunds' else data.get('kind')
            if kind not in ('lesson','credit','refund') or (kind=='refund' and self.path!='/api/refunds'):
                raise ValueError('记录类型无效。')
            if kind=='credit' and data.get('product'):
                data=pricing.normalize_purchase(c,user,data)
            backdated = kind=='credit' and data.get('backdated') in (True, 1, '1', 'true', 'on', 'yes')
            day = dt.date.fromisoformat(str(data.get('date',''))).isoformat()
            if day > teaching.now_local().date().isoformat():
                raise ValueError('不能登记尚未发生的上课或充值记录。')
            if backdated and day >= teaching.now_local().date().isoformat():
                raise ValueError('收钱日期要早于今天，钱记在原来的那个月。')
            if backdated and str(data.get('payment_status') or 'paid') in ('unpaid', '挂账'):
                raise ValueError('补录以前的包是已经收过的钱，不能再挂账。')
            if backdated:
                paid_units = units(data.get('amount'))
                remaining_units = _units_or_zero(data.get('remaining'), '还剩几节')
                gift_left = _backdated_gift_units(data)
                if remaining_units > paid_units:
                    raise ValueError('还剩几节不能多于总节数。')
                data['amount'] = paid_units / 100
                data['gift_amount'] = gift_left / 100
                data['backdated_used'] = paid_units - remaining_units
            delta = (credit_batches.zero_units(data.get('amount'),units)+credit_batches.zero_units(data.get('gift_amount',0),units)) if kind=='credit' else -units(data.get('amount'))
            note = str(data.get('note','')).strip()
            if backdated:
                gift_label = _lesson_count(gift_left)
                note = (note + ' · ' if note else '') + f'补录以前的包 · 还剩赠送 {gift_label} 节'
            if len(note)>300:
                raise ValueError('备注不能超过 300 个字。')
            unpaid = kind=='credit' and str(data.get('payment_status') or 'paid') in ('unpaid', '挂账')
            if kind in ('credit','refund') and not unpaid:
                cents,method,reference=accounting.cash_details(data, c)
                if kind=='credit' and method=='gift' and credit_batches.zero_units(data.get('amount'),units)>0:
                    raise ValueError('纯赠课请将付费课时填 0，并在赠送课时中填写数量。')
                if kind=='refund':
                    note='退课退款：'+text_value(data.get('note'),'退款原因',250)
                cash=(cents if kind=='credit' else -cents,method,reference)
            elif unpaid:
                if data.get('total_cents') in (None, ''):
                    data['total_cents'] = accounting.money(data.get('cash_amount') or 0)
                note = (note + ' · ' if note else '') + '挂账，课时先用，钱还没到'
        student = c.execute('SELECT * FROM students WHERE id=?',(sid,)).fetchone()
        if not student:
            raise ValueError('学生不存在。')
        if student['archived'] and kind in ('credit','lesson'):
            raise ValueError('学生已归档，请先恢复档案。')
        if student['balance']+delta<0:
            raise ValueError('剩余余额不足，无法完成此次操作。')
        if backdated:
            import auditlog
            auditlog.hint(c, '补录以前的包 总节数 %s 还剩 %s 还剩赠送 %s' % (
                data.get('amount'), data.get('remaining'), _lesson_count(gift_left)))
            auditlog.begin(c)
        lid=c.execute('INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of) VALUES(?,?,?,?,?,?,?,?)',(sid,delta,kind,day,note,user['id'],request_id,reversal_of)).lastrowid
        breakdown=credit_batches.apply(c,lid,kind,data,units,original if reversal_of else None)
        if cash:accounting.record_cash(c,lid,*cash,user['id'])
        elif kind=='credit' and str(data.get('payment_status') or 'paid') in ('unpaid', '挂账'):
            import receivables
            receivables.open_on_ledger(c, lid)
        import vouchers
        if reversal_of:
            vouchers.attach_reversal(c,user,reversal_of,lid)
        elif kind in ('credit','refund'):
            vouchers.issue_ledger(c,user,lid)
        if backdated and int(data.get('backdated_used') or 0):
            _consume_prior_hours(c, user, sid, lid, day, int(data['backdated_used']), request_id)
        if kind=='credit' and not reversal_of:
            import timeline
            gift_text = ''
            if backdated:
                gift_text = '，还剩赠送 %s 节' % (data.get('gift_amount') if data.get('gift_amount') not in (None, '') else 0)
            timeline.record(c, user, sid, 'top_up', ('补录以前的包' + gift_text) if backdated else ('挂账充值，钱还没到' if unpaid else f"充值 {student['course']}"))
        if backdated:
            import auditlog
            auditlog.finish(c, user)
        c.commit()
        return self.response(201,{'ok':True,**breakdown})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--create-admin',action='store_true')
    parser.add_argument('--create-owner',action='store_true')
    parser.add_argument('--promote-owner',action='store_true')
    parser.add_argument('--reset-password',action='store_true')
    args = parser.parse_args()
    initialize()
    if args.promote_owner:
        phone=phone_value(input('升级为老板的现有管理员手机号：'))
        with connect() as c:
            user=c.execute("SELECT id FROM users WHERE phone=? AND role='admin' AND active=1",(phone,)).fetchone()
            if not user:raise SystemExit('未找到有效的管理员账号。')
            c.execute('INSERT OR IGNORE INTO organization_owners VALUES(?)',(user['id'],))
        print('老板权限已开通。')
        return
    if args.reset_password:
        import getpass
        phone = phone_value(input('需重设密码的手机号：'))
        password = getpass.getpass('新密码（至少 10 位）：')
        if not 10<=len(password)<=128:
            raise SystemExit('密码长度需为 10–128 位。')
        with connect() as c:
            user = c.execute('SELECT id FROM users WHERE phone=?',(phone,)).fetchone()
            if not user:
                raise SystemExit('账号不存在。')
            c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),user['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        print('密码已重设。')
        return
    if args.create_admin or args.create_owner:
        import getpass
        phone = phone_value(input('老师手机号：'))
        name = text_value(input('老师姓名：'),'姓名',40)
        password = getpass.getpass('密码（至少 10 位）：')
        if not 10<=len(password)<=128:
            raise SystemExit('密码长度需为 10–128 位。')
        with connect() as c:
            uid=c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',(phone,name,password_hash(password),'admin')).lastrowid
            c.execute('INSERT INTO teachers(user_id) VALUES(?)',(uid,))
            if args.create_owner:c.execute('INSERT INTO organization_owners VALUES(?)',(uid,))
        print('老师账号已创建。')
        return
    httpd = ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'课时簿运行中：http://{args.host}:{args.port}',flush=True)
    httpd.serve_forever()

if __name__ == '__main__':
    main()
