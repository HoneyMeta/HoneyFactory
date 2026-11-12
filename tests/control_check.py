"""控制层离线测试：部件行为与传感器时序、故障与强制、评分、15 个场景参考答案满分、控制单元块接入整厂。

    python tests/control_check.py            # 全部
    python tests/control_check.py comp       # 只测部件
需要软 PLC（vfactory/plc）跑场景参考答案；没有时场景部分会标记为跳过。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import copy
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np  # noqa: E402

from vfactory.control import auto_io, catalog, validate_cell  # noqa: E402
from vfactory.control.sim import CLASSES, CellSim  # noqa: E402

res = []
only = sys.argv[1:]


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:240])


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def sim_of(comps, io=None, seed=1):
    cell = {'size': [8, 4], 'components': comps}
    cell['io'] = io if io is not None else auto_io(cell, keep=[])
    return CellSim(cell, np.random.default_rng(seed))


def run(sim, secs, outs=None, ctl=None, every=None):
    n = int(round(secs / 0.02))
    for _ in range(n):
        ins = sim.inputs()
        o = {e['name']: (False if e.get('type', 'BOOL') == 'BOOL' else 0) for e in sim.io if e['dir'] == 'out'}     # 像 PLC 一样每次给全部输出
        o.update(outs or {})
        if ctl:
            o.update(ctl(ins, sim) or {})
        sim.apply_outputs(o)
        sim.step(0.02)
        if every:
            every(sim)


BELT = {'id': 'C1', 'type': 'belt_conveyor', 'pos': [0, 0, 0], 'size': [6, 0.6], 'params': {'speed': 0.3}}


def part_at(sim, x, y=0.0, **tpl):
    t = {'kind': 'box', 'color': 'blue', 'h': 0.2, 'w': 0.25}
    t.update(tpl)
    p = sim.add_part(t, x, y, 0.25)
    return p


# ======================================================================= 目录与 I/O 表
if not only or 'cat' in only:
    missing = [t for t in catalog.COMP_TYPES if t not in CLASSES]
    ok('部件目录 32 种都有仿真模型', len(catalog.COMP_TYPES) >= 32 and not missing, f'{len(catalog.COMP_TYPES)} 种，缺 {missing}')
    allc = [{'id': f"X{i}", 'type': t, 'pos': [0, 0, 0]} for i, t in enumerate(catalog.COMP_TYPES)]
    io = auto_io({'components': allc}, keep=[])
    names = [e['name'] for e in io]
    addrs = [e['addr'] for e in io]
    ok('自动 I/O 表：名称、地址不重复', len(set(names)) == len(names) and len(set(addrs)) == len(addrs), f'{len(io)} 点')
    ok('自动 I/O：输入 %I、输出 %Q', all(e['addr'].startswith('%I' if e['dir'] == 'in' else '%Q') for e in io))
    io2 = auto_io({'components': allc[:5], 'io': [dict(io[0], name='RENAMED', addr='%I9.7')]})
    ok('自动 I/O 保留已有名称和地址', io2[0]['name'] == 'RENAMED' and io2[0]['addr'] == '%I9.7', io2[0])
    bad = {'components': [{'id': 'A1', 'type': 'pusher'}, {'id': 'A1', 'type': 'nope'}],
           'io': [{'name': '1bad', 'dir': 'in', 'comp': 'ZZ', 'signal': 'x', 'addr': '%I0.0'}, {'name': 'Y', 'dir': 'out', 'comp': 'A1', 'signal': 'front', 'addr': '%I0.0'}]}
    errs = [m for lv, m in validate_cell(bad) if lv == 'error']
    ok('单元定义检查能发现错误', len(errs) >= 5, errs[:6])
    ok('信号随参数变化（可反转输送机有 rev）', [s[0] for s in catalog.signals({'type': 'belt_conveyor', 'params': {'reversible': True}})['out']] == ['fwd', 'rev'])

# ======================================================================= 部件行为
if not only or 'comp' in only:
    # 输送速度
    s = sim_of([BELT])
    p = part_at(s, -2.0)
    run(s, 2.0, {'C1_FWD': True})
    ok('皮带输送：0.3 m/s 走 2 s = 0.6 m', near(p.x, -1.4, 0.01), round(p.x, 3))
    run(s, 1.0, {'C1_FWD': False})
    ok('皮带停：零件不动', near(p.x, -1.4, 0.01), round(p.x, 3))
    # 漫反射光电时序：零件前沿到光束的时刻
    s = sim_of([BELT, {'id': 'S1', 'type': 'diffuse_sensor', 'pos': [0.5, 0.35, 0.35]}])
    p = part_at(s, -1.0)
    hit = {}
    run(s, 8, {'C1_FWD': True}, every=lambda sm: hit.setdefault('on', sm.t) if sm.inputs()['S1'] and 'on' not in hit else (
        hit.setdefault('off', sm.t) if 'on' in hit and not sm.inputs()['S1'] and 'off' not in hit else None))
    t_on, t_off = (0.5 - 0.125 + 1.0) / 0.3, (0.5 + 0.125 + 1.0) / 0.3
    ok('光电时序：前沿到光束时亮', near(hit.get('on'), t_on, 0.05), f"{hit.get('on')} 期望 {t_on:.2f}")
    ok('光电时序：后沿离开时灭（遮挡时长 = 件长/速度）', near(hit.get('off'), t_off, 0.05), f"{hit.get('off')} 期望 {t_off:.2f}")
    s = sim_of([BELT, {'id': 'S1', 'type': 'diffuse_sensor', 'pos': [0.5, 0.35, 0.35], 'params': {'nc': True}},
                {'id': 'S2', 'type': 'diffuse_sensor', 'pos': [0.5, 0.35, 0.6]}])
    part_at(s, 0.5)
    run(s, 0.04)
    ok('常闭输出反相；光束高于零件不检测', s.inputs()['S1'] is False and s.inputs()['S2'] is False, s.inputs())
    # 电感 / 电容
    s = sim_of([BELT, {'id': 'IND', 'type': 'inductive', 'pos': [0.0, 0.3, 0.32], 'params': {'range': 0.2}},
                {'id': 'CAP', 'type': 'capacitive', 'pos': [0.0, -0.3, 0.32], 'rot': 180, 'params': {'range': 0.2}}])
    part_at(s, 0.0, material='plastic')
    run(s, 0.04)
    a = s.inputs()
    s = sim_of([BELT, {'id': 'IND', 'type': 'inductive', 'pos': [0.0, 0.3, 0.32], 'params': {'range': 0.2}},
                {'id': 'CAP', 'type': 'capacitive', 'pos': [0.0, -0.3, 0.32], 'rot': 180, 'params': {'range': 0.2}}])
    part_at(s, 0.0, material='metal')
    run(s, 0.04)
    b = s.inputs()
    ok('电感只认金属、电容都认', (a['IND'], a['CAP'], b['IND'], b['CAP']) == (False, True, True, True), (a, b))
    # 视觉 / 测高
    s = sim_of([BELT, {'id': 'V1', 'type': 'vision_sensor', 'pos': [0, 0, 0.9]}, {'id': 'H1', 'type': 'height_sensor', 'pos': [1, 0, 0.9]}])
    part_at(s, 0.0, color='green')
    part_at(s, 1.0, h=0.3)
    run(s, 0.04)
    ok('视觉颜色码（绿 = 2）、测高 mm', s.inputs()['V1_CODE'] == 2 and s.inputs()['V1_DETECT'] and s.inputs()['H1'] == 300, s.inputs())
    # 编码器
    s = sim_of([BELT, {'id': 'ENC', 'type': 'encoder', 'pos': [0, 0.35, 0.27], 'params': {'conveyor': 'C1', 'ppm': 1000}}])
    run(s, 2.0, {'C1_FWD': True})
    ok('编码器 1000 脉冲/m：2 s 600 脉冲', near(s.inputs()['ENC'], 600, 7), s.inputs()['ENC'])
    # 推杆
    comps = [BELT, {'id': 'P1', 'type': 'pusher', 'pos': [0, 0.42, 0.35], 'params': {'stroke': 0.8, 'speed': 1.0}},
             {'id': 'R1', 'type': 'remover', 'pos': [0, -0.76, 0], 'size': [0.9, 0.9], 'params': {'accept': {'color': 'blue'}}}]
    s = sim_of(comps)
    part_at(s, 0.0)
    t_front = {}
    run(s, 1.2, {'P1_EXTEND': True}, every=lambda sm: t_front.setdefault('t', sm.t) if sm.inputs()['P1_FRONT'] and 't' not in t_front else None)
    ok('推杆伸出到位时间 = 行程/速度', near(t_front.get('t'), 0.8, 0.03), t_front)
    ok('推杆把零件推进料箱（判正确）', s.st['sorted_ok'] == 1 and not s.live, s.st)
    run(s, 1.0, {'P1_EXTEND': False})
    ok('单电控断开后缩回到位', s.inputs()['P1_BACK'] and not s.inputs()['P1_FRONT'])
    # 推杆把零件推到另一个零件上 → 碰撞
    s = sim_of(comps)
    part_at(s, 0.0)
    part_at(s, 0.0, y=-0.32 + 0.0)
    s.live[1].y = -0.3
    run(s, 1.0, {'P1_EXTEND': True})
    ok('推杆把零件挤到另一个零件上记碰撞', s.st['collisions'] >= 1, s.st['collisions'])
    # 卡件：输送机推着零件顶在伸出的推板上
    s = sim_of([BELT, {'id': 'P1', 'type': 'pusher', 'pos': [0.5, 0.42, 0.35], 'params': {'stroke': 0.45, 'speed': 1.0}}])
    run(s, 0.6, {'P1_EXTEND': True})
    part_at(s, -0.5)
    run(s, 8, {'C1_FWD': True, 'P1_EXTEND': True})
    ok('零件被伸出的推板挡住超过 3 s 记卡件', s.st['jams'] == 1, s.st['jams'])
    # 挡停
    s = sim_of([BELT, {'id': 'ST1', 'type': 'stopper', 'pos': [0.5, 0, 0]}])
    p = part_at(s, -0.5)
    run(s, 6, {'C1_FWD': True, 'ST1_RAISE': True})
    ok('挡停挡住零件（零件贴着挡板）', near(p.x, 0.5 - 0.125 - 0.015, 0.02) and p.holds.get('ST1', 0) > 2, (round(p.x, 3), p.holds))
    run(s, 2, {'C1_FWD': True, 'ST1_RAISE': False})
    ok('挡停落下放行', p.x > 0.7, round(p.x, 3))
    run(s, 0.1, {'C1_FWD': True, 'ST1_RAISE': False})
    s2 = sim_of([BELT, {'id': 'ST1', 'type': 'stopper', 'pos': [0.5, 0, 0]}])
    part_at(s2, 0.5)
    run(s2, 0.5, {'ST1_RAISE': True})
    ok('挡板升起时顶到上面的零件记碰撞', s2.st['collisions'] == 1, s2.st['collisions'])
    # 摆臂
    s = sim_of([BELT, {'id': 'PA1', 'type': 'pivot_arm', 'pos': [0.5, 0.33, 0.33], 'params': {'length': 1.1}},
                {'id': 'C2', 'type': 'belt_conveyor', 'pos': [2.0, -0.65, 0], 'size': [3, 0.7], 'params': {'height': 0.2}}])
    p = part_at(s, -0.5, h=0.3)
    run(s, 10, {'C1_FWD': True, 'C2_FWD': True, 'PA1_TURN': True})
    ok('摆臂把零件导到旁边的输送线', p.sup is not None and p.sup.id == 'C2' and p.y < -0.4, (round(p.x, 2), round(p.y, 2), getattr(p.sup, 'id', None)))
    ok('摆臂到位信号', s.inputs()['PA1_TURNED'] and not s.inputs()['PA1_HOME'])
    # 转台
    s = sim_of([{'id': 'T1', 'type': 'turntable', 'pos': [0, 0, 0], 'size': [0.9, 0.9], 'params': {'angle': 90, 'speed': 90}}])
    p = part_at(s, 0.1)
    t90 = {}
    run(s, 1.5, {'T1_TURN': True}, every=lambda sm: t90.setdefault('t', sm.t) if sm.inputs()['T1_TURNED'] and 't' not in t90 else None)
    ok('转台 90°/s 转 90° 用 1 s，零件跟着转', near(t90.get('t'), 1.0, 0.03) and near(p.x, 0.0, 0.01) and near(p.y, 0.1, 0.01),
       (t90, round(p.x, 3), round(p.y, 3)))
    run(s, 1.0, {'T1_TURN': True, 'T1_ROLL_FWD': True})
    ok('转台滚筒沿当前方向输送', p.y > 0.3, round(p.y, 3))
    # 升降台
    s = sim_of([{'id': 'L1', 'type': 'lift', 'pos': [0, 0, 0], 'size': [0.8, 0.7], 'params': {'z_high': 1.0, 'speed': 0.4}}])
    p = part_at(s, 0.0)
    run(s, 2.2, {'L1_UP': True})
    ok('升降台把零件托到上位', near(p.z, 1.0, 0.01) and s.inputs()['L1_TOP'], round(p.z, 3))
    # 取放机械手（伺服）
    s = sim_of([BELT, {'id': 'PP1', 'type': 'pick_place', 'pos': [0, 0, 0], 'rot': -90, 'params': {'mode': 'servo', 'x_stroke': 1.6, 'z_stroke': 0.9}},
                {'id': 'PL1', 'type': 'pallet', 'pos': [0, -1.15, 0], 'size': [0.5, 1.0]}])
    p = part_at(s, 0.0)
    seq = [({'PP1_Z_SET': 900}, 2.0), ({'PP1_Z_SET': 900, 'PP1_GRIP': True}, 0.3), ({'PP1_Z_SET': 0, 'PP1_GRIP': True}, 2.0),
           ({'PP1_X_SET': 1150, 'PP1_GRIP': True}, 2.0), ({'PP1_X_SET': 1150, 'PP1_Z_SET': 900, 'PP1_GRIP': True}, 2.0),
           ({'PP1_X_SET': 1150, 'PP1_Z_SET': 900}, 0.3)]
    for o, t in seq:
        run(s, t, o)
    ok('取放机械手：下降接触、吸取、平移、放到托盘上', near(p.y, -1.15, 0.01) and near(p.z, 0.3, 0.01) and s.st['hard_drops'] == 0 and s.st['collisions'] == 0,
       (round(p.y, 3), round(p.z, 3), s.st['hard_drops'], s.st['collisions']))
    ok('托盘统计', s.stats()['pallets']['PL1']['count'] == 1)
    s = sim_of([BELT, {'id': 'PP1', 'type': 'pick_place', 'pos': [0, 0, 0], 'rot': -90, 'params': {'mode': 'pneumatic', 'z_stroke': 0.65}},
                {'id': 'B2', 'type': 'pallet', 'pos': [0, -0.5, 0], 'size': [0.4, 0.4], 'params': {'height': 0.3}}])
    part_at(s, 0.0)
    part_at(s, 0.0, y=-0.5)
    s.live[1].z = 0.3
    run(s, 2.0, {'PP1_Z_DOWN': True, 'PP1_GRIP': True})
    run(s, 1.0, {'PP1_Z_DOWN': True, 'PP1_GRIP': True, 'PP1_X_EXT': True})
    ok('机械手没抬起就平移：撞到旁边的零件记碰撞', s.st['collisions'] >= 1, s.st['collisions'])
    # 堆垛机入库
    s = sim_of([{'id': 'RK1', 'type': 'rack', 'pos': [0, -0.85, 0], 'size': [3.2, 0.6], 'params': {'cols': 4, 'rows': 3}},
                {'id': 'SC1', 'type': 'stacker_crane', 'pos': [-2.4, 0, 0], 'size': [4.8, 0.5],
                 'params': {'travel': 4.8, 'rack': 'RK1', 'fork_stroke': 0.85, 'station_in': [0.3, 0.21], 'station_out': [4.5, 0.21]}},
                {'id': 'CI', 'type': 'belt_conveyor', 'pos': [-2.1, 1.25, 0], 'rot': -90, 'size': [1.3, 0.6]}])
    p = s.add_part({'kind': 'pallet', 'h': 0.25, 'w': 0.45}, -2.1, 0.85, 0.25)
    steps = [({'SC1_TARGET': 0, 'SC1_FORK_LEFT': True}, 2.5), ({'SC1_TARGET': 0, 'SC1_FORK_LEFT': True, 'SC1_LIFT': True}, 0.6),
             ({'SC1_TARGET': 0, 'SC1_LIFT': True}, 2.5), ({'SC1_TARGET': 6, 'SC1_LIFT': True}, 4.0),
             ({'SC1_TARGET': 6, 'SC1_LIFT': True, 'SC1_FORK_RIGHT': True}, 2.5), ({'SC1_TARGET': 6, 'SC1_FORK_RIGHT': True}, 0.6), ({'SC1_TARGET': 6}, 2.5)]
    for o, t in steps:
        run(s, t, o)
    st = s.stats()['racks']['RK1']
    ok('堆垛机：入库口取货 → 送到 6 号库位（第 2 层第 2 列）', st['stored'] == 1 and st['occ'][1][1] == 1 and s.st['collisions'] == 0, st)
    run(s, 0.5, {'SC1_TARGET': 6, 'SC1_FORK_LEFT': True})
    run(s, 1.0, {'SC1_TARGET': 0, 'SC1_FORK_LEFT': True})
    ok('货叉没收回就行走记碰撞', s.st['collisions'] == 1, s.st['collisions'])
    # 夹爪
    s = sim_of([BELT, {'id': 'G1', 'type': 'gripper', 'pos': [0, 0, 0.35], 'size': [0.3, 0.7]}])
    p = part_at(s, 0.0)
    run(s, 2, {'C1_FWD': True, 'G1_CLOSE': True})
    ok('夹爪夹紧后零件不随输送线走', near(p.x, 0.0, 0.07) and s.inputs()['G1_HOLDING'], round(p.x, 3))
    # 电机：启动时间、正反转互锁、过载
    s = sim_of([{'id': 'M1', 'type': 'motor', 'pos': [0, 0, 0], 'params': {'reversible': True, 'ramp': 0.5}}])
    run(s, 0.25, {'M1_FWD': True})
    m = s.comps['M1']
    ok('电机斜坡启动（0.25 s 到一半转速）', near(m.s, 0.5, 0.05), m.s)
    run(s, 0.2, {'M1_FWD': True, 'M1_REV': True})
    ok('正反转同时得电记互锁错误', s.st['interlock_violations'] == 1, s.st['interlock_violations'])
    s.inject('M1', 'motor_overload')
    run(s, 0.1, {'M1_FWD': True})
    ok('过载：热继电器常闭触点断开、电机停', s.inputs()['M1_OL_OK'] is False and not s.inputs()['M1_RUNNING'])
    s.clear_faults()
    run(s, 0.1, {'M1_FWD': True})
    ok('清除故障后复位', s.inputs()['M1_OL_OK'] is True)
    # 弯道 / 链式移载
    s = sim_of([{'id': 'CC1', 'type': 'curved_conveyor', 'pos': [0, 0, 0], 'size': [1.2, 0.6], 'params': {'radius': 0.9, 'angle': 90, 'speed': 0.3}}])
    p = part_at(s, 0.02)
    run(s, 4.5, {'CC1_FWD': True})
    ok('弯道输送机左转 90°（零件沿圆弧到出口方向）', p.y > 0.5 and abs(p.x - 0.9) < 0.15, (round(p.x, 2), round(p.y, 2)))
    s = sim_of([{'id': 'C1', 'type': 'roller_conveyor', 'pos': [0, 0, 0], 'size': [2, 0.6]}, {'id': 'CT1', 'type': 'chain_transfer', 'pos': [0, 0, 0]}])
    p = part_at(s, 0.0)
    run(s, 1.0, {'CT1_UP': True, 'CT1_FWD': True})
    ok('链式移载顶升后横移零件', p.y > 0.15 and s.inputs()['CT1_IS_UP'], round(p.y, 3))
    # 面板
    s = sim_of([{'id': 'B1', 'type': 'button', 'pos': [0, 1.6, 0.95]}, {'id': 'B2', 'type': 'button', 'pos': [0.2, 1.6, 0.95], 'params': {'nc': True}},
                {'id': 'ES', 'type': 'estop', 'pos': [0.4, 1.6, 0.95]}, {'id': 'POT', 'type': 'potentiometer', 'pos': [0.6, 1.6, 0.95]}])
    a = s.inputs()
    s.panel('B1', 'press', hold=0.3)
    s.panel('B2', 'press', hold=0.3)
    s.panel('ES', 'press')
    s.panel('POT', 'set', 640)
    b = s.inputs()
    run(s, 0.5)
    c = s.inputs()
    ok('按钮常开/常闭、急停常闭且自锁、电位器', (a['B1'], a['B2'], a['ES'], b['B1'], b['B2'], b['ES'], b['POT'], c['B1'], c['ES']) ==
       (False, True, True, True, False, False, 640, False, False), (a, b, c))
    # 掉件、接收条件、周转箱计数
    s = sim_of([BELT, {'id': 'R1', 'type': 'remover', 'pos': [3.2, 0, 0], 'size': [0.4, 0.8], 'params': {'accept': {'color': 'blue'}}}])
    part_at(s, 2.5, color='green')
    part_at(s, 1.5, color='blue')
    run(s, 8, {'C1_FWD': True})
    ok('收料器按接收条件判分拣对错', s.st['sorted_ok'] == 1 and s.st['sorted_wrong'] == 1, s.st)
    s = sim_of([BELT])
    part_at(s, 2.5)
    run(s, 3, {'C1_FWD': True})
    ok('输送线尽头没有接续：掉到地上', s.st['dropped'] == 1, s.st['dropped'])
    s = sim_of([{'id': 'C1', 'type': 'belt_conveyor', 'pos': [0, 0, 0], 'size': [2, 0.6], 'params': {'height': 0.7}},
                {'id': 'C2', 'type': 'belt_conveyor', 'pos': [1.2, 0, 0], 'rot': 90, 'size': [4, 0.7]},
                {'id': 'R1', 'type': 'remover', 'pos': [1.2, 1.9, 0], 'size': [0.8, 0.3], 'params': {'accept': {'count': 3}}}])
    s.add_part({'kind': 'tote', 'h': 0.3, 'w': 0.5}, 1.2, 0.0, 0.25)
    for i in range(3):
        s.add_part({'kind': 'box', 'h': 0.12, 'w': 0.15}, 0.4 - i * 0.6, 0, 0.7)
    run(s, 8, {'C1_FWD': True})
    inside = sum(1 for q in s.live if q.box)
    run(s, 8, {'C2_FWD': True})
    ok('周转箱：零件落进箱里随箱走，满 3 个的箱子判正确', inside == 3 and s.st['sorted_ok'] == 1 and not s.live, (inside, s.st['sorted_ok'], len(s.live)))

# ======================================================================= 故障与强制
if not only or 'fault' in only:
    def mk():
        return sim_of([BELT, {'id': 'S1', 'type': 'diffuse_sensor', 'pos': [0, 0.35, 0.35]},
                       {'id': 'P1', 'type': 'pusher', 'pos': [1, 0.42, 0.35], 'params': {'stroke': 0.8, 'speed': 1.0}}], seed=3)
    s = mk()
    ok('注入：传感器常通', s.inject('S1', 'sensor_stuck_on') == '' and s.inputs()['S1'] is True)
    s.clear_faults()
    ok('清除故障', s.inputs()['S1'] is False and not s.fault_list())
    s.inject('S1', 'sensor_flicker')
    vals = []
    run(s, 2, every=lambda sm: vals.append(sm.inputs()['S1']))
    ok('传感器抖动：信号随机跳变', 0 < sum(vals) < len(vals), sum(vals))
    s = mk()
    part_at(s, 0)
    run(s, 0.04)
    s.inject('S1', 'sensor_stuck_off')
    ok('传感器常断', s.inputs()['S1'] is False)
    s = mk()
    s.inject('P1_EXTEND', 'wire_break')
    run(s, 1.0, {'P1_EXTEND': True})
    ok('输出断线：执行器收不到命令（I/O 点级故障）', s.comps['P1'].pos == 0 and s.outputs['P1_EXTEND'] is True, s.comps['P1'].pos)
    s = mk()
    s.inject('P1', 'actuator_jam')
    run(s, 1.0, {'P1_EXTEND': True})
    ok('执行器卡滞', s.comps['P1'].pos == 0)
    s = mk()
    s.inject('P1', 'actuator_slow')
    run(s, 0.5, {'P1_EXTEND': True})
    ok('执行器变慢（35%）', near(s.comps['P1'].pos, 0.175, 0.02), s.comps['P1'].pos)
    s = mk()
    s.inject('C1', 'motor_overload')
    p = part_at(s, -1)
    run(s, 1, {'C1_FWD': True})
    ok('输送机电机过载停转', near(p.x, -1, 0.001))
    ok('不允许的故障被拒绝', s.inject('C1', 'sensor_flicker') != '' and s.inject('NOPE', 'wire_break') != '')
    s = mk()
    s.force('S1', True)
    s.force('P1_EXTEND', True)
    run(s, 1.0, {'P1_EXTEND': False})
    ok('强制输入 / 强制输出', s.inputs()['S1'] is True and s.comps['P1'].pos > 0.7)
    s.force('S1', None)
    ok('取消强制', s.inputs()['S1'] is False)
    ok('按地址写输出（%Q）', (lambda sm: (sm.apply_outputs({'%Q0.0': True}), sm.outputs['C1_FWD'])[1])(mk()))
    # 确定性
    from vfactory.control import scenes as SC
    sc = SC.get_scene('s04_sort_color')
    a, b = CellSim(sc['cell'], np.random.default_rng(5)), CellSim(sc['cell'], np.random.default_rng(5))
    for x in (a, b):
        run(x, 60, {'C1_FWD': True})
    ok('同样的种子和输入：结果完全一样', a.stats() == b.stats() and [(p.x, p.color) for p in a.live] == [(p.x, p.color) for p in b.live])

# ======================================================================= 场景与评分
if not only or 'scene' in only:
    from vfactory.control import scenes as SC
    from vfactory.control import scoring
    try:
        import vfactory.plc  # noqa: F401
        have_plc = True
    except Exception as e:
        have_plc = False
        print('SKIP 场景参考答案：软 PLC 模块不可用', e)
    ids = SC.scene_ids()
    ok('场景库 15 个，等级 1–15', len(ids) == 15 and sorted(SC.get_scene(i)['level'] for i in ids) == list(range(1, 16)), ids)
    for sid in ids:
        sc = SC.get_scene(sid)
        need = all(sc.get(k) for k in ('cell', 'io', 'task_md', 'scoring', 'test', 'reference', 'faults'))
        ok(f'{sid} 字段齐全、I/O 表有效、满分 100', need and not [m for lv, m in validate_cell(sc['cell']) if lv == 'error']
           and abs(sum(r['weight'] for r in sc['scoring']['rules']) - 100) < 1e-6)
    if have_plc:
        t0 = time.time()
        for sid in ids:
            sc = SC.get_scene(sid)
            for lang in ('st', 'ld'):
                if lang not in sc['reference']:
                    continue
                r = scoring.score_scene(sc, sc['reference'][lang])
                ok(f"{sid} 参考答案（{lang.upper()}）满分", r['score'] == r['max'] == 100, [d['text'] for d in r['details'] if not d['ok']] or r.get('error', ''))
        ok('15 个场景评分总耗时', time.time() - t0 < 120, f'{time.time() - t0:.1f}s')
        sc = SC.get_scene('s02_fwd_rev')
        r = scoring.score_scene(sc, {'lang': 'ST', 'vars': [], 'source': 'M1_FWD := (FWD OR M1_FWD) AND STOP;\nM1_REV := (REV OR M1_REV) AND STOP;'})
        ok('没有互锁的正反转程序丢互锁分', r['score'] < 70 and not next(d for d in r['details'] if d['key'] == 'interlock_ok')['ok'], r['score'])
        sc = SC.get_scene('s04_sort_color')
        r = scoring.score_scene(sc, {'lang': 'ST', 'vars': [{'name': 'RUN', 'type': 'BOOL'}],
                                     'source': 'RUN := (START OR RUN) AND STOP AND ESTOP;\nC1_FWD := RUN;\nP1_EXTEND := S1 AND NOT P1_FRONT;'})
        ok('全部都推的分拣程序：正确率不够', r['stats']['sort_accuracy'] < 0.8 and r['score'] <= 65, (r['score'], r['stats']['sort_accuracy']))
        r = scoring.score_scene(sc, {'lang': 'ST', 'source': 'C1_FWD := ;'})
        ok('编译错误：0 分并给出错误', r['score'] == 0 and '编译' in r.get('error', ''), r.get('error'))
        r = scoring.score_scene(sc, {'lang': 'ST', 'vars': [], 'source': 'C1_FWD := TRUE;'})
        ok('不管急停的程序丢急停分', not next(d for d in r['details'] if d['key'] == 'estop_ok')['ok'])

# ======================================================================= 控制单元块接入整厂
if not only or 'plant' in only:
    from vfactory.core import Plant
    from vfactory.control import scenes as SC
    from vfactory.flow.model import validate
    m = SC.scene_plant('s15_full_line', with_reference=True)
    v = validate(m)
    ok('场景独立工厂模型校验通过', v['ok'], v['issues'][:3])
    p = Plant(copy.deepcopy(m))
    c = p.stations['CELL1']
    sig = [l for l in m['links'] if l.get('kind') == 'signal']
    ok('场景工厂：单元 + 独立 PLC 块 + 一条信号线接全部 I/O（单元里不再带 PLC）', 'plc' not in m['blocks'][0]['params']['cell'] and len(sig) == 1
       and {s['point'] for s in sig[0]['signals']} == {e['name'] for e in c.sim.io} and all('%' not in s['ch'] for s in sig[0]['signals'])
       and any(b['type'] == 'plc' and (b['params'].get('program') or {}).get('lang') == 'ST' for b in m['blocks']), [l['id'] for l in sig])
    p.step()
    ok('控制单元由信号线上的 PLC 块控制（单元自己没有 PLC）', c.plc is None and c.plc_state() == 'RUN' and [x.id for x in c.controllers()] == ['PLC1'],
       (c.plc, c.plc_state(), [x.id for x in c.controllers()]))
    c.sim.panel('START', 'press')
    t0 = time.time()
    p.run_for(600)
    wall = time.time() - t0
    k = p.kpi
    ok('整厂来料进单元、合格件交回下游、次品走 ng 报废', k['good'] > 30 and k['scrap'] > 5 and c.sim.st['sorted_wrong'] == 0,
       f"来料 {k['castings']} 合格 {k['good']} 报废 {k['scrap']} 错分 {c.sim.st['sorted_wrong']}")
    ok('600 s 带控制单元的仿真用时', wall < 20, f'{wall:.1f}s')
    tags = c.tags
    ok('每个 I/O 点都是点位（协议发布）', all(('IO/' + e['name']) in tags for e in c.sim.io) and 'Panel/START' in tags and tags['Panel/START'].writable,
       len([t for t in tags if t.startswith('IO/')]))
    ok('状态与 OEE', c.state in ('Executing', 'Idle', 'Starved', 'Blocked') and 'oee' in c.snapshot(), (c.state, c.snapshot().get('oee')))
    ok('点位写按钮', c.write('Panel/STOP', True) == '' and c.sim.comps['STOP'].state == 1)
    c.write('Panel/STOP', False)
    v2 = c.view()['cell']
    ok('三维数据：部件状态、零件、最近帧', set(v2) >= {'comps', 'parts', 'frames', 'rev', 't'} and len(v2['frames']) >= 3)
    pc = copy.deepcopy(p)
    pc.run_for(60)
    ok('整厂深拷贝（预热缓存）后单元照常运行', pc.stations['CELL1'].plc_state() == 'RUN' and pc.kpi['good'] >= k['good'])
    cell = copy.deepcopy(c.cell_def)
    cell['components'][1]['params']['speed'] = 0.32
    c.reload(cell)
    ok('改单元定义后 PLC 继续运行、版本号加 1', c.plc_state() == 'RUN' and c.rev() == 1)
    n0 = c.sim.t
    got = c.pump(0.5)
    ok('实时推进 pump', near(got, 0.5, 0.021) and near(c.sim.t - n0, got, 1e-6), got)
    p.step()
    ok('整厂步补齐剩余子步（一步 1 s）', near(c.sim.t - n0, 1.0, 1e-6), c.sim.t - n0)
    # 预热旁路
    m2 = copy.deepcopy(m)
    m2['plant']['warmup_h'] = 0.5
    p2 = Plant(m2)
    p2.run_for(1800)
    ok('整厂预热期间单元走旁路（零件按旁路时间穿过）', p2.stations['CELL1'].count > 50 and p2.stations['CELL1'].sim.t == 0, p2.stations['CELL1'].count)
    # 所有场景都能建成独立工厂并跑起来
    bad = []
    for sid in SC.scene_ids():
        mm = SC.scene_plant(sid, with_reference=True)
        if not validate(mm)['ok']:
            bad.append(sid)
            continue
        pp = Plant(copy.deepcopy(mm))
        pp.stations['CELL1'].sim.panel('START', 'press') if 'START' in pp.stations['CELL1'].sim.comps else None
        pp.run_for(30)
    ok('15 个场景都能建成独立工厂运行', not bad, bad)

# ======================================================================= 4.1 学校审计：触点说明、任务书对齐、统计项
if not only or 'audit' in only:
    from vfactory.control import scenes as SC
    from vfactory.control.scenes import build as SB
    probs = [m for s_ in SB.SCENES for m in SB.check_task(s_)]
    ok('任务书与评分对齐（每个评分项在任务书里有要求，没有"不要求"之类矛盾）', not probs, probs[:3])
    bad_idle, notes = [], []
    for sid in SC.scene_ids():
        sc = SC.get_scene(sid)
        io = sc['cell']['io']
        ok_fields = all(('idle' in e) and (e['dir'] != 'in' or e['type'] != 'BOOL' or e.get('contact') in ('NO', 'NC')) for e in io)
        sim = CellSim(sc['cell'], np.random.default_rng(1))
        ins = sim.inputs()
        for e in io:
            if e['dir'] == 'in' and e['type'] == 'BOOL' and bool(ins[e['name']]) != bool(e['idle']):
                bad_idle.append(f"{sid}.{e['name']} 实际 {ins[e['name']]} 标注 {e['idle']}")
        if not ok_fields:
            bad_idle.append(f'{sid} 缺 contact/idle')
        ncs = [e['name'] for e in io if e.get('contact') == 'NC']
        if ncs and not all(n in sc['task_md'] for n in ncs) or ('常闭' not in sc['task_md'] and ncs):
            notes.append(sid)
    ok('I/O 表标注触点和未操作时的值，且和仿真静止时一致', not bad_idle, bad_idle[:5])
    ok('任务书写明哪些输入是常闭（STOP、ESTOP 未按下时为 1）', not notes and '`STOP`、`ESTOP` 是**常闭触点**' in SC.get_scene('s03_conveyor')['task_md'], notes)
    s01 = CellSim(SC.get_scene('s01_motor_latch')['cell'], np.random.default_rng(1)).stats()
    s04 = CellSim(SC.get_scene('s04_sort_color')['cell'], np.random.default_rng(1)).stats()
    ok('统计项跟随场景评分指标（电机自锁不显示分拣正确率）', [m['key'] for m in s01['metrics']] == ['interlock_violations', 'hard_reversals']
       and 'sort_accuracy' in [m['key'] for m in s04['metrics']] and all(m['label'] for m in s04['metrics']), (s01['metrics'], [m['label'] for m in s04['metrics']]))
    blank = CellSim({'components': [{'id': 'M1', 'type': 'motor'}, {'id': 'B1', 'type': 'button'}]}, np.random.default_rng(1)).stats()
    ok('没有收料器的单元推断统计项时不出现分拣正确率', 'sort_accuracy' not in [m['key'] for m in blank['metrics']], [m['key'] for m in blank['metrics']])

# ======================================================================= 示范工厂分拣段 + 演示模板
if not only or 'show' in only:
    import glob

    import yaml

    from vfactory.core import Plant
    from vfactory.flow.model import validate
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sp = os.path.join(root, 'plants', 'foundry-housing.yaml')
    m = yaml.safe_load(open(sp, encoding='utf-8'))
    cl = next((b for b in m['blocks'] if b['id'] == 'CELL1'), None)
    sg = [l for l in m.get('links') or [] if l.get('kind') == 'signal' and 'CELL1' in (l['from'], l['to'])]
    pb = next((b for b in m['blocks'] if sg and b['id'] in (sg[0]['from'], sg[0]['to']) and b['type'] == 'plc'), None)
    ok('示范工厂是 2.0 模型，分拣段 CELL1 由独立 PLC 块控制（梯形图程序在 PLC 块里）', cl is not None and 'plc' not in cl['params']['cell']
       and pb is not None and (pb['params'].get('program') or {}).get('lang') == 'LD' and len(sg[0]['signals']) == len(cl['params']['cell']['io']),
       (pb or {}).get('id'))
    v = validate(m)
    ok('示范工厂模型校验无错误', v['ok'], [i['msg'] for i in v['issues'] if i['level'] == 'error'][:3])
    m['plant']['start'], m['plant']['warmup_h'] = '2026-11-02T07:00:00', 0
    p = Plant(m)
    c = p.stations['CELL1']
    ok('分拣段 PLC 上电即运行（不需要 data/ 目录）', c.plc_state() == 'RUN' and not c.plc_error, (c.plc_state(), c.plc_error))
    t0 = time.time()
    p.run_for(6 * 3600)
    st = c.sim.stats()
    k = p.kpi
    ok('分拣段：检测后的件进来、合格件交回、漏检缺陷件被剔除，不卡不撞', st['removed'] > 100 and st['sorted_wrong'] == 0 and st['collisions'] == 0
       and st['jams'] == 0 and st['dropped'] == 0, {x: st[x] for x in ('removed', 'sorted_ok', 'sorted_wrong', 'collisions', 'jams', 'dropped')})
    ok('分拣段不压产能（单元前队列不堆积）', c.available() <= 2 and k['good'] > 150, f"合格入库 {k['good']} 队列 {c.available()} 剔除 {k['scrap_by'].get('分拣段复检剔除', 0)}（{time.time() - t0:.0f}s）")
    ok('数码管显示合格数', c.sim.outputs.get('D1', 0) >= st['bins'].get('OUT_OK', {}).get('n', 0) - 1, (c.sim.outputs.get('D1'), st['bins']))
    files = sorted(glob.glob(os.path.join(root, 'templates', 'cells', '*.yaml')))
    ok('控制单元演示模板 8 个', len(files) == 8, [os.path.basename(f) for f in files])
    for f in files:
        tm = yaml.safe_load(open(f, encoding='utf-8'))
        tm['plant']['start'] = '2026-11-02T08:00:00'
        pp = Plant(tm)
        cc = pp.stations['CELL1']
        pp.run_for(240)
        moved = cc.sim.stats()['removed'] + sum(1 for q in cc.sim.live if abs(q.dx) + abs(q.dy) > 0) + (cc.sim.stats().get('pallets', {}).get('PL1', {}).get('count', 0))
        name = os.path.basename(f)
        ok(f'模板 {name}：名称、PLC 运行' + ('' if 'motor' in name else '、零件在动'), tm['plant']['name'].startswith('控制单元演示') and cc.plc_state() == 'RUN'
           and ('motor' in name or moved > 0 or cc.sim.stats().get('racks', {}).get('RK1', {}).get('stored', 0) > 0), (tm['plant']['name'], cc.plc_state(), moved))

# ======================================================================= 4.3 生产设备的控制接口（PLC 用信号线控制任何设备）
if not only or 'ctl' in only:
    from vfactory.control import iface
    from vfactory.core import CLS_LABEL, CLS_OF_STATE, Plant

    def line(extra_blocks=(), extra_links=(), m1=None):
        """来料 → M1 → M2 → 出口（加工块之间直接相连，没有缓存）。"""
        return {'version': 2, 'plant': {'name': '控制接口', 'seed': 3, 'dt': 1, 'warmup_h': 0, 'start': '2026-11-02T08:00:00'},
                'blocks': [{'id': 'SRC', 'type': 'source', 'pos': [0, 0], 'params': {'interval': '10'}},
                           {'id': 'M1', 'type': 'processor', 'pos': [5, 0], 'params': {'time': '20', **(m1 or {})}},
                           {'id': 'M2', 'type': 'processor', 'pos': [10, 0], 'params': {'time': '15'}},
                           {'id': 'OUT', 'type': 'sink', 'pos': [15, 0], 'params': {}}, *extra_blocks],
                'links': [{'id': 'L1', 'kind': 'material', 'from': 'SRC', 'from_port': 'out', 'to': 'M1', 'to_port': 'in'},
                          {'id': 'L2', 'kind': 'material', 'from': 'M1', 'from_port': 'out', 'to': 'M2', 'to_port': 'in'},
                          {'id': 'L3', 'kind': 'material', 'from': 'M2', 'from_port': 'out', 'to': 'OUT', 'to_port': 'in'}, *extra_links]}

    def kpis(p):
        return (p.kpi['good'], p.kpi['castings'], {k: dict(v.time_in_state) for k, v in p.stations.items()})

    a, b = Plant(line()), Plant(line())
    for st in b.stations.values():               # 读控制点不改变设备行为
        [st.ctl_get(x['name']) for x in st.ctl_points() if x['dir'] == 'in']
    a.run_for(1800)
    b.run_for(1800)
    ok('没接 PLC 的设备行为不变（读控制点不影响结果）', kpis(a) == kpis(b) and a.kpi['good'] > 50, a.kpi['good'])
    pts = {x['name']: x['dir'] for x in a.stations['M1'].ctl_points()}
    ok('加工块的控制点：Running/Fault/PartIn/Count 输入，Enable/Reset 输出，外加速度倍率', pts.get('Running') == 'in' and pts.get('Count') == 'in'
       and pts.get('PartIn') == 'in' and pts.get('Fault') == 'in' and pts.get('Enable') == 'out' and pts.get('Reset') == 'out' and pts.get('SpeedPct') == 'out', pts)
    cpt = {x['name'] for t in ('induction_furnace', 'cnc', 'conveyor') for x in iface.points_of_type(t)}
    ok('高级模型和输送线有自己的点（电炉 Temp/PowerSP、CNC ProgramNo、输送线 Run）', {'Temp', 'PowerSP', 'ProgramNo', 'Run'} <= cpt, sorted(cpt))
    ok('人员池、PLC 本身没有控制点', not iface.points_of_type('operators') and not iface.points_of_type('plc'))
    ok('等待 PLC 的时间类别 wait_plc', CLS_OF_STATE.get('WaitPLC') == 'wait_plc' and CLS_LABEL.get('wait_plc') == '等待 PLC')

    p = Plant(line())
    m1, m2 = p.stations['M1'], p.stations['M2']
    m1._plc_wired = {'Enable'}
    p.run_for(300)
    ok('接了 Enable 且为 0：M1 不开工，状态"等待 PLC 允许"，下游跟着缺料', m1.count == 0 and m1.state == 'WaitPLC' and m2.count == 0
       and m1.time_in_state.get('WaitPLC', 0) > 250 and any(c == 'wait_plc' for _, sid, c in p.class_log if sid == 'M1'),
       (m1.count, m1.state, m1.time_in_state))
    ok('PartIn：有料在等时为 1', m1.ctl_get('PartIn') is True and m1.ctl_get('Running') is False)
    m1.ctl_set('Enable', 1)
    p.run_for(5)
    ok('Enable=1 后开始加工，Running=1', m1.ctl_get('Running') is True and m1.state == 'Executing', m1.state)
    m1.ctl_set('Enable', 0)
    p.run_for(25)
    ok('加工中把 Enable 置 0：这一件做完，然后等待', m1.count == 1 and m1.state == 'WaitPLC', (m1.count, m1.state))
    m1.ctl_set('Enable', 1)
    p.run_for(600)
    ok('Count = 累计完成件数', m1.ctl_get('Count') == m1.count and m1.count >= 25 and m1.get('Production/Count') == m1.count, (m1.count, m1.ctl_get('Count')))
    m1.inject('failure')
    p.run_for(5)
    ok('故障时 Fault=1', m1.ctl_get('Fault') is True and m1.state == 'Stopped')
    m1.ctl_set('Reset', 1)
    p.run_for(1)
    ok('Reset 上升沿清故障', m1.ctl_get('Fault') is False and m1.state != 'Stopped', m1.state)
    m1.inject('failure')
    p.run_for(2)
    m1.ctl_set('Reset', 1)                        # 一直为 1：不是上升沿，不清
    p.run_for(2)
    held = m1.ctl_get('Fault')
    m1.ctl_set('Reset', 0)
    m1.ctl_set('Reset', 1)
    p.run_for(1)
    ok('Reset 保持为 1 不重复清故障，再来一个上升沿才清', held is True and m1.ctl_get('Fault') is False)
    m1.ctl_set('SpeedPct', 500)
    ok('类型自有 out 点写设备点位（越限夹到范围内）', m1.get('Setpoint/SpeedPct') == 150, m1.get('Setpoint/SpeedPct'))
    ok('写 in 点 / 不存在的点给出中文错误', '不能写' in m1.ctl_set('Running', 1) and '没有控制点' in m1.ctl_set('Nope', 1))

    # 输送线 Run、来料 Enable：整体暂停
    cv = {'version': 2, 'plant': {'name': '输送线', 'seed': 3, 'dt': 1, 'warmup_h': 0, 'start': '2026-11-02T08:00:00'},
          'blocks': [{'id': 'SRC', 'type': 'source', 'pos': [0, 0], 'params': {'interval': '5'}},
                     {'id': 'CV1', 'type': 'conveyor', 'pos': [8, 0], 'params': {'length_m': 6, 'speed_mps': 0.5}},
                     {'id': 'OUT', 'type': 'sink', 'pos': [16, 0], 'params': {}}],
          'links': [{'id': 'L1', 'kind': 'material', 'from': 'SRC', 'from_port': 'out', 'to': 'CV1', 'to_port': 'in'},
                    {'id': 'L2', 'kind': 'material', 'from': 'CV1', 'from_port': 'out', 'to': 'OUT', 'to_port': 'in'}]}
    p = Plant(cv)
    c1 = p.stations['CV1']
    c1._plc_wired = {'Run'}
    p.run_for(120)
    ok('输送线接了 Run 且为 0：带不走', c1.count == 0 and c1.state == 'WaitPLC', (c1.count, c1.state))
    c1.ctl_set('Run', True)
    p.run_for(120)
    ok('Run=1 后输送', c1.count > 5 and c1.ctl_get('OnBelt') >= 1, (c1.count, c1.ctl_get('OnBelt')))
    s0 = p.stations['SRC']
    s0._plc_wired = {'Enable'}
    n0 = s0.count
    p.run_for(60)
    ok('来料接了 Enable 且为 0：不放料', s0.count == n0 and s0.state == 'WaitPLC', (n0, s0.count))

    # 真 PLC 块：信号线 + ST 程序，M1 只有在 M2 空闲时才放行（PLC 变量名 = 设备_点位）
    prog = {'id': 'p', 'name': '放行', 'lang': 'ST', 'vars': [],
            'source': 'PROGRAM Gate\nM1_Enable := NOT M2_Running AND NOT M2_PartIn;\nM2_Enable := TRUE;\nM1_Reset := M1_Fault;\nEND_PROGRAM\n'}
    plcb = {'id': 'PLC1', 'type': 'plc', 'pos': [8, 4], 'params': {'scan_ms': 20, 'mode': 'internal', 'program': prog}}
    sl = [{'id': 'S1', 'kind': 'signal', 'from': 'M1', 'to': 'PLC1', 'signals': [
        {'point': 'Running', 'ch': 'I0.0', 'dir': 'in'}, {'point': 'Fault', 'ch': 'I0.1', 'dir': 'in'}, {'point': 'PartIn', 'ch': 'I0.2', 'dir': 'in'},
        {'point': 'Count', 'ch': 'IW64', 'dir': 'in'}, {'point': 'Enable', 'ch': 'Q0.0', 'dir': 'out'}, {'point': 'Reset', 'ch': 'Q0.1', 'dir': 'out'}]},
          {'id': 'S2', 'kind': 'signal', 'from': 'M2', 'to': 'PLC1', 'signals': [
        {'point': 'Running', 'ch': 'I0.3', 'dir': 'in'}, {'point': 'PartIn', 'ch': 'I0.4', 'dir': 'in'}, {'point': 'Enable', 'ch': 'Q0.2', 'dir': 'out'}]}]
    try:
        p = Plant(line([plcb], sl))
        pl = p.stations['PLC1']
        p.run_for(1800)
        free = Plant(line())
        free.run_for(1800)
        m1, m2 = p.stations['M1'], p.stations['M2']
        ok('PLC 块经信号线控制两台设备：M1 只在 M2 空闲时放行（一件流）', getattr(pl.plc, 'state', '') == 'RUN' and m1.count > 20
           and m1.time_in_state.get('WaitPLC', 0) > 100 and set(m1._plc_wired) >= {'Enable'} and p.kpi['good'] <= free.kpi['good'],
           (getattr(pl.plc, 'state', ''), m1.count, round(m1.time_in_state.get('WaitPLC', 0)), p.kpi['good'], free.kpi['good']))
        m1.inject('failure')
        p.run_for(3)
        ok('PLC 程序用 Reset 自动复位故障', m1.ctl_get('Fault') is False, m1.state)
    except Exception as e:                        # noqa: BLE001
        ok('PLC 块经信号线控制设备', False, repr(e)[:200])

bad = [n for n, g in res if not g]
print(f'\n{len(res) - len(bad)}/{len(res)} 通过', ('；失败：' + '、'.join(bad)) if bad else '')
