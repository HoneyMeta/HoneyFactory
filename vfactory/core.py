"""仿真内核：固定步长时钟、点位(Tag)注册表、零件档案、缓冲区、设备故障、能耗。

设计要点
- 固定步长（默认 1 s 仿真时间）推进，所有工位每步调用 step(dt)。离散事件（开始/结束一个工序）在工位
  的状态机里处理，连续量（温度、磨损、电量）在同一步里积分。这样运行中随时改参数、加减设备都安全，
  而且给定随机种子和同样的操作序列，结果完全可复现。
- 每个工位把对外可见的量登记成 Tag。协议层（OPC UA / Modbus / MQTT）和 Web 界面都只读写 Tag，
  不直接碰模型内部变量；模型内部的"真值"（刀具真实磨损、铸件真实缺陷）单独放在 truth 里，
  用来给 AI 算法当标准答案。
"""
from __future__ import annotations

from .i18n import _tr, label, server_language
import hashlib
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np

AMBIENT = 25.0


@dataclass
class Tag:
    name: str                      # 形如 "Monitoring/Spindle/Load"，'/' 分层
    value: Any
    unit: str = ''
    desc: str = ''
    dtype: str = 'float'           # float | int | bool | str
    writable: bool = False
    lo: float | None = None        # 可写量的允许范围
    hi: float | None = None
    modbus: dict | None = None     # {'kind': 'hr'|'coil', 'addr': int, 'scale': 10, 'fmt': 'int16'|'float32'}
    mqtt: bool = True
    history: deque = field(default_factory=lambda: deque(maxlen=600))
    event: bool = False            # 5.0 动作级信号：协议层按事件（精确时间戳）发，不靠轮询比对，见 vfactory/actions.py


# 统计口径：每一步把设备归到一个时间类别（专业仿真软件的"时间构成"）
CLS_LABEL = {'run': '运行', 'idle': '待机', 'starved': '缺料', 'blocked': '堵料', 'failed': '故障', 'setup': '换型', 'planned': '计划停机',
             'offshift': '非班次', 'disabled': '停用', 'wait_plc': '等待 PLC'}
CLS_OF_STATE = {'Executing': 'run', 'Idle': 'idle', 'Starved': 'starved', 'Blocked': 'blocked', 'Stopped': 'failed', 'Setup': 'setup', 'Planned': 'planned',
                'WaitPLC': 'wait_plc'}     # 4.3：接了 PLC 但没给"允许运行"（vfactory/control/iface.py）


