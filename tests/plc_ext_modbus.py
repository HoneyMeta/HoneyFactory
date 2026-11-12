"""外接 PLC 测试（先启动 serve）：本脚本扮演"外部 PLC"，通过 Modbus TCP 控制一个控制单元。

    python tests/plc_ext_modbus.py <工厂> <控制单元> [Modbus 端口，默认 1502]

流程：把单元切到"外接 PLC / Modbus 服务器"→ 本脚本连上虚拟工厂的 Modbus 服务器，每 20 ms 读离散输入（按钮、传感器），
按启停自锁逻辑写线圈（输送线、运行灯）→ 通过单元面板点位按启动/停止 → 检查输送线和灯、实时模式（速度被限制为 1×）、
零件被输送到收料器 → 切回内置 PLC。单元要求：B1 启动按钮、B2 停止按钮（常闭）、C1 输送线、LP 指示灯，见 plctest 工厂。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import os
import sys
import threading
import time
import urllib.request

from pymodbus.client import ModbusTcpClient

sys.stdout.reconfigure(encoding='utf-8')
B = os.environ.get('VF_URL', 'http://127.0.0.1:8800')
pid, bid = sys.argv[1], sys.argv[2]
port = int(sys.argv[3]) if len(sys.argv) > 3 else 1502
TOK = ''
res = []


def call(method, url, body=None):
    r = urllib.request.Request(B + url, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + TOK} if TOK else {})})
    with urllib.request.urlopen(r, timeout=60) as f:
        return json.loads(f.read())


def ok(name, cond, detail=''):
    res.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:240])


TOK = call('POST', '/api/login', {'username': 'admin', 'password': 'honey123'})['token']
P, C = f'/api/p/{pid}', f'/api/p/{pid}/cells/{bid}'
io = call('GET', C + '/program')['io']
by_comp = {}
for e in io:
    by_comp.setdefault((e.get('comp') or '')[:2], []).append(e)
start = next(e['name'] for e in io if e.get('comp') == 'B1')
stop = next(e['name'] for e in io if e.get('comp') == 'B2')
conv = next(e['name'] for e in io if e.get('comp') == 'C1' and e['dir'] == 'out')
lamp = next(e['name'] for e in io if (e.get('comp') or '').startswith('LP'))

call('POST', P + '/ctl', {'action': 'play'})
call('POST', P + '/sim', {'speed': 10})
r = call('PUT', C + '/plc/external', {'mode': 'external', 'protocol': 'modbus_server', 'port': port, 'realtime': True})
mp = {m['name']: m['addr'] for m in r['mapping']}
ok('切到外接 PLC（Modbus 服务器）', r['mode'] == 'external' and r['status']['connected'], r['status'])
ok('信号映射：按钮 → DI，输送线/灯 → 线圈', mp[start].startswith('DI') and mp[conv].startswith('CO') and mp[lamp].startswith('CO'), mp)
n = lambda a: int(a[2:])  # noqa: E731

# ------------------------------------------------ 外部 PLC：启停自锁，20 ms 扫描
stop_flag = threading.Event()
scans = [0]
errors = []


def external_plc():
    cli = ModbusTcpClient('127.0.0.1', port=port)
    if not cli.connect():
        errors.append('连不上')
        return
    motor = False
    while not stop_flag.is_set():
        try:
            di = cli.read_discrete_inputs(0, count=8).bits
            s, t = di[n(mp[start])], di[n(mp[stop])]          # 停止按钮常闭：没按时为 1
            motor = (s or motor) and t
            cli.write_coil(n(mp[conv]), motor)
            cli.write_coil(n(mp[lamp]), motor)
            scans[0] += 1
        except Exception as e:      # noqa: BLE001
            errors.append(str(e))
        time.sleep(0.02)
    cli.close()


th = threading.Thread(target=external_plc, daemon=True)
th.start()
time.sleep(1.5)
st = call('GET', P + '/state')
spd = next(p['speed'] for p in call('GET', '/api/plants')['plants'] if p['id'] == pid)
ok('外部 PLC 连上后实时模式（速度 10× → 1×）', abs(spd - 1.0) < 1e-6, spd)
on = call('GET', C + '/online')
ok('在线：外接 PLC 已连接、1 个客户端', on['state'] == 'EXTERNAL' and on['external']['connected'] and on['external']['peer'] == '1 个客户端', on['external'])
call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B1', 'value': True})
time.sleep(1.5)
call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B1', 'value': False})
time.sleep(1.5)
on = call('GET', C + '/online')
iov = {r['name']: r['value'] for r in on['io']}
s1 = call('GET', P + f'/station/{bid}')
ok('按启动 → 外部 PLC 自锁，输送线和灯亮', iov[conv] is True and iov[lamp] is True and iov[start] is False, iov)
ok('单元点位跟随外部 PLC 输出', s1['tags']['IO/' + conv]['v'] is True, s1['tags']['IO/' + conv])
removed0 = s1['tags'].get('Cell/Removed', {}).get('v', 0)
time.sleep(28)
s2 = call('GET', P + f'/station/{bid}')
ok('外部 PLC 控制下零件被送到收料器', s2['tags'].get('Cell/Removed', {}).get('v', 0) > removed0, (removed0, s2['tags'].get('Cell/Removed', {}).get('v')))
call('POST', C + '/plc', {'action': 'force', 'name': lamp, 'value': False})
time.sleep(1.6)                      # 单元点位在整厂步（1 s）里刷新
s3 = call('GET', P + f'/station/{bid}')
ok('外接模式下也能强制输出', s3['tags']['IO/' + lamp]['v'] is False, s3['tags']['IO/' + lamp])
call('POST', C + '/plc', {'action': 'unforce_all'})
call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B2', 'value': True})
time.sleep(1.5)
call('POST', P + f'/station/{bid}/write', {'tag': 'Panel/B2', 'value': False})
time.sleep(1.0)
on = call('GET', C + '/online')
iov = {r['name']: r['value'] for r in on['io']}
ok('按停止 → 外部 PLC 断开输送线', iov[conv] is False and iov[lamp] is False, iov)
stop_flag.set()
th.join(2)
ok('外部 PLC 扫描正常（无通讯错误）', scans[0] > 100 and not errors, (scans[0], errors[:3]))
r = call('PUT', C + '/plc/external', {'mode': 'internal', 'protocol': 'modbus_server', 'port': port})
ok('切回内置 PLC', r['mode'] == 'internal', r)

n_ok = sum(1 for _, c in res if c)
print(f'\n{n_ok}/{len(res)} 通过')
sys.exit(0 if n_ok == len(res) else 1)
