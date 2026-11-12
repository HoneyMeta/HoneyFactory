"""4.3 通讯层检查：网关组织地址空间、旧地址兼容、网络线故障、MES 节点、架构接口、没有网关的工厂不变。真实客户端（asyncua / amqtt / pymodbus）。

先启动服务（示范工厂 foundry-housing 带 SW1 交换机、GW1 网关、MES1），再运行：
    python tests/protocol_check3.py
环境变量同 protocol_check2：VF_HOST、VF_HTTP / VF_OPCUA / VF_MQTT、VF_PLANT。会注入并恢复网络故障、临时建删一个工厂。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request

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


def link_fault(lid, mode='', **kw):
    return http(P + '/signals/comm', {'link': lid, 'mode': mode, **kw})


def clear_all():
    http(P + '/signals/comm', method='DELETE')


def arch():
    return http(P + '/architecture')


def link_of(a, dev):
    """设备 → 它到交换机的那条网络线编号。"""
    return next(l['id'] for l in a['links'] if l['kind'] == 'network' and dev in (l['from'], l['to']))


def rest_checks():
    a = arch()
    gw = next((g for g in a['gateways'] if g['id'] == 'GW1'), None)
    ok('架构接口：有 GW1，采集 CNC1 / FUR1，北向用户有 MES1', gw and {'CNC1', 'FUR1'} <= set(gw['devices']) and 'MES1' in gw['consumers'],
       gw and {k: gw[k] for k in ('devices', 'consumers', 'north', 'points')})
    layers = {n['layer'] for n in a['nodes']}
    ok('架构接口：节点按层（it / network / process）', {'it', 'network', 'process'} <= layers and a['order'][:2] == ['it', 'network'], sorted(layers))
    ok('架构接口：网络线带状态', all(l['status'] in ('ok', 'degraded', 'down') for l in a['links']) and any(l['kind'] == 'network' for l in a['links']),
       len(a['links']))
    mes = next(n for n in a['nodes'] if n['id'] == 'MES1')
    ok('MES 节点有连接状态', 'mes' in mes and {'connected', 'clients', 'mes_per_min', 'reachable', 'url'} <= set(mes['mes']), mes.get('mes'))
    pts = {p['key']: p for p in http(P + '/points/v2')['points']}
    p = pts['CNC1/Monitoring/Spindle/Load']
    ok('点表 v2：设备带主网关和网关地址', p.get('gateway') == 'GW1' and p['via'][0]['opcua_nodeid'] == f'ns=2;s={PID}/GW1/CNC1/Monitoring/Spindle/Load'
       and p['via'][0]['mqtt_topic'] == f'vfactory/{PID}/GW1/CNC1/Monitoring/Spindle/Load', p.get('via'))
    ok('点表 v2：旧地址仍在（兼容）', p['opcua_nodeid'] == f'ns=2;s={PID}/CNC1/Monitoring/Spindle/Load' and p['mqtt_topic'].endswith('/CNC1/Monitoring/Spindle/Load'))
    return a


async def opcua_checks(a):
    from asyncua import Client, ua
    async with Client(f'opc.tcp://{HOST}:{OPCUA}/vfactory/') as c:
        idx = await c.get_namespace_index('http://honeymeta.cn/vfactory')
        n = lambda s: c.get_node(f'ns={idx};s={PID}/{s}')  # noqa: E731
        g = await n('GW1/CNC1/Monitoring/Spindle/Load').read_data_value()
        old = await n('CNC1/Monitoring/Spindle/Load').read_data_value()
        ok('OPC UA 网关地址 <厂>/GW1/CNC1/… 能读', g.StatusCode.is_good() and isinstance(g.Value.Value, float), g.Value.Value)
        ok('OPC UA 旧地址 <厂>/CNC1/… 仍能读（别名）', old.StatusCode.is_good(), old.Value.Value)
        kids = [(await k.read_browse_name()).Name for k in await n('GW1').get_children()]
        ok('OPC UA 网关对象下挂着它采集的设备', 'CNC1' in kids and 'FUR1' in kids, kids[:8])
        lid = link_of(a, 'CNC1')
        link_fault(lid, 'disconnect')
        await asyncio.sleep(1.5)
        g = await n('GW1/CNC1/Monitoring/Spindle/Load').read_data_value(raise_on_bad_status=False)
        old = await n('CNC1/Monitoring/Spindle/Load').read_data_value(raise_on_bad_status=False)
        other = await n('GW1/CNC2/Monitoring/Spindle/Load').read_data_value(raise_on_bad_status=False)
        ok(f'网络线 {lid}（CNC1→交换机）断开：网关地址 BadNotConnected', g.StatusCode.name == 'BadNotConnected', g.StatusCode.name)
        ok('旧地址跟着主网关一起断（别名）', old.StatusCode.name == 'BadNotConnected', old.StatusCode.name)
        ok('别的设备不受影响', other.StatusCode.is_good(), other.StatusCode.name)
        try:
            await n('GW1/CNC1/Monitoring/Feed/Override').write_value(ua.DataValue(ua.Variant(95.0, ua.VariantType.Double)))
            wr = 'Good'
        except ua.UaStatusCodeError as e:
            wr = ua.StatusCode(e.code).name
        ok('断开时经网关写入返回 BadNotConnected', wr == 'BadNotConnected', wr)
        a2 = arch()
        l2 = next(l for l in a2['links'] if l['id'] == lid)
        gw = next(x for x in a2['gateways'] if x['id'] == 'GW1')
        ok('架构接口：这条线 down、网关列出断开的设备', l2['status'] == 'down' and 'CNC1' in gw['devices_down'] and 'CNC1' in l2['carries'], (l2['status'], gw['devices_down']))
        link_fault(lid, '')
        await asyncio.sleep(1.5)
        g = await n('GW1/CNC1/Monitoring/Spindle/Load').read_data_value()
        ok('恢复后网关地址正常', g.StatusCode.is_good())
        # 冻结：经过这条线的值停在故障开始时
        lf = link_of(a, 'FUR1')
        link_fault(lf, 'freeze')
        await asyncio.sleep(1.2)                  # 等一个发布周期：节点换成冻结那一刻的值
        v1 = await n('GW1/FUR1/Bath/Temperature').read_value()
        await asyncio.sleep(3)
        v2 = await n('GW1/FUR1/Bath/Temperature').read_value()
        real = http(P + '/station/FUR1')['tags']['Bath/Temperature']['v']
        ok(f'网络线 {lf} 冻结：网关读到的值不变（模型在变）', v1 == v2 and abs(real - v2) > 1e-6, f'{v1} → {v2}，模型 {real}')
        link_fault(lf, '')
        # 交换机故障 = 所有经过它的设备断开
        http(P + '/station/SW1/fault', {'kind': 'failure'})
        await asyncio.sleep(1.5)
        bad = [(await n(f'GW1/{d}/Common/State').read_data_value(raise_on_bad_status=False)).StatusCode.name for d in ('CNC1', 'FUR1', 'INS1')]
        ok('交换机故障：经过它的设备全部断开', all(b == 'BadNotConnected' for b in bad), bad)
        http(P + '/station/SW1/fault', {'kind': 'clear'})
        await asyncio.sleep(1.5)
        good = (await n('GW1/CNC1/Common/State').read_data_value()).StatusCode.is_good()
        ok('交换机修好后恢复', good)


async def mqtt_checks(a):
    from amqtt.client import MQTTClient
    base = f'vfactory/{PID}'
    c = MQTTClient(client_id='pc3-checker')
    await c.connect(f'mqtt://{HOST}:{MQTT}/')
    await c.subscribe([(f'{base}/GW1/#', 0), (f'{base}/melting/FUR1/Bath/Temperature', 0), (f'{base}/machining/CNC1/Monitoring/Feed/Override', 0)])
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
    tops = {t for _w, t, _d in msgs}
    ok('MQTT 网关主题 vfactory/<厂>/GW1/<设备>/<点位>', f'{base}/GW1/FUR1/Bath/Temperature' in tops, sorted(x for x in tops if '/GW1/' in x)[:3])
    ok('MQTT 旧主题照发（兼容 HoneyMES）', f'{base}/melting/FUR1/Bath/Temperature' in tops)
    st = next((json.loads(d) for _w, t, d in msgs if t == f'{base}/GW1/_status'), None)
    ok('网关 _status（在线、设备数）', st and st['online'] is True and st['devices'] >= 15, st)
    msgs.clear()
    t_set = f'{base}/GW1/CNC1/Monitoring/Feed/Override/set'
    await c.publish(t_set, json.dumps({'value': 91, 'id': 'gw-1'}).encode())
    await pump(2)
    ack = next((json.loads(d) for _w, t, d in msgs if t == t_set + '/ack'), None)
    ok('经网关主题写入 + 回执', ack and ack['ok'] and http(P + '/station/CNC1')['tags']['Monitoring/Feed/Override']['v'] == 91.0, ack)
    lid = link_of(a, 'CNC1')
    link_fault(lid, 'disconnect')
    msgs.clear()
    await c.publish(t_set, b'92')
    await pump(3)
    ack = next((json.loads(d) for _w, t, d in msgs if t == t_set + '/ack'), None)
    st = [json.loads(d) for _w, t, d in msgs if t == f'{base}/GW1/_status']
    ok('链路断开：经网关写入回执 offline', ack and not ack['ok'] and ack.get('code') == 'offline', ack)
    ok('链路断开：网关 _status 列出断开的设备', st and 'CNC1' in st[-1]['devices_down'], st[-1:] if st else None)
    link_fault(lid, '')
    # 延迟
    link_fault(lid, 'latency', latency=3)
    http(P + '/station/CNC1/write', {'tag': 'Monitoring/Feed/Override', 'value': 88})
    tw = time.time()
    msgs.clear()
    await pump(6)
    hit = [w for w, t, d in msgs if t == f'{base}/GW1/CNC1/Monitoring/Feed/Override' and json.loads(d)['value'] == 88]
    ok('网络线延迟 3 秒：网关报文晚到', hit and hit[0] - tw >= 2.5, f'{hit[0] - tw:.1f}s' if hit else '没收到')
    link_fault(lid, '')
    http(P + '/station/CNC1/write', {'tag': 'Monitoring/Feed/Override', 'value': 100})
    await c.disconnect()
    # 网关到 MES 的线断了：_mes 先存在网关，恢复后补发
    lm = next(l['id'] for l in a['links'] if l['kind'] == 'network' and 'MES1' in (l['from'], l['to']))
    link_fault(lm, 'disconnect')
    await asyncio.sleep(1)
    q0 = http(P + '/signals/status')['mqtt_stats']
    await asyncio.sleep(4)
    q1 = http(P + '/signals/status')['mqtt_stats']
    mes = next(n for n in arch()['nodes'] if n['id'] == 'MES1')
    ok(f'网络线 {lm}（网关→MES）断开：_mes 存在网关、MES 显示路断', q1['mes_queue'] + q1['mes_held'] > q0['mes_queue'] + q0['mes_held'] and not mes['mes']['path_up'],
       f"队列 {q0['mes_queue'] + q0['mes_held']} → {q1['mes_queue'] + q1['mes_held']}，path_up={mes['mes']['path_up']}")
    link_fault(lm, '')
    await asyncio.sleep(2)
    q2 = http(P + '/signals/status')['mqtt_stats']
    ok('恢复后补发', q2['mes_held'] == 0 and q2['mes_queue'] < 50, q2)


def modbus_checks(a):
    from pymodbus.client import ModbusTcpClient
    pts = {p['key']: p for p in http(P + '/points/v2')['points']}
    m = pts['CNC1/Monitoring/Spindle/Load']['modbus']
    c = ModbusTcpClient(HOST, port=m['port'], timeout=3, retries=0)
    c.connect()
    r = c.read_holding_registers(m['address'], count=m['count'], slave=m['unit'])
    ok('Modbus 单元地址不变、经网关可读', not r.isError(), m)
    lid = link_of(a, 'CNC1')
    link_fault(lid, 'disconnect')
    time.sleep(0.5)
    r = c.read_holding_registers(m['address'], count=m['count'], slave=m['unit'])
    m2 = pts['CNC2/Monitoring/Spindle/Load']['modbus']
    r2 = c.read_holding_registers(m2['address'], count=m2['count'], slave=m2['unit'])
    ok('链路断开：该设备的单元返回 0B（网关目标无响应），别的单元正常', r.isError() and getattr(r, 'exception_code', None) == 11 and not r2.isError(), r)
    link_fault(lid, '')
    c.close()


def script_check(a):
    lid = link_of(a, 'CNC1')
    sc = {'name': '网络线断开剧本', 'speed': 30, 'steps': [
        {'kind': 'comm_fault', 'link': lid, 'mode': 'disconnect'},
        {'kind': 'assert', 'via': 'opcua', 'station': 'CNC1', 'tag': 'Common/State', 'expect_bad': True, 'within': 6},
        {'kind': 'comm_fault', 'link': lid, 'mode': ''},
        {'kind': 'assert', 'via': 'opcua', 'station': 'CNC1', 'tag': 'Monitoring/Feed/Override', 'op': '==', 'value': 100, 'within': 6}]}
    rid = http(P + '/tests/run', {'script': sc})['run_id']
    for _ in range(60):
        r = http(P + f'/tests/runs/{rid}')
        if r['status'] != 'running':
            break
        time.sleep(1)
    ok('测试剧本里的网络线故障步骤', r['status'] == 'passed', [s['msg'] for s in r['steps']])


def no_gateway_check():
    pid = http('/api/plants', {'name': '无网关检查厂', 'template': 'integrated'})['id']
    try:
        a = http(f'/api/p/{pid}/architecture')
        pts = http(f'/api/p/{pid}/points/v2')['points']
        ok('没有网关的工厂：架构接口 has_gateways = false', a['has_gateways'] is False and not a['gateways'])
        ok('没有网关的工厂：点表没有网关字段，地址和以前一样', all('gateway' not in p for p in pts) and
           all((p['opcua_nodeid'] or '').startswith(f'ns=2;s={pid}/') and (p['opcua_nodeid'] or '').count('/') == p['key'].count('/') + 1 for p in pts if p['opcua_nodeid']),
           pts[0]['opcua_nodeid'])
    finally:
        http(f'/api/plants/{pid}', method='DELETE')


if __name__ == '__main__':
    TOKEN = http('/api/login', {'username': 'admin', 'password': 'honey123'}, tok='')['token']
    clear_all()
    try:
        a = rest_checks()
        asyncio.run(opcua_checks(a))
        asyncio.run(mqtt_checks(a))
        modbus_checks(a)
        script_check(a)
        no_gateway_check()
    finally:
        clear_all()
        try:
            http(P + '/station/SW1/fault', {'kind': 'clear'})
        except urllib.error.HTTPError:
            pass
    bad = [n for n, g in results if not g]
    print(f'\n{len(results) - len(bad)}/{len(results)} 通过' + ('；失败：' + '、'.join(bad) if bad else ''))
    sys.exit(1 if bad else 0)
