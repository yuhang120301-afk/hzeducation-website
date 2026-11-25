"""Lesson prices, year levels, and package quotes.

Prices are effective by the payment date. A student's own price wins over the
table. Nothing here is shown to parents, teachers, or the front desk.
"""
import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP

from teaching import AccessError, now_local

LEVELS = ('K', 'Prep', 'Y1', 'Y2', 'Y3', 'Y4', 'Y5', 'Y6', 'Y7', 'Y8', 'Y9', 'Y10', 'Y11', 'Y12')
# Kindergarten stays in LEVELS so old codes and price bands still parse. It is not offered.
SELECTABLE_LEVELS = tuple(code for code in LEVELS if code != 'K')
ENROL_YEAR = 2027
PRODUCTS = ('one_to_one', 'one_to_two', 'helen', 'term')
PRODUCT_LABELS = {'one_to_one': '1:1', 'one_to_two': '1:2', 'helen': 'Helen 本人 1:1', 'term': '学期班'}
TERM_COUNTS = {'T1': 8, 'T2': 10, 'T3': 9, 'T4': 10}
LENGTHS = (60, 90, 120, 150)
SEED_KEY = 'price_seed_2027'

# product, level from, level to, hourly cents, lesson minutes (term length; private lessons ignore it)
SEED_ROWS = (
    ('one_to_one', 'Prep', 'Y6', 8500, 60),
    ('one_to_one', 'Y7', 'Y8', 9000, 60),
    ('one_to_one', 'Y9', 'Y10', 10000, 60),
    ('one_to_one', 'Y11', 'Y11', 11000, 60),
    ('one_to_one', 'Y12', 'Y12', 12000, 60),
    ('one_to_two', 'Prep', 'Y1', 5000, 60),
    ('one_to_two', 'Y2', 'Y2', 5500, 60),
    ('one_to_two', 'Y3', 'Y6', 6000, 60),
    ('one_to_two', 'Y7', 'Y8', 7000, 60),
    ('one_to_two', 'Y9', 'Y10', 8500, 60),
    ('one_to_two', 'Y11', 'Y11', 9500, 60),
    ('one_to_two', 'Y12', 'Y12', 10000, 60),
    ('helen', 'K', 'Y10', 12000, 60),
    ('helen', 'Y11', 'Y12', 15000, 60),
    ('term', 'K', 'Y6', 4500, 150),
    ('term', 'Y7', 'Y8', 5000, 120),
    ('term', 'Y9', 'Y10', 6000, 120),
    ('term', 'Y11', 'Y12', 7500, 120),
)


def schema(c):
    cols = {r['name'] for r in c.execute('PRAGMA table_info(students)')}
    if 'level_code' not in cols:
        c.execute("ALTER TABLE students ADD COLUMN level_code TEXT NOT NULL DEFAULT ''")
    if 'level_year' not in cols:
        c.execute('ALTER TABLE students ADD COLUMN level_year INTEGER NOT NULL DEFAULT 0')
    if 'study_level' not in cols:
        c.execute("ALTER TABLE students ADD COLUMN study_level TEXT NOT NULL DEFAULT ''")
    c.executescript('''
    CREATE TABLE IF NOT EXISTS price_tables (
        id INTEGER PRIMARY KEY,
        effective_from TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE IF NOT EXISTS price_rows (
        id INTEGER PRIMARY KEY,
        table_id INTEGER NOT NULL REFERENCES price_tables(id),
        product TEXT NOT NULL,
        level_from TEXT NOT NULL,
        level_to TEXT NOT NULL,
        hourly_cents INTEGER NOT NULL CHECK(hourly_cents>=0),
        lesson_minutes INTEGER NOT NULL DEFAULT 60,
        UNIQUE(table_id, product, level_from, level_to)
    );
    CREATE TABLE IF NOT EXISTS student_prices (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        product TEXT NOT NULL,
        lesson_minutes INTEGER NOT NULL,
        per_lesson_cents INTEGER NOT NULL CHECK(per_lesson_cents>=0),
        note TEXT NOT NULL DEFAULT '',
        updated_by INTEGER NOT NULL REFERENCES users(id),
        UNIQUE(profile_id, product, lesson_minutes)
    );
    ''')
    seed_2027(c)
    import teaching
    teaching.ensure_catalogs(c)
    ensure_enrolment_price(c)
    cols = {r['name'] for r in c.execute('PRAGMA table_info(price_tables)')}
    if 'validity_note' not in cols:
        c.execute("ALTER TABLE price_tables ADD COLUMN validity_note TEXT NOT NULL DEFAULT ''")
    publish_seed(c)
    ensure_subject_prices(c)
    ensure_combo_price(c)


def product_for(c, type_name):
    """The price product stored on the course type. A blank type has no price yet."""
    if c is not None and type_name:
        row = c.execute('SELECT product FROM course_types WHERE name=?', (type_name,)).fetchone()
        if row is not None:
            return row['product'] or ''
    return TYPE_PRODUCT.get(type_name or '', '')


def ensure_combo_price(c):
    """数学加英语 has one combined hourly price, used at Prep, separate from 数学 and 英语."""
    if c.execute("SELECT 1 FROM app_meta WHERE key='combo_price_v1'").fetchone():
        return
    table = c.execute("SELECT id FROM price_tables WHERE effective_from='2027-01-01'").fetchone()
    if not table:
        return
    c.execute('''INSERT OR IGNORE INTO price_rows(table_id,product,level_from,level_to,hourly_cents,lesson_minutes)
        VALUES(?,?,?,?,?,?)''', (table['id'], COMBO_PRODUCT, COMBO_LEVEL, COMBO_LEVEL, COMBO_HOURLY_CENTS, 60))
    if c.execute("SELECT 1 FROM pragma_table_info('price_rows') WHERE name='placeholder'").fetchone():
        c.execute('UPDATE price_rows SET placeholder=0 WHERE product=?', (COMBO_PRODUCT,))
    c.execute("INSERT INTO app_meta(key,value) VALUES('combo_price_v1','1')")


def seed_2027(c):
    if c.execute('SELECT 1 FROM app_meta WHERE key=?', (SEED_KEY,)).fetchone():
        return
    actor = c.execute('SELECT user_id FROM organization_owners ORDER BY user_id LIMIT 1').fetchone()
    actor_id = actor['user_id'] if actor else (c.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone() or {'id': None})['id']
    if not actor_id:
        return
    table_id = c.execute('INSERT INTO price_tables(effective_from,label,created_by) VALUES(?,?,?)',
        ('2027-01-01', '2027 价目（不含 GST）', actor_id)).lastrowid
    c.executemany('''INSERT INTO price_rows(table_id,product,level_from,level_to,hourly_cents,lesson_minutes)
        VALUES(?,?,?,?,?,?)''', [(table_id, *row) for row in SEED_ROWS])
    c.execute('INSERT INTO app_meta(key,value) VALUES(?,?)', (SEED_KEY, '1'))


