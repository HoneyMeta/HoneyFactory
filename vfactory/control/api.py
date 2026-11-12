"""控制层接口：控制单元定义 / 实时 I/O / 强制 / 面板 / 故障 / 统计，场景库与评分。程序与 PLC 相关接口在 vfactory/plc。

  GET  /api/cells/catalog                      部件目录（编辑器部件库）
  POST /api/cells/auto_io      {cell}           按部件自动生成 I/O 表（保留已有名称和地址）
  POST /api/cells/validate     {cell}           检查单元定义
  GET  /api/p/{pid}/cells                       工厂里的控制单元列表
  GET  /api/p/{pid}/cells/{bid}                 定义 + 状态（PLC、I/O、统计、故障）
  PUT  /api/p/{pid}/cells/{bid} {cell}          修改定义：立即作用到运行中的单元，并写进模型（标记未保存；有草稿时同步草稿）
  GET  /api/p/{pid}/cells/{bid}/io              实时 I/O
  POST /api/p/{pid}/cells/{bid}/io/force {name, value|null}   强制 / 取消强制（null）
  POST /api/p/{pid}/cells/{bid}/panel {comp, action: press|release|toggle|set, value, hold}  操作面板
  GET  /api/p/{pid}/cells/{bid}/faults          当前故障 + 每个部件可注入的故障
  POST /api/p/{pid}/cells/{bid}/faults {comp, kind}            注入故障（comp 可以是部件编号或 I/O 名）
  DELETE /api/p/{pid}/cells/{bid}/faults[?comp=]               清除故障
  GET  /api/p/{pid}/cells/{bid}/stats           统计
  POST /api/p/{pid}/cells/{bid}/reset           单元复位（清空零件、统计，PLC 程序保留）
  GET  /api/p/{pid}/cells/{bid}/events          单元事件（碰撞、卡件、分拣错误…）
  GET  /api/p/{pid}/devices/{bid}/control       4.3 设备的控制点（任何生产设备）：点位、当前值、接到哪台 PLC 的哪个通道
  POST /api/p/{pid}/devices/{bid}/control {point, value}       手动写一个没接 PLC 的 out 点（调试用）
  GET  /api/scenes                              场景库列表
  GET  /api/scenes/{id}                         场景（含参考答案；学生账号由教学模块拦截）
  GET  /api/scenes/{id}/plant                   场景的独立工厂模型（学生沙箱用）
  POST /api/scenes/{id}/score {program?}        用程序（不给用参考答案）跑一遍自动测试并评分
"""
from ..i18n import _tr
import asyncio
import copy
import json
import logging
import time

from fastapi import Body, HTTPException, Request

from . import catalog, scenes, scoring, validate_cell

log = logging.getLogger('vfactory.control')


def _coach(mgr, pid, what, **kw):
    """4.5 运行日志（vfactory/teach/coach.py）：有人在看日志时记一笔。"""
    try:
        from ..teach import coach
    except Exception:                       # noqa: BLE001
        return
    coach.hook(mgr, pid, what, **kw)


def _cell(mgr, pid, bid):
    rt = mgr.get(pid)
    st = rt.plant.stations.get(bid) or rt.plant.find(bid)
    if st is None or getattr(st, 'kind', '') != 'cell':
        raise HTTPException(404, _tr('没有控制单元 {bid}', bid=bid))
    return rt, st


def _io_rows(st):
    sim = st.sim
    ins = st.inputs_last or sim.inputs()
    rows = []
    for e in sim.io:
        nm = e['name']
        v = ins.get(nm) if e.get('dir') == 'in' else sim.outputs.get(nm)
        rows.append({**e, 'value': v, 'forced': nm in sim.forced,
                     'fault': sorted(sim.faults.get(e.get('comp'), set()) | sim.io_faults.get(nm, set()))})
    return rows


