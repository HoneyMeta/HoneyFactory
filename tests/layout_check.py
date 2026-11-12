"""平面布局与 AGV 路网（离线）：python tests/layout_check.py
画一个 L 形路网，车队必须沿路网走（车辆坐标始终在路网折线上），单向边不能逆行；没画路网时走直线。"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import math
import sys

sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from vfactory.core import Plant  # noqa: E402

res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:200])


def model(paths=None, oneway=False):
    blocks = [
        {'id': 'SRC', 'type': 'source', 'name': '来料', 'pos': [0, 0], 'size': [3, 3], 'params': {'interval': '20', 'batch': 1}},
        {'id': 'BA', 'type': 'buffer', 'name': '起点库', 'pos': [4, 0], 'size': [3, 3], 'params': {'capacity': 50}},
        {'id': 'BB', 'type': 'buffer', 'name': '终点库', 'pos': [30, 20], 'size': [3, 3], 'params': {'capacity': 500}},
        {'id': 'OUT', 'type': 'sink', 'name': '出口', 'pos': [36, 20], 'size': [3, 3], 'params': {}},
        {'id': 'TR', 'type': 'transporter', 'name': '车队', 'pos': [4, 4], 'size': [2, 2], 'params': {'count': 1, 'speed_mps': 1.0, 'capacity': 2, 'load_s': 5}},
    ]
    links = [{'id': 'L1', 'kind': 'material', 'from': 'SRC', 'to': 'BA'}, {'id': 'L2', 'kind': 'material', 'from': 'BA', 'to': 'BB', 'via': 'TR'},
             {'id': 'L3', 'kind': 'material', 'from': 'BB', 'to': 'OUT'}]
    plant = {'name': '路网测试', 'seed': 3, 'start': '2026-11-02T07:00:00', 'dt': 1.0, 'warmup_h': 0, 'floor': [40, 30]}
    if paths:
        plant['layout'] = {'paths': paths}
    return {'version': 2, 'plant': plant, 'areas': [], 'blocks': blocks, 'links': links, 'groups': [], 'notes': []}


# L 形：(4,0) → (4,20) → (30,20)
NET = {'nodes': [{'id': 'N1', 'x': 4, 'y': 0}, {'id': 'N2', 'x': 4, 'y': 20}, {'id': 'N3', 'x': 30, 'y': 20}],
       'edges': [{'id': 'E1', 'a': 'N1', 'b': 'N2'}, {'id': 'E2', 'a': 'N2', 'b': 'N3'}]}


def on_net(x, y):
    segs = [((4, 0), (4, 20)), ((4, 20), (30, 20))]
    best = 1e9
    for (ax, ay), (bx, by) in segs:
        L2 = (bx - ax) ** 2 + (by - ay) ** 2
        t = max(0, min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
        best = min(best, math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay))))
    return best


p = Plant(model(NET))
tr = p.stations['TR']
worst, moving = 0.0, 0
for _ in range(1800):
    p.step()
    for v in tr.vehicles:
        if v['phase']:
            moving += 1
            worst = max(worst, on_net(v['x'], v['y']))
ok('沿路网行驶（离路网最远距离）', moving > 100 and worst < 0.05, f'{worst:.3f} m，移动 {moving} 步')
ok('车队完成搬运', tr.trips > 3 and len(p.buffers['BB']) + p.kpi.get('good', 0) > 0, f'{tr.trips} 趟')
path = tr._path(4, 0, 30, 20)
ok('最短路经过拐点', path[2] == (4.0, 20.0) or (4.0, 20.0) in path, path)

# 单向：N2→N1 不允许，从 N3 回 N1 只能走另一条边（这里没有）——4.7 起不再直线穿行，走不通返回 None
net2 = {'nodes': NET['nodes'], 'edges': [{'id': 'E1', 'a': 'N1', 'b': 'N2', 'oneway': True}, {'id': 'E2', 'a': 'N2', 'b': 'N3'}]}
p2 = Plant(model(net2))
back = p2.stations['TR']._path(30, 20, 4, 0)
ok('单向边不能逆行（走不通，不再直线穿行）', back is None, back)
fwd = p2.stations['TR']._path(4, 0, 30, 20)
ok('单向边可以顺行', fwd and (4.0, 20.0) in fwd, fwd)
# 运行：送到终点库后空车回不去 → 车停下（Blocked）报警，不离开路网、不穿墙
tr2 = p2.stations['TR']
worst2 = 0.0
for _ in range(1500):
    p2.step()
    for v in tr2.vehicles:
        worst2 = max(worst2, on_net(v['x'], v['y']) if v['phase'] else 0)
st2 = [v for v in tr2.vehicles if v['phase'] == 'stuck']
ok('回程走不通：车停下、状态 Blocked', st2 and st2[0]['state'] == 'Blocked' and tr2.state == 'Blocked', [(v['phase'], v['state']) for v in tr2.vehicles])
ok('回程走不通：报警写清楚哪里回不去', tr2.alarm == '终点库无法返回起点库，请补充返回道路', tr2.alarm)
ok('回程走不通：一直在路网上（没有直线穿行）', worst2 < 0.05, f'{worst2:.3f} m')
ok('回程走不通：报警记进事件日志（只记一次）', sum(1 for e in p2.events if e.get('kind') == 'alarm' and '无法返回' in e.get('msg', '')) == 1,
   [e.get('msg') for e in p2.events if e.get('kind') == 'alarm'][:3])
# 一开始就送不过去（去程单向线方向反了）：在取料点停下，不装车
net5 = {'nodes': NET['nodes'], 'edges': [{'id': 'E1', 'a': 'N2', 'b': 'N1', 'oneway': True}, {'id': 'E2', 'a': 'N2', 'b': 'N3'}]}
p5 = Plant(model(net5))
for _ in range(600):
    p5.step()
v5 = p5.stations['TR'].vehicles[0]
ok('去程走不通：停在取料点报警、不装车', v5['phase'] == 'stuck' and not v5['load'] and p5.stations['TR'].alarm == '起点库无法到达终点库，请补充道路', (v5['phase'], len(v5['load']), p5.stations['TR'].alarm))

p3 = Plant(model(None))
ok('没画路网走直线', p3.stations['TR']._path(4, 0, 30, 20) == [(4, 0), (30, 20)])
# 限速：E1 限速 0.25 m/s（车队 1 m/s），用时变长，但仍走同一条路
net3 = {'nodes': NET['nodes'], 'edges': [{'id': 'E1', 'a': 'N1', 'b': 'N2', 'vmax': 0.25}, {'id': 'E2', 'a': 'N2', 'b': 'N3'}]}
tA = Plant(model(NET)).stations['TR']
tB = Plant(model(net3)).stations['TR']
va, vb = {'x': 4.0, 'y': 0.0}, {'x': 4.0, 'y': 0.0}
Ta, Da = tA._travel(va, 30, 20)
Tb, Db = tB._travel(vb, 30, 20)
ok('边限速：同样的路走得更慢', abs(Da - Db) < 1e-6 and Tb > Ta + 50, f'{Ta:.0f}s → {Tb:.0f}s')
tB._place(vb, 0.5)
ok('限速段按用时放车（一半用时还在限速段上）', abs(vb['x'] - 4) < 1e-6 and vb['y'] < 20, (vb['x'], vb['y']))

# 站点绑定设备：终点是 BB 时停在绑定的站点 N3' (28,20)，而不是 BB 中心
net4 = {'nodes': [{'id': 'N1', 'x': 4, 'y': 0}, {'id': 'N2', 'x': 4, 'y': 20}, {'id': 'S1', 'x': 28, 'y': 20, 'kind': 'station', 'block': 'BB'}],
        'edges': [{'id': 'E1', 'a': 'N1', 'b': 'N2'}, {'id': 'E2', 'a': 'N2', 'b': 'S1'}]}
p4 = Plant(model(net4))
r4 = p4.stations['TR']._path(4, 0, 30, 20)
ok('站点绑定设备：车停在站点上', r4[-1] == (28.0, 20.0), r4)
for _ in range(1500):
    p4.step()
ok('绑定站点后照常搬运', p4.stations['TR'].trips > 3, p4.stations['TR'].trips)

# 路网检查（模型检查里的"路网"类）
from vfactory.flow.model import validate  # noqa: E402
iss = lambda m: [i for i in validate(m)['issues'] if i['cat'] == '路网']
ok('路网检查：正常路网没有问题', not iss(model(NET)), iss(model(NET)))
dead = {'nodes': NET['nodes'] + [{'id': 'S9', 'x': 30, 'y': 30, 'kind': 'station'}],
        'edges': NET['edges'] + [{'id': 'E9', 'a': 'N3', 'b': 'S9', 'oneway': True}]}
msgs = ' | '.join(i['msg'] for i in iss(model(dead)))
ok('路网检查：单向死路', '单向死路' in msgs and any(i['id'] == 'path:S9' for i in iss(model(dead))), msgs)
oneway_back = {'nodes': NET['nodes'], 'edges': [{'id': 'E1', 'a': 'N1', 'b': 'N2', 'oneway': True}, {'id': 'E2', 'a': 'N2', 'b': 'N3', 'oneway': True}]}
ib = [i for i in iss(model(oneway_back)) if '无法返回' in i['msg']]
ok('路网检查：车队空车返回走不通 = 错误，指出缺哪段路', ib and ib[0]['level'] == 'error' and '终点库无法返回起点库' in ib[0]['msg'] and '缺少从' in ib[0]['msg']
   and '请补充返回道路' in ib[0]['msg'] and ib[0]['id'] == 'L2', ib)
ok('路网检查：有错误时模型检查不通过', validate(model(oneway_back))['ok'] is False)
ib2 = [i for i in iss(model(net2)) if '无法返回' in i['msg']]
ok('路网检查：建议把反向的单向线改成双向', ib2 and '单向线 E1' in ib2[0]['msg'] and '改成双向' in ib2[0]['msg'], ib2 and ib2[0]['msg'])
ib5 = [i for i in iss(model(net5)) if i['level'] == 'error']
ok('路网检查：去程走不通 = 错误', any('起点库无法到达终点库' in i['msg'] for i in ib5), [i['msg'] for i in ib5])
ok('没画路网：没有路网错误（允许直线）', not [i for i in iss(model(None)) if i['level'] == 'error'])
island = {'nodes': NET['nodes'] + [{'id': 'S5', 'x': 50, 'y': 50, 'kind': 'station', 'block': 'NOPE'}], 'edges': NET['edges']}
msgs = ' | '.join(i['msg'] for i in iss(model(island)))
ok('路网检查：孤立站点、绑定的设备不存在', '没有连到路网' in msgs and '不存在' in msgs, msgs)

bad = [n for n, g in res if not g]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '、'.join(bad)) if bad else '')