def publish_seed(c):
    """Attach the 2027 bands to course types and clear the 暂定 flag. Edited rows stay."""
    import teaching
    table = c.execute("SELECT id FROM price_tables WHERE effective_from='2027-01-01'").fetchone()
    if not table:
        return
    names = {'one_to_one': '一对一', 'one_to_two': '一对二', 'term': '小班课'}
    for product, label in names.items():
        kind = c.execute('SELECT id FROM course_types WHERE name=?', (label,)).fetchone()
        if not kind:
            continue
        c.execute('''UPDATE price_rows SET course_type_id=?, placeholder=0
            WHERE table_id=? AND product=? AND IFNULL(placeholder,1)=1''', (kind['id'], table['id'], product))
        c.execute('''UPDATE price_rows SET course_type_id=?
            WHERE table_id=? AND product=? AND course_type_id IS NULL''', (kind['id'], table['id'], product))


TYPE_PRODUCT = {'一对一': 'one_to_one', '一对二': 'one_to_two', '小班课': 'term'}
COMBO_SUBJECT = '数学加英语'
COMBO_PRODUCT = 'maths_english'
COMBO_LEVEL = 'Prep'
COMBO_HOURLY_CENTS = 8500
LEGACY_SUBJECTS = ('数学', '英语')
SUBJECT_PRICE_KEY = 'legacy_subject_prices_v1'
SINGAPORE_LEVELS = ('Y7', 'Y8', 'Y9', 'Y10')
SINGAPORE_TYPES = ('一对一', '小班课')
SINGAPORE_NEW_CENTS = 15000
SINGAPORE_OLD_CENTS = 12000


def ensure_enrolment_price(c):
    """One nullable hourly override on the enrolment row. NULL uses the catalog. 0 is free."""
    cols = {r['name'] for r in c.execute('PRAGMA table_info(students)')}
    if 'custom_hourly_cents' not in cols:
        c.execute('ALTER TABLE students ADD COLUMN custom_hourly_cents INTEGER')


def enrolment_hourly(student):
    """The enrolment's own hourly cents, including 0. None means the field is empty."""
    if not student:
        return None
    keys = student.keys() if hasattr(student, 'keys') else ()
    if 'custom_hourly_cents' not in keys:
        return None
    value = student['custom_hourly_cents']
    if value is None:
        return None
    return int(value)


