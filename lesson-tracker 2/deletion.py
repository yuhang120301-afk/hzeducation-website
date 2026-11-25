"""Owner-only deletion of unused profiles, and stopping one course."""
import json

from teaching import AccessError, now_local


def referenced(c, target, target_id, ignored=()):
    # Foreign keys are inspected so new business tables remain protected too.
    for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        table = row['name']
        if table in ignored:
            continue
        quoted = '"' + table.replace('"', '""') + '"'
        for fk in c.execute('PRAGMA foreign_key_list(' + quoted + ')').fetchall():
            column = '"' + fk['from'].replace('"', '""') + '"'
            if fk['table'] == target and c.execute('SELECT 1 FROM ' + quoted + ' WHERE ' + column + '=? LIMIT 1', (target_id,)).fetchone():
                return True
    return False


def remove(c, user, data):
    if user['role'] != 'owner':
        raise AccessError('只有老板可以删除档案。')
    kind = data.get('kind')
    ident = int(data.get('id', 0))
    if kind == 'student':
        student = c.execute('SELECT * FROM students WHERE id=?', (ident,)).fetchone()
        if not student:
            raise ValueError('学生档案不存在，请刷新页面。')
        if student['archived']:
            raise ValueError('学生已经归档，请刷新页面。')
        courses=list(c.execute('SELECT * FROM students WHERE profile_id=? AND archived=0', (student['profile_id'],)))
        c.execute('UPDATE students SET archived=1 WHERE profile_id=?', (student['profile_id'],))
        c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (student['id'],user['id'],'archived'))
        import vouchers
        for course in courses:
            vouchers.issue_stop(c, user, course, False)
    elif kind in ('teacher', 'admin'):
        if kind == 'teacher':
            target = c.execute('SELECT u.* FROM users u JOIN teachers t ON t.user_id=u.id WHERE t.id=?', (ident,)).fetchone()
        else:
            target = c.execute("SELECT * FROM users WHERE id=? AND role='admin'", (ident,)).fetchone()
        if not target:
            raise ValueError('账号不存在，请刷新页面。')
        uid = target['id']
        if uid == user['id'] or c.execute('SELECT 1 FROM organization_owners WHERE user_id=?', (uid,)).fetchone():
            raise ValueError('不能删除老板账号或当前登录账号。')
        if kind == 'teacher' and target['role'] == 'admin':
            raise ValueError('这是管理员账号，请从管理员页面操作。')
        teacher = c.execute('SELECT id FROM teachers WHERE user_id=?', (uid,)).fetchone()
        if referenced(c, 'users', uid, ('sessions', 'teachers')) or (teacher and referenced(c, 'teachers', teacher['id'])):
            raise ValueError('此账号有关联课程或业务记录，不能删除，请使用停用功能。')
        c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        c.execute('DELETE FROM teachers WHERE user_id=?', (uid,))
        c.execute('DELETE FROM users WHERE id=?', (uid,))
    else:
        raise ValueError('档案类型无效。')
    return {'ok': True}


def restore(c, user, data):
    if user['role'] != 'owner':
        raise AccessError('只有老板可以恢复课程。')
    student=c.execute('SELECT * FROM students WHERE id=? AND archived=1', (int(data.get('id',0)),)).fetchone()
    if not student:
        raise ValueError('已停的课程不存在，请刷新页面。')
    c.execute('UPDATE students SET archived=0 WHERE id=?', (student['id'],))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (student['id'],user['id'],'course_restored'))
    return {'ok':True}


def _history(c, sid):
    if c.execute('SELECT 1 FROM ledger WHERE student_id=?', (sid,)).fetchone():
        return True
    if c.execute('SELECT 1 FROM lesson_students WHERE student_id=?', (sid,)).fetchone():
        return True
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_reports'").fetchone() and c.execute('SELECT 1 FROM lesson_reports WHERE student_id=?', (sid,)).fetchone():
        return True
    if c.execute('SELECT 1 FROM credit_batches WHERE student_id=? AND (purchased>0 OR gifted>0 OR paid_left>0 OR gift_left>0)', (sid,)).fetchone():
        return True
    return False


def schema(c):
    cols = {row['name'] for row in c.execute('PRAGMA table_info(students)')}
    if 'voided' not in cols:
        c.execute('ALTER TABLE students ADD COLUMN voided INTEGER NOT NULL DEFAULT 0')
    if 'void_reason' not in cols:
        c.execute("ALTER TABLE students ADD COLUMN void_reason TEXT NOT NULL DEFAULT ''")


