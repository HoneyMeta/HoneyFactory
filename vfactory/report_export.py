"""设计工作区：方案报告导出（Word / PPT）与 SOP 漫游。

报告
  GET  /api/p/{pid}/report/export/options              可选章节、已完成的实验、公司模板是否已上传
  GET  /api/p/{pid}/report/export/check?hours=24&experiments=1,2     导出前的数据自检（同一份统计结果里各处数字是否一致）
  POST /api/p/{pid}/report/export.docx  (同 .pptx)     body {image?: 'data:image/png;base64,...', sections?: [...], experiments?: [id],
                                                              hours?: 24, warmup?: true, title?, author?, template?: true, force?: false}
  GET  /api/p/{pid}/report/export.docx?sections=a,b&experiments=1,2&hours=24     不带截图（服务端画一张平面布局图代替）
  章节：layout 布局图、kpi 运行概况（含小时产出、在制品曲线）、bottleneck 瓶颈与时间构成、flow 物料流向（桑基图）、energy 能耗、
        experiments 方案对比（95% 置信区间图）、conclusions 结论；没有数据的章节自动跳过；最后附统计口径与自检结果。
  自检不通过时返回 409 和不一致的项目（force=true 仍然导出）。
公司模板（全局，所有工厂共用）
  GET    /api/report/templates                         → {docx: {name, size, uploaded} | null, pptx: ...}
  POST   /api/report/templates   {kind: 'docx'|'pptx', name, data_url}     .dotx/.docx 或 .potx/.pptx；导出时沿用模板的样式、页眉页脚、母版
  DELETE /api/report/templates/{kind}
SOP 漫游（新员工培训：按步骤在三维里高亮设备、第一人称走一遍）
  GET  /api/p/{pid}/sop                       → {sops: [...]}
  PUT  /api/p/{pid}/sop          {sops: [...]}
  每个 SOP：{id, name, desc, steps: [{id, title, text, target: {block, comp?}, camera: {mode: 'orbit'|'walk', pos?: [x,y,z], look?: [x,y,z]},
            duration_s?, check?: {kind: 'manual'|'tag', station?, tag?, op?, value?}}]}
依赖：python-docx 1.2.0、python-pptx 1.0.2、Pillow 12.3.0（服务端图表和布局图，见 report_charts.py），都在 requirements.txt 固定版本。
"""
from .i18n import _tr, label, server_tr
import base64
import copy
import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from . import analysis, history, report_charts as charts, store

SECTIONS = {'layout': '布局图', 'kpi': '运行概况', 'bottleneck': '瓶颈与时间构成', 'flow': '物料流向', 'energy': '能耗与电费', 'experiments': '方案对比',
            'conclusions': '结论与建议'}
EXP_KPIS = ['good_per_h', 'good', 'scrap_rate', 'energy_total', 'kwh_per_good', 'lead_mean', 'wip_avg']
CI_CHART_KPIS = [('good_per_h', False), ('wip_avg', False), ('scrap_rate', True)]
from . import paths as _paths  # noqa: E402
SOP_DIR = _paths.data('sop')
TPL_DIR = _paths.data('report_templates')
FONT = '微软雅黑'
CLS_CN = {c['key']: c['label'] for c in analysis.classes()}
BJ = timezone(timedelta(hours=8))


# ---------------- 数据 ----------------
def _num(v, d=2):
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:.{d}f}'.rstrip('0').rstrip('.') if abs(v) < 1e6 else f'{v:.0f}'
    return str(v)


def _pct(v):
    return '—' if v is None else f'{v * 100:.1f}%'


def bj_now():
    return datetime.now(BJ).strftime('%Y-%m-%d %H:%M')


def experiments_of(pid, ids=None):
    from .experiment import annotate
    rows = store.q("select * from experiments where plant=? and status='done' order by id desc", (pid,))
    if ids:
        rows = [r for r in rows if r['id'] in ids]
    else:
        rows = rows[:3]
    out = []
    for r in rows:
        try:
            res = json.loads(r['result'] or '{}')
        except ValueError:
            continue
        if res.get('error'):
            continue
        res = annotate(res, r['hours'])
        q = res.get('quality') or {}
        txt = list(res.get('text') or [])
        res['text'] = txt + [w for w in (q.get('warnings') or []) + ([q['clamped_note']] if q.get('clamped_note') else []) if w not in txt]
        out.append({'id': r['id'], 'name': r['name'], 'hours': r['hours'], 'reps': r['reps'], 'finished': r['finished'], 'result': res})
    return out


def exp_table(e, compact=False):
    """实验 → (表头, 行, 说明文字)。对比实验：方案 × 指标（均值与 95% 区间）；优化：前沿上的候选。compact = PPT 用"均值 ±半宽"。"""
    res = e['result']
    meta = {k['key']: k for k in res.get('kpis') or []}
    if res.get('kind') == 'optimize':
        keys = [o['key'] for o in res.get('objectives') or []] or ['good_per_h']
        head = [_tr('候选')] + [p['label'] for p in res.get('params') or []] + [meta.get(k, {}).get('label', k) for k in keys] + [_tr('前沿')]
        rows = []
        evs = sorted(res.get('evals') or [], key=lambda x: (not x.get('front'), x['i']))[:12]
        for ev in evs:
            cells = [f"#{ev['i'] + 1}"] + [_num(ev['values'].get(p['label'])) for p in res.get('params') or []]
            for k in keys:
                c = (ev.get('ci') or {}).get(k) or {}
                cells.append(_ci_text(ev['kpi'].get(k), c, k, compact))
            cells.append(_tr('是') if ev.get('front') else '')
            rows.append(cells)
        return head, rows, res.get('text') or []
    keys = [k for k in EXP_KPIS if k in meta]
    head = [_tr('方案')] + [f"{meta[k]['label']}{_tr('（') + meta[k]['unit'] + _tr('）') if meta[k].get('unit') else ''}" for k in keys]
    rows = []
    for r in res.get('rows') or []:
        cells = [r['name']]
        for k in keys:
            c = (r.get('ci') or {}).get(k) or {}
            t = _ci_text(r['kpi'].get(k), c, k, compact)
            d = (r.get('diff') or {}).get(k) or {}
            if r is not res['rows'][0] and d.get('lo') is not None:
                t += ' *' if d.get('significant') else ''
            cells.append(t)
        rows.append(cells)
    return head, rows, res.get('text') or []


def _ci_text(mean, c, key, compact=False):
    if mean is None:
        return '—'
    f = _pct if key == 'scrap_rate' else _num
    if c.get('lo') is not None and c.get('hi') is not None:
        if compact and not c.get('clamped') and c.get('half') is not None:
            return f'{f(mean)} ±{f(c["half"])}'
        return _tr('{f}（{f2}–{f3}）', f=f(mean), f2=f(c["lo"]), f3=f(c["hi"]))
    return f(mean)


def window_of(p, opts):
    hours = float(opts.get('hours') or 0)
    warm = str(opts.get('warmup', True)).lower() not in ('0', 'false', 'no', '')
    t0, t1 = analysis.window(p, hours, warm)
    note = _tr('已去掉预热') if warm and analysis.warmup_end(p) > 0 else _tr('含预热期')
    if t1 - t0 < 3600 and warm:            # 刚重置/刚启动：去掉预热后不到 1 小时，统计就把预热期也算进去
        t0, t1 = analysis.window(p, hours, warmup=False)
        note = _tr('运行时间较短，含预热期')
    return t0, t1, note