def singapore_list_hourly(student):
    """New students are $150/hour. Helen's original students default to $120/hour."""
    original = 0
    if student is not None:
        try:
            original = int(student['helen_original'] or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            original = 0
    return SINGAPORE_OLD_CENTS if original else SINGAPORE_NEW_CENTS


def assert_singapore_enrolment(subject_name, type_name, level_code):
    import teaching
    if not teaching.singapore_subject(subject_name):
        return
    if type_name not in SINGAPORE_TYPES:
        raise ValueError('新加坡数学只有一对一和小班课。')
    if level_code not in SINGAPORE_LEVELS:
        raise ValueError('新加坡数学只开设 Year 7 到 Year 10。')


def canonical_subject(text):
    """数学 and 英语 collapse longer labels. VCE maths and 新加坡数学 stay separate."""
    raw = str(text or '').strip()
    import teaching
    named = teaching.vce_subject(raw) or teaching.singapore_subject(raw)
    if named:
        return named
    if '数学' in raw:
        return '数学'
    if '英语' in raw:
        return '英语'
    return raw


def _field(row, key):
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def subject_of(c, student):
    named = canonical_subject(_field(student, 'subject_name'))
    if named:
        return named
    subject_id = _field(student, 'subject_id')
    if subject_id:
        row = c.execute('SELECT name FROM subjects WHERE id=?', (int(subject_id),)).fetchone()
        if row and row['name']:
            return canonical_subject(row['name'])
    return canonical_subject(_field(student, 'course'))


def ensure_subject_prices(c):
    """Copy each old single price onto 数学 and 英语. New table only: no rebuild, no VACUUM."""
    c.execute('''CREATE TABLE IF NOT EXISTS student_subject_prices (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        product TEXT NOT NULL,
        subject TEXT NOT NULL,
        lesson_minutes INTEGER NOT NULL,
        per_lesson_cents INTEGER NOT NULL CHECK(per_lesson_cents>=0),
        note TEXT NOT NULL DEFAULT '',
        updated_by INTEGER NOT NULL,
        UNIQUE(profile_id, product, subject, lesson_minutes)
    )''')
    if c.execute('SELECT 1 FROM app_meta WHERE key=?', (SUBJECT_PRICE_KEY,)).fetchone():
        return
    names = {}
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='students'").fetchone():
        subjects_ready = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='subjects'").fetchone()
        for row in c.execute('SELECT profile_id, course, subject_id FROM students'):
            label = ''
            if row['subject_id'] and subjects_ready:
                found = c.execute('SELECT name FROM subjects WHERE id=?', (row['subject_id'],)).fetchone()
                label = found['name'] if found else ''
            label = canonical_subject(label or row['course'] or '')
            if label:
                names.setdefault(row['profile_id'], set()).add(label)
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_prices'").fetchone():
        for row in c.execute('SELECT profile_id, product, lesson_minutes, per_lesson_cents, note, updated_by FROM student_prices'):
            targets = set(LEGACY_SUBJECTS)
            targets.update(names.get(row['profile_id'], ()))
            for subject in targets:
                c.execute('''INSERT OR IGNORE INTO student_subject_prices
                    (profile_id, product, subject, lesson_minutes, per_lesson_cents, note, updated_by)
                    VALUES(?,?,?,?,?,?,?)''',
                    (row['profile_id'], row['product'], subject, row['lesson_minutes'],
                     row['per_lesson_cents'], row['note'] or '老学员', row['updated_by']))
    c.execute('INSERT OR IGNORE INTO app_meta(key,value) VALUES(?,?)', (SUBJECT_PRICE_KEY, '1'))


def subject_custom_rows(c, profile_id, product, subject):
    if not profile_id or not product or not subject:
        return []
    ensure_subject_prices(c)
    return c.execute('''SELECT lesson_minutes, per_lesson_cents, product, subject FROM student_subject_prices
        WHERE profile_id=? AND product=? AND subject=?''', (profile_id, product, subject)).fetchall()


def profile_custom_rows(c, profile_id):
    if not profile_id:
        return []
    ensure_subject_prices(c)
    return c.execute('''SELECT lesson_minutes, per_lesson_cents, product, subject FROM student_subject_prices
        WHERE profile_id=?''', (profile_id,)).fetchall()


def subject_lesson_cents(c, profile_id, product, subject, minutes):
    if not profile_id or not product or not subject:
        return None
    ensure_subject_prices(c)
    row = c.execute('''SELECT per_lesson_cents FROM student_subject_prices
        WHERE profile_id=? AND product=? AND subject=? AND lesson_minutes=?''',
        (profile_id, product, subject, int(minutes))).fetchone()
    return row['per_lesson_cents'] if row else None


def price_differs(rows, level, item):
    band = matching_row(rows, item['product'], level) if level else None
    if not band:
        return True
    return int(item['per_lesson_cents']) != per_lesson_cents(band['hourly_cents'], item['lesson_minutes'])


def hourly_from_custom(customs):
    custom_hourly = None
    for row in customs:
        if row['lesson_minutes'] == 60:
            custom_hourly = row['per_lesson_cents']
    if custom_hourly is None and customs:
        sample = customs[0]
        minutes = sample['lesson_minutes'] or 60
        custom_hourly = int((Decimal(sample['per_lesson_cents']) * 60 / Decimal(minutes)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return custom_hourly


def legacy_subject_names(rows, level, customs):
    found = []
    for subject in dict.fromkeys(row['subject'] for row in customs):
        subject_rows = [row for row in customs if row['subject'] == subject]
        if any(price_differs(rows, level, row) for row in subject_rows):
            found.append(subject)
    order = {name: index for index, name in enumerate(LEGACY_SUBJECTS)}
    found.sort(key=lambda name: (order.get(name, 99), name))
    return found


def _empty_offer(level, name, product, validity, reason):
    return {'level': level or '', 'course_type': name, 'product': product, 'hourly_cents': None,
        'packages': [], 'validity': validity, 'source': '', 'reason': reason}


def singapore_package(name, product, hourly, minutes):
    """20 paid lessons and no gift. The regular 20+1 pack is not used."""
    each = per_lesson_cents(hourly, minutes)
    total = each * 20
    prices = [value * 10 for value in lesson_prices_cents(total, 20)]
    return {'label': f'{name} 20 节 · {length_label(minutes)} · {money_millis(total * 10)} · 每节 {money_millis(prices[0])}',
        'paid_lessons': 20, 'gift_lessons': 0, 'lesson_minutes': minutes, 'total_cents': total,
        'each_millis': prices[0] if prices else 0, 'unit_fees': prices, 'terms': [], 'product': product,
        'discount_percent': 0, 'validity': '永久有效'}


def singapore_offer(student, level, name, validity):
    """Singapore Maths has its own hourly price. It does not read price_rows."""
    stored = stored_level(dict(student)) if student else str(level or '')
    product = TYPE_PRODUCT.get(name)
    if name not in SINGAPORE_TYPES:
        return _empty_offer(stored, name, product, validity, '新加坡数学只有一对一和小班课。')
    if stored not in SINGAPORE_LEVELS:
        return _empty_offer(stored, name, product, validity, '新加坡数学只开设 Year 7 到 Year 10。')
    override = enrolment_hourly(student)
    hourly = override if override is not None else singapore_list_hourly(student)
    packages = [singapore_package(name, product, hourly, minutes) for minutes in (60, 90)]
    return {'level': stored, 'course_type': name, 'product': product, 'product_label': name,
        'hourly_cents': hourly, 'lesson_minutes': 60, 'packages': packages,
        'validity': validity, 'source': 'custom' if override is not None else 'catalog', 'reason': ''}


def combo_offer(c, student, level, name, product, validity, on):
    """One combined hourly price for 数学加英语, used at Prep. It does not follow 数学 or 英语."""
    stored = stored_level(dict(student)) if student else str(level or '')
    if not name:
        return _empty_offer(stored, name, product, validity, '请先选择年级和课程类型。')
    if not product:
        return _empty_offer(stored, name, '', validity, '还没有价格')
    if stored != COMBO_LEVEL:
        return _empty_offer(stored, name, COMBO_PRODUCT, validity, '数学加英语的价格用在 Prep。')
    table = table_on(c, on.isoformat())
    rows = [dict(row) for row in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))] if table else []
    band = matching_row(rows, COMBO_PRODUCT, COMBO_LEVEL)
    if not band:
        return _empty_offer(stored, name, COMBO_PRODUCT, validity, '还没有价格')
    hourly = int(band['hourly_cents'])
    each = per_lesson_cents(hourly, 60)
    total = each * 10
    prices = [value * 10 for value in lesson_prices_cents(total, 10)]
    package = {
        'label': f'数学加英语 10 节 · {money_millis(total * 10)} · 每节 {money_millis(prices[0] if prices else 0)}',
        'paid_lessons': 10, 'gift_lessons': 0, 'lesson_minutes': 60, 'total_cents': total,
        'each_millis': prices[0] if prices else 0, 'unit_fees': prices, 'terms': [],
        'product': COMBO_PRODUCT, 'discount_percent': 0, 'validity': validity or '永久有效',
    }
    return {'level': stored, 'course_type': name, 'product': COMBO_PRODUCT, 'product_label': name,
        'hourly_cents': hourly, 'lesson_minutes': 60, 'packages': [package],
        'validity': validity, 'source': 'catalog', 'reason': ''}


def presets(c, user, student_id=None, level=None, course_type_id=None, day=None, subject_id=None):
    """Packages that match one year level and one course type. Helen's own rate is never included.

    新加坡数学 does not use this table. New students are $150/hour, old students $120/hour,
    and an enrolment can replace that with its own hourly rate, including $0.
    """
    require_owner(user)
    import teaching
    on = dt.date.fromisoformat(str(day)) if day else now_local().date()
    student = None
    if student_id:
        student = c.execute('SELECT * FROM students WHERE id=? AND archived=0', (int(student_id),)).fetchone()
        if not student:
            raise ValueError('学生不存在。')
        level = annotate(dict(student), on)['level_price'] or level
        course_type_id = course_type_id or student['course_type_id'] or _type_from_text(c, student)
    name = ''
    if course_type_id:
        kind = c.execute('SELECT name FROM course_types WHERE id=?', (int(course_type_id),)).fetchone()
        name = kind['name'] if kind else ''
    product = product_for(c, name)
    subject_name = subject_of(c, student) if student else ''
    if not subject_name and subject_id:
        found = c.execute('SELECT name FROM subjects WHERE id=?', (int(subject_id),)).fetchone()
        subject_name = found['name'] if found else ''
    table = table_on(c, on.isoformat())
    validity = ''
    if table and 'validity_note' in table.keys():
        validity = table['validity_note'] or ''
    if teaching.singapore_subject(subject_name):
        return singapore_offer(student, stored_level(dict(student)) if student else level, name, validity)
    if subject_name == COMBO_SUBJECT:
        return combo_offer(c, student, level, name, product, validity, on)
    if name and not product:
        return _empty_offer(level, name, '', validity, '还没有价格')
    if not level or not product:
        return {'level': level or '', 'course_type': name, 'product': product, 'hourly_cents': None,
            'packages': [], 'validity': validity, 'source': '', 'reason': '请先选择年级和课程类型。'}
    rows = [dict(r) for r in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))] if table else []
    band = matching_row(rows, product, level)
    if not band:
        return {'level': level, 'course_type': name, 'product': product, 'hourly_cents': None,
            'packages': [], 'validity': validity, 'source': '', 'reason': '这个年级还没有价目。'}
    packages = []
    if product == 'term':
        minutes = int(band['lesson_minutes'] or 150)
        choices = [(['T1'], 'T1'), (['T2'], 'T2'), (['T3'], 'T3'), (['T4'], 'T4'),
            (['T1', 'T2'], 'T1+T2'), (['T3', 'T4'], 'T3+T4'), (list(TERM_COUNTS), '四个学期')]
        for terms, label in choices:
            paid = sum(TERM_COUNTS[term] for term in terms)
            each = per_lesson_cents(band['hourly_cents'], minutes)
            discount = discount_percent(terms)
            total = apply_discount(each * paid, discount)
            prices = lesson_prices_millis(total, paid)
            off = f' · {100 - discount}%' if discount else ''
            packages.append({'label': f'{name} {label}{off} · {length_label(minutes)} · {money_millis(total * 10)} · 每节 {money_millis(prices[0])}',
                'paid_lessons': paid, 'gift_lessons': 0, 'lesson_minutes': minutes, 'total_cents': total,
                'each_millis': prices[0], 'unit_fees': prices, 'terms': terms, 'product': product,
                'discount_percent': discount, 'validity': '按所选学期'})
    else:
        for minutes in (60, 90):
            each = per_lesson_cents(band['hourly_cents'], minutes)
            total = each * 20
            prices = [value * 10 for value in lesson_prices_cents(total, 21)]
            packages.append({'label': f'{name} 20+1 节 · {length_label(minutes)} · {money_millis(total * 10)} · 每节 {money_millis(prices[0])}',
                'paid_lessons': 20, 'gift_lessons': 1, 'lesson_minutes': minutes, 'total_cents': total,
                'each_millis': prices[0], 'unit_fees': prices, 'terms': [], 'product': product,
                'discount_percent': 0, 'validity': '永久有效'})
    source = 'table'
    hourly = band['hourly_cents']
    column = enrolment_hourly(student)
    if student and student['profile_id']:
        custom = subject_custom_rows(c, student['profile_id'], product, subject_of(c, student))
        if custom and column is None:
            source = 'custom'
            by_minutes = {row['lesson_minutes']: row['per_lesson_cents'] for row in custom}
            if 60 in by_minutes:
                hourly = by_minutes[60]
            for package in packages:
                each = by_minutes.get(package['lesson_minutes'])
                if each is None and package['product'] == 'term':
                    each = by_minutes.get(minutes)
                if each is None:
                    continue
                paid = package['paid_lessons']
                total = apply_discount(each * paid, discount_percent(package['terms']))
                count = paid if package['product'] == 'term' else paid + package['gift_lessons']
                prices = lesson_prices_millis(total, count) if package['product'] == 'term' else [value * 10 for value in lesson_prices_cents(total, count)]
                package['total_cents'] = total
                package['each_millis'] = prices[0]
                package['unit_fees'] = prices
                package['legacy'] = True
                package['label'] = package['label'].split(' · 每节 ')[0]
                kind = name or PRODUCT_LABELS.get(package['product'], '')
                package['label'] = f"{kind} {'20+1 节' if package['gift_lessons'] else package['label']} · 老学员价 · 每节 {money_millis(prices[0])}"
    if column is not None:
        source = 'custom'
        hourly = column
        for package in packages:
            each = per_lesson_cents(column, package['lesson_minutes'])
            paid = package['paid_lessons']
            total = apply_discount(each * paid, discount_percent(package['terms']))
            count = paid if package['product'] == 'term' else paid + package['gift_lessons']
            prices = lesson_prices_millis(total, count) if package['product'] == 'term' else [value * 10 for value in lesson_prices_cents(total, count)]
            package['total_cents'] = total
            package['each_millis'] = prices[0] if prices else 0
            package['unit_fees'] = prices
            package['legacy'] = True
    return {'level': level, 'course_type': name, 'product': product, 'product_label': PRODUCT_LABELS[product],
        'hourly_cents': hourly, 'lesson_minutes': band['lesson_minutes'], 'packages': packages,
        'validity': validity, 'source': source, 'reason': ''}


