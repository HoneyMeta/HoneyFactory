"""统计分析：时间构成（带预热截断）、产出/在制品/周期/OEE、桑基图、甘特图（按设备 / 按订单 / 按零件）、能耗与电费碳排。

全部基于仿真内核记下的数据：class_log（设备时间类别变化）、wip_log（每分钟在制品）、energy_q（每 15 分钟全厂电量）、
hourly（每小时累计快照）、零件档案的履历。所有函数既能用于运行中的工厂，也能用于实验/推演里的副本。
"""
from .i18n import _tr, label, variants
import heapq
import math
from collections import defaultdict
from datetime import datetime, timedelta

from .core import CLS_LABEL

CLS_ORDER = ['run', 'setup', 'starved', 'blocked', 'wait_plc', 'failed', 'idle', 'planned', 'offshift', 'disabled']
CLS_COLOR = {'run': '#2e9d5b', 'setup': '#3b82c4', 'starved': '#e0a630', 'blocked': '#e07a20', 'failed': '#c83a3a', 'idle': '#b9c0c8',
             'planned': '#7a6cc4', 'offshift': '#dcdfe4', 'disabled': '#6b7680', 'wait_plc': '#f0a35e'}
PASSIVE = ('buffer', 'operators', 'transporter', 'crew', 'agv', 'sink', 'storage', 'source', 'submodel', 'cooling',
           'gateway', 'switch', 'scada', 'mes', 'plc', 'hmi')        # 4.3：通讯/控制设备不参与产能、瓶颈统计


def classes():
    return [{'key': k, 'label': CLS_LABEL[k], 'color': CLS_COLOR[k]} for k in CLS_ORDER]


def warmup_end(plant):
    try:
        return float(plant.cfg.get('plant', {}).get('warmup_h', 0) or 0) * 3600
    except (TypeError, ValueError):
        return 0.0


def window(plant, hours=None, warmup=True, t0=None, t1=None, align=True):
    """统计区间：最近 hours 小时（0/None = 全部），预热期截掉。返回 (t0, t1) 仿真秒。

    align=True 时起点对齐到整点（向后取整）：产出、报废、用电这些累计量按整点快照相减，起点对齐后各处算出来的数完全一致。
    报告、报表、分析浮窗、实验都用这一个函数定区间。"""
    t1 = plant.t if t1 is None else min(float(t1), plant.t)
    if t0 is None:
        t0 = max(0.0, t1 - float(hours) * 3600) if hours else 0.0
    if warmup:
        t0 = max(t0, min(warmup_end(plant), t1))
    if align and t1 > 0:
        if t1 < plant.t - 1:
            t1 = max(3600.0, math.floor(t1 / 3600 + 1e-9) * 3600)
        a = math.ceil(t0 / 3600 - 1e-9) * 3600
        t0 = a if a <= t1 - 1800 else math.floor(t0 / 3600 + 1e-9) * 3600     # 剩不到半小时就往前取整点
        t0 = min(t0, t1)
    return float(t0), float(t1)


def clock(plant, t):
    return (plant.t0 + timedelta(seconds=float(t))).strftime('%Y-%m-%d %H:%M:%S')


def _all(plant):
    return plant.all_stations() if hasattr(plant, 'all_stations') else list(plant.stations.values())


def class_durations(plant, t0, t1):
    """每台设备在 [t0, t1] 内各时间类别的秒数。"""
    by = defaultdict(list)
    for t, sid, c in plant.class_log:
        by[sid].append((t, c))
    out = {}
    for sid, seq in by.items():
        d = defaultdict(float)
        for i, (t, c) in enumerate(seq):
            a = max(t, t0)
            b = min(seq[i + 1][0] if i + 1 < len(seq) else t1, t1)
            if b > a:
                d[c] += b - a
        out[sid] = dict(d)
    return out


def _top(plant, sid):
    """子模型内部块 → 最外层子模型块编号。"""
    par = getattr(plant, 'sub_parent', {})
    seen = 0
    while sid in par and seen < 10:
        sid = par[sid]
        seen += 1
    return sid


# ---------------- 统计 ----------------
def station_stats(plant, t0, t1, dur=None):
    """每台设备在 [t0, t1] 内的时间构成、占比和本区间 OEE（可用率 × 性能 × 质量；计划停机和非班次不计入可用时间）。"""
    dur = class_durations(plant, t0, t1) if dur is None else dur
    objs = []
    for st in _all(plant):
        d = dur.get(st.id, {})
        tot = sum(d.values())
        if tot <= 0:
            continue
        avail_base = tot - d.get('planned', 0) - d.get('offshift', 0)
        loss = d.get('failed', 0) + d.get('setup', 0)
        A = 1 - loss / avail_base if avail_base > 0 else None
        P = d.get('run', 0) / max(1e-9, avail_base - loss) if avail_base - loss > 0 else None
        q = getattr(st, 'quality_rate', None)
        Q = q() if callable(q) else 1.0
        objs.append({'id': st.id, 'name': st.name, 'kind': st.kind, 'group': getattr(st, 'group', None) or st.id,
                     'parent': getattr(plant, 'sub_parent', {}).get(st.id),
                     'passive': st.kind in PASSIVE, 'seconds': {k: round(v, 1) for k, v in d.items()},
                     'share': {k: round(v / tot, 4) for k, v in d.items()}, 'count': getattr(st, 'count', None),
                     'oee': round(A * P * Q, 4) if A is not None and P is not None else None,
                     'A': round(A, 4) if A is not None else None, 'P': round(min(1.0, P), 4) if P is not None else None, 'Q': round(Q, 4)})
    return objs


