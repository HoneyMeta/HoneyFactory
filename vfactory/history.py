"""历史数据：点位环形缓冲（每 30 s 仿真时间一行）、每小时 KPI 快照、报表计算、数据集导出。

全部在内存里，工厂重启后从头记录；需要长期保存时用"数据集导出"或接 MES。
"""
from .i18n import _tr
import csv
import io
import json
import math
import zipfile
from collections import defaultdict
from datetime import timedelta

import numpy as np

FLOW_KINDS = ('molding', 'shotblast', 'cnc', 'deburr', 'inspection', 'receiving', 'processor', 'batch', 'inspect', 'assembly', 'rework', 'conveyor')
KIND_CN = {'furnace': '中频炉', 'treatment': '球化站', 'sand': '砂处理', 'molding': '造型线', 'cooling': '冷却线', 'shotblast': '抛丸机', 'cnc': '加工中心',
           'deburr': '去毛刺', 'inspection': '内窥检测', 'warehouse': '立库', 'agv': 'AGV', 'crew': '班组', 'receiving': '来料'}
STATE_CN = {'Executing': '运行', 'Idle': '待机/等待', 'Starved': '饥饿（缺料）', 'Blocked': '阻塞（下游满）', 'Setup': '换型/换刀', 'Stopped': '故障停机', 'Planned': '计划停机'}


class TagRing:
    """所有数值点位的环形缓冲：n 行 × 点位列，float32。"""

    def __init__(self, plant, n=2880, every=30):
        self.plant, self.n, self.every = plant, n, every
        self.keys: list[str] = []
        self.idx: dict[str, int] = {}
        self.buf = np.full((n, 0), np.nan, dtype=np.float32)
        self.ts = np.full(n, np.nan)
        self.pos = 0
        self.count = 0
        self.ver = -1

    def _ensure(self):
        if self.ver == self.plant.layout_version:
            return
        self.ver = self.plant.layout_version
        new = []
        for st in self.plant.stations.values():
            for k, t in st.tags.items():
                key = f'{st.id}/{k}'
                if t.dtype in ('float', 'int', 'bool') and key not in self.idx:
                    new.append(key)
        if new:
            for k in new:
                self.idx[k] = len(self.keys)
                self.keys.append(k)
            pad = np.full((self.n, len(new)), np.nan, dtype=np.float32)
            self.buf = np.concatenate([self.buf, pad], axis=1)

    def record(self):
        self._ensure()
        row = self.buf[self.pos]
        row[:] = np.nan
        for st in self.plant.stations.values():
            for k, t in st.tags.items():
                i = self.idx.get(f'{st.id}/{k}')
                if i is not None:
                    v = t.value
                    if isinstance(v, (int, float)):
                        row[i] = float(v)
        self.ts[self.pos] = self.plant.t
        self.pos = (self.pos + 1) % self.n
        self.count = min(self.n, self.count + 1)

    def _order(self):
        if self.count < self.n:
            return np.arange(0, self.count)
        return np.concatenate([np.arange(self.pos, self.n), np.arange(0, self.pos)])

    def series(self, key, since_t=None):
        i = self.idx.get(key)
        if i is None:
            return [], []
        o = self._order()
        t, v = self.ts[o], self.buf[o, i]
        m = ~np.isnan(v)
        if since_t is not None:
            m &= t >= since_t
        return t[m].tolist(), [round(float(x), 4) for x in v[m]]

    def frame(self, t0=None, t1=None, keys=None):
        o = self._order()
        t = self.ts[o]
        m = np.ones(len(t), bool)
        if t0 is not None:
            m &= t >= t0
        if t1 is not None:
            m &= t <= t1
        cols = [self.idx[k] for k in (keys or self.keys) if k in self.idx]
        return t[m], self.buf[o][m][:, cols], [self.keys[c] for c in cols]


