"""实验对比：同一工厂的几种方案（基准 + 若干改动）在后台进程里各自快进 N 小时，自动比较 KPI 并给出结论。

改动类型（variants[i].changes 列表）：
  param     设备参数            station, key, value        如 CNC1 mtbf_h、MOLD1 cycle_s
  setpoint  开机后写设定值      station, tag, value        如 INS1 Setpoint/Sensitivity
  add       按模板加设备        template, count            如 复制 CNC1 两台
  remove    去掉设备            station
  crew      岗位人数            role, count
  buffer    缓存容量            name, value
  version   换成另一个模型版本   n（版本号，或 'draft' = 当前草稿）     结构对比：两个布局版本、两种工艺路线
  plan      换生产计划/班次      shifts?, workdays?, breaks?, orders?, label?   如 两班 → 三班、六天 → 五天
version 必须是该方案的第一条改动，后面的改动在这个版本上再做。
"""
from .i18n import _tr, label
import asyncio
import copy
import json
import math
import re
import time
from concurrent.futures import ProcessPoolExecutor

from . import store

_pool = None
KPI_KEYS = [('good', '合格入库', '件', 1), ('good_per_h', '小时产出', '件/h', 1), ('scrap_rate', '废品率', '', -1), ('energy_total', '用电', 'kWh', -1),
            ('kwh_per_good', '单件电耗', 'kWh', -1), ('wip_avg', '平均在制品', '件', -1), ('lead_mean', '平均生产周期', 'h', -1), ('escape', '漏检（真值）', '件', -1),
            ('lead_p90', '生产周期 P90', 'h', -1), ('energy_cost', '电费', '元', -1), ('peak_kw', '峰值需量', 'kW', -1), ('co2_kg', '碳排', 'kg', -1)]


def pool():
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=3)
    return _pool


def apply_plan(cfg, ch):
    """plan 改动：替换计划里的班次 / 工作日 / 休息 / 订单（只替换给出的字段）。"""
    pl = cfg.get('plan') or {}
    cfg['plan'] = pl
    for k in ('shifts', 'workdays', 'breaks', 'orders', 'products', 'downtime'):
        if ch.get(k) is not None:
            pl[k] = copy.deepcopy(ch[k])
    return cfg


def variant_cfg(cfg, changes, resolve=None):
    """方案用的模型：有 version 改动时换成那个版本（计划沿用当前的，除非该版本自带计划），其余改动照常。"""
    rest = []
    for ch in changes or []:
        if ch.get('type') == 'version':
            if resolve is None:
                raise ValueError(_tr('这里不支持按模型版本比较'))
            m = copy.deepcopy(resolve(ch.get('n')))
            if not m.get('plan'):
                m['plan'] = copy.deepcopy(cfg.get('plan'))
            m['plant'] = {**copy.deepcopy(cfg.get('plant') or {}), **(m.get('plant') or {})}
            cfg = m
        else:
            rest.append(ch)
    return cfg, rest


def apply_changes(cfg, changes):
    for ch in changes or []:
        if ch.get('type') == 'plan':
            apply_plan(cfg, ch)
    if 'blocks' in cfg:
        return apply_changes_v2(cfg, changes)
    sts = cfg['stations']
    for ch in changes or []:
        t = ch.get('type')
        if t == 'param':
            s = next((x for x in sts if x['id'] == ch['station']), None)
            if s:
                s[ch['key']] = _num(ch['value'])
        elif t == 'add':
            src = next((x for x in sts if x['id'] == ch['template']), None)
            if src:
                prefix = re.sub(r'\d+$', '', src['id'])
                for _ in range(int(ch.get('count', 1))):
                    n = 1
                    while any(x['id'] == f'{prefix}{n}' for x in sts):
                        n += 1
                    c = copy.deepcopy(src)
                    c['id'] = f'{prefix}{n}'
                    c['name'] = f'{n}#{src["name"].split("#", 1)[-1]}'
                    c['pos'] = [src['pos'][0], src['pos'][1] + 8 * (n - 3)]
                    sts.append(c)
                    for s2 in sts:
                        for r in s2.get('roles', []) or []:
                            if src['id'] in r['stations']:
                                r['stations'].append(c['id'])
        elif t == 'remove':
            cfg['stations'] = sts = [x for x in sts if x['id'] != ch['station']]
        elif t == 'crew':
            for s2 in sts:
                for r in s2.get('roles', []) or []:
                    if r['name'] == ch['role']:
                        r['count'] = int(ch['value'])
        elif t == 'buffer':
            cfg.setdefault('buffers', {})[ch['name']] = int(ch['value'])
    return cfg


