"""Scheduling and teaching reports. All mutation callers hold a DB transaction."""
import datetime as dt
import json
import hashlib
import credit_batches
import os
import re
from zoneinfo import ZoneInfo

TIMEZONE = os.environ.get('LESSON_TIMEZONE', os.environ.get('TZ', 'Australia/Melbourne'))
ZONE = ZoneInfo(TIMEZONE)

class AccessError(Exception):
    pass

def now_local():
    return dt.datetime.now(ZONE).replace(tzinfo=None)

def schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS schedule_options (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('course','location')),
        name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        UNIQUE(kind,name)
    );
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        subject TEXT NOT NULL DEFAULT '数学'
    );
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
        title TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
        planned_units INTEGER NOT NULL CHECK(planned_units>0), location TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')),
        cancel_reason TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER NOT NULL REFERENCES users(id), request_id TEXT NOT NULL UNIQUE,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE IF NOT EXISTS lesson_students (
        lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        student_id INTEGER NOT NULL REFERENCES students(id), PRIMARY KEY(lesson_id,student_id)
    );
    CREATE TABLE IF NOT EXISTS lesson_reports (
        lesson_id INTEGER NOT NULL REFERENCES lessons(id), student_id INTEGER NOT NULL REFERENCES students(id),
        amount INTEGER NOT NULL CHECK(amount>0), content TEXT NOT NULL DEFAULT '',
        homework TEXT NOT NULL DEFAULT '', feedback TEXT NOT NULL DEFAULT '',
        ledger_id INTEGER UNIQUE REFERENCES ledger(id), updated_by INTEGER NOT NULL REFERENCES users(id),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(lesson_id,student_id)
    );
    CREATE TABLE IF NOT EXISTS report_edits (
        id INTEGER PRIMARY KEY, lesson_id INTEGER NOT NULL REFERENCES lessons(id),
        actor_id INTEGER NOT NULL REFERENCES users(id), payload TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX IF NOT EXISTS lesson_time ON lessons(teacher_id,starts_at,ends_at);
    CREATE INDEX IF NOT EXISTS enrollment_student ON lesson_students(student_id,lesson_id);
    ''')
    if 'subjects' not in {r['name'] for r in c.execute('PRAGMA table_info(teachers)')}:
        c.execute("ALTER TABLE teachers ADD COLUMN subjects TEXT NOT NULL DEFAULT '[]'")
    c.execute("INSERT OR IGNORE INTO teachers(user_id) SELECT id FROM users WHERE role='admin'")
    if not c.execute("SELECT 1 FROM app_meta WHERE key='schedule_options_v1'").fetchone():
        for kind, names in [('course',['数学 · 一对一','物理','化学']),('location',[])]:
            column='title' if kind=='course' else 'location'
            names += [r[0] for r in c.execute('SELECT DISTINCT '+column+" FROM lessons WHERE "+column+"!=''")]
            c.executemany('INSERT OR IGNORE INTO schedule_options(kind,name) VALUES(?,?)',[(kind,n) for n in names])
        c.execute("INSERT INTO app_meta VALUES('schedule_options_v1','1')")


def staff_or_admin(user):
    if user['role'] not in ('owner','admin','teacher'):
        raise AccessError('只有管理员或任课老师可以填写课后记录。')

def allowed_lesson(c,user,lesson_id):
    staff_or_admin(user)
    lesson=c.execute('SELECT l.*,t.user_id teacher_user_id FROM lessons l JOIN teachers t ON l.teacher_id=t.id WHERE l.id=?',(int(lesson_id),)).fetchone()
    if not lesson or (user['role'] not in ('owner','admin') and lesson['teacher_user_id']!=user['id']):
        raise AccessError('无法访问这节课程。')
    return lesson

def check_version(lesson,data):
    if int(data.get('version',0))!=lesson['version']:
        raise ValueError('这节课已被更新，请刷新页面后再操作。')

def datetime_value(value):
    value=str(value or '')
    if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d',value):
        raise ValueError('请选择有效的上课日期和时间。')
    parsed=dt.datetime.fromisoformat(value)
    aware=parsed.replace(tzinfo=ZONE)
    if aware.astimezone(dt.timezone.utc).astimezone(ZONE).replace(tzinfo=None)!=parsed:
        raise ValueError('所选时间处于夏令时调整区间，请选择其他时间。')
    if aware.utcoffset()!=parsed.replace(tzinfo=ZONE,fold=1).utcoffset():
        raise ValueError('所选时间有夏令时歧义，请选择其他时间。')
    return parsed

def state_for(c,user):
    role=user['role']
    where, params=('',())
    if role=='teacher':
        where,params=(' WHERE t.user_id=?',(user['id'],))
    elif role=='parent':
        where,params=(' WHERE EXISTS (SELECT 1 FROM lesson_students ls JOIN students s ON ls.student_id=s.id WHERE ls.lesson_id=l.id AND s.parent_id=?)',(user['id'],))
    lessons=[dict(x) for x in c.execute('SELECT l.*,u.name teacher_name FROM lessons l JOIN teachers t ON l.teacher_id=t.id JOIN users u ON t.user_id=u.id'+where+' ORDER BY l.starts_at,l.id',params)]
    for lesson in lessons:
        member_where=' AND s.parent_id=?' if role=='parent' else ''
        member_params=(lesson['id'],user['id']) if role=='parent' else (lesson['id'],)
        lesson['students']=[dict(x) for x in c.execute('SELECT s.id,s.name,s.course,s.balance FROM lesson_students ls JOIN students s ON ls.student_id=s.id WHERE ls.lesson_id=?'+member_where+' ORDER BY s.id',member_params)]
        if role=='parent' and lesson['status']!='completed':
            lesson['reports']=[]
        else:
            lesson['reports']=[dict(x) for x in c.execute('SELECT r.*,s.name student_name,v.id reversed_by FROM lesson_reports r JOIN students s ON r.student_id=s.id LEFT JOIN ledger v ON v.reversal_of=r.ledger_id WHERE r.lesson_id=?'+member_where+' ORDER BY s.id',member_params)]
    teachers=[]
    if role in ('owner','admin','teacher'):
        tw='' if role in ('owner','admin') else ' WHERE u.id=? AND u.active=1'
        tp=() if role in ('owner','admin') else (user['id'],)
        teachers=[dict(x) for x in c.execute("SELECT t.id,t.subject,t.subjects,u.name,u.phone,u.active,u.id user_id,CASE WHEN EXISTS(SELECT 1 FROM organization_owners o WHERE o.user_id=u.id) THEN 'owner' WHEN u.role='admin' THEN 'admin' ELSE 'teacher' END account_role FROM teachers t JOIN users u ON t.user_id=u.id"+tw+' ORDER BY t.id',tp)]
    for t in teachers:
        t['subjects']=json.loads(t['subjects']) or [t['subject']]
    return {'schedule_options':[dict(x) for x in c.execute('SELECT * FROM schedule_options ORDER BY kind,id')] if role in ('owner','admin','teacher') else [],'lessons':lessons,'teachers':teachers,'timezone':TIMEZONE,'today':now_local().date().isoformat(),'now':now_local().strftime('%Y-%m-%dT%H:%M')}

def create_teacher(c,user,data,phone_value,password_hash,text_value):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有管理员可以添加老师。')
    phone=phone_value(data.get('phone'))
    name=text_value(data.get('name'),'老师姓名',40)
    subjects=subject_values(data,text_value)
    subject='、'.join(subjects)
    password=str(data.get('password',''))
    if not 10<=len(password)<=128:
        raise ValueError('初始密码需为 10–128 位。')
    if c.execute('SELECT 1 FROM users WHERE phone=?',(phone,)).fetchone():
        raise ValueError('该手机号已有账号，请使用独立的老师手机号。')
    # Teacher membership augments legacy users without rebuilding its FK-bound table.
    uid=c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",(phone,name,password_hash(password))).lastrowid
    tid=c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)',(uid,subject)).lastrowid
    c.execute('UPDATE teachers SET subjects=? WHERE id=?',(json.dumps(subjects,ensure_ascii=False),tid))
    return {'ok':True,'teacher_id':tid}

def require_scheduler(c,user,data):
    if user['role'] in ('owner','admin'):return
    if user['role']!='teacher' or data.get('lesson_id'):
        raise AccessError('只有管理员可以排课或调整课程。')
    own=c.execute('SELECT id FROM teachers WHERE user_id=?',(user['id'],)).fetchone()
    if not own or str(data.get('teacher_id'))!=str(own['id']):
        raise AccessError('老师只能为自己的学生安排自己的课程。')
    members=data.get('student_ids')
    if not isinstance(members,list) or not members:
        raise AccessError('老师只能为自己的学生安排自己的课程。')
    for sid in members:
        if not c.execute('SELECT 1 FROM lesson_students ls JOIN lessons l ON ls.lesson_id=l.id WHERE ls.student_id=? AND l.teacher_id=?',(int(sid),own['id'])).fetchone():
            raise AccessError('老师只能为自己的学生安排自己的课程。')

def save_schedule(c,user,data,units,text_value):
    require_scheduler(c,user,data)
    repeat=str(data.get('repeat','none'))
    if repeat not in ('none','weekly','fortnightly'):
        raise ValueError('重复选项无效。')
    if data.get('lesson_id'):
        if repeat!='none':raise ValueError('调整课程仅修改本次课程。')
        return save_lesson(c,user,data,units,text_value)
    if repeat=='none':return save_lesson(c,user,data,units,text_value)
    raw=str(data.get('repeat_count',''))
    if not re.fullmatch(r'[0-9]{1,2}',raw) or not 2<=int(raw)<=52:
        raise ValueError('总课次数需为 2–52 次，包含本次。')
    count=int(raw)
    key=str(data.get('request_id',''))
    if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',key):
        raise ValueError('操作编号无效，请重新打开排课表单。')
    existing=c.execute('SELECT id FROM lessons WHERE request_id=?',(key,)).fetchone()
    if existing:return {'ok':True,'lesson_id':existing['id'],'duplicate':True}
    start=datetime_value(data.get('starts_at'))
    end=datetime_value(data.get('ends_at'))
    ids=[]
    for i in range(count):
        offset=dt.timedelta(days=i*(7 if repeat=='weekly' else 14))
        item={**data,'starts_at':(start+offset).strftime('%Y-%m-%dT%H:%M'),
              'ends_at':(end+offset).strftime('%Y-%m-%dT%H:%M'),
              'request_id':key if i==0 else hashlib.sha256((key+':'+str(i)).encode()).hexdigest()}
        try:ids.append(save_lesson(c,user,item,units,text_value)['lesson_id'])
        except ValueError as e:
            raise ValueError(item['starts_at'][:10]+'：'+str(e)) from e
    return {'ok':True,'lesson_id':ids[0],'lesson_ids':ids,'created_count':len(ids)}

def save_lesson(c,user,data,units,text_value):
    require_scheduler(c,user,data)
    lesson_id=int(data.get('lesson_id') or 0)
    if lesson_id:
        old=allowed_lesson(c,user,lesson_id)
        check_version(old,data)
        if old['status']!='scheduled':
            raise ValueError('只能修改尚未完成且未取消的课程。')
    else:
        key=str(data.get('request_id',''))
        if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',key):
            raise ValueError('操作编号无效，请重新打开排课表单。')
        existing=c.execute('SELECT id FROM lessons WHERE request_id=?',(key,)).fetchone()
        if existing:
            return {'ok':True,'lesson_id':existing['id'],'duplicate':True}
    title=text_value(data.get('title'),'课程名称',80)
    teacher_id=int(data.get('teacher_id',0))
    if not c.execute('SELECT 1 FROM teachers t JOIN users u ON t.user_id=u.id WHERE t.id=? AND u.active=1',(teacher_id,)).fetchone():
        raise ValueError('请选择有效的任课老师。')
    start=datetime_value(data.get('starts_at'))
    end=datetime_value(data.get('ends_at'))
    if end<=start or end-start>dt.timedelta(hours=12):
        raise ValueError('结束时间必须晚于开始时间，单次课程最长 12 小时。')
    start,end=start.strftime('%Y-%m-%dT%H:%M'),end.strftime('%Y-%m-%dT%H:%M')
    raw=data.get('student_ids')
    if not isinstance(raw,list) or not 1<=len(raw)<=30:
        raise ValueError('每节课请选择 1–30 位学生。')
    members=sorted(set(int(x) for x in raw))
    profile_ids=[]
    for sid in members:
        account=c.execute('SELECT profile_id FROM students WHERE id=?',(sid,)).fetchone()
        if account: profile_ids.append(account['profile_id'])
    if len(profile_ids)!=len(set(profile_ids)):
        raise ValueError('同一节课，每位学生只能选择一个扣课科目。')
    amount=units(data.get('amount'))
    location=str(data.get('location','')).strip()
    if len(location)>150:
        raise ValueError('上课地点不能超过 150 个字。')
    if c.execute("SELECT 1 FROM lessons WHERE teacher_id=? AND status!='cancelled' AND id!=? AND starts_at<? AND ends_at>?",(teacher_id,lesson_id,end,start)).fetchone():
        raise ValueError('这位老师在该时段已有课程，请调整时间或老师。')
    for sid in members:
        student=c.execute('SELECT name,archived FROM students WHERE id=?',(sid,)).fetchone()
        if not student:
            raise ValueError('所选学生不存在，请刷新后重试。')
        if student['archived']:
            raise ValueError('学生已归档，请先恢复档案再排课。')
        if c.execute("SELECT 1 FROM lesson_students ls JOIN lessons l ON ls.lesson_id=l.id JOIN students enrolled ON enrolled.id=ls.student_id WHERE enrolled.profile_id=(SELECT profile_id FROM students WHERE id=?) AND l.status!='cancelled' AND l.id!=? AND l.starts_at<? AND l.ends_at>?",(sid,lesson_id,end,start)).fetchone():
            raise ValueError(student['name']+'在该时段已有课程。')
    if lesson_id:
        c.execute("UPDATE lessons SET title=?,teacher_id=?,starts_at=?,ends_at=?,planned_units=?,location=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(title,teacher_id,start,end,amount,location,lesson_id))
        c.execute('DELETE FROM lesson_students WHERE lesson_id=?',(lesson_id,))
        marks=','.join('?' for _ in members)
        c.execute(f'DELETE FROM lesson_reports WHERE lesson_id=? AND student_id NOT IN ({marks})',(lesson_id,*members))
    else:
        lesson_id=c.execute('INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id) VALUES(?,?,?,?,?,?,?,?)',(teacher_id,title,start,end,amount,location,user['id'],key)).lastrowid
    c.executemany('INSERT INTO lesson_students VALUES(?,?)',[(lesson_id,sid) for sid in members])
    return {'ok':True,'lesson_id':lesson_id}

def cancel_lesson(c,user,data,text_value):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有管理员可以取消课程。')
    lesson=allowed_lesson(c,user,data['lesson_id'])
    check_version(lesson,data)
    if lesson['status']!='scheduled':
        raise ValueError('只能取消未完成的课程。已完成的课时请通过账本撤销。')
    reason=text_value(data.get('reason'),'取消原因',250)
    c.execute("UPDATE lessons SET status='cancelled',cancel_reason=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(reason,lesson['id']))
    return {'ok':True}

def save_reports(c,user,data,units,action):
    lesson=allowed_lesson(c,user,data['lesson_id'])
    if action=='complete' and lesson['status']=='completed':
        return {'ok':True,'duplicate':True}
    check_version(lesson,data)
    if lesson['status']=='cancelled':
        raise ValueError('已取消的课程不能填写或发布课后记录。')
    if action=='complete' and lesson['ends_at']>now_local().strftime('%Y-%m-%dT%H:%M'):
        raise ValueError('课程尚未结束，可先保存草稿，结束后再确认完成。')
    if action=='draft' and lesson['status']!='scheduled':
        raise ValueError('已完成课程请使用修改课后记录。')
    if action=='edit' and lesson['status']!='completed':
        raise ValueError('课程尚未完成，请先填写并确认完成。')
    members={x['student_id'] for x in c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?',(lesson['id'],))}
    raw=data.get('reports')
    if not isinstance(raw,list) or len(raw)!=len(members) or {int(x['student_id']) for x in raw}!=members:
        raise ValueError('请为这节课的每位学生填写记录。')
    cleaned=[]
    for item in raw:
        sid=int(item['student_id'])
        content=str(item.get('content','')).strip()
        homework=str(item.get('homework','')).strip()
        feedback=str(item.get('feedback','')).strip()
        if any(len(x)>2000 for x in (content,homework,feedback)):
            raise ValueError('学习内容、今日作业和课后反馈各最多 2000 字。')
        if action!='draft' and (not content or not homework or not feedback):
            raise ValueError('请填写学习内容、今日作业和课后反馈；没有作业可填写“今日无作业”。')
        amount=units(item.get('amount'))
        old=c.execute('SELECT * FROM lesson_reports WHERE lesson_id=? AND student_id=?',(lesson['id'],sid)).fetchone()
        if action=='edit' and (not old or amount!=old['amount']):
            raise ValueError('修改反馈不会改变课时。需要调整扣费请由管理员在账本中处理。')
        if action=='complete':
            student=c.execute('SELECT name,balance FROM students WHERE id=?',(sid,)).fetchone()
            if student['balance']<amount:
                raise ValueError(student['name']+'的剩余课时不足。本次尚未扣除任何学生的课时，可先保存草稿。')
        cleaned.append((sid,amount,content,homework,feedback))
    # All validation precedes writes; the caller commits all students atomically.
    for sid,amount,content,homework,feedback in cleaned:
        c.execute("INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,updated_by) VALUES(?,?,?,?,?,?,?) ON CONFLICT(lesson_id,student_id) DO UPDATE SET amount=excluded.amount,content=excluded.content,homework=excluded.homework,feedback=excluded.feedback,updated_by=excluded.updated_by,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",(lesson['id'],sid,amount,content,homework,feedback,user['id']))
        if action=='complete':
            ledger_id=c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,?,?,?)",(sid,-amount,lesson['starts_at'][:10],lesson['title']+' · 课后记录',user['id'],f"scheduled-{lesson['id']}-student-{sid}")).lastrowid
            credit_batches.apply(c,ledger_id,'lesson',{},units)
            c.execute('UPDATE lesson_reports SET ledger_id=? WHERE lesson_id=? AND student_id=?',(ledger_id,lesson['id'],sid))
    c.execute("UPDATE lessons SET status=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",('completed' if action in ('complete','edit') else 'scheduled',lesson['id']))
    c.execute('INSERT INTO report_edits(lesson_id,actor_id,payload) VALUES(?,?,?)',(lesson['id'],user['id'],json.dumps({'action':action,'reports':raw},ensure_ascii=False)))
    return {'ok':True}


def save_option(c,user,data,text_value):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有老板或管理员可以设置课程与地点。')
    kind=data.get('kind')
    if kind not in ('course','location'):
        raise ValueError('选项类型无效。')
    name=text_value(data.get('name'),'选项名称',80 if kind=='course' else 150)
    active=data.get('active',True)
    if type(active) is not bool:
        raise ValueError('选项状态无效。')
    option_id=int(data.get('id') or 0)
    if option_id and not c.execute('SELECT 1 FROM schedule_options WHERE id=? AND kind=?',(option_id,kind)).fetchone():
        raise ValueError('选项不存在，请刷新页面。')
    if c.execute('SELECT 1 FROM schedule_options WHERE kind=? AND name=? AND id!=?',(kind,name,option_id)).fetchone():
        raise ValueError('已有同名选项，请编辑或启用原选项。')
    if option_id:
        c.execute('UPDATE schedule_options SET name=?,active=? WHERE id=?',(name,int(active),option_id))
    else:
        option_id=c.execute('INSERT INTO schedule_options(kind,name,active) VALUES(?,?,?)',(kind,name,int(active))).lastrowid
    return {'ok':True,'id':option_id}


def subject_values(data,text_value):
    raw=data.get('subjects')
    if raw is None: raw=[data.get('subject')]
    if not isinstance(raw,list) or not 1<=len(raw)<=20:
        raise ValueError('请选择 1–20 个教学科目。')
    return list(dict.fromkeys(text_value(x,'教学科目',80) for x in raw))

def managed_teacher(c,user,data):
    if user['role'] not in ('owner','admin'):
        raise AccessError('只有老板或管理员可以管理老师。')
    t=c.execute("SELECT t.*,u.name,u.phone,u.role,u.active,EXISTS(SELECT 1 FROM organization_owners o WHERE o.user_id=u.id) is_owner FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.id=?",(int(data.get('teacher_id',0)),)).fetchone()
    if not t: raise ValueError('老师不存在，请刷新页面。')
    if (t['is_owner'] or t['role']=='admin') and user['role']!='owner':
        raise AccessError('管理员兼任老师的资料仅可由老板修改。')
    return t

def edit_teacher(c,user,data,phone_value,password_hash,text_value):
    t=managed_teacher(c,user,data)
    subjects=subject_values(data,text_value)
    if t['is_owner'] or t['role']=='admin':
        if any(k in data for k in ('name','phone','password')):
            raise ValueError('管理账号请在管理员页面或个人账号中修改，此处仅编辑教学科目。')
    else:
        name=text_value(data.get('name'),'老师姓名',40)
        phone=phone_value(data.get('phone'))
        password=str(data.get('password',''))
        if password and not 10<=len(password)<=128:raise ValueError('新密码需为 10–128 位。')
        if c.execute('SELECT 1 FROM users WHERE phone=? AND id!=?',(phone,t['user_id'])).fetchone():
            raise ValueError('此手机号已被其他账号使用。')
        c.execute('UPDATE users SET name=?,phone=? WHERE id=?',(name,phone,t['user_id']))
        if password:c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),t['user_id']))
        if password or phone!=t['phone']:c.execute('DELETE FROM sessions WHERE user_id=?',(t['user_id'],))
    c.execute('UPDATE teachers SET subject=?,subjects=? WHERE id=?',('、'.join(subjects),json.dumps(subjects,ensure_ascii=False),t['id']))
    return {'ok':True}

def teacher_status(c,user,data):
    t=managed_teacher(c,user,data)
    if t['is_owner'] or t['role']=='admin':
        raise ValueError('管理员兼任老师的账号不能在此停用，请在管理员页面处理。')
    active=data.get('active')
    if type(active) is not bool:raise ValueError('账号状态无效。')
    c.execute('UPDATE users SET active=? WHERE id=?',(int(active),t['user_id']))
    c.execute('DELETE FROM sessions WHERE user_id=?',(t['user_id'],))
    return {'ok':True}