class Station:
    """所有工位的基类。子类实现 build_tags() 和 step(dt)。"""
    kind = 'station'
    area = ''
    split_streams = False          # True：故障、路由等各用独立随机流（通用块）；旧版高级模型保持原随机流以保证结果不变
    action_profile = None          # 5.0 动作级信号的模板（cnc / press / robot，见 vfactory/actions.py）；通用块用参数 actions 打开
    acts = None

    def __init__(self, plant: 'Plant', cfg: dict):
        self.plant = plant
        self.cfg = cfg
        self.id: str = cfg['id']
        self.name: str = cfg.get('name', self.id)
        self.area = cfg.get('area', self.area)
        self.pos = cfg.get('pos', [0, 0])
        self.size = cfg.get('size', [4, 4])
        self.rot = cfg.get('rot', 0)
        self.group = cfg.get('group', self.id)
        self.rng = plant.child_rng(self.id)
        self.tags: dict[str, Tag] = {}
        self.truth: dict[str, Any] = {}
        self.state = 'Idle'
        self.alarm = ''
        self.enabled = True
        self.failure = Failure(self, cfg.get('mtbf_h', 0), cfg.get('mttr_min', 30))
        self.changeover_left = 0.0
        self.changeover_to = ''
        self._plan_alarm = ''
        self._last_state = None
        self.power_kw = 0.0
        self.energy_kwh = 0.0
        self.time_in_state: dict[str, float] = {}
        self.energy_by_cls: dict[str, float] = {}
        self._cls = None
        self._child = False            # 子模型内部的块：能耗由子模型汇总，不重复计入全厂
        self.build_tags()
        self.add_tag('Common/State', self.state, desc=_tr('运行状态'), dtype='str')
        self.add_tag('Common/Alarm', '', desc=_tr('当前报警'), dtype='str')
        self.add_tag('Common/PowerKW', 0.0, 'kW', _tr('实时功率'))
        self.add_tag('Common/EnergyKWh', 0.0, 'kWh', _tr('累计电能'))
        self._init_signals()
        if self.action_profile or cfg.get('actions'):   # 动作点位加在最后：Modbus 自动地址、旧点位都不挪
            from .actions import attach
            attach(self)

    # ---- 自定义点位与信号绑定 ----
    def _init_signals(self):
        from .flow.expr import Ctx
        self._sig, self._bind = [], []
        self._sctx = Ctx(self.plant.child_rng(self.id + ':sig'), self, self.plant)
        for s in self.cfg.get('signals') or []:
            name = str(s.get('name') or '').strip()
            if not name or name in self.tags:
                continue
            init = s.get('init', 0.0)
            t = self.add_tag(name, init if s.get('dtype') != 'bool' else bool(init), s.get('unit', ''), s.get('desc') or name,
                             dtype=s.get('dtype') or ('str' if isinstance(init, str) else 'float'), writable=bool(s.get('writable')),
                             lo=s.get('lo'), hi=s.get('hi'))
            if s.get('expr') and not s.get('writable'):
                self._sig.append((name, str(s['expr'])))
        for b in self.cfg.get('bindings') or []:
            if b.get('target') and b.get('expr'):
                self._bind.append((str(b['target']), str(b['expr'])))

    def _eval_signals(self):
        from .flow.expr import ExprError, evaluate
        for name, ex in self._sig:
            try:
                v = evaluate(ex, self._sctx)
                self.tags[name].value = round(v, 4) if isinstance(v, float) else v
            except ExprError as e:
                self.alarm = _tr('点位 {name} 公式错误：{e}', name=name, e=e)
        for target, ex in self._bind:
            try:
                v = evaluate(ex, self._sctx)
            except ExprError as e:
                self.alarm = _tr('绑定 {target} 公式错误：{e}', target=target, e=e)
                continue
            if target.startswith('param.'):
                self.cfg[target[6:]] = v
            elif target in self.tags:
                self.tags[target].value = v
                if self.tags[target].writable:
                    self.on_write(target, v)

    # ---- tags ----
    def add_tag(self, name, value, unit='', desc='', dtype=None, writable=False, lo=None, hi=None, modbus=None, mqtt=True):
        if dtype is None:
            dtype = 'bool' if isinstance(value, bool) else 'int' if isinstance(value, int) else 'str' if isinstance(value, str) else 'float'
        t = Tag(name, value, unit, desc, dtype, writable, lo, hi, modbus, mqtt)
        self.tags[name] = t
        return t

    def port(self, name, default):
        """端口 → 缓存名：流程图连线决定（cfg.ports），没连时用旧版默认名。"""
        return (self.cfg.get('ports') or {}).get(name, default)

    def buf(self, name, default):
        return self.plant.buffers[self.port(name, default)]

    def set(self, name, value):
        self.tags[name].value = value

    def get(self, name):
        return self.tags[name].value

    def write(self, name: str, value) -> str:
        """外部（协议或界面）写入可写点位。返回空串表示成功，否则是错误原因。"""
        t = self.tags.get(name)
        if t is None:
            return _tr('没有点位 {name}', name=name)
        if not t.writable:
            return _tr('{name} 只读', name=name)
        try:
            if t.dtype == 'bool':
                value = value if isinstance(value, bool) else str(value).lower() in ('1', 'true', 'on', 'yes')
            elif t.dtype == 'int':
                value = int(float(value))
            elif t.dtype == 'float':
                value = float(value)
        except (TypeError, ValueError):
            return _tr('{name} 数值格式不对', name=name)
        if t.dtype in ('int', 'float'):
            if t.lo is not None and value < t.lo or t.hi is not None and value > t.hi:
                return _tr('{name} 超出范围 {lo}–{hi}', name=name, lo=t.lo, hi=t.hi)
        t.value = value
        self.on_write(name, value)
        self.plant.log(self.id, 'param', f'{name} = {value}')
        return ''

    def on_write(self, name, value):
        pass

    # ---- faults ----
    fault_kinds: dict[str, str] = {'failure': '设备故障停机'}

    def inject(self, kind: str) -> str:
        if self.acts is not None:                  # 动作级故障（气缸泄漏 / 夹具卡滞 / 门慢），kind 可带参数 'cyl_leak:extra_s=2'
            r = self.acts.inject(kind)
            if r is not None:
                return r
        if kind == 'failure':
            self.failure.trigger(manual=True)
            return ''
        if kind == 'clear':
            self.failure.repair_left = 0
            self.alarm = ''
            self.plant.label_close(self.id, 'failure')
            self.plant.label_close(self.id, 'fault')
            return ''
        err = self.on_fault(kind)
        if not err:
            self.plant.label_open(self.id, 'fault', self.fault_kinds.get(kind, kind), kind=kind)
        return err

    def on_fault(self, kind) -> str:
        return _tr('{name} 不支持故障类型 {kind}', name=self.name, kind=kind)

    # ---- stepping ----
    def tick(self, dt):
        blk = self.plant.plan.blocked(self)
        cls = None
        if blk:                                       # 计划停机 / 非生产时间
            self.state = 'Planned'
            self.alarm = self._plan_alarm = blk
            self.power_kw = self.idle_power() * 0.3
            cls = 'offshift' if blk == self.plant.plan.off_reason else 'planned'
            self.failure.age(dt)
        elif self.changeover_left > 0:                # 换型
            self.changeover_left -= dt
            self.state = 'Setup'
            self.alarm = _tr('换型中 → {changeover_to}', changeover_to=self.changeover_to)
            self.power_kw = self.idle_power()
            cls = 'setup'
            self.failure.age(dt)
            if self.changeover_left <= 0:
                self.alarm = ''
                self.plant.label_close(self.id, 'changeover')
        else:
            if self._plan_alarm:
                self.alarm = self._plan_alarm = ''
            if self.failure.step(dt):          # 故障中：只走能耗和计时
                self.state = 'Stopped'
                self.power_kw = self.idle_power()
                cls = 'failed'
            elif self.enabled:
                if self._plc_wired and self.ctl_hold_tick():      # 4.3：PLC 没给"允许运行"
                    self.state = 'WaitPLC'
                    self.power_kw = self.idle_power()
                else:
                    self.step(dt)
                    if self._plc_wired:
                        self.ctl_after_step()
            else:
                self.state = 'Stopped'
                self.power_kw = 0.0
                cls = 'disabled'
        if cls is None:
            cls = CLS_OF_STATE.get(self.state, 'idle')
        pbs = self.cfg.get('power_by_state')
        if pbs and cls in pbs:                        # 按状态功率（覆盖模型自己算的功率）
            try:
                self.power_kw = float(pbs[cls])
            except (TypeError, ValueError):
                pass
        if self.state != self._last_state:
            self._last_state = self.state
            self.plant.state_log.append((self.plant.t, self.id, self.state))
        if cls != self._cls:
            self._cls = cls
            self.plant.class_log.append((self.plant.t, self.id, cls))
        if (self._sig or self._bind) and int(self.plant.t) % 5 == 0:
            self._eval_signals()
        e = self.power_kw * dt / 3600
        self.energy_kwh += e
        self.energy_by_cls[cls] = self.energy_by_cls.get(cls, 0.0) + e
        if not self._child:
            self.plant._e_q += e
        self.time_in_state[self.state] = self.time_in_state.get(self.state, 0) + dt
        self.set('Common/State', self.state)
        self.set('Common/Alarm', self.alarm)
        self.set('Common/PowerKW', round(self.power_kw, 2))
        self.set('Common/EnergyKWh', round(self.energy_kwh, 2))

    def step(self, dt):
        raise NotImplementedError

    def idle_power(self):
        return 0.0

    def availability(self):
        tot = sum(self.time_in_state.values()) or 1
        return 1 - self.time_in_state.get('Stopped', 0) / tot

    def snapshot(self, full=False) -> dict:
        d = {'id': self.id, 'name': self.name, 'kind': self.kind, 'area': self.area, 'state': self.state, 'alarm': self.alarm,
             'power': round(self.power_kw, 1), 'enabled': self.enabled}
        d.update(self.view())
        if self.kind in OEE_KINDS:
            d['oee'] = self.plant.oee(self)
        if full:
            d['tags'] = {k: {'v': t.value, 'u': t.unit, 'd': t.desc, 'w': t.writable, 'lo': t.lo, 'hi': t.hi, 'mb': t.modbus}
                         for k, t in self.tags.items()}
            d['faults'] = self.fault_kinds
            d['truth'] = self.truth
        return d

    def view(self) -> dict:
        """给三维界面用的少量动画数据。"""
        return {}


