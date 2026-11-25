"""Bulk approve uses the same write as approving one receipt."""
import uuid

import pytest

import accounting
import credit_batches
import server
import teaching
import vouchers


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('LESSON_DEMO', '0')
    monkeypatch.setattr(server, 'DB_PATH', str(tmp_path / 'bulk.sqlite3'))
    server.initialize()


def _people(c):
    owner_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0421000001','Helen','x','admin')").lastrowid
    parent_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0421000002','家长','x','parent')").lastrowid
    teacher_id = c.execute("INSERT INTO users(phone,name,password,role) VALUES('0421000003','老师','x','parent')").lastrowid
    return {'id': owner_id, 'role': 'owner'}, parent_id, teacher_id


def _credit(c, actor_id, parent_id, sid=None, name='陈一诺'):
    if sid is None:
        sid = c.execute("INSERT INTO students(name,course,parent_id,balance) VALUES(?,?,?,0)", (name, '数学', parent_id)).lastrowid
    lid = c.execute(
        "INSERT INTO ledger(student_id,delta,kind,lesson_date,note,actor_id,request_id) VALUES(?,0,'credit',?,?,?,?)",
        (sid, '2026-11-01', '充值数学包', actor_id, uuid.uuid4().hex)).lastrowid
    credit_batches.apply(c, lid, 'credit', {'amount': '2', 'gift_amount': '1', 'pack_label': '数学 20+1'}, server.units)
    accounting.record_cash(c, lid, 170000, 'bank', '', actor_id)
    vid = vouchers.issue_ledger(c, {'id': actor_id, 'role': 'owner'}, lid)
    return vid, sid


def _effect(c, vid):
    row = dict(c.execute('SELECT * FROM vouchers WHERE id=?', (vid,)).fetchone())
    events = []
    for event in c.execute('SELECT actor_id, action, detail FROM voucher_events WHERE voucher_id=? ORDER BY id', (vid,)):
        detail = '<number>' if event['detail'] == row['number'] else event['detail']
        events.append((event['actor_id'], event['action'], detail))
    kept = {key: row[key] for key in row if key not in ('id', 'number', 'ledger_id', 'created_at', 'approved_at')}
    return kept, events, row['approved_at']


def test_bulk_approves_several_pending(db):
    with server.connect() as c:
        owner, parent_id, _teacher_id = _people(c)
        ids = [_credit(c, owner['id'], parent_id, name=name)[0] for name in ('甲', '乙', '丙')]
        result = vouchers.approve_many(c, owner, ids)
        assert result == {'ok': True, 'approved': 3, 'approved_ids': ids, 'skipped': []}
        for vid in ids:
            row = c.execute('SELECT status, approved_by, approved_at, number FROM vouchers WHERE id=?', (vid,)).fetchone()
            assert row['status'] == 'approved'
            assert row['approved_by'] == owner['id']
            assert row['approved_at']
            event = c.execute("SELECT actor_id, action, detail FROM voucher_events WHERE voucher_id=? AND action='审核'", (vid,)).fetchone()
            assert dict(event) == {'actor_id': owner['id'], 'action': '审核', 'detail': row['number']}


