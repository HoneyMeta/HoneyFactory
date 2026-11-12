"""5.0 动作级信号（节拍分析用）：一个循环里的门、夹具气缸、主轴、程序段号、循环启停，变化时带精确时间戳发出。

为什么要有
- MES 的节拍分析（循环时间分解、找慢动作、气缸泄漏预警）要的是"子循环"信号：电磁阀指令 → 到位传感器之间的时间。
  仿真步长是 1 s，所以动作不按步长走，而是在循环开始时排好一张时间表（精确到毫秒），到点时改点位、记事件。
- 协议层（MQTT / OPC UA）从 plant.act_events 取事件，每个变化单独发一次，时间戳用事件自己的时刻（不是轮询时刻）。

点位（都在 Actions/ 下，加在设备原有点位之后，所以 Modbus 自动地址不会挪动）
- Actions/CycleOn        循环进行中（上升沿 = 循环启动，下降沿 = 循环结束）；Actions/CycleCount 循环计数
- Actions/ProgramStep    程序段号（CNC：10…60 = OP10…OP60，0 = 空闲；压实/机器人：1…n）
- <部件>Valve / <部件>Cmd   电磁阀 / 指令输出；<部件>Extended / Retracted / Closed / Opened  到位传感器
- Actions/Last/<动作>     上次该动作用时（指令 → 到位，秒），Actions/Last/Cycle 上次循环用时

每个动作有标准用时 + 正态抖动（σ ≈ 4%），抖动用独立随机流；没有故障时动作都在原来的节拍里完成（CNC 的关门/夹紧占用上下料时间），
所以开了动作信号、没有故障时，仿真结果和以前完全一样。

故障（plant 配置 params.action_faults、故障接口、场景里的"注入故障"都行；kind 可以带参数：'cyl_leak:cyl=clamp,extra_s=2,drift_s_per_day=0.5'）
- cyl_leak      气缸泄漏：指定气缸（cyl，默认夹具 clamp）伸出变慢 extra_s 秒，可按仿真天数继续变坏 drift_s_per_day
- sticky_clamp  夹具卡滞：夹具松开（缩回）变慢 extra_s 秒（每次 0.6–1.4 倍随机）
- slow_door     防护门变慢：开门、关门各慢 extra_s 秒
动作变慢的部分直接加到设备的循环时间里（CNC：加到上下料时间，循环后段的延误加到下一件），所以产量会跟着降。
"""
from __future__ import annotations

from .i18n import _tr, label
import heapq
from collections import deque

GAP = 0.15                      # 两个动作之间：PLC 扫描 + 到位确认
LEAVE = 0.12                    # 指令发出后多久离开原位传感器
JITTER = 0.04

# 动作定义：cmd=(点位, 值)，leave=离开的到位传感器，arrive=到达的到位传感器，last=用时点位，cyl/dir 给故障用
A = {
    'door_close': dict(cmd=('Actions/DoorCloseCmd', True), leave='Actions/DoorOpened', arrive='Actions/DoorClosed', nominal=3.2, last='Actions/Last/DoorClose', door=True),
    'door_open': dict(cmd=('Actions/DoorCloseCmd', False), leave='Actions/DoorClosed', arrive='Actions/DoorOpened', nominal=3.0, last='Actions/Last/DoorOpen', door=True),
    'clamp_extend': dict(cmd=('Actions/ClampValve', True), leave='Actions/ClampRetracted', arrive='Actions/ClampExtended', nominal=1.1, last='Actions/Last/ClampExtend',
                         cyl='clamp', dir='extend'),
    'clamp_retract': dict(cmd=('Actions/ClampValve', False), leave='Actions/ClampExtended', arrive='Actions/ClampRetracted', nominal=0.9, last='Actions/Last/ClampRetract',
                          cyl='clamp', dir='retract'),
    'fill': dict(cmd=('Actions/FillValve', True), off=True, nominal=2.6, last='Actions/Last/Fill'),
    'squeeze_extend': dict(cmd=('Actions/SqueezeValve', True), leave='Actions/SqueezeRetracted', arrive='Actions/SqueezeExtended', nominal=2.2,
                           last='Actions/Last/SqueezeExtend', cyl='squeeze', dir='extend'),
    'squeeze_retract': dict(cmd=('Actions/SqueezeValve', False), leave='Actions/SqueezeExtended', arrive='Actions/SqueezeRetracted', nominal=1.6,
                            last='Actions/Last/SqueezeRetract', cyl='squeeze', dir='retract'),
    'push_extend': dict(cmd=('Actions/PushValve', True), leave='Actions/PushRetracted', arrive='Actions/PushExtended', nominal=2.4, last='Actions/Last/PushExtend',
                        cyl='push', dir='extend'),
    'push_retract': dict(cmd=('Actions/PushValve', False), leave='Actions/PushExtended', arrive='Actions/PushRetracted', nominal=1.8, last='Actions/Last/PushRetract',
                         cyl='push', dir='retract'),
    'gripper_close': dict(cmd=('Actions/GripperValve', True), leave='Actions/GripperOpened', arrive='Actions/GripperClosed', nominal=0.5, last='Actions/Last/GripperClose',
                          cyl='gripper', dir='extend'),
    'gripper_open': dict(cmd=('Actions/GripperValve', False), leave='Actions/GripperClosed', arrive='Actions/GripperOpened', nominal=0.45, last='Actions/Last/GripperOpen',
                         cyl='gripper', dir='retract'),
}
for _k, _a in A.items():
    _a['key'] = _k

