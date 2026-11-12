"""5.0 标准交付包（交付包）：把虚拟工厂当成"系统集成商刚调完的现场"，按 MES 标准接入路径交付。

GET  /api/p/{pid}/delivery.zip[?protocols=primary|all]   交付包（zip）：
     README.md                说明：协议端点与命名空间、MQTT 主题与载荷、Modbus 从站/寄存器约定、坐标系、动作信号
     points.xlsx              设备清单 + 点表 + 协议 + 说明（列格式见 docs/interface/点表格式.md，MES 接入规范用同一格式）
     layout.dxf               平面布置图（米，原点在厂房左下角，Y 向上）：每类一层；设备是带属性（CODE/NAME/TYPE）的块
     models/<设备类型>.glb     每类设备一个三维模型（glTF 2.0 二进制，米，Y 向上）
     models/scene.glb         整厂场景：每台设备一个节点（名字 = 设备编码），带位置和朝向
POST /api/p/{pid}/delivery.zip   同上，body {"models": {"<类型>": "<GLB base64>"}, "scene": "<GLB base64>"}：
     网页按钮用界面里的三维模型（three.js GLTFExporter）替换服务端生成的简化模型
GET  /api/p/{pid}/delivery/points.xlsx | layout.dxf | models/<类型>.glb | models/scene.glb | README.md   单个文件
GET  /api/p/{pid}/delivery/info      交付包概况（设备数、点数、原始现场模式、动作信号）
GET  /api/p/{pid}/delivery/raw_site  /  PUT {"on": true|false}   原始现场模式（见 rawsite.py），切换时协议层重建、仿真不重置
GET  /api/p/{pid}/actions            动作级信号：每台设备的模板、当前动作故障、上次各动作用时

原始现场模式下导出的点表只有 点位编码 / 协议 / 地址 / 数据类型，其余空着（像真实的半成品交接）；
标准答案只写到 <数据目录>/data/delivery/<工厂>/answer_key.json（不进交付包、不走接口），测试用它给 MES 的 AI 补全打分。
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import struct
import zipfile
from datetime import datetime

from .i18n import _tr, variants  # noqa: F401

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response

from . import comm, paths, rawsite

DEV_COLS = ['设备编码', '设备名称', '设备类型', '型号', '厂家', '车间', '产线', '工位', 'X(m)', 'Y(m)', '宽(m)', '深(m)', '朝向(°)', '3D模型文件', '理想节拍(s)', '备注']
PT_COLS = ['点位编码', '设备编码', '含义', '单位', '数据类型', '读写', '用途', '协议', '地址', '缩放', '偏移', '采集周期(ms)', '报警下限', '报警上限', '正常范围', '备注']
PURPOSES = ('state', 'alarm', 'count', 'power', 'energy', 'load', 'temp', 'quality', 'action', 'step', 'param', 'other')
SKIP_KINDS = {'crew', 'operators', 'split', 'submodel'}          # 人员、逻辑块：不是设备
WORKSHOP = {'熔炼区': '铸造车间', '造型区': '铸造车间', '清理区': '铸造车间', '机加区': '机加车间', '检测区': '机加车间', '收货区': '机加车间',
            '仓储区': '仓储物流', '物流': '仓储物流', '加工区': '生产车间'}
MODEL = {'cnc': 'VMC-850', 'molding': 'HFM-2000 水平分型造型线', 'furnace': 'GW-3T 中频感应炉', 'treatment': 'QH-520 喂丝球化站', 'sand': 'SP-60 砂处理',
         'cooling': 'LS-80 冷却输送线', 'shotblast': 'Q378 吊钩抛丸机', 'deburr': 'IRB-4600 去毛刺单元', 'inspection': 'EV-10 内窥检测', 'warehouse': 'AS-600 立体库',
         'agv': 'AGV-1T 潜伏式', 'plc': 'S7-1200 兼容', 'gateway': 'EG-200 工业网关', 'switch': 'IES-24 工业交换机'}
CONVEYOR_KINDS = {'conveyor', 'cooling'}
DTYPE = {'bool': 'bool', 'int': 'int', 'float': 'float', 'str': 'string'}
NET_PROTO = {'opcua': 'opcua', 'modbus_tcp': 'modbus', 'modbus': 'modbus', 'mqtt': 'mqtt'}
PERIOD = {'action': 100, 'step': 100, 'state': 500, 'alarm': 500, 'count': 1000, 'load': 1000, 'temp': 1000, 'quality': 1000, 'power': 5000,
          'energy': 5000, 'param': 5000, 'other': 1000}
# 已知点位的报警限 / 正常范围（按点位名结尾匹配）
LIMITS = [('Monitoring/Spindle/Load', None, 90, '0~85'), ('Monitoring/Vibration/RMS', None, 4.5, '0.3~2.8'), ('Bath/Temperature', 1380, 1560, '1420~1530'),
          ('Sand/Moisture', 3.2, 4.0, '3.4~3.8'), ('Sand/Compactability', 32, 48, '36~44'), ('Ladle/ResidualMg', 0.030, None, '0.035~0.050'),
          ('Pouring/LastTemp', 1380, 1470, '1395~1450'), ('Quality/BoreDiameter', 40.0, 40.025, '40.005~40.020'), ('Brush/Wear', None, 90, '0~80'),
          ('Dust/Pressure', None, 1800, '600~1500'), ('Actions/Last/ClampExtend', None, 2.0, '0.9~1.4'), ('Actions/Last/ClampRetract', None, 2.0, '0.7~1.2'),
          ('Actions/Last/DoorClose', None, 5.0, '2.7~3.8'), ('Actions/Last/DoorOpen', None, 5.0, '2.5~3.6'), ('Actions/Last/SqueezeExtend', None, 3.5, '1.9~2.6'),
          ('Actions/Last/PushExtend', None, 3.8, '2.0~2.9'), ('Actions/Last/GripperClose', None, 1.0, '0.4~0.6')]


# ================================================================ 设备与点表
def _floor(rt):
    fl = (rt.cfg.get('plant') or {}).get('floor') or ((rt.cfg.get('plant') or {}).get('layout') or {}).get('floor') or [150, 56]
    return float(fl[0]), float(fl[1])


def cad_xy(rt, x, y):
    """平面图坐标（x 向右、y 向下）→ 工厂坐标 / CAD（原点厂房左下角，Y 向上）。"""
    return round(float(x), 3), round(_floor(rt)[1] - float(y), 3)


def type_label(typ):
    try:
        from .flow.catalog import BLOCK_TYPES
        lb = (BLOCK_TYPES.get(typ) or {}).get('label') or typ
    except Exception:
        lb = typ
    return re.sub(r'（高级）$', '', lb)


def _num(expr):
    """节拍表达式的均值：60、'normal(60,3)'、'uniform(50,70)'、'tri(50,60,80)'、'expo(120)'。"""
    if isinstance(expr, (int, float)):
        return float(expr)
    s = str(expr or '').replace(' ', '')
    try:
        return float(s)
    except ValueError:
        pass
    m = re.fullmatch(r'(normal|lognormal|expo|exponential|uniform|tri|triangular|const)\(([-\d.,]+)\)', s)
    if not m:
        return None
    a = [float(x) for x in m.group(2).split(',') if x]
    f = m.group(1)
    if f in ('normal', 'lognormal', 'expo', 'exponential', 'const'):
        return a[0]
    if f == 'uniform' and len(a) >= 2:
        return (a[0] + a[1]) / 2
    if f in ('tri', 'triangular') and len(a) >= 3:
        return sum(a[:3]) / 3
    return None


def ideal_cycle(st):
    k = st.kind
    try:
        if k == 'cnc':
            from .models.machining import HANDLING_S, OPS
            return round(HANDLING_S + sum(o[2] for o in OPS) * st.plant.cycle_factor(), 1)
        if k in ('molding', 'deburr'):
            return float(st.get('Setpoint/CycleSec'))
        if k == 'inspection':
            return float(20 + st.get('Setpoint/Holes') * st.get('Setpoint/SecPerHole'))
        if k == 'processor':
            v = _num(st.cfg.get('time', 'normal(60,3)'))
            return round(v, 1) if v else None
        if k in ('assembly', 'inspect', 'rework', 'batch'):
            v = _num(st.cfg.get('time'))
            return round(v, 1) if v else None
    except Exception:
        return None
    return None


def devices(rt):
    out = []
    for st in list(rt.plant.stations.values()):
        if st.kind in SKIP_KINDS:
            continue
        typ = st.cfg.get('type', st.kind)
        x, y = cad_xy(rt, *(st.pos or [0, 0])[:2])
        size = list(st.size or [1, 1]) + [1, 1]
        note = []
        if st.kind == 'agv':
            note.append(f"{len(getattr(st, 'agvs', []) or [])} 台 AGV 组成的车队（VDA 5050 状态见 README）")
        if st.acts is not None:
            note.append('有动作级信号（Actions/…）')
        out.append({'设备编码': st.id, '设备名称': st.name, '设备类型': type_label(typ), '型号': st.cfg.get('model') or MODEL.get(st.kind, ''),
                    '厂家': st.cfg.get('vendor') or '蜂元虚拟工厂（仿真设备）', '车间': st.cfg.get('workshop') or WORKSHOP.get(st.area, '生产车间' if st.area else '公共'),
                    '产线': st.area or '公共', '工位': f'WS-{st.id}', 'X(m)': x, 'Y(m)': y, '宽(m)': round(float(size[0]), 3), '深(m)': round(float(size[1]), 3),
                    '朝向(°)': round((-float(st.rot or 0)) % 360, 1), '3D模型文件': f'models/{_safe(typ)}.glb', '理想节拍(s)': ideal_cycle(st),
                    '备注': '；'.join(note), '_type': typ, '_kind': st.kind})
    return out


def purpose(tname, tag):
    lo = tname.lower()
    if tname == 'Common/State':
        return 'state'
    if tname == 'Common/Alarm':
        return 'alarm'
    if tag.writable:
        return 'param'
    if tname == 'Common/PowerKW' or tag.unit == 'kW':
        return 'power'
    if tname == 'Common/EnergyKWh' or tag.unit == 'kWh':
        return 'energy'
    if tname == 'Actions/ProgramStep' or lo.endswith('activeprogram/step'):
        return 'step'
    if tname == 'Actions/CycleCount':
        return 'count'
    if tname.startswith('Actions/'):
        return 'action'
    if 'spindle/load' in lo or lo.endswith('/load') or lo.endswith('current'):
        return 'load'
    if tag.unit in ('°C', '℃') or 'temp' in lo:
        return 'temp'
    if tag.writable:
        return 'param'
    if lo.startswith('quality/') or lo.startswith('result/') or 'defect' in lo or 'moisture' in lo or 'hardness' in lo:
        return 'quality'
    if tag.dtype == 'int' and ('count' in lo or 'produced' in lo or 'parts' in lo or 'done' in lo or tag.unit in (variants('件') | variants('次') | variants('批'))):
        return 'count'
    return 'other'


def _limits(tname, tag):
    for suf, lo, hi, normal in LIMITS:
        if tname.endswith(suf):
            return lo, hi, normal
    if tag.writable and tag.lo is not None and tag.hi is not None:
        return None, None, f'{tag.lo:g}~{tag.hi:g}'
    return None, None, ''


def _primary(rt):
    """每台设备的主协议：看网络线（opcua / modbus_tcp / mqtt；profinet、ethernet 等经网关上 MQTT）。"""
    out = {}
    for l in rt.cfg.get('links') or []:
        if l.get('kind') != 'network':
            continue
        pr = NET_PROTO.get(str(l.get('protocol') or '').lower())
        for sid in (l.get('from'), l.get('to')):
            if sid and sid not in out:
                out[sid] = pr or 'mqtt'
    return out


def _addr_tables(rt):
    """三种协议的地址（协议服务没开时按同样的规则算出来）。"""
    p = rt.plant
    raw = rawsite.enabled(p)
    opc = rt.opcua.points() if getattr(rt.opcua, 'top', None) is not None else {}
    if not opc:
        idx = getattr(getattr(rt.mgr, 'opcua', None), 'idx', 2) if not rt.noproto else 2
        names = rawsite.names(p) if raw else {}
        for st in p.stations.values():
            for t in st.tags:
                key = names[(st.id, t)]['opc'] if raw and (st.id, t) in names else f'{st.id}/{t}'
                opc[f'{st.id}/{t}'] = f'ns={idx};s={rt.pid}/{key}'
    if rt.mqtt is not None:
        mq = rt.mqtt.points()
    else:
        from .protocols.mqtt import topic_of
        names = rawsite.names(p) if raw else {}
        mq = {f'{st.id}/{t}': (f"vfactory/{rt.pid}/{names[(st.id, t)]['topic']}" if raw and (st.id, t) in names else topic_of(rt.pid, st, t))
              for st in p.stations.values() for t in st.tags}
    mb_rows = rt.modbus.points()
    if not mb_rows:
        try:
            from .protocols.modbus import ModbusAdapter
            mb_rows = ModbusAdapter(p, None).points()
        except Exception:
            mb_rows = []
    mb = {(r['station'], r['tag']): r for r in mb_rows if r['station'] not in variants('电能表')}
    return opc, mq, mb, mb_rows


def point_rows(rt, protocols='primary'):
    """点表行（PT_COLS 的字典）+ 标准答案。原始现场模式下行里只填 点位编码 / 协议 / 地址 / 数据类型。"""
    p = rt.plant
    raw = rawsite.enabled(p)
    names = rawsite.names(p) if raw else {}
    opc, mq, mb, mb_rows = _addr_tables(rt)
    prim = _primary(rt)
    devs = {d['设备编码'] for d in devices(rt)}
    rows, key = [], []
    for st in list(p.stations.values()):
        if st.id not in devs:
            continue
        for tname, tag in st.tags.items():
            k = f'{st.id}/{tname}'
            m = mb.get((st.id, tname))
            avail = {'opcua': opc.get(k), 'mqtt': mq.get(k), 'modbus': f"{m['unit_id']}:{'coil' if m['kind'] == 'coil' else 'hr'}:{m['address']}" if m else None}
            if protocols == 'all':
                protos = [x for x in ('opcua', 'mqtt', 'modbus') if avail[x]]
            else:
                pr = prim.get(st.id, 'mqtt')
                order = [pr] + [x for x in ('mqtt', 'opcua', 'modbus') if x != pr]
                protos = [next((x for x in order if avail[x]), None)]
                protos = [x for x in protos if x]
            for proto in protos:
                dt = DTYPE.get(tag.dtype, 'string')            # 工程值的类型；寄存器编码写在备注里
                scale, note = 1, ''
                if proto == 'modbus':
                    if m['kind'] == 'coil':
                        dt = 'bool'
                    else:
                        if tname == 'Common/State':
                            dt = 'int'
                        if isinstance(m.get('scale'), (int, float)) and m['scale'] not in (0, 1):
                            scale = round(1 / m['scale'], 6)
                        note = f"{m['datatype']}" + (f" {m['order']}" if m.get('order') else '') + f"，{m['count']} 个寄存器（功能码 03，04 同址镜像）"
                    if tname == 'Common/State':
                        note += '；状态码：' + '、'.join(f'{v}={k}' for k, v in comm_state_codes().items())
                    elif tname == 'Common/Alarm':
                        note = '有报警 = 1（线圈 01，离散输入 02 同址镜像）'
                    elif m['kind'] == 'coil':
                        note = '线圈 01（离散输入 02 同址镜像）'
                elif tag.desc and tname == 'Common/State':
                    note = '状态：Idle 待机、Executing 运行、Starved 缺料、Blocked 堵料、Stopped 停机、Setup 换型、Planned 计划停机'
                pu = purpose(tname, tag)
                lo, hi, normal = _limits(tname, tag)
                if raw:
                    r = names.get((st.id, tname)) or {}
                    code = (r.get('code') if proto != 'modbus' else f"U{m['unit_id']}.{'CO' if m['kind'] == 'coil' else 'HR'}{m['address']}") or k
                else:
                    code = f"{st.id}.{tname.replace('/', '.')}"
                if protocols == 'all':
                    code = f'{code}@{proto}'
                full = {'点位编码': code, '设备编码': st.id, '含义': tag.desc or tname, '单位': tag.unit or '', '数据类型': dt, '读写': 'RW' if tag.writable and (proto != 'modbus' or m.get('writable')) else 'R',
                        '用途': pu, '协议': proto, '地址': avail[proto], '缩放': scale, '偏移': 0, '采集周期(ms)': 0 if proto == 'mqtt' else PERIOD.get(pu, 1000),
                        '报警下限': lo, '报警上限': hi, '正常范围': normal, '备注': note}
                if raw:
                    rows.append({c: (full[c] if c in ('点位编码', '协议', '地址', '数据类型') else None) for c in PT_COLS})
                else:
                    rows.append(full)
                key.append({**full, 'tag': tname, 'device_name': st.name, 'plain_payload': bool(raw and proto == 'mqtt' and (names.get((st.id, tname)) or {}).get('plain'))})
    return rows, key


def comm_state_codes():
    from .protocols.modbus import STATE_CODE
    return STATE_CODE


# ================================================================ Excel
def endpoint_rows(rt):
    ep = comm.endpoints(rt) if not getattr(rt, 'sandbox', False) else {}
    raw = rawsite.enabled(rt.plant)
    idx = getattr(getattr(rt.mgr, 'opcua', None), 'idx', 2) if not rt.noproto else 2
    s = comm.settings(rt.plant)
    mbs = s['modbus']
    off = '（协议服务未开：在客户端设置或服务器上打开）'
    opc_rule = (f'ns={idx};s={rt.pid}/<通道>.<控制器>.<地址>，例如 ns={idx};s={rt.pid}/S7.PLC2.DB10.DBD4、ns={idx};s={rt.pid}/CNC.M3.M3_ZZFZ'
                if raw else f'ns={idx};s={rt.pid}/<设备编码>/<点位>，例如 ns={idx};s={rt.pid}/CNC1/Monitoring/Spindle/Load')
    mq_rule = (f'vfactory/{rt.pid}/<边缘网关>/<PLC>/<地址>、vfactory/{rt.pid}/jj/<机床号_拼音缩写> 等（以点表为准；个别主题不规整，有一台 PLC 的载荷是纯文本数值）'
               if raw else f'vfactory/{rt.pid}/<区域>/<设备编码>/<点位>，例如 vfactory/{rt.pid}/machining/CNC1/Monitoring/Spindle/Load')
    rows = [
        ('OPC UA', '端点', (ep.get('opcua') or off), '安全策略 None（无加密）；匿名登录'),
        ('OPC UA', '命名空间', f'{idx} = http://honeymeta.cn/vfactory', '按 URI 解析命名空间序号，不要写死'),
        ('OPC UA', 'NodeId 规则', opc_rule, '字符串型 NodeId；数值点带 EngineeringUnits / EURange'),
        ('OPC UA', '时间戳', 'SourceTimestamp = 对外时间（仿真时钟或墙钟，见下）', '动作信号的 SourceTimestamp 是动作的精确时刻（毫秒）'),
        ('OPC UA', '写入', 'Write Value 属性；越界 BadOutOfRange、只读 BadUserAccessDenied', ''),
        ('MQTT', 'Broker', (ep.get('mqtt') or off), 'MQTT 3.1.1；匿名' + {'rw': '可读写', 'ro': '只读', 'none': '禁止（用户名随意，密码填 API 令牌）'}.get(_mqtt_anon(), '可读写')),
        ('MQTT', '主题前缀', f'vfactory/{rt.pid}/', '订阅 vfactory/<工厂>/# 可收到全部'),
        ('MQTT', '点位主题', mq_rule, '只在变化时发（report by exception），retain'),
        ('MQTT', '载荷', '{"value": 12.5, "unit": "%", "quality": "good"|"bad", "ts": "...", "sim_ts": "...", "wall_ts": "..."}',
         'ts 是对外时间（ISO 8601，带时区）；动作信号的 ts / sim_ts 精确到毫秒'),
        ('MQTT', '写入', '<点位主题>/set，载荷 {"value": x} 或纯数值；回执 <点位主题>/set/ack', 'retain 的 /set 不执行'),
        ('MQTT', '状态 / 报工', f'vfactory/{rt.pid}/_status（心跳）、vfactory/{rt.pid}/_mes/part（零件事件）、vfactory/{rt.pid}/_mes/event（生产日志）', '扫码 / 报工网关，不受原始现场模式影响'),
        ('MQTT', 'AGV', f'vda5050/v2/{rt.pid}/<AGV>/state', 'VDA 5050 风格状态'),
        ('Modbus TCP', '端点', (ep.get('modbus') or off), '每台设备一个从站（Unit ID），见点表 地址 = 从站:表:地址'),
        ('Modbus TCP', '地址约定', '地址从 0 起（PDU 地址；4x 寄存器 40001 = 地址 0）；表 hr = 保持寄存器（功能码 03/06/16），coil = 线圈（01/05/15）',
         '保持寄存器同址镜像到输入寄存器（04），线圈镜像到离散输入（02）'),
        ('Modbus TCP', '数据类型', f"默认 {mbs.get('fmt', 'float32')}，字序 {mbs.get('order', 'ABCD')}；int16 点按 缩放 换算（工程值 = 原始值 × 缩放 + 偏移）",
         '运行状态是 int16 状态码；报警是线圈'),
        ('Modbus TCP', '电能表', 'Unit 10：0–1 全厂功率 kW、2–3 全厂电能 kWh（float32），之后每个区域 4 个寄存器', ''),
        ('全部', '对外时间', '仿真时间' if s['time'] == 'sim' else '墙钟', '协议设置里可改；仿真可能快进，节拍分析请用仿真时间'),
    ]
    return rows


def _mqtt_anon():
    try:
        from .protocols.mqtt import MqttHub
        return (MqttHub.instance.auth if MqttHub.instance else {}).get('anonymous', 'rw')
    except Exception:
        return 'rw'


EXPLAIN = [
    ('设备', '设备编码', '设备唯一编码（和协议地址、图纸块属性 CODE、三维节点名一致）'),
    ('设备', '设备名称 / 设备类型 / 型号 / 厂家', '台账信息'),
    ('设备', '车间 / 产线 / 工位', '组织结构：车间 → 产线（区域）→ 工位（WS-设备编码）'),
    ('设备', 'X(m) / Y(m)', '设备中心在工厂坐标系的位置：原点在厂房左下角，X 向右，Y 向上（与 layout.dxf 一致）'),
    ('设备', '宽(m) / 深(m)', '设备外形：宽沿设备自身 X 方向，深沿设备自身 Y 方向（朝向为 0 时与工厂坐标轴一致）'),
    ('设备', '朝向(°)', '设备绕竖直轴的转角，逆时针为正（与 DXF 块插入角一致）'),
    ('设备', '3D模型文件', '交付包里的 glTF 二进制模型（米，Y 向上）'),
    ('设备', '理想节拍(s)', '设计节拍（标准循环时间），算性能开动率用；空 = 不适用'),
    ('点表', '点位编码', '点位唯一编码'),
    ('点表', '设备编码', '属于哪台设备（对应设备表）'),
    ('点表', '含义 / 单位', '点位的中文含义和工程单位'),
    ('点表', '数据类型', 'bool / int / float / string（按工程值）'),
    ('点表', '读写', 'R 只读 / RW 可写（设定值）'),
    ('点表', '用途', 'state 运行状态、alarm 报警、count 计数、power 功率、energy 电能、load 负载、temp 温度、quality 质量、'
                     'action 动作信号（阀 / 到位 / 循环）、step 程序段号、param 设定参数、other 其它'),
    ('点表', '协议', 'opcua / mqtt / modbus'),
    ('点表', '地址', 'OPC UA：完整 NodeId（ns=…;s=…）；MQTT：完整主题；Modbus：从站:表:地址（表 hr 保持寄存器 / coil 线圈，地址从 0 起）'),
    ('点表', '缩放 / 偏移', '工程值 = 原始值 × 缩放 + 偏移（只有 Modbus 整数寄存器会用到）'),
    ('点表', '采集周期(ms)', '建议的采集（轮询 / 订阅采样）周期；0 = 变化即推送（MQTT）'),
    ('点表', '报警下限 / 报警上限', '超出即报警；空 = 不设'),
    ('点表', '正常范围', '正常工况范围（文字，如 0~85）'),
    ('点表', '备注', 'Modbus 寄存器编码、状态码对照等'),
]


def xlsx_bytes(rt, devs, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    head = PatternFill('solid', fgColor='F2C94C')

    def sheet(ws, cols, data, widths):
        ws.append(cols)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True), head
        for r in data:
            ws.append([r.get(c) if isinstance(r, dict) else r[i] for i, c in enumerate(cols)])
        for i, w in enumerate(widths):
            ws.column_dimensions[_col(i)].width = w
        ws.freeze_panes = 'A2'
        if data:
            ws.auto_filter.ref = f'A1:{_col(len(cols) - 1)}{len(data) + 1}'

    ws = wb.active
    ws.title = '设备'
    sheet(ws, DEV_COLS, devs, (12, 22, 16, 22, 22, 10, 10, 12, 9, 9, 8, 8, 8, 26, 11, 30))
    sheet(wb.create_sheet('点表'), PT_COLS, rows, (36, 12, 26, 7, 9, 6, 8, 8, 60, 7, 6, 11, 9, 9, 14, 40))
    sheet(wb.create_sheet('协议'), ['协议', '项目', '值', '说明'], [list(r) for r in endpoint_rows(rt)], (12, 12, 90, 50))
    ws = wb.create_sheet('说明')
    ws.append(['表', '列', '说明'])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True), head
    raw = rawsite.enabled(rt.plant)
    intro = [('交付包', '格式', '蜂元交付包 点表格式 v1（docs/interface/点表格式.md）；MES 接入规范用同一格式'),
             ('交付包', '工厂', f'{rt.plant.name}（{rt.pid}）'), ('交付包', '生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
             ('交付包', '现场状态', '原始现场：点表只有 点位编码 / 协议 / 地址 / 数据类型，含义、单位、设备待补全' if raw else '已整理：点表完整')]
    for r in intro + EXPLAIN:
        ws.append(list(r))
    for col, w in (('A', 10), ('B', 26), ('C', 110)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        row[2].alignment = Alignment(wrap_text=True, vertical='top')
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _col(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# ================================================================ DXF（R12 ASCII，不依赖第三方库）
LAYERS = [('VF_WALL', 7, '墙体 / 厂房外轮廓'), ('VF_AREA', 8, '区域（多边形 + 名称）'), ('VF_AISLE', 9, '通道'), ('VF_DEVICE', 5, '设备外形（块，属性 CODE / NAME / TYPE）'),
          ('VF_CONVEYOR', 3, '输送线（块，属性同设备）'), ('VF_AGV_PATH', 1, 'AGV 路径与站点'), ('VF_TEXT', 7, '文字标注')]


def _dxf_text(s):
    """非 ASCII 字符写成 \\U+XXXX（AutoCAD / ezdxf 都认），文件保持纯 ASCII。"""
    return ''.join(ch if 32 <= ord(ch) < 127 else f'\\U+{ord(ch):04X}' for ch in str(s or ''))


def _block_name(code):
    return 'DEV_' + re.sub(r'[^A-Za-z0-9_-]', '_', str(code))


class _Dxf:
    def __init__(self):
        self.out = []

    def g(self, code, val):
        if isinstance(val, float):
            val = f'{val:.4f}'.rstrip('0').rstrip('.') if '.' in f'{val:.4f}' else f'{val:.4f}'
        self.out += [str(code), str(val)]

    def poly(self, layer, pts, closed=True):
        self.g(0, 'POLYLINE'); self.g(8, layer); self.g(66, 1); self.g(10, 0.0); self.g(20, 0.0); self.g(30, 0.0); self.g(70, 1 if closed else 0)
        for x, y in pts:
            self.g(0, 'VERTEX'); self.g(8, layer); self.g(10, float(x)); self.g(20, float(y)); self.g(30, 0.0)
        self.g(0, 'SEQEND'); self.g(8, layer)

    def line(self, layer, a, b):
        self.g(0, 'LINE'); self.g(8, layer); self.g(10, float(a[0])); self.g(20, float(a[1])); self.g(30, 0.0)
        self.g(11, float(b[0])); self.g(21, float(b[1])); self.g(31, 0.0)

    def text(self, layer, x, y, h, s, rot=0.0):
        self.g(0, 'TEXT'); self.g(8, layer); self.g(10, float(x)); self.g(20, float(y)); self.g(30, 0.0); self.g(40, float(h)); self.g(1, _dxf_text(s))
        if rot:
            self.g(50, float(rot))

    def circle(self, layer, x, y, r):
        self.g(0, 'CIRCLE'); self.g(8, layer); self.g(10, float(x)); self.g(20, float(y)); self.g(30, 0.0); self.g(40, float(r))


def _rect(cx, cy, L, W, ang=0.0):
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return [(round(cx + x * c - y * s, 4), round(cy + x * s + y * c, 4)) for x, y in ((-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2))]


def dxf_text(rt, devs=None):
    devs = devs if devs is not None else devices(rt)
    Wf, Df = _floor(rt)
    lay = (rt.cfg.get('plant') or {}).get('layout') or {}
    C = lambda x, y: cad_xy(rt, x, y)
    body = _Dxf()
    # 墙：布局里画了墙就用，没有就用厂房外轮廓
    walls = lay.get('walls') or []
    if walls:
        for w in walls:
            pts = [C(*p[:2]) for p in (w.get('pts') or [])]
            if len(pts) >= 2:
                body.poly('VF_WALL', pts, closed=bool(w.get('outer') or w.get('closed')))
    else:
        body.poly('VF_WALL', [(0, 0), (Wf, 0), (Wf, Df), (0, Df)])
    # 区域
    zones = lay.get('zones') or []
    for z in zones:
        pts = [C(*p[:2]) for p in (z.get('pts') or [])]
        if len(pts) >= 3:
            body.poly('VF_AREA', pts)
            cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            body.text('VF_AREA', cx, cy, 1.0, z.get('name') or z.get('id') or '')
    if not zones:
        for a in rt.cfg.get('areas') or []:
            x0, x1 = (a.get('x') or [0, 0])[:2]
            y0, y1 = (a.get('y') or [0, Df])[:2]
            pts = [C(x0, y0), C(x1, y0), C(x1, y1), C(x0, y1)]
            body.poly('VF_AREA', pts)
            body.text('VF_AREA', x0 + 0.8, Df - y0 - 2.0, 1.2, a.get('name') or '')
    for a in lay.get('aisles') or []:
        pts = [C(*p[:2]) for p in (a.get('pts') or [])]
        if len(pts) >= 2:
            body.poly('VF_AISLE', pts, closed=len(pts) > 2 and bool(a.get('closed', True)))
    # AGV 路径：布局路网；没有路网时用车队站点 + 通道线
    paths_ = lay.get('paths') or {}
    nodes = {n['id']: n for n in paths_.get('nodes') or [] if 'id' in n}
    for e in paths_.get('edges') or []:
        a, b = nodes.get(e.get('a')), nodes.get(e.get('b'))
        if a and b:
            body.line('VF_AGV_PATH', C(a['x'], a['y']), C(b['x'], b['y']))
    for n in nodes.values():
        x, y = C(n['x'], n['y'])
        body.circle('VF_AGV_PATH', x, y, 0.3)
        if n.get('name') or n.get('station'):
            body.text('VF_AGV_PATH', x + 0.4, y + 0.4, 0.5, n.get('name') or n.get('station'))
    if not nodes:
        for st in rt.plant.stations.values():
            if st.kind != 'agv':
                continue
            nd = getattr(st, 'nodes', None) or st.cfg.get('nodes') or {}
            cy = st.cfg.get('corridor_y')
            if cy is not None and nd:
                xs = [float(v[0]) for v in nd.values()]
                body.line('VF_AGV_PATH', C(min(xs), cy), C(max(xs), cy))
            for name, v in nd.items():
                x, y = C(v[0], v[1])
                body.circle('VF_AGV_PATH', x, y, 0.35)
                body.text('VF_AGV_PATH', x + 0.5, y + 0.5, 0.6, name)
                if cy is not None:
                    body.line('VF_AGV_PATH', (x, y), C(v[0], cy))
    # 设备：每台一个块（外形 + 属性定义），插入点 = 设备中心，转角 = 朝向
    blocks = _Dxf()
    for d in devs:
        L, W = max(0.05, d['宽(m)']), max(0.05, d['深(m)'])
        layer = 'VF_CONVEYOR' if d['_kind'] in CONVEYOR_KINDS else 'VF_DEVICE'
        bn = _block_name(d['设备编码'])
        blocks.g(0, 'BLOCK'); blocks.g(8, '0'); blocks.g(2, bn); blocks.g(70, 2); blocks.g(10, 0.0); blocks.g(20, 0.0); blocks.g(30, 0.0); blocks.g(3, bn)
        blocks.poly(layer, _rect(0, 0, L, W))
        blocks.line(layer, (L / 2 - min(L, W) * 0.25, 0), (L / 2, 0))        # 朝向标记（设备自身 +X）
        th = max(0.25, min(1.0, min(L, W) * 0.3))
        for i, (tag, prompt) in enumerate((('CODE', '设备编码'), ('NAME', '设备名称'), ('TYPE', '设备类型'))):
            blocks.g(0, 'ATTDEF'); blocks.g(8, layer); blocks.g(10, -L / 2 + 0.1); blocks.g(20, -th * (i + 0.5)); blocks.g(30, 0.0); blocks.g(40, th)
            blocks.g(1, ''); blocks.g(3, _dxf_text(prompt)); blocks.g(2, tag); blocks.g(70, 0 if tag == 'CODE' else 1)
        blocks.g(0, 'ENDBLK'); blocks.g(8, '0')
        x, y, ang = d['X(m)'], d['Y(m)'], d['朝向(°)']
        body.g(0, 'INSERT'); body.g(8, layer); body.g(66, 1); body.g(2, bn); body.g(10, float(x)); body.g(20, float(y)); body.g(30, 0.0)
        if ang:
            body.g(50, float(ang))
        for i, (tag, val) in enumerate((('CODE', d['设备编码']), ('NAME', d['设备名称']), ('TYPE', d['设备类型']))):
            body.g(0, 'ATTRIB'); body.g(8, layer); body.g(10, float(x) - L / 2 + 0.1); body.g(20, float(y) - th * (i + 0.5)); body.g(30, 0.0); body.g(40, th)
            body.g(1, _dxf_text(val)); body.g(2, tag); body.g(70, 0 if tag == 'CODE' else 1)
        body.g(0, 'SEQEND'); body.g(8, layer)
    xs = [0.0, Wf] + [d['X(m)'] for d in devs]
    ys = [0.0, Df] + [d['Y(m)'] for d in devs]
    h = _Dxf()
    h.g(0, 'SECTION'); h.g(2, 'HEADER')
    h.g(9, '$ACADVER'); h.g(1, 'AC1009')
    h.g(9, '$INSUNITS'); h.g(70, 6)
    h.g(9, '$DWGCODEPAGE'); h.g(3, 'ANSI_1252')
    h.g(9, '$EXTMIN'); h.g(10, float(min(xs) - 5)); h.g(20, float(min(ys) - 5)); h.g(30, 0.0)
    h.g(9, '$EXTMAX'); h.g(10, float(max(xs) + 5)); h.g(20, float(max(ys) + 5)); h.g(30, 0.0)
    h.g(0, 'ENDSEC')
    h.g(0, 'SECTION'); h.g(2, 'TABLES')
    h.g(0, 'TABLE'); h.g(2, 'LTYPE'); h.g(70, 1)
    h.g(0, 'LTYPE'); h.g(2, 'CONTINUOUS'); h.g(70, 0); h.g(3, 'Solid line'); h.g(72, 65); h.g(73, 0); h.g(40, 0.0)
    h.g(0, 'ENDTAB')
    h.g(0, 'TABLE'); h.g(2, 'LAYER'); h.g(70, len(LAYERS) + 1)
    for name, color, _desc in [('0', 7, '')] + LAYERS:
        h.g(0, 'LAYER'); h.g(2, name); h.g(70, 0); h.g(62, color); h.g(6, 'CONTINUOUS')
    h.g(0, 'ENDTAB')
    h.g(0, 'TABLE'); h.g(2, 'STYLE'); h.g(70, 1)
    h.g(0, 'STYLE'); h.g(2, 'STANDARD'); h.g(70, 0); h.g(40, 0.0); h.g(41, 1.0); h.g(50, 0.0); h.g(71, 0); h.g(42, 2.5); h.g(3, 'txt'); h.g(4, '')
    h.g(0, 'ENDTAB')
    h.g(0, 'ENDSEC')
    h.g(0, 'SECTION'); h.g(2, 'BLOCKS')
    h.out += blocks.out
    h.g(0, 'ENDSEC')
    h.g(0, 'SECTION'); h.g(2, 'ENTITIES')
    h.out += body.out
    h.g(0, 'ENDSEC'); h.g(0, 'EOF')
    return '\r\n'.join(h.out) + '\r\n'


# ================================================================ glTF 2.0 二进制（GLB），程序化简化模型
def _safe(s):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', str(s)) or 'device'


def _box(sx, sy, sz, cx=0.0, cy=0.0, cz=0.0):
    """中心 (cx, cy, cz)、尺寸 sx×sy×sz 的立方体：24 个顶点（每面单独法线）。"""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    faces = [((1, 0, 0), [(hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)]),
             ((-1, 0, 0), [(-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz), (-hx, -hy, -hz)]),
             ((0, 1, 0), [(-hx, hy, -hz), (-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz)]),
             ((0, -1, 0), [(-hx, -hy, hz), (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz)]),
             ((0, 0, 1), [(hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz), (-hx, -hy, hz)]),
             ((0, 0, -1), [(-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz)])]
    pos, nor, idx = [], [], []
    for n, quad in faces:
        b = len(pos)
        for x, y, z in quad:
            pos.append((x + cx, y + cy, z + cz))
            nor.append(n)
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    return pos, nor, idx


def _cyl(r, h, cx=0.0, cy=0.0, cz=0.0, seg=20):
    """竖直圆柱（Y 向上），底面中心 (cx, cy, cz)。"""
    pos, nor, idx = [], [], []
    for i in range(seg):
        a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
        b = len(pos)
        for a, y in ((a0, 0), (a0, h), (a1, h), (a1, 0)):
            pos.append((cx + r * math.cos(a), cy + y, cz + r * math.sin(a)))
            nor.append((math.cos(a), 0, math.sin(a)))
        idx += [b, b + 2, b + 1, b, b + 3, b + 2]
    for y, ny in ((h, 1), (0, -1)):
        c = len(pos)
        pos.append((cx, cy + y, cz))
        nor.append((0, ny, 0))
        for i in range(seg):
            a = 2 * math.pi * i / seg
            pos.append((cx + r * math.cos(a), cy + y, cz + r * math.sin(a)))
            nor.append((0, ny, 0))
        for i in range(seg):
            j, k = c + 1 + i, c + 1 + (i + 1) % seg
            idx += ([c, k, j] if ny > 0 else [c, j, k])
    return pos, nor, idx


GREY, DARK, LIGHT, BLUE, ORANGE, YELLOW, GREEN, RED, WOOD, STEEL = ((0.6, 0.62, 0.65), (0.22, 0.24, 0.27), (0.86, 0.88, 0.9), (0.25, 0.48, 0.75),
                                                                  (0.85, 0.45, 0.15), (0.95, 0.75, 0.15), (0.2, 0.6, 0.35), (0.75, 0.2, 0.2),
                                                                  (0.65, 0.5, 0.3), (0.5, 0.55, 0.6))


def model_parts(kind, L, W):
    """一类设备的简化外形：[(几何, 颜色), …]，单位米，原点在设备底面中心，X 沿宽（设备自身 X）、Z 沿深。"""
    m = min(L, W)
    if kind == 'cnc':
        return [(_box(L, 0.8, W, 0, 0.4, 0), DARK), (_box(L * 0.96, 1.6, W * 0.9, 0, 1.6, 0), LIGHT), (_box(L * 0.4, 0.6, 0.03, -L * 0.12, 1.6, W * 0.45 + 0.02), BLUE),
                (_box(0.35, 0.55, 0.15, L * 0.5 + 0.1, 1.5, W * 0.3), DARK)]
    if kind == 'molding':
        return [(_box(L, 1.1, W, 0, 0.55, 0), STEEL), (_box(min(L * 0.12, 4), 3.4, W * 0.9, -L * 0.35, 1.7, 0), BLUE), (_box(L * 0.8, 0.12, W * 0.6, L * 0.05, 1.16, 0), DARK)]
    if kind in ('conveyor', 'cooling', 'cell'):
        parts = [(_box(L, 0.15, W * 0.8, 0, 0.8, 0), DARK), (_box(L, 0.08, 0.06, 0, 0.92, W * 0.42), YELLOW), (_box(L, 0.08, 0.06, 0, 0.92, -W * 0.42), YELLOW)]
        n = max(2, int(L / 3) + 1)
        for i in range(n):
            x = -L / 2 + 0.1 + (L - 0.2) * i / (n - 1)
            parts += [(_box(0.08, 0.75, 0.08, x, 0.375, W * 0.35), STEEL), (_box(0.08, 0.75, 0.08, x, 0.375, -W * 0.35), STEEL)]
        return parts
    if kind == 'furnace':
        return [(_box(L, 0.6, W, 0, 0.3, 0), DARK), (_cyl(m * 0.35, 1.6, 0, 0.6, 0), ORANGE), (_box(L * 0.3, 1.2, W * 0.25, L * 0.3, 1.2, -W * 0.3), GREY)]
    if kind == 'treatment':
        return [(_box(L, 0.4, W, 0, 0.2, 0), STEEL), (_cyl(m * 0.3, 1.4, -L * 0.2, 0.4, 0), ORANGE), (_box(L * 0.3, 2.4, W * 0.3, L * 0.3, 1.6, 0), GREY)]
    if kind == 'sand':
        return [(_box(L, 1.0, W, 0, 0.5, 0), STEEL), (_cyl(m * 0.3, 3.0, -L * 0.25, 1.0, 0), GREY), (_cyl(m * 0.25, 2.5, L * 0.25, 1.0, 0), GREY)]
    if kind == 'shotblast':
        return [(_box(L, 3.2, W, 0, 1.6, 0), STEEL), (_box(L * 0.5, 2.4, 0.05, 0, 1.4, W / 2 + 0.03), DARK)]
    if kind == 'deburr':
        return [(_box(L, 0.05, W, 0, 0.025, 0), DARK), (_cyl(0.35, 0.7, 0, 0.05, 0), ORANGE), (_box(0.3, 1.1, 0.3, 0, 1.3, 0), ORANGE),
                (_box(1.2, 0.25, 0.25, 0.6, 1.9, 0), ORANGE), (_box(L * 0.3, 0.9, W * 0.3, L * 0.3, 0.45, W * 0.3), GREY)]
    if kind in ('inspection', 'inspect'):
        return [(_box(L, 0.9, W, 0, 0.45, 0), LIGHT), (_box(0.1, 1.4, W, -L * 0.45, 1.6, 0), STEEL), (_box(0.1, 1.4, W, L * 0.45, 1.6, 0), STEEL),
                (_box(L, 0.15, 0.2, 0, 2.3, 0), STEEL), (_box(0.2, 0.6, 0.2, 0, 1.9, 0), BLUE)]
    if kind in ('warehouse', 'storage'):
        parts = []
        for lv in range(5):
            parts.append((_box(L, 0.08, W * 0.45, 0, 0.3 + lv * 1.6, W * 0.27), ORANGE))
            parts.append((_box(L, 0.08, W * 0.45, 0, 0.3 + lv * 1.6, -W * 0.27), ORANGE))
        for x in (-L / 2 + 0.1, 0, L / 2 - 0.1):
            parts += [(_box(0.12, 7.0, 0.12, x, 3.5, W * 0.48), BLUE), (_box(0.12, 7.0, 0.12, x, 3.5, -W * 0.48), BLUE)]
        return parts
    if kind == 'agv':
        return [(_box(1.2, 0.35, 0.8, 0, 0.2, 0), YELLOW), (_box(0.3, 0.12, 0.6, 0.35, 0.43, 0), DARK)]
    if kind in ('buffer', 'source', 'sink'):
        return [(_box(L, 0.15, W, 0, 0.075, 0), WOOD), (_box(L * 0.8, 0.6, W * 0.8, 0, 0.45, 0), GREY)]
    if kind in ('plc', 'hmi', 'gateway', 'switch', 'scada', 'mes'):
        return [(_box(max(L, 0.3), max(0.4, min(2.0, m * 2)), max(W, 0.2), 0, max(0.4, min(2.0, m * 2)) / 2 + 0.6, 0), GREY)]
    if kind in ('processor', 'batch', 'assembly', 'rework'):
        return [(_box(L, 0.9, W, 0, 0.45, 0), STEEL), (_box(L * 0.8, 1.0, W * 0.7, 0, 1.4, 0), LIGHT), (_box(0.3, 0.5, 0.12, L * 0.45, 1.3, W * 0.3), DARK)]
    return [(_box(L, 1.5, W, 0, 0.75, 0), GREY)]


class _Gltf:
    def __init__(self):
        self.bin = bytearray()
        self.j = {'asset': {'version': '2.0', 'generator': 'HoneyMeta VirtualFactory delivery'}, 'scene': 0, 'scenes': [{'nodes': []}], 'nodes': [], 'meshes': [],
                  'materials': [], 'accessors': [], 'bufferViews': [], 'buffers': []}
        self.mat = {}

    def _view(self, data: bytes, target):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += data
        self.j['bufferViews'].append({'buffer': 0, 'byteOffset': off, 'byteLength': len(data), 'target': target})
        return len(self.j['bufferViews']) - 1

    def _acc(self, view, ctype, count, typ, mn=None, mx=None):
        a = {'bufferView': view, 'componentType': ctype, 'count': count, 'type': typ}
        if mn is not None:
            a['min'], a['max'] = mn, mx
        self.j['accessors'].append(a)
        return len(self.j['accessors']) - 1

    def material(self, rgb):
        if rgb not in self.mat:
            self.j['materials'].append({'pbrMetallicRoughness': {'baseColorFactor': [*rgb, 1.0], 'metallicFactor': 0.2, 'roughnessFactor': 0.7}})
            self.mat[rgb] = len(self.j['materials']) - 1
        return self.mat[rgb]

    def mesh(self, name, parts):
        prims = []
        for (pos, nor, idx), rgb in parts:
            pb = b''.join(struct.pack('<3f', *p) for p in pos)
            nb = b''.join(struct.pack('<3f', *n) for n in nor)
            ib = struct.pack(f'<{len(idx)}I', *idx)
            mn = [min(p[i] for p in pos) for i in range(3)]
            mx = [max(p[i] for p in pos) for i in range(3)]
            a_p = self._acc(self._view(pb, 34962), 5126, len(pos), 'VEC3', mn, mx)
            a_n = self._acc(self._view(nb, 34962), 5126, len(nor), 'VEC3')
            a_i = self._acc(self._view(ib, 34963), 5125, len(idx), 'SCALAR')
            prims.append({'attributes': {'POSITION': a_p, 'NORMAL': a_n}, 'indices': a_i, 'material': self.material(rgb)})
        self.j['meshes'].append({'name': name, 'primitives': prims})
        return len(self.j['meshes']) - 1

    def node(self, d, root=True):
        self.j['nodes'].append(d)
        i = len(self.j['nodes']) - 1
        if root:
            self.j['scenes'][0]['nodes'].append(i)
        return i

    def glb(self):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j['buffers'] = [{'byteLength': len(self.bin)}]
        js = json.dumps(self.j, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        while len(js) % 4:
            js += b' '
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        return (struct.pack('<4sII', b'glTF', 2, total) + struct.pack('<I4s', len(js), b'JSON') + js +
                struct.pack('<I4s', len(self.bin), b'BIN\x00') + bytes(self.bin))


def _dims(rt, d):
    return max(0.2, float(d['宽(m)'])), max(0.2, float(d['深(m)']))


def glb_models(rt, devs=None):
    """{文件名: GLB 字节}：每类设备一个（按这一类第一台的尺寸），外加 scene.glb（每台设备一个节点，名字 = 设备编码）。"""
    devs = devs if devs is not None else devices(rt)
    first = {}
    for d in devs:
        first.setdefault(d['_type'], d)
    out = {}
    for typ, d in first.items():
        L, W = _dims(rt, d)
        g = _Gltf()
        mi = g.mesh(typ, model_parts(d['_kind'], L, W))
        g.node({'name': typ, 'mesh': mi, 'extras': {'type': d['设备类型'], 'size_m': [L, W]}})
        out[f'{_safe(typ)}.glb'] = g.glb()
    # 整厂场景：工厂坐标 (X, Y) → glTF (X, 高度, −Y)；朝向 a（逆时针）→ 绕 +Y 转 a
    g = _Gltf()
    Wf, Df = _floor(rt)
    fl = g.mesh('Floor', [(_box(Wf, 0.05, Df, Wf / 2, -0.025, -Df / 2), (0.78, 0.8, 0.82))])
    g.node({'name': 'Floor', 'mesh': fl})
    meshes = {}
    for typ, d in first.items():
        L, W = _dims(rt, d)
        meshes[typ] = (g.mesh(typ, model_parts(d['_kind'], L, W)), L, W)
    for d in devs:
        mi, L0, W0 = meshes[d['_type']]
        L, W = _dims(rt, d)
        a = math.radians(float(d['朝向(°)'] or 0))
        nd = {'name': d['设备编码'], 'mesh': mi, 'translation': [float(d['X(m)']), 0.0, -float(d['Y(m)'])],
              'extras': {'code': d['设备编码'], 'name': d['设备名称'], 'type': d['设备类型'], 'model_file': d['3D模型文件']}}
        if a:
            nd['rotation'] = [0.0, math.sin(a / 2), 0.0, math.cos(a / 2)]
        if abs(L / L0 - 1) > 1e-3 or abs(W / W0 - 1) > 1e-3:
            nd['scale'] = [L / L0, 1.0, W / W0]
        g.node(nd)
    out['scene.glb'] = g.glb()
    return out


def check_glb(data: bytes) -> dict:
    """GLB 头和 JSON 块的基本校验（客户端上传的模型也过一遍）。"""
    if len(data) < 20 or data[:4] != b'glTF':
        raise ValueError('不是 GLB 文件')
    ver, total = struct.unpack('<II', data[4:12])
    if ver != 2 or total != len(data):
        raise ValueError('GLB 头不对（版本或长度）')
    n, kind = struct.unpack('<I4s', data[12:20])
    if kind != b'JSON':
        raise ValueError('GLB 第一块不是 JSON')
    j = json.loads(data[20:20 + n])
    if (j.get('asset') or {}).get('version') != '2.0':
        raise ValueError('不是 glTF 2.0')
    return j


# ================================================================ README
def readme(rt, devs, rows, files):
    raw = rawsite.enabled(rt.plant)
    ep = {r[0] + '|' + r[1]: r[2] for r in endpoint_rows(rt)}
    n_act = sum(1 for r in rows if r.get('用途') in ('action', 'step'))
    acts = sorted({st.id for st in rt.plant.stations.values() if st.acts is not None})
    L = [f'# 交付包：{rt.plant.name}（{rt.pid}）', '',
         f'生成时间 {datetime.now():%Y-%m-%d %H:%M:%S}，蜂元虚拟工厂。格式：蜂元交付包 点表格式 v1（和蜂元智能 MES 接入规范一致）。', '']
    if raw:
        L += ['> **原始现场**：这是集成商刚调完、还没整理的现场。点表只有 点位编码 / 协议 / 地址 / 数据类型，'
              '含义、单位、所属设备需要接入方自己摸清（读值、看变化、对照设备清单和图纸）。地址命名是 PLC / 数控系统的原始地址和拼音缩写，'
              '个别 MQTT 主题不规整，有一台 PLC 的网关发的是纯文本数值（不是 JSON）。', '']
    L += ['## 文件', '', '| 文件 | 内容 |', '|---|---|', '| README.md | 本说明 |',
          f'| points.xlsx | 设备（{len(devs)} 台）、点表（{len(rows)} 行）、协议、说明 四张表 |',
          '| layout.dxf | 平面布置图（DXF R12，单位米），每类一层，设备是带属性的块 |']
    for f in files:
        if f.startswith('models/') and f != 'models/scene.glb':
            L.append(f'| {f} | 设备三维模型（glTF 2.0 二进制，米，Y 向上） |')
    L += ['| models/scene.glb | 整厂三维场景：每台设备一个节点，节点名 = 设备编码，extras 里有编码、名称、类型 |', '',
          '## 坐标系', '',
          '- 工厂坐标：原点在厂房左下角，X 向右，Y 向上，单位米。设备表的 X(m)/Y(m) 是设备中心；朝向(°) 逆时针为正。',
          '- layout.dxf 和工厂坐标完全一致（$INSUNITS = 6 米）。设备块插入点 = 设备中心，插入角 = 朝向，块里画了一根短线指向设备自身 +X。',
          '- 三维（glTF，Y 向上）：glTF X = 工厂 X，glTF Y = 高度，glTF Z = −工厂 Y；朝向 a 对应绕 +Y 轴转 a。', '',
          '## 图层（layout.dxf）', '', '| 图层 | 内容 |', '|---|---|']
    L += [f'| {n} | {d} |' for n, _c, d in LAYERS]
    L += ['', '块属性：CODE（设备编码，可见）、NAME（设备名称）、TYPE（设备类型）。中文按 \\U+XXXX 转义（AutoCAD、ezdxf 都能识别）。', '',
          '## 协议接入', '', '### OPC UA', '',
          f"- 端点：`{ep.get('OPC UA|端点')}`（安全策略 None，匿名）",
          f"- 命名空间：{ep.get('OPC UA|命名空间')}",
          f"- NodeId：{ep.get('OPC UA|NodeId 规则')}",
          '- 时间戳：SourceTimestamp = 对外时间；动作信号的 SourceTimestamp 是动作发生的精确时刻（毫秒）。数值点带 EngineeringUnits、EURange，支持 HistoryRead。', '',
          '### MQTT', '',
          f"- Broker：`{ep.get('MQTT|Broker')}`，MQTT 3.1.1",
          f"- 点位主题：{ep.get('MQTT|点位主题')}",
          '- 载荷（JSON，retain，只在变化时发）：', '', '```json',
          '{"value": 12.5, "unit": "%", "quality": "good", "ts": "2026-11-04T08:00:00+08:00", "sim_ts": "2026-11-04T08:00:00+08:00", "wall_ts": "2026-11-04T08:00:01.234+08:00"}',
          '```', '',
          '  quality：good / bad（通讯故障时）；ts 按协议设置是仿真时间或墙钟；动作信号的 ts / sim_ts 精确到毫秒。',
          f"- 写入：`<点位主题>/set`，载荷 `{{\"value\": 60}}` 或纯数值；回执 `<点位主题>/set/ack`（ok / error / code）。",
          f"- 心跳与报工：{ep.get('MQTT|状态 / 报工')}",
          f"- AGV：{ep.get('MQTT|AGV')}", '',
          '### Modbus TCP', '',
          f"- 端点：`{ep.get('Modbus TCP|端点')}`；每台设备一个从站（Unit ID），点表地址写成 `从站:表:地址`，例如 `11:hr:1000`、`11:coil:1000`。",
          f"- {ep.get('Modbus TCP|地址约定')}；保持寄存器同址镜像到输入寄存器（04），线圈镜像到离散输入（02）。",
          f"- {ep.get('Modbus TCP|数据类型')}；多寄存器的类型和字序写在点表 备注 里（例如 `float32 ABCD，2 个寄存器`）。",
          '- 运行状态 Common/State 是 int16 状态码：0 待机、1 运行、2 缺料、3 堵料、4 停机、5 换型、6 计划停机；报警是线圈（有报警 = 1）。',
          f"- {ep.get('Modbus TCP|电能表')}", '', '## 动作级信号（节拍分析）', '']
    if acts:
        L += [f"有动作信号的设备：{'、'.join(acts)}（点表里 用途 = action / step 的 {n_act} 行）。", '',
              '- 加工中心：防护门关门指令 DoorCloseCmd、关到位 DoorClosed、开到位 DoorOpened；夹具电磁阀 ClampValve、夹紧到位 ClampExtended、松开到位 ClampRetracted；'
              '主轴 SpindleRun；程序段号 ProgramStep（10…60 = OP10…OP60，0 = 空闲）；循环 CycleOn（上升沿启动，下降沿结束）、CycleCount。',
              '- 造型线：射砂阀 FillValve、压实气缸 SqueezeValve / SqueezeExtended / SqueezeRetracted、推型气缸 PushValve / PushExtended / PushRetracted、段号 1–4。',
              '- 机器人单元：夹爪 GripperValve / GripperClosed / GripperOpened、工装夹紧 ClampValve / ClampExtended / ClampRetracted、RobotAtHome、段号 1–5。',
              '- 每个动作的用时 = 指令（阀）变化 → 到位传感器变化；设备另给 Actions/Last/<动作> 上次用时（秒）和 Actions/Last/Cycle 上次循环用时。',
              '- 只在变化时发；MQTT 每个变化单独一条，ts 是动作时刻（毫秒）；OPC UA 每个变化写一次，SourceTimestamp 是动作时刻。', '']
    else:
        L += ['这座工厂没有带动作级信号的设备。', '']
    L += ['## 点表格式', '', '列说明见 points.xlsx 的"说明"表；完整规范见 docs/interface/点表格式.md。', '']
    return '\n'.join(L)


# ================================================================ 打包
def answer_key_path(pid):
    return paths.data('delivery', _safe(pid), 'answer_key.json')


def write_answer_key(rt, key=None):
    """原始现场模式的标准答案：只写到数据目录（测试用），不进交付包。"""
    if key is None:
        _rows, key = point_rows(rt)
    p = answer_key_path(rt.pid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'plant': rt.pid, 'name': rt.plant.name, 'generated': datetime.now().isoformat(timespec='seconds'), 'raw_site': True,
                   'points': [{'code': k['点位编码'], 'protocol': k['协议'], 'address': k['地址'], 'dtype': k['数据类型'], 'device': k['设备编码'],
                               'device_name': k['device_name'], 'tag': k['tag'], 'meaning': k['含义'], 'unit': k['单位'], 'rw': k['读写'],
                               'purpose': k['用途'], 'scale': k['缩放'], 'plain_payload': k['plain_payload']} for k in key]},
                  f, ensure_ascii=False, indent=1)
    return p


def build_zip(rt, protocols='primary', client_models=None, client_scene=None):
    devs = devices(rt)
    rows, key = point_rows(rt, protocols)
    models = glb_models(rt, devs)
    for name, data in (client_models or {}).items():
        models[f'{_safe(name)}.glb'] = data
    if client_scene:
        models['scene.glb'] = client_scene
    files = {'points.xlsx': xlsx_bytes(rt, [{k: v for k, v in d.items() if not k.startswith('_')} for d in devs], rows),
             'layout.dxf': dxf_text(rt, devs).encode('ascii')}
    for n, b in models.items():
        files[f'models/{n}'] = b
    files = {'README.md': readme(rt, devs, rows, list(files)).encode('utf-8'), **files}
    if rawsite.enabled(rt.plant):
        write_answer_key(rt, key)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue(), {'devices': len(devs), 'points': len(rows), 'files': list(files)}


# ================================================================ 原始现场模式切换
async def set_raw_site(mgr, rt, on: bool):
    on = bool(on)
    if rawsite.enabled(rt.plant) == on:
        return False
    for c in (rt.cfg, rt.plant.cfg):
        pl = c.setdefault('plant', {})
        if on:
            pl['raw_site'] = True
        else:
            pl.pop('raw_site', None)
    if os.path.exists(rt.path) and not rt.sandbox:            # 只改文件里这一项（不顺带保存别的未保存修改）
        from .server import read_yaml, write_yaml
        c = read_yaml(rt.path) or {}
        if on:
            c.setdefault('plant', {})['raw_site'] = True
        else:
            (c.get('plant') or {}).pop('raw_site', None)
        write_yaml(rt.path, c)
    if not rt.noproto:                                        # 协议层重建（仿真不重置）
        await mgr.opcua.detach(rt.pid)
        rt.opcua = await mgr.opcua.attach(rt.pid, rt.plant)
        if rt.mqtt is not None:
            from .protocols.mqtt import MqttAdapter
            old = rt.mqtt
            await old.stop(clear_retained=True)
            rt.mqtt = MqttAdapter(rt.pid, rt.plant, rt.mgr.args.mqtt)
            rt.mqtt.mesq.extend(old.mesq)                  # 还没发出去的报工 / 事件交给新的适配器
            rt.mqtt.mes_held = list(old.mes_held)
            await rt.mqtt.start()
    if on:
        try:
            write_answer_key(rt)
        except Exception:
            pass
    rt.plant.log('SIGNAL', 'comm', '原始现场模式已' + ('打开：协议层改用集成商原始地址命名' if on else '关闭：协议层恢复标准命名'))
    return True


# ================================================================ 接口
def register(app, mgr):
    from .api2 import need

    def _zip_resp(rt, data):
        return Response(data, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename={_safe(rt.pid)}-delivery.zip'})

    @app.get('/api/p/{pid}/delivery.zip')
    async def delivery_zip(pid: str, protocols: str = 'primary'):
        rt = mgr.get(pid)
        data, _info = build_zip(rt, 'all' if protocols == 'all' else 'primary')
        return _zip_resp(rt, data)

    @app.post('/api/p/{pid}/delivery.zip')
    async def delivery_zip_client(pid: str, body: dict = Body(...)):
        rt = mgr.get(pid)
        models, total = {}, 0
        try:
            for name, b64 in (body.get('models') or {}).items():
                b = base64.b64decode(b64)
                check_glb(b)
                total += len(b)
                models[str(name)] = b
            scene = base64.b64decode(body['scene']) if body.get('scene') else None
            if scene:
                check_glb(scene)
                total += len(scene)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, _tr('三维模型不对：{e}', e=e))
        if total > 80 * 1024 * 1024:
            raise HTTPException(400, _tr('三维模型太大（超过 80 MB）'))
        data, _info = build_zip(rt, 'all' if body.get('protocols') == 'all' else 'primary', models, scene)
        return _zip_resp(rt, data)

    @app.get('/api/p/{pid}/delivery/info')
    async def delivery_info(pid: str):
        rt = mgr.get(pid)
        devs = devices(rt)
        rows, _key = point_rows(rt)
        by = {}
        for r in rows:
            by[r['协议']] = by.get(r['协议'], 0) + 1
        return {'plant': pid, 'raw_site': rawsite.enabled(rt.plant), 'devices': len(devs), 'points': len(rows), 'by_protocol': by,
                'action_devices': [st.id for st in rt.plant.stations.values() if st.acts is not None],
                'files': ['README.md', 'points.xlsx', 'layout.dxf'] + [f'models/{n}' for n in sorted({f"{_safe(d['_type'])}.glb" for d in devs})] + ['models/scene.glb']}

    @app.get('/api/p/{pid}/delivery/raw_site')
    async def raw_get(pid: str):
        return {'on': rawsite.enabled(mgr.get(pid).plant)}

    @app.put('/api/p/{pid}/delivery/raw_site')
    async def raw_put(pid: str, request: Request, body: dict = Body(...)):
        need(request, 'engineer')
        rt = mgr.get(pid)
        changed = await set_raw_site(mgr, rt, bool(body.get('on')))
        return {'ok': True, 'on': rawsite.enabled(rt.plant), 'changed': changed}

    @app.get('/api/p/{pid}/delivery/{name:path}')
    async def delivery_file(pid: str, name: str, protocols: str = 'primary'):
        rt = mgr.get(pid)
        devs = devices(rt)
        if name == 'points.xlsx':
            rows, key = point_rows(rt, 'all' if protocols == 'all' else 'primary')
            if rawsite.enabled(rt.plant):
                write_answer_key(rt, key)
            return Response(xlsx_bytes(rt, [{k: v for k, v in d.items() if not k.startswith('_')} for d in devs], rows),
                            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers={'Content-Disposition': f'attachment; filename={_safe(pid)}-points.xlsx'})
        if name == 'layout.dxf':
            return Response(dxf_text(rt, devs).encode('ascii'), media_type='image/vnd.dxf', headers={'Content-Disposition': f'attachment; filename={_safe(pid)}-layout.dxf'})
        if name == 'README.md':
            rows, _key = point_rows(rt)
            return Response(readme(rt, devs, rows, ['points.xlsx', 'layout.dxf']), media_type='text/markdown; charset=utf-8')
        if name.startswith('models/') and name.endswith('.glb'):
            ms = glb_models(rt, devs)
            b = ms.get(name[len('models/'):])
            if b is None:
                raise HTTPException(404, _tr('没有模型 {name}', name=name))
            return Response(b, media_type='model/gltf-binary')
        raise HTTPException(404, _tr('交付包里没有 {name}', name=name))

    @app.get('/api/p/{pid}/actions')
    async def actions_info(pid: str):
        from .actions import CYL_CN, FAULTS, PROFILES
        rt = mgr.get(pid)
        out = []
        for st in rt.plant.stations.values():
            a = st.acts
            if a is None:
                continue
            out.append({'station': st.id, 'name': st.name, 'profile': a.profile, 'label': PROFILES[a.profile]['label'], 'cylinders': {c: CYL_CN.get(c, c) for c in a.prof['cyls']},
                        'door': a.prof['door'], 'faults': a.fault_info(), 'fault_kinds': {k: v for k, v in FAULTS.items() if a.applicable(k)}, 'cycles': a.count,
                        'last': {k[len('Actions/Last/'):]: st.tags[k].value for k in st.tags if k.startswith('Actions/Last/')}})
        return {'stations': out}