def collect(rt, opts):
    """报告用的全部数据：一个统计区间、一份 summary（stats/瓶颈/结论都从它来），能耗和桑基图用同一个区间。"""
    p = rt.plant
    t0, t1, warm_note = window_of(p, opts)
    s = history.summary(p, t0, t1)
    st = analysis.stats(p, t0, t1, s=s)
    try:
        en = analysis.energy(p, t0, t1)
    except Exception:
        en = None
    try:
        sk = analysis.sankey(p, t0, t1)
    except Exception:
        sk = None
    ids = opts.get('experiments')
    if isinstance(ids, str):
        ids = [int(x) for x in ids.split(',') if x.strip().isdigit()]
    exps = experiments_of(rt.pid, ids or None)
    objs = sorted([o for o in st['objects'] if not o['passive'] and o.get('parent') is None], key=lambda o: -(o['share'].get('run', 0)))[:14]
    concl = list(s.get('findings') or [])
    for e in exps:
        concl += [_tr('［{name}］{t}', name=e['name'], t=t) for t in (e['result'].get('text') or [])]
    d = {'title': opts.get('title') or _tr('{name} 方案报告', name=p.name), 'author': opts.get('author') or '', 'plant': p.name,
         'product': rt.cfg['plant'].get('product', ''), 'sim_time': p.clock_str()[:16], 'exported': bj_now(),
         'window': _tr('{v} — {to}（{hours:g} 小时，{warm_note}）', v=s['from'], to=s['to'], hours=s['hours'], warm_note=warm_note), 'from': s['from'], 'to': s['to'],
         'summary': s, 'stats': st, 'energy': en, 'sankey': sk, 'objects': objs, 'experiments': exps, 'conclusions': concl,
         'bottleneck': s['bottleneck_analysis'], 'kwh': en['kwh'] if en else s['energy_total']}
    want = [x for x in (opts.get('sections') or list(SECTIONS)) if x in SECTIONS]
    d['sections'], d['skipped'] = [], []
    for k in want:
        why = empty_reason(k, d, opts)
        if why:
            d['skipped'].append({'key': k, 'label': SECTIONS[k], 'reason': why})
        else:
            d['sections'].append(k)
    d['check'] = self_check(d)
    return d


def empty_reason(key, d, opts):
    s = d['summary']
    if key == 'kpi' and s['hours'] < 0.05:
        return _tr('统计区间太短')
    if key == 'bottleneck' and not d['objects'] and not d['bottleneck']['items']:
        return _tr('没有设备时间数据')
    if key == 'flow' and not (d.get('sankey') or {}).get('links'):
        return _tr('统计区间内没有零件流动记录')
    if key == 'energy' and (not d['energy'] or not d['energy'].get('kwh')):
        return _tr('统计区间内没有能耗数据')
    if key == 'experiments' and not d['experiments']:
        return _tr('还没有已完成的实验')
    if key == 'conclusions' and not d['conclusions']:
        return _tr('统计区间太短，没有结论')
    return None


def self_check(d):
    """导出前的数据自检：报告里各处用到的同一个指标必须一致（同一个区间、同一个口径）。"""
    s, st, en, bn = d['summary'], d['stats'], d['energy'], d['bottleneck']
    out = []

    def add(name, ok, detail=''):
        out.append({'name': name, 'ok': bool(ok), 'detail': detail})
    add(_tr('统计区间一致（概况、时间构成、能耗、物料流向）'),
        s['from'] == st['from'] and s['to'] == st['to'] and (en is None or (en['from'], en['to']) == (s['from'], s['to']))
        and (d.get('sankey') is None or (d['sankey']['from'], d['sankey']['to']) == (s['from'], s['to'])),
        f"{s['from']} — {s['to']}")
    add(_tr('平均在制品一致（概况表 / 时间构成 / 结论）'), st['plant']['wip_avg'] == s['wip_avg']
        and (not s.get('lead') or any(_tr('在制品平均 {wip_avg} 件', wip_avg=s['wip_avg']) in t or f"在制品平均 {s['wip_avg']} 件" in t for t in s['findings'])), _tr('{wip_avg} 件', wip_avg=s['wip_avg']))
    add(_tr('合格产出一致'), st['plant']['good'] == s['good'] and (en is None or en['good'] == s['good']), _tr('{good} 件', good=s['good']))
    add(_tr('小时产出 = 合格产出 ÷ 区间时长'), s['hours'] <= 0 or abs(s['good_per_h'] - s['good'] / max(1e-9, (s['t1'] - s['t0']) / 3600)) < 0.011,
        _tr('{good_per_h} 件/h', good_per_h=s['good_per_h']))
    if en is not None:
        diff = abs(en['kwh'] - s['energy_total'])
        add(_tr('总用电一致（概况 / 能耗章节）'), diff <= max(1.0, 0.005 * en['kwh']), f"{en['kwh']} kWh / {s['energy_total']} kWh")
    lead = s.get('lead') or {}
    add(_tr('生产周期一致'), st['plant']['lead_mean_h'] == lead.get('mean_h') and st['plant']['lead_p90_h'] == lead.get('p90_h'),
        _tr('平均 {get} h，P90 {get2} h', get=lead.get('mean_h'), get2=lead.get('p90_h')))
    names = [it['name'] for it in bn['items'] if it['group'] in bn['top']]
    add(_tr('结论里的瓶颈与瓶颈分析一致'), not names or (s['findings'] and all(n in s['findings'][0] for n in names)), _tr('、').join(names) or _tr('无'))
    add(_tr('概况表的瓶颈与瓶颈章节一致'), [b['group'] for b in st['plant']['bottleneck'][:len(bn['top'])]] == bn['top'][:3], '')
    bad = [o['name'] for o in st['objects'] if abs(sum(o['share'].values()) - 1) > 0.01]
    add(_tr('每台设备的时间构成合计 100%'), not bad, _tr('、').join(bad[:3]))
    from .experiment import BOUNDS
    badci = []
    for e in d['experiments']:
        res = e['result']
        rows = res.get('rows') or [{'name': _tr('候选 #{v}', v=ev['i'] + 1), 'ci': ev.get('ci') or {}} for ev in res.get('evals') or []]
        for r in rows:
            for k, c in (r.get('ci') or {}).items():
                if not c or c.get('lo') is None or c.get('mean') is None:
                    continue
                lo, hi = BOUNDS.get(k, (None, None))
                if c['lo'] > c['mean'] + 1e-9 or c['hi'] < c['mean'] - 1e-9 or (lo is not None and c['lo'] < lo - 1e-12) or (hi is not None and c['hi'] > hi + 1e-12):
                    badci.append(f"{e['name']}/{r['name']}/{k}")
    add(_tr('实验置信区间在取值范围内（比例 0~100%，计数不小于 0）'), not badci, _tr('、').join(badci[:3]))
    return {'ok': all(x['ok'] for x in out), 'checks': out, 'passed': sum(x['ok'] for x in out), 'total': len(out)}


def kpi_rows(d):
    s, pl = d['summary'], d['stats']['plant']
    rows = [(_tr('合格产出'), _tr('{good} 件', good=s['good'])), (_tr('小时产出'), _tr('{v} 件/h', v=_num(s['good_per_h']))), (_tr('废品率'), _pct(s['scrap_rate'])),
            (_tr('平均在制品'), _tr('{v} 件', v=_num(s['wip_avg']))), (_tr('平均生产周期'), f"{_num(pl.get('lead_mean_h'))} h"),
            (_tr('生产周期 P90'), f"{_num(pl.get('lead_p90_h'))} h"), (_tr('平均 OEE'), _pct(pl.get('oee_avg'))), (_tr('总用电'), f"{_num(d['kwh'])} kWh")]
    if s.get('kwh_per_good'):
        rows.append((_tr('单件电耗'), _tr('{v} kWh/件', v=_num(s['kwh_per_good']))))
    return rows


def breakdown_rows(d):
    cls = ['run', 'setup', 'starved', 'blocked', 'wait_plc', 'failed', 'idle', 'planned', 'offshift']
    cls = [c for c in cls if any(o['share'].get(c) for o in d['objects'])]
    head = [_tr('设备')] + [label(CLS_CN[c]) for c in cls] + ['OEE']
    rows = [[o['name']] + [_pct(o['share'].get(c)) if o['share'].get(c) else '' for c in cls] + [_pct(o.get('oee'))] for o in d['objects']]
    return head, rows, cls


def bottleneck_rows(d):
    head = [_tr('排名'), _tr('设备 / 工位组'), _tr('瓶颈时间占比'), _tr('独占'), _tr('交替'), _tr('运行占比')]
    rows = [[f"{it['rank']}{_tr('（并列）') if it['tie'] else ''}", it['name'], _pct(it['share']), _pct(it['sole']), _pct(it['shifting']), _pct(it['run'])]
            for it in d['bottleneck']['items'][:8]]
    return head, rows