def stats(plant, t0, t1, s=None):
    """时间构成 + 全厂指标。全厂指标直接取 history.summary 的同一份结果（同区间、同口径），报告、报表、分析浮窗看到的数一样。"""
    from .history import summary
    s = s if s is not None else summary(plant, t0, t1)
    objs = s['objects']
    lead = s.get('lead') or {}
    act = [o for o in objs if not o['passive'] and o['oee'] is not None]
    return {'t0': s['t0'], 't1': s['t1'], 'from': s['from'], 'to': s['to'], 'hours': s['hours'],
            'warmup_h': round(warmup_end(plant) / 3600, 2), 'classes': classes(), 'objects': objs,
            'plant': {'good': s['good'], 'castings': s['castings'], 'scrap': s['scrap'], 'scrap_rate': s['scrap_rate'], 'good_per_h': s['good_per_h'],
                      'wip_avg': s['wip_avg'], 'wip_max': s.get('wip_max'),
                      'lead_mean_h': lead.get('mean_h'), 'lead_p50_h': lead.get('p50_h'), 'lead_p90_h': lead.get('p90_h'), 'lead_n': lead.get('n', 0),
                      'oee_avg': round(sum(o['oee'] for o in act) / len(act), 4) if act else None,
                      'bottleneck': s['bottleneck'][:3]},
            'bottleneck': {k: v for k, v in (s.get('bottleneck_analysis') or {}).items() if k != 'by_station'}}


# ---------------- 瓶颈：活跃期法（shifting bottleneck）+ 堵料/缺料旁证 ----------------
ACTIVE_CLS = ('run', 'setup', 'failed')          # 活跃：在加工、换型、故障修理；等待（缺料、堵料、待机）不算
TIE_GAP = 0.05                                   # 前两名瓶颈时间占比相差不到 5 个百分点 → 并列瓶颈
EXCLUDE_KIND = {
    'furnace': '连续保温/熔炼，运行时间里含保温，不能说明它在限制产出',
    'sand': '砂处理按造型线需要连续循环供砂',
    'cooling': '冷却线：铸型停留时间由工艺定死，不受设备能力限制',
    'conveyor': '输送线：零件按固定时间通过，"运行"只表示线上有料',
    'cell': '控制单元（PLC 输送/分拣段）：零件按节拍通过，"运行"只表示线上有料',
}
PASSIVE_REASON = {'gateway': '网关', 'switch': '交换机', 'scada': 'SCADA', 'mes': 'MES', 'plc': 'PLC', 'hmi': 'HMI', 'buffer': '缓存', 'storage': '仓库', 'warehouse': '立体仓库', 'source': '投料口', 'sink': '出口', 'crew': '班组', 'operators': '人员池',
                  'agv': 'AGV', 'transporter': '搬运资源', 'submodel': '子模型（内部设备单独参与判断）', 'split': '分流点',
                  'cooling': '冷却线（停留时间由工艺定死）'}
KIND_CN = {'furnace': '中频炉', 'treatment': '球化站', 'sand': '砂处理', 'molding': '造型线', 'cooling': '冷却线', 'shotblast': '抛丸机', 'cnc': '加工中心',
           'deburr': '去毛刺', 'inspection': '内窥检测', 'warehouse': '立库', 'receiving': '来料', 'processor': '加工', 'inspect': '检验', 'assembly': '装配'}


def _merge(iv):
    out = []
    for a, b in sorted(iv):
        if b <= a:
            continue
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _length(iv):
    return sum(b - a for a, b in iv)


def _intersect(x, y):
    i = j = 0
    out = []
    while i < len(x) and j < len(y):
        a, b = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        if b > a:
            out.append([a, b])
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return out


def active_intervals(seq, t0, t1):
    """[(t, 类别)]（按时间）→ [t0, t1] 内合并后的活跃区间。"""
    out = []
    for i, (t, c) in enumerate(seq):
        a = max(t, t0)
        b = min(seq[i + 1][0] if i + 1 < len(seq) else t1, t1)
        if b <= a or c not in ACTIVE_CLS:
            continue
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = b
        else:
            out.append([a, b])
    return out