def apply_changes_v2(cfg, changes):
    from .flow.model import new_id
    bl = cfg['blocks']
    byid = {b['id']: b for b in bl}
    for ch in changes or []:
        t = ch.get('type')
        if t == 'param' and ch.get('station') in byid:
            byid[ch['station']].setdefault('params', {})[ch['key']] = _num(ch['value'])
        elif t == 'add' and ch.get('template') in byid:
            src = byid[ch['template']]
            prefix = re.sub(r'\d+$', '', src['id']) or 'X'
            for k in range(int(ch.get('count', 1))):
                nid = new_id(cfg, prefix)
                c = copy.deepcopy(src)
                c['id'], c['name'] = nid, f"{nid} {src['name'].split('#', 1)[-1]}"
                c['pos'] = [src['pos'][0], src['pos'][1] + (src['size'][1] + 2) * (k + 1)]
                if c.get('node'):
                    c['node'] = [c['node'][0], c['node'][1] + 120 * (k + 1)]
                bl.append(c)
                byid[nid] = c
                for l in [l for l in cfg['links'] if src['id'] in (l['from'], l['to'])]:
                    l2 = copy.deepcopy(l)
                    l2['id'] = new_id(cfg, 'L')
                    l2['from'] = nid if l['from'] == src['id'] else l['from']
                    l2['to'] = nid if l['to'] == src['id'] else l['to']
                    cfg['links'].append(l2)
                for b in bl:
                    for r in (b.get('params') or {}).get('roles', []) or []:
                        if src['id'] in r.get('stations', []):
                            r['stations'].append(nid)
        elif t == 'remove':
            cfg['blocks'] = bl = [b for b in bl if b['id'] != ch['station']]
            cfg['links'] = [l for l in cfg['links'] if ch['station'] not in (l['from'], l['to'], l.get('via'))]
            byid.pop(ch['station'], None)
        elif t == 'crew':
            for b in bl:
                for r in (b.get('params') or {}).get('roles', []) or []:
                    if r['name'] == ch['role']:
                        r['count'] = int(ch['value'])
                if b['type'] == 'operators' and b.get('name') == ch['role']:
                    b['params']['count'] = int(ch['value'])
        elif t == 'buffer' and ch.get('name') in byid:
            byid[ch['name']].setdefault('params', {})['capacity'] = int(ch['value'])
    return cfg


def _num(v):
    try:
        return float(v) if '.' in str(v) else int(v)
    except (TypeError, ValueError):
        return v


def run_one(cfg, hours, seed, changes, warmup_h=None):
    """子进程里执行：建厂、预热（截掉）、快进、出汇总。同一个 seed 下各方案共用随机流（公共随机数）。"""
    from .analysis import energy
    from .core import Plant
    from .history import summary
    cfg = apply_changes(copy.deepcopy(cfg), changes)
    cfg['plant']['seed'] = seed
    cfg['plant']['start'] = '2026-11-02T07:00:00'
    warm = float(cfg['plant'].get('warmup_h', 3) if warmup_h is None else warmup_h)
    cfg['plant']['warmup_h'] = 0
    p = Plant(cfg)
    for ch in changes or []:
        if ch.get('type') == 'setpoint':
            st = p.find(ch['station'])
            if st:
                st.write(ch['tag'], ch['value'])
    t0 = time.time()
    p.run_for(warm * 3600)
    start = p.t
    p.run_for(hours * 3600)
    r = summary(p, start, p.t)                     # 与运行报表、方案报告同一套口径（在制品每分钟采样平均、生产周期按完成时刻）
    e = energy(p, start, p.t)
    lead = r['lead'] or {}
    bn = r['bottleneck_analysis']
    return {'good': r['good'], 'good_per_h': r['good_per_h'], 'scrap': r['scrap'], 'scrap_rate': r['scrap_rate'], 'castings': r['castings'],
            'energy_total': r['energy_total'], 'kwh_per_good': r['kwh_per_good'], 'kwh_per_t': r['kwh_per_t'], 'wip_avg': r['wip_avg'],
            'lead_mean': lead.get('mean_h'), 'lead_p90': lead.get('p90_h'),
            'escape': r['escape'], 'energy_cost': e['cost'], 'peak_kw': e['peak_kw'], 'co2_kg': e['co2_kg'],
            'bottleneck': [{k: b[k] for k in ('group', 'name', 'n', 'run', 'share', 'tie')} for b in r['bottleneck'][:3]],
            'bottleneck_verdict': bn['verdict'], 'bottleneck_tie': bn['tie'],
            'scrap_by': r['scrap_by'], 'util': [{k: u[k] for k in ('id', 'name', 'run')} for u in r['util']],
            'seed': seed, 'wall_s': round(time.time() - t0, 1)}


# ---------------- 统计：均值与 95% 置信区间 ----------------
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
         14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
         26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}


def t975(df):
    if df <= 0:
        return None
    if df in _T975:
        return _T975[df]
    for k in sorted(_T975):
        if k >= df:
            return _T975[k]
    return 1.96


# 指标的取值范围：比例在 [0, 1]，计数和物理量不小于 0。置信区间超出范围的部分截掉（并标记 clamped）。
BOUNDS = {k: ((0.0, 1.0) if k == 'scrap_rate' else (0.0, None)) for k, *_ in KPI_KEYS}
REL_KEYS = ('good_per_h', 'wip_avg', 'lead_mean', 'energy_total')      # 用来判断"区间是否太宽"的主要指标
REL_MAX = 0.2                                                         # 半宽超过均值的 20% 算太宽
MIN_REPS = 5


