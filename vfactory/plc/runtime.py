"""软 PLC 运行时：扫描引擎、运行/停止/单步、断点、强制、在线监视、在线下载（保留变量值）。

    plc = PlcRuntime(program, scan_ms=20, io=cell['io'])
    outputs = plc.scan(inputs, dt)      # inputs/outputs 都按 I/O 名：{'S1': True, …} → {'P1_EXT': False, …}

一次 scan = 读输入映像 → 执行程序 → 写输出映像，PLC 时钟前进 dt 秒（定时器按这个时钟走，和仿真时间同步）。
状态：RUN 运行、STOP 停止（输出全部为 0）、HALT 暂停（断点/单步，输出保持）、ERROR 运行错误（输出为 0，需要停止或复位后再运行）。
"""
from ..i18n import _tr
import copy
import time
from collections import deque

from .compiler import PlcError, execute, tname, wrapper, zero
from .fb import FB_DEFS, FBInst
from .program import Compiled, compile_program, program_hash
from .st import fmt_time, norm_addr

STATE_CN = {'RUN': '运行', 'STOP': '停止', 'HALT': '暂停', 'ERROR': '错误'}


def _json_val(v, t=None):
    if isinstance(v, FBInst):
        d = FB_DEFS[v.t]
        out = {}
        for k, x in v.public().items():
            out[k] = x
        return out
    if isinstance(v, list):
        return list(v)
    return v


