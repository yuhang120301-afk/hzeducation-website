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


def extend(c,horizon,units,text_value):
    import teaching
    for rule in list(c.execute('SELECT * FROM lesson_series WHERE endless=1')):
        if rule['stop_index'] is not None and rule['next_index']>=rule['stop_index']:continue
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
    if int(data.get('series_version',0))!=rule['version']:
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
    for k in ('title','teacher_id','amount','location','color','student_ids'):
        if k in data:template[k]=data[k]
    for k in shift:template[k]=(dt.datetime.fromisoformat(template[k])+shift[k]).strftime('%Y-%m-%dT%H:%M')
    c.execute("UPDATE lesson_series SET template=?,created_by=?,version=version+1,error='' WHERE id=?",(json.dumps(template),user['id'],rule['id']))
    return {'ok':True,'lesson_id':first['id'],'updated_count':len(lessons)}