def snapshot(plant):
    """每小时一次的累计计数快照。"""
    k = plant.kpi
    areas = defaultdict(float)
    e_cls = defaultdict(float)
    for s in plant.stations.values():
        areas[s.area or _tr('其他')] += s.energy_kwh
        for c, v in getattr(s, 'energy_by_cls', {}).items():
            e_cls[c] += v
    allst = plant.all_stations() if hasattr(plant, 'all_stations') else plant.stations.values()
    e_st_cls = {s.id: {c: round(v, 3) for c, v in getattr(s, 'energy_by_cls', {}).items()} for s in allst if s.kind != 'submodel'}
    return {'e_cls': dict(e_cls), 'e_st_cls': e_st_cls, 't': plant.t, 'time': plant.clock_str(), 'castings': k['castings'], 'machined': k['machined'], 'good': k['good'], 'scrap': k['scrap'],
            'shipped': k['shipped'], 'escape': k['escape'], 'overkill': k['overkill'], 'melt_kg': k['melt_kg'], 'energy': dict(areas),
            'wip': {b: len(v) for b, v in plant.buffers.items()}, 'scrap_by': dict(k['scrap_by'])}


def state_durations(plant, t0, t1):
    """各设备在 [t0, t1] 内各状态的时长（秒），根据状态变化记录还原。"""
    by = defaultdict(list)
    for t, sid, st in plant.state_log:
        by[sid].append((t, st))
    out = {}
    for sid, seq in by.items():
        d = defaultdict(float)
        for i, (t, st) in enumerate(seq):
            a = max(t, t0)
            b = min(seq[i + 1][0] if i + 1 < len(seq) else t1, t1)
            if b > a:
                d[st] += b - a
        out[sid] = dict(d)
    return out


def _at(hist, t):
    """取 t 时刻之前最近的快照。"""
    best = None
    for h in hist:
        if h['t'] <= t:
            best = h
        else:
            break
    return best


ZERO = {'t': 0.0, 'castings': 0, 'machined': 0, 'good': 0, 'scrap': 0, 'shipped': 0, 'escape': 0, 'overkill': 0, 'melt_kg': 0.0, 'energy': {},
        'wip': {}, 'scrap_by': {}, 'e_cls': {}, 'e_st_cls': {}}
CLS_UTIL = {'run': '运行', 'idle': '待机/等待', 'starved': '饥饿（缺料）', 'blocked': '阻塞（下游满）', 'setup': '换型/换刀', 'failed': '故障停机',
            'planned': '计划停机', 'offshift': '非班次', 'disabled': '停用', 'wait_plc': '等待 PLC（未允许运行）'}