def test_bulk_skips_already_approved(db):
    with server.connect() as c:
        owner, parent_id, _teacher_id = _people(c)
        done, sid = _credit(c, owner['id'], parent_id, name='已审')
        vouchers.approve(c, owner, done)
        done_row = c.execute('SELECT number, approved_at, approved_by FROM vouchers WHERE id=?', (done,)).fetchone()
        done_events = c.execute('SELECT actor_id, action, detail FROM voucher_events WHERE voucher_id=? ORDER BY id', (done,)).fetchall()
        fresh = [_credit(c, owner['id'], parent_id, name=name)[0] for name in ('甲', '乙')]
        voided, _sid = _credit(c, owner['id'], parent_id, name='作废')
        vouchers.void(c, owner, voided, server.units)
        result = vouchers.approve_many(c, owner, [fresh[0], done, voided, 999999, fresh[1], done])
        assert result['approved'] == 2
        assert result['approved_ids'] == fresh
        assert result['skipped'] == [
            {'id': done, 'number': done_row['number'], 'status': 'approved'},
            {'id': voided, 'number': c.execute('SELECT number FROM vouchers WHERE id=?', (voided,)).fetchone()['number'], 'status': 'void'},
            {'id': 999999, 'number': '', 'status': 'missing'},
        ]
        again = c.execute('SELECT status, approved_at, approved_by FROM vouchers WHERE id=?', (done,)).fetchone()
        assert again['status'] == 'approved'
        assert again['approved_at'] == done_row['approved_at']
        assert again['approved_by'] == done_row['approved_by']
        assert c.execute('SELECT actor_id, action, detail FROM voucher_events WHERE voucher_id=? ORDER BY id', (done,)).fetchall() == done_events
        assert c.execute('SELECT status FROM vouchers WHERE id=?', (voided,)).fetchone()['status'] == 'void'
        for vid in fresh:
            assert c.execute('SELECT status, approved_by FROM vouchers WHERE id=?', (vid,)).fetchone()['status'] == 'approved'
        assert c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'] == 300


@pytest.mark.parametrize('role', ['teacher', 'parent'])
def test_bulk_approve_denied_for_teacher_and_parent(db, role):
    with server.connect() as c:
        owner, parent_id, teacher_id = _people(c)
        vid, sid = _credit(c, owner['id'], parent_id)
        balance = c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']
        user = {'id': teacher_id if role == 'teacher' else parent_id, 'role': role}
        with pytest.raises(teaching.AccessError) as denied:
            vouchers.approve_many(c, user, [vid])
        with pytest.raises(teaching.AccessError) as single:
            vouchers.approve(c, user, vid)
        assert str(denied.value) == str(single.value)
        assert c.execute('SELECT status, approved_by FROM vouchers WHERE id=?', (vid,)).fetchone()['status'] == 'pending'
        assert c.execute("SELECT COUNT(*) n FROM voucher_events WHERE voucher_id=? AND action='审核'", (vid,)).fetchone()['n'] == 0
        assert c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'] == balance


def test_bulk_matches_single_approve(db):
    with server.connect() as c:
        owner, parent_id, _teacher_id = _people(c)
        first, sid = _credit(c, owner['id'], parent_id)
        second, _sid = _credit(c, owner['id'], parent_id, sid=sid)
        balance = c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance']
        ledger = c.execute('SELECT COUNT(*) n FROM ledger').fetchone()['n']
        cash = c.execute('SELECT COUNT(*) n FROM cash_entries').fetchone()['n']
        vouchers.approve(c, owner, first)
        result = vouchers.approve_many(c, owner, [second])
        assert result['approved'] == 1
        assert result['skipped'] == []
        single, single_events, single_at = _effect(c, first)
        bulk, bulk_events, bulk_at = _effect(c, second)
        assert single_at and bulk_at
        assert single == bulk
        assert single_events == bulk_events
        assert single['status'] == 'approved'
        assert single['approved_by'] == owner['id']
        assert [action for _actor, action, _detail in single_events] == ['开单', '审核']
        assert c.execute('SELECT balance FROM students WHERE id=?', (sid,)).fetchone()['balance'] == balance
        assert c.execute('SELECT COUNT(*) n FROM ledger').fetchone()['n'] == ledger
        assert c.execute('SELECT COUNT(*) n FROM cash_entries').fetchone()['n'] == cash


def test_bulk_approve_stays_in_the_caller_transaction(db):
    with server.connect() as c:
        owner, parent_id, _teacher_id = _people(c)
        ids = [_credit(c, owner['id'], parent_id, name=name)[0] for name in ('甲', '乙')]
    with pytest.raises(RuntimeError):
        with server.connect() as c:
            vouchers.approve_many(c, owner, ids)
            raise RuntimeError('stop before commit')
    with server.connect() as c:
        assert [c.execute('SELECT status FROM vouchers WHERE id=?', (vid,)).fetchone()['status'] for vid in ids] == ['pending', 'pending']
        assert c.execute("SELECT COUNT(*) n FROM voucher_events WHERE action='审核'").fetchone()['n'] == 0
