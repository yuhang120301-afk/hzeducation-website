"""Move the remaining value of one lesson pack onto another course.

The old pack stays, marked 已换课. The new pack points back at it. No cash
entry is written, so the move is not income and not a refund. A leftover that
is not a whole lesson stays on the new pack as account credit.
"""
import json
import uuid

import auditlog
import credit_batches
import pricing
from teaching import AccessError, OFFERED_SUBJECTS, now_local

SUBJECT_REQUIRED = '请选择数学、英语、VCE 中数、VCE 低数或 VCE 高数。'


def schema(c):
    credit_batches.schema(c)
    cols = {row['name'] for row in c.execute('PRAGMA table_info(credit_batches)')}
    if 'status' not in cols:
        c.execute("ALTER TABLE credit_batches ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if 'switched_from' not in cols:
        c.execute('ALTER TABLE credit_batches ADD COLUMN switched_from INTEGER')
    if 'switched_to' not in cols:
        c.execute('ALTER TABLE credit_batches ADD COLUMN switched_to INTEGER')
    if 'leftover_millis' not in cols:
        c.execute('ALTER TABLE credit_batches ADD COLUMN leftover_millis INTEGER NOT NULL DEFAULT 0')
    if 'teacher_id' not in cols:
        c.execute('ALTER TABLE credit_batches ADD COLUMN teacher_id INTEGER')
    if 'lesson_minutes' not in cols:
        c.execute('ALTER TABLE credit_batches ADD COLUMN lesson_minutes INTEGER')


def _owner(user):
    if not user or user.get('role') != 'owner':
        raise AccessError('只有老板可以换课。')


def _fees(batch):
    try:
        raw = json.loads(batch['unit_fees'] or '[]')
    except json.JSONDecodeError:
        raw = []
    fees = []
    for item in raw:
        try:
            fees.append(int(item))
        except (TypeError, ValueError):
            continue
    total_units = int(batch['purchased'] or 0) + int(batch['gifted'] or 0)
    if fees:
        return fees, total_units
    total = batch['total_cents']
    lessons = total_units // 100
    if total and lessons and total_units == lessons * 100:
        return pricing.lesson_prices_millis(int(total), lessons), total_units
    return [], total_units


def _remaining_millis(fees, total_units, left):
    """Value of the unused part of the pack, in millis. 1 dollar = 1000 millis."""
    if left <= 0 or total_units <= 0:
        return 0
    if not fees:
        return None
    used = total_units - left
    acc = 0
    for index, price in enumerate(fees):
        start = index * 100
        overlap = max(0, min(total_units, start + 100) - max(used, start))
        acc += int(price) * overlap
    millis = acc // 100
    if acc % 100:
        millis += 1
    return millis


def _each_millis(c, student, product, subject, minutes, level, manual):
    if manual not in (None, ''):
        import accounting
        return accounting.money(manual) * 10, 'manual'
    custom = pricing.subject_lesson_cents(c, student['profile_id'], product, subject, int(minutes))
    if custom is not None:
        return int(custom) * 10, 'custom'
    table = pricing.table_on(c, now_local().date().isoformat())
    rows = [dict(row) for row in c.execute('SELECT * FROM price_rows WHERE table_id=?', (table['id'],))] if table else []
    band = pricing.matching_row(rows, product, level)
    if not band:
        raise ValueError('这个年级还没有价目。')
    return pricing.per_lesson_cents(band['hourly_cents'], int(minutes)) * 10, 'table'


def _choice(c, data, student):
    subject = str(data.get('subject') or '').strip()
    if subject not in OFFERED_SUBJECTS:
        raise ValueError(SUBJECT_REQUIRED)
    type_id = int(data.get('course_type_id') or 0)
    kind = c.execute('SELECT id, name FROM course_types WHERE id=? AND active=1', (type_id,)).fetchone()
    if not kind:
        raise ValueError('请选择课程类型。')
    product = pricing.TYPE_PRODUCT.get(kind['name'])
    if not product:
        raise ValueError('请选择课程类型。')
    level = str(data.get('level') or '').strip()
    if level not in pricing.LEVELS:
        raise ValueError('请选择年级。')
    minutes = int(data.get('lesson_minutes') or 0)
    allowed = (120, 150) if product == 'term' else (60, 90)
    if minutes not in allowed:
        raise ValueError('请选择课时长度。')
    teacher_id = int(data.get('teacher_id') or 0)
    teacher = c.execute('SELECT t.id, u.name FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.id=? AND u.active=1', (teacher_id,)).fetchone()
    if not teacher:
        raise ValueError('请选择任课老师。')
    each, source = _each_millis(c, student, product, subject, minutes, level, data.get('manual_price'))
    if not each:
        raise ValueError('新课程还没有每节价格。')
    return {
        'subject': subject, 'type_id': kind['id'], 'type_name': kind['name'], 'product': product,
        'level': level, 'minutes': minutes, 'teacher_id': teacher['id'], 'teacher_name': teacher['name'],
        'each_millis': each, 'source': source,
    }


def _target_student(c, source, choice):
    row = c.execute('''SELECT * FROM students WHERE profile_id=? AND subject_id=(SELECT id FROM subjects WHERE name=?) AND archived=0 ORDER BY id LIMIT 1''',
        (source['profile_id'], choice['subject'])).fetchone()
    if row:
        return row
    archived = c.execute('''SELECT * FROM students WHERE profile_id=? AND subject_id=(SELECT id FROM subjects WHERE name=?) AND archived=1 ORDER BY id LIMIT 1''',
        (source['profile_id'], choice['subject'])).fetchone()
    if archived:
        c.execute('UPDATE students SET archived=0, course_type_id=? WHERE id=?', (choice['type_id'], archived['id']))
        return c.execute('SELECT * FROM students WHERE id=?', (archived['id'],)).fetchone()
    subject = c.execute('SELECT id FROM subjects WHERE name=?', (choice['subject'],)).fetchone()
    if not subject:
        raise ValueError(SUBJECT_REQUIRED)
    shown, _past = pricing.calendar_level(pricing.stored_level(dict(source)), now_local().date())
    study = choice['level'] if shown in pricing.LEVELS and pricing.LEVELS.index(choice['level']) > pricing.LEVELS.index(shown) else ''
    sid = c.execute('''INSERT INTO students(name,course,parent_id,profile_id,birthday,grade,notes,billing_unit,subject_id,course_type_id,level_code,level_year,study_level)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
        source['name'], choice['subject'], source['parent_id'], source['profile_id'], source['birthday'], source['grade'],
        source['notes'], source['billing_unit'] if 'billing_unit' in source.keys() else 'lesson', subject['id'], choice['type_id'],
        source['level_code'] if 'level_code' in source.keys() else '', source['level_year'] if 'level_year' in source.keys() else 0, study)).lastrowid
    return c.execute('SELECT * FROM students WHERE id=?', (sid,)).fetchone()


def quote_switch(c, user, data):
    _owner(user)
    schema(c)
    batch = c.execute('SELECT * FROM credit_batches WHERE id=?', (int(data.get('batch_id') or 0),)).fetchone()
    student = c.execute('SELECT * FROM students WHERE id=?', (batch['student_id'],)).fetchone() if batch else None
    if not batch or not student or student['archived']:
        raise ValueError('这个课时包不存在。')
    if (batch['status'] if 'status' in batch.keys() else 'active') == 'switched':
        raise ValueError('这个课时包已经换过课。')
    left = int(batch['paid_left'] or 0) + int(batch['gift_left'] or 0)
    if left <= 0:
        raise ValueError('这个课时包没有剩余课时。')
    fees, total_units = _fees(batch)
    remaining = _remaining_millis(fees, total_units, left)
    if remaining is None:
        product = pricing.TYPE_PRODUCT.get(_type_name(c, student), '')
        level = pricing.annotate(dict(student))['level_price']
        if not product or not level:
            raise ValueError('这个课时包没有可换算的金额。')
        each, _source = _each_millis(c, student, product, pricing.subject_of(c, student), 60, level, None)
        numer = each * left
        remaining = numer // 100
        if numer % 100:
            remaining += 1
    if remaining <= 0:
        raise ValueError('这个课时包没有可换算的金额。')
    choice = _choice(c, data, student)
    whole = remaining // choice['each_millis']
    leftover = remaining - whole * choice['each_millis']
    return {
        'batch_id': batch['id'], 'old_label': batch['pack_label'] or '课时包',
        'old_course': student['course'], 'remaining_units': left,
        'remaining_lessons': left / 100, 'remaining_millis': remaining,
        'remaining_value': pricing.money_millis(remaining),
        'new_subject': choice['subject'], 'new_type': choice['type_name'],
        'new_level': choice['level'], 'new_minutes': choice['minutes'],
        'teacher_name': choice['teacher_name'], 'price_source': choice['source'],
        'new_each_millis': choice['each_millis'], 'new_each': pricing.money_millis(choice['each_millis']),
        'new_lessons': whole, 'leftover_millis': leftover, 'leftover': pricing.money_millis(leftover),
    }


def _type_name(c, student):
    if not student['course_type_id']:
        return ''
    row = c.execute('SELECT name FROM course_types WHERE id=?', (student['course_type_id'],)).fetchone()
    return row['name'] if row else ''


def apply_switch(c, user, data):
    _owner(user)
    schema(c)
    preview = quote_switch(c, user, data)
    if int(preview['new_lessons']) < 0:
        raise ValueError('换课后的节数无效。')
    batch = c.execute('SELECT * FROM credit_batches WHERE id=?', (preview['batch_id'],)).fetchone()
    source = c.execute('SELECT * FROM students WHERE id=?', (batch['student_id'],)).fetchone()
    choice = _choice(c, data, source)
    auditlog.begin(c)
    target = _target_student(c, source, choice)
    day = now_local().date().isoformat()
    out_id = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
        VALUES(?,0,'switch',?,?,?,?)''', (source['id'], day, '换课转出 ' + preview['old_label'], user['id'], uuid.uuid4().hex)).lastrowid
    credit_batches.move(c, out_id, batch['id'], -int(batch['paid_left'] or 0), -int(batch['gift_left'] or 0))
    credit_batches.finish(c, out_id)
    c.execute("UPDATE credit_batches SET status='switched' WHERE id=?", (batch['id'],))
    units = int(preview['new_lessons']) * 100
    label = f"{choice['subject']} {choice['type_name']} · 换课 · {choice['teacher_name']}"
    fees = json.dumps([choice['each_millis']] * int(preview['new_lessons']))
    new_id = c.execute('''INSERT INTO credit_batches(student_id,purchased,gifted,paid_left,gift_left,credited_on,pack_label,total_cents,unit_fees,status,switched_from,leftover_millis,teacher_id,lesson_minutes)
        VALUES(?,?,0,0,0,?,?,?,?,'active',?,?,?,?)''', (
        target['id'], units, day, label, int(preview['new_lessons']) * (choice['each_millis'] // 10), fees,
        batch['id'], int(preview['leftover_millis']), choice['teacher_id'], choice['minutes'])).lastrowid
    inn_id = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
        VALUES(?,0,'switch',?,?,?,?)''', (target['id'], day, '换课转入 ' + label, user['id'], uuid.uuid4().hex)).lastrowid
    if units:
        credit_batches.move(c, inn_id, new_id, units, 0)
    credit_batches.finish(c, inn_id)
    c.execute('UPDATE credit_batches SET switched_to=? WHERE id=?', (new_id, batch['id']))
    auditlog.hint(c, f"换课：{source['name']} {preview['old_label']} → {label}，{preview['new_lessons']} 节，结余 {preview['leftover']}")
    audit_id = auditlog.finish(c, user)
    return {**preview, 'new_batch_id': new_id, 'target_student_id': target['id'], 'audit_id': audit_id}