def summary(plant, t0=None, t1=None):
    """统计区间 [t0, t1] 的全部指标：产出/报废/用电（整点快照相减）、每小时序列、时间构成与 OEE、瓶颈分析、生产周期、在制品、结论。
    报表页、方案报告、实验、AI 助手都用这一份结果（同区间、同口径），不要在别处另算。"""
    from . import analysis
    t1 = plant.t if t1 is None else min(t1, plant.t)
    t0 = (plant.hourly[0]['t'] if plant.hourly else 0) if t0 is None else max(0, t0)
    hours = max(1e-6, (t1 - t0) / 3600)
    hist = list(plant.hourly)
    if (not hist and plant.t <= 3600.5) or (hist and 0.5 < hist[0]['t'] <= 3600.5):
        hist = [{**ZERO, 'time': analysis.clock(plant, 0)}] + hist      # 从 0 时刻跑起来的工厂：t=0 时一切为 0，第一个整点之前也能算
    hist.append(snapshot(plant))
    a, b = _at(hist, t0) or hist[0], hist[-1] if t1 >= plant.t - 1 else (_at(hist, t1) or hist[-1])
    d = {k: b[k] - a[k] for k in ('castings', 'machined', 'good', 'scrap', 'shipped', 'escape', 'overkill', 'melt_kg')}
    energy = {ar: round(b['energy'].get(ar, 0) - a['energy'].get(ar, 0), 1) for ar in b['energy']}
    scrap_by = {c: b['scrap_by'].get(c, 0) - a['scrap_by'].get(c, 0) for c in b['scrap_by'] if b['scrap_by'].get(c, 0) - a['scrap_by'].get(c, 0) > 0}
    # 在制品：每分钟采样（缓存 + 设备内），全区间平均
    wl = [(t, w) for t, w in plant.wip_log if t0 <= t <= t1]
    # 每小时序列
    series = []
    for i in range(1, len(hist)):
        h0, h1 = hist[i - 1], hist[i]
        if h1['t'] <= t0 or h0['t'] >= t1:
            continue
        ws = [w for t, w in wl if h0['t'] < t <= h1['t']]
        series.append({'time': h1['time'][5:16], 'castings': h1['castings'] - h0['castings'], 'good': h1['good'] - h0['good'],
                       'scrap': h1['scrap'] - h0['scrap'], 'energy': round(sum(h1['energy'].values()) - sum(h0['energy'].values()), 1),
                       'wip': round(sum(ws) / len(ws), 1) if ws else sum(h1['wip'].values())})
    # 设备时间构成（与"时间构成"图同一份数据）
    objs = analysis.station_stats(plant, t0, t1)
    util = []
    for o in objs:
        if o['passive']:
            continue
        util.append({'id': o['id'], 'name': o['name'], 'kind': o['kind'], 'group': o.get('group'),
                     **{CLS_UTIL.get(k, k): v for k, v in o['share'].items()}, 'run': o['share'].get('run', 0), 'oee': o['oee']})
    bn = analysis.bottleneck(plant, t0, t1, objs)
    groups = [{k: it[k] for k in ('group', 'name', 'n', 'run', 'share', 'sole', 'shifting', 'rank', 'tie', 'ids')} for it in bn['items']]
    # 生产周期
    lts = [lt for t, lt in plant.lead_times if t0 <= t <= t1]
    lead = {}
    if lts:
        arr = np.array(lts) / 3600
        hist_c, edges = np.histogram(arr, bins=12)
        lead = {'n': len(lts), 'mean_h': round(float(arr.mean()), 2), 'p50_h': round(float(np.percentile(arr, 50)), 2), 'p90_h': round(float(np.percentile(arr, 90)), 2),
                'hist': {'edges': [round(float(e), 2) for e in edges], 'counts': hist_c.tolist()}}
    wip_avg = round(sum(w for _, w in wl) / len(wl), 1) if wl else float(plant.wip_now())
    melt_t = d['melt_kg'] / 1000
    fur_kwh = energy.get('熔炼区', 0)
    res = {'t0': t0, 't1': t1, 'from': analysis.clock(plant, t0)[:16], 'to': analysis.clock(plant, t1)[:16],
           'hours': round(hours, 2), **d, 'scrap_rate': round(d['scrap'] / d['castings'], 4) if d['castings'] else 0,
           'good_per_h': round(d['good'] / hours, 2), 'energy': energy, 'energy_total': round(sum(energy.values()), 1),
           'kwh_per_t': round(fur_kwh / melt_t, 1) if melt_t > 1 else None, 'kwh_per_good': round(sum(energy.values()) / d['good'], 2) if d['good'] else None,
           'scrap_by': scrap_by, 'series': series, 'util': util, 'bottleneck': groups, 'bottleneck_analysis': bn, 'lead': lead,
           'wip_avg': wip_avg, 'wip_max': max(w for _, w in wl) if wl else None, 'objects': objs,
           'basis': {'wip': _tr('每分钟采样一次（缓存 + 设备内在制品），统计区间内取平均'), 'counts': _tr('整点快照相减，区间起点对齐整点'),
                     'lead': _tr('投产到入库，按完成时刻落在区间内的零件统计'), 'bottleneck': bn['method_label']}}
    res['findings'] = findings(res)
    return res


def findings(r):
    """结论文字：数字全部取自同一份 summary 结果。"""
    out = []
    bn = r.get('bottleneck_analysis') or {}
    if bn.get('verdict'):
        out.append(bn['verdict'] + (_tr('提高整线产量要先提高它（加设备、缩短节拍、减少停机）。') if bn.get('top') and not bn.get('tie') else ''))
        rest = [it for it in bn.get('items', []) if it['group'] not in bn.get('top', [])]
        if rest and rest[0]['share'] > 0 and bn.get('top'):
            s = rest[0]
            out.append(_tr('次瓶颈是{name}（瓶颈时间占比 {v:.0f}%），瓶颈缓解后它会成为新的限制。', name=s['name'], v=s['share'] * 100))
        ex = [e for e in bn.get('excluded', []) if e.get('id')]
        if ex:
            by_reason = {}
            for e in ex:
                by_reason.setdefault(e['reason'], []).append(e['name'])
            out.append(_tr('未参与瓶颈判断：') + _tr('；').join(_tr('{join}（{k}）', join=_tr('、').join(v), k=k) for k, v in by_reason.items()) + _tr('。'))
    stops = sorted((u for u in r['util'] if u.get('故障停机', 0) > 0.03), key=lambda u: -u['故障停机'])
    for u in stops[:2]:
        out.append(_tr('{name} 故障停机占 {v:.1f}%，建议查看维修记录和点检。', name=u['name'], v=u['故障停机'] * 100))
    if r['scrap_by']:
        c, n = max(r['scrap_by'].items(), key=lambda x: x[1])
        out.append(_tr('最主要的报废原因是「{c}」，共 {n} 件，占报废的 {v:.0f}%。', c=c, n=n, v=n / max(1, r['scrap']) * 100))
    if r['escape']:
        out.append(_tr('有 {escape} 件缺陷件被内窥检测漏检（仿真真值），需要关注检测灵敏度和光源。', escape=r['escape']))
    if r['lead']:
        out.append(_tr('生产周期平均 {mean_h} 小时，90% 的零件在 {p90_h} 小时内完成；在制品平均 {wip_avg} 件。', mean_h=r['lead']['mean_h'], p90_h=r['lead']['p90_h'], wip_avg=r['wip_avg']))
    return out