def wiring(plant, bid):
    """4.3：设备每个控制点接到哪台 PLC 的哪个通道 {点位名: [{plc, plc_name, ch, link, dir}]}（按模型里的信号线）。"""
    out = {}
    for l in plant.cfg.get('links') or []:
        if l.get('kind') != 'signal' or bid not in (l.get('from'), l.get('to')):
            continue
        other = l['to'] if l.get('from') == bid else l.get('from')
        o = plant.find(other)
        for sg in l.get('signals') or []:
            pt = sg.get('point')
            if pt:
                out.setdefault(pt, []).append({'plc': other, 'plc_name': getattr(o, 'name', other), 'ch': sg.get('ch') or '', 'link': l.get('id'),
                                               'dir': sg.get('dir') or 'in', 'var': sg.get('name') or ''})
    return out


def _controllers(st):
    f = getattr(st, 'controllers', None)
    if callable(f):
        return f()
    try:
        from ..plc.station import controllers
        return controllers(st)
    except Exception:                       # noqa: BLE001
        return []


def _plc_info(st):
    p = st.plc
    ctl = _controllers(st)
    if p is None and ctl:
        p = getattr(ctl[0], 'plc', None)
    info = {'mode': st.mode(), 'state': st.plc_state(), 'error': st.plc_error, 'embedded': st.plc is not None,
            'controllers': [{'id': c.id, 'name': c.name, 'state': str(getattr(getattr(c, 'plc', None), 'state', '') or 'STOP'),
                             'label': c.label() if hasattr(c, 'label') else ''} for c in ctl]}
    if p is not None:
        err = getattr(p, 'error', None)
        if err:
            info['error'] = err.get('msg') if isinstance(err, dict) else str(err)
        for k in ('scan_count', 'downloads'):
            if hasattr(p, k):
                info[k] = getattr(p, k)
    return info


def cell_state(st, full=True):
    d = {'id': st.id, 'name': st.name, 'state': st.state, 'alarm': st.alarm, 'plc': _plc_info(st), 't': round(st.sim.t, 2),
         'stats': st.sim.stats(), 'faults': st.sim.fault_list(), 'rev': st.rev()}
    if full:
        d['cell'] = st.cell_def
        d['io'] = _io_rows(st)
        d['wiring'] = wiring(st.plant, st.id)
        d['validation'] = [{'level': lv, 'msg': m} for lv, m in validate_cell(st.cell_def)]
    return d


def _model_set_cell(model, bid, cell):
    for b in model.get('blocks') or []:
        if b['id'] == bid:
            b.setdefault('params', {})['cell'] = copy.deepcopy(cell)
            return True
    return False


