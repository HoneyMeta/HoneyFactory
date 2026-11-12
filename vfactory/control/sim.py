"""控制层运行时 CellSim：设备级场景的简化运动学仿真（步长 20 ms）。

不用物理引擎：零件是带高度的方块（水平方向按圆近似做碰撞），每步按"支撑面"决定它怎么动：
  - 找零件正下方最高的台面（输送机、转台、升降台、货叉、托盘台、货架、其他零件顶面），零件落在上面并跟着它走；
  - 推杆推板、挡停挡板、摆臂、比零件底面高的台面、其他零件是障碍物，挡住就停（输送机还在转并被执行器挡住超过 3 s 记一次卡件）；
  - 执行器自己动时直接推开零件（推杆、摆臂），推到别的零件上记碰撞；
  - 下面什么都没有就落到地上（记一次掉件）；中心进入收料区/单元出口就被收走并按接收条件判分拣对错。
同样的单元定义、随机种子和 I/O 序列，结果完全一样。

接口（与 PLC 层、整厂、三维界面的约定）：
  sim = CellSim(cell_def, rng)
  sim.inputs() -> {I/O 名: 值}         传感器、按钮等 in 点（已叠加故障与强制）
  sim.apply_outputs({I/O 名或地址: 值}) PLC 输出（out 点；叠加强制、断线）
  sim.step(dt)                         推进 dt 秒（默认 0.02）
  sim.parts() / sim.view() / sim.stats()
  sim.inject(部件或 I/O 名, 故障) / sim.clear_faults() / sim.force(名, 值或 None) / sim.panel(部件, 动作, 值)
"""
from __future__ import annotations

from ..i18n import _tr
import math

from . import catalog as K

DT = 0.02
STEP_UP = 0.02          # 零件能"迈上"的台阶高度
FALL_V = 2.5            # 下落速度 m/s
JAM_S = 3.0             # 输送机推着零件被执行器挡住超过这么久算卡件
HARD_DROP = 0.12        # 下落高度超过这个算"硬摔"
# 4.5 实时观察者（教学的运行日志、实时检查表、"为什么没反应"诊断）：{id(sim): (weakref(sim), fn(sim))}，每步结束后调用。
# 放在模块级而不是 sim 的属性上：工厂会被 deepcopy / pickle（推演、预热缓存），观察者不能跟着复制。
OBSERVERS: dict = {}


def observe(sim, fn):
    """给一个 CellSim 挂观察者（fn=None 取消）。fn(sim) 在每次 step() 之后调用，出错只记日志不影响仿真。"""
    import weakref
    if fn is None:
        OBSERVERS.pop(id(sim), None)
        return
    for k, (ref, _) in list(OBSERVERS.items()):        # 顺手清掉已经回收的
        if ref() is None:
            OBSERVERS.pop(k, None)
    OBSERVERS[id(sim)] = (weakref.ref(sim), fn)


def observer_of(sim):
    v = OBSERVERS.get(id(sim))
    return v[1] if v and v[0]() is sim else None
METRIC_CN = {'removed': '完成件数', 'throughput_per_min': '每分钟产出', 'sort_accuracy': '分拣正确率', 'sorted_wrong': '分拣错误', 'sorted_ok': '分拣正确',
             'collisions': '碰撞', 'jams': '卡件', 'dropped': '掉件', 'hard_drops': '高处摔落', 'part_contacts': '零件追尾',
             'interlock_violations': '互锁错误', 'hard_reversals': '高速直接反转', 'pallets.*.count': '托盘上的件数', 'pallets.*.layers': '码垛层数',
             'pallets.*.inside': '都在托盘范围内', 'racks.*.stored': '库存', 'racks.*.double': '重复放入的库位', 'bins.*.ok': '合格箱数', 'bins.*.n': '出口件数',
             'dwell_min.*': '最短停留 s', 'emit_min_gap.*': '最小放料间隔 s'}
COLOR_CODE = {'blue': 1, 'green': 2, 'grey': 3, 'gray': 3, 'red': 4, 'yellow': 5, 'orange': 6, 'white': 7, 'black': 8}
KIND_CODE = {'box': 1, 'part': 2, 'pallet': 3, 'tote': 4, 'lid': 5, 'base': 6}


def _clamp(v, a, b):
    return a if v < a else b if v > b else v


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


class Part:
    __slots__ = ('id', 'kind', 'color', 'material', 'h', 'w', 'r', 'x', 'y', 'z', 'yaw', 'held', 'born', 'holds', 'plant', 'sup', 'blk_t',
                 'jam', 'free_t', 'fall0', 'dead', 'dead_t', 'dx', 'dy', 'src', 'attrs', 'stops', 'contacts', 'exit_wait', 'removed_by', 'box')

    def __init__(self, pid, tpl, x, y, z, yaw=0.0):
        self.id = pid
        self.kind = str(tpl.get('kind') or 'box')
        self.color = str(tpl.get('color') or 'blue')
        self.material = str(tpl.get('material') or 'plastic')
        self.h = max(0.02, _f(tpl.get('h'), 0.2))
        self.w = max(0.04, _f(tpl.get('w'), 0.25))
        self.r = self.w / 2
        self.x, self.y, self.z, self.yaw = x, y, z, yaw
        self.held = None            # 被谁抓着（取放机械手 / 夹爪）
        self.born = 0.0
        self.holds = {}             # 挡停编号 → 被挡住的累计秒数
        self.plant = None           # 整厂零件档案（从单元入口进来的）
        self.sup = None             # 当前支撑（部件或零件）
        self.blk_t = 0.0
        self.jam = False
        self.free_t = 0.0
        self.fall0 = None
        self.dead = False
        self.dead_t = 0.0
        self.dx = self.dy = 0.0     # 本步位移（叠放在上面的零件跟着走）
        self.src = ''
        self.attrs = {k: v for k, v in tpl.items() if k not in ('kind', 'color', 'material', 'h', 'w', 'weight')}
        self.stops = 0
        self.contacts = set()
        self.exit_wait = False
        self.removed_by = ''
        self.box = None             # 装在哪个周转箱里

    def top(self):
        return self.z + self.h

    def info(self):
        return {'id': self.id, 'kind': self.kind, 'color': self.color, 'material': self.material, 'h': round(self.h, 3), 'w': round(self.w, 3),
                'pos': [round(self.x, 3), round(self.y, 3), round(self.z, 3)], 'yaw': round(math.degrees(self.yaw), 1),
                'held': self.held.id if self.held is not None else None, 'plant_id': self.plant.get('id') if isinstance(self.plant, dict) else None,
                'age_s': None}

    def inner(self, x, y):
        """(x, y) 是否在周转箱内腔里。"""
        m = self.r - 0.03
        return abs(x - self.x) < m and abs(y - self.y) < m

    def match(self, acc, count=None):
        """是否满足接收条件。"""
        if not acc:
            return True
        for k, v in acc.items():
            if k == 'count':
                if count is None or count != int(_f(v)):
                    return False
            elif k == 'min_h':
                if self.h < _f(v) - 1e-6:
                    return False
            elif k == 'max_h':
                if self.h > _f(v) + 1e-6:
                    return False
            else:
                mine = getattr(self, k, None) if k in ('kind', 'color', 'material') else self.attrs.get(k)
                if isinstance(v, list):
                    if mine not in v:
                        return False
                elif mine != v:
                    return False
        return True


# ======================================================================= 部件
class Comp:
    surface = False
    solid = False
    thick = 0.12            # 台面厚度（台面下面的空间可以通过零件）

    def __init__(self, sim, d):
        self.sim, self.d = sim, d
        self.id = str(d['id'])
        self.type = d['type']
        pos = list(d.get('pos') or [0, 0, 0]) + [0, 0, 0]
        self.x, self.y, self.z = _f(pos[0]), _f(pos[1]), _f(pos[2])
        self.rot = _f(d.get('rot'), 0.0)
        th = math.radians(self.rot)
        self.fx, self.fy = math.cos(th), math.sin(th)
        spec = K.COMP_TYPES.get(self.type, {})
        sz = list(d.get('size') or spec.get('size') or [0.5, 0.5]) + [0.5, 0.5]
        self.L, self.W = max(0.01, _f(sz[0], 0.5)), max(0.01, _f(sz[1], 0.5))
        self.p = {k: v['default'] for k, v in spec.get('params', {}).items()}
        self.p.update({k: v for k, v in (d.get('params') or {}).items() if v is not None})
        self.sig = {}           # 给 PLC 的原始信号
        self.cmd = {}           # PLC 来的命令（已叠加强制和断线）
        self.moving = False
        self.init()

    # 坐标
    def loc(self, x, y):
        dx, dy = x - self.x, y - self.y
        return dx * self.fx + dy * self.fy, -dx * self.fy + dy * self.fx

    def wld(self, lx, ly):
        return self.x + lx * self.fx - ly * self.fy, self.y + lx * self.fy + ly * self.fx

    def vec(self, lx, ly):
        return lx * self.fx - ly * self.fy, lx * self.fy + ly * self.fx

    def c(self, k):
        return self.cmd.get(k, False)

    def fault(self, kind):
        return kind in self.sim.faults.get(self.id, ())

    def speed_factor(self):
        if self.fault('actuator_jam'):
            return 0.0
        return 0.35 if self.fault('actuator_slow') else 1.0

    def init(self):
        pass

    def step(self, dt):
        pass

    def sense(self):
        pass

    def view(self):
        return {}

    # 台面
    def top_at(self, x, y, z, follow=False):
        return None

    def disp(self, part, dt):
        return 0.0, 0.0, 0.0

    # 障碍
    def blocks(self, part, x, y):
        return False

    def power(self):
        return 0.0


def _in_rect(lx, ly, hx, hy, m=0.0):
    return -hx - m <= lx <= hx + m and -hy - m <= ly <= hy + m


def _circle_rect(lx, ly, r, x0, x1, y0, y1):
    cx = _clamp(lx, x0, x1)
    cy = _clamp(ly, y0, y1)
    return (lx - cx) ** 2 + (ly - cy) ** 2 < r * r - 1e-9


def _vert(part, z0, z1):
    """零件竖直范围与 [z0, z1] 重叠。"""
    return part.z < z1 - 1e-6 and part.z + part.h > z0 + 1e-6