# ---------------- 导出 ----------------
def to_excel(r, plant_name):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = _tr('汇总')
    head = Font(bold=True)
    fill = PatternFill('solid', fgColor='F2C94C')
    rows = [(_tr('工厂'), plant_name), (_tr('统计区间'), f"{r['from']} ~ {r['to']}"), (_tr('时长 h'), r['hours']), (_tr('浇注/来料'), r['castings']), (_tr('机加'), r['machined']),
            (_tr('合格入库'), r['good']), (_tr('报废'), r['scrap']), (_tr('废品率'), r['scrap_rate']), (_tr('发运'), r['shipped']), (_tr('合格件/小时'), r['good_per_h']),
            (_tr('用电 kWh'), r['energy_total']), (_tr('电炉吨耗 kWh/t'), r['kwh_per_t']), (_tr('单件电耗 kWh'), r['kwh_per_good']), (_tr('漏检（真值）'), r['escape']),
            (_tr('误判'), r['overkill']), (_tr('平均在制品'), r['wip_avg']), (_tr('平均生产周期 h'), r['lead'].get('mean_h') if r['lead'] else None)]
    for row in rows:
        ws.append(row)
    ws.append([])
    ws.append([_tr('结论')])
    for f in r['findings']:
        ws.append([f])
    for c in ws['A']:
        c.font = head
    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 40

    def sheet(title, header, data):
        s = wb.create_sheet(title)
        s.append(header)
        for c in s[1]:
            c.font, c.fill = head, fill
        for d in data:
            s.append(d)
        for i in range(len(header)):
            s.column_dimensions[chr(65 + i)].width = 16
    sheet(_tr('小时产出'), [_tr('时间'), _tr('浇注'), _tr('合格入库'), _tr('报废'), _tr('用电 kWh'), _tr('在制品')], [[x['time'], x['castings'], x['good'], x['scrap'], x['energy'], x['wip']] for x in r['series']])
    states = list(CLS_UTIL.values())
    sheet(_tr('设备利用'), [_tr('设备'), _tr('名称'), 'OEE'] + states, [[u['id'], u['name'], u['oee']] + [u.get(s, 0) for s in states] for u in r['util']])
    sheet(_tr('瓶颈'), [_tr('排名'), _tr('工位组'), _tr('名称'), _tr('设备数'), _tr('瓶颈时间占比'), _tr('其中独占'), _tr('其中交替'), _tr('运行占比'), _tr('并列')],
          [[b.get('rank'), b['group'], b['name'], b['n'], b.get('share'), b.get('sole'), b.get('shifting'), b['run'], _tr('是') if b.get('tie') else '']
           for b in r['bottleneck']])
    sheet(_tr('报废原因'), [_tr('原因'), _tr('件数')], list(r['scrap_by'].items()))
    sheet(_tr('能耗'), [_tr('区域'), 'kWh'], list(r['energy'].items()))
    if r['lead']:
        e = r['lead']['hist']['edges']
        sheet(_tr('生产周期分布'), [_tr('区间 h'), _tr('件数')], [[f'{e[i]}–{e[i + 1]}', n] for i, n in enumerate(r['lead']['hist']['counts'])])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def dataset_zip(plant, t0, t1, keys=None):
    """AI 数据集：时序（宽表）、事件、零件（含真实缺陷）、标签（故障/计划停机/场景动作的起止）。"""
    ring = plant.tagring
    ts, mat, cols = ring.frame(t0, t1, keys)
    z = io.BytesIO()
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as f:
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(['time', 't_s'] + cols)
        for i, t in enumerate(ts):
            w.writerow([(plant.t0 + timedelta(seconds=float(t))).strftime('%Y-%m-%d %H:%M:%S'), int(t)] +
                       ['' if math.isnan(x) else round(float(x), 5) for x in mat[i]])
        f.writestr('tags.csv', '﻿' + s.getvalue())
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(['seq', 'time', 'station', 'kind', 'msg', 'data'])
        for e in plant.events:
            et = (_parse(plant, e['t']))
            if t0 <= et <= t1:
                w.writerow([e['seq'], e['t'], e['station'], e['kind'], e['msg'], json.dumps({k: v for k, v in e.items() if k not in ('seq', 't', 'station', 'kind', 'msg')}, ensure_ascii=False)])
        f.writestr('events.csv', '﻿' + s.getvalue())
        s = io.StringIO()
        w = csv.writer(s)
        attrs = ['heat', 'ladle', 'mold', 'cavity', 'pour_temp', 'mg', 'sand_moisture', 'compactability', 'ce']
        w.writerow(['part', 'type', 'order', 'born_t_s', 'done_t_s', 'status', 'scrap_cause'] + attrs + ['truth_defects', 'inspection_result', 'inspection_found', 'machine'])
        for p in plant.parts.values():
            if not (t0 <= p.get('t0', 0) <= t1):
                continue
            ins = p.get('inspection') or {}
            mach = next((h['station'] for h in p.get('history', []) if h['event'] == 'machined'), '')
            w.writerow([p['id'], p.get('type'), p.get('order', ''), int(p.get('t0', 0)), int(p['t_done']) if p.get('t_done') else '', p.get('status'), p.get('scrap_cause', '')]
                       + [p.get(a, '') for a in attrs] + [json.dumps(p.get('defects') or {}, ensure_ascii=False), ins.get('result', ''), '|'.join(ins.get('found', [])), mach])
        f.writestr('parts.csv', '﻿' + s.getvalue())
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(['station', 'type', 'name', 'start_t_s', 'end_t_s', 'start', 'end'])
        for lb in plant.labels:
            end = lb['end'] if lb['end'] is not None else plant.t
            if end < t0 or lb['start'] > t1:
                continue
            fmt = lambda x: (plant.t0 + timedelta(seconds=x)).strftime('%Y-%m-%d %H:%M:%S')
            w.writerow([lb['station'], lb['type'], lb['name'], int(lb['start']), int(end), fmt(lb['start']), fmt(end) + ('' if lb['end'] is not None else _tr('（进行中）'))])
        f.writestr('labels.csv', '﻿' + s.getvalue())
        f.writestr('README.md', README.format(plant=plant.name, frm=(plant.t0 + timedelta(seconds=t0)).strftime('%Y-%m-%d %H:%M'),
                                              to=(plant.t0 + timedelta(seconds=t1)).strftime('%Y-%m-%d %H:%M'), n=len(ts), cols=len(cols)))
    return z.getvalue()


