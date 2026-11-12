"""客户端上报学习进度（5.0）：学生在客户端本机做作业，客户端定时（和交作业、作答这些事件发生时）把进度报给服务器；
连不上就存在本机队列里，联网后补报（带当时的时间）。老师在网页的班级进度页看（SaaS 服务器上没有沙箱，旁观不了，只能看上报的数据）。

  POST /api/progress/report     {items: [{assignment_id, step, progress (0~1), score (0~100 | null), state, at, data?}]}
                                state：not_started / working / done / submitted；只收自己所在班级的作业
  GET  /api/teach/classes/{cid}/reported         班级 × 作业的最新进度（老师、单位管理员）
  GET  /api/teach/assignments/{aid}/reported     一个作业每个学生的最新进度和最近的上报记录
在线：客户端开着、连着服务器时每分钟报一次（没变化也报一声"心跳"），3 分钟内报过 = 在线。
卡住：在线、作业在做（working），同一个步骤停留超过 VF_STUCK_MIN 分钟（默认 10）。
"""
from ..i18n import _tr
import json
import os
from datetime import datetime, timedelta

from fastapi import Body, HTTPException, Request

from .. import store

STATES = ('not_started', 'working', 'done', 'submitted')
ONLINE_S = 180


def stuck_min():
    try:
        return float(os.environ.get('VF_STUCK_MIN') or 10)
    except ValueError:
        return 10.0