def ci(vals, bounds=None):
    """均值 ± t(0.975, n-1)·s/√n。n=1 时没有区间。bounds=(下限, 上限) 时把区间截到合理范围内（如比例 0~1、计数 ≥0）。"""
    v = [float(x) for x in vals if x is not None]
    n = len(v)
    if not n:
        return {'n': 0, 'mean': None, 'sd': None, 'lo': None, 'hi': None, 'half': None}
    m = sum(v) / n
    if n < 2:
        return {'n': 1, 'mean': round(m, 4), 'sd': None, 'lo': None, 'hi': None, 'half': None}
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    h = t975(n - 1) * sd / math.sqrt(n)
    out = {'n': n, 'mean': round(m, 4), 'sd': round(sd, 4), 'lo': round(m - h, 4), 'hi': round(m + h, 4), 'half': round(h, 4)}
    return clamp(out, bounds)


def clamp(c, bounds):
    """把区间截到取值范围内（原地修改并返回）。"""
    if not bounds or not isinstance(c, dict) or c.get('lo') is None:
        return c
    lo, hi = bounds
    if lo is not None and c['lo'] < lo:
        c['lo'], c['clamped'] = lo, True
    if hi is not None and c['hi'] > hi:
        c['hi'], c['clamped'] = hi, True
    return c


def reps_needed(c, rel=REL_MAX, cap=30):
    """要让半宽 ≤ rel × |均值| 大约需要几次重复（按现有标准差估计）；30 次还不够时返回 31。"""
    if not c or c.get('sd') is None or not c.get('mean'):
        return None
    for n in range(max(2, c['n']), cap + 1):
        if t975(n - 1) * c['sd'] / math.sqrt(n) <= rel * abs(c['mean']):
            return n
    return cap + 1


def quality(rows, nrep, hours=None, label=None):
    """实验结果的可信度：重复次数、区间宽度、仿真时长 → 警告和建议的重复次数。rows = [{name, ci: {指标: 区间}}]。"""
    label = label or {k: l for k, l, *_ in KPI_KEYS}
    warns, rec, worst = [], max(nrep, MIN_REPS), None
    if nrep < 2:
        warns.append(_tr('每个方案只跑了 1 次，没有置信区间，看不出差别是不是随机波动。'))
    elif nrep < MIN_REPS:
        warns.append(_tr('每个方案只重复了 {nrep} 次（少于 {MIN_REPS} 次），区间偏宽、结论不稳。', nrep=nrep, MIN_REPS=MIN_REPS))
    for r in rows:
        for k in REL_KEYS:
            c = (r.get('ci') or {}).get(k) or {}
            if c.get('half') is None or not c.get('mean'):
                continue
            rel = c['half'] / abs(c['mean'])
            if rel > REL_MAX:
                rec = max(rec, reps_needed(c) or rec)
                if worst is None or rel > worst[2]:
                    worst = (r.get('name'), k, rel)
    if worst:
        warns.append(_tr('「{v}」的{get}区间半宽达到均值的 {v2:.0f}%（超过 {v3:.0f}%），区间太宽。', v=worst[0], get=label.get(worst[1], worst[1]), v2=worst[2] * 100, v3=REL_MAX * 100))
    if hours is not None and float(hours) < 8:
        warns.append(_tr('每次只仿真 {float:g} 小时，偏短：故障、换型这类偶发事件可能没出现几次，建议至少 24 小时。', float=float(hours)))
    clamped = sorted({label.get(k, k) for r in rows for k, c in (r.get('ci') or {}).items() if (c or {}).get('clamped')})
    if warns:
        warns.append(_tr('建议把重复次数加到 {min} 次', min=min(rec, 30)) + (_tr('（30 次仍不够时再延长仿真时长）') if rec > 30 else '') + _tr('后再下结论。'))
    return {'ok': not warns, 'warnings': warns, 'recommended_reps': min(rec, 30) if warns else nrep, 'reps': nrep,
            'clamped': clamped, 'clamped_note': (_tr('{join}的区间已按取值范围截断（比例在 0~100%，计数和用量不小于 0）。', join=_tr('、').join(clamped)) if clamped else '')}


def opt_quality(reps, hours=None):
    warns = []
    if reps < 2:
        warns.append(_tr('每个候选只跑 1 次，候选之间小的差别可能只是随机波动。挑出推荐方案后，建议用"新建实验"把它和基准各重复 5 次确认。'))
    if hours is not None and float(hours) < 8:
        warns.append(_tr('每个候选只仿真 {float:g} 小时，偏短，建议至少 8 小时。', float=float(hours)))
    return {'ok': not warns, 'warnings': warns, 'recommended_reps': MIN_REPS if reps < 2 else reps, 'reps': reps, 'clamped': [], 'clamped_note': ''}


