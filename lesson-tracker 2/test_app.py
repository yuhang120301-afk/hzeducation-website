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
