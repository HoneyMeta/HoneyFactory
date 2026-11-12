"""PLC 层 REST 接口。在 server.py 里 `plc_api.register(app, mgr)`。

4.3 起 PLC 是工厂里独立的 `plc` 块（vfactory/plc/station.py 的 PlcStation），信号线把它和设备连起来。
编程对象（下面的 bid）是 PLC 块编号；传控制单元/设备编号时自动转到控制它的 PLC 块；旧的"单元内置 PLC"（没迁移的）也还能用。
PLC 对象约定：station.plc（PlcRuntime 或 ExternalPlc，都有 scan(inputs, dt) -> outputs）；I/O 表：station.cell_def['io']。
本模块负责：程序的保存（data/plc/<工厂>/cells/<PLC 块>.json；迁移来的 PLC 第一次找不到时读原控制单元的文件）、编译、下载、
工厂重置/重建后把已下载的程序装回去、外接 PLC 驱动的启停。没有 PLC 时可以用 bid = "_sandbox"：一个独立的练习 PLC。

接口（都在 /api/p/{pid}/cells/{bid} 下，bid = PLC 块编号）：
  GET  /program                      {program, io, online_hash, project_hash, same, plc}
  PUT  /program                      保存工程程序（不下载）
  POST /program/compile              {program?} → {ok, errors:[{line|rung, msg}], warnings, symbols, lines}
  POST /program/download             {program?, cold?, run?} → 编译 + 下载（运行中下载保留变量值，cold=true 冷启动）
  GET  /online                       在线值：状态、变量、强制、I/O、LD 元件通断、梯级能流、扫描时间
  POST /plc                          {action: run|stop|step|breakpoint|clear_breakpoints|force|unforce_all|write|reset, …}
  POST /program/import               {xml, save?} PLCopen XML → 程序
  GET  /program/export.xml           PLCopen XML 文件
  GET  /plc/external                 外接配置 + 默认映射 + 状态
  PUT  /plc/external                 {mode: internal|external, protocol, endpoint, port, unit, rack, slot, mapping, realtime}
  GET  /api/p/{pid}/plc/cells        本工厂所有 PLC 块（含状态、接的设备）和 HMI 块
  GET  /api/p/{pid}/plc/status       每台 PLC 的 {bid, name, state, label, halt, bps, devices}（断点面板、暂停提示条用）
  GET  /api/p/{pid}/plc/{bid}/io     PLC 通道表 [{ch, dir, point, device, device_name, value, forced, name, type, addr, link}]
  GET  /api/p/{pid}/hmi              画面列表
  GET/PUT/DELETE /api/p/{pid}/hmi/{id}
"""
from ..i18n import _tr
import asyncio
import copy
import logging
import time

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from . import store
from .external import PROTOCOLS, ExternalPlc, merged_mapping
from .plcopen import ImportError_, export_xml, import_xml
from .program import blank_program, compile_program, program_hash
from .runtime import PlcRuntime
from .demo import SANDBOX_DEMO_HMI, SANDBOX_DEMO_PROGRAM, auto_screen, cell_screens, seed_screens

log = logging.getLogger('vfactory.plc')
STATE_CN_PLC = {'RUN': '运行', 'STOP': '停止', 'HALT': '暂停', 'ERROR': '错误'}
SANDBOX = '_sandbox'
SANDBOX_IO = [
    {'name': 'Start', 'dir': 'in', 'type': 'BOOL', 'addr': '%I0.0', 'comment': '启动按钮（常开）'},
    {'name': 'Stop', 'dir': 'in', 'type': 'BOOL', 'addr': '%I0.1', 'comment': '停止按钮（按下为 1）'},
    {'name': 'Sensor1', 'dir': 'in', 'type': 'BOOL', 'addr': '%I0.2', 'comment': '光电传感器'},
    {'name': 'Sensor2', 'dir': 'in', 'type': 'BOOL', 'addr': '%I0.3', 'comment': '光电传感器'},
    {'name': 'Level', 'dir': 'in', 'type': 'INT', 'addr': '%IW2', 'comment': '模拟量输入'},
    {'name': 'Motor', 'dir': 'out', 'type': 'BOOL', 'addr': '%Q0.0', 'comment': '电机接触器'},
    {'name': 'Lamp_Run', 'dir': 'out', 'type': 'BOOL', 'addr': '%Q0.1', 'comment': '运行指示灯（绿）'},
    {'name': 'Lamp_Fault', 'dir': 'out', 'type': 'BOOL', 'addr': '%Q0.2', 'comment': '故障指示灯（红）'},
    {'name': 'Valve', 'dir': 'out', 'type': 'BOOL', 'addr': '%Q0.3', 'comment': '电磁阀'},
    {'name': 'Display', 'dir': 'out', 'type': 'INT', 'addr': '%QW2', 'comment': '数码管显示'},
]


def is_cell(st):
    return getattr(st, 'kind', '') == 'cell' or (getattr(st, 'cfg', None) or {}).get('type') == 'cell' or hasattr(st, 'sim')


def is_plc(st):
    return getattr(st, 'kind', '') == 'plc'


def is_target(st):
    """能编程的对象：PLC 块；还没迁移的"自带 PLC 的控制单元"。"""
    if is_plc(st):
        return True
    return is_cell(st) and (getattr(st, 'plc', None) is not None or 'plc' in cell_def_of(st))


def targets(plant):
    return [st for st in plant.all_stations() if is_target(st)]


