"""评分引擎：用学生程序（或参考答案）把场景从头跑一遍，按自动测试序列操作面板、注入故障、检查输出，再按评分规则打分。

场景里的测试序列 scene['test']：
  {"duration": 200,                    仿真总时长（秒）
   "feed": {"interval": 8},            有单元入口时：模拟整厂上游来料的间隔（秒，可写分布表达式）
   "steps": [                          按时间顺序执行（t 秒）
     {"t": 1, "press": "START"},               按一下按钮（默认按住 0.3 s，可写 "hold"）
     {"t": 5, "press": "ESTOP"} / {"t": 6, "release": "ESTOP"} / {"t": 7, "set": ["SW1", 1]}
     {"t": 2, "key": "start_ok", "check": {"out": "C1_FWD", "eq": true}}       某一时刻检查
     {"t": 2, "key": "x", "check": {...}, "within": 0.5}                         0.5 s 内变成真即可
     {"t": 2, "key": "x", "check": {...}, "hold": 3}                             之后 3 s 一直为真
     {"t": 0, "until": 180, "key": "interlock_ok", "watch": {"never_both": ["KM1", "KM2"]}}  整段时间监视
     {"t": 180, "snapshot": true}                统计快照（评分规则里的统计量取这一刻的值）
     {"t": 50, "fault": {"comp": "S1", "kind": "sensor_stuck_off"}} / {"t": 60, "clear_faults": true}
   ]}
检查条件 check：{"out": 名, "eq": 值} / {"in": 名, "eq": 值} / {"all_off": [名…]}（空列表 = 全部 BOOL 输出）
          / {"stat": "removed", "op": ">=", "value": 3} / {"out": "D1", "eq_stat": "bins.R1.n"}
同一个 key 的多条检查全部通过才算通过（值 1，否则 0）。

评分规则 scene['scoring']['rules']：[{key, label, op, value, weight}]，key 可以是统计量（sort_accuracy、collisions、jams、
throughput_per_min、removed、dropped、part_contacts、hard_drops、interlock_violations…，可用点号取下级：bins.R1.ok、
pallets.PL1.count、racks.RK1.stored、dwell_min.ST1、emit_min_gap.E1），也可以是测试序列里的检查 key。
"""
from __future__ import annotations

from ..i18n import _tr
import copy
import math

from .sim import DT, CellSim

OPS = {'>=': lambda a, b: a >= b - 1e-9, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b + 1e-9, '<': lambda a, b: a < b,
       '==': lambda a, b: abs(a - b) < 1e-6 if isinstance(a, (int, float)) and isinstance(b, (int, float)) else a == b,
       '!=': lambda a, b: a != b}
OP_CN = {'>=': '≥', '>': '>', '<=': '≤', '<': '<', '==': '=', '!=': '≠'}
KEY_CN = {'sort_accuracy': '分拣正确率', 'collisions': '碰撞次数', 'jams': '卡件次数', 'throughput_per_min': '每分钟产出', 'removed': '完成件数',
          'dropped': '掉件数', 'part_contacts': '零件追尾次数', 'hard_drops': '高处摔落次数', 'interlock_violations': '互锁错误次数',
          'hard_reversals': '高速直接反转次数', 'sorted_wrong': '分拣错误件数', 'sorted_ok': '分拣正确件数'}


def _program_of(program):
    """学生程序 / 参考答案包 {"st":…, "ld":…} → 一份程序。"""
    if isinstance(program, dict) and 'source' not in program:
        for k in ('st', 'ST', 'ld', 'LD', 'program'):
            if isinstance(program.get(k), dict):
                return program[k]
    return program


