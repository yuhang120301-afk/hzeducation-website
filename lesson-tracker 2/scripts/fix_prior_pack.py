#!/usr/bin/env python3
"""Correct one back-dated pack to the numbers Helen gives.

The pack is rebuilt the way 补录以前的包 would have stored it:
已用付费 = 总节数 − 还剩付费, written as history only (no class, no teacher pay).
Gift left at entry is the gift she names. A later real lesson stays deducted,
paid hours first, and is listed. 金额 and 收钱日期 stay unless --amount is set.
Future lesson price is 金额 ÷ (总节数 + 赠送).

Dry-run is the default. Do not set LESSON_DB.

  python3 scripts/fix_prior_pack.py --student Aaron --total 20 --gift 1 --remaining-paid 13 --remaining-gift 1
  python3 scripts/fix_prior_pack.py --student Aaron --total 20 --gift 1 --remaining-paid 13 --remaining-gift 1 --apply
"""
import argparse
import os
import secrets
import sqlite3
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LESSON = 100
HISTORY_NOTE = '补录已用课时，没有对应课程'


def connect(db_path):
    c = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c


def norm_name(value):
    return ' '.join(str(value or '').strip().casefold().split())


def to_units(raw, label):
    try:
        number = Decimal(str(raw).strip())
    except (InvalidOperation, AttributeError):
        raise SystemExit(f'{label}不是数字。')
    if number < 0 or number > 10000:
        raise SystemExit(f'{label}要在 0 到 10000 之间。')
    scaled = number * LESSON
    if scaled != scaled.to_integral_value():
        raise SystemExit(f'{label}最多两位小数。')
    return int(scaled)


def money_to_cents(raw):
    try:
        number = Decimal(str(raw).strip())
    except (InvalidOperation, AttributeError):
        raise SystemExit('金额不是数字。')
    cents = number * 100
    if cents != cents.to_integral_value() or cents < 0:
        raise SystemExit('金额要是 0 以上，最多两位小数。')
    return int(cents)


