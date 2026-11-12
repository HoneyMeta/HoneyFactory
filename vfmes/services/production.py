"""生产：工单下达、有限产能排产、派工、手工/扫码报工、领退料、工单进度。"""
from ..i18n import _tr
from datetime import datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db
from ..auth import current_user, require_write
from ..crud import action, attach_labels, out
from ..db import clock
from ..schema import TABLES

router = APIRouter()


def group_capacity(c) -> dict:
    """工位组 → 可并行设备数（按工位表统计）。"""
    cap = {}
    for w in db.rows(c, 'workstation'):
        g = w['group'] or w['code']
        cap[g] = cap.get(g, 0) + 1
    return cap


@action('work_order', 'release')
def release(c, wo, body, user):
    if wo['status'] != 'draft':
        raise HTTPException(400, _tr('只有草稿状态的工单可以下达'))
    route = wo['route']
    if not route:
        r = db.get(c, 'route', product=wo['product'], status='active')
        route = r['id'] if r else None
    if not route:
        raise HTTPException(400, _tr('这个产品还没有生效的工艺路线'))
    steps = db.rows(c, 'route_step', order=TABLES['route_step'].c.seq, route=route)
    c.execute(TABLES['wo_op'].delete().where(TABLES['wo_op'].c.work_order == wo['id']))
    for i, s in enumerate(steps):
        db.insert(c, 'wo_op', {'work_order': wo['id'], 'seq': s['seq'], 'process': s['process'], 'station_group': s['station_group'],
                               'qty_plan': wo['qty'], 'qty_good': 0, 'qty_ng': 0, 'status': 'ready' if i == 0 else 'waiting'}, raw=True)
    db.update(c, 'work_order', wo['id'], {'route': route, 'status': 'released', 'released_at': clock.now(),
                                          'start_plan': wo['start_plan'] or clock.now()}, raw=True)
    schedule(c)
    return {'msg': _tr('已下达，生成 {len} 道工序并完成排产', len=len(steps))}


@action('work_order', 'close')
def close(c, wo, body, user):
    db.update(c, 'work_order', wo['id'], {'status': 'closed', 'completed_at': wo['completed_at'] or clock.now()}, raw=True)


@action('work_order', 'cancel')
def cancel(c, wo, body, user):
    if wo['status'] in ('in_progress', 'completed'):
        raise HTTPException(400, _tr('已开工的工单请用"关闭"'))
    db.update(c, 'work_order', wo['id'], {'status': 'cancelled'}, raw=True)


@action('wo_op', 'dispatch')
def dispatch(c, op, body, user):
    if not body.get('assignee'):
        raise HTTPException(400, _tr('请选择派工对象'))
    db.update(c, 'wo_op', op['id'], {'assignee': int(body['assignee']), 'status': 'ready' if op['status'] == 'waiting' else op['status']}, raw=True)


def schedule(c):
    """前移式有限产能排产：按优先级、交期依次给工单排各工序；同一工位组的设备数即并行能力。
    流水线上各工序并行流动：后一道工序在前一道开工一个"首件流转时间"后即可开工，结束不早于前一道结束。"""
    wot, opt = TABLES['work_order'], TABLES['wo_op']
    cap = group_capacity(c)
    procs = {p['id']: p for p in db.rows(c, 'process')}
    steps_ct = {}
    for s in db.rows(c, 'route_step'):
        steps_ct[(s['route'], s['seq'])] = s['std_cycle_s']
    free: dict[str, datetime] = {}
    now = clock.now().replace(second=0, microsecond=0)
    wos = db.rows(c, 'work_order', wot.c.status.in_(('released', 'in_progress')), order=(wot.c.priority, wot.c.due, wot.c.id))
    late = []
    for wo in wos:
        ops = db.rows(c, 'wo_op', order=opt.c.seq, work_order=wo['id'])
        prev_s = prev_e = max(now, wo['start_plan'] or now)
        for op in ops:
            g = op['station_group'] or f"P{op['process']}"
            n = max(1, cap.get(g, 1))
            ct = steps_ct.get((wo['route'], op['seq'])) or (procs.get(op['process']) or {}).get('std_cycle_s') or 60
            remain = max(0, (op['qty_plan'] or 0) - (op['qty_good'] or 0))
            dur = timedelta(seconds=remain * ct / n)
            start = max(prev_s + timedelta(seconds=ct * 2), free.get(g, now)) if op['seq'] != ops[0]['seq'] else max(prev_s, free.get(g, now))
            if op['act_start'] and op['status'] == 'running':
                start = max(now, start)
            end = max(start + dur, prev_e + timedelta(seconds=ct))
            free[g] = start + dur
            c.execute(opt.update().where(opt.c.id == op['id']).values(plan_start=start, plan_end=end))
            prev_s, prev_e = start, end
        if wo['due'] and prev_e > wo['due']:
            late.append(wo['code'])
    return late