def shifting_bottleneck(ents):
    """活跃期法（Roser 等）。ents = {对象: [[开始, 结束], ...] 活跃区间}。
    每一时刻，当前活跃期最长的对象是"瞬时瓶颈"；相邻两个瓶颈的活跃期重叠的那段是"转移期"，两边都记。
    返回 {对象: {'momentary', 'sole', 'shifting'}}（秒）和瞬时瓶颈时间线 [(对象, 开始, 结束)]。"""
    ivs = [(a, b, k) for k, L in ents.items() for a, b in L if b > a]
    out = {k: {'momentary': 0.0, 'sole': 0.0, 'shifting': 0.0} for k in ents}
    if not ivs:
        return out, []
    cuts = sorted({x for a, b, _ in ivs for x in (a, b)})
    order = sorted(range(len(ivs)), key=lambda i: ivs[i][0])
    heap, p, mom = [], 0, []
    for ci in range(len(cuts) - 1):
        a, b = cuts[ci], cuts[ci + 1]
        while p < len(order) and ivs[order[p]][0] <= a:
            i = order[p]
            heapq.heappush(heap, (-(ivs[i][1] - ivs[i][0]), ivs[i][0], i))
            p += 1
        while heap and ivs[heap[0][2]][1] <= a:
            heapq.heappop(heap)
        if not heap:
            continue
        i = heap[0][2]
        if mom and mom[-1][1] == i and abs(mom[-1][3] - a) < 1e-6:
            mom[-1][3] = b
        else:
            mom.append([ivs[i][2], i, a, b])
    mom_iv, shift_iv = defaultdict(list), defaultdict(list)
    for k, i, a, b in mom:
        out[k]['momentary'] += b - a
        mom_iv[k].append([a, b])
    for x, y in zip(mom, mom[1:]):
        if x[0] == y[0] or abs(x[3] - y[2]) > 1e-6:
            continue                       # 同一个对象，或中间有一段谁都不活跃：不算转移
        sa, ea, _ = ivs[x[1]]
        sb, eb, _ = ivs[y[1]]
        a, b = max(sa, sb), min(ea, eb)
        if b > a:
            shift_iv[x[0]].append([a, b])
            shift_iv[y[0]].append([a, b])
    for k in out:
        sh = _merge(shift_iv.get(k, []))
        out[k]['shifting'] = _length(sh)
        out[k]['sole'] = max(0.0, out[k]['momentary'] - _length(_intersect(_merge(mom_iv.get(k, [])), sh)))
    return out, [(k, a, b) for k, _, a, b in mom]


def _graph(plant):
    """块级物料连线 → (上游表, 下游表, {(块, 'in'|'out'): [缓存名]})。旧版模型（没有 blocks）返回空表。"""
    cfg = getattr(plant, 'cfg', {}) or {}
    blocks = {b['id']: b for b in cfg.get('blocks') or []}
    up, down, bufs = defaultdict(set), defaultdict(set), defaultdict(list)
    for l in cfg.get('links') or []:
        if l.get('kind', 'material') != 'material':
            continue
        A, B = blocks.get(l.get('from')), blocks.get(l.get('to'))
        if A is None or B is None or l.get('cond') == '返修':        # 返修回流不算上下游
            continue
        down[A['id']].add(B['id'])
        up[B['id']].add(A['id'])
        via = l.get('via')
        if A['type'] == 'buffer':
            bufs[(B['id'], 'in')].append(A['id'])
        else:
            bufs[(B['id'], 'in')].append(f"{l['id']}@b" if via else l['id'])
        if B['type'] == 'buffer':
            bufs[(A['id'], 'out')].append(B['id'])
        else:
            bufs[(A['id'], 'out')].append(f"{l['id']}@a" if via else l['id'])
    return up, down, bufs


def _neighbors(plant, ids, adj, cand):
    """从 ids 沿 adj 走，穿过缓存等被动块，碰到候选设备就停。"""
    seen, out, stack = set(ids), set(), list(ids)
    while stack:
        x = stack.pop()
        for y in adj.get(x, ()):
            if y in seen:
                continue
            seen.add(y)
            if y in cand:
                out.add(y)
                continue
            st = plant.find(y) if hasattr(plant, 'find') else None
            if st is None or st.kind in PASSIVE or st.kind in PASSIVE_REASON:
                stack.append(y)
    return out


def _buffer_fill(plant, names, t0, t1):
    """缓存在区间内的平均占用率（整点快照的平均；区间内没有快照时用当前值）。"""
    names = [n for n in dict.fromkeys(names) if n in plant.buffers and plant.buffers[n].capacity]
    if not names:
        return None
    snaps = [h for h in plant.hourly if t0 < h['t'] <= t1 and h.get('wip') is not None]
    vals = []
    for n in names:
        cap = float(plant.buffers[n].capacity)
        seq = [h['wip'].get(n, 0) for h in snaps] or [len(plant.buffers[n])]
        vals.append(min(1.0, sum(seq) / len(seq) / cap))
    return round(sum(vals) / len(vals), 3)


