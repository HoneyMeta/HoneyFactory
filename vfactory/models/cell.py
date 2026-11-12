"""控制单元块 cell：把一个设备级场景（CellSim + PLC）当作普通块放进整厂流程。

- 整厂每步（1 s）里按 20 ms 子步进：读输入 → PLC 扫描 → 写输出 → CellSim 推进；
- 上游零件从 cell_entry 进入单元，到达 cell_exit 的零件交回下游队列（端口 out / ng）；
- 每个 I/O 点登记为点位 IO/<名>，OPC UA / Modbus / MQTT 自动发布；面板按钮/开关是可写点位 Panel/<部件>；
- 实时模式：界面运行时由 vfactory/control/api.py 的泵按墙钟推进（pump），三维里动作连续；离线跑（实验、测试）不受影响，结果可复现。

给 PLC 层 / 教学层用的属性：
  .sim      CellSim               .plc      PlcRuntime（或外接 PLC 代理），没有时为 None
  .outputs  最近一次给执行器的输出 {I/O 名: 值}      .inputs_last  最近一次的输入
  .set_program(program) 下载程序    .set_controller(fn) 测试用：fn(inputs, dt) -> outputs 代替 PLC
  .reload(cell_def)    换单元定义（重建 CellSim 和 PLC）   .pump(秒) 实时推进
"""
from ..i18n import _tr
import copy
import math

from ..control import catalog as K
from ..control.sim import DT, CellSim
from .generic import Block

DEFAULT_CELL = {'size': [8, 4], 'components': [], 'io': []}     # 4.3：PLC 不在单元里，是独立的 plc 块，用信号线接单元的 I/O