class PlcRuntime:
    def __init__(self, program=None, scan_ms=20, io=None, autorun=True):
        self.scan_ms = float(scan_ms or 20)
        self.io = list(io or [])
        self.state = 'STOP'
        self.error = None                 # {'msg', 'line'}
        self.prog: Compiled | None = None
        self.mem = None
        self.forces = {}                  # 存储键 → 强制值
        self.bps = set()                  # 断点：ST 行号 / LD 梯级号+1
        self.halt_pc = None               # 暂停在扫描中间的位置（None = 在扫描边界）
        self.halt_reason = ''
        self.last_inputs = {}
        self.outputs = {}
        self.scan_count = 0
        self.t_last = self.t_max = self.t_sum = 0.0
        self.t_win = deque(maxlen=200)
        self.downloads = 0
        self.last_compile = None
        self.over = 0                     # 扫描用时超过扫描周期的次数
        self.tracer = None                # I/O 时序记录（逻辑分析仪），没下载程序时也记（看输入）
        self.tclock_us = 0                # 时序记录用的时钟（每次 scan 前进 dt，暂停/停止时也走）
        if program is not None:
            r = self.load(program, cold=True)
            if r['ok'] and autorun:
                self.state = 'RUN'
        self._zero_outputs()

    # ---------------------------------------------------------- 复制与序列化
    # 编译结果里是 Python 闭包：deepcopy 时直接共享（无状态，快），pickle（推演/快照）时只存程序源，恢复时重新编译。
    # 变量值、定时器/计数器、沿记忆、强制、断点、运行状态、扫描统计、时序记录都在内存对象里，原样保留。
    _SHARED = ('prog', '_io_keys_for')

    def __deepcopy__(self, memo):
        new = self.__class__.__new__(self.__class__)
        memo[id(self)] = new
        for k, v in self.__dict__.items():
            setattr(new, k, v if k in self._SHARED else copy.deepcopy(v, memo))
        return new

    def __getstate__(self):
        d = dict(self.__dict__)
        prog = d.pop('prog', None)
        d.pop('_io_keys', None)
        d.pop('_io_keys_for', None)
        d.pop('_trace_names', None)
        d['_prog_src'] = copy.deepcopy(prog.program) if prog is not None else None
        return d

    def __setstate__(self, d):
        src = d.pop('_prog_src', None)
        self.__dict__.update(d)
        self.prog = None
        if src is not None:
            c = compile_program(src, self.io)
            if c.ok:
                self.prog = c
            else:                                  # 理论上不会发生（同一份程序编译过）；万一不行就停机，不让恢复失败
                self.state, self.halt_pc = 'STOP', None
        if self.prog is None or (self.halt_pc is not None and self.halt_pc >= len(self.prog.code)):
            self.halt_pc = None

    @property
    def program(self):
        """当前下载在 PLC 里的程序（LD 已补齐元素 id）；没有返回 None。"""
        return copy.deepcopy(self.prog.program) if self.prog else None

    # ---------------------------------------------------------- 下载
    def load(self, program, cold=False, io=None):
        """编译并下载。编译失败时运行中的程序不变。cold=False 时保留同名同类型变量的值（在线修改）。"""
        if io is not None:
            self.io = list(io)
        c = compile_program(program, self.io)
        res = c.result()
        self.last_compile = res
        if not c.ok:
            return res
        old_prog, old_mem = self.prog, self.mem
        mem = c.new_memory()
        kept = []
        if old_prog and old_mem is not None and not cold:
            old = {s.name.upper(): s for s in old_prog.syms}
            for s in c.syms:
                o = old.get(s.name.upper())
                if o is None or tname(o.type) != tname(s.type) or o.key not in old_mem.v:
                    continue
                if s.constant:
                    continue
                mem.v[s.key] = copy.deepcopy(old_mem.v[o.key])
                kept.append(s.name)
            for a in c.used_addrs:
                if a in old_mem.v and a not in kept:
                    mem.v[a] = old_mem.v[a]
            mem.now = old_mem.now
            mem.edge = {k: v for k, v in old_mem.edge.items()}
        self.prog, self.mem = c, mem
        self.halt_pc = None
        if self.state == 'ERROR':
            self.state = 'STOP'
            self.error = None
        valid = {s.key for s in c.syms} | set(c.used_addrs)
        self.forces = {k: v for k, v in self.forces.items() if k in valid}
        self.downloads += 1
        res['kept'] = kept
        res['cold'] = bool(cold or not old_prog)
        return res

    def reset(self, cold=True):
        """复位：cold 冷复位（全部回到初值）；warm 暖复位（保持型 RETAIN 变量保留）。"""
        if not self.prog:
            return
        mem = self.prog.new_memory()
        if not cold and self.mem is not None:
            for s in self.prog.syms:
                if s.retain and s.key in self.mem.v:
                    mem.v[s.key] = copy.deepcopy(self.mem.v[s.key])
        self.mem = mem
        self.halt_pc = None
        self.error = None
        if self.state in ('ERROR', 'HALT'):
            self.state = 'STOP'
        self._zero_outputs()

    # ---------------------------------------------------------- 扫描
    def scan(self, inputs=None, dt=None):
        """一个扫描周期。dt 秒（默认 scan_ms）。返回输出（按 I/O 名）。"""
        if inputs:
            self.last_inputs = dict(inputs)
        dt = self.scan_ms / 1000 if dt is None else dt
        if self.state == 'RUN' and self.prog:
            self._cycle(dt)
        elif self.state in ('STOP', 'ERROR'):
            if self.mem is not None:
                self.mem.now += int(round(dt * 1e6))
                self._read_inputs()
        self.tclock_us += int(round(dt * 1e6))
        self._trace()
        return dict(self.outputs)

    def _trace(self):
        tn = self.__dict__.get('_trace_names')
        if tn is None or tn[0] is not self.io or tn[1] != len(self.io):   # I/O 表没换就不用每次扫描重算名字（4.3 性能）
            tn = self._trace_names = (self.io, len(self.io), [e.get('name') for e in self.io if e.get('name')])
        names = tn[2]
        if self.tracer is None or self.tracer.names != names:
            from .trace import Tracer
            self.tracer = Tracer(names)
        m, p = self.mem, self.prog
        if p is None or m is None:              # 还没有程序：输入照样记（看按钮、传感器）
            self.tracer.record(self.tclock_us // 1000, tuple(self.last_inputs.get(e.get('name')) if e.get('dir') != 'out' else self.outputs.get(e.get('name'))
                                                            for e in self.io if e.get('name')))
            return
        if getattr(self, '_io_keys_for', None) is not p:
            self._io_keys = [(e.get('name'), e.get('dir') == 'out', (self.resolve(e.get('name')) or (None,))[0]) for e in self.io if e.get('name')]
            self._io_keys_for = p
        og, vg = self.outputs.get, m.v.get
        self.tracer.record(self.tclock_us // 1000, tuple([og(n) if out else (vg(k) if k else None) for n, out, k in self._io_keys]))

    def cycle(self, inputs, dt):
        """按扫描周期累计：dt 可以比扫描周期大（会执行多次）或小（攒够一个周期才执行）。返回输出。"""
        self._acc = min(getattr(self, '_acc', 0.0) + dt, 1.0)
        per = self.scan_ms / 1000
        if inputs:
            self.last_inputs = dict(inputs)
        while self._acc + 1e-9 >= per:
            self.scan(None, per)
            self._acc -= per
        return dict(self.outputs)

    def _read_inputs(self):
        m, f = self.mem, self.forces
        prog = self.prog
        inp = self.last_inputs
        for name, key, w in prog.in_map:
            if key in f:
                m.v[key] = f[key]
            elif name in inp:
                try:
                    m.v[key] = w(inp[name])
                except (TypeError, ValueError):
                    pass
        if not prog.in_map and inp:
            idx = {s.name.upper(): s for s in prog.syms}
            for name, val in inp.items():
                s = idx.get(str(name).upper())
                key = s.key if s else (norm_addr(name) or [None])[0]
                if key and key in m.v and not isinstance(m.v[key], (FBInst, list)):
                    try:
                        m.v[key] = wrapper(s.type if s else _addr_t(key))(val)
                    except (TypeError, ValueError):
                        pass
        for key, val in f.items():
            if key.startswith('%I'):
                m.v[key] = val

    def _apply_forces(self):
        m = self.mem
        for key, val in self.forces.items():
            if key in m.v and not isinstance(m.v[key], (FBInst, list)):
                m.v[key] = val
            elif '.' in key and not key.startswith('%'):
                k, fld = key.split('.', 1)
                inst = m.v.get(k)
                if isinstance(inst, FBInst) and fld in inst.f:
                    inst.f[fld] = val

    def _write_outputs(self):
        m = self.mem
        out = {}
        for name, key, t in self.prog.out_map:
            out[name] = m.v.get(key, zero(t))
        for a in self.prog.used_addrs:
            if a.startswith('%Q') and a not in out:
                out[a] = m.v.get(a)
        self.outputs = out

    def _zero_outputs(self):
        if not self.prog:
            self.outputs = {}
            return
        self.outputs = {name: zero(t) for name, key, t in self.prog.out_map}
        for a, t in self.prog.used_addrs.items():
            if a.startswith('%Q'):
                self.outputs.setdefault(a, zero(t))

    def _cycle(self, dt, stmt_mode=False, ignore_bps=False):
        """执行（或继续执行）一个扫描周期。返回 True = 扫描完成，False = 停在断点/单步。"""
        m = self.mem
        t0 = time.perf_counter()
        resume = self.halt_pc is not None
        if not resume:
            m.now += int(round(dt * 1e6))
            self._read_inputs()
            self._apply_forces()
            pc = 0
        else:
            pc = self.halt_pc
        try:
            r, pc = execute(self.prog.code, m, pc, set() if ignore_bps else self.bps, stmt_mode=stmt_mode, skip_first=resume)
        except PlcError as e:
            self.state = 'ERROR'
            self.error = {'msg': e.msg, 'line': e.line if self.prog.lang == 'ST' else 0,
                          'rung': (e.line - 1) if self.prog.lang == 'LD' and e.line else None}
            self.halt_pc = None
            self._zero_outputs()
            return True
        el = (time.perf_counter() - t0) * 1000
        self._t_part = getattr(self, '_t_part', 0.0) + el
        if r == 'halt':
            self.halt_pc = pc
            ln = self.prog.code[pc][4]
            self.halt_reason = 'step' if stmt_mode else 'breakpoint'
            self._halt_line = ln
            self.state = 'HALT'
            return False
        self.halt_pc = None
        self._apply_forces()
        self._write_outputs()
        t = self._t_part
        self._t_part = 0.0
        self.scan_count += 1
        if t > self.scan_ms:
            self.over += 1
        self.t_last = t
        self.t_max = max(self.t_max, t)
        self.t_win.append(t)
        return True

    # ---------------------------------------------------------- 控制
    def run(self):
        if not self.prog or not self.prog.ok:
            return _tr('没有可运行的程序，请先编译下载')
        if self.state == 'ERROR':
            self.error = None
            self.halt_pc = None
        if self.halt_pc is not None:
            self.state = 'RUN'
            done = self._cycle(0)
            if not done:
                return ''
        self.state = 'RUN' if self.state != 'ERROR' else 'ERROR'
        return ''

    def stop(self):
        self.state = 'STOP'
        self.halt_pc = None
        self._zero_outputs()
        return ''

    def step(self, kind='scan'):
        """单步：scan 执行一个完整扫描周期后暂停；stmt 执行到下一条语句（LD：下一个梯级）。"""
        if not self.prog or not self.prog.ok:
            return _tr('没有可运行的程序，请先编译下载')
        if self.state == 'ERROR':
            return _tr('程序处于错误状态，请先停止或复位')
        dt = self.scan_ms / 1000
        if kind == 'stmt':
            done = self._cycle(dt, stmt_mode=True)
            if done and self.state != 'ERROR':
                self.state = 'HALT'
                self.halt_reason = 'scan_end'
                self._halt_line = 0
        else:
            self._cycle(dt, ignore_bps=True)
            if self.state != 'ERROR':
                self.state = 'HALT'
                self.halt_reason = 'scan_end'
                self._halt_line = 0
        return ''

    def set_breakpoint(self, line, on=True):
        """line：ST 行号，或 LD 梯级序号+1。设在不能停的行上时自动挪到下一条语句。返回实际行号。"""
        line = int(line)
        if on:
            if self.prog and self.prog.lines and line not in self.prog.lines:
                nxt = [x for x in self.prog.lines if x >= line]
                if not nxt:
                    return None
                line = nxt[0]
            self.bps.add(line)
        else:
            self.bps.discard(line)
        return line

    def clear_breakpoints(self):
        self.bps.clear()

    # ---------------------------------------------------------- 变量访问
    def resolve(self, name):
        """名称/地址/实例.字段 → (存储键, 类型, 显示名)。不认识返回 None。"""
        if not self.prog:
            return None
        name = str(name).strip()
        na = norm_addr(name)
        if na:
            a = na[0]
            for s in self.prog.syms:
                if s.key == a:
                    return a, s.type, s.name
            if a in self.mem.v:
                return a, self.prog.used_addrs.get(a) or _addr_t(a), a
            return None
        up = name.upper()
        if '.' in up:
            base, fld = up.split('.', 1)
            for s in self.prog.syms:
                if s.name.upper() == base and s.type in FB_DEFS:
                    d = FB_DEFS[s.type]
                    t = d['in'].get(fld) or d['out'].get(fld)
                    if t:
                        return f'{s.key}.{fld}', t, f'{s.name}.{fld}'
            return None
        for s in self.prog.syms:
            if s.name.upper() == up:
                return s.key, s.type, s.name
        return None

    def force(self, name, value):
        """强制（value=None 取消）。输入强制在读输入时生效，其他变量在扫描开始和结束时覆盖程序的结果。"""
        r = self.resolve(name)
        if not r:
            return _tr('没有变量 {name}', name=name)
        key, t, _ = r
        if t in FB_DEFS or isinstance(t, tuple):
            return _tr('功能块实例和数组不能整体强制')
        if '.' in key and not key.startswith('%') and value is not None:
            return _tr('功能块的输入输出每次调用都会被功能块重新计算，不能强制；请强制接到它上面的变量，或用“写入”改一次')
        if value is None:
            self.forces.pop(key, None)
            return ''
        try:
            v = _coerce(t, value)
        except (TypeError, ValueError):
            return _tr('值 {value} 不是 {tname}', value=value, tname=tname(t))
        self.forces[key] = v
        self._poke(key, v)
        if self.state != 'RUN' and self.prog:
            # 停止/暂停时也让输出映像立刻反映强制（I/O 监视表里能看到）
            if self.state != 'STOP':
                self._write_outputs()
        return ''

    def unforce_all(self):
        self.forces.clear()

    def write(self, name, value):
        """写一次（不强制，程序可以再改它）。HMI 按钮、在线修改变量值用。"""
        r = self.resolve(name)
        if not r:
            return _tr('没有变量 {name}', name=name)
        key, t, _ = r
        if t in FB_DEFS or isinstance(t, tuple):
            return _tr('功能块实例和数组不能整体写入')
        try:
            v = _coerce(t, value)
        except (TypeError, ValueError):
            return _tr('值 {value} 不是 {tname}', value=value, tname=tname(t))
        self._poke(key, v)
        return ''

    def _poke(self, key, v):
        m = self.mem
        if m is None:
            return
        if '.' in key and not key.startswith('%'):
            k, fld = key.split('.', 1)
            inst = m.v.get(k)
            if isinstance(inst, FBInst):
                inst.f[fld] = v
        else:
            m.v[key] = v

    def value(self, name):
        r = self.resolve(name)
        if not r:
            return None
        key, t, _ = r
        if '.' in key and not key.startswith('%'):
            k, fld = key.split('.', 1)
            return self.mem.v[k].f[fld]
        return self.mem.v.get(key)

    # ---------------------------------------------------------- 在线监视
    def stats(self):
        w = list(self.t_win)
        recent = sum(1 for x in w if x > self.scan_ms)
        return {'count': self.scan_count, 'last_ms': round(self.t_last, 4), 'avg_ms': round(sum(w) / len(w), 4) if w else 0,
                'max_ms': round(self.t_max, 4), 'cycle_ms': self.scan_ms, 'over': self.over, 'over_recent': recent,
                'over_pct': round(recent / len(w) * 100, 1) if w else 0}

    def reset_stats(self):
        self.t_max, self.over = 0.0, 0
        self.t_win.clear()

    def halt_info(self):
        """暂停位置：{'line': ST 行号} 或 {'rung': LD 梯级序号（从 0 起）}，没暂停返回 None。"""
        if self.state != 'HALT':
            return None
        ln = getattr(self, '_halt_line', 0)
        p = self.prog
        if p and p.lang == 'LD':
            return {'rung': ln - 1 if ln else None, 'reason': self.halt_reason, 'mid_scan': self.halt_pc is not None}
        return {'line': ln or None, 'reason': self.halt_reason, 'mid_scan': self.halt_pc is not None}

    def label(self):
        """给三维标签、状态栏用的一句话：运行 / 停止 / 断点暂停（第 5 行）/ 单步暂停（梯级 2）/ 错误。"""
        if self.state == 'HALT':
            h = self.halt_info() or {}
            where = _tr('第 {line} 行', line=h['line']) if h.get('line') else _tr('梯级 {v}', v=h['rung'] + 1) if h.get('rung') is not None else _tr('周期结束')
            return (_tr('断点暂停') if h.get('reason') == 'breakpoint' else _tr('单步暂停')) + _tr('（{where}）', where=where)
        if self.state == 'ERROR':
            return _tr('错误：') + ((self.error or {}).get('msg') or '')
        return STATE_CN.get(self.state, self.state)

    def online(self, ld=True):
        p = self.prog
        out = {'state': self.state, 'state_cn': STATE_CN[self.state], 'error': self.error, 'scan': self.stats(),
               'hash': p.hash if p else None, 'lang': p.lang if p else None, 'bps': sorted(self.bps), 'downloads': self.downloads,
               'clock_ms': (self.mem.now // 1000) if self.mem else 0}
        if self.state == 'HALT':
            ln = getattr(self, '_halt_line', 0)
            out['halt'] = {'reason': self.halt_reason, 'line': ln if p and p.lang == 'ST' else 0,
                           'rung': (ln - 1) if p and p.lang == 'LD' and ln else None, 'mid_scan': self.halt_pc is not None}
        if not p or self.mem is None:
            out.update(vars={}, types={}, forced={}, io=[], ld={}, rungs=[])
            return out
        m = self.mem
        vals, types = {}, {}
        for s in p.syms:
            vals[s.name] = _json_val(m.v.get(s.key))
            types[s.name] = tname(s.type)
        for a, t in p.used_addrs.items():
            if not any(s.key == a for s in p.syms):
                vals[a] = m.v.get(a)
                types[a] = tname(t)
        forced = {}
        for key, v in self.forces.items():
            nm = next((s.name for s in p.syms if s.key == key), None)
            if nm is None and '.' in key:
                k, fld = key.split('.', 1)
                nm = next((f'{s.name}.{fld}' for s in p.syms if s.key == k), key)
            forced[nm or key] = v
        io = []
        for ent in self.io:
            r = self.resolve(ent.get('name', ''))
            key = r[0] if r else None
            if ent.get('dir') == 'out':          # 输出显示真正送到现场的值（停止时为 0）
                val = self.outputs.get(ent.get('name'), m.v.get(key) if key else None)
            else:
                val = m.v.get(key) if key else None
            io.append({'name': ent.get('name'), 'addr': ent.get('addr'), 'dir': ent.get('dir'), 'type': ent.get('type') or 'BOOL',
                       'value': val, 'forced': key in self.forces if key else False,
                       'comment': ent.get('comment') or ent.get('desc') or ''})
        out.update(vars=vals, types=types, forced=forced, io=io)
        if ld and p.lang == 'LD':
            out['ld'] = {k: [bool(a), bool(b), bool(c)] for k, (a, b, c) in m.ld.items()}
            out['rungs'] = [bool(x) for x in m.rungs]
        return out

    # ---------------------------------------------------------- 状态信息
    def info(self):
        p = self.prog
        return {'state': self.state, 'label': self.label(), 'halt': self.halt_info(), 'bps': sorted(self.bps), 'hash': p.hash if p else None,
                'lang': p.lang if p else None, 'scan_ms': self.scan_ms, 'error': self.error, 'scan': self.stats()}


def _addr_t(a):
    na = norm_addr(a)
    return {'X': 'BOOL', 'B': 'BYTE', 'W': 'INT', 'D': 'DINT', 'L': 'LINT'}[na[2]] if na else 'INT'


def _coerce(t, value):
    if t == 'BOOL':
        if isinstance(value, str):
            v = value.strip().upper()
            if v in ('TRUE', '1', 'ON', '真'):
                return True
            if v in ('FALSE', '0', 'OFF', '假', ''):
                return False
            raise ValueError(value)
        return bool(value)
    if t == 'TIME':
        if isinstance(value, str):
            from .st import parse_time
            ms = parse_time(value)
            if ms is None:
                return wrapper('TIME')(float(value))
            return wrapper('TIME')(ms)
        return wrapper('TIME')(value)
    if isinstance(value, str):
        value = float(value) if any(ch in value for ch in '.eE') else int(value, 0)
    if t in ('REAL', 'LREAL'):
        return float(value)
    if t == 'STRING':
        return str(value)
    return wrapper(t)(int(round(value)) if isinstance(value, float) else value)


__all__ = ['PlcRuntime', 'program_hash', 'fmt_time']