class Conveyor(Comp):
    surface = True

    def init(self):
        self.top = self.z + _f(self.p.get('height'), 0.25)
        self.v = 0.0            # 当前带速（带方向）
        self.travel = 0.0       # 累计皮带行程（编码器、皮带纹理）

    def step(self, dt):
        sp = _f(self.p.get('speed'), 0.3) * self.speed_factor()
        if self.fault('motor_overload'):
            sp = 0.0
        m = self.p.get('motor')
        if m:
            mo = self.sim.comps.get(m)
            dirn = mo.s if isinstance(mo, Motor) else 0.0
        else:
            dirn = (1.0 if self.c('fwd') else 0.0) - (1.0 if self.c('rev') and self.p.get('reversible') else 0.0)
            if self.c('fwd') and self.c('rev') and self.p.get('reversible'):
                self.sim.violation(self, 'fwd+rev')
                dirn = 0.0
        if self.sim.estop_cut:
            dirn = 0.0
        self.v = sp * dirn
        self.travel += self.v * dt
        self.moving = abs(self.v) > 1e-6

    def top_at(self, x, y, z, follow=False):
        lx, ly = self.loc(x, y)
        if abs(lx) <= self.L / 2 and abs(ly) <= self.W / 2 and (follow or self.top <= z + STEP_UP):
            return self.top
        return None

    def disp(self, part, dt):
        vx, vy = self.vec(self.v * dt, 0.0)
        # 零件朝向慢慢转到输送方向
        return vx, vy, 0.0

    def blocks(self, part, x, y):
        if self.top <= part.z + STEP_UP or not _vert(part, self.top - self.thick, self.top):
            return False
        lx, ly = self.loc(x, y)
        return _circle_rect(lx, ly, part.r * 0.9, -self.L / 2, self.L / 2, -self.W / 2, self.W / 2)

    def view(self):
        return {'v': round(self.v, 3), 'o': round(self.travel % 10, 3)}

    def power(self):
        return _f(self.p.get('kw'), 0.37) if self.moving else 0.0


