"""Merge the duplicate profiles Helen named: Miya, Rebecca, and Zoey Xue.

Keeps the profile that has courses, lessons, or a parent login, otherwise the
older one. An empty duplicate's parents, notes, and original-student tick move
across, then the empty profile is removed. If the duplicate has lessons or
money that cannot be combined cleanly, that person is left untouched.
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

import backup

KEY = 'merge_miya_rebecca_zoey_v1'
NAMES = ('Miya', 'Rebecca', 'Zoey Xue')


def _log(lines):
    print('\n'.join(lines), file=sys.stderr, flush=True)


def _marked(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'").fetchone():
        return False
    return c.execute('SELECT 1 FROM app_meta WHERE key=?', (KEY,)).fetchone() is not None


def _norm(value):
    return ' '.join(str(value or '').strip().casefold().split())


def _display_name(profile_name, rows):
    name = (profile_name or '').strip()
    if name:
        return name
    for row in rows:
        if (row['name'] or '').strip():
            return row['name'].strip()
    return ''


def _ids(rows):
    return [row['id'] for row in rows]


def _count(c, sql, ids):
    if not ids:
        return 0
    marks = ','.join('?' for _ in ids)
    return int(c.execute(sql.format(marks=marks), ids).fetchone()[0])


def _facts(c, profile_id):
    profile = c.execute('SELECT * FROM student_profiles WHERE id=?', (profile_id,)).fetchone()
    rows = [dict(row) for row in c.execute(
        '''SELECT id, name, course, helen_original, archived, IFNULL(voided,0) voided
           FROM students WHERE profile_id=? ORDER BY archived, id''', (profile_id,))]
    ids = _ids(rows)
    lessons = _count(c, 'SELECT COUNT(*) FROM lesson_students WHERE student_id IN ({marks})', ids)
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_reports'").fetchone():
        lessons += _count(c, 'SELECT COUNT(*) FROM lesson_reports WHERE student_id IN ({marks})', ids)
    ledger = _count(c, 'SELECT COUNT(*) FROM ledger WHERE student_id IN ({marks})', ids)
    cash = 0
    if ids and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cash_entries'").fetchone():
        marks = ','.join('?' for _ in ids)
        cash = int(c.execute(f'''SELECT COUNT(*) FROM cash_entries e
            JOIN ledger l ON l.id=e.ledger_id WHERE l.student_id IN ({marks})''', ids).fetchone()[0])
    batches = 0
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='credit_batches'").fetchone():
        batches = _count(c, 'SELECT COUNT(*) FROM credit_batches WHERE student_id IN ({marks})', ids)
    parents = []
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_parents'").fetchone():
        parents = [row['user_id'] for row in c.execute(
            'SELECT user_id FROM profile_parents WHERE profile_id=?', (profile_id,))]
    live = [row['course'] for row in rows if not row['archived'] and not row['voided'] and (row['course'] or '').strip()]
    courses = [row['course'] for row in rows if (row['course'] or '').strip()]
    flag = None
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_origin_events'").fetchone():
        latest = c.execute('''SELECT helen_original FROM student_origin_events
            WHERE profile_id=? ORDER BY effective_from DESC, id DESC LIMIT 1''', (profile_id,)).fetchone()
        if latest is not None:
            flag = int(latest['helen_original'])
    if flag is None and rows:
        flag = max(int(row['helen_original'] or 0) for row in rows)
    return {
        'id': profile_id,
        'name': _display_name(profile['name'] if profile else '', rows),
        'notes': (profile['notes'] if profile and 'notes' in profile.keys() else '') or '',
        'rows': rows,
        'courses': courses,
        'live': live,
        'lessons': lessons,
        'ledger': ledger,
        'cash': cash,
        'batches': batches,
        'parents': parents,
        'flag': flag,
    }


def _score(info):
    money = info['lessons'] or info['ledger'] or info['cash'] or info['batches']
    return (1 if info['live'] else 0, 1 if info['courses'] else 0, 1 if money else 0, 1 if info['parents'] else 0, -info['id'])


def _conflict(keeper, donor):
    reasons = []
    overlap = sorted(set(keeper['courses']) & set(donor['courses']))
    if overlap:
        reasons.append('课程重复：' + '、'.join(overlap))
    donor_money = donor['lessons'] or donor['ledger'] or donor['cash'] or donor['batches']
    keeper_money = keeper['lessons'] or keeper['ledger'] or keeper['cash'] or keeper['batches']
    if donor_money and keeper_money:
        reasons.append('两边都有上课记录或账目')
    elif donor_money and keeper['flag'] not in (None, donor['flag']) and keeper['courses']:
        reasons.append('重复档案上的上课记录和保留档案的原有学生标记对不上')
    return reasons


def plan(c):
    wanted = {_norm(name): name for name in NAMES}
    grouped = {key: [] for key in wanted}
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_profiles'").fetchone():
        return []
    for profile in c.execute('SELECT id, name FROM student_profiles'):
        rows = c.execute('SELECT name FROM students WHERE profile_id=?', (profile['id'],)).fetchall()
        label = _display_name(profile['name'], rows)
        key = _norm(label)
        if key in wanted:
            grouped[key].append(_facts(c, profile['id']))
    actions = []
    for key, label in wanted.items():
        people = grouped[key]
        if len(people) < 2:
            actions.append({'name': label, 'status': 'single', 'count': len(people)})
            continue
        keeper = max(people, key=_score)
        donors = [person for person in people if person['id'] != keeper['id']]
        blocked = []
        for donor in donors:
            why = _conflict(keeper, donor)
            if why:
                blocked.append((donor, why))
        if blocked:
            actions.append({'name': label, 'status': 'skip', 'keeper': keeper, 'donors': donors, 'blocked': blocked})
            continue
        actions.append({'name': label, 'status': 'merge', 'keeper': keeper, 'donors': donors})
    return actions


def _describe(person):
    courses = '、'.join(person['courses']) if person['courses'] else '无课程'
    bits = [f"#{person['id']}（{courses}）"]
    if person['parents']:
        bits.append(f"家长 {len(person['parents'])}")
    if person['lessons'] or person['ledger'] or person['cash'] or person['batches']:
        bits.append('有上课或账目')
    if person['flag']:
        bits.append('已标原有学生')
    return ' '.join(bits)


def dry_lines(actions):
    lines = ['DRY-RUN  合并重复学生 Miya、Rebecca、Zoey Xue']
    for action in actions:
        if action['status'] == 'single':
            lines.append(f"{action['name']}：找到 {action['count']} 个档案，不用合并。")
            continue
        keeper = _describe(action['keeper'])
        donors = '；'.join(_describe(donor) for donor in action['donors'])
        if action['status'] == 'skip':
            why = '；'.join('、'.join(reasons) for _donor, reasons in action['blocked'])
            lines.append(f"{action['name']}：不合并。保留 {keeper}。重复档案 {donors}。原因：{why}")
            continue
        lines.append(f"{action['name']}：保留 {keeper}。并入后删除 {donors}。")
    return lines


def _copy_text(c, keeper_id, donor_id):
    cols = {row['name'] for row in c.execute('PRAGMA table_info(student_profiles)')}
    fields = [name for name in ('birthday', 'grade', 'notes', 'school', 'health_notes', 'parent_email') if name in cols]
    if not fields:
        return
    keeper = c.execute(f"SELECT {', '.join(fields)} FROM student_profiles WHERE id=?", (keeper_id,)).fetchone()
    donor = c.execute(f"SELECT {', '.join(fields)} FROM student_profiles WHERE id=?", (donor_id,)).fetchone()
    updates = []
    values = []
    for name in fields:
        current = (keeper[name] or '').strip()
        extra = (donor[name] or '').strip()
        if not extra or extra == current:
            continue
        if not current:
            updates.append(f'{name}=?')
            values.append(extra)
        elif name == 'notes':
            updates.append('notes=?')
            values.append(current + '\n' + extra)
    if updates:
        c.execute(f"UPDATE student_profiles SET {', '.join(updates)} WHERE id=?", (*values, keeper_id))


def _move_origin(c, keeper, donor):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_origin_events'").fetchone():
        return
    # A kept profile that already has lessons keeps its own tick. An empty
    # duplicate must not rewrite those lessons.
    if keeper['lessons'] or keeper['ledger'] or keeper['cash'] or keeper['batches']:
        c.execute('DELETE FROM student_origin_events WHERE profile_id=?', (donor['id'],))
        return
    keeper_events = c.execute('SELECT COUNT(*) FROM student_origin_events WHERE profile_id=?', (keeper['id'],)).fetchone()[0]
    if keeper_events:
        c.execute('DELETE FROM student_origin_events WHERE profile_id=?', (donor['id'],))
        return
    c.execute('UPDATE student_origin_events SET profile_id=? WHERE profile_id=?', (keeper['id'], donor['id']))


def _move_prices(c, keeper_id, donor_id):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_subject_prices'").fetchone():
        return
    for row in c.execute('SELECT id, product, subject, lesson_minutes FROM student_subject_prices WHERE profile_id=?', (donor_id,)):
        clash = c.execute('''SELECT id FROM student_subject_prices
            WHERE profile_id=? AND product=? AND subject=? AND lesson_minutes=?''',
            (keeper_id, row['product'], row['subject'], row['lesson_minutes'])).fetchone()
        if clash:
            c.execute('DELETE FROM student_subject_prices WHERE id=?', (row['id'],))
        else:
            c.execute('UPDATE student_subject_prices SET profile_id=? WHERE id=?', (keeper_id, row['id']))


def apply(c, actions):
    merged = []
    for action in actions:
        if action['status'] != 'merge':
            continue
        keeper = action['keeper']
        for donor in action['donors']:
            c.execute('UPDATE students SET profile_id=? WHERE profile_id=?', (keeper['id'], donor['id']))
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_parents'").fetchone():
                c.execute('''INSERT OR IGNORE INTO profile_parents(profile_id, user_id)
                    SELECT ?, user_id FROM profile_parents WHERE profile_id=?''', (keeper['id'], donor['id']))
                c.execute('DELETE FROM profile_parents WHERE profile_id=?', (donor['id'],))
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_events'").fetchone():
                c.execute('UPDATE profile_events SET profile_id=? WHERE profile_id=?', (keeper['id'], donor['id']))
            _move_prices(c, keeper['id'], donor['id'])
            _move_origin(c, keeper, donor)
            _copy_text(c, keeper['id'], donor['id'])
            left = c.execute('SELECT COUNT(*) FROM students WHERE profile_id=?', (donor['id'],)).fetchone()[0]
            if left:
                raise RuntimeError(f"{action['name']} 的重复档案 #{donor['id']} 仍有课程，没有删除。")
            c.execute('DELETE FROM student_profiles WHERE id=?', (donor['id'],))
            merged.append((action['name'], keeper['id'], donor['id']))
    c.execute('INSERT INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))
    return merged


def _production(db_path):
    real = os.path.realpath(db_path) if db_path else ''
    return real == '/var/data/lessons.sqlite3' or real.startswith('/var/data/')


def _backup(db_path):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    destination = f'/var/data/backup-merge-profiles-{stamp}.sqlite3'
    backup.write_snapshot(db_path, destination)
    return destination


def run(c, db_path):
    try:
        if _marked(c):
            return
        actions = plan(c)
    except sqlite3.Error as exc:
        _log([f'重复学生没有读成：{exc}'])
        return
    lines = dry_lines(actions)
    _log(lines)
    if not any(action['status'] == 'merge' for action in actions):
        seen = any(action['count'] for action in actions if action['status'] == 'single') or any(
            action['status'] == 'skip' for action in actions)
        if seen and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'").fetchone():
            c.execute('INSERT OR IGNORE INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))
        if any(action['status'] == 'skip' for action in actions):
            _log(['有人因为上课或账目冲突没有合并。'])
        else:
            _log(['没有需要合并的重复档案。'])
        return
    if _production(db_path):
        try:
            copied = _backup(db_path)
        except (OSError, FileExistsError, FileNotFoundError, RuntimeError) as exc:
            _log([f'备份没有写成，这次不合并：{exc}'])
            return
        _log([f'已备份到 {copied}，没有替换正在用的数据库。'])
    c.execute('SAVEPOINT merge_profiles')
    try:
        merged = apply(c, actions)
    except Exception as exc:
        c.execute('ROLLBACK TO merge_profiles')
        c.execute('RELEASE merge_profiles')
        _log([f'没有合并：{exc}'])
        return
    c.execute('RELEASE merge_profiles')
    done = '，'.join(f'{name} 保留 #{keeper} 删除 #{donor}' for name, keeper, donor in merged)
    _log([f'APPLY  已合并：{done}'])
