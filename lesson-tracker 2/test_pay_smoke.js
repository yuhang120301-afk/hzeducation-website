const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = __dirname;
const store = {};
function el() {
  return {
    innerHTML: '',
    hidden: false,
    value: '',
    dataset: {},
    onclick: null,
    onsubmit: null,
    onchange: null,
    oninput: null,
    querySelector() { return el(); },
    querySelectorAll() { return []; },
    setAttribute() {},
    addEventListener() {},
    prepend() {},
    remove() {},
    click() {},
    appendChild() {},
    insertAdjacentHTML() {},
  };
}
function $(selector) {
  if (!store[selector]) store[selector] = el();
  return store[selector];
}
const document = {
  querySelector() { return null; },
  querySelectorAll() { return []; },
  getElementById() { return null; },
  createElement() { return el(); },
};
const teacher = {
  teacher_id: 2, name: 'Vincent', active: 1,
  rule: {rule_type: 'percent', percent_bp: 4000, hourly_floor_cents: null},
  rules_in_period: false, lessons: [{
    lesson_id: 1, date: '2026-11-03', starts_at: '2026-11-03T16:00', ends_at: '2026-11-03T17:00',
    minutes: 60, course_type_name: '一对一', subject_name: '数学', pay_cents: 4000, pay_basis: 'percent',
    fee_cents: 10000, unknown_fee_count: 0, top_up_cents: 0, share_bp: 4000, percent_cents: 4000,
    lines: [{student_name: '新学生', course: '数学', is_new: true, fee_known: true, fee_cents: 10000, fee_overridden: false, student_id: 9}],
  }],
  total_minutes: 60, total_fee_cents: 10000, total_pay_cents: 4000, total_top_up_cents: 0, unknown_fee_count: 0,
};
const payData = {
  start: '2026-11-01', end: '2026-11-30', teachers: [teacher],
  rules: [], students: [{profile_id: 1, name: '新学生', archived: 0, helen_original: 0}],
  cost_entries: [], cost_schedules: [],
  profit_share: {percent_bp: 3000, revenue_cents: 10000, cost_cents: 1000, remainder_cents: 9000, share_cents: 2700,
    lines: [{date: '2026-11-03', student_name: '新学生', lesson: '数学', fee_known: true, revenue_cents: 10000, share_cents: 2700}],
    costs: [{date: '2026-11-01', label: '房租', amount_cents: 1000}]},
};
const shareData = {
  start: '2026-11-01', end: '2026-11-30', revenue_cents: 10000, cost_cents: 1000, profit_cents: 9000,
  share_cents: 2700, helen_share_cents: 6300, percent_bp: 3000, lines: payData.profit_share.lines,
  costs: payData.profit_share.costs, roster: [{profile_id: 1, name: '新学生', archived: 0, helen_original: 0}],
};
const financeData = {
  start: '2026-11-01', end: '2026-11-30',
  dashboard: {
    own_revenue_cents: 2000, own_lines: [{date: '2026-11-02', student_name: '原有', lesson: '数学', fee_known: true, revenue_cents: 2000}],
    revenue_cents: 10000, cost_cents: 1000, profit_cents: 9000, vincent_cents: 2700, helen_share_cents: 6300,
    total_cents: 8300, lines: payData.profit_share.lines, costs: payData.profit_share.costs,
  },
};
const context = {
  console, document, $,
  state: {user: {role: 'owner', name: 'Helen'}, teachers: [{id: 2, name: 'Vincent'}], today: '2026-11-25', timezone: 'Australia/Melbourne', students: [], administrators: [], lessons: []},
  view: 'pay',
  api: async (path) => {
    if (String(path).startsWith('pay')) return payData;
    if (String(path).startsWith('share')) return shareData;
    if (String(path).startsWith('finance')) return financeData;
    if (String(path).startsWith('prices')) return {by_type: []};
    if (String(path).startsWith('expenses')) return {month: '2026-11', categories: [], by_category: [], entries: [], monthly: [], total_cents: 0};
    if (String(path).startsWith('reports/monthly')) return {month: '2026-11', money_received_cents: 0, money_refunded_cents: 0, lessons_value_cents: 0, outstanding_units: 0, outstanding_value_cents: 0, teacher_pay_cents: 0, cost_cents: 0, forfeit_units: 0, receivable_cents: 0, exceptions: []};
    if (String(path).startsWith('receivables')) return {rows: [], owed_cents: 0};
    if (String(path).startsWith('reconciliation')) return {start: '2026-11-01', end: '2026-11-30', totals: {receipts_cents: 0, missing_cash_count: 0}, rows: [], by_method: [], by_receiver: [], unhanded: [], arrears: {debts: [], booked_without_credit: []}};
    return {};
  },
  toast() {},
  escapeHTML: (value) => String(value ?? ''),
  userHTML: (value) => String(value ?? ''),
  cashFmt: (cents) => '$' + ((cents || 0) / 100).toFixed(2),
  typeBadge: (value) => String(value || ''),
  refresh: async () => {},
  modal() {},
  openDetail() {},
  fmt: (value) => String(value ?? ''),
  datePlus: (day, n = 0) => {
    const date = new Date(String(day).slice(0, 10) + 'T12:00:00Z');
    date.setUTCDate(date.getUTCDate() + Number(n || 0));
    return date.toISOString().slice(0, 10);
  },
  formatDate: (day) => String(day || ''),
  weekStart: '2026-11-23',
  scheduleStatus: 'all',
  teacherFilter: '',
  requestAnimationFrame: (fn) => fn(),
  addEventListener() {},
  window: {matchMedia: () => ({matches: false})},
  backBar: () => '',
  bindBack() {},
  goBack() {},
  localStorage: {getItem() { return null; }, setItem() {}},
  URL: {createObjectURL() { return ''; }, revokeObjectURL() {}},
  fetch: async () => ({ok: true, blob: async () => ({}), json: async () => ({})}),
  crypto: {randomUUID: () => 'test'},
  setTimeout, clearTimeout,
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'static/calendar.js'), 'utf8'), context, {filename: 'calendar.js'});
vm.runInContext(fs.readFileSync(path.join(root, 'static/pay.js'), 'utf8'), context, {filename: 'pay.js'});
vm.runInContext(fs.readFileSync(path.join(root, 'static/accounting.js'), 'utf8'), context, {filename: 'accounting.js'});