def annotate(result, hours=None):
    """读出实验结果时调用：旧结果补上区间截断和可信度提示（不改库里的数据）。"""
    if not isinstance(result, dict) or result.get('error'):
        return result
    if result.get('kind') == 'optimize':
        for ev in result.get('evals') or []:
            for k, c in (ev.get('ci') or {}).items():
                clamp(c, BOUNDS.get(k))
        if 'quality' not in result:
            d = result.get('design') or {}
            result['quality'] = opt_quality(d.get('reps', 1), d.get('hours', hours))
        return result
    for r in result.get('rows') or []:
        for k, c in (r.get('ci') or {}).items():
            clamp(c, BOUNDS.get(k))
    if 'quality' not in result:
        result['quality'] = quality(result.get('rows') or [], result.get('reps') or 1, hours)
    return result


def expand_factors(factors, include_base=True, limit=64):
    """方案表：参数 × 水平 → 全因子组合。factor = {label, type: param|buffer|add|crew|setpoint, station/key/name/template/role/tag, levels: [...]}"""
    fs = [f for f in factors or [] if f.get('levels')]
    if not fs:
        return []
    combos = [[]]
    for f in fs:
        combos = [c + [(f, lv)] for c in combos for lv in f['levels']]
    if len(combos) > limit:
        raise ValueError(_tr('组合数 {len} 超过上限 {limit}，请减少水平数', len=len(combos), limit=limit))
    out = [{'name': _tr('基准（当前方案）'), 'changes': []}] if include_base else []
    for c in combos:
        changes, names = [], []
        for f, lv in c:
            t = f.get('type', 'param')
            lab = f.get('label') or (f"{f.get('station')}.{f.get('key')}" if t == 'param' else f.get('name') or f.get('template') or f.get('role') or t)
            names.append(f'{lab}={lv}')
            if t == 'param':
                changes.append({'type': 'param', 'station': f['station'], 'key': f['key'], 'value': lv})
            elif t == 'setpoint':
                changes.append({'type': 'setpoint', 'station': f['station'], 'tag': f['tag'], 'value': lv})
            elif t == 'buffer':
                changes.append({'type': 'buffer', 'name': f['name'], 'value': int(float(lv))})
            elif t == 'add':
                if int(float(lv)) > 0:
                    changes.append({'type': 'add', 'template': f['template'], 'count': int(float(lv))})
            elif t == 'crew':
                changes.append({'type': 'crew', 'role': f['role'], 'value': int(float(lv))})
        out.append({'name': ' × '.join(names), 'changes': changes, 'levels': {(f.get('label') or f.get('key') or f.get('name') or f.get('template') or f.get('role')): lv for f, lv in c}})
    return out


async def run_experiment(eid, cfg, hours, reps, variants, seed0=42, warmup_h=None, resolve=None):
    """resolve(n) → 模型版本 n 的模型（方案里有 version 改动时用）。"""
    loop = asyncio.get_running_loop()
    jobs = []
    try:
        vcfgs = [variant_cfg(cfg, v.get('changes', []), resolve) for v in variants]
    except Exception as ex:
        store.x("update experiments set status='failed', result=? where id=? ", (json.dumps({'error': str(ex)}, ensure_ascii=False), eid))
        return
    for vi, v in enumerate(variants):
        c, ch = vcfgs[vi]
        for rep in range(reps):
            jobs.append((vi, rep, loop.run_in_executor(pool(), run_one, c, hours, seed0 + rep * 1000, ch, warmup_h)))
    total, done = len(jobs), 0
    raw = [[None] * reps for _ in variants]
    store.x("update experiments set status='running', progress=0 where id=?", (eid,))
    try:
        for vi, rep, fut in jobs:
            raw[vi][rep] = await fut
            done += 1
            store.x('update experiments set progress=? where id=?', (round(done / total, 3), eid))
        result = compare(variants, raw, hours)
        result['design'] = {'seed0': seed0, 'seeds': [seed0 + r * 1000 for r in range(reps)], 'warmup_h': warmup_h, 'crn': True, 'hours': hours}
        store.x("update experiments set status='done', progress=1, result=?, finished=? where id=?",
                (json.dumps(result, ensure_ascii=False), store.now(), eid))
    except Exception as ex:
        store.x("update experiments set status='failed', result=? where id=? ", (json.dumps({'error': str(ex)}, ensure_ascii=False), eid))


def _bn_mode(reps):
    """各次重复里最常出现的瓶颈判断（并列瓶颈整组算一种）→ (名称, 次数)。"""
    cnt = {}
    for r in reps:
        b = (r or {}).get('bottleneck') or []
        if not b:
            continue
        key = (_tr('并列 ') + _tr('、').join(x['name'] for x in b if x.get('tie'))) if r.get('bottleneck_tie') else b[0]['name']
        cnt[key] = cnt.get(key, 0) + 1
    if not cnt:
        return None, 0
    k = max(cnt, key=lambda x: (cnt[x], x))
    return k, cnt[k]


