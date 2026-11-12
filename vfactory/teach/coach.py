"""4.5 教练：运行日志、实时检查表、"为什么没反应"诊断、自动测试预检。学生按一下按钮，界面上马上有字。

每个工厂（主要是学生沙箱）一个 Coach，有人在看（轮询 /coach）时才挂到控制单元的 CellSim 上（control.sim.observe），
每个 20 ms 子步看一次：面板按钮、输入、输出、PLC 状态、单元状态、故障有没有变化 → 记一条日志（环形缓冲，最多 800 条）。
60 秒没人看自动摘下（大工厂不白花时间）。沙箱"重来"会换一个新工厂对象 → 新 Coach → 日志清空。

  GET  /api/p/{pid}/coach?since=<seq>      新日志 + 检查表 + 状态一句话 + 最近一次诊断 + 自动测试结果
  POST /api/p/{pid}/coach/trial {key?}     演示：按评分的测试序列在沙箱里自动做一遍（key 只演示这一项，比如要注入过载的那项）
  POST /api/p/{pid}/coach/stop_trial
  POST /api/p/{pid}/coach/autotest         自动测试预检：用 PLC 里的程序按评分标准完整跑一遍（和提交评分同一个函数，不记成绩）
  POST /api/p/{pid}/coach/clear            清空日志

日志条目 {seq, t: 单元仿真时间（秒）, wall: 墙钟（毫秒）, k: act|in|out|dev|alarm|plc|check|diag|info|trial, msg, …}。
诊断 {seq, msg, cause, rung?, elems?: [梯形图元件 id], line?: ST 行号, var, plc: PLC 块编号, hash: 程序哈希}：编辑器按哈希对上了才标红。
"""
from ..i18n import _tr, matches
import asyncio
import copy
import logging
import time
from collections import deque

from fastapi import Body, HTTPException, Request

log = logging.getLogger('vfactory.teach')

COACHES: dict = {}            # pid → Coach
PRE: dict = {}                # 场景编号（老师改过评分的课：场景编号#改动的哈希）→ 参考答案的前提状态（live.pre_states）
IDLE_DETACH_S = 60.0