def lessons(units):
    units = int(units or 0)
    sign = '-' if units < 0 else ''
    units = abs(units)
    if units % LESSON == 0:
        return sign + str(units // LESSON)
    return sign + f'{units / LESSON:.2f}'.rstrip('0').rstrip('.')


def money(cents):
    if cents is None:
        return '—'
    cents = int(cents)
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}${cents // 100}.{cents % 100:02d}'


def per_lesson_cents(cash, pool):
    if cash is None or pool <= 0:
        return None
    return (int(cash) * LESSON + pool // 2) // pool


def _columns(c, table):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return set()
    return {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}


def find_students(c, name):
    wanted = norm_name(name)
    rows = [dict(row) for row in c.execute('SELECT id, name FROM students ORDER BY id')]
    exact = [row for row in rows if norm_name(row['name']) == wanted]
    if exact:
        return exact
    partial = [row for row in rows if wanted and (wanted in norm_name(row['name']).split() or norm_name(row['name']).startswith(wanted))]
    return partial


def load_packs(c, student_ids, batch_id):
    batch_cols = _columns(c, 'credit_batches')
    status = 'b.status' if 'status' in batch_cols else "''"
    fees = 'b.unit_fees' if 'unit_fees' in batch_cols else "''"
    total = 'b.total_cents' if 'total_cents' in batch_cols else 'NULL'
    where = 'l.kind=\'credit\' AND l.note LIKE \'%补录%\''
    params = []
    if batch_id:
        where += ' AND b.id=?'
        params.append(batch_id)
    if student_ids:
        marks = ','.join('?' for _ in student_ids)
        where += f' AND b.student_id IN ({marks})'
        params.extend(student_ids)
    rows = c.execute(f'''SELECT b.id, b.student_id, b.ledger_id, b.purchased, b.gifted, b.paid_left, b.gift_left,
            {total} AS total_cents, {fees} AS unit_fees, {status} AS status,
            l.lesson_date, l.note, l.delta, l.actor_id, l.request_id, s.name AS student, s.course, s.balance,
            cash.cash_delta
        FROM credit_batches b
        JOIN ledger l ON l.id=b.ledger_id
        JOIN students s ON s.id=b.student_id
        LEFT JOIN cash_entries cash ON cash.ledger_id=l.id
        WHERE {where}
        ORDER BY b.id''', params).fetchall()
    return [dict(row) for row in rows]


def _movements(c, batch_id):
    rows = c.execute('''SELECT m.ledger_id, m.paid, m.gift, m.voided, l.kind, l.note, l.lesson_date, l.delta,
            l.reversal_of, l.request_id,
            EXISTS(SELECT 1 FROM ledger r WHERE r.reversal_of=l.id) AS reversed,
            (SELECT COUNT(*) FROM lesson_reports r WHERE r.ledger_id=l.id) AS reports
        FROM credit_movements m
        JOIN ledger l ON l.id=m.ledger_id
        WHERE m.batch_id=?
        ORDER BY m.ledger_id''', (batch_id,)).fetchall()
    return [dict(row) for row in rows]


def classify(pack, movements):
    credit, history, real, reversed_rows = [], [], [], []
    blocked = []
    for row in movements:
        if row['ledger_id'] == pack['ledger_id'] or row['kind'] == 'credit':
            credit.append(row)
            continue
        if row['reversal_of'] or row['reversed']:
            reversed_rows.append(row)
            continue
        if '补录已用课时' in (row['note'] or '') and not row['reports']:
            history.append(row)
            continue
        if row['kind'] in ('refund', 'switch'):
            blocked.append(row)
            continue
        real.append(row)
    return credit, history, real, reversed_rows, blocked


def _take(row):
    paid = -int(row['paid']) if int(row['paid']) < 0 else 0
    gift = -int(row['gift']) if int(row['gift']) < 0 else 0
    return paid + gift


def plan_correction(pack, movements, total, gift, remaining_paid, remaining_gift, new_cents):
    if pack.get('status') in ('voided', 'switched'):
        raise SystemExit(f"课时包 #{pack['id']} 已作废或已换走，不能改。")
    credit, history, real, reversed_rows, blocked = classify(pack, movements)
    if blocked:
        listed = '，'.join(f"#{row['ledger_id']} {row['kind']} {row['lesson_date']}" for row in blocked)
        raise SystemExit(f'这包还有退费或换课，不能用这个脚本改：{listed}。')
    if len(credit) != 1:
        raise SystemExit(f"课时包 #{pack['id']} 的充值记录不是一条，不能改。")
    if len(history) > 1:
        listed = '，'.join(f"#{row['ledger_id']}" for row in history)
        raise SystemExit(f'补录已用记录有好几条，不能改：{listed}。')
    if remaining_paid > total:
        raise SystemExit('还剩付费不能多于总节数。')
    if remaining_gift > gift:
        raise SystemExit('还剩赠送不能多于赠送总节数。')
    for row in real:
        if _take(row) <= 0 and (int(row['paid']) > 0 or int(row['gift']) > 0):
            raise SystemExit(f"账目 #{row['ledger_id']} 往这包里加了课时，不能用这个脚本改。")
    paid_left = remaining_paid
    gift_left = remaining_gift
    realloc = []
    for row in real:
        taken = _take(row)
        from_paid = min(paid_left, taken)
        from_gift = taken - from_paid
        if from_gift > gift_left:
            raise SystemExit(
                f"补录之后的课已经扣了 {lessons(taken)} 节（账目 #{row['ledger_id']} {row['lesson_date']}），"
                f"多于更正后还剩的 {lessons(remaining_paid)} 节付费和 {lessons(remaining_gift)} 节赠送。没有改。")
        paid_left -= from_paid
        gift_left -= from_gift
        realloc.append({'ledger_id': row['ledger_id'], 'date': row['lesson_date'], 'taken': taken,
            'paid': -from_paid, 'gift': -from_gift, 'old_paid': int(row['paid']), 'old_gift': int(row['gift'])})
    history_paid = -(total - remaining_paid)
    history_gift = -(gift - remaining_gift)
    cash = new_cents if new_cents is not None else pack['cash_delta']
    pool = total + gift
    return {
        'purchased': total,
        'gifted': gift,
        'paid_left': paid_left,
        'gift_left': gift_left,
        'entry_paid': remaining_paid,
        'entry_gift': remaining_gift,
        'history_paid': history_paid,
        'history_gift': history_gift,
        'history': history[0] if history else None,
        'credit': credit[0],
        'real': realloc,
        'reversed': len(reversed_rows),
        'cash': cash,
        'per_lesson': per_lesson_cents(cash, pool),
        'date': pack['lesson_date'],
    }


def describe(pack, correction):
    cash = pack['cash_delta'] if pack['cash_delta'] is not None else pack['total_cents']
    lines = [
        f"学生 {pack['student']} · {pack['course']} · 课时包 #{pack['id']} · 收钱日期 {pack['lesson_date']} · 金额 {money(cash)}",
        f"改前  总节数 {lessons(pack['purchased'])}  赠送 {lessons(pack['gifted'])}  剩余付费 {lessons(pack['paid_left'])}  剩余赠送 {lessons(pack['gift_left'])}",
        f"改后  总节数 {lessons(correction['purchased'])}  赠送 {lessons(correction['gifted'])}  剩余付费 {lessons(correction['paid_left'])}  剩余赠送 {lessons(correction['gift_left'])}",
        f"补录时还剩付费 {lessons(correction['entry_paid'])}，已用付费 {lessons(-(correction['history_paid']))} 只记历史，不排课也不算工资。",
    ]
    price = correction['per_lesson']
    lines.append(f"以后每节 {money(price) if price is not None else '—'}（金额 ÷（总节数 + 赠送））。")
    if correction['real']:
        lines.append('补录之后已经上过这些课，仍然扣着，先扣付费再扣赠送：')
        for row in correction['real']:
            lines.append(f"  账目 #{row['ledger_id']} {row['date']} 扣 {lessons(row['taken'])} 节")
        lines.append(f"所以现在剩余付费是 {lessons(correction['paid_left'])}，剩余赠送是 {lessons(correction['gift_left'])}。")
    else:
        lines.append('补录之后没有从这包扣过真正上过的课。')
    if correction['reversed']:
        lines.append(f"另有 {correction['reversed']} 条已撤销的扣课，不计算。")
    same_cash = correction['cash'] == pack['cash_delta'] or (correction['cash'] is None and pack['cash_delta'] is None)
    lines.append('收款和收钱日期不变。' if same_cash and correction['date'] == pack['lesson_date'] else '收款按 --amount 修改。收钱日期不变。')
    return '\n'.join(lines)


def unchanged(pack, correction):
    if any(int(row['old_paid']) != int(row['paid']) or int(row['old_gift']) != int(row['gift']) for row in correction['real']):
        return False
    history = correction['history']
    history_paid = int(history['paid']) if history else 0
    history_gift = int(history['gift']) if history else 0
    credit = correction['credit']
    return (
        int(pack['purchased']) == correction['purchased']
        and int(pack['gifted']) == correction['gifted']
        and int(pack['paid_left']) == correction['paid_left']
        and int(pack['gift_left']) == correction['gift_left']
        and int(credit['paid']) == correction['purchased']
        and int(credit['gift']) == correction['gifted']
        and history_paid == correction['history_paid']
        and history_gift == correction['history_gift']
        and (correction['cash'] == pack['cash_delta'] or correction['cash'] is None)
    )


def _resync(c, ledger_id):
    sums = c.execute('SELECT COALESCE(SUM(paid),0), COALESCE(SUM(gift),0), COALESCE(SUM(voided),0) FROM credit_movements WHERE ledger_id=?', (ledger_id,)).fetchone()
    delta = int(sums[0]) + int(sums[1])
    old = int(c.execute('SELECT delta FROM ledger WHERE id=?', (ledger_id,)).fetchone()['delta'])
    c.execute('UPDATE ledger SET delta=?, paid_delta=?, gift_delta=?, gift_void=?, split_known=1 WHERE id=?',
        (delta, int(sums[0]), int(sums[1]), int(sums[2]), ledger_id))
    return delta - old


def _set_movement(c, ledger_id, batch_id, paid, gift):
    found = c.execute('SELECT 1 FROM credit_movements WHERE ledger_id=? AND batch_id=?', (ledger_id, batch_id)).fetchone()
    if found:
        c.execute('UPDATE credit_movements SET paid=?, gift=? WHERE ledger_id=? AND batch_id=?', (paid, gift, ledger_id, batch_id))
    else:
        c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)',
            (ledger_id, batch_id, paid, gift))