def legacy_price(c, student, on=None):
    """Legacy is per subject. An empty subject uses the 2027 list and is not badged."""
    on = on or now_local().date()
    student = annotate(dict(student), on)
    name = student.get('course_type_name') or ''
    if not name and student.get('course_type_id'):
        kind = c.execute('SELECT name FROM course_types WHERE id=?', (student['course_type_id'],)).fetchone()
        name = kind['name'] if kind else ''
    product = TYPE_PRODUCT.get(name)
    level = student.get('level_price') or student.get('level_now') or ''
    subject = subject_of(c, student)
    table = table_on(c, on.isoformat())
    rows = [dict(r) for r in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))] if table else []
    import teaching
    override = enrolment_hourly(student)
    if teaching.singapore_subject(subject):
        list_hourly = singapore_list_hourly(student)
        legacy = override is not None and override != list_hourly
        return {'legacy': legacy, 'legacy_subjects': [],
            'list_hourly_cents': list_hourly, 'custom_hourly_cents': override,
            'product': product, 'subject': subject, 'level': level, 'course_type': name}
    band = matching_row(rows, product, level) if product and level else None
    list_hourly = band['hourly_cents'] if band else None
    customs = subject_custom_rows(c, student.get('profile_id'), product, subject) if product and product != 'helen' else []
    all_custom = profile_custom_rows(c, student.get('profile_id'))
    legacy = bool(customs) and any(price_differs(rows, level, row) for row in customs)
    custom = hourly_from_custom(customs) if customs else None
    if override is not None:
        custom = override
        legacy = list_hourly is None or override != list_hourly
    return {'legacy': legacy, 'legacy_subjects': legacy_subject_names(rows, level, all_custom),
        'list_hourly_cents': list_hourly, 'custom_hourly_cents': custom,
        'product': product, 'subject': subject, 'level': level, 'course_type': name}


def save_legacy_price(c, user, data):
    require_owner(user)
    import accounting
    student = c.execute('''SELECT s.*, ct.name course_type_name, sb.name subject_name FROM students s
        LEFT JOIN course_types ct ON ct.id=s.course_type_id
        LEFT JOIN subjects sb ON sb.id=s.subject_id
        WHERE s.id=? AND s.archived=0''',
        (int(data.get('student_id') or 0),)).fetchone()
    if not student:
        raise ValueError('学生不存在。')
    info = legacy_price(c, student)
    product = info['product']
    subject = info['subject']
    if not product:
        raise ValueError('请先选择课程类型。')
    if not subject:
        raise ValueError('请先选择科目。')
    ensure_enrolment_price(c)
    if data.get('clear') is True or str(data.get('hourly') or '').strip() == '':
        c.execute('UPDATE students SET custom_hourly_cents=NULL WHERE id=?', (student['id'],))
        c.execute('DELETE FROM student_subject_prices WHERE profile_id=? AND product=? AND subject=?',
            (student['profile_id'], product, subject))
        return {'ok': True, 'legacy': False}
    cents = accounting.money(data.get('hourly'))
    c.execute('UPDATE students SET custom_hourly_cents=? WHERE id=?', (cents, student['id'],))
    if info['product'] == 'term':
        minutes_list = [150]
        table = table_on(c, now_local().date().isoformat())
        if table and info['level']:
            rows = [dict(r) for r in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))]
            band = matching_row(rows, 'term', info['level'])
            if band:
                minutes_list = [int(band['lesson_minutes'] or 150)]
    else:
        minutes_list = [60, 90]
    for minutes in minutes_list:
        each = per_lesson_cents(cents, minutes)
        c.execute('''INSERT INTO student_subject_prices(profile_id,product,subject,lesson_minutes,per_lesson_cents,note,updated_by)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(profile_id,product,subject,lesson_minutes) DO UPDATE SET
            per_lesson_cents=excluded.per_lesson_cents, note=excluded.note, updated_by=excluded.updated_by''',
            (student['profile_id'], product, subject, minutes, each, '老学员', user['id']))
    import teaching
    if teaching.singapore_subject(subject):
        c.execute('DELETE FROM student_subject_prices WHERE profile_id=? AND subject=?',
            (student['profile_id'], subject))
    return {'ok': True, 'legacy': cents != info['list_hourly_cents']}


