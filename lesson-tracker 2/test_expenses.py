"""Operating costs are separate from teacher pay, and a monthly cost is recorded once."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import date
from pathlib import Path

os.environ['LESSON_DB'] = str(Path(tempfile.mkdtemp()) / 'expenses.sqlite3')
os.environ['LESSON_DEMO'] = '0'
os.environ['LESSON_SECURE_COOKIE'] = '0'

import auditlog
import expenses
import finance
import payroll
import server
import teaching


class ExpenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.initialize()

    def setUp(self):
        self.c = server.connect()
        self.c.execute('BEGIN')
        self.n = 0
        uid = self.user('Helen')
        self.owner = {'id': uid, 'role': 'owner'}

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def user(self, name, role='admin'):
        self.n += 1
        phone = f'048{self.n:04d}{uuid.uuid4().int % 10000:04d}'[:15]
        return self.c.execute('INSERT INTO users(phone,name,password,role) VALUES(?,?,?,?)',
            (phone, name, 'x', role)).lastrowid

    def category(self, name):
        return self.c.execute('SELECT id FROM expense_categories WHERE name=?', (name,)).fetchone()['id']

    def test_default_categories_and_a_custom_one(self):
        names = [row['name'] for row in self.c.execute('SELECT name FROM expense_categories ORDER BY builtin DESC, id')]
        self.assertEqual(names[:6], ['房租', '教材打印', '广告', '软件', '设备/文具', '其他'])
        expenses.add_category(self.c, self.owner, {'name': '保险'})
        self.assertTrue(self.c.execute('SELECT 1 FROM expense_categories WHERE name=?', ('保险',)).fetchone())
        with self.assertRaises(ValueError):
            expenses.add_category(self.c, self.owner, {'name': '保险'})
        with self.assertRaises(teaching.AccessError):
            expenses.add_entry(self.c, {'id': self.owner['id'], 'role': 'admin'}, {
                'cost_date': '2026-11-25', 'category_id': self.category('其他'), 'amount': '1.00'})

    def test_entry_can_be_edited_voided_and_undone(self):
        expenses.add_entry(self.c, self.owner, {
            'cost_date': '2026-11-25', 'category_id': self.category('设备/文具'),
            'amount': '120.00', 'note': '白板'})
        row = self.c.execute('SELECT * FROM cost_entries').fetchone()
        self.assertEqual((row['label'], row['note'], row['amount_cents'], row['shared'], row['voided']),
            ('设备/文具', '白板', 12000, 1, 0))
        expenses.edit_entry(self.c, self.owner, {
            'id': row['id'], 'cost_date': '2026-11-26', 'category_id': self.category('其他'),
            'amount': '80.00', 'note': '白板改价'})
        expenses.void_entry(self.c, self.owner, {'id': row['id']})
        voided = self.c.execute('SELECT * FROM cost_entries WHERE id=?', (row['id'],)).fetchone()
        self.assertEqual((voided['amount_cents'], voided['voided'], voided['note']), (8000, 1, '白板改价'))
        audit = self.c.execute("SELECT id, summary FROM audit_log WHERE summary LIKE '作废成本%' ORDER BY id DESC").fetchone()
        self.assertIn('白板改价', audit['summary'])
        self.assertIn('$80.00', audit['summary'])
        auditlog.undo(self.c, self.owner, audit['id'])
        restored = self.c.execute('SELECT voided, amount_cents FROM cost_entries WHERE id=?', (row['id'],)).fetchone()
        self.assertEqual(tuple(restored), (0, 8000))
        with self.assertRaises(ValueError):
            auditlog.undo(self.c, self.owner, audit['id'])
        shown = expenses.page(self.c, self.owner, '2026-11')
        self.assertEqual(shown['total_cents'], 8000)
        self.assertEqual(shown['by_category'], [{'name': '其他', 'amount_cents': 8000}])

    def test_monthly_cost_is_created_once_and_stays_editable(self):
        self.assertEqual(expenses.entry_date(2026, 2, 31), date(2026, 2, 28))
        self.assertEqual(expenses.entry_date(2024, 2, 31), date(2024, 2, 29))
        expenses.add_monthly(self.c, self.owner, {
            'name': '教室房租', 'category_id': self.category('房租'), 'amount': '2000.00',
            'day_of_month': 31, 'start_month': '2026-02', 'end_month': '2026-02'})
        expenses.materialize(self.c)
        rows = self.c.execute('SELECT cost_date, amount_cents, source_month, shared FROM cost_entries').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['cost_date'], rows[0]['amount_cents'], rows[0]['source_month'], rows[0]['shared']),
            ('2026-02-28', 200000, '2026-02', 1))
        entry_id = self.c.execute('SELECT id FROM cost_entries').fetchone()['id']
        expenses.edit_entry(self.c, self.owner, {
            'id': entry_id, 'cost_date': '2026-02-20', 'category_id': self.category('房租'),
            'amount': '50.00', 'note': '本月少收'})
        expenses.materialize(self.c)
        edited = self.c.execute('SELECT cost_date, amount_cents, note FROM cost_entries').fetchone()
        self.assertEqual(tuple(edited), ('2026-02-20', 5000, '本月少收'))
        schedule_id = self.c.execute('SELECT id FROM monthly_costs').fetchone()['id']
        expenses.edit_monthly(self.c, self.owner, {
            'id': schedule_id, 'name': '教室房租', 'category_id': self.category('房租'),
            'amount': '99.00', 'day_of_month': 31, 'start_month': '2026-02', 'end_month': '2026-02'})
        self.assertEqual(self.c.execute('SELECT amount_cents FROM cost_entries').fetchone()[0], 5000)
        expenses.void_entry(self.c, self.owner, {'id': entry_id})
        expenses.materialize(self.c, today=date(2026, 11, 25))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM cost_entries').fetchone()[0], 1)
        self.assertEqual(self.c.execute('SELECT voided FROM cost_entries').fetchone()[0], 1)
        total, details = payroll.costs_for(self.c, date(2026, 2, 1), date(2026, 2, 28))
        self.assertEqual(total, 0)
        self.assertEqual(details, [])

    def test_fixed_cost_stops_at_this_month_and_old_schedules_still_add(self):
        expenses.add_monthly(self.c, self.owner, {
            'name': '软件订阅', 'category_id': self.category('软件'), 'amount': '20.00',
            'day_of_month': 3, 'start_month': '2026-11'})
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM cost_entries WHERE source_month='2026-11'").fetchone()[0], 1)
        expenses.add_monthly(self.c, self.owner, {
            'name': '还没到', 'category_id': self.category('其他'), 'amount': '9.00',
            'day_of_month': 1, 'start_month': '2026-12', 'end_month': '2026-12'})
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM cost_entries WHERE source_month='2026-12'").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            expenses.add_monthly(self.c, self.owner, {
                'name': '倒着', 'category_id': self.category('其他'), 'amount': '1.00',
                'day_of_month': 1, 'start_month': '2026-11', 'end_month': '2026-10'})
        schedule = self.c.execute("SELECT id FROM monthly_costs WHERE name='软件订阅'").fetchone()['id']
        expenses.stop_monthly(self.c, self.owner, {'id': schedule})
        expenses.materialize(self.c, today=date(2026, 12, 15))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM cost_entries WHERE label='软件订阅' AND source_month='2026-12'").fetchone()[0], 0)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM cost_entries WHERE label='还没到' AND source_month='2026-12'").fetchone()[0], 1)
        stopped = self.c.execute('SELECT active, end_month FROM monthly_costs WHERE id=?', (schedule,)).fetchone()
        self.assertEqual(tuple(stopped), (0, '2026-11'))
        self.c.execute('''INSERT INTO cost_schedules(label,amount_cents,cadence,effective_from,effective_to,shared,created_by)
            VALUES('旧的按月分摊',1000,'month','2026-08-01','2026-08-31',1,?)''', (self.owner['id'],))
        expenses.add_monthly(self.c, self.owner, {
            'name': '八月房租', 'category_id': self.category('房租'), 'amount': '20.00',
            'day_of_month': 1, 'start_month': '2026-08', 'end_month': '2026-08'})
        total, details = payroll.costs_for(self.c, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(total, 3000)
        self.assertEqual(sorted(item['kind'] for item in details), ['entry', 'schedule'])

    def test_vincent_share_uses_the_new_expenses_and_not_teacher_pay(self):
        teacher_user = self.user('Vincent')
        teacher = self.c.execute('INSERT INTO teachers(user_id,subject) VALUES(?,?)', (teacher_user, '数学')).lastrowid
        parent = self.user('家长', 'parent')
        profile = self.c.execute('INSERT INTO student_profiles DEFAULT VALUES').lastrowid
        student = self.c.execute('''INSERT INTO students(name,course,parent_id,profile_id,balance,helen_original)
            VALUES('新学生','数学',?,?,100000,0)''', (parent, profile)).lastrowid
        units = 100
        credit = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'credit','2026-05-01','购课',?,?)",
            (student, units, self.owner['id'], uuid.uuid4().hex)).lastrowid
        batch = self.c.execute('''INSERT INTO credit_batches(student_id,ledger_id,purchased,gifted,paid_left,gift_left,credited_on)
            VALUES(?,?,?,0,?,0,'2026-05-01')''', (student, credit, units, units)).lastrowid
        self.c.execute('INSERT INTO cash_entries(ledger_id,cash_delta,payment_method,reference,recorded_by) VALUES(?,?,?,?,?)',
            (credit, 10000, 'bank', '', self.owner['id']))
        day = '2026-05-05'
        lesson = self.c.execute('''INSERT INTO lessons(teacher_id,title,starts_at,ends_at,planned_units,location,status,created_by,request_id)
            VALUES(?,?,?,?,100,'教室','completed',?,?)''',
            (teacher, '数学', day + 'T16:00', day + 'T17:00', self.owner['id'], uuid.uuid4().hex)).lastrowid
        self.c.execute('INSERT INTO lesson_students VALUES(?,?)', (lesson, student))
        ledger = self.c.execute("INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,?,'lesson',?,'上课',?,?)",
            (student, -units, day, self.owner['id'], uuid.uuid4().hex)).lastrowid
        self.c.execute('''INSERT INTO lesson_reports(lesson_id,student_id,amount,content,homework,feedback,ledger_id,updated_by)
            VALUES(?,?,100,'内容','作业','反馈',?,?)''', (lesson, student, ledger, self.owner['id']))
        self.c.execute('INSERT INTO credit_movements(ledger_id,batch_id,paid,gift,voided) VALUES(?,?,?,?,0)',
            (ledger, batch, -units, 0))
        self.c.execute('''INSERT INTO pay_rules(teacher_id,rule_type,percent_bp,effective_from,created_by)
            VALUES(?,?,?,?,?)''', (teacher, 'percent', 4000, '2000-01-01', self.owner['id']))
        self.c.execute('''INSERT INTO partner_share_rules(teacher_id,percent_bp,effective_from,created_by)
            VALUES(?,?,?,?)''', (teacher, 3000, '2000-01-01', self.owner['id']))
        expenses.add_entry(self.c, self.owner, {
            'cost_date': day, 'category_id': self.category('广告'), 'amount': '10.00', 'note': '传单'})
        self.c.execute('''INSERT INTO cost_entries(cost_date,label,amount_cents,note,shared,created_by)
            VALUES(?,'私人开支',5000,'',0,?)''', (day, self.owner['id']))
        report = payroll.report(self.c, self.owner, 'custom', None, '2026-05-01', '2026-05-31')
        partner = report['partner']
        self.assertEqual(partner['percent_bp'], 3000)
        self.assertEqual(partner['revenue_cents'], 10000)
        self.assertEqual(partner['shared_cost_cents'], 5000)
        self.assertEqual(partner['remainder_cents'], 5000)
        self.assertEqual(partner['share_cents'], 1500)
        self.assertEqual(report['teachers'][0]['total_pay_cents'], 4000)
        month = finance.monthly(self.c, self.owner, '2026-05')
        self.assertEqual(month['teacher_pay_cents'], 4000)
        self.assertEqual(month['cost_cents'], 5000)
        self.assertNotEqual(month['cost_cents'], month['teacher_pay_cents'])


class ExpensePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        if not Path('/usr/local/bin/google-chrome').exists():
            raise unittest.SkipTest('chrome is not installed')
        cls.tmp = tempfile.mkdtemp()
        cls.port = '8794'
        env = {**os.environ, 'LESSON_DEMO': '1', 'LESSON_DB': str(Path(cls.tmp) / 'ui.sqlite3'), 'LESSON_SECURE_COOKIE': '0'}
        cls.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('server.py')), '--port', cls.port],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(50):
            import urllib.request
            try:
                urllib.request.urlopen('http://127.0.0.1:%s/health' % cls.port, timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('expense page server did not start')

    @classmethod
    def tearDownClass(cls):
        proc = getattr(cls, 'proc', None)
        if proc:
            proc.terminate()
            proc.communicate(timeout=5)

    def test_boss_records_voids_and_sees_cost_apart_from_pay(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/usr/local/bin/google-chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.goto('http://127.0.0.1:%s/' % self.port)
            page.click('[data-demo=owner]')
            page.wait_for_selector('.sidebar [data-view=expenses]')
            page.click('.sidebar [data-view=expenses]')
            page.wait_for_selector('#expense-form')
            self.assertEqual(page.locator('h1').first.inner_text(), '成本')
            page.select_option('#expense-form select[name=category_id]', label='设备/文具')
            page.fill('#expense-form input[name=amount]', '120.00')
            page.fill('#expense-form input[name=note]', '白板')
            page.click('#expense-form button[type=submit]')
            page.wait_for_selector('article.trow:has-text("白板")')
            self.assertIn('$120.00', page.locator('#surface .sums').inner_text())
            page.locator('article.trow', has_text='白板').locator('button', has_text='作废').click()
            page.wait_for_selector('article.trow:has-text("已作废")')
            page.click('.sidebar [data-view=month]')
            page.wait_for_selector('#surface .sums .card .k')
            labels = page.locator('#surface .sums .card .k').all_inner_texts()
            self.assertIn('老师工资', labels)
            self.assertIn('机构成本', labels)
            self.assertNotIn('成本', labels)
            page.click('.sidebar [data-view=audit]')
            page.wait_for_selector('#audit-list')
            self.assertIn('作废成本', page.locator('#audit-list').inner_text())
            browser.close()


if __name__ == '__main__':
    unittest.main()