def bottleneck(plant, t0, t1, objs=None, timeline=False):
    """瓶颈分析：活跃期法给出每台设备 / 每个工位组的"瓶颈时间占比"（独占 + 交替），再用上下游的堵料/等料和缓存占用做旁证。
    同组设备（参数 group 相同，如 6 台加工中心）合成一个对象：整组都在忙时才算这一组活跃。"""
    objs = station_stats(plant, t0, t1) if objs is None else objs
    by_obj = {o['id']: o for o in objs}
    excluded, groups, passive_n = [], defaultdict(list), defaultdict(list)
    for o in objs:
        k = o['kind']
        if k in PASSIVE or k in PASSIVE_REASON:
            passive_n[PASSIVE_REASON.get(k, '辅助对象')].append(o['name'])
            continue
        if k in EXCLUDE_KIND:
            excluded.append({'id': o['id'], 'name': o['name'], 'kind': k, 'reason': EXCLUDE_KIND[k]})
            continue
        sh = o['share']
        if sh.get('disabled', 0) + sh.get('offshift', 0) + sh.get('planned', 0) >= 0.999:
            excluded.append({'id': o['id'], 'name': o['name'], 'kind': k, 'reason': _tr('统计区间内一直停用或不在班次')})
            continue
        groups[o.get('group') or o['id']].append(o)
    by = defaultdict(list)
    for t, sid, c in plant.class_log:
        by[sid].append((t, c))
    ents = {}
    for g, members in groups.items():
        L = None
        for o in members:
            iv = active_intervals(by.get(o['id'], []), t0, t1)
            L = iv if L is None else _intersect(L, iv)
        ents[g] = L or []
    res, tl = shifting_bottleneck(ents)
    prod = _length(_merge([list(iv) for L in ents.values() for iv in L]))       # 至少有一个对象在活跃的时间
    den = prod or 1.0
    up, down, bufs = _graph(plant)
    cand = {o['id'] for ms in groups.values() for o in ms}
    items = []
    for g, members in groups.items():
        ids = [o['id'] for o in members]
        r = res.get(g) or {'sole': 0, 'shifting': 0, 'momentary': 0}
        run = sum(o['share'].get('run', 0) for o in members) / len(members)
        act = sum(sum(o['share'].get(c, 0) for c in ACTIVE_CLS) for o in members) / len(members)
        k0 = members[0]['kind']
        name = members[0]['name'] if len(members) == 1 else f"{label(KIND_CN.get(k0) or members[0]['name'])} ×{len(members)}"
        ev = _evidence(plant, ids, up, down, bufs, cand, by_obj, t0, t1) if (up or down) else None
        items.append({'group': g, 'name': name, 'ids': ids, 'n': len(members), 'kind': k0, 'run': round(run, 4), 'active': round(act, 4),
                      'sole': round(r['sole'] / den, 4), 'shifting': round(r['shifting'] / den, 4),
                      'share': round((r['sole'] + r['shifting']) / den, 4), 'momentary': round(r['momentary'] / den, 4),
                      'evidence': ev, 'evidence_text': _evidence_text(ev) if ev else ''})
    items.sort(key=lambda x: (-x['share'], -x['active'], -x['run'], x['name']))
    for i, it in enumerate(items):
        it['rank'], it['tie'] = i + 1, False
    top = [it for it in items if items[0]['share'] - it['share'] < TIE_GAP] if items and items[0]['share'] > 0 else []
    if len(top) > 1:
        for it in top:
            it['tie'] = True
    gap = round(items[0]['share'] - items[len(top)]['share'], 4) if top and len(items) > len(top) else None
    verdict, conf = _verdict(top, gap)
    by_station = {}
    for it in items:
        for sid in it['ids']:
            by_station[sid] = {'group': it['group'], 'rank': it['rank'], 'share': it['share'], 'tie': it['tie'],
                               'util': by_obj[sid]['share'].get('run', 0), 'bottleneck': it in top}
    for o in objs:
        if o['id'] not in by_station and not o['passive']:
            by_station[o['id']] = {'group': None, 'rank': None, 'share': None, 'tie': False, 'util': o['share'].get('run', 0), 'bottleneck': False}
    excluded += [{'id': None, 'name': _tr('、').join(v[:6]) + (_tr(' 等 {len} 个', len=len(v)) if len(v) > 6 else ''), 'kind': 'passive', 'reason': _tr('{k}，不加工零件', k=k)}
                 for k, v in passive_n.items()]
    return {'method': 'active_period', 'method_label': _tr('活跃期法（shifting bottleneck）+ 堵料/等料旁证'),
            'from': clock(plant, t0)[:16], 'to': clock(plant, t1)[:16], 'hours': round((t1 - t0) / 3600, 2), 'production_h': round(prod / 3600, 2),
            'tie_gap': TIE_GAP, 'items': items, 'top': [it['group'] for it in top], 'tie': len(top) > 1, 'gap': gap,
            'verdict': verdict, 'confidence': conf, 'confidence_label': {'high': _tr('高'), 'medium': _tr('中'), 'low': _tr('低')}[conf],
            'excluded': excluded, 'by_station': by_station,
            **({'timeline': [[k, round(a, 1), round(b, 1)] for k, a, b in tl[-400:]]} if timeline else {}),
            'note': (_tr('瓶颈时间占比 = 该设备（同组设备则整组都在忙时）处在"当前活跃期最长"位置的时间 ÷ 有设备在工作的时间。活跃 = 运行、换型、故障修理；缺料、堵料、待机算等待。独占 = 只有它在限制产出；交替 = 和前后一个瓶颈重叠的转移期，两边都记。前两名相差小于 {v:.0f} 个百分点时写"并列瓶颈"。', v=TIE_GAP * 100))}