def charged_fee_cents(c, student_id, lesson, amount_units):
    """This subject's locked hourly price, or the 2027 list when that field is empty."""
    student = c.execute('''SELECT s.*, ct.name course_type_name, sb.name subject_name FROM students s
        LEFT JOIN course_types ct ON ct.id=s.course_type_id
        LEFT JOIN subjects sb ON sb.id=s.subject_id WHERE s.id=?''', (student_id,)).fetchone()
    if not student:
        return None
    info = legacy_price(c, student)
    hourly = info['custom_hourly_cents'] if info['custom_hourly_cents'] is not None else info['list_hourly_cents']
    if hourly is None:
        return None
    start = dt.datetime.fromisoformat(lesson['starts_at'])
    end = dt.datetime.fromisoformat(lesson['ends_at'])
    minutes = max(1, int((end - start).total_seconds() // 60))
    each = per_lesson_cents(hourly, minutes)
    return int((Decimal(each) * Decimal(amount_units) / Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def save_band(c, user, data):
    """Edit one year-band hourly price. This is the number parents are charged from."""
    require_owner(user)
    import accounting
    row = c.execute('SELECT * FROM price_rows WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not row or row['product'] == 'helen':
        raise ValueError('这条价目不能修改。')
    cents = accounting.money(data.get('hourly'))
    c.execute('UPDATE price_rows SET hourly_cents=?, placeholder=0 WHERE id=?', (cents, row['id']))
    return {'ok': True}


def save_validity(c, user, data):
    require_owner(user)
    note = str(data.get('validity_note') or '').strip()
    if len(note) > 80:
        raise ValueError('有效期说明最多 80 个字。')
    table = c.execute("SELECT id FROM price_tables WHERE effective_from='2027-01-01'").fetchone()
    if not table:
        raise ValueError('还没有 2027 价目。')
    c.execute('UPDATE price_tables SET validity_note=? WHERE id=?', (note, table['id']))
    return {'ok': True}


def require_owner(user):
    if user['role'] != 'owner':
        raise AccessError('价格只对老板开放。')


def _type_from_text(c, student):
    """Old rows stored 一对一 in the course name and left course_type_id empty."""
    import teaching
    blob = ' '.join(str(student[key] or '') for key in student.keys() if key in ('course', 'course_note', 'course_type_name'))
    _subject, kind, _raw = teaching.parse_label(blob, None)
    if not kind:
        return None
    row = c.execute('SELECT id FROM course_types WHERE name=?', (kind,)).fetchone()
    return row['id'] if row else None


def level_rank(code):
    try:
        return LEVELS.index(code)
    except ValueError:
        return len(LEVELS)


def level_index(code):
    try:
        return LEVELS.index(code)
    except ValueError:
        raise ValueError('请选择年级。')


def parse_level(text):
    raw = str(text or '').strip()
    if not raw:
        return ''
    compact = re.sub(r'[\s._-]+', '', raw).lower()
    aliases = {
        'k': 'K', 'kindergarten': 'K', 'kindy': 'K', '学前': 'K', '幼儿园': 'K',
        'prep': 'Prep', 'p': 'Prep', 'pre': 'Prep', '预备': 'Prep', '预备班': 'Prep',
        'foundation': 'Prep',
    }
    if compact in aliases:
        return aliases[compact]
    matched = re.fullmatch(r'(?:year|yr|y|grade|g|年级)?(\d{1,2})(?:年级)?', compact)
    if matched:
        number = int(matched.group(1))
        if 1 <= number <= 12:
            return f'Y{number}'
    return ''


def move_level(code, years):
    """Shift a level by whole years. Below Prep stays Prep. Above Year 12 stays Year 12 and is marked past."""
    if code not in LEVELS:
        return '', False
    index = LEVELS.index(code) + int(years)
    past = index > LEVELS.index('Y12')
    floor = LEVELS.index('Prep')
    index = max(floor, min(LEVELS.index('Y12'), index))
    return LEVELS[index], past


def shift_level(code, years):
    shown, _past = move_level(code, years)
    return shown


def stored_level(student):
    """The saved code is the 2027 enrolment year. grade text is the same value when the code is empty."""
    code = str((student or {}).get('level_code') or '').strip()
    if code in LEVELS:
        return code
    return parse_level((student or {}).get('grade'))


def calendar_level(code, on):
    """Level in the calendar year of `on`. 2027 Year 5 is Year 4 throughout 2026."""
    if code not in LEVELS:
        return '', False
    return move_level(code, on.year - ENROL_YEAR)


def price_level(code, on, study_level=''):
    """Renewal price uses that date's year. A higher 学习年级 replaces it. A lower one does not."""
    shown, past = calendar_level(code, on)
    override = study_level if study_level in LEVELS else parse_level(study_level)
    if override in LEVELS and shown in LEVELS and LEVELS.index(override) > LEVELS.index(shown):
        return override, past
    return shown, past


def level_label(code, past=False):
    if code in ('K', 'Prep'):
        text = 'Prep'
    elif code and code.startswith('Y') and code[1:].isdigit():
        text = 'Year ' + code[1:]
    else:
        text = code or ''
    if past and text:
        text += ' · 已毕业?'
    return text


def current_level(code, level_year, on=None):
    """Display level for a stored 2027 code. level_year is not rewritten and is not used."""
    if code not in LEVELS:
        return ''
    on = on or now_local().date()
    shown, _past = calendar_level(code, on)
    return shown


def annotate(student, on=None):
    on = on or now_local().date()
    code = stored_level(student)
    shown, past = calendar_level(code, on) if code else ('', False)
    priced, past = price_level(code, on, student.get('study_level') or '') if code else ('', False)
    student['level_stored'] = code
    student['level_calendar'] = shown
    student['level_price'] = priced
    student['level_now'] = priced
    student['level_past'] = past
    student['level_label'] = level_label(priced, past)
    return student


def remember_level(data, grade, today=None):
    """The value in the form is the 2027 year. Later years are calculated, not stored."""
    code = str(data.get('level_code') or '').strip() or parse_level(grade)
    if code and code not in LEVELS:
        raise ValueError('请选择年级。')
    if not code:
        return '', 0
    return code, ENROL_YEAR


def clean_study_level(value):
    text = str(value or '').strip()
    if not text:
        return ''
    code = text if text in LEVELS else parse_level(text)
    if code not in LEVELS:
        raise ValueError('请选择学习年级。')
    return code


def length_label(minutes):
    minutes = int(minutes or 0)
    if minutes == 60:
        return '1 小时'
    if minutes == 90:
        return '1.5 小时'
    if minutes == 120:
        return '2 小时'
    if minutes == 150:
        return '2.5 小时'
    if minutes:
        return f'{minutes / 60:.1f} 小时'
    return ''


def _round_div(value, numerator, denominator):
    return int((Decimal(value) * Decimal(numerator) / Decimal(denominator)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def per_lesson_cents(hourly_cents, minutes):
    return _round_div(hourly_cents, minutes, 60)


def discount_percent(terms):
    chosen = set(terms)
    if chosen == set(TERM_COUNTS):
        return 10
    if chosen in ({'T1', 'T2'}, {'T3', 'T4'}):
        return 5
    return 0


def apply_discount(cents, percent):
    if not percent:
        return cents
    return _round_div(cents, 100 - percent, 100)


def gift_for(product, paid_lessons):
    if product == 'term':
        return 0
    return 1 if int(paid_lessons) == 20 else 0


def lesson_prices_cents(total_cents, count):
    """Round each lesson to cents. The last lesson keeps the remainder so they sum to the total."""
    count = int(count)
    total_cents = int(total_cents)
    if count <= 0:
        return []
    standard = int((Decimal(total_cents) / Decimal(count)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if standard < 0 or standard * (count - 1) > total_cents:
        standard = total_cents // count
    last = total_cents - standard * (count - 1)
    return [standard] * (count - 1) + [last]


def lesson_prices_millis(total_cents, count):
    """Class prices stay at 3 decimal dollars. 1 dollar = 1000 millis. Remainder sits on the last lesson."""
    count = int(count)
    millis = int(total_cents) * 10
    if count <= 0:
        return []
    standard = millis // count
    last = millis - standard * (count - 1)
    return [standard] * (count - 1) + [last]


def money_millis(millis):
    millis = int(millis)
    if millis % 10 == 0:
        return f'${millis / 1000:,.2f}'
    return f'${millis / 1000:,.3f}'


def trial_cents(single_lesson_cents):
    return _round_div(single_lesson_cents, 80, 100)


def list_lesson_cents(c, student_id, day, product, minutes):
    """One lesson at this subject's locked price, or the 2027 list when that field is empty."""
    student = c.execute('SELECT * FROM students WHERE id=?', (int(student_id),)).fetchone()
    if not student or product not in TYPE_PRODUCT.values():
        return None
    import teaching
    if teaching.singapore_subject(subject_of(c, student)):
        if product not in ('one_to_one', 'term'):
            return None
        info = legacy_price(c, student)
        hourly = info['custom_hourly_cents'] if info['custom_hourly_cents'] is not None else info['list_hourly_cents']
        if hourly is None:
            return None
        return per_lesson_cents(hourly, int(minutes))
    level = annotate(dict(student), dt.date.fromisoformat(str(day)[:10]))['level_now']
    custom = subject_lesson_cents(c, student['profile_id'], product, subject_of(c, student), int(minutes))
    if custom is not None:
        return custom
    table = table_on(c, str(day)[:10])
    rows = [dict(r) for r in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))] if table else []
    band = matching_row(rows, product, level) if level else None
    if not band:
        return None
    use = band['lesson_minutes'] if product == 'term' else int(minutes)
    return per_lesson_cents(band['hourly_cents'], use)


def table_on(c, day):
    row = c.execute('SELECT * FROM price_tables WHERE effective_from<=? ORDER BY effective_from DESC, id DESC LIMIT 1', (day,)).fetchone()
    if row:
        return row
    # Before the first list starts, enrolment still needs a price. Use that first list.
    return c.execute('SELECT * FROM price_tables ORDER BY effective_from, id LIMIT 1').fetchone()


def matching_row(rows, product, level):
    """The narrowest year band wins, so a later wide placeholder cannot hide Y11."""
    if level not in LEVELS:
        return None
    index = LEVELS.index(level)
    found = None
    span = None
    for row in rows:
        if row['product'] != product or row.get('placeholder'):
            continue
        start, stop = LEVELS.index(row['level_from']), LEVELS.index(row['level_to'])
        if start <= index <= stop and (span is None or stop - start < span):
            found = row
            span = stop - start
    return found


def singapore_quote(c, student, product, lesson_minutes, paid_lessons, day):
    """20 paid lessons, no gift, and no row from the shared price table."""
    if product not in ('one_to_one', 'term'):
        raise ValueError('新加坡数学只有一对一和小班课。')
    stored = stored_level(dict(student))
    if stored not in SINGAPORE_LEVELS:
        raise ValueError('新加坡数学只开设 Year 7 到 Year 10。')
    minutes = int(lesson_minutes or 0)
    if minutes not in (60, 90):
        raise ValueError('请选择 1 小时或 1.5 小时。')
    try:
        paid = int(paid_lessons or 0)
    except (TypeError, ValueError):
        raise ValueError('购买节数需为整数。')
    if paid != 20:
        raise ValueError('新加坡数学一次购买 20 节，没有赠课。')
    info = legacy_price(c, student)
    hourly = info['custom_hourly_cents'] if info['custom_hourly_cents'] is not None else info['list_hourly_cents']
    each = per_lesson_cents(hourly, minutes)
    total = each * paid
    unit_fees = [value * 10 for value in lesson_prices_cents(total, paid)]
    name = '一对一' if product == 'one_to_one' else '小班课'
    table = table_on(c, str(day)[:10])
    return {
        'student_id': student['id'], 'profile_id': student['profile_id'], 'level': stored,
        'product': product, 'product_label': name,
        'lesson_minutes': minutes, 'length_label': length_label(minutes),
        'paid_lessons': paid, 'gift_lessons': 0, 'discount_percent': 0,
        'per_lesson_cents': each, 'hourly_cents': hourly, 'total_cents': total,
        'unit_fees': unit_fees, 'each_millis': unit_fees[0] if unit_fees else 0,
        'label': f'{name} · {length_label(minutes)} · {paid} 节',
        'source': 'custom' if info['custom_hourly_cents'] is not None else 'catalog',
        'table_from': table['effective_from'] if table else None,
        'terms': [], 'gst': False,
    }


def quote(c, user, student_id, product, lesson_minutes, paid_lessons, day, terms=None):
    require_owner(user)
    if product not in PRODUCTS:
        raise ValueError('请选择课程类型。')
    student = c.execute('SELECT * FROM students WHERE id=?', (int(student_id),)).fetchone()
    if not student:
        raise ValueError('学生不存在。')
    import teaching
    if teaching.singapore_subject(subject_of(c, student)):
        return singapore_quote(c, student, product, lesson_minutes, paid_lessons, day)
    on = dt.date.fromisoformat(str(day))
    level = annotate(dict(student), on)['level_now']
    terms = list(dict.fromkeys(terms or []))
    if product == 'term':
        if any(term not in TERM_COUNTS for term in terms) or not terms:
            raise ValueError('请选择学期。学期班按学期购买。')
        paid = sum(TERM_COUNTS[term] for term in terms)
        discount = discount_percent(terms)
    else:
        if int(lesson_minutes) not in (60, 90):
            raise ValueError('请选择 1 小时或 1.5 小时。')
        paid = int(paid_lessons or 0)
        if paid != 20:
            raise ValueError('一对一和一对二只有 20 节加 1 节赠课这一种课时包。')
        discount = 0
        terms = []
    minutes = int(lesson_minutes or 0)
    subject = subject_of(c, student)
    custom = subject_lesson_cents(c, student['profile_id'], product, subject, minutes)
    source = 'none'
    each = None
    hourly = None
    table = table_on(c, on.isoformat())
    rows = [dict(r) for r in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))] if table else []
    band = matching_row(rows, product, level) if level else None
    if product == 'term' and band and not minutes:
        minutes = band['lesson_minutes']
        custom = subject_lesson_cents(c, student['profile_id'], product, subject, minutes)
    if custom is not None:
        each = custom
        source = 'custom'
    elif band and (product == 'term' or minutes in (60, 90)):
        use_minutes = band['lesson_minutes'] if product == 'term' else minutes
        minutes = use_minutes
        hourly = band['hourly_cents']
        each = per_lesson_cents(hourly, use_minutes)
        source = 'table'
    gift = 1 if product != 'term' and paid == 20 else 0
    total = apply_discount(each * paid, discount) if each is not None else None
    count = paid if product == 'term' else paid + gift
    unit_fees = []
    if total is not None and count:
        unit_fees = lesson_prices_millis(total, count) if product == 'term' else [value * 10 for value in lesson_prices_cents(total, count)]
    return {
        'student_id': student['id'], 'profile_id': student['profile_id'], 'level': level,
        'product': product, 'product_label': PRODUCT_LABELS[product],
        'lesson_minutes': minutes, 'length_label': length_label(minutes),
        'paid_lessons': paid, 'gift_lessons': gift, 'discount_percent': discount,
        'per_lesson_cents': each, 'hourly_cents': hourly, 'total_cents': total,
        'unit_fees': unit_fees, 'each_millis': unit_fees[0] if unit_fees else None,
        'label': f"{PRODUCT_LABELS[product]} · {length_label(minutes)} · {paid} 节" + (f' + 赠 {gift}' if gift else ''),
        'source': source, 'table_from': table['effective_from'] if table else None,
        'terms': terms, 'gst': False,
    }


def save_type_price(c, user, data):
    """Boss edits the hourly price for one course type. Saving clears the 暂定 mark."""
    require_owner(user)
    import accounting
    import teaching
    type_id = int(data.get('course_type_id') or 0)
    kind = c.execute('SELECT name FROM course_types WHERE id=? AND active=1', (type_id,)).fetchone()
    if not kind:
        raise ValueError('请选择课程类型。')
    cents = accounting.money(data.get('hourly'))
    minutes = int(data.get('lesson_minutes') or 60)
    if minutes not in LENGTHS:
        raise ValueError('课时长度无效。')
    day = dt.date.fromisoformat(str(data.get('effective_from') or now_local().date().isoformat())).isoformat()
    table = c.execute('SELECT id FROM price_tables WHERE effective_from=?', (day,)).fetchone()
    if table:
        table_id = table['id']
    else:
        table_id = c.execute('INSERT INTO price_tables(effective_from,label,created_by) VALUES(?,?,?)',
            (day, day[:4] + ' 价目', user['id'])).lastrowid
    product = {'一对一': 'one_to_one', '一对二': 'one_to_two', '小班课': 'term'}.get(kind['name'], 'one_to_one')
    existing = c.execute('''SELECT id FROM price_rows WHERE table_id=? AND course_type_id=? AND lesson_minutes=? AND level_from='Prep' AND level_to='Y12' ''',
        (table_id, type_id, minutes)).fetchone()
    if existing:
        c.execute('UPDATE price_rows SET hourly_cents=?, placeholder=0, product=? WHERE id=?', (cents, product, existing['id']))
    else:
        c.execute('''INSERT INTO price_rows(table_id,product,level_from,level_to,hourly_cents,lesson_minutes,course_type_id,placeholder)
            VALUES(?,?,?,?,?,?,?,0)''', (table_id, product, 'Prep', 'Y12', cents, minutes, type_id))
    return {'ok': True}


def prices_by_type(c):
    import teaching
    types = [dict(r) for r in c.execute('SELECT * FROM course_types WHERE active=1 ORDER BY sort_order, id')]
    rows = [dict(r) for r in c.execute('SELECT * FROM price_rows ORDER BY id')]
    grouped = []
    for kind in types:
        own = [row for row in rows if row.get('course_type_id') == kind['id']]
        if not own:
            aliases = [key for key, name in teaching.TYPE_ALIASES.items() if name == kind['name']]
            own = [row for row in rows if row['product'] in aliases or teaching.TYPE_ALIASES.get(row['product']) == kind['name']]
        own = [row for row in own if row.get('product') != 'helen']
        grouped.append({'id': kind['id'], 'name': kind['name'], 'rows': own,
            'placeholder': bool(own) and any(row.get('placeholder', 1) for row in own)})
    return grouped


def list_prices(c, user):
    require_owner(user)
    tables = []
    for table in c.execute('SELECT * FROM price_tables ORDER BY effective_from DESC, id DESC'):
        item = dict(table)
        item['rows'] = [dict(r) for r in c.execute("SELECT * FROM price_rows WHERE table_id=? AND product!='helen'", (table['id'],))]
        item['rows'].sort(key=lambda row: (level_rank(row['level_from']), level_rank(row['level_to']), row['product'], row['id']))
        tables.append(item)
    ensure_subject_prices(c)
    custom = [dict(r) for r in c.execute('''SELECT p.*, s.name student_name FROM student_subject_prices p
        JOIN students s ON s.profile_id=p.profile_id
        GROUP BY p.id ORDER BY s.name, p.subject, p.product, p.lesson_minutes''')]
    return {'tables': tables, 'custom': custom, 'levels': list(SELECTABLE_LEVELS), 'terms': TERM_COUNTS, 'products': PRODUCT_LABELS, 'by_type': prices_by_type(c)}


def save_table(c, user, data):
    require_owner(user)
    import accounting
    day = dt.date.fromisoformat(str(data.get('effective_from') or '')).isoformat()
    label = str(data.get('label') or '').strip() or day[:4] + ' 价目'
    if len(label) > 80:
        raise ValueError('价目名称最多 80 个字。')
    rows = data.get('rows')
    if not isinstance(rows, list) or not rows:
        raise ValueError('请至少填写一行价格。')
    cleaned = []
    for row in rows:
        product = row.get('product')
        if product not in PRODUCTS:
            raise ValueError('课程类型无效。')
        start, end = row.get('level_from'), row.get('level_to')
        if start not in LEVELS or end not in LEVELS or LEVELS.index(start) > LEVELS.index(end):
            raise ValueError('年级范围无效。')
        minutes = int(row.get('lesson_minutes') or (150 if product == 'term' else 60))
        if minutes not in LENGTHS:
            raise ValueError('课时长度无效。')
        cleaned.append((product, start, end, accounting.money(row.get('hourly')), minutes))
    existing = c.execute('SELECT id FROM price_tables WHERE effective_from=?', (day,)).fetchone()
    if existing:
        table_id = existing['id']
        c.execute('UPDATE price_tables SET label=? WHERE id=?', (label, table_id))
        c.execute('DELETE FROM price_rows WHERE table_id=?', (table_id,))
    else:
        table_id = c.execute('INSERT INTO price_tables(effective_from,label,created_by) VALUES(?,?,?)', (day, label, user['id'])).lastrowid
    c.executemany('''INSERT INTO price_rows(table_id,product,level_from,level_to,hourly_cents,lesson_minutes)
        VALUES(?,?,?,?,?,?)''', [(table_id, *row) for row in cleaned])
    return {'ok': True, 'id': table_id}


def save_custom(c, user, data):
    require_owner(user)
    import accounting
    profile_id = int(data.get('profile_id') or 0)
    if not c.execute('SELECT 1 FROM students WHERE profile_id=?', (profile_id,)).fetchone():
        raise ValueError('学生不存在。')
    product = data.get('product')
    if product not in PRODUCTS:
        raise ValueError('请选择课程类型。')
    subject = canonical_subject(data.get('subject'))
    if not subject:
        raise ValueError('请选择科目。')
    minutes = int(data.get('lesson_minutes') or 0)
    if minutes not in LENGTHS:
        raise ValueError('请选择课时长度。')
    note = str(data.get('note') or '').strip()
    if len(note) > 200:
        raise ValueError('备注最多 200 个字。')
    ensure_subject_prices(c)
    if data.get('remove') is True:
        c.execute('DELETE FROM student_subject_prices WHERE profile_id=? AND product=? AND subject=? AND lesson_minutes=?',
            (profile_id, product, subject, minutes))
        return {'ok': True}
    cents = accounting.money(data.get('per_lesson'))
    c.execute('''INSERT INTO student_subject_prices(profile_id,product,subject,lesson_minutes,per_lesson_cents,note,updated_by)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(profile_id,product,subject,lesson_minutes) DO UPDATE SET
        per_lesson_cents=excluded.per_lesson_cents, note=excluded.note, updated_by=excluded.updated_by''',
        (profile_id, product, subject, minutes, cents, note, user['id']))
    return {'ok': True}


def normalize_purchase(c, user, data):
    """Turn a package form into the credit the ledger already understands."""
    if user['role'] not in ('owner', 'admin'):
        raise AccessError('只有老板或管理员可以登记课时包。')
    product = data.get('product')
    if product not in PRODUCTS:
        raise ValueError('请选择课程类型：1:1、1:2、Helen 本人 1:1 或学期班。')
    if product == 'helen' and user['role'] != 'owner':
        raise AccessError('Helen 本人 1:1 只对老板开放。')
    student = c.execute('SELECT * FROM students WHERE id=? AND archived=0', (int(data.get('student_id') or 0),)).fetchone()
    if not student:
        raise ValueError('学生不存在。')
    import teaching
    if teaching.singapore_subject(subject_of(c, student)):
        if product not in ('one_to_one', 'term'):
            raise ValueError('新加坡数学只有一对一和小班课。')
        minutes = int(data.get('lesson_minutes') or 0)
        if minutes not in (60, 90):
            raise ValueError('请选择 1 小时或 1.5 小时。')
        try:
            paid = int(str(data.get('paid_lessons') or data.get('amount') or '0'))
        except ValueError:
            raise ValueError('购买节数需为整数。')
        if paid != 20:
            raise ValueError('新加坡数学一次购买 20 节，没有赠课。')
        offer = quote(c, user, student['id'], product, minutes, paid, data.get('date') or now_local().date().isoformat(), [])
        if offer.get('total_cents') is None:
            raise ValueError('新加坡数学还没有价格。')
        import json
        label = '一对一' if product == 'one_to_one' else '小班课'
        detail = f'{label} · 每节 {length_label(minutes)} · {paid} 节'
        note = str(data.get('note') or '').strip()
        if note:
            detail += ' · ' + note
        if len(detail) > 300:
            raise ValueError('备注太长。')
        return {**data, 'kind': 'credit', 'amount': paid, 'gift_amount': 0,
            'package_mode': 'lesson', 'lesson_minutes': minutes, 'product': product, 'note': detail,
            'pack_label': offer.get('label') or detail, 'total_cents': offer['total_cents'],
            'unit_fees': json.dumps(offer.get('unit_fees') or []),
            'cash_amount': f"{offer['total_cents'] / 100:.2f}"}
    minutes = int(data.get('lesson_minutes') or 0)
    terms = []
    if product == 'term':
        raw_terms = data.get('terms') or []
        if isinstance(raw_terms, str):
            raw_terms = [part for part in raw_terms.split(',') if part]
        terms = list(dict.fromkeys(raw_terms))
        if not terms or any(term not in TERM_COUNTS for term in terms):
            raise ValueError('请选择学期。')
        if minutes not in (120, 150):
            raise ValueError('学期班请选择 2 小时或 2.5 小时。')
        paid = sum(TERM_COUNTS[term] for term in terms)
        gift = 0
    else:
        if minutes not in (60, 90):
            raise ValueError('请选择 1 小时或 1.5 小时。')
        try:
            paid = int(str(data.get('paid_lessons') or data.get('amount') or '0'))
        except ValueError:
            raise ValueError('购买节数需为整数。')
        if paid != 20:
            raise ValueError('一对一和一对二只有 20 节加 1 节赠课这一种课时包。')
        gift = 1
    label = PRODUCT_LABELS[product]
    note = str(data.get('note') or '').strip()
    detail = f'{label} · 每节 {length_label(minutes)} · {paid} 节'
    if gift:
        detail += f' + 赠 {gift} 节（付费课上完后才能用）'
    if terms:
        names = '+'.join(terms)
        detail += f' · {names}'
        off = discount_percent(terms)
        if off:
            detail += f' · 已含 {off}% 优惠'
    if note:
        detail += ' · ' + note
    if len(detail) > 300:
        raise ValueError('备注太长。')
    offer = quote(c, user, student['id'], product, minutes, paid, data.get('date') or now_local().date().isoformat(), terms)
    if offer.get('total_cents') is None:
        raise ValueError(offer.get('reason') or '这个年级还没有价目。')
    import json
    purchased = {**data, 'kind': 'credit', 'amount': paid, 'gift_amount': gift,
        'package_mode': 'lesson', 'lesson_minutes': minutes, 'product': product, 'note': detail,
        'pack_label': offer.get('label') or detail, 'total_cents': offer['total_cents'],
        'unit_fees': json.dumps(offer.get('unit_fees') or []),
        'cash_amount': f"{offer['total_cents'] / 100:.2f}"}
    return purchased