class Cell(Block):
    kind = 'cell'
    area = '控制单元'
    fault_kinds = {'failure': '单元故障停机'}

    def build_tags(self):
        self.controller = None
        self.ahead = 0.0
        self.frames = []
        self._frame_t = -1.0
        self._frame_t = -1.0
        self.inputs_last = {}
        self.outputs = {}
        self.ext_out = {}
        self._ctl_out = {}            # 4.3：PLC 块经信号线写来的输出（下一个子步生效）
        self._ins_now = None
        self._tin = 0.0
        self.plc = None
        self.plc_error = ''
        self.state_hint = ''
        self.bypass = []
        self._build(self.cfg.get('cell') or DEFAULT_CELL, first=True)
        A = self.add_tag
        A('Production/Count', 0, _tr('件'), _tr('单元出口累计'))
        A('Production/InProcess', 0, _tr('件'), _tr('单元内的整厂零件'))
        A('Cell/Removed', 0, _tr('件'), _tr('收走的零件（含收料器）'))
        A('Cell/SortedOK', 0, _tr('件'), _tr('分拣正确'))
        A('Cell/SortedWrong', 0, _tr('件'), _tr('分拣错误'))
        A('Cell/Dropped', 0, _tr('件'), _tr('掉落'))
        A('Cell/Collisions', 0, _tr('次'), _tr('碰撞'))
        A('Cell/Jams', 0, _tr('次'), _tr('卡件'))
        A('Cell/WIP', 0, _tr('件'), _tr('单元内零件'))
        A('Cell/Throughput', 0.0, _tr('件/min'), _tr('产出速度'))
        A('PLC/State', self.plc_state(), desc=_tr('PLC 状态'), dtype='str')
        A('PLC/Mode', self.mode(), desc=_tr('PLC 方式（internal 内置 / external 外接）'), dtype='str')

    # ---------------- 构建 ----------------
    def _build(self, cell_def, first=False, keep_plc=False):
        cell_def = copy.deepcopy(cell_def or DEFAULT_CELL)
        if not cell_def.get('io'):
            cell_def['io'] = K.auto_io(cell_def, keep=[])
        else:
            K.annotate_io(cell_def, cell_def['io'])        # 触点形式 / 未操作时的值（老模型里没有）
        self.cell_def = cell_def
        self._has_emitter = None
        self._cell_ref = self.cfg.get('cell')
        self._cell_key = _key(self._cell_ref)
        self._rev = getattr(self, '_rev', 0) + (0 if first else 1)
        self.sim = CellSim(cell_def, self.plant.child_rng(self.id + ':cell'))
        self.sim.entry_ready = self._entry_ready     # 绑定方法而不是 lambda：推演/回放要能 pickle 整个工厂
        self.sim.entry_take = self.take
        self.sim.exit_put = self._exit_put
        self.sim.on_remove = self._on_remove
        self.outputs = dict(self.sim.outputs)
        if not keep_plc:
            self._make_plc()
        self._io_tags(first)

    def _io_tags(self, first):
        unit = self.p('modbus_unit')
        try:
            unit = int(unit) if unit not in (None, '', 0) else None
        except (TypeError, ValueError):
            unit = None
        ext = self.mode() == 'external'
        ins = self.sim.inputs()
        for e in self.sim.io:
            nm = 'IO/' + e['name']
            typ = e.get('type') or 'BOOL'
            v = ins.get(e['name'], self.sim.outputs.get(e['name'], False if typ == 'BOOL' else 0))
            mb = None
            if unit:
                mb = _modbus_of(e, unit)
            if nm in self.tags:
                self.tags[nm].writable = ext and e.get('dir') == 'out'
                continue
            self.add_tag(nm, v, 'mm' if self._ctype(e) == 'height_sensor' else '', e.get('comment') or f"{e.get('comp')} {e.get('signal')}", dtype='bool' if typ == 'BOOL' else 'int',
                         writable=ext and e.get('dir') == 'out', modbus=mb)
        for c in self.cell_def.get('components') or []:
            if c.get('type') in K.PANEL_IN:
                nm = 'Panel/' + c['id']
                if nm not in self.tags:
                    pot = c['type'] == 'potentiometer'
                    self.add_tag(nm, 0 if pot else False, '', _tr('{label} {id}（按下/档位/旋钮值）', label=K.COMP_TYPES[c['type']]['label'], id=c['id']),
                                 dtype='int' if pot or c['type'] == 'switch' else 'bool', writable=True)

    def _ctype(self, e):
        c = self.sim.comps.get(e.get('comp'))
        return c.type if c is not None else ''

    def mode(self):
        return ((self.cell_def.get('plc') or {}).get('mode') or 'internal')

    def _make_plc(self):
        self.plc, self.plc_error = None, ''
        if 'plc' not in self.cell_def:           # 4.3：单元里没有 PLC（由信号线上的 PLC 块控制）
            return
        try:
            from .. import plc as plcmod
        except Exception as e:           # 软 PLC 模块不可用：单元照常建，输出全为 0
            self.plc_error = _tr('软 PLC 模块不可用：{e}', e=e)
            return
        try:
            self.plc = plcmod.for_cell(self.cell_def)
        except Exception as e:
            self.plc_error = _tr('PLC 初始化失败：{e}', e=e)
            self.plc = None

    def plc_state(self):
        if self.controller is not None:
            return 'RUN'
        if self.plc is None:
            c = self.controllers()
            if c:
                return str(getattr(getattr(c[0], 'plc', None), 'state', 'RUN') or 'RUN')
            return 'NONE'
        return str(getattr(self.plc, 'state', 'RUN'))

    def controllers(self):
        """接到这个单元的 PLC 块（4.3，PLC 层提供）。"""
        try:
            from ..plc.station import controllers
        except Exception:
            return []
        try:
            return list(controllers(self) or [])
        except Exception:
            return []

    # ---------------- 4.3 控制接口：单元的 I/O 就是它的控制点 ----------------
    def ctl_points(self):
        out = []
        for e in self.cell_def.get('io') or []:
            d = {'name': e['name'], 'dir': e.get('dir', 'in'), 'type': e.get('type') or 'BOOL',
                 'label': e.get('comment') or f"{e.get('comp')} {e.get('signal')}", 'addr': str(e.get('addr') or '').lstrip('%'),
                 'comp': e.get('comp'), 'signal': e.get('signal')}
            if e.get('contact'):
                d['contact'] = e['contact']
            if 'idle' in e:
                d['idle'] = e['idle']
            out.append(d)
        return out

    def _io_dir(self, name):
        io = self.sim.io
        c = self.__dict__.get('_io_idx')
        if c is None or c[0] is not io or c[1] != len(io):      # 4.3 性能：按名字查表（PLC 每次扫描每一路都要查）
            idx = {}
            for e in io:
                idx.setdefault(e['name'], (e.get('dir', 'in'), e.get('type') or 'BOOL'))
            c = self._io_idx = (io, len(io), idx)
        return c[2].get(name, (None, None))

    def ctl_get(self, name):
        d, _ = self._io_dir(name)
        if d == 'in':
            ins = self._ins_now
            if ins is None:               # 不在子步里：同一仿真时刻只算一次输入（PLC 一次扫描会读很多点）
                c = getattr(self, '_ins_cache', None)
                if c is None or c[0] != self.plant.t or c[1] != getattr(self.sim, 't', None):
                    c = self._ins_cache = (self.plant.t, getattr(self.sim, 't', None), self.sim.inputs())
                ins = c[2]
            return ins.get(name)
        if d == 'out':
            return self._ctl_out.get(name, self.sim.outputs.get(name))
        return super().ctl_get(name)

    def ctl_set(self, name, value):
        d, typ = self._io_dir(name)
        if d is None:
            return _tr('{name} 没有 I/O 点 {name2}', name=self.name, name2=name)
        if d != 'out':
            return _tr('{name} 是输入（单元 → PLC），不能写', name=name)
        try:
            self._ctl_out[name] = bool(value) if typ == 'BOOL' else int(float(value or 0))
        except (TypeError, ValueError):
            return _tr('{name} 数值格式不对', name=name)
        return ''

    def ctl_hold(self):
        return False                  # 单元由 PLC 逐点控制，不用 Enable 门控

    def reload(self, cell_def):
        """换单元定义（编辑器保存）：重建 CellSim；PLC 对象保留（已下载的程序按新 I/O 表重新编译，变量值保留），
        PLC 方式（内置/外接）变了才重建。新增的 I/O 点位会加进点位表（协议层重启后才发布）。"""
        old_plc, old_mode = self.plc, self.mode()
        self.cfg['cell'] = copy.deepcopy(cell_def)
        self._build(self.cfg['cell'], keep_plc=True)
        io = self.cell_def.get('io') or []
        if old_plc is None or self.mode() != old_mode:
            self._make_plc()
        else:
            self.plc = old_plc
            prog = self._current_program()
            was_running = str(getattr(old_plc, 'state', '')) in ('RUN', 'HALT')
            try:
                if prog is not None and hasattr(old_plc, 'load'):
                    r = old_plc.load(prog, cold=False, io=io)
                    if was_running and (r or {}).get('ok', True) and hasattr(old_plc, 'run'):
                        old_plc.run()                        # 改单元后 PLC 继续运行
                elif hasattr(old_plc, 'io'):
                    old_plc.io = list(io)
            except Exception as e:
                self.plc_error = _tr('PLC 按新 I/O 表重新编译失败：{e}', e=e)
        self.frames = []
        self._frame_t = -1.0

    def _current_program(self):
        """PLC 里当前的程序（软 PLC 编译结果里保存的源程序）。"""
        p = self.plc
        prog = getattr(getattr(p, 'prog', None), 'program', None)
        if isinstance(prog, dict):
            return copy.deepcopy(prog)
        for k in ('program', 'source_program'):
            v = getattr(p, k, None) if p is not None else None
            if isinstance(v, dict):
                return copy.deepcopy(v)
        return None

    def set_program(self, program, run=True):
        """下载程序到单元的内置 PLC，并写进单元定义（保存模型时一起保存）。返回编译结果。
        4.3：单元没有内置 PLC 时转给接在单元上的 PLC 块（vfactory.plc.migrate.set_cell_program）。"""
        if self.plc is None and 'plc' not in self.cell_def:
            try:
                from ..plc.migrate import set_cell_program
            except Exception as e:
                return {'ok': False, 'errors': [{'msg': _tr('这个单元没有接 PLC：{e}', e=e)}]}
            return set_cell_program(self.plant, self.id, program)
        if self.plc is None or not hasattr(self.plc, 'load'):
            self._make_plc()
        if self.plc is None or not hasattr(self.plc, 'load'):
            return {'ok': False, 'errors': [{'msg': self.plc_error or _tr('这个单元没有内置 PLC')}]}
        r = self.plc.load(program, cold=True)
        if r.get('ok'):
            self.cfg.setdefault('cell', {}).setdefault('plc', {})['program'] = copy.deepcopy(program)
            self.cell_def.setdefault('plc', {})['program'] = copy.deepcopy(program)
            if run and hasattr(self.plc, 'run'):
                self.plc.run()
        return r

    def set_controller(self, fn):
        """测试/桩：fn(inputs, dt) -> outputs 代替 PLC（只给离线测试和没有软 PLC 时用）。"""
        self.controller = fn

    # ---------------- 整厂接口 ----------------
    def _entry_ready(self):
        return self.available() > 0

    def _exit_put(self, part, port):
        item = part.plant
        if item is None:
            item = self.plant.new_part(heat=self.name, mold='', defects={}, rework=0)
            item.update(kind=part.kind, color=part.color, material=part.material)
        ok = self.put(item, port) if self.has_out(port) else self.put(item, 'out') if self.has_out('out') else True
        if ok:
            item.event(self.plant, self.id, 'processed', cell_s=round(self.sim.t - part.born, 1))
            self.count += 1
            if port == 'ng':
                self.ng += 1
        return ok

    def _on_remove(self, part, rem):
        if part.plant is not None and rem.type == 'remover':
            self.plant.scrap(part.plant, self.id, rem.p.get('label') or _tr('单元收料 {id}', id=rem.id))

    # ---------------- 推进 ----------------
    def _substep(self, dt):
        sim = self.sim
        ins = sim.inputs()
        self.inputs_last = ins
        outs = None
        if self.controller is not None:
            outs = self.controller(ins, dt)
        elif self.plc is not None:
            try:
                outs = self.plc.scan(ins, dt)
            except Exception as e:          # PLC 运行出错：输出保持 0
                self.plc_error = _tr('PLC 运行错误：{e}', e=e)
                outs = {}
        else:                               # 4.3：信号线上的 PLC 块在这里扫描（读 ctl_get、写 ctl_set）
            self._ins_now = ins
            drive = _drive_fn()
            if drive is not None:
                try:
                    drive(self, self.plant.t + self._tin)
                except Exception as e:
                    self.plc_error = _tr('PLC 运行错误：{e}', e=e)
            self._ins_now = None
            outs = dict(self._ctl_out)
        self._tin += dt
        if self.ext_out:
            outs = dict(outs or {})
            outs.update(self.ext_out)
        sim.apply_outputs(outs or {})
        self.outputs = sim.outputs
        sim.step(dt)
        if sim.t - self._frame_t >= 0.1 - 1e-9:
            self._frame_t = sim.t
            self.frames.append(self._frame())
            if len(self.frames) > 6:
                del self.frames[0]

    def _frame(self):
        v = self.sim.view()
        return [v['t'], v['comps'], v['parts']]

    def _can_run(self):
        return self.enabled and self.failure.repair_left <= 0 and not self.plant.plan.blocked(self) and self.changeover_left <= 0

    def pump(self, seconds):
        """实时推进（墙钟驱动），最多推进到下一个整厂步之前。返回实际推进的秒数。"""
        if not self._can_run() or self._warm():
            return 0.0
        sub = self._sub()
        room = self.plant.dt - self.ahead - sub * 0.5
        n = int(min(seconds, room) / sub + 1e-9)
        self._tin = self.ahead
        for _ in range(max(0, n)):
            self._substep(sub)
        self.ahead += n * sub
        return n * sub

    def _sub(self):
        try:
            return max(0.005, min(0.1, float(self.p('substep_ms', 20)) / 1000))
        except (TypeError, ValueError):
            return DT

    def _warm(self):
        """整厂预热期间不做设备级仿真：零件按"旁路时间"直接穿过单元（预热 8 小时 × 50 子步太慢）。"""
        wh = float(self.plant.cfg.get('plant', {}).get('warmup_h', 0) or 0)
        return wh > 0 and self.plant.t < wh * 3600

    def step(self, dt):
        if self.cfg.get('cell') is not self._cell_ref:          # 热更新：单元定义真的变了才重建
            if _key(self.cfg.get('cell')) != self._cell_key:
                self.reload(self.cfg.get('cell') or DEFAULT_CELL)
            else:
                self._cell_ref = self.cfg.get('cell')
        if self._warm():
            self._bypass_step(dt)
            return
        sub = self._sub()
        n = int(round((dt - self.ahead) / sub))
        self._tin = self.ahead
        i = 0
        while i < n:
            k = self._coarse(sub, n - i)
            self._substep(sub * k)
            i += k
        self.ahead = 0.0
        self._update(dt)

    COARSE_S = 0.25

    def _coarse(self, sub, left):
        """单元空着（没有零件、上游没来料、执行器都停着、没有自带发料器）时用 0.25 s 的粗步推进，PLC 定时器照常走；
        整厂里大部分时间单元在等料，这样长时间离线运行（实验、报表）快很多，结果仍然可复现。"""
        sim = self.sim
        if self._has_emitter is None:
            self._has_emitter = any(c.type == 'emitter' for c in sim.comps.values())
        if self._has_emitter or sim.live or self.available() > 0 or self.controller is not None:
            return 1
        if any(c.moving for c in sim.comps.values() if c.type not in K.CONVEYORS):     # 空转的输送带不算
            return 1
        if any(getattr(c, 'until', None) is not None for c in sim.comps.values()):
            return 1
        return max(1, min(left, int(self.COARSE_S / sub + 1e-9)))

    def _bypass_step(self, dt):
        for it in self.bypass:
            it[1] -= dt
        while True:
            q = [x for x in self.bypass if x[1] <= 0]
            if not q or not self.put(q[0][0]):
                break
            self.bypass.remove(q[0])
            self.count += 1
        if len(self.bypass) < 20 and any(c.get('type') == 'cell_entry' for c in self.cell_def.get('components') or []):
            it = self.take()
            if it is not None:
                self.bypass.append([it, float(self.p('bypass_s', 30) or 30)])
        self.state = 'Executing' if self.bypass else 'Starved'
        self.power_kw = self.idle_power()
        self.set('Production/Count', self.count)
        self.set('Production/InProcess', len(self.bypass))

    def plc_has_program(self):
        """控制这个单元的 PLC（独立 PLC 块或单元自带）有没有下载过程序。"""
        p = self.plc
        if p is None:
            c = self.controllers()
            p = getattr(c[0], 'plc', None) if c else None
        return p is not None and getattr(p, 'prog', 1) is not None

    def _update(self, dt):
        self.hint = ''
        sim = self.sim
        s = sim.st
        ins = self.inputs_last or sim.inputs()
        for e in sim.io:
            nm = 'IO/' + e['name']
            if nm in self.tags:
                self.tags[nm].value = ins.get(e['name']) if e.get('dir') == 'in' else sim.outputs.get(e['name'])
        for c in sim.comps.values():
            nm = 'Panel/' + c.id
            if nm in self.tags:
                self.tags[nm].value = c.state if c.type in ('potentiometer', 'switch') else bool(c.state)
        estop = any(c.type == 'estop' and c.state for c in sim.comps.values())
        exit_busy = any(getattr(c, 'busy', False) for c in sim.comps.values())
        plc_st = self.plc_state()
        has_entry = any(c.type == 'cell_entry' for c in sim.comps.values())
        if estop:
            self.state, self.alarm = 'Stopped', _tr('急停已按下')
        elif plc_st not in ('RUN', 'NONE') or (plc_st == 'NONE' and self.mode() == 'internal' and self.controller is None):
            self.state = 'Idle'
            if plc_st == 'STOP' and not self.plc_error and not self.plc_has_program():
                # 控制它的 PLC 还没有程序：实训课刚开始的正常状态，不算报警，给一句"下一步做什么"
                self.alarm = ''
                self.hint = _tr('先给 PLC 编程并下载；PLC 运行后再按操作台上的"启动"')
            else:
                self.alarm = self.plc_error or (_tr('PLC 未运行') if plc_st != 'NONE' else
                                                _tr('没有 PLC 程序') if 'plc' in self.cell_def else _tr('没有接 PLC（用信号线接一台 PLC）'))
                if plc_st == 'STOP' and not self.plc_error:
                    self.hint = _tr('PLC 已停止：在 PLC 面板点"运行"（或重新下载）后再按操作台上的"启动"')
        elif exit_busy:
            self.state, self.alarm = 'Blocked', ''
        elif sim.busy():
            self.state, self.alarm = 'Executing', ''
        elif not sim.live and has_entry and self.available() == 0:
            self.state, self.alarm = 'Starved', ''
        else:
            self.state, self.alarm = 'Idle', ''
        if self.mode() == 'external' and plc_st == 'NONE':
            self.alarm = ''
        self.power_kw = self.idle_power() * 0.2 + sim.power_kw()
        inproc = sum(1 for p in sim.live if p.plant is not None)
        self.set('Production/Count', self.count)
        self.set('Production/InProcess', inproc)
        self.set('Cell/Removed', s['removed'])
        self.set('Cell/SortedOK', s['sorted_ok'])
        self.set('Cell/SortedWrong', s['sorted_wrong'])
        self.set('Cell/Dropped', s['dropped'])
        self.set('Cell/Collisions', s['collisions'])
        self.set('Cell/Jams', s['jams'])
        self.set('Cell/WIP', len(sim.live))
        self.set('Cell/Throughput', round(s['removed'] / max(1e-6, sim.t / 60), 2) if sim.t > 0 else 0.0)
        self.set('PLC/State', plc_st)
        self.set('PLC/Mode', self.mode())

    def idle_power(self):
        return float(self.p('idle_kw', 0.5) or 0.5)

    # ---------------- 点位写入 ----------------
    def on_write(self, name, value):
        if name.startswith('Panel/'):
            c = self.sim.comps.get(name[6:])
            if c is None:
                return
            if c.type == 'potentiometer':
                self.sim.panel(c.id, 'set', int(float(value)))
            elif c.type == 'switch':
                self.sim.panel(c.id, 'set', int(float(value)))
            else:
                self.sim.panel(c.id, 'press' if value else 'release', hold=None)
        elif name.startswith('IO/') and self.mode() == 'external':
            self.ext_out[name[3:]] = value

    def write(self, name, value):
        t = self.tags.get(name)
        if t is not None and t.writable and t.dtype == 'int' and name.startswith('Panel/'):
            try:
                value = int(float(value))
            except (TypeError, ValueError):
                return _tr('{name} 数值格式不对', name=name)
        return super().write(name, value)

    # ---------------- 故障 ----------------
    def on_fault(self, kind):
        return _tr('{name}：单元内部件的故障请用"控制单元 → 故障注入"（部件 + 故障类型）', name=self.name)

    def inject(self, kind):
        if kind == 'clear':
            self.sim.clear_faults()
        return super().inject(kind)

    # ---------------- 输出 ----------------
    def quality_rate(self):
        s = self.sim.st
        n = s['sorted_ok'] + s['sorted_wrong'] + s['dropped']
        return s['sorted_ok'] / n if n else 1.0

    def snapshot(self, full=False):
        d = super().snapshot(full)
        d['oee'] = self.plant.oee(self)
        return d

    def view(self):
        v = self.sim.view()
        return {'cell': {'t': v['t'], 'comps': v['comps'], 'parts': v['parts'], 'frames': self.frames[-5:], 'rev': self.rev(),
                         'plc': self.plc_state(), 'faults': len(self.sim.fault_list())}, 'hint': getattr(self, 'hint', '')}

    def rev(self):
        """单元定义的版本号（前端发现变了就重新取定义、重建模型）。"""
        return getattr(self, '_rev', 0)

    def __deepcopy__(self, memo):
        """整厂预热缓存会 deepcopy 工厂：PLC 运行时的编译结果是无状态闭包、可共享，内存各自一份；CellSim 的整厂回调重新绑定到副本。"""
        cls = self.__class__
        new = cls.__new__(cls)
        memo[id(self)] = new
        for k, v in self.__dict__.items():
            if k in ('controller',):
                setattr(new, k, v)
            else:
                setattr(new, k, copy.deepcopy(v, memo))
        sim = new.sim
        sim.entry_ready = new._entry_ready
        sim.entry_take = new.take
        sim.exit_put = new._exit_put
        sim.on_remove = new._on_remove
        return new