def _hash(o):
    import hashlib
    import json
    return hashlib.md5(json.dumps(o, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:10]
MAX_LOG = 800

KIND_CN = {'act': '操作', 'in': '输入', 'out': '输出', 'dev': '设备', 'alarm': '报警', 'plc': 'PLC', 'check': '检查', 'diag': '诊断', 'info': '提示',
           'trial': '演示'}
PANEL_TYPES = ('button', 'estop', 'switch', 'potentiometer')
STATE_CN = {'Executing': '运行中', 'Idle': '待机', 'Starved': '等来料', 'Blocked': '出口堵住', 'Stopped': '停机', 'Setup': '换型'}


def _b(v):
    if isinstance(v, bool):
        return '1' if v else '0'
    if v is None:
        return '—'
    return str(v)


def _now_ms():
    return int(time.time() * 1000)


class Coach:
    def __init__(self, mgr, rt):
        self.mgr, self.rt, self.plant = mgr, rt, rt.plant
        self.pid = rt.pid
        self.entries = deque(maxlen=MAX_LOG)
        self.seq = 0
        self.last_poll = time.time()
        self.cells = {}               # 单元编号 → 观察状态
        self.diag = None
        self.auto = None              # 自动测试预检结果
        self.auto_busy = False
        self.lc = None                # LiveChecker（有场景时）
        self.spec = None
        self.scene = None
        self.scene_id = None
        self.overlay = None           # 4.6 老师在课程编辑器里改过的评分（rubric / tests / extra_rules）：检查表、演示、预检都按它
        self.pre_key = None
        self.user_note = {}           # 部件 → 墙钟（界面上点的按钮：日志里写"你按下了"）
        self.expect = []              # 按了按钮以后等输出变化（没变就诊断）
        self.prog_hash = None
        self._find_scene()
        self.info(_tr('开始记录运行日志：你在操作台上的每一次操作、PLC 输入输出的每一次变化都会记在这里'))

    # ---------------- 场景 / 对象 ----------------
    def _find_scene(self):
        from . import scenes as ts
        sid = (getattr(self.rt, 'cfg', None) or {}).get('scene')
        if not sid:
            for c in ts.cells(self.rt):
                sid = (getattr(c, 'cell_def', None) or {}).get('scene')
                if sid:
                    break
        if not sid:
            return
        from ..control import scenes as cs
        sc = cs.get_scene(sid)
        if not sc:
            return
        # 4.6：老师在课程编辑器里选了部分评分项 / 加了"按 X → Y 秒内输出 Z"的检查：实时检查表、演示、自动测试预检和最终评分用同一份改过的场景
        ov = self._lesson_overlay()
        if ov:
            try:
                sc = ts.overlay_scene(sc, ov)
                self.overlay = ov
            except Exception:                           # noqa: BLE001
                log.exception(_tr('课程评分改动套用失败，检查表按原场景'))
        self.scene, self.scene_id = sc, sid
        self.pre_key = sid if not self.overlay else sid + '#' + _hash(self.overlay)
        pre = PRE.get(self.pre_key)
        if pre is not None:
            self._make_checker(pre)

    def _lesson_overlay(self):
        """这个沙箱是哪一课的（沙箱表 / 复核沙箱的提交）→ 课里老师对场景评分的改动；没有返回 None。"""
        try:
            from . import db
            from .tasks import CellTask, task_of
            pid = str(getattr(self.rt, 'pid', '') or '')
            r = db.q('select assignment_id from sandboxes where pid=?', (pid,), one=True)
            if not r and pid.startswith('sb-review-'):
                r = db.q('select assignment_id from submissions where id=?', (int(pid[len('sb-review-'):]),), one=True)
            if not r:
                return None
            a = db.assignment(r['assignment_id'])
            t = task_of(a) if a else None
            return t.overlay() if isinstance(t, CellTask) else None
        except Exception:                               # noqa: BLE001
            return None

    def _make_checker(self, pre):
        from ..control import live
        self.spec = live.build_spec(self.scene, pre)
        hows = _hows(self.scene)
        for it in self.spec['items']:
            h = hows.get(it['key'])
            if h:
                it['how'] = h.get('how') or it['how']
                it['means'] = h.get('means') or it['means']
        self.lc = live.LiveChecker(self.spec, self.scene)

    async def ensure_pre(self):
        if self.scene is None or self.lc is not None:
            return
        sid = self.pre_key or self.scene_id
        if sid not in PRE:
            from ..control import live
            PRE[sid] = None
            loop = asyncio.get_running_loop()
            try:
                from .api import score_pool
                pre = await loop.run_in_executor(score_pool(), live.pre_states, self.scene)
            except Exception:                           # noqa: BLE001
                log.exception(_tr('实时检查表准备失败'))
                pre = {}
            PRE[sid] = pre
        if PRE.get(sid) is not None and self.lc is None:
            self._make_checker(PRE[sid])

    def plc_of(self, cell):
        from . import scenes as ts
        p = ts.plc_station(self.rt, cell.id)
        return p, (ts._plc(p) if p is not None else None)

    # ---------------- 日志 ----------------
    def add(self, k, msg, t=None, **kw):
        self.seq += 1
        e = {'seq': self.seq, 't': round(t, 2) if isinstance(t, (int, float)) else None, 'wall': _now_ms(), 'k': k, 'msg': msg}
        e.update({x: y for x, y in kw.items() if y is not None})
        self.entries.append(e)
        return e

    def info(self, msg, **kw):
        return self.add('info', msg, t=self._t(), **kw)

    def _t(self):
        for c in self.cells.values():
            return c['sim'].t
        return None

    # ---------------- 挂上观察者 ----------------
    def attach(self):
        from ..control.sim import observe
        from . import scenes as ts
        seen = set()
        for c in ts.cells(self.rt):
            seen.add(c.id)
            st = self.cells.get(c.id)
            sim = getattr(c, 'sim', None)
            if sim is None:
                continue
            if st is not None and st['sim'] is sim:
                continue
            if st is not None:
                observe(st['sim'], None)
                self.add('dev', _tr('{name}：设备复位（零件清空、单元时间归零）', name=c.name), t=0.0, cell=c.id)
                if self.lc is not None:
                    self.lc.pending.clear()
                    self.lc.armed.clear()
                    self.lc.trial = None
            self.cells[c.id] = self._cell_state(c, sim)
            observe(sim, self._make_obs(c.id))
        for cid in list(self.cells):
            if cid not in seen:
                observe(self.cells.pop(cid)['sim'], None)

    def detach(self):
        from ..control.sim import observe
        for st in self.cells.values():
            observe(st['sim'], None)
        self.cells.clear()

    def _cell_state(self, c, sim):
        io = {e['name']: e for e in sim.io}
        panels = {x.id: x for x in sim.comps.values() if x.type in PANEL_TYPES}
        return {'cell': c, 'sim': sim, 'io': io, 'ins': dict(sim.inputs()), 'outs': dict(sim.outputs),
                'panel': {k: getattr(x, 'state', 0) for k, x in panels.items()}, 'panels': panels, 'next_slow': 0.0, 'plc_state': None, 'plc_err': None,
                'cell_state': None, 'alarm': None, 'faults': None, 'held_snap': None, 'held_t': -1.0, 'cnt': 0}

    def _make_obs(self, cid):
        def ob(sim):
            st = self.cells.get(cid)
            if st is None or st['sim'] is not sim:
                return
            if time.time() - self.last_poll > IDLE_DETACH_S:
                from ..control.sim import observe
                observe(sim, None)
                self.cells.pop(cid, None)
                return
            self._tick(st, sim)
        return ob

    # ---------------- 每个子步 ----------------
    def _tick(self, st, sim):
        t = sim.t
        c = st['cell']
        ins = sim.inputs()
        outs = sim.outputs
        prev_outs = st['outs']
        trial = self.lc is not None and self.lc.trial is not None
        # 面板动作
        for k, x in st['panels'].items():
            v = getattr(x, 'state', 0)
            ov = st['panel'].get(k)
            if v == ov:
                continue
            st['panel'][k] = v
            lab = x.d.get('label') or k
            who = _tr('演示：') if trial else (_tr('你') if time.time() - self.user_note.pop(k, 0) < 3 else '')
            if x.type == 'potentiometer':
                ev = {'k': 'set', 'comp': k, 'value': v, 't': t}
                self.add('act', _tr('{who}把 {lab}（{k}）调到 {v}', who=who, lab=lab, k=k, v=v), t=t, comp=k, code=ev['k'])
            elif x.type == 'switch':
                ev = {'k': 'set', 'comp': k, 'value': v, 't': t}
                self.add('act', _tr('{who}把 {lab}（{k}）拨到 {v}', who=who, lab=lab, k=k, v=_tr('开') if v else _tr('关')), t=t, comp=k, code=ev['k'])
            elif x.type == 'estop':
                ev = {'k': 'press' if v else 'release', 'comp': k, 't': t}
                self.add('act', _tr('{who}{v} {lab}（{k}）', who=who, v=_tr('拍下') if v else _tr('复位（旋起）'), lab=lab, k=k), t=t, comp=k, code=ev['k'])
            else:
                ev = {'k': 'press' if v else 'release', 'comp': k, 't': t}
                self.add('act', _tr('{who}{v} {lab}（{k}）', who=who, v=_tr('按下') if v else _tr('松开'), lab=lab, k=k), t=t, comp=k, code=ev['k'])
            ev['trial'] = trial
            if self.lc is not None:
                self.lc.on_event(ev, sim, prev_outs)
            if ev['k'] == 'press' and not trial:
                self._on_press(st, sim, k, lab)
        # 输入变化（布尔量逐条记；数值量不记，太多）
        pins = st['ins']
        for nm, v in ins.items():
            ov = pins.get(nm)
            if v != ov:
                e = st['io'].get(nm) or {}
                if isinstance(v, bool) or isinstance(ov, bool):
                    addr = str(e.get('addr') or '').lstrip('%')
                    note = _tr('（常闭：按下/动作时变 0）') if e.get('contact') == 'NC' and ov and not v else ''
                    self.add('in', _tr('输入 {addr} {nm} {v}→{v2}{note}', addr=addr, nm=nm, v=_b(ov), v2=_b(v), note=note), t=t, name=nm, v=v, cell=c.id)
                pins[nm] = v
        # 输出变化
        for nm, v in outs.items():
            ov = prev_outs.get(nm)
            if v != ov:
                e = st['io'].get(nm) or {}
                addr = str(e.get('addr') or '').lstrip('%')
                self.add('out', _tr('输出 {addr} {nm} {v}→{v2}', addr=addr, nm=nm, v=_b(ov), v2=_b(v)) + (_tr('（{get}）', get=e.get("comment")) if e.get('comment') else ''), t=t, name=nm, v=v, cell=c.id)
                for x in self.expect:
                    x['changed'] = True
        st['outs'] = dict(outs)
        # 按住按钮期间：记下 PLC 的在线值（诊断用：松开之后再分析就看不出"按着的时候哪里断了"）
        held = [k for k, x in st['panels'].items() if x.type == 'button' and getattr(x, 'state', 0)]
        if held and t - st['held_t'] >= 0.1:
            p, rp = self.plc_of(c)
            if rp is not None and getattr(rp, 'prog', None) is not None:
                from ..plc.explain import snapshot
                st['held_snap'] = {'snap': snapshot(rp), 'comps': held, 't': t, 'outs': dict(outs)}
                st['held_t'] = t
        # 慢的检查（每 0.2 s）：PLC 状态、单元状态/报警、故障
        if t >= st['next_slow']:
            st['next_slow'] = t + 0.2
            self._slow(st, sim)
        if self.lc is not None:
            self.lc.tick(sim)
            if self.lc.results:
                res, self.lc.results = self.lc.results, []
                for r in res:
                    self._on_result(st, sim, r)
        if self.expect:
            self._check_expect(st, sim)

    def _slow(self, st, sim):
        c = st['cell']
        p, rp = self.plc_of(c)
        if rp is not None:
            s = str(getattr(rp, 'state', '') or '')
            err = getattr(rp, 'error', None)
            if s != st['plc_state']:
                if st['plc_state'] is not None:
                    cn = {'RUN': _tr('运行'), 'STOP': _tr('停止（输出全部断开）'), 'HALT': _tr('暂停（断点/单步，输出保持）'), 'ERROR': _tr('出错停机')}.get(s, s)
                    self.add('plc', f'PLC {getattr(p, "name", "")} → {cn}', t=sim.t, state=s)
                st['plc_state'] = s
            em = (err or {}).get('msg') if isinstance(err, dict) else (str(err) if err else None)
            if em != st['plc_err']:
                if em:
                    self.add('alarm', _tr('PLC 运行错误：{em}', em=em), t=sim.t)
                st['plc_err'] = em
            h = getattr(getattr(rp, 'prog', None), 'hash', None)
            if h != self.prog_hash:
                if self.prog_hash is not None and self.lc is not None:
                    self.lc.reset()
                self.prog_hash = h
        cst, alarm = getattr(c, 'state', None), getattr(c, 'alarm', '') or ''
        if cst != st['cell_state']:
            if st['cell_state'] is not None:
                self.add('dev', _tr('{name}：{get} → {get2}', name=c.name, get=STATE_CN.get(st["cell_state"], st["cell_state"]), get2=STATE_CN.get(cst, cst)), t=sim.t, cell=c.id)
            st['cell_state'] = cst
        if alarm != st['alarm']:
            if alarm:
                self.add('alarm', _tr('{name} 报警：{alarm}', name=c.name, alarm=alarm), t=sim.t, cell=c.id)
            elif st['alarm']:
                self.add('alarm', _tr('{name} 报警消除', name=c.name), t=sim.t, cell=c.id)
            st['alarm'] = alarm
        fl = tuple(sorted((f['comp'], f['kind']) for f in sim.fault_list()))
        if fl != st['faults']:
            if st['faults'] is not None:
                from ..control import catalog as K
                new = set(fl) - set(st['faults'])
                gone = set(st['faults']) - set(fl)
                for comp, kind in sorted(new):
                    self.add('alarm', _tr('故障：{comp} {get}', comp=comp, get=K.FAULTS.get(kind, kind)), t=sim.t, comp=comp)
                for comp, kind in sorted(gone):
                    self.add('alarm', _tr('故障排除：{comp} {get}', comp=comp, get=K.FAULTS.get(kind, kind)), t=sim.t, comp=comp)
            st['faults'] = fl

    # ---------------- 按了按钮 ----------------
    def _on_press(self, st, sim, comp, lab):
        c = st['cell']
        p, rp = self.plc_of(c)
        e = next((x for x in st['io'].values() if x.get('comp') == comp and x.get('dir') == 'in'), None)
        name = e['name'] if e else comp
        if rp is None:
            self._diag({'msg': _tr('这个设备没有接 PLC，按钮不会有任何反应。'), 'cause': 'no_plc'}, sim, c, p)
            return
        state = str(getattr(rp, 'state', '') or '')
        if getattr(rp, 'prog', None) is None:
            self._diag({'msg': _tr('PLC 里还没有程序：按 {lab} 只会让输入 {name} 变化，不会有任何输出。先在编程窗口写好程序，点"下载"。', lab=lab, name=name), 'cause': 'no_program'},
                       sim, c, p)
            return
        if state != 'RUN':
            msg = {'STOP': _tr('PLC 现在是停止状态（STOP）：按 {lab} 输入 {name} 会变，但程序不执行、输出全是 0。在 PLC 面板或编程窗口点"运行"。', lab=lab, name=name),
                   'HALT': _tr('PLC 停在断点/单步上：输出不变。点"运行"继续，或者去掉断点。'),
                   'ERROR': _tr('PLC 出错停下了：看编程窗口顶上的红色错误，改好后重新下载。')}.get(state) or _tr('PLC 状态 {state}，程序没有在运行。', state=state)
            self._diag({'msg': msg, 'cause': 'plc_' + state.lower()}, sim, c, p)
            return
        self.expect = [x for x in self.expect if sim.t - x['t'] < 3] + [{'t': sim.t, 'comp': comp, 'name': name, 'lab': lab, 'changed': False,
                                                                         'cell': c.id, 'matched': False}]

    def _check_expect(self, st, sim):
        keep = []
        for x in self.expect:
            if x['changed'] or x['matched']:
                continue
            held = bool(getattr(st['panels'].get(x['comp']), 'state', 0))
            busy = self.lc is not None and (self.lc.pending or self.lc.armed)      # 检查表正在测这一下：等它的结果（带更准的诊断）
            if sim.t - x['t'] < (1.5 if held else 1.0) or (busy and sim.t - x['t'] < 6):
                keep.append(x)
                continue
            self._generic_diag(st, sim, x)
        self.expect = keep

    def _generic_diag(self, st, sim, x):
        """按了按钮，1 秒内没有任何输出变化，也没有对应的检查项：看程序里有没有用到这个输入、用到它的梯级断在哪。"""
        c = st['cell']
        p, rp = self.plc_of(c)
        if rp is None or getattr(rp, 'prog', None) is None:
            return
        from ..plc import explain as X
        prog = rp.prog.program
        io = _io_rows(p, c)
        name = x['name']
        snap = (st['held_snap'] or {}).get('snap') if (st['held_snap'] or {}).get('t', -9) >= x['t'] - 0.05 else None
        snap = snap or X.snapshot(rp)
        lang = str(prog.get('lang') or 'LD').upper()
        if lang == 'LD':
            from ..plc.ld import COILS, iter_elements, norm_t
            uses = []
            for ri, r in enumerate(X.rungs_of(prog)):
                els = list((r or {}).get('elements') or [])
                if any(str(el.get('var') or '').upper() == name.upper() for el in iter_elements(els)):
                    coils = [el for el in iter_elements(els) if norm_t(el.get('t')) in COILS]
                    uses.append((ri, coils))
            if not uses:
                self._diag({'msg': _tr('按了 {lab}，但程序里没有用到输入 {name}：哪个梯级都没有 {name} 的触点，所以按它不会有任何反应。', lab=x["lab"], name=name), 'cause': 'unused_input',
                            'var': name}, sim, c, p, rp)
                return
            reads = {str(el.get('var') or '').upper() for r in X.rungs_of(prog) for el in iter_elements(list((r or {}).get('elements') or []))
                     if norm_t(el.get('t')) not in COILS}
            io_names = {str(e.get('name') or '').upper() for e in io or []}
            for ri, coils in uses:
                for el in coils:
                    v = str(el.get('var') or '').upper()
                    if v not in io_names and v in reads:       # 内部继电器（如 RUN）
                        continue
                    d = X.why_not(prog, snap, io, el.get('var'), True, trigger=name)
                    if d and d.get('cause') not in (None,):
                        d['msg'] = _tr('按了 {lab}，1 秒内没有任何输出变化。', lab=x["lab"]) + d['msg']
                        self._diag(d, sim, c, p, rp)
                        return
        else:
            src = str(prog.get('source') or '')
            if name.upper() not in src.upper():
                self._diag({'msg': _tr('按了 {lab}，但程序里没有用到输入 {name}，所以按它不会有任何反应。', lab=x["lab"], name=name), 'cause': 'unused_input', 'var': name}, sim, c, p, rp)
                return
            outs = [e['name'] for e in io if e.get('dir') == 'out']
            for o in outs:
                d = X.why_not(prog, snap, io, o, True, trigger=name)
                if d and d.get('line') and name.upper() in d.get('msg', '').upper():
                    d['msg'] = _tr('按了 {lab}，1 秒内没有任何输出变化。', lab=x["lab"]) + d['msg']
                    self._diag(d, sim, c, p, rp)
                    return
        self.add('info', _tr('按了 {lab}，1 秒内没有输出变化（程序里用到了 {name}，但现在的条件还不满足）。可以在编程窗口里点梯级上的"解释"看能流。', lab=x["lab"], name=name),
                 t=sim.t)

    # ---------------- 检查结果 ----------------
    def _on_result(self, st, sim, r):
        if r.get('trial_end'):
            self.add('trial', r['msg'], t=sim.t)
            return
        it = next((i for i in self.spec['items'] if i['key'] == r.get('key')), None)
        lab = it['label'] if it else r.get('key')
        if r['ok'] is None:
            self.add('check', _tr('— {lab}：{msg}', lab=lab, msg=r["msg"]), t=sim.t, key=r.get('key'), ok=None)
            return
        via = _tr('（演示）') if r.get('via') == 'trial' else ''
        if r['ok']:
            self.add('check', f'✓ {lab}{via}', t=sim.t, key=r.get('key'), ok=True)
        else:
            self.add('check', _tr('✗ {lab}{via}：{msg}', lab=lab, via=via, msg=r["msg"]), t=sim.t, key=r.get('key'), ok=False)
        for x in self.expect:
            x['matched'] = True
        if not r['ok'] and r.get('c'):
            self._check_diag(st, sim, r)
        if self.lc is not None:
            items = self.lc.items(sim)
            if items and all(i['state'] == 'ok' for i in items) and not getattr(self, '_all_ok_said', False):
                self._all_ok_said = True
                self.add('check', _tr('🎉 检查表全部打勾：可以点"提交评分"了（提交时系统会按同样的标准从头再测一遍）'), t=sim.t, ok=True, key='_all')

    def _check_diag(self, st, sim, r):
        c = st['cell']
        p, rp = self.plc_of(c)
        from ..plc import explain as X
        cond = r['c']
        if 'never_both' in cond:
            a, b = cond['never_both'][:2]
            self._diag({'msg': _tr('{a} 和 {b} 同时为 1（正反转同时得电会短路）：两个线圈要互锁——{a} 的梯级里串一个 {b} 的常闭触点，{b} 的梯级里串一个 {a} 的常闭触点。', a=a, b=b),
                        'cause': 'interlock', 'var': a}, sim, c, p, rp)
            return
        if rp is None:
            return
        prog = getattr(getattr(rp, 'prog', None), 'program', None)
        io = _io_rows(p, c)
        want, out = None, None
        if 'out' in cond and 'eq' in cond and isinstance(cond['eq'], bool):
            out, want = cond['out'], cond['eq']
        elif 'all_off' in cond:
            on = [n for n in (cond['all_off'] or []) if sim.outputs.get(n)]
            if on:
                out, want = on[0], False
        if not out:
            return
        acts = r.get('acts') or []
        trig = None
        for a in acts:
            if a.get('k') == 'press' and a.get('dt') == 0:
                trig = a.get('comp')
        trig_in = None
        if trig:
            e = next((x for x in st['io'].values() if x.get('comp') == trig and x.get('dir') == 'in'), None)
            trig_in = e['name'] if e else trig
        hs = st['held_snap']
        held = hs if hs and trig and trig in hs['comps'] and hs['t'] >= (r.get('t0') or 0) - 5 else None
        if held and want and held['outs'].get(out) and not sim.outputs.get(out):
            self._diag({'msg': _tr('按住 {trig_in} 时 {out} 得电了，一松开就掉电：没有自锁。在 {trig_in} 触点下面并联一个 {out} 的常开触点（输出自己保持自己），ST 里写成 {out} := ({trig_in} OR {out}) AND …;', trig_in=trig_in, out=out), 'cause': 'no_latch', 'var': out}, sim, c, p, rp)
            return
        snap = held['snap'] if held else X.snapshot(rp)
        wired = sim.outputs.get(out)
        plc_out = (getattr(rp, 'outputs', None) or {}).get(out)
        d = X.why_not(prog, snap, io, out, want, trigger=trig_in, wired=wired if plc_out is not None else None)
        if d is None and plc_out is not None and bool(plc_out) == bool(want) and bool(wired) != bool(want):
            d = {'msg': _tr('PLC 输出 {out} = {v}，设备收到的却是 {v2}：这一路断线或者没接上。', out=out, v=_b(plc_out), v2=_b(wired)), 'cause': 'not_wired', 'var': out}
        if d:
            self._diag(d, sim, c, p, rp)

    def _diag(self, d, sim, c, p, rp=None):
        now = time.time()
        last = self.diag or {}
        same = (last.get('cause'), last.get('rung'), last.get('line'), tuple(last.get('elems') or ())) == (d.get('cause'), d.get('rung'), d.get('line'), tuple(d.get('elems') or ()))
        if (same and now - last.get('_at', 0) < 8) or (last and abs(last.get('_t', -99) - sim.t) < 0.05):
            return                                     # 同一个原因不重复说；同一时刻的连带失败（指示灯跟着电机）只说第一条
        d = dict(d)
        d['plc'] = getattr(p, 'id', None)
        d['cell'] = c.id
        d['hash'] = getattr(getattr(rp, 'prog', None), 'hash', None) if rp is not None else None
        e = self.add('diag', _tr('诊断：') + d['msg'], t=sim.t, **{k: d.get(k) for k in ('cause', 'rung', 'elems', 'line', 'var', 'plc', 'hash')})
        d['seq'] = e['seq']
        d['_at'] = now
        d['_t'] = sim.t
        d['wall'] = e['wall']
        self.diag = d

    # ---------------- 界面钩子 ----------------
    def note_user(self, comp):
        self.user_note[comp] = time.time()
        if self.lc is not None and self.lc.trial is not None:
            self.lc.trial['abort'] = _tr('演示中途你按了操作台，演示停止')

    def on_download(self, r, program, st=None):
        if not r.get('ok'):
            errs = r.get('errors') or []
            first = errs[0] if errs else {}
            where = _tr('第 {line} 行', line=first['line']) if first.get('line') else _tr('梯级 {v}', v=first['rung'] + 1) if first.get('rung') is not None else ''
            self.add('plc', _tr('下载失败：程序有 {len} 个错误', len=len(errs)) + (_tr('（{where}：{get}）', where=where, get=first.get("msg")) if first else '') + _tr('，PLC 里还是原来的程序'), t=self._t())
            return
        lang = str((program or {}).get('lang') or 'LD').upper()
        if lang == 'LD':
            n = len(((program or {}).get('source') or {}).get('rungs') or [])
            what = _tr('梯形图 {n} 个梯级', n=n)
        else:
            n = len([x for x in str((program or {}).get('source') or '').split('\n') if x.strip()])
            what = _tr('ST {n} 行', n=n)
        state = {'RUN': _tr('，PLC 运行'), 'STOP': _tr('，PLC 停止（点"运行"开始）')}.get(r.get('state'), '')
        warn = _tr('，{len} 条警告', len=len(r.get("warnings") or [])) if r.get('warnings') else ''
        self.add('plc', _tr('下载程序（{what}{warn}）{state}', what=what, warn=warn, state=state), t=self._t(), state=r.get('state'), code='download')
        if self.lc is not None:
            self.lc.reset()
        self._all_ok_said = False
        self.diag = None
        self.auto = None
        if self.scene is not None:
            asyncio.ensure_future(self.run_auto(program, quiet=True))

    def on_plc_action(self, action, body, ok=True):
        a = {'run': _tr('点了"运行"'), 'stop': _tr('点了"停止"'), 'step': _tr('单步'), 'reset': _tr('复位 PLC'), 'reset_program': _tr('恢复初始程序'), 'unforce_all': _tr('取消全部强制')}.get(action)
        if action == 'force':
            v = body.get('value')
            a = _tr('强制 {get} = {v}', get=body.get("name"), v=_b(v)) if v is not None else _tr('取消强制 {get}', get=body.get("name"))
        if action == 'breakpoint':
            a = _tr('改断点')
        if a:
            self.add('plc', _tr('PLC：{a}', a=a), t=self._t())

    def on_force(self, name, value):
        self.add('act', _tr('强制 I/O {name} = {v}', name=name, v=_b(value)) if value is not None else _tr('取消强制 {name}', name=name), t=self._t(), name=name)

    # ---------------- 自动测试预检 ----------------
    async def run_auto(self, program=None, quiet=False):
        if self.scene is None or self.auto_busy:
            return self.auto
        from . import scenes as ts
        if program is None:
            program = ts.get_program(self.rt)
        if not program:
            return None
        self.auto_busy = True
        try:
            from .api import score_pool
            loop = asyncio.get_running_loop()
            args = (self.scene_id, program, self.overlay) if self.overlay else (self.scene_id, program)
            r = await asyncio.wait_for(loop.run_in_executor(score_pool(), ts.score_job, *args), timeout=300)
        except Exception as e:                          # noqa: BLE001
            r = {'ok': False, 'error': _tr('自动测试出错：{e}', e=e), 'score': 0, 'max': 100, 'details': []}
        finally:
            self.auto_busy = False
        sc = round(float(r.get('score') or 0) / float(r.get('max') or 100) * 100, 1) if r.get('ok') else None
        self.auto = {'score': sc, 'ok': bool(r.get('ok')), 'error': r.get('error'), 'at': _now_ms(),
                     'details': [{k: d.get(k) for k in ('key', 'label', 'ok', 'value', 'weight', 'score', 'desc')} for d in r.get('details') or []],
                     'log': [x for x in (r.get('log') or []) if matches(str(x.get('msg', '')), '检查未通过')][:8]}
        bad = [d for d in self.auto['details'] if not d.get('ok')]
        if sc is not None:
            self.add('check', _tr('自动测试预检（和提交评分同一套测试，不记成绩）：{sc:g} 分', sc=sc) + (_tr('，没过：{join}', join=_tr('、').join(d["label"] for d in bad)) if bad else _tr('，全部通过')),
                     t=self._t(), key='_auto', ok=not bad)
        elif not quiet:
            self.add('check', _tr('自动测试预检没有完成：') + str(r.get('error') or ''), t=self._t(), key='_auto', ok=False)
        return self.auto

    # ---------------- 给界面 ----------------
    def view(self, since=0):
        self.last_poll = time.time()
        out = {'seq': self.seq, 'entries': [e for e in self.entries if e['seq'] > since], 'first': self.entries[0]['seq'] if self.entries else 0,
               'scene': self.scene_id, 'state': self.state(), 'diag': {k: v for k, v in (self.diag or {}).items() if not k.startswith('_')} or None,
               'auto': self.auto, 'auto_busy': self.auto_busy}
        if since and self.entries and self.entries[0]['seq'] > since + 1:
            out['gap'] = True                            # 太久没取：中间有被挤掉的
        st = next(iter(self.cells.values()), None)
        if self.lc is not None:
            sim = st['sim'] if st else None
            running = (st or {}).get('plc_state') == 'RUN'
            items = self.lc.items(sim, running)
            auto = {d['key']: d for d in (self.auto or {}).get('details') or []}
            for it in items:
                a = auto.get(it['key'])
                if a is not None:
                    it['auto'] = {'ok': bool(a.get('ok')), 'value': a.get('value'), 'desc': a.get('desc') or ''}
            done = sum(1 for i in items if i['state'] == 'ok')
            out['checklist'] = {'items': items, 'done': done, 'total': len(items), 'all_ok': bool(items) and done == len(items),
                                'trial': ({'key': self.lc.trial.get('key'), 'end': self.lc.trial.get('end')} if self.lc.trial else None),
                                'auto_full': bool(self.auto and self.auto.get('score') is not None and self.auto['score'] >= 99.95)}
        elif self.scene is not None:
            out['checklist'] = {'items': [], 'preparing': True}
        return out

    def state(self):
        """操作台上的一句话：PLC 在不在跑、哪些输出得电了。另带 plc（PLC 状态）、program（有没有程序）。"""
        d = self._state()
        if d is not None:
            st = next(iter(self.cells.values()), None)
            p, rp = self.plc_of(st['cell'])
            d['plc'] = str(getattr(rp, 'state', '') or '') if rp is not None else None
            d['program'] = getattr(rp, 'prog', None) is not None if rp is not None else False
            d['t'] = round(st['sim'].t, 2)
        return d

    def _state(self):
        st = next(iter(self.cells.values()), None)
        if st is None:
            return None
        c, sim = st['cell'], st['sim']
        p, rp = self.plc_of(c)
        io = st['io']
        on = [n for n, v in sim.outputs.items() if v is True or (not isinstance(v, bool) and v)]
        estop = any(x.type == 'estop' and getattr(x, 'state', 0) for x in st['panels'].values())
        if rp is None:
            return {'kind': 'warn', 'text': _tr('没有接 PLC：设备不会动'), 'on': on}
        state = str(getattr(rp, 'state', '') or '')
        if getattr(rp, 'prog', None) is None:
            return {'kind': 'idle', 'text': _tr('PLC 还没有程序：先编程并下载'), 'on': on}
        if state == 'STOP':
            return {'kind': 'warn', 'text': _tr('PLC 已停止：输出全部断开（点"运行"）'), 'on': on}
        if state == 'HALT':
            return {'kind': 'warn', 'text': _tr('PLC 暂停在断点/单步：输出保持'), 'on': on}
        if state == 'ERROR':
            return {'kind': 'err', 'text': _tr('PLC 出错停机：看编程窗口的错误提示'), 'on': on}
        if estop:
            return {'kind': 'err', 'text': _tr('PLC 运行中 · 急停已拍下') + ('' if not on else _tr('（还有输出得电：{join}）', join=_tr('、').join(on[:4]))), 'on': on}
        if not on:
            return {'kind': 'idle', 'text': _tr('PLC 运行中 · 所有输出都没得电'), 'on': on}
        names = []
        for n in on[:4]:
            cm = (io.get(n) or {}).get('comment') or ''
            names.append(n + (_tr('（{cm}）', cm=cm) if cm else ''))
        return {'kind': 'run', 'text': _tr('PLC 运行中 · 得电：') + _tr('、').join(names) + ('…' if len(on) > 4 else ''), 'on': on}


def _io_rows(p, c):
    try:
        from ..plc.api import cell_def_of, io_rows
        if p is not None:
            return io_rows(cell_def_of(p))
    except Exception:                                   # noqa: BLE001
        pass
    return [dict(e) for e in getattr(getattr(c, 'sim', None), 'io', []) or []]


def _hows(scene):
    out = {}
    for r in ((scene.get('scoring') or {}).get('rules') or []):
        if r.get('how') or r.get('means'):
            out[r['key']] = {'how': r.get('how'), 'means': r.get('means')}
    return out


# ---------------- 跟随教程的步骤数据（vfactory/teach/tours/<课>.json，课程课的 "课程/课" 存成 "课程__课.json"） ----------------
import json as _json  # noqa: E402
import os as _os  # noqa: E402
import re as _re  # noqa: E402

TOURS = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'tours')


