"""课时簿 — standalone, standard-library application. See README.md."""
import argparse
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import teaching
import profiles
import credit_batches
import accounting
import deletion
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
DB_PATH = os.environ.get('LESSON_DB', str(ROOT / 'data' / 'lessons.sqlite3'))
DEMO = os.environ.get('LESSON_DEMO') == '1'
SECURE = os.environ.get('LESSON_SECURE_COOKIE') == '1'
ORG_NAME = os.environ.get('LESSON_ORG_NAME', 'HELEN’S MATH SECRETS')[:60]

def connect():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return salt + ':' + digest

def phone_value(raw):
    phone = re.sub(r'[\s()\-]', '', str(raw or ''))
    if not re.fullmatch(r'\+?[0-9]{7,15}', phone):
        raise ValueError('请输入完整手机号，可包含国家区号。')
    return phone

def units(raw):
    try:
        n = Decimal(str(raw))
        if not n.is_finite() or n <= 0 or n > 10000 or n * 100 != (n * 100).to_integral_value():
            raise ValueError()
        return int(n * 100)
    except (InvalidOperation, ValueError):
        raise ValueError('课时必须大于 0，最多保留两位小数，且不超过 10000。')

def text_value(raw, label, maximum=100):
    value = str(raw or '').strip()
    if not value or len(value) > maximum:
        raise ValueError(f'{label}不能为空，且不能超过 {maximum} 个字。')
    return value