def excluded_text(d):
    """未参与瓶颈判断的设备和原因；缓存、出入口、人员、搬运这类不加工零件的对象合成一句。"""
    ex = d['bottleneck'].get('excluded') or []
    out = _tr('；').join(_tr('{name}（{reason}）', name=e['name'], reason=e['reason']) for e in ex if e.get('id'))
    passive = [e['reason'].split('，')[0].split('（')[0].split(', ')[0].split(' (')[0] for e in ex if not e.get('id')]
    if passive:
        out += (_tr('。') if out else '') + _tr('{join}不加工零件，也不参与', join=_tr('、').join(dict.fromkeys(passive)))
    return out


def energy_rows(d):
    e = d['energy']
    if not e:
        return [], []
    a = [(_tr('总用电'), f"{_num(e['kwh'])} kWh"), (_tr('电费'), _tr('{v} 元', v=_num(e['cost']))), (_tr('平均电价'), _tr('{v} 元/kWh', v=_num(e['avg_price'], 3))),
         (_tr('峰值需量'), _tr('{v} kW（{v2}）', v=_num(e['peak_kw']), v2=e.get('peak_at') or '—')), (_tr('单件电耗'), _tr('{v} kWh/件', v=_num(e.get('kwh_per_good'), 3))),
         (_tr('碳排'), f"{_num(e['co2_kg'])} kg")]
    b = [[x['name'], _num(x['kwh'])] for x in e['by_station'][:8]]
    return a, b


def flow_rows(d, n=10):
    sk = d['sankey']
    lab = {x['name']: x['label'] for x in sk['nodes']}
    return [[lab.get(l['source'], l['source']), lab.get(l['target'], l['target']), l['value']] for l in sk['links'][:n]]


# ---------------- 图表（服务端渲染 PNG） ----------------
PERIOD_COLOR = {'峰': '#c8553a', '平': '#d99a16', '谷': '#3b82c4'}


def make_charts(d):
    """按章节生成图表 PNG：{名称: bytes}；没有数据的图不生成。"""
    s, out = d['summary'], {}
    sub = _tr('统计区间（仿真时间）{v} — {to}', v=d['from'], to=d['to'])

    def put(k, f, *a, **kw):
        try:
            png = f(*a, **kw)
        except Exception:
            import logging
            logging.getLogger('vfactory').exception(_tr('报告图表 %s 生成失败'), k)
            png = None
        if png:
            out[k] = png
    if 'kpi' in d['sections']:
        put('hourly', charts.hourly_output, s['series'], _tr('每小时产出（件）'), sub)
        put('wip', charts.line_chart, [x['time'] for x in s['series']], [x['wip'] for x in s['series']], _tr('在制品（每小时平均，件）'), '', sub, color='#7a6cc4')
    if 'bottleneck' in d['sections']:
        put('bottleneck', charts.bottleneck_bars, d['bottleneck']['items'], _tr('瓶颈时间占比（活跃期法）'), sub)
        put('breakdown', charts.time_breakdown, d['objects'], analysis.classes(), _tr('主要设备时间构成'), sub)
    if 'flow' in d['sections']:
        put('sankey', charts.sankey, d['sankey'], _tr('物料流向（{parts} 件零件，线宽 = 件数）', parts=d['sankey']['parts']), sub)
    if 'energy' in d['sections'] and d['energy']:
        e = d['energy']
        put('energy_period', charts.donut, [(k, v, PERIOD_COLOR.get(k[:1], '#7a6cc4')) for k, v in (e.get('kwh_by_period') or {}).items()], _tr('分时段用电'), 'kWh', sub)
        put('energy_station', charts.hbars, [(x['name'], x['kwh']) for x in e['by_station'][:8]], _tr('用电最多的设备'), 'kWh', sub, color='#d99a16')
    if 'experiments' in d['sections']:
        for e in d['experiments']:
            res = e['result']
            meta = {k['key']: k for k in res.get('kpis') or []}
            if res.get('kind') == 'optimize':
                objs = res.get('objectives') or []
                kx = objs[0]['key'] if objs else 'good_per_h'
                ky = objs[1]['key'] if len(objs) > 1 else 'wip_avg'
                best = (res.get('best') or {}).get('i')
                put(f"exp{e['id']}_pareto", charts.pareto_scatter, res.get('evals') or [], kx, ky, meta.get(kx, {}).get('label', kx), meta.get(ky, {}).get('label', ky),
                    best, kx == 'scrap_rate', ky == 'scrap_rate', _tr('{name}：候选分布', name=e['name']), _tr('每个候选 {get} 次重复的均值', get=res.get('design', {}).get('reps', 1)))
                continue
            for k, pct in CI_CHART_KPIS:
                if k not in meta:
                    continue
                rows = [{'name': r['name'], 'mean': (r.get('ci') or {}).get(k, {}).get('mean', r['kpi'].get(k)), 'lo': (r.get('ci') or {}).get(k, {}).get('lo'),
                         'hi': (r.get('ci') or {}).get(k, {}).get('hi'), 'best': r['name'] == res.get('best') and i > 0} for i, r in enumerate(res.get('rows') or [])]
                put(f"exp{e['id']}_{k}", charts.ci_chart, rows, meta[k]['label'], meta[k].get('unit') or '', pct,
                    _tr('均值与 95% 置信区间（{reps} 次重复）', reps=e['reps']))
    return out


# ---------------- 布局图（服务端兜底） ----------------
def _font(size):
    from PIL import ImageFont
    for f in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'):
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size), True
            except OSError:
                pass
    return ImageFont.load_default(), False


def render_plan(rt, width=1600):
    """当前布局的平面示意图（PNG 字节）：区域色带 + 设备方块 + 名称。没有中文字体时只写设备编号。"""
    from PIL import Image, ImageDraw
    meta = rt.meta()
    fw, fh = (meta.get('floor') or [150, 56])[:2]
    sc = (width - 80) / max(1.0, float(fw))
    h = int(fh * sc) + 80
    img = Image.new('RGB', (width, h), 'white')
    dr = ImageDraw.Draw(img)
    f, cjk = _font(max(11, int(sc * 1.1)))
    f2, _ = _font(16)
    ox, oy = 40, 40

    def X(x):
        return ox + float(x) * sc

    def Y(y):
        return oy + float(y) * sc
    for a in meta.get('areas') or []:
        xs = a.get('x') or [0, fw]
        ys = a.get('y') or [0, fh]
        col = a.get('color') or '#EEF2F5'
        try:
            dr.rectangle([X(xs[0]), Y(ys[0]), X(xs[1]), Y(ys[1])], fill=col)
        except ValueError:
            dr.rectangle([X(xs[0]), Y(ys[0]), X(xs[1]), Y(ys[1])], fill='#EEF2F5')
        if cjk:
            dr.text((X(xs[0]) + 6, Y(ys[0]) + 4), str(a.get('name', '')), fill='#6b7680', font=f2)
    dr.rectangle([X(0), Y(0), X(fw), Y(fh)], outline='#9aa4ae', width=2)
    palette = {'cnc': '#f2c46b', 'processor': '#f2c46b', 'buffer': '#b7cde3', 'source': '#9fd3b0', 'sink': '#eaa3a3', 'cell': '#9cc3ea',
               'furnace': '#f0a97a', 'molding': '#c9b7e8', 'warehouse': '#c3ccd6'}
    for s in meta.get('stations') or []:
        if s['kind'] in ('crew', 'agv') or not s.get('size'):
            continue
        x, y = s['pos'][:2]
        w, hh = s['size'][:2]
        if int(round(s.get('rot') or 0)) % 180 == 90:
            w, hh = hh, w
        col = palette.get(s['kind'], '#cfd8e2')
        dr.rectangle([X(x), Y(y), X(x + w), Y(y + hh)], fill=col, outline='#33404d', width=1)
        label = (s['name'] if cjk else s['id'])[:14]
        tw = dr.textlength(label, font=f)
        if tw > (w * sc - 4):                   # 设备太小放不下名字：写在方块下面
            dr.text((X(x), Y(y + hh) + 2), label, fill='#1d2733', font=f)
        else:
            dr.text((X(x) + 3, Y(y) + 2), label, fill='#1d2733', font=f)
    dr.text((ox, h - 30), (_tr('{name} 平面布局（{fw}×{fh} m，服务端生成）', name=rt.plant.name, fw=fw, fh=fh) if cjk else f'{rt.pid} layout {fw}x{fh} m'), fill='#33404d', font=f2)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def decode_image(data_url):
    if not data_url:
        return None
    m = re.match(r'^data:image/(png|jpeg|jpg);base64,(.+)$', data_url.strip(), re.S)
    if not m:
        raise HTTPException(400, _tr('截图需要 PNG/JPEG 的 data URL'))
    raw = base64.b64decode(m.group(2))
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(400, _tr('截图太大（超过 15 MB）'))
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        im.verify()
    except Exception:
        raise HTTPException(400, _tr('截图不是有效图片'))
    return raw