OEE_KINDS = ('cnc', 'molding', 'deburr', 'inspection', 'shotblast', 'processor', 'batch', 'inspect', 'assembly', 'rework')


class Failure:
    """随机故障：故障间隔服从 Weibull（形状默认 1.5，可用参数 fail_beta 改），修复时间服从对数正态。

    计时口径 fail_basis：operating（默认，只在运行时累计，等待/停机不算）或 calendar（日历时间，停着也会老化）。
    通用块用独立随机流（同种子下改别的参数不会挪动故障时刻，方案对比更公平）。"""
    BETA = 1.5

    def __init__(self, st: Station, mtbf_h: float, mttr_min: float):
        self.st, self.mtbf_h, self.mttr_min = st, mtbf_h, mttr_min
        self.rng = st.plant.child_rng(st.id + ':fail') if st.split_streams else st.rng
        self.repair_left = 0.0
        self.next_fail = self._draw() if mtbf_h else math.inf

    @property
    def beta(self):
        b = self.st.cfg.get('fail_beta')
        try:
            b = float(b)
        except (TypeError, ValueError):
            return self.BETA
        return b if b > 0 else self.BETA

    @property
    def calendar(self):
        return self.st.cfg.get('fail_basis') == 'calendar'

    def _draw(self):
        beta = self.beta
        scale = self.mtbf_h * 3600 / math.gamma(1 + 1 / beta)
        return self.rng.weibull(beta) * scale

    def trigger(self, manual=False):
        sigma = 0.5
        mu = math.log(self.mttr_min * 60) - sigma ** 2 / 2
        self.repair_left = float(self.rng.lognormal(mu, sigma))
        self.st.alarm = _tr('设备故障（人工注入）') if manual else _tr('设备故障')
        self.st.plant.log(self.st.id, 'fault', self.st.alarm, repair_min=round(self.repair_left / 60, 1))
        self.st.plant.label_open(self.st.id, 'failure', self.st.alarm)
        self.st.on_failure()

    def age(self, dt):
        """计划停机/换型期间：日历时间口径照样累计（到点后在下一个可运行步触发）。"""
        if self.repair_left <= 0 and self.mtbf_h and self.calendar:
            self.next_fail -= dt

    def step(self, dt) -> bool:
        if self.repair_left > 0:
            self.repair_left -= dt
            if self.repair_left <= 0:
                self.st.alarm = ''
                self.st.plant.log(self.st.id, 'repair', _tr('故障修复'))
                self.st.plant.label_close(self.st.id, 'failure')
                self.next_fail = self._draw() if self.mtbf_h else math.inf
            return True
        if self.st.state not in ('Idle', 'Stopped', 'Starved', 'Blocked', 'Planned') or (self.mtbf_h and self.calendar):
            self.next_fail -= dt
            if self.next_fail <= 0:
                self.trigger()
                return True
        return False