@router.post('/api/production/schedule')
def run_schedule(user=Depends(current_user)):
    require_write(user, 'work_order')
    with db.engine.begin() as c:
        late = schedule(c)
    return {'ok': True, 'late': late}


@router.get('/api/production/gantt')
def gantt(user=Depends(current_user)):
    wot, opt, pt = TABLES['work_order'], TABLES['wo_op'], TABLES['process']
    with db.engine.connect() as c:
        wos = db.rows(c, 'work_order', wot.c.status.in_(('released', 'in_progress', 'completed')), order=(wot.c.priority, wot.c.due, wot.c.id), limit=40)
        attach_labels(c, 'work_order', wos)
        ops = []
        for wo in wos:
            rows = db.rows(c, 'wo_op', order=opt.c.seq, work_order=wo['id'])
            attach_labels(c, 'wo_op', rows)
            ops += rows
    return {'orders': out(wos), 'ops': out(ops), 'now': db.jsonable(clock.now())}


@router.get('/api/production/board')
def board(user=Depends(current_user)):
    """工单进度看板。"""
    wot = TABLES['work_order']
    with db.engine.connect() as c:
        wos = db.rows(c, 'work_order', wot.c.status.in_(('released', 'in_progress')), order=(wot.c.priority, wot.c.due))
        attach_labels(c, 'work_order', wos)
        for wo in wos:
            ops = db.rows(c, 'wo_op', order=TABLES['wo_op'].c.seq, work_order=wo['id'])
            attach_labels(c, 'wo_op', ops)
            wo['ops'] = out(ops)
            last = ops[-1]['plan_end'] if ops else None
            wo['eta'] = db.jsonable(last)
            wo['late'] = bool(last and wo['due'] and last > wo['due'])
    return out(wos)


# ---------------- 手机扫码报工 ----------------
@router.get('/api/production/my_tasks')
def my_tasks(user=Depends(current_user)):
    opt, wot = TABLES['wo_op'], TABLES['work_order']
    with db.engine.connect() as c:
        q = sa.select(opt).join(wot, wot.c.id == opt.c.work_order).where(wot.c.status.in_(('released', 'in_progress')) & opt.c.status.in_(('ready', 'running', 'waiting')))
        if user.get('employee') and 'operator' in user['role_list']:
            q = q.where(sa.or_(opt.c.assignee == user['employee'], opt.c.assignee.is_(None)))
        ops = [dict(r) for r in c.execute(q.order_by(wot.c.priority, opt.c.seq).limit(60)).mappings()]
        attach_labels(c, 'wo_op', ops)
        procs = {p['id']: p for p in db.rows(c, 'process')}
        modes = {(s['route'], s['seq']): s['report_mode'] for s in db.rows(c, 'route_step')}
        wos = {w['id']: w for w in db.rows(c, 'work_order', wot.c.id.in_({o['work_order'] for o in ops}))} if ops else {}
        for o in ops:
            wo = wos.get(o['work_order'], {})
            o['mode'] = modes.get((wo.get('route'), o['seq']), 'auto')
            o['process_name'] = procs.get(o['process'], {}).get('name')
    return out(ops)