def compare(variants, raw, hours=None):
    rows = []
    for v, reps in zip(variants, raw):
        avg, cis = {}, {}
        for k, *_ in KPI_KEYS:
            c = ci([r.get(k) for r in reps if r is not None], BOUNDS.get(k))
            cis[k] = c
            avg[k] = c['mean']
        bm, bn_n = _bn_mode(reps)
        rows.append({'name': v['name'], 'changes': v.get('changes', []), 'levels': v.get('levels'), 'kpi': avg, 'ci': cis, 'reps': reps,
                     'bottleneck': reps[0]['bottleneck'], 'bottleneck_mode': bm, 'bottleneck_mode_n': bn_n})
    base = rows[0]
    for r in rows:
        r['delta'] = {k: (round((r['kpi'][k] - base['kpi'][k]) / base['kpi'][k], 4) if base['kpi'].get(k) and r['kpi'].get(k) is not None else None)
                      for k, *_ in KPI_KEYS}
        # 与基准的配对差（同一个种子 = 同一组随机数，差值的区间比各自区间窄得多）
        d = {}
        for k, *_ in KPI_KEYS:
            pairs = [(a.get(k), b.get(k)) for a, b in zip(r['reps'], base['reps']) if a and b and a.get(k) is not None and b.get(k) is not None]
            c = ci([a - b for a, b in pairs])
            c['significant'] = bool(c['lo'] is not None and (c['lo'] > 0 or c['hi'] < 0))
            d[k] = c
        r['diff'] = d
    best = max(rows, key=lambda r: (r['kpi']['good_per_h'] or 0) - 50 * (r['kpi']['scrap_rate'] or 0))
    text = []
    nrep = len(raw[0]) if raw else 0
    for r in rows[1:]:
        dl = r['delta']
        parts = []
        for k, label, unit, sign in KPI_KEYS:
            if dl.get(k) is not None and abs(dl[k]) >= 0.02:
                sig = r['diff'][k].get('significant')
                tag = '' if nrep < 2 else (_tr('（显著）') if sig else _tr('（不显著）'))
                parts.append(f"{label}{_tr('提高') if dl[k] > 0 else _tr('降低')} {abs(dl[k]) * 100:.0f}%{tag}")
        b = r.get('bottleneck_mode') or '—'
        bt = _tr('瓶颈仍是 {b}', b=b) if b == base.get('bottleneck_mode') else _tr('瓶颈变为 {b}', b=b)
        if nrep > 1 and r.get('bottleneck_mode_n', nrep) < nrep:
            bt += _tr('（{bottleneck_mode_n}/{nrep} 次重复如此）', bottleneck_mode_n=r['bottleneck_mode_n'], nrep=nrep)
        text.append(_tr('「{name}」相比基准：', name=r['name']) + (_tr('，').join(parts) or _tr('各项指标变化都在 2% 以内')) + _tr('；{bt}。', bt=bt))
    if nrep >= 2:
        text.append(_tr('每个方案重复 {nrep} 次（各次用不同随机种子，方案之间用同一组种子），区间为 95% 置信区间；"显著"指与基准的配对差的区间不含 0。', nrep=nrep))
    q = quality(rows, nrep, hours)
    text += q['warnings']
    if q['clamped_note']:
        text.append(q['clamped_note'])
    text.append(_tr('综合产出和质量，推荐方案：「{name}」', name=best['name']) + (_tr('（重复次数还不够，先作参考）。') if not q['ok'] else _tr('。')))
    return {'kpis': [{'key': k, 'label': l, 'unit': u, 'better': s} for k, l, u, s in KPI_KEYS], 'rows': rows, 'text': text, 'best': best['name'],
            'reps': nrep, 'quality': q}


# ---------------- 优化 ----------------
def _levels(p):
    t = p.get('kind', p.get('type', 'param'))
    if p.get('levels'):
        return list(p['levels'])
    lo, hi = float(p.get('lo', 0)), float(p.get('hi', 1))
    step = float(p.get('step') or (1 if t in ('buffer', 'add', 'crew') else (hi - lo) / 4 or 1))
    vals = []
    v = lo
    while v <= hi + step * 1e-6 and len(vals) < 200:
        vals.append(int(round(v)) if t in ('buffer', 'add', 'crew') or (float(v).is_integer() and float(step).is_integer() and float(lo).is_integer()) else round(v, 6))
        v += step
    return vals


def _changes_of(params, genome):
    ch, vals = [], {}
    for p, gi in zip(params, genome):
        lv = p['_levels'][gi]
        t = p.get('kind', p.get('type', 'param'))
        vals[p['_label']] = lv
        if t == 'param':
            ch.append({'type': 'param', 'station': p['station'], 'key': p['key'], 'value': lv})
        elif t == 'buffer':
            ch.append({'type': 'buffer', 'name': p['name'], 'value': int(lv)})
        elif t == 'add':
            if int(lv) > 0:
                ch.append({'type': 'add', 'template': p['template'], 'count': int(lv)})
        elif t == 'crew':
            ch.append({'type': 'crew', 'role': p['role'], 'value': int(lv)})
        elif t == 'setpoint':
            ch.append({'type': 'setpoint', 'station': p['station'], 'tag': p['tag'], 'value': lv})
    return ch, vals