def target_of(plant, bid):
    """bid 是 PLC 块 → 它；是被 PLC 控制的设备（控制单元）→ 控制它的第一台 PLC；否则 None。"""
    st = plant.find(bid)
    if st is None:
        return None
    if is_target(st):
        return st
    from .station import controllers
    c = controllers(st)
    if not c:
        from .migrate import plc_of_cell
        p = plc_of_cell(plant, bid)
        c = [p] if p is not None else []
    return c[0] if c else None


def device_cells(plant, st):
    """PLC 块接的控制单元（HMI 面板按钮、场景、部件信息用）。"""
    if not is_plc(st):
        return [st] if is_cell(st) else []
    out = []
    for d in getattr(st, 'devices', None) or []:
        x = plant.find(d)
        if x is not None and is_cell(x):
            out.append(x)
    return out


def saved_of(pid, st):
    """PLC 的保存记录（程序、下载、运行状态、外接配置）。迁移来的 PLC 块还没有自己的记录时读原控制单元的。"""
    d = store.load(pid, 'cells', st.id, None)
    if d is None:
        mf = (getattr(st, 'cfg', None) or {}).get('migrated_from') if is_plc(st) else None
        if mf:
            d = store.load(pid, 'cells', mf, None)
    return d or {}


def upd(pid, st, **kv):
    if store.load(pid, 'cells', st.id, None) is None:
        old = saved_of(pid, st)
        if old:
            store.save(pid, 'cells', st.id, old)
    return store.update(pid, 'cells', st.id, **kv)


_NC_TYPES = {'estop'}


def io_rows(cd):
    """I/O 表加两列：触点 contact（NO 常开 / NC 常闭）和 idle（没人操作、没有零件时的值 0/1）。
    控制层在 I/O 条目里写了 contact / idle 就用它的；没写时按部件推断：急停、勾了"常闭"的按钮和传感器是常闭，静止为 1。"""
    comps = {c.get('id'): c for c in cd.get('components') or []}
    out = []
    for e in cd.get('io') or []:
        e = dict(e)
        if e.get('dir') == 'in' and (e.get('type') or 'BOOL').upper() == 'BOOL':
            c = comps.get(e.get('comp')) or comps.get(e.get('point')) or {}
            nc = c.get('type') in _NC_TYPES or bool((c.get('params') or {}).get('nc'))
            e.setdefault('contact', 'NC' if nc else 'NO')
            e.setdefault('idle', 1 if e['contact'] == 'NC' else 0)
        out.append(e)
    return out


def cell_def_of(st):
    d = getattr(st, 'cell_def', None)
    if isinstance(d, dict):
        return d
    cfg = getattr(st, 'cfg', None) or {}
    return cfg.get('cell') or (cfg.get('params') or {}).get('cell') or {}


class _Sandbox:
    """没有控制单元时的练习 PLC。"""
    kind = 'sandbox'

    def __init__(self, io):
        self.id = SANDBOX
        self.name = _tr('练习 PLC')
        self.cell_def = {'io': io, 'plc': {'mode': 'internal', 'scan_ms': 20}}
        self.plc = PlcRuntime(None, scan_ms=20, io=io)
        # 现场值：没有设备，输入默认都是 0；“写入”输入等于拨动现场开关，强制取消后回到现场值
        from .compiler import zero
        self.field = {e['name']: zero((e.get('type') or 'BOOL').upper()) for e in io if e.get('dir') == 'in'}


