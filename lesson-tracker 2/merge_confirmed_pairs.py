"""Merge the pairs Helen confirmed are the same person.

Cathy Bao folds into Cathy. Zoey folds into Zoey Xue, and the kept name is
Zoey Xue unless the Zoey profile has more lessons or payments. A backup is
written first. A pair whose two profiles both have lessons or money is left
alone and named in the log.
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

import backup
import merge_named_profiles as pairs

KEY = 'merge_cathy_zoey_v1'
PAIRS = (
    {'label': 'Cathy', 'names': ('Cathy', 'Cathy Bao'), 'prefer_name': '', 'unless_name': ''},
    {'label': 'Zoey Xue', 'names': ('Zoey Xue', 'Zoey'), 'prefer_name': 'Zoey Xue', 'unless_name': 'Zoey'},
)


def _log(lines):
    print('\n'.join(lines), file=sys.stderr, flush=True)


def _marked(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'").fetchone():
        return False
    return c.execute('SELECT 1 FROM app_meta WHERE key=?', (KEY,)).fetchone() is not None


def _exact(c):
    found = {}
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_profiles'").fetchone():
        return found
    for profile in c.execute('SELECT id, name FROM student_profiles'):
        rows = c.execute('SELECT name FROM students WHERE profile_id=?', (profile['id'],)).fetchall()
        label = pairs._display_name(profile['name'], rows).strip()
        found.setdefault(label, []).append(profile['id'])
    return found


def _history(info):
    return (info['lessons'] or 0) + (info['ledger'] or 0) + (info['cash'] or 0) + (info['batches'] or 0)


def _kept_name(spec, keeper, people):
    prefer = spec['prefer_name']
    unless = spec['unless_name']
    if not prefer:
        return keeper['name']
    other = [person for person in people if person['name'].strip() == unless]
    chosen = [person for person in people if person['name'].strip() == prefer]
    if other and sum(_history(person) for person in other) > sum(_history(person) for person in chosen):
        return keeper['name']
    return prefer


def plan(c):
    grouped = _exact(c)
    actions = []
    for spec in PAIRS:
        people = []
        ambiguous = []
        for name in spec['names']:
            ids = grouped.get(name, [])
            if len(ids) > 1:
                ambiguous.append(name)
            people.extend(pairs._facts(c, profile_id) for profile_id in ids)
        if ambiguous:
            actions.append({'spec': spec, 'status': 'skip', 'people': people, 'why': '同名档案不止一个：' + '、'.join(ambiguous)})
            continue
        if len(people) < 2:
            actions.append({'spec': spec, 'status': 'single', 'count': len(people)})
            continue
        keeper = max(people, key=pairs._score)
        donors = [person for person in people if person['id'] != keeper['id']]
        blocked = []
        for donor in donors:
            why = pairs._conflict(keeper, donor)
            if why:
                blocked.append((donor, why))
        if blocked:
            actions.append({'spec': spec, 'status': 'skip', 'keeper': keeper, 'donors': donors, 'people': people, 'blocked': blocked})
            continue
        actions.append({
            'spec': spec, 'status': 'merge', 'keeper': keeper, 'donors': donors, 'people': people,
            'name': _kept_name(spec, keeper, people),
        })
    return actions


def dry_lines(actions):
    lines = ['DRY-RUN  合并 Cathy / Cathy Bao，Zoey Xue / Zoey']
    for action in actions:
        label = action['spec']['label']
        if action['status'] == 'single':
            lines.append(f"{label}：找到 {action['count']} 个档案，不用合并。")
            continue
        if action['status'] == 'skip' and action.get('why'):
            lines.append(f"{label}：不合并。{action['why']}")
            continue
        keeper = pairs._describe(action['keeper'])
        donors = '；'.join(pairs._describe(donor) for donor in action['donors'])
        if action['status'] == 'skip':
            why = '；'.join('、'.join(reasons) for _donor, reasons in action['blocked'])
            lines.append(f"{label}：不合并。保留 {keeper}。另一份 {donors}。原因：{why}")
            continue
        lines.append(f"{label}：保留 {keeper}，姓名用「{action['name']}」。并入后删除 {donors}。")
    return lines


def _rename(c, profile_id, name):
    if not name:
        return
    c.execute('UPDATE student_profiles SET name=? WHERE id=?', (name, profile_id))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='students'").fetchone():
        c.execute('UPDATE students SET name=? WHERE profile_id=?', (name, profile_id))


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
            pairs._move_prices(c, keeper['id'], donor['id'])
            pairs._move_origin(c, keeper, donor)
            pairs._copy_text(c, keeper['id'], donor['id'])
            left = c.execute('SELECT COUNT(*) FROM students WHERE profile_id=?', (donor['id'],)).fetchone()[0]
            if left:
                raise RuntimeError(f"{donor['name']} 的档案 #{donor['id']} 仍有课程，没有删除。")
            c.execute('DELETE FROM student_profiles WHERE id=?', (donor['id'],))
        _rename(c, keeper['id'], action['name'])
        merged.append((action['spec']['label'], keeper['id'], action['name'], [donor['id'] for donor in action['donors']]))
    c.execute('INSERT OR IGNORE INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))
    return merged


def _production(db_path):
    real = os.path.realpath(db_path) if db_path else ''
    return real == '/var/data/lessons.sqlite3' or real.startswith('/var/data/')


def _backup(db_path):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    destination = f'/var/data/backup-merge-cathy-zoey-{stamp}.sqlite3'
    backup.write_snapshot(db_path, destination)
    return destination


def run(c, db_path):
    try:
        if _marked(c):
            return
        actions = plan(c)
    except sqlite3.Error as exc:
        _log([f'Cathy 和 Zoey 没有读成：{exc}'])
        return
    _log(dry_lines(actions))
    if not any(action['status'] == 'merge' for action in actions):
        populated = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_profiles'").fetchone() and c.execute('SELECT COUNT(*) n FROM student_profiles').fetchone()['n']
        if populated and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'").fetchone():
            c.execute('INSERT OR IGNORE INTO app_meta(key, value) VALUES(?,?)', (KEY, '1'))
        if any(action['status'] == 'skip' for action in actions):
            _log(['有一对因为上课或账目冲突没有合并。'])
        elif populated:
            _log(['没有需要合并的 Cathy 或 Zoey。'])
        return
    if _production(db_path):
        try:
            copied = _backup(db_path)
        except (OSError, FileExistsError, FileNotFoundError, RuntimeError) as exc:
            _log([f'备份没有写成，这次不合并：{exc}'])
            return
        _log([f'已备份到 {copied}，没有替换正在用的数据库。'])
    c.execute('SAVEPOINT merge_cathy_zoey')
    try:
        merged = apply(c, actions)
    except Exception as exc:
        c.execute('ROLLBACK TO merge_cathy_zoey')
        c.execute('RELEASE merge_cathy_zoey')
        _log([f'没有合并：{exc}'])
        return
    c.execute('RELEASE merge_cathy_zoey')
    done = '；'.join(
        f"{label} 保留 #{keeper}（{name}）删除 {','.join('#'+str(item) for item in donors)}"
        for label, keeper, name, donors in merged)
    _log([f'APPLY  已合并：{done}'])