def image_size(raw):
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    return im.size


# ---------------- 公司模板 ----------------
TPL_KIND = {'docx': ('.dotx', '.docx'), 'pptx': ('.potx', '.pptx')}
TPL_CT = {'docx': ('wordprocessingml.template.main+xml', 'wordprocessingml.document.main+xml'),
          'pptx': ('presentationml.template.main+xml', 'presentationml.presentation.main+xml')}


def tpl_file(kind):
    for ext in TPL_KIND[kind]:
        f = os.path.join(TPL_DIR, f'template{ext}')
        if os.path.exists(f):
            return f
    return None


def tpl_info(kind):
    f = tpl_file(kind)
    if not f:
        return None
    meta = {}
    mp = os.path.join(TPL_DIR, f'{kind}.json')
    if os.path.exists(mp):
        with open(mp, encoding='utf-8') as fh:
            meta = json.load(fh)
    return {'name': meta.get('name') or os.path.basename(f), 'size': os.path.getsize(f), 'uploaded': meta.get('uploaded'), 'user': meta.get('user')}


def as_document_bytes(raw, kind):
    """.dotx/.potx 的内容类型改成文档类型（python-docx / python-pptx 只认文档），其余不动。"""
    a, b = TPL_CT[kind]
    zin = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == '[Content_Types].xml':
                data = data.replace(a.encode(), b.encode())
            zo.writestr(it, data)
    return out.getvalue()


def open_template(kind, raw=None):
    """→ python-docx Document / python-pptx Presentation（清空正文/幻灯片，保留样式、页眉页脚、母版），没有模板时 None。"""
    if raw is None:
        f = tpl_file(kind)
        if not f:
            return None
        with open(f, 'rb') as fh:
            raw = fh.read()
    data = as_document_bytes(raw, kind)
    if kind == 'docx':
        from docx import Document
        doc = Document(io.BytesIO(data))
        body = doc.element.body
        for el in list(body):
            if not el.tag.endswith('}sectPr'):
                body.remove(el)
        return doc
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    lst = prs.slides._sldIdLst
    for sid in list(lst):
        prs.part.drop_rel(sid.rId)
        lst.remove(sid)
    return prs


# ---------------- Word ----------------
def build_docx(d, image, template=None):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
    pics = make_charts(d)
    doc = template or Document()
    branded = template is not None
    sec = doc.sections[-1]
    if not branded:
        sec.left_margin = sec.right_margin = Cm(2.2)
        stl = doc.styles['Normal']
        stl.font.name = FONT
        stl.font.size = Pt(10.5)
        stl.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), FONT)
        for nm in ('Heading 1', 'Heading 2', 'Title'):
            try:
                s = doc.styles[nm]
                s.font.name = FONT
                s.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), FONT)
            except KeyError:
                pass
    width = sec.page_width - sec.left_margin - sec.right_margin

    def heading(text, level):
        try:
            return doc.add_heading(text, level)
        except KeyError:                          # 模板里没有标题样式
            p = doc.add_paragraph()
            r = p.add_run(text)
            r.bold, r.font.size = True, Pt({0: 20, 1: 15, 2: 12.5}.get(level, 12))
            return p

    def para(text, style=None, size=None, color=None):
        try:
            p = doc.add_paragraph(text, style=style) if style else doc.add_paragraph(text)
        except KeyError:
            p = doc.add_paragraph(('· ' if 'Bullet' in style else '') + text)
        if size or color:
            for r in p.runs:
                if size:
                    r.font.size = Pt(size)
                if color:
                    r.font.color.rgb = color
        return p

    def note(text):
        return para(text, size=8.5, color=RGBColor(0x66, 0x70, 0x7a))

    def picture(png, frac=1.0):
        if not png:
            return
        w, h = image_size(png)
        doc.add_picture(io.BytesIO(png), width=int(width * frac) if w >= h * 0.9 else int(width * frac * w / h * 0.75))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    def table(head, rows, widths=None):
        tb = doc.add_table(rows=1, cols=len(head))
        for st_ in ('Light Grid Accent 1', 'Table Grid'):
            try:
                tb.style = st_
                break
            except (KeyError, ValueError):
                continue
        for i, h in enumerate(head):
            c = tb.rows[0].cells[i]
            c.text = str(h)
            for pp in c.paragraphs:
                for rr in pp.runs:
                    rr.font.bold = True
                    rr.font.size = Pt(9)
        for row in rows:
            cs = tb.add_row().cells
            for i, v in enumerate(row):
                cs[i].text = '' if v is None else str(v)
                for pp in cs[i].paragraphs:
                    for rr in pp.runs:
                        rr.font.size = Pt(9)
        if widths:
            tb.autofit = False
            for i, w in enumerate(widths):
                tb.columns[i].width = Cm(w)
            for row in tb.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        doc.add_paragraph()
        return tb
    t = heading(d['title'], 0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(_tr('工厂：{plant}\u3000产品：{v}\n仿真时间（模型里的时钟）：{sim_time}\u3000统计区间（仿真时间）：{window}\n导出时间（北京时间）：{exported}{v2}\u3000蜂元虚拟工厂', plant=d['plant'], v=d['product'] or '—', sim_time=d['sim_time'], window=d['window'], exported=d['exported'], v2=_tr('\u3000编制：') + d['author'] if d['author'] else ''))
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x66, 0x70, 0x7a)
    n = 0
    for key in d['sections']:
        n += 1
        if key == 'layout':
            heading(_tr('{n}. 布局', n=n), 1)
            if image:
                picture(image)
            meta_st = [s for s in d['stats']['objects'] if not s['passive']]
            para(_tr('共 {len} 台主要设备。', len=len(meta_st)))
        elif key == 'kpi':
            heading(_tr('{n}. 运行概况', n=n), 1)
            table([_tr('指标'), _tr('数值')], kpi_rows(d), [6, 8])
            picture(pics.get('hourly'))
            picture(pics.get('wip'))
            note(_tr('在制品为每分钟采样（缓存 + 设备内）的平均值；小时产出、废品率、用电按区间起止的整点快照相减。'))
        elif key == 'bottleneck':
            bn = d['bottleneck']
            heading(_tr('{n}. 瓶颈与时间构成', n=n), 1)
            para(_tr('{verdict}判断把握：{confidence_label}。', verdict=bn['verdict'], confidence_label=bn['confidence_label']))
            picture(pics.get('bottleneck'))
            head, rows = bottleneck_rows(d)
            if rows:
                table(head, rows, [2.2, 5, 2.6, 2, 2, 2.4])
            for it in [x for x in bn['items'][:3] if x.get('evidence_text')]:
                para(_tr('{name} 的上下游旁证：{evidence_text}', name=it['name'], evidence_text=it['evidence_text']), 'List Bullet', size=9.5)
            ex = excluded_text(d)
            if ex:
                para(_tr('未参与瓶颈判断：') + ex + _tr('。'), size=9.5)
            note(_tr('方法：') + bn['note'])
            picture(pics.get('breakdown'))
            head, rows, _ = breakdown_rows(d)
            if rows:
                para(_tr('主要设备时间构成（统计区间内各状态占比）：'))
                table(head, rows)
        elif key == 'flow':
            heading(_tr('{n}. 物料流向', n=n), 1)
            picture(pics.get('sankey'))
            table([_tr('从'), _tr('到'), _tr('件数')], flow_rows(d), [6, 6, 3])
            if d['sankey'].get('loops'):
                lab = {x['name']: x['label'] for x in d['sankey']['nodes']}
                note(_tr('返修等回流画成"（回流）"节点：') + _tr('、').join(f"{lab.get(l['source'], l['source'])} → {lab.get(l['target'], l['target'])}" for l in d['sankey']['loops']))
        elif key == 'energy':
            heading(_tr('{n}. 能耗与电费', n=n), 1)
            a, b = energy_rows(d)
            table([_tr('指标'), _tr('数值')], a, [6, 8])
            picture(pics.get('energy_period'))
            picture(pics.get('energy_station'))
            bp = d['energy'].get('cost_by_period') or {}
            if bp:
                para(_tr('分时电费：') + _tr('，').join(_tr('{k} {v} 元', k=k, v=v) for k, v in bp.items()))
        elif key == 'experiments':
            heading(_tr('{n}. 方案对比', n=n), 1)
            for e in d['experiments']:
                heading(_tr('{name}（每次仿真 {hours:g} 小时 × {reps} 次重复）', name=e['name'], hours=e['hours'], reps=e['reps']), 2)
                head, rows, text = exp_table(e)
                table(head, rows)
                note(_tr('括号内为 95% 置信区间（比例和计数已截到合理范围）；* 表示与基准的配对差显著（区间不含 0）。'))
                for k, _ in CI_CHART_KPIS:
                    picture(pics.get(f"exp{e['id']}_{k}"), 0.92)
                picture(pics.get(f"exp{e['id']}_pareto"), 0.92)
                for tx in text:
                    para(tx, 'List Bullet')
        elif key == 'conclusions':
            heading(_tr('{n}. 结论与建议', n=n), 1)
            for tx in d['conclusions']:
                para(tx, 'List Number')
    heading(_tr('附：统计口径与数据自检'), 1)
    basis = d['summary'].get('basis') or {}
    for k, label in (('counts', _tr('产出与用电')), ('wip', _tr('在制品')), ('lead', _tr('生产周期')), ('bottleneck', _tr('瓶颈'))):
        if basis.get(k):
            para(_tr('{label}：{v}', label=label, v=basis[k]), size=9)
    ck = d['check']
    para(_tr('数据自检：{passed}/{total} 项一致', passed=ck['passed'], total=ck['total']) + (_tr('。') if ck['ok'] else _tr('，有不一致的项目（导出时选择了仍然导出）：')), size=9)
    for c in ck['checks']:
        if not c['ok']:
            para(_tr('不一致：{name}（{detail}）', name=c['name'], detail=c['detail']), size=9, color=RGBColor(0xC8, 0x3A, 0x3A))
    if d['skipped']:
        note(_tr('没有数据、已跳过的章节：') + _tr('；').join(_tr('{label}（{reason}）', label=x['label'], reason=x['reason']) for x in d['skipped']))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------- PPT ----------------