def _evidence(plant, ids, up, down, bufs, cand, by_obj, t0, t1):
    u = _neighbors(plant, ids, up, cand) - set(ids)
    dn = _neighbors(plant, ids, down, cand) - set(ids)

    def avg(xs, keys):
        xs = [by_obj[x] for x in xs if x in by_obj]
        return round(sum(sum(o['share'].get(c, 0) for c in keys) for o in xs) / len(xs), 4) if xs else None
    ev = {'up': sorted(by_obj[x]['name'] for x in u if x in by_obj), 'down': sorted(by_obj[x]['name'] for x in dn if x in by_obj),
          'up_blocked': avg(u, ('blocked',)), 'up_waiting': avg(u, ('starved', 'idle')),
          'down_blocked': avg(dn, ('blocked',)), 'down_waiting': avg(dn, ('starved', 'idle')),
          'in_fill': _buffer_fill(plant, [b for i in ids for b in bufs.get((i, 'in'), [])], t0, t1),
          'out_fill': _buffer_fill(plant, [b for i in ids for b in bufs.get((i, 'out'), [])], t0, t1)}
    pro = con = 0
    if ev['in_fill'] is not None:                 # 瓶颈前面的缓存偏满、后面的偏空
        pro += ev['in_fill'] >= 0.6
        con += ev['in_fill'] <= 0.2
    if ev['out_fill'] is not None:
        pro += ev['out_fill'] <= 0.4
        con += ev['out_fill'] >= 0.8
    if ev['up_blocked'] is not None and (ev['up_blocked'] or ev['up_waiting']):      # 上游被它堵住多于等料
        pro += ev['up_blocked'] > ev['up_waiting']
    if ev['down_waiting'] is not None and (ev['down_waiting'] or ev['down_blocked']):  # 下游等它来料多于被堵
        pro += ev['down_waiting'] > ev['down_blocked']
        con += ev['down_blocked'] > ev['down_waiting']
    ev['agree'] = True if pro > con else (False if con > pro else None)
    return ev


def _evidence_text(ev):
    parts = []
    if ev.get('in_fill') is not None:
        parts.append(_tr('进料缓存平均 {v:.0f}% 满', v=ev['in_fill'] * 100))
    if ev.get('out_fill') is not None:
        parts.append(_tr('出料缓存平均 {v:.0f}% 满', v=ev['out_fill'] * 100))
    if ev.get('up') and ev.get('up_blocked') is not None:
        parts.append(_tr('上游 {join} 堵料 {v:.0f}%、等料 {v2:.0f}%', join=_tr('、').join(ev['up'][:2]), v=ev['up_blocked'] * 100, v2=ev['up_waiting'] * 100))
    if ev.get('down') and ev.get('down_waiting') is not None:
        parts.append(_tr('下游 {join} 等料 {v:.0f}%、堵料 {v2:.0f}%', join=_tr('、').join(ev['down'][:2]), v=ev['down_waiting'] * 100, v2=ev['down_blocked'] * 100))
    tail = {True: _tr('符合瓶颈特征'), False: _tr('不像瓶颈'), None: ''}[ev.get('agree')]
    return _tr('；').join(parts) + (_tr('（{tail}）', tail=tail) if tail and parts else '')


