"""Editable student profiles and guardian account administration."""
import datetime as dt
from teaching import AccessError, now_local

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
    for name in ('birthday','grade','notes'):
        if name not in cols:
            c.execute('ALTER TABLE students ADD COLUMN '+name+" TEXT NOT NULL DEFAULT ''")
    cols={r['name'] for r in c.execute('PRAGMA table_info(users)')}
    if 'contact_phone' not in cols:
        c.execute("ALTER TABLE users ADD COLUMN contact_phone TEXT NOT NULL DEFAULT ''")
    c.execute("CREATE TABLE IF NOT EXISTS profile_audit (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id), actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")

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

def require_admin(user):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有老板或管理员可以编辑学生档案。')

def student(c,data):
    row=c.execute('SELECT * FROM students WHERE archived=0 AND id=?',(int(data.get('student_id',0)),)).fetchone()
    if not row: raise ValueError('学生不存在，请刷新页面。')
    return row

def update(c,user,data,text_value):
    require_admin(user)
    s=student(c,data)
    name=text_value(data.get('name'),'学生姓名',40)
    birthday,grade,notes=fields(data)
    c.execute('UPDATE students SET name=?,birthday=?,grade=?,notes=? WHERE profile_id=?',(name,birthday,grade,notes,s['profile_id']))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',(s['id'],user['id'],'profile_updated'))
    return {'ok':True}

def guardian(c,user,data,text_value,phone_value,password_hash):
    require_admin(user)
    s=student(c,data)
    parent=c.execute("SELECT * FROM users WHERE id=? AND role='parent'",(s['parent_id'],)).fetchone()
    if not parent or c.execute('SELECT 1 FROM teachers WHERE user_id=?',(s['parent_id'],)).fetchone():
        raise ValueError('此账号不是家长账号。')
    name=text_value(data.get('parent_name'),'家长姓名',40)
    login=phone_value(data.get('phone'))
    contact=str(data.get('contact_phone','')).strip()
    if contact: contact=phone_value(contact)
    if c.execute('SELECT 1 FROM users WHERE phone=? AND id!=?',(login,parent['id'])).fetchone():
        raise ValueError('此登录手机号已被其他账号使用。')
    password=str(data.get('password',''))
    if password and not 10<=len(password)<=128:
        raise ValueError('新密码需为 10–128 位。')
    c.execute('UPDATE users SET name=?,phone=?,contact_phone=? WHERE id=?',(name,login,contact,parent['id']))
    if password:
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),parent['id']))
    if password or login!=parent['phone']:
        c.execute('DELETE FROM sessions WHERE user_id=?',(parent['id'],))
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',(s['id'],user['id'],'guardian_updated_with_reset' if password else 'guardian_updated'))
    return {'ok':True}


def add_course(c,user,data,text_value):
    require_admin(user)
    s=student(c,data)
    course=text_value(data.get('course'),'课程名称',80)
    if not c.execute("SELECT 1 FROM schedule_options WHERE kind='course' AND name=? AND active=1",(course,)).fetchone():
        raise ValueError('请选择已启用的课程。')
    if c.execute('SELECT 1 FROM students WHERE profile_id=? AND course=?',(s['profile_id'],course)).fetchone():
        raise ValueError('这位学生已有关联课程，无需重复添加。')
    sid=c.execute('INSERT INTO students(name,course,parent_id,profile_id,birthday,grade,notes) VALUES(?,?,?,?,?,?,?)',(s['name'],course,s['parent_id'],s['profile_id'],s['birthday'],s['grade'],s['notes'])).lastrowid
    c.execute('INSERT INTO profile_audit(student_id,actor_id,action) VALUES(?,?,?)',(s['id'],user['id'],'course_added'))
    return {'ok':True,'student_id':sid}