@router.post('/api/production/report')
def manual_report(body: dict = Body(...), user=Depends(current_user)):
    """人工 / 扫码报工：{wo_op 或 sn+process, qty_good, qty_ng, defect}。扫码时按零件码找工单。"""
    require_write(user, 'report')
    with db.engine.begin() as c:
        op = db.get(c, 'wo_op', int(body['wo_op'])) if body.get('wo_op') else None
        if not op and body.get('sn'):
            part = db.get(c, 'part', sn=body['sn'].strip())
            if not part:
                raise HTTPException(404, _tr('没有零件码 {sn}', sn=body['sn']))
            ops = db.rows(c, 'wo_op', order=TABLES['wo_op'].c.seq, work_order=part['work_order'])
            op = next((o for o in ops if str(o['process']) == str(body.get('process'))), None) or next((o for o in ops if o['status'] != 'done'), None)
        if not op:
            raise HTTPException(400, _tr('没找到对应的工单工序'))
        g, n = int(body.get('qty_good') or 0), int(body.get('qty_ng') or 0)
        now = clock.now()
        vals = {'qty_good': (op['qty_good'] or 0) + g, 'qty_ng': (op['qty_ng'] or 0) + n, 'act_start': op['act_start'] or now, 'status': 'running'}
        if vals['qty_good'] >= (op['qty_plan'] or 0):
            vals.update(status='done', act_end=now)
        db.update(c, 'wo_op', op['id'], vals, raw=True)
        nxt = db.rows(c, 'wo_op', TABLES['wo_op'].c.seq > op['seq'], order=TABLES['wo_op'].c.seq, limit=1, work_order=op['work_order'])
        if nxt and nxt[0]['status'] == 'waiting':
            db.update(c, 'wo_op', nxt[0]['id'], {'status': 'ready'}, raw=True)
        rid = db.insert(c, 'report', {'work_order': op['work_order'], 'wo_op': op['id'], 'process': op['process'], 'employee': user.get('employee'),
                                      'qty_good': g, 'qty_ng': n, 'defect': body.get('defect') or None, 'start': now, 'end': now,
                                      'source': 'mobile' if body.get('sn') or body.get('mobile') else 'manual', 'remark': body.get('remark')}, raw=True)
        wo = db.get(c, 'work_order', op['work_order'])
        if wo['status'] == 'released':
            db.update(c, 'work_order', wo['id'], {'status': 'in_progress'}, raw=True)
        if n:
            from .quality import defect_id
            db.insert(c, 'ncr', {'sn': body.get('sn'), 'work_order': wo['id'], 'material': wo['product'], 'qty': n, 'defect': body.get('defect') or None,
                                 'station': body.get('station'), 'found_at': now, 'found_by': user['name'] or user['username'], 'source': 'manual',
                                 'disposition': 'pending', 'status': 'open'}, raw=True)
    return {'ok': True, 'id': rid}


@router.post('/api/production/issue_bom')
def issue_bom(body: dict = Body(...), user=Depends(current_user)):
    """按 BOM 领料：{work_order, qty(套数), warehouse}"""
    require_write(user, 'material_issue')
    from .warehouse import move
    with db.engine.begin() as c:
        wo = db.get(c, 'work_order', int(body['work_order']))
        sets = float(body.get('qty') or wo['qty'])
        bom = db.rows(c, 'bom', product=wo['product'])
        if not bom:
            raise HTTPException(400, _tr('这个产品没有 BOM'))
        wh = int(body['warehouse']) if body.get('warehouse') else None
        for b in bom:
            q = round(b['qty'] * sets, 3)
            db.insert(c, 'material_issue', {'kind': 'issue', 'work_order': wo['id'], 'material': b['component'], 'qty': q, 'warehouse': wh,
                                            'employee': user.get('employee'), 'time': clock.now()}, raw=True)
            if wh:
                move(c, 'out', b['component'], q, wh, ref=wo['code'], who=user['name'] or user['username'], reason=_tr('按 BOM 领料'))
    return {'ok': True, 'lines': len(bom)}