def _verdict(top, gap):
    if not top:
        return _tr('统计区间内没有设备在工作，判断不出瓶颈。'), 'low'
    if len(top) > 1:
        shares = _tr('、').join(f"{x['share'] * 100:.0f}%" for x in top)
        return (_tr('并列瓶颈：{join}（瓶颈时间占比分别为 {shares}，相差不到 {v:.0f} 个百分点，分不出谁更限制产出，改善时要一起考虑）。', join=_tr('、').join(x['name'] for x in top), shares=shares, v=TIE_GAP * 100)), 'low'
    b = top[0]
    v = (_tr('瓶颈是{name}：{v:.0f}% 的生产时间里它是限制产出的设备（独占 {v2:.0f}%，与其他设备交替 {v3:.0f}%）', name=b['name'], v=b['share'] * 100, v2=b['sole'] * 100, v3=b['shifting'] * 100))
    v += _tr('，领先第二名 {v:.0f} 个百分点。', v=gap * 100) if gap is not None else _tr('。')
    agree = (b.get('evidence') or {}).get('agree')
    if agree is False:
        v += _tr('上下游的堵料/等料情况不太支持这个判断，建议延长统计区间再看。')
    return v, ('high' if (gap is None or gap >= 0.15) and agree is not False else 'medium')


# ---------------- 桑基图 ----------------
def _ts(plant, s):
    try:
        return (datetime.fromisoformat(s) - plant.t0).total_seconds()
    except (TypeError, ValueError):
        return None


def sankey(plant, t0, t1, level='block'):
    """零件在设备之间的流向（件数）。环路（返修回流）拆成"↺"节点，保证图是无环的。"""
    s0, s1 = clock(plant, t0), clock(plant, t1)
    edges = defaultdict(int)
    first_seen = {}
    n_parts = 0
    term = {'SCRAP': _tr('报废'), 'SHIPPED': _tr('发运')}
    for p in list(plant.parts.values()):
        hist = p.get('history') or []
        prev = None
        used = False
        for h in hist:
            ts = h.get('t', '')
            sid = h.get('station')
            if not sid or ts < s0 or ts > s1:
                if ts > s1:
                    break
                prev = (_top(plant, sid) if level == 'block' else sid) if sid else prev
                continue
            node = _top(plant, sid) if level == 'block' else sid
            first_seen.setdefault(node, len(first_seen))
            if prev is not None and node != prev:
                edges[(prev, node)] += 1
                used = True
            prev = node
        if prev is not None and p.get('status') in term and hist and s0 <= hist[-1].get('t', '') <= s1:
            tn = term[p['status']]
            first_seen.setdefault(tn, 10 ** 6 + len(first_seen))
            edges[(prev, tn)] += 1
            used = True
        n_parts += used
    # 去环：件数多的边优先保留为正向，加上会成环的边（通常是返修回流）改指向 "节点 ↺"
    fwd, back = defaultdict(set), set()

    def reach(x, y):
        seen, st = {x}, [x]
        while st:
            u = st.pop()
            if u == y:
                return True
            for v in fwd[u]:
                if v not in seen:
                    seen.add(v)
                    st.append(v)
        return False
    for (a, b), n in sorted(edges.items(), key=lambda kv: (-kv[1], first_seen.get(kv[0][0], 0))):
        if a == b or reach(b, a):
            back.add((a, b))
        else:
            fwd[a].add(b)
    links = []
    names = set()
    for (a, b), n in edges.items():
        tgt = f'{b} ↺' if (a, b) in back else b
        links.append({'source': a, 'target': tgt, 'value': n})
        names.update((a, tgt))

    def label(nid):
        base = nid[:-2] if nid.endswith(' ↺') else nid
        st = plant.find(base) if hasattr(plant, 'find') else plant.stations.get(base)
        nm = st.name if st is not None else base
        return nm + (_tr('（回流）') if nid.endswith(' ↺') else '')

    def kind(nid):
        st = plant.find(nid) if hasattr(plant, 'find') else plant.stations.get(nid)
        return st.kind if st is not None else ('scrap' if nid in variants('报废') else 'ship' if nid in variants('发运') else 'loop')
    nodes = [{'name': n, 'label': label(n), 'kind': kind(n)} for n in sorted(names, key=lambda k: first_seen.get(k.removesuffix(' ↺'), 10 ** 7))]
    links.sort(key=lambda x: -x['value'])
    return {'from': s0[:16], 'to': s1[:16], 'hours': round((t1 - t0) / 3600, 2), 'level': level, 'parts': n_parts, 'nodes': nodes, 'links': links,
            'loops': [{'source': a, 'target': b} for a, b in sorted(back)]}


