"""Persistent recurrence rules and atomic updates of future occurrences."""
import datetime as dt
import hashlib
import json
import uuid


def schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS lesson_series (
        id TEXT PRIMARY KEY, interval_days INTEGER NOT NULL,
        endless INTEGER NOT NULL DEFAULT 0, next_index INTEGER NOT NULL DEFAULT 0,
        stop_index INTEGER, template TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
        version INTEGER NOT NULL DEFAULT 1, error TEXT NOT NULL DEFAULT '')""")
    columns={r['name'] for r in c.execute('PRAGMA table_info(lessons)')}
    if 'series_id' not in columns:
        c.execute('ALTER TABLE lessons ADD COLUMN series_id TEXT REFERENCES lesson_series(id)')
        c.execute('ALTER TABLE lessons ADD COLUMN occurrence_index INTEGER')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS series_occurrence ON lessons(series_id,occurrence_index)')
    # Older repeated lessons used a deterministic request ID for each occurrence.
    if not c.execute("SELECT 1 FROM app_meta WHERE key='series_links_v1'").fetchone():
        rows=list(c.execute('SELECT * FROM lessons WHERE series_id IS NULL'))
        by_key={l['request_id']:l for l in rows}
        for first in rows:
            key=first['request_id']
            if len(key)>40: continue
            members=[(0,first)]+[(i,by_key[h]) for i in range(1,52)
                if (h:=hashlib.sha256((key+':'+str(i)).encode()).hexdigest()) in by_key]
            if len(members)<2: continue
            sid=str(uuid.uuid4())
            c.execute('INSERT INTO lesson_series(id,interval_days,next_index,stop_index,template,created_by) VALUES(?,?,?,?,?,?)',
                (sid,7,max(i for i,_ in members)+1,max(i for i,_ in members)+1,json.dumps(payload(c,first)),first['created_by']))
            c.executemany('UPDATE lessons SET series_id=?,occurrence_index=? WHERE id=?',[(sid,i,l['id']) for i,l in members])
        c.execute("INSERT INTO app_meta VALUES('series_links_v1','1')")


def payload(c,l):
    return {**{k:l[k] for k in ('title','teacher_id','starts_at','ends_at','location','color')},
        'amount':str(l['planned_units']/100),
        'student_ids':[s[0] for s in c.execute('SELECT student_id FROM lesson_students WHERE lesson_id=?',(l['id'],))]}


def occurrence(rule,index):
    item=json.loads(rule['template'])
    offset=dt.timedelta(days=index*rule['interval_days'])
    for k in ('starts_at','ends_at'):
        item[k]=(dt.datetime.fromisoformat(item[k])+offset).strftime('%Y-%m-%dT%H:%M')
    item['request_id']=hashlib.sha256((rule['id']+':'+str(index)).encode()).hexdigest()
    return item


def warnings(c):
    """Conflicts already stored on a series. Reading them does not insert lessons."""
    import teaching
    found = []
    for rule in c.execute("SELECT * FROM lesson_series WHERE error!=''"):
        text = rule['error'] or ''
        day = text[:10] if len(text) >= 10 and text[4] == '-' and text[7] == '-' else ''
        try:
            template = json.loads(rule['template'] or '{}')
        except json.JSONDecodeError:
            template = {}
        teacher = ''
        if template.get('teacher_id'):
            row = c.execute('SELECT u.name FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.id=?', (template['teacher_id'],)).fetchone()
            teacher = teaching.display_person(row['name']) if row else ''
        names = []
        for sid in template.get('student_ids') or []:
            student = c.execute('SELECT name FROM students WHERE id=?', (int(sid),)).fetchone()
            if student:
                names.append(student['name'])
        starts = str(template.get('starts_at') or '')
        found.append({
            'date': day,
            'time': starts[11:16] if len(starts) >= 16 else '',
            'teacher': teacher,
            'students': names,
            'message': text.split('：', 1)[1] if '：' in text else text,
        })
    return found


REAL_2027_START = '2027-01-25'
REAL_2027_END = '2027-01-31'


def template_of(rule):
    try:
        return json.loads(rule['template'] or '{}')
    except (json.JSONDecodeError, TypeError):
        return {}


def series_started(template):
    return str((template or {}).get('starts_at') or '')[:10]


def keeps_real_2027_schedule(template):
    """Helen’s real 2027 timetable starts in the week of 25–31 January 2027."""
    day = series_started(template)
    return bool(day) and REAL_2027_START <= day <= REAL_2027_END


def courses_are_closed(c, template):
    """True when every enrolment on the template is archived, voided, or gone."""
    raw = (template or {}).get('student_ids') or []
    if not raw:
        return False
    for sid in raw:
        try:
            student_id = int(sid)
        except (TypeError, ValueError):
            return False
        row = c.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()
        if not row:
            continue
        voided = int(row['voided'] or 0) if 'voided' in row.keys() else 0
        if not row['archived'] and not voided:
            return False
    return True


def is_stale_series(c, rule):
    """An old 2026 rule whose courses are no longer active. The January 2027 timetable is never stale."""
    template = template_of(rule)
    if keeps_real_2027_schedule(template):
        return False
    started = series_started(template)
    if not started or started >= REAL_2027_START:
        return False
    return courses_are_closed(c, template)


def lesson_is_locked(c, lesson_id):
    """A reported lesson, or one with a ledger entry, is history and must stay."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_reports'").fetchone():
        return False
    return c.execute('SELECT 1 FROM lesson_reports WHERE lesson_id=?', (lesson_id,)).fetchone() is not None


