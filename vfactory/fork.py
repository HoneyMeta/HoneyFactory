"""从此刻推演（实时孪生的 what-if）：把运行中工厂的当前状态复制一份，在后台进程里快进 N 小时，
和"照现在这样继续"的基准副本比较 KPI。两个副本从同一状态、同一组随机数出发（公共随机数），差异只来自改动。

改动（changes 列表，作用在副本上，不碰运行中的工厂）：
  param     {station, key, value}   改设备参数（如 mtbf_h、time、run_kw、setup_min）
  setpoint  {station, tag, value}   写可写点位（如 Setpoint/SpeedPct）
  fault     {station, kind}         注入故障（failure / slow / clear …）
  enable    {station, value}        停用/启用设备
  buffer    {name, value}           缓存容量
"""
from .i18n import _tr
import asyncio
import copy
import pickle
import time
from collections import deque

from .experiment import KPI_KEYS, ci, pool


def snapshot_blob(plant) -> bytes:
    """把工厂的当前状态序列化（去掉协议/场景等外部回调，丢掉历史日志，只留在制零件）。"""
    from .history import TagRing
    keep = {k: getattr(plant, k) for k in ('listeners', 'part_hooks', 'event_hooks', 'step_hooks', 'state_log', 'class_log', 'events', 'parts',
                                           'labels', 'tagring', 'hourly', 'lead_times', 'wip_log', 'energy_q')}
    net = plant.__dict__.pop('net', None)      # 4.3 网络层（netmodel.Network）引用着服务器运行时，不进快照；副本里没有网络层照样能跑
    try:
        plant.listeners, plant.part_hooks, plant.event_hooks, plant.step_hooks = [], [], [], []
        plant.state_log, plant.class_log = deque(maxlen=300000), deque(maxlen=300000)
        plant.events, plant.labels = deque(maxlen=2000), deque(maxlen=20000)
        plant.parts = {k: v for k, v in keep['parts'].items() if v.get('status') not in ('SCRAP', 'SHIPPED', 'CONSUMED', 'RAW_STORE')}
        plant.tagring = TagRing(plant, n=64)
        plant.hourly, plant.lead_times = deque(maxlen=24 * 60), deque(maxlen=50000)
        plant.wip_log, plant.energy_q = deque(maxlen=60 * 24 * 14), deque(maxlen=4 * 24 * 31)
        return pickle.dumps(plant, protocol=pickle.HIGHEST_PROTOCOL)
    finally:
        for k, v in keep.items():
            setattr(plant, k, v)
        if net is not None:
            plant.net = net


def reseed(p, seed):
    """所有设备换一组随机流（重复推演用）。两个副本用同一个 seed，仍是公共随机数。"""
    p.seed = int(seed)
    for st in p.all_stations():
        st.rng = p.child_rng(st.id)
        if hasattr(st, 'ctx'):
            st.ctx.rng = p.child_rng(st.id + ':x')
        if hasattr(st, 'rng_route'):
            st.rng_route = p.child_rng(st.id + ':route')
            st.rng_mix = p.child_rng(st.id + ':mix')
        if getattr(st, '_sctx', None) is not None:
            st._sctx.rng = p.child_rng(st.id + ':sig')
        st.failure.rng = p.child_rng(st.id + ':fail') if st.split_streams else st.rng


def apply_live(p, changes):
    errs = []
    for ch in changes or []:
        t = ch.get('type')
        st = p.find(ch.get('station')) if ch.get('station') else None
        if t in ('param', 'setpoint', 'fault', 'enable') and st is None:
            errs.append(_tr('没有设备 {get}', get=ch.get('station')))
            continue
        if t == 'param':
            v = ch.get('value')
            try:
                v = float(v) if isinstance(v, str) and v.replace('.', '', 1).lstrip('-').isdigit() else v
            except ValueError:
                pass
            st.cfg[ch['key']] = v
            if ch['key'] == 'mtbf_h':
                st.failure.mtbf_h = float(v or 0)
                st.failure.next_fail = st.failure._draw() if st.failure.mtbf_h else float('inf')
            elif ch['key'] == 'mttr_min':
                st.failure.mttr_min = float(v or 30)
        elif t == 'setpoint':
            e = st.write(ch['tag'], ch.get('value'))
            if e:
                errs.append(e)
        elif t == 'fault':
            e = st.inject(ch.get('kind', 'failure'))
            if e:
                errs.append(e)
        elif t == 'enable':
            st.enabled = bool(ch.get('value'))
        elif t == 'buffer':
            b = p.buffers.get(ch.get('name'))
            if b is None:
                errs.append(_tr('没有缓存 {get}', get=ch.get('name')))
            else:
                b.capacity = int(float(ch.get('value')))
        else:
            errs.append(_tr('推演不支持改动类型 {t}（结构改动请用实验对比）', t=t))
    return errs