# ---------------- 甘特图 ----------------
def gantt_resource(plant, t0, t1, ids=None, max_items=20000):
    """按设备：每台设备的时间类别区间。items = [行号, 开始秒, 结束秒, 类别]（仿真秒，base 为 t=0 的时刻）。"""
    want = set(ids) if ids else None
    rows, idx = [], {}
    for st in _all(plant):
        if want is not None and st.id not in want:
            continue
        if want is None and st.kind in ('crew', 'agv', 'operators', 'transporter', 'buffer', 'sink', 'storage', 'warehouse'):
            continue
        idx[st.id] = len(rows)
        rows.append({'id': st.id, 'name': st.name, 'kind': st.kind, 'parent': getattr(plant, 'sub_parent', {}).get(st.id)})
    by = defaultdict(list)
    for t, sid, c in plant.class_log:
        if sid in idx:
            by[sid].append((t, c))
    items = []
    for sid, seq in by.items():
        for i, (t, c) in enumerate(seq):
            a = max(t, t0)
            b = min(seq[i + 1][0] if i + 1 < len(seq) else t1, t1)
            if b > a:
                items.append([idx[sid], a, b, c])
    min_s = 0.0
    if len(items) > max_items:                     # 太密时丢掉最短的区间（甘特图上本来也看不见）
        lens = sorted(it[2] - it[1] for it in items)
        min_s = lens[len(items) - max_items]
        items = [it for it in items if it[2] - it[1] >= min_s]
    return {'by': 'resource', 't0': t0, 't1': t1, 'base': plant.t0.strftime('%Y-%m-%dT%H:%M:%S'), 'rows': rows, 'items': items,
            'classes': classes(), 'dropped_shorter_than_s': round(min_s, 1)}


def _segments(plant, part, s0, s1):
    """零件在各设备的停留区间：从在该设备的第一条事件到离开（下一台设备的第一条事件）。"""
    out = []
    cur, start, last = None, None, None
    for h in part.get('history') or []:
        ts, sid = h.get('t', ''), h.get('station')
        if not sid:
            continue
        sid = _top(plant, sid)
        if sid != cur:
            if cur is not None:
                out.append((cur, start, ts))
            cur, start = sid, ts
        last = ts
    if cur is not None:
        end = last if part.get('status') in ('SCRAP', 'SHIPPED', 'FG', 'CONSUMED', 'GOOD') else clock(plant, plant.t)
        out.append((cur, start, end if end > start else last))
    res = []
    for sid, a, b in out:
        if b < s0 or a > s1:
            continue
        st = plant.find(sid) if hasattr(plant, 'find') else plant.stations.get(sid)
        if st is not None and st.kind in ('sink', 'storage', 'warehouse'):
            continue                                  # 入库后在成品库里的停留不算生产过程
        ta, tb = _ts(plant, a), _ts(plant, b)
        if ta is None or tb is None:
            continue
        res.append((sid, ta, max(tb, ta + 1)))
    return res


def gantt_orders(plant, t0, t1, by='order', order=None, limit=60):
    """按订单：每个订单一行，各设备上该订单零件的最早开始~最晚结束；按零件：每件一行（可按订单过滤）。"""
    s0, s1 = clock(plant, t0), clock(plant, t1)
    st_rows, st_idx = [], {}

    def sidx(sid):
        if sid not in st_idx:
            st = plant.find(sid) if hasattr(plant, 'find') else plant.stations.get(sid)
            st_idx[sid] = len(st_rows)
            st_rows.append({'id': sid, 'name': st.name if st is not None else sid})
        return st_idx[sid]
    parts = [p for p in plant.parts.values() if (order is None or p.get('order') == order) and p.get('history')]
    rows, items = [], []
    if by == 'part':
        parts = [p for p in parts if p['history'][-1].get('t', '') >= s0 and p['history'][0].get('t', '') <= s1][-limit:]
        for p in parts:
            r = len(rows)
            rows.append({'id': p['id'], 'name': p['id'], 'order': p.get('order'), 'type': p.get('type'), 'status': p.get('status')})
            for sid, a, b in _segments(plant, p, s0, s1):
                items.append([r, a, b, sidx(sid)])
    else:
        agg = {}
        span = {}
        cnt = defaultdict(lambda: [0, 0])
        for p in parts:
            o = p.get('order')
            if not o:
                continue
            segs = _segments(plant, p, s0, s1)
            if not segs:
                continue
            cnt[o][0] += 1
            cnt[o][1] += p.get('status') in ('FG', 'SHIPPED', 'GOOD')
            for sid, a, b in segs:
                k = (o, sid)
                if k in agg:
                    agg[k][0], agg[k][1] = min(agg[k][0], a), max(agg[k][1], b)
                else:
                    agg[k] = [a, b]
                sp = span.setdefault(o, [a, b])
                sp[0], sp[1] = min(sp[0], a), max(sp[1], b)
        orders = sorted(span, key=lambda o: span[o][0])[:limit]
        due = {o['code']: o.get('due') for o in getattr(plant.plan, 'orders', [])}
        oi = {}
        for o in orders:
            oi[o] = len(rows)
            d = due.get(o)
            rows.append({'id': o, 'name': o, 'parts': cnt[o][0], 'done': cnt[o][1], 'start': span[o][0], 'end': span[o][1],
                         'due': str(d)[:16] if d else None, 'due_t': _ts(plant, str(d)[:16].replace('T', ' ') + ':00') if d else None})
        for (o, sid), (a, b) in agg.items():
            if o in oi:
                items.append([oi[o], a, b, sidx(sid)])
    return {'by': by, 't0': t0, 't1': t1, 'base': plant.t0.strftime('%Y-%m-%dT%H:%M:%S'), 'rows': rows, 'items': items, 'stations': st_rows,
            'orders': sorted({p.get('order') for p in plant.parts.values() if p.get('order')})}