def initialize():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','parent'))
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, course TEXT NOT NULL,
            parent_id INTEGER NOT NULL REFERENCES users(id),
            balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0)
        );
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id),
            delta INTEGER NOT NULL, kind TEXT NOT NULL, lesson_date TEXT NOT NULL,
            note TEXT NOT NULL, actor_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            request_id TEXT UNIQUE NOT NULL, reversal_of INTEGER UNIQUE REFERENCES ledger(id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attempts (
            key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ledger_student ON ledger(student_id,id);
        ''')
        if DEMO and not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            c.execute('INSERT INTO users(id,phone,name,password,role) VALUES(1,?,?,?,?)', ('0400000000', 'Helen 老师', password_hash('TeacherDemo2026!'), 'admin'))
            c.execute('INSERT INTO users(id,phone,name,password,role) VALUES(2,?,?,?,?)', ('0400000001', '陈同学家长', password_hash('ParentDemo2026!'), 'parent'))
            c.execute('INSERT INTO users(id,phone,name,password,role) VALUES(3,?,?,?,?)', ('0400000002', '其他学生家长', password_hash(secrets.token_urlsafe(24)), 'parent'))
            for sid, name, course, pid, total, used in [(1,'陈一诺','数学 · 一对一',2,2000,650),(2,'陈子墨','数学 · 小班课',2,1200,300),(3,'王星然','数学 · 一对一',3,1000,800),(4,'李沐阳','数学 · 小班课',3,2000,400)]:
                c.execute('INSERT INTO students(id,name,course,parent_id,balance) VALUES(?,?,?,?,?)',(sid,name,course,pid,total-used))
                c.execute('INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,?,?,?,1,?)',(sid,total,'credit','2026-09-01','示例：购入课时',secrets.token_hex(16)))
                c.execute('INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,?,?,?,1,?)',(sid,-used,'lesson','2026-09-20','示例：历史上课汇总',secrets.token_hex(16)))
        c.execute('CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        teaching.schema(c)
        if DEMO and not c.execute("SELECT 1 FROM app_meta WHERE key='teaching_demo_v1'").fetchone():
            demo_teacher=c.execute("SELECT id FROM users WHERE phone='0400000003'").fetchone()
            if not demo_teacher:
                uid=c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'parent')",('0400000003','Emma 老师',password_hash('TutorDemo2026!'))).lastrowid
                tid=c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)',(uid,'数学')).lastrowid
                admin=c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
                student=c.execute('SELECT id FROM students ORDER BY id LIMIT 1').fetchone()
                if admin and student:
                    for offset,hour in [(-1,16),(1,17)]:
                        day=(teaching.now_local().date()+dt.timedelta(days=offset)).isoformat()
                        lid=c.execute('INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,created_by,request_id) VALUES(?,?,?,?,?,?,?,?)',(tid,'数学 · 一对一',f'{day}T{hour}:00',f'{day}T{hour+1}:00',100,'教室 1',admin['id'],secrets.token_hex(16))).lastrowid
                        c.execute('INSERT INTO lesson_students VALUES(?,?)',(lid,student['id']))
            c.execute("INSERT INTO app_meta VALUES('teaching_demo_v1','1')")
        accounting.schema(c,DEMO)
        profiles.schema(c)
        credit_batches.schema(c)
        if DEMO and not c.execute("SELECT 1 FROM app_meta WHERE key='owner_demo_v1'").fetchone():
            if not c.execute("SELECT 1 FROM users WHERE phone='0400000004'").fetchone():
                uid=c.execute("INSERT INTO users(phone,name,password,role) VALUES(?,?,?,'admin')",('0400000004','Amy 管理员',password_hash('AdminDemo2026!'))).lastrowid
                c.execute('INSERT INTO teachers(user_id) VALUES(?)',(uid,))
            c.execute("INSERT INTO app_meta VALUES('owner_demo_v1','1')")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Never log request bodies, passwords, or sessions.
        pass

    def response(self, status, value, cookie=None, content_type='application/json; charset=utf-8'):
        data = json.dumps(value, ensure_ascii=False).encode() if isinstance(value,(dict,list)) else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(data)

    def current(self, c):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie',''))
            token = cookies['session'].value if 'session' in cookies else ''
        except Exception:
            return None
        return c.execute("SELECT u.id,u.name,u.phone,u.password,CASE WHEN o.user_id IS NOT NULL THEN 'owner' WHEN u.role='admin' THEN 'admin' WHEN t.id IS NOT NULL THEN 'teacher' ELSE 'parent' END role,t.id teacher_id,s.csrf,s.token_hash FROM sessions s JOIN users u ON s.user_id=u.id LEFT JOIN teachers t ON t.user_id=u.id LEFT JOIN organization_owners o ON o.user_id=u.id WHERE s.token_hash=? AND s.expires>? AND u.active=1",(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/reconciliation':
            with connect() as c:
                user=self.current(c)
                if not user:return self.response(401,{'error':'请先登录。'})
                try:
                    params=parse_qs(urlsplit(self.path).query)
                    return self.response(200,accounting.reconciliation(c,user,params.get('period',['day'])[0],params.get('date',[teaching.now_local().date().isoformat()])[0]))
                except teaching.AccessError as e:return self.response(403,{'error':str(e)})
                except ValueError as e:return self.response(400,{'error':str(e)})
        if path == '/health':
            with connect() as c:
                c.execute('SELECT 1 FROM users LIMIT 1').fetchone()
            return self.response(200, {'ok': True})
        if path == '/api/state':
            with connect() as c:
                user = self.current(c)
                if not user:
                    return self.response(200, {'user':None,'demo':DEMO,'organization':ORG_NAME})
                condition = '' if user['role'] in ('owner','admin') else ' WHERE s.parent_id=?'
                params = () if user['role'] in ('owner','admin') else (user['id'],)
                if user['role']=='teacher':
                    condition=' WHERE EXISTS (SELECT 1 FROM lesson_students ls JOIN lessons tl ON ls.lesson_id=tl.id WHERE ls.student_id=s.id AND tl.teacher_id=?)'
                    params=(user['teacher_id'],)
                students = [dict(x) for x in c.execute('SELECT s.*,u.name parent_name,u.phone,u.contact_phone FROM students s JOIN users u ON s.parent_id=u.id'+condition+' ORDER BY s.id',params)]
                if user['role'] not in ('owner','admin'):
                    for s in students: s.pop('notes',None)
                credit_batches.enrich(c,students)
                entry_condition=condition
                if user['role']=='teacher':
                    entry_condition=' WHERE EXISTS (SELECT 1 FROM lesson_reports lr JOIN lessons tl ON lr.lesson_id=tl.id WHERE lr.ledger_id=l.id AND tl.teacher_id=?)'
                entries = [dict(x) for x in c.execute('SELECT l.*,s.name student_name,s.course,u.name actor_name, r.id reversed_by FROM ledger l JOIN students s ON l.student_id=s.id JOIN users u ON l.actor_id=u.id LEFT JOIN ledger r ON r.reversal_of=l.id'+entry_condition+' ORDER BY l.id DESC',params)]
                return self.response(200, {'user':{'id':user['id'],'name':user['name'],'role':user['role'],'phone':user['phone'],'teacher_id':user['teacher_id']},'csrf':user['csrf'],'students':students,'entries':entries,'demo':DEMO,'organization':ORG_NAME,**teaching.state_for(c,user),'administrators':accounting.administrators(c,user) if user['role']=='owner' else []})
        files = {'/':'index.html','/app.js':'app.js','/teaching.js':'teaching.js','/accounting.js':'accounting.js','/i18n.js':'i18n.js','/style.css':'style.css','/favicon.svg':'favicon.svg','/logo.jpg':'logo.jpg'}
        if path not in files:
            return self.response(404, {'error':'页面不存在。'})
        name = files[path]
        mime = {'html':'text/html; charset=utf-8','js':'application/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml','jpg':'image/jpeg'}[name.rsplit('.',1)[1]]
        content = (ROOT/'static'/name).read_bytes()
        if name == 'index.html':
            content = content.decode().replace('课时簿 · 每一节，都有记录',html.escape(ORG_NAME)+' · 课时管理').encode()
        return self.response(200,content,content_type=mime)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length <= 0 or length > 1048576:
                return self.response(400, {'error':'请求内容无效。'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError('请求内容无效。')
            # Reject cross-site requests, including login CSRF. No permissive CORS.
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://'+self.headers.get('Host',''), 'https://'+self.headers.get('Host','')):
                return self.response(403, {'error':'请求来源无效。'})
            with connect() as c:
                if self.path == '/api/login':
                    return self.login(c,data)
                user = self.current(c)
                if not user:
                    return self.response(401, {'error':'登录已过期，请重新登录。'})
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),user['csrf']):
                    return self.response(403, {'error':'页面已过期，请刷新后重试。'})
                if self.path == '/api/logout':
                    c.execute('DELETE FROM sessions WHERE token_hash=?',(user['token_hash'],))
                    c.commit()
                    return self.response(200,{'ok':True},'session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'+('; Secure' if SECURE else ''))
                if self.path == '/api/password':
                    old = str(data.get('old',''))
                    if not hmac.compare_digest(password_hash(old,user['password'].split(':')[0]),user['password']):
                        raise ValueError('当前密码不正确。')
                    new = str(data.get('password',''))
                    if not 10 <= len(new) <= 128:
                        raise ValueError('新密码需为 10–128 位。')
                    c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(new),user['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                    c.commit()
                    return self.response(200,{'ok':True})
                if self.path == '/api/profiles/delete':
                    c.execute('BEGIN IMMEDIATE')
                    result=deletion.remove(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path in ('/api/administrators','/api/administrators/edit','/api/administrators/status','/api/accounting/cash'):
                    c.execute('BEGIN IMMEDIATE')
                    if self.path=='/api/administrators':result=accounting.add_administrator(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/administrators/edit':result=accounting.edit_administrator(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/administrators/status':result=accounting.set_active(c,user,data)
                    else:result=accounting.supplement_cash(c,user,data)
                    c.commit()
                    return self.response(200,result)
                if self.path in ('/api/schedule-options','/api/teachers/edit','/api/teachers/status','/api/teachers','/api/lessons','/api/lessons/cancel','/api/reports/draft','/api/reports/complete','/api/reports/edit'):
                    c.execute('BEGIN IMMEDIATE')
                    if self.path=='/api/schedule-options':
                        result=teaching.save_option(c,user,data,text_value)
                    elif self.path=='/api/teachers/edit':
                        result=teaching.edit_teacher(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/teachers/status':
                        result=teaching.teacher_status(c,user,data)
                    elif self.path=='/api/teachers':
                        result=teaching.create_teacher(c,user,data,phone_value,password_hash,text_value)
                    elif self.path=='/api/lessons':
                        result=teaching.save_schedule(c,user,data,units,text_value)
                    elif self.path=='/api/lessons/cancel':
                        result=teaching.cancel_lesson(c,user,data,text_value)
                    else:
                        result=teaching.save_reports(c,user,data,units,self.path.rsplit('/',1)[1])
                    c.commit()
                    return self.response(200,result)
                if user['role'] not in ('owner','admin'):
                    return self.response(403, {'error':'只有老师可以修改课时。'})
                if self.path in ('/api/students/profile','/api/students/guardian','/api/students/course'):
                    c.execute('BEGIN IMMEDIATE')
                    if self.path.endswith('/profile'): result=profiles.update(c,user,data,text_value)
                    elif self.path.endswith('/course'): result=profiles.add_course(c,user,data,text_value)
                    else: result=profiles.guardian(c,user,data,text_value,phone_value,password_hash)
                    c.commit()
                    return self.response(200,result)
                if self.path == '/api/students':
                    return self.add_student(c,user,data)
                if self.path in ('/api/entries','/api/reverse','/api/refunds'):
                    return self.record(c,user,data)
                return self.response(404,{'error':'接口不存在。'})
        except teaching.AccessError as e:
            return self.response(403,{'error':str(e)})
        except (ValueError, TypeError, KeyError) as e:
            return self.response(400,{'error':str(e) or '输入内容无效。'})
        except sqlite3.IntegrityError:
            return self.response(409,{'error':'记录已存在，请刷新后查看。'})
        except Exception:
            return self.response(500,{'error':'暂时无法完成操作，请稍后重试。'})

    def login(self,c,data):
        phone = phone_value(data.get('phone'))
        password = str(data.get('password',''))
        if len(password)>128:
            raise ValueError('手机号或密码不正确。')
        now = time.time()
        keys = ('phone:'+phone, 'ip:'+self.client_address[0])
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM attempts WHERE expires<?',(now,))
        for key in keys:
            attempt = c.execute('SELECT count FROM attempts WHERE key=?',(key,)).fetchone()
            if attempt and attempt['count'] >= (10 if key.startswith('phone:') else 50):
                return self.response(429,{'error':'登录尝试过多，请 15 分钟后重试。'})
        user = c.execute('SELECT * FROM users WHERE phone=?',(phone,)).fetchone()
        expected = user['password'] if user else '00'*16+':'+ '00'*32
        valid = hmac.compare_digest(password_hash(password,expected.split(':')[0]),expected)
        if not user or not valid or not user['active']:
            for key in keys:
                c.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',(key,now+900))
            c.commit()
            return self.response(401,{'error':'手机号或密码不正确。'})
        c.execute('DELETE FROM attempts WHERE key=?',(keys[0],))
        c.execute('DELETE FROM sessions WHERE expires<?',(now,))
        token = secrets.token_urlsafe(32)
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],secrets.token_urlsafe(24),now+43200))
        c.commit()
        return self.response(200,{'ok':True},f'session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200'+('; Secure' if SECURE else ''))

    def add_student(self,c,user,data):
        name = text_value(data.get('name'),'学生姓名',40)
        course = text_value(data.get('course'),'课程名称',80)
        birthday,grade,notes=profiles.fields(data)
        phone = phone_value(data.get('phone'))
        c.execute('BEGIN IMMEDIATE')
        parent = c.execute('SELECT * FROM users WHERE phone=?',(phone,)).fetchone()
        if parent and (parent['role'] != 'parent' or c.execute('SELECT 1 FROM teachers WHERE user_id=?',(parent['id'],)).fetchone()):
            raise ValueError('此手机号是老师账号，请使用家长手机号。')
        if parent:
            pid = parent['id']
        else:
            password = str(data.get('password',''))
            if not 10 <= len(password) <=128:
                raise ValueError('新家长的初始密码需为 10–128 位。')
            pid = c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',(phone,text_value(data.get('parent_name') or name+'家长','家长姓名',40),password_hash(password),'parent')).lastrowid
        profile_id=c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        sid = c.execute('INSERT INTO students(name,course,parent_id,profile_id) VALUES(?,?,?,?)',(name,course,pid,profile_id)).lastrowid
        c.execute('UPDATE students SET birthday=?,grade=?,notes=? WHERE id=?',(birthday,grade,notes,sid))
        c.commit()
        return self.response(201,{'ok':True,'student_id':sid})

    def record(self,c,user,data):
        request_id = str(data.get('request_id',''))
        if not re.fullmatch(r'[A-Za-z0-9-]{16,80}',request_id):
            raise ValueError('操作编号无效，请刷新后重试。')
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM ledger WHERE request_id=?',(request_id,)).fetchone():
            return self.response(200,{'ok':True,'duplicate':True})
        reversal_of = None
        cash=None
        if self.path == '/api/reverse':
            original = c.execute('SELECT * FROM ledger WHERE id=?',(int(data['entry_id']),)).fetchone()
            if not original or original['kind']=='reversal':
                raise ValueError('此记录不能撤销。')
            if c.execute('SELECT 1 FROM ledger WHERE reversal_of=?',(original['id'],)).fetchone():
                raise ValueError('此记录已撤销。')
            sid, delta, kind = original['student_id'], -original['delta'], 'reversal'
            reversal_of = original['id']
            day = teaching.now_local().date().isoformat()
            note = '撤销原因：'+text_value(data.get('note'),'撤销原因',250)
            original_cash=c.execute('SELECT * FROM cash_entries WHERE ledger_id=?',(original['id'],)).fetchone()
            if original_cash:
                cash=(-original_cash['cash_delta'],original_cash['payment_method'],'纠正原记账 #'+str(original['id']))
        else:
            sid = int(data['student_id'])
            kind = 'refund' if self.path=='/api/refunds' else data.get('kind')
            if kind not in ('lesson','credit','refund') or (kind=='refund' and self.path!='/api/refunds'):
                raise ValueError('记录类型无效。')
            delta = (credit_batches.zero_units(data.get('amount'),units)+credit_batches.zero_units(data.get('gift_amount',0),units)) if kind=='credit' else -units(data.get('amount'))
            day = dt.date.fromisoformat(str(data.get('date',''))).isoformat()
            if day > teaching.now_local().date().isoformat():
                raise ValueError('不能登记尚未发生的上课或充值记录。')
            note = str(data.get('note','')).strip()
            if len(note)>300:
                raise ValueError('备注不能超过 300 个字。')
            if kind in ('credit','refund'):
                cents,method,reference=accounting.cash_details(data)
                if kind=='credit' and method=='gift' and credit_batches.zero_units(data.get('amount'),units)>0:
                    raise ValueError('纯赠课请将付费课时填 0，并在赠送课时中填写数量。')
                if kind=='refund':
                    if cents<=0:raise ValueError('实际退款金额必须大于 0。')
                    note='退课退款：'+text_value(data.get('note'),'退款原因',250)
                cash=(cents if kind=='credit' else -cents,method,reference)
        student = c.execute('SELECT * FROM students WHERE id=?',(sid,)).fetchone()
        if not student:
            raise ValueError('学生不存在。')
        if student['balance']+delta<0:
            raise ValueError('剩余课时不足，无法完成此次操作。')
        lid=c.execute('INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id,reversal_of) VALUES(?,?,?,?,?,?,?,?)',(sid,delta,kind,day,note,user['id'],request_id,reversal_of)).lastrowid
        breakdown=credit_batches.apply(c,lid,kind,data,units,original if reversal_of else None)
        if cash:accounting.record_cash(c,lid,*cash,user['id'])
        c.commit()
        return self.response(201,{'ok':True,**breakdown})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--create-admin',action='store_true')
    parser.add_argument('--create-owner',action='store_true')
    parser.add_argument('--promote-owner',action='store_true')
    parser.add_argument('--reset-password',action='store_true')
    args = parser.parse_args()
    initialize()
    if args.promote_owner:
        phone=phone_value(input('升级为老板的现有管理员手机号：'))
        with connect() as c:
            user=c.execute("SELECT id FROM users WHERE phone=? AND role='admin' AND active=1",(phone,)).fetchone()
            if not user:raise SystemExit('未找到有效的管理员账号。')
            c.execute('INSERT OR IGNORE INTO organization_owners VALUES(?)',(user['id'],))
        print('老板权限已开通。')
        return
    if args.reset_password:
        import getpass
        phone = phone_value(input('需重设密码的手机号：'))
        password = getpass.getpass('新密码（至少 10 位）：')
        if not 10<=len(password)<=128:
            raise SystemExit('密码长度需为 10–128 位。')
        with connect() as c:
            user = c.execute('SELECT id FROM users WHERE phone=?',(phone,)).fetchone()
            if not user:
                raise SystemExit('账号不存在。')
            c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(password),user['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        print('密码已重设。')
        return
    if args.create_admin or args.create_owner:
        import getpass
        phone = phone_value(input('老师手机号：'))
        name = text_value(input('老师姓名：'),'姓名',40)
        password = getpass.getpass('密码（至少 10 位）：')
        if not 10<=len(password)<=128:
            raise SystemExit('密码长度需为 10–128 位。')
        with connect() as c:
            uid=c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',(phone,name,password_hash(password),'admin')).lastrowid
            c.execute('INSERT INTO teachers(user_id) VALUES(?)',(uid,))
            if args.create_owner:c.execute('INSERT INTO organization_owners VALUES(?)',(uid,))
        print('老师账号已创建。')
        return
    httpd = ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'课时簿运行中：http://{args.host}:{args.port}',flush=True)
    httpd.serve_forever()

if __name__ == '__main__':
    main()