def build_pptx(d, image, template=None):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Emu, Inches, Pt
    pics = make_charts(d)
    branded = template is not None
    prs = template or Presentation()
    if not branded:
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    W, H = prs.slide_width, prs.slide_height
    kx, ky = W / Inches(13.333), H / Inches(7.5)          # 模板不是 16:9 时按比例摆放

    def X(v):
        return Emu(int(Inches(v) * kx))

    def Y(v):
        return Emu(int(Inches(v) * ky))
    ACC = RGBColor(0x1F, 0x5F, 0x99)

    def layout(*names, idx=6):
        for lo in prs.slide_layouts:
            if any(n.lower() in (lo.name or '').lower() for n in names):
                return lo
        return prs.slide_layouts[min(idx, len(prs.slide_layouts) - 1)]

    def txt(slide, x, y, w, h, text, size=14, bold=False, color=None, align=None):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        lines = text if isinstance(text, list) else [text]
        for i, ln in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            r = p.add_run()
            r.text = ln
            r.font.size, r.font.bold = Pt(size), bold
            if not branded:
                r.font.name = FONT
            if color is not None:
                r.font.color.rgb = color
            if align is not None:
                p.alignment = align
        return tb

    def page(title):
        if branded:
            s = prs.slides.add_slide(layout('title only', _tr('仅标题'), _tr('标题'), idx=5))
            if s.shapes.title is not None:
                s.shapes.title.text = title
            else:
                txt(s, X(0.5), Y(0.15), X(12), Y(0.7), title, 26, True)
            for ph in list(s.placeholders):           # 正文占位符不用，去掉（避免空的"单击此处添加文本"）
                if ph.placeholder_format.idx != 0:
                    ph._element.getparent().remove(ph._element)
            return s
        s = prs.slides.add_slide(prs.slide_layouts[6])
        bar = s.shapes.add_shape(1, 0, 0, W, Inches(0.9))
        bar.fill.solid()
        bar.fill.fore_color.rgb = ACC
        bar.line.fill.background()
        txt(s, Inches(0.5), Inches(0.15), Inches(12), Inches(0.7), title, 26, True, RGBColor(0xFF, 0xFF, 0xFF))
        txt(s, Inches(0.5), H - Inches(0.45), Inches(12.3), Inches(0.35),
            _tr('{plant} · 统计区间（仿真时间）{v} — {to} · 导出（北京时间）{exported} · 蜂元虚拟工厂', plant=d['plant'], v=d['from'], to=d['to'], exported=d['exported']), 10, color=RGBColor(0x88, 0x90, 0x98))
        return s

    def picture(s, png, x, y, maxw, maxh):
        if not png:
            return 0
        w, h = image_size(png)
        sc = min(maxw / w, maxh / h)
        pw, ph = int(w * sc), int(h * sc)
        s.shapes.add_picture(io.BytesIO(png), int(x + (maxw - pw) / 2), int(y), Emu(pw), Emu(ph))
        return ph

    def table(s, head, rows, x, y, w, row_h=0.32, size=11):
        rows = rows[:14]
        shp = s.shapes.add_table(len(rows) + 1, len(head), x, y, w, Y(row_h * (len(rows) + 1)))
        tb = shp.table
        for i, h in enumerate(head):
            c = tb.cell(0, i)
            c.text = str(h)
            for p in c.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size, r.font.bold = Pt(size), True
                    if not branded:
                        r.font.name = FONT
        for ri, row in enumerate(rows, 1):
            for ci_, v in enumerate(row):
                c = tb.cell(ri, ci_)
                c.text = '' if v is None else str(v)
                for p in c.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(size)
                        if not branded:
                            r.font.name = FONT
        return tb

    def style_chart(ch, legend=True):
        ch.has_legend = legend
        if legend:
            ch.legend.position = XL_LEGEND_POSITION.BOTTOM
            ch.legend.include_in_layout = False
            ch.legend.font.size = Pt(10)
        return ch
    # 封面
    meta_lines = [_tr('工厂：{plant}\u3000产品：{v}', plant=d['plant'], v=d['product'] or '—'), _tr('仿真时间（模型里的时钟）：{sim_time}', sim_time=d['sim_time']),
                  _tr('统计区间（仿真时间）：{window}', window=d['window']), _tr('导出时间（北京时间）：{exported}{v}', exported=d['exported'], v=_tr('\u3000编制：') + d['author'] if d['author'] else '')]
    if branded:
        s = prs.slides.add_slide(layout('title slide', _tr('标题幻灯片'), idx=0))
        if s.shapes.title is not None:
            s.shapes.title.text = d['title']
        sub = next((ph for ph in s.placeholders if ph.placeholder_format.idx == 1), None)
        if sub is not None:
            sub.text_frame.text = '\n'.join(meta_lines)
        else:
            txt(s, X(0.8), Y(4.6), X(11.7), Y(1.8), meta_lines, 14)
    else:
        s = prs.slides.add_slide(prs.slide_layouts[6])
        bg = s.shapes.add_shape(1, 0, 0, W, H)
        bg.fill.solid()
        bg.fill.fore_color.rgb = ACC
        bg.line.fill.background()
        txt(s, Inches(0.8), Inches(2.2), Inches(11.7), Inches(1.2), d['title'], 40, True, RGBColor(0xFF, 0xFF, 0xFF))
        txt(s, Inches(0.8), Inches(3.6), Inches(11.7), Inches(2), meta_lines, 16, color=RGBColor(0xDD, 0xE8, 0xF3))
    TOP = Y(1.15)
    GREY = RGBColor(0x55, 0x60, 0x6b)
    for key in d['sections']:
        if key == 'layout':
            s = page(_tr('布局'))
            if image:
                picture(s, image, X(0.5), Y(1.1), X(12.3), Y(5.6))
        elif key == 'kpi':
            s = page(_tr('运行概况'))
            rows = kpi_rows(d)[:8]
            for i, (k, v) in enumerate(rows):
                x, y = X(0.5 + (i % 4) * 3.1), Y(1.15 + (i // 4) * 1.25)
                card = s.shapes.add_shape(1, x, y, X(2.95), Y(1.1))
                card.fill.solid()
                card.fill.fore_color.rgb = RGBColor(0xEE, 0xF3, 0xF8)
                card.line.color.rgb = RGBColor(0xC9, 0xD6, 0xE3)
                txt(s, x + X(0.15), y + Y(0.08), X(2.7), Y(0.4), k, 12, color=GREY)
                txt(s, x + X(0.15), y + Y(0.45), X(2.7), Y(0.6), v, 20, True, ACC)
            ser = d['summary']['series']
            if ser:
                cd = CategoryChartData()
                cd.categories = [x['time'][6:] for x in ser]
                cd.add_series(_tr('合格入库'), [x['good'] for x in ser])
                cd.add_series(_tr('报废'), [x['scrap'] for x in ser])
                ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, X(0.5), Y(3.75), X(12.3), Y(3.2), cd).chart
                style_chart(ch)
                ch.has_title = True
                ch.chart_title.text_frame.text = _tr('每小时产出（件）')
                ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
                ch.category_axis.tick_labels.font.size = Pt(9)
                ch.value_axis.tick_labels.font.size = Pt(9)
                ch.plots[0].gap_width = 40
                for ser_, col in zip(ch.plots[0].series, ('3B82C4', 'C8553A')):
                    ser_.format.fill.solid()
                    ser_.format.fill.fore_color.rgb = RGBColor.from_string(col)
        elif key == 'bottleneck':
            bn = d['bottleneck']
            s = page(_tr('瓶颈分析'))
            ph = picture(s, pics.get('bottleneck'), X(0.4), TOP, X(7.9), Y(5.7))
            txt(s, X(8.6), TOP, X(4.4), Y(0.5), _tr('结论（把握：{confidence_label}）', confidence_label=bn['confidence_label']), 16, True, ACC)
            lines = [bn['verdict']]
            ex = excluded_text(d)
            if ex:
                lines.append(_tr('未参与判断：') + ex)
            txt(s, X(8.6), TOP + Y(0.55), X(4.4), Y(4.6), lines, 12)
            txt(s, X(0.5), H - Y(0.95), X(12.3), Y(0.5), _tr('方法：活跃期法（shifting bottleneck）；独占 = 只有它在限制产出，交替 = 与前后瓶颈重叠的转移期。'), 10, color=GREY)
            if d['objects']:
                s = page(_tr('设备时间构成'))
                head, rows, cls = breakdown_rows(d)
                cd = CategoryChartData()
                cd.categories = [o['name'][:12] for o in d['objects'][:12]]
                present = [c for c in cls if any(o['share'].get(c, 0) for o in d['objects'][:12])]
                for c in present:
                    cd.add_series(label(CLS_CN[c]), [round(o['share'].get(c, 0) * 100, 1) for o in d['objects'][:12]])
                ch = s.shapes.add_chart(XL_CHART_TYPE.BAR_STACKED_100, X(0.5), TOP, X(12.3), Y(5.6), cd).chart
                style_chart(ch)
                ch.category_axis.tick_labels.font.size = Pt(10)
                ch.value_axis.tick_labels.font.size = Pt(9)
                ch.category_axis.reverse_order = True
                ch.plots[0].gap_width = 50
                colors = {c['key']: c['color'] for c in analysis.classes()}
                for ser_, c in zip(ch.plots[0].series, present):
                    ser_.format.fill.solid()
                    ser_.format.fill.fore_color.rgb = RGBColor.from_string(colors[c].lstrip('#').upper())
        elif key == 'flow':
            s = page(_tr('物料流向'))
            picture(s, pics.get('sankey'), X(0.4), TOP, X(8.6), Y(5.7))
            fr = flow_rows(d, 8)
            table(s, [_tr('从'), _tr('到'), _tr('件数')], fr, X(9.2), TOP, X(3.8), 0.36, 10)
        elif key == 'energy':
            s = page(_tr('能耗与电费'))
            a, b = energy_rows(d)
            table(s, [_tr('指标'), _tr('数值')], a, X(0.5), TOP, X(4.6), 0.42, 12)
            picture(s, pics.get('energy_period'), X(5.4), TOP, X(7.5), Y(2.6))
            picture(s, pics.get('energy_station'), X(5.4), TOP + Y(2.75), X(7.5), Y(3.0))
        elif key == 'experiments':
            for e in d['experiments']:
                s = page(_tr('方案对比：{name}', name=e['name']))
                head, rows, text = exp_table(e, compact=True)
                two = any(len(str(c)) > 16 for r in rows for c in r)          # 单元格会折行：按两行高估计
                rh = 0.58 if two else 0.36
                table(s, head, rows, X(0.4), TOP, X(12.5), rh, 10 if len(head) > 6 else 12)
                y = TOP + Y(rh * (min(len(rows), 14) + 1) + 0.25)
                txt(s, X(0.5), y, X(12.3), H - y - Y(0.6), [_tr('± 为 95% 置信区间半宽（截到取值范围时写成下限–上限），* 表示与基准的配对差显著。')] + text[:5], 11)
                res = e['result']
                if res.get('kind') == 'optimize':
                    png = pics.get(f"exp{e['id']}_pareto")
                    if png:
                        s = page(_tr('{name}：候选分布', name=e['name']))
                        picture(s, png, X(0.8), TOP, X(11.7), Y(5.7))
                    continue
                cis = [pics.get(f"exp{e['id']}_{k}") for k, _ in CI_CHART_KPIS]
                cis = [x for x in cis if x]
                if cis:
                    s = page(_tr('{name}：均值与 95% 置信区间', name=e['name']))
                    hh = Y(5.7) / len(cis)
                    for i, png in enumerate(cis):
                        picture(s, png, X(0.8), TOP + int(hh * i), X(11.7), hh - Y(0.05))
        elif key == 'conclusions':
            s = page(_tr('结论与建议'))
            lines = [f'{i + 1}. {t}' for i, t in enumerate(d['conclusions'][:10])]
            txt(s, X(0.7), TOP, X(12), Y(5.4), lines, 14 if len(lines) <= 7 else 12)
            ck = d['check']
            txt(s, X(0.7), H - Y(0.95), X(12), Y(0.4), _tr('数据自检：{passed}/{total} 项一致；口径见 Word 版附录。', passed=ck['passed'], total=ck['total']), 10, color=GREY)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---------------- SOP ----------------
def sop_path(pid):
    return os.path.join(SOP_DIR, f"{re.sub(r'[^A-Za-z0-9_.-]', '_', pid)}.json")


def load_sops(pid):
    p = sop_path(pid)
    if not os.path.exists(p):
        return []
    with open(p, encoding='utf-8') as f:
        return json.load(f).get('sops', [])


# ---------------- 示例数据（新装就有，不会覆盖用户自己的数据） ----------------
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'samples')
SAMPLE_SOPS = {'foundry-housing': [{
    'id': 'sop-demo', 'name': '新员工熟悉产线：从铁水到成品', 'desc': '按工艺顺序走一遍：熔炼、球化、造型浇注、冷却、清理、机加、检测、入库。每一步看设备、听讲解。',
    'steps': [
        {'id': 's1', 'title': '中频炉熔炼', 'target': {'block': 'FUR1'}, 'camera': {'mode': 'orbit'}, 'duration_s': None,
         'text': '两台 3 吨中频炉轮流熔化废钢和回炉料。**注意安全线**，出铁前要取样做光谱、测温，铁水温度约 1500 ℃。'},
        {'id': 's2', 'title': '球化孕育', 'target': {'block': 'TRT1'}, 'camera': {'mode': 'orbit'},
         'text': '铁水出到浇包里加球化剂和孕育剂，石墨才会长成球状。球化后要在规定时间内浇完，否则会**球化衰退**。'},
        {'id': 's3', 'title': '造型浇注（全厂瓶颈）', 'target': {'block': 'MOLD1'}, 'camera': {'mode': 'walk'},
         'text': '水平分型造型线每 40 秒出一型、一型两件。这是全厂的瓶颈，它停一分钟全厂就少两件，**设备点检要优先**。'},
        {'id': 's4', 'title': '冷却输送', 'target': {'block': 'COOL1'}, 'camera': {'mode': 'orbit'},
         'text': '铸型在冷却线上冷却约 45 分钟后落砂。冷却不够会导致变形和硬度不合格。'},
        {'id': 's5', 'title': '抛丸清理', 'target': {'block': 'SHOT1'}, 'camera': {'mode': 'orbit'},
         'text': '吊钩抛丸机成批清理铸件表面，同时目视检出冷隔等外观缺陷。'},
        {'id': 's6', 'title': '数控加工', 'target': {'block': 'CNC1'}, 'camera': {'mode': 'walk'},
         'text': '6 台加工中心加工壳体的孔和端面。操作工负责上下料、换刀，**刀具寿命到数必须换**。'},
        {'id': 's7', 'title': '内窥检测', 'target': {'block': 'INS1'}, 'camera': {'mode': 'orbit'},
         'text': '自动内窥检测每个孔的气孔和毛刺。漏检会流到客户，误判会多返修——灵敏度不能随便调。'},
        {'id': 's8', 'title': '成品入库', 'target': {'block': 'ASRS1'}, 'camera': {'mode': 'orbit'},
         'text': 'AGV 把合格品送到立体仓库，每 4 小时发运一次。到这里一件壳体的旅程就结束了。'},
    ]}]}


