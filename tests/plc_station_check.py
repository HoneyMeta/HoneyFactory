"""4.3 PLC 作为独立设备的离线测试（不用启动服务）：python tests/plc_station_check.py [-v]

覆盖：PLC 控制一台通用加工设备（Enable 允许运行、Count 计数、Fault/Reset）、一台 PLC 控制两台设备、
旧的控制单元模型自动迁移（单元 + PLC 块 + 信号线，程序照常运行）、15 个实训场景迁移后能建厂运行、
带 PLC 块的工厂能 pickle（从此刻推演用）。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import copy
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from vfactory.core import Plant  # noqa: E402
from vfactory.plc.migrate import migrate_model, plc_of_cell, set_cell_program  # noqa: E402

VERBOSE = '-v' in sys.argv
res = []


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    if VERBOSE or not cond:
        print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300])


def model(blocks, links):
    return {'version': 2, 'plant': {'name': 'PLC 测试', 'seed': 7, 'start': '2026-11-02T08:00:00', 'dt': 1.0, 'speed': 1, 'warmup_h': 0, 'floor': [60, 30]},
            'areas': [{'name': '区', 'x': [0, 60]}], 'blocks': blocks, 'links': links, 'groups': [], 'notes': []}


def B(id_, type_, x, **params):
    return {'id': id_, 'type': type_, 'name': id_, 'pos': [x, 10], 'size': [3, 3], 'rot': 0, 'params': params}


def mat(i, a, b):
    return {'id': i, 'kind': 'material', 'from': a, 'from_port': 'out', 'to': b, 'to_port': 'in'}


def run(plant, s):
    for _ in range(int(s)):
        plant.step()


def count(st):
    return int(getattr(st, 'count', 0) or 0)


PROG = {'lang': 'ST', 'vars': [{'name': 'Allow', 'type': 'BOOL'}, {'name': 'DoReset', 'type': 'BOOL'}, {'name': 'Seen', 'type': 'INT'}],
        'source': 'M1_Enable := Allow;\nM1_Reset := DoReset;\nSeen := M1_Count;\n'}
SIG = [{'point': 'Running', 'ch': 'I0.0', 'dir': 'in'}, {'point': 'Fault', 'ch': 'I0.1', 'dir': 'in'}, {'point': 'Count', 'ch': 'IW64', 'dir': 'in'},
       {'point': 'Enable', 'ch': 'Q0.0', 'dir': 'out'}, {'point': 'Reset', 'ch': 'Q0.1', 'dir': 'out'}]

# ============================================================ 1. PLC 控制一台加工设备
m = model([B('SRC', 'source', 2, interval='10'), B('M1', 'processor', 10, time='20', mtbf_h=0), B('OUT', 'sink', 20),
           {'id': 'PLC1', 'type': 'plc', 'name': 'PLC1', 'pos': [10, 20], 'size': [1.2, 0.6], 'params': {'scan_ms': 20, 'program': PROG}}],
          [mat('L1', 'SRC', 'M1'), mat('L2', 'M1', 'OUT'), {'id': 'S1', 'kind': 'signal', 'from': 'M1', 'to': 'PLC1', 'signals': SIG}])
p = Plant(m)
plc, m1 = p.find('PLC1'), p.find('M1')
ok('plc 块建成 PLC 运行时并运行', plc is not None and plc.plc is not None and plc.plc.state == 'RUN', getattr(getattr(plc, 'plc', None), 'last_compile', None))
run(p, 2)
ok('信号线接好：I/O 表按 设备_点位 命名、地址来自通道', [(e['name'], e['addr']) for e in plc.io] ==
   [('M1_Running', '%IX0.0'), ('M1_Fault', '%IX0.1'), ('M1_Count', '%IW64'), ('M1_Enable', '%QX0.0'), ('M1_Reset', '%QX0.1')], plc.io)
ok('设备知道自己被 PLC 控制（_plc_wired 含 Enable）', 'Enable' in (getattr(m1, '_plc_wired', None) or ()) and m1._plcs == ['PLC1'])
run(p, 120)
ok('Enable=0：设备不开工', count(m1) == 0, (count(m1), m1.state))
plc.plc.write('Allow', True)
run(p, 200)
c1 = count(m1)
ok('Enable=1：设备开始加工，Count 增加', c1 >= 5, (c1, m1.state))
ok('PLC 读到 Count', plc.plc.value('Seen') == c1 or abs(plc.plc.value('Seen') - c1) <= 1, (plc.plc.value('Seen'), c1))
ok('PLC 读到 Running', plc.plc.value('M1_Running') in (True, False))
plc.plc.write('Allow', False)
run(p, 60)
c2 = count(m1)
run(p, 120)
ok('Enable 再变 0：做完手上的件后不再开工', count(m1) - c2 <= 1, (c2, count(m1)))
plc.plc.write('Allow', True)
m1.inject('failure')
run(p, 3)
ok('设备故障 → PLC 的 M1_Fault = TRUE', plc.plc.value('M1_Fault') is True, (m1.state, getattr(m1.failure, 'repair_left', None)))
plc.plc.write('DoReset', True)
run(p, 3)
plc.plc.write('DoReset', False)
run(p, 3)
ok('PLC 输出 Reset 上升沿：故障清除', plc.plc.value('M1_Fault') is False and m1.failure.repair_left <= 0, (m1.state, m1.failure.repair_left))
plc.plc.stop()
run(p, 3)
ok('PLC 停止：输出为 0（Enable=0）', plc.plc.outputs.get('M1_Enable') is False)

# ============================================================ 2. 一台 PLC 控制两台设备
PROG2 = {'lang': 'ST', 'source': 'M1_Enable := TRUE;\nM2_Enable := M1_Count >= 3;\n'}
m = model([B('SRC', 'source', 2, interval='5'), B('M1', 'processor', 10, time='10'), B('M2', 'processor', 15, time='10'), B('OUT', 'sink', 20),
           {'id': 'PLC1', 'type': 'plc', 'name': 'PLC1', 'pos': [10, 20], 'size': [1.2, 0.6], 'params': {'program': PROG2}}],
          [mat('L1', 'SRC', 'M1'), mat('L2', 'M1', 'M2'), mat('L3', 'M2', 'OUT'),
           {'id': 'S1', 'kind': 'signal', 'from': 'M1', 'to': 'PLC1', 'signals': [{'point': 'Count', 'ch': 'IW64', 'dir': 'in'}, {'point': 'Enable', 'ch': 'Q0.0', 'dir': 'out'}]},
           {'id': 'S2', 'kind': 'signal', 'from': 'M2', 'to': 'PLC1', 'signals': [{'point': 'Enable', 'ch': 'Q0.1', 'dir': 'out'}]}])
p = Plant(m)
plc, m1, m2 = p.find('PLC1'), p.find('M1'), p.find('M2')
before = None
for _ in range(400):
    p.step()
    if count(m1) < 3 and count(m2) > 0:
        before = (count(m1), count(m2))
ok('一台 PLC 接两台设备：两条信号线都接上', sorted(plc.devices) == ['M1', 'M2'], plc.devices)
ok('M2 在 M1 做满 3 件之前不开工', before is None, before)
ok('M1 做满 3 件后 M2 开工', count(m1) >= 3 and count(m2) >= 1, (count(m1), count(m2)))

# ============================================================ 2b. HMI 块：网络线连到 PLC 就绑定它
m = model([B('SRC', 'source', 2, interval='5'), B('M1', 'processor', 10, time='10'), B('OUT', 'sink', 20),
           {'id': 'PLC1', 'type': 'plc', 'name': 'PLC1', 'pos': [10, 20], 'size': [1.2, 0.6], 'params': {'program': {'lang': 'ST', 'source': 'M1_Enable := TRUE;'}}},
           {'id': 'HMI1', 'type': 'hmi', 'name': '操作屏', 'pos': [12, 20], 'size': [0.6, 0.4], 'params': {'screen': 'panel1'}},
           {'id': 'HMI2', 'type': 'hmi', 'name': '没接线的屏', 'pos': [14, 20], 'size': [0.6, 0.4], 'params': {}}],
          [mat('L1', 'SRC', 'M1'), mat('L2', 'M1', 'OUT'),
           {'id': 'S1', 'kind': 'signal', 'from': 'M1', 'to': 'PLC1', 'signals': [{'point': 'Count', 'ch': 'IW64', 'dir': 'in'}, {'point': 'Enable', 'ch': 'Q0.0', 'dir': 'out'}]},
           {'id': 'N1', 'kind': 'network', 'from': 'HMI1', 'to': 'PLC1', 'protocol': 'profinet'}])
p = Plant(m)
run(p, 3)
h1, h2 = p.find('HMI1'), p.find('HMI2')
ok('HMI 块：经网络线绑定 PLC，PLC 运行时 HMI 在运行', h1.plc_id() == 'PLC1' and h1.state == 'Executing' and h1.get('HMI/PLC') == 'PLC1', (h1.plc_id(), h1.state))
ok('HMI 块：没连 PLC 时提示', h2.plc_id() == '' and '没有连到 PLC' in h2.alarm, h2.alarm)
ok('PLC 块不把 HMI 当成受控设备', p.find('PLC1').devices == ['M1'], p.find('PLC1').devices)

# ============================================================ 3. 旧的控制单元模型自动迁移
LD = {'id': 'main', 'name': '皮带启停', 'lang': 'LD', 'vars': [], 'source': {'rungs': [
    {'comment': '启停', 'elements': [{'par': [[{'t': 'NO', 'var': 'B1'}], [{'t': 'NO', 'var': 'C1_FWD'}]]}, {'t': 'NO', 'var': 'B2'}, {'t': 'COIL', 'var': 'C1_FWD'}]},
    {'comment': '灯', 'elements': [{'t': 'NO', 'var': 'C1_FWD'}, {'t': 'COIL', 'var': 'LP1'}]}]}}
cell = {'size': [8, 4], 'components': [
    {'id': 'C1', 'type': 'belt_conveyor', 'pos': [0, 0, 0], 'rot': 0, 'size': [6, 0.6], 'params': {'speed': 0.3}},
    {'id': 'S1', 'type': 'diffuse_sensor', 'pos': [2.0, 0.35, 0.3], 'rot': 0, 'params': {'range': 0.8}},
    {'id': 'B1', 'type': 'button', 'pos': [-3, 1.6, 0.9], 'params': {'label': '启动', 'color': 'green'}},
    {'id': 'B2', 'type': 'button', 'pos': [-2.7, 1.6, 0.9], 'params': {'label': '停止', 'color': 'red', 'nc': True}},
    {'id': 'LP1', 'type': 'lamp', 'pos': [-2.4, 1.6, 0.9], 'params': {'label': '运行', 'color': 'green'}}],
    'io': [], 'plc': {'mode': 'internal', 'scan_ms': 20, 'program': LD},
    'hmi': [{'id': 'belt', 'name': '皮带面板', 'widgets': [{'id': 'w', 'type': 'lamp', 'x': 10, 'y': 10, 'w': 80, 'h': 30, 'var': 'LP1'}]}]}
old = model([{'id': 'CELL1', 'type': 'cell', 'name': '皮带单元', 'pos': [10, 10], 'size': [8, 4], 'node': [300, 100], 'params': {'cell': cell}}], [])
m = copy.deepcopy(old)
ch = migrate_model(m)
ok('迁移：说明', ch and 'PLC1' in ch[0], ch)
blk = {b['id']: b for b in m['blocks']}
ok('迁移：单元不再带 plc，HMI 画面搬到 PLC 块并绑定 PLC', 'plc' not in blk['CELL1']['params']['cell'] and 'hmi' not in blk['CELL1']['params']['cell']
   and blk['PLC1']['params']['hmi'][0]['cell'] == 'PLC1', blk['PLC1']['params'])
ok('迁移：PLC 块带程序、扫描周期、migrated_from、位置在单元旁边', blk['PLC1']['type'] == 'plc' and blk['PLC1']['params']['program']['name'] == '皮带启停'
   and blk['PLC1']['params']['migrated_from'] == 'CELL1' and blk['PLC1']['pos'][0] > 10 and blk['PLC1']['node'] == [300, 270], blk['PLC1'])
sig = next(l for l in m['links'] if l['kind'] == 'signal')
ok('迁移：一条信号线带全部 I/O，地址不带 %', sig['from'] == 'CELL1' and sig['to'] == 'PLC1' and len(sig['signals']) == 5
   and all(not s['ch'].startswith('%') for s in sig['signals']) and {'point': 'B1', 'ch': 'I0.1', 'dir': 'in'} in sig['signals'], sig)
ok('迁移：重复调用不再改', migrate_model(m) == [])
p = Plant(copy.deepcopy(old))
ok('旧模型直接建厂：自动迁移出 PLC1', p.find('PLC1') is not None and p.find('PLC1').plc.state == 'RUN')
c = p.find('CELL1')
ok('迁移后单元自己不再建 PLC', getattr(c, 'plc', None) is None, getattr(c, 'plc', None))
ok('plc_of_cell 找到控制单元的 PLC', plc_of_cell(p, 'CELL1') is p.find('PLC1'))
run(p, 2)
c.on_write('Panel/B1', True)
run(p, 3)
c.on_write('Panel/B1', False)
run(p, 3)
pl = p.find('PLC1')
ok('迁移后程序照常运行：按启动 → 输送线自锁', pl.plc.value('C1_FWD') is True and pl.plc.value('LP1') is True, pl.plc.online(ld=False)['vars'])
ok('单元的输出跟着 PLC', (getattr(c, 'outputs', None) or {}).get('C1_FWD') is True, getattr(c, 'outputs', None))
c.on_write('Panel/B2', True)
run(p, 3)
c.on_write('Panel/B2', False)
run(p, 2)
ok('按停止 → 停', pl.plc.value('C1_FWD') is False)
r = set_cell_program(p, 'CELL1', {'lang': 'ST', 'source': 'C1_FWD := TRUE;\nLP1 := FALSE;'})
run(p, 2)
ok('set_cell_program：给单元下载程序（到它的 PLC）', r['ok'] and pl.plc.value('C1_FWD') is True, r.get('errors'))
# all_io：在单元里新加一个传感器（I/O 表多一路），PLC 不用改信号线就接上
cd2 = copy.deepcopy(c.cfg['cell'])
cd2['components'].append({'id': 'S9', 'type': 'diffuse_sensor', 'pos': [-1.0, 0.35, 0.3], 'rot': 0, 'params': {'range': 0.8}})
e9 = dict(next(e for e in cd2['io'] if e['name'] == 'S1'), name='S9', comp='S9', addr='%IX0.7')
cd2['io'].append(e9)
c.reload(cd2)
run(p, 2)
row = next((e for e in pl.io if e['name'] == 'S9'), None)
ok('all_io：单元新加的 I/O 自动接到 PLC（地址用单元 I/O 表的）', row is not None and row['addr'] == '%IX0.7' and row['device'] == 'CELL1', pl.io)
ok('all_io：重新接线后程序还在运行', pl.plc.state == 'RUN' and pl.plc.value('C1_FWD') is True)

# ============================================================ 4. pickle（从此刻推演）
p = Plant(model([B('SRC', 'source', 2, interval='10'), B('M1', 'processor', 10, time='20'), B('OUT', 'sink', 20),
                 {'id': 'PLC1', 'type': 'plc', 'name': 'PLC1', 'pos': [10, 20], 'size': [1.2, 0.6], 'params': {'program': PROG}}],
                [mat('L1', 'SRC', 'M1'), mat('L2', 'M1', 'OUT'), {'id': 'S1', 'kind': 'signal', 'from': 'M1', 'to': 'PLC1', 'signals': SIG}]))
p.find('PLC1').plc.write('Allow', True)
run(p, 100)
try:
    q = pickle.loads(pickle.dumps(p))
    run(p, 100)
    run(q, 100)
    ok('带 PLC 块的工厂可以 pickle，恢复后接着跑结果一样', count(q.find('M1')) == count(p.find('M1')) and q.find('PLC1').plc.value('Allow') is True,
       (count(q.find('M1')), count(p.find('M1'))))
except Exception as e:                    # noqa: BLE001
    ok('带 PLC 块的工厂可以 pickle', False, f'{type(e).__name__}: {e}')
p = Plant(copy.deepcopy(old))
run(p, 5)
try:
    q = pickle.loads(pickle.dumps(p))
    run(q, 3)
    ok('带控制单元 + PLC 块的工厂可以 pickle', q.find('PLC1').plc.state == 'RUN')
except Exception as e:                    # noqa: BLE001
    ok('带控制单元 + PLC 块的工厂可以 pickle（控制单元里还有不能 pickle 的东西时由控制层修）', False, f'{type(e).__name__}: {e}')

# ============================================================ 5. 15 个实训场景迁移后建厂运行
try:
    from vfactory.control import scenes
    ids = [s['id'] for s in scenes.list_scenes()]
except Exception as e:                    # noqa: BLE001
    ids = []
    print('（没有场景库，跳过）', e)
bad = []
for sid in ids:
    try:
        sm = scenes.scene_plant(sid, with_reference=True)
        sp = Plant(sm)
        pl = next((s for s in sp.all_stations() if getattr(s, 'kind', '') == 'plc'), None)
        if pl is None or pl.plc is None or pl.plc.state != 'RUN':
            bad.append((sid, 'PLC 没运行', getattr(getattr(pl, 'plc', None), 'last_compile', None)))
            continue
        run(sp, 30)
        if pl.plc.state != 'RUN':
            bad.append((sid, pl.plc.state, pl.plc.error))
    except Exception as e:                # noqa: BLE001
        bad.append((sid, f'{type(e).__name__}: {e}'))
if ids:
    ok(f'{len(ids)} 个实训场景（带参考答案）迁移成 PLC 块后能建厂、PLC 运行 30 秒不出错', not bad, bad[:3])

n_ok = sum(1 for _, c in res if c)
print(f'\n{n_ok}/{len(res)} 通过')
sys.exit(0 if n_ok == len(res) else 1)