def _dominates(a, b):
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def pareto(points):
    """points: [(编号, 目标向量（都已转成越大越好）)] → 非支配的编号。"""
    return [i for i, v in points if not any(_dominates(w, v) for j, w in points if j != i)]


def _ranks(points):
    """非支配排序：返回 {编号: 层号}（0 = 帕累托前沿）。"""
    left = dict(points)
    rank, r = {}, 0
    while left:
        front = pareto(list(left.items()))
        for i in front:
            rank[i] = r
            left.pop(i)
        r += 1
    return rank


def _ok(kpi, cons):
    for c in cons or []:
        v = kpi.get(c['key'])
        if v is None:
            return False
        if c.get('op', '<=') == '<=' and v > float(c['value']) + 1e-12:
            return False
        if c.get('op') == '>=' and v < float(c['value']) - 1e-12:
            return False
    return True


async def run_optimization(eid, cfg, spec):
    """遗传算法（非支配排序 + 锦标赛 + 均匀交叉 + 变异）或随机搜索；每个候选按 reps 个公共种子评估取平均。"""
    import random
    loop = asyncio.get_running_loop()
    params = [dict(p) for p in spec.get('params') or []]
    for p in params:
        p['_levels'] = _levels(p)
        t = p.get('kind', p.get('type', 'param'))
        p['_label'] = p.get('label') or (f"{p.get('station')}.{p.get('key')}" if t in ('param', 'setpoint') else p.get('name') or p.get('template') or p.get('role') or t)
    objs = spec.get('objectives') or [{'key': 'good_per_h', 'sense': 'max'}]
    cons = spec.get('constraints') or []
    hours, reps = float(spec.get('hours', 8)), int(spec.get('reps', 1))
    budget = int(spec.get('budget', 24))
    method = spec.get('method', 'ga')
    pop_n = max(4, int(spec.get('pop', 8)))
    seed0 = int(spec.get('seed', 42))
    warm = spec.get('warmup_h')
    rnd = random.Random(int(spec.get('search_seed', 7)))
    space = 1
    for p in params:
        space *= len(p['_levels'])
    budget = min(budget, space)
    evals, cache = [], {}
    best_hist = []

    def vec(kpi):
        return [(kpi.get(o['key']) or 0) * (1 if o.get('sense', 'max') == 'max' else -1) for o in objs]

    async def evaluate(genomes):
        new = [g for g in dict.fromkeys(genomes) if g not in cache][:max(0, budget - len(evals))]
        futs = []
        for g in new:
            ch, _ = _changes_of(params, g)
            futs.append([loop.run_in_executor(pool(), run_one, cfg, hours, seed0 + r * 1000, ch, warm) for r in range(reps)])
        for g, fs in zip(new, futs):
            res = [await f for f in fs]
            ch, vals = _changes_of(params, g)
            kpi = {k: ci([x.get(k) for x in res])['mean'] for k, *_ in KPI_KEYS}
            ev = {'i': len(evals), 'genome': list(g), 'values': vals, 'changes': ch, 'kpi': kpi,
                  'ci': {o['key']: ci([x.get(o['key']) for x in res], BOUNDS.get(o['key'])) for o in objs}, 'feasible': _ok(kpi, cons),
                  'bottleneck': res[0]['bottleneck'][:1]}
            cache[g] = ev
            evals.append(ev)
            fe = [e for e in evals if e['feasible']]
            b = max(fe, key=lambda e: vec(e['kpi'])[0]) if fe else None
            best_hist.append({'n': len(evals), 'best': b['kpi'].get(objs[0]['key']) if b else None})
            store.x('update experiments set progress=? where id=?', (round(len(evals) / max(1, budget), 3), eid))

    def rand_genome():
        return tuple(rnd.randrange(len(p['_levels'])) for p in params)

    def fitness_order(pop):
        fe = [(cache[g]['i'], vec(cache[g]['kpi'])) for g in pop if cache[g]['feasible']]
        rk = _ranks(fe) if fe else {}
        return sorted(pop, key=lambda g: (0 if cache[g]['feasible'] else 1, rk.get(cache[g]['i'], 99), -vec(cache[g]['kpi'])[0]))

    store.x("update experiments set status='running', progress=0 where id=?", (eid,))
    try:
        if not params:
            raise ValueError(_tr('没有选择可调参数'))
        if method == 'random' or space <= pop_n:
            gs = []
            tries = 0
            while len(set(gs)) < budget and tries < budget * 50:
                gs.append(rand_genome())
                tries += 1
            await evaluate(gs)
        else:
            pop = []
            tries = 0
            while len(set(pop)) < pop_n and tries < 500:
                pop.append(rand_genome())
                tries += 1
            pop = list(dict.fromkeys(pop))
            await evaluate(pop)
            stall = 0
            while len(evals) < budget and stall < 6:
                ranked = fitness_order([g for g in pop if g in cache])
                kids = []
                tries = 0
                while len(kids) < pop_n and tries < pop_n * 30:
                    tries += 1
                    a = min(rnd.sample(ranked, min(2, len(ranked))), key=ranked.index)
                    b = min(rnd.sample(ranked, min(2, len(ranked))), key=ranked.index)
                    child = [x if rnd.random() < 0.5 else y for x, y in zip(a, b)]
                    for i, p in enumerate(params):
                        if rnd.random() < max(0.2, 1 / len(params)):
                            child[i] = max(0, min(len(p['_levels']) - 1, child[i] + rnd.choice((-1, 1)) * rnd.choice((1, 1, 2))))
                    child = tuple(child)
                    if child not in cache and child not in kids:
                        kids.append(child)
                if not kids:
                    stall += 1
                    kids = [rand_genome() for _ in range(2)]
                n0 = len(evals)
                await evaluate(kids)
                if len(evals) == n0:
                    stall += 1
                pop = fitness_order(list(dict.fromkeys(ranked + [k for k in kids if k in cache])))[:pop_n]
        fe = [e for e in evals if e['feasible']]
        front = pareto([(e['i'], vec(e['kpi'])) for e in fe])
        for e in evals:
            e['front'] = e['i'] in front
        if fe:
            if len(objs) == 1:
                best = max(fe, key=lambda e: vec(e['kpi'])[0])
            else:            # 多目标：前沿上按归一化加权和挑一个推荐解
                fr = [e for e in fe if e['front']]
                vs = [vec(e['kpi']) for e in fr]
                lo = [min(v[i] for v in vs) for i in range(len(objs))]
                hi = [max(v[i] for v in vs) for i in range(len(objs))]
                w = [float(o.get('weight', 1)) for o in objs]
                best = max(fr, key=lambda e: sum(w[i] * ((vec(e['kpi'])[i] - lo[i]) / (hi[i] - lo[i]) if hi[i] > lo[i] else 1) for i in range(len(objs))))
        else:
            best = None
        meta = {k: (l, u) for k, l, u, _ in KPI_KEYS}
        text = [_tr('共评估 {len} 个候选（搜索空间 {space} 个组合，{v}），每个候选重复 {reps} 次、仿真 {hours:g} 小时；满足约束的 {len2} 个，帕累托前沿上 {len3} 个。', len=len(evals), space=space, v=_tr('遗传算法') if method != 'random' and space > pop_n else _tr('随机搜索'), reps=reps, hours=hours, len2=len(fe), len3=len(front))]
        if best:
            text.append(_tr('推荐：') + _tr('，').join(f'{k}={v}' for k, v in best['values'].items()) + _tr('；') +
                        _tr('，').join(f"{meta[o['key']][0]} {best['kpi'].get(o['key'])}{meta[o['key']][1]}" for o in objs if o['key'] in meta))
        else:
            text.append(_tr('没有候选满足约束，请放宽约束或扩大参数范围。'))
        q = opt_quality(reps, hours)
        text += q['warnings']
        result = {'kind': 'optimize', 'quality': q, 'params': [{k: v for k, v in p.items() if not k.startswith('_')} | {'levels': p['_levels'], 'label': p['_label']} for p in params],
                  'objectives': objs, 'constraints': cons, 'method': method, 'space': space, 'evals': evals, 'front': front,
                  'best': best, 'history': best_hist, 'text': text, 'kpis': [{'key': k, 'label': l, 'unit': u, 'better': s} for k, l, u, s in KPI_KEYS],
                  'design': {'seed0': seed0, 'seeds': [seed0 + r * 1000 for r in range(reps)], 'hours': hours, 'reps': reps, 'crn': True}}
        store.x("update experiments set status='done', progress=1, result=?, finished=? where id=?",
                (json.dumps(result, ensure_ascii=False), store.now(), eid))
    except Exception as ex:
        store.x("update experiments set status='failed', result=? where id=? ", (json.dumps({'error': str(ex)}, ensure_ascii=False), eid))


