"""Lesson prices, year levels, and package quotes.

Prices are effective by the payment date. A student's own price wins over the
table. Nothing here is shown to parents, teachers, or the front desk.
"""
import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP

from teaching import AccessError, now_local

LEVELS = ('K', 'Prep', 'Y1', 'Y2', 'Y3', 'Y4', 'Y5', 'Y6', 'Y7', 'Y8', 'Y9', 'Y10', 'Y11', 'Y12')
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
    cols = {r['name'] for r in c.execute('PRAGMA table_info(price_tables)')}
    if 'validity_note' not in cols:
        c.execute("ALTER TABLE price_tables ADD COLUMN validity_note TEXT NOT NULL DEFAULT ''")
    publish_seed(c)


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


def presets(c, user, student_id=None, level=None, course_type_id=None, day=None):
    """Packages that match one year level and one course type. Helen's own rate is never included."""
    require_owner(user)
    on = dt.date.fromisoformat(str(day)) if day else now_local().date()
    student = None
    if student_id:
        student = c.execute('SELECT * FROM students WHERE id=? AND archived=0', (int(student_id),)).fetchone()
        if not student:
            raise ValueError('学生不存在。')
        level = annotate(dict(student), on)['level_now'] or level
        course_type_id = course_type_id or student['course_type_id']
    name = ''
    if course_type_id:
        kind = c.execute('SELECT name FROM course_types WHERE id=?', (int(course_type_id),)).fetchone()
        name = kind['name'] if kind else ''
    product = TYPE_PRODUCT.get(name)
    table = table_on(c, on.isoformat())
    validity = ''
    if table and 'validity_note' in table.keys():
        validity = table['validity_note'] or ''
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
            total = apply_discount(each * paid, discount_percent(terms))
            packages.append({'label': f'{label} · {length_label(minutes)}', 'paid_lessons': paid, 'gift_lessons': 0,
                'lesson_minutes': minutes, 'total_cents': total, 'terms': terms, 'product': product,
                'validity': '有效期为所选学期'})
    else:
        for minutes in (60, 90):
            each = per_lesson_cents(band['hourly_cents'], minutes)
            packages.append({'label': f'20 节 · {length_label(minutes)}', 'paid_lessons': 20, 'gift_lessons': 1,
                'lesson_minutes': minutes, 'total_cents': each * 20, 'terms': [], 'product': product,
                'validity': validity or '有效期未定'})
    source = 'table'
    if student and student['profile_id']:
        custom = c.execute('SELECT per_lesson_cents, lesson_minutes FROM student_prices WHERE profile_id=? AND product=?',
            (student['profile_id'], product)).fetchall()
        if custom:
            source = 'custom'
            by_minutes = {row['lesson_minutes']: row['per_lesson_cents'] for row in custom}
            for package in packages:
                each = by_minutes.get(package['lesson_minutes'])
                if each is None:
                    continue
                paid = package['paid_lessons']
                package['total_cents'] = apply_discount(each * paid, discount_percent(package['terms']))
                package['legacy'] = True
    return {'level': level, 'course_type': name, 'product': product, 'product_label': PRODUCT_LABELS[product],
        'hourly_cents': band['hourly_cents'], 'lesson_minutes': band['lesson_minutes'], 'packages': packages,
        'validity': validity, 'source': source, 'reason': ''}


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
    matched = re.fullmatch(r'(?:year|yr|y|grade|g|年级)?(\d{1,2})年级?', compact)
    if matched:
        number = int(matched.group(1))
        if 1 <= number <= 12:
            return f'Y{number}'
    return ''


def shift_level(code, years):
    if code not in LEVELS:
        return ''
    index = LEVELS.index(code) + int(years)
    return LEVELS[max(0, min(len(LEVELS) - 1, index))]


def current_level(code, level_year, on=None):
    """Year levels move up on 1 January. The stored code is the level in level_year."""
    if code not in LEVELS:
        return ''
    on = on or now_local().date()
    base = int(level_year or on.year)
    return shift_level(code, on.year - base)


def annotate(student, on=None):
    on = on or now_local().date()
    code = student.get('level_code') or ''
    if code in LEVELS and int(student.get('level_year') or 0):
        student['level_now'] = current_level(code, student.get('level_year'), on)
    else:
        student['level_now'] = parse_level(student.get('grade'))
    return student


def remember_level(data, grade, today=None):
    """The value typed today is this year's level. Next January it moves up on its own."""
    today = today or now_local().date()
    code = str(data.get('level_code') or '').strip() or parse_level(grade)
    if code and code not in LEVELS:
        raise ValueError('请选择年级。')
    if not code:
        return '', 0
    return code, today.year


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
    return int(paid_lessons) // 20


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


