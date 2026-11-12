"""PLC 和 HMI 作为独立设备（4.3）：工厂模型里的 `plc` / `hmi` 块。

信号线（link.kind == 'signal'）把设备和 PLC 连起来，一条线带多路信号：
    {id, kind:'signal', from:<设备>, to:<PLC>, signals:[{point:'Running', ch:'I0.0', dir:'in'}, {point:'Enable', ch:'Q0.0', dir:'out'}, …]}
dir 以 PLC 为准：in 设备 → PLC，out PLC → 设备；ch 是 PLC 通道（不带 %：I0.0 / Q0.0 / IW64），或者直接是变量名。
控制单元的信号线可以带 all_io: true（迁移生成的都带）：单元 I/O 表里没列在 signals 里的点也接上（地址用单元 I/O 表的），
这样在设备内部新加传感器、执行器后不用再改信号线。

PLC 的变量名：信号可以写 name；没写时，接控制单元的信号用点位名（= 控制单元的 I/O 名，原来的程序不用改），
接普通设备的信号用 <设备编号>_<点位>（例如 M1_Running），重名时加后缀。

和设备的接口（控制层助手在每类设备上实现；没有时这里有兜底）：
    st.ctl_points() -> [{'name','dir','type','label'}]
    st.ctl_get(point) -> 值            st.ctl_set(point, 值)
    st._plc_wired = {接了线的 out 点}    （本模块在第一次扫描前设置；含 'Enable' 时设备要等 PLC 允许才开工）
扫描节奏：普通设备每个整厂步（1 s）扫一次；控制单元在每个子步里调用 drive(self, t_abs)，离上次扫描满一个扫描周期就扫一次（每个子步最多一次）。
"""
from ..i18n import _tr
import json
import logging

from ..core import Station

log = logging.getLogger('vfactory.plc')
NOT_DEVICES = {'plc', 'hmi', 'gateway', 'switch', 'scada', 'mes'}


def _default_points(eq):
    """设备没有 ctl_points() 时：通用控制点 + 控制单元的 I/O 表。"""
    from ..flow.catalog import CONTROL_POINTS
    out = [dict(p, dir='in') for p in CONTROL_POINTS['in']] + [dict(p, dir='out') for p in CONTROL_POINTS['out']]
    if getattr(eq, 'kind', '') == 'cell':
        for e in (getattr(eq, 'cell_def', None) or {}).get('io') or []:
            out.append({'name': e.get('name'), 'dir': e.get('dir'), 'type': e.get('type') or 'BOOL', 'label': e.get('comment') or e.get('name')})
    return out


def points_of(eq):
    f = getattr(eq, 'ctl_points', None)
    if callable(f):
        try:
            r = f()
            if isinstance(r, dict):                       # 兼容 {'in': [...], 'out': [...]}
                r = [dict(x, dir='in') for x in r.get('in') or []] + [dict(x, dir='out') for x in r.get('out') or []]
            return list(r or [])
        except Exception:                                 # noqa: BLE001
            log.exception(_tr('ctl_points 出错'))
    return _default_points(eq)


def eq_get(eq, point):
    f = getattr(eq, 'ctl_get', None)
    if callable(f):
        return f(point)
    if getattr(eq, 'kind', '') == 'cell':                 # 控制单元（还没有 ctl_get 时）：最近一次的输入
        ins = getattr(eq, 'inputs_last', None) or {}
        if point in ins:
            return ins[point]
    st = getattr(eq, 'state', '')
    if point == 'Running':
        return st == 'Executing'
    if point == 'Fault':
        return st == 'Stopped' or getattr(getattr(eq, 'failure', None), 'repair_left', 0) > 0
    if point == 'Count':
        return int(getattr(eq, 'count', 0) or 0)
    if point == 'PartIn':
        return st in ('Executing', 'Blocked')
    return None


def eq_set(eq, point, value):
    f = getattr(eq, 'ctl_set', None)
    if callable(f):
        return f(point, value)
    if getattr(eq, 'kind', '') == 'cell':                 # 控制单元（还没有 ctl_set 时）：走外部输出
        eq.ext_out = getattr(eq, 'ext_out', None) or {}
        eq.ext_out[point] = value
        return ''
    # 兜底：Enable 用"停用"实现，Reset 上升沿结束故障
    if point == 'Enable':
        eq.enabled = bool(value)
    elif point == 'Reset':
        last = getattr(eq, '_plc_reset_last', False)
        if value and not last and getattr(getattr(eq, 'failure', None), 'repair_left', 0) > 0:
            eq.failure.repair_left = 0
        eq._plc_reset_last = bool(value)
    return ''