# ---------------- 导出 ----------------
def export_rows(result):
    """实验结果 → 表格行（方案 × 指标：均值、标准差、95% 区间、与基准差及显著性）。"""
    meta = {k['key']: k for k in result.get('kpis') or []}
    head = [_tr('方案'), _tr('改动'), _tr('指标'), _tr('单位'), _tr('均值'), _tr('标准差'), _tr('95%下限'), _tr('95%上限'), _tr('次数'), _tr('与基准差'), _tr('差的95%下限'), _tr('差的95%上限'), _tr('显著')]
    out = []
    if result.get('kind') == 'optimize':
        keys = [k['key'] for k in result['kpis']]
        head = [_tr('序号'), _tr('前沿'), _tr('满足约束')] + [label(p['label']) for p in result['params']] + [label(meta[k]['label']) for k in keys]
        for e in result['evals']:
            out.append([e['i'] + 1, _tr('是') if e.get('front') else '', _tr('是') if e['feasible'] else _tr('否')] + [e['values'].get(p['label']) for p in result['params']]
                       + [e['kpi'].get(k) for k in keys])
        return head, out
    for r in result.get('rows') or []:
        chg = _tr('；').join(_chg_text(c) for c in r.get('changes') or []) or _tr('当前配置')
        for k, m in meta.items():
            c = (r.get('ci') or {}).get(k) or {'mean': r['kpi'].get(k)}
            d = (r.get('diff') or {}).get(k) or {}
            out.append([label(r['name']), chg, label(m['label']), label(m['unit']), c.get('mean'), c.get('sd'), c.get('lo'), c.get('hi'), c.get('n'),
                        d.get('mean'), d.get('lo'), d.get('hi'), (_tr('是') if d.get('significant') else _tr('否')) if d.get('lo') is not None else ''])
    return head, out


