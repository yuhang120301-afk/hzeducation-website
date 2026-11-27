"""Move Atticus's 12 maths lessons off the English enrolment.

Helen taught these lessons as maths, but the hours were taken from Year 5
英语 一对一. The lessons, their reports and their hour deductions move onto
Year 5 数学 一对一. Twelve hours are moved with them, so the remaining
balances stay where they are: English 8, maths 11 (9 paid + 2 gift).

The 12 lessons are priced at $2550 / 32. An English or maths pack with no
price is priced at $600 / 11 or $2550 / 32. Runs once, from startup. A
production database is copied first. The live file is never replaced.
"""
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone

import backup

KEY = 'atticus_maths_lessons_v1'
MARKER = 'Atticus数学课更正：12节从英语转入'
DATES = (
    '2026-09-29', '2026-10-02', '2026-10-10', '2026-10-11', '2026-10-17', '2026-10-18',
    '2026-10-25', '2026-10-28', '2026-10-31', '2026-11-01', '2026-11-15', '2026-11-22',
)
LESSON = 100
MATHS_CENTS = 255000
MATHS_COUNT = 32
ENGLISH_CENTS = 60000
ENGLISH_COUNT = 11
# Same slice the 32-lesson price list uses for every lesson except the last.
MATHS_MILLIS = (MATHS_CENTS * 10) // MATHS_COUNT
ENGLISH_MILLIS = (ENGLISH_CENTS * 10) // ENGLISH_COUNT
MATHS_FEE_CENTS = (MATHS_MILLIS + 5) // 10
ENGLISH_FEE_CENTS = (ENGLISH_MILLIS + 5) // 10
PRICE_KEY = 'atticus_prices_v1'


def _log(lines):
    print('\n'.join(lines), file=sys.stderr, flush=True)


def _columns(c, table):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return set()
    return {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}


