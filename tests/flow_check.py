"""2.0 建模内核测试：旧版迁移一致性、通用块搭建的车间、编辑命令撤销。python tests/flow_check.py"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
import yaml  # noqa: E402

from vfactory.core import Plant  # noqa: E402
from vfactory.flow.model import apply_ops, expand, to_v2, validate  # noqa: E402
from vfactory.history import summary  # noqa: E402

res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300])


root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
legacy = yaml.safe_load(open(os.path.join(root, 'templates', 'integrated.yaml'), encoding='utf-8'))
legacy['plant']['start'] = '2026-11-02T07:00:00'
H = 24
t0 = time.time()
a = Plant(copy.deepcopy(legacy))
a.run_for(H * 3600)
v2 = to_v2(copy.deepcopy(legacy))
b = Plant(copy.deepcopy(v2))
b.run_for(H * 3600)
ka = {k: a.kpi[k] for k in ('castings', 'machined', 'good', 'scrap', 'shipped')}
kb = {k: b.kpi[k] for k in ('castings', 'machined', 'good', 'scrap', 'shipped')}
diff = max(abs(ka[k] - kb[k]) / max(1, ka[k]) for k in ka)
ok('示范工厂迁移到 2.0 结果一致', diff <= 0.03, f'旧 {ka}  新 {kb}  最大偏差 {diff * 100:.2f}%  ({time.time() - t0:.0f}s)')
v = validate(v2)
ok('迁移后模型校验', v['ok'], v['summary'])
ok('迁移后连线数', len(v2['links']) >= 15, f"{len(v2['blocks'])} 块 {len(v2['links'])} 条连线")

# ---- 纯通用块：机加车间 ----
m = {
    'version': 2, 'plant': {'name': '通用块机加车间', 'product': 'HSG-200 壳体', 'seed': 7, 'start': '2026-11-02T07:00:00', 'dt': 1.0, 'speed': 10,
                            'warmup_h': 0, 'floor': [60, 40], 'modbus_port': 5030},
    'areas': [{'name': '收货区', 'x': [0, 12], 'color': '#F2EEE3'}, {'name': '机加区', 'x': [12, 40], 'color': '#E3ECF2'}, {'name': '检测区', 'x': [40, 60], 'color': '#E8E3F2'}],
    'blocks': [
        {'id': 'SRC', 'type': 'source', 'name': '毛坯来料', 'pos': [4, 10], 'size': [4, 4], 'params': {'interval': 'expo(110)', 'lot_prefix': '外协A',
                                                                                                  'defects': [{'name': '气孔', 'prob': '0.03'}]}},
        {'id': 'B0', 'type': 'buffer', 'name': '收货暂存', 'pos': [8, 4], 'size': [3, 3], 'params': {'capacity': 100}},
        {'id': 'B1', 'type': 'buffer', 'name': '线边库', 'pos': [18, 4], 'size': [3, 3], 'params': {'capacity': 20}},
        {'id': 'TR1', 'type': 'transporter', 'name': '叉车', 'pos': [12, 0], 'size': [2, 2], 'params': {'count': 1, 'speed_mps': 1.0, 'capacity': 6}},
        {'id': 'OP1', 'type': 'operators', 'name': 'CNC 操作工', 'pos': [25, 20], 'size': [2, 2], 'params': {'count': 2}},
        *[{'id': f'M{i}', 'type': 'processor', 'name': f'{i}#加工中心', 'pos': [16 + 6 * i, 12], 'size': [4, 3.4],
           'params': {'time': 'normal(300,15)', 'operator': 'OP1', 'operator_mode': 'load', 'load_s': 40, 'mtbf_h': 60, 'mttr_min': 30,
                      'defects': [{'name': '毛刺', 'prob': '0.06'}], 'run_kw': 18},
           'signals': [{'name': 'Spindle/Load', 'unit': '%', 'desc': '主轴负载', 'expr': 'if_(busy, 55 + walk(1.5, -10, 15) + noise(2), 2 + noise(0.3))'}]}
          for i in (1, 2, 3)],
        {'id': 'B2', 'type': 'buffer', 'name': '待检', 'pos': [42, 8], 'size': [3, 3], 'params': {'capacity': 30}},
        {'id': 'QC', 'type': 'inspect', 'name': '在线检测', 'pos': [47, 12], 'size': [4, 4], 'params': {'time': '45', 'pod_pct': 92, 'false_pct': 1}},
        {'id': 'RW', 'type': 'rework', 'name': '返修台', 'pos': [47, 20], 'size': [4, 4], 'params': {'time': 'normal(240,30)', 'fixes': ['毛刺'], 'max_rework': 1}},
        {'id': 'OUT', 'type': 'sink', 'name': '成品库', 'pos': [56, 12], 'size': [6, 6], 'params': {'ship_every_h': 4}},
    ],
    'links': [
        {'id': 'L1', 'from': 'SRC', 'from_port': 'out', 'to': 'B0', 'to_port': 'in'},
        {'id': 'L2', 'from': 'B0', 'from_port': 'out', 'to': 'B1', 'to_port': 'in', 'via': 'TR1'},
        *[{'id': f'L3{i}', 'from': 'B1', 'from_port': 'out', 'to': f'M{i}', 'to_port': 'in'} for i in (1, 2, 3)],
        *[{'id': f'L4{i}', 'from': f'M{i}', 'from_port': 'out', 'to': 'B2', 'to_port': 'in'} for i in (1, 2, 3)],
        {'id': 'L5', 'from': 'B2', 'from_port': 'out', 'to': 'QC', 'to_port': 'in'},
        {'id': 'L6', 'from': 'QC', 'from_port': 'out', 'to': 'OUT', 'to_port': 'in'},
        {'id': 'L7', 'from': 'QC', 'from_port': 'ng', 'to': 'RW', 'to_port': 'in'},
        {'id': 'L8', 'from': 'RW', 'from_port': 'out', 'to': 'B2', 'to_port': 'in'},
    ], 'groups': [], 'notes': [],
}
v = validate(m)
ok('通用块模型校验', v['ok'], v['issues'][:3])
ex = expand(m)
ok('展开为设备和队列', len(ex['stations']) == len(m['blocks']) and 'L5' not in ex['buffers'], f"队列 {list(ex['buffers'])}")
p = Plant(m)
t0 = time.time()
p.run_for(8 * 3600)
r = summary(p)
k = p.kpi
ok('通用块车间跑 8 小时', k['good'] > 100, f"来料 {k['castings']} 合格入库 {k['good']} 报废 {k['scrap']} 漏检 {k['escape']} 发运 {k['shipped']}  ({time.time() - t0:.0f}s)")
ok('瓶颈分析', r['bottleneck'], [(x['name'], x['run']) for x in r['bottleneck'][:3]])
st = {s.id: s.state for s in p.stations.values()}
ok('状态含饥饿/阻塞', any(x in ('Starved', 'Blocked') for x in [s for t, i, s in p.state_log]), st)
ok('自定义点位在算', abs(p.stations['M1'].tags['Spindle/Load'].value) > 0, p.stations['M1'].tags['Spindle/Load'].value)
ok('人员池', p.stations['OP1'].tags['Crew/Busy'].value >= 0, p.stations['OP1'].tags['Crew/OnDuty'].value)
ok('搬运车队', p.stations['TR1'].trips > 5, f"{p.stations['TR1'].trips} 趟")
ok('返修回路', p.stations['RW'].count > 0, f"返修 {p.stations['RW'].count} 件")
# ---- 编辑命令 ----
m2, inv = apply_ops(m, [{'op': 'add_block', 'block': {'id': 'M4', 'type': 'processor', 'name': '4#', 'pos': [34, 18], 'size': [4, 3], 'params': {}}},
                        {'op': 'update_block', 'id': 'M1', 'set': {'params.time': 'normal(280,10)', 'name': '1#高速加工中心'}},
                        {'op': 'remove_link', 'id': 'L8'}])
m3, _ = apply_ops(m2, inv)
ok('编辑命令可撤销', json.dumps(m3, sort_keys=True, ensure_ascii=False) == json.dumps(m, sort_keys=True, ensure_ascii=False), f'{len(inv)} 条逆命令')
bad = [n for n, g in res if not g]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '、'.join(bad)) if bad else '')