_COMMON = [('Actions/CycleOn', False, '', '循环进行中（上升沿=循环启动，下降沿=循环结束）'), ('Actions/CycleCount', 0, '次', '循环计数'),
           ('Actions/ProgramStep', 0, '', '程序段号（0=空闲）')]
_LAST_CYCLE = ('Actions/Last/Cycle', 0.0, 's', '上次循环用时（循环启动→循环结束）')


def _sensor_tags(names):
    out = []
    for nm, init, desc in names:
        out.append((f'Actions/{nm}', init, '', desc))
    return out


PROFILES = {
    # CNC / 加工中心：防护门 + 夹具气缸 + 主轴 + NC 程序段
    'cnc': dict(
        label='加工中心（门 / 夹具 / 主轴）',
        tags=_COMMON + [('Actions/SpindleRun', False, '', '主轴运转')] + _sensor_tags([
            ('DoorCloseCmd', False, '防护门关门指令（1=关门，0=开门）'), ('DoorClosed', False, '防护门关到位'), ('DoorOpened', True, '防护门开到位'),
            ('ClampValve', False, '夹具夹紧电磁阀（1=夹紧）'), ('ClampExtended', False, '夹紧气缸伸出到位（已夹紧）'), ('ClampRetracted', True, '夹紧气缸缩回到位（已松开）')]) + [
            ('Actions/Last/DoorClose', 0.0, 's', '上次关门用时'), ('Actions/Last/ClampExtend', 0.0, 's', '上次夹紧用时（电磁阀→伸出到位）'),
            ('Actions/Last/ClampRetract', 0.0, 's', '上次松开用时（电磁阀→缩回到位）'), ('Actions/Last/DoorOpen', 0.0, 's', '上次开门用时'), _LAST_CYCLE],
        pre=['door_close', 'clamp_extend'], post=['clamp_retract', 'door_open'], cyls=['clamp'], door=True, steps=[10, 20, 30, 40, 50, 60]),
    # 造型线 / 压机类：射砂阀 + 压实气缸 + 推型气缸
    'press': dict(
        label='造型 / 压机（射砂 / 压实 / 推型）',
        tags=_COMMON + _sensor_tags([
            ('FillValve', False, '射砂（加料）阀'), ('SqueezeValve', False, '压实气缸电磁阀（1=压下）'), ('SqueezeExtended', False, '压实气缸伸出到位'),
            ('SqueezeRetracted', True, '压实气缸缩回到位'), ('PushValve', False, '推型气缸电磁阀（1=推出）'), ('PushExtended', False, '推型气缸伸出到位'),
            ('PushRetracted', True, '推型气缸缩回到位')]) + [
            ('Actions/Last/Fill', 0.0, 's', '上次射砂用时'), ('Actions/Last/SqueezeExtend', 0.0, 's', '上次压实用时（电磁阀→伸出到位）'),
            ('Actions/Last/SqueezeRetract', 0.0, 's', '上次压实回程用时'), ('Actions/Last/PushExtend', 0.0, 's', '上次推型用时'),
            ('Actions/Last/PushRetract', 0.0, 's', '上次推型回程用时'), _LAST_CYCLE],
        pre=['fill', 'squeeze_extend'], post=['squeeze_retract', 'push_extend', 'push_retract'], cyls=['squeeze', 'push'], door=False, steps=[1, 2, 3, 4]),
    # 机器人 / 取放单元：夹爪 + 工装夹紧气缸 + 机器人程序步
    'robot': dict(
        label='机器人 / 取放（夹爪 / 工装夹紧）',
        tags=_COMMON + _sensor_tags([
            ('RobotAtHome', True, '机器人在原点'), ('GripperValve', False, '夹爪电磁阀（1=闭合）'), ('GripperClosed', False, '夹爪闭合到位'), ('GripperOpened', True, '夹爪张开到位'),
            ('ClampValve', False, '工装夹紧电磁阀（1=夹紧）'), ('ClampExtended', False, '工装夹紧到位'), ('ClampRetracted', True, '工装松开到位')]) + [
            ('Actions/Last/GripperClose', 0.0, 's', '上次夹爪闭合用时'), ('Actions/Last/ClampExtend', 0.0, 's', '上次工装夹紧用时'),
            ('Actions/Last/ClampRetract', 0.0, 's', '上次工装松开用时'), ('Actions/Last/GripperOpen', 0.0, 's', '上次夹爪张开用时'), _LAST_CYCLE],
        pre=['gripper_close', 'clamp_extend'], post=['clamp_retract', 'gripper_open'], cyls=['clamp', 'gripper'], door=False, steps=[1, 2, 3, 4, 5]),
}
PROFILE_ALIAS = {'machine': 'cnc', 'cnc': 'cnc', 'machining': 'cnc', 'press': 'press', 'molding': 'press', 'robot': 'robot', 'pick': 'robot', 'pick_place': 'robot'}
CYL_CN = {'clamp': '夹具气缸', 'squeeze': '压实气缸', 'push': '推型气缸', 'gripper': '夹爪气缸'}

