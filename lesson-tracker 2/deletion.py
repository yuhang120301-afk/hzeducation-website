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
        return withdraw_student(c, user, data)
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


def _settle_keep(c, course, reason):
    c.execute('UPDATE students SET settle_reason=? WHERE id=?', (reason, course['id']))


def _settle_forfeit(c, user, course):
    """Write the hours off. This is not income and does not move cash."""
    import secrets
    balance = int(course['balance'] or 0)
    if balance:
        c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
            VALUES(?,?,'forfeit',?,?,?,?)''', (
            course['id'], -balance, now_local().date().isoformat(), '作废余额', user['id'], 'forfeit-' + secrets.token_hex(8)))
    if _has(c, 'credit_batches'):
        c.execute('UPDATE credit_batches SET paid_left=0, gift_left=0 WHERE student_id=?', (course['id'],))
    c.execute("UPDATE students SET balance=0, settle_reason='void' WHERE id=?", (course['id'],))


def _settle_refund(c, user, course, choice):
    import secrets
    import accounting
    import vouchers
    balance = int(course['balance'] or 0)
    try:
        cents = int(choice.get('refund_cents') or 0)
    except (TypeError, ValueError):
        raise ValueError('请填写退款金额。')
    if cents < 0:
        raise ValueError('退款金额不能为负。')
    day = now_local().date().isoformat()
    lid = c.execute('''INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id)
        VALUES(?,?,'refund',?,?,?,?)''', (
        course['id'], -balance, day, '退学退款', user['id'], 'refund-' + secrets.token_hex(8))).lastrowid
    if _has(c, 'credit_batches'):
        c.execute('UPDATE credit_batches SET paid_left=0, gift_left=0 WHERE student_id=?', (course['id'],))
    c.execute("UPDATE students SET balance=0, settle_reason='refund' WHERE id=?", (course['id'],))
    if cents:
        accounting.record_cash(c, lid, -cents, 'bank', '退学退款', user['id'])
    vouchers.issue_ledger(c, user, lid)


def withdraw_student(c, user, data):
    """Archive the whole student, including a profile whose courses are already stopped."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以退学。')
    schema(c)
    import profiles
    profiles.ensure_enrolment_columns(c)
    student = c.execute('SELECT * FROM students WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not student:
        raise ValueError('学生档案不存在，请刷新页面。')
    if profiles.profile_withdrawn(c, student['profile_id']):
        raise ValueError('学生已经退学，请在退学学员里查看。')
    courses = list(c.execute('SELECT * FROM students WHERE profile_id=? AND voided=0', (student['profile_id'],)))
    supplied = data.get('courses')
    choices = {}
    if isinstance(supplied, list):
        for item in supplied:
            if isinstance(item, dict):
                choices[int(item.get('student_id') or 0)] = item
    for course in courses:
        if int(course['balance'] or 0) <= 0:
            continue
        if supplied is None:
            choice = {'reason': 'keep'}
        else:
            choice = choices.get(course['id']) or {}
        reason = choice.get('reason') or ''
        if reason not in ('refund', 'keep', 'void'):
            raise ValueError(f"{course['course']} 还有余额，请选择退款、保留余额或作废。")
        if reason == 'refund':
            _settle_refund(c, user, course, choice)
        elif reason == 'void':
            _settle_forfeit(c, user, course)
        else:
            _settle_keep(c, course, 'keep')
    import vouchers
    for course in courses:
        _drop_future(c, course['id'], '退学', user)
        if not course['archived']:
            vouchers.issue_stop(c, user, dict(course), False)
    c.execute('UPDATE students SET archived=1 WHERE profile_id=? AND voided=0', (student['profile_id'],))
    c.execute("UPDATE student_profiles SET status='withdrawn', withdrawn_on=? WHERE id=?",
        (now_local().date().isoformat(), student['profile_id']))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (student['id'], user['id'], 'archived'))
    import timeline
    timeline.record(c, user, student['id'], 'withdraw', f"退学 {student['name']}")
    return {'ok': True}


def reinstate_student(c, user, data):
    """Bring a withdrawn student back. Kept balances stay. Refunded or forfeited courses return at zero."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以复学。')
    schema(c)
    import profiles
    profiles.ensure_enrolment_columns(c)
    student = c.execute('SELECT * FROM students WHERE id=?', (int(data.get('id') or 0),)).fetchone()
    if not student or not profiles.profile_withdrawn(c, student['profile_id']):
        raise ValueError('这位学生没有退学。')
    c.execute('UPDATE students SET archived=0 WHERE profile_id=? AND voided=0', (student['profile_id'],))
    c.execute("UPDATE student_profiles SET status='active', withdrawn_on='' WHERE id=?", (student['profile_id'],))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (student['id'], user['id'], 'reinstated'))
    import timeline
    timeline.record(c, user, student['id'], 'reinstate', f"复学 {student['name']}")
    return {'ok': True}


def restore(c, user, data):
    if user['role'] != 'owner':
        raise AccessError('只有老板可以恢复课程。')
    student=c.execute('SELECT * FROM students WHERE id=? AND archived=1', (int(data.get('id',0)),)).fetchone()
    if not student:
        raise ValueError('已停的课程不存在，请刷新页面。')
    c.execute('UPDATE students SET archived=0 WHERE id=?', (student['id'],))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (student['id'],user['id'],'course_restored'))
    import timeline
    timeline.record(c, user, student['id'], 'reinstate', f"复学 {student['name']} {student['course']}")
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
    if 'settle_reason' not in cols:
        c.execute("ALTER TABLE students ADD COLUMN settle_reason TEXT NOT NULL DEFAULT ''")
    c.execute('DROP INDEX IF EXISTS profile_course_unique')
    c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS profile_course_active
        ON students(profile_id, course) WHERE archived=0 AND voided=0''')