class Buffer:
    def __init__(self, name, capacity):
        self.name, self.capacity = name, capacity
        self.items: deque = deque()

    def full(self):
        return len(self.items) >= self.capacity

    def put(self, x):
        self.items.append(x)

    def get(self):
        return self.items.popleft() if self.items else None

    def __len__(self):
        return len(self.items)


class Part(dict):
    """一个铸件 / 工件的完整档案。dict 方便直接序列化给 API。"""

    def event(self, plant: 'Plant', station: str, what: str, **data):
        self.setdefault('history', []).append({'t': plant.clock_str(), 'station': station, 'event': what, **data})
        if what == 'stored':
            self['t_done'] = plant.t
            plant.lead_times.append((plant.t, plant.t - self.get('t0', plant.t)))
            plant.plan.on_stored(self)
        for f in plant.part_hooks:
            f(self, station, what, data)


# 各类工位用到的缓冲区；新增工位时缺的自动补上（默认容量）
BUFFERS_FOR = {'cooling': ['shot_in'], 'shotblast': ['shot_in', 'raw'], 'receiving': ['raw'], 'cnc': ['cnc_in', 'deb_in'],
               'deburr': ['deb_in', 'ins_in'], 'inspection': ['ins_in', 'fg', 'deb_in']}
BUFFER_DEFAULT = {'shot_in': 120, 'raw': 300, 'cnc_in': 40, 'deb_in': 24, 'ins_in': 24, 'fg': 200}
# 造型线每步都要用到砂处理、球化站、冷却线
REQUIRES = {'molding': ['sand', 'treatment', 'cooling']}
KIND_CN = {'sand': '砂处理系统', 'treatment': '球化孕育站', 'cooling': '冷却线', 'molding': '造型线'}