_DRIVE = []


def _drive_fn():
    """4.3：PLC 块的扫描入口 vfactory.plc.station.drive（PLC 层提供），第一次用时再导入，避免循环导入。"""
    if not _DRIVE:
        try:
            from ..plc.station import drive
        except Exception:                   # noqa: BLE001  PLC 层还没有：单元只用旧的内置 PLC
            drive = None
        _DRIVE.append(drive)
    return _DRIVE[0]


def _modbus_of(e, unit):
    """I/O → Modbus：%Ib.n → 线圈 b*8+n；%Qb.n → 线圈 128+b*8+n；%IWn → 保持寄存器 n；%QWn → 保持寄存器 256+n。"""
    a = str(e.get('addr') or '').upper().replace('X', '')
    try:
        if a.startswith('%I') and '.' in a:
            b, n = a[2:].split('.')
            return {'unit': unit, 'kind': 'coil', 'addr': int(b) * 8 + int(n)}
        if a.startswith('%Q') and '.' in a:
            b, n = a[2:].split('.')
            return {'unit': unit, 'kind': 'coil', 'addr': 128 + int(b) * 8 + int(n)}
        if a.startswith('%IW') or a.startswith('%ID'):
            return {'unit': unit, 'kind': 'hr', 'addr': int(a[3:]) % 256, 'scale': 1}
        if a.startswith('%QW') or a.startswith('%QD'):
            return {'unit': unit, 'kind': 'hr', 'addr': 256 + int(a[3:]) % 256, 'scale': 1}
    except ValueError:
        return None
    return None


def _key(cell):
    import json
    try:
        return json.dumps(cell, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(id(cell))


_ = math
