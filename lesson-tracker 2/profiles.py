"""Editable student profiles and guardian account administration."""
import datetime as dt
from teaching import AccessError, now_local, singapore_subject, vce_subject

def schema(c):
    c.execute("CREATE TABLE IF NOT EXISTS student_profiles (id INTEGER PRIMARY KEY)")
    cols={r['name'] for r in c.execute('PRAGMA table_info(students)')}
    if 'profile_id' not in cols:
        c.execute('ALTER TABLE students ADD COLUMN profile_id INTEGER REFERENCES student_profiles(id)')
    for row in c.execute('SELECT id FROM students WHERE profile_id IS NULL').fetchall():
        pid=c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        c.execute('UPDATE students SET profile_id=? WHERE id=?',(pid,row['id']))
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS profile_course_unique ON students(profile_id,course)')
    if 'archived' not in cols:
        c.execute('ALTER TABLE students ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
    if 'billing_unit' not in cols:
        c.execute("ALTER TABLE students ADD COLUMN billing_unit TEXT NOT NULL DEFAULT 'lesson' CHECK(billing_unit IN ('lesson','hour'))")
    for name in ('birthday','grade','notes'):
        if name not in cols:
            c.execute('ALTER TABLE students ADD COLUMN '+name+" TEXT NOT NULL DEFAULT ''")
    cols={r['name'] for r in c.execute('PRAGMA table_info(users)')}
    if 'contact_phone' not in cols:
        c.execute("ALTER TABLE users ADD COLUMN contact_phone TEXT NOT NULL DEFAULT ''")
    c.execute("CREATE TABLE IF NOT EXISTS profile_audit (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id), actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
    c.execute('''CREATE TABLE IF NOT EXISTS profile_parents (
        profile_id INTEGER NOT NULL REFERENCES student_profiles(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        PRIMARY KEY(profile_id, user_id)
    )''')
    c.execute('''INSERT OR IGNORE INTO profile_parents(profile_id, user_id)
        SELECT DISTINCT profile_id, parent_id FROM students WHERE profile_id IS NOT NULL''')
    ensure_enrolment_columns(c)


PROFILE_TEXT = (
    'school', 'parent_email', 'emergency_name', 'emergency_relation', 'emergency_phone',
    'health_notes', 'enrolment_course', 'enrolment_subject', 'consent_on', 'consent_withdrawn_on', 'signed_on',
)
PROFILE_FLAGS = ('photo_homework', 'photo_class', 'photo_face', 'photo_none', 'handbook_read')


def ensure_enrolment_columns(c):
    cols = {r['name'] for r in c.execute('PRAGMA table_info(student_profiles)')}
    for name in PROFILE_TEXT:
        if name not in cols:
            c.execute(f"ALTER TABLE student_profiles ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    for name in PROFILE_FLAGS:
        if name not in cols:
            c.execute(f'ALTER TABLE student_profiles ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
    if 'study_status' not in cols:
        c.execute("ALTER TABLE student_profiles ADD COLUMN study_status TEXT NOT NULL DEFAULT 'studying'")
    if 'status' not in cols:
        c.execute("ALTER TABLE student_profiles ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if 'withdrawn_on' not in cols:
        c.execute("ALTER TABLE student_profiles ADD COLUMN withdrawn_on TEXT NOT NULL DEFAULT ''")
    if 'left_on' not in cols:
        c.execute("ALTER TABLE student_profiles ADD COLUMN left_on TEXT NOT NULL DEFAULT ''")
    if 'left_reason' not in cols:
        c.execute("ALTER TABLE student_profiles ADD COLUMN left_reason TEXT NOT NULL DEFAULT ''")
    ensure_identity(c)


def ensure_identity(c):
    """The person lives on the profile. Course rows copy the name, they do not own it."""
    cols = {r['name'] for r in c.execute('PRAGMA table_info(student_profiles)')}
    for name in ('name', 'birthday', 'grade', 'notes'):
        if name not in cols:
            c.execute(f"ALTER TABLE student_profiles ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='students'").fetchone():
        return
    if int(c.execute('PRAGMA query_only').fetchone()[0]):
        return
    for field in ('name', 'birthday', 'grade', 'notes'):
        c.execute(f'''UPDATE student_profiles SET {field}=COALESCE((
            SELECT s.{field} FROM students s
            WHERE s.profile_id=student_profiles.id AND TRIM(COALESCE(s.{field},''))!=''
            ORDER BY s.archived, s.id LIMIT 1), {field})
            WHERE TRIM(COALESCE({field},''))='' ''')


def remember_person(c, student_id):
    """Copy this course row's identity onto the profile before the row can disappear."""
    ensure_identity(c)
    row = c.execute('SELECT * FROM students WHERE id=?', (int(student_id),)).fetchone()
    if not row or not row['profile_id']:
        return
    current = c.execute('SELECT name, birthday, grade, notes FROM student_profiles WHERE id=?', (row['profile_id'],)).fetchone()
    if not current:
        return
    c.execute('UPDATE student_profiles SET name=?, birthday=?, grade=?, notes=? WHERE id=?', (
        (current['name'] or row['name'] or '').strip(),
        current['birthday'] or row['birthday'] or '',
        current['grade'] or row['grade'] or '',
        current['notes'] or row['notes'] or '',
        row['profile_id']))


def normalize_person_name(value):
    return ' '.join(str(value or '').strip().casefold().split())

def fields(data):
    birthday=str(data.get('birthday','')).strip()
    if birthday:
        try: day=dt.date.fromisoformat(birthday)
        except ValueError: raise ValueError('请输入有效的出生日期。')
        if day>now_local().date() or day.year<1900:
            raise ValueError('出生日期需在 1900 年至今天之间。')
        birthday=day.isoformat()
    grade=str(data.get('grade','')).strip()
    notes=str(data.get('notes','')).strip()
    if len(grade)>40 or len(notes)>2000:
        raise ValueError('年级最多 40 字，备注最多 2000 字。')
    return birthday,grade,notes

def _date_or_blank(value, label):
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        day = dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError(label + '日期无效。')
    return day.isoformat()


def enrolment_values(data):
    """Optional HMS enrolment answers. Name and year level are checked by the caller."""
    values = {}
    for name in PROFILE_TEXT:
        text = str(data.get(name) or '').strip()
        if name == 'parent_email' and text and ('@' not in text or len(text) > 80):
            raise ValueError('请填写有效的家长邮箱。')
        if name in ('consent_on', 'consent_withdrawn_on', 'signed_on'):
            text = _date_or_blank(text, {'consent_on': '同意', 'consent_withdrawn_on': '撤回', 'signed_on': '签字'}[name])
        if len(text) > (2000 if name == 'health_notes' else 80):
            raise ValueError('这一项太长。')
        values[name] = text
    flags = {name: 1 if data.get(name) in (True, 1, '1', 'on', 'true') else 0 for name in PROFILE_FLAGS}
    if flags['photo_none']:
        flags['photo_homework'] = flags['photo_class'] = flags['photo_face'] = 0
    values.update(flags)
    return values


def save_enrolment(c, profile_id, data):
    ensure_enrolment_columns(c)
    if not any(name in data for name in ('health_notes', 'school', 'parent_email', 'emergency_name')):
        return
    values = enrolment_values(data)
    assignments = ','.join(f'{name}=?' for name in values)
    c.execute(f'UPDATE student_profiles SET {assignments} WHERE id=?', (*values.values(), profile_id))


def require_admin(user):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有老板或管理员可以编辑学生档案。')

def profile_withdrawn(c, profile_id):
    """A whole student was archived, and has not since been reinstated."""
    if not profile_id:
        return False
    ensure_enrolment_columns(c)
    status = c.execute('SELECT status FROM student_profiles WHERE id=?', (profile_id,)).fetchone()
    if status and status['status'] == 'withdrawn':
        return True
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_audit'").fetchone():
        return False
    latest = c.execute('''SELECT a.action FROM profile_audit a
        JOIN students s ON s.id=a.student_id
        WHERE s.profile_id=? AND a.action IN ('archived','reinstated')
        ORDER BY a.id DESC LIMIT 1''', (profile_id,)).fetchone()
    return bool(latest and latest['action'] == 'archived')


def student(c,data):
    row=c.execute('SELECT * FROM students WHERE id=?',(int(data.get('student_id',0)),)).fetchone()
    if not row:
        raise ValueError('学生不存在，请刷新页面。')
    if row['archived'] and profile_withdrawn(c, row['profile_id']):
        raise ValueError('学生已归档，请先恢复档案。')
    return row


def course_shells(c, rows):
    """One visible card per profile that still belongs here but has no current course."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get('profile_id') or row['id'], []).append(row)
    shells = []
    for profile_id, group in grouped.items():
        if any(not row['archived'] for row in group):
            continue
        if profile_withdrawn(c, profile_id):
            continue
        source = dict(group[0])
        source['no_course'] = True
        source['course'] = ''
        source['subject_name'] = ''
        source['course_type_name'] = ''
        source['balance'] = 0
        source['paid_balance'] = 0
        source['gift_balance'] = 0
        source['credit_batches'] = []
        source['archived'] = 0
        source['voided'] = 0
        source['legacy'] = False
        source['legacy_subjects'] = []
        source['study_status'] = source.get('study_status') or 'studying'
        shells.append(source)
    return shells


def set_study_status(c, user, data):
    if user['role'] != 'owner':
        raise AccessError('只有老板可以修改在读状态。')
    status = str(data.get('study_status') or '')
    if status not in ('studying', 'graduated'):
        raise ValueError('请选择在读或已毕业。')
    ensure_enrolment_columns(c)
    row = student(c, data)
    c.execute('UPDATE student_profiles SET study_status=? WHERE id=?', (status, row['profile_id']))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)', (row['id'], user['id'], 'study_'+status))
    return {'ok': True, 'study_status': status}

def update(c,user,data,text_value):
    import payroll
    payroll.reject_original_flag(user, data)
    require_admin(user)
    if not data.get('student_id') and data.get('profile_id'):
        ensure_identity(c)
        profile_id=int(data.get('profile_id') or 0)
        profile=c.execute('SELECT * FROM student_profiles WHERE id=?',(profile_id,)).fetchone()
        if not profile:
            raise ValueError('学生不存在，请刷新页面。')
        name=text_value(data.get('name'),'学生姓名',40)
        birthday,grade,notes=fields(data)
        if 'grade' in data and not str(data.get('grade') or '').strip():
            raise ValueError('请选择年级。')
        c.execute('UPDATE student_profiles SET name=?,birthday=?,grade=?,notes=? WHERE id=?',(name,birthday,grade,notes,profile_id))
        if c.execute('SELECT 1 FROM students WHERE profile_id=?',(profile_id,)).fetchone():
            import pricing
            level_code, level_year = pricing.remember_level(data, grade)
            c.execute('UPDATE students SET name=?,birthday=?,grade=?,notes=?,level_code=?,level_year=? WHERE profile_id=?',(name,birthday,grade,notes,level_code,level_year,profile_id))
        save_enrolment(c, profile_id, data)
        return {'ok':True}
    s=student(c,data)
    name=text_value(data.get('name'),'学生姓名',40)
    birthday,grade,notes=fields(data)
    unit=billing_unit(data.get('billing_unit',s['billing_unit']))
    c.execute('UPDATE students SET billing_unit=? WHERE profile_id=?',(unit,s['profile_id']))
    import pricing
    level_code, level_year = pricing.remember_level(data, grade)
    if 'grade' in data and not str(data.get('grade') or '').strip():
        raise ValueError('请选择年级。')
    c.execute('UPDATE students SET name=?,birthday=?,grade=?,notes=?,level_code=?,level_year=? WHERE profile_id=?',(name,birthday,grade,notes,level_code,level_year,s['profile_id']))
    ensure_identity(c)
    c.execute('UPDATE student_profiles SET name=?,birthday=?,grade=?,notes=? WHERE id=?',(name,birthday,grade,notes,s['profile_id']))
    save_enrolment(c, s['profile_id'], data)
    if str(data.get('study_status') or ''):
        set_study_status(c, user, {'student_id': s['id'], 'study_status': data.get('study_status')})
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',(s['id'],user['id'],'profile_updated'))
    return {'ok':True}

def _login_phone(raw, phone_value, label):
    try:
        return phone_value(raw)
    except ValueError:
        raise ValueError(label)


def guardian(c,user,data,text_value,phone_value,password_hash):
    """Edit one linked parent login. Does not rename students or move parent links."""
    require_admin(user)
    schema(c)
    s=student(c,data)
    target=data.get('parent_user_id') or s['parent_id']
    parent=c.execute("SELECT * FROM users WHERE id=? AND role='parent'",(int(target),)).fetchone()
    if not parent or c.execute('SELECT 1 FROM teachers WHERE user_id=?',(parent['id'],)).fetchone():
        raise ValueError('此账号不是家长账号。')
    linked=parent['id']==s['parent_id'] or c.execute(
        'SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?',(s['profile_id'],parent['id'])).fetchone()
    if not linked:
        raise ValueError('这位家长没有关联这个学生。')
    name=text_value(data.get('parent_name'),'家长姓名',40)
    login=_login_phone(data.get('phone'), phone_value, '请输入有效的登录手机号。')
    contact=str(data.get('contact_phone') or '').strip()
    if contact:
        contact=_login_phone(contact, phone_value, '请输入有效的联系手机号。')
    if c.execute('SELECT 1 FROM users WHERE phone=? AND id!=?',(login,parent['id'])).fetchone():
        raise ValueError('此登录手机号已被其他账号使用。')
    password=str(data.get('password') or '').strip()
    if password and not 10<=len(password)<=128:
        raise ValueError('新密码需为 10–128 位。')
    c.execute('UPDATE users SET name=?,phone=?,contact_phone=? WHERE id=?',(name,login,contact,parent['id']))
    if password:
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),parent['id']))
    if password or login!=parent['phone']:
        c.execute('DELETE FROM sessions WHERE user_id=?',(parent['id'],))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',(s['id'],user['id'],'guardian_updated_with_reset' if password else 'guardian_updated'))
    return {'ok':True}


def linked_clause(alias='s'):
    """A parent sees a child on the original parent_id and on any extra link."""
    return (f'({alias}.parent_id=? OR EXISTS (SELECT 1 FROM profile_parents pp '
            f'WHERE pp.profile_id={alias}.profile_id AND pp.user_id=?))')


def linked_params(user_id):
    return (user_id, user_id)


def parents_for(c, profile_id, primary_id):
    rows = []
    seen = set()
    if primary_id:
        row = c.execute("SELECT id, name, phone, contact_phone FROM users WHERE id=? AND role='parent'", (primary_id,)).fetchone()
        if row:
            rows.append({'id': row['id'], 'name': row['name'], 'phone': row['phone'], 'contact_phone': row['contact_phone'] or '', 'primary': True})
            seen.add(row['id'])
    for row in c.execute('''SELECT u.id, u.name, u.phone, u.contact_phone FROM profile_parents pp
            JOIN users u ON u.id=pp.user_id WHERE pp.profile_id=? AND u.role='parent' ORDER BY u.name''', (profile_id,)):
        if row['id'] in seen:
            continue
        rows.append({'id': row['id'], 'name': row['name'], 'phone': row['phone'], 'contact_phone': row['contact_phone'] or '', 'primary': False})
        seen.add(row['id'])
    return rows


def search_parents(c, user, query):
    if user['role'] not in ('owner', 'admin'):
        raise AccessError('只有老板或管理员可以查找家长。')
    text = str(query or '').strip()
    if len(text) < 1:
        return {'parents': []}
    like = f'%{text}%'
    rows = []
    for row in c.execute('''SELECT u.id, u.name, u.phone, u.contact_phone FROM users u
            WHERE u.role='parent' AND NOT EXISTS (SELECT 1 FROM teachers t WHERE t.user_id=u.id)
              AND (u.name LIKE ? OR u.phone LIKE ? OR u.contact_phone LIKE ?)
            ORDER BY u.name LIMIT 8''', (like, like, like)):
        rows.append({'id': row['id'], 'name': row['name'], 'phone': row['phone'], 'contact_phone': row['contact_phone']})
    return {'parents': rows}


def _parent_account(c, user_id):
    row = c.execute("SELECT * FROM users WHERE id=? AND role='parent'", (int(user_id),)).fetchone()
    if not row or c.execute('SELECT 1 FROM teachers WHERE user_id=?', (row['id'],)).fetchone():
        raise ValueError('请选择一个家长账号。')
    return row


def link_parent(c, user, data, phone_value, password_hash, text_value):
    """Attach one existing parent, or create one account, without renaming anyone else."""
    if user['role'] not in ('owner', 'admin'):
        raise AccessError('只有老板或管理员可以关联家长。')
    schema(c)
    student_row = student(c, data)
    chosen = data.get('parent_user_id')
    import auditlog
    auditlog.begin(c)
    if chosen:
        parent = _parent_account(c, chosen)
    else:
        name = text_value(data.get('parent_name'), '家长姓名', 40)
        phone = phone_value(data.get('phone'))
        password = str(data.get('password') or '').strip()
        if not password:
            password = phone
        elif not 10 <= len(password) <= 128:
            raise ValueError('新家长的初始密码需为 10–128 位。')
        existing = c.execute('SELECT id, role FROM users WHERE phone=?', (phone,)).fetchone()
        if existing:
            raise ValueError('这个手机号已有账号。请从搜索结果里选择，不要新建。')
        pid = c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
            (phone, name, password_hash(password), 'parent')).lastrowid
        parent = _parent_account(c, pid)
    c.execute('INSERT OR IGNORE INTO profile_parents(profile_id, user_id) VALUES(?,?)',
        (student_row['profile_id'], parent['id']))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',
        (student_row['id'], user['id'], 'parent_linked'))
    auditlog.hint(c, f"关联家长 {parent['name']} 到 {student_row['name']}")
    auditlog.finish(c, user)
    return {'ok': True, 'parent_id': parent['id']}


def unlink_parent(c, user, data):
    if user['role'] not in ('owner', 'admin'):
        raise AccessError('只有老板或管理员可以取消家长关联。')
    schema(c)
    student_row = student(c, data)
    parent = _parent_account(c, data.get('parent_user_id') or 0)
    others = [row['user_id'] for row in c.execute(
        'SELECT user_id FROM profile_parents WHERE profile_id=? AND user_id!=?',
        (student_row['profile_id'], parent['id']))]
    if student_row['parent_id'] == parent['id'] and not others:
        raise ValueError('至少保留一位家长。可以先关联另一位，再取消这一位。')
    import auditlog
    auditlog.begin(c)
    c.execute('DELETE FROM profile_parents WHERE profile_id=? AND user_id=?',
        (student_row['profile_id'], parent['id']))
    if student_row['parent_id'] == parent['id']:
        c.execute('UPDATE students SET parent_id=? WHERE profile_id=?', (others[0], student_row['profile_id']))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',
        (student_row['id'], user['id'], 'parent_unlinked'))
    auditlog.hint(c, f"取消家长 {parent['name']} 与 {student_row['name']} 的关联")
    auditlog.finish(c, user)
    return {'ok': True}


def _course_person(c, data):
    """A course is opened for a person. The person can exist with no course row yet."""
    if data.get('student_id'):
        return student(c, data)
    ensure_identity(c)
    profile_id = int(data.get('profile_id') or 0)
    profile = c.execute('SELECT * FROM student_profiles WHERE id=?', (profile_id,)).fetchone()
    if not profile or not str(profile['name'] or '').strip():
        raise ValueError('学生不存在，请刷新页面。')
    parent = c.execute('SELECT user_id FROM profile_parents WHERE profile_id=? ORDER BY user_id LIMIT 1', (profile_id,)).fetchone()
    if not parent:
        raise ValueError('请先关联家长，再开课。')
    return {'id': None, 'name': profile['name'], 'profile_id': profile_id, 'parent_id': parent['user_id'],
        'birthday': profile['birthday'] or '', 'grade': profile['grade'] or '', 'notes': profile['notes'] or '',
        'billing_unit': 'lesson', 'helen_original': 0, 'course_type_id': None, 'level_code': '', 'level_year': 0,
        'archived': 0}


def add_course(c,user,data,text_value):
    import payroll
    payroll.reject_original_flag(user, data)
    require_admin(user)
    s=_course_person(c, data)
    subject_id = int(data.get('subject_id') or 0)
    if subject_id:
        subject = c.execute('SELECT name FROM subjects WHERE id=? AND active=1', (subject_id,)).fetchone()
        if not subject:
            raise ValueError('请选择科目。')
        course = subject['name']
    else:
        course=text_value(data.get('course'),'课程名称',80)
        subject = c.execute('SELECT id FROM subjects WHERE name=? AND active=1', (course,)).fetchone()
        if not subject:
            raise ValueError('请选择已启用的科目。')
        subject_id = subject['id']
    if c.execute('SELECT 1 FROM students WHERE profile_id=? AND course=? AND archived=0 AND IFNULL(voided,0)=0',(s['profile_id'],course)).fetchone():
        raise ValueError('这位学生已有关联课程，无需重复添加。')
    created=s['helen_original'] if 'helen_original' in s.keys() else 0
    type_id = int(data.get('course_type_id') or 0) or s['course_type_id']
    import pricing
    kind = c.execute('SELECT name FROM course_types WHERE id=?', (type_id,)).fetchone() if type_id else None
    level = s['level_code'] if 'level_code' in s.keys() else ''
    course, subject_id, type_id = pricing.apply_primary_class(c, course, subject_id, type_id, kind['name'] if kind else '', level)
    kind = c.execute('SELECT name FROM course_types WHERE id=?', (type_id,)).fetchone() if type_id else kind
    pricing.assert_singapore_enrolment(course, kind['name'] if kind else '', level)
    pricing.schema(c)
    study = pricing.clean_study_level(data.get('study_level'))
    stopped = c.execute('''SELECT id FROM students WHERE profile_id=? AND course=? AND (archived=1 OR IFNULL(voided,0)=1)
        ORDER BY id DESC LIMIT 1''', (s['profile_id'], course)).fetchone()
    if stopped:
        sid = stopped['id']
        c.execute('''UPDATE students SET archived=0, voided=0, settle_reason='', billing_unit=?, helen_original=?, subject_id=?, course_type_id=?, level_code=?, level_year=?, study_level=?
            WHERE id=?''', (s['billing_unit'], created, subject_id, type_id, s['level_code'] if 'level_code' in s.keys() else '', s['level_year'] if 'level_year' in s.keys() else 0, study, sid))
    else:
        sid=c.execute('INSERT INTO students(name,course,parent_id,profile_id,birthday,grade,notes) VALUES(?,?,?,?,?,?,?)',(s['name'],course,s['parent_id'],s['profile_id'],s['birthday'],s['grade'],s['notes'])).lastrowid
        c.execute('UPDATE students SET billing_unit=?,helen_original=?,subject_id=?,course_type_id=?,level_code=?,level_year=?,study_level=? WHERE id=?',(s['billing_unit'],created,subject_id,type_id,s['level_code'] if 'level_code' in s.keys() else '', s['level_year'] if 'level_year' in s.keys() else 0, study, sid))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',(s['id'] or sid,user['id'],'course_added'))
    import timeline
    timeline.record(c, user, sid, 'course_added', f'添加课程 {course}')
    moved=relink_future_lessons(c, sid)
    return {'ok':True,'student_id':sid,'moved':moved}


def same_subject(left_name, left_subject, right_name, right_subject):
    """数学 and 英语 match even when the old course name is longer, such as 数学 一对一.

    VCE 中数, VCE 低数 and VCE 高数 do not match 数学. Math Methods matches VCE 中数.
    新加坡数学 does not match 数学.
    """
    def token(name, subject):
        blob = f'{subject or ""} {name or ""}'
        import teaching
        if teaching.combo_subject(blob):
            return teaching.COMBO_SUBJECT
        for part in (subject, name, blob):
            found = vce_subject(part) or singapore_subject(part)
            if found:
                return found
        text=f'{subject or ""} {name or ""}'
        if '数学' in text:
            return '数学'
        if '英语' in text:
            return '英语'
        return (subject or name or '').strip()
    a, b = token(left_name, left_subject), token(right_name, right_subject)
    return bool(a) and a==b


def relink_future_lessons(c, student_id):
    """Point future scheduled lessons from an archived same-subject course at this one."""
    current=c.execute('''SELECT s.*, sb.name subject_name FROM students s
        LEFT JOIN subjects sb ON sb.id=s.subject_id WHERE s.id=?''', (int(student_id),)).fetchone()
    if not current or current['archived']:
        return 0
    now=now_local().strftime('%Y-%m-%dT%H:%M')
    olds=c.execute('''SELECT s.id, s.course, sb.name subject_name FROM students s
        LEFT JOIN subjects sb ON sb.id=s.subject_id
        WHERE s.profile_id=? AND s.id!=? AND s.archived=1''', (current['profile_id'], current['id'])).fetchall()
    moved=0
    for old in olds:
        if not same_subject(current['course'], current['subject_name'], old['course'], old['subject_name']):
            continue
        moved += move_future_lessons(c, old['id'], current['id'])
    return moved


def move_future_lessons(c, from_id, to_id):
    """Point future lessons and repeat templates from one enrolment at another."""
    from_id, to_id = int(from_id), int(to_id)
    if from_id == to_id:
        return 0
    now = now_local().strftime('%Y-%m-%dT%H:%M')
    moved = 0
    lessons = c.execute('''SELECT l.id FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        WHERE ls.student_id=? AND l.status='scheduled' AND l.starts_at>=?''', (from_id, now)).fetchall()
    for lesson in lessons:
        already = c.execute('SELECT 1 FROM lesson_students WHERE lesson_id=? AND student_id=?', (lesson['id'], to_id)).fetchone()
        if already:
            c.execute('DELETE FROM lesson_students WHERE lesson_id=? AND student_id=?', (lesson['id'], from_id))
        else:
            c.execute('UPDATE lesson_students SET student_id=? WHERE lesson_id=? AND student_id=?', (to_id, lesson['id'], from_id))
        report = c.execute('SELECT 1 FROM lesson_reports WHERE lesson_id=? AND student_id=?', (lesson['id'], to_id)).fetchone()
        if report:
            c.execute('DELETE FROM lesson_reports WHERE lesson_id=? AND student_id=?', (lesson['id'], from_id))
        else:
            c.execute('UPDATE lesson_reports SET student_id=? WHERE lesson_id=? AND student_id=?', (to_id, lesson['id'], from_id))
        moved += 1
    _retarget_series(c, from_id, to_id)
    return moved


def _retarget_series(c, from_id, to_id):
    import json
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_series'").fetchone():
        return
    for rule in c.execute('SELECT id, template FROM lesson_series'):
        try:
            template = json.loads(rule['template'] or '{}')
        except json.JSONDecodeError:
            continue
        raw = template.get('student_ids') or []
        if not any(str(item) == str(from_id) for item in raw):
            continue
        new = []
        for item in raw:
            if str(item) == str(from_id):
                if not any(str(kept) == str(to_id) for kept in new):
                    new.append(to_id)
            else:
                new.append(item)
        template['student_ids'] = new
        c.execute('UPDATE lesson_series SET template=? WHERE id=?', (json.dumps(template), rule['id']))


def set_study_level(c, user, data):
    """Optional content year for one course. Blank clears it."""
    require_admin(user)
    import pricing
    pricing.schema(c)
    row = student(c, data)
    code = pricing.clean_study_level(data.get('study_level'))
    c.execute('UPDATE students SET study_level=? WHERE id=?', (code, row['id']))
    return {'ok': True, 'study_level': code}


def relink_future(c, user, data):
    require_admin(user)
    sid=int(data.get('student_id') or 0)
    if not c.execute('SELECT 1 FROM students WHERE id=? AND archived=0', (sid,)).fetchone():
        raise ValueError('这门课不存在，请刷新页面。')
    moved=relink_future_lessons(c, sid)
    return {'ok':True,'moved':moved}

def billing_unit(value):
    if value not in ('lesson','hour'):raise ValueError('请选择按课时或按小时计费。')
    return value


def profiles_without_courses(c, covered_ids, user, include_left=False):
    """People who still have an account after every course row is gone."""
    if not user or user['role'] == 'teacher':
        return []
    ensure_enrolment_columns(c)
    shells = []
    for profile in c.execute('SELECT * FROM student_profiles ORDER BY id'):
        if profile['id'] in covered_ids or (profile['status'] or '') == 'withdrawn':
            continue
        if str(profile['left_on'] or '').strip() and user['role'] in ('owner', 'admin') and not include_left:
            continue
        if include_left and not str(profile['left_on'] or '').strip():
            continue
        if not str(profile['name'] or '').strip():
            continue
        if user['role'] == 'parent' and not c.execute(
                'SELECT 1 FROM profile_parents WHERE profile_id=? AND user_id=?', (profile['id'], user['id'])).fetchone():
            continue
        parent = c.execute('''SELECT u.id, u.name, u.phone, u.contact_phone FROM profile_parents pp
            JOIN users u ON u.id=pp.user_id WHERE pp.profile_id=? AND u.role='parent'
            ORDER BY pp.user_id LIMIT 1''', (profile['id'],)).fetchone()
        shell = {'id': 'p%s' % profile['id'], 'profile_id': profile['id'], 'name': profile['name'],
            'course': '', 'subject_name': '', 'course_type_name': '', 'balance': 0, 'paid_balance': 0,
            'gift_balance': 0, 'credit_batches': [], 'archived': 0, 'voided': 0, 'no_course': True,
            'birthday': profile['birthday'] or '', 'grade': profile['grade'] or '', 'notes': profile['notes'] or '',
            'study_status': profile['study_status'] or 'studying', 'billing_unit': 'lesson', 'level_code': '',
            'left_on': profile['left_on'] or '', 'left_reason': profile['left_reason'] or '',
            'parent_id': parent['id'] if parent else None, 'parent_name': parent['name'] if parent else '',
            'phone': parent['phone'] if parent else '', 'contact_phone': (parent['contact_phone'] if parent else '') or '',
            'legacy': False, 'legacy_subjects': []}
        if user['role'] in ('owner', 'admin'):
            shell['parents'] = parents_for(c, profile['id'], shell['parent_id'])
        import pricing
        pricing.annotate(shell)
        shells.append(shell)
    return shells


def _parent_ids(c, profile_id, primary_id):
    found = set()
    if primary_id:
        found.add(int(primary_id))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_parents'").fetchone():
        for row in c.execute('SELECT user_id FROM profile_parents WHERE profile_id=?', (profile_id,)):
            found.add(int(row['user_id']))
    found.discard(0)
    return found


def merge_plan(c):
    """Course rows for one person and one parent belong on one profile."""
    ensure_identity(c)
    rows = [dict(row) for row in c.execute('SELECT id, name, course, parent_id, profile_id, archived FROM students ORDER BY id')]
    if not rows:
        return []
    parent = {row['id']: row['id'] for row in rows}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left, right):
        ra, rb = find(left), find(right)
        if ra != rb:
            parent[rb] = ra

    by_profile = {}
    for row in rows:
        by_profile.setdefault(row['profile_id'], []).append(row['id'])
    for ids in by_profile.values():
        for other in ids[1:]:
            union(ids[0], other)
    by_name = {}
    for row in rows:
        name = normalize_person_name(row['name'])
        if not name:
            continue
        for user_id in _parent_ids(c, row['profile_id'], row['parent_id']):
            by_name.setdefault((name, user_id), []).append(row['id'])
    for ids in by_name.values():
        for other in ids[1:]:
            union(ids[0], other)
    grouped = {}
    for row in rows:
        grouped.setdefault(find(row['id']), []).append(row)
    plan = []
    for group in grouped.values():
        profiles = sorted({row['profile_id'] for row in group if row['profile_id']})
        if len(profiles) < 2:
            continue
        keeper = profiles[0]
        plan.append({'name': group[0]['name'], 'keeper': keeper, 'profiles': profiles, 'rows': group})
    plan.sort(key=lambda item: item['keeper'])
    return plan


def apply_merge(c, plan):
    ensure_identity(c)
    for group in plan:
        keeper = group['keeper']
        for row in group['rows']:
            if row['profile_id'] != keeper:
                c.execute('UPDATE students SET profile_id=? WHERE id=?', (keeper, row['id']))
        for donor in group['profiles']:
            if donor == keeper:
                continue
            c.execute('''INSERT OR IGNORE INTO profile_parents(profile_id, user_id)
                SELECT ?, user_id FROM profile_parents WHERE profile_id=?''', (keeper, donor))
            c.execute('DELETE FROM profile_parents WHERE profile_id=?', (donor,))
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_events'").fetchone():
                c.execute('UPDATE profile_events SET profile_id=? WHERE profile_id=?', (keeper, donor))
            c.execute('DELETE FROM student_profiles WHERE id=? AND NOT EXISTS (SELECT 1 FROM students WHERE profile_id=?)', (donor, donor))
        ensure_identity(c)


def _profile_from(c, data):
    ensure_enrolment_columns(c)
    if data.get('profile_id') and not data.get('student_id'):
        profile = c.execute('SELECT * FROM student_profiles WHERE id=?', (int(data['profile_id']),)).fetchone()
    else:
        row = student(c, data)
        profile = c.execute('SELECT * FROM student_profiles WHERE id=?', (row['profile_id'],)).fetchone()
    if not profile:
        raise ValueError('学生不存在，请刷新页面。')
    return profile


def future_active_lessons(c, profile_id):
    """Scheduled lessons still ahead on a course that has not been stopped."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lessons'").fetchone():
        return []
    now = now_local().strftime('%Y-%m-%dT%H:%M')
    return [dict(row) for row in c.execute('''SELECT l.id lesson_id, l.starts_at, l.title, s.id student_id, s.course, s.name
        FROM lessons l
        JOIN lesson_students ls ON ls.lesson_id=l.id
        JOIN students s ON s.id=ls.student_id
        WHERE s.profile_id=? AND s.archived=0 AND IFNULL(s.voided,0)=0
          AND l.status='scheduled' AND l.starts_at>=?
        ORDER BY l.starts_at, l.id''', (profile_id, now))]


def mark_left(c, user, data):
    """The person stops studying. Courses, history and money stay."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以标记不再上课。')
    profile = _profile_from(c, data)
    if str(profile['left_on'] or '').strip():
        raise ValueError('这位学生已经不再上课。')
    lessons = future_active_lessons(c, profile['id'])
    if lessons:
        return {'ok': False, 'blocked': True, 'lessons': lessons}
    reason = str(data.get('reason') or '').strip()
    if len(reason) > 200:
        raise ValueError('原因最多 200 个字。')
    import auditlog
    auditlog.begin(c)
    today = now_local().date().isoformat()
    c.execute('UPDATE student_profiles SET left_on=?, left_reason=? WHERE id=?', (today, reason, profile['id']))
    hint = '不再上课：%s' % (profile['name'] or '学生')
    if reason:
        hint += '（%s）' % reason
    auditlog.hint(c, hint)
    auditlog.finish(c, user)
    return {'ok': True, 'left_on': today}


def mark_returned(c, user, data):
    """Bring a person who left back to the active list. Courses are not reopened."""
    if user['role'] != 'owner':
        raise AccessError('只有老板可以恢复学生。')
    profile = _profile_from(c, data)
    if not str(profile['left_on'] or '').strip():
        raise ValueError('这位学生还在上课名单里。')
    import auditlog
    auditlog.begin(c)
    c.execute("UPDATE student_profiles SET left_on='', left_reason='' WHERE id=?", (profile['id'],))
    auditlog.hint(c, '恢复：%s' % (profile['name'] or '学生'))
    auditlog.finish(c, user)
    return {'ok': True}