def _marked(c):
    if 'app_meta' not in {row['name'] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        return False
    return c.execute('SELECT 1 FROM app_meta WHERE key=?', (KEY,)).fetchone() is not None


def _people(c):
    rows = [dict(row) for row in c.execute('SELECT id, profile_id, name FROM students')]
    exact = [row for row in rows if ' '.join(str(row['name'] or '').split()).casefold() == 'atticus']
    profiles = {}
    for row in exact:
        profiles.setdefault(row['profile_id'], []).append(row)
    return profiles


def _year_text(row):
    parts = [row.get('course'), row.get('grade'), row.get('level_code'), row.get('study_level'), row.get('type_name')]
    return ' '.join(str(part or '') for part in parts)


def _is_year_five(text):
    folded = text.casefold().replace(' ', '')
    return 'year5' in folded or 'y5' in folded or '5年级' in text


def _other_year(text):
    folded = text.casefold()
    for year in ('year 1', 'year 2', 'year 3', 'year 4', 'year 6', 'year 7', 'year 8', 'year 9', 'year 10', 'year 11', 'year 12'):
        if year in folded:
            return True
    return False


def _enrolments(c, profile_id):
    type_name = ''
    student_cols = _columns(c, 'students')
    join = ''
    if 'course_type_id' in student_cols:
        join = 'LEFT JOIN course_types t ON t.id=s.course_type_id'
        type_name = ', t.name AS type_name'
    level = ', s.level_code' if 'level_code' in student_cols else ", '' AS level_code"
    study = ', s.study_level' if 'study_level' in student_cols else ", '' AS study_level"
    grade = ', s.grade' if 'grade' in student_cols else ", '' AS grade"
    voided = 'AND IFNULL(s.voided,0)=0' if 'voided' in student_cols else ''
    rows = [dict(row) for row in c.execute(f'''SELECT s.id, s.course, s.balance, s.archived, s.subject_id {grade} {level} {study} {type_name}
        FROM students s {join}
        WHERE s.profile_id=? AND IFNULL(s.archived,0)=0 {voided}
        ORDER BY s.id''', (profile_id,))]
    english, maths = [], []
    for row in rows:
        if 'type_name' not in row:
            row['type_name'] = ''
        text = _year_text(row)
        kind = row.get('type_name') or ''
        private = kind == '一对一' or '一对一' in (row.get('course') or '')
        if not private or _other_year(text):
            continue
        course = row.get('course') or ''
        if '英语' in course and '数学' not in course:
            english.append(row)
        elif '数学' in course and '英语' not in course and '新加坡' not in course and 'VCE' not in course and 'vce' not in course:
            maths.append(row)
    english = [row for row in english if _is_year_five(_year_text(row))] or english
    maths = [row for row in maths if _is_year_five(_year_text(row))] or maths
    return english, maths


def _lessons(c, profile_id):
    marks = ','.join('?' for _ in DATES)
    subject = 'sb.name' if 'is_maths' in _columns(c, 'subjects') or _columns(c, 'subjects') else 'NULL'
    rows = c.execute(f'''SELECT l.id lesson_id, substr(l.starts_at,1,10) day, l.status, l.subject_id, l.title,
            r.student_id, r.amount, r.ledger_id, r.fee_cents, s.course, s.profile_id,
            u.name teacher_name, sb.name subject_name, sb.is_maths,
            led.delta, led.kind, led.reversal_of,
            EXISTS(SELECT 1 FROM ledger rev WHERE rev.reversal_of=led.id) reversed
        FROM lessons l
        JOIN lesson_reports r ON r.lesson_id=l.id
        JOIN students s ON s.id=r.student_id
        JOIN teachers t ON t.id=l.teacher_id
        JOIN users u ON u.id=t.user_id
        LEFT JOIN subjects sb ON sb.id=l.subject_id
        LEFT JOIN ledger led ON led.id=r.ledger_id
        WHERE s.profile_id=? AND substr(l.starts_at,1,10) IN ({marks})
        ORDER BY l.starts_at, l.id''', (profile_id, *DATES)).fetchall()
    return [dict(row) for row in rows]


def _taken(c, ledger_id):
    rows = [dict(row) for row in c.execute('''SELECT batch_id, paid, gift, voided FROM credit_movements
        WHERE ledger_id=? AND IFNULL(voided,0)=0''', (ledger_id,))]
    paid = sum(-int(row['paid']) for row in rows if int(row['paid']) < 0)
    gift = sum(-int(row['gift']) for row in rows if int(row['gift']) < 0)
    return paid, gift, rows


def _left(c, student_id):
    status = ''
    if 'status' in _columns(c, 'credit_batches'):
        status = " AND IFNULL(status,'active')='active'"
    row = c.execute(f'''SELECT COALESCE(SUM(paid_left),0) paid_left, COALESCE(SUM(gift_left),0) gift_left
        FROM credit_batches WHERE student_id=? {status}''', (student_id,)).fetchone()
    return int(row['paid_left']), int(row['gift_left'])


def _blank_pack(row, cash):
    fees = str(row.get('unit_fees') or '').strip()
    total = row.get('total_cents')
    receivable = row.get('receivable_cents') or 0
    return (cash in (None, 0)) and (total in (None, 0)) and int(receivable or 0) == 0 and fees in ('', '[]', 'null')


def _packs(c, student_id):
    cols = _columns(c, 'credit_batches')
    total = 'b.total_cents' if 'total_cents' in cols else 'NULL'
    fees = 'b.unit_fees' if 'unit_fees' in cols else "''"
    receivable = 'b.receivable_cents' if 'receivable_cents' in cols else '0'
    rows = c.execute(f'''SELECT b.id, b.purchased, b.gifted, b.paid_left, b.gift_left, b.ledger_id,
            {total} AS total_cents, {fees} AS unit_fees, {receivable} AS receivable_cents, cash.cash_delta
        FROM credit_batches b
        LEFT JOIN cash_entries cash ON cash.ledger_id=b.ledger_id
        WHERE b.student_id=?
        ORDER BY b.id''', (student_id,)).fetchall()
    return [dict(row) for row in rows]


def plan(c):
    lines = ['DRY-RUN  Atticus maths lessons']
    if _marked(c):
        lines.append('已经改过，不再写入。')
        return {'status': 'skip', 'lines': lines}
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='students'").fetchone():
        lines.append('还没有学生表，跳过。')
        return {'status': 'skip', 'lines': lines}
    people = _people(c)
    if not people:
        lines.append('没有名为 Atticus 的学生，跳过。')
        return {'status': 'skip', 'lines': lines}
    if len(people) != 1:
        lines.append(f'名为 Atticus 的人不止一个（{len(people)}），不改。')
        return {'status': 'abort', 'lines': lines}
    profile_id = next(iter(people))
    english, maths = _enrolments(c, profile_id)
    if len(english) != 1 or len(maths) != 1:
        lines.append(f'Year 5 一对一课程对不上：英语 {len(english)} 门，数学 {len(maths)} 门，不改。')
        return {'status': 'abort', 'lines': lines}
    english_id, maths_id = english[0]['id'], maths[0]['id']
    lessons = _lessons(c, profile_id)
    found = {row['day'] for row in lessons}
    if found != set(DATES) or len(lessons) != len(DATES):
        lines.append(f'这 12 天的课是 {sorted(found)}，共 {len(lessons)} 节，不改。')
        return {'status': 'abort', 'lines': lines}
    if all(row['student_id'] == maths_id for row in lessons) and c.execute(
            'SELECT 1 FROM ledger WHERE note=?', (MARKER,)).fetchone():
        lines.append('12 节课已经在数学课上，只补上完成标记。')
        return {'status': 'done', 'lines': lines}
    problems = []
    moves = []
    for row in lessons:
        if row['student_id'] != english_id:
            problems.append(f"{row['day']} 不在英语课上")
        if row['status'] != 'completed':
            problems.append(f"{row['day']} 状态是 {row['status']}")
        if 'helen' not in (row['teacher_name'] or '').casefold():
            problems.append(f"{row['day']} 老师是 {row['teacher_name']}")
        subject = row.get('subject_name') or ''
        title = row.get('title') or ''
        if subject != '数学' and '数学' not in title:
            problems.append(f"{row['day']} 科目是 {subject or title}")
        if int(row['amount'] or 0) != LESSON or int(row['delta'] or 0) != -LESSON or row['reversed']:
            problems.append(f"{row['day']} 扣课不是 1 节")
        paid, gift, movements = _taken(c, row['ledger_id'])
        if paid + gift != LESSON or not movements:
            problems.append(f"{row['day']} 课时包扣减不是 1 节")
        moves.append((row, paid, gift, movements))
    if problems:
        lines.extend(problems)
        lines.append('条件不一致，不改。')
        return {'status': 'abort', 'lines': lines}
    english_paid, english_gift = _left(c, english_id)
    maths_paid, maths_gift = _left(c, maths_id)
    lines.append(f'英语还剩 {english_paid // LESSON} 付费 + {english_gift // LESSON} 赠送')
    lines.append(f'数学还剩 {maths_paid // LESSON} 付费 + {maths_gift // LESSON} 赠送')
    if (english_paid, english_gift, maths_paid, maths_gift) != (800, 0, 900, 200):
        lines.append('余额不是英语 8、数学 9 付费 + 2 赠送，不改。')
        return {'status': 'abort', 'lines': lines}
    lines.append(f'将 12 节课从英语 #{english_id} 改到数学 #{maths_id}，余额保持不变。')
    lines.append(f'每节课酬 ${MATHS_FEE_CENTS // 100}.{MATHS_FEE_CENTS % 100:02d}（$2550 / 32）。')
    lines.append('9 月 1 节，10 月 8 节，11 月 3 节。')
    return {'status': 'apply', 'lines': lines, 'profile_id': profile_id, 'english_id': english_id,
        'maths_id': maths_id, 'moves': moves}


def _actor(c):
    row = c.execute('SELECT user_id FROM organization_owners ORDER BY user_id LIMIT 1').fetchone()
    if row:
        return row['user_id']
    owner = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    return owner['id'] if owner else 1


def _insert_ledger(c, student_id, delta, kind, day, note, actor, paid_delta, gift_delta):
    cols = _columns(c, 'ledger')
    fields = ['student_id', 'delta', 'kind', 'lesson_date', 'note', 'actor_id', 'request_id']
    values = [student_id, delta, kind, day, note, actor, secrets.token_hex(16)]
    if 'paid_delta' in cols:
        fields += ['paid_delta', 'gift_delta', 'split_known']
        values += [paid_delta, gift_delta, 1]
    marks = ','.join('?' for _ in fields)
    return c.execute(f"INSERT INTO ledger({','.join(fields)}) VALUES({marks})", values).lastrowid


def _sync_balance(c, student_id):
    paid, gift = _left(c, student_id)
    c.execute('UPDATE students SET balance=? WHERE id=?', (paid + gift, student_id))
    return paid + gift


def _price_blank_packs(c, student_id, millis_each):
    changed = 0
    for pack in _packs(c, student_id):
        if not _blank_pack(pack, pack.get('cash_delta')):
            continue
        count = (int(pack['purchased'] or 0) + int(pack['gifted'] or 0)) // LESSON
        if count <= 0 or (int(pack['purchased'] or 0) + int(pack['gifted'] or 0)) % LESSON:
            continue
        total = ((millis_each * count) + 5) // 10
        fees = json.dumps([millis_each] * count)
        cols = _columns(c, 'credit_batches')
        sets = ['total_cents=?', 'unit_fees=?']
        values = [total, fees]
        if 'paid_cents' in cols:
            sets.append('paid_cents=?')
            values.append(total)
        if 'payment_status' in cols:
            sets.append("payment_status='paid'")
        c.execute(f"UPDATE credit_batches SET {', '.join(sets)} WHERE id=?", (*values, pack['id']))
        changed += 1
    return changed


def _maths_subject(c):
    row = c.execute("SELECT id FROM subjects WHERE name='数学' ORDER BY id LIMIT 1").fetchone()
    return row['id'] if row else None


def apply(c, decision):
    english_id = decision['english_id']
    maths_id = decision['maths_id']
    before = (_left(c, english_id), _left(c, maths_id))
    actor = _actor(c)
    restored = {}
    for row, paid, gift, movements in decision['moves']:
        c.execute('UPDATE lesson_reports SET student_id=? WHERE lesson_id=? AND student_id=?',
            (maths_id, row['lesson_id'], english_id))
        c.execute('UPDATE lesson_students SET student_id=? WHERE lesson_id=? AND student_id=?',
            (maths_id, row['lesson_id'], english_id))
        c.execute('UPDATE ledger SET student_id=? WHERE id=?', (maths_id, row['ledger_id']))
        subject_id = _maths_subject(c)
        if subject_id and row.get('subject_id') != subject_id:
            c.execute('UPDATE lessons SET subject_id=? WHERE id=?', (subject_id, row['lesson_id']))
        for movement in movements:
            batch_id = movement['batch_id']
            restored.setdefault(batch_id, [0, 0])
            taken_paid = -int(movement['paid']) if int(movement['paid']) < 0 else 0
            taken_gift = -int(movement['gift']) if int(movement['gift']) < 0 else 0
            restored[batch_id][0] += taken_paid
            restored[batch_id][1] += taken_gift
            c.execute('UPDATE credit_batches SET paid_left=paid_left+?, gift_left=gift_left+? WHERE id=?',
                (taken_paid, taken_gift, batch_id))
    paid_total = sum(pair[0] for pair in restored.values())
    gift_total = sum(pair[1] for pair in restored.values())
    out_ledger = _insert_ledger(c, english_id, -(paid_total + gift_total), 'switch', '2026-11-27', MARKER, actor,
        -paid_total, -gift_total)
    for batch_id, (paid, gift) in restored.items():
        c.execute('INSERT INTO credit_movements(ledger_id, batch_id, paid, gift, voided) VALUES(?,?,?,?,0)',
            (out_ledger, batch_id, -paid, -gift))
        c.execute('UPDATE credit_batches SET paid_left=paid_left-?, gift_left=gift_left-? WHERE id=?',
            (paid, gift, batch_id))
    in_ledger = _insert_ledger(c, maths_id, paid_total + gift_total, 'switch', '2026-11-27', MARKER, actor,
        paid_total, gift_total)
    count = (paid_total + gift_total) // LESSON
    total = (MATHS_MILLIS * count + 5) // 10
    fees = json.dumps([MATHS_MILLIS] * count)
    cols = _columns(c, 'credit_batches')
    fields = ['student_id', 'ledger_id', 'purchased', 'gifted', 'paid_left', 'gift_left', 'credited_on']
    values = [maths_id, in_ledger, paid_total, gift_total, 0, 0, '2026-11-27']
    if 'total_cents' in cols:
        fields += ['total_cents', 'unit_fees']
        values += [total, fees]
    if 'paid_cents' in cols:
        fields += ['paid_cents']
        values.append(total)
    marks = ','.join('?' for _ in values)
    batch_id = c.execute(
        f"INSERT INTO credit_batches({','.join(fields)}) VALUES({marks})", values).lastrowid
    for row, paid, gift, movements in decision['moves']:
        for movement in movements:
            c.execute('UPDATE credit_movements SET batch_id=? WHERE ledger_id=? AND batch_id=?',
                (batch_id, row['ledger_id'], movement['batch_id']))
    if _sync_balance(c, english_id) != before[0][0] + before[0][1]:
        raise RuntimeError('英语余额变了。')
    if _sync_balance(c, maths_id) != before[1][0] + before[1][1]:
        raise RuntimeError('数学余额变了。')
    after = (_left(c, english_id), _left(c, maths_id))
    if after != before:
        raise RuntimeError(f'课时包余额变了：{before} → {after}')
    _price_blank_packs(c, english_id, ENGLISH_MILLIS)
    _price_blank_packs(c, maths_id, MATHS_MILLIS)
    c.execute('INSERT INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))


def _production(db_path):
    real = os.path.realpath(db_path) if db_path else ''
    return real == '/var/data/lessons.sqlite3' or real.startswith('/var/data/')


def _backup(db_path):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    destination = f'/var/data/backup-atticus-maths-{stamp}.sqlite3'
    backup.write_snapshot(db_path, destination)
    return destination


def run(c, db_path):
    """Log the dry-run, then apply inside a savepoint. Never replaces the live file."""
    try:
        decision = plan(c)
    except sqlite3.Error as exc:
        _log([f'Atticus 数学课更正没有读成：{exc}'])
        return
    _log(decision['lines'])
    if decision['status'] == 'done':
        c.execute('INSERT OR IGNORE INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))
        return
    if decision['status'] != 'apply':
        return
    if _production(db_path):
        try:
            copied = _backup(db_path)
        except (OSError, FileExistsError, FileNotFoundError, RuntimeError) as exc:
            _log([f'备份没有写成，这次不改：{exc}'])
            return
        _log([f'已备份到 {copied}，没有替换正在用的数据库。'])
    c.execute('SAVEPOINT atticus_maths')
    try:
        apply(c, decision)
    except Exception as exc:
        c.execute('ROLLBACK TO atticus_maths')
        c.execute('RELEASE atticus_maths')
        _log([f'没有写成：{exc}'])
        return
    c.execute('RELEASE atticus_maths')
    _log(['APPLY  12 节数学课已改到数学课程。英语还剩 8，数学还剩 11。'])


def _pack_total(millis_each, count):
    return (int(millis_each) * int(count) + 5) // 10


def _drop_zero_cash(c, ledger_id):
    """A stored $0 hides the pack total. Removing it does not change money received."""
    if not ledger_id:
        return
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cash_entries'").fetchone():
        return
    c.execute('DELETE FROM cash_entries WHERE ledger_id=? AND IFNULL(cash_delta,0)=0', (ledger_id,))


def _set_pack_value(c, pack, millis_each, count):
    total = _pack_total(millis_each, count)
    fees = json.dumps([millis_each] * count)
    cols = _columns(c, 'credit_batches')
    sets = ['total_cents=?', 'unit_fees=?']
    values = [total, fees]
    if 'paid_cents' in cols:
        sets.append('paid_cents=?')
        values.append(total)
    if 'payment_status' in cols:
        sets.append("payment_status='paid'")
    c.execute(f"UPDATE credit_batches SET {', '.join(sets)} WHERE id=?", (*values, pack['id']))
    _drop_zero_cash(c, pack.get('ledger_id'))
    return total


def _save_hourly(c, student_id, profile_id, subject, hourly_cents, actor):
    c.execute('UPDATE students SET custom_hourly_cents=? WHERE id=?', (hourly_cents, student_id))
    import pricing
    pricing.ensure_subject_prices(c)
    for minutes in (60, 90):
        each = pricing.per_lesson_cents(hourly_cents, minutes)
        c.execute('''INSERT INTO student_subject_prices(profile_id,product,subject,lesson_minutes,per_lesson_cents,note,updated_by)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(profile_id,product,subject,lesson_minutes) DO UPDATE SET
            per_lesson_cents=excluded.per_lesson_cents, note=excluded.note, updated_by=excluded.updated_by''',
            (profile_id, 'one_to_one', subject, minutes, each, 'Atticus 约定价格', actor))


def _lesson_fees(c, profile_id):
    marks = ','.join('?' for _ in DATES)
    rows = c.execute(f'''SELECT substr(l.starts_at,1,10) day, r.lesson_id, r.fee_cents, r.ledger_id, s.course
        FROM lessons l
        JOIN lesson_reports r ON r.lesson_id=l.id
        JOIN students s ON s.id=r.student_id
        WHERE s.profile_id=? AND substr(l.starts_at,1,10) IN ({marks})
        ORDER BY l.starts_at''', (profile_id, *DATES)).fetchall()
    return [dict(row) for row in rows]


def _backup_fees():
    folder = '/var/data'
    if not os.path.isdir(folder):
        return {}, ''
    names = sorted(name for name in os.listdir(folder)
        if name.startswith('backup-atticus-maths-') and name.endswith('.sqlite3'))
    if not names:
        return {}, ''
    path = os.path.join(folder, names[0])
    found = {}
    try:
        uri = PathUri(path)
        src = sqlite3.connect(uri, uri=True, timeout=30)
    except sqlite3.Error:
        return {}, path
    src.row_factory = sqlite3.Row
    try:
        marks = ','.join('?' for _ in DATES)
        rows = src.execute(f'''SELECT substr(l.starts_at,1,10) day, r.fee_cents
            FROM lessons l
            JOIN lesson_reports r ON r.lesson_id=l.id
            JOIN students s ON s.id=r.student_id
            WHERE lower(trim(s.name))='atticus' AND substr(l.starts_at,1,10) IN ({marks})
            ORDER BY l.starts_at''', DATES).fetchall()
        for row in rows:
            found.setdefault(row['day'], row['fee_cents'])
    except sqlite3.Error:
        found = {}
    finally:
        src.close()
    return found, path


def PathUri(path):
    return f"file:{os.path.realpath(path)}?mode=ro"


def _month_sum(fees):
    months = {'2026-09': 0, '2026-10': 0, '2026-11': 0}
    counts = {'2026-09': 0, '2026-10': 0, '2026-11': 0}
    for day, cents in fees:
        key = day[:7]
        if key in months and cents is not None:
            months[key] += int(cents)
            counts[key] += 1
    return months, counts


def apply_prices(c, decision):
    actor = _actor(c)
    english_id = decision['english_id']
    maths_id = decision['maths_id']
    profile_id = decision['profile_id']
    before = _lesson_fees(c, profile_id)
    backup_fees, backup_path = _backup_fees()
    lines = ['APPLY  Atticus prices']
    if backup_path:
        lines.append(f'更正前的备份 {backup_path}')
    for row in before:
        old = backup_fees.get(row['day'])
        lines.append(
            f"{row['day']} 更正前 { _aud(old) }，现在 {_aud(row['fee_cents'])}，改为 {_aud(MATHS_FEE_CENTS)}")
    for row in before:
        c.execute('''UPDATE lesson_reports SET fee_cents=?, fee_millis=?, fee_overridden=0
            WHERE lesson_id=?''', (MATHS_FEE_CENTS, MATHS_MILLIS, row['lesson_id']))
    english_packs = _packs(c, english_id)
    maths_packs = _packs(c, maths_id)
    for pack in english_packs:
        count = (int(pack['purchased'] or 0) + int(pack['gifted'] or 0)) // LESSON
        if count not in (8, 23):
            continue
        total = _set_pack_value(c, pack, ENGLISH_MILLIS, count)
        note = '已用完，不改变英语还剩的 8 节' if count == 23 else '还剩的 8 节按这个价'
        lines.append(f"英语课时包 #{pack['id']} {count} 节改为 {_aud(total)}（{note}）")
    for pack in maths_packs:
        paid = int(pack['purchased'] or 0)
        gift = int(pack['gifted'] or 0)
        if paid == 900 and gift == 200:
            total = _set_pack_value(c, pack, MATHS_MILLIS, 11)
            lines.append(f"数学转移包 #{pack['id']} 9+2 改为 {_aud(total)}，以后按这个价扣。")
        elif paid == 1200 and gift == 0:
            _set_pack_value(c, pack, MATHS_MILLIS, 12)
            total = MATHS_FEE_CENTS * 12
            c.execute('UPDATE credit_batches SET total_cents=? WHERE id=?', (total, pack['id']))
            if 'paid_cents' in _columns(c, 'credit_batches'):
                c.execute('UPDATE credit_batches SET paid_cents=? WHERE id=?', (total, pack['id']))
            lines.append(f"数学 12 节包 #{pack['id']} 改为 {_aud(total)}")
    _save_hourly(c, english_id, profile_id, '英语', ENGLISH_FEE_CENTS, actor)
    _save_hourly(c, maths_id, profile_id, '数学', MATHS_FEE_CENTS, actor)
    lines.append(f'英语保存单价 {_aud(ENGLISH_FEE_CENTS)}/小时，数学 {_aud(MATHS_FEE_CENTS)}/小时。')
    after = [(row['day'], MATHS_FEE_CENTS) for row in before]
    old_pairs = [(row['day'], backup_fees.get(row['day']) if backup_fees else row['fee_cents']) for row in before]
    now_pairs = [(row['day'], row['fee_cents']) for row in before]
    for label, pairs in (('备份里的课酬', old_pairs), ('改价前的课酬', now_pairs), ('改价后的课酬', after)):
        months, counts = _month_sum(pairs)
        lines.append(
            f"{label} 9月 {_aud(months['2026-09'])}（{counts['2026-09']}节）"
            f" 10月 {_aud(months['2026-10'])}（{counts['2026-10']}节）"
            f" 11月 {_aud(months['2026-11'])}（{counts['2026-11']}节）")
    c.execute('INSERT OR IGNORE INTO app_meta(key, value) VALUES(?,?)', (PRICE_KEY, '1'))
    return lines


def _aud(cents):
    if cents is None:
        return '无'
    cents = int(cents)
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}${cents // 100}.{cents % 100:02d}'


def run_prices(c, db_path):
    """Save Atticus's agreed hourly prices and put them on the packs and the 12 lessons."""
    try:
        if _marked_price(c):
            return
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='students'").fetchone():
            return
        people = _people(c)
        if len(people) != 1:
            if people:
                _log([f'Atticus 价格不改：名为 Atticus 的人有 {len(people)} 个。'])
            return
        profile_id = next(iter(people))
        english, maths = _enrolments(c, profile_id)
        if len(english) != 1 or len(maths) != 1:
            _log(['Atticus 价格不改：英语或数学课不是一门。'])
            return
        if _production(db_path):
            try:
                copied = _backup(db_path)
                _log([f'已备份到 {copied}，没有替换正在用的数据库。'])
            except (OSError, FileExistsError, FileNotFoundError, RuntimeError) as exc:
                _log([f'备份没有写成，价格这次不改：{exc}'])
                return
        decision = {'english_id': english[0]['id'], 'maths_id': maths[0]['id'], 'profile_id': profile_id}
        c.execute('SAVEPOINT atticus_prices')
        try:
            lines = apply_prices(c, decision)
        except Exception as exc:
            c.execute('ROLLBACK TO atticus_prices')
            c.execute('RELEASE atticus_prices')
            _log([f'Atticus 价格没有写成：{exc}'])
            return
        c.execute('RELEASE atticus_prices')
        _log(lines)
    except sqlite3.Error as exc:
        _log([f'Atticus 价格没有读成：{exc}'])


def _marked_price(c):
    tables = {row['name'] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'app_meta' not in tables:
        return False
    return c.execute('SELECT 1 FROM app_meta WHERE key=?', (PRICE_KEY,)).fetchone() is not None
