"""Per-admin switches. Missing keys stay on, which is how admins work today.

Money pages stay owner-only and are not stored here.
"""
import json

from teaching import AccessError

KEYS = (
    ('schedule', '日历排课（全部老师）'),
    ('students', '学生资料编辑 / 加课程'),
    ('parents', '家长账号管理 / 重置密码'),
    ('topup', '充值（含挂账）及查看课时包金额'),
    ('reverse', '账目撤销'),
    ('reports', '课堂报告（全部老师）'),
    ('teachers', '老师管理（添加 / 重置密码 / 停用）'),
    ('places', '地点'),
)
KEY_SET = {key for key, _label in KEYS}


def schema(c):
    cols = {row['name'] for row in c.execute('PRAGMA table_info(users)')}
    if 'admin_permissions' not in cols:
        c.execute("ALTER TABLE users ADD COLUMN admin_permissions TEXT NOT NULL DEFAULT ''")


def defaults():
    return {key: True for key, _label in KEYS}


def read(raw):
    flags = defaults()
    if not raw:
        return flags
    try:
        saved = json.loads(raw)
    except json.JSONDecodeError:
        return flags
    if isinstance(saved, dict):
        for key in KEY_SET:
            if key in saved:
                flags[key] = bool(saved[key])
    return flags


def for_user(c, user):
    if not user or user['role'] != 'admin':
        return defaults() if user and user['role'] == 'owner' else {key: False for key in KEY_SET}
    schema(c)
    row = c.execute('SELECT admin_permissions FROM users WHERE id=?', (user['id'],)).fetchone()
    return read(row['admin_permissions'] if row else '')


def has(c, user, key):
    if not user:
        return False
    if user['role'] == 'owner':
        return True
    if user['role'] != 'admin':
        return False
    return bool(for_user(c, user).get(key))


def allow(c, user, key):
    if has(c, user, key):
        return
    if user and user['role'] == 'admin':
        raise AccessError('这个权限已关闭。请联系老板。')
    raise AccessError('没有这个权限。')


def set_flag(c, user, data):
    import accounting
    accounting.require_owner(user)
    schema(c)
    uid = int(data.get('admin_id') or 0)
    key = str(data.get('key') or '')
    if key not in KEY_SET:
        raise ValueError('没有这项权限。')
    on = data.get('on')
    if type(on) is not bool:
        raise ValueError('开关状态无效。')
    admin = c.execute("""SELECT u.id, u.admin_permissions FROM users u
        LEFT JOIN organization_owners o ON o.user_id=u.id
        WHERE u.id=? AND u.role='admin' AND o.user_id IS NULL""", (uid,)).fetchone()
    if not admin:
        raise ValueError('请选择有效的管理员。')
    flags = read(admin['admin_permissions'])
    flags[key] = on
    c.execute('UPDATE users SET admin_permissions=? WHERE id=?', (json.dumps(flags, ensure_ascii=False), uid))
    return {'ok': True, 'permissions': flags}