class CurvedConveyor(Conveyor):
    """pos 是入口中心，rot 是入口处输送方向；中心线半径 radius，转角 angle（正数左转）。"""

    def init(self):
        super().init()
        self.R = max(0.2, _f(self.p.get('radius'), 0.9))
        self.ang = math.radians(_f(self.p.get('angle'), 90) or 90)
        s = 1.0 if self.ang > 0 else -1.0
        self.sgn = s
        # 圆心在入口左侧（左转）或右侧（右转）
        self.cx, self.cy = self.wld(0.0, s * self.R)
        self.a0 = math.atan2(self.y - self.cy, self.x - self.cx)

    def _polar(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        rr = math.hypot(dx, dy)
        a = math.atan2(dy, dx) - self.a0
        a = (a + math.pi) % (2 * math.pi) - math.pi
        return rr, a * self.sgn

    def top_at(self, x, y, z, follow=False):
        rr, a = self._polar(x, y)
        if abs(rr - self.R) <= self.W / 2 and -0.01 <= a <= abs(self.ang) + 0.01 and (follow or self.top <= z + STEP_UP):
            return self.top
        return None

    def disp(self, part, dt):
        dx, dy = part.x - self.cx, part.y - self.cy
        rr = math.hypot(dx, dy) or 1e-6
        w = self.v / self.R * self.sgn            # 角速度（按中心线速度）
        da = w * dt
        ca, sa = math.cos(da), math.sin(da)
        nx, ny = self.cx + dx * ca - dy * sa, self.cy + dx * sa + dy * ca
        return nx - part.x, ny - part.y, da

    def blocks(self, part, x, y):
        return False


class ChainTransfer(Comp):
    surface = True

    def init(self):
        self.base = self.z + _f(self.p.get('height'), 0.25)
        self.u = 0.0            # 顶升 0..1
        self.v = 0.0

    def top_now(self):
        return self.base - 0.03 + 0.05 * self.u

    def step(self, dt):
        f = self.speed_factor()
        tgt = 1.0 if self.c('up') and not self.sim.estop_cut else 0.0
        if f > 0:
            self.u = tgt if abs(tgt - self.u) < dt / 0.2 * f else self.u + math.copysign(dt / 0.2 * f, tgt - self.u)
        dirn = (1.0 if self.c('fwd') else 0.0) - (1.0 if self.c('rev') and self.p.get('reversible', True) else 0.0)
        if self.sim.estop_cut or self.fault('motor_overload'):
            dirn = 0.0
        self.v = _f(self.p.get('speed'), 0.3) * f * dirn
        self.moving = abs(self.v) > 0 or 0 < self.u < 1
        self.sig['is_up'] = self.u > 0.95

    def top_at(self, x, y, z, follow=False):
        if self.u < 0.6:
            return None
        lx, ly = self.loc(x, y)
        t = self.top_now()
        if abs(lx) <= self.L / 2 and abs(ly) <= self.W / 2 and (follow or t <= z + STEP_UP + 0.03):
            return t
        return None

    def disp(self, part, dt):
        vx, vy = self.vec(0.0, self.v * dt)
        return vx, vy, 0.0

    def view(self):
        return {'u': round(self.u, 2), 'v': round(self.v, 3)}

    def power(self):
        return _f(self.p.get('kw'), 0.25) if abs(self.v) > 0 else 0.0


class Emitter(Comp):
    def init(self):
        self.next_t = _f(self.p.get('start_delay'), 1.0)
        self.count = 0
        self.pending = False
        self.prev = False
        self.last_t = -1e9
        self.intervals = []
        self._blk = False
        self.tpl = None
        self.waited = False
        self.clear_t = None
        self.gap = 4.0

    def _tpl(self):
        tpls = self.p.get('parts') or [{}]
        if isinstance(tpls, dict):
            tpls = [tpls]
        if len(tpls) == 1:
            return dict(tpls[0])
        w = [max(0.0, _f(t.get('weight'), 1.0)) for t in tpls]
        s = sum(w) or 1.0
        u = self.sim.rng.random() * s
        acc = 0.0
        for t, wi in zip(tpls, w):
            acc += wi
            if u <= acc:
                return dict(t)
        return dict(tpls[-1])

    def step(self, dt):
        mx = int(_f(self.p.get('max'), 0))
        if mx and self.count >= mx:
            return
        sim = self.sim
        sig = self.p.get('trigger') == 'signal'
        if sig:
            cur = bool(self.c('release'))
            if cur and not self.prev:
                self.pending = True
            self.prev = cur
        elif not self.pending and sim.t >= self.next_t:
            self.pending = True
        if not self.pending:
            self._blk = False
            return
        if self.tpl is None:
            self.tpl = self._tpl()
        tpl = self.tpl
        if not sim.spawn_clear(self.x, self.y, self.z, _f(tpl.get('w'), 0.25), _f(tpl.get('h'), 0.2)):
            if not self._blk:
                sim.st['emit_blocked'] += 1
            self._blk, self.waited, self.clear_t = True, True, None
            return
        self._blk = False
        if self.waited and not sig:
            # 出料口被堵过（比如停线）：出料口空出来后再等一个间隔，免得一下子挤出一串
            if self.clear_t is None:
                self.clear_t = sim.t
            if sim.t - self.clear_t < self.gap:
                return
        p = sim.add_part(tpl, self.x, self.y, self.z, math.radians(_f(self.p.get('yaw'), 0) + self.rot), src=self.id)
        self.count += 1
        self.pending, self.tpl, self.waited, self.clear_t = False, None, False, None
        if not sig:                      # 下一件从这件真正放出时起算
            self.gap = max(0.2, sim.expr(self.p.get('interval'), 6.0))
            self.next_t = sim.t + self.gap
        if self.last_t > -1e8:
            self.intervals.append(sim.t - self.last_t)
        self.last_t = sim.t
        return p

    def view(self):
        return {'n': self.count}


class CellEntry(Emitter):
    def init(self):
        super().init()
        self.ready = False

    def step(self, dt):
        sim = self.sim
        self.ready = bool(sim.entry_ready())
        self.sig['ready'] = self.ready
        if self.p.get('trigger') == 'signal':
            cur = bool(self.c('release'))
            if cur and not self.prev:
                self.pending = True
            self.prev = cur
        else:
            self.pending = self.ready and sim.t - self.last_t >= _f(self.p.get('min_gap'), 2.0)
        if not self.pending or not self.ready:
            return
        if not sim.spawn_clear(self.x, self.y, self.z, 0.3, 0.3):
            self.waited, self.clear_t = True, None
            return
        if self.waited and self.p.get('trigger') != 'signal':     # 入口被堵过：空出来后再等一个最小间隔
            if self.clear_t is None:
                self.clear_t = sim.t
            if sim.t - self.clear_t < _f(self.p.get('min_gap'), 2.0):
                return
        pp = sim.entry_take()
        if pp is None:
            return
        tpl = self._assign(pp)
        p = sim.add_part(tpl, self.x, self.y, self.z, math.radians(self.rot), src=self.id)
        p.plant = pp
        self.count += 1
        self.pending, self.waited, self.clear_t = False, False, None
        self.last_t = sim.t

    def _assign(self, pp):
        a = self.p.get('assign') or {}
        tpl = {'kind': 'box', 'color': 'blue', 'material': 'plastic', 'h': 0.2, 'w': 0.25}
        tpl.update(a.get('default') or {})
        for k in ('kind', 'color', 'material', 'h', 'w'):
            if isinstance(pp, dict) and pp.get(k) not in (None, ''):
                tpl[k] = pp[k]
        bt = (a.get('by_type') or {}).get(pp.get('type') if isinstance(pp, dict) else None)
        if bt:
            tpl.update(bt)
        rnd = a.get('random')
        if rnd:
            w = [max(0.0, _f(t.get('weight'), 1.0)) for t in rnd]
            u = self.sim.rng.random() * (sum(w) or 1)
            acc = 0.0
            for t, wi in zip(rnd, w):
                acc += wi
                if u <= acc:
                    tpl.update({k: v for k, v in t.items() if k != 'weight'})
                    break
        if a.get('defect') and isinstance(pp, dict) and pp.get('defects'):     # 带真实缺陷的件（如检测漏检）：外观按 defect 规则（视觉可识别）
            tpl.update(a['defect'])
        if isinstance(pp, dict):
            for k in ('kind', 'color', 'material'):
                pp.setdefault(k, tpl.get(k))
        return tpl


class Remover(Comp):
    def init(self):
        self.count = 0
        self.ok = 0
        self.bad = 0
        self.depth = _f(self.p.get('depth'), 0.6)

    def inside(self, part):
        lx, ly = self.loc(part.x, part.y)
        return abs(lx) <= self.L / 2 and abs(ly) <= self.W / 2 and self.z - 0.05 <= part.z <= self.z + self.depth

    def view(self):
        return {'n': self.count, 'ok': self.ok, 'bad': self.bad}


class CellExit(Remover):
    def init(self):
        super().init()
        self.busy = False

    def sense(self):
        self.sig['busy'] = self.busy


class BeamSensor(Comp):
    """漫反射 / 对射：光束从 pos 沿局部 -y。"""
    material = None

    def init(self):
        self.rng_ = _f(self.p.get('range'), 0.8)
        self.hit = None
        self.hit_d = self.rng_
        self.det = False

    def sense(self):
        best, bd = None, self.rng_
        z = self.z
        for p in self.sim.live:
            if not (p.z - 1e-6 <= z <= p.z + p.h + 1e-6):
                continue
            if self.material and p.material != self.material:
                continue
            lx, ly = self.loc(p.x, p.y)
            if abs(lx) >= p.r or ly > p.r or ly < -self.rng_ - p.r:
                continue
            # 光束（沿 -y 的线段）与圆相交：入射点距离
            dd = -ly - math.sqrt(max(0.0, p.r * p.r - lx * lx))
            dd = max(0.0, dd)
            if dd < bd:
                bd, best = dd, p
        self.hit = best
        self.hit_d = bd if best else self.rng_
        self.det = best is not None
        self.sig['detect'] = self.det != bool(self.p.get('nc'))

    def view(self):
        return {'d': self.det, 'len': round(self.hit_d, 3)}


class ProxSensor(Comp):
    """电容 / 电感接近开关：面前 range 内的零件。"""

    def init(self):
        self.rng_ = _f(self.p.get('range'), 0.12)
        self.det = False

    def sense(self):
        det = False
        for p in self.sim.live:
            if self.type == 'inductive' and p.material != 'metal':
                continue
            if not (p.z - 0.05 <= self.z <= p.z + p.h + 0.05):
                continue
            lx, ly = self.loc(p.x, p.y)
            if _circle_rect(lx, ly, p.r, -0.03, 0.03, -self.rng_, 0.0):
                det = True
                break
        self.det = det
        self.sig['detect'] = det != bool(self.p.get('nc'))

    def view(self):
        return {'d': self.det}


class DownSensor(Comp):
    """视觉 / 测高：装在上方朝下，零件中心进入视野。"""

    def init(self):
        self.rad = _f(self.p.get('radius'), 0.1)
        self.cur = None

    def sense(self):
        cur = None
        for p in self.sim.live:
            if p.top() > self.z or p.held is not None and p.top() > self.z - 0.02:
                continue
            if (p.x - self.x) ** 2 + (p.y - self.y) ** 2 <= self.rad * self.rad:
                if cur is None or p.top() > cur.top():
                    cur = p
        self.cur = cur
        if self.type == 'vision_sensor':
            self.sig['detect'] = cur is not None
            if cur is None:
                self.sig['code'] = 0
            else:
                m = self.p.get('mode')
                cc, kc = COLOR_CODE.get(cur.color, 9), KIND_CODE.get(cur.kind, 9)
                self.sig['code'] = kc if m == 'kind' else kc * 10 + cc if m == 'id' else cc
        else:
            self.sig['value'] = int(round(cur.h * 1000)) if cur is not None else 0

    def view(self):
        return {'d': self.cur is not None, 'z': round(self.cur.top(), 3) if self.cur is not None else None}


class Encoder(Comp):
    def init(self):
        self.cnt = 0.0

    def sense(self):
        cv = self.sim.comps.get(self.p.get('conveyor') or '')
        if cv is not None and hasattr(cv, 'travel'):
            self.cnt = cv.travel * _f(self.p.get('ppm'), 1000)
        v = int(self.cnt)
        self.sig['count'] = ((v + 2 ** 31) % 2 ** 32) - 2 ** 31

    def view(self):
        return {'n': int(self.cnt)}


class Pusher(Comp):
    solid = True

    def init(self):
        self.pos = 0.0
        self.stroke = _f(self.p.get('stroke'), 0.8)
        self.hw = _f(self.p.get('head'), 0.4) / 2

    def head_rect(self):
        # 局部坐标：推板面在 y = -pos，厚 0.05 向 +y
        return -self.hw, self.hw, -self.pos, -self.pos + 0.05

    def step(self, dt):
        if self.p.get('mode') == 'double':
            e, r = self.c('extend'), self.c('retract')
            if e and r:
                self.sim.violation(self, 'extend+retract')
            tgt = self.stroke if e and not r else 0.0 if r and not e else self.pos
        else:
            tgt = self.stroke if self.c('extend') else 0.0
        if self.sim.estop_cut:
            tgt = self.pos
        v = _f(self.p.get('speed'), 1.0) * self.speed_factor()
        old = self.pos
        d = tgt - self.pos
        self.pos = tgt if abs(d) <= v * dt else self.pos + math.copysign(v * dt, d)
        self.moving = abs(self.pos - old) > 1e-9
        if self.pos > old:
            self.sim.sweep_push(self, self.vec(0.0, -1.0), self._pen)

    def _pen(self, p):
        """推板与零件重叠时，零件要沿推出方向移动多少。"""
        if p.held is not None or not _vert(p, self.z - 0.1, self.z + 0.1):
            return 0.0
        lx, ly = self.loc(p.x, p.y)
        x0, x1, y0, y1 = self.head_rect()
        if ly >= y1 or not _circle_rect(lx, ly, p.r, x0, x1, y0, y1):
            return 0.0
        return max(0.0, (ly + p.r) - y0)         # 零件 +y 边要退到推板面之前

    def blocks(self, part, x, y):
        if self.pos < 0.005 or not _vert(part, self.z - 0.1, self.z + 0.1):
            return False
        lx, ly = self.loc(x, y)
        x0, x1, y0, y1 = self.head_rect()
        return _circle_rect(lx, ly, part.r, x0, x1, y0, y1 + self.pos)

    def sense(self):
        self.sig['front'] = self.pos >= self.stroke - 0.005
        self.sig['back'] = self.pos <= 0.005

    def view(self):
        return {'p': round(self.pos, 3)}


class Stopper(Comp):
    solid = True

    def init(self):
        self.u = 0.0
        self.width = _f(self.p.get('width'), self.W)
        self.hit_flag = False

    def want_up(self):
        if self.p.get('normally_up'):
            return not self.c('lower')
        return bool(self.c('raise'))

    def step(self, dt):
        tgt = 1.0 if self.want_up() else 0.0
        f = self.speed_factor()
        if f <= 0:
            return
        rate = dt / max(0.02, _f(self.p.get('time'), 0.15)) * f
        old = self.u
        if tgt > self.u:
            # 挡板升起时正上方有零件：顶到零件底面，记碰撞，升不起来
            over = [p for p in self.sim.live if p.held is None and self._over(p)]
            if over:
                if self.u < 0.05 and not self.hit_flag:
                    self.sim.collide(self, over[0], _tr('挡板升起时顶到零件'))
                    self.hit_flag = True
                return
        self.hit_flag = False
        self.u = tgt if abs(tgt - self.u) <= rate else self.u + math.copysign(rate, tgt - self.u)
        self.moving = self.u != old

    def _over(self, p):
        lx, ly = self.loc(p.x, p.y)
        return abs(lx) < p.r * 0.6 and abs(ly) <= self.width / 2 + p.r * 0.5

    def blocks(self, part, x, y):
        if self.u < 0.5 or part.z > self.z + _f(self.p.get('height'), 0.25) + 0.05 - 0.005:
            return False                 # 挡板只伸出台面 5 cm：托起的货物从上面过去
        lx, ly = self.loc(x, y)
        return _circle_rect(lx, ly, part.r, -0.015, 0.015, -self.width / 2, self.width / 2)

    def view(self):
        return {'u': round(self.u, 2)}


class PivotArm(Comp):
    solid = True

    def init(self):
        self.a = 0.0
        self.La = _f(self.p.get('length'), 0.85)
        self.amax = math.radians(_f(self.p.get('angle'), 45))

    def seg(self, a=None):
        a = self.a if a is None else a
        dx, dy = self.vec(math.cos(a) * self.La, -math.sin(a) * self.La)
        return self.x, self.y, self.x + dx, self.y + dy

    def _dist(self, x, y, a=None):
        x0, y0, x1, y1 = self.seg(a)
        vx, vy = x1 - x0, y1 - y0
        L2 = vx * vx + vy * vy or 1e-9
        t = _clamp(((x - x0) * vx + (y - y0) * vy) / L2, 0.0, 1.0)
        cx, cy = x0 + t * vx, y0 + t * vy
        return math.hypot(x - cx, y - cy), cx, cy, t

    def step(self, dt):
        tgt = self.amax if self.c('turn') else 0.0
        if self.sim.estop_cut:
            tgt = self.a
        w = math.radians(_f(self.p.get('speed'), 180)) * self.speed_factor()
        old = self.a
        d = tgt - self.a
        self.a = tgt if abs(d) <= w * dt else self.a + math.copysign(w * dt, d)
        self.moving = self.a != old
        if self.moving:
            # 摆臂扫过零件：把零件沿摆臂法向推开
            for p in self.sim.live:
                if p.held is not None or not _vert(p, self.z - 0.1, self.z + 0.12):
                    continue
                dist, cx, cy, t = self._dist(p.x, p.y)
                lim = p.r + 0.03
                if dist < lim and t > 0.02:
                    nx, ny = (p.x - cx, p.y - cy)
                    n = math.hypot(nx, ny)
                    if n < 1e-6:
                        nx, ny = self.vec(-math.sin(self.a), -math.cos(self.a))
                        n = 1.0
                    self.sim.push_part(p, nx / n * (lim - dist), ny / n * (lim - dist), self)

    def blocks(self, part, x, y):
        if not _vert(part, self.z - 0.1, self.z + 0.12):
            return False
        dist, _, _, t = self._dist(x, y)
        if dist >= part.r + 0.03:
            return False
        cur = self._dist(part.x, part.y)[0]
        return dist < cur - 1e-6          # 只挡往摆臂里钻的移动，贴着摆臂滑动不挡

    def slide_dir(self):
        """零件顶在摆臂上时沿摆臂往末端滑。"""
        dx, dy = self.vec(math.cos(self.a), -math.sin(self.a))
        return dx, dy

    def sense(self):
        self.sig['turned'] = self.a >= self.amax - 1e-3
        self.sig['home'] = self.a <= 1e-3

    def view(self):
        return {'a': round(math.degrees(self.a), 1)}


class Turntable(Comp):
    surface = True

    def init(self):
        self.R = min(self.L, self.W) / 2
        self.top = self.z + _f(self.p.get('height'), 0.25)
        self.a = 0.0
        self.da = 0.0
        self.v = 0.0
        self.amax = math.radians(_f(self.p.get('angle'), 90))
        self.flag = False

    def step(self, dt):
        f = self.speed_factor()
        tgt = self.amax if self.c('turn') else 0.0
        if self.sim.estop_cut:
            tgt = self.a
        w = math.radians(_f(self.p.get('speed'), 90)) * f
        old = self.a
        d = tgt - self.a
        self.a = tgt if abs(d) <= w * dt else self.a + math.copysign(w * dt, d)
        self.da = self.a - old
        self.moving = abs(self.da) > 1e-9
        if self.moving:
            if not self.flag:
                for p in self.sim.live:
                    if p.held is not None or not _vert(p, self.top - 0.02, self.top + 0.05):
                        continue
                    dd = math.hypot(p.x - self.x, p.y - self.y)
                    on = p.sup is self
                    if (on and dd + p.r * 0.7 > self.R) or (not on and dd < self.R + p.r * 0.3):
                        self.sim.collide(self, p, _tr('转台转动时零件没完全在台面上'))
                        self.flag = True
                        break
        else:
            self.flag = False
        dirn = (1.0 if self.c('roll_fwd') else 0.0) - (1.0 if self.c('roll_rev') else 0.0)
        if self.sim.estop_cut:
            dirn = 0.0
        self.v = _f(self.p.get('roll_speed'), 0.3) * f * dirn

    def top_at(self, x, y, z, follow=False):
        if (x - self.x) ** 2 + (y - self.y) ** 2 <= self.R * self.R and (follow or self.top <= z + STEP_UP):
            return self.top
        return None

    def disp(self, part, dt):
        dx, dy = part.x - self.x, part.y - self.y
        ca, sa = math.cos(self.da), math.sin(self.da)
        nx, ny = self.x + dx * ca - dy * sa, self.y + dx * sa + dy * ca
        th = math.radians(self.rot) + self.a
        nx += math.cos(th) * self.v * dt
        ny += math.sin(th) * self.v * dt
        return nx - part.x, ny - part.y, self.da

    def sense(self):
        self.sig['home'] = abs(self.a) < 1e-3
        self.sig['turned'] = abs(self.a - self.amax) < 1e-3
        self.sig['part'] = any(p.sup is self and math.hypot(p.x - self.x, p.y - self.y) < 0.12 for p in self.sim.live)

    def blocks(self, part, x, y):
        if self.top <= part.z + STEP_UP or not _vert(part, self.top - self.thick, self.top):
            return False
        return (x - self.x) ** 2 + (y - self.y) ** 2 < (self.R + part.r * 0.9) ** 2

    def view(self):
        return {'a': round(math.degrees(self.a), 1), 'v': round(self.v, 3)}

    def power(self):
        return 0.4 if self.moving or self.v else 0.0


class Lift(Comp):
    surface = True

    def init(self):
        self.z_lo = self.z + _f(self.p.get('height'), 0.25)
        self.z_hi = self.z + _f(self.p.get('z_high'), 1.0)
        self.top = self.z_lo
        self.v = 0.0
        self.flag = False

    def step(self, dt):
        f = self.speed_factor()
        tgt = self.z_hi if self.c('up') else self.z_lo
        if self.sim.estop_cut:
            tgt = self.top
        v = _f(self.p.get('speed'), 0.4) * f
        old = self.top
        d = tgt - self.top
        self.top = tgt if abs(d) <= v * dt else self.top + math.copysign(v * dt, d)
        self.moving = abs(self.top - old) > 1e-9
        if self.moving and not self.flag:
            for p in self.sim.live:
                if p.held is not None:
                    continue
                lx, ly = self.loc(p.x, p.y)
                on = p.sup is self
                inside = abs(lx) <= self.L / 2 - p.r * 0.6 and abs(ly) <= self.W / 2 - p.r * 0.6
                touch = _circle_rect(lx, ly, p.r * 0.8, -self.L / 2, self.L / 2, -self.W / 2, self.W / 2)
                if (on and not inside) or (not on and touch and _vert(p, min(old, self.top) - 0.1, max(old, self.top) + 0.01)):
                    self.sim.collide(self, p, _tr('升降台升降时零件卡在台边'))
                    self.flag = True
                    break
        if not self.moving:
            self.flag = False
        dirn = (1.0 if self.c('roll_fwd') else 0.0) - (1.0 if self.c('roll_rev') else 0.0)
        if self.sim.estop_cut:
            dirn = 0.0
        self.v = _f(self.p.get('roll_speed'), 0.3) * f * dirn

    def top_at(self, x, y, z, follow=False):
        lx, ly = self.loc(x, y)
        if abs(lx) <= self.L / 2 and abs(ly) <= self.W / 2 and (follow or self.top <= z + STEP_UP):
            return self.top
        return None

    def disp(self, part, dt):
        vx, vy = self.vec(self.v * dt, 0.0)
        return vx, vy, 0.0

    def blocks(self, part, x, y):
        if self.top <= part.z + STEP_UP or not _vert(part, self.top - self.thick, self.top):
            return False
        lx, ly = self.loc(x, y)
        return _circle_rect(lx, ly, part.r * 0.9, -self.L / 2, self.L / 2, -self.W / 2, self.W / 2)

    def sense(self):
        self.sig['bottom'] = abs(self.top - self.z_lo) < 1e-3
        self.sig['top'] = abs(self.top - self.z_hi) < 1e-3
        self.sig['part'] = any(p.sup is self and abs(self.loc(p.x, p.y)[0]) < 0.15 for p in self.sim.live)

    def view(self):
        return {'z': round(self.top, 3), 'v': round(self.v, 3)}

    def power(self):
        return 0.75 if self.moving else 0.1 if self.v else 0.0


class PickPlace(Comp):
    def init(self):
        self.X = 0.0
        self.Z = 0.0           # 下降量（0 = 最高）
        self.xs = _f(self.p.get('x_stroke'), 1.2)
        self.zs = _f(self.p.get('z_stroke'), 0.6)
        self.ztop = _f(self.p.get('z_top'), 1.1) + self.z
        self.carry = None
        self.contact = False
        self.tx = self.tz = 0.0
        self.hit = False

    def tool(self, X=None, Z=None):
        X = self.X if X is None else X
        Z = self.Z if Z is None else Z
        x, y = self.wld(X, 0.0)
        return x, y, self.ztop - Z

    def step(self, dt):
        f = self.speed_factor()
        servo = self.p.get('mode') == 'servo'
        if servo:
            self.tx = _clamp(_f(self.c('x_set'), 0) / 1000.0, 0.0, self.xs)
            self.tz = _clamp(_f(self.c('z_set'), 0) / 1000.0, 0.0, self.zs)
        else:
            self.tx = self.xs if self.c('x_ext') else 0.0
            self.tz = self.zs if self.c('z_down') else 0.0
        if self.sim.estop_cut:
            self.tx, self.tz = self.X, self.Z
        sim = self.sim
        moved = False
        # Z 轴
        vz = _f(self.p.get('z_speed'), 0.5) * f * dt
        if abs(self.tz - self.Z) > 1e-9:
            nz = self.tz if abs(self.tz - self.Z) <= vz else self.Z + math.copysign(vz, self.tz - self.Z)
            if nz > self.Z:
                # 往下：最低点（吸盘或吸着的零件底面）不能穿过下面的台面/零件
                x, y, tip = self.tool()
                low_r = self.carry.r if self.carry is not None else 0.03
                bottom_off = self.carry.h if self.carry is not None else 0.0
                floor_z = sim.support_under(x, y, tip - bottom_off, low_r, skip=self.carry)
                min_tip = floor_z + bottom_off
                lim = self.ztop - min_tip
                if nz >= lim:
                    nz = max(self.Z, lim)
                    self.contact = True
                else:
                    self.contact = False
            else:
                self.contact = False
            moved = moved or abs(nz - self.Z) > 1e-9
            self.Z = nz
        # X 轴：吸盘或零件比沿途的东西低就会撞上
        vx = _f(self.p.get('x_speed'), 0.8) * f * dt
        if abs(self.tx - self.X) > 1e-9:
            nX = self.tx if abs(self.tx - self.X) <= vx else self.X + math.copysign(vx, self.tx - self.X)
            nx, ny, ntip = self.tool(nX, self.Z)
            blocker = sim.tool_blocked(self, nx, ny, ntip)
            if blocker is not None:
                if not self.hit:
                    sim.collide(self, blocker, _tr('机械手水平移动时撞到零件/台面（先抬起再平移）'))
                    self.hit = True
            else:
                self.hit = False
                moved = True
                self.X = nX
        self.moving = moved
        # 吸取 / 释放
        x, y, tip = self.tool()
        if self.c('grip') and not self.sim.estop_cut:
            if self.carry is None:
                for p in sim.live:
                    if p.held is None and abs(p.top() - tip) < 0.02 and (p.x - x) ** 2 + (p.y - y) ** 2 <= (p.r * 0.8) ** 2:
                        self.carry = p
                        p.held = self
                        p.sup = None
                        break
        elif self.carry is not None:
            sim.release(self.carry)
            self.carry = None
        if self.carry is not None:
            p = self.carry
            p.dx, p.dy = x - p.x, y - p.y
            p.x, p.y, p.z = x, y, tip - p.h

    def sense(self):
        servo = self.p.get('mode') == 'servo'
        if servo:
            self.sig['x_pos'] = int(round(self.X * 1000))
            self.sig['z_pos'] = int(round(self.Z * 1000))
            self.sig['x_at'] = abs(self.X - self.tx) < 0.002
            self.sig['z_at'] = abs(self.Z - self.tz) < 0.002 or (self.contact and self.tz > self.Z)
        else:
            self.sig['x_back'] = self.X < 0.003
            self.sig['x_front'] = self.X > self.xs - 0.003
            self.sig['z_top'] = self.Z < 0.003
            self.sig['z_bottom'] = self.Z > self.zs - 0.003 or self.contact
        self.sig['gripped'] = self.carry is not None

    def view(self):
        return {'x': round(self.X, 3), 'z': round(self.Z, 3), 'g': self.carry is not None, 'on': bool(self.c('grip'))}

    def power(self):
        return 0.6 if self.moving else 0.05


class Rack(Comp):
    surface = True
    thick = 0.04

    def init(self):
        self.cols = max(1, int(_f(self.p.get('cols'), 4)))
        self.rows = max(1, int(_f(self.p.get('rows'), 3)))
        self.ch = _f(self.p.get('cell_h'), 0.5)
        self.base = _f(self.p.get('base'), 0.3)
        self.cw = self.L / self.cols
        self.levels = [self.z + self.base + r * self.ch for r in range(self.rows)]

    def slot(self, c, r):
        x, y = self.wld(-self.L / 2 + (c + 0.5) * self.cw, 0.0)
        return x, y, self.levels[r]

    def top_at(self, x, y, z, follow=False):
        lx, ly = self.loc(x, y)
        if abs(lx) > self.L / 2 or abs(ly) > self.W / 2:
            return None
        best = None
        for t in self.levels:
            if t <= z + STEP_UP + (0.05 if follow else 0):
                best = t
        return best

    def blocks(self, part, x, y):
        lx, ly = self.loc(x, y)
        if not _circle_rect(lx, ly, part.r * 0.9, -self.L / 2, self.L / 2, -self.W / 2, self.W / 2):
            return False
        for t in self.levels:
            if t > part.z + STEP_UP and _vert(part, t - self.thick, t):
                return True
        return False

    def occupancy(self):
        occ = [[0] * self.cols for _ in range(self.rows)]
        for p in self.sim.live:
            if p.sup is self:
                lx, _ = self.loc(p.x, p.y)
                c = int(_clamp((lx + self.L / 2) // self.cw, 0, self.cols - 1))
                r = min(range(self.rows), key=lambda i: abs(self.levels[i] - p.z))
                occ[r][c] += 1
        return occ

    def view(self):
        return {'occ': self.occupancy()}


class StackerCrane(Comp):
    surface = True
    thick = 0.03

    def init(self):
        self.X = 0.0
        self.travel = _f(self.p.get('travel'), self.L)
        self.Zf = None           # 货叉高度（绝对）
        self.F = 0.0             # 货叉伸出（+y 正）
        self.lift = 0.0
        self.fs = _f(self.p.get('fork_stroke'), 0.7)
        self.hit = False
        self.targets = []
        self.ox = self.oy = 0.0
        self._last = (0.0, 0.0, 0.0)

    def build_targets(self):
        tg = self.p.get('targets') or []
        if tg:
            self.targets = [(float(a), float(b)) for a, b in tg]
        else:
            self.targets = []
            si = self.p.get('station_in')
            self.targets.append((float(si[0]), float(si[1])) if si else (0.0, self.z + 0.22))
            rk = self.sim.comps.get(self.p.get('rack') or '')
            if isinstance(rk, Rack):
                for r in range(rk.rows):
                    for c in range(rk.cols):
                        x, y, t = rk.slot(c, r)
                        lx, _ = self.loc(x, y)
                        self.targets.append((lx, t - 0.04))
            so = self.p.get('station_out')
            self.targets.append((float(so[0]), float(so[1])) if so else (self.travel, self.z + 0.22))
        if self.Zf is None:
            self.X, self.Zf = self.targets[0]

    def fork_top(self):
        return self.Zf + 0.02 + 0.08 * self.lift

    def fork_rect(self):
        # 货叉在局部：x ∈ X±0.22，y ∈ [0, F]（或 [F, 0]）
        y0, y1 = (0.0, self.F) if self.F >= 0 else (self.F, 0.0)
        return self.X - 0.22, self.X + 0.22, y0 - 0.25, y1 + 0.25

    def step(self, dt):
        if not self.targets:
            self.build_targets()
        f = self.speed_factor()
        sim = self.sim
        ti = int(_f(self.c('target'), 0))
        tx, tz = self.targets[ti] if 0 <= ti < len(self.targets) else (self.X, self.Zf)
        old = (self.X, self.Zf, self.F)
        need = abs(tx - self.X) > 1e-6 or abs(tz - self.Zf) > 1e-6
        if sim.estop_cut:
            need = False
        self.moving = False
        if need:
            if abs(self.F) > 0.01:
                if not self.hit:
                    sim.collide(self, None, _tr('堆垛机货叉没收回就行走/升降'))
                    self.hit = True
            else:
                self.hit = False
                vx = _f(self.p.get('x_speed'), 1.0) * f * dt
                vz = _f(self.p.get('z_speed'), 0.6) * f * dt
                d = tx - self.X
                self.X = tx if abs(d) <= vx else self.X + math.copysign(vx, d)
                d = tz - self.Zf
                self.Zf = tz if abs(d) <= vz else self.Zf + math.copysign(vz, d)
                self.moving = True
        else:
            self.hit = False
        l, r = self.c('fork_left'), self.c('fork_right')
        if l and r:
            sim.violation(self, 'fork_left+fork_right')
        ft = self.fs if l and not r else -self.fs if r and not l else 0.0
        if sim.estop_cut or self.moving:
            ft = self.F
        vf = _f(self.p.get('fork_speed'), 0.5) * f * dt
        d = ft - self.F
        nF = ft if abs(d) <= vf else self.F + math.copysign(vf, d)
        # 货叉伸进去时如果撞到货物侧面（货叉高度在货物竖直范围内）→ 碰撞，停住
        if abs(nF) > abs(self.F):
            ft_top = self.fork_top()
            for p in sim.live:
                if p.sup is self or p.held is not None:
                    continue
                lx, ly = self.loc(p.x, p.y)
                if abs(lx - self.X) < 0.22 + p.r * 0.5 and (min(0, nF) - 0.25 <= ly <= max(0, nF) + 0.25) and p.z + 0.01 < ft_top < p.z + p.h:
                    if not self.hit:
                        sim.collide(self, p, _tr('货叉伸出时撞到货物（高度不对）'))
                        self.hit = True
                    nF = self.F
                    break
        self.F = nF
        lt = 1.0 if self.c('lift') and not sim.estop_cut else 0.0
        if f > 0:
            self.lift = lt if abs(lt - self.lift) <= dt / 0.3 * f else self.lift + math.copysign(dt / 0.3 * f, lt - self.lift)
        self.moving = self.moving or abs(self.F - old[2]) > 1e-9
        # 本步货叉位移（托在货叉上的货物跟着走）
        x0, y0 = self.wld(old[0], old[2])
        x1, y1 = self.wld(self.X, self.F)
        self.ox, self.oy = x1 - x0, y1 - y0

    def top_at(self, x, y, z, follow=False):
        if self.Zf is None:
            return None
        lx, ly = self.loc(x, y)
        x0, x1, y0, y1 = self.fork_rect()
        t = self.fork_top()
        if x0 <= lx <= x1 and y0 <= ly <= y1 and (follow or t <= z + STEP_UP + 0.09):
            return t
        return None

    def disp(self, part, dt):
        return self.ox, self.oy, 0.0

    def sense(self):
        if not self.targets:
            self.build_targets()
        ti = int(_f(self.c('target'), 0))
        idx = -1
        for i, (tx, tz) in enumerate(self.targets):
            if abs(tx - self.X) < 0.003 and abs(tz - self.Zf) < 0.003:
                idx = i
                break
        self.sig['at_target'] = idx == ti
        self.sig['moving'] = self.moving and abs(self.F) < 0.01
        self.sig['fork_home'] = abs(self.F) < 0.005
        self.sig['fork_left_end'] = self.F > self.fs - 0.005
        self.sig['fork_right_end'] = self.F < -self.fs + 0.005
        self.sig['loaded'] = any(p.sup is self for p in self.sim.live)
        self.sig['pos'] = idx

    def view(self):
        return {'x': round(self.X, 3), 'z': round(self.Zf or 0, 3), 'f': round(self.F, 3), 'l': round(self.lift, 2)}

    def power(self):
        return 1.5 if self.moving else 0.1


class Gripper(Comp):
    def init(self):
        self.u = 0.0
        self.width = _f(self.p.get('width'), self.W)
        self.hold = None

    def step(self, dt):
        f = self.speed_factor()
        tgt = 1.0 if self.c('close') else 0.0
        if f > 0 and not self.sim.estop_cut:
            rate = dt / max(0.02, _f(self.p.get('time'), 0.2)) * f
            self.u = tgt if abs(tgt - self.u) <= rate else self.u + math.copysign(rate, tgt - self.u)
        if self.u >= 0.99 and self.hold is None:
            for p in self.sim.live:
                if p.held is None and abs(self.loc(p.x, p.y)[0]) < 0.12 and abs(self.loc(p.x, p.y)[1]) < self.width / 2 and _vert(p, self.z - 0.1, self.z + 0.1):
                    self.hold = p
                    p.held = self
                    break
        elif self.u < 0.99 and self.hold is not None:
            self.sim.release(self.hold)
            self.hold = None

    def sense(self):
        self.sig['closed'] = self.u >= 0.99
        self.sig['holding'] = self.hold is not None

    def view(self):
        return {'u': round(self.u, 2)}


class Motor(Comp):
    def init(self):
        self.s = 0.0
        self.tripped = False
        self.energized = False

    def step(self, dt):
        if self.p.get('reversible'):
            fw, rv = bool(self.c('fwd')), bool(self.c('rev'))
            if fw and rv:
                self.sim.violation(self, 'fwd+rev')
                tgt = 0.0
            else:
                tgt = 1.0 if fw else -1.0 if rv else 0.0
        else:
            tgt = 1.0 if self.c('run') else 0.0
        if self.fault('motor_overload'):
            self.tripped = True
        if self.tripped or self.sim.estop_cut:
            tgt = 0.0
        if self.fault('actuator_jam'):
            tgt = 0.0
        tgt *= 0.35 if self.fault('actuator_slow') else 1.0
        if tgt * self.s < 0 and abs(self.s) > 0.5:
            self.sim.st['hard_reversals'] += 1
            self.sim.log(_tr('{id} 高速直接反转', id=self.id))
        rate = dt / max(0.02, _f(self.p.get('ramp'), 0.5))
        d = tgt - self.s
        self.s = tgt if abs(d) <= rate else self.s + math.copysign(rate, d)
        self.moving = abs(self.s) > 0.01
        self.energized = tgt != 0.0

    def sense(self):
        self.sig['running'] = bool(getattr(self, 'energized', False))
        self.sig['ol_ok'] = not self.tripped

    def view(self):
        return {'s': round(self.s, 3), 'trip': self.tripped}

    def power(self):
        return _f(self.p.get('kw'), 1.5) * abs(self.s)


class Panel(Comp):
    """按钮 / 旋钮 / 急停 / 电位器：state 由界面或测试序列设置。"""

    def init(self):
        self.state = 0
        self.until = None
        if self.type == 'potentiometer':
            self.state = 0

    def step(self, dt):
        if self.until is not None and self.sim.t >= self.until:
            self.state = 0
            self.until = None

    def sense(self):
        t = self.type
        if t == 'button':
            self.sig['value'] = bool(self.state) != bool(self.p.get('nc'))
        elif t == 'estop':
            self.sig['value'] = not self.state
        elif t == 'switch':
            if int(_f(self.p.get('positions'), 2)) == 3:
                self.sig['left'] = self.state == -1
                self.sig['right'] = self.state == 1
            else:
                self.sig['value'] = bool(self.state)
        elif t == 'potentiometer':
            self.sig['value'] = int(_clamp(_f(self.state), 0, _f(self.p.get('max'), 1000)))

    def view(self):
        return {'s': self.state}


class Lamp(Comp):
    def view(self):
        if self.type == 'display':
            return {'v': int(_f(self.c('value'), 0))}
        return {'on': bool(self.c('on'))}


class PalletTable(Comp):
    surface = True

    def init(self):
        self.top = self.z + _f(self.p.get('height'), 0.3)

    def top_at(self, x, y, z, follow=False):
        lx, ly = self.loc(x, y)
        if abs(lx) <= self.L / 2 and abs(ly) <= self.W / 2 and (follow or self.top <= z + STEP_UP):
            return self.top
        return None

    def blocks(self, part, x, y):
        if self.top <= part.z + STEP_UP or not _vert(part, self.top - self.thick, self.top):
            return False
        lx, ly = self.loc(x, y)
        return _circle_rect(lx, ly, part.r * 0.9, -self.L / 2, self.L / 2, -self.W / 2, self.W / 2)

    def stack(self):
        """托盘上的零件：(件数, 层数, 都在台面范围内)。"""
        on = [p for p in self.sim.live if p.held is None and p.sup is not None and self._chain(p)]
        layers = set()
        inside = True
        for p in on:
            lx, ly = self.loc(p.x, p.y)
            if abs(lx) > self.L / 2 - p.r * 0.5 or abs(ly) > self.W / 2 - p.r * 0.5:
                inside = False
            layers.add(round((p.z - self.top) / max(0.01, p.h)))
        return len(on), len(layers), inside

    def _chain(self, p):
        s, n = p.sup, 0
        while isinstance(s, Part) and n < 20:
            s, n = s.sup, n + 1
        return s is self

    def view(self):
        n, l, _ = self.stack()
        return {'n': n, 'layers': l}


CLASSES = {'belt_conveyor': Conveyor, 'roller_conveyor': Conveyor, 'curved_conveyor': CurvedConveyor, 'chain_transfer': ChainTransfer,
           'emitter': Emitter, 'remover': Remover, 'cell_entry': CellEntry, 'cell_exit': CellExit,
           'diffuse_sensor': BeamSensor, 'retro_sensor': BeamSensor, 'capacitive': ProxSensor, 'inductive': ProxSensor,
           'vision_sensor': DownSensor, 'height_sensor': DownSensor, 'encoder': Encoder,
           'pusher': Pusher, 'stopper': Stopper, 'pivot_arm': PivotArm, 'turntable': Turntable, 'lift': Lift, 'pick_place': PickPlace,
           'stacker_crane': StackerCrane, 'gripper': Gripper, 'motor': Motor,
           'button': Panel, 'switch': Panel, 'estop': Panel, 'potentiometer': Panel, 'lamp': Lamp, 'display': Lamp,
           'rack': Rack, 'pallet': PalletTable}


# ======================================================================= 单元
class CellSim:
    def __init__(self, cell_def: dict, rng=None):
        import numpy as np
        self.d = cell_def or {}
        self.rng = rng if rng is not None else np.random.default_rng(1)
        self.t = 0.0
        self.size = list(self.d.get('size') or [8, 4])
        self.comps: dict[str, Comp] = {}
        for c in self.d.get('components') or []:
            cls = CLASSES.get(c.get('type'))
            if cls is None or not c.get('id'):
                continue
            self.comps[str(c['id'])] = cls(self, c)
        self.io = [dict(e) for e in (self.d.get('io') or K.auto_io(self.d, keep=[]))]
        self.io_by_name = {e['name']: e for e in self.io}
        self.io_by_addr = {}
        for e in self.io:
            if e.get('addr'):
                self.io_by_addr[_norm_addr(e['addr'])] = e
        self.parts_: list[Part] = []
        self.live: list[Part] = []
        self.faults: dict[str, set] = {}
        self.io_faults: dict[str, set] = {}
        self.fault_since: dict = {}
        self.forced: dict = {}
        self.outputs: dict = {e['name']: _zero(e.get('type')) for e in self.io if e.get('dir') == 'out'}
        self.seq = 0
        self.estop_cut = False
        self.events: list = []
        self.st = {'emitted': 0, 'removed': 0, 'sorted_ok': 0, 'sorted_wrong': 0, 'dropped': 0, 'collisions': 0, 'jams': 0, 'part_contacts': 0,
                   'hard_drops': 0, 'interlock_violations': 0, 'hard_reversals': 0, 'emit_blocked': 0, 'exited': 0}
        self.removed_t: list = []
        self.lead: list = []
        self.by_bin: dict = {}
        self.contacts: set = set()
        self.viol_on: set = set()
        self._viol_seen: set = set()
        self.entry_ready = lambda: False      # 整厂接上：上游是否有料
        self.entry_take = lambda: None        # 整厂接上：取一件整厂零件
        self.exit_put = None                  # 整厂接上：(零件, 端口) → 是否被下游接收
        self.on_remove = None                 # (零件, 收料器) 回调
        self.ctx = None
        self.surfaces = [c for c in self.comps.values() if c.surface]
        self.solids = [c for c in self.comps.values() if c.solid or c.surface]
        self.sensors = [c for c in self.comps.values() if type(c).sense is not Comp.sense]
        self.removers = [c for c in self.comps.values() if isinstance(c, Remover)]
        self.emitters = [c for c in self.comps.values() if isinstance(c, Emitter)]
        self.actuators = [c for c in self.comps.values() if type(c).step is not Comp.step and not isinstance(c, Emitter)]
        for c in self.comps.values():
            if isinstance(c, StackerCrane):
                c.build_targets()
        for c in self.comps.values():
            if isinstance(c, Rack):
                for item in c.p.get('fill') or []:
                    try:
                        cc, rr = int(item[0]), int(item[1])
                        tpl = dict(item[2]) if len(item) > 2 and isinstance(item[2], dict) else {}
                    except (TypeError, ValueError, IndexError):
                        continue
                    if 0 <= cc < c.cols and 0 <= rr < c.rows:
                        tpl.setdefault('kind', 'pallet')
                        tpl.setdefault('h', 0.25)
                        tpl.setdefault('w', 0.45)
                        x, y, z = c.slot(cc, rr)
                        p = self.add_part(tpl, x, y, z, math.radians(c.rot), src=c.id, count=False)
                        p.sup = c
        for c in self.sensors:
            c.sense()

    # ---------------- 工具 ----------------
    def expr(self, src, default):
        if isinstance(src, (int, float)):
            return float(src)
        if src in (None, ''):
            return default
        try:
            return float(src)
        except (TypeError, ValueError):
            pass
        from ..flow.expr import Ctx, ExprError, evaluate
        if self.ctx is None:
            self.ctx = Ctx(self.rng)
        try:
            return float(evaluate(str(src), self.ctx))
        except (ExprError, TypeError, ValueError):
            return default

    def log(self, msg, **kw):
        self.events.append({'t': round(self.t, 2), 'msg': msg, **kw})
        if len(self.events) > 400:
            del self.events[:100]

    def collide(self, a, b, why=''):
        self.st['collisions'] += 1
        self.log(_tr('碰撞：{getattr}{v} {why}', getattr=getattr(a, 'id', a), v=' ↔ ' + b.id if b is not None else '', why=why).strip(), kind='collision')

    def violation(self, comp, what):
        key = (comp.id, what)
        if key not in self.viol_on:
            self.viol_on.add(key)
            self.st['interlock_violations'] += 1
            self.log(_tr('互锁错误：{id} {what} 同时得电', id=comp.id, what=what), kind='interlock')
        self._viol_seen.add(key)

    def add_part(self, tpl, x, y, z, yaw=0.0, src='', count=True):
        self.seq += 1
        p = Part(f"{src or 'P'}-{self.seq}", tpl, x, y, z, yaw)
        p.born = self.t
        p.src = src
        p.fall0 = z
        self.parts_.append(p)
        self.live.append(p)
        if count:
            self.st['emitted'] += 1
        return p

    def spawn_clear(self, x, y, z, w, h):
        r = w / 2
        for p in self.live:
            if (p.x - x) ** 2 + (p.y - y) ** 2 < (p.r + r) ** 2 and p.z < z + h and p.z + p.h > z - 0.3:
                return False
        return True

    def support_under(self, x, y, z, r=0.0, skip=None):
        """(x, y) 处、z 以下最高的台面/零件顶面。"""
        best = 0.0
        for c in self.surfaces:
            t = c.top_at(x, y, z)
            if t is not None and t > best:
                best = t
        for p in self.live:
            if p is skip or p.held is not None:
                continue
            if (p.x - x) ** 2 + (p.y - y) ** 2 < (p.r + r * 0.5) ** 2 and p.top() <= z + STEP_UP and p.top() > best:
                best = p.top()
        return best

    def tool_blocked(self, pp, x, y, tip):
        """取放机械手平移：吸盘（或吸着的零件）在新位置会不会撞上东西。"""
        carry = pp.carry
        low = tip - (carry.h if carry is not None else 0.0)
        r = carry.r if carry is not None else 0.03
        for p in self.live:
            if p is carry or p.held is not None:
                continue
            if (p.x - x) ** 2 + (p.y - y) ** 2 < (p.r + r) ** 2 * 0.81 and p.top() > low + 0.005 and p.z < tip:
                return p
        for c in self.surfaces:
            t = c.top_at(x, y, 99.0, follow=True)
            if t is not None and t > low + 0.005 and t - c.thick < tip:
                return c
        return None

    def release(self, p):
        p.held = None
        p.fall0 = p.z
        p.sup = None

    def push_part(self, p, dx, dy, by):
        """执行器推动零件（运动学）：被推的零件挤到别的零件上记碰撞，并把对方也挤开。"""
        p.x += dx
        p.y += dy
        p.dx += dx
        p.dy += dy
        p.blk_t = 0.0
        for q in self.live:
            if q is p or q.held is not None or not (q.z < p.z + p.h and q.z + q.h > p.z):
                continue
            dd = math.hypot(q.x - p.x, q.y - p.y)
            lim = (q.r + p.r) * 0.92
            if dd < lim:
                key = (min(p.id, q.id), max(p.id, q.id))
                if key not in self.contacts:
                    self.contacts.add(key)
                    self.collide(by, q, _tr('{id} 被推到 {id2} 上', id=p.id, id2=q.id))
                n = dd or 1e-6
                ux, uy = ((q.x - p.x) / n, (q.y - p.y) / n) if dd > 1e-6 else (dx, dy)
                m = math.hypot(ux, uy) or 1.0
                push = lim - dd
                q.x += ux / m * push
                q.y += uy / m * push

    def sweep_push(self, comp, d, pen):
        dx, dy = d
        for p in self.live:
            k = pen(p)
            if k > 1e-9:
                self.push_part(p, dx * k, dy * k, comp)

    # ---------------- I/O ----------------
    def raw(self, e):
        c = self.comps.get(e.get('comp'))
        if c is None:
            return _zero(e.get('type'))
        return c.sig.get(e.get('signal'), _zero(e.get('type')))

    def _io_index(self):
        """I/O 快速表（没有故障、强制时走快路径）。"""
        ins, outs = [], []
        for e in self.io:
            c = self.comps.get(e.get('comp'))
            typ = e.get('type') or 'BOOL'
            row = (e['name'], c, e.get('signal'), typ, _zero(typ), _norm_addr(e['addr']) if e.get('addr') else None, e.get('addr'))
            (ins if e.get('dir') == 'in' else outs).append(row)
        self._fast_in, self._fast_out = ins, outs

    def inputs(self) -> dict:
        if not (self.faults or self.io_faults or self.forced):
            if getattr(self, '_fast_in', None) is None:
                self._io_index()
            out = {}
            for nm, c, sig, typ, z, _, _ in self._fast_in:
                v = c.sig.get(sig, z) if c is not None else z
                out[nm] = (v is True or (v is not False and bool(v))) if typ == 'BOOL' else _cast(v, typ)
            return out
        out = {}
        for e in self.io:
            if e.get('dir') != 'in':
                continue
            nm = e['name']
            v = self.raw(e)
            fk = self.faults.get(e.get('comp'), set()) | self.io_faults.get(nm, set())
            if fk:
                v = self._apply_fault(e, v, fk)
            if nm in self.forced:
                v = self.forced[nm]
            out[nm] = _cast(v, e.get('type'))
        return out

    def _apply_fault(self, e, v, fk):
        typ = e.get('type')
        if 'wire_break' in fk:
            return _zero(typ)
        if 'sensor_stuck_on' in fk:
            if typ == 'BOOL':
                return True
            k = (e['name'], 'stuck')
            if k not in self.fault_since:
                self.fault_since[k] = v or 1
            return self.fault_since[k]
        if 'sensor_stuck_off' in fk:
            return _zero(typ)
        if 'sensor_flicker' in fk:
            if self.rng.random() < 0.12:
                return (not v) if typ == 'BOOL' else 0
        return v

    def apply_outputs(self, outs: dict | None):
        outs = outs or {}
        if not (self.faults or self.io_faults or self.forced):
            if getattr(self, '_fast_out', None) is None:
                self._io_index()
            cur = self.outputs
            for nm, c, sig, typ, z, na, addr in self._fast_out:
                if nm in outs:
                    v = outs[nm]
                elif na is not None and na in outs:
                    v = outs[na]
                elif addr is not None and addr in outs:
                    v = outs[addr]
                else:
                    v = cur.get(nm, z)
                v = (v is True or (v is not False and bool(v))) if typ == 'BOOL' else _cast(v, typ)
                cur[nm] = v
                if c is not None:
                    c.cmd[sig] = v
            return
        for e in self.io:
            if e.get('dir') != 'out':
                continue
            nm = e['name']
            if nm in outs:
                v = outs[nm]
            elif e.get('addr') and _norm_addr(e['addr']) in outs:
                v = outs[_norm_addr(e['addr'])]
            elif e.get('addr') in outs:
                v = outs[e['addr']]
            else:
                v = self.outputs.get(nm, _zero(e.get('type')))
            if nm in self.forced:
                v = self.forced[nm]
            v = _cast(v, e.get('type'))
            self.outputs[nm] = v
            fk = self.faults.get(e.get('comp'), set()) | self.io_faults.get(nm, set())
            if 'wire_break' in fk:
                v = _zero(e.get('type'))
            c = self.comps.get(e.get('comp'))
            if c is not None:
                c.cmd[e.get('signal')] = v

    def io_values(self):
        """当前 I/O（输入 + 输出）：{名: 值}。"""
        d = self.inputs()
        d.update(self.outputs)
        return d

    def force(self, name, value):
        e = self.io_by_name.get(name) or self.io_by_addr.get(_norm_addr(str(name)))
        if e is None:
            return _tr('没有 I/O 点 {name}', name=name)
        if value is None:
            self.forced.pop(e['name'], None)
        else:
            self.forced[e['name']] = _cast(value, e.get('type'))
        return ''

    # ---------------- 面板 ----------------
    def panel(self, comp, action='press', value=None, hold=0.3):
        c = self.comps.get(comp)
        if c is None:
            e = self.io_by_name.get(comp)
            c = self.comps.get(e['comp']) if e else None
        if not isinstance(c, Panel):
            return _tr('{comp} 不是面板按钮/开关', comp=comp)
        if c.type == 'potentiometer' or action == 'set':
            c.state = value if c.type != 'potentiometer' else int(_f(value))
            c.until = None
        elif action == 'press':
            c.state = 1
            c.until = None if c.type == 'estop' else (self.t + float(hold) if hold else None)
        elif action == 'release':
            c.state = 0
            c.until = None
        elif action == 'toggle':
            c.state = 0 if c.state else 1
            c.until = None
        else:
            return _tr('不认识的动作 {action}', action=action)
        c.sense()
        return ''

    # ---------------- 故障 ----------------
    def inject(self, comp, kind):
        if kind not in K.FAULTS:
            return _tr('不认识的故障类型 {kind}', kind=kind)
        if comp in self.comps:
            c = self.comps[comp]
            if kind not in K.faults_for(c.type):
                return _tr('{comp}（{label}）不能注入"{v}"', comp=comp, label=K.COMP_TYPES[c.type]["label"], v=K.FAULTS[kind])
            self.faults.setdefault(comp, set()).add(kind)
        elif comp in self.io_by_name:
            if kind not in ('wire_break', 'sensor_stuck_on', 'sensor_stuck_off', 'sensor_flicker'):
                return _tr('I/O 点只能注入断线或信号类故障')
            self.io_faults.setdefault(comp, set()).add(kind)
        else:
            return _tr('没有部件或 I/O 点 {comp}', comp=comp)
        self.log(_tr('注入故障：{comp} {v}', comp=comp, v=K.FAULTS[kind]), kind='fault')
        return ''

    def clear_faults(self, comp=None):
        if comp:
            self.faults.pop(comp, None)
            self.io_faults.pop(comp, None)
        else:
            self.faults.clear()
            self.io_faults.clear()
        self.fault_since.clear()
        for c in self.comps.values():
            if isinstance(c, Motor) and (comp is None or c.id == comp):
                c.tripped = False
        self.log(_tr('清除故障') + (f' {comp}' if comp else ''), kind='fault')

    def fault_list(self):
        out = [{'comp': k, 'kind': f, 'label': K.FAULTS.get(f, f)} for k, v in self.faults.items() for f in sorted(v)]
        out += [{'comp': k, 'kind': f, 'label': K.FAULTS.get(f, f), 'io': True} for k, v in self.io_faults.items() for f in sorted(v)]
        return out

    # ---------------- 推进 ----------------
    def step(self, dt=DT):
        self.t += dt
        self._viol_seen = set()
        self.estop_cut = any(c.type == 'estop' and c.state and c.p.get('hardwired') for c in self.comps.values())
        for c in self.emitters:
            c.step(dt)
        for p in self.live:
            p.dx = p.dy = 0.0
        for c in self.actuators:
            c.step(dt)
        self.viol_on &= self._viol_seen
        self._move_parts(dt)
        self._collect(dt)
        for c in self.sensors:
            c.sense()
        if OBSERVERS:
            ob = OBSERVERS.get(id(self))
            if ob is not None and ob[0]() is self:
                try:
                    ob[1](self)
                except Exception:                    # noqa: BLE001  观察者出错不能影响仿真
                    import logging
                    logging.getLogger('vfactory.control').exception(_tr('CellSim 观察者出错'))

    def _support(self, p):
        """(台面对象, 顶面高度)。先跟着上一步的支撑走（升降台、货叉上升时零件被托起）。"""
        best, bt = None, 0.0
        prev = p.sup
        if prev is not None and not isinstance(prev, Part):
            t = prev.top_at(p.x, p.y, p.z, follow=True)
            if t is not None and t <= p.z + 0.12:
                best, bt = prev, t
        for c in self.surfaces:
            if c is best:
                continue
            t = c.top_at(p.x, p.y, p.z)
            if t is not None and t > bt + 1e-9:
                best, bt = c, t
        for q in self.live:
            if q is p or q.held is not None:
                continue
            if q.kind == 'tote' and p.kind != 'tote' and q.inner(p.x, p.y):
                t = q.z + 0.03                       # 周转箱底板
                if t <= p.z + STEP_UP and t > bt + 1e-9:
                    best, bt = q, t
                continue
            if abs(q.x - p.x) < q.r * 0.9 and abs(q.y - p.y) < q.r * 0.9:
                t = q.top()
                if t <= p.z + STEP_UP and t > bt + 1e-9:
                    best, bt = q, t
        return best, bt

    def _into_tote(self, p):
        """零件落进周转箱：摆到箱内的下一个格位（2×2，满了往上叠）。"""
        for q in self.live:
            if q.kind != 'tote' or q is p or not q.inner(p.x, p.y) or p.z >= q.top():
                continue
            n = sum(1 for o in self.live if o.box == q.id)
            d = min(0.11, q.r - 0.03 - p.r)
            ox, oy = ((-d, -d), (d, -d), (-d, d), (d, d))[n % 4]
            c, s_ = math.cos(q.yaw), math.sin(q.yaw)
            p.x, p.y = q.x + ox * c - oy * s_, q.y + ox * s_ + oy * c
            p.box = q.id
            p.yaw = q.yaw
            return

    def _blocked(self, p, x, y):
        """零件移到 (x, y) 会被什么挡住：('part', q) / ('stopper', c) / ('arm', c) / ('act', c) / None。"""
        for c in self.solids:
            if c is p.sup:
                continue
            if c.blocks(p, x, y):
                if c.blocks(p, p.x, p.y):
                    continue            # 已经和它重叠（从高处落到台面边上、挡板升起时擦到零件尾部）：允许移开，不算挡住
                if isinstance(c, Stopper):
                    return 'stopper', c
                if isinstance(c, PivotArm):
                    return 'arm', c
                return 'act', c
        for q in self.live:
            if q is p or q.held is not None or q.sup is p:
                continue
            if not (q.z < p.z + p.h - 0.005 and q.z + q.h > p.z + 0.005):
                continue
            if (q.kind == 'tote' and p.box == q.id) or (p.kind == 'tote' and q.box == p.id) or (p.box and p.box == q.box):
                continue
            lim = (q.r + p.r) * 0.98
            ddx, ddy = q.x - x, q.y - y
            if ddx * ddx + ddy * ddy < lim * lim:
                # 只挡"往对方方向走"的移动（已经挤在一起的零件可以分开）
                if (q.x - p.x) * (x - p.x) + (q.y - p.y) * (y - p.y) > 0:
                    return 'part', q
        return None

    def _move_parts(self, dt):
        order = sorted((p for p in self.live if p.held is None and not p.exit_wait), key=lambda q: q.z)
        for p in order:
            sup, top = self._support(p)
            # 下落
            if p.z > top + 1e-6:
                if p.fall0 is None:
                    p.fall0 = p.z
                p.z = max(top, p.z - FALL_V * dt)
                if p.box is None and p.kind != 'tote':
                    self._into_tote(p)
                if p.z > top + 1e-6:
                    p.sup = None
                    continue
            p.z = top
            if p.fall0 is not None:
                h = p.fall0 - top
                if h > HARD_DROP and sup is not None:
                    self.st['hard_drops'] += 1
                    self.log(_tr('{id} 从 {h:.2f} m 高处摔下', id=p.id, h=h), kind='drop')
                p.fall0 = None
            p.sup = sup
            if sup is None:
                if not p.dead:
                    p.dead, p.dead_t = True, self.t
                    self.st['dropped'] += 1
                    self.log(_tr('{id} 掉到地上', id=p.id), kind='drop')
                continue
            if isinstance(sup, Part):
                dx, dy, da = sup.dx, sup.dy, 0.0
            else:
                dx, dy, da = sup.disp(p, dt)
            if abs(dx) < 1e-12 and abs(dy) < 1e-12:
                p.yaw += da
                p.blk_t = 0.0
                continue
            nx, ny = p.x + dx, p.y + dy
            hit = self._blocked(p, nx, ny)
            if hit is not None and hit[0] == 'arm':
                # 沿摆臂滑向末端
                sx, sy = hit[1].slide_dir()
                k = dx * sx + dy * sy
                if k > 0:
                    nx2, ny2 = p.x + sx * k, p.y + sy * k
                    if self._blocked(p, nx2, ny2) is None:
                        nx, ny, hit = nx2, ny2, None
            if hit is None:
                p.x, p.y = nx, ny
                p.dx += dx
                p.dy += dy
                p.yaw += da
                p.blk_t = 0.0
                if p.jam:
                    p.jam = False
                p.contacts.clear()
                continue
            kind, obj = hit
            if kind == 'part':
                if obj.id not in p.contacts:
                    p.contacts.add(obj.id)
                    self.st['part_contacts'] += 1
            elif kind == 'stopper':
                p.holds[obj.id] = p.holds.get(obj.id, 0.0) + dt
            if kind in ('act', 'arm'):
                p.blk_t += dt
                if p.blk_t >= JAM_S and not p.jam:
                    p.jam = True
                    self.st['jams'] += 1
                    self.log(_tr('卡件：{id} 被 {id2} 挡住', id=p.id, id2=obj.id), kind='jam')
            else:
                p.blk_t = 0.0

    def _collect(self, dt):
        keep = []
        for p in self.live:
            if p.dead:
                if self.t - p.dead_t > 1.5:
                    continue
                keep.append(p)
                continue
            gone = False
            if p.held is None and p.box is None:
                for r in self.removers:
                    if r.inside(p):
                        if isinstance(r, CellExit):
                            ok = True
                            if self.exit_put is not None:
                                ok = self.exit_put(p, r.p.get('port') or 'out')
                            if not ok:
                                r.busy = True
                                p.exit_wait = True
                                break
                            p.exit_wait = False
                            r.busy = False
                            self.st['exited'] += 1
                        self._tally(p, r)
                        gone = True
                        break
            if not gone:
                keep.append(p)
        if getattr(self, '_gone', None):
            keep = [p for p in keep if p.id not in self._gone]
            self._gone = set()
        self.live = keep
        if self.contacts:
            by = {p.id: p for p in keep}
            self.contacts = {k for k in self.contacts if k[0] in by and k[1] in by and
                             math.hypot(by[k[0]].x - by[k[1]].x, by[k[0]].y - by[k[1]].y) < (by[k[0]].r + by[k[1]].r) * 1.05}
        if len(self.parts_) > 600:
            self.parts_ = [p for p in self.parts_ if not p.removed_by and not p.dead][-300:]
        for r in self.removers:
            if isinstance(r, CellExit) and not any(p.exit_wait and r.inside(p) for p in self.live):
                r.busy = False

    def _tally(self, p, r):
        cnt = None
        if p.kind == 'tote':
            inside = [o for o in self.live if o.box == p.id]
            cnt = len(inside)
            for o in inside:
                o.removed_by = r.id
            self._gone = getattr(self, '_gone', set()) | {o.id for o in inside}
        good = p.match(r.p.get('accept') or {}, cnt)
        r.count += 1
        self.st['removed'] += 1
        if good:
            r.ok += 1
            self.st['sorted_ok'] += 1
        else:
            r.bad += 1
            self.st['sorted_wrong'] += 1
            self.log(_tr('分拣错误：{id}（{color}/{material}/{kind}/{h:.2f}m）进了 {id2}', id=p.id, color=p.color, material=p.material, kind=p.kind, h=p.h, id2=r.id), kind='wrong')
        p.removed_by = r.id
        self.removed_t.append(self.t)
        self.lead.append(self.t - p.born)
        if len(self.removed_t) > 2000:
            del self.removed_t[:500]
            del self.lead[:500]
        b = self.by_bin.setdefault(r.id, {'n': 0, 'ok': 0, 'parts': []})
        b['n'] += 1
        b['ok'] += good
        b['parts'].append({'color': p.color, 'material': p.material, 'kind': p.kind, 'h': p.h, 'holds': {k: round(v, 2) for k, v in p.holds.items()},
                           **({'count': cnt} if cnt is not None else {})})
        if len(b['parts']) > 200:
            del b['parts'][:50]
        if self.on_remove is not None:
            self.on_remove(p, r)

    # ---------------- 输出 ----------------
    def parts(self):
        return [p.info() for p in self.live]

    def view(self):
        return {'t': round(self.t, 2), 'comps': {c.id: c.view() for c in self.comps.values()},
                'parts': [{'i': p.id, 'k': p.kind, 'c': p.color, 'm': p.material, 'h': round(p.h, 3), 'w': round(p.w, 3),
                           'p': [round(p.x, 3), round(p.y, 3), round(p.z, 3)], 'a': round(p.yaw, 3), 'd': p.dead} for p in self.live]}

    def stats(self):
        s = dict(self.st)
        n = s['sorted_ok'] + s['sorted_wrong'] + s['dropped']
        s['sort_accuracy'] = round(s['sorted_ok'] / n, 4) if n else 0.0
        s['t'] = round(self.t, 2)
        mins = self.t / 60.0
        s['throughput_per_min'] = round(s['removed'] / mins, 3) if mins > 0 else 0.0
        if len(self.removed_t) >= 2:
            ts = self.removed_t
            s['cycle_s'] = round((ts[-1] - ts[0]) / (len(ts) - 1), 2)
        else:
            s['cycle_s'] = None
        s['lead_s'] = round(sum(self.lead) / len(self.lead), 2) if self.lead else None
        s['wip'] = len(self.live)
        s['bins'] = {k: {'n': v['n'], 'ok': v['ok']} for k, v in self.by_bin.items()}
        for c in self.comps.values():
            if isinstance(c, PalletTable):
                n_, l_, inside = c.stack()
                s.setdefault('pallets', {})[c.id] = {'count': n_, 'layers': l_, 'inside': inside}
            elif isinstance(c, Rack):
                occ = c.occupancy()
                s.setdefault('racks', {})[c.id] = {'stored': sum(sum(r) for r in occ), 'occ': occ, 'double': sum(1 for r in occ for v in r if v > 1)}
            elif isinstance(c, Emitter) and c.intervals:
                s.setdefault('emit_min_gap', {})[c.id] = round(min(c.intervals), 2)
        dm = {}
        stoppers = [c.id for c in self.comps.values() if c.type == 'stopper']
        for b_ in self.by_bin.values():
            for pp in b_['parts']:
                for sid in stoppers:                 # 完成件经过每个挡停的最短停留（没被挡过按 0）
                    dm[sid] = min(dm.get(sid, math.inf), (pp.get('holds') or {}).get(sid, 0.0))
        s['dwell_min'] = {k: round(v, 2) for k, v in dm.items()}
        s['faults'] = len(self.fault_list())
        s['metrics'] = self.metric_rows(s)
        return s

    def metric_keys(self):
        """统计页显示哪些指标：单元定义里写了 metrics（场景按评分指标写）就用它，否则按部件推断（没有收料器就不显示分拣正确率）。"""
        if isinstance(self.d.get('metrics'), list) and self.d['metrics']:
            return list(self.d['metrics'])
        types = {c.type for c in self.comps.values()}
        keys = []
        if self.removers:
            keys += ['removed', 'throughput_per_min']
            if any(r.p.get('accept') for r in self.removers):
                keys += ['sort_accuracy', 'sorted_wrong']
        if types & (K.CONVEYORS | K.ACTUATORS - {'motor'}):
            keys += ['collisions', 'jams']
        if 'motor' in types:
            keys += ['interlock_violations', 'hard_reversals']
        keys += [f'pallets.{c.id}.count' for c in self.comps.values() if isinstance(c, PalletTable)]
        keys += [f'racks.{c.id}.stored' for c in self.comps.values() if isinstance(c, Rack)]
        return keys

    def metric_rows(self, s):
        out = []
        for k in self.metric_keys():
            cur = s
            for part in k.split('.'):
                cur = cur.get(part) if isinstance(cur, dict) else None
            ps = k.split('.')
            pat = f'{ps[0]}.*.{ps[2]}' if len(ps) == 3 else f'{ps[0]}.*' if len(ps) == 2 else k
            label = METRIC_CN.get(k) or METRIC_CN.get(pat, k)
            out.append({'key': k, 'label': label, 'value': cur})
        return out

    def power_kw(self):
        return sum(c.power() for c in self.comps.values())

    def busy(self):
        return any(c.moving for c in self.comps.values()) or any(abs(p.dx) + abs(p.dy) > 1e-7 for p in self.live)


def _zero(typ):
    return False if (typ or 'BOOL') == 'BOOL' else 0.0 if typ == 'REAL' else 0


def _cast(v, typ):
    typ = typ or 'BOOL'
    if typ == 'BOOL':
        if isinstance(v, str):
            return v.strip().lower() in ('1', 'true', 'on', 'yes')
        return bool(v)
    if typ == 'REAL':
        return _f(v)
    try:
        iv = int(round(float(v)))
    except (TypeError, ValueError):
        iv = 0
    if typ == 'INT':
        return max(-32768, min(32767, iv))
    return iv


def _norm_addr(a):
    """%I0.0 / %IX0.0 → %IX0.0；%IW100 不变。"""
    a = str(a or '').strip().upper()
    if len(a) > 2 and a[0] == '%' and a[1] in 'IQM' and a[2].isdigit():
        if '.' in a:
            return a[:2] + 'X' + a[2:]
    return a