def register(app, mgr):
    def need(request, role='engineer'):
        u = getattr(request.state, 'user', None) or {}
        lv = {'viewer': 0, 'student': 1, 'teacher': 1, 'engineer': 1, 'admin': 2}
        if lv.get(u.get('role'), 0) < lv[role]:
            raise HTTPException(403, _tr('当前账号没有这个权限'))
        return u

    # ---------------- 目录 / 工具 ----------------
    @app.get('/api/cells/catalog')
    async def cell_catalog():
        return catalog.public()

    @app.post('/api/cells/auto_io')
    async def cell_auto_io(body: dict = Body(...)):
        cell = body.get('cell') or {}
        keep = cell.get('io') if body.get('keep', True) else []
        return {'io': catalog.auto_io(cell, keep=keep or [])}

    @app.post('/api/cells/validate')
    async def cell_validate(body: dict = Body(...)):
        return {'issues': [{'level': lv, 'msg': m} for lv, m in validate_cell(body.get('cell') or {})]}

    # ---------------- 运行中的单元 ----------------
    @app.get('/api/p/{pid}/cells')
    async def cells_list(pid: str):
        rt = mgr.get(pid)
        return [cell_state(st, full=False) for st in rt.plant.all_stations() if getattr(st, 'kind', '') == 'cell']

    @app.get('/api/p/{pid}/cells/{bid}')
    async def cell_get(pid: str, bid: str):
        _, st = _cell(mgr, pid, bid)
        return cell_state(st)

    @app.put('/api/p/{pid}/cells/{bid}')
    async def cell_put(pid: str, bid: str, request: Request, body: dict = Body(...)):
        need(request)
        rt, st = _cell(mgr, pid, bid)
        cell = body.get('cell')
        if not isinstance(cell, dict):
            raise HTTPException(400, _tr('缺少单元定义 cell'))
        issues = validate_cell(cell)
        errs = [m for lv, m in issues if lv == 'error']
        if errs:
            raise HTTPException(400, _tr('单元定义有错误：') + _tr('；').join(errs[:5]))
        if not cell.get('io'):
            cell['io'] = catalog.auto_io(cell, keep=[])
        if 'plc' not in st.cell_def:
            cell.pop('plc', None)                    # 4.3：PLC 是独立设备，单元定义里不再带 PLC
        prog = (st.cell_def.get('plc') or {}).get('program')
        if prog is not None and not (cell.get('plc') or {}).get('program'):
            cell.setdefault('plc', {})['program'] = copy.deepcopy(prog)      # 改布局不丢程序
        if body.get('live', True):
            st.reload(cell)
        else:
            st.cfg['cell'] = copy.deepcopy(cell)
        _model_set_cell(rt.cfg, bid, cell)
        rt.dirty = True
        try:
            from .. import editor_api
            d = editor_api.load_draft(pid)
            if d and _model_set_cell(d['model'], bid, cell):
                with open(editor_api.draft_path(pid), 'w', encoding='utf-8') as f:
                    json.dump(d, f, ensure_ascii=False)
        except Exception:
            log.exception(_tr('同步草稿失败'))
        rt.plant.log(bid, 'layout', _tr('控制单元 {name} 定义已修改（{len} 个部件，{len2} 个 I/O）', name=st.name, len=len(cell.get("components") or []), len2=len(cell.get("io") or [])))
        return cell_state(st)

    @app.get('/api/p/{pid}/cells/{bid}/io')
    async def cell_io(pid: str, bid: str):
        _, st = _cell(mgr, pid, bid)
        sim = st.sim
        ins = st.inputs_last or sim.inputs()
        return {'t': round(sim.t, 2), 'inputs': ins, 'outputs': dict(sim.outputs), 'forced': dict(sim.forced), 'io': _io_rows(st),
                'plc': _plc_info(st), 'wiring': wiring(st.plant, st.id)}

    @app.post('/api/p/{pid}/cells/{bid}/io/force')
    async def cell_force(pid: str, bid: str, request: Request, body: dict = Body(...)):
        need(request)
        rt, st = _cell(mgr, pid, bid)
        nm = body.get('name')
        err = st.sim.force(nm, body.get('value'))
        if err:
            raise HTTPException(400, err)
        rt.plant.log(bid, 'param', f"I/O {nm} {_tr('取消强制') if body.get('value') is None else _tr('强制为 ') + str(body.get('value'))}")
        _coach(mgr, pid, 'force', name=nm, value=body.get('value'))
        return {'ok': True, 'forced': dict(st.sim.forced)}

    @app.post('/api/p/{pid}/cells/{bid}/panel')
    async def cell_panel(pid: str, bid: str, request: Request, body: dict = Body(...)):
        need(request)
        _, st = _cell(mgr, pid, bid)
        _coach(mgr, pid, 'panel', comp=body.get('comp'))
        err = st.sim.panel(body.get('comp'), body.get('action') or 'press', body.get('value'), body.get('hold', 0.3))
        if err:
            raise HTTPException(400, err)
        return {'ok': True}

    @app.get('/api/p/{pid}/cells/{bid}/faults')
    async def cell_faults(pid: str, bid: str):
        _, st = _cell(mgr, pid, bid)
        comps = [{'id': c.id, 'type': c.type, 'label': c.d.get('label') or catalog.COMP_TYPES.get(c.type, {}).get('label', c.type),
                  'kinds': catalog.faults_for(c.type)} for c in st.sim.comps.values()]
        return {'active': st.sim.fault_list(), 'comps': [c for c in comps if c['kinds']], 'labels': catalog.FAULTS}

    @app.post('/api/p/{pid}/cells/{bid}/faults')
    async def cell_fault_add(pid: str, bid: str, request: Request, body: dict = Body(...)):
        need(request)
        rt, st = _cell(mgr, pid, bid)
        comp, kind = body.get('comp'), body.get('kind')
        err = st.sim.inject(comp, kind)
        if err:
            raise HTTPException(400, err)
        rt.plant.log(bid, 'fault', _tr('控制单元故障：{comp} {get}', comp=comp, get=catalog.FAULTS.get(kind, kind)), comp=comp, fault=kind)
        rt.plant.label_open(f'{bid}/{comp}', 'cell_fault', catalog.FAULTS.get(kind, kind), kind=kind)
        return {'ok': True, 'active': st.sim.fault_list()}

    @app.delete('/api/p/{pid}/cells/{bid}/faults')
    async def cell_fault_clear(pid: str, bid: str, request: Request, comp: str = ''):
        need(request)
        rt, st = _cell(mgr, pid, bid)
        olds = {f['comp'] for f in st.sim.fault_list()}
        st.sim.clear_faults(comp or None)
        for c in olds if not comp else [comp]:
            rt.plant.label_close(f'{bid}/{c}', 'cell_fault')
        rt.plant.log(bid, 'repair', _tr('控制单元故障已清除') + (_tr('：{comp}', comp=comp) if comp else ''))
        return {'ok': True, 'active': st.sim.fault_list()}

    @app.get('/api/p/{pid}/cells/{bid}/stats')
    async def cell_stats(pid: str, bid: str):
        rt, st = _cell(mgr, pid, bid)
        s = st.sim.stats()
        s['oee'] = rt.plant.oee(st)
        s['state'] = st.state
        s['exited'] = st.count
        return s

    @app.get('/api/p/{pid}/cells/{bid}/events')
    async def cell_events(pid: str, bid: str, limit: int = 100):
        _, st = _cell(mgr, pid, bid)
        return st.sim.events[-max(1, min(400, limit)):]

    @app.post('/api/p/{pid}/cells/{bid}/reset')
    async def cell_reset(pid: str, bid: str, request: Request):
        need(request)
        rt, st = _cell(mgr, pid, bid)
        p = st.plc
        if p is None:                                   # 4.3：接在单元上的 PLC 块
            ctl = _controllers(st)
            p = getattr(ctl[0], 'plc', None) if ctl else None
        was = str(getattr(p, 'state', ''))
        st.reload(copy.deepcopy(st.cell_def))          # 新的 CellSim：零件清空、单元时间归零、面板复位（急停也复位）
        st._ctl_out = {}
        if st.plc is not None:
            p = st.plc
        if p is not None and hasattr(p, 'reset'):       # PLC 冷启动（程序保留），复位前在运行就继续运行
            try:
                p.reset(cold=True)
                if was in ('RUN', 'HALT') and hasattr(p, 'run'):
                    p.run()
            except Exception:
                log.exception(_tr('PLC 复位失败'))
        st.ahead = 0.0
        _coach(mgr, pid, 'reset')
        rt.plant.log(bid, 'info', _tr('控制单元 {name} 已复位：零件清空，单元时间归零，PLC 重新启动', name=st.name))
        d = cell_state(st)
        d['msg'] = _tr('设备已回到初始状态：零件清空，单元时间归零，PLC 重新启动（程序保留）')
        return d

    # ---------------- 4.3 设备的控制点（设备内部视图里的 I/O 板） ----------------
    def _device(pid, bid):
        rt = mgr.get(pid)
        st = rt.plant.find(bid)
        if st is None:
            raise HTTPException(404, _tr('没有设备 {bid}', bid=bid))
        return rt, st

    def _points(st):
        wired = wiring(st.plant, st.id)
        rows = []
        for p in st.ctl_points():
            try:
                v = st.ctl_get(p['name'])
            except Exception:                   # noqa: BLE001
                v = None
            rows.append({**p, 'value': v, 'wired': wired.get(p['name'], [])})
        return rows

    @app.get('/api/p/{pid}/devices/{bid}/control')
    async def device_control(pid: str, bid: str):
        _, st = _device(pid, bid)
        hold = False
        try:
            hold = bool(st._plc_wired) and st.ctl_hold()
        except Exception:                       # noqa: BLE001
            pass
        return {'id': st.id, 'name': st.name, 'type': st.cfg.get('type'), 'kind': st.kind, 'state': st.state, 'alarm': st.alarm,
                'waiting_plc': hold, 'points': _points(st), 'plcs': [{'id': c.id, 'name': c.name} for c in _controllers(st)]}

    @app.post('/api/p/{pid}/devices/{bid}/control')
    async def device_control_set(pid: str, bid: str, request: Request, body: dict = Body(...)):
        need(request)
        rt, st = _device(pid, bid)
        pt = str(body.get('point') or '')
        w = wiring(st.plant, st.id).get(pt)
        if w:
            raise HTTPException(400, _tr('{pt} 由 PLC {plc_name} 控制（通道 {ch}），不能手动写；先断开这一路信号', pt=pt, plc_name=w[0]['plc_name'], ch=w[0]['ch']))
        err = st.ctl_set(pt, body.get('value'))
        if err:
            raise HTTPException(400, err)
        rt.plant.log(bid, 'param', _tr('控制点 {pt} = {get}（手动）', pt=pt, get=body.get('value')))
        return {'points': _points(st)}

    # ---------------- 场景库 ----------------
    @app.get('/api/scenes')
    async def scene_list():
        return scenes.list_scenes()

    @app.get('/api/scenes/{sid}')
    async def scene_get(sid: str):
        s = scenes.get_scene(sid)
        if not s:
            raise HTTPException(404, _tr('没有场景 {sid}', sid=sid))
        return s

    @app.get('/api/scenes/{sid}/plant')
    async def scene_plant(sid: str, reference: bool = False):
        s = scenes.get_scene(sid)
        if not s:
            raise HTTPException(404, _tr('没有场景 {sid}', sid=sid))
        return scenes.scene_plant(s, with_reference=reference)

    @app.post('/api/scenes/{sid}/score')
    async def scene_score(sid: str, request: Request, body: dict = Body(default={})):
        need(request, 'engineer')
        s = scenes.get_scene(sid)
        if not s:
            raise HTTPException(404, _tr('没有场景 {sid}', sid=sid))
        t0 = time.time()
        loop = asyncio.get_running_loop()
        r = await loop.run_in_executor(None, scoring.score_scene, s, body.get('program'))
        r['wall_s'] = round(time.time() - t0, 2)
        return r

    # ---------------- 实时泵：运行中的工厂按墙钟推进控制单元，三维里动作连续 ----------------
    state = {'task': None}

    async def pump_loop():
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.04)
            now = time.perf_counter()
            el, last = min(0.25, now - last), now
            rts = list(getattr(mgr, 'rts', {}).values()) + list((getattr(mgr, 'sandboxes', None) or {}).values())
            for rt in rts:
                p = getattr(rt, 'plant', None)
                if p is None or p.paused or getattr(rt, 'asleep', False):
                    continue
                if p.speed > 20:                 # 高倍速时不逐帧推进（整厂步里一次补齐）
                    continue
                for st in list(p.stations.values()):
                    if getattr(st, 'kind', '') == 'cell':
                        try:
                            st.pump(el * p.speed)
                        except Exception:
                            log.exception(_tr('控制单元实时推进出错'))

    def start_pump():
        if state['task'] is None or state['task'].done():
            state['task'] = asyncio.get_running_loop().create_task(pump_loop())

    @app.middleware('http')
    async def _pump_starter(request, call_next):
        """第一个 HTTP 请求时启动实时泵（FastAPI 新版本没有 startup 事件钩子可用）。"""
        if state['task'] is None or state['task'].done():
            start_pump()
        return await call_next(request)