FAULTS = {'cyl_leak': '气缸泄漏（伸出变慢）', 'sticky_clamp': '夹具卡滞（松开变慢）', 'slow_door': '防护门动作变慢'}
FAULT_DEFAULT = {'cyl_leak': 1.5, 'sticky_clamp': 1.2, 'slow_door': 2.5}


def parse_kind(kind: str):
    """'cyl_leak:cyl=clamp,extra_s=2' → ('cyl_leak', {'cyl': 'clamp', 'extra_s': 2.0})。"""
    kind = str(kind or '').strip()
    name, _, rest = kind.partition(':')
    if not rest and '?' in name:
        name, _, rest = name.partition('?')
    params = {}
    for kv in rest.replace('&', ',').split(','):
        k, _, v = kv.partition('=')
        k, v = k.strip(), v.strip()
        if not k:
            continue
        k = {'extra': 'extra_s', 'drift': 'drift_s_per_day', 'cylinder': 'cyl'}.get(k, k)
        try:
            params[k] = float(v)
        except ValueError:
            params[k] = v
    return name.strip(), params


class ActHub:
    """每个工厂一个：每步把到点的动作写进点位。用绑定方法挂在 step_hooks 上（预热缓存 deepcopy 时跟着复制）。"""

    def __init__(self, plant):
        self.plant = plant
        self.seqs: list[ActionSeq] = []
        plant.act_events = deque(maxlen=20000)      # (序号, 仿真秒, 设备, 点位, 值)
        plant.act_seq = 0
        plant.step_hooks.append(self.step)

    @staticmethod
    def of(plant):
        h = getattr(plant, 'act_hub', None)
        if h is None:
            h = plant.act_hub = ActHub(plant)
        return h

    def step(self):
        t = self.plant.t
        for s in self.seqs:
            if s.q and s.q[0][0] <= t:
                s.flush(t)


def events_since(plant, seq):
    """协议层取新事件：返回 (新游标, [事件…])。事件序号递增，从尾部倒着找。"""
    ev = getattr(plant, 'act_events', None)
    if not ev or ev[-1][0] <= seq:
        return seq, []
    out = []
    for e in reversed(ev):
        if e[0] <= seq:
            break
        out.append(e)
    out.reverse()
    return out[-1][0], out


def profile_of(st):
    p = st.cfg.get('actions')
    if p in (False, 'none', 'off', 0):
        return None
    if isinstance(p, str) and p:
        return PROFILE_ALIAS.get(p)
    return getattr(st, 'action_profile', None)


def attach(st):
    """Station.__init__ 最后调用：这类设备有动作信号就挂上（工厂 plant.actions: false 全部关掉）。"""
    if (st.plant.cfg.get('plant') or {}).get('actions') is False:
        return None
    prof = profile_of(st)
    if not prof or prof not in PROFILES:
        return None
    st.acts = ActionSeq(st, prof)
    return st.acts


