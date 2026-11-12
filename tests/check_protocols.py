"""用"真实客户端"检查三种协议：读到会变化的数据，写入能改变仿真。
运行前先启动：python -m vfactory serve
    python tests/check_protocols.py [host]
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import asyncio
import json
import struct
import sys
import time
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
sys.stdout.reconfigure(encoding='utf-8')
results = []
P = '/api/p/foundry-housing'


def ok(name, cond, detail=''):
    results.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, detail)


TOKEN = ''


def http(path, body=None, method=None):
    req = urllib.request.Request(f'http://{HOST}:{__import__("os").environ.get("VF_HTTP", "8800")}{path}', data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + TOKEN} if TOKEN else {})}, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


async def opcua():
    from asyncua import Client, ua
    async with Client(f'opc.tcp://{HOST}:{__import__("os").environ.get("VF_OPCUA", "4840")}/vfactory/') as c:
        idx = await c.get_namespace_index('http://honeymeta.cn/vfactory')
        temp = c.get_node(f'ns={idx};s=foundry-housing/FUR1/Bath/Temperature')
        v1 = await temp.read_value()
        await asyncio.sleep(3)
        v2 = await temp.read_value()
        ok('OPC UA 读电炉温度且在变化', v1 != v2, f'{v1} -> {v2}')
        load = await c.get_node(f'ns={idx};s=foundry-housing/CNC1/Monitoring/Spindle/Load').read_value()
        ok('OPC UA 读 CNC 主轴负载', isinstance(load, float), f'{load}%')
        fo = c.get_node(f'ns={idx};s=foundry-housing/CNC1/Monitoring/Feed/Override')
        await fo.write_value(ua.Variant(85.0, ua.VariantType.Double))
        await asyncio.sleep(1.5)
        st = http(P + '/station/CNC1')
        ok('OPC UA 写进给倍率进入模型', st['tags']['Monitoring/Feed/Override']['v'] == 85.0, str(st['tags']['Monitoring/Feed/Override']['v']))
        await fo.write_value(ua.Variant(100.0, ua.VariantType.Double))


def modbus():
    from pymodbus.client import ModbusTcpClient
    c = ModbusTcpClient(HOST, port=int(__import__('os').environ.get('VF_MODBUS', '5020')))
    c.connect()
    r = c.read_holding_registers(0, count=7, slave=1)
    moist = r.registers[0] / 100
    ok('Modbus 读型砂水分（Unit1 HR0 ÷100）', 2.0 < moist < 5.0, f'{moist}%')
    c.write_register(100, 360, slave=1)                    # 水分设定 3.60%
    time.sleep(1.5)
    st = http(P + '/station/SAND1')
    ok('Modbus 写水分设定进入模型', abs(st['tags']['Setpoint/Moisture']['v'] - 3.60) < 1e-6, str(st['tags']['Setpoint/Moisture']['v']))
    c.write_register(100, 340, slave=1)
    m = c.read_holding_registers(0, count=4, slave=10).registers
    kw = struct.unpack('>f', struct.pack('>HH', m[0], m[1]))[0]
    ok('Modbus 读全厂电能表（Unit10 float32）', kw > 0, f'{kw:.0f} kW')
    c.close()


def plants():
    r = http('/api/plants', {'name': '测试机加厂', 'template': 'machining'})
    pid = r['id']
    lst = http('/api/plants')['plants']
    me = next(p for p in lst if p['id'] == pid)
    ok('新建工厂（机加模板）', me['stations'] >= 8, f"{pid} Modbus :{me['modbus_port']}")
    from pymodbus.client import ModbusTcpClient
    c = ModbusTcpClient(HOST, port=me['modbus_port'])
    c.connect()
    m = c.read_holding_registers(0, count=4, slave=10).registers
    c.close()
    ok('新工厂独立 Modbus 端口在线', len(m) == 4, str(m))
    time.sleep(2)
    st = http(f'/api/p/{pid}/state')
    ok('新工厂在跑', st['t'] > 0, st['time'])
    ok('删除工厂', http(f'/api/plants/{pid}', method='DELETE')['ok'])


async def mqtt():
    from amqtt.client import MQTTClient
    c = MQTTClient(client_id='checker')
    await c.connect(f'mqtt://{HOST}:{__import__("os").environ.get("VF_MQTT", "1883")}/')
    await c.subscribe([('vfactory/foundry-housing/melting/FUR1/Bath/Temperature', 0), ('vda5050/v2/foundry-housing/+/state', 0)])
    got = {}
    t0 = time.time()
    while time.time() - t0 < 8 and len(got) < 2:
        try:
            m = await c.deliver_message(timeout_duration=3)
            got['vda' if m.topic.startswith('vda') else 'uns'] = m.data.decode()[:80]
        except asyncio.TimeoutError:
            pass
    ok('MQTT 收到 UNS 点位', 'uns' in got, got.get('uns', ''))
    ok('MQTT 收到 VDA 5050 AGV 状态', 'vda' in got, got.get('vda', ''))
    await c.publish('vfactory/foundry-housing/inspection/INS1/Setpoint/LedBrightness/set', b'{"value": 65}')
    await asyncio.sleep(1.5)
    st = http(P + '/station/INS1')
    ok('MQTT 写光源亮度进入模型', st['tags']['Setpoint/LedBrightness']['v'] == 65.0, str(st['tags']['Setpoint/LedBrightness']['v']))
    http(P + '/station/INS1/write', {'tag': 'Setpoint/LedBrightness', 'value': 70})
    await c.disconnect()


def api():
    m = http(P + '/meta')
    ok('HTTP /api/meta', len(m['stations']) >= 15, f"{len(m['stations'])} 台设备")
    r = http(P + '/station', {'template': 'CNC1'})
    ok('运行中新增一台 CNC', r['ok'], r['id'])
    time.sleep(2)
    st = http(f"{P}/station/{r['id']}")
    ok('新增 CNC 已开始工作或待料', st['state'] in ('Executing', 'Idle'), st['state'])
    r2 = http(f"{P}/station/{r['id']}", method='DELETE')
    ok('移除新增的 CNC', r2['ok'])
    sug = http(P + '/track/suggest')['id']
    loc = http(f'{P}/track/{sug}')
    ok('跟踪一件在制品（位置+履历）', loc.get('pos') and loc.get('history'), f"{sug} @ {loc.get('where')}")
    ok('工艺路线', len(m['route']) >= 8, f"{len(m['route'])} 步")
    http(P + '/station/FUR1/fault', {'kind': 'cooling_low'})
    pts = http(P + '/points')
    ok('点表可导出', len(pts) > 200, f'{len(pts)} 个点位')


if __name__ == '__main__':
    TOKEN = http('/api/login', {'username': 'admin', 'password': 'honey123'})['token']
    api()
    asyncio.run(opcua())
    modbus()
    asyncio.run(mqtt())
    plants()
    bad = [n for n, g in results if not g]
    print(f'\n{len(results) - len(bad)}/{len(results)} 通过', '；失败：' + '、'.join(bad) if bad else '')