class PlcService:
    def __init__(self, mgr):
        self.mgr = mgr
        self.seen = {}               # pid → id(plant)：工厂重建后要把程序装回去
        self.sandboxes = {}          # pid → _Sandbox
        self.task = None
        self.ext_running = {}        # (pid, bid) → ExternalPlc（驱动在跑的）
        self.plc_seen = {}           # (pid, bid) → id(station.plc)：控制单元换了 PLC 对象就重新装程序

    # ------------------------------------------------ 查找
    def rt(self, pid):
        return self.mgr.get(pid)

    def cell(self, pid, bid):
        """→ (station, cell_def)。"""
        self.ensure_task()
        if bid == SANDBOX:
            sb = self.sandbox(pid)
            return sb, sb.cell_def
        rt = self.rt(pid)
        self.reconcile(pid, rt)
        st = target_of(rt.plant, bid)
        if st is None:
            raise HTTPException(404, _tr('没有 PLC {bid}', bid=bid) if rt.plant.find(bid) is None else _tr('{bid} 没有接 PLC', bid=bid))
        return st, cell_def_of(st)

    def sandbox(self, pid):
        self.rt(pid)
        sb = self.sandboxes.get(pid)
        if sb is None:
            saved = store.load(pid, 'cells', SANDBOX, {}) or {}
            sb = _Sandbox(saved.get('sandbox_io') or SANDBOX_IO)
            # 没下载过就装示范程序并运行（新装的系统打开就有东西可看）
            r = sb.plc.load(saved.get('downloaded') or SANDBOX_DEMO_PROGRAM, cold=True)
            if r['ok'] and saved.get('run', True):
                sb.plc.state = 'RUN'
            self.sandboxes[pid] = sb
        return sb

    def plc_of(self, pid, st, cd):
        p = getattr(st, 'plc', None)
        if p is None:
            p = self._make(pid, st, cd)
            st.plc = p
        return p

    def _make(self, pid, st, cd):
        saved = saved_of(pid, st)
        io = cd.get('io') or []
        scan_ms = float((cd.get('plc') or {}).get('scan_ms') or 20)
        mode = saved.get('mode') or (cd.get('plc') or {}).get('mode') or 'internal'
        if mode == 'external':
            cfg = saved.get('external') or (cd.get('plc') or {}).get('external') or {}
            return ExternalPlc(cfg, io, scan_ms=scan_ms)
        prog = saved.get('downloaded')
        if prog is None:
            cp = (cd.get('plc') or {}).get('program')
            prog = cp if isinstance(cp, dict) else None
        p = PlcRuntime(prog, scan_ms=scan_ms, io=io, autorun=saved.get('run', True))
        return p

    # ------------------------------------------------ 工厂重建后恢复
    def reconcile(self, pid, rt=None):
        """工厂重建、控制单元重建（换了 station.plc 对象）之后，把已下载的程序、运行状态、外接配置装回去。"""
        rt = rt or self.mgr.rts.get(pid)
        if rt is None:
            return
        plant_changed = self.seen.get(pid) != id(rt.plant)
        self.seen[pid] = id(rt.plant)
        for st in targets(rt.plant):
            k = (pid, st.id)
            cur = getattr(st, 'plc', None)
            if not plant_changed and cur is not None and self.plc_seen.get(k) == id(cur):
                continue
            cd = cell_def_of(st)
            saved = saved_of(pid, st)
            mode = saved.get('mode') or (cd.get('plc') or {}).get('mode') or 'internal'
            if mode == 'external':
                if not isinstance(cur, ExternalPlc):
                    cur = self._make(pid, st, cd)
                    st.plc = cur
                self._start_ext(pid, st.id, cur, rt)
            else:
                dl = saved.get('downloaded')
                if cur is None or (dl is not None and not isinstance(cur, PlcRuntime)):
                    st.plc = cur = self._make(pid, st, cd)
                elif dl is not None:
                    if cur.prog is None or cur.prog.hash != program_hash(dl):
                        r = cur.load(dl, cold=True, io=cd.get('io') or [])
                        if r['ok'] and saved.get('run', True):
                            cur.run()
                    elif saved.get('run', True) and cur.state == 'STOP':
                        cur.run()                    # 单元重建后（例如改了单元定义）恢复运行
                elif isinstance(cur, PlcRuntime) and cur.prog is not None and cur.state == 'STOP' and saved.get('run', True)                         and isinstance((cd.get('plc') or {}).get('program'), dict):
                    cur.run()                        # 单元定义自带的程序：新装系统打开就在运行
            self.plc_seen[k] = id(st.plc) if getattr(st, 'plc', None) is not None else None
        # 旧对象上的外接驱动停掉
        for (p, b), ext in list(self.ext_running.items()):
            if p == pid and ext is not getattr(rt.plant.find(b), 'plc', None):
                asyncio.ensure_future(ext.stop())
                self.ext_running.pop((p, b), None)

    def _start_ext(self, pid, bid, ext, rt):
        if self.ext_running.get((pid, bid)) is ext:
            return
        old = self.ext_running.pop((pid, bid), None)

        async def go():
            if old is not None:
                await old.stop()
            try:
                await ext.start({'mgr': self.mgr, 'rt': rt, 'pid': pid, 'bid': bid})
            except Exception as e:
                ext.status.update(connected=False, error=str(e))
                log.warning(_tr('外接 PLC %s/%s 启动失败：%s'), pid, bid, e)
        self.ext_running[(pid, bid)] = ext
        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(go())
        except RuntimeError:
            pass

    # ------------------------------------------------ 后台：练习 PLC 实时扫描、工厂重建检测
    def ensure_task(self):
        if self.task is None or self.task.done():
            try:
                self.task = asyncio.get_running_loop().create_task(self._loop())
            except RuntimeError:
                pass

    async def _loop(self):
        last = time.perf_counter()
        n = 0
        while True:
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            dt, last = now - last, now
            for sb in list(self.sandboxes.values()):
                try:
                    sb.plc.cycle(sb.field, min(dt, 0.5))
                except Exception:
                    log.exception(_tr('练习 PLC 扫描出错'))
            n += 1
            if n % 25 == 0:
                for pid in list(self.mgr.rts):
                    try:
                        self.reconcile(pid)
                    except Exception:
                        log.exception(_tr('PLC 恢复程序失败'))


def _scene_of(svc, pid, cd, st=None):
    """PLC 对应的实训场景：单元定义里的 scene（PLC 块看它接的控制单元），或者场景生成的工厂（学生沙箱）模型顶层的 scene。"""
    sid = cd.get('scene')
    if not sid and st is not None and is_plc(st):
        for c in device_cells(st.plant, st):
            sid = cell_def_of(c).get('scene')
            if sid:
                break
    if not sid:
        rt = svc.mgr.rts.get(pid)
        sid = (getattr(rt, 'cfg', None) or {}).get('scene') if rt is not None else None
    if not sid:
        return None
    try:
        from ..control import scenes
        return scenes.get_scene(sid)
    except Exception:                         # noqa: BLE001
        return None


def _program_of(svc, pid, st, cd):
    saved = saved_of(pid, st)
    prog = saved.get('program')
    if prog is None:
        p = getattr(st, 'plc', None)
        if isinstance(p, PlcRuntime) and p.prog is not None:
            prog = p.prog.program
        else:
            cp = (cd.get('plc') or {}).get('program')
            prog = copy.deepcopy(cp) if isinstance(cp, dict) else blank_program('LD')
    return prog


def _norm_program(body):
    if not isinstance(body, dict):
        raise HTTPException(400, _tr('程序格式不对'))
    p = dict(body)
    p['lang'] = str(p.get('lang') or 'LD').upper()
    p.setdefault('id', 'main')
    p.setdefault('name', _tr('主程序'))
    p.setdefault('vars', [])
    if p['lang'] == 'LD' and not isinstance(p.get('source'), (dict, str)):
        p['source'] = {'rungs': []}
    if p['lang'] == 'ST' and not isinstance(p.get('source'), str):
        p['source'] = ''
    return p