def teacher_name(c, template):
    teacher_id = (template or {}).get('teacher_id')
    if not teacher_id:
        return ''
    row = c.execute('SELECT u.name FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.id=?', (teacher_id,)).fetchone()
    if not row:
        return ''
    import teaching
    return teaching.display_person(row['name'])


def stale_series_report(c, now):
    """Future scheduled lessons on old series whose courses are archived. The January 2027 timetable is omitted."""
    found = []
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_series'").fetchone():
        return found
    for rule in c.execute('SELECT * FROM lesson_series ORDER BY id'):
        if not is_stale_series(c, rule):
            continue
        template = template_of(rule)
        lessons = []
        for lesson in c.execute('''SELECT id, title, starts_at, ends_at, status, teacher_id FROM lessons
            WHERE series_id=? AND status='scheduled' AND starts_at>=? ORDER BY starts_at, id''',
            (rule['id'], now)):
            lessons.append({
                'id': lesson['id'], 'title': lesson['title'], 'starts_at': lesson['starts_at'],
                'ends_at': lesson['ends_at'], 'locked': lesson_is_locked(c, lesson['id']),
            })
        names = []
        for sid in template.get('student_ids') or []:
            try:
                student = c.execute('SELECT name, archived FROM students WHERE id=?', (int(sid),)).fetchone()
            except (TypeError, ValueError):
                continue
            if student:
                names.append(student['name'] + ('（已归档）' if student['archived'] else ''))
        found.append({
            'series_id': rule['id'], 'started': series_started(template),
            'teacher': teacher_name(c, template), 'students': names,
            'endless': rule['endless'], 'lessons': lessons,
        })
    return found


def stop_stale_series(c, now):
    """Delete only future scheduled lessons that have no report and no ledger, then stop the series."""
    removed = 0
    stopped = 0
    for item in stale_series_report(c, now):
        for lesson in item['lessons']:
            if lesson['locked']:
                continue
            c.execute('DELETE FROM lesson_students WHERE lesson_id=?', (lesson['id'],))
            c.execute("DELETE FROM lessons WHERE id=? AND status='scheduled'", (lesson['id'],))
            removed += 1
        remaining = c.execute('SELECT MAX(occurrence_index) n FROM lessons WHERE series_id=?', (item['series_id'],)).fetchone()
        stop = int(remaining['n']) + 1 if remaining and remaining['n'] is not None else 0
        c.execute("UPDATE lesson_series SET endless=0, stop_index=?, error='' WHERE id=?", (stop, item['series_id']))
        stopped += 1
    return {'removed': removed, 'stopped': stopped}


