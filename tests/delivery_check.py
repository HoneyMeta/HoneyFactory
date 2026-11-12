"""5.0 交付包、原始现场模式、动作级信号、动作故障检查。真实客户端（asyncua / amqtt / pymodbus 不需要），离线仿真对比产量。

先启动服务（示范工厂 foundry-housing），再运行（要能 import vfactory：在仓库根目录或测试副本的启动器下跑）：
    python tests/delivery_check.py
环境变量：VF_HOST、VF_HTTP / VF_OPCUA / VF_MQTT、VF_PLANT；VF_HOME = 服务端的数据目录（找原始现场标准答案 data/delivery/<厂>/answer_key.json）。
会临时打开原始现场模式、注入动作故障，结束时恢复。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import asyncio
import io
import json
import math
import os
import re
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
HOST = os.environ.get('VF_HOST', '127.0.0.1')
HTTP = os.environ.get('VF_HTTP', '8800')
OPCUA = int(os.environ.get('VF_OPCUA', '4840'))
MQTT = int(os.environ.get('VF_MQTT', '1883'))
PID = os.environ.get('VF_PLANT', 'foundry-housing')
P = f'/api/p/{PID}'
TOKEN = ''
results = []
DEV_COLS = ['设备编码', '设备名称', '设备类型', '型号', '厂家', '车间', '产线', '工位', 'X(m)', 'Y(m)', '宽(m)', '深(m)', '朝向(°)', '3D模型文件', '理想节拍(s)', '备注']
PT_COLS = ['点位编码', '设备编码', '含义', '单位', '数据类型', '读写', '用途', '协议', '地址', '缩放', '偏移', '采集周期(ms)', '报警下限', '报警上限', '正常范围', '备注']
PURPOSES = {'state', 'alarm', 'count', 'power', 'energy', 'load', 'temp', 'quality', 'action', 'step', 'param', 'other'}


def ok(name, cond, detail=''):
    results.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300], flush=True)


def http(path, body=None, method=None, tok=None, raw=False):
    t = TOKEN if tok is None else tok
    req = urllib.request.Request(f'http://{HOST}:{HTTP}{path}', data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + t} if t else {})})
    with urllib.request.urlopen(req, timeout=180) as f:
        d = f.read()
        return d if raw else json.loads(d)


def ts_of(s):
    return datetime.fromisoformat(s).timestamp()


# ---------------------------------------------------------------- 交付包文件
def read_xlsx(data):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        out[ws.title] = (list(rows[0]) if rows else [], [list(r) for r in rows[1:]])
    return out


def dxf_scan(text):
    """最小 DXF 扫描：图层表、实体（图层）、INSERT 及其 ATTRIB。"""
    lines = text.replace('\r\n', '\n').split('\n')
    pairs = [(int(lines[i].strip()), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2) if lines[i].strip()]
    layers, ents, inserts, blocks = set(), [], [], set()
    sec, cur, i = None, None, 0
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0 and v == 'SECTION':
            sec = pairs[i + 1][1]
        elif c == 0 and sec == 'TABLES' and v == 'LAYER' and pairs[i + 1][0] == 2:
            layers.add(pairs[i + 1][1])
        elif c == 0 and sec == 'BLOCKS' and v == 'BLOCK':
            j = i + 1
            while pairs[j][0] != 2:
                j += 1
            blocks.add(pairs[j][1])
        elif c == 0 and sec == 'ENTITIES':
            cur = {'type': v}
            ents.append(cur)
            if v == 'INSERT':
                cur['attribs'] = {}
                inserts.append(cur)
            elif v == 'ATTRIB' and inserts:
                cur['parent'] = inserts[-1]
        elif cur is not None and sec == 'ENTITIES':
            cur.setdefault(c, v)
            if cur['type'] == 'ATTRIB' and c == 2:
                cur['parent']['attribs'][v] = cur.get(1, '')
        i += 1
    return layers, ents, inserts, blocks


def undxf(s):
    return re.sub(r'\\U\+([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), s)


def glb_parse(data):
    assert data[:4] == b'glTF', 'magic'
    ver, total = struct.unpack('<II', data[4:12])
    assert ver == 2 and total == len(data), 'header'
    n, kind = struct.unpack('<I4s', data[12:20])
    assert kind == b'JSON'
    j = json.loads(data[20:20 + n])
    off = 20 + n
    bn, bk = struct.unpack('<I4s', data[off:off + 8])
    assert bk == b'BIN\x00' and bn == j['buffers'][0]['byteLength'], 'bin chunk'
    for v in j['bufferViews']:
        assert v['byteOffset'] + v['byteLength'] <= bn, 'view out of range'
    for a in j['accessors']:
        v = j['bufferViews'][a['bufferView']]
        size = {5126: 4, 5125: 4, 5123: 2}[a['componentType']] * {'VEC3': 3, 'SCALAR': 1}[a['type']]
        assert a['count'] * size <= v['byteLength'], 'accessor too long'
    for m in j['meshes']:
        for pr in m['primitives']:
            assert 'POSITION' in pr['attributes'] and 'indices' in pr
    return j


def package_checks():
    meta = http(P + '/meta')
    info = http(P + '/delivery/info')
    ok('交付包概况：设备、点数、动作设备', info['devices'] >= 20 and info['points'] >= 300 and {'CNC1', 'MOLD1', 'DEB1'} <= set(info['action_devices']), info)
    z = zipfile.ZipFile(io.BytesIO(http(P + '/delivery.zip', raw=True)))
    names = set(z.namelist())
    ok('zip 里有 README / 点表 / DXF / 场景', {'README.md', 'points.xlsx', 'layout.dxf', 'models/scene.glb'} <= names, sorted(names)[:8])
    x = read_xlsx(z.read('points.xlsx'))
    ok('Excel 四张表：设备 / 点表 / 协议 / 说明', list(x) == ['设备', '点表', '协议', '说明'], list(x))
    dh, devs = x['设备']
    ph, pts = x['点表']
    ok('设备表列格式', dh == DEV_COLS, dh)
    ok('点表列格式', ph == PT_COLS, ph)
    D = [dict(zip(dh, r)) for r in devs]
    T = [dict(zip(ph, r)) for r in pts]
    codes = [d['设备编码'] for d in D]
    ok('设备编码唯一', len(codes) == len(set(codes)), len(codes))
    fl = meta['floor']
    st = {s['id']: s for s in meta['stations']}
    c1 = next(d for d in D if d['设备编码'] == 'CNC1')
    ok('设备坐标：X = 平面 x，Y = 厂房进深 − 平面 y（米）', abs(c1['X(m)'] - st['CNC1']['pos'][0]) < 1e-6 and abs(c1['Y(m)'] - (fl[1] - st['CNC1']['pos'][1])) < 1e-6
       and c1['宽(m)'] == st['CNC1']['size'][0], (c1['X(m)'], c1['Y(m)'], st['CNC1']['pos']))
    ok('每台设备的 3D 模型文件都在 zip 里', all(d['3D模型文件'] in names for d in D), [d['3D模型文件'] for d in D if d['3D模型文件'] not in names][:3])
    ok('CNC 有理想节拍', c1['理想节拍(s)'] and 400 < float(c1['理想节拍(s)']) < 500, c1['理想节拍(s)'])
    pcodes = [t['点位编码'] for t in T]
    ok('点位编码唯一', len(pcodes) == len(set(pcodes)), len(pcodes) - len(set(pcodes)))
    ok('点表的设备编码都在设备表里', all(t['设备编码'] in codes for t in T))
    ok('数据类型 / 读写 / 用途 / 协议取值合法', all(t['数据类型'] in ('bool', 'int', 'float', 'string') and t['读写'] in ('R', 'RW') and t['用途'] in PURPOSES
                                         and t['协议'] in ('opcua', 'mqtt', 'modbus') for t in T),
       next((t for t in T if not (t['数据类型'] in ('bool', 'int', 'float', 'string') and t['用途'] in PURPOSES)), ''))
    fmt = {'opcua': lambda a: a.startswith('ns=') and ';s=' in a, 'mqtt': lambda a: a.startswith(f'vfactory/{PID}/'),
           'modbus': lambda a: re.fullmatch(r'\d+:(hr|coil):\d+', a) is not None}
    ok('地址格式（NodeId / 主题 / 从站:表:地址）', all(fmt[t['协议']](t['地址'] or '') for t in T), next((t['地址'] for t in T if not fmt[t['协议']](t['地址'] or '')), ''))
    ok('三种协议都用到（按设备的网络线选主协议）', {t['协议'] for t in T} == {'opcua', 'mqtt', 'modbus'}, {t['协议'] for t in T})
    v2 = {p['key']: p for p in http(P + '/points/v2')['points']}
    bad = []
    for t in T:
        key = t['设备编码'] + '/' + t['点位编码'][len(t['设备编码']) + 1:].replace('.', '/')
        p = v2.get(key)
        if p is None:
            continue
        want = p['opcua_nodeid'] if t['协议'] == 'opcua' else p['mqtt_topic'] if t['协议'] == 'mqtt' else (
            f"{p['modbus']['unit']}:{'coil' if p['modbus']['table'] == 'coil' else 'hr'}:{p['modbus']['address']}" if p['modbus'] else None)
        if want != t['地址']:
            bad.append((key, t['地址'], want))
    ok('点表地址和 /points/v2 一致', not bad, bad[:3])
    acts = [t for t in T if t['设备编码'] == 'CNC1' and t['点位编码'].startswith('CNC1.Actions.')]
    ok('点表里有 CNC1 的动作信号（action / step）', len(acts) >= 12 and {t['用途'] for t in acts} >= {'action', 'step'}, len(acts))
    mb = next((t for t in T if t['协议'] == 'modbus' and t['点位编码'].endswith('Common.State')), None)
    ok('Modbus 状态点：int + 状态码备注', mb and mb['数据类型'] == 'int' and '状态码' in (mb['备注'] or ''), mb)
    ph2 = read_xlsx(http(P + '/delivery/points.xlsx?protocols=all', raw=True))['点表'][1]
    ok('protocols=all：每个点按每种协议各一行', len(ph2) > len(T) * 2, (len(ph2), len(T)))
    proto = {(r[0], r[1]): r[2] for r in x['协议'][1]}
    ok('协议表：OPC UA / MQTT / Modbus 端点', proto.get(('OPC UA', '端点'), '').startswith('opc.tcp://') and ':' in proto.get(('MQTT', 'Broker'), '')
       and ':' in proto.get(('Modbus TCP', '端点'), ''), proto.get(('OPC UA', '端点')))
    rd = z.read('README.md').decode('utf-8')
    ok('README：端点、命名空间、MQTT 载荷、Modbus 约定、坐标系', all(k in rd for k in ('opc.tcp://', 'http://honeymeta.cn/vfactory', '"value"', '/set', '从站:表:地址', '坐标系', 'Actions/Last')),
       len(rd))
    # DXF
    txt = z.read('layout.dxf').decode('ascii')
    layers, ents, inserts, blocks = dxf_scan(txt)
    ok('DXF 图层：墙 / 区域 / 设备 / 输送线 / AGV 路径', {'VF_WALL', 'VF_AREA', 'VF_DEVICE', 'VF_CONVEYOR', 'VF_AGV_PATH'} <= layers, sorted(layers))
    used = {e.get(8) for e in ents}
    ok('DXF 各层都有图元', {'VF_WALL', 'VF_AREA', 'VF_DEVICE', 'VF_CONVEYOR', 'VF_AGV_PATH'} <= used, sorted(x for x in used if x))
    ins = {i['attribs'].get('CODE'): i for i in inserts}
    ok('DXF 每台设备一个块引用，属性 CODE = 设备编码', set(codes) <= set(ins) and all(f"DEV_{c}" in blocks or any(b.endswith(c) for b in blocks) for c in codes[:5]),
       sorted(set(codes) - set(ins))[:5])
    i1 = ins.get('CNC1', {})
    ok('DXF 块插入点 = 设备中心（米）', i1 and abs(float(i1.get(10, 0)) - c1['X(m)']) < 1e-3 and abs(float(i1.get(20, 0)) - c1['Y(m)']) < 1e-3, (i1.get(10), i1.get(20)))
    ok('DXF 块属性 NAME 中文按 \\U+ 转义', undxf(i1.get('attribs', {}).get('NAME', '')) == c1['设备名称'], i1.get('attribs'))
    try:
        from vfactory import dxf as vfdxf
        r = vfdxf.convert(txt)
        ok('DXF 能被 VF 自己的 DXF 导入器解析（米，尺寸对）', abs(r['w'] - max(fl[0], max(d['X(m)'] for d in D) + 6)) < 60 and r['layers'], {k: r[k] for k in ('w', 'h')})
    except ImportError:
        ok('DXF 能被 VF 自己的 DXF 导入器解析', True, '（没有 vfactory，跳过）')
    try:
        if os.environ.get('VF_PYLIB'):            # ezdxf 装在别处（不污染共用的 Python）
            sys.path.insert(0, os.environ['VF_PYLIB'])
        import tempfile

        from ezdxf import recover
        fd, tp = tempfile.mkstemp(suffix='.dxf')
        os.write(fd, txt.encode('ascii'))
        os.close(fd)
        doc, aud = recover.readfile(tp)
        os.remove(tp)
        ins2 = {e.get_attrib_text('CODE'): e for e in doc.modelspace() if e.dxftype() == 'INSERT'}
        ok('DXF ezdxf 读取：R12、米、每台设备一个带属性的块、审计没有错误', doc.header.get('$INSUNITS') == 6 and set(codes) <= set(ins2) and not aud.errors
           and ins2['CNC1'].get_attrib_text('NAME') == c1['设备名称'], (doc.dxfversion, len(ins2), len(aud.errors)))
    except ImportError:
        print('  (没有 ezdxf，用最小解析器)')
    # GLB
    errs = []
    for n in names:
        if n.endswith('.glb'):
            try:
                glb_parse(z.read(n))
            except AssertionError as e:
                errs.append((n, str(e)))
    ok('GLB 全部有效（头、JSON、BIN 块、访问器范围）', not errs, errs[:3])
    sj = glb_parse(z.read('models/scene.glb'))
    nodes = {nd.get('name'): nd for nd in sj['nodes']}
    ok('场景 GLB：每台设备一个节点，名字 = 设备编码', set(codes) <= set(nodes), sorted(set(codes) - set(nodes))[:5])
    t = nodes.get('CNC1', {}).get('translation', [0, 0, 0])
    ok('场景 GLB：节点位置 = (X, 0, −Y)', abs(t[0] - c1['X(m)']) < 1e-3 and abs(t[2] + c1['Y(m)']) < 1e-3, t)
    cj = glb_parse(z.read('models/cnc.glb'))
    acc = cj['accessors'][cj['meshes'][0]['primitives'][0]['attributes']['POSITION']]
    ok('设备 GLB 尺寸是米（CNC 宽约 4 m）', 3 < acc['max'][0] - acc['min'][0] < 5, (acc['min'], acc['max']))
    # 网页按钮：上传界面里导出的模型替换服务端模型
    import base64
    mine = z.read('models/cnc.glb')
    z2 = zipfile.ZipFile(io.BytesIO(http(P + '/delivery.zip', {'models': {'cnc': base64.b64encode(mine).decode()}, 'scene': base64.b64encode(z.read('models/scene.glb')).decode()},
                                          method='POST', raw=True)))
    ok('POST 交付包（客户端三维模型）', z2.read('models/cnc.glb') == mine and 'points.xlsx' in z2.namelist())
    try:
        http(P + '/delivery.zip', {'models': {'cnc': base64.b64encode(b'not a glb').decode()}}, method='POST', raw=True)
        ok('上传坏 GLB 被拒绝', False)
    except urllib.error.HTTPError as e:
        ok('上传坏 GLB 被拒绝（400）', e.code == 400, e.code)
    return D, T


# ---------------------------------------------------------------- 动作信号
async def mqtt_collect(filters, sec, cid='dc-checker'):
    from amqtt.client import MQTTClient
    c = MQTTClient(client_id=cid)
    await c.connect(f'mqtt://{HOST}:{MQTT}/')
    await c.subscribe([(f, 0) for f in filters])
    msgs = []
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            m = await c.deliver_message(timeout_duration=0.3)
            msgs.append((m.topic, m.data.decode('utf-8', 'replace'), bool(getattr(m, 'retain', False))))
        except asyncio.TimeoutError:
            pass
    await c.disconnect()
    return msgs


def durations(msgs, sid, cmd, cmd_val, arrive, retained_ok=False):
    """从 MQTT 消息里算 指令变化 → 到位传感器 的用时（秒，按 ts）。"""
    ev = []
    for topic, data, ret in msgs:
        if ret and not retained_ok:
            continue
        parts = topic.split('/')
        if len(parts) < 5 or parts[3] != sid:
            continue
        try:
            d = json.loads(data)
        except ValueError:
            continue
        ev.append((ts_of(d['sim_ts']), '/'.join(parts[4:]), d['value']))
    ev.sort()
    out, t_cmd = [], None
    for t, tn, v in ev:
        if tn == cmd and v == cmd_val:
            t_cmd = t
        elif tn == arrive and v is True and t_cmd is not None:
            out.append(round(t - t_cmd, 3))
            t_cmd = None
    return out, ev


async def action_checks():
    base = f'vfactory/{PID}'
    http(P + '/sim', {'speed': 120})
    msgs = await mqtt_collect([f'{base}/machining/+/Actions/#', f'{base}/molding/MOLD1/Actions/#'], 25)
    live = [m for m in msgs if not m[2]]
    ok('MQTT 动作信号：有实时变化（不是 retain）', len(live) > 50, len(live))
    ext, ev = [], []
    for sid in ('CNC1', 'CNC2', 'CNC3', 'CNC4', 'CNC5', 'CNC6'):
        d, e = durations(msgs, sid, 'Actions/ClampValve', True, 'Actions/ClampExtended')
        ext += d
        ev += e
    ok('夹紧用时分布（指令 → 到位）：均值约 1.1 s，有抖动', len(ext) >= 3 and 0.95 < statistics.mean(ext) < 1.3 and (len(ext) < 2 or statistics.pstdev(ext) > 0.005),
       (len(ext), round(statistics.mean(ext), 3) if ext else None, round(statistics.pstdev(ext), 4) if len(ext) > 1 else None))
    ms = [t for t, _tn, _v in ev if abs(t * 1000 - round(t * 1000)) < 1e-3 and abs(t - round(t)) > 1e-3]
    ok('时间戳精确到毫秒（不是整秒）', len(ms) > len(ev) * 0.3, (len(ms), len(ev)))
    steps = [v for _t, tn, v in ev if tn == 'Actions/ProgramStep']
    ok('程序段号按 10→20→…→60→0 走', {10, 20, 30, 40, 50, 60, 0} <= set(steps), sorted(set(steps)))
    cyc = [v for _t, tn, v in ev if tn == 'Actions/CycleOn']
    ok('循环启停（CycleOn 上升 / 下降沿）', True in cyc and False in cyc, cyc[:6])
    sq, _e = durations(msgs, 'MOLD1', 'Actions/SqueezeValve', True, 'Actions/SqueezeExtended')
    ok('造型线压实气缸用时（约 2.2 s）', len(sq) >= 3 and 1.8 < statistics.mean(sq) < 2.7, (len(sq), round(statistics.mean(sq), 3) if sq else None))
    # OPC UA：浏览新节点、读值、订阅看 SourceTimestamp
    from asyncua import Client
    async with Client(f'opc.tcp://{HOST}:{OPCUA}/vfactory/') as c:
        idx = await c.get_namespace_index('http://honeymeta.cn/vfactory')
        folder = c.get_node(f'ns={idx};s={PID}/CNC1/Actions')
        kids = {(await k.read_browse_name()).Name for k in await folder.get_children()}
        ok('OPC UA 浏览 CNC1/Actions', {'ClampValve', 'ClampExtended', 'DoorClosed', 'SpindleRun', 'ProgramStep', 'CycleOn', 'Last'} <= kids, sorted(kids))
        got = []

        class H:
            def datachange_notification(self, node, val, data):
                got.append((val, data.monitored_item.Value.SourceTimestamp))
        sub = await c.create_subscription(50, H())
        await sub.subscribe_data_change([c.get_node(f'ns={idx};s={PID}/{s}/Actions/ClampExtended') for s in ('CNC1', 'CNC2', 'CNC3', 'CNC4', 'CNC5', 'CNC6')])
        await asyncio.sleep(15)
        await sub.delete()
        frac = [ts for _v, ts in got[6:] if ts and ts.microsecond != 0]
        ok('OPC UA 动作变化：SourceTimestamp 是动作时刻（毫秒，不是整秒）', len(got) > 6 and frac, (len(got), [str(t) for _v, t in got[-3:]]))
    http(P + '/sim', {'speed': 10})


async def fault_checks():
    base = f'vfactory/{PID}'
    st = http(P + '/station/CNC2')
    ok('设备接口带动作故障类型（故障菜单里能选）', {'cyl_leak', 'sticky_clamp', 'slow_door'} <= set(st['faults']) and st.get('actions', {}).get('profile') == 'cnc',
       list(st['faults']))
    before = float(st['tags']['Production/LastCycleTime']['v'] or 0)
    http(P + '/station/CNC2/fault', {'kind': 'cyl_leak', 'params': {'cyl': 'clamp', 'extra_s': 20}})
    ok('动作故障已记录（/actions）', next(s for s in http(P + '/actions')['stations'] if s['station'] == 'CNC2')['faults'].get('cyl_leak', {}).get('extra_s') == 20)
    try:
        http(P + '/station/MOLD1/fault', {'kind': 'slow_door'})
        ok('造型线没有门：slow_door 被拒绝', False)
    except urllib.error.HTTPError as e:
        ok('造型线没有门：slow_door 被拒绝（400）', e.code == 400)
    http(P + '/sim', {'speed': 200})
    msgs = await mqtt_collect([f'{base}/machining/+/Actions/#', f'{base}/machining/CNC2/Production/LastCycleTime'], 35, 'dc-fault')
    http(P + '/sim', {'speed': 10})
    d2, _e = durations(msgs, 'CNC2', 'Actions/ClampValve', True, 'Actions/ClampExtended')
    d1, _e = durations(msgs, 'CNC1', 'Actions/ClampValve', True, 'Actions/ClampExtended')
    # 注入前已经排好的那次夹紧（上料最后几秒排的）还是原来的用时，所以看中位数
    ok('气缸泄漏：CNC2 夹紧变慢约 20 s，CNC1 不变', len(d2) >= 2 and statistics.median(d2) > 19 and d1 and max(d1) < 2, (d2[:4], d1[:4]))
    cyc = [json.loads(d)['value'] for t, d, r in msgs if t.endswith('CNC2/Production/LastCycleTime') and not r]
    ok('气缸泄漏：CNC2 上一件节拍变长', cyc and max(cyc) >= before + 15, (before, cyc[-3:]))
    http(P + '/station/CNC2/fault', {'kind': 'clear'})
    ok('清除故障后动作故障清空', not next(s for s in http(P + '/actions')['stations'] if s['station'] == 'CNC2')['faults'])


def offline_fault_checks():
    """离线同种子对比：故障让动作变慢、循环变长、产量下降（同样的随机流，结果可复现）。"""
    try:
        import yaml

        from vfactory.core import Plant
    except ImportError:
        ok('离线对比（需要 vfactory）', True, '跳过')
        return
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'plants', 'foundry-housing.yaml'), encoding='utf-8') as f:
        cfg0 = yaml.safe_load(f)
    cfg0['plant']['start'] = '2026-11-02T07:00:00'

    def run(fault=None, sid='CNC1', hours=10, cfg_fault=None):
        cfg = json.loads(json.dumps(cfg0))
        if cfg_fault:
            for b in cfg['blocks']:
                if b['id'] == sid:
                    b['params']['action_faults'] = [cfg_fault]
        p = Plant(cfg)
        p.run_for(3600)
        if fault:
            assert p.stations[sid].inject(fault) == '', fault
        cnt = 'Production/PartsProduced' if 'Production/PartsProduced' in p.stations[sid].tags else 'Actions/CycleCount'
        n0 = p.stations[sid].get(cnt)
        p.run_for(hours * 3600)
        st = p.stations[sid]
        last = {k.split('/')[-1]: [] for k in st.tags if k.startswith('Actions/Last/')}
        for e in p.act_events:
            if e[2] == sid and e[3].startswith('Actions/Last/') and e[1] >= 3600 + 600:     # 注入（第 1 小时）之后的
                last[e[3].split('/')[-1]].append(e[4])
        return st.get(cnt) - n0, {k: (round(statistics.mean(v), 3) if v else None) for k, v in last.items()}, p
    n_base, l_base, pb = run()
    n_leak, l_leak, _ = run('cyl_leak:cyl=clamp,extra_s=60')
    ok('离线：气缸泄漏 60 s → 夹紧用时 +60 s、循环变长、CNC1 产量下降', l_leak['ClampExtend'] > l_base['ClampExtend'] + 55 and l_leak['Cycle'] > l_base['Cycle'] + 50
       and n_leak < n_base, (n_base, n_leak, l_base['ClampExtend'], l_leak['ClampExtend'], l_base['Cycle'], l_leak['Cycle']))
    n_st, l_st, _ = run('sticky_clamp:extra_s=30')
    ok('离线：夹具卡滞 → 松开变慢、产量下降', l_st['ClampRetract'] > l_base['ClampRetract'] + 15 and n_st < n_base, (l_base['ClampRetract'], l_st['ClampRetract'], n_base, n_st))
    n_dr, l_dr, _ = run('slow_door:extra_s=25')
    ok('离线：防护门变慢 → 开关门都变慢、产量下降', l_dr['DoorClose'] > l_base['DoorClose'] + 20 and l_dr['DoorOpen'] > l_base['DoorOpen'] + 20 and n_dr < n_base,
       (l_dr['DoorClose'], l_dr['DoorOpen'], n_base, n_dr))
    _n, l_cf, pc = run(cfg_fault={'kind': 'cyl_leak', 'cyl': 'clamp', 'extra_s': 2, 'drift_s_per_day': 20}, hours=24)
    ev = [e[4] for e in pc.act_events if e[2] == 'CNC1' and e[3] == 'Actions/Last/ClampExtend']
    ok('离线：工厂配置预置故障 + 按天漂移（越来越慢）', len(ev) > 10 and statistics.mean(ev[-5:]) > statistics.mean(ev[:5]) + 2 and statistics.mean(ev[-5:]) > 20,
       (ev[:3], ev[-3:]))
    n_mb, _l, _ = run(sid='MOLD1', hours=4)
    n_m, l_m, _ = run('cyl_leak:cyl=squeeze,extra_s=8', sid='MOLD1', hours=4)
    ok('离线：造型线压实气缸泄漏 → 压实变慢、循环变长、造型数下降', l_m['SqueezeExtend'] > 9 and l_m['Cycle'] > 48 and n_m < n_mb,
       (l_m['SqueezeExtend'], l_m['Cycle'], n_mb, n_m))
    k0 = [x for x in (pb.stations['CNC2'].get('Production/PartsProduced'),)]
    ok('离线：没有故障时结果和关掉动作信号时完全一样（动作信号不改仿真）', _same_without_actions(cfg0, pb), k0)


def _same_without_actions(cfg0, pb):
    from vfactory.core import Plant
    cfg = json.loads(json.dumps(cfg0))
    cfg['plant']['actions'] = False
    p = Plant(cfg)
    p.run_for(3600 + 10 * 3600)
    return p.kpi == pb.kpi and all(p.stations[s].get('Production/PartsProduced') == pb.stations[s].get('Production/PartsProduced') for s in ('CNC1', 'CNC2', 'CNC6'))


# ---------------------------------------------------------------- 原始现场模式
def answer_key():
    home = os.environ.get('VF_HOME') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(home, 'data', 'delivery', PID, 'answer_key.json')
    if not os.path.exists(p):
        return None, p
    with open(p, encoding='utf-8') as f:
        return json.load(f), p


async def raw_checks():
    from asyncua import Client, ua
    base = f'vfactory/{PID}'
    from amqtt.client import MQTTClient
    c0 = MQTTClient(client_id='dc-leftover')            # 模拟以前删掉的设备留在 Broker 里的 retain（标准名字）
    await c0.connect(f'mqtt://{HOST}:{MQTT}/')
    await c0.publish(f'{base}/machining/CNC99/Common/State', b'{"value": "Idle"}', qos=1, retain=True)
    await c0.disconnect()
    r = http(P + '/delivery/raw_site', {'on': True}, method='PUT')
    ok('打开原始现场模式', r['on'] is True, r)
    time.sleep(3)
    x = read_xlsx(http(P + '/delivery/points.xlsx', raw=True))
    ph, pts = x['点表']
    T = [dict(zip(ph, r)) for r in pts]
    filled = {'点位编码', '协议', '地址', '数据类型'}
    ok('原始现场点表：只有 点位编码 / 协议 / 地址 / 数据类型', T and all(all((t[c] is None or t[c] == '') for c in PT_COLS if c not in filled) and all(t[c] for c in filled) for t in T),
       T[0] if T else '')
    ok('原始现场点表：地址是集成商风格（DBx / PLC / M3_ 拼音）', any(re.search(r'DB\d+\.DB[DWXB]', t['地址']) for t in T) and any(re.search(r'M\d_[A-Z]{2}', t['地址']) for t in T)
       and not any('/CNC1/' in t['地址'] or 'Monitoring' in t['地址'] for t in T), [t['地址'] for t in T if t['协议'] != 'modbus'][:3])
    ok('设备表照常（集成商交了设备清单）', len(x['设备'][1]) >= 20)
    key, kp = answer_key()
    ok('标准答案只写在数据目录（answer_key.json），条数和点表一致', key and len(key['points']) == len(T) and {p['code'] for p in key['points']} == {t['点位编码'] for t in T}, kp)
    if not key:
        return
    K = {(p['device'], p['tag']): p for p in key['points']}
    load = K.get(('CNC1', 'Monitoring/Spindle/Load'))
    ok('标准答案：CNC1 主轴负载 → M1_ZZFZ（拼音首字母）', load and load['code'].startswith('M1_ZZFZ') and load['meaning'] == '主轴负载' and load['unit'] == '%', load)
    z = zipfile.ZipFile(io.BytesIO(http(P + '/delivery.zip', raw=True)))
    ok('交付包里没有标准答案', not any('answer' in n for n in z.namelist()), z.namelist())
    ok('README 说明这是原始现场', '原始现场' in z.read('README.md').decode('utf-8'))
    # OPC UA：干净名字没了，原始地址在
    async with Client(f'opc.tcp://{HOST}:{OPCUA}/vfactory/') as c:
        idx = await c.get_namespace_index('http://honeymeta.cn/vfactory')
        dv = await c.get_node(f'ns={idx};s={PID}/CNC1/Monitoring/Spindle/Load').read_data_value(raise_on_bad_status=False)
        ok('OPC UA：标准 NodeId 不存在', dv.StatusCode.value == ua.StatusCodes.BadNodeIdUnknown, dv.StatusCode.name)
        lo = next(p for p in key['points'] if p['protocol'] == 'opcua' and p['device'] == 'CNC1' and p['tag'] == 'Monitoring/Spindle/Load') if any(
            p['protocol'] == 'opcua' and p['device'] == 'CNC1' and p['tag'] == 'Monitoring/Spindle/Load' for p in key['points']) else None
        if lo:
            v = await c.get_node(lo['address']).read_value()
            ok('OPC UA：原始 NodeId 能读（M1_ZZFZ）', isinstance(v, float), (lo['address'], v))
        top = c.get_node(f'ns={idx};s={PID}/_plant')
        kids = sorted([(await k.read_browse_name()).Name for k in await top.get_children()])
        ok('OPC UA：目录是 通道 / 控制器 / 地址（没有区域、设备）', {'S7', 'CNC'} <= set(kids) and '机加区' not in kids, kids)
    # MQTT：主题全是原始风格；有纯文本载荷
    msgs = await mqtt_collect([f'{base}/#'], 4, 'dc-raw')
    tops = {t for t, _d, _r in msgs}
    clean = [t for t, d, _r in msgs if d and re.match(rf'{re.escape(base)}/(machining|melting|molding|cleaning|inspection|warehouse|logistics|people|other)/', t)]
    ok('MQTT：没有标准主题（区域/设备/点位）', not clean, clean[:3])
    ok('MQTT：原始主题（edge01/PLC… 、jj/M…）', any('/edge0' in t for t in tops) and any('/jj/M' in t for t in tops), sorted(tops)[:4])
    plain = [d for t, d, _r in msgs if not t.endswith('_status') and '/_mes/' not in t and d and not d.startswith('{')]
    ok('MQTT：有一台 PLC 的载荷是纯文本数值', plain and all(re.fullmatch(r'-?[\d.eE+-]+|True|False|[^{].*', p) for p in plain[:20]), plain[:3])
    ok('MQTT：_status / _mes 仍在', any(t.endswith('/_status') for t in tops), '')
    # 写入：原始主题 /set
    ov = next((p for p in key['points'] if p['device'] == 'CNC1' and p['tag'] == 'Monitoring/Feed/Override' and p['protocol'] in ('mqtt', 'opcua')), None)
    names = http(P + '/points')
    row = next(r for r in names if r['工位'].startswith('CNC1 ') and r['点位'] == 'Monitoring/Feed/Override')
    ok('私有点表接口（界面用）：标准名字 + 原始地址', row['MQTT 主题'].startswith(base + '/jj/') and row['OPC UA NodeId'].startswith(f'ns=2;s={PID}/CNC.'), row)
    from amqtt.client import MQTTClient
    c = MQTTClient(client_id='dc-raw-w')
    await c.connect(f'mqtt://{HOST}:{MQTT}/')
    t_set = row['MQTT 主题'] + '/set'
    await c.subscribe([(t_set + '/ack', 0)])
    await c.publish(t_set, json.dumps({'value': 93, 'id': 'raw-1'}).encode())
    ack, t0 = None, time.time()
    while ack is None and time.time() - t0 < 6:
        try:
            m = await c.deliver_message(timeout_duration=1)
            if m.topic == t_set + '/ack':
                ack = json.loads(m.data)
        except asyncio.TimeoutError:
            pass
    await c.disconnect()
    ok('MQTT：原始主题 /set 写入 + 回执', isinstance(ack, dict) and ack.get('ok') and http(P + '/station/CNC1')['tags']['Monitoring/Feed/Override']['v'] == 93.0, (ov and ov['code'], ack))
    http(P + '/station/CNC1/write', {'tag': 'Monitoring/Feed/Override', 'value': 100})
    # 动作信号在原始现场下照样发
    ce = next(p for p in key['points'] if p['device'] == 'CNC1' and p['tag'] == 'Actions/ClampExtended')
    ce_topic = next(r['MQTT 主题'] for r in names if r['工位'].startswith('CNC1 ') and r['点位'] == 'Actions/ClampExtended')
    http(P + '/sim', {'speed': 200})
    msgs = await mqtt_collect([ce_topic], 12, 'dc-raw-a')
    http(P + '/sim', {'speed': 10})
    ok('原始现场：动作信号照样发（原始地址）', sum(1 for _t, _d, r in msgs if not r) >= 1 and re.search(r'/jj/M1/X\d+\.\d', ce_topic), (ce['code'], ce_topic, len(msgs)))
    st = http(P + '/state')
    ok('原始现场：仿真和界面接口照常', st['stations'] and st['t'] > 0)
    # 关掉：标准名字回来，原始主题的 retain 清掉
    r = http(P + '/delivery/raw_site', {'on': False}, method='PUT')
    time.sleep(3)
    msgs = await mqtt_collect([f'{base}/edge01/#', f'{base}/jj/#'], 3, 'dc-raw-off')
    stale = [t for t, d, ret in msgs if d]
    ok('关闭原始现场：原始主题的 retain 已清掉', r['on'] is False and not stale, stale[:3])
    async with Client(f'opc.tcp://{HOST}:{OPCUA}/vfactory/') as c:
        idx = await c.get_namespace_index('http://honeymeta.cn/vfactory')
        v = await c.get_node(f'ns={idx};s={PID}/CNC1/Monitoring/Spindle/Load').read_value()
        ok('关闭原始现场：标准 NodeId 回来了', isinstance(v, float), v)


if __name__ == '__main__':
    TOKEN = http('/api/login', {'username': 'admin', 'password': 'honey123'}, tok='')['token']
    try:
        if http(P + '/delivery/raw_site')['on']:
            http(P + '/delivery/raw_site', {'on': False}, method='PUT')
        only = set(sys.argv[1:])               # 只跑某几段：package / actions / faults / offline / raw
        if not only or 'package' in only:
            package_checks()
        if not only or 'actions' in only:
            asyncio.run(action_checks())
        if not only or 'faults' in only:
            asyncio.run(fault_checks())
        if not only or 'offline' in only:
            offline_fault_checks()
        if not only or 'raw' in only:
            asyncio.run(raw_checks())
    finally:
        try:
            http(P + '/delivery/raw_site', {'on': False}, method='PUT')
            http(P + '/station/CNC2/fault', {'kind': 'clear'})
            http(P + '/sim', {'speed': 10})
        except Exception:
            pass
    bad = [n for n, g in results if not g]
    print(f'\n{len(results) - len(bad)}/{len(results)} 通过' + ('；失败：' + '、'.join(bad) if bad else ''))
    sys.exit(1 if bad else 0)