def sample_sop(rt):
    """"看示例"：示范工厂用内置的 SOP；其他工厂按设备顺序生成一个示例。"""
    if rt.pid in SAMPLE_SOPS:
        return copy.deepcopy(SAMPLE_SOPS[rt.pid][0])
    sts = [s for s in rt.plant.stations.values() if s.kind not in ('crew', 'agv', 'operators', 'transporter')][:8]
    return {'id': 'sop-sample', 'name': _tr('{name} 认识产线（示例）', name=rt.plant.name), 'desc': _tr('自动生成的示例：按设备顺序各看一眼，可以在此基础上改。'),
            'steps': [{'id': f's{i + 1}', 'title': _tr('认识{name}', name=s.name), 'target': {'block': s.id}, 'camera': {'mode': 'orbit'},
                       'text': _tr('这是 **{name}**（{id}）。看看它在流程里的位置、上下游是谁、现在是什么状态。', name=s.name, id=s.id)} for i, s in enumerate(sts)]}


def sample_experiment_files(pid):
    """内置示例实验：samples/experiment_<工厂>.json、experiment_<工厂>_<后缀>.json，每个文件一个已完成的实验。"""
    if not os.path.isdir(SAMPLE_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(SAMPLE_DIR)):
        if not fn.startswith('experiment_') or not fn.endswith('.json'):
            continue
        stem = fn[len('experiment_'):-5]
        if stem == pid or stem.startswith(pid + '__'):
            out.append(os.path.join(SAMPLE_DIR, fn))
    return out