class ActionSeq:
    def __init__(self, st, profile):
        self.st, self.plant = st, st.plant
        self.profile = profile
        self.prof = PROFILES[profile]
        self.rng = st.plant.child_rng(st.id + ':act')
        self.q: list = []
        self.n = 0
        self.faults: dict[str, dict] = {}
        self.count = 0
        self.cyc_t0 = None
        self.pending = 0.0                        # 循环后段（松开 / 开门）的故障延误：加到下一件
        for tname, init, unit, desc in self.prof['tags']:
            if tname in st.tags:
                continue
            t = st.add_tag(tname, init, unit, desc)
            t.event = True
        fk = dict(type(st).fault_kinds)
        fk.update(getattr(st, 'fault_kinds', {}) or {})
        fk.update({k: v for k, v in FAULTS.items() if self.applicable(k)})
        st.fault_kinds = fk
        ActHub.of(st.plant).seqs.append(self)
        for f in st.cfg.get('action_faults') or []:          # 工厂配置里写好的故障（从仿真开始就有）
            if isinstance(f, dict) and f.get('kind'):
                self.inject(str(f['kind']), {k: v for k, v in f.items() if k != 'kind'}, log=False)

    # ---------- 故障 ----------
    def applicable(self, kind):
        if kind == 'cyl_leak':
            return bool(self.prof['cyls'])
        if kind == 'sticky_clamp':
            return 'clamp' in self.prof['cyls']
        if kind == 'slow_door':
            return bool(self.prof['door'])
        return False

    def inject(self, kind, params=None, log=True):
        """返回 None = 不是动作故障；'' = 成功；其它 = 错误说明。"""
        name, p = parse_kind(kind)
        p.update(params or {})
        if name == 'clear':
            self.faults.clear()
            return None
        if name not in FAULTS:
            return None
        if not self.applicable(name):
            return _tr('{name} 没有{v}，不能注入 {v2}', name=self.st.name, v=_tr('防护门') if name == "slow_door" else _tr('夹具气缸') if name == "sticky_clamp" else _tr('气缸'), v2=FAULTS[name])
        cyl = str(p.get('cyl') or ('clamp' if name == 'sticky_clamp' else self.prof['cyls'][0] if self.prof['cyls'] else ''))
        if name == 'cyl_leak' and cyl not in self.prof['cyls']:
            return _tr('气缸只能是 {join}', join='/'.join(self.prof['cyls']))
        try:
            extra = float(p.get('extra_s', FAULT_DEFAULT[name]))
            drift = float(p.get('drift_s_per_day', 0) or 0)
        except (TypeError, ValueError):
            return _tr('extra_s / drift_s_per_day 需要数字')
        if not 0 <= extra <= 600 or not -60 <= drift <= 600:
            return _tr('extra_s 范围 0–600 秒，drift_s_per_day 范围 −60–600 秒/天')
        self.faults[name] = {'cyl': cyl, 'extra_s': extra, 'drift_s_per_day': drift, 't0': self.plant.t}
        if log:
            what = label(FAULTS[name]) + (_tr('（{get}）', get=CYL_CN.get(cyl, cyl)) if name == 'cyl_leak' else '')
            self.plant.label_open(self.st.id, 'fault', what, kind=name, cyl=cyl, extra_s=extra, drift_s_per_day=drift)
        return ''

    def fault_info(self):
        return {k: {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in self.faults.items()}

    def _delta(self, a):
        if not self.faults:
            return 0.0
        d = 0.0
        days = lambda f: max(0.0, (self.plant.t - f['t0']) / 86400.0)
        f = self.faults.get('cyl_leak')
        if f and a.get('cyl') == f['cyl'] and a.get('dir') == 'extend':
            d += f['extra_s'] + f['drift_s_per_day'] * days(f)
        f = self.faults.get('sticky_clamp')
        if f and a.get('cyl') == 'clamp' and a.get('dir') == 'retract':
            d += f['extra_s'] * (0.6 + 0.8 * float(self.rng.random())) + f['drift_s_per_day'] * days(f)
        f = self.faults.get('slow_door')
        if f and a.get('door'):
            d += f['extra_s'] + f['drift_s_per_day'] * days(f)
        return max(0.0, d)

    # ---------- 时间表 ----------
    def at(self, t, tname, value):
        heapq.heappush(self.q, (t, self.n, tname, value))
        self.n += 1

    def flush(self, now):
        st, p = self.st, self.plant
        ev = p.act_events
        while self.q and self.q[0][0] <= now + 1e-9:
            t, _n, tname, v = heapq.heappop(self.q)
            tag = st.tags.get(tname)
            if tag is None:
                continue
            tag.value = v
            p.act_seq += 1
            ev.append((p.act_seq, t, st.id, tname, v))

    def _draw(self, keys):
        out = []
        for k in keys:
            a = A[k]
            j = float(self.rng.normal(0, JITTER))
            d = a['nominal'] * min(1.25, max(0.85, 1 + j))
            e = self._delta(a)
            out.append((a, d + e, e))
        return out

    def _emit(self, draws, t0):
        t = t0
        for i, (a, d, _e) in enumerate(draws):
            tn, val = a['cmd']
            self.at(t, tn, val)
            if a.get('off'):                       # 只有阀、没有到位开关（射砂）：到时关阀
                self.at(t + d, tn, not val)
            if a.get('leave'):
                self.at(t + min(LEAVE, d / 4), a['leave'], False)
            if a.get('arrive'):
                self.at(t + d, a['arrive'], True)
            self.at(t + d, a['last'], round(d, 3))
            t += d + (GAP if i < len(draws) - 1 else 0)
        return t

    @staticmethod
    def _span(draws):
        return sum(d for _a, d, _e in draws) + GAP * max(0, len(draws) - 1)

    def _cycle_on(self, t):
        self.cyc_t0 = t
        self.at(t, 'Actions/CycleOn', True)

    def _cycle_off(self, t):
        self.count += 1
        self.at(t, 'Actions/CycleOn', False)
        self.at(t, 'Actions/CycleCount', self.count)
        if self.cyc_t0 is not None:
            self.at(t, 'Actions/Last/Cycle', round(t - self.cyc_t0, 3))
        self.cyc_t0 = None

    def step(self, t, n):
        self.at(t, 'Actions/ProgramStep', int(n))

    # ---------- CNC：关门 / 夹紧占用上下料时间的最后几秒，松开 / 开门在加工完以后 ----------
    PRE_WINDOW = 8.0

    def take_pending(self):
        e, self.pending = self.pending, 0.0
        return e

    def cnc_pre(self, t_ops):
        """上下料剩 PRE_WINDOW 秒以内时调用：t_ops = 按原节拍开始加工的时刻。返回故障延误（秒），设备把它加到上下料时间上。"""
        draws = self._draw(self.prof['pre'])
        extra = sum(e for _a, _d, e in draws)
        t_end = t_ops + extra
        t0 = t_end - self._span(draws) - GAP
        self._cycle_on(t0)
        self._emit(draws, t0)
        return extra

    def cnc_start(self, t):
        self.step(t, self.prof['steps'][0])
        self.at(t + 0.2, 'Actions/SpindleRun', True)

    def cnc_op(self, t, op_i):
        steps = self.prof['steps']
        self.step(t, steps[min(op_i, len(steps) - 1)])
        if op_i >= len(steps) - 1:                 # 最后一段是测头测量：主轴停
            self.at(t, 'Actions/SpindleRun', False)

    def cnc_end(self, t):
        """加工完（或断刀中止）：主轴停、段号清零、松开、开门、循环结束。后段的故障延误记到下一件。"""
        self.at(t, 'Actions/SpindleRun', False)
        self.step(t, 0)
        draws = self._draw(self.prof['post'])
        self.pending += sum(e for _a, _d, e in draws)
        t_end = self._emit(draws, t + 0.3)
        self._cycle_off(t_end)

    # ---------- 通用：整个循环在开始时排好（造型、机器人、通用加工块） ----------
    def cycle(self, t0, total):
        """t0 开始、按原节拍 total 秒结束的一个循环。返回故障延误（秒），设备把它加到这个循环上。"""
        pre = self._draw(self.prof['pre'])
        post = self._draw(self.prof['post'])
        extra = sum(e for _a, _d, e in pre) + sum(e for _a, _d, e in post) + self.take_pending()
        t_end = t0 + total + extra
        steps = self.prof['steps']
        self._cycle_on(t0)
        self.step(t0, steps[0])
        tp = self._emit(pre, t0)
        t_post = max(tp + GAP, t_end - self._span(post))
        mids = steps[1:-1]
        for i, n in enumerate(mids):               # 中间段号在"前段完 → 后段开始"之间均分
            self.step(tp + (t_post - tp) * i / max(1, len(mids)), n)
        if self.profile == 'robot':
            self.at(t0 + 0.05, 'Actions/RobotAtHome', False)
            self.at(t_end, 'Actions/RobotAtHome', True)
        self.step(t_post, steps[-1])
        te = self._emit(post, t_post)
        self.step(te, 0)
        self._cycle_off(te)
        return extra
