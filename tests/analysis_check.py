"""专业仿真功能离线测试（不需要启动服务）：python tests/analysis_check.py [--quick]

覆盖：时间构成统计与预热截断、独立随机流（公共随机数）、实验方案表 + 重复 + 95% 置信区间、优化（帕累托前沿）、
桑基图、甘特图（设备/订单/零件）、能耗（按状态功率、峰值需量、分时电价、碳排）、数据表（导入、来料按订单表、tbl()、工艺路线/BOM 导入）、
故障口径（运行/日历）、顺序相关换型矩阵、操作工技能、子模型（含两层嵌套）、DXF 解析、从此刻推演。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import asyncio
import copy
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
QUICK = '--quick' in sys.argv

from vfactory import analysis, datatables  # noqa: E402
from vfactory.core import Plant  # noqa: E402
from vfactory.flow.model import expand, validate  # noqa: E402

res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300], flush=True)


def shop(seed=7, extra=None):
    """通用块机加车间（同 flow_check）。"""
    m = {
        'version': 2, 'plant': {'name': '测试车间', 'product': 'A', 'seed': seed, 'start': '2026-11-02T07:00:00', 'dt': 1.0, 'speed': 10, 'warmup_h': 1,
                                'floor': [60, 40], 'modbus_port': 6090},
        'areas': [],
        'blocks': [
            {'id': 'SRC', 'type': 'source', 'name': '来料', 'pos': [4, 10], 'size': [4, 4],
             'params': {'interval': 'expo(110)', 'products': [{'code': 'A', 'weight': 2}, {'code': 'B', 'weight': 1}], 'defects': [{'name': '气孔', 'prob': '0.03'}]}},
            {'id': 'B1', 'type': 'buffer', 'name': '线边库', 'pos': [12, 4], 'size': [3, 3], 'params': {'capacity': 20}},
            {'id': 'OP1', 'type': 'operators', 'name': '操作工', 'pos': [25, 20], 'size': [2, 2], 'params': {'count': 2}},
            *[{'id': f'M{i}', 'type': 'processor', 'name': f'{i}#加工中心', 'pos': [16 + 6 * i, 12], 'size': [4, 3.4],
               'params': {'time': 'normal(300,15)', 'operator': 'OP1', 'operator_mode': 'load', 'load_s': 40, 'mtbf_h': 20, 'mttr_min': 30, 'run_kw': 18,
                          'idle_kw': 3, 'defects': [{'name': '毛刺', 'prob': '0.06'}]}} for i in (1, 2, 3)],
            {'id': 'B2', 'type': 'buffer', 'name': '待检', 'pos': [42, 8], 'size': [3, 3], 'params': {'capacity': 30}},
            {'id': 'QC', 'type': 'inspect', 'name': '检测', 'pos': [47, 12], 'size': [4, 4], 'params': {'time': '45', 'pod_pct': 92, 'false_pct': 1}},
            {'id': 'RW', 'type': 'rework', 'name': '返修', 'pos': [47, 20], 'size': [4, 4], 'params': {'time': 'normal(240,30)', 'fixes': ['毛刺']}},
            {'id': 'OUT', 'type': 'sink', 'name': '成品库', 'pos': [56, 12], 'size': [6, 6], 'params': {'ship_every_h': 2}},
        ],
        'links': [
            {'id': 'L1', 'from': 'SRC', 'from_port': 'out', 'to': 'B1', 'to_port': 'in'},
            *[{'id': f'L3{i}', 'from': 'B1', 'from_port': 'out', 'to': f'M{i}', 'to_port': 'in'} for i in (1, 2, 3)],
            *[{'id': f'L4{i}', 'from': f'M{i}', 'from_port': 'out', 'to': 'B2', 'to_port': 'in'} for i in (1, 2, 3)],
            {'id': 'L5', 'from': 'B2', 'from_port': 'out', 'to': 'QC', 'to_port': 'in'},
            {'id': 'L6', 'from': 'QC', 'from_port': 'out', 'to': 'OUT', 'to_port': 'in'},
            {'id': 'L7', 'from': 'QC', 'from_port': 'ng', 'to': 'RW', 'to_port': 'in'},
            {'id': 'L8', 'from': 'RW', 'from_port': 'out', 'to': 'B2', 'to_port': 'in'},
        ], 'groups': [], 'notes': [],
        'plan': {'shifts': [{'name': '早班', 'start': '07:00', 'end': '15:00'}, {'name': '中班', 'start': '15:00', 'end': '23:00'}]},
    }
    if extra:
        extra(m)
    return m


def main():
    t_all = time.time()
    # ---------------- 1. 时间构成 + 预热截断 ----------------
    p = Plant(shop())
    p.run_for(18 * 3600)
    t0, t1 = analysis.window(p, hours=0, warmup=True)
    ok('预热截断：统计从预热结束开始', t0 == 3600 and t1 == p.t, (t0, t1))
    s = analysis.stats(p, t0, t1)
    m1 = next(o for o in s['objects'] if o['id'] == 'M1')
    ok('时间构成：各类别占比合计为 1', abs(sum(m1['share'].values()) - 1) < 1e-6, m1['share'])
    ok('时间构成：含运行/缺料/故障等类别', {'run'} <= set(m1['share']) and len(m1['share']) >= 3, sorted(m1['share']))
    ok('时间构成：非班次（23:00–01:00）单独统计，约 2 小时', abs(m1['seconds'].get('offshift', 0) - 7200) < 120, m1['seconds'].get('offshift'))
    ok('统计：在制品/周期/OEE', s['plant']['wip_avg'] is not None and s['plant']['lead_mean_h'] and m1['oee'] is not None,
       {k: s['plant'][k] for k in ('good', 'good_per_h', 'wip_avg', 'wip_max', 'lead_mean_h', 'lead_p90_h', 'oee_avg')})
    sec = sum(m1['seconds'].values())
    ok('时间构成：总时长 = 统计区间', abs(sec - (t1 - t0)) < 2, (sec, t1 - t0))
    s_all = analysis.stats(p, *analysis.window(p, 0, warmup=False))
    ok('不截预热时区间更长', s_all['hours'] > s['hours'], (s_all['hours'], s['hours']))

    # ---------------- 1b. 同一份统计（报告一致性）、瓶颈（活跃期法）、报告自检 ----------------
    from vfactory import history  # noqa: E402
    sm = history.summary(p, t0, t1)
    s2 = analysis.stats(p, t0, t1, s=sm)
    ok('一致性：时间构成页与报表概况的在制品、产出、生产周期是同一个数', s2['plant']['wip_avg'] == sm['wip_avg'] and s2['plant']['good'] == sm['good']
       and s2['plant']['lead_p90_h'] == sm['lead']['p90_h'], (s2['plant']['wip_avg'], sm['wip_avg']))
    ok('一致性：结论里的在制品数字 = 概况表', any(f"在制品平均 {sm['wip_avg']} 件" in f for f in sm['findings']), sm['findings'][-1:])
    en_ = analysis.energy(p, t0, t1)
    ok('一致性：能耗章节总用电 = 概况总用电（±0.5%）', abs(en_['kwh'] - sm['energy_total']) <= max(1, 0.005 * en_['kwh']), (en_['kwh'], sm['energy_total']))
    tw0, tw1 = analysis.window(p, 5)
    ok('统计区间起点对齐整点（产出按整点快照相减才精确）', tw0 % 3600 == 0 and tw1 == p.t, (tw0, tw1))
    sm5 = history.summary(p, tw0, tw1)
    ok('小时产出 = 区间内合格数 ÷ 区间时长', abs(sm5['good_per_h'] - sm5['good'] / ((tw1 - tw0) / 3600)) < 0.01, (sm5['good'], sm5['good_per_h']))
    bn = sm['bottleneck_analysis']
    ok('瓶颈：活跃期法给出排名、独占/交替与结论', bn['method'] == 'active_period' and bn['items'] and bn['verdict'] and
       all(abs(it['share'] - it['sole'] - it['shifting']) < 0.002 for it in bn['items']), [(it['name'], it['share'], it['sole'], it['shifting']) for it in bn['items'][:3]])
    ok('瓶颈：同组设备合成一组、被动对象说明原因', any(e_['kind'] == 'passive' for e_ in bn['excluded']) and set(bn['by_station']) >= {'M1', 'M2', 'M3', 'QC'},
       [e_['name'] + '：' + e_['reason'] for e_ in bn['excluded']])
    ok('瓶颈：结论第一句就是瓶颈分析的结论', sm['findings'][0].startswith(bn['verdict'][:12]), sm['findings'][0][:60])
    sb, tl = analysis.shifting_bottleneck({'A': [[0, 10]], 'B': [[5, 20]]})
    ok('活跃期法：瞬时瓶颈与转移期（A 0–5 独占，5–10 交替，B 10–20 独占）', sb['A'] == {'momentary': 5, 'sole': 5, 'shifting': 5} and
       sb['B'] == {'momentary': 15, 'sole': 10, 'shifting': 5} and [x[0] for x in tl] == ['A', 'B'], sb)
    from datetime import datetime
    from types import SimpleNamespace

    def fake(logs, kinds):
        fp = SimpleNamespace(class_log=sorted((t, sid, c) for sid, L in logs.items() for t, c in L), cfg={}, buffers={}, hourly=[], t0=datetime(2026, 11, 2, 7))
        objs = [{'id': k, 'name': k + '机', 'kind': kinds.get(k, 'processor'), 'group': k, 'passive': False, 'share': {'run': 0.9, 'idle': 0.1}} for k in logs]
        return analysis.bottleneck(fp, 0, 1000, objs)
    near = fake({'A': [(0, 'run'), (500, 'idle'), (510, 'run')], 'B': [(0, 'run'), (495, 'idle'), (505, 'run')], 'C': [(0, 'run'), (100, 'idle')],
                 'F': [(0, 'run')]}, {'F': 'furnace'})
    ok('瓶颈：前两名差距 < 5 个百分点写"并列瓶颈"', near['tie'] and set(near['top']) == {'A', 'B'} and '并列瓶颈' in near['verdict'] and near['confidence'] == 'low',
       near['verdict'])
    ok('瓶颈：连续运行设备（中频炉）排除并写明原因', any(e_['id'] == 'F' and '保温' in e_['reason'] for e_ in near['excluded']) and 'F' not in near['top'], near['excluded'][:1])
    clear = fake({'A': [(0, 'run')], 'B': [(0, 'run'), (100, 'idle'), (200, 'run'), (300, 'idle')]}, {})
    ok('瓶颈：差距明显时只有一个瓶颈、把握高', clear['top'] == ['A'] and not clear['tie'] and clear['confidence'] == 'high', clear['verdict'])

    from vfactory import report_export as RX  # noqa: E402
    real_exps = RX.experiments_of
    RX.experiments_of = lambda pid, ids=None: []
    rt_ = SimpleNamespace(pid='t', plant=p, cfg={'plant': {'product': 'A'}})
    d_ = RX.collect(rt_, {'hours': 0, 'sections': ['kpi', 'bottleneck', 'flow', 'energy', 'experiments', 'conclusions']})
    ok('报告自检：各处数字一致（全部通过）', d_['check']['ok'], [c_ for c_ in d_['check']['checks'] if not c_['ok']])
    ok('报告：没有实验时"方案对比"章节跳过（不导出空页）', 'experiments' not in d_['sections'] and any(x['key'] == 'experiments' for x in d_['skipped']), d_['skipped'])
    ok('报告：抬头区分仿真时间和导出时间', d_['sim_time'] and d_['exported'] and d_['window'].startswith(sm['from']), (d_['sim_time'], d_['exported']))
    import io as _io
    from docx import Document as _Doc
    from pptx import Presentation as _Prs
    dx_ = _Doc(_io.BytesIO(RX.build_docx(d_, None)))
    alltx = '\n'.join(x.text for x in dx_.paragraphs)
    ok('Word：嵌入图表（小时产出、在制品、瓶颈、时间构成、桑基图、能耗）', len(dx_.inline_shapes) >= 6, len(dx_.inline_shapes))
    ok('Word：写明仿真时间与导出时间（北京时间）、附统计口径与自检', '仿真时间' in alltx and '导出时间（北京时间）' in alltx and '数据自检' in alltx, '')
    d_['check'] = dict(d_['check'], ok=False, checks=d_['check']['checks'] + [{'name': '人为制造的不一致', 'ok': False, 'detail': 'x'}])
    ok('Word：自检不通过且强制导出时，附录列出不一致项', '人为制造的不一致' in '\n'.join(x.text for x in _Doc(_io.BytesIO(RX.build_docx(d_, None))).paragraphs), '')
    pr_ = _Prs(_io.BytesIO(RX.build_pptx(d_, None)))
    npic = sum(1 for sl in pr_.slides for sh in sl.shapes if sh.shape_type == 13)
    nch = sum(1 for sl in pr_.slides for sh in sl.shapes if sh.has_chart)
    ok('PPT：原生图表 + 图片图表', nch >= 2 and npic >= 3, (nch, npic))
    RX.experiments_of = real_exps

    # ---------------- 2. 独立随机流 / 公共随机数 ----------------
    def crn(seed=7, more_defects=False):
        def ex(m):
            for b_ in m['blocks']:
                if b_['id'] == 'M1':
                    b_['params']['mtbf_h'] = 1.5
                    if more_defects:                      # 多一条缺陷规则：M1 的质量随机流多消耗随机数
                        b_['params']['defects'] = b_['params']['defects'] + [{'name': '划伤', 'prob': '0.2'}]
        q = Plant(shop(seed=seed, extra=ex))
        q.run_for(8 * 3600)
        return [e['repair_min'] for e in q.events if e['kind'] == 'fault' and e['station'] == 'M1'][:4], q.stations['M1']
    fa, ra_ = crn()
    fb, _ = crn(more_defects=True)
    ok('公共随机数：改质量规则不影响 M1 的故障随机流（修复时长序列相同）', fa == fb and len(fa) >= 2, (fa, fb))
    ok('故障用独立随机流（不是质量随机流）', ra_.failure.rng is not ra_.rng and ra_.rng_route is not ra_.rng, '')
    fc, _ = crn(seed=8)
    ok('换种子后随机流不同', fc != fa, (fa, fc))

    # ---------------- 3. 故障口径：运行时间 vs 日历时间 ----------------
    def fail_count(basis):
        def ex(m):
            m['blocks'][0]['params']['interval'] = 'expo(900)'         # 来料少 → 加工块大部分时间在等料
            for b_ in m['blocks']:
                if b_['type'] == 'processor':
                    b_['params'].update(mtbf_h=4, fail_basis=basis)
        q = Plant(shop(extra=ex))
        q.run_for(24 * 3600)
        return sum(1 for e in q.events if e['kind'] == 'fault')
    fo, fcal = fail_count('operating'), fail_count('calendar')
    ok('故障按日历时间计：等料时也老化，故障更多', fcal > fo, f'运行时间口径 {fo} 次，日历时间口径 {fcal} 次')

    # ---------------- 4. 换型矩阵 + 操作工技能 ----------------
    def ex_setup(mx):
        def f(m):
            for b_ in m['blocks']:
                if b_['type'] == 'processor':
                    b_['params'].update(setup_min=1, setup_matrix=mx, mtbf_h=0)
        return f
    q1 = Plant(shop(extra=ex_setup({})))
    q1.run_for(8 * 3600)
    q2 = Plant(shop(extra=ex_setup({'A': {'B': 20}, 'B': {'A': 2}})))
    q2.run_for(8 * 3600)
    st1 = sum(analysis.class_durations(q1, 0, q1.t).get(f'M{i}', {}).get('setup', 0) for i in (1, 2, 3))
    st2 = sum(analysis.class_durations(q2, 0, q2.t).get(f'M{i}', {}).get('setup', 0) for i in (1, 2, 3))
    ok('顺序相关换型矩阵生效（A→B 20 分钟）', st2 > st1 * 3 and st1 > 0, f'统一 1 分钟：{st1 / 60:.0f} min；矩阵：{st2 / 60:.0f} min')
    b_ = q2.stations['M1']
    b_.last_product = 'B'
    ok('换型矩阵查表：B→A = 2 分钟，* 通配回退', b_.setup_needed({'type': 'A'}) == 120 and b_.setup_needed({'type': 'A'}) == 0, '')


    def ex_skill(eff):
        def f(m):
            for b_ in m['blocks']:
                if b_['type'] == 'operators':
                    b_['params']['workers'] = [{'name': '张三', 'skills': ['M1', 'M2'], 'eff': eff}, {'name': '李四', 'skills': ['M3'], 'eff': eff}]
                if b_['type'] == 'processor':
                    b_['params'].update(operator_mode='full', mtbf_h=0)
        return f
    k1 = Plant(shop(extra=ex_skill(1.0)))
    k1.run_for(6 * 3600)
    k2 = Plant(shop(extra=ex_skill(1.6)))
    k2.run_for(6 * 3600)
    c1 = sum(k1.stations[f'M{i}'].count for i in (1, 2, 3))
    c2 = sum(k2.stations[f'M{i}'].count for i in (1, 2, 3))
    ok('操作工技能与效率：效率 1.6 产出更多', c2 > c1 * 1.15, f'效率 1.0：{c1} 件；1.6：{c2} 件')
    op = k1.stations['OP1']
    op.busy, op.busy_w = [], []
    g1 = op.acquire('M3', 'M3')
    g2 = op.acquire('M3', 'M3')
    ok('技能匹配：M3 只能派李四一个人', g1 and not g2 and op.busy_w == [1], (g1, g2, op.busy_w))

    # ---------------- 5. 能耗 ----------------
    def ex_power(m):
        for b_ in m['blocks']:
            if b_['type'] == 'processor':
                b_['params']['power_by_state'] = {'starved': 0.5, 'blocked': 0.5, 'failed': 0}
    pe = Plant(shop(extra=ex_power))
    pe.run_for(10 * 3600)
    e = analysis.energy(pe, *analysis.window(pe, 0))
    ok('能耗：总电量、电费、碳排', e['kwh'] > 0 and e['cost'] > 0 and abs(e['co2_kg'] - e['kwh'] * 0.5703) < 1, {k: e[k] for k in ('kwh', 'cost', 'co2_kg', 'avg_price')})
    ok('能耗：15 分钟峰值需量 ≥ 平均功率', e['peak_kw'] >= e['kwh'] / e['hours'] - 1e-6, (e['peak_kw'], round(e['kwh'] / e['hours'], 1)))
    ok('能耗：分时电价按时段拆分', len(e['cost_by_period']) >= 2 and abs(sum(e['kwh_by_period'].values()) - e['kwh']) < 1, e['cost_by_period'])
    ok('能耗：按状态拆分（运行/缺料…）', 'run' in e['by_cls'] and abs(sum(e['by_cls'].values()) - e['kwh']) / e['kwh'] < 0.08, (e['by_cls'], e['kwh']))
    m1e = next(x for x in e['by_station'] if x['id'] == 'M1')
    dur = analysis.class_durations(pe, *analysis.window(pe, 0))['M1']
    exp_starved = dur.get('starved', 0) / 3600 * 0.5
    ok('按状态功率覆盖生效（缺料 0.5 kW）', abs(m1e['by_cls'].get('starved', 0) - exp_starved) < 0.05 + exp_starved * 0.05, (m1e['by_cls'].get('starved'), round(exp_starved, 2)))
    cheap = analysis.energy(pe, *analysis.window(pe, 0), settings={**analysis.DEFAULT_ENERGY, 'tou': [], 'default_price': 0.1})
    ok('电价设置可改（统一 0.1 元）', abs(cheap['cost'] - cheap['kwh'] * 0.1) < 0.5, cheap['cost'])

    # ---------------- 6. 桑基图 + 甘特图 ----------------
    sk = analysis.sankey(p, *analysis.window(p, 0))
    names = {n['name'] for n in sk['nodes']}
    ok('桑基图：节点与流量', {'SRC', 'M1', 'QC', 'OUT'} <= names and sk['links'] and sk['parts'] > 50, (len(sk['nodes']), len(sk['links']), sk['parts']))
    ok('桑基图：返修回流拆成无环', any(n['name'].endswith('↺') for n in sk['nodes']) and sk['loops'], sk['loops'])
    src_out = sum(l['value'] for l in sk['links'] if l['source'] == 'SRC')
    ok('桑基图：来料流出 ≈ 区间内到货件数', src_out > 0, src_out)
    g = analysis.gantt_resource(p, *analysis.window(p, hours=4))
    ok('甘特图（按设备）：区间不重叠且在窗口内', g['items'] and all(g['t0'] <= it[1] < it[2] <= g['t1'] for it in g['items']), (len(g['rows']), len(g['items'])))
    by_row = {}
    for it in g['items']:
        by_row.setdefault(it[0], []).append(it)
    ok('甘特图：每行区间首尾相接', all(abs(sum(x[2] - x[1] for x in v) - (g['t1'] - g['t0'])) < 2 for v in by_row.values()), '')
    gp = analysis.gantt_orders(p, *analysis.window(p, hours=4), by='part', limit=20)
    ok('甘特图（按零件）', gp['rows'] and gp['items'] and gp['stations'], (len(gp['rows']), len(gp['items'])))

    # ---------------- 7. 数据表：来料按订单表、tbl()、导入、路线/BOM ----------------
    csv_text = '时间,产品,数量,订单\n0,A,5,SO-1\n0.5,B,3,SO-2\n1.0,A,4,SO-3\n2026-11-02 09:00,B,2,SO-4\n'
    t = datatables.parse_file('orders.csv', csv_text.encode('utf-8'))
    ok('CSV 导入（中文列名、数字转换）', t['columns'] == ['时间', '产品', '数量', '订单'] and t['rows'][1]['数量'] == 3, t['rows'][:2])
    gbk = datatables.parse_file('o.csv', '产品,工时\nA,100\n'.encode('gbk'))
    ok('GBK 编码 CSV', gbk['rows'][0]['工时'] == 100, gbk)
    from openpyxl import Workbook  # noqa: E402
    wb = Workbook()
    ws = wb.active
    ws.append(['产品', '工时'])
    ws.append(['A', 250])
    ws.append(['B', 400])
    xf = os.path.join(tempfile.gettempdir(), 'vf_tbl_test.xlsx')
    wb.save(xf)
    tx = datatables.parse_file('工时.xlsx', open(xf, 'rb').read())
    ok('Excel 导入', tx['rows'] == [{'产品': 'A', '工时': 250}, {'产品': 'B', '工时': 400}], tx)


    def ex_tables(m):
        m['tables'] = [{'name': '订单', **t}, {'name': '工时', **tx}]
        m['blocks'][0]['params'] = {'table': '订单'}
        for b_ in m['blocks']:
            if b_['type'] == 'processor':
                b_['params'].update(time="tbl('工时', item.get('type'), '工时')", mtbf_h=0)
    pt = Plant(shop(extra=ex_tables))
    pt.run_for(3 * 3600)
    orders = {}
    for x in pt.parts.values():
        if x.get('order'):
            orders[x['order']] = orders.get(x['order'], 0) + 1
    ok('来料按订单表放料（数量、订单号）', orders == {'SO-1': 5, 'SO-2': 3, 'SO-3': 4, 'SO-4': 2} and pt.kpi['castings'] == 14, orders)
    cyc = [h.get('cycle') for x in pt.parts.values() for h in x.get('history', []) if h['event'] == 'processed' and h['station'].startswith('M') and x.get('type') == 'B']
    ok('tbl() 查表：B 产品工时 400 s', cyc and all(abs(c - 400) < 1 for c in cyc), cyc[:5])
    gp2 = analysis.gantt_orders(pt, 0, pt.t, by='order')
    ok('甘特图（按订单）', {r['id'] for r in gp2['rows']} == {'SO-1', 'SO-2', 'SO-3', 'SO-4'} and gp2['items'], [(r['id'], r['parts']) for r in gp2['rows']])
    rt_tab = datatables.normalize(['产品', '工序号', '设备', '工时', '换型'], [['A', 10, 'M1', 200, 5], ['A', 20, 'QC', 30, ''], ['B', 10, '2#加工中心', 'normal(500,20)', 8], ['C', 10, 'M9', 1, '']])
    ro = datatables.routing_ops(shop(), rt_tab)
    ok('工艺路线表 → 编辑命令（按产品用时、换型矩阵）', any(o['id'] == 'M1' and o['set']['params.times_by_product'] == {'A': 200} for o in ro['ops'])
       and any(o['id'] == 'M2' and o['set']['params.setup_matrix']['*'] == {'B': 8} for o in ro['ops']), ro['ops'])
    ok('工艺路线表校验：未知设备报错', any('M9' in i['msg'] for i in ro['issues']), ro['issues'])
    from vfactory.flow.model import apply_ops  # noqa: E402
    m_r, _ = apply_ops(shop(), ro['ops'])
    pr = Plant(m_r)
    pr.run_for(2 * 3600)
    cyc_a = [h.get('cycle') for x in pr.parts.values() for h in x.get('history', []) if h['event'] == 'processed' and h['station'] == 'M1' and x.get('type') == 'A']
    ok('导入的工艺路线生效（M1 加工 A 用 200 s）', cyc_a and all(abs(c - 200) < 1 for c in cyc_a), cyc_a[:4])
    bom_tab = datatables.normalize(['父件', '子件', '数量'], [['总成X', '壳体', 1], ['总成X', '轴', 2]])


    def asm_model():
        return {'version': 2, 'plant': {'name': '装配', 'seed': 3, 'start': '2026-11-02T07:00:00', 'warmup_h': 0}, 'areas': [],
                'blocks': [{'id': 'S1', 'type': 'source', 'name': '壳体', 'pos': [0, 0], 'params': {'interval': '60', 'products': [{'code': '壳体'}]}},
                           {'id': 'S2', 'type': 'source', 'name': '轴', 'pos': [0, 5], 'params': {'interval': '25', 'products': [{'code': '轴'}]}},
                           {'id': 'B', 'type': 'buffer', 'name': '料箱', 'pos': [5, 3], 'params': {'capacity': 500}},
                           {'id': 'ASM', 'type': 'assembly', 'name': '装配台', 'pos': [10, 3], 'params': {'time': '30'}},
                           {'id': 'OUT', 'type': 'sink', 'name': '出口', 'pos': [15, 3], 'params': {}}],
                'links': [{'id': 'a', 'from': 'S1', 'from_port': 'out', 'to': 'B', 'to_port': 'in'}, {'id': 'b', 'from': 'S2', 'from_port': 'out', 'to': 'B', 'to_port': 'in'},
                          {'id': 'c', 'from': 'B', 'from_port': 'out', 'to': 'ASM', 'to_port': 'in'}, {'id': 'd', 'from': 'ASM', 'from_port': 'out', 'to': 'OUT', 'to_port': 'in'}]}
    bo = datatables.bom_ops(asm_model(), bom_tab)
    ok('BOM 表 → 装配块参数', bo['ops'] and bo['ops'][0]['set']['params.bom'] == {'壳体': 1, '轴': 2}, bo)
    ma, _ = apply_ops(asm_model(), bo['ops'])
    pa = Plant(ma)
    pa.run_for(2 * 3600)
    fg = [x for x in pa.parts.values() if x.get('status') in ('FG',)]
    ok('按 BOM 装配：每件总成 = 1 壳体 + 2 轴', fg and all(x['type'] == '总成X' and len(x.get('children', [])) == 2 for x in fg)
       and all(pa.parts[c]['type'] == '轴' for x in fg for c in x['children'] if c in pa.parts), (len(fg), fg[0].get('children') if fg else None))

    # ---------------- 8. 子模型（两层嵌套） ----------------
    cell = {'id': 'CELL', 'name': '加工单元', 'blocks': [
        {'id': 'Q', 'type': 'buffer', 'name': '单元缓存', 'pos': [0, 0], 'params': {'capacity': 6}},
        {'id': 'P1', 'type': 'processor', 'name': '粗加工', 'pos': [4, 0], 'params': {'time': '200', 'mtbf_h': 0}},
        {'id': 'P2', 'type': 'processor', 'name': '精加工', 'pos': [8, 0], 'params': {'time': '150', 'mtbf_h': 0}}],
        'links': [{'id': 'i1', 'from': 'Q', 'from_port': 'out', 'to': 'P1', 'to_port': 'in'}, {'id': 'i2', 'from': 'P1', 'from_port': 'out', 'to': 'P2', 'to_port': 'in'}],
        'expose': [{'name': 'rough', 'label': '粗加工用时', 'default': '200', 'targets': ['P1.time']}]}
    line = {'id': 'LINE', 'name': '双单元产线', 'blocks': [
        {'id': 'C1', 'type': 'submodel', 'name': '单元1', 'pos': [0, 0], 'params': {'def': 'CELL', 'values': {'rough': '120'}}},
        {'id': 'C2', 'type': 'submodel', 'name': '单元2', 'pos': [12, 0], 'params': {'def': 'CELL'}}],
        'links': [{'id': 'j1', 'from': 'C1', 'from_port': 'out', 'to': 'C2', 'to_port': 'in'}]}
    msub = {'version': 2, 'plant': {'name': '子模型', 'seed': 5, 'start': '2026-11-02T07:00:00', 'warmup_h': 0}, 'areas': [], 'submodels': [cell, line],
            'blocks': [{'id': 'SRC', 'type': 'source', 'name': '来料', 'pos': [0, 0], 'params': {'interval': '180'}},
                       {'id': 'L', 'type': 'submodel', 'name': '产线', 'pos': [20, 0], 'params': {'def': 'LINE'}},
                       {'id': 'OUT', 'type': 'sink', 'name': '出口', 'pos': [40, 0], 'params': {}}],
            'links': [{'id': 'k1', 'from': 'SRC', 'from_port': 'out', 'to': 'L', 'to_port': 'in'}, {'id': 'k2', 'from': 'L', 'from_port': 'out', 'to': 'OUT', 'to_port': 'in'}]}
    v = validate(msub)
    ok('子模型：模型校验通过', v['ok'], v['issues'])
    exs = expand(msub)
    top_ids = [x['id'] for x in exs['stations']]
    lst = next(x for x in exs['stations'] if x['id'] == 'L')
    ok('子模型展开：顶层只有 3 个块，内部嵌在 _children（两层）', top_ids == ['SRC', 'L', 'OUT'] and [c['id'] for c in lst['_children']] == ['L_C1', 'L_C2']
       and [c['id'] for c in lst['_children'][0]['_children']] == ['L_C1_Q', 'L_C1_P1', 'L_C1_P2'], top_ids)
    ok('子模型：暴露参数覆盖到内部块', lst['_children'][0]['_children'][1]['time'] == '120' and lst['_children'][1]['_children'][1]['time'] == '200', '')
    ps = Plant(msub)
    ps.run_for(6 * 3600)
    ok('子模型运行：零件穿过两层子模型到出口', ps.kpi['good'] > 50 and ps.find('L_C2_P2').count > 50 and ps.stations['L'].count == ps.find('L_C2_P2').count,
       f"合格 {ps.kpi['good']}，内部 {ps.find('L_C2_P2').count}")
    ok('子模型：内部块不在顶层 stations（模型结构不变）', set(ps.stations) == {'SRC', 'L', 'OUT'} and 'L_C1_P1' in ps.sub_index, sorted(ps.sub_index)[:4])
    e2 = analysis.energy(ps, 0, ps.t)
    tot_st = sum(s_.energy_kwh for s_ in ps.stations.values())
    ok('子模型能耗不重复计算', abs(e2['kwh'] - tot_st) < 0.5, (e2['kwh'], round(tot_st, 2)))
    sks = analysis.sankey(ps, 0, ps.t, level='station')
    ok('子模型：桑基图可按内部块展开', any(n['name'] == 'L_C1_P1' for n in sks['nodes']), [n['name'] for n in sks['nodes']])
    sk_b = analysis.sankey(ps, 0, ps.t, level='block')
    ok('子模型：桑基图按顶层块汇总', {n['name'] for n in sk_b['nodes']} >= {'SRC', 'L'} and not any('_' in n['name'] for n in sk_b['nodes']), [n['name'] for n in sk_b['nodes']])
    bad = copy.deepcopy(msub)
    bad['blocks'][1]['params']['def'] = 'NOPE'
    ok('子模型：引用不存在的定义时报错', not validate(bad)['ok'], validate(bad)['issues'][:1])

    # ---------------- 9. DXF ----------------
    from vfactory.dxf import convert, to_svg  # noqa: E402
    DXF = """0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n2\nCOL\n10\n0\n20\n0\n0\nLWPOLYLINE\n8\n柱\n90\n4\n70\n1\n10\n-200\n20\n-200\n10\n200\n20\n-200\n10\n200\n20\n200\n10\n-200\n20\n200\n0\nENDBLK\n0\nENDSEC
    0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n墙\n10\n0\n20\n0\n11\n60000\n21\n0\n0\nLINE\n8\n墙\n10\n60000\n20\n0\n11\n60000\n21\n30000\n0\nLWPOLYLINE\n8\n墙\n90\n3\n70\n0\n10\n60000\n20\n30000\n10\n0\n20\n30000\n42\n0\n10\n0\n20\n0\n0\nCIRCLE\n8\n设备\n10\n10000\n20\n10000\n40\n1000\n0\nARC\n8\n设备\n10\n30000\n20\n10000\n40\n2000\n50\n0\n51\n180\n0\nPOLYLINE\n8\n通道\n66\n1\n70\n0\n0\nVERTEX\n10\n5000\n20\n20000\n0\nVERTEX\n10\n55000\n20\n20000\n0\nSEQEND\n0\nINSERT\n2\nCOL\n8\n柱\n10\n20000\n20\n15000\n41\n1\n42\n1\n50\n45\n0\nTEXT\n8\n文字\n10\n1000\n20\n29000\n40\n500\n1\n机加车间\n0\nENDSEC\n0\nEOF\n"""
    dx = convert(DXF)
    ok('DXF：单位 mm → m，外包尺寸 60×30 m', abs(dx['w'] - 60) < 1e-6 and abs(dx['h'] - 30) < 1e-6 and dx['unit'] == 'mm', (dx['w'], dx['h'], dx['unit']))
    ok('DXF：直线/多段线/圆/圆弧/旧式多段线/块引用都解析', dx['layers'].get('墙') == 3 and dx['layers'].get('设备') == 2 and dx['layers'].get('通道') == 1 and dx['layers'].get('柱') == 1, dx['layers'])
    col_ = next(pl for pl in dx['polylines'] if pl['layer'] == '柱')
    cx = sum(p_[0] for p_ in col_['pts']) / len(col_['pts'])
    ok('DXF：块引用平移+旋转（柱子中心在 20 m）', abs(cx - 20) < 0.01 and abs(max(p_[0] for p_ in col_['pts']) - min(p_[0] for p_ in col_['pts']) - 0.5657) < 0.01, cx)
    ok('DXF：y 轴翻转（图纸上方 → 平面图上方）', dx['texts'] and abs(dx['texts'][0]['y'] - 1.0) < 1e-6 and dx['texts'][0]['text'] == '机加车间', dx['texts'])
    svg = to_svg(dx)
    ok('DXF → SVG', svg.startswith('<svg') and svg.count('<poly') == len(dx['polylines']) and '机加车间' in svg, len(svg))
    ok('DXF：图层过滤', convert(DXF, layers=['墙'])['layers'] == {'墙': 3}, convert(DXF, layers=['墙'])['layers'])
    try:
        convert('hello')
        ok('DXF：不是 DXF 时报中文错误', False)
    except ValueError as ex:
        ok('DXF：不是 DXF 时报中文错误', 'DXF' in str(ex), ex)


    # ---------------- 10. 实验：方案表 + 重复 + 置信区间；优化：帕累托 ----------------
    from vfactory import experiment as X  # noqa: E402
    X.store.x = lambda *a, **k: None                                    # 离线：不写数据库
    X.store.now = lambda: '2026-11-02 07:00:00'
    saved = {}
    X.store.x = lambda sql, args=(): saved.__setitem__('last', (sql, args))
    vs = X.expand_factors([{'label': 'B1容量', 'type': 'buffer', 'name': 'B1', 'levels': [10, 40]},
                           {'label': 'M1故障间隔', 'type': 'param', 'station': 'M1', 'key': 'mtbf_h', 'levels': [10, 60]}])
    ok('方案表：2×2 全因子 + 基准 = 5 个方案', len(vs) == 5 and vs[0]['changes'] == [] and vs[4]['changes'][1]['value'] == 60, [v['name'] for v in vs])
    c95 = X.ci([10, 12, 14])
    ok('95% 置信区间（t 分布）', abs(c95['half'] - 4.303 * 2 / 3 ** 0.5) < 1e-3 and c95['lo'] < 12 < c95['hi'], c95)
    cs = X.ci([0.0, 0.0, 0.1], X.BOUNDS['scrap_rate'])
    cc = X.ci([0, 0, 9], X.BOUNDS['escape'])
    ok('置信区间：比例、计数的下限截到 0（不出负数）并标记', cs['lo'] == 0 and cs['clamped'] and cc['lo'] == 0 and cc['hi'] > cc['mean'], (cs, cc))
    ok('置信区间：比例上限不超过 100%', X.ci([0.9, 1.0, 1.0], X.BOUNDS['scrap_rate'])['hi'] <= 1.0, X.ci([0.9, 1.0, 1.0], X.BOUNDS['scrap_rate']))
    q2 = X.quality([{'name': 'A', 'ci': {'good_per_h': X.ci([10, 14])}}], 2, 4)
    ok('可信度：重复 2 次、区间宽、时长短 → 警告并给出建议重复次数', not q2['ok'] and q2['recommended_reps'] >= 5 and len(q2['warnings']) >= 3, q2)
    q5 = X.quality([{'name': 'A', 'ci': {'good_per_h': X.ci([40, 41, 40.5, 39.8, 40.2])}}], 5, 24)
    ok('可信度：5 次重复、区间窄 → 不报警', q5['ok'] and q5['recommended_reps'] == 5, q5)
    old = {'rows': [{'name': 'A', 'ci': {'scrap_rate': {'n': 2, 'mean': 0.03, 'lo': -0.063, 'hi': 0.12, 'half': 0.093, 'sd': 0.01}}}], 'reps': 2}
    X.annotate(old, 12)
    ok('旧实验结果读出时补截断和提示', old['rows'][0]['ci']['scrap_rate']['lo'] == 0 and old['quality']['warnings'], old['quality']['warnings'][:1])
    vm = {'plant': {'name': 'v'}, 'blocks': [{'id': 'X'}], 'links': []}
    vc, rest = X.variant_cfg({'plant': {'name': 'cur', 'seed': 1}, 'blocks': [], 'links': [], 'plan': {'shifts': []}},
                             [{'type': 'version', 'n': 3}, {'type': 'param', 'station': 'X', 'key': 'k', 'value': 1}], lambda n: vm)
    ok('方案 = 模型版本 #n：换成那个版本的模型、沿用当前计划，其余改动照做', vc['blocks'] == [{'id': 'X'}] and vc['plan'] == {'shifts': []} and rest[0]['type'] == 'param', vc)
    pc = X.apply_changes({'blocks': [], 'links': [], 'plan': {}}, [{'type': 'plan', 'shifts': [{'name': '早班', 'start': '07:00', 'end': '15:00'}], 'workdays': [1, 2, 3, 4, 5]}])
    ok('方案 = 换班次/计划', pc['plan']['workdays'] == [1, 2, 3, 4, 5] and len(pc['plan']['shifts']) == 1 and '周一至周五' in X.plan_text({'type': 'plan', **pc['plan']}), X.plan_text({'type': 'plan', **pc['plan']}))
    cfg_x = shop()
    H = 3 if QUICK else 6
    REPS = 3


    async def exp():
        variants = [{'name': '基准', 'changes': []}, {'name': '加一台', 'changes': [{'type': 'add', 'template': 'M1', 'count': 1}]},
                    {'name': '只开 7–10 点', 'changes': [{'type': 'plan', 'shifts': [{'name': '短班', 'start': '07:00', 'end': '10:00'}]}]}]
        await X.run_experiment(1, cfg_x, H, REPS, variants, 42, 1)
        return json.loads(saved['last'][1][0])
    t_e = time.time()
    r = asyncio.run(exp())
    row = r['rows'][1]
    ok('实验：每方案 3 次重复、各有均值与 95% 区间', r['reps'] == 3 and row['ci']['good']['n'] == 3 and row['ci']['good']['lo'] <= row['ci']['good']['mean'] <= row['ci']['good']['hi'],
       {k: row['ci']['good'][k] for k in ('mean', 'lo', 'hi')})
    ok('实验：不同重复用不同种子，方案间同一组种子（公共随机数）', [x['seed'] for x in row['reps']] == [42, 1042, 2042] == [x['seed'] for x in r['rows'][0]['reps']], '')
    ok('实验：与基准的配对差及显著性', 'significant' in row['diff']['good_per_h'] and row['diff']['good_per_h']['n'] == 3, row['diff']['good_per_h'])
    ok('实验：新指标（电费、峰值、碳排、P90）', all(row['kpi'].get(k) is not None for k in ('energy_cost', 'peak_kw', 'co2_kg', 'lead_p90')), {k: row['kpi'][k] for k in ('energy_cost', 'peak_kw', 'co2_kg', 'lead_p90')})
    one = r['rows'][2]
    ok('实验：班次方案（只开 7–10 点）跑得通，产出低于两班', one['kpi']['good'] < r['rows'][0]['kpi']['good'], (one['kpi']['good'], r['rows'][0]['kpi']['good']))
    ok('实验：结果带可信度评估，区间不越界', 'quality' in r and all(c_['lo'] is None or c_['lo'] >= 0 for rr in r['rows'] for c_ in rr['ci'].values()), r['quality'])
    csv_ = X.export_csv(r)
    xl = X.export_xlsx(r, '测试')
    ok('实验导出 CSV / Excel', '95%下限' in csv_ and '每次重复' not in csv_ and len(xl) > 4000, (len(csv_), len(xl)))
    print(f'   （实验耗时 {time.time() - t_e:.0f}s）')


    async def opt():
        spec = {'hours': 2 if QUICK else 4, 'reps': 1, 'budget': 10 if QUICK else 14, 'pop': 5, 'method': 'ga', 'warmup_h': 0.5,
                'params': [{'kind': 'buffer', 'name': 'B2', 'lo': 2, 'hi': 30, 'step': 7}, {'kind': 'add', 'template': 'M1', 'lo': 0, 'hi': 2},
                           {'kind': 'param', 'station': 'QC', 'key': 'time', 'levels': [30, 45, 60]}],
                'objectives': [{'key': 'good_per_h', 'sense': 'max'}, {'key': 'wip_avg', 'sense': 'min'}],
                'constraints': [{'key': 'scrap_rate', 'op': '<=', 'value': 0.2}]}
        await X.run_optimization(2, cfg_x, spec)
        return json.loads(saved['last'][1][0])
    t_o = time.time()
    o = asyncio.run(opt())
    ok('优化：完成并给出推荐解', o.get('kind') == 'optimize' and o.get('best') and len(o['evals']) >= 8, o.get('text') or o)
    fr = [e_ for e_ in o['evals'] if e_['front']]

    def dom(x, f):
        a, b = x['kpi'], f['kpi']
        return a['good_per_h'] >= b['good_per_h'] and a['wip_avg'] <= b['wip_avg'] and (a['good_per_h'] > b['good_per_h'] or a['wip_avg'] < b['wip_avg'])
    dominated = any(dom(x, f) for f in fr for x in o['evals'] if x['feasible'] and x is not f)
    ok('优化：帕累托前沿互不支配', fr and not dominated, [(f['values'], f['kpi']['good_per_h'], f['kpi']['wip_avg']) for f in fr])
    ok('优化：候选不重复', len({tuple(e_['genome']) for e_ in o['evals']}) == len(o['evals']), len(o['evals']))
    print(f'   （优化耗时 {time.time() - t_o:.0f}s）')

    # ---------------- 11. 从此刻推演 ----------------
    from vfactory import fork as F  # noqa: E402
    pf = Plant(shop())
    pf.run_for(4 * 3600)
    pf.step_hooks.append(lambda: None)                         # 模拟外部回调（协议层），推演副本里应被去掉
    k_before = dict(pf.kpi)
    blob = F.snapshot_blob(pf)
    ok('推演：当前状态可序列化、原工厂回调保留', len(blob) > 1000 and len(pf.step_hooks) == 1 and pf.kpi == k_before, f'{len(blob) // 1024} KB')
    ra = F.run_fork(blob, 3, [])
    rb = F.run_fork(blob, 3, [])
    ok('推演：同一状态快进两次结果完全一致（可复现）', ra['kpi'] == rb['kpi'], ra['kpi']['good'])
    rc = F.run_fork(blob, 3, [{'type': 'enable', 'station': 'M2', 'value': False}, {'type': 'enable', 'station': 'M3', 'value': False}])
    ok('推演：停两台加工中心产量下降', rc['kpi']['good'] < ra['kpi']['good'] * 0.8, (ra['kpi']['good'], rc['kpi']['good']))
    pf.run_for(3 * 3600)
    ok('推演：基准副本 = 原工厂继续运行（同随机数）', pf.kpi['good'] - k_before['good'] == ra['kpi']['good'], (pf.kpi['good'] - k_before['good'], ra['kpi']['good']))


    async def fk():
        pf2 = Plant(shop())
        pf2.run_for(4 * 3600)
        return await F.fork(pf2, 2, [{'type': 'param', 'station': 'QC', 'key': 'time', 'value': 90}, {'type': 'setpoint', 'station': 'M1', 'tag': 'Setpoint/SpeedPct', 'value': 140}], reps=3)
    fr_ = asyncio.run(fk())
    row_g = next(x for x in fr_['rows'] if x['key'] == 'good')
    ok('推演接口：3 次重复的均值、区间与配对差', row_g['base']['n'] == 3 and row_g['diff']['n'] == 3 and fr_['text'], fr_['text'])
    ok('推演：错误改动给出中文原因', F.apply_live(Plant(shop()), [{'type': 'param', 'station': 'NOPE', 'key': 'x', 'value': 1}]) == ['没有设备 NOPE'], '')

    bad = [n for n, g_ in res if not g_]
    print(f'\n{len(res) - len(bad)}/{len(res)} 通过（{time.time() - t_all:.0f}s）', ('；失败：' + '、'.join(bad)) if bad else '')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
