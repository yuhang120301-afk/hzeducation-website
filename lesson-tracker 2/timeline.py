"""Profile timeline. Every state change that a person can look up stays here.

The row is the record Helen opens on the student page. It names the action,
the date and who did it. Undo of an audited action removes the row it added,
because that action no longer stands.
"""

ACTIONS = {
    'course_added': '添加课程',
    'top_up': '充值',
    'switch': '换课',
    'stop': '停课',
    'mistake': '加错了删除',
    'withdraw': '退学',
    'reinstate': '复学',
    'void': '作废单据',
    'unvoid': '取消作废',
    'receipt': '挂账收款',
}


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS profile_events (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL,
        student_id INTEGER,
        actor_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        summary TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS profile_events_profile ON profile_events(profile_id, id)')


def record(c, user, student_id, action, summary):
    """Append one line. Missing profile or unknown action is skipped, not fatal."""
    if action not in ACTIONS or not user or not student_id:
        return None
    schema(c)
    student = c.execute('SELECT profile_id FROM students WHERE id=?', (int(student_id),)).fetchone()
    if not student or not student['profile_id']:
        return None
    text = str(summary or ACTIONS[action]).strip()
    if not text:
        text = ACTIONS[action]
    return c.execute(
        'INSERT INTO profile_events(profile_id,student_id,actor_id,action,summary) VALUES(?,?,?,?,?)',
        (student['profile_id'], int(student_id), int(user['id']), action, text[:200])).lastrowid


def for_staff(c):
    schema(c)
    voucher_join = ''
    voucher_cols = ', NULL voucher_id, NULL voucher_status'
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vouchers'").fetchone():
        voucher_cols = ', v.id voucher_id, v.status voucher_status'
        voucher_join = "LEFT JOIN vouchers v ON e.action='void' AND e.summary=('作废单据 '||v.number)"
    return [dict(row) for row in c.execute(f'''SELECT e.id, e.profile_id, e.student_id, e.action, e.summary,
        e.created_at, u.name actor_name{voucher_cols}
        FROM profile_events e LEFT JOIN users u ON u.id=e.actor_id
        {voucher_join}
        ORDER BY e.id DESC LIMIT 2000''')]