def _get(d, path):
    cur = d
    for k in str(path).split('.'):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def sim_stats(sim):
    """评分用的统计量（CellSim.stats() + 每个挡停的最短停留 dwell_min）。"""
    s = sim.stats()
    dm = {}
    for b in sim.by_bin.values():
        for pp in b['parts']:
            for k, v in (pp.get('holds') or {}).items():
                dm[k] = min(dm.get(k, math.inf), v)
    # 没有被挡停挡过的完成件按 0 计（只统计经过了这个挡停的单元）
    stoppers = [c.id for c in sim.comps.values() if c.type == 'stopper']
    for sid in stoppers:
        if any(b['parts'] for b in sim.by_bin.values()):
            for b in sim.by_bin.values():
                for pp in b['parts']:
                    if sid not in (pp.get('holds') or {}):
                        dm[sid] = 0.0
    s['dwell_min'] = {k: round(v, 2) for k, v in dm.items() if math.isfinite(v)}
    return s


def eval_cond(c, sim, ins, stats_fn):
    """检查条件 c 在当前时刻是否成立（评分和 4.5 的实时检查表共用这一份，保证两边判断完全一样）。
    stats_fn() → 统计量（只有条件里用到统计量时才调用）。"""
    if 'all_off' in c:
        names = c['all_off'] or [e['name'] for e in sim.io if e.get('dir') == 'out' and (e.get('type') or 'BOOL') == 'BOOL']
        return all(not sim.outputs.get(n) for n in names)
    if 'never_both' in c:
        a, b = c['never_both'][:2]
        return not (sim.outputs.get(a) and sim.outputs.get(b))
    if 'stat' in c:
        v = _get(stats_fn(), c['stat'])
        if v is None:
            return False
        return OPS.get(c.get('op', '>='), OPS['>='])(v, c.get('value', 0))
    if 'out' in c or 'in' in c:
        v = sim.outputs.get(c['out']) if 'out' in c else ins.get(c['in'])
        if 'eq_stat' in c:
            tgt = _get(stats_fn(), c['eq_stat'])
            return tgt is not None and v == tgt
        if 'eq' in c:
            ev = c['eq']
            return bool(v) == ev if isinstance(ev, bool) else v == ev
        op = c.get('op')
        if op:
            return v is not None and OPS[op](v, c.get('value', 0))
        return bool(v)
    return False