def _addr(ch):
    from .st import norm_addr
    ch = str(ch or '').strip()
    if not ch:
        return None
    na = norm_addr(ch if ch.startswith('%') else '%' + ch)
    return na[0] if na else None


class PlcStation(Station):
    """一台 PLC：一个软 PLC 运行时（或外接 PLC 代理），通过信号线读写多台设备。"""
    kind = 'plc'
    area = '控制'
    fault_kinds = {}

    def build_tags(self):
        self.plc = None
        self.io = []
        self.devices = []
        self._wmap = {}
        self.t_done = None
        self._wire_key = None
        self._driven = False             # 上一步有设备用子步驱动过它（控制单元）
        self._driven_now = False
        self.add_tag('PLC/State', 'STOP', desc=_tr('PLC 状态（RUN 运行 / STOP 停止 / HALT 暂停 / ERROR 错误）'), dtype='str')
        self.add_tag('PLC/ScanCount', 0, desc=_tr('扫描次数'), dtype='int')
        self._make()

    # -------------------------------------------------- 定义（API 和编程窗口用，和控制单元的格式一样）
    @property
    def cell_def(self):
        c = self.cfg
        return {'io': self.io, 'plc': {'mode': c.get('mode') or 'internal', 'scan_ms': self.scan_ms(), 'program': c.get('program'),
                                       'external': c.get('external') or {}},
                'hmi': c.get('hmi') or [], 'scene': c.get('scene'), 'migrated_from': c.get('migrated_from')}

    def scan_ms(self):
        try:
            return max(1.0, float(self.cfg.get('scan_ms') or 20))
        except (TypeError, ValueError):
            return 20.0

    def _make(self):
        from . import for_cell
        self.wire(force=True)
        try:
            self.plc = for_cell({'io': self.io, 'plc': {'mode': self.cfg.get('mode') or 'internal', 'scan_ms': self.scan_ms(),
                                                       'program': self.cfg.get('program'), 'external': self.cfg.get('external') or {}}})
        except Exception:                                 # noqa: BLE001
            log.exception(_tr('PLC %s 初始化失败'), self.id)
            self.plc = None

    # -------------------------------------------------- 接线
    def links(self):
        return [l for l in self.plant.cfg.get('links') or [] if l.get('kind') == 'signal' and self.id in (l.get('from'), l.get('to'))]

    def _wire_sig(self, links):
        """便宜的变化指纹：连线对象、信号表、all_io 设备的 I/O 定义（改模型时这些对象都会换新）。"""
        sig = [id(self.plant.cfg.get('links'))]
        for l in links:
            sig += [id(l), id(l.get('signals')), len(l.get('signals') or [])]
            if l.get('all_io'):
                eq = self.plant.find(l['to'] if l.get('from') == self.id else l.get('from'))
                cd = getattr(eq, 'cell_def', None) if eq is not None else None
                sig += [id(eq), id(cd), id((cd or {}).get('io')), len((cd or {}).get('io') or [])]
        return tuple(sig)

    def wire(self, force=False):
        links = self.links()
        # 每步都会调：指纹没变、离上次完整比较不到 10 s 仿真时间就不用再序列化比较（4.3 性能）
        sig = self._wire_sig(links)
        now = getattr(self.plant, 't', 0.0)
        if not force and self._wire_key is not None and sig == getattr(self, '_wire_fast', None) and now - getattr(self, '_wire_t', -1e9) < 10:
            return False
        self._wire_fast, self._wire_t = sig, now
        extra = []
        for l in links:                                   # all_io 的信号线：单元 I/O 表变了也要重新接线
            if l.get('all_io'):
                eq = self.plant.find(l['to'] if l.get('from') == self.id else l.get('from'))
                if eq is not None:
                    extra.append([(p.get('name'), p.get('dir'), p.get('addr')) for p in points_of(eq)])
        key = json.dumps([links, extra], sort_keys=True, ensure_ascii=False, default=str)
        if key == self._wire_key and not force:
            return False
        self._wire_key = key
        io, names, devs, wmap = [], set(), [], {}
        missing = False
        for l in links:
            eid = l['to'] if l.get('from') == self.id else l.get('from')
            eq = self.plant.find(eid) if eid else None
            if eq is None:
                missing = True                             # 建工厂时设备可能还没建好：下一步再接一次
                continue
            if getattr(eq, 'kind', '') in NOT_DEVICES:
                continue
            meta = {p.get('name'): p for p in points_of(eq)}
            cellish = getattr(eq, 'kind', '') == 'cell'
            wired_out = set()
            sigs = list(l.get('signals') or [])
            if cellish and l.get('all_io'):               # 迁移来的信号线：单元的全部 I/O（单元里新加的传感器、执行器自动接上）
                from .migrate import ch_of
                have = {str(x.get('point') or '') for x in sigs}
                for p in points_of(eq):
                    if p.get('name') and p['name'] not in have and (p.get('addr') or p.get('comp')):
                        sigs.append({'point': p['name'], 'ch': ch_of(p.get('addr')) or '', 'dir': p.get('dir') or 'in'})
            for sg in sigs:
                pt = str(sg.get('point') or '').strip()
                if not pt:
                    continue
                m = meta.get(pt) or {}
                d = sg.get('dir') or m.get('dir') or 'in'
                nm = str(sg.get('name') or (pt if cellish else f'{eid}_{pt}'))
                ch = str(sg.get('ch') or '').strip()
                addr = _addr(ch)
                if not addr and ch and not sg.get('name') and ch.replace('_', '').isalnum() and not ch[0].isdigit():
                    nm = ch                                # ch 直接写变量名
                base, k = nm, 2
                while nm.upper() in names:
                    nm = f'{base}_{k}'
                    k += 1
                names.add(nm.upper())
                io.append({'name': nm, 'dir': d, 'type': (sg.get('type') or m.get('type') or 'BOOL').upper(), 'addr': addr,
                           'comment': f"{getattr(eq, 'name', eid)} {m.get('label') or pt}", 'device': eid, 'point': pt, 'link': l.get('id'), 'ch': ch,
                           **({k2: m[k2] for k2 in ('contact', 'idle', 'comp') if k2 in m})})
                if d == 'out':
                    wired_out.add(pt)
            wmap.setdefault(eid, set()).update(wired_out)
            plcs = list(getattr(eq, '_plcs', None) or [])
            if self.id not in plcs:
                plcs.append(self.id)
            eq._plcs = plcs
            if eid not in devs:
                devs.append(eid)
        old_devs = [d for d in self.devices if d not in devs]
        self.io, self.devices, self._wmap = io, devs, wmap
        for eid in old_devs:                              # 拆掉的线：设备不再归这台 PLC 管
            eq = self.plant.find(eid)
            if eq is not None:
                eq._plcs = [x for x in getattr(eq, '_plcs', None) or [] if x != self.id]
        for eid in set(devs) | set(old_devs):             # 接了线的 out 点 = 所有控制它的 PLC 的并集
            eq = self.plant.find(eid)
            if eq is None:
                continue
            w, ps = set(), [p for p in controllers(eq) if p is not self]
            if eid in devs:
                ps.append(self)                           # 建厂时自己可能还没登记到工厂里
            for p in ps:
                w |= (getattr(p, '_wmap', None) or {}).get(eid, set())
            if hasattr(eq, 'ctl_bind'):
                eq.ctl_bind(w)
            else:
                eq._plc_wired = w
        if missing:
            self._wire_key = None
        p = self.plc
        if p is not None and not force:
            if hasattr(p, 'prog') and p.prog is not None:
                p.load(p.prog.program, cold=False, io=io)
            else:
                p.io = list(io)
                if hasattr(p, 'mapping'):                 # 外接 PLC：重建映射
                    from .external import merged_mapping
                    p.mapping = merged_mapping(p.io, p.protocol, p.cfg)
        return True

    # -------------------------------------------------- 扫描
    def _routes(self):
        """每一路 I/O 的读/写办法，按设备分组（4.3 性能：每次扫描都要用，I/O 表、设备对象、单元 I/O 表换了才重算）。
        控制单元的输入点直接从单元本子步的输入表取、BOOL 输出直接写单元的 _ctl_out（和 Cell.ctl_get / ctl_set 结果一样，省掉逐点查表）；
        其它设备走 ctl_get / ctl_set。"""
        pl = self.plant
        c = self.__dict__.get('_route_cache')
        if c is not None and c[0] is self.io and c[1] == pl.layout_version and c[2] is pl and all(eq.sim.io is io for eq, io in c[3]):
            return c[4], c[5]                             # 设备增删会改 layout_version；单元改定义会换 sim.io
        find = pl.find
        gin, gout = {}, {}
        for e in self.io:
            eq = find(e['device'])
            if eq is None:
                continue
            cellish = getattr(eq, 'kind', '') == 'cell' and hasattr(eq, '_ins_now') and hasattr(eq, '_io_dir')
            cd = eq._io_dir(e['point']) if cellish else (None, None)
            if e['dir'] == 'in':
                f = getattr(eq, 'ctl_get', None)
                g = gin.setdefault(id(eq), [eq, f if callable(f) else None, [], []])
                g[2 if cd[0] == 'in' else 3].append((e['name'], e['point']))      # [2] 单元输入点（快速）；[3] 逐点 ctl_get
            elif e['dir'] == 'out':
                f = getattr(eq, 'ctl_set', None)
                g = gout.setdefault(id(eq), [eq, f if callable(f) else None, [], []])
                g[2 if cd == ('out', 'BOOL') else 3].append((e['name'], e['point']))   # [2] 单元 BOOL 输出（快速）；[3] 逐点 ctl_set
        ins, outs = [tuple(v) for v in gin.values()], [tuple(v) for v in gout.values()]
        seen = {}
        for g in list(gin.values()) + list(gout.values()):
            eq = g[0]
            if getattr(eq, 'kind', '') == 'cell' and getattr(eq, 'sim', None) is not None:
                seen[id(eq)] = (eq, eq.sim.io)
        cells = list(seen.values())
        self._route_cache = (self.io, pl.layout_version, pl, cells, ins, outs)
        return ins, outs

    def _scan(self, dt):
        p = self.plc
        if p is None:
            return
        rin, rout = self._routes()
        ins = {}
        for eq, get, fast, slow in rin:
            src = eq._ins_now if fast else None
            if src is None:
                slow = fast + slow if fast else slow
            else:
                for name, pt in fast:
                    v = src.get(pt)
                    if v is not None:
                        ins[name] = v
            for name, pt in slow:
                v = get(pt) if get is not None else eq_get(eq, pt)
                if v is not None:
                    ins[name] = v
        outs = p.scan(ins, dt)
        for eq, put, fast, slow in rout:
            if fast:
                co = eq._ctl_out
                for name, pt in fast:
                    if name in outs:
                        co[pt] = bool(outs[name])
            for name, pt in slow:
                if name in outs:
                    if put is not None:
                        put(pt, outs[name])
                    else:
                        eq_set(eq, pt, outs[name])

    def sync_to(self, t, coarse=False, substep=False):
        """把 PLC 扫描到仿真时刻 t。coarse：用一次扫描补齐（普通设备 1 s 一步）；
        substep：控制单元的子步驱动——离上次扫描满一个扫描周期才扫，一次扫描补齐到 t（子步比扫描周期长时每个子步扫一次，
        和 4.2 单元内置 PLC 一样：单元的输入输出每个子步才变一次，多扫没有意义，单元空闲时的粗步也只扫一次）；
        否则按扫描周期一次次扫。"""
        if self.t_done is None:
            self.t_done = self.plant.t
        if t <= self.t_done + 1e-9:
            return
        if substep:
            if t - self.t_done >= self.scan_ms() / 1000 - 1e-9:
                self._scan(t - self.t_done)
                self.t_done = t
            return
        if coarse:
            self._scan(t - self.t_done)
            self.t_done = t
            return
        per = self.scan_ms() / 1000
        n = 0
        while self.t_done + per <= t + 1e-9 and n < 1000:
            self._scan(per)
            self.t_done += per
            n += 1
        if n >= 1000:
            self.t_done = t

    def tick(self, dt):
        self.wire()
        now = self.plant.t
        if self.t_done is None:
            self.t_done = now
        self._driven, self._driven_now = self._driven_now, False
        if self.t_done < now - 1e-9:                      # 上一步没人驱动：补一次
            self.sync_to(now, coarse=True)
        if not self._driven:                              # 没有控制单元用子步驱动：这一步扫一次
            self.sync_to(now + dt, coarse=True)
        p = self.plc
        st = getattr(p, 'state', 'STOP') if p is not None else 'STOP'
        self.state = {'RUN': 'Executing', 'HALT': 'Idle', 'STOP': 'Idle', 'ERROR': 'Stopped'}.get(st, 'Idle')
        # 还没有程序（新建的 PLC、实训课刚开始）是正常的起点，不算报警；提示放在 hint 里（对象面板、操作台、任务面板显示"先编程并下载"）
        empty = st == 'STOP' and (p is None or getattr(p, 'prog', 1) is None)
        self.alarm = '' if st == 'RUN' or empty else (p.label() if p is not None and hasattr(p, 'label') else _tr('PLC 没有程序'))
        self.hint = _tr('还没有程序：先编程并下载，PLC 运行后设备才会动') if empty else ''
        self.power_kw = 0.05
        self.set('PLC/State', st)
        self.set('PLC/ScanCount', int(getattr(p, 'scan_count', 0) or 0))
        self.set('Common/State', self.state)
        self.set('Common/Alarm', self.alarm)
        self.time_in_state[self.state] = self.time_in_state.get(self.state, 0) + dt

    def step(self, dt):
        pass

    def label(self):
        p = self.plc
        return p.label() if p is not None and hasattr(p, 'label') else _tr('没有程序')

    def view(self):
        p = self.plc
        return {'plc': {'state': getattr(p, 'state', 'STOP') if p else 'STOP', 'label': self.label(), 'devices': self.devices,
                        'halt': p.halt_info() if p is not None and hasattr(p, 'halt_info') else None,
                        'empty': bool(p is None or getattr(p, 'prog', 1) is None)}, 'hint': getattr(self, 'hint', '')}

    def __getstate__(self):
        d = dict(self.__dict__)
        d.pop('_route_cache', None)
        d['_wire_key'] = None                             # 恢复后重新接线（设备对象换了）
        return d


