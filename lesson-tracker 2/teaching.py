"""Scheduling and teaching reports. All mutation callers hold a DB transaction."""
import datetime as dt
import json
import hashlib
import secrets
import credit_batches
import recurrence
import os
import re
from zoneinfo import ZoneInfo

TIMEZONE = os.environ.get('LESSON_TIMEZONE', os.environ.get('TZ', 'Australia/Melbourne'))
ZONE = ZoneInfo(TIMEZONE)

class AccessError(Exception):
    pass

def now_local():
    return dt.datetime.now(ZONE).replace(tzinfo=None)

def schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS schedule_options (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('course','location')),
        name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        UNIQUE(kind,name)
    );
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        subject TEXT NOT NULL DEFAULT '数学'
    );
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
        title TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
        planned_units INTEGER NOT NULL CHECK(planned_units>0), location TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')),
        cancel_reason TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER NOT NULL REFERENCES users(id), request_id TEXT NOT NULL UNIQUE,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE IF NOT EXISTS lesson_students (
        lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        student_id INTEGER NOT NULL REFERENCES students(id), PRIMARY KEY(lesson_id,student_id)
    );
    CREATE TABLE IF NOT EXISTS lesson_reports (
        lesson_id INTEGER NOT NULL REFERENCES lessons(id), student_id INTEGER NOT NULL REFERENCES students(id),
        amount INTEGER NOT NULL CHECK(amount>0), content TEXT NOT NULL DEFAULT '',
        homework TEXT NOT NULL DEFAULT '', feedback TEXT NOT NULL DEFAULT '',
        ledger_id INTEGER UNIQUE REFERENCES ledger(id), updated_by INTEGER NOT NULL REFERENCES users(id),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(lesson_id,student_id)
    );
    CREATE TABLE IF NOT EXISTS report_edits (
        id INTEGER PRIMARY KEY, lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        actor_id INTEGER NOT NULL REFERENCES users(id), payload TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE IF NOT EXISTS arrears (
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id),
        lesson_id INTEGER,
        amount INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        settled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX IF NOT EXISTS lesson_time ON lessons(teacher_id,starts_at,ends_at);
    CREATE INDEX IF NOT EXISTS enrollment_student ON lesson_students(student_id,lesson_id);
    ''')
    if 'color' not in {r['name'] for r in c.execute('PRAGMA table_info(lessons)')}:
        c.execute("ALTER TABLE lessons ADD COLUMN color TEXT NOT NULL DEFAULT 'green'")
    if 'updated_at' not in {r['name'] for r in c.execute('PRAGMA table_info(lessons)')}:
        c.execute("ALTER TABLE lessons ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
    # Existing rows stay scheduled and uncharged. Defaults do not rewrite them.
    _add_column(c, 'lessons', 'absent', 'absent INTEGER NOT NULL DEFAULT 0')
    _add_column(c, 'lessons', 'absent_charge', 'absent_charge INTEGER NOT NULL DEFAULT 0')
    c.execute('''CREATE TABLE IF NOT EXISTS lesson_absence_charges (
        lesson_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        ledger_id INTEGER NOT NULL UNIQUE,
        PRIMARY KEY(lesson_id, student_id)
    )''')
    if 'subjects' not in {r['name'] for r in c.execute('PRAGMA table_info(teachers)')}:
        c.execute("ALTER TABLE teachers ADD COLUMN subjects TEXT NOT NULL DEFAULT '[]'")
    _add_column(c, 'teachers', 'duty', 'duty TEXT')
    c.execute("INSERT OR IGNORE INTO teachers(user_id) SELECT id FROM users WHERE role='admin'")
    if not c.execute("SELECT 1 FROM app_meta WHERE key='schedule_options_v1'").fetchone():
        for kind, names in [('course',['数学 · 一对一','物理','化学']),('location',[])]:
            column='title' if kind=='course' else 'location'
            names += [r[0] for r in c.execute('SELECT DISTINCT '+column+" FROM lessons WHERE "+column+"!=''")]
            c.executemany('INSERT OR IGNORE INTO schedule_options(kind,name) VALUES(?,?)',[(kind,n) for n in names])
        c.execute("INSERT INTO app_meta VALUES('schedule_options_v1','1')")

    recurrence.schema(c)
    ensure_catalogs(c)

DEFAULT_COURSE_TYPES = ('一对一', '一对二', '小班课')
DEFAULT_SUBJECTS = ('数学', '英语', '科学', '物理', '化学', '中文', '写作', '高数', '中数')
VCE_SUBJECTS = ('VCE 中数', 'VCE 低数', 'VCE 高数')
SINGAPORE_SUBJECT = '新加坡数学'
COMBO_SUBJECT = '数学 + 英语'
OFFERED_SUBJECTS = ('数学', '英语', *VCE_SUBJECTS, SINGAPORE_SUBJECT, COMBO_SUBJECT)
OFFERED_TYPES = ('一对一', '一对二', '小班课')
TYPE_ALIASES = {
    '一对一': '一对一', '1:1': '一对一', '1：1': '一对一', 'one': '一对一', 'one_to_one': '一对一',
    '一对二': '一对二', '1:2': '一对二', '1：2': '一对二', 'two': '一对二', 'one_to_two': '一对二',
    '小班课': '小班课', '班课': '小班课', 'group': '小班课', 'term': '小班课',
}
SUBJECT_ALIASES = {
    '数学': '数学', 'maths': '数学', 'math': '数学', 'mathematics': '数学',
    '英语': '英语', 'english': '英语',
    '科学': '科学', 'science': '科学',
    '物理': '物理', '化学': '化学', '中文': '中文',
    '写作': '写作', 'writing': '写作',
    '高数': '高数', '中数': '中数',
    'vce 中数': 'VCE 中数', 'vce 低数': 'VCE 低数', 'vce 高数': 'VCE 高数',
    'math methods': 'VCE 中数', 'maths methods': 'VCE 中数', 'mathematical methods': 'VCE 中数',
    'general mathematics': 'VCE 低数', 'specialist mathematics': 'VCE 高数',
    '新加坡数学': '新加坡数学',
    'singapore maths': '新加坡数学', 'singapore math': '新加坡数学', 'singapore mathematics': '新加坡数学',
    '数学加英语': '数学 + 英语', '数学 + 英语': '数学 + 英语', '数学/英语': '数学 + 英语',
    'maths and english': '数学 + 英语', 'math and english': '数学 + 英语',
}
# Longer English names first, so "math methods" is not swallowed by the generic "math" prefix.
VCE_ALIASES = (
    ('mathematical methods', 'VCE 中数'),
    ('specialist mathematics', 'VCE 高数'),
    ('general mathematics', 'VCE 低数'),
    ('maths methods', 'VCE 中数'),
    ('math methods', 'VCE 中数'),
)


def display_person(name):
    """HELEN is shown as Helen. Mixed-case names stay as stored."""
    text = str(name or '').strip()
    letters = ''.join(ch for ch in text if ch.isalpha())
    if letters and letters.isascii() and letters.upper() == letters and letters.lower() != letters:
        return text.title()
    return text


def vce_subject(name):
    """VCE maths stays its own subject. Names do not contain 数学, and Math Methods is not generic maths."""
    text = str(name or '').strip()
    if not text:
        return ''
    for label in VCE_SUBJECTS:
        if text == label or label in text:
            return label
    key = text.casefold()
    for alias, label in VCE_ALIASES:
        if key == alias or key.startswith(alias + ' ') or key.startswith(alias + '·') or key.startswith(alias + ' ·'):
            return label
    return ''


def singapore_subject(name):
    """新加坡数学 stays its own subject. The name contains 数学 and must not fold into 数学."""
    text = str(name or '').strip()
    if not text:
        return ''
    if text == SINGAPORE_SUBJECT or SINGAPORE_SUBJECT in text:
        return SINGAPORE_SUBJECT
    key = text.casefold()
    for alias in ('singapore mathematics', 'singapore maths', 'singapore math'):
        if key == alias or key.startswith(alias + ' ') or key.startswith(alias + '·') or key.startswith(alias + ' ·'):
            return SINGAPORE_SUBJECT
    return ''


def combo_subject(name):
    """数学 + 英语 is the one primary small class. 数学加英语 and 数学/英语 are the same course."""
    text = str(name or '').strip()
    if not text:
        return ''
    compact = ''.join(text.split()).replace('＋', '+').replace('／', '/')
    if '数学加英语' in compact or '数学+英语' in compact or '数学/英语' in compact:
        return COMBO_SUBJECT
    if text.casefold() in ('maths and english', 'math and english', 'maths + english', 'math + english'):
        return COMBO_SUBJECT
    return ''


def canonical_subject(name):
    """Science and 科学 display as the same Chinese subject. Stored labels are not rewritten.

    VCE 中数 / VCE 低数 / VCE 高数, and Math Methods, are not folded into 数学.
    新加坡数学 is not folded into 数学 either.
    The unused 中数 and 高数 labels stay as themselves.
    """
    text = str(name or '').strip()
    if not text:
        return ''
    named = combo_subject(text) or vce_subject(text) or singapore_subject(text)
    if named:
        return named
    key = text.casefold()
    if key in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[key]
    if text in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[text]
    for token, label in (('english', '英语'), ('science', '科学'), ('writing', '写作'), ('maths', '数学'), ('math', '数学')):
        if key == token or key.startswith(token + ' '):
            return label
    return text


def infer_type_name(student_count):
    if student_count == 1:
        return '一对一'
    if student_count == 2:
        return '一对二'
    return '小班课'


def _split_label(text):
    raw = str(text or '').strip()
    parts = [part.strip() for part in raw.replace('・', '·').split('·') if part.strip()]
    if len(parts) < 2 and ' - ' in raw:
        parts = [part.strip() for part in raw.split(' - ') if part.strip()]
    return raw, parts


def parse_label(text, student_count=None):
    """Pull a subject and a course type out of an old free-text label. The original is kept."""
    raw, parts = _split_label(text)
    found_type = ''
    found_subject = ''
    for part in parts or ([raw] if raw else []):
        key = part.casefold()
        if key in TYPE_ALIASES or part in TYPE_ALIASES:
            found_type = TYPE_ALIASES.get(part) or TYPE_ALIASES.get(key, '')
        elif key in SUBJECT_ALIASES or part in SUBJECT_ALIASES:
            found_subject = SUBJECT_ALIASES.get(part) or SUBJECT_ALIASES.get(key, '')
    if not found_type:
        for token in ('小班课', '一对二', '一对一', '小班', '班课', '1:2', '1:1'):
            if token in raw:
                found_type = TYPE_ALIASES.get(token, '')
                break
    if not found_type and student_count is not None:
        found_type = infer_type_name(student_count)
    return found_subject, found_type, raw


def _add_column(c, table, name, ddl):
    cols = {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
    if name not in cols:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {ddl}')


def ensure_catalogs(c):
    """Add course types and subjects. One transaction, no file changes, no journal mode."""
    c.execute('''CREATE TABLE IF NOT EXISTS course_types (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
        sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
        sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1)''')
    for index, name in enumerate(DEFAULT_COURSE_TYPES):
        c.execute('INSERT OR IGNORE INTO course_types(name, sort_order) VALUES(?,?)', (name, (index + 1) * 10))
    for index, name in enumerate(DEFAULT_SUBJECTS):
        c.execute('INSERT OR IGNORE INTO subjects(name, sort_order) VALUES(?,?)', (name, (index + 1) * 10))
    _add_column(c, 'lessons', 'course_type_id', 'course_type_id INTEGER REFERENCES course_types(id)')
    _add_column(c, 'lessons', 'subject_id', 'subject_id INTEGER REFERENCES subjects(id)')
    _add_column(c, 'lessons', 'title_note', "title_note TEXT NOT NULL DEFAULT ''")
    _add_column(c, 'students', 'course_type_id', 'course_type_id INTEGER REFERENCES course_types(id)')
    _add_column(c, 'students', 'subject_id', 'subject_id INTEGER REFERENCES subjects(id)')
    _add_column(c, 'students', 'course_note', "course_note TEXT NOT NULL DEFAULT ''")
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_series'").fetchone():
        _add_column(c, 'lesson_series', 'course_type_id', 'course_type_id INTEGER REFERENCES course_types(id)')
        _add_column(c, 'lesson_series', 'subject_id', 'subject_id INTEGER REFERENCES subjects(id)')
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_rows'").fetchone():
        _add_column(c, 'price_rows', 'course_type_id', 'course_type_id INTEGER REFERENCES course_types(id)')
        _add_column(c, 'price_rows', 'placeholder', 'placeholder INTEGER NOT NULL DEFAULT 1')
    _backfill_catalogs(c)
    focus_catalog(c)
    refocus_catalog(c)
    activate_vce_subjects(c)
    activate_singapore_maths(c)
    activate_combo_subject(c)
    merge_combo_subject(c)
    ensure_type_products(c)


def focus_catalog(c):
    """Hide extra subjects and old course-name options once. Rows stay, so Settings can turn them back on."""
    if c.execute("SELECT 1 FROM app_meta WHERE key='catalog_focus_v1'").fetchone():
        return
    for index, name in enumerate(OFFERED_SUBJECTS):
        c.execute('INSERT OR IGNORE INTO subjects(name, sort_order, active) VALUES(?,?,1)', (name, (index + 1) * 10))
        c.execute('UPDATE subjects SET active=1 WHERE name=?', (name,))
    marks = ','.join('?' * len(OFFERED_SUBJECTS))
    c.execute(f'UPDATE subjects SET active=0 WHERE name NOT IN ({marks})', OFFERED_SUBJECTS)
    type_marks = ','.join('?' * len(OFFERED_TYPES))
    c.execute(f'UPDATE course_types SET active=1 WHERE name IN ({type_marks})', OFFERED_TYPES)
    c.execute(f'UPDATE course_types SET active=0 WHERE name NOT IN ({type_marks})', OFFERED_TYPES)
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_options'").fetchone():
        c.execute(f"UPDATE schedule_options SET active=0 WHERE kind='course' AND name NOT IN ({marks})", OFFERED_SUBJECTS)
        for name in OFFERED_SUBJECTS:
            c.execute("INSERT OR IGNORE INTO schedule_options(kind, name, active) VALUES('course', ?, 1)", (name,))
            c.execute("UPDATE schedule_options SET active=1 WHERE kind='course' AND name=?", (name,))
    c.execute("INSERT INTO app_meta(key, value) VALUES('catalog_focus_v1', '1')")


def refocus_catalog(c):
    """Hide course names added after the first pass, such as 跟踪辅导. Rows stay."""
    if c.execute("SELECT 1 FROM app_meta WHERE key='catalog_focus_v2'").fetchone():
        return
    marks = ','.join('?' * len(OFFERED_SUBJECTS))
    c.execute(f'UPDATE subjects SET active=0 WHERE name NOT IN ({marks})', OFFERED_SUBJECTS)
    c.execute(f'UPDATE subjects SET active=1 WHERE name IN ({marks})', OFFERED_SUBJECTS)
    type_marks = ','.join('?' * len(OFFERED_TYPES))
    c.execute(f'UPDATE course_types SET active=0 WHERE name NOT IN ({type_marks})', OFFERED_TYPES)
    c.execute(f'UPDATE course_types SET active=1 WHERE name IN ({type_marks})', OFFERED_TYPES)
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_options'").fetchone():
        c.execute(f"UPDATE schedule_options SET active=0 WHERE kind='course' AND name NOT IN ({marks})", OFFERED_SUBJECTS)
    c.execute("INSERT INTO app_meta(key, value) VALUES('catalog_focus_v2', '1')")


def activate_vce_subjects(c):
    """Add VCE 中数, VCE 低数 and VCE 高数 on databases that already focused on 数学 and 英语.

    Idempotent. Does not deactivate 数学 or 英语, and does not touch the unused 中数 / 高数 rows.
    """
    if c.execute("SELECT 1 FROM app_meta WHERE key='catalog_vce_maths_v1'").fetchone():
        return
    start = OFFERED_SUBJECTS.index(VCE_SUBJECTS[0])
    for offset, name in enumerate(VCE_SUBJECTS):
        c.execute('INSERT OR IGNORE INTO subjects(name, sort_order, active) VALUES(?,?,1)', (name, (start + offset + 1) * 10))
        c.execute('UPDATE subjects SET active=1 WHERE name=?', (name,))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_options'").fetchone():
        for name in VCE_SUBJECTS:
            c.execute("INSERT OR IGNORE INTO schedule_options(kind, name, active) VALUES('course', ?, 1)", (name,))
            c.execute("UPDATE schedule_options SET active=1 WHERE kind='course' AND name=?", (name,))
    c.execute("INSERT INTO app_meta(key, value) VALUES('catalog_vce_maths_v1', '1')")


def activate_singapore_maths(c):
    """Add 新加坡数学 on databases that already focused on 数学, 英语 and VCE.

    Idempotent. Does not deactivate those subjects, and does not touch the unused 中数 / 高数 rows.
    """
    if c.execute("SELECT 1 FROM app_meta WHERE key='catalog_singapore_maths_v1'").fetchone():
        return
    sort = (OFFERED_SUBJECTS.index(SINGAPORE_SUBJECT) + 1) * 10
    c.execute('INSERT OR IGNORE INTO subjects(name, sort_order, active) VALUES(?,?,1)', (SINGAPORE_SUBJECT, sort))
    c.execute('UPDATE subjects SET active=1 WHERE name=?', (SINGAPORE_SUBJECT,))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_options'").fetchone():
        c.execute("INSERT OR IGNORE INTO schedule_options(kind, name, active) VALUES('course', ?, 1)", (SINGAPORE_SUBJECT,))
        c.execute("UPDATE schedule_options SET active=1 WHERE kind='course' AND name=?", (SINGAPORE_SUBJECT,))
    c.execute("INSERT INTO app_meta(key, value) VALUES('catalog_singapore_maths_v1', '1')")


def activate_combo_subject(c):
    """Add 数学 + 英语 as one subject. It keeps its own price and is not 数学 plus 英语."""
    if c.execute("SELECT 1 FROM app_meta WHERE key='catalog_combo_v1'").fetchone():
        return
    sort = (OFFERED_SUBJECTS.index(COMBO_SUBJECT) + 1) * 10
    c.execute('INSERT OR IGNORE INTO subjects(name, sort_order, active) VALUES(?,?,1)', (COMBO_SUBJECT, sort))
    c.execute('UPDATE subjects SET active=1 WHERE name=?', (COMBO_SUBJECT,))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_options'").fetchone():
        c.execute("INSERT OR IGNORE INTO schedule_options(kind, name, active) VALUES('course', ?, 1)", (COMBO_SUBJECT,))
        c.execute("UPDATE schedule_options SET active=1 WHERE kind='course' AND name=?", (COMBO_SUBJECT,))
    c.execute("INSERT INTO app_meta(key, value) VALUES('catalog_combo_v1', '1')")


def merge_combo_subject(c):
    """Fold the seeded 数学加英语 catalog row into Helen's 数学 + 英语. Leave her name as it is.

    A second startup does nothing. If the duplicate was never created, this only records that.
    References move first. The duplicate row is deleted only after nothing still points at it.
    """
    if c.execute("SELECT 1 FROM app_meta WHERE key='combo_name_v1'").fetchone():
        return
    sort = (OFFERED_SUBJECTS.index(COMBO_SUBJECT) + 1) * 10
    c.execute('INSERT OR IGNORE INTO subjects(name, sort_order, active) VALUES(?,?,1)', (COMBO_SUBJECT, sort))
    c.execute('UPDATE subjects SET active=1 WHERE name=?', (COMBO_SUBJECT,))
    canonical = c.execute('SELECT id FROM subjects WHERE name=?', (COMBO_SUBJECT,)).fetchone()
    aliases = ('数学加英语',)
    for alias in aliases:
        row = c.execute('SELECT id FROM subjects WHERE name=? AND id!=?', (alias, canonical['id'])).fetchone()
        if not row:
            continue
        old_id = row['id']
        for table in ('students', 'lessons', 'lesson_series'):
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() and c.execute(f"SELECT 1 FROM pragma_table_info('{table}') WHERE name='subject_id'").fetchone():
                c.execute(f'UPDATE {table} SET subject_id=? WHERE subject_id=?', (canonical['id'], old_id))
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_subject_prices'").fetchone():
            c.execute('UPDATE student_subject_prices SET subject=? WHERE subject=?', (COMBO_SUBJECT, alias))
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_options'").fetchone():
            c.execute("UPDATE schedule_options SET active=0 WHERE kind='course' AND name=?", (alias,))
        c.execute('DELETE FROM subjects WHERE id=?', (old_id,))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='course_types'").fetchone():
        extra = c.execute("SELECT id FROM course_types WHERE name='数学加英语'").fetchone()
        if extra:
            kept = c.execute("SELECT id FROM course_types WHERE name IN ('数学 + 英语', '小班课') ORDER BY CASE name WHEN '数学 + 英语' THEN 0 ELSE 1 END LIMIT 1").fetchone()
            if kept and kept['id'] != extra['id']:
                for table in ('students', 'lessons', 'lesson_series', 'price_rows'):
                    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() and c.execute(f"SELECT 1 FROM pragma_table_info('{table}') WHERE name='course_type_id'").fetchone():
                        c.execute(f'UPDATE {table} SET course_type_id=? WHERE course_type_id=?', (kept['id'], extra['id']))
                c.execute('DELETE FROM course_types WHERE id=?', (extra['id'],))
            elif not kept:
                c.execute("UPDATE course_types SET name='小班课' WHERE id=? AND NOT EXISTS(SELECT 1 FROM course_types WHERE name='小班课')", (extra['id'],))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_options'").fetchone():
        c.execute("INSERT OR IGNORE INTO schedule_options(kind, name, active) VALUES('course', ?, 1)", (COMBO_SUBJECT,))
        c.execute("UPDATE schedule_options SET active=1 WHERE kind='course' AND name=?", (COMBO_SUBJECT,))
    c.execute("INSERT INTO app_meta(key, value) VALUES('combo_name_v1', '1')")


def ensure_type_products(c):
    """Each course type points at a price product. A new type stays blank until one is set."""
    _add_column(c, 'course_types', 'product', "product TEXT NOT NULL DEFAULT ''")
    for name, product in (('一对一', 'one_to_one'), ('一对二', 'one_to_two'), ('小班课', 'term')):
        c.execute("UPDATE course_types SET product=? WHERE name=? AND product=''", (product, name))


def courses_match_lesson(c, student_ids, subject_id, type_id):
    """The lesson subject comes from the chosen courses. A different subject is refused."""
    subjects = []
    for sid in student_ids:
        row = c.execute('SELECT subject_id FROM students WHERE id=?', (sid,)).fetchone()
        if row and row['subject_id']:
            subjects.append(row['subject_id'])
    if len(set(subjects)) > 1:
        raise ValueError('请选择同一科目的课程。')
    if subjects:
        if subject_id and int(subject_id) != int(subjects[0]):
            raise ValueError('这节课的科目和所选课程不一致。')
        subject_id = subjects[0]
    return type_id, subject_id


def _id_by_name(c, table, name):
    if not name:
        return None
    row = c.execute(f'SELECT id FROM {table} WHERE name=?', (name,)).fetchone()
    if row:
        return row['id']
    if table == 'subjects' and name and len(name) <= 40:
        return c.execute('INSERT INTO subjects(name, sort_order) VALUES(?, 500)', (name,)).lastrowid
    return None


def _backfill_catalogs(c):
    for row in c.execute("SELECT id, title, title_note FROM lessons WHERE course_type_id IS NULL OR subject_id IS NULL"):
        count = c.execute('SELECT COUNT(*) FROM lesson_students WHERE lesson_id=?', (row['id'],)).fetchone()[0]
        subject, kind, original = parse_label(row['title'], count)
        if not row['title_note']:
            c.execute('UPDATE lessons SET title_note=? WHERE id=?', (original, row['id']))
        if kind and not c.execute('SELECT course_type_id FROM lessons WHERE id=?', (row['id'],)).fetchone()['course_type_id']:
            c.execute('UPDATE lessons SET course_type_id=? WHERE id=? AND course_type_id IS NULL', (_id_by_name(c, 'course_types', kind), row['id']))
        if subject:
            c.execute('UPDATE lessons SET subject_id=? WHERE id=? AND subject_id IS NULL', (_id_by_name(c, 'subjects', subject), row['id']))
    for row in c.execute('SELECT id, course, course_note FROM students WHERE course_type_id IS NULL OR subject_id IS NULL'):
        subject, kind, original = parse_label(row['course'], None)
        if not row['course_note']:
            c.execute('UPDATE students SET course_note=? WHERE id=?', (original, row['id']))
        if kind:
            c.execute('UPDATE students SET course_type_id=? WHERE id=? AND course_type_id IS NULL', (_id_by_name(c, 'course_types', kind), row['id']))
        if subject:
            c.execute('UPDATE students SET subject_id=? WHERE id=? AND subject_id IS NULL', (_id_by_name(c, 'subjects', subject), row['id']))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_series'").fetchone():
        c.execute('''UPDATE lesson_series SET
            course_type_id=COALESCE(course_type_id, (SELECT course_type_id FROM lessons WHERE series_id=lesson_series.id AND course_type_id IS NOT NULL ORDER BY occurrence_index LIMIT 1)),
            subject_id=COALESCE(subject_id, (SELECT subject_id FROM lessons WHERE series_id=lesson_series.id AND subject_id IS NOT NULL ORDER BY occurrence_index LIMIT 1))
            WHERE course_type_id IS NULL OR subject_id IS NULL''')
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_rows'").fetchone():
        for row in c.execute('SELECT id, product FROM price_rows WHERE course_type_id IS NULL'):
            kind = TYPE_ALIASES.get(row['product']) or TYPE_ALIASES.get(str(row['product']).casefold())
            if kind:
                c.execute('UPDATE price_rows SET course_type_id=? WHERE id=?', (_id_by_name(c, 'course_types', kind), row['id']))


def catalog_lists(c):
    types = [dict(r) for r in c.execute('SELECT * FROM course_types ORDER BY sort_order, id')]
    subjects = [dict(r) for r in c.execute('SELECT * FROM subjects ORDER BY sort_order, id')]
    return types, subjects


def save_catalog_item(c, user, table, data, text_value):
    if user['role'] != 'owner':
        raise AccessError('只有老板可以修改课程类型和科目。')
    if table not in ('course_types', 'subjects'):
        raise ValueError('列表无效。')
    name = text_value(data.get('name'), '名称', 40)
    active = 0 if data.get('active') in (False, 0, '0') else 1
    item_id = int(data.get('id') or 0)
    if item_id:
        if c.execute(f'SELECT 1 FROM {table} WHERE name=? AND id!=?', (name, item_id)).fetchone():
            raise ValueError('这个名称已经有了。')
        c.execute(f'UPDATE {table} SET name=?, active=? WHERE id=?', (name, active, item_id))
        return {'ok': True, 'id': item_id}
    if c.execute(f'SELECT 1 FROM {table} WHERE name=?', (name,)).fetchone():
        raise ValueError('这个名称已经有了。')
    sort = c.execute(f'SELECT COALESCE(MAX(sort_order),0)+10 FROM {table}').fetchone()[0]
    new_id = c.execute(f'INSERT INTO {table}(name, sort_order, active) VALUES(?,?,?)', (name, sort, active)).lastrowid
    return {'ok': True, 'id': new_id}


def resolve_catalog(c, data, student_count, fallback_text=''):
    """Use the chosen ids. Older callers that only send a label are parsed, not left as free text."""
    explicit_type = int(data.get('course_type_id') or 0)
    explicit_subject = int(data.get('subject_id') or 0)
    type_id = explicit_type
    subject_id = explicit_subject
    if not type_id or not subject_id:
        subject_name, type_name, _original = parse_label(data.get('title') or data.get('course') or fallback_text, student_count if not type_id else None)
        if not type_id and type_name:
            type_id = _id_by_name(c, 'course_types', type_name) or 0
        if not subject_id and subject_name:
            subject_id = _id_by_name(c, 'subjects', subject_name) or 0
    if not type_id:
        type_id = _id_by_name(c, 'course_types', infer_type_name(student_count if student_count is not None else 0)) or 0
    if explicit_type and not c.execute('SELECT 1 FROM course_types WHERE id=? AND active=1', (type_id,)).fetchone():
        raise ValueError('请选择课程类型。')
    if explicit_subject and not c.execute('SELECT 1 FROM subjects WHERE id=? AND active=1', (subject_id,)).fetchone():
        raise ValueError('请选择科目。')
    if subject_id and not explicit_subject and not c.execute('SELECT 1 FROM subjects WHERE id=? AND active=1', (subject_id,)).fetchone():
        subject_id = None
    return type_id or None, subject_id or None

def staff_or_admin(user):
    if user['role'] not in ('owner','admin','teacher'):
        raise AccessError('只有管理员或任课老师可以填写课后记录。')

def allowed_lesson(c,user,lesson_id):
    staff_or_admin(user)
    lesson=c.execute('SELECT l.*,t.user_id teacher_user_id FROM lessons l JOIN teachers t ON l.teacher_id=t.id WHERE l.id=?',(int(lesson_id),)).fetchone()
    if not lesson or (user['role'] not in ('owner','admin') and lesson['teacher_user_id']!=user['id']):
        raise AccessError('无法访问这节课程。')
    return lesson

def check_version(lesson,data):
    try:
        sent=int(data.get('version',0))
    except (TypeError, ValueError):
        raise ValueError('这节课已被更新，请刷新页面后再操作。')
    if sent!=lesson['version']:
        raise ValueError('这节课已被更新，请刷新页面后再操作。')

def datetime_value(value):
    value=str(value or '')
    if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d',value):
        raise ValueError('请选择有效的上课日期和时间。')
    parsed=dt.datetime.fromisoformat(value)
    aware=parsed.replace(tzinfo=ZONE)
    if aware.astimezone(dt.timezone.utc).astimezone(ZONE).replace(tzinfo=None)!=parsed:
        raise ValueError('所选时间处于夏令时调整区间，请选择其他时间。')
    if aware.utcoffset()!=parsed.replace(tzinfo=ZONE,fold=1).utcoffset():
        raise ValueError('所选时间有夏令时歧义，请选择其他时间。')
    return parsed

def report_written(report):
    """A draft or a submitted row counts when it has text or a charged ledger.

    Saving a draft inserts lesson_reports and leaves lessons.status as scheduled.
    Callers decide "already recorded" from this row, not from that status.
    """
    if not report:
        return False
    if report.get('ledger_id'):
        return True
    return any(str(report.get(key) or '').strip() for key in ('content', 'homework', 'feedback'))


def lesson_recorded(lesson):
    status = str(lesson.get('status') or '').lower()
    if status in ('completed', 'attended', 'done', 'redeemed'):
        return True
    return any(report_written(report) for report in lesson.get('reports') or [])


def is_absent(lesson):
    """True when this lesson was marked 请假. A database from before the column is not absent."""
    if not lesson:
        return False
    try:
        flag = lesson['absent']
    except (KeyError, IndexError, TypeError):
        return False
    try:
        return int(flag or 0) == 1
    except (TypeError, ValueError):
        return False


def lesson_charge_units(lesson, billing_unit, units):
    """The same quantity an attended lesson deducts for this student.

    Hourly students use the lesson length. Other students use the planned amount.
    """
    if (billing_unit or 'lesson') == 'hour':
        start = dt.datetime.fromisoformat(lesson['starts_at'])
        end = dt.datetime.fromisoformat(lesson['ends_at'])
        hours = round((end - start).total_seconds() / 3600, 2)
        return units(hours)
    return units(lesson['planned_units'] / 100)


def state_for(c,user):
    role=user['role']
    where, params=('',())
    if role=='teacher':
        where,params=(' WHERE t.user_id=?',(user['id'],))
    elif role=='parent':
        import profiles
        profiles.schema(c)
        where,params=(' WHERE EXISTS (SELECT 1 FROM lesson_students ls JOIN students s ON ls.student_id=s.id WHERE ls.lesson_id=l.id AND '+profiles.linked_clause('s')+')', profiles.linked_params(user['id']))
    lessons=[dict(x) for x in c.execute('SELECT l.*, ct.name course_type_name, sb.name subject_name, (SELECT version FROM lesson_series WHERE id=l.series_id) series_version,(SELECT endless FROM lesson_series WHERE id=l.series_id) repeats_forever,(SELECT course_type_id FROM lesson_series WHERE id=l.series_id) series_course_type_id, u.name teacher_name FROM lessons l JOIN teachers t ON l.teacher_id=t.id JOIN users u ON t.user_id=u.id LEFT JOIN course_types ct ON ct.id=l.course_type_id LEFT JOIN subjects sb ON sb.id=l.subject_id'+where+' ORDER BY l.starts_at,l.id',params)]
    for lesson in lessons:
        member_where=' AND '+profiles.linked_clause('s') if role=='parent' else ''
        member_params=(lesson['id'],*profiles.linked_params(user['id'])) if role=='parent' else (lesson['id'],)
        lesson['students']=[dict(x) for x in c.execute('SELECT s.id,s.name,s.course,s.balance,s.billing_unit,s.grade FROM lesson_students ls JOIN students s ON ls.student_id=s.id WHERE ls.lesson_id=?'+member_where+' ORDER BY s.id',member_params)]
        if role=='teacher':
            for student in lesson['students']:
                student.pop('balance', None)
        if role=='parent' and lesson['status']!='completed':
            lesson['reports']=[]
        else:
            lesson['reports']=[dict(x) for x in c.execute('SELECT r.*,s.name student_name,s.billing_unit,v.id reversed_by FROM lesson_reports r JOIN students s ON r.student_id=s.id LEFT JOIN ledger v ON v.reversal_of=r.ledger_id WHERE r.lesson_id=?'+member_where+' ORDER BY s.id',member_params)]
            if role!='owner':
                for report in lesson['reports']:
                    report.pop('fee_cents', None)
                    report.pop('fee_overridden', None)
        lesson['absent'] = 1 if is_absent(lesson) else 0
        lesson['absent_charge'] = 1 if lesson['absent'] and int(lesson.get('absent_charge') or 0) else 0
        # An absence is not a lesson record, even if a draft was saved earlier.
        lesson['recorded'] = False if lesson['absent'] else lesson_recorded(lesson)
        lesson['subject_name'] = canonical_subject(lesson.get('subject_name') or '')
        lesson['teacher_name'] = display_person(lesson.get('teacher_name'))
    teachers=[]
    if role in ('owner','admin','teacher'):
        tw='' if role in ('owner','admin') else ' WHERE u.id=? AND u.active=1'
        tp=() if role in ('owner','admin') else (user['id'],)
        teachers=[dict(x) for x in c.execute("SELECT t.id,t.subject,t.subjects,t.duty,u.name,u.phone,u.active,u.id user_id,CASE WHEN EXISTS(SELECT 1 FROM organization_owners o WHERE o.user_id=u.id) THEN 'owner' WHEN u.role='admin' THEN 'admin' ELSE 'teacher' END account_role FROM teachers t JOIN users u ON t.user_id=u.id"+tw+' ORDER BY t.id',tp)]
    for t in teachers:
        t['name']=display_person(t.get('name'))
        t['subjects']=[canonical_subject(name) for name in (json.loads(t['subjects']) or [t['subject']])]
        t['subject']=canonical_subject(t.get('subject') or '')
        if role!='owner' and role!='admin':
            t.pop('duty', None)
    if role=='parent':
        for lesson in lessons:lesson['reports']=[r for r in lesson['reports'] if not r.get('reversed_by')]
        lessons=[l for l in lessons if l['status']!='completed' or l['reports']]
    types, subjects = catalog_lists(c)
    return {'recurrence_warnings':recurrence.warnings(c) if role in ('owner','admin') else [],'schedule_options':[dict(x) for x in c.execute('SELECT * FROM schedule_options ORDER BY kind,id')] if role in ('owner','admin','teacher') else [],'course_types':types,'subjects':subjects,'lessons':lessons,'teachers':teachers,'timezone':TIMEZONE,'today':now_local().date().isoformat(),'now':now_local().strftime('%Y-%m-%dT%H:%M')}

def create_teacher(c,user,data,phone_value,password_hash,text_value):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有管理员可以添加老师。')
    phone=phone_value(data.get('phone'))
    name=text_value(data.get('name'),'老师姓名',40)
    subjects=subject_values(data,text_value)
    subject='、'.join(subjects)
    password=str(data.get('password',''))
    if not 10<=len(password)<=128:
        raise ValueError('初始密码需为 10–128 位。')
    if c.execute('SELECT 1 FROM users WHERE phone=?',(phone,)).fetchone():
        raise ValueError('该手机号已有账号，请使用独立的老师手机号。')
    # Teacher membership augments legacy users without rebuilding its FK-bound table.
    uid=c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",(phone,name,password_hash(password))).lastrowid
    tid=c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)',(uid,subject)).lastrowid
    c.execute('UPDATE teachers SET subjects=?,duty=? WHERE id=?',(json.dumps(subjects,ensure_ascii=False),duty_value(data),tid))
    return {'ok':True,'teacher_id':tid}

def require_scheduler(c,user,data):
    """Scheduling, rescheduling, skipping and hour changes are boss and admin only."""
    if user['role'] in ('owner','admin'):
        return
    raise AccessError('只有老板或管理员可以排课或调整课程。')

def save_schedule(c,user,data,units,text_value):
    require_scheduler(c,user,data)
    repeat=str(data.get('repeat','none'))
    if repeat not in ('none','weekly','fortnightly'):
        raise ValueError('重复选项无效。')
    if data.get('lesson_id'):
        scope=data.get('scope','single')
        if scope not in ('single','future'):raise ValueError('调整范围无效。')
        if scope=='future':return recurrence.update_future(c,user,data,units,text_value)
        result=save_lesson(c,user,data,units,text_value)
        c.execute('UPDATE lesson_series SET version=version+1 WHERE id=(SELECT series_id FROM lessons WHERE id=?)',(data['lesson_id'],))
        return result
    if repeat=='none':return save_lesson(c,user,data,units,text_value)
    raw=str(data.get('repeat_count',''))
    forever=data.get('repeat_end')=='forever'
    if not forever and (not re.fullmatch(r'[0-9]{1,2}',raw) or not 2<=int(raw)<=52):
        raise ValueError('总课次数需为 2–52 次，包含本次。')
    count=(53 if repeat=='weekly' else 27) if forever else int(raw)
    key=str(data.get('request_id',''))
    if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',key):
        raise ValueError('操作编号无效，请重新打开排课表单。')
    existing=c.execute('SELECT id FROM lessons WHERE request_id=?',(key,)).fetchone()
    if existing:return {'ok':True,'lesson_id':existing['id'],'duplicate':True}
    start=datetime_value(data.get('starts_at'))
    end=datetime_value(data.get('ends_at'))
    series_id=key
    template={k:data[k] for k in ('title','teacher_id','starts_at','ends_at','amount','location','color','student_ids','course_type_id','subject_id') if k in data}
    c.execute('INSERT INTO lesson_series(id,interval_days,endless,next_index,stop_index,template,created_by) VALUES(?,?,?,?,?,?,?)',(series_id,7 if repeat=='weekly' else 14,int(forever),count,None if forever else count,json.dumps(template),user['id']))
    ids=[]
    for i in range(count):
        offset=dt.timedelta(days=i*(7 if repeat=='weekly' else 14))
        item={**data,'starts_at':(start+offset).strftime('%Y-%m-%dT%H:%M'),
              'ends_at':(end+offset).strftime('%Y-%m-%dT%H:%M'),
              'request_id':key if i==0 else hashlib.sha256((key+':'+str(i)).encode()).hexdigest()}
        try:ids.append(save_lesson(c,user,item,units,text_value)['lesson_id'])
        except ValueError as e:
            raise ValueError(item['starts_at'][:10]+'：'+str(e)) from e
        c.execute('UPDATE lessons SET series_id=?,occurrence_index=? WHERE id=?',(series_id,i,ids[-1]))
    first = c.execute('SELECT course_type_id, subject_id FROM lessons WHERE id=?', (ids[0],)).fetchone()
    if first:
        c.execute('UPDATE lesson_series SET course_type_id=?, subject_id=? WHERE id=?', (first['course_type_id'], first['subject_id'], series_id))
    return {'ok':True,'lesson_id':ids[0],'lesson_ids':ids,'created_count':len(ids)}

def save_lesson(c,user,data,units,text_value):
    require_scheduler(c,user,data)
    lesson_id=int(data.get('lesson_id') or 0)
    if lesson_id:
        old=allowed_lesson(c,user,lesson_id)
        check_version(old,data)
        if is_absent(old):
            raise ValueError('已请假的课程请先取消请假，再调整排课。')
        if old['status']!='scheduled' and user['role']!='owner':
            raise ValueError('已完成或取消课程仅老板可以编辑。')
    else:
        key=str(data.get('request_id',''))
        if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',key):
            raise ValueError('操作编号无效，请重新打开排课表单。')
        existing=c.execute('SELECT id FROM lessons WHERE request_id=?',(key,)).fetchone()
        if existing:
            return {'ok':True,'lesson_id':existing['id'],'duplicate':True}
    color=data.get('color',old['color'] if lesson_id else 'green')
    if color not in ('green','blue','purple','pink','orange','yellow','gray'):
        raise ValueError('请选择有效的课程颜色。')
    raw_students=data.get('student_ids') if isinstance(data.get('student_ids'), list) else []
    type_id, subject_id = resolve_catalog(c, data, len(set(raw_students)), data.get('title') or '')
    type_name = c.execute('SELECT name FROM course_types WHERE id=?', (type_id,)).fetchone()
    subject_name = c.execute('SELECT name FROM subjects WHERE id=?', (subject_id,)).fetchone() if subject_id else None
    if not data.get('title') and type_name:
        data = {**data, 'title': ((subject_name['name'] + ' · ') if subject_name else '') + type_name['name']}
    title=text_value(data.get('title'),'课程名称',80)
    try:
        teacher_id=int(data.get('teacher_id') or 0)
    except (TypeError, ValueError):
        raise ValueError('请选择有效的任课老师。')
    if not c.execute('SELECT 1 FROM teachers t JOIN users u ON t.user_id=u.id WHERE t.id=? AND u.active=1',(teacher_id,)).fetchone():
        raise ValueError('请选择有效的任课老师。')
    if subject_name and subject_name['name'] == SINGAPORE_SUBJECT:
        if not type_name or type_name['name'] not in ('一对一', '小班课'):
            raise ValueError('新加坡数学只有一对一和小班课。')
        boss = c.execute('''SELECT 1 FROM teachers t JOIN organization_owners o ON o.user_id=t.user_id WHERE t.id=?''', (teacher_id,)).fetchone()
        if not boss:
            raise ValueError('新加坡数学只由 Helen 授课。')
    start=datetime_value(data.get('starts_at'))
    end=datetime_value(data.get('ends_at'))
    if end<=start or end-start>dt.timedelta(hours=12):
        raise ValueError('结束时间必须晚于开始时间，单次课程最长 12 小时。')
    start,end=start.strftime('%Y-%m-%dT%H:%M'),end.strftime('%Y-%m-%dT%H:%M')
    raw=data.get('student_ids')
    allow_empty=bool(data.get('allow_empty'))
    if not isinstance(raw,list) or len(raw)>30 or (not allow_empty and len(raw)<1):
        raise ValueError('每节课请选择 1–30 位学生。')
    try:
        members=sorted(set(int(x) for x in raw))
    except (TypeError, ValueError):
        raise ValueError('请选择有效的学生。')
    profile_ids=[]
    for sid in members:
        account=c.execute('SELECT profile_id FROM students WHERE id=?',(sid,)).fetchone()
        if account: profile_ids.append(account['profile_id'])
    if len(profile_ids)!=len(set(profile_ids)):
        raise ValueError('同一节课，每位学生只能选择一个扣课科目。')
    if lesson_id and old['status']!='scheduled':
        original_members=sorted(x[0] for x in c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?',(lesson_id,)))
        if members!=original_members:raise ValueError('已完成或取消的课程需保留原学生关联，请在单据中更正扣费。')
    amount=units(data.get('amount'))
    location=str(data.get('location','')).strip()
    if len(location)>150:
        raise ValueError('上课地点不能超过 150 个字。')
    if c.execute("SELECT 1 FROM lessons WHERE teacher_id=? AND status!='cancelled' AND id!=? AND starts_at<? AND ends_at>?",(teacher_id,lesson_id,end,start)).fetchone():
        raise ValueError('这位老师在该时段已有课程，请调整时间或老师。')
    for sid in members:
        student=c.execute('SELECT name,archived FROM students WHERE id=?',(sid,)).fetchone()
        if not student:
            raise ValueError('所选学生不存在，请刷新后重试。')
        if student['archived']:
            raise ValueError('学生已归档，请先恢复档案再排课。')
        if c.execute("SELECT 1 FROM lesson_students ls JOIN lessons l ON ls.lesson_id=l.id JOIN students enrolled ON enrolled.id=ls.student_id WHERE enrolled.profile_id=(SELECT profile_id FROM students WHERE id=?) AND l.status!='cancelled' AND l.id!=? AND l.starts_at<? AND l.ends_at>?",(sid,lesson_id,end,start)).fetchone():
            raise ValueError(student['name']+'在该时段已有课程。')
    type_id, subject_id = courses_match_lesson(c, members, subject_id, type_id)
    type_name = c.execute('SELECT name FROM course_types WHERE id=?', (type_id,)).fetchone() if type_id else type_name
    subject_name = c.execute('SELECT name FROM subjects WHERE id=?', (subject_id,)).fetchone() if subject_id else None
    if subject_name and type_name:
        import pricing
        for sid in members:
            enrolled = c.execute('SELECT level_code FROM students WHERE id=?', (sid,)).fetchone()
            year = enrolled['level_code'] if enrolled and 'level_code' in enrolled.keys() else ''
            mapped = pricing.align_primary_class(subject_name['name'], type_name['name'], year)
            if mapped != subject_name['name']:
                raise ValueError('小学小班课是数学 + 英语，不能单独排数学或英语。')
    if subject_name and subject_name['name'] == SINGAPORE_SUBJECT:
        if not type_name or type_name['name'] not in ('一对一', '小班课'):
            raise ValueError('新加坡数学只有一对一和小班课。')
        boss = c.execute('''SELECT 1 FROM teachers t JOIN organization_owners o ON o.user_id=t.user_id WHERE t.id=?''', (teacher_id,)).fetchone()
        if not boss:
            raise ValueError('新加坡数学只由 Helen 授课。')
    if lesson_id:
        if old['status']!='scheduled':
            c.execute('INSERT INTO report_edits(lesson_id,actor_id,payload) VALUES(?,?,?)',(lesson_id,user['id'],json.dumps({'action':'owner_schedule_correction','before':dict(old),'after':data},ensure_ascii=False)))
        c.execute("UPDATE lessons SET title=?,teacher_id=?,starts_at=?,ends_at=?,planned_units=?,location=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(title,teacher_id,start,end,amount,location,lesson_id))
        c.execute('DELETE FROM lesson_students WHERE lesson_id=?',(lesson_id,))
        marks=','.join('?' for _ in members)
        c.execute(f'DELETE FROM lesson_reports WHERE lesson_id=? AND student_id NOT IN ({marks})',(lesson_id,*members))
    else:
        lesson_id=c.execute('INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id) VALUES(?,?,?,?,?,?,?,?)',(teacher_id,title,start,end,amount,location,user['id'],key)).lastrowid
    note = str(data.get('title_note') or '').strip()
    c.execute('UPDATE lessons SET color=?, course_type_id=?, subject_id=? WHERE id=?', (color, type_id, subject_id, lesson_id))
    if note:
        c.execute('UPDATE lessons SET title_note=? WHERE id=? AND title_note=?', (note[:200], lesson_id, ''))
    c.executemany('INSERT INTO lesson_students VALUES(?,?)',[(lesson_id,sid) for sid in members])
    return {'ok':True,'lesson_id':lesson_id}

def cancel_lesson(c,user,data,text_value):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有管理员可以取消课程。')
    lesson=allowed_lesson(c,user,data['lesson_id'])
    check_version(lesson,data)
    if lesson['status']!='scheduled':
        raise ValueError('只能取消未完成的课程。已完成的课时请通过账本撤销。')
    if is_absent(lesson):
        raise ValueError('已请假的课程请先取消请假。')
    scope=data.get('scope','single')
    if scope not in ('single','future'):raise ValueError('取消范围无效。')
    if scope=='future':
        if not lesson['series_id']:raise ValueError('这不是重复课程。')
        rule=c.execute('SELECT * FROM lesson_series WHERE id=?',(lesson['series_id'],)).fetchone()
        if int(data.get('series_version',0))!=rule['version']:raise ValueError('重复课程已被调整，请刷新后重试。')
    reason=str(data.get('reason') or '').strip()
    if len(reason)>250:
        raise ValueError('取消原因不能超过 250 个字。')
    import auditlog
    auditlog.begin(c)
    c.execute("UPDATE lessons SET status='cancelled',cancel_reason=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(reason,lesson['id']))
    if scope=='future':
        c.execute("UPDATE lessons SET status='cancelled',cancel_reason=?,version=version+1 WHERE series_id=? AND occurrence_index>? AND status='scheduled'",(reason,lesson['series_id'],lesson['occurrence_index']))
        c.execute("UPDATE lesson_series SET stop_index=MIN(COALESCE(stop_index,?),?),error='',version=version+1 WHERE id=?",(lesson['occurrence_index'],lesson['occurrence_index'],lesson['series_id']))
    elif lesson['series_id']:
        c.execute('UPDATE lesson_series SET version=version+1 WHERE id=?',(lesson['series_id'],))
    if data.get('charge') is True:
        apply_late_leave(c, lesson)
    auditlog.hint(c, '取消课程' + ('并扣课时' if data.get('charge') is True else ''))
    auditlog.finish(c, user)
    return {'ok':True}

def _absence_columns(c):
    cols = {r['name'] for r in c.execute('PRAGMA table_info(lessons)')}
    return 'absent' in cols and 'absent_charge' in cols

def _reverse_absence_ledger(c, user, ledger_id):
    """Put a 请假 deduction back. A second undo finds the reversal and does nothing."""
    original = c.execute('SELECT * FROM ledger WHERE id=?', (ledger_id,)).fetchone()
    if not original or original['kind'] == 'reversal':
        return
    if c.execute('SELECT 1 FROM ledger WHERE reversal_of=?', (original['id'],)).fetchone():
        return
    request_id = 'undo-absent-%s-%s' % (original['id'], secrets.token_hex(8))
    lid = c.execute(
        "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of) VALUES(?,?,?,?,?,?,?,?)",
        (original['student_id'], -int(original['delta'] or 0), 'reversal', now_local().date().isoformat(),
         '取消请假，退回课时', user['id'], request_id, original['id'])).lastrowid
    credit_batches.apply(c, lid, 'reversal', {}, lambda raw: 0, original)

def release_absence(c, user, lesson_id, student_id=None, clear=False):
    """Reverse absence deductions. clear=True also returns the lesson to a normal schedule row.

    Callers that cancel or drop the lesson pass clear=True for a lesson with no
    remaining students. One student leaving a shared lesson only reverses that student.
    """
    if not _absence_columns(c):
        return 0
    lesson = c.execute('SELECT id, absent FROM lessons WHERE id=?', (lesson_id,)).fetchone()
    if not lesson:
        return 0
    table = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_absence_charges'").fetchone()
    if student_id is None:
        rows = list(c.execute('SELECT * FROM lesson_absence_charges WHERE lesson_id=?', (lesson_id,))) if table else []
    else:
        rows = list(c.execute('SELECT * FROM lesson_absence_charges WHERE lesson_id=? AND student_id=?', (lesson_id, student_id))) if table else []
    if not int(lesson['absent'] or 0) and not rows:
        return 0
    for row in rows:
        _reverse_absence_ledger(c, user, row['ledger_id'])
        c.execute('DELETE FROM lesson_absence_charges WHERE lesson_id=? AND student_id=?', (row['lesson_id'], row['student_id']))
    if clear:
        c.execute('UPDATE lessons SET absent=0, absent_charge=0 WHERE id=?', (lesson_id,))
    elif table and not c.execute('SELECT 1 FROM lesson_absence_charges WHERE lesson_id=?', (lesson_id,)).fetchone():
        c.execute('UPDATE lessons SET absent_charge=0 WHERE id=?', (lesson_id,))
    return len(rows)

def mark_absent(c, user, data, units):
    """Mark one scheduled lesson 请假. charge is chosen for this lesson alone.

    A charged absence deducts each student's balance the same way an attended
    lesson does, and does not create a lesson report. Teacher pay is not
    decided here; see payroll.absence_pay_clause.
    """
    require_scheduler(c, user, data)
    lesson = allowed_lesson(c, user, data['lesson_id'])
    check_version(lesson, data)
    if lesson['status'] != 'scheduled':
        raise ValueError('只能为未完成的课程请假。')
    if is_absent(lesson):
        raise ValueError('这节课已经请假。')
    charge = data.get('charge')
    if type(charge) is not bool:
        raise ValueError('请选择扣课时或不扣课时。')
    members = [dict(row) for row in c.execute(
        'SELECT s.id, s.name, s.balance, s.billing_unit FROM lesson_students ls JOIN students s ON s.id=ls.student_id WHERE ls.lesson_id=? ORDER BY s.id',
        (lesson['id'],))]
    charges = []
    if charge:
        for student in members:
            amount = lesson_charge_units(lesson, student['billing_unit'], units)
            available = c.execute('SELECT COALESCE(SUM(paid_left+gift_left),0) AS n FROM credit_batches WHERE student_id=?', (student['id'],)).fetchone()['n']
            if student['balance'] < amount or available < amount:
                raise ValueError(student['name'] + '的剩余课时不足。本次没有扣除任何学生的课时。')
            charges.append((student['id'], amount))
    for sid, amount in charges:
        request_id = 'absent-%s-student-%s-v%s' % (lesson['id'], sid, lesson['version'])
        ledger_id = c.execute(
            "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,?,?,?)",
            (sid, -amount, lesson['starts_at'][:10], (lesson['title'] or '课程') + ' · 请假扣课时', user['id'], request_id)).lastrowid
        credit_batches.apply(c, ledger_id, 'lesson', {}, units)
        c.execute('INSERT INTO lesson_absence_charges(lesson_id,student_id,ledger_id) VALUES(?,?,?)', (lesson['id'], sid, ledger_id))
    c.execute(
        "UPDATE lessons SET absent=1, absent_charge=?, version=version+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (1 if charge else 0, lesson['id']))
    return {'ok': True, 'absent': True, 'charged': charge}

def undo_absent(c, user, data):
    """Return one absence to a normal scheduled lesson and reverse any deduction."""
    require_scheduler(c, user, data)
    lesson = allowed_lesson(c, user, data['lesson_id'])
    check_version(lesson, data)
    if lesson['status'] != 'scheduled' or not is_absent(lesson):
        raise ValueError('这节课没有请假。' if lesson['status'] == 'scheduled' else '只能取消仍在课表上的请假。')
    release_absence(c, user, lesson['id'], clear=True)
    c.execute("UPDATE lessons SET absent=0, absent_charge=0, version=version+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (lesson['id'],))
    return {'ok': True, 'absent': False}

def apply_late_leave(c, lesson):
    """A cancellation inside 48 hours uses one lesson when the balance allows. Otherwise it is recorded as arrears and the balance stays put."""
    try:
        start = datetime_value(lesson['starts_at'])
    except (ValueError, TypeError):
        return
    now = now_local()
    if start.tzinfo is not None and now.tzinfo is None:
        start = start.replace(tzinfo=None)
    if now.tzinfo is not None and start.tzinfo is None:
        now = now.replace(tzinfo=None)
    gap = (start - now).total_seconds()
    if gap <= 0 or gap > 48 * 3600:
        return
    import credit_batches
    for row in c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?', (lesson['id'],)):
        student = c.execute('SELECT balance, billing_unit FROM students WHERE id=?', (row['student_id'],)).fetchone()
        if not student:
            continue
        amount = 100 if (student['billing_unit'] or 'lesson') != 'hour' else int(lesson['planned_units'] or 100)
        available = c.execute('SELECT COALESCE(SUM(paid_left+gift_left),0) AS n FROM credit_batches WHERE student_id=?', (row['student_id'],)).fetchone()['n']
        if amount > 0 and student['balance'] >= amount and available >= amount:
            import secrets
            ledger = c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'lesson',?,'48小时内请假，扣一节课',?,?)",
                (row['student_id'], now_local().date().isoformat(), lesson['created_by'] or 1, secrets.token_hex(16))).lastrowid
            credit_batches.consume(c, ledger, row['student_id'], amount)
            credit_batches.finish(c, ledger)
        else:
            c.execute('INSERT INTO arrears(student_id,lesson_id,amount,reason) VALUES(?,?,?,?)',
                (row['student_id'], lesson['id'], amount, '48小时内请假，余额不足'))

def save_reports(c,user,data,units,action):
    lesson=allowed_lesson(c,user,data['lesson_id'])
    if is_absent(lesson):
        raise ValueError('已请假的课程不用填写课后记录。需要上课请先取消请假。')
    closing=action in ('complete','close')
    if closing and lesson['status']=='completed':
        return {'ok':True,'duplicate':True}
    check_version(lesson,data)
    if lesson['status']=='cancelled':
        raise ValueError('已取消的课程不能填写或发布课后记录。')
    if closing and lesson['ends_at']>now_local().strftime('%Y-%m-%dT%H:%M'):
        raise ValueError('课程尚未结束，可先保存草稿，结束后再确认完成。')
    if action=='draft' and lesson['status']!='scheduled':
        raise ValueError('已完成课程请使用修改课后记录。')
    if action=='edit' and lesson['status']!='completed':
        raise ValueError('课程尚未完成，请先填写并确认完成。')
    if action=='close' and user['role'] not in ('owner','admin'):
        raise AccessError('只有老板或管理员可以这样确认上课。')
    members={x['student_id'] for x in c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?',(lesson['id'],))}
    raw=data.get('reports')
    if not isinstance(raw,list) or len(raw)!=len(members) or {int(x['student_id']) for x in raw}!=members:
        raise ValueError('请为这节课的每位学生填写记录。')
    cleaned=[]
    for item in raw:
        sid=int(item['student_id'])
        content=str(item.get('content','')).strip()
        homework=str(item.get('homework','')).strip()
        feedback=str(item.get('feedback','')).strip()
        if any(len(x)>2000 for x in (content,homework,feedback)):
            raise ValueError('学习内容、今日作业和课后反馈各最多 2000 字。')
        if action not in ('draft','close') and (not content or not homework or not feedback):
            raise ValueError('请填写学习内容、今日作业和课后反馈；没有作业可填写“今日无作业”。')
        account=c.execute('SELECT billing_unit FROM students WHERE id=?',(sid,)).fetchone()
        default_amount=round((dt.datetime.fromisoformat(lesson['ends_at'])-dt.datetime.fromisoformat(lesson['starts_at'])).total_seconds()/3600,2) if account['billing_unit']=='hour' else lesson['planned_units']/100
        planned=units(default_amount)
        amount=units(item.get('amount',default_amount))
        if user['role']=='teacher' and amount!=planned:
            raise AccessError('老师不能修改课时数量。')
        if user['role']!='owner':
            item['fee_amount']=None
        old=c.execute('SELECT * FROM lesson_reports WHERE lesson_id=? AND student_id=?',(lesson['id'],sid)).fetchone()
        if action=='edit' and (not old or (amount!=old['amount'] and user['role']!='owner')):
            raise ValueError('修改反馈不会改变课时。需要调整扣费请由管理员在账本中处理。')
        if closing:
            student=c.execute('SELECT name,balance FROM students WHERE id=?',(sid,)).fetchone()
            if student['balance']<amount:
                raise ValueError(student['name']+'的剩余课时不足。本次尚未扣除任何学生的课时，可先保存草稿。')
        cleaned.append((sid,amount,content,homework,feedback,item.get('fee_amount')))
    # All validation precedes writes; the caller commits all students atomically.
    for sid,amount,content,homework,feedback,fee_amount in cleaned:
        if action=='edit' and user['role']=='owner':
            previous=c.execute('SELECT * FROM lesson_reports WHERE lesson_id=? AND student_id=?',(lesson['id'],sid)).fetchone()
            if previous and previous['amount']!=amount:
                import record_edits
                entry=c.execute('SELECT * FROM ledger WHERE id=?',(previous['ledger_id'],)).fetchone()
                record_edits.edit(c,user,{'entry_id':entry['id'],'version':entry['version'],'amount':str(amount/100),'date':entry['lesson_date'],'note':entry['note'],'reason':'老板修改课后记录扣除数量'},units,lambda raw,label,maximum: str(raw).strip())
        c.execute("INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,updated_by) VALUES(?,?,?,?,?,?,?) ON CONFLICT(lesson_id,student_id) DO UPDATE SET amount=excluded.amount,content=excluded.content,homework=excluded.homework,feedback=excluded.feedback,updated_by=excluded.updated_by,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",(lesson['id'],sid,amount,content,homework,feedback,user['id']))
        if closing:
            ledger_id=c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,?,?,?)",(sid,-amount,lesson['starts_at'][:10],lesson['title']+' · 课后记录',user['id'],f"scheduled-{lesson['id']}-student-{sid}")).lastrowid
            credit_batches.apply(c,ledger_id,'lesson',{},units)
            import payroll
            computed,_,_=payroll.fee_for_ledger(c,ledger_id,amount)
            millis = payroll.indexed_fee_millis(c, ledger_id)
            if '试听' in (lesson['title'] or '') and not str(fee_amount or '').strip():
                import pricing
                kind = c.execute('''SELECT ct.name FROM students s LEFT JOIN course_types ct ON ct.id=s.course_type_id WHERE s.id=?''', (sid,)).fetchone()
                product = pricing.TYPE_PRODUCT.get(kind['name'] if kind and kind['name'] else '', 'one_to_one')
                length = max(1, int((dt.datetime.fromisoformat(lesson['ends_at']) - dt.datetime.fromisoformat(lesson['starts_at'])).total_seconds() // 60))
                snapped = (150 if length >= 135 else 120) if product == 'term' else (90 if length >= 75 else 60)
                single = pricing.list_lesson_cents(c, sid, lesson['starts_at'][:10], product, snapped)
                if single:
                    computed = pricing.trial_cents(single)
                    millis = computed * 10
            elif computed is None and not str(fee_amount or '').strip():
                import pricing
                computed = pricing.charged_fee_cents(c, sid, lesson, amount)
                if computed is not None:
                    millis = computed * 10
            if str(fee_amount or '').strip():
                import accounting
                overridden = accounting.money(fee_amount)
                c.execute('UPDATE lesson_reports SET ledger_id=?,fee_cents=?,fee_millis=?,fee_overridden=1 WHERE lesson_id=? AND student_id=?',(ledger_id,overridden,overridden*10,lesson['id'],sid))
            else:
                c.execute('UPDATE lesson_reports SET ledger_id=?,fee_cents=?,fee_millis=?,fee_overridden=0 WHERE lesson_id=? AND student_id=?',(ledger_id,computed,millis,lesson['id'],sid))
    c.execute("UPDATE lessons SET status=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",('completed' if action in ('complete','edit','close') else 'scheduled',lesson['id']))
    c.execute('INSERT INTO report_edits(lesson_id,actor_id,payload) VALUES(?,?,?)',(lesson['id'],user['id'],json.dumps({'action':action,'reports':raw},ensure_ascii=False)))
    return {'ok':True}


def save_option(c,user,data,text_value):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有老板或管理员可以设置课程与地点。')
    kind=data.get('kind')
    if kind not in ('course','location'):
        raise ValueError('选项类型无效。')
    name=text_value(data.get('name'),'选项名称',80 if kind=='course' else 150)
    active=data.get('active',True)
    if type(active) is not bool:
        raise ValueError('选项状态无效。')
    option_id=int(data.get('id') or 0)
    if option_id and not c.execute('SELECT 1 FROM schedule_options WHERE id=? AND kind=?',(option_id,kind)).fetchone():
        raise ValueError('选项不存在，请刷新页面。')
    if c.execute('SELECT 1 FROM schedule_options WHERE kind=? AND name=? AND id!=?',(kind,name,option_id)).fetchone():
        raise ValueError('已有同名选项，请编辑或启用原选项。')
    if option_id:
        c.execute('UPDATE schedule_options SET name=?,active=? WHERE id=?',(name,int(active),option_id))
    else:
        option_id=c.execute('INSERT INTO schedule_options(kind,name,active) VALUES(?,?,?)',(kind,name,int(active))).lastrowid
    return {'ok':True,'id':option_id}


def duty_value(data):
    """Optional title. Missing or blank is stored as NULL. At most 60 characters."""
    if 'duty' not in data:
        return None
    text=str(data.get('duty') or '').strip()
    if len(text)>60:
        raise ValueError('职责最多 60 个字。')
    return text or None

def subject_values(data,text_value):
    raw=data.get('subjects')
    if raw is None: raw=[data.get('subject')]
    if not isinstance(raw,list) or not 1<=len(raw)<=20:
        raise ValueError('请选择 1–20 个教学科目。')
    return list(dict.fromkeys(text_value(x,'教学科目',80) for x in raw))

def managed_teacher(c,user,data):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有老板或管理员可以管理老师。')
    t=c.execute("SELECT t.*,u.name,u.phone,u.role,u.active,EXISTS(SELECT 1 FROM organization_owners o WHERE o.user_id=u.id) is_owner FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.id=?",(int(data.get('teacher_id',0)),)).fetchone()
    if not t: raise ValueError('老师不存在，请刷新页面。')
    if (t['is_owner'] or t['role']=='admin') and user['role']!='owner':
        raise AccessError('管理员兼任老师的资料仅可由老板修改。')
    return t

def edit_teacher(c,user,data,phone_value,password_hash,text_value):
    t=managed_teacher(c,user,data)
    subjects=subject_values(data,text_value)
    if t['is_owner'] or t['role']=='admin':
        if any(k in data for k in ('name','phone','password')):
            raise ValueError('管理账号请在管理员页面或个人账号中修改，此处仅编辑教学科目。')
    else:
        name=text_value(data.get('name'),'老师姓名',40)
        phone=phone_value(data.get('phone'))
        password=str(data.get('password',''))
        if password and not 10<=len(password)<=128:raise ValueError('新密码需为 10–128 位。')
        if c.execute('SELECT 1 FROM users WHERE phone=? AND id!=?',(phone,t['user_id'])).fetchone():
            raise ValueError('此手机号已被其他账号使用。')
        c.execute('UPDATE users SET name=?,phone=? WHERE id=?',(name,phone,t['user_id']))
        if password:c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),t['user_id']))
        if password or phone!=t['phone']:c.execute('DELETE FROM sessions WHERE user_id=?',(t['user_id'],))
    fields=['subject=?','subjects=?']
    params=['、'.join(subjects), json.dumps(subjects,ensure_ascii=False)]
    if 'duty' in data:
        fields.append('duty=?')
        params.append(duty_value(data))
    params.append(t['id'])
    c.execute('UPDATE teachers SET '+','.join(fields)+' WHERE id=?', params)
    return {'ok':True}

def teacher_status(c,user,data):
    t=managed_teacher(c,user,data)
    if t['is_owner'] or t['role']=='admin':
        raise ValueError('管理员兼任老师的账号不能在此停用，请在管理员页面处理。')
    active=data.get('active')
    if type(active) is not bool:raise ValueError('账号状态无效。')
    c.execute('UPDATE users SET active=? WHERE id=?',(int(active),t['user_id']))
    c.execute('DELETE FROM sessions WHERE user_id=?',(t['user_id'],))
    return {'ok':True}