def _tour_path(key):
    k = str(key or '').replace('/', '__')
    if not _re.fullmatch(r'[A-Za-z0-9_\-]{1,80}', k):
        return None
    return _os.path.join(TOURS, k + '.json')


def tour_exists(key):
    p = _tour_path(key)
    return bool(p and _os.path.exists(p))


def load_tour(key):
    p = _tour_path(key)
    if not p or not _os.path.exists(p):
        return None
    from ..i18n import content                  # display texts in the current language (tours/i18n/<tour>.en.json)
    with open(p, encoding='utf-8') as f:
        return content(_json.load(f), p)


# ---------------- 取 / 建 ----------------
def coach_for(mgr, pid, create=True):
    sbs = getattr(mgr, 'sandboxes', None) or {}
    rt = mgr.rts.get(pid) or sbs.get(pid)
    for k in [k for k in COACHES if k not in mgr.rts and k not in sbs]:     # 卸载/删除了的沙箱：教练一起丢掉
        forget(k)
    if rt is None:
        return None
    co = COACHES.get(pid)
    if co is not None and (co.rt is not rt or co.plant is not rt.plant):
        co.detach()
        co = None
        COACHES.pop(pid, None)
    if co is None:
        if not create:
            return None
        co = COACHES[pid] = Coach(mgr, rt)
    return co


