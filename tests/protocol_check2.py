"""协议"像真实设备"检查（4.1 走查 #13、#65–#82、#87、#88）：全部用真实外部客户端（asyncua / amqtt / pymodbus）连协议端口。

先启动服务（python -m vfactory serve），再运行：
    python tests/protocol_check2.py
环境变量：VF_HOST（默认 127.0.0.1）、VF_HTTP / VF_OPCUA / VF_MQTT（默认 8800 / 4840 / 1883）、VF_PLANT（默认 foundry-housing）、
         VF_LOG（服务日志路径，可选：检查新建工厂/故障恢复时没有"写入被拒绝"刷屏）。
会临时修改协议设置、注入通讯故障、建删 API 令牌，结束时全部恢复。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import asyncio
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')
HOST = os.environ.get('VF_HOST', '127.0.0.1')
HTTP = os.environ.get('VF_HTTP', '8800')
OPCUA = int(os.environ.get('VF_OPCUA', '4840'))
MQTT = int(os.environ.get('VF_MQTT', '1883'))
PID = os.environ.get('VF_PLANT', 'foundry-housing')
P = f'/api/p/{PID}'
TOKEN = ''
results = []


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


def http_err(path, body=None, method=None, tok=None):
    try:
        http(path, body, method, tok)
        return 200, ''
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def comm(protocol, mode='', **kw):
    return http(P + '/signals/comm', {'protocol': protocol, 'mode': mode, **kw})


def clear_all():
    http(P + '/signals/comm', method='DELETE')


def tagv(sid, tag):
    return http(f'{P}/station/{sid}')['tags'][tag]['v']


# ------------------------------------------------------------------ 点表 / 地址 / 文档
def rest_checks():
    v2 = http(P + '/points/v2')
    pts = v2['points']
    p0 = next(p for p in pts if p['key'] == 'FUR1/Setpoint/PowerKW')
    ok('#80 点表 v2：英文键、结构化 Modbus 字段', {'station', 'tag', 'unit', 'datatype', 'writable', 'opcua_nodeid', 'mqtt_topic'} <= set(p0) and
       isinstance(p0['modbus'], dict) and {'port', 'unit', 'table', 'address', 'type', 'scale'} <= set(p0['modbus']), json.dumps(p0, ensure_ascii=False)[:240])
    num = [p for p in pts if p['datatype'] in ('float', 'int', 'bool') and p['station'] != '_meter']
    mapped = [p for p in num if p['modbus']]
    ok('#76 所有数值/开关量点位都有 Modbus 地址', len(mapped) == len(num), f'{len(mapped)}/{len(num)}')
    sp = [p for p in pts if '/Setpoint/' in '/' + p['tag'] and p['writable']]
    ok('#76 设定值映射到可写保持寄存器/线圈', sp and all(p['modbus'] and p['modbus']['writable'] for p in sp), f'{len(sp)} 个设定值')
    legacy = http(P + '/points')
    ok('旧版 /points 仍是中文键（兼容）', '工位' in legacy[0] and 'Modbus' in legacy[0])
    csv = http(P + '/points.csv', raw=True).decode('utf-8-sig')
    ok('CSV 点表保留中文表头', csv.startswith('工位,点位'), csv[:60])
    ep = v2['endpoints']
    ok('#79 接入地址是真实 IP（不是占位符）', '<' not in (ep['opcua'] or '') and ep.get('hosts') and ep['opcua'].startswith('opc.tcp://' + ep['hosts'][0]),
       f"{ep['opcua']} {ep.get('hosts')} {ep.get('hostname')}")
    d = http('/docs', raw=True, tok='').decode()
    js = urllib.request.urlopen(f'http://{HOST}:{HTTP}/_apidocs/swagger-ui-bundle.js', timeout=10)
    ok('#82 /docs 用本地 Swagger UI（不依赖 CDN）', '/_apidocs/swagger-ui-bundle.js' in d and 'cdn.jsdelivr' not in d and js.status == 200)
    rd = http('/redoc', raw=True, tok='').decode()
    ok('#82 /redoc 用本地 ReDoc、不加载 Google 字体', '/_apidocs/redoc.standalone.js' in rd and 'fonts.googleapis' not in rd)
    oa = http('/openapi.json', tok='')
    tags = {t for path in oa['paths'].values() for op in path.values() for t in op.get('tags', [])}
    ok('#82 接口按模块分组（中文标签）', {'信号与协议', '联调测试', '账号与令牌'} <= tags, sorted(tags))
    s = http(P + '/signals/status')
    ok('#75 每种协议只列支持的故障模式', 'latency' not in s['supported']['opcua'] and 'latency' in s['supported']['modbus'])
    code, msg = http_err(P + '/signals/comm', {'protocol': 'opcua', 'mode': 'latency'})
    ok('#75 不支持的模式返回 400', code == 400, msg[:100])


# ------------------------------------------------------------------ OPC UA
async def opcua_checks():
    from asyncua import Client, ua
    url = f'opc.tcp://{HOST}:{OPCUA}/vfactory/'
    async with Client(url) as c:
        idx = await c.get_namespace_index('http://honeymeta.cn/vfactory')
        n = lambda s: c.get_node(f'ns={idx};s={PID}/{s}')  # noqa: E731
        dv = await n('FUR1/Bath/Temperature').read_data_value()
        dv2 = await n('Plant/Castings').read_data_value()
        ok('#65 SourceTimestamp / ServerTimestamp 都有', dv.SourceTimestamp and dv.ServerTimestamp and dv2.SourceTimestamp, f'{dv.SourceTimestamp} / {dv.ServerTimestamp}')
        temp = n('FUR1/Bath/Temperature')
        td = await temp.read_type_definition()
        props = {(await p.read_browse_name()).Name: p for p in await temp.get_properties()}
        eu = await props['EngineeringUnits'].read_value() if 'EngineeringUnits' in props else None
        ok('#66 数值点是 AnalogUnitType/AnalogItemType + EngineeringUnits（UNECE °C=CEL）',
           td.Identifier in (ua.ObjectIds.AnalogItemType, ua.ObjectIds.AnalogUnitType) and eu is not None and eu.UnitId == 4408652,
           f'type={td.Identifier} eu={eu.DisplayName.Text if eu else None} id={eu.UnitId if eu else None}')
        spn = n('FUR1/Setpoint/PowerKW')
        props = {(await p.read_browse_name()).Name: p for p in await spn.get_properties()}
        rng = await props['EURange'].read_value() if 'EURange' in props else None
        ok('#66 设定值有 EURange（AnalogItemType）', rng is not None and rng.Low == 0 and rng.High > 0 and (await spn.read_type_definition()).Identifier == ua.ObjectIds.AnalogItemType,
           f'{rng}')
        cnc = n('CNC1')
        ctd = await cnc.read_type_definition()
        ok('#66 设备对象有自己的类型（VFStationType 子类型）', ctd.NamespaceIndex == idx and 'StationType' in str(ctd.Identifier), ctd.to_string())
        st = await n('Plant/SimTime').read_data_value()
        ok('#88 Plant/SimTime 是 DateTime', st.Value.VariantType == ua.VariantType.DateTime, f'{st.Value.Value}')
        before = tagv('FUR1', 'Setpoint/PowerKW')
        try:
            await spn.write_value(ua.DataValue(ua.Variant(-99999.0, ua.VariantType.Double)))
            res = 'Good'
        except ua.UaStatusCodeError as e:
            res = e.code
        ok('#67 越界写入返回 BadOutOfRange，模型不变', res == ua.StatusCodes.BadOutOfRange and tagv('FUR1', 'Setpoint/PowerKW') == before,
           f'{ua.StatusCode(res).name if res != "Good" else res} 模型 {tagv("FUR1", "Setpoint/PowerKW")}')
        fo = n('CNC1/Monitoring/Feed/Override')
        await fo.write_value(ua.DataValue(ua.Variant(87, ua.VariantType.Int32)))
        await asyncio.sleep(0.3)
        ok('#68 宽松类型：Int32 写 Double 节点成功', tagv('CNC1', 'Monitoring/Feed/Override') == 87.0, tagv('CNC1', 'Monitoring/Feed/Override'))
        back = await fo.read_data_value()
        ok('#68 写入后节点值是 Double、带新时间戳', back.Value.VariantType == ua.VariantType.Double and back.Value.Value == 87.0, back.Value)
        await fo.write_value(ua.DataValue(ua.Variant(100.0, ua.VariantType.Double)))
        now = datetime.now(timezone.utc)
        hist = await temp.read_raw_history(starttime=now - timedelta(days=30), endtime=now + timedelta(days=30), numvalues=0)
        ok('#69 HistoryRead 有数据（30 秒一个点）', len(hist) > 20, f'{len(hist)} 条，最早 {hist[0].SourceTimestamp if hist else None}')
        # 报警事件
        got = []

        class H:
            def event_notification(self, ev):
                got.append(ev)
        sub = await c.create_subscription(200, H())
        h = await sub.subscribe_events(c.nodes.server, ua.ObjectIds.AlarmConditionType)
        http(P + '/station/CNC2/fault', {'kind': 'failure'})
        for _ in range(30):
            if any('CNC2' in str(getattr(e, 'SourceName', '')) for e in got):
                break
            await asyncio.sleep(0.2)
        ev = next((e for e in got if 'CNC2' in str(getattr(e, 'SourceName', ''))), None)
        ok('#69 报警按 AlarmConditionType 事件发出', ev is not None, f'{getattr(ev, "SourceName", None)} {getattr(ev, "Message", None)} sev={getattr(ev, "Severity", None)}')
        http(P + '/station/CNC2/fault', {'kind': 'clear'})
        await sub.unsubscribe(h)
        await sub.delete()
        # 坏质量 → 恢复后不应有"写回旧值"的刷屏（#13 的根因）
        comm('opcua', 'bad')
        await asyncio.sleep(1.5)
        bad = await temp.read_data_value(raise_on_bad_status=False)
        ok('坏质量：BadCommunicationError', bad.StatusCode.name == 'BadCommunicationError', bad.StatusCode.name)
        comm('opcua', '')
        await asyncio.sleep(2)
        good = await temp.read_data_value()
        ok('坏质量恢复后数值正常', good.StatusCode.is_good() and isinstance(good.Value.Value, float), good.Value.Value)
        # 设备级卡死：只有这个点位被卡住
        comm('opcua', 'stuck', station='FUR1', tag='Bath/Temperature', value=1234.5)
        await asyncio.sleep(1.5)
        sv = await temp.read_value()
        other = await n('FUR2/Bath/Temperature').read_value() if True else None
        ok('#87 点位级卡死（OPC UA FUR1/Bath/Temperature = 1234.5，其它点不受影响）', sv == 1234.5 and other != 1234.5, f'{sv} / FUR2 {other}')
        clear_all()
    # 断开：订阅了本厂的会话被关闭；重连后一碰本厂节点就再被断开；恢复后正常
    c = Client(url, timeout=4)
    await c.connect()
    idx = await c.get_namespace_index('http://honeymeta.cn/vfactory')

    class N:
        def datachange_notification(self, *a):
            pass
    sub = await c.create_subscription(300, N())
    await sub.subscribe_data_change(c.get_node(f'ns={idx};s={PID}/FUR1/Bath/Temperature'))
    comm('opcua', 'disconnect')
    await asyncio.sleep(2.5)
    try:
        await asyncio.wait_for(c.get_node(f'ns={idx};s={PID}/FUR1/Bath/Temperature').read_value(), 4)
        dropped = False
    except Exception as e:      # noqa: BLE001
        dropped = True
        why = type(e).__name__
    ok('#74 OPC UA 断开：会话被关闭', dropped, why if dropped else '会话还活着')
    try:
        await c.disconnect()
    except Exception:
        pass
    c2 = Client(url, timeout=4)
    await c2.connect()
    try:
        v = await asyncio.wait_for(c2.get_node(f'ns={idx};s={PID}/FUR1/Bath/Temperature').read_data_value(raise_on_bad_status=False), 4)
        rej = v.StatusCode.name
    except Exception as e:      # noqa: BLE001
        rej = type(e).__name__
    ok('#74 OPC UA 断开期间重连读本厂节点被拒', rej != 'Good', rej)
    try:
        await c2.disconnect()
    except Exception:
        pass
    comm('opcua', '')
    await asyncio.sleep(1.5)
    async with Client(url) as c3:
        v = await c3.get_node(f'ns={idx};s={PID}/FUR1/Bath/Temperature').read_data_value()
        ok('#74 恢复后重连正常', v.StatusCode.is_good(), v.Value.Value)


# ------------------------------------------------------------------ MQTT
async def mqtt_checks():
    from amqtt.client import MQTTClient
    base = f'vfactory/{PID}'
    c = MQTTClient(client_id='pc2-checker', config={'auto_reconnect': False})
    await c.connect(f'mqtt://{HOST}:{MQTT}/')
    t_tap = f'{base}/melting/FUR1/Setpoint/TapTemp'
    await c.subscribe([(f'{base}/#', 0)])
    msgs = []

    async def pump(sec):
        t0 = time.time()
        while time.time() - t0 < sec:
            try:
                m = await c.deliver_message(timeout_duration=0.3)
                msgs.append((time.time(), m.topic, m.data.decode('utf-8', 'replace')))
            except asyncio.TimeoutError:
                pass
    await pump(3)
    pl = next((json.loads(d) for _t, tp, d in msgs if tp == f'{base}/melting/FUR1/Bath/Temperature'), None)
    ok('#72 载荷 ts / sim_ts / wall_ts 是带时区的 ISO 8601，带 quality', pl and all(k in pl for k in ('ts', 'sim_ts', 'wall_ts', 'quality'))
       and datetime.fromisoformat(pl['sim_ts']).tzinfo is not None and datetime.fromisoformat(pl['wall_ts']).tzinfo is not None, pl)
    stat = next((json.loads(d) for _t, tp, d in msgs if tp == f'{base}/_status'), None)
    ok('#72 _status 心跳带时间', stat and stat.get('online') is True and 'wall_ts' in stat, stat)
    # {"value": x} 写入 + 回执
    msgs.clear()
    await c.publish(t_tap + '/set', json.dumps({'value': 1491, 'id': 'req-1'}).encode())
    await pump(2.5)
    ack = next((json.loads(d) for _t, tp, d in msgs if tp == t_tap + '/set/ack'), None)
    ok('#71 {"value": x} 写入生效并回 /set/ack（带请求号）', ack and ack['ok'] and ack['id'] == 'req-1' and tagv('FUR1', 'Setpoint/TapTemp') == 1491.0, ack)
    msgs.clear()
    await c.publish(t_tap + '/set', b'1492')
    await c.publish(t_tap + '/set', json.dumps({'value': 99999, 'id': 'req-2'}).encode())
    await c.publish(t_tap + '/set', b'{"val": 1}')
    await pump(2.5)
    acks = [json.loads(d) for _t, tp, d in msgs if tp == t_tap + '/set/ack']
    errs = [json.loads(d) for _t, tp, d in msgs if tp == f'{base}/_errors']
    ok('#71 纯数值写入仍可用', any(a['ok'] and a['value'] == 1492.0 for a in acks), acks[:1])
    ok('#71 越界写入回执失败（code=range）并发到 _errors', any(not a['ok'] and a.get('code') == 'range' and a['id'] == 'req-2' for a in acks)
       and any(e.get('code') == 'range' for e in errs), [a.get('error') for a in acks])
    ok('#71 格式不对回执失败（code=format）', any(not a['ok'] and a.get('code') == 'format' for a in acks))
    http(P + '/station/FUR1/write', {'tag': 'Setpoint/TapTemp', 'value': 1500})
    # 坏质量不洪泛
    msgs.clear()
    comm('mqtt', 'bad')
    await pump(6)
    comm('mqtt', '')
    taps = [d for _t, tp, d in msgs if tp == t_tap]
    allbad = [d for _t, tp, d in msgs if '"quality": "bad"' in d]
    topics = {tp for _t, tp, d in msgs if '"quality": "bad"' in d}
    ok('#73 坏质量只发一次（不变的点 6 秒内只 1 条）', len(taps) == 1 and json.loads(taps[0])['quality'] == 'bad', f'TapTemp {len(taps)} 条；坏质量报文 {len(allbad)} 条 / {len(topics)} 个主题')
    await pump(2)
    # 设备级漂移、丢包
    comm('mqtt', 'drift', station='FUR1', tag='Setpoint/TapTemp', rate=60)
    msgs.clear()
    await pump(4)
    vals = [json.loads(d)['value'] for _t, tp, d in msgs if tp == t_tap]
    ok('#87 点位级漂移（MQTT 设定值在变，模型不变）', len(vals) >= 2 and vals[-1] != vals[0] and tagv('FUR1', 'Setpoint/TapTemp') == 1500.0, vals[:5])
    clear_all()
    comm('mqtt', 'latency', station='CNC1', latency=3)
    http(P + '/station/CNC1/write', {'tag': 'Monitoring/Feed/Override', 'value': 93})
    t_w = time.time()
    msgs.clear()
    await pump(6)
    hit = [t for t, tp, d in msgs if tp.endswith('/CNC1/Monitoring/Feed/Override') and json.loads(d)['value'] == 93]
    ok('#87 设备级延迟（CNC1 的报文晚约 3 秒到）', hit and hit[0] - t_w >= 2.5, f'{(hit[0] - t_w) if hit else None:.1f}s' if hit else '没收到')
    http(P + '/station/CNC1/write', {'tag': 'Monitoring/Feed/Override', 'value': 100})
    clear_all()
    # 断开：外部客户端被踢、重订阅被拒，_mes 先存后补发
    msgs.clear()
    comm('mqtt', 'disconnect')
    t0 = time.time()
    kicked = False
    while time.time() - t0 < 6:
        try:
            m = await c.deliver_message(timeout_duration=0.5)
            msgs.append((time.time(), m.topic, m.data.decode('utf-8', 'replace')))
        except asyncio.TimeoutError:
            pass
        except Exception:      # noqa: BLE001
            kicked = True
            break
        if not c.session or not getattr(c, '_connected_state', None) or (hasattr(c._connected_state, 'is_set') and not c._connected_state.is_set()):
            kicked = True
            break
    ok('#74 MQTT 断开：订阅本厂的客户端被踢掉', kicked, f'{time.time() - t0:.1f}s')
    try:
        await c.disconnect()
    except Exception:
        pass
    c2 = MQTTClient(client_id='pc2-checker-2', config={'auto_reconnect': False})
    await c2.connect(f'mqtt://{HOST}:{MQTT}/')
    rc = await c2.subscribe([(f'{base}/#', 0)])
    ok('#74 断开期间订阅本厂主题被拒', rc and rc[0] == 0x80, rc)
    await c2.disconnect()
    q0 = http(P + '/signals/status')['mqtt_stats']
    await asyncio.sleep(3)
    q1 = http(P + '/signals/status')['mqtt_stats']
    comm('mqtt', '')
    await asyncio.sleep(1.5)
    q2 = http(P + '/signals/status')['mqtt_stats']
    ok('#74 断开期间 _mes 先存着（不发），恢复后补发', q1['mes_queue'] > q0['mes_queue'] and q2['mes_queue'] == 0,
       f"断开中队列 {q0['mes_queue']} → {q1['mes_queue']}，恢复后 {q2['mes_queue']}")


# ------------------------------------------------------------------ Modbus
def modbus_checks():
    from pymodbus.client import ModbusTcpClient
    pts = {p['key']: p for p in http(P + '/points/v2')['points']}
    port = pts['FUR1/Setpoint/PowerKW']['modbus']['port']
    c = ModbusTcpClient(HOST, port=port, timeout=3, retries=0)
    c.connect()
    m = pts['FUR1/Setpoint/PowerKW']['modbus']
    r = c.read_holding_registers(m['address'], count=m['count'], slave=m['unit'])
    v = struct.unpack('>f', struct.pack('>HH', *r.registers))[0] if m['type'] == 'float32' and m['order'] == 'ABCD' else None
    ok('#76 读设定值（float32 保持寄存器）', v is not None and abs(v - tagv('FUR1', 'Setpoint/PowerKW')) < 0.5, f"Unit {m['unit']} HR{m['address']} = {v}")
    regs = list(struct.unpack('>HH', struct.pack('>f', 1800.0)))
    w = c.write_registers(m['address'], regs, slave=m['unit'])
    ok('#76 Modbus 写设定值进入模型', not w.isError() and tagv('FUR1', 'Setpoint/PowerKW') == 1800.0, tagv('FUR1', 'Setpoint/PowerKW'))
    w = c.write_registers(m['address'], list(struct.unpack('>HH', struct.pack('>f', -99999.0))), slave=m['unit'])
    ok('#67/#77 越界写入返回异常码 03', w.isError() and getattr(w, 'exception_code', None) == 3 and tagv('FUR1', 'Setpoint/PowerKW') == 1800.0, w)
    http(P + '/station/FUR1/write', {'tag': 'Setpoint/PowerKW', 'value': 2000})
    ro = pts['FUR1/Bath/Temperature']['modbus']
    w = c.write_registers(ro['address'], [0, 0], slave=ro['unit'])
    ok('#77 写只读寄存器返回异常码 02', w.isError() and getattr(w, 'exception_code', None) == 2, w)
    r = c.read_holding_registers(0, count=2, slave=99)
    ok('#77 不存在的 Unit 返回异常码 0B（不再是畸形包）', r.isError() and getattr(r, 'exception_code', None) == 11, r)
    r = c.read_holding_registers(60000, count=2, slave=m['unit'])
    ok('#77 地址越界返回异常码 02', r.isError() and getattr(r, 'exception_code', None) == 2, r)
    ir = c.read_input_registers(ro['address'], count=2, slave=ro['unit'])
    ok('输入寄存器（04）同址镜像', not ir.isError() and len(ir.registers) == 2)
    sand = c.read_holding_registers(0, count=1, slave=1)
    ok('原有手工地址不变（砂处理 Unit1 HR0 水分 ÷100）', not sand.isError() and 2.0 < sand.registers[0] / 100 < 5.0, sand.registers)
    # 数据类型 / 字序
    http(P + '/protocol/settings', {'modbus': {'fmt': 'int32', 'order': 'CDAB'}}, method='PUT')
    pts2 = {p['key']: p for p in http(P + '/points/v2')['points']}
    m2 = pts2['FUR1/Bath/Temperature']['modbus']
    r = c.read_holding_registers(m2['address'], count=2, slave=m2['unit'])
    lo, hi = r.registers
    iv = struct.unpack('>i', struct.pack('>HH', hi, lo))[0] / (m2['scale'] or 1)
    ok('#78 数据类型 int32 + 字序 CDAB 生效', m2['type'] == 'int32' and m2['order'] == 'CDAB' and abs(iv - tagv('FUR1', 'Bath/Temperature')) < 5,
       f"{iv} vs {tagv('FUR1', 'Bath/Temperature')} scale {m2['scale']}")
    http(P + '/protocol/settings', {'modbus': {'fmt': 'float32', 'order': 'ABCD'}}, method='PUT')
    # 延迟
    comm('modbus', 'latency', latency=2)
    t0 = time.time()
    r = c.read_holding_registers(0, count=1, slave=1)
    dt = time.time() - t0
    ok('#75 Modbus 延迟真的生效', not r.isError() and dt >= 1.8, f'{dt:.2f}s')
    clear_all()
    comm('modbus', 'bad', station='SAND1')
    r = c.read_holding_registers(0, count=1, slave=1)
    r2 = c.read_holding_registers(m['address'], count=2, slave=m['unit'])
    ok('#87 设备级坏质量：该从站返回异常码 04，别的从站正常', r.isError() and getattr(r, 'exception_code', None) == 4 and not r2.isError(), r)
    clear_all()
    c.close()


# ------------------------------------------------------------------ 令牌
def token_checks():
    other = [p['id'] for p in http('/api/plants')['plants'] if p['id'] != PID]
    t_read = http('/api/tokens', {'name': '检查-只读', 'scope': 'read', 'plants': [PID], 'expires_days': 1})
    ok('#81 新建只读令牌（限定工厂、1 天有效）', t_read['token'].startswith('vf_') and t_read['expires'], t_read['expires'])
    tk = t_read['token']
    ok('#81 只读令牌能读', http(P + '/meta', tok=tk)['id'] == PID)
    code, _ = http_err(f'{P}/station/FUR1/write', {'tag': 'Setpoint/TapTemp', 'value': 1500}, tok=tk)
    ok('#81 只读令牌不能写（403）', code == 403, code)
    if other:
        code, _ = http_err(f'/api/p/{other[0]}/meta', tok=tk)
        ok('#81 限定工厂：访问别的工厂 403', code == 403, code)
    ov = http('/api/overview', tok=tk)
    ok('#81 限定工厂：总览只看到自己', [x['id'] for x in ov['plants']] == [PID])
    code, _ = http_err('/api/tokens', tok=tk)
    ok('#81 非 admin 范围不能看令牌列表', code == 403, code)
    t_w = http('/api/tokens', {'name': '检查-写点位', 'scope': 'write'})['token']
    w = http(f'{P}/station/FUR1/write', {'tag': 'Setpoint/TapTemp', 'value': 1500}, tok=t_w)
    code, _ = http_err(P + '/signals/comm', {'protocol': 'mqtt', 'mode': 'freeze'}, tok=t_w)
    ok('#81 write 范围能写点位、不能注入故障', w['ok'] and code == 403, code)
    t_old = http('/api/tokens', {'name': '检查-已过期', 'scope': 'read', 'expires': '2020-01-01'})['token']
    code, msg = http_err(P + '/meta', tok=t_old)
    ok('#81 过期令牌 401', code == 401 and '过期' in msg, msg[:80])
    t_ip = http('/api/tokens', {'name': '检查-IP', 'scope': 'read', 'ips': '10.254.254.254'})['token']
    code, msg = http_err(P + '/meta', tok=t_ip)
    ok('#81 IP 白名单生效', code == 401 and '白名单' in msg, msg[:80])
    code, _ = http_err('/api/tokens', {'name': 'x', 'scope': 'nope'})
    ok('#81 范围不对 400', code == 400)
    time.sleep(0.2)
    rows = {r['name']: r for r in http('/api/tokens')}
    r = rows['检查-只读']
    ok('#81 最近使用/次数/来源 IP 按真实调用记录', r['last_used'] and r['uses'] >= 1 and r['last_ip'] and r['scope'] == 'read' and r['plants'] == [PID],
       {k: r[k] for k in ('last_used', 'uses', 'last_ip', 'scope', 'plants', 'expires')})
    fresh = http('/api/tokens', {'name': '检查-新建未用', 'scope': 'read'})
    rows = {x['name']: x for x in http('/api/tokens')}
    ok('#81 新建未使用的令牌"最近使用"为空', not rows['检查-新建未用']['last_used'])
    for x in http('/api/tokens'):
        if x['name'].startswith('检查-') and not x['revoked']:
            http(f"/api/tokens/{x['id']}", method='DELETE')
    return t_w, fresh


async def mqtt_auth_checks():
    from amqtt.client import MQTTClient
    base = f'vfactory/{PID}'
    tok = http('/api/tokens', {'name': '检查-MQTT', 'scope': 'write', 'plants': [PID]})['token']
    rtok = http('/api/tokens', {'name': '检查-MQTT只读', 'scope': 'read'})['token']
    http('/api/settings/mqtt', {'anonymous': 'ro'}, method='PUT')
    try:
        t = f'{base}/melting/FUR1/Setpoint/CarbonRaiserKg'
        c = MQTTClient(client_id='pc2-anon')
        await c.connect(f'mqtt://{HOST}:{MQTT}/')
        await c.publish(t + '/set', b'12')
        await asyncio.sleep(1.5)
        await c.disconnect()
        ok('#70 MQTT 匿名只读：匿名写 /set 被拒', tagv('FUR1', 'Setpoint/CarbonRaiserKg') != 12.0, tagv('FUR1', 'Setpoint/CarbonRaiserKg'))
        c = MQTTClient(client_id='pc2-tok')
        await c.connect(f'mqtt://mes:{tok}@{HOST}:{MQTT}/')
        await c.publish(t + '/set', b'12')
        await asyncio.sleep(1.5)
        await c.disconnect()
        ok('#70 MQTT 用 API 令牌（write 范围）作密码可以写', tagv('FUR1', 'Setpoint/CarbonRaiserKg') == 12.0, tagv('FUR1', 'Setpoint/CarbonRaiserKg'))
        c = MQTTClient(client_id='pc2-rtok')
        await c.connect(f'mqtt://mes:{rtok}@{HOST}:{MQTT}/')
        await c.publish(t + '/set', b'13')
        await asyncio.sleep(1.5)
        await c.disconnect()
        ok('#70 只读令牌不能写', tagv('FUR1', 'Setpoint/CarbonRaiserKg') == 12.0)
        http('/api/settings/mqtt', {'anonymous': 'none'}, method='PUT')
        c = MQTTClient(client_id='pc2-anon2', config={'auto_reconnect': False})
        try:
            await asyncio.wait_for(c.connect(f'mqtt://{HOST}:{MQTT}/'), 5)
            refused = False
            await c.disconnect()
        except Exception:      # noqa: BLE001
            refused = True
        ok('#70 禁止匿名：匿名连接被拒', refused)
    finally:
        http('/api/settings/mqtt', {'anonymous': 'rw'}, method='PUT')
        http(P + '/station/FUR1/write', {'tag': 'Setpoint/CarbonRaiserKg', 'value': 0})
        for x in http('/api/tokens'):
            if x['name'].startswith('检查-') and not x['revoked']:
                http(f"/api/tokens/{x['id']}", method='DELETE')


def log_check(mark):
    path = os.environ.get('VF_LOG')
    if not path or not os.path.exists(path):
        print('INFO 没给 VF_LOG，跳过日志检查')
        return
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.read().splitlines()
    tail = lines[mark:]
    rej = [x for x in tail if 'write rejected' in x or '写入被拒绝' in x]
    ok('#13 服务日志没有"写入被拒绝"刷屏（只有测试故意写的几条）', len(rej) <= 12, f'{len(rej)} 条：' + ' | '.join(x[-80:] for x in rej[:3]))


def log_len():
    path = os.environ.get('VF_LOG')
    if not path or not os.path.exists(path):
        return 0
    with open(path, encoding='utf-8', errors='replace') as f:
        return len(f.read().splitlines())


if __name__ == '__main__':
    TOKEN = http('/api/login', {'username': 'admin', 'password': 'honey123'}, tok='')['token']
    mark = log_len()
    clear_all()
    try:
        rest_checks()
        asyncio.run(opcua_checks())
        asyncio.run(mqtt_checks())
        modbus_checks()
        token_checks()
        asyncio.run(mqtt_auth_checks())
        # 新建工厂（#13）：不应刷出几百行"写入被拒绝"
        pid = http('/api/plants', {'name': '协议检查临时厂', 'template': 'machining'})['id']
        time.sleep(3)
        http(f'/api/plants/{pid}', method='DELETE')
        log_check(mark)
    finally:
        clear_all()
        http(P + '/protocol/settings', {'modbus': {'fmt': 'float32', 'order': 'ABCD'}, 'time': 'sim'}, method='PUT')
    bad = [n for n, g in results if not g]
    print(f'\n{len(results) - len(bad)}/{len(results)} 通过' + ('；失败：' + '、'.join(bad) if bad else ''))
    sys.exit(1 if bad else 0)