def _coach(mgr, pid, what, **kw):
    """4.5 运行日志（vfactory/teach/coach.py）：下载、运行/停止记一笔（没人看日志时什么都不做）。"""
    try:
        from ..teach import coach
    except Exception:                       # noqa: BLE001
        return
    coach.hook(mgr, pid, what, **kw)


def register(app, mgr):
    svc = PlcService(mgr)
    app.state.plc = svc
    C = '/api/p/{pid}/cells/{bid}'

    @app.get('/api/p/{pid}/plc/cells')
    async def cells(pid: str):
        rt = svc.rt(pid)
        svc.ensure_task()
        svc.reconcile(pid, rt)
        out = []
        for st in targets(rt.plant):
            cd = cell_def_of(st)
            p = getattr(st, 'plc', None)
            devs = list(getattr(st, 'devices', None) or []) if is_plc(st) else [st.id]
            out.append({'id': st.id, 'name': st.name, 'kind': 'plc' if is_plc(st) else 'cell', 'io': len(cd.get('io') or []),
                        'plc': p.info() if p is not None else None, 'devices': devs,
                        'device_names': {d: getattr(rt.plant.find(d), 'name', d) for d in devs},
                        'cells': [c.id for c in device_cells(rt.plant, st)], 'migrated_from': cd.get('migrated_from')})
        hmis = []
        for st in rt.plant.all_stations():
            if getattr(st, 'kind', '') == 'hmi':
                hmis.append({'id': st.id, 'name': st.name, 'plc': st.plc_id() if hasattr(st, 'plc_id') else '', 'screen': (st.cfg or {}).get('screen') or ''})
        sb = svc.sandboxes.get(pid)
        return {'cells': out, 'plcs': out, 'hmis': hmis, 'sandbox': {'id': SANDBOX, 'name': _tr('练习 PLC（不接设备）'), 'plc': sb.plc.info() if sb else None}}

    @app.get(C + '/program')
    async def get_program(pid: str, bid: str):
        st, cd = svc.cell(pid, bid)
        p = svc.plc_of(pid, st, cd)
        prog = _program_of(svc, pid, st, cd)
        online_hash = p.prog.hash if isinstance(p, PlcRuntime) and p.prog else None
        ph = program_hash(prog)
        saved = saved_of(pid, st)
        return {'program': prog, 'io': io_rows(cd), 'project_hash': ph, 'online_hash': online_hash, 'same': online_hash == ph,
                'plc': p.info(), 'scan_ms': getattr(p, 'scan_ms', 20), 'mode': 'external' if isinstance(p, ExternalPlc) else 'internal',
                'saved_at': saved.get('saved_at'), 'cell': {'id': st.id, 'name': getattr(st, 'name', st.id)}}

    @app.put(C + '/program')
    async def put_program(pid: str, bid: str, body: dict = Body(...)):
        st, cd = svc.cell(pid, bid)
        prog = _norm_program(body.get('program', body) if isinstance(body.get('program'), dict) else body)
        upd(pid, st, program=prog, saved_at=time.strftime('%Y-%m-%d %H:%M:%S'))
        return {'ok': True, 'project_hash': program_hash(prog)}

    @app.post(C + '/program/compile')
    async def compile_(pid: str, bid: str, body: dict = Body(default={})):
        st, cd = svc.cell(pid, bid)
        prog = _norm_program(body['program']) if isinstance(body.get('program'), dict) else _program_of(svc, pid, st, cd)
        c = compile_program(prog, cd.get('io') or [])
        r = c.result()
        if c.lang == 'LD':
            r['source'] = c.program.get('source')        # 补齐了元素 id
        return r

    @app.post(C + '/program/download')
    async def download(pid: str, bid: str, body: dict = Body(default={})):
        st, cd = svc.cell(pid, bid)
        p = svc.plc_of(pid, st, cd)
        if isinstance(p, ExternalPlc):
            raise HTTPException(400, _tr('这台 PLC 现在是外接 PLC，先在“外接 PLC”里切回内置 PLC'))
        prog = _norm_program(body['program']) if isinstance(body.get('program'), dict) else _program_of(svc, pid, st, cd)
        was, had_prog = p.state, p.prog is not None
        r = p.load(prog, cold=bool(body.get('cold')), io=cd.get('io') or [])
        if not r['ok']:
            _coach(mgr, pid, 'download', result=r, program=prog)
            return r
        run = body.get('run')
        if run is None:                          # 运行中下载继续运行；第一次下载自动运行；停止状态下载保持停止
            run = was in ('RUN', 'HALT') or not had_prog
        if run:
            p.run()
        upd(pid, st, program=p.prog.program, downloaded=p.prog.program, run=p.state == 'RUN',
                     downloaded_at=time.strftime('%Y-%m-%d %H:%M:%S'), mode='internal')
        r['state'] = p.state
        if p.prog.lang == 'LD':
            r['source'] = p.prog.program.get('source')
        _coach(mgr, pid, 'download', result=r, program=p.prog.program)
        return r

    @app.get(C + '/online')
    async def online(pid: str, bid: str, ld: int = 1):
        st, cd = svc.cell(pid, bid)
        p = svc.plc_of(pid, st, cd)
        o = p.online(ld=bool(ld))
        extra = {e['name']: e for e in io_rows(cd)}
        for r in o.get('io') or []:
            x = extra.get(r.get('name')) or {}
            if 'contact' in x:
                r['contact'], r['idle'] = x['contact'], x['idle']
        o['label'] = p.label() if hasattr(p, 'label') else ''
        return o

    @app.get(C + '/trace')
    async def trace(pid: str, bid: str, seconds: float = 30):
        """I/O 时序（逻辑分析仪）：最近 seconds 秒（最多 120）里每个 I/O 的变化，时间是 PLC 时钟（毫秒，跟仿真时间走）。"""
        st, cd = svc.cell(pid, bid)
        p = svc.plc_of(pid, st, cd)
        tr = getattr(p, 'tracer', None)
        rows = {e['name']: e for e in io_rows(cd)}
        if tr is None:
            return {'names': [], 'signals': [], 'now_ms': 0, 'start_ms': 0, 'events': []}
        w = tr.window(max(1.0, min(120.0, seconds)))
        w['signals'] = [{'name': n, 'dir': rows.get(n, {}).get('dir'), 'type': rows.get(n, {}).get('type') or 'BOOL', 'addr': rows.get(n, {}).get('addr'),
                         'comment': rows.get(n, {}).get('comment') or '', 'contact': rows.get(n, {}).get('contact')} for n in w['names']]
        return w

    @app.get(C + '/timing_spec')
    async def timing_spec(pid: str, bid: str):
        """期望时序：控制单元来自实训场景时，从场景的自动测试步骤生成（按钮什么时候按、输出什么时候应该是多少）。"""
        st, cd = svc.cell(pid, bid)
        sc = _scene_of(svc, pid, cd, st)
        if not sc:
            return {'scene': None}
        t = sc.get('test') or {}
        presses, checks = [], []
        for x in t.get('steps') or []:
            if x.get('press'):
                presses.append({'sig': x['press'], 't': float(x.get('t', 0)), 'hold': float(x.get('hold', 0.3) or 0.3)})
            elif isinstance(x.get('check'), dict) and x['check'].get('out'):
                c = x['check']
                checks.append({'sig': c['out'], 't': float(x.get('t', 0)), 'hold': float(x.get('hold', 0) or 0), 'eq': c.get('eq'),
                               'desc': x.get('desc') or '', 'key': x.get('key')})
        return {'scene': sc.get('id'), 'name': sc.get('name'), 'duration': t.get('duration'), 'presses': presses, 'checks': checks}

    @app.get(C + '/reference')
    async def reference(pid: str, bid: str, request: Request):
        """参考答案（只读对比用）：只给老师、管理员、工程师。"""
        u = getattr(request.state, 'user', None) or {}
        if u.get('role') not in ('admin', 'engineer', 'teacher'):
            raise HTTPException(403, _tr('参考答案只对老师开放'))
        st, cd = svc.cell(pid, bid)
        sc = _scene_of(svc, pid, cd, st)
        if not sc or not sc.get('reference'):
            raise HTTPException(404, _tr('这台 PLC 不是从实训场景来的，没有参考答案'))
        ref = sc['reference']
        progs = [dict(ref[k], lang=ref[k].get('lang') or ('LD' if k == 'ld' else 'ST')) for k in ('ld', 'st') if isinstance(ref.get(k), dict)]
        return {'scene': sc.get('id'), 'name': sc.get('name'), 'programs': progs}

    @app.get('/api/p/{pid}/plc/status')
    async def plc_status(pid: str):
        """本工厂所有 PLC 的状态和断点（外壳的"断点"面板、断点暂停提示条用）。"""
        rt = svc.rt(pid)
        svc.ensure_task()
        svc.reconcile(pid, rt)
        out = []
        items = [(st, cell_def_of(st)) for st in targets(rt.plant)]
        sb = svc.sandboxes.get(pid)
        if sb is not None:
            items.append((sb, sb.cell_def))
        for st, cd in items:
            p = getattr(st, 'plc', None)
            if p is None:
                continue
            info = p.info()
            prog = getattr(p, 'prog', None)
            bps = []
            for ln in info.get('bps') or []:
                if prog is not None and prog.lang == 'LD':
                    rungs = ((prog.program or {}).get('source') or {}).get('rungs') or []
                    cm = (rungs[ln - 1].get('comment') or '') if 0 < ln <= len(rungs) and isinstance(rungs[ln - 1], dict) else ''
                    bps.append({'rung': ln - 1, 'label': _tr('梯级 {ln}', ln=ln) + (_tr('：{cm}', cm=cm) if cm else '')})
                else:
                    src = ((prog.program or {}).get('source') if prog else '') or ''
                    lines = src.split('\n') if isinstance(src, str) else []
                    txt = lines[ln - 1].strip() if 0 < ln <= len(lines) else ''
                    bps.append({'line': ln, 'label': _tr('第 {ln} 行', ln=ln) + (_tr('：{v}', v=txt[:40]) if txt else '')})
            devs = list(getattr(st, 'devices', None) or []) if is_plc(st) else ([] if st.id == SANDBOX else [st.id])
            out.append({'bid': st.id, 'name': getattr(st, 'name', st.id) if st.id != SANDBOX else _tr('练习 PLC（不接设备）'), 'state': info.get('state'),
                        'label': info.get('label') or '', 'halt': info.get('halt'), 'lang': info.get('lang'), 'bps': bps, 'error': info.get('error'),
                        'devices': devs})
        return {'plcs': out, 'cells': out, 'halted': [c for c in out if c['state'] == 'HALT']}

    @app.get('/api/p/{pid}/plc/{bid}/io')
    async def plc_io(pid: str, bid: str):
        """PLC 通道表：每一路接到哪台设备的哪个点、现在的值、是否强制（对象面板、跳转用）。"""
        st, cd = svc.cell(pid, bid)
        p = svc.plc_of(pid, st, cd)
        from .migrate import ch_of
        on = {r.get('name'): r for r in (p.online(ld=False).get('io') or [])}
        plant = svc.rt(pid).plant if st.id != SANDBOX else None
        rows = []
        for e in cd.get('io') or []:
            r = on.get(e.get('name')) or {}
            dev = e.get('device') or (st.id if is_cell(st) else None)
            d = plant.find(dev) if plant is not None and dev else None
            rows.append({'ch': e.get('ch') or ch_of(e.get('addr')) or '', 'dir': e.get('dir'), 'point': e.get('point') or e.get('name'),
                         'device': dev, 'device_name': getattr(d, 'name', dev) if dev else '', 'value': r.get('value'),
                         'forced': bool(r.get('forced')), 'name': e.get('name'), 'type': (e.get('type') or 'BOOL').upper(),
                         'addr': e.get('addr'), 'link': e.get('link'), 'comment': e.get('comment') or ''})
        return rows

    @app.post(C + '/plc')
    async def plc_action(pid: str, bid: str, body: dict = Body(...)):
        st, cd = svc.cell(pid, bid)
        p = svc.plc_of(pid, st, cd)
        a = str(body.get('action') or '')
        err = ''
        extra = {}
        if isinstance(p, ExternalPlc):
            if a == 'force':
                err = p.force(body.get('name'), body.get('value'))
            elif a == 'unforce_all':
                p.unforce_all()
            else:
                raise HTTPException(400, _tr('外接 PLC 只能强制 I/O；运行/停止请在外部 PLC 上操作'))
        elif a == 'run':
            err = p.run()
        elif a == 'stop':
            err = p.stop()
        elif a == 'step':
            err = p.step(body.get('kind') or 'scan')
        elif a == 'breakpoint':
            if body.get('clear'):
                p.clear_breakpoints()
            else:
                ln = body.get('line')
                if ln is None and body.get('rung') is not None:
                    ln = int(body['rung']) + 1
                if ln is None:
                    raise HTTPException(400, _tr('断点要给 line（ST 行号）或 rung（梯级序号，从 0 开始）'))
                on = body.get('on', True)
                if on == 'toggle':
                    on = int(ln) not in p.bps
                got = p.set_breakpoint(ln, bool(on))
                if got is None and on:
                    err = _tr('这一行后面没有可以停的语句')
                extra['line'] = got
        elif a == 'clear_breakpoints':
            p.clear_breakpoints()
        elif a == 'force':
            err = p.force(body.get('name'), body.get('value'))
        elif a == 'unforce_all':
            p.unforce_all()
        elif a == 'write':
            sb = svc.sandboxes.get(pid) if bid == SANDBOX else None
            nm = next((k for k in (sb.field if sb else {}) if k.upper() == str(body.get('name') or '').upper()), None)
            if nm is not None:
                from .runtime import _coerce
                try:
                    sb.field[nm] = _coerce('BOOL' if isinstance(sb.field[nm], bool) else 'INT', body.get('value'))
                except (TypeError, ValueError):
                    raise HTTPException(400, _tr('值 {get} 格式不对', get=body.get("value")))
            else:
                err = p.write(body.get('name'), body.get('value'))
        elif a == 'reset':
            p.reset(cold=body.get('cold', True) is not False)
        elif a == 'reset_stats':
            p.reset_stats()
        elif a == 'reset_program':
            # 恢复初始程序：丢掉保存/下载的程序，回到单元定义自带的（练习 PLC 回到示范程序），冷启动并运行
            cur = saved_of(pid, st)
            for k in ('program', 'downloaded', 'run', 'saved_at', 'downloaded_at'):
                cur.pop(k, None)
            store.save(pid, 'cells', st.id, cur)
            cp = (cd.get('plc') or {}).get('program')
            init = SANDBOX_DEMO_PROGRAM if bid == SANDBOX else cp if isinstance(cp, dict) else blank_program('LD')
            r = p.load(init, cold=True, io=cd.get('io') or [])
            if not r['ok']:
                raise HTTPException(400, _tr('初始程序编译不通过：') + _tr('；').join(e['msg'] for e in r['errors'][:3]))
            p.run() if isinstance(cp, dict) or bid == SANDBOX else p.stop()
        else:
            raise HTTPException(400, _tr('不认识的操作 {a}（run / stop / step / breakpoint / force / write / reset）', a=a))
        if err:
            raise HTTPException(400, err)
        if a in ('run', 'stop') and isinstance(p, PlcRuntime):
            upd(pid, st, run=p.state == 'RUN')
        if bid != SANDBOX:
            _coach(mgr, pid, 'plc', action=a, body=body)
        return {'ok': True, **extra, **p.online(ld=False)}

    @app.get(C + '/explain')
    async def explain_(pid: str, bid: str, rung: int = -1, line: int = 0):
        """4.5"解释这个梯级"：梯级 rung（从 0 起）或 ST 第 line 行现在的能流/条件值（用 PLC 里正在运行的程序和实时值）。"""
        from . import explain as X
        st, cd = svc.cell(pid, bid)
        p = svc.plc_of(pid, st, cd)
        if not isinstance(p, PlcRuntime) or p.prog is None:
            return {'lines': [_tr('PLC 里还没有程序：下载以后才能看实时能流。')], 'summary': _tr('还没下载'), 'hash': None}
        snap = X.snapshot(p)
        io = io_rows(cd)
        r = X.explain_rung(p.prog.program, snap, io, rung) if rung >= 0 else X.explain_line(p.prog.program, snap, io, line)
        r['hash'] = p.prog.hash
        r['state'] = p.state
        if p.state != 'RUN':
            r['lines'] = [_tr('注意：PLC 现在是 {get}，下面是停下来那一刻的值。', get=STATE_CN_PLC.get(p.state, p.state))] + list(r.get('lines') or [])
        return r

    @app.post(C + '/program/import')
    async def import_(pid: str, bid: str, request: Request):
        st, cd = svc.cell(pid, bid)
        raw = await request.body()
        save = False
        text = raw.decode('utf-8', 'replace')
        if (request.headers.get('content-type') or '').startswith('application/json'):
            import json
            try:
                j = json.loads(text)
            except ValueError:
                raise HTTPException(400, _tr('请求不是合法的 JSON'))
            text = j.get('xml') or ''
            save = bool(j.get('save'))
        try:
            prog, globals_, warns = import_xml(text)
        except ImportError_ as e:
            raise HTTPException(400, str(e))
        except Exception as e:                    # noqa: BLE001  任何文件都不该让接口 500
            log.exception(_tr('PLCopen 导入失败'))
            raise HTTPException(400, _tr('这个文件没能导入（{v}），请确认是 PLCopen XML（TC6）格式', v=type(e).__name__))
        io_names = {e.get('name', '').upper() for e in cd.get('io') or []}
        extra = [g for g in globals_ if (g.get('name') or '').upper() not in io_names]
        if extra:
            for g in extra:
                g.pop('section', None)
            prog['vars'] = list(prog.get('vars') or []) + extra
            warns.append(_tr('文件里的全局变量 {join} 不在这台 PLC 的 I/O 表里，已加到程序变量表', join=_tr('、').join(g["name"] for g in extra)))
        c = compile_program(prog, cd.get('io') or [])
        if save:
            upd(pid, st, program=c.program, saved_at=time.strftime('%Y-%m-%d %H:%M:%S'))
        return {'program': c.program, 'warnings': warns, 'compile': c.result()}

    @app.get(C + '/program/export.xml')
    async def export_(pid: str, bid: str):
        st, cd = svc.cell(pid, bid)
        prog = _program_of(svc, pid, st, cd)
        p = getattr(st, 'plc', None)
        prog = dict(prog, scan_ms=getattr(p, 'scan_ms', 20))
        xml = export_xml(prog, cd.get('io') or [], name=f'{pid}-{st.id}')
        fn = f'{pid}-{st.id}-plc.xml'
        return Response(xml, media_type='application/xml', headers={'Content-Disposition': f'attachment; filename="{fn}"'})

    # ------------------------------------------------ 外接 PLC
    @app.get(C + '/plc/external')
    async def get_ext(pid: str, bid: str, protocol: str = ''):
        st, cd = svc.cell(pid, bid)
        saved = saved_of(pid, st)
        p = svc.plc_of(pid, st, cd)
        cfg = saved.get('external') or (cd.get('plc') or {}).get('external') or {'protocol': 'modbus_server', 'port': 1502, 'unit': 1, 'realtime': True}
        io = cd.get('io') or []
        proto = protocol if protocol in PROTOCOLS else (cfg.get('protocol') or 'modbus_server')
        return {'mode': 'external' if isinstance(p, ExternalPlc) else 'internal', 'config': cfg, 'protocols': PROTOCOLS,
                'mapping': merged_mapping(io, proto, cfg if proto == cfg.get('protocol') else {}),
                'status': p.online()['external'] if isinstance(p, ExternalPlc) else None}

    @app.put(C + '/plc/external')
    async def put_ext(pid: str, bid: str, body: dict = Body(...)):
        st, cd = svc.cell(pid, bid)
        if bid == SANDBOX:
            raise HTTPException(400, _tr('练习 PLC 不能接外部 PLC'))
        mode = body.get('mode') or 'external'
        cfg = {k: v for k, v in body.items() if k != 'mode'}
        if cfg.get('protocol') and cfg['protocol'] not in PROTOCOLS:
            raise HTTPException(400, _tr('不支持的协议 {protocol}', protocol=cfg["protocol"]))
        rt = svc.rt(pid)
        old = getattr(st, 'plc', None)
        if isinstance(old, ExternalPlc):
            await old.stop()
            svc.ext_running.pop((pid, st.id), None)
        if mode == 'external':
            from .drivers import make_driver
            ext = ExternalPlc(cfg, cd.get('io') or [], scan_ms=float((cd.get('plc') or {}).get('scan_ms') or 20))
            try:
                make_driver(ext, {'mgr': mgr, 'rt': rt, 'pid': pid, 'bid': st.id})      # 先校验地址
            except Exception as e:
                raise HTTPException(400, str(e))
            upd(pid, st, mode='external', external=cfg)
            st.plc = ext
            try:
                await ext.start({'mgr': mgr, 'rt': rt, 'pid': pid, 'bid': st.id})
            except Exception as e:
                ext.status.update(connected=False, error=str(e))
            svc.ext_running[(pid, st.id)] = ext
            return {'ok': True, 'mode': 'external', 'status': ext.online()['external'], 'mapping': ext.mapping}
        upd(pid, st, mode='internal', external=cfg)
        st.plc = None
        p = svc.plc_of(pid, st, cd)
        return {'ok': True, 'mode': 'internal', 'plc': p.info()}

    # ------------------------------------------------ HMI
    def shipped(pid):
        """随模型/软件分发的画面（不含用户保存的）：控制单元定义里的 hmi、seeds、自动生成、练习 PLC 示范画面。"""
        rt = svc.rt(pid)
        out, seen = [], set()

        def add(s):
            if s['id'] not in seen:
                seen.add(s['id'])
                out.append(s)
        cells = targets(rt.plant)
        for st in cells:
            for s in cell_screens(st.id, cell_def_of(st)):
                add(s)
        ids = {st.id for st in cells}
        for s in seed_screens(pid):
            c = s.get('cell')
            if c not in ids and c != SANDBOX:                          # 画面绑定的是控制单元：改绑到控制它的 PLC
                t = target_of(rt.plant, c) if c else None
                if t is None:
                    continue                                           # 种子画面只在工厂里真有这个单元/PLC 时出现
                s['cell'] = t.id
            add(s)
        for st in cells:
            if not any(s.get('cell') == st.id for s in out):
                cd = cell_def_of(st)
                comps = list(cd.get('components') or [])
                for c in device_cells(rt.plant, st):
                    if c is not st:
                        comps += cell_def_of(c).get('components') or []
                add(auto_screen(st.id, getattr(st, 'name', st.id), cd.get('io') or [], comps))
        add(copy.deepcopy(SANDBOX_DEMO_HMI))
        return out

    @app.get('/api/p/{pid}/hmi')
    async def hmi_list(pid: str):
        sh = {s['id']: s for s in shipped(pid)}
        out, seen = [], set()
        for h in store.listing(pid, 'hmi'):
            d = store.load(pid, 'hmi', h, {}) or {}
            if d.get('deleted'):
                seen.add(h)
                continue
            src = 'user' if h not in sh else 'user+' + sh[h]['source']
            out.append({'id': h, 'name': d.get('name') or h, 'cell': d.get('cell'), 'widgets': len(d.get('widgets') or []), 'source': src})
            seen.add(h)
        for s in sh.values():
            if s['id'] not in seen:
                out.append({'id': s['id'], 'name': s['name'], 'cell': s.get('cell'), 'widgets': len(s.get('widgets') or []), 'source': s['source']})
        order = {'user': 0, 'model': 1, 'seed': 1, 'auto': 2, 'demo': 3}
        out.sort(key=lambda x: order.get(str(x['source']).split('+')[-1], 0))
        return {'items': out}

    @app.get('/api/p/{pid}/hmi/{hid}')
    async def hmi_get(pid: str, hid: str):
        if not store.safe_id(hid):
            raise HTTPException(400, _tr('画面编号只能包含字母、数字、下划线和短横线'))
        d = store.load(pid, 'hmi', hid)
        sh = next((s for s in shipped(pid) if s['id'] == hid), None)
        if d is not None and not d.get('deleted'):
            if sh:
                d['source'] = 'user+' + sh['source']
            return d
        if sh:
            return sh
        return {'id': hid, 'name': _tr('新画面'), 'cell': None, 'size': [960, 560], 'widgets': [], 'new': True}

    @app.put('/api/p/{pid}/hmi/{hid}')
    async def hmi_put(pid: str, hid: str, body: dict = Body(...)):
        svc.rt(pid)
        if not store.safe_id(hid):
            raise HTTPException(400, _tr('画面编号只能包含字母、数字、下划线和短横线'))
        ws = body.get('widgets') or []
        if not isinstance(ws, list) or len(ws) > 500:
            raise HTTPException(400, _tr('控件列表不对（最多 500 个）'))
        allowed = {'button', 'switch', 'lamp', 'number', 'input', 'trend', 'text', 'bar', 'rect'}
        for w in ws:
            if not isinstance(w, dict) or w.get('type') not in allowed:
                raise HTTPException(400, _tr('不认识的控件类型：{v}', v=w.get("type") if isinstance(w, dict) else w))
        d = {'id': hid, 'name': str(body.get('name') or hid)[:60], 'cell': body.get('cell'), 'size': body.get('size') or [960, 560],
             'widgets': ws, 'saved_at': time.strftime('%Y-%m-%d %H:%M:%S')}
        store.save(pid, 'hmi', hid, d)
        return d

    @app.post('/api/p/{pid}/hmi/_restore')
    async def hmi_restore(pid: str):
        """把隐藏掉的自带画面（单元自带、随软件、自动生成、示范）都显示回来。"""
        svc.rt(pid)
        n = 0
        for h in store.listing(pid, 'hmi'):
            if (store.load(pid, 'hmi', h, {}) or {}).get('deleted'):
                store.remove(pid, 'hmi', h)
                n += 1
        return {'ok': True, 'restored': n}

    @app.delete('/api/p/{pid}/hmi/{hid}')
    async def hmi_del(pid: str, hid: str):
        """删除用户保存的画面；随模型分发的画面删除后恢复成模型里的样子，再删一次才隐藏。"""
        if not store.safe_id(hid):
            raise HTTPException(400, _tr('画面编号不对'))
        d = store.load(pid, 'hmi', hid)
        sh = any(s['id'] == hid for s in shipped(pid))
        if d is not None and not d.get('deleted'):
            store.remove(pid, 'hmi', hid)
            return {'ok': True, 'restored': sh}
        if sh:
            store.save(pid, 'hmi', hid, {'id': hid, 'deleted': True})
            return {'ok': True, 'hidden': True}
        return {'ok': False}

    # 工厂启动后把已下载的程序装回控制单元（register 在 mgr.start() 之前调用）
    orig_launch = mgr.launch

    async def launch(pid):
        rt = await orig_launch(pid)
        svc.ensure_task()
        if rt is not None:
            try:
                svc.reconcile(pid, rt)
            except Exception:
                log.exception(_tr('PLC 恢复程序失败'))
        return rt
    mgr.launch = launch
    return svc