def run_fork(blob, hours, changes, seed=None):
    """子进程：还原副本 → 应用改动 → 快进 → KPI 与曲线。"""
    from .analysis import energy
    from .history import snapshot, summary
    t_wall = time.time()
    p = pickle.loads(blob)
    if seed is not None:
        reseed(p, seed)
    errs = apply_live(p, changes)
    start = p.t
    for st in p.all_stations():                    # 统计从分叉时刻开始：先记下每台设备当前的状态
        p.state_log.append((p.t, st.id, st.state))
        p.class_log.append((p.t, st.id, st._cls or 'idle'))
    p.hourly.append(snapshot(p))
    p.energy_q.clear()
    p._e_q = 0.0
    k0 = dict(p.kpi)
    curve = []
    step = 600
    n = int(hours * 3600 / p.dt)
    for i in range(n):
        p.step()
        if int(p.t - start) % step == 0:
            curve.append({'t': p.clock_str()[5:16], 'good': p.kpi['good'] - k0['good'], 'wip': p.wip_now()})
    r = summary(p, start, p.t)
    e = energy(p, start, p.t)
    lts = sorted(lt / 3600 for t, lt in p.lead_times if t >= start)
    wl = [w for t, w in p.wip_log if t >= start]
    kpi = {'good': p.kpi['good'] - k0['good'], 'good_per_h': round((p.kpi['good'] - k0['good']) / max(1e-6, hours), 2),
           'scrap_rate': round((p.kpi['scrap'] - k0['scrap']) / max(1, p.kpi['castings'] - k0['castings']), 4),
           'energy_total': e['kwh'], 'kwh_per_good': e['kwh_per_good'], 'wip_avg': round(sum(wl) / len(wl), 2) if wl else None,
           'lead_mean': round(sum(lts) / len(lts), 3) if lts else None, 'lead_p90': round(lts[int(0.9 * (len(lts) - 1))], 3) if lts else None,
           'escape': p.kpi['escape'] - k0['escape'], 'energy_cost': e['cost'], 'peak_kw': e['peak_kw'], 'co2_kg': e['co2_kg']}
    return {'kpi': kpi, 'curve': curve, 'bottleneck': r['bottleneck'][:3], 'errors': errs, 'from': r['from'], 'to': r['to'],
            'seed': seed, 'wall_s': round(time.time() - t_wall, 1)}


async def fork(plant, hours=4.0, changes=None, reps=1, name='改动后'):
    """基准副本 vs 改动副本，各重复 reps 次（第 1 次沿用当前随机流状态，之后每次换一组公共种子）。"""
    hours = max(0.25, min(72.0, float(hours)))
    reps = max(1, min(10, int(reps)))
    t_wall = time.time()
    blob = snapshot_blob(plant)
    loop = asyncio.get_running_loop()
    futs = []
    for r in range(reps):
        seed = None if r == 0 else 9000 + r
        try:
            ex = pool()
            fa = loop.run_in_executor(ex, run_fork, blob, hours, [], seed)
            fb = loop.run_in_executor(ex, run_fork, blob, hours, copy.deepcopy(changes or []), seed)
        except Exception:                                  # 进程池不可用时退回线程
            fa = loop.run_in_executor(None, run_fork, blob, hours, [], seed)
            fb = loop.run_in_executor(None, run_fork, blob, hours, copy.deepcopy(changes or []), seed)
        futs.append((fa, fb))
    base, what = [], []
    for fa, fb in futs:
        base.append(await fa)
        what.append(await fb)
    rows = []
    for k, label, unit, better in KPI_KEYS:
        a = ci([x['kpi'].get(k) for x in base])
        b = ci([x['kpi'].get(k) for x in what])
        d = ci([(y['kpi'].get(k) - x['kpi'].get(k)) for x, y in zip(base, what) if x['kpi'].get(k) is not None and y['kpi'].get(k) is not None])
        rel = round((b['mean'] - a['mean']) / a['mean'], 4) if a['mean'] and b['mean'] is not None else None
        rows.append({'key': k, 'label': label, 'unit': unit, 'better': better, 'base': a, 'whatif': b, 'diff': d, 'rel': rel,
                     'significant': bool(d['lo'] is not None and (d['lo'] > 0 or d['hi'] < 0))})
    txt = []
    for r in rows:
        if r['rel'] is not None and abs(r['rel']) >= 0.02 and r['key'] in ('good', 'wip_avg', 'lead_mean', 'energy_total', 'scrap_rate', 'energy_cost'):
            good = r['rel'] * r['better'] > 0
            txt.append(_tr('{label}{v} {v2:.0f}%（{v3}）', label=r['label'], v=_tr('提高') if r['rel'] > 0 else _tr('降低'), v2=abs(r['rel']) * 100, v3=_tr('更好') if good else _tr('更差')))
    summary_txt = (_tr('从 {v} 起推演 {hours:g} 小时：', v=base[0]["from"], hours=hours) + (_tr('；').join(txt) if txt else _tr('各项指标变化都在 2% 以内')) + _tr('。'))
    return {'hours': hours, 'reps': reps, 'name': name, 'changes': changes or [], 'from': base[0]['from'], 'to': base[0]['to'],
            'rows': rows, 'text': summary_txt, 'errors': what[0]['errors'],
            'base': {'curve': base[0]['curve'], 'bottleneck': base[0]['bottleneck']}, 'whatif': {'curve': what[0]['curve'], 'bottleneck': what[0]['bottleneck']},
            'wall_s': round(time.time() - t_wall, 1), 'blob_kb': round(len(blob) / 1024)}