def _ts(s):
    try:
        return datetime.strptime(str(s)[:19], '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return None


def touch(u, client='', aid=None, step=None):
    """在线状态：客户端的心跳和上报都更新。"""
    cur = store.q('select assignment_id, step from presence where username=?', (u['username'],), one=True) or {}
    store.x('insert or replace into presence(username, org, last_seen, client, assignment_id, step) values(?,?,?,?,?,?)',
            (u['username'], u.get('org') or 'default', store.now(), str(client or '')[:40], aid if aid is not None else cur.get('assignment_id'),
             (step if step is not None else cur.get('step')) or None))


def step_since(username, aid, step):
    """当前这一步从什么时候开始的（上报日志里最后一段同一步骤的最早时间）。"""
    since = None
    for r in store.q('select step, client_at from progress_log where username=? and assignment_id=? order by id desc limit 200', (username, aid)):
        if (r['step'] or '') != (step or ''):
            break
        since = r['client_at']
    return since
MAX_ITEMS = 200
LOG_KEEP = 200


def _num(v, lo, hi):
    if v in (None, ''):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:                                    # NaN
        return None
    return max(lo, min(hi, f))


def _row_view(r):
    if not r:
        return None
    return {'step': r['step'], 'progress': r['progress'], 'score': r['score'], 'state': r['state'], 'at': r['client_at'], 'received': r['received']}


def record(u, items):
    from ..teach import db
    db.ready()
    mine = set(db.classes_of_student(u['username']))
    org = u.get('org') or 'default'
    ok, bad = 0, []
    last_item = (None, None)
    for it in (items or [])[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        try:
            aid = int(it.get('assignment_id'))
        except (TypeError, ValueError):
            bad.append({'assignment_id': it.get('assignment_id'), 'why': _tr('作业号不对')})
            continue
        a = db.q('select a.id, a.class_id, c.org from assignments a join classes c on c.id=a.class_id where a.id=?', (aid,), one=True)
        if not a or a['class_id'] not in mine or (a['org'] or 'default') != org:
            bad.append({'assignment_id': aid, 'why': _tr('不是你的作业')})
            continue
        state = it.get('state') if it.get('state') in STATES else 'working'
        step = str(it.get('step') or '')[:120]
        prog = _num(it.get('progress'), 0.0, 1.0)
        score = _num(it.get('score'), 0.0, 100.0)
        at = str(it.get('at') or store.now())[:19]
        data = it.get('data')
        data = json.dumps(data, ensure_ascii=False)[:2000] if isinstance(data, dict) else None
        now = store.now()
        store.x('insert into progress_log(org, username, assignment_id, step, progress, score, state, client_at, received) values(?,?,?,?,?,?,?,?,?)',
                (org, u['username'], aid, step, prog, score, state, at, now))
        cur = store.q('select client_at from progress_reports where username=? and assignment_id=?', (u['username'], aid), one=True)
        if not cur or (cur['client_at'] or '') <= at:          # 补报的旧记录只进日志，不覆盖更新的状态
            store.x('insert or replace into progress_reports(username, assignment_id, org, class_id, step, progress, score, state, client_at, received, data) '
                    'values(?,?,?,?,?,?,?,?,?,?,?)', (u['username'], aid, org, a['class_id'], step, prog, score, state, at, now, data))
        ok += 1
        last_item = (aid, step)
    if ok:
        touch(u, aid=last_item[0], step=last_item[1])
    # 每个作业的上报日志只留最近 LOG_KEEP 条
    for r in store.q('select assignment_id, count(*) n from progress_log where username=? group by assignment_id having n>?', (u['username'], LOG_KEEP)):
        store.x('delete from progress_log where id in (select id from progress_log where username=? and assignment_id=? order by id limit ?)',
                (u['username'], r['assignment_id'], r['n'] - LOG_KEEP))
    return {'accepted': ok, 'rejected': bad}


def overlay(aid, rows):
    """SaaS 的教学控制台：服务器上没有沙箱，学生的状态按客户端上报的进度和在线情况算（进行中 / 卡住 / 离开 / 已提交 / 未开始）。"""
    names = [r['username'] for r in rows]
    if not names:
        return rows
    qs = ','.join('?' * len(names))
    rep = {r['username']: r for r in store.q(f'select * from progress_reports where assignment_id=? and username in ({qs})', (aid, *names))}
    pres = {r['username']: r for r in store.q(f'select * from presence where username in ({qs})', tuple(names))}
    now = datetime.now()
    smin = stuck_min()
    for row in rows:
        r = rep.get(row['username'])
        p = pres.get(row['username']) or {}
        seen = _ts(p.get('last_seen'))
        online = bool(seen and (now - seen).total_seconds() <= ONLINE_S)
        info = {'online': online, 'last_seen': p.get('last_seen')}
        if r:
            info.update(_row_view(r))
            if r['state'] == 'working':
                st = _ts(step_since(row['username'], aid, r['step']))
                info['step_min'] = round((now - st).total_seconds() / 60, 1) if st else None
        if online and p.get('assignment_id') and p['assignment_id'] != aid:          # 在线，但在做别的课
            t = store.q('select title from assignments where id=?', (p['assignment_id'],), one=True)
            info['elsewhere'] = {'assignment_id': p['assignment_id'], 'title': (t or {}).get('title'), 'step': p.get('step')}
        row['reported'] = info
        row['active'] = online
        row['seen'] = (p.get('last_seen') or '')[11:16] or None
        if row['best'] is not None and row['best'] >= 99.5:
            row['state'] = _tr('已满分')
        elif r and r['state'] == 'working' and online and (info.get('step_min') or 0) >= smin:
            row['state'] = _tr('卡住')
            row['alarm'] = _tr('在「{v}」停了 {round} 分钟', v=r['step'] or _tr('同一步'), round=round(info['step_min']))
        elif r and r['state'] == 'working' and online:
            row['state'] = _tr('进行中')
        elif row['submissions'] or (r and r['state'] == 'submitted'):
            row['state'] = _tr('已提交')
        elif r:
            row['state'] = _tr('离开')
        else:
            row['state'] = _tr('未开始')
    return rows


def note_submission(username, aid, score, state='submitted'):
    """服务器收到作业包时也记一笔（老师看到的状态跟着变）。"""
    org = store.org_of(username)
    a = store.q('select class_id from assignments where id=?', (aid,), one=True)
    cur = store.q('select * from progress_reports where username=? and assignment_id=?', (username, aid), one=True)
    store.x('insert or replace into progress_reports(username, assignment_id, org, class_id, step, progress, score, state, client_at, received, data) '
            'values(?,?,?,?,?,?,?,?,?,?,?)', (username, aid, org, (a or {}).get('class_id'), (cur or {}).get('step') or _tr('已提交'),
                                              1.0, score, state, store.now(), store.now(), (cur or {}).get('data')))


def register(app, mgr):
    from ..teach import db
    from ..teach.api import best_scores, need_assignment, need_class, need_teacher

    @app.post('/api/progress/report')
    async def report(request: Request, body: dict = Body(...)):
        """客户端上报进度（批量；离线补报的带当时的时间）。"""
        u = request.state.user
        items = body.get('items')
        if not isinstance(items, list):
            raise HTTPException(400, _tr('缺少 items'))
        out = record(u, items)
        hb = body.get('heartbeat')
        if isinstance(hb, dict) or not items:            # 心跳：客户端开着、连着（没有新进度也报）
            touch(u, client=(hb or {}).get('client') if isinstance(hb, dict) else '')
        return out

    @app.get('/api/teach/classes/{cid}/reported')
    async def class_reported(cid: int, request: Request):
        """班级进度：每个学生、每个作业的最新上报（客户端报的进度、当前步骤、本机分数）+ 服务器上的最高分。"""
        u = need_teacher(request)
        c = need_class(u, cid)
        asg = db.q("select id, title, course, lesson, seq, due from assignments where class_id=? and status='published' order by coalesce(course,''), "
                   'coalesce(seq,0), id', (cid,))
        members = db.members(cid)
        names = {r['username']: r['name'] for r in store.q('select username, name from users where org=?', (c.get('org') or 'default',))}
        latest = {}
        for r in store.q('select * from progress_reports where class_id=?', (cid,)):
            latest[(r['username'], r['assignment_id'])] = r
        bests = {a['id']: best_scores(a['id']) for a in asg}
        titles = {a['id']: a['title'] for a in asg}
        qs = ','.join('?' * len(members)) or "''"
        pres = {r['username']: r for r in store.q(f'select * from presence where username in ({qs})', tuple(members))}
        now = datetime.now()
        smin = stuck_min()
        rows = []
        summary = {'students': len(members), 'online': 0, 'stuck': 0, 'not_started': 0, 'submitted': 0, 'working': 0}
        for m in members:
            items = {}
            last = ''
            cur = None
            for a in asg:
                r = latest.get((m, a['id']))
                b = (bests[a['id']].get(m) or {}).get('score')
                if r or b is not None:
                    it = {**(_row_view(r) or {}), 'best': b}
                    if r and r['state'] == 'working':
                        since = step_since(m, a['id'], r['step'])
                        st = _ts(since)
                        it['step_since'] = since
                        it['step_min'] = round((now - st).total_seconds() / 60, 1) if st else None
                    items[a['id']] = it
                    if r and (r['received'] or '') > last:
                        last, cur = r['received'], {'assignment_id': a['id'], 'title': a['title'], **it}
            p = pres.get(m) or {}
            seen = _ts(p.get('last_seen'))
            online = bool(seen and (now - seen).total_seconds() <= ONLINE_S)
            stuck = bool(online and cur and cur.get('state') == 'working' and (cur.get('step_min') or 0) >= smin)
            if p.get('assignment_id') in titles and (not cur or cur['assignment_id'] != p.get('assignment_id')) and online:
                pa = p['assignment_id']
                cur = {'assignment_id': pa, 'title': titles[pa], **(items.get(pa) or {})}
            state = 'not_started' if not items else ('submitted' if all((v.get('state') == 'submitted') for v in items.values()) else 'working')
            summary['online'] += online
            summary['stuck'] += stuck
            summary[state] += 1
            rows.append({'username': m, 'name': names.get(m) or m, 'items': items, 'last': last or None, 'online': online,
                         'last_seen': p.get('last_seen'), 'current': cur, 'stuck': stuck, 'state': state})
        return {'class': {'id': c['id'], 'name': c['name']}, 'assignments': asg, 'students': rows, 'summary': summary,
                'online_s': ONLINE_S, 'stuck_min': smin, 'now': store.now()}

    @app.get('/api/teach/assignments/{aid}/reported')
    async def assignment_reported(aid: int, request: Request):
        u = need_teacher(request)
        a = need_assignment(u, aid, teacher=True)
        members = db.members(a['class_id'])
        best = best_scores(aid)
        out = []
        for m in members:
            r = store.q('select * from progress_reports where username=? and assignment_id=?', (m, aid), one=True)
            log = store.q('select step, progress, score, state, client_at at, received from progress_log where username=? and assignment_id=? '
                          'order by id desc limit 20', (m, aid))
            out.append({'username': m, 'latest': _row_view(r), 'best': (best.get(m) or {}).get('score'), 'log': log})
        return {'assignment': {'id': a['id'], 'title': a['title']}, 'students': out}