WEEK = '一二三四五六日'
WEEKDAYS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')


def _wd(i):
    return _tr(WEEKDAYS[i - 1])


def plan_text(c):
    """plan 改动 → 文字，如"班次 早班 07:00–15:00、中班 15:00–23:00；工作日 周一至周六"。"""
    if c.get('label'):
        return c['label']
    parts = []
    if c.get('shifts') is not None:
        parts.append(_tr('班次 ') + (_tr('、').join(f"{x.get('name', '')} {x.get('start')}–{x.get('end')}" for x in c['shifts']) or _tr('连续生产')))
    if c.get('workdays') is not None:
        w = sorted(int(x) for x in c['workdays'])
        cont = bool(w) and w == list(range(w[0], w[-1] + 1))
        parts.append(_tr('工作日 ') + (_tr('{a}至{b}', a=_wd(w[0]), b=_wd(w[-1])) if cont else _tr('、').join(_wd(x) for x in w)))
    if c.get('breaks') is not None:
        parts.append(_tr('休息 ') + (_tr('、').join(f"{x.get('start')}–{x.get('end')}" for x in c['breaks']) or _tr('无')))
    if c.get('orders') is not None:
        parts.append(_tr('订单 {len} 个', len=len(c['orders'])))
    return _tr('；').join(parts) or _tr('换生产计划')


def _chg_text(c):
    t = c.get('type')
    if t == 'version':
        return _tr('当前草稿（未应用）') if c.get('n') == 'draft' else _tr('模型版本 #{get}', get=c.get('n'))
    if t == 'plan':
        return plan_text(c)
    return (_tr('按 {get} 加 {get2} 台', get=c.get('template'), get2=c.get('count')) if t == 'add' else _tr('去掉 {get}', get=c.get('station')) if t == 'remove'
            else f"{c.get('station')}.{c.get('key')}={c.get('value')}" if t == 'param' else f"{c.get('station')} {c.get('tag')}={c.get('value')}" if t == 'setpoint'
            else _tr('{get} {get2} 人', get=c.get('role'), get2=c.get('value')) if t == 'crew' else _tr('缓存 {get}={get2}', get=c.get('name'), get2=c.get('value')))


def export_csv(result):
    import csv
    import io
    head, rows = export_rows(result)
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(head)
    w.writerows(rows)
    if result.get('kind') != 'optimize':
        w.writerow([])
        w.writerow([_tr('方案'), _tr('重复'), _tr('种子')] + [k['label'] for k in result['kpis']])
        for r in result.get('rows') or []:
            for i, rep in enumerate(r.get('reps') or []):
                w.writerow([r['name'], i + 1, rep.get('seed', '')] + [rep.get(k['key']) for k in result['kpis']])
    return '﻿' + s.getvalue()


def export_xlsx(result, title='实验'):
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = _tr('结论')
    ws.append([title])
    ws['A1'].font = Font(bold=True, size=13)
    for t in result.get('text') or []:
        ws.append([t])
    ws.column_dimensions['A'].width = 120

    def sheet(name, head, rows):
        s = wb.create_sheet(name)
        s.append(head)
        for c in s[1]:
            c.font, c.fill = Font(bold=True), PatternFill('solid', fgColor='F2C94C')
        for r in rows:
            s.append(r)
        for i in range(len(head)):
            s.column_dimensions[chr(65 + i) if i < 26 else 'A' + chr(65 + i - 26)].width = 14
        s.freeze_panes = 'A2'
    head, rows = export_rows(result)
    sheet(_tr('候选') if result.get('kind') == 'optimize' else _tr('方案对比'), head, rows)
    if result.get('kind') != 'optimize':
        reps = []
        for r in result.get('rows') or []:
            for i, rep in enumerate(r.get('reps') or []):
                reps.append([r['name'], i + 1, rep.get('seed', '')] + [rep.get(k['key']) for k in result['kpis']])
        sheet(_tr('每次重复'), [_tr('方案'), _tr('重复'), _tr('种子')] + [k['label'] for k in result['kpis']], reps)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