# ---------------- 能耗 ----------------
DEFAULT_ENERGY = {
    'tou': [{'name': '谷', 'start': '00:00', 'end': '08:00', 'price': 0.32}, {'name': '峰', 'start': '08:00', 'end': '12:00', 'price': 1.05},
            {'name': '平', 'start': '12:00', 'end': '17:00', 'price': 0.65}, {'name': '峰', 'start': '17:00', 'end': '21:00', 'price': 1.05},
            {'name': '平', 'start': '21:00', 'end': '24:00', 'price': 0.65}],
    'default_price': 0.65, 'demand_price': 38.0, 'co2_kg_per_kwh': 0.5703,
}


def energy_settings(cfg):
    e = dict(DEFAULT_ENERGY)
    e.update((cfg or {}).get('energy') or {})
    return e


def _hm(s):
    h, m = str(s).split(':')[:2]
    return int(h) * 60 + int(m)


def tou_period(settings, dt: datetime):
    m = dt.hour * 60 + dt.minute
    for p in settings.get('tou') or []:
        a, b = _hm(p['start']), _hm(p['end'])
        if (a <= m < b) if a < b else (m >= a or m < b):
            return p.get('name') or _tr('时段'), float(p.get('price', settings.get('default_price', 0.65)))
    return _tr('其他'), float(settings.get('default_price', 0.65))


def energy(plant, t0, t1, settings=None):
    from .history import _at, snapshot
    st_ = settings or energy_settings(plant.cfg)
    qs = [(t, kwh, 900.0) for t, kwh in plant.energy_q if t0 < t <= t1 + 1]
    part = plant.t - (plant.t // 900) * 900
    if t1 >= plant.t - 1 and part > 0 and plant._e_q > 0:
        qs.append((plant.t, plant._e_q, part))     # 当前未满 15 分钟的这一段
    curve, cost_by, kwh_by = [], defaultdict(float), defaultdict(float)
    peak, peak_at = 0.0, None
    total_q = 0.0
    for t, kwh, span in qs:
        mid = plant.t0 + timedelta(seconds=t - span / 2)
        name, price = tou_period(st_, mid)
        kw = kwh * 3600 / max(1.0, span)
        curve.append({'t': clock(plant, t)[5:16], 'kw': round(kw, 1), 'period': name})
        if span >= 899 and kw > peak:
            peak, peak_at = kw, clock(plant, t)[5:16]
        cost_by[name] += kwh * price
        kwh_by[name] += kwh
        total_q += kwh
    hist = list(plant.hourly) + [snapshot(plant)]
    a = _at(hist, t0) or hist[0]
    b = hist[-1] if t1 >= plant.t - 1 else (_at(hist, t1) or hist[-1])

    def dd(x, y):
        return {k: round(y.get(k, 0) - x.get(k, 0), 2) for k in y if y.get(k, 0) - x.get(k, 0) > 0.005}
    by_cls = dd(a.get('e_cls', {}), b.get('e_cls', {}))
    by_st = []
    for sid, ecls in (b.get('e_st_cls') or {}).items():
        d = dd((a.get('e_st_cls') or {}).get(sid, {}), ecls)
        tot = round(sum(d.values()), 2)
        if tot > 0.01:
            st = plant.find(sid) if hasattr(plant, 'find') else plant.stations.get(sid)
            by_st.append({'id': sid, 'name': st.name if st is not None else sid, 'kind': st.kind if st is not None else '', 'kwh': tot, 'by_cls': d})
    by_st.sort(key=lambda x: -x['kwh'])
    good = b['good'] - a['good']
    total = round(total_q, 1)
    cost = round(sum(cost_by.values()), 1)
    return {'from': clock(plant, t0)[:16], 'to': clock(plant, t1)[:16], 'hours': round((t1 - t0) / 3600, 2), 'settings': st_,
            'kwh': total, 'cost': cost, 'avg_price': round(cost / total, 3) if total else None,
            'cost_by_period': {k: round(v, 1) for k, v in cost_by.items()}, 'kwh_by_period': {k: round(v, 1) for k, v in kwh_by.items()},
            'peak_kw': round(peak, 1), 'peak_at': peak_at, 'demand_cost_month': round(peak * float(st_.get('demand_price') or 0), 0),
            'co2_kg': round(total * float(st_.get('co2_kg_per_kwh') or 0), 1), 'good': good,
            'kwh_per_good': round(total / good, 3) if good else None, 'cost_per_good': round(cost / good, 3) if good else None,
            'by_cls': by_cls, 'by_station': by_st[:60], 'curve': curve[-4 * 24 * 7:], 'classes': classes()}