def _sample_lang(e, path):
    """Sample experiment texts in the server language (content map samples/i18n/<file>.en.json; variants/result are JSON strings)."""
    from .i18n import content, default_lang
    lg = default_lang()
    out = dict(content(e, path, lg))
    for k in ('variants', 'result'):
        v = e.get(k)
        if isinstance(v, str):
            try:
                out[k] = json.dumps(content(json.loads(v), path, lg), ensure_ascii=False)
            except ValueError:
                pass
        elif v is not None:
            out[k] = content(v, path, lg)
    return out


def load_sample_experiments(pid, force=False, skip=()):
    """把示例实验写进实验列表（按名称去重，已有的不重复写）。返回写入的个数。"""
    n = 0
    have = {r['name'] for r in store.q('select name from experiments where plant=?', (pid,))}
    for path in sample_experiment_files(pid):
        if os.path.basename(path) in skip:
            continue
        with open(path, encoding='utf-8') as f:
            e = json.load(f)
        e = _sample_lang(e, path)
        if e['name'] in have:
            continue
        store.x('insert into experiments(plant,name,hours,reps,variants,status,progress,result,created,finished,username) values(?,?,?,?,?,?,?,?,?,?,?)',
                (pid, e['name'], e['hours'], e['reps'], e['variants'] if isinstance(e['variants'], str) else json.dumps(e['variants'], ensure_ascii=False),
                 'done', 1, e['result'] if isinstance(e['result'], str) else json.dumps(e['result'], ensure_ascii=False),
                 e.get('created') or store.now(), e.get('finished') or store.now(), server_tr('示例数据')))
        n += 1
    return n


def seed_samples(mgr):
    """示范工厂的示例数据：SOP 一条、已完成的对比实验和优化实验各一个。新装第一次启动时写一次，用户删掉后不再自动补
    （实验面板里的"用示例填充"可以手动再加回来）。"""
    for pid, sops in SAMPLE_SOPS.items():
        if pid in mgr.rts and not os.path.exists(sop_path(pid)) and not store.q("select 1 from settings where k=?", (f'sample_sop:{pid}',), one=True):
            os.makedirs(SOP_DIR, exist_ok=True)
            with open(sop_path(pid), 'w', encoding='utf-8') as f:
                json.dump({'plant': pid, 'sops': sops}, f, ensure_ascii=False, indent=1)
            store.x("insert or replace into settings(k,v) values(?,?)", (f'sample_sop:{pid}', store.now()))
    for pid in mgr.rts:
        key = f'sample_exp2:{pid}'
        if not sample_experiment_files(pid) or store.q("select 1 from settings where k=?", (key,), one=True):
            continue
        old = store.q("select 1 from settings where k=?", (f'sample_exp:{pid}',), one=True)    # 旧版已经写过（或用户删过）对比示例
        load_sample_experiments(pid, skip=(f'experiment_{pid}.json',) if old else ())
        store.x("insert or replace into settings(k,v) values(?,?)", (key, store.now()))


def clean_sops(sops, rt):
    if not isinstance(sops, list):
        raise HTTPException(400, _tr('sops 需要是列表'))
    ids = set(rt.plant.stations) | set(getattr(rt.plant, 'sub_index', {}))
    out = []
    for i, s in enumerate(sops[:100]):
        steps = []
        for j, st in enumerate((s.get('steps') or [])[:200]):
            tgt = st.get('target') or {}
            if tgt.get('block') and tgt['block'] not in ids:
                raise HTTPException(400, _tr('SOP「{get}」第 {v} 步的目标设备 {block} 不存在', get=s.get('name'), v=j + 1, block=tgt['block']))
            cam = st.get('camera') or {}
            steps.append({'id': st.get('id') or f's{j + 1}', 'title': str(st.get('title') or _tr('第 {v} 步', v=j + 1))[:80], 'text': str(st.get('text') or '')[:4000],
                          'target': {'block': tgt.get('block') or None, 'comp': tgt.get('comp') or None},
                          'camera': {'mode': cam.get('mode') if cam.get('mode') in ('orbit', 'walk') else 'orbit',
                                     **{k: [float(x) for x in cam[k]][:3] for k in ('pos', 'look') if isinstance(cam.get(k), list)}},
                          'duration_s': float(st['duration_s']) if st.get('duration_s') not in (None, '') else None,
                          'check': st.get('check') if isinstance(st.get('check'), dict) else {'kind': 'manual'}})
        out.append({'id': s.get('id') or f'sop{i + 1}', 'name': str(s.get('name') or f'SOP {i + 1}')[:80], 'desc': str(s.get('desc') or '')[:2000],
                    'steps': steps, 'updated': store.now()})
    return out


