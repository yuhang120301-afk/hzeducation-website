"""Owner-only deletion of unused, mistakenly created profiles."""
from teaching import AccessError


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
        accounts = c.execute('SELECT * FROM students WHERE profile_id=?', (student['profile_id'],)).fetchall()
        for account in accounts:
            if account['balance'] or referenced(c, 'students', account['id'], ('profile_audit',)):
                raise ValueError('这位学生有课时余额、课程或账目记录，不能删除。请编辑档案修正信息。')
        for account in accounts:
            c.execute('DELETE FROM profile_audit WHERE student_id=?', (account['id'],))
            c.execute('DELETE FROM students WHERE id=?', (account['id'],))
        c.execute('DELETE FROM student_profiles WHERE id=?', (student['profile_id'],))
        # The shared guardian account is intentionally retained for other children.
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