class Plant:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        p = cfg['plant']
        self.name = p['name']
        self.seed = int(p.get('seed', 42))
        self.t = 0.0                                   # 仿真秒
        start = str(p.get('start', '2026-11-02T07:00:00'))
        if start == 'now':                               # 仿真时钟接近真实时间（预热结束时约等于启动时刻）
            self.t0 = datetime.now().replace(second=0, microsecond=0) - timedelta(hours=float(p.get('warmup_h', 0)))
        else:
            self.t0 = datetime.fromisoformat(start)
        self.dt = float(p.get('dt', 1.0))
        self.speed = float(p.get('speed', 10))
        self.paused = False
        self.events: deque = deque(maxlen=5000)
        self.event_seq = 0
        self.parts: dict[str, Part] = {}
        self.part_seq = 0
        self.kpi = {'castings': 0, 'machined': 0, 'good': 0, 'scrap': 0, 'shipped': 0, 'scrap_by': {}, 'escape': 0, 'overkill': 0,
                    'melt_kg': 0.0}
        if 'blocks' in cfg:                            # 2.0 项目模型：块 + 连线 → 设备 + 队列
            from .flow.model import expand
            from .plc.migrate import migrate_model; migrate_model(cfg)   # 4.3：控制单元内置 PLC → 独立 plc 块 + 信号线（旧模型自动迁移）
            ex = expand(cfg)
            station_cfgs, buf_cfg = ex['stations'], ex['buffers']
        else:
            station_cfgs, buf_cfg = cfg['stations'], cfg.get('buffers', {})
        self.buffers: dict[str, Buffer] = {k: Buffer(k, v) for k, v in buf_cfg.items()}
        self.stations: dict[str, Station] = {}
        self.listeners: list[Callable] = []           # 协议层登记：工位增删时回调
        self.part_hooks: list[Callable] = []          # MES 网关登记：零件事件（相当于扫码/PLC 报工）
        self.event_hooks: list[Callable] = []         # MES 网关登记：生产日志
        self.step_hooks: list[Callable] = []          # 场景、回放等每步回调
        self.state_log: deque = deque(maxlen=300000)  # (t, 设备, 状态)
        self.hourly: deque = deque(maxlen=24 * 60)    # 每小时快照
        self.lead_times: deque = deque(maxlen=50000)  # (完成时刻, 生产周期 s)
        self.labels: deque = deque(maxlen=20000)      # 真值标签区间
        self.class_log: deque = deque(maxlen=300000)  # (t, 设备, 时间类别 CLS_LABEL 的键)
        self.energy_q: deque = deque(maxlen=4 * 24 * 31)  # (15 分钟末时刻, 全厂 kWh)
        self._e_q = 0.0
        self.wip_log: deque = deque(maxlen=60 * 24 * 14)  # (t, 在制品件数) 每分钟一次
        self.sub_index: dict[str, 'Station'] = {}     # 子模型内部的块（不在 stations 里）
        self.sub_parent: dict[str, str] = {}
        self._open_labels: dict = {}
        self.layout_version = 0
        self.comm: dict = {}                          # 通讯故障：协议 -> {mode, latency}
        from .history import TagRing
        from .plan import Plan
        self.tagring = TagRing(self)
        self.plan = Plan(self, cfg.get('plan'))
        from . import models
        for sc in station_cfgs:
            self.add_station(sc, models.REGISTRY[sc['type']], log=False)

    # ---- helpers ----
    def child_rng(self, key: str):
        h = int(hashlib.sha256(f'{self.seed}:{key}'.encode()).hexdigest()[:12], 16)
        return np.random.default_rng(h)

    def now(self) -> datetime:
        return self.t0 + timedelta(seconds=self.t)

    def clock_str(self):
        return self.now().strftime('%Y-%m-%d %H:%M:%S')

    def log(self, station, kind, msg, **data):
        self.event_seq += 1
        ev = {'seq': self.event_seq, 't': self.clock_str(), 'station': station, 'kind': kind, 'msg': msg, **data}
        self.events.append(ev)
        for f in self.event_hooks:
            f(ev)

    def new_part(self, **fields) -> Part:
        self.part_seq += 1
        pid = f"SH{self.now():%y%m%d}{self.part_seq:05d}"
        p = Part(id=pid, type=self.plan.product['code'], status='WIP', t0=self.t, **fields)
        self.plan.on_born(p)
        self.parts[pid] = p
        if len(self.parts) > 20000:                    # 只保留最近的档案，防止内存无限增长
            for k in list(self.parts)[:2000]:
                del self.parts[k]
        return p

    def scrap(self, part: Part, station: str, cause: str):
        part['status'] = 'SCRAP'
        part['scrap_cause'] = cause
        part.event(self, station, 'scrap', cause=cause)
        self.kpi['scrap'] += 1
        self.kpi['scrap_by'][cause] = self.kpi['scrap_by'].get(cause, 0) + 1

    # ---- 真值标签 ----
    def label_open(self, station, ltype, name, **data):
        key = (station, ltype)
        if key in self._open_labels:
            return
        lb = {'station': station, 'type': ltype, 'name': name, 'start': self.t, 'end': None, **data}
        self.labels.append(lb)
        self._open_labels[key] = lb

    def label_close(self, station, ltype):
        lb = self._open_labels.pop((station, ltype), None)
        if lb:
            lb['end'] = self.t

    def label_point(self, station, ltype, name, **data):
        self.labels.append({'station': station, 'type': ltype, 'name': name, 'start': self.t, 'end': self.t, **data})

    def cycle_factor(self):
        return float(self.plan.product.get('cycle_factor', 1.0))

    def recent_rate(self, hours=4):
        """近几小时的合格入库速度（件/小时）。"""
        overall = self.kpi['good'] / max(1, self.t / 3600) if self.t > 1800 else 0.0
        h = [x for x in self.hourly if x['t'] >= self.t - hours * 3600]
        if h and self.t - h[0]['t'] > 600:
            recent = (self.kpi['good'] - h[0]['good']) / ((self.t - h[0]['t']) / 3600)
            return recent if recent > 0 else overall
        return overall

    def crew_present(self, sid) -> bool:
        crew = next((s for s in self.stations.values() if s.kind == 'crew'), None)
        return True if crew is None else crew.present(sid)

    def find(self, sid):
        """按编号找设备，含子模型内部的块。"""
        return self.stations.get(sid) or self.sub_index.get(sid)

    def all_stations(self):
        return list(self.stations.values()) + list(self.sub_index.values())

    def wip_now(self):
        n = sum(len(b) for b in self.buffers.values())
        for st in self.all_stations():
            t = st.tags.get('Production/InProcess')
            if t is not None and isinstance(t.value, (int, float)):
                n += t.value
        return n

    def of_kind(self, kind):
        return [s for s in self.stations.values() if s.kind == kind]

    def add_station(self, sc: dict, cls=None, log=True):
        from . import models
        cls = cls or models.REGISTRY[sc['type']]
        for b in BUFFERS_FOR.get(cls.kind, []):
            if b not in self.buffers:
                self.buffers[b] = Buffer(b, BUFFER_DEFAULT[b])
                self.cfg.setdefault('buffers', {})[b] = BUFFER_DEFAULT[b]
        miss = [label(KIND_CN[k]) for k in REQUIRES.get(cls.kind, []) if not self.of_kind(k)]
        if miss and log:          # 运行中新增才检查；读配置时设备顺序任意
            raise ValueError(_tr('{get} 需要先有：{join}', get=sc.get('name', sc['type']), join=_tr('、').join(miss)))
        st = cls(self, sc)
        self.stations[st.id] = st
        self.layout_version += 1
        if log:
            self.log(st.id, 'layout', _tr('新增设备 {name}', name=st.name))
            for f in self.listeners:
                f('add', st)
        return st

    def remove_station(self, sid: str, any_group=False) -> str:
        st = self.stations.get(sid)
        if not st:
            return _tr('没有设备 {sid}', sid=sid)
        if not any_group:
            same = [s for s in self.stations.values() if s.group == st.group]
            if len(same) <= 1:
                return _tr('这一组只剩这一台，不能删除')
        if st.kind in ('crew', 'agv'):
            return _tr('班组和 AGV 车队不能删除，可以停用或在属性里改人数/台数')
        if len(self.of_kind(st.kind)) == 1:
            users = [s.name for s in self.stations.values() if st.kind in REQUIRES.get(s.kind, [])]
            if users:
                return _tr('{join} 还要用它，先删掉这些设备', join=_tr('、').join(users))
        st.on_remove()
        del self.stations[sid]
        self.layout_version += 1
        self.log(sid, 'layout', _tr('移除设备 {name}', name=st.name))
        for f in self.listeners:
            f('remove', st)
        return ''

    def remove_station_any(self, sid: str) -> str:
        return self.remove_station(sid, any_group=True)

    # ---- run ----
    def step(self):
        with server_language():                  # simulation texts (events, alarms, logs) are in the server language
            self._step()

    def _step(self):
        if int(self.t) % 60 == 0:
            self.plan.update()
        for st in list(self.stations.values()):
            st.tick(self.dt)
        self.t += self.dt
        it = int(self.t)
        if it % 30 == 0:
            self.tagring.record()
        if it % 60 == 0:
            self.wip_log.append((self.t, self.wip_now()))
        if it % 900 == 0:
            self.energy_q.append((self.t, self._e_q))
            self._e_q = 0.0
        if it % 3600 == 0:
            from .history import snapshot
            self.hourly.append(snapshot(self))
        for f in self.step_hooks:
            f()
        if int(self.t) % 5 == 0:
            for st in self.stations.values():
                for k in st.history_tags():
                    tg = st.tags[k]
                    tg.history.append((round(self.t, 1), tg.value))

    def run_for(self, seconds: float):
        n = int(seconds / self.dt)
        with server_language():
            for _ in range(n):
                self._step()

    def oee(self, st: Station) -> dict:
        tot = (sum(st.time_in_state.values()) - st.time_in_state.get('Planned', 0)) or 1
        run = st.time_in_state.get('Executing', 0)
        avail = 1 - (st.time_in_state.get('Stopped', 0) + st.time_in_state.get('Setup', 0)) / tot
        perf = run / max(1, tot - st.time_in_state.get('Stopped', 0) - st.time_in_state.get('Setup', 0))
        q = getattr(st, 'quality_rate', lambda: 1.0)()
        return {'A': round(avail, 3), 'P': round(perf, 3), 'Q': round(q, 3), 'OEE': round(avail * perf * q, 3)}

    def snapshot(self) -> dict:
        hours = self.t / 3600
        energy = sum(s.energy_kwh for s in self.stations.values())
        melt_t = self.kpi['melt_kg'] / 1000
        return {
            'time': self.clock_str(), 't': round(self.t, 1), 'speed': self.speed, 'paused': self.paused,
            'shift': self.plan.shift_name(), 'off': self.plan.off_reason, 'product': self.plan.product['code'],
            'order': self.plan.order['code'] if self.plan.order else None,
            'kpi': {**self.kpi, 'hours': round(hours, 2), 'energy_kwh': round(energy, 1),
                    'kwh_per_t_melt': round(sum(s.energy_kwh for s in self.of_kind('furnace')) / melt_t, 0) if melt_t > 10 else None,
                    'scrap_rate': round(self.kpi['scrap'] / max(1, self.kpi['castings']), 4),
                    'buffers': {k: len(b) for k, b in self.buffers.items()}},
            'stations': [s.snapshot() for s in self.stations.values()],
        }


# Station 默认：没有需要画历史曲线的点位；子类覆盖
def _history_tags(self):
    return self.cfg.get('history', [])


Station.history_tags = _history_tags
Station.on_failure = lambda self: None
Station.on_remove = lambda self: None

from .control.iface import install as _ctl_install  # noqa: E402  4.3 生产设备控制接口 ctl_points / ctl_get / ctl_set

_ctl_install(Station)
