"""4.5 实时检查表：把场景的评分标准变成"边操作边打勾"的清单，判断逻辑和评分完全相同（scoring.eval_cond）。

评分是按自动测试序列 test.steps 跑的（第 1 秒按启动、第 2 秒检查电机……）；学生在沙箱里是自己按的，时间不固定。
这里把测试序列拆成一段一段的"触发 → 检查"：
  - 一段 = 上一次检查之后的动作（按/松按钮、拨开关、故障、清故障）+ 紧跟着的检查（at 某时刻 / within 多久内变成真 / hold 一直为真）；
  - 起点：最后一个动作是"按一下按钮"且检查在松开之后 → 从学生松开按钮起算（和评分时按 0.3 秒就松开一致）；检查在按住期间 → 从按下起算，
    要一直按着（例如"同时按启动和停止"）；其他动作从动作那一刻起算；
  - 前提：评分时（用参考答案跑同一个序列）动作之前主要输出的状态（灯和数码管不算），学生按的时候设备也要是这个状态，
    比如"按反转时正转在运行"才去检查互锁；
  - 含故障/清故障的段学生自己做不出来：清单里给"演示"按钮，在学生的沙箱里按测试序列自动做一遍（也是同样的检查）。
统计类评分项（分拣正确率、碰撞次数……）直接显示当前值和目标。

    spec = build_spec(scene, pre_states(scene))        # pre_states 用参考答案跑一遍（几秒），结果可以缓存
    lc = LiveChecker(spec)
    lc.on_event(ev, sim, prev_outs)                    # 观察者发现的动作：{'k': press|release|set|fault|clear, 'comp', 'value', 't'}
    lc.tick(sim)                                       # 每步一次
    lc.items(sim) → [{key, label, state, checks:[…], …}]
"""
from __future__ import annotations

from ..i18n import _tr
import copy

from .scoring import KEY_CN, OP_CN, OPS, Run, _get, eval_cond, rules_of, sim_stats

NOSTATE_TYPES = {'lamp', 'display'}          # 前提里不比较指示灯、数码管（灯接错了也能去试别的项目）
MANUAL = {'press', 'release', 'set'}
EPS = 1e-6


def _acts(step):
    out = []
    t = float(step.get('t', 0))
    if 'press' in step:
        out.append({'k': 'press', 'comp': step['press'], 'hold': float(step.get('hold', 0.3) or 0.3), 't': t})
    if 'release' in step:
        out.append({'k': 'release', 'comp': step['release'], 't': t})
    if 'set' in step:
        v = step['set']
        comp, val = (v[0], v[1]) if isinstance(v, (list, tuple)) else (v.get('comp'), v.get('value'))
        out.append({'k': 'set', 'comp': comp, 'value': val, 't': t})
    if step.get('fault'):
        out.append({'k': 'fault', 'comp': step['fault'].get('comp'), 'kind': step['fault'].get('kind'), 't': t})
    if step.get('clear_faults'):
        out.append({'k': 'clear', 't': t})
    return out


def _cond_outs(c):
    if 'out' in c:
        return [c['out']]
    if 'all_off' in c:
        return list(c['all_off'] or [])
    if 'never_both' in c:
        return list(c['never_both'][:2])
    return []