class Run:
    """一次评分运行（也可以单独用来做自动测试）。"""

    def __init__(self, scene, program=None, controller=None, seed=None, plc_factory=None):
        self.scene = scene
        self.cell = copy.deepcopy(scene.get('cell') or {})
        # 4.3：PLC 设置不在单元里（场景的 plc 段）；评分时按"单元 + 一台 PLC"直接建
        self.cell['plc'] = copy.deepcopy(scene.get('plc') or self.cell.get('plc') or {'mode': 'internal', 'scan_ms': 20})
        import numpy as np
        test = scene.get('test') or {}
        self.seed = int(seed if seed is not None else test.get('seed', 1))
        self.sim = CellSim(self.cell, np.random.default_rng(self.seed))
        self.test = test
        self.duration = float(test.get('duration', 120))
        self.steps = sorted(test.get('steps') or [], key=lambda s: float(s.get('t', 0)))
        self.si = 0
        self.checks: dict[str, list] = {}
        self.fails: dict[str, list] = {}       # 检查项 → 没通过的原因（测试步骤的 desc），给学生看
        self.pending = []           # within / hold / watch
        self.snap = None
        self.log = []
        self.error = ''
        self.compile = None
        self.controller = controller
        self.plc = None
        if controller is None:
            prog = _program_of(program)
            try:
                from .. import plc as plcmod
            except Exception as e:
                self.error = _tr('软 PLC 模块不可用：{e}', e=e)
                return
            if prog is not None:
                self.compile = plcmod.compile(prog, self.cell.get('io') or [])
                if not self.compile.get('ok'):
                    errs = self.compile.get('errors') or []
                    self.error = _tr('程序编译有错误：') + _tr('；').join(str(e.get('msg')) + (_tr('（第 {line} 行）', line=e['line']) if e.get('line') else '') for e in errs[:5])
                    return
            self.plc = (plc_factory or plcmod.for_cell)(self.cell, prog)
        self._feed_setup()

    # ---------------- 单元入口（模拟整厂上游） ----------------
    def _feed_setup(self):
        feed = self.test.get('feed') or {}
        self.feed_next = float(feed.get('start', 1.0))
        self.feed_q = []
        self.feed_n = 0
        sim = self.sim
        sim.entry_ready = lambda: bool(self.feed_q)
        sim.entry_take = lambda: self.feed_q.pop(0) if self.feed_q else None
        sim.exit_put = lambda part, port: True

    def _feed(self):
        feed = self.test.get('feed')
        if not feed:
            return
        mx = int(feed.get('max', 0) or 0)
        if self.sim.t >= self.feed_next and len(self.feed_q) < 3 and (not mx or self.feed_n < mx):
            self.feed_n += 1
            self.feed_q.append({'id': f'UP{self.feed_n:04d}', 'type': feed.get('type', 'A')})
            self.feed_next = self.sim.t + max(0.5, self.sim.expr(feed.get('interval', 8), 8.0))

    # ---------------- 测试步骤 ----------------
    def _cond(self, c, ins):
        return eval_cond(c, self.sim, ins, self._stats)

    def _record(self, key, ok, why=''):
        if not key:
            return
        self.checks.setdefault(key, []).append(bool(ok))
        if not ok and why:
            lst = self.fails.setdefault(key, [])
            if why not in lst:
                lst.append(why)
        if not ok:
            self.log.append({'t': round(self.sim.t, 2), 'msg': _tr('检查未通过：{key} {why}', key=key, why=why).strip()})

    def _do(self, s, ins):
        sim = self.sim
        if 'press' in s:
            sim.panel(s['press'], 'press', hold=s.get('hold', 0.3))
        if 'release' in s:
            sim.panel(s['release'], 'release')
        if 'set' in s:
            v = s['set']
            comp, val = (v[0], v[1]) if isinstance(v, (list, tuple)) else (v.get('comp'), v.get('value'))
            sim.panel(comp, 'set', val)
        if s.get('fault'):
            f = s['fault']
            sim.inject(f.get('comp'), f.get('kind'))
        if s.get('clear_faults'):
            sim.clear_faults()
        if s.get('snapshot'):
            self.snap = self._stats()
        if 'check' in s:
            if s.get('within'):
                self.pending.append({'kind': 'within', 'end': sim.t + float(s['within']), 'c': s['check'], 'key': s.get('key'), 'ok': False, 'desc': s.get('desc', '')})
            elif s.get('hold'):
                self.pending.append({'kind': 'hold', 'end': sim.t + float(s['hold']), 'c': s['check'], 'key': s.get('key'), 'ok': True, 'desc': s.get('desc', '')})
            else:
                ok = self._cond(s['check'], ins)
                self._record(s.get('key'), ok, s.get('desc', ''))
        if 'watch' in s:
            self.pending.append({'kind': 'hold', 'end': float(s.get('until', self.duration)), 'c': s['watch'], 'key': s.get('key'), 'ok': True,
                                 'desc': s.get('desc', '')})

    def _tick_pending(self, ins):
        keep = []
        for p in self.pending:
            v = self._cond(p['c'], ins)
            if p['kind'] == 'within':
                p['ok'] = p['ok'] or v
            else:
                p['ok'] = p['ok'] and v
            if self.sim.t >= p['end'] - 1e-9:
                self._record(p['key'], p['ok'], p['desc'])
            else:
                keep.append(p)
        self.pending = keep

    def _stats(self):
        return sim_stats(self.sim)

    # ---------------- 推进 ----------------
    def run(self):
        if self.error:
            return self
        sim = self.sim
        n = int(round(self.duration / DT))
        ctl = self.controller
        plc = self.plc
        for _ in range(n):
            ins = sim.inputs()
            while self.si < len(self.steps) and float(self.steps[self.si].get('t', 0)) <= sim.t + 1e-9:
                self._do(self.steps[self.si], ins)
                self.si += 1
                ins = sim.inputs()
            self._feed()
            if ctl is not None:
                outs = ctl(ins, DT)
            elif plc is not None:
                try:
                    outs = plc.scan(ins, DT)
                except Exception as e:
                    self.error = _tr('PLC 运行错误：{e}', e=e)
                    break
            else:
                outs = {}
            sim.apply_outputs(outs)
            sim.step(DT)
            if self.pending:
                self._tick_pending(sim.inputs())
            st = getattr(plc, 'state', None)
            if st == 'ERROR' and not self.error:
                err = getattr(plc, 'error', None) or {}
                self.error = _tr('PLC 运行错误：{v}', v=err.get('msg', '') if isinstance(err, dict) else err)
        for p in self.pending:
            self._record(p['key'], p['ok'], p['desc'])
        self.pending = []
        if self.snap is None:
            self.snap = self._stats()
        return self

    def values(self):
        v = dict(self.snap or {})
        for k, lst in self.checks.items():
            v[k] = 1 if lst and all(lst) else 0
        return v