def _drop_future(c, sid, cancel_reason='停课', user=None):
    """Cancel this course's future lessons and stop a series that would keep adding it."""
    now = now_local().strftime('%Y-%m-%dT%H:%M')
    lessons = list(c.execute('''SELECT l.id, l.series_id, l.occurrence_index FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE ls.student_id=? AND l.status='scheduled' AND l.starts_at>=?''', (sid, now)))
    seen = set()
    for lesson in lessons:
        others = c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id!=?', (lesson['id'], sid)).fetchone()
        if user:
            import teaching
            teaching.release_absence(c, user, lesson['id'], None if not others else sid, clear=not others)
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
    import timeline
    if not _history(c, sid):
        timeline.record(c, user, sid, 'stop', f"停课 {student['course']}")
        c.execute('DELETE FROM credit_batches WHERE student_id=?', (sid,))
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='arrears'").fetchone():
            c.execute('DELETE FROM arrears WHERE student_id=?', (sid,))
        c.execute('DELETE FROM profile_audit WHERE student_id=?', (sid,))
        c.execute('DELETE FROM students WHERE id=?', (sid,))
        _tell_vouchers(c, user, student, True)
        return {'ok': True, 'deleted': True, 'archived': False, 'balance': balance}
    _drop_future(c, sid, user=user)
    c.execute('UPDATE students SET archived=1 WHERE id=?', (sid,))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (sid, user['id'], 'course_stopped'))
    timeline.record(c, user, sid, 'stop', f"停课 {student['course']}")
    _tell_vouchers(c, user, student, False)
    return {'ok': True, 'deleted': False, 'archived': True, 'balance': balance}


def _has(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _open_topup(c, sid):
    """A live top-up still counts. A voided receipt and its reversal do not."""
    if _has(c, 'vouchers'):
        live = c.execute('''SELECT 1 FROM vouchers
            WHERE student_id=? AND kind IN ('credit','adjust') AND status!='void' LIMIT 1''', (sid,)).fetchone()
        if live:
            return True
    return c.execute('''SELECT 1 FROM ledger
        WHERE student_id=? AND kind='credit' AND reversal_of IS NULL
          AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reversal_of=ledger.id)
        LIMIT 1''', (sid,)).fetchone() is not None


def course_blockers(c, sid):
    """Why this course cannot be removed as 加错了. Empty means the void is allowed.

    The button and this function share the list. A voided 充值 is not money.
    """
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
    if _open_topup(c, sid):
        problems.append('请先作废这门课的充值单据')
    return problems


def course_problems(c, sid):
    return course_blockers(c, sid)


def annotate_blockers(c, rows):
    for row in rows:
        row['delete_blockers'] = course_blockers(c, row['id'])


def _void_course(c, user, student):
    """加错了. The row stays so the profile can still show it. No 退课 receipt."""
    sid = student['id']
    _drop_future(c, sid, '加错了', user)
    if _has(c, 'credit_batches'):
        c.execute('UPDATE credit_batches SET paid_left=0, gift_left=0 WHERE student_id=?', (sid,))
    if _has(c, 'arrears'):
        c.execute('DELETE FROM arrears WHERE student_id=?', (sid,))
    c.execute("UPDATE students SET archived=1, voided=1, void_reason='加错了', balance=0 WHERE id=?", (sid,))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (sid, user['id'], 'course_voided'))
    import timeline
    timeline.record(c, user, sid, 'mistake', f"按加错了删除了课程 {student['course']}")
    return {'ok': True, 'deleted': False, 'voided': True, 'archived': True}


def remove_course(c, user, data):
    """Delete one course. This button is only 加错了, and it writes no 退课 receipt."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以删除课程。')
    schema(c)
    import timeline
    timeline.schema(c)
    sid = int(data.get('student_id') or data.get('id') or 0)
    student = c.execute('SELECT * FROM students WHERE id=? AND archived=0', (sid,)).fetchone()
    if not student:
        raise ValueError('这门课不存在，请刷新页面。')
    problems = course_blockers(c, sid)
    if problems == ['请先作废这门课的充值单据']:
        raise ValueError('请先作废这门课的充值单据')
    if problems:
        raise ValueError('这门课不能按加错了删除：' + '；'.join(problems) + '。')
    import auditlog
    auditlog.begin(c)
    result = _void_course(c, user, student)
    auditlog.hint(c, f"删除课程 {student['name']} {student['course']}（加错了）")
    auditlog.finish(c, user)
    result['reason'] = 'mistake'
    return result