def hook(mgr, pid, what, **kw):
    """其他模块（控制层面板/强制/复位、PLC 下载/运行）调用：有 Coach 才记，没人看就什么都不做。"""
    try:
        co = coach_for(mgr, pid, create=False)
        if co is None:
            return
        if what == 'panel':
            co.note_user(kw.get('comp'))
        elif what == 'force':
            co.on_force(kw.get('name'), kw.get('value'))
        elif what == 'reset':
            co.attach()
        elif what == 'download':
            co.on_download(kw.get('result') or {}, kw.get('program'))
        elif what == 'plc':
            co.on_plc_action(kw.get('action'), kw.get('body') or {})
    except Exception:                                   # noqa: BLE001
        log.exception(_tr('教练钩子出错'))


def forget(pid):
    co = COACHES.pop(pid, None)
    if co is not None:
        co.detach()


def register(app, mgr):
    def _get(pid):
        try:
            mgr.get(pid)
        except HTTPException:
            raise
        co = coach_for(mgr, pid)
        if co is None:
            raise HTTPException(404, _tr('没有工厂 {pid}', pid=pid))
        co.attach()
        return co

    @app.get('/api/teach/tours/{key:path}')
    async def tour_get(key: str):
        d = load_tour(key)
        if d is None:
            raise HTTPException(404, _tr('这一课还没有跟随教程：{key}', key=key))
        return d

    @app.get('/api/p/{pid}/coach')
    async def coach_get(pid: str, since: int = 0):
        co = _get(pid)
        await co.ensure_pre()
        return co.view(since)

    @app.post('/api/p/{pid}/coach/trial')
    async def coach_trial(pid: str, body: dict = Body(default={})):
        co = _get(pid)
        await co.ensure_pre()
        if co.lc is None:
            raise HTTPException(400, _tr('这个工厂没有评分标准，不能演示'))
        st = next(iter(co.cells.values()), None)
        if st is None:
            raise HTTPException(400, _tr('没有控制单元'))
        key = (body or {}).get('key') or None
        p, rp = co.plc_of(st['cell'])
        if rp is None or getattr(rp, 'prog', None) is None or str(getattr(rp, 'state', '')) != 'RUN':
            raise HTTPException(400, _tr('先把程序下载到 PLC 并让 PLC 运行，再演示'))
        if co.plant.paused:
            raise HTTPException(400, _tr('仿真暂停着：先点"运行"'))
        it = next((i for i in co.spec['items'] if i['key'] == key), None) if key else None
        dur = co.lc.start_trial(st['sim'], key)
        co.add('trial', _tr('开始演示{v}：按评分时的测试顺序自动操作（约 {dur:.0f} 秒），中途按操作台就停止', v=(_tr('「') + it["label"] + _tr('」')) if it else _tr('全部测试'), dur=dur), t=st['sim'].t)
        return {'ok': True, 'seconds': dur}

    @app.post('/api/p/{pid}/coach/stop_trial')
    async def coach_stop_trial(pid: str):
        co = _get(pid)
        if co.lc is not None and co.lc.trial is not None:
            co.lc.trial['abort'] = _tr('你停止了演示')
        return {'ok': True}

    @app.post('/api/p/{pid}/coach/autotest')
    async def coach_autotest(pid: str):
        co = _get(pid)
        if co.scene is None:
            raise HTTPException(400, _tr('这个工厂没有评分标准'))
        r = await co.run_auto()
        if r is None:
            raise HTTPException(400, _tr('还没有下载过程序'))
        return r

    @app.post('/api/p/{pid}/coach/clear')
    async def coach_clear(pid: str, request: Request):
        co = _get(pid)
        co.entries.clear()
        co.info(_tr('日志已清空'))
        return {'ok': True, 'seq': co.seq}

    _ = copy