def extend(c,horizon,units,text_value):
    import teaching
    for rule in list(c.execute('SELECT * FROM lesson_series WHERE endless=1')):
        if rule['stop_index'] is not None and rule['next_index']>=rule['stop_index']:continue
        # Saving a later lesson uses that lesson's date as the horizon, so an old
        # endless rule would otherwise be copied into 2027 and 2028. Archived
        # courses from 2026 are not part of the January 2027 timetable.
        template = template_of(rule)
        if is_stale_series(c, rule) or courses_are_closed(c, template):
            continue
        user=c.execute("""SELECT u.id,u.active,CASE WHEN o.user_id IS NOT NULL THEN 'owner'
            WHEN u.role='admin' THEN 'admin' ELSE 'teacher' END role
            FROM users u LEFT JOIN organization_owners o ON o.user_id=u.id WHERE u.id=?""",(rule['created_by'],)).fetchone()
        if not user or not user['active']:
            c.execute('UPDATE lesson_series SET error=? WHERE id=?',('排课账号已停用，请联系老板调整重复课程。',rule['id']))
            continue
        for index in range(rule['next_index'],rule['next_index']+1000):
            if rule['stop_index'] is not None and index>=rule['stop_index']: break
            item=occurrence(rule,index)
            if item['starts_at'][:10]>horizon: break
            c.execute('SAVEPOINT recurrence_occurrence')
            try:
                lid=teaching.save_lesson(c,user,item,units,text_value)['lesson_id']
                c.execute('UPDATE lessons SET series_id=?,occurrence_index=? WHERE id=?',(rule['id'],index,lid))
                c.execute("UPDATE lesson_series SET next_index=?,error='' WHERE id=?",(index+1,rule['id']))
            except (ValueError,teaching.AccessError) as e:
                c.execute('ROLLBACK TO recurrence_occurrence')
                c.execute('UPDATE lesson_series SET error=? WHERE id=?',(item['starts_at'][:10]+'：'+str(e),rule['id']))
                c.execute('RELEASE recurrence_occurrence')
                break
            c.execute('RELEASE recurrence_occurrence')


def update_future(c,user,data,units,text_value):
    import teaching
    if user['role'] not in ('owner','admin'): raise teaching.AccessError('只有老板或管理员可以调整后续课程。')
    first=teaching.allowed_lesson(c,user,data['lesson_id'])
    teaching.check_version(first,data)
    if first['status']!='scheduled': raise ValueError('只能调整尚未完成的课程。')
    if not first['series_id']: raise ValueError('这不是重复课程，请选择仅本次。')
    rule=c.execute('SELECT * FROM lesson_series WHERE id=?',(first['series_id'],)).fetchone()
    try:
        sent_series=int(data.get('series_version',0))
    except (TypeError, ValueError):
        sent_series=-1
    if sent_series!=rule['version']:
        raise ValueError('重复课程已被调整，请刷新后重试。')
    shift={k:teaching.datetime_value(data[k])-dt.datetime.fromisoformat(first[k]) for k in ('starts_at','ends_at')}
    lessons=list(c.execute("SELECT * FROM lessons WHERE series_id=? AND occurrence_index>=? AND status='scheduled' ORDER BY occurrence_index",(rule['id'],first['occurrence_index'])))
    # Exclude the moving set from conflict checks until each new slot is validated.
    c.executemany("UPDATE lessons SET status='cancelled' WHERE id=?",[(l['id'],) for l in lessons])
    for l in lessons:
        c.execute("UPDATE lessons SET status='scheduled' WHERE id=?",(l['id'],))
        item={**data,'lesson_id':l['id'],'version':l['version']}
        for k in shift:item[k]=(dt.datetime.fromisoformat(l[k])+shift[k]).strftime('%Y-%m-%dT%H:%M')
        teaching.save_lesson(c,user,item,units,text_value)
    template=json.loads(rule['template'])
    for k in ('title','teacher_id','amount','location','color','student_ids','course_type_id','subject_id'):
        if k in data:template[k]=data[k]
    for k in shift:template[k]=(dt.datetime.fromisoformat(template[k])+shift[k]).strftime('%Y-%m-%dT%H:%M')
    c.execute("UPDATE lesson_series SET template=?,created_by=?,version=version+1,error='' WHERE id=?",(json.dumps(template),user['id'],rule['id']))
    return {'ok':True,'lesson_id':first['id'],'updated_count':len(lessons)}