class HmiStation(Station):
    """HMI 触摸屏：画面绑定一台 PLC（params.plc，或者信号线/网络线连到的 PLC）。运行时就是 PLC 编程里的 HMI 画面。"""
    kind = 'hmi'
    area = '控制'
    fault_kinds = {}

    def build_tags(self):
        self.add_tag('HMI/PLC', '', desc=_tr('绑定的 PLC'), dtype='str')

    def plc_id(self):
        pid = self.cfg.get('plc')
        if pid:
            return pid
        for l in self.plant.cfg.get('links') or []:
            if l.get('kind') in ('signal', 'network') and self.id in (l.get('from'), l.get('to')):
                o = l['to'] if l.get('from') == self.id else l.get('from')
                st = self.plant.find(o)
                if st is not None and getattr(st, 'kind', '') == 'plc':
                    return o
        return ''

    def tick(self, dt):
        pid = self.plc_id()
        st = self.plant.find(pid) if pid else None
        ok = st is not None and getattr(getattr(st, 'plc', None), 'state', '') == 'RUN'
        self.state = 'Executing' if ok else 'Idle'
        self.alarm = '' if pid else _tr('没有连到 PLC')
        self.set('HMI/PLC', pid)
        self.set('Common/State', self.state)
        self.set('Common/Alarm', self.alarm)

    def step(self, dt):
        pass


def controllers(station):
    """控制这台设备的 PLC 块（PlcStation 列表）。"""
    out = []
    for pid in getattr(station, '_plcs', None) or ():
        p = station.plant.find(pid)
        if p is not None:
            out.append(p)
    return out


def drive(station, t_abs):
    """控制单元在每个子步里调用：把接在它上面的 PLC 扫描到仿真时刻 t_abs（满一个扫描周期才扫，每个子步最多扫一次，重复调用不会多扫）。"""
    plcs = getattr(station, '_plcs', None)
    if not plcs:
        return
    find = station.plant.find
    for pid in plcs:
        p = find(pid)
        if p is not None:
            p._driven_now = True
            p.sync_to(t_abs, substep=True)