const required = ['paySettings', 'bindPaySettings', 'feeModal', 'loadShareChoice', 'saveShareChoice', 'shareQuery', 'bindShareCalendar', 'paintPay', 'renderPay', 'renderShare', 'renderFinance', 'renderExpenses', 'renderMonth', 'renderReceivable', 'renderAccounting'];
for (const name of required) {
  if (typeof context[name] !== 'function') throw new Error(name + ' is not defined');
}

function html(selector) {
  return store[selector] ? store[selector].innerHTML : '';
}

(async () => {
  context.view = 'pay';
  context.state.user.role = 'owner';
  await context.renderPay();
  const boss = html('#pay-result');
  if (!boss.includes('id="pay-rule-form"')) throw new Error('boss pay is missing the wage rule form');
  if (!boss.includes('id="pay-cost-form"')) throw new Error('boss pay is missing the cost form');
  if (!boss.includes('Vincent')) throw new Error('boss pay is missing the teacher');
  if (boss.includes('paySettings is not defined')) throw new Error('boss pay still names a missing function');

  store['#pay-result'].innerHTML = '';
  context.state.user.role = 'teacher';
  await context.renderPay();
  const teacherPay = html('#pay-result');
  if (teacherPay.includes('id="pay-rule-form"')) throw new Error('teacher pay rendered the boss wage form');
  if (!teacherPay.includes('分红')) throw new Error('teacher pay is missing 分红');
  if (teacherPay.includes('我的学生收入')) throw new Error('teacher pay shows Helen student income');
  if (teacherPay.includes('· 原有学生') || teacherPay.includes('· 新学生')) throw new Error('teacher pay labels whether a student is original');

  context.view = 'share';
  context.state.user.role = 'owner';
  await context.renderShare();
  const share = html('#surface');
  if (share.includes('class="error"') || share.includes('is not defined')) throw new Error('share page failed: ' + share.slice(0, 300));
  if (!share.includes('机构收入') || !share.includes('Vincent 分红')) throw new Error('share page is missing the institution cards');

  context.view = 'finance';
  await context.renderFinance();
  const finance = html('#surface');
  if (finance.includes('is not defined')) throw new Error('finance page failed: ' + finance.slice(0, 300));
  if (!finance.includes('我的学生收入') || !finance.includes('本月我的总收入')) throw new Error('finance page is missing its cards');

  for (const [name, view] of [['renderExpenses', 'expenses'], ['renderMonth', 'month'], ['renderReceivable', 'receivable'], ['renderAccounting', 'accounting']]) {
    context.view = view;
    store['#surface'].innerHTML = '';
    await context[name]();
    const page = html('#surface') + html('#accounting-result');
    if (page.includes('is not defined')) throw new Error(name + ' failed: ' + page.slice(0, 300));
  }

  context.view = 'schedule';
  context.state.user.role = 'owner';
  context.state.today = '2026-11-27';
  context.state.lessons = [
    {id: 11, status: 'scheduled', starts_at: '2026-11-27T17:45', ends_at: '2026-11-27T19:00', teacher_name: 'Helen', title: '数学', students: [{name: 'Edward'}], reports: [{content: '先记着', homework: '', feedback: ''}]},
    {id: 12, status: 'completed', starts_at: '2026-11-27T10:00', ends_at: '2026-11-27T11:00', teacher_name: 'Helen', title: '数学', students: [{name: 'Edward'}], reports: [{content: '已交', homework: '作业', feedback: '好', ledger_id: 4}]},
  ];
  context.renderTimeGrid();
  const monthButton = store['#span-month'];
  if (!monthButton || typeof monthButton.onclick !== 'function') throw new Error('calendar month button was not wired');
  monthButton.onclick();
  const grid = html('#surface');
  if (grid.includes('正在读取月度对账')) throw new Error('month calendar opened the reconciliation page');
  if (!grid.includes('class="month-grid"') || !grid.includes('month-days')) throw new Error('month calendar grid did not render');
  if (!grid.includes(' draft') || !grid.includes('草稿')) throw new Error('month calendar is missing the draft colour');
  if (!grid.includes(' completed')) throw new Error('month calendar is missing the completed colour');

  context.view = 'month';
  store['#surface'].innerHTML = '';
  await context.renderMonth();
  const reconciliation = html('#surface');
  if (reconciliation.includes('正在读取月度对账')) throw new Error('reconciliation stayed on its loading line');
  if (!reconciliation.includes('月度对账')) throw new Error('reconciliation page did not render');
  if (reconciliation.includes('class="month-grid"')) throw new Error('reconciliation rendered the calendar grid');
  console.log('pay smoke ok');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