def _parse(plant, s):
    from datetime import datetime
    return (datetime.strptime(s, '%Y-%m-%d %H:%M:%S') - plant.t0).total_seconds()


README = """# 蜂元虚拟工厂数据集

工厂：{plant}
区间：{frm} ~ {to}（仿真时间）
时序：{n} 行 × {cols} 个点位，每 30 秒（仿真时间）一行

## 文件
- tags.csv：时序宽表。列名为 设备/点位，例如 CNC1/Monitoring/Spindle/Load。空值表示该时刻设备不存在。
- events.csv：生产日志（炉次、换刀、报警、故障、维修、计划、场景动作……），data 列为结构化字段 JSON。
- parts.csv：零件档案。truth_defects 为仿真内部的真实缺陷（标准答案），inspection_* 为检测站给出的结论，可直接评估漏检/误判。
- labels.csv：标签区间。type 取值：failure 设备故障、fault 注入的异常（如断刀、水分仪漂移）、planned 计划停机/非生产时间、
  changeover 换型、scenario 场景动作、comm 通讯故障。end 为"进行中"表示导出时仍未结束。

## 用法提示
- 异常检测：用 tags.csv 训练，用 labels.csv 的 failure/fault 区间做评估。
- 质量预测：parts.csv 的浇注参数（pour_temp、mg、sand_moisture、compactability、ce）→ truth_defects。
- 刀具磨损：CNCx/Monitoring/Spindle/Load、Tools/Txx/LifeCount，配合 events.csv 里的换刀事件。
"""
