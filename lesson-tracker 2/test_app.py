"""Integration checks for permissions, balances, idempotency and concurrency."""
import concurrent.futures
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

class Client:
    def __init__(self):
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf=''
    def request(self,path,data=None,csrf=True):
        headers={'Content-Type':'application/json'}
        if csrf: headers['X-CSRF-Token']=self.csrf
        req=urllib.request.Request('http://127.0.0.1:8766/api/'+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        try: r=self.opener.open(req)
        except urllib.error.HTTPError as e: r=e
        return r.status,json.loads(r.read())
    def login(self,phone,password):
        status,_=self.request('login',{'phone':phone,'password':password})
        assert status==200
        _,state=self.request('state')
        self.csrf=state['csrf']
        return state

class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        env={**os.environ,'LESSON_DEMO':'1','LESSON_DB':cls.tmp.name+'/test.sqlite3'}
        args=[sys.executable,str(Path(__file__).with_name('server.py')),'--port','8766']
        if os.environ.get('LESSON_TEST_WSGI')=='1':
            args=[sys.executable,'-m','gunicorn','--chdir',str(Path(__file__).resolve().parent),'--bind','127.0.0.1:8766','--threads','4','wsgi:application']
        cls.proc=subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        for _ in range(60):
            try:
                Client().request('state');break
            except OSError: time.sleep(.1)
        else: raise RuntimeError('Test server failed to start')
        cls.admin=Client();cls.admin.login('0400000000','TeacherDemo2026!')
        cls.parent=Client();cls.parent.login('0400000001','ParentDemo2026!')
    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate();cls.proc.communicate(timeout=5);cls.tmp.cleanup()
    def test_owner_only_profile_deletion(self):
        regular=Client();regular.login('0400000004','AdminDemo2026!')
        sid=self.new_student();tid,tutor=self.new_teacher()
        phone='04'+str(uuid.uuid4().int)[:8]
        status,result=self.admin.request('administrators',{'name':'Duplicate Admin','phone':phone,'password':'SafePassword2026!'})
        self.assertEqual(status,200)
        aid=result['admin_id'];duplicate=Client();duplicate.login(phone,'SafePassword2026!')
        for kind,ident in [('student',sid),('teacher',tid),('admin',aid)]:
            data={'kind':kind,'id':ident}
            for client in (regular,tutor,self.parent):
                self.assertEqual(client.request('profiles/delete',data)[0],403)
            self.assertEqual(self.admin.request('profiles/delete',data,csrf=False)[0],403)
        for kind,ident in [('student',sid),('teacher',tid),('admin',aid)]:
            self.assertEqual(self.admin.request('profiles/delete',{'kind':kind,'id':ident})[0],200)
            self.assertEqual(self.admin.request('profiles/delete',{'kind':kind,'id':ident})[0],400)
        self.assertIsNone(tutor.request('state')[1]['user'])
        self.assertIsNone(duplicate.request('state')[1]['user'])
        self.assertIsNotNone(self.parent.request('state')[1]['user'])
        self.assertNotIn(sid,[s['id'] for s in self.admin.request('state')[1]['students']])
        owner=self.admin.request('state')[1]['user']
        self.assertEqual(self.admin.request('profiles/delete',{'kind':'admin','id':owner['id']})[0],400)
        self.assertEqual(self.admin.request('profiles/delete',{'kind':'teacher','id':owner['teacher_id']})[0],400)
        used=self.new_student();self.entry(used,'credit','1')
        self.assertEqual(self.admin.request('profiles/delete',{'kind':'student','id':used})[0],400)
        tid,_=self.new_teacher();scheduled=self.new_student();self.schedule(tid,[scheduled])
        self.assertEqual(self.admin.request('profiles/delete',{'kind':'teacher','id':tid})[0],400)
        self.assertEqual(self.admin.request('profiles/delete',{'kind':'student','id':scheduled})[0],400)

    def test_schedule_options(self):
        payload={'kind':'location','name':'测试教室','active':True}
        self.assertEqual(self.parent.request('schedule-options',payload)[0],403)
        code,created=self.admin.request('schedule-options',payload)
        self.assertEqual(code,200)
        self.assertEqual(self.admin.request('schedule-options',payload)[0],400)
        oid=created['id']
        self.assertEqual(self.admin.request('schedule-options',{**payload,'id':oid,'name':'新教室','active':False})[0],200)
        options=self.admin.request('state')[1]['schedule_options']
        row=next(o for o in options if o['id']==oid)
        self.assertEqual((row['name'],row['active']),('新教室',0))
        self.assertEqual(self.parent.request('state')[1]['schedule_options'],[])
        self.assertEqual(self.admin.request('schedule-options',{**payload,'id':oid,'active':True})[0],200)

    def test_student_profiles_and_separate_course_balances(self):
        sid=self.new_student()
        payload={'student_id':sid,'name':'多科学生','birthday':'2015-04-12','grade':'Year 6','notes':'内部教学备注'}
        self.assertEqual(self.parent.request('students/profile',payload)[0],403)
        self.assertEqual(self.admin.request('students/profile',{**payload,'birthday':'2999-01-01'})[0],400)
        self.assertEqual(self.admin.request('students/profile',payload)[0],200)
        code,result=self.admin.request('students/course',{'student_id':sid,'course':'物理'})
        self.assertEqual(code,200)
        physics=result['student_id']
        self.assertEqual(self.admin.request('students/course',{'student_id':sid,'course':'物理'})[0],400)
        self.assertEqual(self.parent.request('students/course',{'student_id':sid,'course':'化学'})[0],403)
        self.assertEqual(self.entry(sid,'credit','4')[0],201)
        self.assertEqual(self.entry(physics,'credit','2')[0],201)
        self.assertEqual(self.entry(physics,'lesson','3')[0],400)
        self.assertEqual(self.entry(physics,'lesson','0.5')[0],201)
        self.assertEqual(self.balance(sid),400)
        self.assertEqual(self.balance(physics),150)
        tid,tutor=self.new_teacher()
        lid=self.schedule(tid,[physics])[1]['lesson_id']
        self.assertTrue(all('notes' not in x for x in tutor.request('state')[1]['students']))
        self.assertEqual(tutor.request('students/profile',payload)[0],403)
        self.assertEqual(tutor.request('reports/complete',self.report_data(lid,[physics]))[0],200)
        self.assertEqual(self.balance(physics),100)
        self.assertEqual(self.balance(sid),400)
        code,result=self.admin.request('refunds',{'student_id':physics,'amount':'0.5','cash_amount':'10','payment_method':'bank','date':date.today().isoformat(),'note':'测试退款','request_id':str(uuid.uuid4())})
        self.assertEqual(code,201)
        self.assertEqual(self.balance(physics),50)
        self.assertEqual(self.balance(sid),400)
        refund=next(e for e in self.admin.request('state')[1]['entries'] if e['student_id']==physics and e['kind']=='refund')
        self.assertEqual(self.admin.request('reverse',{'entry_id':refund['id'],'note':'测试撤销','request_id':str(uuid.uuid4())})[0],201)
        self.assertEqual(self.balance(physics),100)
        self.assertEqual(self.balance(sid),400)
        self.assertEqual(self.admin.request('students/profile',{**payload,'student_id':physics,'name':'更新姓名','grade':'Year 7'})[0],200)
        rows=self.admin.request('state')[1]['students']
        accounts=[x for x in rows if x['id'] in (sid,physics)]
        self.assertEqual(len({x['profile_id'] for x in accounts}),1)
        self.assertTrue(all(x['name']=='更新姓名' and x['grade']=='Year 7' for x in accounts))
        self.assertTrue(all('notes' not in x for x in self.parent.request('state')[1]['students']))
        state=self.admin.request('state')[1]
        teacher=state['teachers'][0]['id']
        day=(date.today()+timedelta(days=50)).isoformat()
        lesson={'title':'物理','teacher_id':teacher,'starts_at':day+'T09:00','ends_at':day+'T10:00','amount':'1','student_ids':[sid,physics],'request_id':str(uuid.uuid4())}
        self.assertEqual(self.admin.request('lessons',lesson)[0],400)
        lesson.update(student_ids=[sid],request_id=str(uuid.uuid4()))
        self.assertEqual(self.admin.request('lessons',lesson)[0],200)
        lesson.update(student_ids=[physics],teacher_id=state['teachers'][1]['id'],request_id=str(uuid.uuid4()))
        self.assertEqual(self.admin.request('lessons',lesson)[0],400)

    def test_guardian_account_edit_and_password_reset(self):
        phone='0498765432'
        code,result=self.admin.request('students',{'name':'账号测试','course':'物理','phone':phone,'password':'OriginalPass2026!','parent_name':'测试家长'})
        self.assertEqual(code,201)
        sid=result['student_id']
        guardian=Client();guardian.login(phone,'OriginalPass2026!')
        payload={'student_id':sid,'parent_name':'家长新姓名','phone':'0498765431','contact_phone':'0498765430','password':'UpdatedPass2026!'}
        self.assertEqual(guardian.request('students/guardian',payload)[0],403)
        self.assertEqual(self.admin.request('students/guardian',{**payload,'phone':'0400000000'})[0],400)
        self.assertEqual(self.admin.request('students/guardian',payload)[0],200)
        self.assertIsNone(guardian.request('state')[1]['user'])
        after=guardian.login(payload['phone'],payload['password'])
        account=next(s for s in after['students'] if s['id']==sid)
        self.assertEqual(account['parent_name'],payload['parent_name'])
        self.assertEqual(account['contact_phone'],payload['contact_phone'])
        self.assertNotIn('password',account)
        self.assertEqual(self.admin.request('students/guardian',{**payload,'password':''})[0],200)
        guardian.login(payload['phone'],payload['password'])

    def test_edit_administrator_permissions_and_login(self):
        code,result=self.admin.request('administrators',{'name':'编辑测试','phone':'0491111111','password':'InitialAdmin2026!'})
        self.assertEqual(code,200)
        uid=result['admin_id']
        admin=Client();before=admin.login('0491111111','InitialAdmin2026!')
        payload={'admin_id':uid,'name':'新管理员姓名','phone':'0491111112','password':''}
        self.assertEqual(admin.request('administrators/edit',payload)[0],403)
        self.assertEqual(self.parent.request('administrators/edit',payload)[0],403)
        self.assertEqual(self.admin.request('administrators/edit',{**payload,'admin_id':1})[0],400)
        self.assertEqual(self.admin.request('administrators/edit',{**payload,'phone':'0400000001'})[0],400)
        self.assertEqual(self.admin.request('administrators/edit',{**payload,'password':'short'})[0],400)
        self.assertEqual(self.admin.request('administrators/edit',payload)[0],200)
        self.assertIsNone(admin.request('state')[1]['user'])
        after=admin.login('0491111112','InitialAdmin2026!')
        self.assertEqual(after['user']['name'],payload['name'])
        self.assertEqual(after['user']['teacher_id'],before['user']['teacher_id'])
        self.assertEqual(self.admin.request('administrators/edit',{**payload,'password':'ResetAdmin2026!'})[0],200)
        self.assertIsNone(admin.request('state')[1]['user'])
        admin.login('0491111112','ResetAdmin2026!')
        self.assertEqual(self.admin.request('administrators/status',{'admin_id':uid,'active':False})[0],200)
        self.assertEqual(self.admin.request('administrators/edit',{**payload,'password':''})[0],200)
        self.assertEqual(admin.request('login',{'phone':payload['phone'],'password':'ResetAdmin2026!'})[0],401)

    def test_teacher_edit_subjects_and_departure(self):
        tid,tutor=self.new_teacher()
        current=tutor.request('state')[1]['user']
        payload={'teacher_id':tid,'name':'多科老师','phone':current['phone'],'subjects':['物理','化学'],'password':''}
        self.assertEqual(tutor.request('teachers/edit',payload)[0],403)
        self.assertEqual(self.parent.request('teachers/status',{'teacher_id':tid,'active':False})[0],403)
        self.assertEqual(self.admin.request('teachers/edit',{**payload,'subjects':[]})[0],400)
        self.assertEqual(self.admin.request('teachers/edit',payload)[0],200)
        row=next(t for t in self.admin.request('state')[1]['teachers'] if t['id']==tid)
        self.assertEqual(row['subjects'],['物理','化学'])
        sid=self.new_student();lid=self.schedule(tid,[sid])[1]['lesson_id']
        self.assertEqual(self.admin.request('teachers/status',{'teacher_id':tid,'active':False})[0],200)
        self.assertIsNone(tutor.request('state')[1]['user'])
        self.assertEqual(self.schedule(tid,[self.new_student()])[0],400)
        self.assertEqual(self.lesson(lid)['teacher_id'],tid)
        row=next(t for t in self.admin.request('state')[1]['teachers'] if t['id']==tid)
        self.assertEqual(row['active'],0)
        self.assertEqual(self.admin.request('teachers/status',{'teacher_id':tid,'active':True})[0],200)
        self.assertEqual(self.admin.request('teachers/edit',{**payload,'phone':'0492222222','password':'NewTeacher2026!'})[0],200)
        tutor.login('0492222222','NewTeacher2026!')
        owner_teacher=next(t for t in self.admin.request('state')[1]['teachers'] if t['account_role']=='owner')
        self.assertEqual(self.admin.request('teachers/status',{'teacher_id':owner_teacher['id'],'active':False})[0],400)
        self.assertEqual(self.admin.request('teachers/edit',{'teacher_id':owner_teacher['id'],'subjects':['数学','物理']})[0],200)
        self.assertEqual(self.admin.request('teachers/edit',{**payload,'teacher_id':owner_teacher['id']})[0],400)

    def gift_credit(self,sid,paid,gift,key=None):
        return self.admin.request('entries',{'student_id':sid,'kind':'credit','amount':paid,'gift_amount':gift,'cash_amount':'100' if float(paid)>0 else '0','payment_method':'bank' if float(paid)>0 else 'gift','date':date.today().isoformat(),'request_id':key or str(uuid.uuid4())})
    def credit_account(self,sid):
        return next(s for s in self.admin.request('state')[1]['students'] if s['id']==sid)
    def test_gifts_paid_first_across_batches_and_scheduled_lessons(self):
        sid=self.new_student();key=str(uuid.uuid4())
        self.assertEqual(self.gift_credit(sid,'2','1',key)[0],201)
        self.assertEqual(self.gift_credit(sid,'2','1',key)[0],200)
        self.gift_credit(sid,'1','2')
        self.assertEqual(len(self.credit_account(sid)['credit_batches']),2)
        self.assertEqual(self.entry(sid,'lesson','2.5')[0],201)
        s=self.credit_account(sid)
        self.assertEqual((s['paid_balance'],s['gift_balance']),(50,300))
        self.assertEqual(self.entry(sid,'lesson','1')[0],201)
        s=self.credit_account(sid)
        self.assertEqual((s['paid_balance'],s['gift_balance']),(0,250))
        tid,tutor=self.new_teacher();lid=self.schedule(tid,[sid])[1]['lesson_id']
        self.assertEqual(tutor.request('reports/complete',self.report_data(lid,[sid]))[0],200)
        s=self.credit_account(sid)
        self.assertEqual((s['paid_balance'],s['gift_balance'],s['balance']),(0,200,200))
        self.assertEqual(self.entry(sid,'lesson','2.01')[0],400)
        self.assertEqual(self.balance(sid),200)
    def test_gift_refund_voids_only_selected_batch_and_reversal(self):
        sid=self.new_student();self.gift_credit(sid,'10','2');self.gift_credit(sid,'5','1')
        self.entry(sid,'lesson','3')
        batch=self.credit_account(sid)['credit_batches'][0]
        key=str(uuid.uuid4())
        payload={'student_id':sid,'batch_id':batch['id'],'amount':'2','cash_amount':'20','payment_method':'bank','date':date.today().isoformat(),'note':'部分退款','request_id':key}
        code,result=self.admin.request('refunds',payload)
        self.assertEqual(code,201);self.assertEqual(result['gift_void'],200)
        self.assertEqual(self.admin.request('refunds',payload)[0],200)
        s=self.credit_account(sid)
        self.assertEqual((s['paid_balance'],s['gift_balance'],s['balance']),(1000,100,1100))
        self.assertEqual(s['credit_batches'][1]['gift_left'],100)
        refund=next(e for e in self.admin.request('state')[1]['entries'] if e['student_id']==sid and e['kind']=='refund')
        self.assertEqual((refund['paid_delta'],refund['gift_delta'],refund['delta']),(-200,-200,-400))
        self.assertEqual(self.admin.request('reverse',{'entry_id':refund['id'],'note':'纠错','request_id':str(uuid.uuid4())})[0],201)
        s=self.credit_account(sid)
        self.assertEqual((s['paid_balance'],s['gift_balance']),(1200,300))
        report=self.admin.request('reconciliation?period=day&date='+date.today().isoformat())[1]
        self.assertTrue(report['balance_check'])
        self.assertGreaterEqual(report['totals']['gift_void_units'],200)
    def test_gift_only_not_refundable_and_batch_isolation(self):
        sid=self.new_student();self.assertEqual(self.gift_credit(sid,'0','2')[0],201)
        other=self.new_student();self.gift_credit(other,'5','1')
        batch=self.credit_account(other)['credit_batches'][0]
        payload={'student_id':sid,'batch_id':batch['id'],'amount':'1','cash_amount':'10','payment_method':'bank','date':date.today().isoformat(),'note':'退款','request_id':str(uuid.uuid4())}
        self.assertEqual(self.admin.request('refunds',payload)[0],400)
        self.assertEqual(self.admin.request('refunds',{**payload,'batch_id':self.credit_account(sid)['credit_batches'][0]['id']})[0],400)
        self.assertEqual(self.gift_credit(sid,'0','0')[0],400)
        self.assertEqual(self.gift_credit(sid,'1','-1')[0],400)
        self.assertEqual(self.balance(sid),200)
        self.assertEqual(self.balance(other),600)
    def test_gift_concurrent_consumption_no_overdraw(self):
        sid=self.new_student();self.gift_credit(sid,'0.5','0.5')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            codes=list(pool.map(lambda _:self.entry(sid,'lesson','0.75')[0],range(2)))
        self.assertEqual(sorted(codes),[201,400])
        s=self.credit_account(sid)
        self.assertEqual((s['paid_balance'],s['gift_balance'],s['balance']),(0,25,25))

    def new_student(self):
        status,result=self.admin.request('students',{'name':'测试学生','course':'测试课程','phone':'0400000001'})
        self.assertEqual(status,201)
        return result['student_id']
    def entry(self,sid,kind,amount,key=None):
        return self.admin.request('entries',{'student_id':sid,'kind':kind,'amount':amount,'date':date.today().isoformat(),'note':'集成测试','cash_amount':'100.00','payment_method':'bank','request_id':key or str(uuid.uuid4())})
    def balance(self,sid):
        return next(s['balance'] for s in self.admin.request('state')[1]['students'] if s['id']==sid)
    def test_parent_isolation_and_write_denied(self):
        state=self.parent.request('state')[1]
        self.assertTrue(all(s['parent_id']==2 for s in state['students']))
        allowed={s['id'] for s in state['students']}
        self.assertTrue(all(e['student_id'] in allowed for e in state['entries']))
        self.assertEqual(self.parent.request('entries',{'student_id':3})[0],403)
        self.assertEqual(self.parent.request('students',{})[0],403)
        self.assertEqual(self.parent.request('reverse',{})[0],403)
        self.assertEqual(Client().request('entries',{})[0],401)
    def test_decimal_and_duplicate_request(self):
        sid=self.new_student();self.entry(sid,'credit','2.25')
        key=str(uuid.uuid4())
        self.assertEqual(self.entry(sid,'lesson','0.5',key)[0],201)
        self.assertEqual(self.entry(sid,'lesson','0.5',key)[0],200)
        self.assertEqual(self.balance(sid),175)
        self.assertEqual(self.entry(sid,'lesson','2')[0],400)
        self.assertEqual(self.balance(sid),175)
        self.assertEqual(self.entry(sid,'credit','NaN')[0],400)
        self.assertEqual(self.entry(sid,'credit','0.001')[0],400)
    def test_concurrent_deductions_cannot_overdraw(self):
        sid=self.new_student();self.entry(sid,'credit','1')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.entry(sid,'lesson','0.75')[0],range(2)))
        self.assertEqual(sorted(results),[201,400]);self.assertEqual(self.balance(sid),25)
    def test_reversal_is_once_and_auditable(self):
        sid=self.new_student();self.entry(sid,'credit','2');self.entry(sid,'lesson','.5')
        entry=next(e for e in self.admin.request('state')[1]['entries'] if e['student_id']==sid and e['kind']=='lesson')
        data={'entry_id':entry['id'],'note':'重复记录','request_id':str(uuid.uuid4())}
        self.assertEqual(self.admin.request('reverse',data)[0],201)
        data['request_id']=str(uuid.uuid4())
        self.assertEqual(self.admin.request('reverse',data)[0],400)
        self.assertEqual(self.balance(sid),200)
        entries=[e for e in self.admin.request('state')[1]['entries'] if e['student_id']==sid]
        self.assertEqual(len(entries),3)
        self.assertEqual(sum(e['delta'] for e in entries),200)
    def test_csrf_is_enforced(self):
        self.assertEqual(self.admin.request('students',{},csrf=False)[0],403)
    def test_parent_sees_updated_half_lesson(self):
        sid=self.new_student()
        self.entry(sid,'credit','10')
        self.assertEqual(self.entry(sid,'lesson','0.5')[0],201)
        state=self.parent.request('state')[1]
        self.assertEqual(next(s['balance'] for s in state['students'] if s['id']==sid),950)
        self.assertTrue(any(e['student_id']==sid and e['delta']==-50 for e in state['entries']))
    def test_password_change_invalidates_sessions(self):
        phone='0400000099'
        self.assertEqual(self.admin.request('students',{'name':'密码测试','course':'数学','phone':phone,'password':'InitialPass123!'})[0],201)
        client=Client();client.login(phone,'InitialPass123!')
        self.assertEqual(client.request('password',{'old':'InitialPass123!','password':'ChangedPass456!'})[0],200)
        self.assertIsNone(client.request('state')[1]['user'])
        self.assertEqual(client.request('login',{'phone':phone,'password':'InitialPass123!'})[0],401)
        client.login(phone,'ChangedPass456!')

    def new_teacher(self):
        phone='04'+str(uuid.uuid4().int)[:8]
        status,r=self.admin.request('teachers',{'name':'独立老师','subject':'数学','phone':phone,'password':'TutorPassword123!'})
        self.assertEqual(status,200,r)
        client=Client();client.login(phone,'TutorPassword123!')
        return r['teacher_id'],client

    def schedule(self,tid,students,day='2026-01-05',start='10:00',end='11:00',**extra):
        payload={'teacher_id':tid,'student_ids':students,'title':'分数课程','starts_at':day+'T'+start,'ends_at':day+'T'+end,'amount':'1','location':'教室 1','request_id':str(uuid.uuid4()),**extra}
        return self.admin.request('lessons',payload)

    def lesson(self,lid,client=None):
        return next(l for l in (client or self.admin).request('state')[1]['lessons'] if l['id']==lid)

    def report_data(self,lid,students,amount='.5',client=None):
        return {'lesson_id':lid,'version':self.lesson(lid,client)['version'],'reports':[{'student_id':sid,'amount':amount,'content':'通分与约分','homework':'练习册第 12 页','feedback':f'学生 {sid} 的私人反馈'} for sid in students]}

    def test_schedule_conflicts_and_cancel_no_debit(self):
        tid,_=self.new_teacher();tid2,_=self.new_teacher();s1=self.new_student();s2=self.new_student()
        status,r=self.schedule(tid,[s1]);self.assertEqual(status,200,r);lid=r['lesson_id']
        self.assertEqual(self.balance(s1),0)
        self.assertEqual(self.schedule(tid,[s2],start='10:30',end='11:30')[0],400)
        self.assertEqual(self.schedule(tid2,[s1],start='10:30',end='11:30')[0],400)
        self.assertEqual(self.schedule(tid,[s2],start='11:00',end='12:00')[0],200)
        lesson=self.lesson(lid)
        self.assertEqual(self.admin.request('lessons/cancel',{'lesson_id':lid,'version':lesson['version'],'reason':'学生请假'})[0],200)
        self.assertEqual(self.schedule(tid2,[s1])[0],200)
        self.assertEqual(self.balance(s1),0)

    def test_teacher_scope_enforced_server_side(self):
        tid,t1=self.new_teacher();tid2,t2=self.new_teacher();s1=self.new_student();s2=self.new_student()
        lid=self.schedule(tid,[s1])[1]['lesson_id'];other=self.schedule(tid2,[s2])[1]['lesson_id']
        state=t1.request('state')[1]
        self.assertEqual(state['user']['role'],'teacher')
        self.assertEqual([x['id'] for x in state['students']],[s1])
        self.assertEqual([x['id'] for x in state['lessons']],[lid])
        self.assertEqual(t1.request('reports/draft',self.report_data(other,[s2]))[0],403)
        self.assertEqual(t1.request('lessons',{})[0],403)
        self.assertEqual(t1.request('teachers',{})[0],403)
        self.assertEqual(t1.request('entries',{})[0],403)
        self.assertEqual(self.parent.request('reports/complete',self.report_data(lid,[s1]))[0],403)

    def test_group_draft_completion_parent_privacy_and_edit(self):
        tid,teacher=self.new_teacher();s1=self.new_student()
        status,new=self.admin.request('students',{'name':'另一家学生','course':'数学','phone':'0400000002'})
        self.assertEqual(status,201);s2=new['student_id']
        for sid in [s1,s2]:self.entry(sid,'credit','4')
        lid=self.schedule(tid,[s1,s2])[1]['lesson_id']
        draft=self.report_data(lid,[s1,s2])
        self.assertEqual(teacher.request('reports/draft',draft)[0],200)
        parent_lesson=self.lesson(lid,self.parent)
        self.assertEqual(parent_lesson['reports'],[])
        self.assertEqual([s['id'] for s in parent_lesson['students']],[s1])
        self.assertEqual(self.balance(s1),400)
        data=self.report_data(lid,[s1,s2]);data['reports'][1]['amount']='1.25'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:teacher.request('reports/complete',data)[0],range(2)))
        self.assertEqual(results,[200,200]);self.assertEqual(self.balance(s1),350);self.assertEqual(self.balance(s2),275)
        parent_lesson=self.lesson(lid,self.parent)
        self.assertEqual([r['student_id'] for r in parent_lesson['reports']],[s1])
        self.assertEqual(parent_lesson['reports'][0]['homework'],'练习册第 12 页')
        edited=self.report_data(lid,[s1,s2]);edited['reports'][1]['amount']='1.25';edited['reports'][0]['feedback']='订正后掌握良好'
        self.assertEqual(teacher.request('reports/edit',edited)[0],200)
        self.assertEqual(self.balance(s1),350)
        self.assertEqual(self.lesson(lid,self.parent)['reports'][0]['feedback'],'订正后掌握良好')
        edited['version']=self.lesson(lid)['version'];edited['reports'][0]['amount']='2'
        self.assertEqual(teacher.request('reports/edit',edited)[0],400)
        self.assertEqual(self.balance(s1),350)

    def test_group_insufficient_balance_rolls_back_all(self):
        tid,t=self.new_teacher();s1=self.new_student();s2=self.new_student();self.entry(s1,'credit','3')
        lid=self.schedule(tid,[s1,s2])[1]['lesson_id']
        self.assertEqual(t.request('reports/complete',self.report_data(lid,[s1,s2]))[0],400)
        self.assertEqual(self.balance(s1),300);self.assertEqual(self.balance(s2),0)
        self.assertEqual(self.lesson(lid)['status'],'scheduled')
        self.assertEqual(self.lesson(lid)['reports'],[])

    def test_future_completion_and_stale_updates_rejected(self):
        tid,t=self.new_teacher();sid=self.new_student();self.entry(sid,'credit','2')
        day=(date.today()+timedelta(days=30)).isoformat()
        lid=self.schedule(tid,[sid],day=day)[1]['lesson_id']
        data=self.report_data(lid,[sid])
        self.assertEqual(t.request('reports/complete',data)[0],400)
        self.assertEqual(t.request('reports/draft',data)[0],200)
        self.assertEqual(t.request('reports/draft',data)[0],400)
        self.assertEqual(self.balance(sid),200)

    def test_report_reversal_preserves_feedback(self):
        tid,t=self.new_teacher();sid=self.new_student();self.entry(sid,'credit','2')
        lid=self.schedule(tid,[sid])[1]['lesson_id'];data=self.report_data(lid,[sid])
        self.assertEqual(t.request('reports/complete',data)[0],200)
        report=self.lesson(lid)['reports'][0]
        self.assertEqual(self.admin.request('reverse',{'entry_id':report['ledger_id'],'note':'课时扣除有误','request_id':str(uuid.uuid4())})[0],201)
        self.assertEqual(self.balance(sid),200)
        self.assertIsNotNone(self.lesson(lid,self.parent)['reports'][0]['reversed_by'])
        self.assertEqual(t.request('reports/complete',data)[0],200)
        self.assertEqual(self.balance(sid),200)

    def test_owner_permissions_and_admin_disable(self):
        regular=Client();regular.login('0400000004','AdminDemo2026!')
        self.assertEqual(regular.request('reconciliation?period=day&date='+date.today().isoformat())[0],403)
        self.assertEqual(regular.request('administrators',{})[0],403)
        status,result=self.admin.request('administrators',{'name':'Test Admin','phone':'0499999999','password':'SafePassword2026!','role':'owner'})
        self.assertEqual(status,200)
        new=Client();state=new.login('0499999999','SafePassword2026!')
        self.assertEqual(state['user']['role'],'admin')
        self.assertEqual(self.admin.request('administrators/status',{'admin_id':result['admin_id'],'active':False})[0],200)
        self.assertEqual(new.request('state')[1].get('user'),None)

    def test_refund_exact_money_and_duplicate(self):
        sid=self.new_student();self.entry(sid,'credit','3.5')
        query='reconciliation?period=day&date='+date.today().isoformat()
        before=self.admin.request(query)[1]['totals']
        data={'student_id':sid,'amount':'1.5','cash_amount':'45.25','payment_method':'bank','date':date.today().isoformat(),'note':'Student withdrawal','request_id':str(uuid.uuid4())}
        self.assertEqual(self.parent.request('refunds',data)[0],403)
        self.assertEqual(self.admin.request('refunds',data)[0],201)
        self.assertEqual(self.admin.request('refunds',data)[0],200)
        self.assertEqual(self.balance(sid),200)
        after=self.admin.request(query)[1]
        self.assertEqual(after['totals']['refunds_cents']-before['refunds_cents'],4525)
        self.assertEqual(after['totals']['refund_units']-before['refund_units'],150)
        self.assertTrue(after['balance_check'])
        data.update(amount='2.5',request_id=str(uuid.uuid4()))
        self.assertEqual(self.admin.request('refunds',data)[0],400)
        self.assertEqual(self.balance(sid),200)

    def test_recurring_schedule_dates_retry_and_no_charge(self):
        for mode,days in [('weekly',7),('fortnightly',14)]:
            tid,_=self.new_teacher();sid=self.new_student();key=str(uuid.uuid4())
            status,result=self.schedule(tid,[sid],day='2026-09-28',repeat=mode,repeat_count='3',request_id=key)
            self.assertEqual(status,200,result)
            self.assertEqual(len(result['lesson_ids']),3)
            for i,lid in enumerate(result['lesson_ids']):
                lesson=self.lesson(lid)
                self.assertEqual(lesson['starts_at'],(date(2026,9,28)+timedelta(days=i*days)).isoformat()+'T10:00')
            self.assertEqual(self.balance(sid),0)
            self.assertTrue(self.schedule(tid,[sid],day='2026-09-28',repeat=mode,repeat_count='3',request_id=key)[1]['duplicate'])
            self.assertEqual(len([l for l in self.admin.request('state')[1]['lessons'] if l['teacher_id']==tid]),3)

    def test_recurring_conflict_rolls_back_and_bounds(self):
        tid,_=self.new_teacher();sid=self.new_student()
        self.schedule(tid,[sid],day='2026-10-12')
        status,result=self.schedule(tid,[sid],day='2026-09-28',repeat='weekly',repeat_count='4')
        self.assertEqual(status,400,result)
        self.assertIn('2026-10-12',result['error'])
        self.assertEqual(len([l for l in self.admin.request('state')[1]['lessons'] if l['teacher_id']==tid]),1)
        for count in ['0','1','53','2.5']:
            self.assertEqual(self.schedule(tid,[sid],repeat='weekly',repeat_count=count)[0],400)

if __name__=='__main__':unittest.main(verbosity=2)