def register(app, mgr):
    from .api2 import need

    def options(pid):
        return {'sections': SECTIONS, 'templates': {k: tpl_info(k) for k in TPL_KIND},
                'experiments': [{'id': e['id'], 'name': e['name'], 'kind': e['result'].get('kind', 'compare'), 'finished': e['finished'],
                                 'variants': len(e['result'].get('rows') or e['result'].get('evals') or []), 'reps': e['reps'], 'hours': e['hours'],
                                 'warnings': (e['result'].get('quality') or {}).get('warnings') or []}
                                for e in experiments_of(pid, ids=[r['id'] for r in store.q("select id from experiments where plant=? and status='done'", (pid,))])]}

    @app.get('/api/p/{pid}/report/export/options')
    async def export_options(pid: str):
        mgr.get(pid)
        seed_once()
        return options(pid)

    @app.get('/api/p/{pid}/report/export/check')
    async def export_check(pid: str, request: Request):
        """导出前预览：统计区间、各章节有没有数据、数据自检结果。"""
        rt = mgr.get(pid)
        d = collect(rt, _q(request))
        return {'window': d['window'], 'from': d['from'], 'to': d['to'], 'sim_time': d['sim_time'], 'exported': d['exported'],
                'sections': d['sections'], 'skipped': d['skipped'], 'check': d['check'],
                'bottleneck': {k: d['bottleneck'][k] for k in ('verdict', 'confidence', 'confidence_label', 'tie')}}

    def export(pid, fmt, opts):
        rt = mgr.get(pid)
        t0 = time.time()
        img = decode_image(opts.get('image')) if opts.get('image') else None
        d = collect(rt, opts)
        if not d['check']['ok'] and not opts.get('force'):
            bad = [c for c in d['check']['checks'] if not c['ok']]
            raise HTTPException(409, _tr('报告数据自检没通过：') + _tr('；').join(_tr('{name}（{detail}）', name=c['name'], detail=c['detail']) for c in bad) + _tr('。可以选择"仍然导出"。'))
        if 'layout' in d['sections'] and img is None:
            try:
                img = render_plan(rt)
            except Exception:
                img = None
            if img is None:
                d['sections'].remove('layout')
                d['skipped'].insert(0, {'key': 'layout', 'label': SECTIONS['layout'], 'reason': _tr('没有截图，服务端也画不出平面图')})
        use_tpl = str(opts.get('template', True)).lower() not in ('0', 'false', 'no', '')
        tpl = None
        if use_tpl and tpl_file(fmt):
            try:
                tpl = open_template(fmt)
            except Exception:
                import logging
                logging.getLogger('vfactory').exception(_tr('公司模板打不开，改用默认样式'))
        data = build_docx(d, img, tpl) if fmt == 'docx' else build_pptx(d, img, tpl)
        mt = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' if fmt == 'docx' else \
            'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        from urllib.parse import quote
        return Response(data, media_type=mt, headers={'Content-Disposition': f'attachment; filename=report-{pid}.{fmt}',
                                                      'X-Report-Ms': str(int((time.time() - t0) * 1000)),
                                                      'X-Report-Image': 'client' if opts.get('image') else ('server' if img else 'none'),
                                                      'X-Report-Template': 'company' if tpl is not None else 'default',
                                                      'X-Report-Check': f"{d['check']['passed']}/{d['check']['total']}",
                                                      'X-Report-Skipped': quote(','.join(x['key'] for x in d['skipped'])),
                                                      'Access-Control-Expose-Headers': 'X-Report-Image, X-Report-Template, X-Report-Check, X-Report-Skipped, X-Report-Ms'})

    def _q(request):
        qp = request.query_params
        o = {k: qp.get(k) for k in ('hours', 'title', 'author', 'experiments', 'warmup', 'template', 'force') if qp.get(k)}
        if qp.get('force'):
            o['force'] = qp['force'] not in ('0', 'false')
        if qp.get('sections'):
            o['sections'] = qp['sections'].split(',')
        return o

    for fmt in ('docx', 'pptx'):
        def mk(fmt):
            async def post_export(pid: str, body: dict = Body(default={})):
                return export(pid, fmt, body or {})

            async def get_export(pid: str, request: Request):
                return export(pid, fmt, _q(request))
            app.post(f'/api/p/{{pid}}/report/export.{fmt}')(post_export)
            app.get(f'/api/p/{{pid}}/report/export.{fmt}')(get_export)
        mk(fmt)

    # ---------------- 公司模板 ----------------
    @app.get('/api/report/templates')
    async def tpl_list():
        return {k: tpl_info(k) for k in TPL_KIND}

    @app.post('/api/report/templates')
    async def tpl_upload(request: Request, body: dict = Body(...)):
        u = need(request, 'engineer')
        kind = body.get('kind')
        name = str(body.get('name') or '')
        ext = os.path.splitext(name.lower())[1]
        if kind not in TPL_KIND:
            raise HTTPException(400, _tr('kind 只能是 docx（Word 模板）或 pptx（PPT 模板）'))
        if ext not in TPL_KIND[kind]:
            raise HTTPException(400, _tr('{v} 模板要用 {join} 文件', v='Word' if kind == 'docx' else 'PPT', join=_tr(' 或 ').join(TPL_KIND[kind])))
        data = str(body.get('data_url') or '')
        try:
            raw = base64.b64decode(data.split(',', 1)[1] if ',' in data else data)
        except ValueError:
            raise HTTPException(400, _tr('文件内容不是有效的 base64'))
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(400, _tr('模板太大（超过 20 MB）'))
        try:
            open_template(kind, raw)
        except Exception as e:
            raise HTTPException(400, _tr('模板打不开：{e}', e=e))
        os.makedirs(TPL_DIR, exist_ok=True)
        for x in TPL_KIND[kind]:
            f = os.path.join(TPL_DIR, f'template{x}')
            if os.path.exists(f):
                os.remove(f)
        with open(os.path.join(TPL_DIR, f'template{ext}'), 'wb') as f:
            f.write(raw)
        with open(os.path.join(TPL_DIR, f'{kind}.json'), 'w', encoding='utf-8') as f:
            json.dump({'name': os.path.basename(name), 'uploaded': store.now(), 'user': u['username']}, f, ensure_ascii=False)
        return {'ok': True, kind: tpl_info(kind)}

    @app.delete('/api/report/templates/{kind}')
    async def tpl_delete(kind: str, request: Request):
        need(request, 'engineer')
        if kind not in TPL_KIND:
            raise HTTPException(404, _tr('没有这种模板'))
        for x in TPL_KIND[kind] + ('.json',):
            f = os.path.join(TPL_DIR, f'template{x}' if x != '.json' else f'{kind}.json')
            if os.path.exists(f):
                os.remove(f)
        return {'ok': True}

    # ---------------- 示例实验："用示例填充" ----------------
    @app.post('/api/p/{pid}/experiments/samples')
    async def exp_samples(pid: str, request: Request):
        need(request, 'engineer')
        mgr.get(pid)
        files = sample_experiment_files(pid)
        if not files:
            raise HTTPException(404, _tr('这个工厂没有内置的示例实验（示范工厂才有）'))
        return {'ok': True, 'added': load_sample_experiments(pid, force=True), 'available': len(files)}

    @app.get('/api/p/{pid}/sop')
    async def sop_get(pid: str):
        mgr.get(pid)
        seed_once()
        return {'sops': load_sops(pid)}

    @app.get('/api/p/{pid}/sop/sample')
    async def sop_sample(pid: str):
        return sample_sop(mgr.get(pid))

    seeded = {'done': False}

    def seed_once():
        if not seeded['done'] and mgr.rts:
            seeded['done'] = True
            try:
                seed_samples(mgr)
            except Exception:
                import logging
                logging.getLogger('vfactory').exception(_tr('示例数据写入失败'))

    @app.middleware('http')
    async def _seed_samples(request, call_next):
        """服务起来后的第一个请求时写入示例数据（工厂这时已经加载）。"""
        if not seeded['done'] and request.url.path.startswith('/api/'):
            seed_once()
        return await call_next(request)

    @app.put('/api/p/{pid}/sop')
    async def sop_put(pid: str, body: dict = Body(...)):
        rt = mgr.get(pid)
        sops = clean_sops(body.get('sops'), rt)
        os.makedirs(SOP_DIR, exist_ok=True)
        tmp = sop_path(pid) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'plant': pid, 'sops': sops}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, sop_path(pid))
        return {'ok': True, 'sops': sops}