def rules_of(scene):
    r = scene.get('scoring') or scene.get('rules') or []
    if isinstance(r, dict):
        r = r.get('rules') or []
    return r


def grade(scene, values):
    """按评分规则给分。返回 (得分, 满分, 明细)。"""
    total = mx = 0.0
    details = []
    for r in rules_of(scene):
        key = r.get('key')
        w = float(r.get('weight', 0) or 0)
        mx += w
        got = _get(values, key)
        op = r.get('op', '>=')
        target = r.get('value', 1)
        ok = got is not None and OPS.get(op, OPS['>='])(got, target)
        if ok:
            total += w
        details.append({'key': key, 'label': r.get('label') or KEY_CN.get(key, key), 'op': op, 'target': target, 'value': got, 'weight': w,
                        'score': w if ok else 0.0, 'ok': bool(ok), 'desc': r.get('desc', ''),
                        'text': _tr('{v} {get} {target}：实际 {v2}', v=r.get('label') or KEY_CN.get(key, key), get=OP_CN.get(op, op), target=target, v2=_fmt(got))})
    return round(total, 2), round(mx, 2), details


def _fmt(v):
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:.3g}'
    return str(v)


def score_scene(scene, program=None, controller=None, seed=None):
    """评分入口（教学模块调用）：返回 {ok, score, max, details, stats, checks, log, error?}。
    program 是学生程序（{lang, vars, source}）；不给时用场景的参考答案（ST）。"""
    if program is None and controller is None:
        program = (scene.get('reference') or {}).get('st')
    r = Run(scene, program=program, controller=controller, seed=seed).run()
    if r.error and r.snap is None:
        return {'ok': False, 'error': r.error, 'score': 0.0, 'max': float(sum(float(x.get('weight', 0) or 0) for x in rules_of(scene))) or 100.0,
                'details': [], 'stats': {}, 'checks': {}, 'log': r.log, 'compile': r.compile}
    vals = r.values()
    sc, mx, det = grade(scene, vals)
    for d in det:                                   # 4.5：检查项没过时写清楚是哪一步没做到（以前只在日志里）
        if not d['ok'] and not d.get('desc') and r.fails.get(d['key']):
            d['desc'] = _tr('；').join(r.fails[d['key']][:3])
    out = {'ok': not r.error, 'score': sc, 'max': mx, 'details': det, 'stats': r.snap, 'final_stats': r.sim.stats(),
           'checks': {k: (1 if v and all(v) else 0) for k, v in r.checks.items()}, 'log': (r.log + r.sim.events)[-80:], 'duration': r.duration}
    if r.error:
        out['error'] = r.error
    return out


score = score_scene