class _PreRun(Run):
    """用参考答案跑测试序列，记下每个动作之前的输出（活动检查的前提）。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pre_at = {}

    def _do(self, s, ins):
        if _acts(s):
            k = round(float(s.get('t', 0)), 3)
            self.pre_at.setdefault(k, dict(self.sim.outputs))
        super()._do(s, ins)


def pre_states(scene):
    """{动作时刻: 输出}（参考答案）。没有参考答案或跑不了返回 {}。可以在进程池里跑（只用场景 dict）。"""
    prog = (scene.get('reference') or {}).get('st') or (scene.get('reference') or {}).get('ld')
    if not prog:
        return {}
    try:
        r = _PreRun(scene, program=prog).run()
    except Exception:                                   # noqa: BLE001
        return {}
    if r.error:
        return {}
    return {str(k): v for k, v in r.pre_at.items()}


def _how_default(key, label, segs):
    """没写"怎么触发"时按测试序列生成一句。"""
    for sg in segs:
        names = []
        for a in sg['acts']:
            if a['k'] == 'press':
                names.append(_tr('按{v} {comp}', v=_tr('住') if sg['origin'] == 'press' and len(sg['acts']) > 1 else _tr('一下'), comp=a['comp']))
            elif a['k'] == 'release':
                names.append(_tr('松开/复位 {comp}', comp=a['comp']))
            elif a['k'] == 'set':
                names.append(_tr('把 {comp} 拨到 {value}', comp=a['comp'], value=a['value']))
            elif a['k'] == 'fault':
                names.append(_tr('出现故障'))
            elif a['k'] == 'clear':
                names.append(_tr('故障排除后'))
        if names:
            return _tr('，').join(names) + _tr('，看输出是不是符合要求')
    return ''


def build_spec(scene, pre=None):
    """场景 → 实时检查表的定义（可以 JSON 化）。"""
    pre = pre or {}
    test = scene.get('test') or {}
    steps = sorted(test.get('steps') or [], key=lambda s: float(s.get('t', 0)))
    comps = {c.get('id'): c for c in ((scene.get('cell') or {}).get('components') or [])}
    io = {e['name']: e for e in (scene.get('io') or (scene.get('cell') or {}).get('io') or []) if e.get('name')}

    def is_state_out(n):
        e = io.get(n) or {}
        return (comps.get(e.get('comp')) or {}).get('type') not in NOSTATE_TYPES

    key_outs = set()
    for s in steps:
        for c in (s.get('check'), s.get('watch')):
            if isinstance(c, dict):
                key_outs.update(n for n in _cond_outs(c) if is_state_out(n))
    groups = []               # [{'acts': [...], 'checks': [...]}]
    acts, checked = [], True
    watches = {}
    for i, s in enumerate(steps):
        a = _acts(s)
        if a:
            if checked:
                acts = []
                checked = False
                groups.append({'acts': acts, 'checks': []})
            acts.extend(a)
        if isinstance(s.get('check'), dict) and s.get('key'):
            if not groups:
                groups.append({'acts': acts, 'checks': []})
            checked = True
            mode = 'within' if s.get('within') else 'hold' if s.get('hold') else 'at'
            groups[-1]['checks'].append({'key': s['key'], 'c': s['check'], 'mode': mode, 'tc': float(s.get('t', 0)),
                                         'dur': float(s.get('within') or s.get('hold') or 0), 'desc': s.get('desc', ''), 'si': i})
        if isinstance(s.get('watch'), dict) and s.get('key'):
            watches.setdefault(s['key'], []).append({'c': s['watch'], 'desc': s.get('desc', ''), 'from': float(s.get('t', 0)),
                                                    'until': float(s.get('until', test.get('duration', 0)) or 0)})
    segs, step_cid = [], {}
    by_sig = {}
    for g in groups:
        if not g['checks']:
            continue
        ga = g['acts']
        if not ga:
            t_last = 0.0
            origin = 'state'
        else:
            last = max(ga, key=lambda a: a['t'])
            t_last = last['t']
            if last['k'] == 'press' and (comps.get(last['comp']) or {}).get('type') == 'estop':
                origin = 'press'
            elif last['k'] == 'press':
                dmin = min(c['tc'] - t_last for c in g['checks'])
                origin = 'release' if dmin >= last['hold'] - EPS else 'press'
            else:
                origin = 'act'
        t_first = min((a['t'] for a in ga), default=0.0)
        p0 = pre.get(str(round(t_first, 3))) or {}
        prereq = {n: bool(p0[n]) for n in sorted(key_outs) if n in p0}
        rel = [{**{k: v for k, v in a.items() if k != 't'}, 'dt': round(a['t'] - t_last, 3)} for a in ga]
        manual = bool(ga) and all(a['k'] in MANUAL for a in ga)
        if origin != 'state' and any(c['tc'] - t_last > 8 for c in g['checks']):
            origin = 'state'                       # 动作之后很久才检查（数码管、计数）：当作随时成立的状态检查
        sig = repr((rel, prereq, origin))
        sg = by_sig.get(sig)
        if sg is None:
            hold = 0.0
            if origin == 'release':
                hold = max(a.get('hold', 0.3) for a in ga if a['k'] == 'press' and a['t'] == t_last)
            sg = by_sig[sig] = {'id': f'g{len(segs)}', 'acts': rel, 'pre': prereq, 'origin': origin, 'manual': manual, 'hold': hold,
                                't_first': t_first, 't_last': t_last, 'checks': []}
            segs.append(sg)
        for c in g['checks']:
            d = round(c['tc'] - t_last - (sg['hold'] if origin == 'release' else 0.0), 3)
            ck = {'key': c['key'], 'c': c['c'], 'mode': c['mode'], 'd': max(0.0, d), 'dur': c['dur'], 'desc': c['desc']}
            same = next((x for x in sg['checks'] if {k: x[k] for k in ('key', 'c', 'mode', 'd', 'dur')} == {k: ck[k] for k in ('key', 'c', 'mode', 'd', 'dur')}), None)
            if same is None:
                ck['id'] = f"{sg['id']}c{len(sg['checks'])}"
                sg['checks'].append(ck)
                same = ck
            elif not same['desc'] and ck['desc']:
                same['desc'] = ck['desc']
            step_cid[c['si']] = same['id']
    items = []
    for r in rules_of(scene):
        key = r.get('key')
        ks = [sg for sg in segs if any(c['key'] == key for c in sg['checks'])]
        kind = 'check' if ks or key in watches else 'stat'
        it = {'key': key, 'label': r.get('label') or KEY_CN.get(key, key), 'weight': float(r.get('weight', 0) or 0), 'op': r.get('op', '>='),
              'value': r.get('value', 1), 'kind': kind, 'how': r.get('how') or '', 'means': r.get('means') or r.get('desc') or '',
              'segs': [sg['id'] for sg in ks], 'trial': any(not sg['manual'] and sg['origin'] != 'state' for sg in ks),
              'watch': watches.get(key, [])}
        if not it['how']:
            it['how'] = _how_default(key, it['label'], ks) if kind == 'check' else _tr('让设备连续运行一段时间，看{label}', label=it['label'])
        items.append(it)
    trial_end = {}
    for i, s in enumerate(steps):
        if isinstance(s.get('check'), dict) and s.get('key'):
            trial_end[s['key']] = max(trial_end.get(s['key'], 0.0), float(s.get('t', 0)) + float(s.get('hold') or s.get('within') or 0))
    return {'scene': scene.get('id'), 'items': items, 'segs': segs, 'step_cid': {str(k): v for k, v in step_cid.items()}, 'trial_end': trial_end,
            'duration': float(test.get('duration', 0) or 0), 'key_outs': sorted(key_outs)}


def _stats_fn(sim):
    cache = []

    def f():
        if not cache:
            cache.append(sim_stats(sim))
        return cache[0]
    return f


class LiveChecker:
    """一个沙箱的实时检查状态。所有时间都是单元仿真时间 sim.t。"""

    def __init__(self, spec, scene):
        self.spec = spec
        self.scene = scene
        self.segs = {sg['id']: sg for sg in spec['segs']}
        self.checks = {c['id']: (sg, c) for sg in spec['segs'] for c in sg['checks']}
        self.status = {}             # 检查 id → {'ok', 't', 'msg', 'via'}
        self.watch_bad = {}          # key → 文字
        self.pending = []            # 待判定：{'cid', 'sg', 'c', 'start', 'end', 'ok', 'mode', 'need_held'}
        self.armed = {}              # 起点 = 松开：按下时记下 {seg id: (t, 前提满足)}
        self.history = []            # 最近的动作 [(t, k, comp)]
        self.trial = None
        self.results = []            # 新判定的结果（教练取走写日志）

    # ---------------- 动作 ----------------
    def reset(self):
        self.status.clear()
        self.watch_bad.clear()
        self.pending.clear()
        self.armed.clear()
        self.history.clear()
        self.trial = None

    def _pre_ok(self, sg, outs):
        return all(bool(outs.get(n)) == v for n, v in sg['pre'].items())

    def _held(self, sim, comp):
        c = sim.comps.get(comp)
        return bool(getattr(c, 'state', 0)) if c is not None else False

    def _acts_ok(self, sg, sim, ev):
        """除了最后一个动作，段里其他动作：同时按的现在要按着；更早的要在最近 60 s 里按顺序发生过。"""
        last = [a for a in sg['acts'] if a['dt'] == 0]
        earlier = sorted([a for a in sg['acts'] if a['dt'] < 0], key=lambda a: a['dt'])
        mine = {a.get('comp') for a in sg['acts']}
        for cid, c in sim.comps.items():               # 评分时这一段只按了这几个按钮：别的按钮还按着（例如 Shift 锁住的启动）就不算这一段
            if c.type == 'button' and cid not in mine and getattr(c, 'state', 0):
                return False
        for a in last:
            if a.get('comp') == ev.get('comp'):
                continue
            if a['k'] == 'press' and not self._held(sim, a['comp']):
                return False
        t = ev['t']
        hist = [h for h in self.history if h[0] >= t - 60]
        pos = len(hist)
        for a in reversed(earlier):
            found = False
            while pos > 0:
                pos -= 1
                h = hist[pos]
                if h[1] == a['k'] and (a.get('comp') is None or h[2] == a.get('comp')):
                    found = True
                    break
            if not found:
                return False
        return True

    def _match_last(self, sg, ev, want_k):
        last = [a for a in sg['acts'] if a['dt'] == 0]
        if not last:
            return False
        for a in last:
            if a['k'] == want_k and a.get('comp') == ev.get('comp') and (want_k != 'set' or a.get('value') == ev.get('value')):
                return True
        return False

    def on_event(self, ev, sim, prev_outs):
        """一个用户动作（观察者从面板状态的变化里发现的）。"""
        if self.trial is not None and not ev.get('trial'):
            self.trial['abort'] = _tr('演示中途按了操作台，演示停止')
        if not ev.get('trial'):
            for p in self.pending:                      # 中途又动了别的：这次不算
                ids = {a.get('comp') for a in p['sg']['acts']}
                if ev.get('comp') not in ids or ev['k'] not in ('release', 'press'):
                    p['cancel'] = _tr('中途按了别的按钮，这一次不算')
                elif p['need_held'] and ev['k'] == 'release':
                    p['early'] = _tr('{get} 松开得太早（这一项要一直按着），这一次不算', get=ev.get('comp'))
        self.history.append((ev['t'], ev['k'], ev.get('comp')))
        if len(self.history) > 40:
            del self.history[:10]
        if ev.get('trial'):
            return
        for sg in self.spec['segs']:
            if not sg['manual'] or sg['origin'] == 'state':
                continue
            if sg['origin'] == 'release':
                if ev['k'] == 'press' and self._match_last(sg, ev, 'press'):
                    self.armed[sg['id']] = (ev['t'], self._pre_ok(sg, prev_outs) and self._acts_ok(sg, sim, ev))
                elif ev['k'] == 'release' and self._match_last(sg, {**ev}, 'press'):
                    arm = self.armed.pop(sg['id'], None)
                    if arm and arm[1]:
                        self._arm(sg, ev['t'], False)
            elif self._match_last(sg, ev, ev['k']) and self._pre_ok(sg, prev_outs) and self._acts_ok(sg, sim, ev):
                self._arm(sg, ev['t'], sg['origin'] == 'press' and any(a['k'] == 'press' for a in sg['acts']))

    def _arm(self, sg, t0, need_held, via='manual'):
        for c in sg['checks']:
            st = t0 + c['d']
            self.pending.append({'cid': c['id'], 'sg': sg, 'c': c, 'start': st, 'end': st + (c['dur'] or 0), 'ok': c['mode'] == 'hold',
                                 'mode': c['mode'], 'need_held': need_held, 'via': via, 't0': t0})

    # ---------------- 推进 ----------------
    def tick(self, sim):
        if self.trial is not None:
            self._trial_tick(sim)
        if self.pending:
            ins = None
            keep = []
            sf = _stats_fn(sim)
            for p in self.pending:
                if p.get('cancel'):
                    self.results.append({'cid': p['cid'], 'ok': None, 'msg': p['cancel'], 'key': p['c']['key'], 't': sim.t})
                    continue
                if p.get('early'):                     # 按住的按钮提前松开：用松开前最后一刻的值判断（仿真比墙钟慢时按 0.7 s 可能只走了 0.25 s）
                    if p.get('held_v') is None:
                        self.results.append({'cid': p['cid'], 'ok': None, 'msg': p['early'], 'key': p['c']['key'], 't': sim.t})
                    else:
                        p['ok'] = p['held_v']
                        self._resolve(p, sim)
                    continue
                if sim.t + EPS < p['start']:
                    if p['need_held'] and p['mode'] == 'at' and sim.t - p['t0'] >= 0.1:
                        if ins is None:
                            ins = sim.inputs()
                        p['held_v'] = eval_cond(p['c']['c'], sim, ins, sf)
                    keep.append(p)
                    continue
                if ins is None:
                    ins = sim.inputs()
                v = eval_cond(p['c']['c'], sim, ins, sf)
                if p['mode'] == 'within':
                    p['ok'] = p['ok'] or v
                elif p['mode'] == 'hold':
                    p['ok'] = p['ok'] and v
                else:
                    p['ok'] = v
                if p['mode'] == 'at' or sim.t >= p['end'] - EPS or (p['mode'] == 'hold' and not p['ok']) or (p['mode'] == 'within' and p['ok']):
                    self._resolve(p, sim)
                else:
                    keep.append(p)
            self.pending = keep
        # 整段监视（互锁）：PLC 在跑、有输出时一直看
        for it in self.spec['items']:
            for w in it['watch']:
                if it['key'] in self.watch_bad:
                    continue
                if not eval_cond(w['c'], sim, {}, _stats_fn(sim)):
                    names = _tr(' 和 ').join(_cond_outs(w['c']))
                    self.watch_bad[it['key']] = w['desc'] or _tr('{names} 同时为 1', names=names)
                    self.results.append({'cid': None, 'key': it['key'], 'ok': False, 'msg': self.watch_bad[it['key']], 't': sim.t, 'c': w['c']})

    def _resolve(self, p, sim):
        c = p['c']
        ok = bool(p['ok'])
        self.status[p['cid']] = {'ok': ok, 't': round(sim.t, 2), 'msg': '' if ok else (c['desc'] or _tr('没有达到要求')), 'via': p['via']}
        self.results.append({'cid': p['cid'], 'key': c['key'], 'ok': ok, 'msg': self.status[p['cid']]['msg'], 't': sim.t, 'c': c['c'],
                             'via': p['via'], 't0': p['t0'], 'acts': p['sg']['acts']})

    # ---------------- 演示：按测试序列在沙箱里自动做一遍 ----------------
    def start_trial(self, sim, key=None):
        steps = sorted((self.scene.get('test') or {}).get('steps') or [], key=lambda s: float(s.get('t', 0)))
        end = self.spec['trial_end'].get(key, self.spec['duration']) if key else self.spec['duration']
        start = 0.0
        if key:                                    # 从这一项的第一个动作开始演示（设备状态和评分时一样才行，否则从头演示）
            sgs = [sg for sg in self.spec['segs'] if any(c['key'] == key for c in sg['checks']) and sg['origin'] != 'state']
            if sgs:
                first = min(sgs, key=lambda sg: sg['t_first'])
                if self._pre_ok(first, sim.outputs):
                    start = max(0.0, first['t_first'] - 0.5)
        self.pending.clear()
        self.armed.clear()
        self.trial = {'t0': sim.t - start, 'si': 0, 'steps': [(i, s) for i, s in enumerate(steps) if start - EPS <= float(s.get('t', 0)) <= end + EPS],
                      'end': end, 'key': key, 'pend': [], 'faulted': False, 'abort': ''}
        return end - start

    def _trial_tick(self, sim):
        tr = self.trial
        if tr['abort']:
            self._trial_end(sim, tr['abort'])
            return
        rel = sim.t - tr['t0']
        ins = sim.inputs()
        while tr['si'] < len(tr['steps']) and float(tr['steps'][tr['si']][1].get('t', 0)) <= rel + EPS:
            i, s = tr['steps'][tr['si']]
            tr['si'] += 1
            if 'press' in s:
                sim.panel(s['press'], 'press', hold=s.get('hold', 0.3))
            if 'release' in s:
                sim.panel(s['release'], 'release')
            if 'set' in s:
                v = s['set']
                comp, val = (v[0], v[1]) if isinstance(v, (list, tuple)) else (v.get('comp'), v.get('value'))
                sim.panel(comp, 'set', val)
            if s.get('fault'):
                sim.inject(s['fault'].get('comp'), s['fault'].get('kind'))
                tr['faulted'] = True
            if s.get('clear_faults'):
                sim.clear_faults()
                tr['faulted'] = False
            if isinstance(s.get('check'), dict) and s.get('key') and (tr['key'] is None or s['key'] == tr['key']):
                cid = self.spec['step_cid'].get(str(i))
                hit = self.checks.get(cid)
                if hit:
                    sg, c = hit
                    mode = c['mode']
                    st = sim.t
                    self.pending.append({'cid': cid, 'sg': sg, 'c': c, 'start': st, 'end': st + (c['dur'] or 0), 'ok': mode == 'hold', 'mode': mode,
                                         'need_held': False, 'via': 'trial', 't0': st})
        if tr['si'] >= len(tr['steps']) and not any(p['via'] == 'trial' for p in self.pending) and rel >= tr['end'] - EPS:
            self._trial_end(sim, '')

    def _trial_end(self, sim, why):
        tr, self.trial = self.trial, None
        if tr and tr['faulted']:
            sim.clear_faults()
        for p in self.pending:
            if p['via'] == 'trial' and why:
                p['cancel'] = why
        self.results.append({'cid': None, 'key': tr.get('key') if tr else None, 'ok': None, 'trial_end': True, 'msg': why or _tr('演示结束'), 't': sim.t})

    # ---------------- 输出 ----------------
    def items(self, sim=None, running=True):
        out = []
        stats = None
        for it in self.spec['items']:
            d = {k: it[k] for k in ('key', 'label', 'weight', 'kind', 'how', 'means', 'trial')}
            d['target'] = f"{OP_CN.get(it['op'], it['op'])} {it['value']}"
            if it['kind'] == 'stat':
                if sim is not None:
                    if stats is None:
                        stats = sim_stats(sim)
                    v = _get(stats, it['key'])
                    d['value'] = round(v, 3) if isinstance(v, float) else v
                    ok = v is not None and OPS.get(it['op'], OPS['>='])(v, it['value'])
                    tried = (sim.t >= 20 and running) or bool(stats.get('removed'))
                    d['state'] = ('ok' if ok else 'fail') if tried else 'todo'
                    d['msg'] = _tr('当前 {v}（目标 {target}）', v=d['value'] if v is not None else '—', target=d['target'])
                else:
                    d['state'] = 'todo'
                out.append(d)
                continue
            cks = []
            for sid in it['segs']:
                sg = self.segs[sid]
                for c in sg['checks']:
                    if c['key'] != it['key']:
                        continue
                    s = self.status.get(c['id'])
                    cks.append({'id': c['id'], 'desc': c['desc'], 'ok': None if s is None else s['ok'], 'manual': sg['manual'], 'via': (s or {}).get('via'),
                                'state_check': sg['origin'] == 'state'})
            if sim is not None:
                ins = None
                for ck in cks:                            # 状态检查（数码管 = 库存…）：随时看
                    if ck['state_check']:
                        sg, c = self.checks[ck['id']]
                        if ins is None:
                            ins = sim.inputs()
                        ck['ok'] = bool(eval_cond(c['c'], sim, ins, _stats_fn(sim))) if (running and sim.t > 5) else None
            d['checks'] = [{k: v for k, v in ck.items() if k != 'state_check'} for ck in cks]
            bad = self.watch_bad.get(it['key'])
            oks = [ck['ok'] for ck in cks]
            if bad or any(x is False for x in oks):
                d['state'] = 'fail'
                d['msg'] = bad or next(ck['desc'] or _tr('没有达到要求') for ck in cks if ck['ok'] is False)
            elif oks and all(x is True for x in oks):
                d['state'] = 'ok'
            elif any(x is True for x in oks):
                d['state'] = 'partial'
            else:
                d['state'] = 'todo'
            out.append(d)
        return out


def checklist_of(scene, pre=None):
    """便捷：场景 → (spec, LiveChecker)。"""
    spec = build_spec(scene, pre)
    return spec, LiveChecker(spec, copy.deepcopy(scene))