def _drop_future(c, sid, cancel_reason='停课'):
    """Cancel this course's future lessons and stop a series that would keep adding it."""
    now = now_local().strftime('%Y-%m-%dT%H:%M')
    lessons = list(c.execute('''SELECT l.id, l.series_id, l.occurrence_index FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE ls.student_id=? AND l.status='scheduled' AND l.starts_at>=?''', (sid, now)))
    seen = set()
    for lesson in lessons:
        others = c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id!=?', (lesson['id'], sid)).fetchone()
        if others:
            c.execute('DELETE FROM lesson_students WHERE lesson_id=? AND student_id=?', (lesson['id'], sid))
        else:
            c.execute("UPDATE lessons SET status='cancelled', cancel_reason=?, version=version+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (cancel_reason, lesson['id'],))
        if lesson['series_id']:
            seen.add(lesson['series_id'])
    for rule in c.execute('SELECT * FROM lesson_series'):
        try:
            template = json.loads(rule['template'] or '{}')
        except json.JSONDecodeError:
            continue
        raw = template.get('student_ids') or []
        ids = []
        for item in raw:
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                continue
        if sid not in ids and rule['id'] not in seen:
            continue
        template['student_ids'] = [item for item in raw if str(item) != str(sid)]
        if template['student_ids']:
            c.execute("UPDATE lesson_series SET template=?, version=version+1, error='' WHERE id=?", (json.dumps(template), rule['id']))
            continue
        indexes = [lesson['occurrence_index'] for lesson in lessons if lesson['series_id'] == rule['id'] and lesson['occurrence_index'] is not None]
        stop = min(indexes) if indexes else rule['next_index']
        if rule['stop_index'] is not None:
            stop = min(stop, rule['stop_index'])
        c.execute("UPDATE lesson_series SET template=?, endless=0, stop_index=?, version=version+1, error='' WHERE id=?", (json.dumps(template), stop, rule['id']))


def _tell_vouchers(c, user, student, deleted):
    """The receipt book, once it exists, records this stop. Missing module is fine."""
    try:
        import vouchers
    except ImportError:
        return
    issue = getattr(vouchers, 'issue_stop', None)
    if issue:
        issue(c, user, dict(student), deleted)


def stop_course(c, user, data):
    """Archive one course. A course with no lessons and no ledger is removed instead."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以停课。')
    sid = int(data.get('student_id') or data.get('id') or 0)
    student = c.execute('SELECT * FROM students WHERE id=? AND archived=0', (sid,)).fetchone()
    if not student:
        raise ValueError('这门课不存在，请刷新页面。')
    balance = student['balance']
    if not _history(c, sid):
        c.execute('DELETE FROM credit_batches WHERE student_id=?', (sid,))
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='arrears'").fetchone():
            c.execute('DELETE FROM arrears WHERE student_id=?', (sid,))
        c.execute('DELETE FROM profile_audit WHERE student_id=?', (sid,))
        c.execute('DELETE FROM students WHERE id=?', (sid,))
        _tell_vouchers(c, user, student, True)
        return {'ok': True, 'deleted': True, 'archived': False, 'balance': balance}
    _drop_future(c, sid)
    c.execute('UPDATE students SET archived=1 WHERE id=?', (sid,))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (sid, user['id'], 'course_stopped'))
    _tell_vouchers(c, user, student, False)
    return {'ok': True, 'deleted': False, 'archived': True, 'balance': balance}


def _has(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def course_problems(c, sid):
    """Why this course cannot be removed as a mistake. Empty means a void is allowed."""
    problems = []
    attended = c.execute('''SELECT COUNT(*) n FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE ls.student_id=? AND l.status='completed' ''', (sid,)).fetchone()['n']
    if _has(c, 'lesson_reports'):
        attended += c.execute('''SELECT COUNT(*) n FROM lesson_reports
            WHERE student_id=? AND (ledger_id IS NOT NULL OR content!='' OR homework!='' OR feedback!='')''', (sid,)).fetchone()['n']
    if attended:
        problems.append(f'已经上过或写过记录（{attended}）')
    charged = c.execute('''SELECT COUNT(*) n FROM ledger WHERE student_id=? AND kind='lesson'
        AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reversal_of=ledger.id)''', (sid,)).fetchone()['n']
    if charged:
        problems.append(f'已经扣过课时（{charged} 笔）')
    if _has(c, 'cash_entries'):
        money = c.execute('''SELECT COALESCE(SUM(ABS(cash.cash_delta)),0) n
            FROM cash_entries cash JOIN ledger l ON l.id=cash.ledger_id
            WHERE l.student_id=? AND cash.cash_delta!=0''', (sid,)).fetchone()['n']
        if money:
            problems.append('有收过或退过的钱')
    return problems


def _erase_zero_money(c, sid):
    """Drop packs and receipts that never moved money. Charged lessons are refused earlier."""
    ledger_ids = [row['id'] for row in c.execute(
        "SELECT id FROM ledger WHERE student_id=? AND kind!='lesson'", (sid,))]
    if not ledger_ids:
        if _has(c, 'credit_batches'):
            c.execute('DELETE FROM credit_batches WHERE student_id=?', (sid,))
        c.execute('UPDATE students SET balance=0 WHERE id=?', (sid,))
        return
    marks = ','.join('?' for _ in ledger_ids)
    if _has(c, 'vouchers'):
        voucher_ids = [row['id'] for row in c.execute(
            f'SELECT id FROM vouchers WHERE student_id=? OR ledger_id IN ({marks})', (sid, *ledger_ids))]
        if voucher_ids:
            vmarks = ','.join('?' for _ in voucher_ids)
            if _has(c, 'voucher_events'):
                c.execute(f'DELETE FROM voucher_events WHERE voucher_id IN ({vmarks})', tuple(voucher_ids))
            c.execute(f'DELETE FROM vouchers WHERE id IN ({vmarks})', tuple(voucher_ids))
    if _has(c, 'cash_entries'):
        c.execute(f'DELETE FROM cash_entries WHERE ledger_id IN ({marks})', tuple(ledger_ids))
    if _has(c, 'credit_movements'):
        c.execute(f'DELETE FROM credit_movements WHERE ledger_id IN ({marks})', tuple(ledger_ids))
    if _has(c, 'credit_batches'):
        c.execute(f'DELETE FROM credit_batches WHERE student_id=? OR ledger_id IN ({marks})', (sid, *ledger_ids))
    c.execute(f'DELETE FROM ledger WHERE id IN ({marks}) AND reversal_of IS NOT NULL', tuple(ledger_ids))
    c.execute(f'DELETE FROM ledger WHERE id IN ({marks})', tuple(ledger_ids))
    c.execute('UPDATE students SET balance=0 WHERE id=?', (sid,))


def _void_course(c, user, student, reason):
    sid = student['id']
    if not _history(c, sid):
        c.execute('DELETE FROM credit_batches WHERE student_id=?', (sid,))
        if _has(c, 'arrears'):
            c.execute('DELETE FROM arrears WHERE student_id=?', (sid,))
        c.execute('DELETE FROM profile_audit WHERE student_id=?', (sid,))
        c.execute('DELETE FROM students WHERE id=?', (sid,))
        return {'ok': True, 'deleted': True, 'voided': True, 'archived': False}
    _drop_future(c, sid, '加错了')
    _erase_zero_money(c, sid)
    c.execute('UPDATE students SET archived=1, voided=1, void_reason=?, balance=0 WHERE id=?', (reason[:200], sid))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (sid, user['id'], 'course_voided'))
    return {'ok': True, 'deleted': False, 'voided': True, 'archived': True}


def remove_course(c, user, data):
    """Delete one course. 加错了 voids it. 退课 keeps today's withdrawal receipt."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以删除课程。')
    schema(c)
    reason = str(data.get('reason') or 'mistake')
    if reason not in ('mistake', 'withdraw', 'other'):
        raise ValueError('请选择原因。')
    note = str(data.get('note') or '').strip()
    if reason == 'other' and not note:
        raise ValueError('请填写原因。')
    if len(note) > 200:
        raise ValueError('原因不能超过 200 个字。')
    sid = int(data.get('student_id') or data.get('id') or 0)
    student = c.execute('SELECT * FROM students WHERE id=? AND archived=0', (sid,)).fetchone()
    if not student:
        raise ValueError('这门课不存在，请刷新页面。')
    problems = course_problems(c, sid)
    if reason != 'withdraw' and problems:
        raise ValueError('这门课不能按加错了删除：' + '；'.join(problems) + '。请改选退课。')
    import auditlog
    auditlog.begin(c)
    if reason == 'withdraw':
        result = stop_course(c, user, {'student_id': sid})
        label = '退课'
    else:
        result = _void_course(c, user, student, note or '加错了')
        label = note or '加错了'
    auditlog.hint(c, f"删除课程 {student['name']} {student['course']}（{label}）")
    auditlog.finish(c, user)
    result['reason'] = reason
    return result