def _note(note, gift_units):
    import re
    text = note or ''
    label = lessons(gift_units)
    if '还剩赠送' in text:
        return re.sub(r'还剩赠送\s*[0-9]+(?:\.[0-9]+)?', f'还剩赠送 {label}', text, count=1)
    if '补录' in text:
        return text + f' · 还剩赠送 {label} 节'
    return text


def apply_correction(c, pack, correction, user):
    import auditlog
    if unchanged(pack, correction):
        return 0
    auditlog.begin(c)
    auditlog.hint(c, f"更正补录 {pack['student']} 总节数 {lessons(correction['purchased'])} 赠送 {lessons(correction['gifted'])} 还剩付费 {lessons(correction['entry_paid'])} 还剩赠送 {lessons(correction['entry_gift'])}"[:200])
    before_cash = c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0]
    before_dates = {row['id']: row['lesson_date'] for row in c.execute('SELECT id, lesson_date FROM ledger')}
    c.execute('UPDATE credit_batches SET purchased=?, gifted=?, paid_left=?, gift_left=? WHERE id=?',
        (correction['purchased'], correction['gifted'], correction['paid_left'], correction['gift_left'], pack['id']))
    if 'unit_fees' in _columns(c, 'credit_batches'):
        c.execute("UPDATE credit_batches SET unit_fees='' WHERE id=?", (pack['id'],))
    _set_movement(c, pack['ledger_id'], pack['id'], correction['purchased'], correction['gifted'])
    c.execute('UPDATE ledger SET note=? WHERE id=?', (_note(pack['note'], correction['gifted']), pack['ledger_id']))
    delta_change = _resync(c, pack['ledger_id'])
    if correction['history']:
        history_id = correction['history']['ledger_id']
    elif correction['history_paid'] or correction['history_gift']:
        request_id = (pack.get('request_id') or secrets.token_hex(16)) + '-used'
        if c.execute('SELECT 1 FROM ledger WHERE request_id=?', (request_id,)).fetchone() or len(request_id) > 80:
            request_id = secrets.token_hex(16)
        history_id = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
            VALUES(?,0,'lesson',?,?,?,?)''', (
            pack['student_id'], pack['lesson_date'], HISTORY_NOTE, pack['actor_id'], request_id)).lastrowid
    else:
        history_id = None
    if history_id:
        _set_movement(c, history_id, pack['id'], correction['history_paid'], correction['history_gift'])
        delta_change += _resync(c, history_id)
    for row in correction['real']:
        _set_movement(c, row['ledger_id'], pack['id'], row['paid'], row['gift'])
        delta_change += _resync(c, row['ledger_id'])
    if correction['cash'] is not None and correction['cash'] != pack['cash_delta']:
        c.execute('UPDATE cash_entries SET cash_delta=? WHERE ledger_id=?', (correction['cash'], pack['ledger_id']))
        if 'total_cents' in _columns(c, 'credit_batches'):
            c.execute('UPDATE credit_batches SET total_cents=? WHERE id=?', (correction['cash'], pack['id']))
        if _columns(c, 'vouchers'):
            c.execute('UPDATE vouchers SET amount_cents=? WHERE ledger_id=?', (correction['cash'], pack['ledger_id']))
    if _columns(c, 'vouchers'):
        c.execute('UPDATE vouchers SET paid_units=?, gift_units=? WHERE ledger_id=?',
            (correction['purchased'], correction['gifted'], pack['ledger_id']))
    c.execute('UPDATE students SET balance=balance+? WHERE id=?', (delta_change, pack['student_id']))
    stored = c.execute('SELECT paid_left, gift_left, purchased, gifted FROM credit_batches WHERE id=?', (pack['id'],)).fetchone()
    moved = c.execute('SELECT COALESCE(SUM(paid),0) paid, COALESCE(SUM(gift),0) gift FROM credit_movements WHERE batch_id=?', (pack['id'],)).fetchone()
    if int(stored['paid_left']) != int(moved['paid']) or int(stored['gift_left']) != int(moved['gift']):
        raise RuntimeError('课时包剩余和明细对不上，已停止。')
    if int(stored['purchased']) != correction['purchased'] or int(stored['gifted']) != correction['gifted']:
        raise RuntimeError('总节数没有写成指定的数，已停止。')
    after_dates = {row['id']: row['lesson_date'] for row in c.execute('SELECT id, lesson_date FROM ledger')}
    if any(before_dates.get(key) != value for key, value in after_dates.items() if key in before_dates):
        raise RuntimeError('收钱日期变了，已停止。')
    after_cash = c.execute('SELECT COALESCE(SUM(cash_delta),0) FROM cash_entries').fetchone()[0]
    expected_cash = before_cash if correction['cash'] == pack['cash_delta'] or correction['cash'] is None else before_cash - int(pack['cash_delta'] or 0) + int(correction['cash'])
    if after_cash != expected_cash:
        raise RuntimeError('收款数字不对，已停止。')
    auditlog.finish(c, user)
    return delta_change


def _owner(c):
    row = c.execute('SELECT user_id FROM organization_owners ORDER BY user_id LIMIT 1').fetchone()
    if not row:
        raise SystemExit('没有老板账号，不能写入。')
    return {'id': row['user_id'], 'role': 'owner'}


def main():
    parser = argparse.ArgumentParser(description='Correct one back-dated pack.')
    parser.add_argument('--db', default=os.environ.get('LESSON_DB', ''))
    parser.add_argument('--student', required=True)
    parser.add_argument('--batch', type=int)
    parser.add_argument('--total', required=True, help='Paid lessons in the pack.')
    parser.add_argument('--gift', required=True, help='Gift lessons in the pack.')
    parser.add_argument('--remaining-paid', required=True)
    parser.add_argument('--remaining-gift', required=True)
    parser.add_argument('--amount', help='New pack amount in dollars. Omit to keep the current amount.')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.db or not os.path.exists(args.db):
        raise SystemExit('请设置 LESSON_DB，或传入 --db。')
    total = to_units(args.total, '总节数')
    gift = to_units(args.gift, '赠送')
    remaining_paid = to_units(args.remaining_paid, '还剩付费')
    remaining_gift = to_units(args.remaining_gift, '还剩赠送')
    new_cents = money_to_cents(args.amount) if args.amount is not None else None
    import auditlog
    import credit_batches
    c = connect(args.db)
    try:
        credit_batches.schema(c)
        auditlog.schema(c)
        students = find_students(c, args.student)
        if args.batch and not students:
            packs = load_packs(c, [], args.batch)
        else:
            if not students:
                raise SystemExit(f'找不到学生 {args.student}。')
            if len({row['id'] for row in students}) > 1 and not args.batch:
                listed = '，'.join(f"#{row['id']} {row['name']}" for row in students)
                raise SystemExit(f'有好几位同名学生：{listed}。请加上 --batch。')
            packs = load_packs(c, [row['id'] for row in students], args.batch)
        if not packs:
            raise SystemExit('没有找到这个学生的补录课时包。')
        if len(packs) > 1:
            lines = [f"{args.student} 有好几包补录，请加上 --batch："]
            for pack in packs:
                lines.append(f"  #{pack['id']} {pack['student']} {pack['lesson_date']} {money(pack['cash_delta'])} 总节数 {lessons(pack['purchased'])} 剩余付费 {lessons(pack['paid_left'])}")
            raise SystemExit('\n'.join(lines))
        pack = packs[0]
        if args.batch and norm_name(args.student) not in norm_name(pack['student']) and norm_name(pack['student']) != norm_name(args.student):
            if not (norm_name(args.student) in norm_name(pack['student']).split() or norm_name(pack['student']).startswith(norm_name(args.student))):
                raise SystemExit(f"课时包 #{pack['id']} 是 {pack['student']} 的，不是 {args.student}。")
        movements = _movements(c, pack['id'])
        correction = plan_correction(pack, movements, total, gift, remaining_paid, remaining_gift, new_cents)
        print('APPLY' if args.apply else 'DRY-RUN')
        print(describe(pack, correction))
        if unchanged(pack, correction):
            print('已经是这些数字。')
        elif args.apply:
            user = _owner(c)
            c.execute('BEGIN IMMEDIATE')
            apply_correction(c, pack, correction, user)
            c.execute('COMMIT')
            print('已写入。')
        else:
            print('未写入。加上 --apply 才会改。')
        print(f"database={os.path.realpath(args.db)}")
    except BaseException:
        if c.in_transaction:
            c.execute('ROLLBACK')
        raise


if __name__ == '__main__':
    main()