def quote(c, user, student_id, product, lesson_minutes, paid_lessons, day, terms=None):
    require_owner(user)
    if product not in PRODUCTS:
        raise ValueError('请选择课程类型。')
    student = c.execute('SELECT * FROM students WHERE id=?', (int(student_id),)).fetchone()
    if not student:
        raise ValueError('学生不存在。')
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
        if paid < 1:
            raise ValueError('请填写购买节数。')
        discount = 0
        terms = []
    minutes = int(lesson_minutes or 0)
    custom = c.execute('''SELECT per_lesson_cents FROM student_prices
        WHERE profile_id=? AND product=? AND lesson_minutes=?''', (student['profile_id'], product, minutes if product != 'term' else minutes)).fetchone()
    source = 'none'
    each = None
    hourly = None
    table = table_on(c, on.isoformat())
    rows = [dict(r) for r in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))] if table else []
    band = matching_row(rows, product, level) if level else None
    if product == 'term' and band and not minutes:
        minutes = band['lesson_minutes']
        custom = c.execute('''SELECT per_lesson_cents FROM student_prices
            WHERE profile_id=? AND product=? AND lesson_minutes=?''', (student['profile_id'], product, minutes)).fetchone()
    if custom:
        each = custom['per_lesson_cents']
        source = 'custom'
    elif band and (product == 'term' or minutes in (60, 90)):
        use_minutes = band['lesson_minutes'] if product == 'term' else minutes
        minutes = use_minutes
        hourly = band['hourly_cents']
        each = per_lesson_cents(hourly, use_minutes)
        source = 'table'
    gift = gift_for(product, paid)
    total = apply_discount(each * paid, discount) if each is not None else None
    return {
        'student_id': student['id'], 'profile_id': student['profile_id'], 'level': level,
        'product': product, 'product_label': PRODUCT_LABELS[product],
        'lesson_minutes': minutes, 'length_label': length_label(minutes),
        'paid_lessons': paid, 'gift_lessons': gift, 'discount_percent': discount,
        'per_lesson_cents': each, 'hourly_cents': hourly, 'total_cents': total,
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
        item['rows'] = [dict(r) for r in c.execute("SELECT * FROM price_rows WHERE table_id=? AND product!='helen' ORDER BY product, level_from, id", (table['id'],))]
        tables.append(item)
    custom = [dict(r) for r in c.execute('''SELECT p.*, s.name student_name FROM student_prices p
        JOIN students s ON s.profile_id=p.profile_id
        GROUP BY p.id ORDER BY s.name, p.product, p.lesson_minutes''')]
    return {'tables': tables, 'custom': custom, 'levels': list(LEVELS), 'terms': TERM_COUNTS, 'products': PRODUCT_LABELS, 'by_type': prices_by_type(c)}


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
    minutes = int(data.get('lesson_minutes') or 0)
    if minutes not in LENGTHS:
        raise ValueError('请选择课时长度。')
    note = str(data.get('note') or '').strip()
    if len(note) > 200:
        raise ValueError('备注最多 200 个字。')
    if data.get('remove') is True:
        c.execute('DELETE FROM student_prices WHERE profile_id=? AND product=? AND lesson_minutes=?', (profile_id, product, minutes))
        return {'ok': True}
    cents = accounting.money(data.get('per_lesson'))
    c.execute('''INSERT INTO student_prices(profile_id,product,lesson_minutes,per_lesson_cents,note,updated_by)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(profile_id,product,lesson_minutes) DO UPDATE SET
        per_lesson_cents=excluded.per_lesson_cents, note=excluded.note, updated_by=excluded.updated_by''',
        (profile_id, product, minutes, cents, note, user['id']))
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
        if paid < 20:
            raise ValueError('课时包至少购买 20 节。买 20 节赠 1 节。')
        if data.get('gift_lessons') in (None, ''):
            gift = gift_for(product, paid)
        else:
            try:
                gift = int(str(data.get('gift_lessons')))
            except ValueError:
                raise ValueError('赠课节数需为整数。')
            if gift < 0 or gift > paid:
                raise ValueError('赠课不能超过购买节数。')
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
    purchased = {**data, 'kind': 'credit', 'amount': paid, 'gift_amount': gift,
        'package_mode': 'lesson', 'lesson_minutes': minutes, 'product': product, 'note': detail}
    return purchased
