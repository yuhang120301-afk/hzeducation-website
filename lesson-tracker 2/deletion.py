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


def remove(c, user, data, db_path=None):
    if user['role'] != 'owner':
        raise AccessError('只有老板可以删除档案。')
    kind = data.get('kind')
    if kind == 'student':
        return withdraw_student(c, user, data)
    if kind == 'erase':
        return erase_profile(c, user, data, db_path)
    ident = int(data.get('id', 0))
    if kind in ('teacher', 'admin'):
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


def _optional_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _table_names(c):
    return {row['name'] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _erase_sets(c):
    """Profiles that cannot be erased, grouped by the reason that blocks them."""
    tables = _table_names(c)
    history = set()

    def collect(sql):
        for row in c.execute(sql):
            if row[0]:
                history.add(row[0])

    if 'students' in tables and 'lesson_students' in tables:
        collect('SELECT s.profile_id FROM lesson_students ls JOIN students s ON s.id=ls.student_id')
    if 'students' in tables and 'lesson_reports' in tables:
        collect('SELECT s.profile_id FROM lesson_reports r JOIN students s ON s.id=r.student_id')
    if 'students' in tables and 'ledger' in tables:
        collect('SELECT s.profile_id FROM ledger l JOIN students s ON s.id=l.student_id')
    if 'students' in tables and 'vouchers' in tables:
        collect('SELECT s.profile_id FROM vouchers v JOIN students s ON s.id=v.student_id')
    if 'students' in tables and 'credit_batches' in tables:
        collect('SELECT s.profile_id FROM credit_batches b JOIN students s ON s.id=b.student_id')
    if 'students' in tables:
        collect('SELECT profile_id FROM students WHERE COALESCE(balance,0)!=0')
    if 'students' in tables and 'lesson_series' in tables:
        owned = {row['id']: row['profile_id'] for row in c.execute('SELECT id, profile_id FROM students')}
        for rule in c.execute('SELECT template FROM lesson_series'):
            try:
                raw = json.loads(rule['template'] or '{}').get('student_ids') or []
            except json.JSONDecodeError:
                continue
            for item in raw:
                profile_id = owned.get(_optional_int(item))
                if profile_id:
                    history.add(profile_id)
    duplicates = set()
    import profiles
    names = {}
    if 'student_profiles' in tables:
        for row in c.execute('SELECT id, name FROM student_profiles'):
            key = profiles.normalize_person_name(row['name'])
            if key:
                names.setdefault(key, []).append(row['id'])
    for ids in names.values():
        if len(ids) > 1:
            duplicates.update(ids)
    parents = set()
    if 'users' in tables and 'profile_parents' in tables:
        for row in c.execute('''SELECT pp.profile_id, u.phone FROM profile_parents pp
            JOIN users u ON u.id=pp.user_id'''):
            if row['profile_id'] and not str(row['phone'] or '').startswith('pending-'):
                parents.add(row['profile_id'])
    if 'users' in tables and 'students' in tables:
        for row in c.execute('''SELECT s.profile_id, u.phone FROM students s
            JOIN users u ON u.id=s.parent_id'''):
            if row['profile_id'] and not str(row['phone'] or '').startswith('pending-'):
                parents.add(row['profile_id'])
    return history, duplicates, parents


def erase_reason(profile_id, history, duplicates, parents):
    if profile_id in history:
        return '有上课、账目或单据，不能删除。请用退学。'
    if profile_id in duplicates:
        return '这是同名的另一份档案，请合并，不要删除。'
    if profile_id in parents:
        return '有可以登录的家长，不能删除档案。'
    return ''


def annotate_erase(c, rows):
    history, duplicates, parents = _erase_sets(c)
    for row in rows:
        profile_id = row.get('profile_id') or row.get('id')
        try:
            profile_id = int(profile_id)
        except (TypeError, ValueError):
            row['erase_reason'] = ''
            continue
        row['erase_reason'] = erase_reason(profile_id, history, duplicates, parents)


def _backup_database(c, db_path, profile_id):
    from pathlib import Path
    import backup
    if not db_path:
        raise ValueError('无法备份，已取消删除。')
    import secrets
    stamp = now_local().strftime('%Y%m%d%H%M%S')
    folder = Path(db_path).resolve().parent
    dest = folder / f'backup-delete-profile-{stamp}-{profile_id}-{secrets.token_hex(3)}.sqlite3'
    if dest.exists():
        raise ValueError('无法备份，已取消删除。')
    try:
        backup.write_snapshot(db_path, dest)
    except Exception as first:
        raw = __import__('sqlite3').connect(str(dest))
        try:
            c.backup(raw)
            if raw.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('备份校验失败。')
        except Exception as second:
            raw.close()
            if dest.exists():
                dest.unlink()
            raise ValueError('无法备份，已取消删除。') from second
        raw.close()
        dest.chmod(0o600)
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise ValueError('无法备份，已取消删除。')
    return dest


def _delete_where(c, tables, table, column, value):
    if table not in tables:
        return
    columns = {row['name'] for row in c.execute('PRAGMA table_info(' + table + ')')}
    if column not in columns:
        return
    c.execute(f'DELETE FROM {table} WHERE {column}=?', (value,))


def erase_profile(c, user, data, db_path):
    """Remove one empty profile. A profile with history, a real parent, or a duplicate name stays."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以删除档案。')
    import profiles
    profiles.ensure_enrolment_columns(c)
    profile_id = _optional_int(data.get('profile_id') or data.get('id'))
    profile = c.execute('SELECT * FROM student_profiles WHERE id=?', (profile_id,)).fetchone() if profile_id else None
    if not profile:
        raise ValueError('学生档案不存在，请刷新页面。')
    history, duplicates, parents = _erase_sets(c)
    reason = erase_reason(profile_id, history, duplicates, parents)
    if reason:
        raise ValueError(reason)
    _backup_database(c, db_path, profile_id)
    import auditlog
    auditlog.begin(c)
    tables = _table_names(c)
    course_ids = [row['id'] for row in c.execute('SELECT id FROM students WHERE profile_id=?', (profile_id,))] if 'students' in tables else []
    linked = []
    if 'users' in tables and 'profile_parents' in tables:
        linked += [row['user_id'] for row in c.execute('SELECT user_id FROM profile_parents WHERE profile_id=?', (profile_id,))]
    if 'users' in tables and 'students' in tables:
        linked += [row['parent_id'] for row in c.execute('SELECT parent_id FROM students WHERE profile_id=?', (profile_id,))]
    for sid in course_ids:
        for table, column in (
            ('lesson_students', 'student_id'), ('lesson_reports', 'student_id'),
            ('credit_batches', 'student_id'), ('arrears', 'student_id'),
            ('profile_audit', 'student_id'),
        ):
            _delete_where(c, tables, table, column, sid)
        _delete_where(c, tables, 'ledger', 'student_id', sid)
    _delete_where(c, tables, 'students', 'profile_id', profile_id)
    _delete_where(c, tables, 'profile_parents', 'profile_id', profile_id)
    _delete_where(c, tables, 'student_origin_events', 'profile_id', profile_id)
    _delete_where(c, tables, 'student_subject_prices', 'profile_id', profile_id)
    _delete_where(c, tables, 'profile_events', 'profile_id', profile_id)
    c.execute('DELETE FROM student_profiles WHERE id=?', (profile_id,))
    for uid in {item for item in linked if item}:
        user_row = c.execute('SELECT phone FROM users WHERE id=?', (uid,)).fetchone()
        if not user_row or not str(user_row['phone'] or '').startswith('pending-'):
            continue
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='teachers'").fetchone() and c.execute('SELECT 1 FROM teachers WHERE user_id=?', (uid,)).fetchone():
            continue
        still = False
        if 'profile_parents' in tables and c.execute('SELECT 1 FROM profile_parents WHERE user_id=?', (uid,)).fetchone():
            still = True
        if 'students' in tables and c.execute('SELECT 1 FROM students WHERE parent_id=?', (uid,)).fetchone():
            still = True
        if still:
            continue
        _delete_where(c, tables, 'sessions', 'user_id', uid)
        c.execute('DELETE FROM users WHERE id=?', (uid,))
    auditlog.hint(c, f"删除档案 {profile['name']}")
    auditlog.finish(c, user)
    return {'ok': True, 'deleted': profile_id}


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
    profile_id = _optional_int(data.get('profile_id'))
    student = None
    if profile_id:
        student = c.execute('SELECT * FROM students WHERE profile_id=? ORDER BY archived, id LIMIT 1', (profile_id,)).fetchone()
    if not student:
        sid = _optional_int(data.get('id'))
        if sid:
            student = c.execute('SELECT * FROM students WHERE id=?', (sid,)).fetchone()
            if student:
                profile_id = student['profile_id']
    profile = c.execute('SELECT * FROM student_profiles WHERE id=?', (profile_id,)).fetchone() if profile_id else None
    if not profile:
        raise ValueError('学生档案不存在，请刷新页面。')
    if profiles.profile_withdrawn(c, profile_id):
        raise ValueError('学生已经退学，请在退学学员里查看。')
    import auditlog
    auditlog.begin(c)
    courses = list(c.execute('SELECT * FROM students WHERE profile_id=? AND voided=0', (profile_id,)))
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
    c.execute('UPDATE students SET archived=1 WHERE profile_id=? AND voided=0', (profile_id,))
    c.execute("UPDATE student_profiles SET status='withdrawn', withdrawn_on=? WHERE id=?",
        (now_local().date().isoformat(), profile_id))
    import timeline
    timeline.schema(c)
    if student:
        c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (student['id'], user['id'], 'archived'))
        timeline.record(c, user, student['id'], 'withdraw', f"退学 {profile['name']}")
    else:
        c.execute('INSERT INTO profile_events(profile_id,student_id,actor_id,action,summary) VALUES(?,NULL,?,?,?)',
            (profile_id, user['id'], 'withdraw', f"退学 {profile['name']}"[:200]))
    auditlog.hint(c, f"退学 {profile['name']}")
    auditlog.finish(c, user)
    return {'ok': True}


def settle_course(c, user, data):
    """One 退课/停课 action. The balance needs 退款, 保留余额 or 作废."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以退课或停课。')
    schema(c)
    course = c.execute('SELECT * FROM students WHERE id=? AND archived=0 AND voided=0', (int(data.get('student_id') or 0),)).fetchone()
    if not course:
        raise ValueError('这门课不存在，请刷新页面。')
    reason = str(data.get('reason') or '')
    if int(course['balance'] or 0) > 0 and reason not in ('refund', 'keep', 'void'):
        raise ValueError('还有余额，请选择退款、保留余额或作废。')
    if reason not in ('refund', 'keep', 'void'):
        reason = 'keep'
    import auditlog
    auditlog.begin(c)
    if reason == 'refund':
        _settle_refund(c, user, course, data)
    elif reason == 'void':
        _settle_forfeit(c, user, course)
    else:
        _settle_keep(c, course, 'keep')
    _drop_future(c, course['id'], '退课/停课', user)
    c.execute('UPDATE students SET archived=1 WHERE id=?', (course['id'],))
    import vouchers
    note = {'refund': '退课退款', 'keep': '停课，余额保留', 'void': '作废余额'}[reason]
    vid = vouchers.issue_stop(c, user, dict(course), False)
    c.execute('UPDATE vouchers SET note=? WHERE id=?', (note, vid))
    import timeline
    timeline.record(c, user, course['id'], 'stop', f"{note} {course['course']}")
    auditlog.hint(c, f"{note} {course['name']} {course['course']}")
    auditlog.finish(c, user)
    return {'ok': True, 'reason': reason, 'voucher_id': vid}


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
        import profiles
        profiles.remember_person(c, sid)
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


def _person_groups(rows):
    groups = {}
    for row in rows or []:
        key = row.get('profile_id') or row.get('id')
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def _live_course(account):
    return account and not account.get('no_course') and not account.get('archived') and not account.get('voided')


def _needs_renewal(account):
    if isinstance(account.get('needs_renewal'), bool):
        return account['needs_renewal']
    paid = account.get('paid_balance')
    if paid is None:
        paid = account.get('balance') or 0
    return paid < 300


def roster_counts(state):
    """Same numbers the boss home page shows. One person per profile."""
    enrolled = 0
    for group in _person_groups(state.get('students')):
        person = group[0]
        if (person.get('study_status') or 'studying') == 'graduated':
            continue
        if str(person.get('left_on') or '').strip() or any(item.get('withdrawn') for item in group):
            continue
        if any(_live_course(item) for item in group):
            enrolled += 1
    seen = set()
    for bucket in ('students', 'withdrawn_students', 'left_students'):
        for row in state.get(bucket) or []:
            seen.add(row.get('profile_id') or row.get('id'))
    people = 0
    courses = 0
    for group in _person_groups(state.get('students')):
        hits = [item for item in group if _live_course(item) and (item.get('study_status') or 'studying') != 'graduated' and _needs_renewal(item)]
        if hits:
            people += 1
            courses += len(hits)
    return {'enrolled': enrolled, 'everyone': len(seen), 'renewal_people': people, 'renewal_courses': courses}


def report_roster_once(c):
    """Log the home-page counts and who could be erased. Does not delete anyone."""
    import sys
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'").fetchone() is None:
        return
    if c.execute("SELECT 1 FROM app_meta WHERE key='roster_home_report_v1'").fetchone():
        return
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_profiles'").fetchone() is None:
        return
    if not c.execute('SELECT COUNT(*) n FROM student_profiles').fetchone()['n']:
        return
    try:
        owner = c.execute('''SELECT u.id, u.name, u.phone FROM users u
            JOIN organization_owners o ON o.user_id=u.id
            WHERE u.active=1 ORDER BY u.id LIMIT 1''').fetchone()
    except Exception:
        return
    if not owner:
        return
    import server
    user = {'id': owner['id'], 'name': owner['name'], 'phone': owner['phone'], 'role': 'owner', 'teacher_id': None, 'csrf': ''}
    try:
        state = server.build_state(c, user)
    except Exception:
        print('学员名单统计没有完成。', file=sys.stderr, flush=True)
        return
    counts = roster_counts(state)
    classified = {}
    for bucket in ('students', 'withdrawn_students', 'left_students', 'archived_students', 'voided_students'):
        for row in state.get(bucket) or []:
            profile_id = row.get('profile_id') or row.get('id')
            if profile_id in classified:
                continue
            classified[profile_id] = (row.get('name') or '', row.get('erase_reason') or '')
    openable = [name for name, reason in classified.values() if name and not reason]
    blocked = {}
    for name, reason in classified.values():
        if name and reason:
            blocked.setdefault(reason, []).append(name)
    print(f"在读学员 {counts['enrolled']}", file=sys.stderr, flush=True)
    print(f"全部学员 {counts['everyone']}", file=sys.stderr, flush=True)
    print(f"需要续费 {counts['renewal_people']} 位，{counts['renewal_courses']} 门课", file=sys.stderr, flush=True)
    print('可删除档案：' + ('、'.join(openable) if openable else '没有'), file=sys.stderr, flush=True)
    for reason, names in blocked.items():
        print(f"不能删除（{reason}）：{'、'.join(names)}", file=sys.stderr, flush=True)
    c.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES('roster_home_report_v1','1')")
